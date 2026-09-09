"""Tool: look up the commodity price trend/signal for one DSPI series.

Wraps the existing `services.get_price_forecast()` HTTP client -- no new
backend work. Zero LLM cost: this hits the price-forecaster's own ML model,
not Bedrock, so it does not touch the orchestrator's token ledger at all.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from .. import services
from ._util import merge_state_of_world

log = logging.getLogger(__name__)


@tool
def price_forecaster(
    series: str,
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Get the price trend/signal for one commodity (DSPI series name).

    Returns a BUY_NOW / DEFER / NEUTRAL recommendation with a calibrated
    confidence, plus the recent % change and seasonal-low months. `series`
    is the `dspi_series` value on the SKU you're investigating (the exact
    SingStat commodity name), not a made-up label -- an unresolvable series
    is not an error, it usually means that commodity was deliberately
    excluded from the price model as too perishable to time a purchase
    against (fresh produce, fresh meat, eggs). Only call this for SKUs you
    are actually considering acting on -- it is a real network call, not
    free in latency even though it costs no LLM budget.
    """
    try:
        forecast = services.get_price_forecast(series)
    except services.ServiceError as exc:
        log.info("price_forecaster: %s unavailable: %s", series, exc)
        sow = merge_state_of_world(state, {
            "price_forecast": {
                **(state.get("state_of_world", {}).get("price_forecast") or
                   {"forecasts": {}, "no_forecast_for": []}),
                "no_forecast_for": sorted({
                    *((state.get("state_of_world", {}).get("price_forecast") or {})
                      .get("no_forecast_for") or []),
                    series,
                }),
            },
        })
        return Command(update={
            "state_of_world": sow,
            "messages": [ToolMessage(
                content=f"No forecast available for '{series}': {exc}",
                tool_call_id=tool_call_id,
            )],
        })

    pf = dict(state.get("state_of_world", {}).get("price_forecast") or
              {"forecasts": {}, "no_forecast_for": []})
    pf["forecasts"] = {**pf.get("forecasts", {}), series: forecast}
    pf["no_forecast_for"] = [s for s in pf.get("no_forecast_for", []) if s != series]
    sow = merge_state_of_world(state, {"price_forecast": pf})

    summary: dict[str, Any] = {
        k: forecast.get(k) for k in
        ("series", "recommendation", "confidence", "direction",
         "pct_change_3m", "data_lag_months", "rationale")
    }
    return Command(update={
        "state_of_world": sow,
        "messages": [ToolMessage(content=str(summary), tool_call_id=tool_call_id)],
    })
