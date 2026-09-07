"""Execute exactly the staged, approved actions using durable backend keys."""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from .. import services
from ..config import BASELINES
from ..state import APPROVAL_VERSION, AgentState, Plan, PlanStep

# 1. Define the logger
log = logging.getLogger(__name__)

# 2. Define the idempotency set
_COMMITTED: set[str] = set()


def _checklist(state: AgentState, staged: list[dict]) -> dict:
    world = state.get("state_of_world", {})
    stock = {i["sku"]: i for i in world.get("inventory") or []}
    needs = (world.get("unmet_needs") or {}).get("ranked", [])
    items = []
    for entry in staged:
        step = entry["step"]
        if step["action"] == "flag_for_human":
            continue
        item = stock.get(step["sku"], {})
        draw = item.get("avg_daily_draw", 0)
        cover = item.get("on_hand", 0) / draw if draw else BASELINES["min_days_cover"]
        shortfall = max(0, BASELINES["min_days_cover"] - cover)
        urgency = max((n.get("urgency", 0) for n in needs
                       if step["sku"] in n.get("mentioned_skus", [])), default=0)
        items.append({"sku": step["sku"], "qty": step["qty"], "why": step.get("rationale", ""),
                      "urgency": urgency, "days_cover_shortfall": shortfall,
                      "priority_score": urgency * shortfall})
    items.sort(key=lambda i: (-i["priority_score"], i["sku"]))
    return {"kind": "acquisition_checklist", "items": items,
            "review_flags": [s["step"] for s in staged if s["step"]["action"] == "flag_for_human"]}


def _line_value(result: dict[str, Any]) -> float:
    """Workstream 1 returns unit_price_sgd + qty, not total_sgd."""
    if result.get("total_sgd") is not None:
        return float(result["total_sgd"])
    if result.get("total_price_sgd") is not None:
        return float(result["total_price_sgd"])
    unit, qty = result.get("unit_price_sgd"), result.get("qty")
    return float(unit) * int(qty) if unit is not None and qty else 0.0


def commit(state: AgentState) -> dict[str, Any]:
    if state.get("approval_version") != APPROVAL_VERSION:
        return {"halt_reason": "Legacy approval: review existing orders and start a new run."}
    if state.get("approval") != "approved" or state.get("halt_reason"):
        return {"halt_reason": state.get("halt_reason") or "Human approval is required before commit."}
    
    # FIX 1: Assign thread_id
    thread_id = state.get("thread_id")
    if not thread_id:
        raise ValueError("commit requires a durable thread_id")
        
    staged = state.get("staged", [])
    plan = Plan.model_validate(state["plan"]) if state.get("plan") else None
    
    # FIX 2: Assign charity_type
    charity_type = state.get("charity_type", "B")
    
    if charity_type == "A":
        return {"outcome": _checklist(state, staged),
                "attempts": [{"node": "commit", "ok": True, "kind": "acquisition_checklist"}]}

    approved = state.get("approved_steps")
    step_index = {}
    if plan:
        for i, st in enumerate(plan.steps):
            step_index[(st.action, st.sku)] = i

    committed: list[dict[str, Any]] = []
    skipped: list[str] = []
    declined: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for idx, item in enumerate(staged):
        st = item.get("step") or {}
        i = step_index.get((st.get("action"), st.get("sku")), idx)
        if approved is not None and i not in approved:
            declined.append(st)
            continue

        # thread_id is now safely defined
        key = f"{thread_id}:{idx}"
        if key in _COMMITTED:
            skipped.append(key)
            continue
        _COMMITTED.add(key)

        if item["type"] == "order":
            try:
                placed = services.vendor_order(st["vendor_id"], st["sku"], st["qty"])
                committed.append({"type": "order", "step": st,
                                  "result": {**placed, "status": "CONFIRMED"}})
            except Exception as exc:                  
                log.warning("commit: order failed for %s: %s", st.get("sku"), exc)
                failed.append({"step": st, "error": str(exc)})
        else:
            committed.append(item)

    # Resolve Feedback
    ordered_skus = sorted({c["step"]["sku"] for c in committed
                           if c.get("type") == "order" and c.get("step", {}).get("sku")})
    resolution = {"resolved": 0}
    if ordered_skus:
        try:
            resolution = services.resolve_feedback(
                ordered_skus, thread_id,
                note=f"ordered via agent run {thread_id}")
        except Exception as exc:                      
            log.warning("commit: feedback resolution failed: %s", exc)
            resolution = {"resolved": 0, "error": str(exc)}

    # FIX 3: Define failure
    failure = failed[0]["error"] if failed else None

    # FIX 4: Build ONE unified outcome dictionary instead of overwriting it
    orders = [c for c in committed if c["type"] == "order"]
    outcome = {
        "kind": "commit_failed" if failure else "purchase_order",
        "orders": orders,
        "allocations": [c for c in committed if c["type"] == "allocation"],
        "total_sgd": float(sum((services.total_sgd(o["result"]) for o in orders), Decimal(0))) if hasattr(services, 'total_sgd') else round(sum(_line_value(o["result"]) for o in orders), 2),
        "timing_rationale": (state.get("state_of_world", {}).get("price_forecast") or {}).get("rationale", plan.reasoning if plan else ""),
        "review_flags": [s["step"] for s in staged if s["step"]["action"] == "flag_for_human"],
        "declined_steps": declined,
        "failed_steps": failed,
        "failure": failure,
        "feedback_resolved": resolution.get("resolved", 0)
    }

    log.info("commit: %s — %d committed, %d declined, %d skipped, "
             "%d feedback row(s) resolved",
             outcome["kind"], len(committed), len(declined), len(skipped),
             resolution.get("resolved", 0))

    return {"outcome": outcome,
            "attempts": [{"node": "commit", "ok": True, "kind": outcome["kind"],
                          "committed": len(committed), "declined": len(declined),
                          "skipped": len(skipped),
                          "feedback_resolved": resolution.get("resolved", 0)}]}


def reset_idempotency() -> None:
    """Clear the commit guard. Tests and long-lived processes only."""
    _COMMITTED.clear()
