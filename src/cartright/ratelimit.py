from __future__ import annotations

import threading
import time
from collections import deque


class RateLimiter:
    """A tiny in-process sliding-window limiter (single instance, single user)."""

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self._max = max_requests
        self._window = window_seconds
        self._hits: deque[float] = deque()
        self._lock = threading.Lock()

    def allow(self, now: float | None = None) -> bool:
        current = now if now is not None else time.monotonic()
        with self._lock:
            while self._hits and self._hits[0] <= current - self._window:
                self._hits.popleft()
            if len(self._hits) >= self._max:
                return False
            self._hits.append(current)
            return True
