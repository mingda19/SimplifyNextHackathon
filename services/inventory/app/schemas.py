"""Typed public API contracts for the inventory service.

The internal ``vendor_offers`` table deliberately has no schema here: it is an
implementation detail and is not exposed through a public CRUD API.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, StringConstraints
from pydantic import model_validator


Identifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]
NameText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
CategoryText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]
UnitText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=32),
]
SeriesText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
ShortText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveQuantity = Annotated[int, Field(gt=0)]
NonNegativeFloat = Annotated[float, Field(ge=0)]
Money = Annotated[
    Decimal,
    Field(ge=Decimal("0"), max_digits=12, decimal_places=2),
    PlainSerializer(float, return_type=float, when_used="json"),
]


class APIModel(BaseModel):
    """Common strict configuration for request and response models."""

    model_config = ConfigDict(
        extra="forbid",
        from_attributes=True,
        str_strip_whitespace=True,
    )


class LotSource(str, Enum):
    """How an inventory lot entered the charity's stock."""

    PURCHASED = "PURCHASED"
    DONATED = "DONATED"


class OrderStatus(str, Enum):
    """States persisted for committed purchase orders."""

    PLACED = "PLACED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class AlertType(str, Enum):
    """The three alert classifications frozen for Workstream 1."""

    EXPIRING_SOON = "EXPIRING_SOON"
    BELOW_REORDER = "BELOW_REORDER"
    OVERSTOCKED = "OVERSTOCKED"


class ItemCreate(APIModel):
    """Create one inventory item."""

    sku: Identifier
    name: NameText
    category: CategoryText
    unit: UnitText
    on_hand: NonNegativeInt = 0
    reorder_point: NonNegativeInt
    avg_daily_draw: NonNegativeInt
    unit_cost_sgd: Money
    preferred_vendor_id: Identifier | None = None
    dspi_series: SeriesText | None = None


class ItemUpdate(APIModel):
    """Patch mutable item fields.

    Callers should persist ``model_dump(exclude_unset=True)``. Explicit null is
    accepted only for the two nullable database columns.
    """

    name: NameText | None = None
    category: CategoryText | None = None
    unit: UnitText | None = None
    on_hand: NonNegativeInt | None = None
    reorder_point: NonNegativeInt | None = None
    avg_daily_draw: NonNegativeInt | None = None
    unit_cost_sgd: Money | None = None
    preferred_vendor_id: Identifier | None = None
    dspi_series: SeriesText | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> ItemUpdate:
        """Reject empty patches and nulls for non-nullable columns."""

        if not self.model_fields_set:
            raise ValueError("at least one field must be supplied")

        nullable_fields = {"preferred_vendor_id", "dspi_series"}
        null_non_nullable = sorted(
            field_name
            for field_name in self.model_fields_set - nullable_fields
            if getattr(self, field_name) is None
        )
        if null_non_nullable:
            joined = ", ".join(null_non_nullable)
            raise ValueError(f"fields cannot be null: {joined}")

        return self

    def changes(self) -> dict[str, Any]:
        """Return only fields explicitly supplied by the PATCH caller."""

        return self.model_dump(exclude_unset=True)


class ItemResponse(APIModel):
    """Inventory item representation used by create, list, and update."""

    sku: Identifier
    name: NameText
    category: CategoryText
    unit: UnitText
    on_hand: NonNegativeInt
    reorder_point: NonNegativeInt
    avg_daily_draw: NonNegativeInt
    unit_cost_sgd: Money
    preferred_vendor_id: Identifier | None
    dspi_series: SeriesText | None


class LotResponse(APIModel):
    """One received inventory lot."""

    lot_id: Identifier
    sku: Identifier
    qty: NonNegativeInt
    expiry_date: date
    received_at: datetime
    source: LotSource


class ItemDetailResponse(ItemResponse):
    """Item representation enriched only with lots and calculated cover."""

    lots: list[LotResponse] = Field(default_factory=list)
    days_cover: NonNegativeFloat | None


class InventoryAlertResponse(APIModel):
    """A typed inventory alert.

    Lot fields are present only for expiry alerts; ``days_cover`` is present
    only where the classification depends on cover. A zero daily draw produces
    ``days_cover=null`` and does not by itself create an overstock alert.
    """

    type: AlertType
    sku: Identifier
    message: ShortText
    lot_id: Identifier | None = None
    expiry_date: date | None = None
    days_cover: NonNegativeFloat | None = None


class VendorQuoteRequest(APIModel):
    """Request a non-committing vendor quote."""

    sku: Identifier
    qty: PositiveQuantity


class VendorQuoteResponse(APIModel):
    """Deterministic local quote, without DSPI implementation details."""

    vendor_id: Identifier
    sku: Identifier
    qty: PositiveQuantity
    available: bool
    unit_price_sgd: Money
    total_price_sgd: Money
    expected_at: datetime


class VendorOrderRequest(APIModel):
    """Request a committing purchase order."""

    sku: Identifier
    qty: PositiveQuantity


class VendorOrderResponse(APIModel):
    """Committed purchase order representation."""

    order_id: Identifier
    vendor_id: Identifier
    sku: Identifier
    qty: PositiveQuantity
    status: OrderStatus
    unit_price_sgd: Money
    placed_at: datetime
    expected_at: datetime


class AllocationRequest(APIModel):
    """Allocate a positive quantity from one explicitly selected lot."""

    lot_id: Identifier
    qty: PositiveQuantity


class AllocationResponse(APIModel):
    """Minimal acknowledgement of a successful lot allocation."""

    sku: Identifier
    lot_id: Identifier
    qty: PositiveQuantity


class DomainErrorResponse(APIModel):
    """Exact response envelope returned for every domain error."""

    code: ShortText
    message: str = Field(min_length=1)
    remedy_hint: str = Field(min_length=1)
    alternatives: list[dict[str, Any]] = Field(default_factory=list)


# Concise aliases make router response declarations readable while preserving a
# single generated OpenAPI schema for each contract.
InventoryListResponse = list[ItemResponse]
AlertListResponse = list[InventoryAlertResponse]
ErrorResponse = DomainErrorResponse
