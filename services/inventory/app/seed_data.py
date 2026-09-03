"""Stable, local demo fixtures for Workstream 1.

Dates are expressed as offsets and resolved when seeding so expiry behaviour is
repeatable without baking a calendar date into the repository.  Pricing fields
are only deterministic local inputs; ``dspi_series`` is preserved as metadata
for the future Workstream 3 integration and is never fetched here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from app.models import LotSource


RICE_SKU = "RICE-5KG"
OOS_SKU = "MILK-UHT-1L"
EXPIRED_LOT_SKU = "BEANS-CANNED-400G"

PREFERRED_VENDOR_ID = "VENDOR-HARVEST"
SECONDARY_VENDOR_ID = "VENDOR-COMMUNITY"
RAPID_VENDOR_ID = "VENDOR-RAPID"
SLOW_VENDOR_ID = "VENDOR-SLOW"

EXPIRED_LOT_ID = "LOT-BEANS-CANNED-400G-EXPIRED"
LIVE_LOT_ID = "LOT-BEANS-CANNED-400G-LIVE"


@dataclass(frozen=True, slots=True)
class VendorSeed:
    vendor_id: str
    name: str
    moq_units: int
    lead_time_days: int
    reliability: Decimal


@dataclass(frozen=True, slots=True)
class ItemSeed:
    sku: str
    name: str
    category: str
    unit: str
    on_hand: int
    reorder_point: int
    avg_daily_draw: int
    unit_cost_sgd: Decimal
    preferred_vendor_id: str
    dspi_series: str | None


@dataclass(frozen=True, slots=True)
class LotSeed:
    lot_id: str
    sku: str
    qty: int
    expiry_date: date
    received_at: datetime
    source: LotSource


@dataclass(frozen=True, slots=True)
class VendorOfferSeed:
    vendor_id: str
    sku: str
    available_qty: int
    price_multiplier: Decimal
    bulk_discount_threshold: int | None
    bulk_discount_rate: Decimal


VENDOR_SEEDS: tuple[VendorSeed, ...] = (
    VendorSeed(
        vendor_id=PREFERRED_VENDOR_ID,
        name="Harvest Wholesale",
        moq_units=250,
        lead_time_days=5,
        reliability=Decimal("0.9600"),
    ),
    VendorSeed(
        vendor_id=SECONDARY_VENDOR_ID,
        name="Community Supply Co",
        moq_units=100,
        lead_time_days=3,
        reliability=Decimal("0.9200"),
    ),
    VendorSeed(
        vendor_id=RAPID_VENDOR_ID,
        name="Rapid Relief Trading",
        moq_units=50,
        lead_time_days=2,
        reliability=Decimal("0.8800"),
    ),
    VendorSeed(
        vendor_id=SLOW_VENDOR_ID,
        name="Value Bulk Imports",
        moq_units=200,
        lead_time_days=10,
        reliability=Decimal("0.9800"),
    ),
)


# Forty practical pantry, fresh-food, and household SKUs.  RICE-5KG is kept at
# exactly eight days of cover: 200 on hand / 25 average daily draw.
ITEM_SEEDS: tuple[ItemSeed, ...] = (
    ItemSeed(RICE_SKU, "Jasmine Rice 5 kg", "STAPLES", "kg", 200, 250, 25, Decimal("2.40"), PREFERRED_VENDOR_ID, "Rice"),
    ItemSeed("NOODLES-1KG", "Dried Noodles 1 kg", "STAPLES", "kg", 180, 160, 12, Decimal("2.10"), PREFERRED_VENDOR_ID, "Cereal Preparations And Preparations Of Flour Or Starch Of Fruits Or Vegetables"),
    ItemSeed("OIL-2L", "Vegetable Cooking Oil 2 L", "STAPLES", "litre", 96, 120, 8, Decimal("3.80"), PREFERRED_VENDOR_ID, "Fixed Vegetable Fats And Oils, Crude, Refined Or Fractionated"),
    ItemSeed("FLOUR-1KG", "Plain Flour 1 kg", "STAPLES", "kg", 140, 100, 6, Decimal("1.75"), PREFERRED_VENDOR_ID, "Wheat (Including Spelt) And Meslin, Unmilled"),
    ItemSeed("SUGAR-1KG", "White Sugar 1 kg", "STAPLES", "kg", 110, 90, 5, Decimal("1.65"), PREFERRED_VENDOR_ID, "Sugars, Molasses And Honey"),
    ItemSeed("SALT-500G", "Table Salt 500 g", "STAPLES", "pack", 400, 80, 8, Decimal("0.75"), SLOW_VENDOR_ID, None),
    ItemSeed("OATS-1KG", "Rolled Oats 1 kg", "BREAKFAST", "kg", 150, 120, 7, Decimal("4.20"), SECONDARY_VENDOR_ID, "Cereal Preparations And Preparations Of Flour Or Starch Of Fruits Or Vegetables"),
    ItemSeed("CEREAL-500G", "Breakfast Cereal 500 g", "BREAKFAST", "pack", 90, 75, 5, Decimal("4.80"), SECONDARY_VENDOR_ID, "Cereal Preparations And Preparations Of Flour Or Starch Of Fruits Or Vegetables"),
    # Expired lots remain in history but are excluded from usable on-hand stock.
    ItemSeed(EXPIRED_LOT_SKU, "Canned Baked Beans 400 g", "CANNED", "can", 150, 140, 6, Decimal("1.35"), RAPID_VENDOR_ID, "Vegetables, Roots And Tubers, Prepared Or Preserved, N.E.S."),
    ItemSeed("CHICKPEAS-CANNED-400G", "Canned Chickpeas 400 g", "CANNED", "can", 135, 100, 5, Decimal("1.45"), SECONDARY_VENDOR_ID, "Vegetables, Roots And Tubers, Prepared Or Preserved, N.E.S."),
    ItemSeed("TUNA-CANNED-185G", "Canned Tuna 185 g", "CANNED", "can", 160, 130, 8, Decimal("2.20"), SECONDARY_VENDOR_ID, "Fish, Prepared Or Preserved; Caviar And Caviar Substitutes"),
    ItemSeed("SARDINES-CANNED-155G", "Canned Sardines 155 g", "CANNED", "can", 150, 120, 7, Decimal("1.70"), SECONDARY_VENDOR_ID, "Fish, Prepared Or Preserved; Caviar And Caviar Substitutes"),
    ItemSeed(OOS_SKU, "UHT Milk 1 L", "DAIRY", "carton", 120, 150, 12, Decimal("2.25"), RAPID_VENDOR_ID, "Milk And Cream And Milk Products Other Than Butter Or Cheese"),
    ItemSeed("SOY-MILK-1L", "Soy Milk 1 L", "DAIRY", "carton", 84, 75, 6, Decimal("2.40"), RAPID_VENDOR_ID, "Non-Alcoholic Beverages, N.E.S."),
    ItemSeed("INFANT-FORMULA-900G", "Infant Formula 900 g", "INFANT", "tin", 48, 60, 3, Decimal("32.00"), SECONDARY_VENDOR_ID, "Milk And Cream And Milk Products Other Than Butter Or Cheese"),
    ItemSeed("EGGS-TRAY30", "Eggs Tray of 30", "PROTEIN", "tray", 54, 60, 6, Decimal("8.50"), RAPID_VENDOR_ID, "Birds' Eggs, And Egg Yolks, Fresh, Dried Or Otherwise Preserved, Sweetened Or Not; Egg Albumin"),
    ItemSeed("CHICKEN-FROZEN-1KG", "Frozen Chicken 1 kg", "PROTEIN", "kg", 95, 110, 10, Decimal("5.80"), RAPID_VENDOR_ID, "Meat And Edible Meat Offal, Fresh, Chilled Or Frozen"),
    ItemSeed("FISH-FROZEN-1KG", "Frozen White Fish 1 kg", "PROTEIN", "kg", 70, 90, 7, Decimal("7.20"), RAPID_VENDOR_ID, "Fish, Fresh (Live Or Dead), Chilled Or Frozen"),
    ItemSeed("TOFU-300G", "Firm Tofu 300 g", "PROTEIN", "pack", 45, 55, 9, Decimal("1.20"), RAPID_VENDOR_ID, None),
    ItemSeed("VEGETABLES-MIXED-1KG", "Mixed Vegetables 1 kg", "PRODUCE", "kg", 72, 100, 12, Decimal("3.50"), RAPID_VENDOR_ID, "Vegetables, Fresh, Chilled, Frozen Or Simply Preserved"),
    ItemSeed("FRUIT-CANNED-825G", "Canned Mixed Fruit 825 g", "PRODUCE", "can", 100, 80, 4, Decimal("3.60"), SECONDARY_VENDOR_ID, "Fruit, Preserved, And Fruit Preparations (Excluding Fruit Juices)"),
    ItemSeed("POTATOES-5KG", "Potatoes 5 kg", "PRODUCE", "kg", 125, 140, 10, Decimal("1.60"), RAPID_VENDOR_ID, "Vegetables, Fresh, Chilled, Frozen Or Simply Preserved"),
    ItemSeed("ONIONS-2KG", "Onions 2 kg", "PRODUCE", "kg", 86, 90, 6, Decimal("1.85"), RAPID_VENDOR_ID, "Vegetables, Fresh, Chilled, Frozen Or Simply Preserved"),
    ItemSeed("CARROTS-1KG", "Carrots 1 kg", "PRODUCE", "kg", 78, 95, 7, Decimal("2.10"), RAPID_VENDOR_ID, "Vegetables, Fresh, Chilled, Frozen Or Simply Preserved"),
    ItemSeed("TOMATOES-CANNED-400G", "Canned Tomatoes 400 g", "CANNED", "can", 144, 100, 5, Decimal("1.30"), SECONDARY_VENDOR_ID, "Vegetables, Roots And Tubers, Prepared Or Preserved, N.E.S."),
    ItemSeed("BISCUITS-500G", "Plain Biscuits 500 g", "SNACKS", "pack", 112, 90, 6, Decimal("2.60"), SECONDARY_VENDOR_ID, "Cereal Preparations And Preparations Of Flour Or Starch Of Fruits Or Vegetables"),
    ItemSeed("PEANUT-BUTTER-500G", "Peanut Butter 500 g", "SPREADS", "jar", 65, 70, 4, Decimal("4.50"), SECONDARY_VENDOR_ID, "Oil Seeds And Oleaginous Fruits, Whole Or Broken, Of A Kind Used For The Extraction Of Other Fixed Vegetable Oils"),
    ItemSeed("JAM-450G", "Fruit Jam 450 g", "SPREADS", "jar", 74, 60, 3, Decimal("3.20"), SECONDARY_VENDOR_ID, "Fruit, Preserved, And Fruit Preparations (Excluding Fruit Juices)"),
    ItemSeed("TEA-100BAG", "Black Tea 100 Bags", "BEVERAGES", "box", 52, 50, 2, Decimal("5.40"), SLOW_VENDOR_ID, "Tea And Mate"),
    ItemSeed("COFFEE-500G", "Instant Coffee 500 g", "BEVERAGES", "jar", 46, 55, 2, Decimal("9.80"), SLOW_VENDOR_ID, "Coffee And Coffee Substitutes"),
    ItemSeed("WATER-1-5L", "Drinking Water 1.5 L", "BEVERAGES", "bottle", 360, 300, 20, Decimal("0.80"), PREFERRED_VENDOR_ID, "Non-Alcoholic Beverages, N.E.S."),
    ItemSeed("HYGIENE-SOAP-4PK", "Bath Soap 4 Pack", "HYGIENE", "pack", 96, 80, 4, Decimal("3.10"), SECONDARY_VENDOR_ID, None),
    ItemSeed("SHAMPOO-500ML", "Shampoo 500 ml", "HYGIENE", "bottle", 58, 50, 2, Decimal("5.20"), SECONDARY_VENDOR_ID, None),
    ItemSeed("TOOTHPASTE-100G", "Toothpaste 100 g", "HYGIENE", "tube", 88, 75, 4, Decimal("2.75"), SECONDARY_VENDOR_ID, None),
    ItemSeed("SANITARY-PADS-20PK", "Sanitary Pads 20 Pack", "HYGIENE", "pack", 76, 90, 5, Decimal("4.10"), RAPID_VENDOR_ID, None),
    ItemSeed("DIAPERS-M-40PK", "Medium Diapers 40 Pack", "INFANT", "pack", 44, 60, 4, Decimal("14.50"), RAPID_VENDOR_ID, None),
    ItemSeed("DETERGENT-2KG", "Laundry Detergent 2 kg", "HOUSEHOLD", "pack", 62, 55, 3, Decimal("7.40"), SLOW_VENDOR_ID, None),
    ItemSeed("DISHWASH-LIQUID-1L", "Dishwashing Liquid 1 L", "HOUSEHOLD", "bottle", 68, 50, 3, Decimal("3.30"), SLOW_VENDOR_ID, None),
    ItemSeed("MASKS-50PK", "Disposable Masks 50 Pack", "HEALTH", "box", 200, 40, 0, Decimal("6.50"), SLOW_VENDOR_ID, None),
    ItemSeed("HAND-SANITISER-500ML", "Hand Sanitiser 500 ml", "HEALTH", "bottle", 85, 60, 2, Decimal("4.20"), SECONDARY_VENDOR_ID, None),
)


def utc_today() -> date:
    """Return today's date in UTC; injectable dates keep tests deterministic."""

    return datetime.now(UTC).date()


