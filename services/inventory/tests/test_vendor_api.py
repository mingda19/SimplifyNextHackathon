"""API and persistence tests for deterministic vendor operations."""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.errors import install_error_handlers
from app.models import Base, Item, Order, Vendor, VendorOffer
from app.routers.vendors import router
from app.services.pricing import calculate_local_price
from app.services.rate_limit import reset_rate_limits


@pytest.fixture()
def vendor_api() -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_session = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    Base.metadata.create_all(engine)

    with test_session() as db:
        db.add_all(
            [
                Vendor(
                    vendor_id="VENDOR-HARVEST",
                    name="Harvest Wholesale",
                    moq_units=250,
                    lead_time_days=5,
                    reliability=Decimal("0.9500"),
                ),
                Vendor(
                    vendor_id="VENDOR-COMMUNITY",
                    name="Community Supply",
                    moq_units=100,
                    lead_time_days=3,
                    reliability=Decimal("0.9000"),
                ),
                Vendor(
                    vendor_id="VENDOR-RAPID",
                    name="Rapid Relief Supply",
                    moq_units=50,
                    lead_time_days=2,
                    reliability=Decimal("0.9800"),
                ),
                Vendor(
                    vendor_id="VENDOR-SLOW",
                    name="Slow Bulk Supply",
                    moq_units=200,
                    lead_time_days=10,
                    reliability=Decimal("0.8000"),
                ),
            ]
        )
        db.add_all(
            [
                Item(
                    sku="RICE-5KG",
                    name="Rice 5kg",
                    category="STAPLES",
                    unit="bag",
                    on_hand=200,
                    reorder_point=250,
                    avg_daily_draw=25,
                    unit_cost_sgd=Decimal("2.40"),
                    preferred_vendor_id="VENDOR-HARVEST",
                    dspi_series="Rice",
                ),
                Item(
                    sku="MILK-UHT-1L",
                    name="UHT Milk 1L",
                    category="DAIRY",
                    unit="carton",
                    on_hand=200,
                    reorder_point=80,
                    avg_daily_draw=10,
                    unit_cost_sgd=Decimal("1.80"),
                    preferred_vendor_id="VENDOR-COMMUNITY",
                    dspi_series=None,
                ),
            ]
        )
        db.add_all(
            [
                VendorOffer(
                    vendor_id="VENDOR-HARVEST",
                    sku="RICE-5KG",
                    available_qty=2000,
                    price_multiplier=Decimal("1.0000"),
                    bulk_discount_threshold=None,
                    bulk_discount_rate=Decimal("0.0000"),
                ),
                VendorOffer(
                    vendor_id="VENDOR-COMMUNITY",
                    sku="RICE-5KG",
                    available_qty=1600,
                    price_multiplier=Decimal("1.0400"),
                    bulk_discount_threshold=250,
                    bulk_discount_rate=Decimal("0.1000"),
                ),
                VendorOffer(
                    vendor_id="VENDOR-RAPID",
                    sku="RICE-5KG",
                    available_qty=1000,
                    price_multiplier=Decimal("1.1000"),
                    bulk_discount_threshold=None,
                    bulk_discount_rate=Decimal("0.0000"),
                ),
                VendorOffer(
                    vendor_id="VENDOR-SLOW",
                    sku="RICE-5KG",
                    available_qty=3000,
                    price_multiplier=Decimal("0.9500"),
                    bulk_discount_threshold=None,
                    bulk_discount_rate=Decimal("0.0000"),
                ),
                VendorOffer(
                    vendor_id="VENDOR-COMMUNITY",
                    sku="MILK-UHT-1L",
                    available_qty=0,
                    price_multiplier=Decimal("1.0000"),
                    bulk_discount_threshold=None,
                    bulk_discount_rate=Decimal("0.0000"),
                ),
                VendorOffer(
                    vendor_id="VENDOR-RAPID",
                    sku="MILK-UHT-1L",
                    available_qty=500,
                    price_multiplier=Decimal("1.0500"),
                    bulk_discount_threshold=None,
                    bulk_discount_rate=Decimal("0.0000"),
                ),
            ]
        )
        db.commit()

    test_app = FastAPI()
    install_error_handlers(test_app)
    test_app.include_router(router)

    def override_get_db() -> Generator[Session, None, None]:
        with test_session() as db:
            yield db

    test_app.dependency_overrides[get_db] = override_get_db
    reset_rate_limits()
    with TestClient(test_app) as client:
        yield client, test_session
    reset_rate_limits()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_local_price_applies_inclusive_bulk_discount_and_cent_rounding() -> None:
    price = calculate_local_price(
        unit_cost_sgd=Decimal("2.40"),
        vendor_multiplier=Decimal("1.0400"),
        qty=250,
        bulk_discount_threshold=250,
        bulk_discount_rate=Decimal("0.1000"),
    )

    assert price.unit_price_sgd == Decimal("2.25")
    assert price.total_price_sgd == Decimal("562.50")


