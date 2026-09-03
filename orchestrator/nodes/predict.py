"""
PHASE 2 — the reasoning node.  LLM call #1.

Emits a *typed* Plan. The Literal-constrained action field means a hallucinated
verb fails validation here rather than crashing `act` mid-demo.
"""
from __future__ import annotations

import logging
from typing import Any

from .. import llm
from ..ledger import BudgetExceeded
from ..state import AgentState

log = logging.getLogger(__name__)


def predict(state: AgentState) -> dict[str, Any]:
    try:
        plan, led = llm.predict_plan(
            state_of_world=state.get("state_of_world", {}),
            degraded=state.get("degraded_services", []),
            charity_type=state.get("charity_type", "B"),
        )
    except BudgetExceeded as exc:
        log.error("predict: %s", exc)
        return {"halt_reason": str(exc),
                "attempts": [{"node": "predict", "ok": False, "error": str(exc)}]}
    except Exception as exc:                      # noqa: BLE001
        log.exception("predict: model call failed")
        return {"halt_reason": f"predict failed: {exc}",
                "attempts": [{"node": "predict", "ok": False, "error": str(exc)}]}

    log.info("predict: %s fails in %sd, %d step(s)",
             plan.stockout_sku, plan.days_until_failure, len(plan.steps))

    return {
        "plan": plan.model_dump(),
        "current_step": 0,
        "retry_count": 0,
        "last_error": None,
        "token_ledger": led or state.get("token_ledger", {}),
        "attempts": [{"node": "predict", "ok": True,
                      "stockout_sku": plan.stockout_sku,
                      "days_until_failure": plan.days_until_failure,
                      "steps": len(plan.steps)}],
    }
