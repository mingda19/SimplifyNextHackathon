"""
Canned data for FAKE_SERVICES mode (workstreams 1/2/3 -- inventory, feedback,
price -- while those are being built or unavailable).

There is no FAKE_LLM canned response here any more: the agent node always
calls real Bedrock (see `config.py`, `llm.py`). This module only stands in
for the HTTP backends, gated by `FAKE_SERVICES`/`FAKE_INVENTORY`/etc.

The MOQ_NOT_MET -> read alternatives -> raise qty -> reprice -> switch
vendor beat these fixtures were built to demonstrate is still exercisable
live: VENDOR-HARVEST's `moq_units=250` vs VENDOR-COMMUNITY's
`volume_break_qty=250` below is what makes a real agent run discover the
switch is worth it, not a canned script.
"""
from __future__ import annotations

from typing import Any

# --------------------------------------------------------------------------
# Workstream 1 — inventory
# --------------------------------------------------------------------------
INVENTORY: list[dict[str, Any]] = [
    {"sku": "RICE-5KG", "name": "White rice 5kg", "category": "staples",
     "unit": "bag", "on_hand": 40, "reorder_point": 60, "avg_daily_draw": 5.0,
     "unit_cost_sgd": 2.10, "preferred_vendor_id": "VENDOR-HARVEST",
     "dspi_series": "Rice", "days_cover": 8.0},
    {"sku": "OIL-1L", "name": "Cooking oil 1L", "category": "staples",
     "unit": "bottle", "on_hand": 120, "reorder_point": 50, "avg_daily_draw": 3.0,
     "unit_cost_sgd": 3.40, "preferred_vendor_id": "VENDOR-COMMUNITY",
     "dspi_series": "Fixed Vegetable Fats & Oils", "days_cover": 40.0},
    {"sku": "CAN-SARDINE", "name": "Canned sardines", "category": "protein",
     "unit": "tin", "on_hand": 18, "reorder_point": 40, "avg_daily_draw": 2.0,
     "unit_cost_sgd": 1.85, "preferred_vendor_id": "VENDOR-HARVEST",
     "dspi_series": "Fish", "days_cover": 9.0},
]

ALERTS: dict[str, Any] = {
    "below_reorder": ["RICE-5KG", "CAN-SARDINE"],
    "expiring_soon": [
        {"sku": "OIL-1L", "lot_id": "LOT-8821", "qty": 30, "expiry_date": "2026-09-14",
         "days_left": 11, "source": "DONATED"},
    ],
    "overstocked": ["OIL-1L"],
}

VENDORS: dict[str, dict[str, Any]] = {
    "VENDOR-HARVEST": {"name": "Golden Grain Supplies", "moq_units": 250,
               "lead_time_days": 5, "reliability": 0.94, "base_price_sgd": 2.10},
    "VENDOR-COMMUNITY": {"name": "Harmony Food Distributors", "moq_units": 100,
               "lead_time_days": 3, "reliability": 0.88, "base_price_sgd": 2.35,
               # volume break at 250 — this is what makes the switch rational
               "volume_break_qty": 250, "volume_break_price_sgd": 1.98},
}

# --------------------------------------------------------------------------
# Workstream 2 — beneficiary feedback
# --------------------------------------------------------------------------
UNMET_NEEDS: dict[str, Any] = {
    "as_of": "2026-09-03",
    "ranked": [
        {"need": "rice ran out before month end", "frequency": 3, "urgency": 4,
         "score": 12, "mentioned_skus": ["RICE-5KG"]},
        {"need": "softer food for elderly who cannot chew", "frequency": 1,
         "urgency": 5, "score": 5, "mentioned_skus": [],
         "suggested_category": "soft_foods",
         "gap": True},   # no matching SKU — highest-signal output
    ],
}

# --------------------------------------------------------------------------
# Workstream 3 — price forecast
# --------------------------------------------------------------------------
# SENSE now asks for a forecast per at-risk commodity, so the fake mirrors that
# envelope: {"forecasts": {series: {...}}, "no_forecast_for": [...]}.
PRICE_FORECAST_ENVELOPE: dict[str, Any] = {
    "forecasts": {},          # filled at the bottom of this file
    "no_forecast_for": ["Vegetables, Fresh, Chilled, Frozen Or Simply Preserved"],
}

PRICE_FORECAST: dict[str, Any] = {
    "series": "Rice",
    "as_of": "2026-06",
    "data_lag_months": 3,
    "latest_index": 95.706,
    "pct_change_3m": 2.15,
    "pct_change_12m": 4.02,
    "direction": "rising",
    "seasonal_low_months": ["Jan", "Feb"],
    "recommendation": "BUY_NOW",
    "confidence": 0.71,
    "rationale": "Rising 4 consecutive months (+2.15%); no seasonal trough before Jan.",
}

PRICE_FORECAST_ENVELOPE["forecasts"]["Rice"] = PRICE_FORECAST
