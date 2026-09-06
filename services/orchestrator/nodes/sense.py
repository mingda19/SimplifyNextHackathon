"""
PHASE 1 — the ingestion node.  No LLM. Cost: $0.

Deterministic on purpose. Making a model do data fetching is the most common
way hackathon agents waste budget, and it adds a failure mode for no benefit.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any, Callable

from .. import services
from ..state import AgentState

log = logging.getLogger(__name__)


def _safe(name: str, fn: Callable[[], Any]) -> tuple[str, Any, bool]:
    """Never propagate an upstream failure. Degrade and let `predict` know."""
    try:
        return name, fn(), True
    except Exception as exc:                      # noqa: BLE001 — deliberate
        log.warning("sense: %s unavailable (%s: %s)", name, type(exc).__name__, exc)
        return name, None, False


def sense(state: AgentState) -> dict[str, Any]:
    # Round 1 — the three primary reads, in parallel.
    tasks: dict[str, Callable[[], Any]] = {
        "inventory": services.get_inventory,
        "alerts": services.get_alerts,
        "unmet_needs": services.get_unmet_needs,
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

    # Round 2 — price, but only for what is actually at risk. This has to come
    # second: which commodities matter is a function of the inventory we just
    # read, not a fixed list.
    at_risk = _at_risk_series(sow)
    sow["at_risk_series"] = at_risk
    if at_risk:
        name, value, ok = _safe("price_forecast",
                                lambda: services.get_price_forecasts(at_risk))
        if ok:
            sow["price_forecast"] = value
        else:
            degraded.append(name)
    else:
        sow["price_forecast"] = {"forecasts": {}, "no_forecast_for": [],
                                 "note": "nothing at risk, no price lookup needed"}

    if degraded:
        log.warning("sense: degraded, continuing without %s", ", ".join(degraded))

    _trace(sow, degraded)
    return {
        "state_of_world": sow,
        "degraded_services": degraded,
        "attempts": [{"node": "sense", "ok": True, "degraded": degraded,
                      "shape": _shape(sow)}],
    }


def _at_risk_series(sow: dict[str, Any]) -> list[str]:
    """DSPI series for SKUs that are low, expiring, or asked for by name."""
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

    # Beneficiaries asking for something is a demand signal on that SKU too.
    for need in ((sow.get("unmet_needs") or {}).get("ranked") or [])[:10]:
        risky.update(need.get("mentioned_skus") or [])

    series = {by_sku[s]["dspi_series"] for s in risky
              if s in by_sku and by_sku[s].get("dspi_series")}
    return sorted(series)


def _shape(sow: dict[str, Any]) -> dict[str, Any]:
    """Compact description of what SENSE produced — carried in `attempts`."""
    inv = sow.get("inventory") or []
    alerts = sow.get("alerts") or {}
    needs = (sow.get("unmet_needs") or {}).get("ranked") or []
    pf = sow.get("price_forecast") or {}
    return {
        "inventory_items": len(inv),
        "below_reorder": len(alerts.get("below_reorder") or []),
        "expiring_soon": len(alerts.get("expiring_soon") or []),
        "unmet_needs": len(needs),
        "needs_with_no_sku": sum(1 for n in needs if n.get("gap")),
        "at_risk_series": len(sow.get("at_risk_series") or []),
        "price_forecasts": len(pf.get("forecasts") or {}),
        "price_no_forecast": len(pf.get("no_forecast_for") or []),
        "actionable_price_signals": sum(
            1 for f in (pf.get("forecasts") or {}).values()
            if f.get("recommendation") in ("BUY_NOW", "DEFER")),
    }


def _trace(sow: dict[str, Any], degraded: list[str]) -> None:
    sh = _shape(sow)
    log.info("SENSE ─ inventory=%d below_reorder=%d expiring=%d | needs=%d (gaps=%d) "
             "| at_risk_series=%d forecasts=%d actionable=%d | degraded=%s",
             sh["inventory_items"], sh["below_reorder"], sh["expiring_soon"],
             sh["unmet_needs"], sh["needs_with_no_sku"], sh["at_risk_series"],
             sh["price_forecasts"], sh["actionable_price_signals"],
             degraded or "none")
