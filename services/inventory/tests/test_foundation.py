"""Foundation checks for the runtime, schema, contracts, and error handlers."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.errors import MoqNotMetError, install_error_handlers
from app.main import app
from app.models import Base
from app.schemas import ItemCreate, ItemDetailResponse


def test_docs_and_openapi_load_without_database() -> None:
    client = TestClient(app)

    docs = client.get("/docs")
    schema = client.get("/openapi.json")

    assert docs.status_code == 200
    assert schema.status_code == 200
    assert schema.json()["info"]["title"] == "SimplifyNext Inventory Service"
    assert "/health" in schema.json()["paths"]


def test_health_endpoint_can_boot(monkeypatch) -> None:
    monkeypatch.setattr("app.main.check_database_connection", lambda: None)

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_expected_database_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == {
        "items",
        "lots",
        "vendors",
        "orders",
        "vendor_offers",
    }


def test_frozen_item_fields_are_preserved() -> None:
    item_columns = set(Base.metadata.tables["items"].columns.keys())
    assert item_columns == {
        "sku",
        "name",
        "category",
        "unit",
        "on_hand",
        "reorder_point",
        "avg_daily_draw",
        "unit_cost_sgd",
        "preferred_vendor_id",
        "dspi_series",
    }


def test_inventory_contracts_do_not_expose_unrequested_fields() -> None:
    assert set(ItemCreate.model_json_schema()["properties"]) == {
        "sku",
        "name",
        "category",
        "unit",
        "on_hand",
        "reorder_point",
        "avg_daily_draw",
        "unit_cost_sgd",
        "preferred_vendor_id",
        "dspi_series",
    }
    assert set(ItemDetailResponse.model_json_schema()["properties"]) == {
        *ItemCreate.model_json_schema()["properties"],
        "lots",
        "days_cover",
    }


def test_domain_error_has_exact_envelope() -> None:
    test_app = FastAPI()
    install_error_handlers(test_app)

    @test_app.get("/fail")
    def fail() -> None:
        raise MoqNotMetError(
            alternatives=[{"vendor_id": "VENDOR-B", "minimum_qty": 250}]
        )

    response = TestClient(test_app).get("/fail")

    assert response.status_code == 400
    assert set(response.json()) == {
        "code",
        "message",
        "remedy_hint",
        "alternatives",
    }
    assert response.json()["code"] == "MOQ_NOT_MET"
    assert response.json()["alternatives"] == [
        {"vendor_id": "VENDOR-B", "minimum_qty": 250}
    ]


def test_validation_error_uses_standard_envelope() -> None:
    test_app = FastAPI()
    install_error_handlers(test_app)

    @test_app.post("/items")
    def create_item(_payload: ItemCreate) -> None:
        return None

    response = TestClient(test_app).post("/items", json={})

    assert response.status_code == 422
    assert set(response.json()) == {
        "code",
        "message",
        "remedy_hint",
        "alternatives",
    }
    assert response.json()["code"] == "VALIDATION_ERROR"
