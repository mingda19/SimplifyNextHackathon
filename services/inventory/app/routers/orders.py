"""Read-only view of placed purchase orders.

Added so the orchestrator's SENSE node can see what is ALREADY on the way.
Without it the agent re-proposes the same restock on every run: `on_hand` does
not move until goods physically arrive, so a SKU stays below its reorder point
for the whole lead time and looks unaddressed.

Read-only on purpose — orders are created through POST /vendor/{id}/order.
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Order

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
