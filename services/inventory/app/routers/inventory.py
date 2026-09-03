"""HTTP endpoints for inventory items, alerts, and lot allocation."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import (
    AllocationRequest,
    AllocationResponse,
    DomainErrorResponse,
    Identifier,
    InventoryAlertResponse,
    ItemCreate,
    ItemDetailResponse,
    ItemResponse,
    ItemUpdate,
)
from app.services import alerts as alert_service
from app.services import inventory as inventory_service


router = APIRouter(prefix="/inventory", tags=["inventory"])
DatabaseSession = Annotated[Session, Depends(get_db)]


def _errors(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """Declare the standardized domain envelope in generated OpenAPI."""

    return {
        code: {
            "model": DomainErrorResponse,
            "description": "Standardized domain error response.",
        }
        for code in status_codes
    }


@router.get(
    "/alerts",
    response_model=list[InventoryAlertResponse],
    responses=_errors(422),
    summary="List inventory alerts",
)
def get_inventory_alerts(db: DatabaseSession) -> list[InventoryAlertResponse]:
    """Return current expiry, below-reorder, and overstock alerts."""

    return alert_service.list_inventory_alerts(db)


@router.get(
    "",
    response_model=list[ItemResponse],
    responses=_errors(422),
    summary="List inventory items",
)
def get_inventory(
    db: DatabaseSession,
    category: str | None = Query(default=None, min_length=1, max_length=100),
    below_reorder: bool = Query(default=False),
) -> list[ItemResponse]:
    """List inventory with optional exact-category and reorder filters."""

    return inventory_service.list_items(
        db,
        category=category,
        below_reorder=below_reorder,
    )


@router.post(
    "",
    response_model=ItemResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_errors(
        status.HTTP_404_NOT_FOUND,
        status.HTTP_409_CONFLICT,
        422,
    ),
    summary="Create an inventory item",
)
def post_inventory(payload: ItemCreate, db: DatabaseSession) -> ItemResponse:
    """Create a unique SKU."""

    return inventory_service.create_item(db, payload)


@router.post(
    "/{sku}/allocate",
    response_model=AllocationResponse,
    responses=_errors(
        status.HTTP_404_NOT_FOUND,
        status.HTTP_409_CONFLICT,
        status.HTTP_410_GONE,
        422,
    ),
    summary="Allocate from an inventory lot",
)
def post_allocation(
    sku: Identifier,
    payload: AllocationRequest,
    db: DatabaseSession,
) -> AllocationResponse:
    """Allocate a positive quantity from one selected lot."""

    return inventory_service.allocate_lot(db, sku=sku, payload=payload)


@router.get(
    "/{sku}",
    response_model=ItemDetailResponse,
    responses=_errors(
        status.HTTP_404_NOT_FOUND,
        422,
    ),
    summary="Get inventory item details",
)
def get_inventory_item(sku: Identifier, db: DatabaseSession) -> ItemDetailResponse:
    """Return an item with lots and calculated days of cover."""

    return inventory_service.get_item_detail(db, sku)


@router.patch(
    "/{sku}",
    response_model=ItemResponse,
    responses=_errors(
        status.HTTP_404_NOT_FOUND,
        status.HTTP_409_CONFLICT,
        422,
    ),
    summary="Update an inventory item",
)
def patch_inventory_item(
    sku: Identifier,
    payload: ItemUpdate,
    db: DatabaseSession,
) -> ItemResponse:
    """Patch supplied mutable fields on an existing item."""

    return inventory_service.update_item(db, sku, payload)


@router.delete(
    "/{sku}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_errors(
        status.HTTP_404_NOT_FOUND,
        status.HTTP_409_CONFLICT,
        422,
    ),
    summary="Delete an inventory item",
)
def remove_inventory_item(sku: Identifier, db: DatabaseSession) -> Response:
    """Delete only an item without dependent lots or orders."""

    inventory_service.delete_item(db, sku)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