def test_quote_is_typed_deterministic_and_non_mutating(vendor_api) -> None:
    client, test_session = vendor_api
    response = client.post(
        "/vendor/VENDOR-COMMUNITY/quote",
        json={"sku": "RICE-5KG", "qty": 250},
    )

    assert response.status_code == 200
    assert set(response.json()) == {
        "vendor_id",
        "sku",
        "qty",
        "available",
        "unit_price_sgd",
        "total_price_sgd",
        "expected_at",
    }
    assert response.json() | {"expected_at": None} == {
        "vendor_id": "VENDOR-COMMUNITY",
        "sku": "RICE-5KG",
        "qty": 250,
        "available": True,
        "unit_price_sgd": 2.25,
        "total_price_sgd": 562.5,
        "expected_at": None,
    }
    assert datetime.fromisoformat(response.json()["expected_at"])

    with test_session() as db:
        offer = db.get(VendorOffer, ("VENDOR-COMMUNITY", "RICE-5KG"))
        assert offer is not None
        assert offer.available_qty == 1600
        assert db.scalar(select(func.count()).select_from(Order)) == 0


def test_order_revalidates_commits_and_only_decrements_vendor_stock(vendor_api) -> None:
    client, test_session = vendor_api
    response = client.post(
        "/vendor/VENDOR-HARVEST/order",
        json={"sku": "RICE-5KG", "qty": 250},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "PLACED"
    assert response.json()["unit_price_sgd"] == 2.4
    placed_at = datetime.fromisoformat(response.json()["placed_at"])
    expected_at = datetime.fromisoformat(response.json()["expected_at"])
    assert (expected_at - placed_at).days == 5

    with test_session() as db:
        offer = db.get(VendorOffer, ("VENDOR-HARVEST", "RICE-5KG"))
        item = db.get(Item, "RICE-5KG")
        order = db.scalar(select(Order))
        assert offer is not None and offer.available_qty == 1750
        assert item is not None and item.on_hand == 200
        assert order is not None and order.qty == 250


def test_failed_order_does_not_mutate_offer_or_create_order(vendor_api) -> None:
    client, test_session = vendor_api
    response = client.post(
        "/vendor/VENDOR-HARVEST/order",
        json={"sku": "RICE-5KG", "qty": 200},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "MOQ_NOT_MET"
    with test_session() as db:
        offer = db.get(VendorOffer, ("VENDOR-HARVEST", "RICE-5KG"))
        assert offer is not None and offer.available_qty == 2000
        assert db.scalar(select(func.count()).select_from(Order)) == 0


def test_moq_error_suggests_raise_and_viable_vendor(vendor_api) -> None:
    client, _ = vendor_api
    response = client.post(
        "/vendor/VENDOR-HARVEST/quote",
        json={"sku": "RICE-5KG", "qty": 200},
    )

    assert response.status_code == 400
    assert set(response.json()) == {
        "code",
        "message",
        "remedy_hint",
        "alternatives",
    }
    assert response.json()["code"] == "MOQ_NOT_MET"
    assert {
        alternative["action"] for alternative in response.json()["alternatives"]
    } >= {"raise_quantity", "choose_vendor"}
    assert response.json()["alternatives"][0]["minimum_qty"] == 250


def test_out_of_stock_error_suggests_stocked_vendor_before_moq(vendor_api) -> None:
    client, _ = vendor_api
    response = client.post(
        "/vendor/VENDOR-COMMUNITY/quote",
        json={"sku": "MILK-UHT-1L", "qty": 50},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "OUT_OF_STOCK"
    assert any(
        alternative.get("vendor_id") == "VENDOR-RAPID"
        for alternative in response.json()["alternatives"]
    )


def test_lead_time_error_suggests_feasible_faster_vendors(vendor_api) -> None:
    client, _ = vendor_api
    response = client.post(
        "/vendor/VENDOR-SLOW/quote",
        json={"sku": "RICE-5KG", "qty": 250},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "LEAD_TIME_EXCEEDED"
    alternatives = response.json()["alternatives"]
    assert alternatives
    assert all(alternative["lead_time_days"] <= 8 for alternative in alternatives)


def test_unknown_vendor_uses_standard_error_and_known_alternatives(vendor_api) -> None:
    client, _ = vendor_api
    response = client.post(
        "/vendor/DOES-NOT-EXIST/quote",
        json={"sku": "RICE-5KG", "qty": 250},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    assert response.json()["alternatives"]


def test_demo_rate_limit_has_retry_header_and_useful_alternative(vendor_api) -> None:
    client, _ = vendor_api
    response = client.post(
        "/vendor/VENDOR-RAPID/quote",
        headers={"X-Demo-Rate-Limit": "pytest-cycle"},
        json={"sku": "RICE-5KG", "qty": 50},
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "1"
    assert response.json()["code"] == "RATE_LIMITED"
    assert response.json()["alternatives"] == [
        {"action": "retry", "after_seconds": 1, "demo_key": "pytest-cycle"}
    ]


def test_openapi_documents_typed_vendor_success_and_error_models(vendor_api) -> None:
    client, _ = vendor_api
    operation = client.get("/openapi.json").json()["paths"][
        "/vendor/{id}/quote"
    ]["post"]

    assert operation["responses"]["200"]["content"]["application/json"]["schema"]
    for status_code in ("400", "404", "409", "422", "429"):
        assert operation["responses"][status_code]["content"]["application/json"][
            "schema"
        ]
