"""Deterministic local pricing for Workstream 1 vendor quotes.

This module is the deliberate seam for Workstream 3.  Until that workstream is
integrated, prices depend only on the item's stored unit cost and private
vendor-offer inputs; no external service or DSPI data is consulted here.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


CENT = Decimal("0.01")
ONE = Decimal("1")


@dataclass(frozen=True, slots=True)
class LocalPrice:
    """A rounded, internally consistent local quote."""

    unit_price_sgd: Decimal
    total_price_sgd: Decimal


def round_sgd(value: Decimal) -> Decimal:
    """Round a monetary amount to cents using commercial half-up rounding."""

    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def calculate_local_price(
    *,
    unit_cost_sgd: Decimal,
    vendor_multiplier: Decimal,
    qty: int,
    bulk_discount_threshold: int | None = None,
    bulk_discount_rate: Decimal = Decimal("0"),
) -> LocalPrice:
    """Calculate a deterministic quote from local item and offer values.

    The optional discount applies when the requested quantity reaches the
    offer's inclusive bulk threshold.  The total is derived from the displayed
    rounded unit price so callers never see an internally inconsistent quote.
    """

    if qty <= 0:
        raise ValueError("qty must be positive")
    if unit_cost_sgd < 0:
        raise ValueError("unit_cost_sgd must be non-negative")
    if vendor_multiplier <= 0:
        raise ValueError("vendor_multiplier must be positive")
    if not Decimal("0") <= bulk_discount_rate < ONE:
        raise ValueError("bulk_discount_rate must be between zero and one")
    if bulk_discount_threshold is not None and bulk_discount_threshold <= 0:
        raise ValueError("bulk_discount_threshold must be positive")

    discount = (
        bulk_discount_rate
        if bulk_discount_threshold is not None and qty >= bulk_discount_threshold
        else Decimal("0")
    )
    unit_price = round_sgd(unit_cost_sgd * vendor_multiplier * (ONE - discount))
    total_price = round_sgd(unit_price * Decimal(qty))
    return LocalPrice(unit_price_sgd=unit_price, total_price_sgd=total_price)


__all__ = ["LocalPrice", "calculate_local_price", "round_sgd"]
