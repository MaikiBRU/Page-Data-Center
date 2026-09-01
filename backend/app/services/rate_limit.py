"""In-process sliding window rate limiting.

**Known limitation, by design.** The counters live in the process. On a single
instance they are exact; if the service is ever scaled out, each instance
keeps its own window, so the effective limit becomes ``limit x instances``.
That is a weaker guarantee than a shared store would give, and it is the one
this project accepts: a portfolio demo does not justify running Redis, and a
per-instance brake still turns an unbounded brute force attempt into a slow
one. Anything that must hold globally is enforced in the database instead
(see ``demo_session.create_session``, which counts live sessions with a
query).

The window is a plain list of timestamps per key, pruned on read.
"""

from __future__ import annotations

import hashlib
import threading
import time

from fastapi import Request


class RateLimitExceeded(Exception):
    """A key used up its allowance. Carries the seconds until it frees up."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Rate limit exceeded, retry in {retry_after}s")
        self.retry_after = max(1, retry_after)


class SlidingWindowLimiter:
    """Allow ``limit`` events per ``window_seconds`` for each key."""

    # Above this many tracked keys a sweep runs, so a flood of distinct keys
    # cannot grow the dictionary without bound.
    _SWEEP_AT = 5000

    def __init__(self, limit: int, window_seconds: int, name: str = "") -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.name = name
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = {}

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        stale = [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
        for key in stale:
            self._hits.pop(key, None)

    def hit(self, key: str | None) -> None:
        """Record one event, or raise if the key is over its allowance.

        A ``None`` key means the caller could not identify the client; the
        request is allowed rather than blocking everyone behind an
        unidentifiable proxy.
        """
        if key is None or self.limit <= 0:
            return
        now = time.time()
        cutoff = now - self.window_seconds
        with self._lock:
            recent = [t for t in self._hits.get(key, []) if t > cutoff]
            if len(recent) >= self.limit:
                self._hits[key] = recent
                oldest = recent[0]
                raise RateLimitExceeded(int(oldest + self.window_seconds - now) + 1)
            recent.append(now)
            self._hits[key] = recent
            if len(self._hits) > self._SWEEP_AT:
                self._prune(now)

    def clear(self, key: str | None) -> None:
        """Forget a key. Used to stop penalising a caller who succeeded."""
        if key is None:
            return
        with self._lock:
            self._hits.pop(key, None)

    def reset(self) -> None:
        """Drop every counter. For tests and for process-local maintenance."""
        with self._lock:
            self._hits.clear()

    def remaining(self, key: str | None) -> int:
        if key is None or self.limit <= 0:
            return self.limit
        cutoff = time.time() - self.window_seconds
        with self._lock:
            recent = [t for t in self._hits.get(key, []) if t > cutoff]
        return max(0, self.limit - len(recent))


def client_ip(request: Request) -> str | None:
    """Best guess at who is calling.

    Cloudflare and App Runner both sit in front of the API, so the socket
    address is a proxy; the first hop of the forwarded chain is the closest
    thing to a client address available.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else None


def hash_key(*parts: str | None) -> str | None:
    """Build an opaque bucket key.

    Hashed so that neither an address nor an email address is held in memory
    in the clear just to count requests.
    """
    usable = [p for p in parts if p]
    if not usable:
        return None
    joined = "\x1f".join(p.strip().lower() for p in usable)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
