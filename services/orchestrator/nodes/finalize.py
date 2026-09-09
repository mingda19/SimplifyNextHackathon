"""
PHASE 4 — the guardrail + commit node, merged.  No LLM. Cost: $0.

`tools_condition`'s "no tool call" branch routes here once the agent stops
calling tools. This single node does what used to be two separate nodes
(`approval.py` then `commit.py`): build the dashboard summary, call
`interrupt()` and block for a human decision, then -- on resume -- commit
exactly the approved actions.

IMPORTANT: `interrupt()` re-runs this entire function from the top on every
resume (documented LangGraph HITL behavior, not new to this merge). Nothing
above the `interrupt()` call may have a side effect, or it double-fires on
every resume. `build_summary()` is pure -- reads state, calls no service --
so this is safe today. Do not "optimize" by hoisting a `services.*` call
above the `interrupt()` line.
"""
from __future__ import annotations

import ast
import logging
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import interrupt

from .. import services
from ..config import BASELINES
from ..state import APPROVAL_VERSION, AgentState

log = logging.getLogger(__name__)

_COMMITTED: set[str] = set()


def _line_total(staged_item: dict[str, Any]) -> float:
    """Value of one staged order line.

    Workstream 1's order response returns `unit_price_sgd` and `qty` but NOT a
    `total_sgd` — only the local fake did. Reading total_sgd alone made every
    real run show S$0.00.
    """
    r = staged_item.get("result") or {}
    if r.get("total_sgd") is not None:
        return float(r["total_sgd"])
    if r.get("total_price_sgd") is not None:
        return float(r["total_price_sgd"])
    unit = r.get("unit_price_sgd")
    qty = r.get("qty") or (staged_item.get("step") or {}).get("qty")
    if unit is not None and qty:
        return float(unit) * int(qty)
    return 0.0