def _received_at(today: date, days_ago: int) -> datetime:
    return datetime.combine(today - timedelta(days=days_ago), time(hour=9), tzinfo=UTC)


def build_lot_seeds(today: date | None = None) -> tuple[LotSeed, ...]:
    """Resolve stable lot IDs into expiry and receipt dates relative to UTC today."""

    anchor = today or utc_today()
    lots: list[LotSeed] = []

    for index, item in enumerate(ITEM_SEEDS):
        if item.sku == EXPIRED_LOT_SKU:
            lots.extend(
                (
                    LotSeed(
                        lot_id=EXPIRED_LOT_ID,
                        sku=item.sku,
                        qty=30,
                        expiry_date=anchor - timedelta(days=1),
                        received_at=_received_at(anchor, 180),
                        source=LotSource.DONATED,
                    ),
                    LotSeed(
                        lot_id=LIVE_LOT_ID,
                        sku=item.sku,
                        qty=150,
                        expiry_date=anchor + timedelta(days=180),
                        received_at=_received_at(anchor, 20),
                        source=LotSource.PURCHASED,
                    ),
                )
            )
            continue

        purchased_qty = (item.on_hand * 3) // 5
        donated_qty = item.on_hand - purchased_qty

        # Staggered horizons deliberately include a handful of <=14 day lots
        # for alert demos while keeping the rice purchasing story independent.
        purchased_expiry_days = 45 + (index % 6) * 30
        donated_expiry_days = 7 + (index % 8) * 12
        if item.sku == RICE_SKU:
            purchased_expiry_days, donated_expiry_days = 120, 75
        elif item.sku == OOS_SKU:
            purchased_expiry_days, donated_expiry_days = 90, 7
        elif item.sku == "TOFU-300G":
            purchased_expiry_days, donated_expiry_days = 9, 5

        lots.extend(
            (
                LotSeed(
                    lot_id=f"LOT-{item.sku}-PURCHASED",
                    sku=item.sku,
                    qty=purchased_qty,
                    expiry_date=anchor + timedelta(days=purchased_expiry_days),
                    received_at=_received_at(anchor, 30 + index),
                    source=LotSource.PURCHASED,
                ),
                LotSeed(
                    lot_id=f"LOT-{item.sku}-DONATED",
                    sku=item.sku,
                    qty=donated_qty,
                    expiry_date=anchor + timedelta(days=donated_expiry_days),
                    received_at=_received_at(anchor, 7 + index),
                    source=LotSource.DONATED,
                ),
            )
        )

    return tuple(lots)


