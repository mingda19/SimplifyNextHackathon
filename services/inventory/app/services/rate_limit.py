"""Small, resettable rate-limit mechanism for deterministic demonstrations.

Normal callers are not rate limited.  A request carrying the documented demo
header is rejected once, allowed once after the retry window, and then re-armed
for the next run.  This makes repeated ``force_error.sh RATE_LIMIT`` runs
reliable without adding Redis or production-distributed state.
"""

from __future__ import annotations

from math import ceil
from threading import Lock
from time import monotonic
from typing import Callable

from app.errors import RateLimitedError


DEMO_RATE_LIMIT_HEADER = "X-Demo-Rate-Limit"


class DemoRateLimiter:
    """Block the first call for each key, then permit one delayed retry."""

    def __init__(
        self,
        *,
        retry_after_seconds: int = 1,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if retry_after_seconds <= 0:
            raise ValueError("retry_after_seconds must be positive")
        self.retry_after_seconds = retry_after_seconds
        self._clock = clock
        self._blocked_until: dict[str, float] = {}
        self._lock = Lock()

    def check(self, key: str | None) -> None:
        """Bypass normal calls or enforce one demo backoff cycle for ``key``."""

        if key is None or not key.strip():
            return

        normalized_key = key.strip()
        now = self._clock()
        with self._lock:
            blocked_until = self._blocked_until.get(normalized_key)
            if blocked_until is None:
                self._blocked_until[normalized_key] = now + self.retry_after_seconds
                retry_after = self.retry_after_seconds
            elif now < blocked_until:
                retry_after = max(1, ceil(blocked_until - now))
            else:
                # Permit this retry and remove the key.  A later script run with
                # the same key starts a fresh deterministic cycle.
                del self._blocked_until[normalized_key]
                return

        raise RateLimitedError(
            retry_after_seconds=retry_after,
            alternatives=[
                {
                    "action": "retry",
                    "after_seconds": retry_after,
                    "demo_key": normalized_key,
                }
            ],
        )

    def reset(self, key: str | None = None) -> None:
        """Clear one demo key, or all keys when omitted (primarily for tests)."""

        with self._lock:
            if key is None:
                self._blocked_until.clear()
            else:
                self._blocked_until.pop(key.strip(), None)


demo_rate_limiter = DemoRateLimiter()


def enforce_demo_rate_limit(key: str | None) -> None:
    """Check the process-wide demo limiter used by the HTTP router."""

    demo_rate_limiter.check(key)


def reset_rate_limits(key: str | None = None) -> None:
    """Reset process-local limiter state without exposing an HTTP admin route."""

    demo_rate_limiter.reset(key)


__all__ = [
    "DEMO_RATE_LIMIT_HEADER",
    "DemoRateLimiter",
    "demo_rate_limiter",
    "enforce_demo_rate_limit",
    "reset_rate_limits",
]
