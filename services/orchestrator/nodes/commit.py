"""
PHASE 4b — final execution.  No LLM. Cost: $0.

Runs only after approval. Idempotent: keyed on thread_id + step index so an
approval double-click cannot place two orders.
"""
from __future__ import annotations

import logging
from typing import Any

from .. import services
from ..state import AgentState, Plan

log = logging.getLogger(__name__)

# Process-local idempotency guard. A real deployment would persist this
# alongside the checkpoint.
_COMMITTED: set[str] = set()


def _line_value(result: dict[str, Any]) -> float:
    """Workstream 1 returns unit_price_sgd + qty, not total_sgd."""
    if result.get("total_sgd") is not None:
        return float(result["total_sgd"])
    if result.get("total_price_sgd") is not None:
        return float(result["total_price_sgd"])
    unit, qty = result.get("unit_price_sgd"), result.get("qty")
    return float(unit) * int(qty) if unit is not None and qty else 0.0


def commit(state: AgentState) -> dict[str, Any]:
    thread_id = state.get("thread_id", "unknown")
    charity_type = state.get("charity_type", "B")
    staged = state.get("staged", [])
    plan = Plan.model_validate(state["plan"]) if state.get("plan") else None

    # Only the steps the human actually ticked. None means "whole plan"
    # (older callers / the CLI); an empty list means nothing was approved.
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

        key = f"{thread_id}:{idx}"
        if key in _COMMITTED:
            skipped.append(key)
            continue
        _COMMITTED.add(key)

        if item["type"] == "order":
            # THIS is where money is spent — the only place that calls /order.
            try:
                placed = services.vendor_order(st["vendor_id"], st["sku"], st["qty"])
                committed.append({"type": "order", "step": st,
                                  "result": {**placed, "status": "CONFIRMED"}})
            except Exception as exc:                  # noqa: BLE001
                # One line failing must not lose the others that succeeded.
                log.warning("commit: order failed for %s: %s", st.get("sku"), exc)
                failed.append({"step": st, "error": str(exc)})
        else:
            committed.append(item)

    if charity_type == "A":
        # Donation-fed: the terminal action is a ranked acquisition checklist.
        outcome = {
            "kind": "acquisition_checklist",
            "items": [
                {"sku": c["step"]["sku"], "qty": c["step"].get("qty", 0),
                 "why": c["step"].get("rationale", "")}
                for c in committed
            ],
            "review_flags": [c["step"] for c in committed
                             if c["step"]["action"] == "flag_for_human"],
        }
    else:
        # Budget-funded: the terminal action is a confirmed purchase order.
        orders = [c for c in committed if c["type"] == "order"]
        outcome = {
            "kind": "purchase_order",
            "orders": orders,
            "total_sgd": round(sum(_line_value(o["result"]) for o in orders), 2),
            "timing_rationale": (plan.reasoning if plan else ""),
            "review_flags": [c["step"] for c in committed
                             if c["step"]["action"] == "flag_for_human"],
        }

    outcome["declined_steps"] = declined
    outcome["failed_steps"] = failed

    # Close the loop: tell the feedback service which needs this order actually
    # addresses, so the next run does not re-propose work already done. Only
    # SKUs we really committed — a declined line resolves nothing.
    ordered_skus = sorted({c["step"]["sku"] for c in committed
                           if c.get("type") == "order" and c.get("step", {}).get("sku")})
    resolution = {"resolved": 0}
    if ordered_skus:
        try:
            resolution = services.resolve_feedback(
                ordered_skus, thread_id,
                note=f"ordered via agent run {thread_id}")
        except Exception as exc:                      # noqa: BLE001
            # Never fail a committed order because bookkeeping failed — the
            # money is already spent; the worst case is a duplicate proposal.
            log.warning("commit: feedback resolution failed: %s", exc)
            resolution = {"resolved": 0, "error": str(exc)}
    outcome["feedback_resolved"] = resolution.get("resolved", 0)

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
