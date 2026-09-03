"""Vendor quote validation and committing order operations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import (
    LeadTimeExceededError,
    MoqNotMetError,
    NotFoundError,
    OutOfStockError,
)
from app.models import Item, Order, OrderStatus, Vendor, VendorOffer
from app.schemas import (
    VendorOrderRequest,
    VendorOrderResponse,
    VendorQuoteRequest,
    VendorQuoteResponse,
)
from app.services.pricing import LocalPrice, calculate_local_price


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _load_request_context(
    db: Session,
    *,
    vendor_id: str,
    sku: str,
    lock_offer: bool,
) -> tuple[Vendor, Item, VendorOffer | None]:
    """Load public identifiers first, then the private vendor/SKU offer."""

    vendor = db.get(Vendor, vendor_id)
    if vendor is None:
        known_vendors = db.scalars(
            select(Vendor).order_by(Vendor.vendor_id).limit(5)
        ).all()
        raise NotFoundError(
            message=f"Vendor '{vendor_id}' was not found.",
            alternatives=[
                {"action": "choose_vendor", "vendor_id": candidate.vendor_id}
                for candidate in known_vendors
            ],
        )

    item = db.get(Item, sku)
    if item is None:
        known_items = db.scalars(select(Item).order_by(Item.sku).limit(5)).all()
        raise NotFoundError(
            message=f"Inventory item '{sku}' was not found.",
            alternatives=[
                {"action": "choose_sku", "sku": candidate.sku}
                for candidate in known_items
            ],
        )

    offer_statement = select(VendorOffer).where(
        VendorOffer.vendor_id == vendor_id,
        VendorOffer.sku == sku,
    )
    if lock_offer:
        offer_statement = offer_statement.with_for_update()
    offer = db.scalar(offer_statement)
    return vendor, item, offer


def _offers_for_sku(
    db: Session,
    *,
    sku: str,
    exclude_vendor_id: str,
) -> list[tuple[VendorOffer, Vendor]]:
    """Return deterministic alternative-offer rows ordered by vendor ID."""

    rows = db.execute(
        select(VendorOffer, Vendor)
        .join(Vendor, Vendor.vendor_id == VendorOffer.vendor_id)
        .where(
            VendorOffer.sku == sku,
            VendorOffer.vendor_id != exclude_vendor_id,
            VendorOffer.available_qty > 0,
        )
        .order_by(Vendor.vendor_id)
    ).all()
    return [(row[0], row[1]) for row in rows]


def _vendor_alternative(
    *,
    offer: VendorOffer,
    vendor: Vendor,
    requested_qty: int,
    item: Item,
) -> dict[str, object]:
    """Describe enough constraints and price information to adapt a request."""

    suggested_qty = max(requested_qty, vendor.moq_units)
    alternative: dict[str, object] = {
        "action": "choose_vendor",
        "vendor_id": vendor.vendor_id,
        "available_qty": offer.available_qty,
        "minimum_qty": vendor.moq_units,
        "lead_time_days": vendor.lead_time_days,
        "suggested_qty": suggested_qty,
    }
    if suggested_qty <= offer.available_qty:
        price = _price(item=item, offer=offer, qty=suggested_qty)
        alternative.update(
            unit_price_sgd=float(price.unit_price_sgd),
            total_price_sgd=float(price.total_price_sgd),
        )
    return alternative


def _stock_alternatives(
    db: Session,
    *,
    item: Item,
    vendor_id: str,
    requested_qty: int,
    selected_available_qty: int,
) -> list[dict[str, object]]:
    alternatives: list[dict[str, object]] = []
    if selected_available_qty > 0:
        alternatives.append(
            {
                "action": "reduce_quantity",
                "vendor_id": vendor_id,
                "max_qty": selected_available_qty,
            }
        )
    alternatives.extend(
        _vendor_alternative(
            offer=offer,
            vendor=vendor,
            requested_qty=requested_qty,
            item=item,
        )
        for offer, vendor in _offers_for_sku(
            db,
            sku=item.sku,
            exclude_vendor_id=vendor_id,
        )
    )
    if not alternatives:
        alternatives.append(
            {
                "action": "defer_order",
                "sku": item.sku,
                "reason": "no_stocked_vendor",
            }
        )
    return alternatives


def _moq_alternatives(
    db: Session,
    *,
    item: Item,
    offer: VendorOffer,
    vendor: Vendor,
    requested_qty: int,
) -> list[dict[str, object]]:
    alternatives: list[dict[str, object]] = []
    if offer.available_qty >= vendor.moq_units:
        raised_price = _price(item=item, offer=offer, qty=vendor.moq_units)
        alternatives.append(
            {
                "action": "raise_quantity",
                "vendor_id": vendor.vendor_id,
                "minimum_qty": vendor.moq_units,
                "unit_price_sgd": float(raised_price.unit_price_sgd),
                "total_price_sgd": float(raised_price.total_price_sgd),
            }
        )
    for candidate_offer, candidate_vendor in _offers_for_sku(
        db,
        sku=item.sku,
        exclude_vendor_id=vendor.vendor_id,
    ):
        if (
            candidate_vendor.moq_units <= requested_qty
            and candidate_offer.available_qty >= requested_qty
        ):
            alternatives.append(
                _vendor_alternative(
                    offer=candidate_offer,
                    vendor=candidate_vendor,
                    requested_qty=requested_qty,
                    item=item,
                )
            )
    if not alternatives:
        alternatives.append(
            {
                "action": "choose_vendor",
                "sku": item.sku,
                "maximum_moq": requested_qty,
            }
        )
    return alternatives


def _days_cover(item: Item) -> Decimal | None:
    if item.avg_daily_draw == 0:
        return None
    return Decimal(item.on_hand) / Decimal(item.avg_daily_draw)


def _lead_time_alternatives(
    db: Session,
    *,
    item: Item,
    vendor: Vendor,
    requested_qty: int,
    days_cover: Decimal,
) -> list[dict[str, object]]:
    alternatives: list[dict[str, object]] = []
    for candidate_offer, candidate_vendor in _offers_for_sku(
        db,
        sku=item.sku,
        exclude_vendor_id=vendor.vendor_id,
    ):
        if (
            candidate_vendor.moq_units <= requested_qty
            and candidate_offer.available_qty >= requested_qty
            and Decimal(candidate_vendor.lead_time_days) <= days_cover
        ):
            alternatives.append(
                _vendor_alternative(
                    offer=candidate_offer,
                    vendor=candidate_vendor,
                    requested_qty=requested_qty,
                    item=item,
                )
            )
    if not alternatives:
        alternatives.append(
            {
                "action": "revise_replenishment_plan",
                "maximum_lead_time_days": int(
                    days_cover.to_integral_value(rounding=ROUND_FLOOR)
                ),
            }
        )
    return alternatives


def _price(*, item: Item, offer: VendorOffer, qty: int) -> LocalPrice:
    """Keep the Workstream 3 replacement seam out of orchestration logic."""

    return calculate_local_price(
        unit_cost_sgd=Decimal(item.unit_cost_sgd),
        vendor_multiplier=Decimal(offer.price_multiplier),
        qty=qty,
        bulk_discount_threshold=offer.bulk_discount_threshold,
        bulk_discount_rate=Decimal(offer.bulk_discount_rate),
    )


def _validate_request(
    db: Session,
    *,
    vendor: Vendor,
    item: Item,
    offer: VendorOffer | None,
    qty: int,
) -> VendorOffer:
    """Validate stock, MOQ, then lead time in deterministic precedence order."""

    available_qty = 0 if offer is None else offer.available_qty
    if offer is None or available_qty < qty:
        raise OutOfStockError(
            message=(
                f"Vendor '{vendor.vendor_id}' has {available_qty} units of "
                f"'{item.sku}' available; {qty} were requested."
            ),
            alternatives=_stock_alternatives(
                db,
                item=item,
                vendor_id=vendor.vendor_id,
                requested_qty=qty,
                selected_available_qty=available_qty,
            ),
        )

    if qty < vendor.moq_units:
        raise MoqNotMetError(
            message=(
                f"Vendor '{vendor.vendor_id}' requires at least "
                f"{vendor.moq_units} units; {qty} were requested."
            ),
            alternatives=_moq_alternatives(
                db,
                item=item,
                offer=offer,
                vendor=vendor,
                requested_qty=qty,
            ),
        )

    days_cover = _days_cover(item)
    if days_cover is not None and Decimal(vendor.lead_time_days) > days_cover:
        raise LeadTimeExceededError(
            message=(
                f"Vendor '{vendor.vendor_id}' needs {vendor.lead_time_days} days, "
                f"but '{item.sku}' has {float(days_cover):g} days of stock cover."
            ),
            alternatives=_lead_time_alternatives(
                db,
                item=item,
                vendor=vendor,
                requested_qty=qty,
                days_cover=days_cover,
            ),
        )

    return offer


def get_vendor_quote(
    db: Session,
    *,
    vendor_id: str,
    payload: VendorQuoteRequest,
    now: datetime | None = None,
) -> VendorQuoteResponse:
    """Validate and return a quote without mutating persistent state."""

    vendor, item, offer = _load_request_context(
        db,
        vendor_id=vendor_id,
        sku=payload.sku,
        lock_offer=False,
    )
    valid_offer = _validate_request(
        db,
        vendor=vendor,
        item=item,
        offer=offer,
        qty=payload.qty,
    )
    quoted_at = now or _utc_now()
    price = _price(item=item, offer=valid_offer, qty=payload.qty)
    return VendorQuoteResponse(
        vendor_id=vendor.vendor_id,
        sku=item.sku,
        qty=payload.qty,
        available=True,
        unit_price_sgd=price.unit_price_sgd,
        total_price_sgd=price.total_price_sgd,
        expected_at=quoted_at + timedelta(days=vendor.lead_time_days),
    )


def place_vendor_order(
    db: Session,
    *,
    vendor_id: str,
    payload: VendorOrderRequest,
    now: datetime | None = None,
) -> VendorOrderResponse:
    """Revalidate, atomically reserve vendor stock, and commit a placed order."""

    vendor, item, offer = _load_request_context(
        db,
        vendor_id=vendor_id,
        sku=payload.sku,
        lock_offer=True,
    )
    valid_offer = _validate_request(
        db,
        vendor=vendor,
        item=item,
        offer=offer,
        qty=payload.qty,
    )
    placed_at = now or _utc_now()
    expected_at = placed_at + timedelta(days=vendor.lead_time_days)
    price = _price(item=item, offer=valid_offer, qty=payload.qty)

    order = Order(
        order_id=f"ORD-{uuid4().hex.upper()}",
        vendor_id=vendor.vendor_id,
        sku=item.sku,
        qty=payload.qty,
        status=OrderStatus.PLACED,
        unit_price_sgd=price.unit_price_sgd,
        placed_at=placed_at,
        expected_at=expected_at,
    )
    valid_offer.available_qty -= payload.qty
    db.add(order)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(order)

    return VendorOrderResponse(
        order_id=order.order_id,
        vendor_id=order.vendor_id,
        sku=order.sku,
        qty=order.qty,
        status=order.status.value,
        unit_price_sgd=order.unit_price_sgd,
        placed_at=order.placed_at,
        expected_at=order.expected_at,
    )


__all__ = ["get_vendor_quote", "place_vendor_order"]
