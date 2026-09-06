"""
PHASE 4 — the guardrail node.  No LLM. Cost: $0.

LangGraph `interrupt()` pauses the graph here. Execution resumes only when a
human sends a decision back, and the checkpointer means a pending approval
survives a process restart.
"""
from __future__ import annotations

import logging
from typing import Any
from decimal import Decimal

from langgraph.types import interrupt

from ..config import BASELINES
from ..state import APPROVAL_VERSION, AgentState, Plan
from ..services import total_sgd

log = logging.getLogger(__name__)


def _line_total(staged_item: dict[str, Any]) -> float:
    """Value of one staged order line.

    Workstream 1's order response returns `unit_price_sgd` and `qty` but NOT a
    `total_sgd` — only the local fake did. Reading total_sgd alone made every
    real run show S$0.00.
    """
    r = staged_item.get("result") or {}
    if r.get("total_sgd") is not None:
        return float(r["total_sgd"])
    if r.get("total_price_sgd") is not None:      # quote responses use this name
        return float(r["total_price_sgd"])
    unit = r.get("unit_price_sgd")
    qty = r.get("qty") or (staged_item.get("step") or {}).get("qty")
    if unit is not None and qty:
        return float(unit) * int(qty)
    return 0.0


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
            total += _line_total(s)

    def _steps_with_value(pl, stg):
        """Each step with its own index and value, so a human can approve
        individual lines rather than the whole plan or nothing."""
        out = []
        for i, st in enumerate(pl.steps if pl else []):
            d = st.model_dump()
            d["index"] = i
            match = next((x for x in stg
                          if (x.get("step") or {}).get("sku") == d["sku"]
                          and (x.get("step") or {}).get("action") == d["action"]), None)
            d["value_sgd"] = round(_line_total(match), 2) if match else 0.0
            d["staged"] = match is not None
            out.append(d)
        return out

    return {
        "approval_version": state.get("approval_version"),
        "sensed": {
            "as_of": sow.get("as_of"),
            "below_reorder": (sow.get("alerts") or {}).get("below_reorder", []),
            "expiring_soon": (sow.get("alerts") or {}).get("expiring_soon", []),
            "top_unmet_needs": (sow.get("unmet_needs") or {}).get("ranked", [])[:3],
            # SENSE now returns a forecast PER at-risk commodity, not one
            # hardcoded series. Surface only the actionable ones — a screen full
            # of NEUTRAL tells the approver nothing.
            "price_signals": [
                {k: f.get(k) for k in ("series", "direction", "recommendation",
                                       "pct_change_3m", "confidence",
                                       "data_lag_months")}
                for f in ((sow.get("price_forecast") or {}).get("forecasts") or {}).values()
                if f.get("recommendation") in ("BUY_NOW", "DEFER")
            ],
            "price_series_without_forecast":
                (sow.get("price_forecast") or {}).get("no_forecast_for") or [],
            "unavailable_services": state.get("degraded_services", []),
        },
        "predicted": {
            "stockout_sku": plan.stockout_sku if plan else None,
            "days_until_failure": plan.days_until_failure if plan else None,
            "reasoning": plan.reasoning if plan else None,
        },
        "queued": {
            "steps": _steps_with_value(plan, staged),
            "staged": staged,
            "total_sgd": float(total),
        },
        # The panel that matters. Give it the most space in the UI.
        "adaptations": [
            {"attempt": a.get("attempt"), "error_code": a.get("error_code"),
             "what_changed": a.get("what_changed"), "confidence": a.get("confidence")}
            for a in adaptations
        ],
        "guardrails": {
            "baselines": BASELINES,
            "exceeds_single_order_cap": state.get("charity_type", "B") == "B" and any(
                t > BASELINES["max_single_order_sgd"] for t in order_totals),
            "exceeds_monthly_budget": total > BASELINES["monthly_budget_sgd"],
            "halt_reason": state.get("halt_reason") or (
                "This run predates the approval fix. Review existing orders and start a new run."
                if state.get("approval_version") != APPROVAL_VERSION else None),
        },
        "trace": attempts,
    }


def approval(state: AgentState) -> dict[str, Any]:
    summary = build_summary(state)
    log.info("approval: pausing for human — S$%.2f staged, %d adaptation(s)",
             summary["queued"]["total_sgd"], len(summary["adaptations"]))

    # Blocks here. The resumed value arrives as the return.
    decision = interrupt(summary)

    # Two shapes accepted:
    #   {"decision": "approved"}                    — the whole plan
    #   {"approved_steps": [0, 2]}                  — only these step indexes
    # Per-step exists because "approve everything or nothing" is not how a
    # charity actually reviews a purchase: they may want the rice but not the
    # S$400 of cooking oil in the same plan.
    approved_steps = None
    if isinstance(decision, dict):
        verdict = str(decision.get("decision", "") or "").strip().lower()
        if decision.get("approved_steps") is not None:
            approved_steps = [int(i) for i in decision["approved_steps"]]
            verdict = "approved" if approved_steps else "rejected"
    else:
        verdict = str(decision or "rejected").strip().lower()
    verdict = verdict if verdict in {"approved", "rejected"} else "rejected"
    if verdict == "approved" and (summary["guardrails"]["halt_reason"] or summary["guardrails"]["exceeds_monthly_budget"]):
        return {"approval": "rejected", "halt_reason": summary["guardrails"]["halt_reason"] or "Monthly budget exceeded."}

    n_steps = len(Plan.model_validate(state["plan"]).steps) if state.get("plan") else 0
    if verdict == "approved" and approved_steps is None:
        approved_steps = list(range(n_steps))          # whole plan
    if verdict == "rejected":
        approved_steps = []

    log.info("approval: human said %s (steps %s of %d)",
             verdict, approved_steps, n_steps)
    return {"approval": verdict,
            "approved_steps": approved_steps,
            "attempts": [{"node": "approval", "ok": True, "decision": verdict,
                          "approved_steps": approved_steps}]}
