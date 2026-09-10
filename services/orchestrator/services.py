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
from pantry_common.security import service_headers

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


def count_feedback() -> int:
    """Total feedback row count -- used by watch mode to detect "10+ new
    messages poured in" without pulling the whole table every poll."""
    if settings.fake_feedback:
        return len((fixtures.UNMET_NEEDS.get("ranked") or []))
    return _get(settings.feedback_url, "/feedback/count")["count"]


def get_inbound_orders() -> dict[str, Any]:
    """Open purchase orders per SKU — what is already on the way.

    `on_hand` does not move until goods physically arrive, so without this a
    SKU sits below its reorder point for the whole lead time and the agent
    re-proposes the same restock on every run.
    """
    if settings.fake_inventory:
        return {}
    return _get(settings.inventory_url, "/orders/inbound")


def resolve_feedback(skus: list[str], run_id: str, note: str = "") -> dict[str, Any]:
    """Close the feedback rows an approved order actually addresses."""
    if settings.fake_feedback or not skus:
        return {"resolved": 0}
    url = f"{settings.feedback_url.rstrip('/')}/feedback/resolve"
    try:
        with httpx.Client(timeout=settings.http_timeout) as c:
            r = c.post(url, json={"skus": skus, "run_id": run_id, "note": note},
                      headers=service_headers())
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as exc:
        log.warning("could not resolve feedback: %s", exc)
        return {"resolved": 0, "error": str(exc)}


def extract_pending_feedback(limit: int = 50) -> dict[str, Any]:
    """Sweep up feedback rows still `pending`/`failed` before reading needs.

    `POST /feedback` queues extraction in the background by default now (fast
    response for the beneficiary) rather than blocking on it, so a message
    posted moments ago may not be extracted yet by the time the agent looks.
    Calling this first is what makes `feedback_extraction`'s read fresh
    without making the beneficiary wait on Bedrock at submission time.
    """
    if settings.fake_feedback:
        return {"attempted": 0, "done": 0, "failed": 0}
    url = f"{settings.feedback_url.rstrip('/')}/feedback/extract-pending"
    try:
        with httpx.Client(timeout=settings.http_timeout * 4) as c:
            r = c.post(url, params={"limit": limit}, headers=service_headers())
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError as exc:
        log.warning("could not sweep pending feedback: %s", exc)
        return {"attempted": 0, "done": 0, "failed": 0, "error": str(exc)}


def get_price_forecasts(series_names: list[str]) -> dict[str, Any]:
    """Forecast every series the at-risk SKUs actually map to.

    `sense` used to request a single hardcoded "Rice", so the agent timed every
    purchase against the rice curve no matter what was low. This asks for the
    commodities that are genuinely at risk this run.

    A series with no forecast is not an error: perishables were deliberately
    excluded from the price model (you cannot stockpile fresh vegetables, so a
    forecast on them is not actionable). Those come back as `unavailable`.
    """
    if settings.fake_pricing:
        return fixtures.PRICE_FORECAST_ENVELOPE
    out: dict[str, Any] = {}
    unavailable: list[str] = []
    for name in series_names:
        try:
            out[name] = get_price_forecast(name)
        except Exception:                              # noqa: BLE001
            unavailable.append(name)
    return {"forecasts": out, "no_forecast_for": unavailable}


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


def vendor_quote(vendor_id: str, sku: str, qty: int) -> dict[str, Any]:
    """Price a line WITHOUT committing it.

    ACT used to call /vendor/{id}/order to "stage" a step — but that endpoint
    really places the order. Every line was therefore committed before the human
    saw the plan, which made the approval gate cosmetic: declining a line left
    the order standing in the database.

    /quote returns the same error codes and the same `alternatives` payload the
    adapt loop reasons over, and creates nothing. Planning happens here; money
    is spent only in COMMIT, and only for approved steps.
    """
    if settings.fake_inventory:
        return _fake_vendor_call(vendor_id, sku, qty)

    url = f"{settings.inventory_url.rstrip('/')}/vendor/{vendor_id}/quote"
    try:
        with httpx.Client(timeout=settings.http_timeout) as c:
            r = c.post(url, json={"sku": sku, "qty": qty}, headers=service_headers())
    except httpx.HTTPError as exc:
        raise ServiceError(f"POST {url} failed: {type(exc).__name__}: {exc}") from exc

    body: dict[str, Any] = {}
    try:
        body = r.json()
    except ValueError:
        pass
    # This service reports domain refusals in the body with a `code`, whether or
    # not the HTTP status is an error — treat either as a VendorError.
    if body.get("code") or (400 <= r.status_code < 500):
        raise VendorError(r.status_code, body.get("code", "UNKNOWN"),
                          body.get("message", r.text),
                          body.get("alternatives", []), body.get("remedy_hint", ""))
    if not r.is_success:
        raise ServiceError(f"quote {vendor_id} returned {r.status_code}")
    return {"status": "QUOTED", **body}


def allocate_lot(sku: str, lot_id: str, qty: int, *, validate_only: bool = True) -> dict[str, Any]:
    """Allocate from a specific lot WITHOUT committing it, by default.

    Was previously called from `act.py` but never implemented in this module
    -- any `reallocate_lot` PlanStep that reached execution would have raised
    a bare `AttributeError` (uncaught anywhere, unlike `VendorError`/
    `ServiceError`) and crashed the graph outright. Workstream 1's inventory
    service does have the endpoint this always should have called:
    `POST /{sku}/allocate/validate` for a non-committing check (mirrors
    `vendor_quote` vs `vendor_order` exactly), `POST /{sku}/allocate` to
    actually commit. `action_generator` must only ever call this with
    `validate_only=True` -- committing a real allocation, like a real order,
    happens in `finalize` after human approval, never mid-loop.
    """
    if settings.fake_inventory:
        # No lot fixtures exist (fixtures.py has no per-lot data) -- a plain
        # deterministic ack is enough for graph-mechanics testing, matching
        # AllocationResponse's real shape.
        return {"sku": sku, "lot_id": lot_id, "qty": qty}

    suffix = "/allocate/validate" if validate_only else "/allocate"
    url = f"{settings.inventory_url.rstrip('/')}/inventory/{sku}{suffix}"
    try:
        with httpx.Client(timeout=settings.http_timeout) as c:
            r = c.post(url, json={"lot_id": lot_id, "qty": qty}, headers=service_headers())
    except httpx.HTTPError as exc:
        raise ServiceError(f"POST {url} failed: {type(exc).__name__}: {exc}") from exc

    body: dict[str, Any] = {}
    try:
        body = r.json()
    except ValueError:
        pass
    if body.get("code") or (400 <= r.status_code < 500):
        raise VendorError(r.status_code, body.get("code", "UNKNOWN"),
                          body.get("message", r.text),
                          body.get("alternatives", []), body.get("remedy_hint", ""))
    if not r.is_success:
        raise ServiceError(f"allocate {sku}/{lot_id} returned {r.status_code}")
    return body


def vendor_order(vendor_id: str, sku: str, qty: int) -> dict[str, Any]:
    """COMMIT an order. Real money. Only COMMIT calls this."""
    if settings.fake_inventory:
        return _fake_vendor_call(vendor_id, sku, qty)

    url = f"{settings.inventory_url.rstrip('/')}/vendor/{vendor_id}/order"
    try:
        with httpx.Client(timeout=settings.http_timeout) as c:
            r = c.post(url, json={"sku": sku, "qty": qty}, headers=service_headers())
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
