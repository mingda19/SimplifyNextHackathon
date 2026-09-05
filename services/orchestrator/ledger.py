"""
Token ledger with a hard stop.

Reported AWS spend lags by hours, so this local ledger is the only real-time
view we have of what the session has cost. It also refuses to make the next
call once a cap is hit — the mitigation for the one bug in this design that can
actually drain the budget (see plan.md §4.4, §7.2).
"""
from __future__ import annotations

import json
import threading
from typing import Any

from .config import settings

_LOCK = threading.Lock()

# Planning proxy only — Anthropic first-party rates, USD per 1M tokens.
# Bedrock is partner-operated and priced separately: verify against
# https://aws.amazon.com/bedrock/pricing/ and correct these on day 1.
PRICES: dict[str, tuple[float, float]] = {
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": (1.00, 5.00),
    "us.anthropic.claude-sonnet-5": (2.00, 10.00),
    "anthropic.claude-haiku-4-5": (1.00, 5.00),
    "anthropic.claude-sonnet-5": (2.00, 10.00),
    "anthropic.claude-opus-5": (5.00, 25.00),
}
_DEFAULT_PRICE = (1.00, 5.00)


class BudgetExceeded(RuntimeError):
    """Raised instead of making a call that would breach the session cap."""


def _blank() -> dict[str, Any]:
    return {"calls": 0, "input": 0, "output": 0, "cache_read": 0,
            "cache_write": 0, "usd": 0.0, "by_model": {}}


def load() -> dict[str, Any]:
    if not settings.ledger_path.exists():
        return _blank()
    try:
        return json.loads(settings.ledger_path.read_text())
    except (json.JSONDecodeError, OSError):
        return _blank()


def _save(led: dict[str, Any]) -> None:
    try:
        settings.ledger_path.write_text(json.dumps(led, indent=2, sort_keys=True))
    except OSError:
        pass  # never let a bookkeeping failure kill a run


def check_budget() -> None:
    """Call BEFORE every model request. Raises rather than overspending."""
    led = load()
    if led["usd"] >= settings.max_session_spend_usd:
        raise BudgetExceeded(
            f"Session spend ${led['usd']:.4f} has reached the "
            f"${settings.max_session_spend_usd:.2f} cap. Raise MAX_SESSION_SPEND_USD "
            f"deliberately, or reset with `make reset-ledger`."
        )


def record(model: str, usage: Any) -> dict[str, Any]:
    """Accumulate one response's usage. Tolerates missing cache fields."""
    inp = int(getattr(usage, "input_tokens", 0) or 0)
    out = int(getattr(usage, "output_tokens", 0) or 0)
    c_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    c_write = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)

    in_rate, out_rate = PRICES.get(model, _DEFAULT_PRICE)
    # cache reads ~0.1x, cache writes ~1.25x
    usd = ((inp + c_read * 0.1 + c_write * 1.25) * in_rate + out * out_rate) / 1_000_000

    with _LOCK:
        led = load()
        led["calls"] += 1
        led["input"] += inp
        led["output"] += out
        led["cache_read"] += c_read
        led["cache_write"] += c_write
        led["usd"] = round(led["usd"] + usd, 6)
        m = led["by_model"].setdefault(model, {"calls": 0, "usd": 0.0})
        m["calls"] += 1
        m["usd"] = round(m["usd"] + usd, 6)
        _save(led)
        return led


def reset() -> None:
    _save(_blank())


def summary() -> str:
    led = load()
    cap = settings.max_session_spend_usd
    # Our system prompts are ~500 tokens, far below Bedrock's ~4k minimum
    # cacheable prefix, so cache_read=0 is EXPECTED here and is not a bug.
    # Measured on this account: a 3,009-token prefix does not cache; 8,102 does.
    note = ""
    return (
        f"spend ${led['usd']:.4f} / ${cap:.2f} cap  ·  {led['calls']} calls  ·  "
        f"in {led['input']:,} out {led['output']:,} cache_read {led['cache_read']:,}{note}"
    )
