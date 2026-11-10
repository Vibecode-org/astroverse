import asyncio
from threading import Event
import unittest
from fastapi import HTTPException
from backend.position_work import PositionWork


class Request:
    disconnected = False
    async def is_disconnected(self):
        return self.disconnected


class PositionWorkTests(unittest.IsolatedAsyncioTestCase):
    async def test_deadline_keeps_hung_worker_charged_and_rejects_backlog(self):
        work=PositionWork(workers=1,timeout=.03,poll=.005);finish=Event()
        try:
            with self.assertRaises(HTTPException) as timeout:
                await work.run(Request(),lambda cancelled:finish.wait(2))
            self.assertEqual(timeout.exception.detail['code'],'position_timeout')
            self.assertEqual(work.inspect(),{'active':1,'peak':1})
            with self.assertRaises(HTTPException) as busy:
                await work.run(Request(),lambda cancelled:self.fail('Backlog was admitted'))
            self.assertEqual(busy.exception.detail['code'],'position_busy')
            finish.set()
            while work.inspect()['active']:await asyncio.sleep(.005)
            self.assertEqual(await work.run(Request(),lambda cancelled:42),42)
        finally:
            finish.set();work.close()

    async def test_disconnect_and_cancel_signal_cooperative_workers(self):
        for cancel_task in [False,True]:
            work=PositionWork(timeout=.5,poll=.005);request=Request();observed=Event()
            def operation(cancelled):
                if cancelled.wait(1):observed.set()
            task=asyncio.create_task(work.run(request,operation))
            try:
                await asyncio.sleep(.01)
                if cancel_task:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):await task
                else:
                    request.disconnected=True
                    self.assertEqual((await task).status_code,499)
                while work.inspect()['active']:await asyncio.sleep(.005)
                self.assertTrue(observed.is_set())
            finally:work.close()

    async def test_errors_release_slots_and_shutdown_rejects_without_slot_leak(self):
        work=PositionWork(workers=1)
        def fail(cancelled):raise ValueError('solver failure')
        try:
            with self.assertRaisesRegex(ValueError,'solver failure'):await work.run(Request(),fail)
            self.assertEqual(work.inspect()['active'],0)
            class BrokenRequest:
                async def is_disconnected(self):raise RuntimeError('broken receive')
            with self.assertRaisesRegex(RuntimeError,'broken receive'):
                await work.run(BrokenRequest(),lambda cancelled:cancelled.wait(.5))
        finally:work.close()
        with self.assertRaises(RuntimeError):await work.run(Request(),lambda cancelled:None)
        self.assertEqual(work.inspect()['active'],0)
        with self.assertRaises(ValueError):PositionWork(workers=0)
