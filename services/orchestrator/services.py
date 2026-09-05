"""
Clients for workstreams 1/2/3, plus the fake backend that stands in until they
ship.

Every reader degrades instead of raising: a teammate's service WILL be down at
some point on 5 Sep, and the graph must keep reasoning without it.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from . import fixtures
from .config import settings

log = logging.getLogger(__name__)


class ServiceError(Exception):
    """Transport-level failure. Callers degrade; they do not crash."""


def _get(base: str, path: str) -> Any:
    url = f"{base.rstrip('/')}{path}"
    try:
        with httpx.Client(timeout=settings.http_timeout) as c:
            r = c.get(url)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as exc:
        raise ServiceError(f"GET {url} failed: {type(exc).__name__}: {exc}") from exc


# ---------------------------------------------------------------- readers ---
def get_inventory() -> list[dict[str, Any]]:
    if settings.fake_inventory:
        return fixtures.INVENTORY
    return _get(settings.inventory_url, "/inventory")


def _normalise_alerts(raw: Any) -> dict[str, Any]:
    """
    Adapt workstream 1's alert feed to the shape the approval summary reads.

    G's service returns a FLAT LIST of {type, sku, message, lot_id,
    expiry_date, days_cover}; the orchestrator groups by type. Keeping the
    adapter here means one service owning the translation instead of every
    consumer re-deriving it.
    """
    if isinstance(raw, dict):
        return raw                      # already grouped (fixtures)
    grouped: dict[str, Any] = {"below_reorder": [], "expiring_soon": [],
                               "overstocked": [], "other": []}
    for a in raw or []:
        kind = str(a.get("type", "")).upper()
        if kind in {"BELOW_REORDER", "LOW_STOCK", "REORDER"}:
            grouped["below_reorder"].append(a.get("sku"))
        elif kind in {"EXPIRING_SOON", "EXPIRED"}:
            grouped["expiring_soon"].append(a)
        elif kind in {"OVERSTOCKED", "OVERSTOCK"}:
            grouped["overstocked"].append(a.get("sku"))
        else:
            grouped["other"].append(a)
    return grouped


def get_alerts() -> dict[str, Any]:
    if settings.fake_inventory:
        return fixtures.ALERTS
    return _normalise_alerts(_get(settings.inventory_url, "/inventory/alerts"))


def get_unmet_needs() -> dict[str, Any]:
    if settings.fake_feedback:
        return fixtures.UNMET_NEEDS
    return _get(settings.feedback_url, "/feedback/unmet-needs")


def get_price_forecast(series: str = "Rice") -> dict[str, Any]:
    if settings.fake_pricing:
        return fixtures.PRICE_FORECAST
    return _get(settings.pricing_url,
                f"/price/forecast?series={series}&horizon_months=3")


# ---------------------------------------------------------------- writers ---
def _fake_quote(vendor_id: str, sku: str, qty: int) -> dict[str, Any]:
    """Deterministic pricing with a volume break, so a retry genuinely re-prices."""
    v = fixtures.VENDORS[vendor_id]
    price = v["base_price_sgd"]
    if v.get("volume_break_qty") and qty >= v["volume_break_qty"]:
        price = v["volume_break_price_sgd"]
    return {"vendor_id": vendor_id, "sku": sku, "qty": qty,
            "unit_price_sgd": price, "total_sgd": round(price * qty, 2),
            "lead_time_days": v["lead_time_days"]}


def _fake_vendor_call(vendor_id: str, sku: str, qty: int) -> dict[str, Any]:
    """
    Stands in for W and G's endpoints, including the error bodies.

    Deterministic on the request alone — no hidden state — so the demo is
    reproducible and the same call always yields the same outcome.
    """
    v = fixtures.VENDORS.get(vendor_id)
    if v is None:
        raise VendorError(404, "UNKNOWN_VENDOR", f"No vendor {vendor_id}", [])

    if qty < v["moq_units"]:
        # The `alternatives` array is what lets the agent adapt intelligently
        # instead of guessing. W and G must guarantee this field.
        alts: list[dict[str, Any]] = [{"minimum_qty": v["moq_units"]}]
        for other_id, other in fixtures.VENDORS.items():
            if other_id == vendor_id:
                continue
            q = _fake_quote(other_id, sku, v["moq_units"])
            alts.append({"vendor_id": other_id,
                         "unit_price_sgd": q["unit_price_sgd"],
                         "lead_time_days": q["lead_time_days"],
                         "moq_units": other["moq_units"]})
        raise VendorError(
            400, "MOQ_NOT_MET",
            f"Order of {qty} is below {vendor_id}'s minimum of {v['moq_units']}.",
            alts, remedy_hint="Raise the quantity, or split across vendors.")

    return {"status": "STAGED", **_fake_quote(vendor_id, sku, qty)}


class VendorError(Exception):
    """A 4xx from the vendor API, carrying the structured body `adapt` needs."""

    def __init__(self, status: int, code: str, message: str,
                 alternatives: list[dict[str, Any]],
                 remedy_hint: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = {"code": code, "message": message,
                     "remedy_hint": remedy_hint, "alternatives": alternatives}


def vendor_order(vendor_id: str, sku: str, qty: int) -> dict[str, Any]:
    """Stage an order. Raises VendorError on a 4xx."""
    if settings.fake_inventory:
        return _fake_vendor_call(vendor_id, sku, qty)

    url = f"{settings.inventory_url.rstrip('/')}/vendor/{vendor_id}/order"
    try:
        with httpx.Client(timeout=settings.http_timeout) as c:
            r = c.post(url, json={"sku": sku, "qty": qty})
    except httpx.HTTPError as exc:
        # A transport failure is not a vendor decision. Surface it as a
        # ServiceError so `act` routes to `adapt` instead of the graph dying.
        raise ServiceError(f"POST {url} failed: {type(exc).__name__}: {exc}") from exc
    if r.is_success:
        return r.json()
    if 400 <= r.status_code < 500:
        try:
            b = r.json()
        except ValueError:
            b = {}
        raise VendorError(r.status_code, b.get("code", "UNKNOWN"),
                          b.get("message", r.text),
                          b.get("alternatives", []), b.get("remedy_hint", ""))
    raise ServiceError(f"vendor {vendor_id} returned {r.status_code}")
