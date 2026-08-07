"""rate_limit.py — a tiny, dependency-free, in-process sliding-window rate limiter.

H2 fix (partial): /forgot-password had no throttling, so an attacker could grind
email+phone combinations without limit. This adds a per-key attempt cap over a
rolling time window with zero new dependencies and — importantly — NO schema change
(the platform schema is frozen; a durable, multi-worker limiter backed by a table
or Redis is a follow-up that needs a baseline decision, see IMPLEMENTATION_REPORT).

Scope/limitations (documented deliberately, not hidden):
  * State lives in this process only. With multiple workers each has its own view,
    so the effective cap is (per-worker cap × worker count). It still turns an
    unbounded grind into a bounded one — a real mitigation, not a complete control.
  * A process restart clears the counters.

The limiter is pure and time-injectable (`now=` argument), so it is fully unit-
testable without sleeping.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque, Dict, Tuple

# Run the expired-key sweep once per this many recorded failures (amortised cleanup).
_SWEEP_EVERY = 256


class RateLimiter:
    def __init__(self, max_attempts: int = 5, window_seconds: float = 900.0):
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.max_attempts = max_attempts
        self.window_seconds = float(window_seconds)
        # NOTE: a plain dict, deliberately NOT a defaultdict. `check()` is called on
        # every /forgot-password request (an UNAUTHENTICATED endpoint), so a container
        # that materialises an entry merely by being read would let anyone grow this
        # map without bound — a memory-exhaustion DoS. Only `record()` may create keys.
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()
        self._ops_since_sweep = 0

    def _prune(self, key: str, now: float):
        """Drop expired timestamps for `key`. Returns the live deque, or None when the
        key has no live attempts. NEVER creates an entry (see __init__)."""
        q = self._hits.get(key)
        if q is None:
            return None
        cutoff = now - self.window_seconds
        while q and q[0] <= cutoff:
            q.popleft()
        if not q:
            del self._hits[key]      # fully expired → reclaim immediately
            return None
        return q

    def _sweep(self, now: float) -> None:
        """Periodic O(n) reclaim of fully-expired keys, so entries left behind by keys
        that are never touched again cannot accumulate indefinitely. Amortised: runs
        once per `_SWEEP_EVERY` recorded failures, not per request."""
        cutoff = now - self.window_seconds
        for k in [k for k, q in self._hits.items() if not q or q[-1] <= cutoff]:
            del self._hits[k]

    def check(self, key: str, now: float | None = None) -> Tuple[bool, int]:
        """Peek: is another attempt allowed for `key`? Does NOT record anything.

        Returns (allowed, retry_after_seconds); retry_after is the whole seconds
        until the oldest in-window attempt ages out (0 when allowed).

        `check` and `record` are deliberately SEPARATE so the caller decides what
        counts as an attempt. /forgot-password records only *identity-verification
        failures* (the actual guessing surface) — never a request that proved
        identity correctly but was rejected for an unrelated reason such as password
        policy. Counting the latter would let a legitimate user lock themselves out
        just by fumbling the password rules."""
        now = time.time() if now is None else now
        with self._lock:
            q = self._prune(key, now)
            if q is not None and len(q) >= self.max_attempts:
                retry_after = self.window_seconds - (now - q[0])
                return False, max(0, int(retry_after + 0.999))
            return True, 0

    def record(self, key: str, now: float | None = None) -> None:
        """Record one failed attempt against `key`. This is the ONLY method that
        creates state, so unauthenticated traffic that never fails cannot grow the map."""
        now = time.time() if now is None else now
        with self._lock:
            self._prune(key, now)
            self._hits.setdefault(key, deque()).append(now)
            self._ops_since_sweep += 1
            if self._ops_since_sweep >= _SWEEP_EVERY:
                self._ops_since_sweep = 0
                self._sweep(now)

    def reset(self, key: str) -> None:
        """Clear a key's history (e.g. after a successful, legitimate action)."""
        with self._lock:
            self._hits.pop(key, None)
