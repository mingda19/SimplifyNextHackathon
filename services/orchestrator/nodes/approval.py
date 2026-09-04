"""
PHASE 4 — the guardrail node.  No LLM. Cost: $0.

LangGraph `interrupt()` pauses the graph here. Execution resumes only when a
human sends a decision back, and the checkpointer means a pending approval
survives a process restart.
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.types import interrupt

from ..config import BASELINES
from ..state import AgentState, Plan

log = logging.getLogger(__name__)


def build_summary(state: AgentState) -> dict[str, Any]:
    """
    The four panels the dashboard renders. The fourth — adaptations — is the
    story of the whole build, so it gets first-class treatment here.
    """
    sow = state.get("state_of_world", {})
    plan = Plan.model_validate(state["plan"]) if state.get("plan") else None
    attempts = state.get("attempts", [])

    adaptations = [a for a in attempts if a.get("node") == "adapt" and a.get("ok")]
    staged = state.get("staged", [])

    total = 0.0
    for s in staged:
        if s.get("type") == "order":
            total += float(s.get("result", {}).get("total_sgd", 0) or 0)

    return {
        "sensed": {
            "as_of": sow.get("as_of"),
            "below_reorder": (sow.get("alerts") or {}).get("below_reorder", []),
            "expiring_soon": (sow.get("alerts") or {}).get("expiring_soon", []),
            "top_unmet_needs": (sow.get("unmet_needs") or {}).get("ranked", [])[:3],
            "price_signal": {
                k: (sow.get("price_forecast") or {}).get(k)
                for k in ("series", "direction", "recommendation",
                          "pct_change_3m", "data_lag_months")
            },
            "unavailable_services": state.get("degraded_services", []),
        },
        "predicted": {
            "stockout_sku": plan.stockout_sku if plan else None,
            "days_until_failure": plan.days_until_failure if plan else None,
            "reasoning": plan.reasoning if plan else None,
        },
        "queued": {
            "steps": [s.model_dump() for s in plan.steps] if plan else [],
            "staged": staged,
            "total_sgd": round(total, 2),
        },
        # The panel that matters. Give it the most space in the UI.
        "adaptations": [
            {"attempt": a.get("attempt"), "error_code": a.get("error_code"),
             "what_changed": a.get("what_changed"), "confidence": a.get("confidence")}
            for a in adaptations
        ],
        "guardrails": {
            "baselines": BASELINES,
            "exceeds_single_order_cap": total > BASELINES["max_single_order_sgd"],
            "halt_reason": state.get("halt_reason"),
        },
    }


def approval(state: AgentState) -> dict[str, Any]:
    summary = build_summary(state)
    log.info("approval: pausing for human — S$%.2f staged, %d adaptation(s)",
             summary["queued"]["total_sgd"], len(summary["adaptations"]))

    # Blocks here. The resumed value arrives as the return.
    decision = interrupt(summary)

    if isinstance(decision, dict):
        verdict = decision.get("decision", "rejected")
    else:
        verdict = str(decision or "rejected")
    verdict = verdict.strip().lower()
    verdict = verdict if verdict in {"approved", "rejected"} else "rejected"

    log.info("approval: human said %s", verdict)
    return {"approval": verdict,
            "attempts": [{"node": "approval", "ok": True, "decision": verdict}]}
