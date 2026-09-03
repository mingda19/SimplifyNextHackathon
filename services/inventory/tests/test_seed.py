"""Deterministic seed-data checks."""

from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models import Base, Item, Lot, LotSource, Vendor, VendorOffer
from app.seed import seed_database
from app.seed_data import (
    EXPIRED_LOT_ID,
    LIVE_LOT_ID,
    PREFERRED_VENDOR_ID,
    RICE_SKU,
    SECONDARY_VENDOR_ID,
)


def test_seed_counts_demo_invariants_and_restart_safety() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    anchor = date(2026, 9, 3)

    with Session(engine) as db:
        summary = seed_database(db, reset=True, today=anchor)

        assert summary.items == 40
        assert summary.lots == 80
        assert summary.vendors == 4
        assert summary.vendor_offers == 160
        assert db.scalar(select(func.count()).select_from(Item)) == 40
        assert db.scalar(select(func.count()).select_from(Lot)) == 80
        assert db.scalar(select(func.count()).select_from(Vendor)) == 4
        assert db.scalar(select(func.count()).select_from(VendorOffer)) == 160

        rice = db.get(Item, RICE_SKU)
        preferred = db.get(Vendor, PREFERRED_VENDOR_ID)
        secondary_offer = db.get(VendorOffer, (SECONDARY_VENDOR_ID, RICE_SKU))
        assert rice is not None and rice.on_hand / rice.avg_daily_draw == 8
        assert rice.dspi_series == "Rice"
        assert preferred is not None
        assert preferred.moq_units == 250
        assert preferred.lead_time_days == 5
        assert secondary_offer is not None
        assert secondary_offer.bulk_discount_threshold == 250

        sources = set(db.scalars(select(Lot.source)).all())
        assert sources == {LotSource.PURCHASED, LotSource.DONATED}
        assert db.get(Lot, EXPIRED_LOT_ID).expiry_date == date(2026, 9, 2)
        assert db.get(Lot, LIVE_LOT_ID).expiry_date > anchor

        for item in db.scalars(select(Item)).all():
            usable_lot_qty = db.scalar(
                select(func.coalesce(func.sum(Lot.qty), 0)).where(
                    Lot.sku == item.sku,
                    Lot.expiry_date >= anchor,
                )
            )
            assert item.on_hand == usable_lot_qty

        # Ordinary startup seeding must not undo a placed order reservation or
        # allocation. An explicit --reset remains available for demo resets.
        rice.on_hand = 199
        secondary_offer.available_qty = 1234
        db.commit()
        seed_database(db, today=date(2026, 9, 4))

        assert db.get(Item, RICE_SKU).on_hand == 199
        assert db.get(VendorOffer, (SECONDARY_VENDOR_ID, RICE_SKU)).available_qty == 1234
        assert db.scalar(select(func.count()).select_from(Item)) == 40

    engine.dispose()
