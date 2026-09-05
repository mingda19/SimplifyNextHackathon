"""
Canned data for FAKE_LLM / FAKE_SERVICES mode.

These reproduce the scripted demo scenario in ../README.md exactly, so the whole
graph runs end to end for $0 while services 1/2/3 are still being built.

The load-bearing beat: the agent orders 200kg from the cheaper vendor, gets
400 MOQ_NOT_MET, reads `alternatives`, raises to the 250 MOQ, re-prices, and
discovers the second vendor is now cheaper — so it switches.
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

# --------------------------------------------------------------------------
# Canned LLM outputs
# --------------------------------------------------------------------------
FAKE_PLAN: dict[str, Any] = {
    "stockout_sku": "RICE-5KG",
    "days_until_failure": 8,
    "reasoning": (
        "RICE-5KG has 8 days of cover against a 10-day baseline, and three "
        "beneficiaries reported running out. Preferred vendor lead time is 5 days, "
        "so an order must be placed now. Rice prices are rising (+2.15% over 3 "
        "months) with no seasonal trough before January, so deferring costs more. "
        "A request for softer food maps to no existing SKU and needs a human."
    ),
    "steps": [
        {"action": "place_order", "sku": "RICE-5KG", "qty": 200,
         "vendor_id": "VENDOR-HARVEST",
         "rationale": "Cover 40 days at 5 bags/day from the cheaper preferred vendor."},
        {"action": "flag_for_human", "sku": "SOFT-FOOD-GAP", "qty": 0,
         "vendor_id": None,
         "rationale": "Repeated request for softer food matches no stocked SKU."},
    ],
}


def fake_adaptation(step: dict[str, Any], error: dict[str, Any]) -> dict[str, Any]:
    """
    Canned adaptation, keyed on the error code so each branch is exercisable
    without spending anything.
    """
    code = error.get("code", "")
    revised = dict(step)
    alts = error.get("alternatives") or []

    if code == "MOQ_NOT_MET":
        min_qty = next((a.get("minimum_qty") or a.get("min_qty") for a in alts if a.get("minimum_qty") or a.get("min_qty")), 250)
        cheaper = next((a for a in alts if a.get("vendor_id")
                        and a.get("unit_price_sgd", 99) < 2.10), None)
        revised["qty"] = min_qty
        what = f"Raised quantity from {step.get('qty')} to the {min_qty} minimum"
        if cheaper:
            revised["vendor_id"] = cheaper["vendor_id"]
            what += (f", and switched to {cheaper['vendor_id']} — at {min_qty} units its "
                     f"volume price (S${cheaper['unit_price_sgd']:.2f}) undercuts "
                     f"{step.get('vendor_id')}")
        return {"revised_step": revised, "what_changed": what, "confidence": 0.86}

    if code == "OUT_OF_STOCK":
        alt = next((a for a in alts if a.get("vendor_id")), None)
        if alt:
            revised["vendor_id"] = alt["vendor_id"]
        return {"revised_step": revised,
                "what_changed": f"Preferred vendor is out of stock; fell back to "
                                f"{revised.get('vendor_id')}.",
                "confidence": 0.78}

    if code == "LEAD_TIME_EXCEEDED":
        alt = next((a for a in alts if a.get("lead_time_days")), None)
        if alt:
            revised["vendor_id"] = alt["vendor_id"]
        return {"revised_step": revised,
                "what_changed": "Lead time landed after the stockout date; switched to "
                                "a faster vendor.",
                "confidence": 0.72}

    if code == "LOT_EXPIRED":
        revised["action"] = "reallocate_lot"
        return {"revised_step": revised,
                "what_changed": "Target lot has expired; reallocating from a live lot.",
                "confidence": 0.80}

    return {"revised_step": revised,
            "what_changed": f"Unrecognised error {code!r}; retrying unchanged.",
            "confidence": 0.30}
