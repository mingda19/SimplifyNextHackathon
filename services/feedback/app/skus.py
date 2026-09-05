"""SKU catalogue and multilingual alias table for the feedback matcher.

The catalogue is now LIVE -- `app.catalogue.load_items()` reads it from
workstream 1's `GET /inventory`. This module only adds the two things the
inventory API cannot supply:

  1. ALIASES -- multilingual surface terms (English, Singlish, Mandarin, Malay,
     Tamil) mapped to real SKU codes.
  2. QUALIFIER_OVERLAY -- dietary/texture flags the matcher's guard needs, which
     `items` does not carry.

Every alias target is asserted against the live catalogue at import (see
_validate), so a rename in W/G's seed data fails loudly here instead of
silently resolving `mentioned_skus` to codes that do not exist.

Terms deliberately WITHOUT a target -- bread, soft/pureed food, adult diapers --
are real gaps in the charity's catalogue. The matcher reports them as
unmatched, which is the highest-signal output the feedback loop produces:
a need nobody has stocked for.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.catalogue import SKUItem, load_items

logger = logging.getLogger("feedback.skus")

# Controlled vocabulary of dietary/texture qualifiers the matcher's guard
# checks against. matcher.QUALIFIER_PATTERNS keys off these exact names.
GLUTEN_FREE = "gluten_free"
HALAL = "halal"
SUGAR_FREE = "sugar_free"
LOW_SODIUM = "low_sodium"
LACTOSE_FREE = "lactose_free"
VEGETARIAN = "vegetarian"
NUT_FREE = "nut_free"
SOFT_TEXTURE = "soft_texture"
MSG_FREE = "msg_free"
# The catalogue stocks INFANT diapers only (DIAPERS-M-40PK, category INFANT).
# Without this, "adult diapers" matched the infant SKU — a false match, which
# the matcher's whole guard exists to prevent.
ADULT_SIZED = "adult_sized"

ALL_QUALIFIERS = {
    GLUTEN_FREE, HALAL, SUGAR_FREE, LOW_SODIUM, LACTOSE_FREE,
    VEGETARIAN, NUT_FREE, SOFT_TEXTURE, MSG_FREE, ADULT_SIZED,
}

# Dietary/texture flags the inventory API does not model. Keyed on REAL SKUs.
# Conservative on purpose: the matcher refuses a match when a qualifier is
# requested and the candidate doesn't carry it, so an over-claimed flag here
# produces a false match — the one failure mode the matcher exists to prevent.
QUALIFIER_OVERLAY: dict[str, frozenset] = {
    "TOFU-300G": frozenset({VEGETARIAN, LACTOSE_FREE, NUT_FREE}),
    "BEANS-CANNED-400G": frozenset({VEGETARIAN, NUT_FREE}),
    "CHICKPEAS-CANNED-400G": frozenset({VEGETARIAN, NUT_FREE}),
    "TOMATOES-CANNED-400G": frozenset({VEGETARIAN, NUT_FREE, LACTOSE_FREE}),
    "VEGETABLES-MIXED-1KG": frozenset({VEGETARIAN, NUT_FREE, LACTOSE_FREE}),
    "CARROTS-1KG": frozenset({VEGETARIAN, NUT_FREE, LACTOSE_FREE}),
    "POTATOES-5KG": frozenset({VEGETARIAN, NUT_FREE, LACTOSE_FREE}),
    "ONIONS-2KG": frozenset({VEGETARIAN, NUT_FREE, LACTOSE_FREE}),
    "SOY-MILK-1L": frozenset({VEGETARIAN, LACTOSE_FREE}),
    "RICE-5KG": frozenset({VEGETARIAN, GLUTEN_FREE, NUT_FREE, LACTOSE_FREE}),
    "SALT-500G": frozenset({VEGETARIAN, GLUTEN_FREE, NUT_FREE, LACTOSE_FREE}),
    "OIL-2L": frozenset({VEGETARIAN, GLUTEN_FREE, NUT_FREE, LACTOSE_FREE}),
}


def _build_catalogue() -> list[SKUItem]:
    return [
        SKUItem(
            sku=i["sku"], name=i["name"], category=i.get("category", ""),
            qualifiers=QUALIFIER_OVERLAY.get(i["sku"], frozenset()),
        )
        for i in load_items()
    ]


SKU_CATALOGUE: list[SKUItem] = _build_catalogue()
SKU_BY_CODE: dict[str, SKUItem] = {i.sku: i for i in SKU_CATALOGUE}


# Curated multilingual alias table (matcher layer 2). Surface term -> REAL SKU.
# Literal by design; layer 3 (fuzzy) catches typos and transcription noise.
ALIASES: dict[str, str] = {
    # rice
    "rice": "RICE-5KG", "白米": "RICE-5KG", "大米": "RICE-5KG",
    "beras": "RICE-5KG", "arisi": "RICE-5KG", "அரிசி": "RICE-5KG",
    # cooking oil
    "cooking oil": "OIL-2L", "oil": "OIL-2L", "食油": "OIL-2L",
    "minyak masak": "OIL-2L", "minyak": "OIL-2L", "ஆயில்": "OIL-2L",
    # noodles
    "instant noodles": "NOODLES-1KG", "noodles": "NOODLES-1KG",
    "maggi": "NOODLES-1KG", "泡面": "NOODLES-1KG", "mee": "NOODLES-1KG",
    "面条": "NOODLES-1KG", "mi": "NOODLES-1KG",
    # infant formula / milk powder
    "milk powder": "INFANT-FORMULA-900G", "baby formula": "INFANT-FORMULA-900G",
    "formula": "INFANT-FORMULA-900G", "奶粉": "INFANT-FORMULA-900G",
    "susu tepung": "INFANT-FORMULA-900G", "பால் பொடி": "INFANT-FORMULA-900G",
    # fresh milk
    "milk": "MILK-UHT-1L", "牛奶": "MILK-UHT-1L", "susu": "MILK-UHT-1L",
    "soy milk": "SOY-MILK-1L", "豆奶": "SOY-MILK-1L",
    # canned protein
    "sardine": "SARDINES-CANNED-155G", "sardines": "SARDINES-CANNED-155G",
    "沙丁鱼": "SARDINES-CANNED-155G", "ikan sardin": "SARDINES-CANNED-155G",
    "tuna": "TUNA-CANNED-185G", "金枪鱼": "TUNA-CANNED-185G",
    "beans": "BEANS-CANNED-400G", "canned beans": "BEANS-CANNED-400G",
    "kacang": "BEANS-CANNED-400G",
    "chickpeas": "CHICKPEAS-CANNED-400G", "kacang kuda": "CHICKPEAS-CANNED-400G",
    "tomatoes": "TOMATOES-CANNED-400G", "canned tomatoes": "TOMATOES-CANNED-400G",
    # staples
    "sugar": "SUGAR-1KG", "糖": "SUGAR-1KG", "gula": "SUGAR-1KG", "சர்க்கரை": "SUGAR-1KG",
    "salt": "SALT-500G", "盐": "SALT-500G", "garam": "SALT-500G",
    "flour": "FLOUR-1KG", "面粉": "FLOUR-1KG", "tepung": "FLOUR-1KG",
    # produce
    "vegetables": "VEGETABLES-MIXED-1KG", "vegetable": "VEGETABLES-MIXED-1KG",
    "青菜": "VEGETABLES-MIXED-1KG", "菜": "VEGETABLES-MIXED-1KG",
    "sayur": "VEGETABLES-MIXED-1KG", "காய்கறி": "VEGETABLES-MIXED-1KG",
    "frozen vegetables": "VEGETABLES-MIXED-1KG",
    "carrots": "CARROTS-1KG", "胡萝卜": "CARROTS-1KG", "lobak": "CARROTS-1KG",
    "potatoes": "POTATOES-5KG", "土豆": "POTATOES-5KG", "kentang": "POTATOES-5KG",
    "onions": "ONIONS-2KG", "洋葱": "ONIONS-2KG", "bawang": "ONIONS-2KG",
    "canned fruit": "FRUIT-CANNED-825G", "fruit": "FRUIT-CANNED-825G",
    "水果": "FRUIT-CANNED-825G", "buah": "FRUIT-CANNED-825G",
    # protein
    "eggs": "EGGS-TRAY30", "egg": "EGGS-TRAY30", "鸡蛋": "EGGS-TRAY30",
    "telur": "EGGS-TRAY30", "முட்டை": "EGGS-TRAY30",
    "chicken": "CHICKEN-FROZEN-1KG", "鸡肉": "CHICKEN-FROZEN-1KG",
    "ayam": "CHICKEN-FROZEN-1KG", "கோழி": "CHICKEN-FROZEN-1KG",
    "fish": "FISH-FROZEN-1KG", "鱼": "FISH-FROZEN-1KG",
    "ikan": "FISH-FROZEN-1KG", "மீன்": "FISH-FROZEN-1KG",
    "tofu": "TOFU-300G", "豆腐": "TOFU-300G", "tauhu": "TOFU-300G",
    # breakfast
    "cereal": "CEREAL-500G", "麦片": "CEREAL-500G",
    "oats": "OATS-1KG", "porridge": "OATS-1KG", "粥": "OATS-1KG", "கஞ்சி": "OATS-1KG",
    "biscuits": "BISCUITS-500G", "饼干": "BISCUITS-500G", "biskut": "BISCUITS-500G",
    # spreads
    "jam": "JAM-450G", "果酱": "JAM-450G",
    "peanut butter": "PEANUT-BUTTER-500G", "花生酱": "PEANUT-BUTTER-500G",
    # beverages
    "coffee": "COFFEE-500G", "咖啡": "COFFEE-500G", "kopi": "COFFEE-500G", "காபி": "COFFEE-500G",
    "tea": "TEA-100BAG", "茶": "TEA-100BAG", "teh": "TEA-100BAG", "தேநீர்": "TEA-100BAG",
    # NB: no bare "water" alias — it fuzzy-matches "weather" at 0.83, above the
    # 0.72 accept threshold, producing a false match on "nice weather today".
    "drinking water": "WATER-1-5L", "bottled water": "WATER-1-5L", "水": "WATER-1-5L",
    # hygiene / household
    "soap": "HYGIENE-SOAP-4PK", "肥皂": "HYGIENE-SOAP-4PK", "sabun": "HYGIENE-SOAP-4PK",
    "shampoo": "SHAMPOO-500ML", "洗发水": "SHAMPOO-500ML", "syampu": "SHAMPOO-500ML",
    "toothpaste": "TOOTHPASTE-100G", "牙膏": "TOOTHPASTE-100G",
    "detergent": "DETERGENT-2KG", "洗衣粉": "DETERGENT-2KG",
    "dishwashing liquid": "DISHWASH-LIQUID-1L", "洗洁精": "DISHWASH-LIQUID-1L",
    "sanitary pads": "SANITARY-PADS-20PK", "pads": "SANITARY-PADS-20PK",
    "masks": "MASKS-50PK", "口罩": "MASKS-50PK",
    "hand sanitiser": "HAND-SANITISER-500ML", "sanitizer": "HAND-SANITISER-500ML",
    # Infant diapers only. An adult-sizing request is refused by the qualifier
    # guard and reported as near_sku instead — see ADULT_SIZED.
    "diapers": "DIAPERS-M-40PK", "diaper": "DIAPERS-M-40PK",
    "尿布": "DIAPERS-M-40PK", "lampin": "DIAPERS-M-40PK",
}

# Terms with NO catalogue target. These are genuine gaps in what the charity
# stocks, and the matcher surfacing them is the point of the feedback loop.
# Listed so the gap is documented rather than looking like a missing alias.
KNOWN_GAPS = {
    "bread": "no bread SKU in the catalogue",
    "roti": "no bread SKU in the catalogue",
    "面包": "no bread SKU in the catalogue",
    "soft food": "no soft/pureed meal SKU in the catalogue",
    "pureed food": "no soft/pureed meal SKU in the catalogue",
    "adult diapers": "only infant diapers (DIAPERS-M-40PK) are stocked",
    "chapati": "no flatbread SKU in the catalogue",
}


def _validate() -> None:
    """Fail loudly if an alias points at a SKU the live catalogue doesn't have."""
    missing = sorted({s for s in ALIASES.values() if s not in SKU_BY_CODE})
    if missing:
        raise RuntimeError(
            f"ALIASES reference {len(missing)} SKU(s) absent from the live "
            f"inventory catalogue: {missing}. Either the seed data changed or an "
            f"alias is stale — fix app/skus.py rather than letting mentioned_skus "
            f"resolve to codes that do not exist."
        )
    stale = sorted({s for s in QUALIFIER_OVERLAY if s not in SKU_BY_CODE})
    if stale:
        logger.warning("QUALIFIER_OVERLAY has stale SKUs (ignored): %s", stale)


_validate()
