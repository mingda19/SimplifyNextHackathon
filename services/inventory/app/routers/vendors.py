"""HTTP routes for vendor quotes and committing purchase orders."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import (
    DomainErrorResponse,
    Identifier,
    VendorOrderRequest,
    VendorOrderResponse,
    VendorQuoteRequest,
    VendorQuoteResponse,
)
from app.services.rate_limit import DEMO_RATE_LIMIT_HEADER, enforce_demo_rate_limit
from app.services.vendors import get_vendor_quote, place_vendor_order


router = APIRouter(prefix="/vendor", tags=["vendors"])

ERROR_RESPONSES = {
    status.HTTP_400_BAD_REQUEST: {
        "model": DomainErrorResponse,
        "description": "Vendor minimum order was not met.",
    },
    status.HTTP_404_NOT_FOUND: {
        "model": DomainErrorResponse,
        "description": "Vendor or SKU was not found.",
    },
    status.HTTP_409_CONFLICT: {
        "model": DomainErrorResponse,
        "description": "Vendor stock cannot fulfil the request.",
    },
    422: {
        "model": DomainErrorResponse,
        "description": "Lead time or request validation failed.",
    },
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "model": DomainErrorResponse,
        "description": "Demo rate limit; retry using the Retry-After header.",
        "headers": {
            "Retry-After": {
                "description": "Seconds until the demo request can be retried.",
                "schema": {"type": "integer", "minimum": 1},
            }
        },
    },
}


@router.post(
    "/{id}/quote",
    response_model=VendorQuoteResponse,
    responses=ERROR_RESPONSES,
    summary="Validate and price a non-committing vendor quote",
)
def quote_vendor(
    id: Identifier,
    payload: VendorQuoteRequest,
    db: Annotated[Session, Depends(get_db)],
    demo_rate_limit_key: Annotated[
        str | None,
        Header(alias=DEMO_RATE_LIMIT_HEADER),
    ] = None,
) -> VendorQuoteResponse:
    """Quote current local vendor availability without changing it."""

    enforce_demo_rate_limit(demo_rate_limit_key)
    return get_vendor_quote(db, vendor_id=id, payload=payload)


@router.post(
    "/{id}/order",
    response_model=VendorOrderResponse,
    responses=ERROR_RESPONSES,
    summary="Validate and commit a vendor purchase order",
)
def order_from_vendor(
    id: Identifier,
    payload: VendorOrderRequest,
    db: Annotated[Session, Depends(get_db)],
    demo_rate_limit_key: Annotated[
        str | None,
        Header(alias=DEMO_RATE_LIMIT_HEADER),
    ] = None,
) -> VendorOrderResponse:
    """Revalidate the request and reserve vendor stock in one transaction."""

    enforce_demo_rate_limit(demo_rate_limit_key)
    return place_vendor_order(db, vendor_id=id, payload=payload)


__all__ = ["router"]
