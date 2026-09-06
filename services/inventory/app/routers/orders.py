"""Read-only view of placed purchase orders.

Added so the orchestrator's SENSE node can see what is ALREADY on the way.
Without it the agent re-proposes the same restock on every run: `on_hand` does
not move until goods physically arrive, so a SKU stays below its reorder point
for the whole lead time and looks unaddressed.

Read-only on purpose — orders are created through POST /vendor/{id}/order.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Item, Lot, LotSource, Order

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("", summary="List purchase orders")
def list_orders(
    db: Annotated[Session, Depends(get_db)],
    status: Optional[str] = Query(None, description="PLACED | FULFILLED | CANCELLED"),
    sku: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
) -> list[dict]:
    stmt = select(Order).order_by(Order.placed_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Order.status == status.upper())
    if sku:
        stmt = stmt.where(Order.sku == sku)
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "order_id": o.order_id,
            "vendor_id": o.vendor_id,
            "sku": o.sku,
            "qty": o.qty,
            "status": getattr(o.status, "value", str(o.status)),
            "unit_price_sgd": float(o.unit_price_sgd),
            "total_sgd": round(float(o.unit_price_sgd) * o.qty, 2),
            "placed_at": o.placed_at.isoformat() if o.placed_at else None,
            "expected_at": o.expected_at.isoformat() if o.expected_at else None,
        }
        for o in rows
    ]


@router.get("/inbound", summary="Open quantity on the way, per SKU")
def inbound(db: Annotated[Session, Depends(get_db)]) -> dict[str, dict]:
    """`{sku: {qty_inbound, orders, earliest_expected}}` for PLACED orders."""
    rows = db.execute(
        select(Order).where(Order.status == "PLACED")
    ).scalars().all()
    out: dict[str, dict] = {}
    for o in rows:
        e = out.setdefault(o.sku, {"qty_inbound": 0, "orders": 0,
                                   "earliest_expected": None})
        e["qty_inbound"] += o.qty
        e["orders"] += 1
        exp = o.expected_at.isoformat() if o.expected_at else None
        if exp and (e["earliest_expected"] is None or exp < e["earliest_expected"]):
            e["earliest_expected"] = exp
    return out


@router.post("/{order_id}/receive", summary="Mark an order as arrived")
def receive_order(
    order_id: str,
    db: Annotated[Session, Depends(get_db)],
    payload: dict = Body(default={}),
) -> dict:
    """Book a delivered order into stock.

    Receiving creates a LOT rather than just bumping `on_hand`, because a lot
    carries its own expiry date — that is what makes FEFO allocation and the
    EXPIRING_SOON alerts work. Bumping the running total instead would put
    stock in the system with no expiry, and it would silently never appear in
    an expiry alert.

    Optional body: {"qty": <partial>, "expiry_date": "YYYY-MM-DD"}.
    """
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, {"code": "ORDER_NOT_FOUND",
                                  "message": f"No order {order_id}"})
    status = getattr(order.status, "value", str(order.status))
    if status != "PLACED":
        raise HTTPException(409, {"code": "ORDER_NOT_OPEN",
                                  "message": f"Order {order_id} is {status}, not PLACED"})

    qty = int(payload.get("qty") or order.qty)
    if qty <= 0 or qty > order.qty:
        raise HTTPException(400, {"code": "BAD_QTY",
                                  "message": f"qty must be 1..{order.qty}"})

    item = db.get(Item, order.sku)
    if item is None:
        raise HTTPException(404, {"code": "SKU_NOT_FOUND",
                                  "message": f"No item {order.sku}"})

    exp_raw = payload.get("expiry_date")
    expiry = (date.fromisoformat(exp_raw) if exp_raw
              else datetime.now(UTC).date() + timedelta(days=180))

    lot_id = f"LOT-{order.sku}-{order_id[-8:]}"
    if db.get(Lot, lot_id) is None:
        db.add(Lot(lot_id=lot_id, sku=order.sku, qty=qty, expiry_date=expiry,
                   received_at=datetime.now(UTC), source=LotSource.PURCHASED))
    item.on_hand += qty
    order.status = "FULFILLED"
    db.commit()

    return {"order_id": order_id, "sku": order.sku, "qty_received": qty,
            "lot_id": lot_id, "expiry_date": expiry.isoformat(),
            "on_hand": item.on_hand, "status": "FULFILLED"}


@router.post("/{order_id}/cancel", summary="Cancel an open order")
def cancel_order(order_id: str, db: Annotated[Session, Depends(get_db)]) -> dict:
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(404, {"code": "ORDER_NOT_FOUND", "message": "no such order"})
    status = getattr(order.status, "value", str(order.status))
    if status != "PLACED":
        raise HTTPException(409, {"code": "ORDER_NOT_OPEN",
                                  "message": f"Order is {status}"})
    order.status = "CANCELLED"
    db.commit()
    return {"order_id": order_id, "status": "CANCELLED"}
