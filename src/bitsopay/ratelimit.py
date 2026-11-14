"""A tiny in-memory limiter used to slow down brute-forcing of the admin token.

It counts *failures* per client key inside a sliding window. State is per process: with several
gunicorn workers each worker keeps its own counters, so the effective limit is
``max_failures * workers``. For a hard global limit, rate-limit at your reverse proxy as well
(see ``docs/deployment.md``).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Deque, Dict


class FailureLimiter:
    """Block a key after ``max_failures`` failures within ``window`` seconds."""

    def __init__(
        self,
        max_failures: int = 10,
        window: float = 60.0,
        *,
        clock: Callable[[], float] = time.time,
        max_keys: int = 10_000,
    ) -> None:
        if max_failures < 1 or window <= 0:
            raise ValueError("max_failures must be >= 1 and window > 0")
        self.max_failures = max_failures
        self.window = window
        self._clock = clock
        self._max_keys = max_keys
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def _trim(self, key: str, now: float) -> Deque[float]:
        hits = self._hits.get(key)
        if hits is None:
            return deque()
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if not hits:
            self._hits.pop(key, None)
        return hits

    def retry_after(self, key: str) -> int:
        """Seconds until ``key`` may try again; ``0`` if it is not blocked."""
        with self._lock:
            now = self._clock()
            hits = self._trim(key, now)
            if len(hits) < self.max_failures:
                return 0
            return max(1, int(hits[0] + self.window - now) + 1)

    def record_failure(self, key: str) -> None:
        with self._lock:
            now = self._clock()
            if key not in self._hits and len(self._hits) >= self._max_keys:
                # bound memory under a flood of distinct keys: drop expired entries first
                for known in list(self._hits):  # snapshot: _trim() removes emptied keys
                    self._trim(known, now)
                if len(self._hits) >= self._max_keys:
                    self._hits.pop(next(iter(self._hits)))
            self._hits.setdefault(key, deque()).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)
