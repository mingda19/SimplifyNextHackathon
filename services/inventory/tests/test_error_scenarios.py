"""Focused checks for the five deterministic demo error contracts."""

from __future__ import annotations

import pytest

from app.errors import (
    LeadTimeExceededError,
    LotExpiredError,
    MoqNotMetError,
    OutOfStockError,
    RateLimitedError,
)
from app.services.rate_limit import DemoRateLimiter


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (OutOfStockError(alternatives=[{"action": "choose_vendor"}]), 409, "OUT_OF_STOCK"),
        (MoqNotMetError(alternatives=[{"action": "raise_quantity"}]), 400, "MOQ_NOT_MET"),
        (
            LeadTimeExceededError(alternatives=[{"action": "choose_vendor"}]),
            422,
            "LEAD_TIME_EXCEEDED",
        ),
        (LotExpiredError(alternatives=[{"action": "choose_lot"}]), 410, "LOT_EXPIRED"),
        (
            RateLimitedError(
                retry_after_seconds=1,
                alternatives=[{"action": "retry", "after_seconds": 1}],
            ),
            429,
            "RATE_LIMITED",
        ),
    ],
)
def test_demo_errors_have_exact_envelope_and_useful_alternatives(
    error,
    status_code: int,
    code: str,
) -> None:
    response = error.as_response_model().model_dump()

    assert error.status_code == status_code
    assert set(response) == {"code", "message", "remedy_hint", "alternatives"}
    assert response["code"] == code
    assert response["message"]
    assert response["remedy_hint"]
    assert response["alternatives"]


def test_demo_limiter_blocks_retries_then_passes_once_and_rearms() -> None:
    current_time = [100.0]
    limiter = DemoRateLimiter(
        retry_after_seconds=1,
        clock=lambda: current_time[0],
    )

    with pytest.raises(RateLimitedError) as first:
        limiter.check("repeatable-demo")
    assert first.value.headers == {"Retry-After": "1"}

    with pytest.raises(RateLimitedError):
        limiter.check("repeatable-demo")

    current_time[0] = 101.0
    limiter.check("repeatable-demo")

    with pytest.raises(RateLimitedError):
        limiter.check("repeatable-demo")


def test_demo_limiter_bypasses_unmarked_calls_and_can_be_reset() -> None:
    limiter = DemoRateLimiter(retry_after_seconds=1, clock=lambda: 100.0)

    limiter.check(None)
    limiter.check("   ")
    with pytest.raises(RateLimitedError):
        limiter.check("reset-me")
    limiter.reset("reset-me")
    with pytest.raises(RateLimitedError):
        limiter.check("reset-me")
