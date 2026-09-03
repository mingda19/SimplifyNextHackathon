"""Full-application OpenAPI contract checks."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_openapi_contains_every_workstream_one_route() -> None:
    schema = TestClient(app).get("/openapi.json").json()

    assert set(schema["paths"]) == {
        "/health",
        "/inventory",
        "/inventory/alerts",
        "/inventory/{sku}",
        "/inventory/{sku}/allocate",
        "/vendor/{id}/quote",
        "/vendor/{id}/order",
    }
    assert set(schema["paths"]["/inventory"]) == {"get", "post"}
    assert set(schema["paths"]["/inventory/{sku}"]) == {
        "get",
        "patch",
        "delete",
    }


def test_public_models_are_minimal_and_keep_dspi_series() -> None:
    schemas = TestClient(app).get("/openapi.json").json()["components"]["schemas"]

    item_fields = set(schemas["ItemResponse"]["properties"])
    assert item_fields == {
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
    assert set(schemas["ItemDetailResponse"]["properties"]) == item_fields | {
        "lots",
        "days_cover",
    }
    assert not any("VendorOffer" in name for name in schemas)
    assert "open_order_qty" not in str(schemas)
    assert "dspi_basis" not in str(schemas)


def test_required_domain_errors_and_retry_header_are_documented() -> None:
    schema = TestClient(app).get("/openapi.json").json()
    quote_responses = schema["paths"]["/vendor/{id}/quote"]["post"]["responses"]

    for status_code in ("400", "409", "422", "429"):
        response_schema = quote_responses[status_code]["content"]["application/json"][
            "schema"
        ]
        assert response_schema["$ref"] == "#/components/schemas/DomainErrorResponse"

    assert "Retry-After" in quote_responses["429"]["headers"]
    allocation_responses = schema["paths"]["/inventory/{sku}/allocate"]["post"][
        "responses"
    ]
    assert "410" in allocation_responses
