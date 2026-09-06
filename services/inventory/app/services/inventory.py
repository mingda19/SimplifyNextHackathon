"""Transactional inventory item and lot operations."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.errors import (
    DomainError,
    DomainErrorCode,
    LotExpiredError,
    NotFoundError,
    OutOfStockError,
)
from app.models import Item, Lot, Order, Vendor
from app.schemas import (
    AllocationRequest,
    AllocationResponse,
    ItemCreate,
    ItemDetailResponse,
    ItemResponse,
    ItemUpdate,
    LotResponse,
    ReceiptRequest,
    MAX_QUANTITY,
)
from app.services.alerts import calculate_days_cover
from app.services import idempotency


def _item_not_found(sku: str) -> NotFoundError:
    return NotFoundError(
        message=f"Inventory item {sku!r} was not found.",
        alternatives=[{"action": "list_inventory", "path": "/inventory"}],
    )


def _available_vendors(db: Session) -> list[dict[str, object]]:
    return [
        {"vendor_id": vendor.vendor_id, "name": vendor.name}
        for vendor in db.scalars(select(Vendor).order_by(Vendor.vendor_id)).all()
    ]


def _validate_preferred_vendor(db: Session, vendor_id: str | None) -> None:
    if vendor_id is None:
        return
    if db.get(Vendor, vendor_id) is None:
        alternatives = _available_vendors(db)
        if not alternatives:
            alternatives.append({"action": "omit_preferred_vendor_id"})
        raise NotFoundError(
            message=f"Preferred vendor {vendor_id!r} was not found.",
            remedy_hint="Use an existing vendor ID or omit preferred_vendor_id.",
            alternatives=alternatives,
        )


def _as_item_response(item: Item) -> ItemResponse:
    return ItemResponse.model_validate(item)


def list_items(
    db: Session,
    *,
    category: str | None = None,
    below_reorder: bool = False,
) -> list[ItemResponse]:
    """List items using the two filters in the frozen contract."""

    statement = select(Item)
    if category is not None:
        statement = statement.where(Item.category == category)
    if below_reorder:
        statement = statement.where(Item.on_hand < Item.reorder_point)
    statement = statement.order_by(Item.sku)

    return [_as_item_response(item) for item in db.scalars(statement).all()]


def get_item_detail(db: Session, sku: str) -> ItemDetailResponse:
    """Return one item with ordered lots and calculated days of cover."""

    item = db.scalar(
        select(Item).where(Item.sku == sku).options(selectinload(Item.lots))
    )
    if item is None:
        raise _item_not_found(sku)

    base = _as_item_response(item).model_dump()
    lots = [
        LotResponse.model_validate(lot)
        for lot in sorted(
            item.lots,
            key=lambda candidate: (candidate.expiry_date, candidate.lot_id),
        )
    ]
    return ItemDetailResponse(
        **base,
        lots=lots,
        days_cover=calculate_days_cover(item.on_hand, item.avg_daily_draw),
    )


def create_item(db: Session, payload: ItemCreate) -> ItemResponse:
    """Create and commit one inventory item."""

    if db.get(Item, payload.sku) is not None:
        raise DomainError(
            status_code=status.HTTP_409_CONFLICT,
            code=DomainErrorCode.CONFLICT,
            message=f"Inventory item {payload.sku!r} already exists.",
            remedy_hint="Choose a unique SKU or patch the existing item.",
            alternatives=[
                {"action": "update_item", "path": f"/inventory/{payload.sku}"}
            ],
        )

    _validate_preferred_vendor(db, payload.preferred_vendor_id)
    item = Item(**payload.model_dump(exclude={"opening_expiry_date", "opening_source"}))
    db.add(item)
    if payload.on_hand:
        db.add(Lot(lot_id=f"LOT-{uuid4().hex.upper()}", sku=payload.sku,
                   qty=payload.on_hand, expiry_date=payload.opening_expiry_date,
                   source=payload.opening_source.value,
                   received_at=datetime.now(timezone.utc)))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DomainError(
            status_code=status.HTTP_409_CONFLICT,
            code=DomainErrorCode.CONFLICT,
            message=f"Inventory item {payload.sku!r} could not be created.",
            remedy_hint="Check that the SKU is unique and referenced values exist.",
            alternatives=[{"action": "list_inventory", "path": "/inventory"}],
        ) from exc

    db.refresh(item)
    return _as_item_response(item)


def update_item(db: Session, sku: str, payload: ItemUpdate) -> ItemResponse:
    """Apply and commit a partial update without changing the item's SKU."""

    item = db.scalar(select(Item).where(Item.sku == sku).with_for_update())
    if item is None:
        raise _item_not_found(sku)

    changes = payload.changes()
    if "on_hand" in changes and changes["on_hand"] != item.on_hand:
        raise DomainError(status_code=422, code="VALIDATION_ERROR",
                          message="Stock changes must be recorded against a lot.",
                          remedy_hint="Use /receive for incoming stock or /allocate for outgoing stock.",
                          alternatives=[{"action": "receive", "path": f"/inventory/{sku}/receive"}])
    if "preferred_vendor_id" in changes:
        _validate_preferred_vendor(db, changes["preferred_vendor_id"])
    for field_name, value in changes.items():
        setattr(item, field_name, value)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DomainError(
            status_code=status.HTTP_409_CONFLICT,
            code=DomainErrorCode.CONFLICT,
            message=f"Inventory item {sku!r} could not be updated.",
            remedy_hint="Review the supplied values and retry the patch.",
            alternatives=[{"action": "get_item", "path": f"/inventory/{sku}"}],
        ) from exc

    db.refresh(item)
    return _as_item_response(item)


