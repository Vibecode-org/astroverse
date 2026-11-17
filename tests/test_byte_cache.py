"""Concurrent cache fill lifecycle and independent-key progress."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest.mock import patch
import unittest

from backend.byte_cache import ByteLRU


class ByteCacheFillTests(unittest.TestCase):
    def test_concurrent_fill_once_and_other_keys_keep_progressing(self):
        cache = ByteLRU(4096)
        barrier, entered, release = Barrier(8), Event(), Event()
        calls = []
        def build():
            calls.append(1)
            entered.set()
            self.assertTrue(release.wait(5))
            return b'one shared payload'
        def request():
            barrier.wait(timeout=5)
            return cache.get_or_build('same', build)
        with ThreadPoolExecutor(max_workers=8) as pool:
            tasks = [pool.submit(request) for _ in range(8)]
            try:
                self.assertTrue(entered.wait(5))
                self.assertEqual(cache.get_or_build('different', lambda: b'independent'), b'independent')
            finally:
                release.set()
            self.assertEqual([task.result(timeout=5) for task in tasks], [b'one shared payload']*8)
        self.assertEqual(len(calls), 1)
        self.assertEqual(cache.pending, {})
        self.assertLessEqual(cache.bytes, cache.max_bytes)

    def test_error_releases_owner_and_retry_works(self):
        cache = ByteLRU(4096)
        def fail():
            raise ValueError('build failed')
        with self.assertRaisesRegex(ValueError, 'build failed'):
            cache.get_or_build('key', fail)
        self.assertEqual(cache.pending, {})
        self.assertEqual(cache.get_or_build('key', lambda: b'retry'), b'retry')

    def test_failed_owner_wakes_waiter_that_can_retry(self):
        cache = ByteLRU(4096)
        entered, release, waiting = Event(), Event(), Event()
        class ObservedEvent(Event):
            def wait(self, timeout=None):
                waiting.set()
                return super().wait(timeout)
        def fail():
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test owner deadline')
            raise ValueError('owner failed')
        with patch('backend.byte_cache.Event', ObservedEvent), ThreadPoolExecutor(max_workers=2) as pool:
            owner = pool.submit(cache.get_or_build, 'same', fail)
            self.assertTrue(entered.wait(5))
            waiter = pool.submit(cache.get_or_build, 'same', lambda: b'retried')
            try:
                self.assertTrue(waiting.wait(5))
            finally:
                release.set()
            with self.assertRaisesRegex(ValueError, 'owner failed'):
                owner.result(timeout=5)
            self.assertEqual(waiter.result(timeout=5), b'retried')
        self.assertEqual(cache.pending, {})

    def test_many_distinct_keys_evict_with_accounting_within_shared_cap(self):
        cache = ByteLRU(8192)
        for i in range(200):
            key = ('search/1' if i % 2 else 'legacy', 'revision', str(i))
            cache.get_or_build(key, lambda: b'x'*512)
            self.assertLessEqual(cache.bytes, cache.max_bytes)
            self.assertEqual(cache.bytes, sum(cache.cost(k, v) for k, v in cache.entries.items()))
            self.assertEqual(cache.pending, {})
        self.assertLess(len(cache.entries), 200)
        self.assertIsNone(cache.get(('legacy', 'revision', '0')))

    def test_disabled_and_oversize_do_not_retain_payload_or_pending(self):
        for capacity in (0, 1):
            cache = ByteLRU(capacity)
            self.assertEqual(cache.get_or_build('key', lambda: b'payload'), b'payload')
            self.assertEqual(cache.entries, {})
            self.assertEqual(cache.pending, {})
            self.assertEqual(cache.bytes, 0)


if __name__ == '__main__':
    unittest.main()
