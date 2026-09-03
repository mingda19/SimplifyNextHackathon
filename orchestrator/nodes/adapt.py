"""
PHASE 3b — the agentic loop.  LLM calls #2..N.

THIS NODE IS THE SUBMISSION. Everything else is scaffolding around it.

The retry cap is written first and enforced unconditionally: an uncapped adapt
loop calling Bedrock forever is the one bug in this design that can actually
drain the budget while nobody is watching.
"""
from __future__ import annotations

import logging
from typing import Any

from .. import llm
from ..config import settings
from ..ledger import BudgetExceeded
from ..state import AgentState, Plan

log = logging.getLogger(__name__)


def adapt(state: AgentState) -> dict[str, Any]:
    error = state.get("last_error") or {}
    retry = state.get("retry_count", 0) + 1

    # --- hard cap, checked before any model call -------------------------
    if retry > settings.max_retries:
        msg = (f"Could not resolve {error.get('code', 'the failure')} after "
               f"{settings.max_retries} attempts.")
        log.warning("adapt: %s — escalating to human", msg)
        return {"retry_count": retry, "halt_reason": msg,
                "attempts": [{"node": "adapt", "ok": False, "escalated": True,
                              "reason": msg}]}

    failed_step = error.get("failed_step", {})
    try:
        adaptation, led = llm.adapt_step(failed_step, error, retry)
    except BudgetExceeded as exc:
        log.error("adapt: %s", exc)
        return {"retry_count": retry, "halt_reason": str(exc),
                "attempts": [{"node": "adapt", "ok": False, "error": str(exc)}]}
    except Exception as exc:                      # noqa: BLE001
        log.exception("adapt: model call failed")
        return {"retry_count": retry, "halt_reason": f"adapt failed: {exc}",
                "attempts": [{"node": "adapt", "ok": False, "error": str(exc)}]}

    # --- splice the revised step back into the plan ----------------------
    plan = Plan.model_validate(state["plan"])
    idx = error.get("step_index", state.get("current_step", 0))
    plan.steps[idx] = adaptation.revised_step

    log.info("adapt: attempt %d — %s", retry, adaptation.what_changed)

    return {
        "plan": plan.model_dump(),
        "retry_count": retry,
        "last_error": None,
        "token_ledger": led or state.get("token_ledger", {}),
        "attempts": [{"node": "adapt", "ok": True, "attempt": retry,
                      "error_code": error.get("code"),
                      "what_changed": adaptation.what_changed,
                      "confidence": adaptation.confidence,
                      "revised_step": adaptation.revised_step.model_dump()}],
    }
