"""API tests for inventory CRUD, details, and lot allocation."""

from __future__ import annotations

from collections.abc import Generator
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.errors import install_error_handlers
from app.models import Base, Item, Lot, LotSource, Vendor
from app.routers.inventory import router


@pytest.fixture
def inventory_api() -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:  # type: ignore[no-untyped-def]
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    app = FastAPI()
    install_error_handlers(app)
    app.include_router(router)

    def override_db() -> Generator[Session, None, None]:
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client, session_factory

    Base.metadata.drop_all(engine)
    engine.dispose()


def _item_payload(sku: str, *, category: str = "Staples", on_hand: int = 20) -> dict:
    return {
        "sku": sku,
        "name": f"Item {sku}",
        "category": category,
        "unit": "pack",
        "on_hand": on_hand,
        "reorder_point": 10,
        "avg_daily_draw": 2,
        "unit_cost_sgd": 3.25,
        "preferred_vendor_id": None,
        "dspi_series": "Demo Series",
    }


def test_crud_filters_and_detail_contract(inventory_api) -> None:  # type: ignore[no-untyped-def]
    client, _session_factory = inventory_api

    created = client.post("/inventory", json=_item_payload("SKU-B", on_hand=8))
    assert created.status_code == 201
    assert created.json()["sku"] == "SKU-B"
    assert "lots" not in created.json()
    assert "days_cover" not in created.json()

    assert client.post(
        "/inventory", json=_item_payload("SKU-A", category="Hygiene", on_hand=40)
    ).status_code == 201

    all_items = client.get("/inventory")
    assert all_items.status_code == 200
    assert [item["sku"] for item in all_items.json()] == ["SKU-A", "SKU-B"]

    category_items = client.get("/inventory", params={"category": "Hygiene"})
    assert [item["sku"] for item in category_items.json()] == ["SKU-A"]

    below_reorder = client.get("/inventory", params={"below_reorder": "true"})
    assert [item["sku"] for item in below_reorder.json()] == ["SKU-B"]

    patched = client.patch(
        "/inventory/SKU-B",
        json={"name": "Updated item", "avg_daily_draw": 4},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Updated item"

    detail = client.get("/inventory/SKU-B")
    assert detail.status_code == 200
    assert detail.json()["lots"] == []
    assert detail.json()["days_cover"] == 2.0

    deleted = client.delete("/inventory/SKU-A")
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert client.get("/inventory/SKU-A").status_code == 404


def test_create_duplicate_and_unknown_vendor_use_standard_errors(inventory_api) -> None:  # type: ignore[no-untyped-def]
    client, _session_factory = inventory_api
    payload = _item_payload("SKU-DUP")
    assert client.post("/inventory", json=payload).status_code == 201

    duplicate = client.post("/inventory", json=payload)
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "CONFLICT"
    assert duplicate.json()["alternatives"]

    unknown_vendor_payload = _item_payload("SKU-VENDOR")
    unknown_vendor_payload["preferred_vendor_id"] = "NO-SUCH-VENDOR"
    unknown_vendor = client.post("/inventory", json=unknown_vendor_payload)
    assert unknown_vendor.status_code == 404
    assert set(unknown_vendor.json()) == {
        "code",
        "message",
        "remedy_hint",
        "alternatives",
    }


def test_detail_orders_lots_and_zero_draw_returns_null(inventory_api) -> None:  # type: ignore[no-untyped-def]
    client, session_factory = inventory_api
    now = datetime.now(timezone.utc)
    today = now.date()
    with session_factory() as db:
        db.add(
            Item(
                sku="SKU-LOTS",
                name="Lots item",
                category="Staples",
                unit="bag",
                on_hand=12,
                reorder_point=4,
                avg_daily_draw=0,
                unit_cost_sgd=Decimal("2.00"),
            )
        )
        db.add_all(
            [
                Lot(
                    lot_id="LOT-LATE",
                    sku="SKU-LOTS",
                    qty=7,
                    expiry_date=today + timedelta(days=20),
                    received_at=now,
                    source=LotSource.PURCHASED,
                ),
                Lot(
                    lot_id="LOT-EARLY",
                    sku="SKU-LOTS",
                    qty=5,
                    expiry_date=today + timedelta(days=5),
                    received_at=now,
                    source=LotSource.DONATED,
                ),
            ]
        )
        db.commit()

    response = client.get("/inventory/SKU-LOTS")
    assert response.status_code == 200
    assert response.json()["days_cover"] is None
    assert [lot["lot_id"] for lot in response.json()["lots"]] == [
        "LOT-EARLY",
        "LOT-LATE",
    ]


def test_allocation_is_atomic_and_expired_lot_has_live_alternative(inventory_api) -> None:  # type: ignore[no-untyped-def]
    client, session_factory = inventory_api
    now = datetime.now(timezone.utc)
    today = now.date()
    with session_factory() as db:
        db.add(
            Item(
                sku="SKU-ALLOC",
                name="Allocation item",
                category="Staples",
                unit="bag",
                on_hand=15,
                reorder_point=5,
                avg_daily_draw=1,
                unit_cost_sgd=Decimal("1.50"),
            )
        )
        db.add_all(
            [
                Lot(
                    lot_id="LOT-EXPIRED",
                    sku="SKU-ALLOC",
                    qty=5,
                    expiry_date=today - timedelta(days=1),
                    received_at=now,
                    source=LotSource.DONATED,
                ),
                Lot(
                    lot_id="LOT-LIVE",
                    sku="SKU-ALLOC",
                    qty=10,
                    expiry_date=today + timedelta(days=10),
                    received_at=now,
                    source=LotSource.PURCHASED,
                ),
            ]
        )
        db.commit()

    expired = client.post(
        "/inventory/SKU-ALLOC/allocate",
        json={"lot_id": "LOT-EXPIRED", "qty": 1},
    )
    assert expired.status_code == 410
    assert expired.json()["code"] == "LOT_EXPIRED"
    assert expired.json()["alternatives"][0]["lot_id"] == "LOT-LIVE"

    allocated = client.post(
        "/inventory/SKU-ALLOC/allocate",
        json={"lot_id": "LOT-LIVE", "qty": 4},
    )
    assert allocated.status_code == 200
    assert allocated.json() == {"sku": "SKU-ALLOC", "lot_id": "LOT-LIVE", "qty": 4}

    with session_factory() as db:
        assert db.get(Item, "SKU-ALLOC").on_hand == 11
        assert db.get(Lot, "LOT-LIVE").qty == 6
        assert db.get(Lot, "LOT-EXPIRED").qty == 5


def test_delete_with_dependent_lot_returns_conflict(inventory_api) -> None:  # type: ignore[no-untyped-def]
    client, session_factory = inventory_api
    with session_factory() as db:
        db.add(
            Item(
                sku="SKU-HISTORY",
                name="History item",
                category="Staples",
                unit="bag",
                on_hand=1,
                reorder_point=1,
                avg_daily_draw=1,
                unit_cost_sgd=Decimal("1.00"),
            )
        )
        db.add(
            Lot(
                lot_id="LOT-HISTORY",
                sku="SKU-HISTORY",
                qty=1,
                expiry_date=datetime.now(timezone.utc).date() + timedelta(days=5),
                received_at=datetime.now(timezone.utc),
                source=LotSource.PURCHASED,
            )
        )
        db.commit()

    response = client.delete("/inventory/SKU-HISTORY")
    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"
    assert response.json()["alternatives"][0]["lot_count"] == 1


def test_inventory_openapi_declares_expired_lot_error(inventory_api) -> None:  # type: ignore[no-untyped-def]
    client, _session_factory = inventory_api
    schema = client.get("/openapi.json").json()

    assert "/inventory/alerts" in schema["paths"]
    allocation_responses = schema["paths"]["/inventory/{sku}/allocate"]["post"]["responses"]
    assert "410" in allocation_responses
    assert (
        allocation_responses["410"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/DomainErrorResponse"
    )
