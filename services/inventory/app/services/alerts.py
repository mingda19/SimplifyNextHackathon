"""Inventory alert and stock-cover calculations."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Item, Lot
from app.schemas import AlertType, InventoryAlertResponse


EXPIRY_WINDOW_DAYS = 14
OVERSTOCKED_DAYS_COVER = 30


def calculate_days_cover(on_hand: int, avg_daily_draw: int) -> float | None:
    """Return projected days of stock, or ``None`` for a non-depleting item."""

    if avg_daily_draw == 0:
        return None
    return on_hand / avg_daily_draw


def list_inventory_alerts(
    db: Session,
    *,
    as_of: date | None = None,
) -> list[InventoryAlertResponse]:
    """Build deterministic expiry, reorder, and overstock alerts.

    The expiry window is inclusive at both ends: a positive-quantity lot is
    included from ``as_of`` through ``as_of + 14 days``. Already-expired and
    empty lots are deliberately excluded.
    """

    today = as_of if as_of is not None else datetime.now(timezone.utc).date()
    expiry_limit = today + timedelta(days=EXPIRY_WINDOW_DAYS)

    expiring_lots = db.scalars(
        select(Lot)
        .where(
            Lot.qty > 0,
            Lot.expiry_date >= today,
            Lot.expiry_date <= expiry_limit,
        )
        .order_by(Lot.expiry_date, Lot.sku, Lot.lot_id)
    ).all()
    items = db.scalars(select(Item).order_by(Item.sku)).all()

    alerts: list[InventoryAlertResponse] = [
        InventoryAlertResponse(
            type=AlertType.EXPIRING_SOON,
            sku=lot.sku,
            lot_id=lot.lot_id,
            expiry_date=lot.expiry_date,
            message=f"Lot {lot.lot_id} expires on {lot.expiry_date.isoformat()}.",
        )
        for lot in expiring_lots
    ]

    for item in items:
        days_cover = calculate_days_cover(item.on_hand, item.avg_daily_draw)

        if item.on_hand < item.reorder_point:
            alerts.append(
                InventoryAlertResponse(
                    type=AlertType.BELOW_REORDER,
                    sku=item.sku,
                    message=(
                        f"On-hand quantity {item.on_hand} is below reorder point "
                        f"{item.reorder_point}."
                    ),
                    days_cover=days_cover,
                )
            )

        if days_cover is not None and days_cover > OVERSTOCKED_DAYS_COVER:
            alerts.append(
                InventoryAlertResponse(
                    type=AlertType.OVERSTOCKED,
                    sku=item.sku,
                    message=f"Stock cover is {days_cover:g} days, above 30 days.",
                    days_cover=days_cover,
                )
            )

    return alerts


__all__ = [
    "EXPIRY_WINDOW_DAYS",
    "OVERSTOCKED_DAYS_COVER",
    "calculate_days_cover",
    "list_inventory_alerts",
]
