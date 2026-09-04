"""
PHASE 4b — final execution.  No LLM. Cost: $0.

Runs only after approval. Idempotent: keyed on thread_id + step index so an
approval double-click cannot place two orders.
"""
from __future__ import annotations

import logging
from typing import Any

from ..state import AgentState, Plan

log = logging.getLogger(__name__)

# Process-local idempotency guard. A real deployment would persist this
# alongside the checkpoint.
_COMMITTED: set[str] = set()


def commit(state: AgentState) -> dict[str, Any]:
    thread_id = state.get("thread_id", "unknown")
    charity_type = state.get("charity_type", "B")
    staged = state.get("staged", [])
    plan = Plan.model_validate(state["plan"]) if state.get("plan") else None

    committed: list[dict[str, Any]] = []
    skipped: list[str] = []

    for idx, item in enumerate(staged):
        key = f"{thread_id}:{idx}"
        if key in _COMMITTED:
            skipped.append(key)
            continue
        _COMMITTED.add(key)

        if item["type"] == "order":
            # TODO(W/G): swap for the real committing call once /vendor/{id}/order
            # distinguishes stage from commit.
            committed.append({"type": "order", "step": item["step"],
                              "result": {**item.get("result", {}),
                                         "status": "CONFIRMED"}})
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
            "total_sgd": round(sum(float(o["result"].get("total_sgd", 0) or 0)
                                   for o in orders), 2),
            "timing_rationale": (plan.reasoning if plan else ""),
            "review_flags": [c["step"] for c in committed
                             if c["step"]["action"] == "flag_for_human"],
        }

    log.info("commit: %s — %d committed, %d skipped (idempotent)",
             outcome["kind"], len(committed), len(skipped))

    return {"outcome": outcome,
            "attempts": [{"node": "commit", "ok": True, "kind": outcome["kind"],
                          "committed": len(committed), "skipped": len(skipped)}]}


def reset_idempotency() -> None:
    """Clear the commit guard. Tests and long-lived processes only."""
    _COMMITTED.clear()