_OFFER_TERMS: dict[str, tuple[Decimal, int | None, Decimal]] = {
    PREFERRED_VENDOR_ID: (Decimal("1.0000"), 500, Decimal("0.0200")),
    # At 250 units, 2.40 * 1.04 * 0.90 rounds to SGD 2.25, making this
    # secondary rice supplier cheaper than Harvest's SGD 2.40 quote.
    SECONDARY_VENDOR_ID: (Decimal("1.0400"), 250, Decimal("0.1000")),
    RAPID_VENDOR_ID: (Decimal("1.1500"), 100, Decimal("0.0300")),
    SLOW_VENDOR_ID: (Decimal("0.9500"), 500, Decimal("0.0400")),
}


def build_vendor_offer_seeds() -> tuple[VendorOfferSeed, ...]:
    """Build private vendor/SKU stock and local deterministic price inputs."""

    offers: list[VendorOfferSeed] = []
    for item_index, item in enumerate(ITEM_SEEDS):
        for vendor_index, vendor in enumerate(VENDOR_SEEDS):
            multiplier, threshold, discount = _OFFER_TERMS[vendor.vendor_id]
            available_qty = 900 + item_index * 17 + vendor_index * 113

            if item.sku == RICE_SKU:
                available_qty = {
                    PREFERRED_VENDOR_ID: 2_000,
                    SECONDARY_VENDOR_ID: 1_600,
                    RAPID_VENDOR_ID: 600,
                    SLOW_VENDOR_ID: 3_000,
                }[vendor.vendor_id]
            elif item.sku == OOS_SKU and vendor.vendor_id == SECONDARY_VENDOR_ID:
                available_qty = 0

            offers.append(
                VendorOfferSeed(
                    vendor_id=vendor.vendor_id,
                    sku=item.sku,
                    available_qty=available_qty,
                    price_multiplier=multiplier,
                    bulk_discount_threshold=threshold,
                    bulk_discount_rate=discount,
                )
            )

    return tuple(offers)


VENDOR_OFFER_SEEDS: tuple[VendorOfferSeed, ...] = build_vendor_offer_seeds()


__all__ = [
    "EXPIRED_LOT_ID",
    "EXPIRED_LOT_SKU",
    "ITEM_SEEDS",
    "LIVE_LOT_ID",
    "OOS_SKU",
    "PREFERRED_VENDOR_ID",
    "RAPID_VENDOR_ID",
    "RICE_SKU",
    "SECONDARY_VENDOR_ID",
    "SLOW_VENDOR_ID",
    "VENDOR_OFFER_SEEDS",
    "VENDOR_SEEDS",
    "ItemSeed",
    "LotSeed",
    "VendorOfferSeed",
    "VendorSeed",
    "build_lot_seeds",
    "build_vendor_offer_seeds",
    "utc_today",
]
