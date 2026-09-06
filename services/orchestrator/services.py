"""
Clients for workstreams 1/2/3, plus the fake backend that stands in until they
ship.

Every reader degrades instead of raising: a teammate's service WILL be down at
some point on 5 Sep, and the graph must keep reasoning without it.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
from urllib.parse import quote

from pantry_common.security import service_headers
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
            r = c.get(url, headers=service_headers())
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
                f"/price/forecast?series={quote(series)}&horizon_months=3")


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
                 remedy_hint: str = "", retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after_seconds = retry_after_seconds
        self.body = {"code": code, "message": message,
                     "remedy_hint": remedy_hint, "alternatives": alternatives}
        if retry_after_seconds is not None:
            self.body["retry_after_seconds"] = retry_after_seconds



def total_sgd(result: dict) -> Decimal:
    """Normalize WS1 quotes and orders without a silent zero fallback."""
    value = result.get("total_price_sgd", result.get("total_sgd"))
    if value is None:
        value = Decimal(str(result["qty"])) * Decimal(str(result["unit_price_sgd"]))
    total = Decimal(str(value)).quantize(Decimal("0.01"))
    if not total.is_finite() or total < 0:
        raise ValueError("invalid order total")
    return total


def _retry_after(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        try:
            seconds = (parsedate_to_datetime(raw) - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    import math
    return max(0, seconds) if math.isfinite(seconds) else None


def _post(path: str, body: dict, key: str | None = None) -> dict:
    url = f"{settings.inventory_url.rstrip('/')}{path}"
    headers = service_headers()
    if key:
        headers["Idempotency-Key"] = key
    # Quotes/validation are read-only. Committing calls are retried only with
    # the same durable idempotency key, including after ambiguous timeouts.
    retries = 3 if key or path.endswith(("/quote", "/validate")) else 1
    for attempt in range(retries):
        try:
            with httpx.Client(timeout=settings.http_timeout) as c:
                r = c.post(url, json=body, headers=headers)
            if r.is_success:
                try:
                    result = r.json()
                    if not isinstance(result, dict):
                        raise ValueError("expected an object")
                    return result
                except ValueError as exc:
                    raise ServiceError("inventory returned an invalid response") from exc
            if 400 <= r.status_code < 500:
                try:
                    b = r.json()
                except ValueError:
                    b = {}
                if not isinstance(b, dict):
                    b = {}
                raise VendorError(r.status_code, b.get("code", "UNKNOWN"),
                                  b.get("message", r.text), b.get("alternatives", []),
                                  b.get("remedy_hint", ""), _retry_after(r.headers.get("Retry-After")))
            failure = f"inventory returned {r.status_code}"
        except httpx.HTTPError as exc:
            failure = f"{type(exc).__name__}: {exc}"
        if attempt + 1 < retries:
            time.sleep(0.25 * 2**attempt)
    raise ServiceError(f"POST {url} failed: {failure}")


def vendor_quote(vendor_id: str, sku: str, qty: int) -> dict[str, Any]:
    if settings.fake_inventory:
        return _fake_vendor_call(vendor_id, sku, qty)
    result = _post(f"/vendor/{quote(vendor_id, safe='')}/quote", {"sku": sku, "qty": qty})
    return {**result, "total_sgd": float(total_sgd(result))}


def vendor_order(vendor_id: str, sku: str, qty: int, *,
                 idempotency_key: str | None = None,
                 expected_unit_price_sgd: float | None = None) -> dict[str, Any]:
    """Commit an approved order. Never call this during staging."""
    if settings.fake_inventory:
        return {**_fake_vendor_call(vendor_id, sku, qty), "status": "PLACED",
                "order_id": f"FAKE-{idempotency_key}"}
    body = {"sku": sku, "qty": qty}
    if expected_unit_price_sgd is not None:
        body["expected_unit_price_sgd"] = expected_unit_price_sgd
    result = _post(f"/vendor/{quote(vendor_id, safe='')}/order", body, idempotency_key)
    return {**result, "total_sgd": float(total_sgd(result))}


def allocate_lot(sku: str, lot_id: str, qty: int, *, validate_only: bool = False,
                 idempotency_key: str | None = None) -> dict[str, Any]:
    if settings.fake_inventory:
        return {"sku": sku, "lot_id": lot_id, "qty": qty}
    suffix = "/validate" if validate_only else ""
    return _post(f"/inventory/{quote(sku, safe='')}/allocate{suffix}",
                 {"lot_id": lot_id, "qty": qty}, idempotency_key)
