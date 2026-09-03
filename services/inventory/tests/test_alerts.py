"""Boundary tests for inventory alert rules."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Item, Lot, LotSource
from app.schemas import AlertType
from app.services.alerts import calculate_days_cover, list_inventory_alerts


def _item(
    sku: str,
    *,
    on_hand: int,
    reorder_point: int,
    avg_daily_draw: int,
) -> Item:
    return Item(
        sku=sku,
        name=f"Item {sku}",
        category="Test",
        unit="unit",
        on_hand=on_hand,
        reorder_point=reorder_point,
        avg_daily_draw=avg_daily_draw,
        unit_cost_sgd=Decimal("1.00"),
    )


def test_days_cover_zero_draw_is_null() -> None:
    assert calculate_days_cover(100, 0) is None
    assert calculate_days_cover(24, 3) == 8.0


def test_all_alert_boundaries_are_frozen() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    as_of = date(2026, 9, 3)
    now = datetime(2026, 9, 3, 12, tzinfo=timezone.utc)

    with Session(engine) as db:
        db.add_all(
            [
                _item("BELOW", on_hand=9, reorder_point=10, avg_daily_draw=3),
                _item("EQUAL", on_hand=10, reorder_point=10, avg_daily_draw=1),
                _item("OVER", on_hand=301, reorder_point=1, avg_daily_draw=10),
                _item("THIRTY", on_hand=300, reorder_point=1, avg_daily_draw=10),
                _item("ZERO-DRAW", on_hand=999, reorder_point=1, avg_daily_draw=0),
            ]
        )
        db.add_all(
            [
                Lot(
                    lot_id="EXPIRED",
                    sku="BELOW",
                    qty=1,
                    expiry_date=as_of - timedelta(days=1),
                    received_at=now,
                    source=LotSource.DONATED,
                ),
                Lot(
                    lot_id="TODAY",
                    sku="BELOW",
                    qty=1,
                    expiry_date=as_of,
                    received_at=now,
                    source=LotSource.DONATED,
                ),
                Lot(
                    lot_id="DAY-14",
                    sku="EQUAL",
                    qty=1,
                    expiry_date=as_of + timedelta(days=14),
                    received_at=now,
                    source=LotSource.PURCHASED,
                ),
                Lot(
                    lot_id="DAY-15",
                    sku="EQUAL",
                    qty=1,
                    expiry_date=as_of + timedelta(days=15),
                    received_at=now,
                    source=LotSource.PURCHASED,
                ),
                Lot(
                    lot_id="EMPTY",
                    sku="EQUAL",
                    qty=0,
                    expiry_date=as_of + timedelta(days=2),
                    received_at=now,
                    source=LotSource.PURCHASED,
                ),
            ]
        )
        db.commit()

        alerts = list_inventory_alerts(db, as_of=as_of)

    by_type = {
        alert_type: [alert for alert in alerts if alert.type == alert_type]
        for alert_type in AlertType
    }
    assert [alert.lot_id for alert in by_type[AlertType.EXPIRING_SOON]] == [
        "TODAY",
        "DAY-14",
    ]
    assert [alert.sku for alert in by_type[AlertType.BELOW_REORDER]] == ["BELOW"]
    assert by_type[AlertType.BELOW_REORDER][0].days_cover == 3.0
    assert [alert.sku for alert in by_type[AlertType.OVERSTOCKED]] == ["OVER"]
    assert by_type[AlertType.OVERSTOCKED][0].days_cover == 30.1
    assert all(alert.sku != "ZERO-DRAW" for alert in by_type[AlertType.OVERSTOCKED])

    engine.dispose()
