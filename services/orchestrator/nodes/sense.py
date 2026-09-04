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
    tasks: dict[str, Callable[[], Any]] = {
        "inventory": services.get_inventory,
        "alerts": services.get_alerts,
        "unmet_needs": services.get_unmet_needs,
        "price_forecast": services.get_price_forecast,
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

    if degraded:
        log.warning("sense: degraded, continuing without %s", ", ".join(degraded))

    return {
        "state_of_world": sow,
        "degraded_services": degraded,
        "attempts": [{"node": "sense", "ok": True, "degraded": degraded}],
    }
