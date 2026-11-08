"""Serialized-byte budget, including keys and fixed entry overhead; thread safe."""

from collections import OrderedDict
from threading import RLock


class ByteLRU:
    def __init__(self, max_bytes):
        self.max_bytes = max(0, max_bytes)
        self.entries = OrderedDict()
        self.bytes = 0
        self.lock = RLock()

    @staticmethod
    def cost(key, payload):
        return len(payload) + len(repr(key).encode()) + 256

    def get(self, key):
        with self.lock:
            value = self.entries.get(key)
            if value is not None:
                self.entries.move_to_end(key)
            return value

    def put(self, key, payload):
        cost = self.cost(key, payload)
        with self.lock:
            previous = self.entries.pop(key, None)
            if previous is not None:
                self.bytes -= self.cost(key, previous)
            if cost > self.max_bytes:
                return
            while self.bytes + cost > self.max_bytes:
                old_key, old = self.entries.popitem(last=False)
                self.bytes -= self.cost(old_key, old)
            self.entries[key] = payload
            self.bytes += cost
