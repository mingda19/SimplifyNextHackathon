"""
PHASE 3a — the execution node.  No LLM. Cost: $0.

Pure dispatch: the plan is already typed, so nothing is left to reason about.
Committing actions are STAGED, never executed — `commit` runs them after the
human approves.
"""
from __future__ import annotations

import logging
from typing import Any

from .. import services
from ..state import COMMITTING_ACTIONS, AgentState, Plan

log = logging.getLogger(__name__)


def _current_step(state: AgentState) -> dict[str, Any] | None:
    raw = state.get("plan")
    if not raw:
        return None
    plan = Plan.model_validate(raw)
    i = state.get("current_step", 0)
    if i >= len(plan.steps):
        return None
    return plan.steps[i].model_dump()


def act(state: AgentState) -> dict[str, Any]:
    step = _current_step(state)
    if step is None:
        return {"last_error": None}

    i = state.get("current_step", 0)
    action = step["action"]
    log.info("act: step %d/%s -> %s %s",
             i + 1, len(Plan.model_validate(state["plan"]).steps), action, step["sku"])

    # -- non-backend action: nothing can fail, nothing to stage ------------
    if action == "flag_for_human":
        return {
            "current_step": i + 1,
            "last_error": None,
            "retry_count": 0,
            "staged": [*state.get("staged", []),
                       {"type": "flag", "step": step}],
            "attempts": [{"node": "act", "step_index": i, "action": action,
                          "ok": True, "detail": step["rationale"]}],
        }

    # -- backend actions ---------------------------------------------------
    try:
        if action in COMMITTING_ACTIONS:
            result = services.vendor_order(step["vendor_id"], step["sku"], step["qty"])
        elif action == "request_quote":
            result = services.vendor_order(step["vendor_id"], step["sku"], step["qty"])
        else:  # reallocate_lot
            # TODO(W/G): real endpoint once workstream 1 ships lot reallocation.
            result = {"status": "STAGED", "note": "reallocate_lot stub"}
    except services.VendorError as exc:
        log.info("act: step %d failed %s — routing to adapt", i, exc.body["code"])
        return {
            "last_error": {**exc.body, "step_index": i, "failed_step": step},
            "attempts": [{"node": "act", "step_index": i, "action": action,
                          "ok": False, "error": exc.body}],
        }
    except services.ServiceError as exc:
        return {
            "last_error": {"code": "TRANSPORT", "message": str(exc),
                           "remedy_hint": "retry or use a different vendor",
                           "alternatives": [], "step_index": i, "failed_step": step},
            "attempts": [{"node": "act", "step_index": i, "action": action,
                          "ok": False, "error": str(exc)}],
        }

    return {
        "current_step": i + 1,
        "last_error": None,
        "retry_count": 0,           # reset per step — the cap is per step, not per run
        "staged": [*state.get("staged", []),
                   {"type": "order", "step": step, "result": result}],
        "attempts": [{"node": "act", "step_index": i, "action": action,
                      "ok": True, "result": result}],
    }
