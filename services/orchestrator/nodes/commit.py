"""Execute exactly the staged, approved actions using durable backend keys."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from .. import services
from ..config import BASELINES
from ..state import APPROVAL_VERSION, AgentState, Plan, PlanStep


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


def commit(state: AgentState) -> dict[str, Any]:
    if state.get("approval_version") != APPROVAL_VERSION:
        return {"halt_reason": "Legacy approval: review existing orders and start a new run."}
    if state.get("approval") != "approved" or state.get("halt_reason"):
        return {"halt_reason": state.get("halt_reason") or "Human approval is required before commit."}
    if not state.get("thread_id"):
        raise ValueError("commit requires a durable thread_id")
    staged = state.get("staged", [])
    plan = Plan.model_validate(state["plan"]) if state.get("plan") else None
    if state.get("charity_type", "B") == "A":
        return {"outcome": _checklist(state, staged),
                "attempts": [{"node": "commit", "ok": True, "kind": "acquisition_checklist"}]}

    committed = []
    failure = None
    # Check the final adapted plan before the first committing call.
    total = sum((services.total_sgd(s["result"]) for s in staged
                 if s["step"]["action"] == "place_order"), Decimal(0))
    if total > BASELINES["monthly_budget_sgd"]:
        return {"halt_reason": "Staged purchases exceed the monthly budget."}
    for index, entry in enumerate(staged):
        step = PlanStep.model_validate(entry["step"])
        key = f"{state['thread_id']}:{entry.get('step_index', index)}"
        try:
            if step.action == "place_order":
                result = services.vendor_order(step.vendor_id, step.sku, step.qty,
                    idempotency_key=key,
                    expected_unit_price_sgd=entry["result"]["unit_price_sgd"])
                committed.append({"type": "order", "step": step.model_dump(), "result": result})
            elif step.action == "reallocate_lot":
                result = services.allocate_lot(step.sku, step.lot_id, step.qty, idempotency_key=key)
                committed.append({"type": "allocation", "step": step.model_dump(), "result": result})
        except services.VendorError as exc:
            # New vendor terms are never implicitly approved. A changed price,
            # expiry or availability must be reviewed in another run.
            failure = {**exc.body, "step_index": index, "step": step.model_dump()}
            break
        # Transport errors deliberately propagate. LangGraph keeps the failed
        # commit task; the decision API can resume it using the same keys.

    orders = [entry for entry in committed if entry["type"] == "order"]
    outcome = {"kind": "commit_failed" if failure else "purchase_order",
               "orders": orders, "allocations": [c for c in committed if c["type"] == "allocation"],
               "total_sgd": float(sum((services.total_sgd(o["result"]) for o in orders), Decimal(0))),
               "timing_rationale": (state.get("state_of_world", {}).get("price_forecast") or {}).get(
                   "rationale", plan.reasoning if plan else ""),
               "review_flags": [s["step"] for s in staged if s["step"]["action"] == "flag_for_human"],
               "failure": failure}
    return {"outcome": outcome,
            "halt_reason": f"Commit stopped: {failure['message']}" if failure else None,
            "attempts": [{"node": "commit", "ok": not failure, "committed": len(committed),
                          "error": failure}]}
