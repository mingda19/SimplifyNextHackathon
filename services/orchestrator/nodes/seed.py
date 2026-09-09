"""
PHASE 1 — the ingestion node.  No LLM. Cost: $0.

Trimmed from the old `sense.py`: inventory/alerts/inbound-orders only.
Feedback and price forecasting are no longer pre-fetched here -- they are
tools (`feedback_extraction`, `price_forecaster`) the agent calls on its own
mid-loop, so a run that doesn't need them doesn't pay for them, and the
agent's own reasoning decides which SKUs are worth a price lookup rather than
a fixed upfront batch.

Deterministic on purpose, same as before: making a model do data fetching is
the most common way hackathon agents waste budget, and it adds a failure mode
for no benefit.

Also builds the first `HumanMessage` the agent loop reasons over -- this is
`_compact()`'s old job (used to live in `llm.py`, called once inside
`predict_plan()`); it belongs here now since `llm.py` no longer owns "what
goes in the user turn," `seed` does.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any, Callable

from langchain_core.messages import HumanMessage

from .. import services
from ..config import BASELINES
from ..state import AgentState

log = logging.getLogger(__name__)


def _safe(name: str, fn: Callable[[], Any]) -> tuple[str, Any, bool]:
    """Never propagate an upstream failure. Degrade and let the agent know."""
    try:
        return name, fn(), True
    except Exception as exc:                      # noqa: BLE001 — deliberate
        log.warning("seed: %s unavailable (%s: %s)", name, type(exc).__name__, exc)
        return name, None, False


def seed(state: AgentState) -> dict[str, Any]:
    tasks: dict[str, Callable[[], Any]] = {
        "inventory": services.get_inventory,
        "alerts": services.get_alerts,
        "inbound_orders": services.get_inbound_orders,
    }
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        results = list(pool.map(lambda kv: _safe(kv[0], kv[1]), tasks.items()))

    sow: dict[str, Any] = {"as_of": date.today().isoformat()}
    degraded: list[str] = []
    for name, value, ok in results:
        if ok:
            sow[name] = value
        else:
            degraded.append(name)

    # Deterministic hint for the agent: which commodities are worth a
    # price_forecaster call. Still $0 -- this is arithmetic over inventory,
    # not a fetch -- and it saves the agent from having to reason about risk
    # from scratch or call price_forecaster on every SKU indiscriminately.
    sow["at_risk_dspi_series"] = _at_risk_series(sow)

    if degraded:
        log.warning("seed: degraded, continuing without %s", ", ".join(degraded))

    payload = {
        "charity_type": state.get("charity_type", "B"),
        "baselines": BASELINES,
        "state_of_world": _compact(sow),
        "unavailable_services": degraded,
    }
    # sort_keys is not cosmetic — unsorted JSON makes the same run non-
    # reproducible in tests and harder to diff across runs.
    user_turn = json.dumps(payload, sort_keys=True, indent=2, default=str)

    _trace(sow, degraded)
    return {
        "state_of_world": sow,
        "degraded_services": degraded,
        "messages": [HumanMessage(content=user_turn)],
        "attempts": [{"node": "seed", "ok": True, "degraded": degraded,
                      "shape": _shape(sow)}],
    }


def _at_risk_series(sow: dict[str, Any]) -> list[str]:
    """DSPI series for SKUs that are low, expiring, or already flagged."""
    items = sow.get("inventory") or []
    by_sku = {i["sku"]: i for i in items if isinstance(i, dict) and "sku" in i}

    risky: set[str] = set()
    for i in items:
        if not isinstance(i, dict):
            continue
        draw = i.get("avg_daily_draw") or 0
        cover = (i.get("on_hand", 0) / draw) if draw else float("inf")
        if i.get("on_hand", 0) < i.get("reorder_point", 0) or cover < 21:
            risky.add(i["sku"])

    alerts = sow.get("alerts") or {}
    risky.update(alerts.get("below_reorder") or [])
    for a in (alerts.get("expiring_soon") or []):
        if isinstance(a, dict) and a.get("sku"):
            risky.add(a["sku"])

    series = {by_sku[s]["dspi_series"] for s in risky
              if s in by_sku and by_sku[s].get("dspi_series")}
    return sorted(series)


def _compact(sow: dict[str, Any]) -> dict[str, Any]:
    """Trim the raw inventory read to what's actually worth the agent's
    attention.

    Same trimming philosophy as the old `llm._compact()`: only drop fields
    and rows that are inert, never invent data, and say how much was
    dropped so the model knows the list is truncated rather than complete.
    Simpler than the old version since `unmet_needs`/`price_forecast` are no
    longer part of the upfront snapshot -- the agent fetches those itself,
    via tools, only if and when it decides it needs them.
    """
    out: dict[str, Any] = {"as_of": sow.get("as_of")}

    items = sow.get("inventory") or []
    keep, skipped = [], 0
    for i in items:
        draw = i.get("avg_daily_draw") or 0
        cover = (i.get("on_hand", 0) / draw) if draw else None
        if i.get("on_hand", 0) < i.get("reorder_point", 0) or (
                cover is not None and cover < 21):
            keep.append({k: i.get(k) for k in
                         ("sku", "name", "on_hand", "unit", "reorder_point",
                          "avg_daily_draw", "unit_cost_sgd",
                          "preferred_vendor_id", "dspi_series")}
                        | {"days_cover": round(cover, 1) if cover else None})
        else:
            skipped += 1
    out["inventory_at_risk"] = keep
    out["inventory_healthy_count"] = skipped
    out["at_risk_dspi_series"] = sow.get("at_risk_dspi_series") or []

    out["alerts"] = sow.get("alerts")

    # What is already ordered. The agent must subtract this before proposing
    # a restock, or it re-orders the same SKU every run for the whole lead
    # time -- see AGENT_SYSTEM's rule on `already_on_the_way`.
    out["already_on_the_way"] = sow.get("inbound_orders") or {}

    return out


def _shape(sow: dict[str, Any]) -> dict[str, Any]:
    """Compact description of what SEED produced — carried in `attempts`."""
    inv = sow.get("inventory") or []
    alerts = sow.get("alerts") or {}
    return {
        "inventory_items": len(inv),
        "below_reorder": len(alerts.get("below_reorder") or []),
        "expiring_soon": len(alerts.get("expiring_soon") or []),
        "at_risk_series": len(sow.get("at_risk_dspi_series") or []),
        "skus_with_inbound": len(sow.get("inbound_orders") or {}),
    }


def _trace(sow: dict[str, Any], degraded: list[str]) -> None:
    sh = _shape(sow)
    log.info("SEED ─ inventory=%d below_reorder=%d expiring=%d inbound=%d "
             "| at_risk_series=%d | degraded=%s",
             sh["inventory_items"], sh["below_reorder"], sh["expiring_soon"],
             sh["skus_with_inbound"], sh["at_risk_series"], degraded or "none")