def delete_item(db: Session, sku: str) -> None:
    """Delete an item only when no lot or order history depends on it."""

    item = db.get(Item, sku)
    if item is None:
        raise _item_not_found(sku)

    lot_count = db.scalar(select(func.count()).select_from(Lot).where(Lot.sku == sku)) or 0
    order_count = (
        db.scalar(select(func.count()).select_from(Order).where(Order.sku == sku)) or 0
    )
    if lot_count or order_count:
        raise DomainError(
            status_code=status.HTTP_409_CONFLICT,
            code=DomainErrorCode.CONFLICT,
            message=f"Inventory item {sku!r} has dependent lot or order records.",
            remedy_hint="Retain the item so its inventory and order history remains valid.",
            alternatives=[
                {
                    "action": "retain_item",
                    "sku": sku,
                    "lot_count": lot_count,
                    "order_count": order_count,
                }
            ],
        )

    db.delete(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DomainError(
            status_code=status.HTTP_409_CONFLICT,
            code=DomainErrorCode.CONFLICT,
            message=f"Inventory item {sku!r} is still referenced.",
            remedy_hint="Retain the item until dependent records are no longer required.",
            alternatives=[{"action": "retain_item", "sku": sku}],
        ) from exc


def _live_lot_alternatives(
    db: Session,
    *,
    sku: str,
    as_of: date,
) -> list[dict[str, object]]:
    lots = db.scalars(
        select(Lot)
        .where(Lot.sku == sku, Lot.qty > 0, Lot.expiry_date >= as_of)
        .order_by(Lot.expiry_date, Lot.lot_id)
    ).all()
    alternatives: list[dict[str, object]] = [
        {
            "action": "allocate_lot",
            "lot_id": lot.lot_id,
            "available_qty": lot.qty,
            "expiry_date": lot.expiry_date.isoformat(),
        }
        for lot in lots
    ]
    if not alternatives:
        alternatives.append({"action": "replenish", "sku": sku})
    return alternatives


def allocate_lot(
    db: Session,
    *,
    sku: str,
    payload: AllocationRequest,
    as_of: date | None = None,
    validate_only: bool = False,
    idempotency_key: str | None = None,
) -> AllocationResponse:
    """Atomically allocate stock from one explicit, non-expired lot."""

    request = {"action": "allocate", "sku": sku, **payload.model_dump(mode="json")}
    if not validate_only:
        previous = idempotency.replay(db, idempotency_key, request)
        if previous is not None:
            return AllocationResponse.model_validate(previous)
    today = as_of if as_of is not None else datetime.now(timezone.utc).date()
    item = db.scalar(select(Item).where(Item.sku == sku).with_for_update())
    if item is None:
        raise _item_not_found(sku)

    lot = db.scalar(
        select(Lot)
        .where(Lot.lot_id == payload.lot_id, Lot.sku == sku)
        .with_for_update()
    )
    if lot is None:
        alternatives = _live_lot_alternatives(db, sku=sku, as_of=today)
        raise NotFoundError(
            message=f"Lot {payload.lot_id!r} was not found for SKU {sku!r}.",
            remedy_hint="Choose a listed live lot for this SKU.",
            alternatives=alternatives,
        )

    alternatives = _live_lot_alternatives(db, sku=sku, as_of=today)
    if lot.expiry_date < today:
        raise LotExpiredError(
            message=(
                f"Lot {lot.lot_id!r} expired on {lot.expiry_date.isoformat()} "
                "and cannot be allocated."
            ),
            alternatives=alternatives,
        )

    maximum_qty = min(lot.qty, item.on_hand)
    if payload.qty > maximum_qty:
        raise OutOfStockError(
            message=(
                f"Lot {lot.lot_id!r} cannot supply {payload.qty} units; "
                f"at most {maximum_qty} units are allocatable."
            ),
            remedy_hint="Reduce the quantity or choose another live lot.",
            alternatives=alternatives,
        )

    result = AllocationResponse(sku=sku, lot_id=lot.lot_id, qty=payload.qty)
    if validate_only:
        return result
    lot.qty -= payload.qty
    item.on_hand -= payload.qty
    idempotency.record(db, idempotency_key, request, result.model_dump(mode="json"))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DomainError(
            status_code=status.HTTP_409_CONFLICT,
            code=DomainErrorCode.CONFLICT,
            message="The allocation conflicted with another inventory change.",
            remedy_hint="Refresh the item and retry against the latest lot quantities.",
            alternatives=[{"action": "get_item", "path": f"/inventory/{sku}"}],
        ) from exc

    return result


def receive_stock(db: Session, *, sku: str, payload: ReceiptRequest,
                  idempotency_key: str | None = None) -> LotResponse:
    request = {"action": "receive", "sku": sku, **payload.model_dump(mode="json")}
    previous = idempotency.replay(db, idempotency_key, request)
    if previous is not None:
        return LotResponse.model_validate(previous)
    item = db.scalar(select(Item).where(Item.sku == sku).with_for_update())
    if item is None:
        raise _item_not_found(sku)
    if item.on_hand + payload.qty > MAX_QUANTITY:
        raise DomainError(status_code=422, code="VALIDATION_ERROR",
                          message="Receipt would exceed the maximum stock quantity.",
                          remedy_hint="Reduce the receipt quantity.")
    lot = Lot(lot_id=f"LOT-{uuid4().hex.upper()}", sku=sku, qty=payload.qty,
              expiry_date=payload.expiry_date, source=payload.source.value,
              received_at=datetime.now(timezone.utc))
    db.add(lot)
    item.on_hand += payload.qty
    result = LotResponse.model_validate(lot)
    idempotency.record(db, idempotency_key, request, result.model_dump(mode="json"))
    db.commit()
    return result


__all__ = [
    "allocate_lot",
    "create_item",
    "delete_item",
    "get_item_detail",
    "list_items",
    "update_item",
    "receive_stock",
]
