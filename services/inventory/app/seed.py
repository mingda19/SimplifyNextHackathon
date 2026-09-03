"""Idempotent database seeding for the Inventory Service."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Item, Lot, Order, Vendor, VendorOffer
from app.seed_data import (
    ITEM_SEEDS,
    VENDOR_OFFER_SEEDS,
    VENDOR_SEEDS,
    build_lot_seeds,
    utc_today,
)


@dataclass(frozen=True, slots=True)
class SeedSummary:
    vendors: int
    items: int
    lots: int
    vendor_offers: int
    reset: bool
    anchor_date: date


def _insert_if_missing(
    session: Session,
    model: type[Any],
    identity: str | tuple[str, str],
    values: dict[str, Any],
) -> None:
    """Insert a fixture without overwriting operational changes on restart."""

    instance = session.get(model, identity)
    if instance is None:
        session.add(model(**values))


def _reset_all_data(session: Session) -> None:
    """Clear operational tables only after an explicit ``--reset`` request."""

    # Delete in foreign-key order.  A reset intentionally includes non-fixture
    # rows; normal seeding never deletes user-created inventory or orders.
    session.execute(delete(Order))
    session.execute(delete(VendorOffer))
    session.execute(delete(Lot))
    session.execute(delete(Item))
    session.execute(delete(Vendor))
    session.flush()


def seed_database(
    session: Session,
    *,
    reset: bool = False,
    today: date | None = None,
) -> SeedSummary:
    """Insert missing stable fixtures and commit them as one transaction.

    Re-running this function does not duplicate rows or overwrite allocations,
    vendor reservations, or user edits. Rows outside the fixture set are also
    preserved unless ``reset=True``.
    """

    anchor = today or utc_today()
    lots = build_lot_seeds(anchor)

    try:
        if reset:
            _reset_all_data(session)

        for vendor in VENDOR_SEEDS:
            values = asdict(vendor)
            _insert_if_missing(session, Vendor, vendor.vendor_id, values)
        session.flush()

        for item in ITEM_SEEDS:
            values = asdict(item)
            _insert_if_missing(session, Item, item.sku, values)
        session.flush()

        for lot in lots:
            values = asdict(lot)
            _insert_if_missing(session, Lot, lot.lot_id, values)
        session.flush()

        for offer in VENDOR_OFFER_SEEDS:
            values = asdict(offer)
            identity = (offer.vendor_id, offer.sku)
            _insert_if_missing(session, VendorOffer, identity, values)

        session.commit()
    except Exception:
        session.rollback()
        raise

    return SeedSummary(
        vendors=len(VENDOR_SEEDS),
        items=len(ITEM_SEEDS),
        lots=len(lots),
        vendor_offers=len(VENDOR_OFFER_SEEDS),
        reset=reset,
        anchor_date=anchor,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed Inventory Service demo data.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="delete all current inventory/order data before inserting fixtures",
    )
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        metavar="YYYY-MM-DD",
        help="override the UTC anchor date (intended for deterministic tests)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    with SessionLocal() as session:
        summary = seed_database(session, reset=args.reset, today=args.today)

    print(
        "Seeded "
        f"{summary.vendors} vendors, {summary.items} items, "
        f"{summary.lots} lots, and {summary.vendor_offers} vendor offers "
        f"(anchor date {summary.anchor_date.isoformat()}, reset={summary.reset})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["SeedSummary", "main", "seed_database"]
