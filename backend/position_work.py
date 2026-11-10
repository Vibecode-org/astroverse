"""Bounded offline computation lifetime; HTTP cancellation never frees a busy slot.

A running native solver cannot be killed safely in a Python thread. Admission
stays charged until that worker actually returns; no executor backlog is built.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, Event, Lock

from fastapi import HTTPException
from fastapi.responses import Response


class PositionWorkCancelled(Exception):
    pass


class PositionWork:
    def __init__(self, workers=4, timeout=8.0, poll=0.025):
        if workers < 1 or timeout <= 0 or poll <= 0:
            raise ValueError('Invalid position work limits')
        self.timeout, self.poll = timeout, poll
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='positions')
        self.slots = BoundedSemaphore(workers)
        self.lock = Lock()
        self.active = self.peak = 0

    def inspect(self):
        with self.lock:
            return {'active':self.active, 'peak':self.peak}

    async def run(self, request, operation):
        if not self.slots.acquire(blocking=False):
            raise HTTPException(503, detail={'code':'position_busy','message':'Position workers busy; retry later'},
                                headers={'Retry-After':'1','Cache-Control':'no-store'})
        cancelled = Event()
        with self.lock:
            self.active += 1
            self.peak = max(self.peak,self.active)
        def release(_):
            with self.lock:
                self.active -= 1
            self.slots.release()
        try:
            native = self.executor.submit(operation, cancelled)
        except BaseException:
            release(None)
            raise
        native.add_done_callback(release)
        future = asyncio.wrap_future(native)
        # A timed-out caller does not own the running result. Retrieve its eventual
        # exception without retaining the HTTP task or logging an orphan Future.
        future.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
        async def disconnected():
            while not await request.is_disconnected():
                await asyncio.sleep(self.poll)
        watcher = asyncio.create_task(disconnected())
        try:
            done, _ = await asyncio.wait([future,watcher],timeout=self.timeout,return_when=asyncio.FIRST_COMPLETED)
            if future in done:
                return future.result()
            if watcher in done:
                watcher.result()  # A broken receive channel is a server error, not a disconnect.
                return Response(status_code=499)
            raise HTTPException(503, detail={'code':'position_timeout','message':'Position computation deadline exceeded'},
                                headers={'Retry-After':'1','Cache-Control':'no-store'})
        finally:
            cancelled.set()
            native.cancel()  # Only succeeds before the native operation starts.
            watcher.cancel()
            await asyncio.gather(watcher,return_exceptions=True)

    def close(self):
        self.executor.shutdown(wait=True,cancel_futures=True)