def _steps_with_value(staged: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each staged item with its own index and value.

    Replaces the old plan-vs-staged reconciliation (matching a `Plan.steps`
    entry to a `staged` entry by `(action, sku)`): there is no separate plan
    list any more, `staged` already carries everything -- every entry IS a
    step, in the order the agent generated it, so its own list position is
    the index a human approves by.
    """
    out = []
    for i, s in enumerate(staged):
        step = dict(s.get("step") or {})
        step["index"] = i
        step["value_sgd"] = round(_line_total(s), 2)
        step["staged"] = True
        out.append(step)
    return out


def _parse_tool_content(content: Any) -> dict[str, Any] | None:
    """`ToolMessage.content` is `str(dict)` for action_generator's results
    and errors (see `tools/action_generator.py`) -- literal_eval round-trips
    it safely since we control the exact serialization."""
    if not isinstance(content, str):
        return None
    try:
        val = ast.literal_eval(content)
    except (ValueError, SyntaxError):
        return None
    return val if isinstance(val, dict) else None


def _reconstruct_adaptations(messages: list[Any]) -> list[dict[str, Any]]:
    """Rebuild the old `adaptations` panel from the message transcript.

    There is no `adapt` node any more -- retries happen because the agent
    calls `action_generator` again after seeing an error `ToolMessage`. This
    walks the transcript looking for exactly that pattern: an
    `action_generator` call for a SKU whose result was an error dict (has
    `code`, no `status`), followed by another `action_generator` call for the
    same SKU. `what_changed` comes from the retry's own `rationale` argument
    -- AGENT_SYSTEM instructs the model to explain what changed there, so
    there is no need to diff the two calls' arguments by hand.
    """
    calls: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for m in messages:
        if isinstance(m, AIMessage):
            for tc in (m.tool_calls or []):
                if tc["name"] == "action_generator":
                    calls[tc["id"]] = {"sku": tc["args"].get("sku"),
                                       "args": tc["args"], "content": None}
                    order.append(tc["id"])
        elif isinstance(m, ToolMessage) and m.tool_call_id in calls:
            calls[m.tool_call_id]["content"] = m.content

    by_sku: dict[str, list[str]] = {}
    for cid in order:
        by_sku.setdefault(calls[cid]["sku"], []).append(cid)

    adaptations: list[dict[str, Any]] = []
    for sku, ids in by_sku.items():
        attempt = 0
        for i in range(len(ids) - 1):
            cur = _parse_tool_content(calls[ids[i]]["content"])
            if cur and "code" in cur and "status" not in cur:
                attempt += 1
                nxt = calls[ids[i + 1]]["args"]
                adaptations.append({
                    "attempt": attempt,
                    "sku": sku,
                    "error_code": cur.get("code"),
                    "what_changed": nxt.get("rationale", ""),
                })
    return adaptations


def build_summary(state: AgentState) -> dict[str, Any]:
    """
    The four panels the dashboard renders. The fourth — adaptations — is the
    story of the whole build, so it gets first-class treatment here.
    """
    sow = state.get("state_of_world", {})
    diagnosis = state.get("diagnosis") or {}
    staged = state.get("staged", [])
    attempts = state.get("attempts", [])

    order_values = [_line_total(s) for s in staged if s.get("type") == "order"]
    total = sum(order_values)

    return {
        "sensed": {
            "as_of": sow.get("as_of"),
            "below_reorder": (sow.get("alerts") or {}).get("below_reorder", []),
            "expiring_soon": (sow.get("alerts") or {}).get("expiring_soon", []),
            "top_unmet_needs": (sow.get("unmet_needs") or {}).get("ranked", [])[:3],
            "price_signals": [
                {k: f.get(k) for k in
                 ("series", "direction", "recommendation", "pct_change_3m",
                  "confidence", "data_lag_months")}
                for f in ((sow.get("price_forecast") or {}).get("forecasts") or {}).values()
                if f.get("recommendation") in ("BUY_NOW", "DEFER")
            ],
            "price_series_without_forecast":
                (sow.get("price_forecast") or {}).get("no_forecast_for") or [],
            "unavailable_services": state.get("degraded_services", []),
        },
        "predicted": {
            "stockout_sku": diagnosis.get("stockout_sku"),
            "days_until_failure": diagnosis.get("days_until_failure"),
            "reasoning": diagnosis.get("reasoning"),
        },
        "queued": {
            "steps": _steps_with_value(staged),
            "staged": staged,
            "total_sgd": round(total, 2),
        },
        # The panel that matters. Give it the most space in the UI.
        "adaptations": _reconstruct_adaptations(state.get("messages", [])),
        "guardrails": {
            "baselines": BASELINES,
            # Pre-existing bug fixed here: this used to check the SUM of all
            # staged order lines against a baseline literally named "max
            # SINGLE order" -- two S$1000 lines (sum S$2000) tripped a
            # S$1500 cap meant to flag any ONE line that large, while a
            # genuinely oversized S$1500.01 single line among small ones
            # would not have tripped it at all. Now checks the max line.
            "exceeds_single_order_cap": bool(order_values) and
                max(order_values) > BASELINES["max_single_order_sgd"],
            "halt_reason": state.get("halt_reason"),
        },
        "trace": attempts,
        "approval_version": APPROVAL_VERSION,
    }


def _checklist(state: AgentState, staged: list[dict[str, Any]]) -> dict[str, Any]:
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
        items.append({"sku": step["sku"], "qty": step["qty"],
                      "why": step.get("rationale", ""), "urgency": urgency,
                      "days_cover_shortfall": shortfall,
                      "priority_score": urgency * shortfall})
    items.sort(key=lambda i: (-i["priority_score"], i["sku"]))
    return {"kind": "acquisition_checklist", "items": items,
            "review_flags": [s["step"] for s in staged
                             if s["step"]["action"] == "flag_for_human"]}


def finalize(state: AgentState) -> dict[str, Any]:
    # -- build + interrupt (see module docstring: nothing above this line in
    #    a resumed call may have run a side effect) --------------------------
    summary = build_summary(state)
    log.info("finalize: pausing for human — S$%.2f staged, %d adaptation(s)",
             summary["queued"]["total_sgd"], len(summary["adaptations"]))

    decision = interrupt(summary)

    # Two resume-payload shapes accepted, unchanged from the old design:
    #   {"decision": "approved"}      — the whole batch
    #   {"approved_steps": [0, 2]}    — only these staged-item indexes
    approved_steps = None
    if isinstance(decision, dict):
        verdict = str(decision.get("decision", "") or "").strip().lower()
        if decision.get("approved_steps") is not None:
            approved_steps = [int(i) for i in decision["approved_steps"]]
            verdict = "approved" if approved_steps else "rejected"
    else:
        verdict = str(decision or "rejected").strip().lower()
    verdict = verdict if verdict in {"approved", "rejected"} else "rejected"

    staged = state.get("staged", [])
    if verdict == "approved" and approved_steps is None:
        approved_steps = list(range(len(staged)))
    if verdict == "rejected":
        approved_steps = []

    log.info("finalize: human said %s (steps %s of %d)",
             verdict, approved_steps, len(staged))

    if state.get("approval_version") != APPROVAL_VERSION:
        return {"approval": verdict, "approved_steps": approved_steps,
                "halt_reason": "Legacy approval: review existing orders and start a new run."}
    if verdict != "approved" or state.get("halt_reason"):
        return {"approval": verdict, "approved_steps": approved_steps,
                "halt_reason": state.get("halt_reason") if verdict == "approved"
                else "Human declined this run."}

    thread_id = state.get("thread_id")
    if not thread_id:
        raise ValueError("finalize requires a durable thread_id")

    charity_type = state.get("charity_type", "B")
    if charity_type == "A":
        return {"approval": verdict, "approved_steps": approved_steps,
                "outcome": _checklist(state, staged),
                "attempts": [{"node": "finalize", "ok": True,
                              "kind": "acquisition_checklist"}]}

    committed: list[dict[str, Any]] = []
    skipped: list[str] = []
    declined: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for idx, item in enumerate(staged):
        st = item.get("step") or {}
        if approved_steps is not None and idx not in approved_steps:
            declined.append(st)
            continue

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
            except Exception as exc:                      # noqa: BLE001
                log.warning("finalize: order failed for %s: %s", st.get("sku"), exc)
                failed.append({"step": st, "error": str(exc)})
        else:
            committed.append(item)

    ordered_skus = sorted({c["step"]["sku"] for c in committed
                           if c.get("type") == "order" and c.get("step", {}).get("sku")})
    resolution = {"resolved": 0}
    if ordered_skus:
        try:
            resolution = services.resolve_feedback(
                ordered_skus, thread_id, note=f"ordered via agent run {thread_id}")
        except Exception as exc:                          # noqa: BLE001
            log.warning("finalize: feedback resolution failed: %s", exc)
            resolution = {"resolved": 0, "error": str(exc)}

    failure = failed[0]["error"] if failed else None
    orders = [c for c in committed if c["type"] == "order"]
    outcome = {
        "kind": "commit_failed" if failure else "purchase_order",
        "orders": orders,
        "allocations": [c for c in committed if c["type"] == "allocation"],
        "total_sgd": round(sum(_line_total(o) for o in orders), 2),
        "timing_rationale": (state.get("state_of_world", {})
                             .get("price_forecast") or {}).get("rationale",
                             (state.get("diagnosis") or {}).get("reasoning", "")),
        "review_flags": [s["step"] for s in staged
                         if s["step"]["action"] == "flag_for_human"],
        "declined_steps": declined,
        "failed_steps": failed,
        "failure": failure,
        "feedback_resolved": resolution.get("resolved", 0),
    }

    log.info("finalize: %s — %d committed, %d declined, %d skipped, "
             "%d feedback row(s) resolved",
             outcome["kind"], len(committed), len(declined), len(skipped),
             resolution.get("resolved", 0))

    return {"approval": verdict, "approved_steps": approved_steps,
            "outcome": outcome,
            "attempts": [{"node": "finalize", "ok": True, "kind": outcome["kind"],
                          "committed": len(committed), "declined": len(declined),
                          "skipped": len(skipped),
                          "feedback_resolved": resolution.get("resolved", 0)}]}
