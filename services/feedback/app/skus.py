"""SKU catalogue and multilingual alias table for the feedback matcher.

This is a local stub of workstream 1's `items` table (see README "Workstream 1 ·
Inventory Service" schema) — just enough shape (sku, name, category, plus the
qualifier flags this service needs) to develop and test the matcher without a
live Postgres connection. `GET /inventory` from W's service is the real source
of truth at runtime; this module is what the matcher and its golden tests run
against until that integration lands.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Controlled vocabulary of dietary/texture qualifiers the matcher's guard
# checks against. Extend this list, not ad-hoc strings, if a new qualifier
# type comes up — `matcher.QUALIFIER_PATTERNS` keys off these exact names.
GLUTEN_FREE = "gluten_free"
HALAL = "halal"
SUGAR_FREE = "sugar_free"
LOW_SODIUM = "low_sodium"
LACTOSE_FREE = "lactose_free"
VEGETARIAN = "vegetarian"
NUT_FREE = "nut_free"
SOFT_TEXTURE = "soft_texture"  # pureed / soft / cannot-chew
MSG_FREE = "msg_free"

ALL_QUALIFIERS = {
    GLUTEN_FREE,
    HALAL,
    SUGAR_FREE,
    LOW_SODIUM,
    LACTOSE_FREE,
    VEGETARIAN,
    NUT_FREE,
    SOFT_TEXTURE,
    MSG_FREE,
}


@dataclass(frozen=True)
class SKUItem:
    sku: str
    name: str
    category: str
    qualifiers: frozenset = field(default_factory=frozenset)


SKU_CATALOGUE: list[SKUItem] = [
    SKUItem("RICE-5KG", "White rice 5kg", "staples"),
    SKUItem("RICE-10KG", "White rice 10kg", "staples"),
    SKUItem("BREAD-LOAF", "White bread loaf", "staples"),
    SKUItem("COOKING-OIL-1L", "Cooking oil 1L", "staples"),
    SKUItem("NOODLE-INST", "Instant noodles", "staples"),
    SKUItem("MILK-POWDER", "Milk powder / infant formula", "dietary_accessibility"),
    SKUItem("CANNED-SARDINE", "Canned sardines", "protein"),
    SKUItem("CANNED-BEANS", "Canned beans", "protein", frozenset({VEGETARIAN, NUT_FREE})),
    SKUItem("SUGAR-1KG", "Sugar 1kg", "staples"),
    SKUItem("VEG-LEAFY", "Fresh leafy vegetables", "produce"),
    SKUItem("VEG-FROZEN-MIX", "Frozen mixed vegetables", "produce"),
    SKUItem("EGGS-DOZEN", "Eggs (dozen)", "protein"),
    SKUItem("INSTANT-COFFEE", "Instant coffee", "beverages"),
    SKUItem("TEA-BAGS", "Tea bags", "beverages"),
    SKUItem("TOFU", "Tofu", "protein", frozenset({VEGETARIAN, LACTOSE_FREE, NUT_FREE})),
    SKUItem("CHICKEN-FROZEN", "Frozen chicken", "protein"),
    SKUItem("FISH-FROZEN", "Frozen fish", "protein"),
    SKUItem("SOFT-FOOD-PACK", "Soft / pureed meal pack for elderly", "soft_foods", frozenset({SOFT_TEXTURE})),
    SKUItem("DIAPERS-ADULT", "Adult diapers", "hygiene"),
    SKUItem("INSTANT-CEREAL", "Instant cereal porridge", "staples"),
]

SKU_BY_CODE: dict[str, SKUItem] = {item.sku: item for item in SKU_CATALOGUE}


# Curated multilingual alias table (layer 2). Surface term -> SKU code.
# Covers English, Singlish shorthand, Mandarin, Malay, and Tamil (transliterated)
# terms actually seen in the seed corpus. Deliberately literal, no fuzziness
# here — layer 3 (fuzzy) is what catches typos and voice-transcription noise.
ALIASES: dict[str, str] = {
    # rice
    "rice": "RICE-5KG",
    "白米": "RICE-5KG",
    "大米": "RICE-5KG",
    "beras": "RICE-5KG",
    "arisi": "RICE-5KG",
    "அரிசி": "RICE-5KG",  # Tamil, native script
    # bread
    "bread": "BREAD-LOAF",
    "面包": "BREAD-LOAF",
    "roti": "BREAD-LOAF",
    "ரொட்டி": "BREAD-LOAF",  # Tamil, native script
    # cooking oil
    "cooking oil": "COOKING-OIL-1L",
    "oil": "COOKING-OIL-1L",
    "食油": "COOKING-OIL-1L",
    "minyak masak": "COOKING-OIL-1L",
    "minyak": "COOKING-OIL-1L",
    # instant noodles
    "instant noodles": "NOODLE-INST",
    "noodles": "NOODLE-INST",
    "maggi": "NOODLE-INST",
    "泡面": "NOODLE-INST",
    "mee": "NOODLE-INST",
    # milk powder / formula
    "milk powder": "MILK-POWDER",
    "baby formula": "MILK-POWDER",
    "formula": "MILK-POWDER",
    "奶粉": "MILK-POWDER",
    "susu tepung": "MILK-POWDER",
    "பால் பொடி": "MILK-POWDER",  # Tamil, native script
    # sardines
    "sardine": "CANNED-SARDINE",
    "sardines": "CANNED-SARDINE",
    "沙丁鱼": "CANNED-SARDINE",
    # beans
    "beans": "CANNED-BEANS",
    "canned beans": "CANNED-BEANS",
    # sugar
    "sugar": "SUGAR-1KG",
    "糖": "SUGAR-1KG",
    "gula": "SUGAR-1KG",
    "சர்க்கரை": "SUGAR-1KG",  # Tamil, native script
    # vegetables
    "vegetables": "VEG-LEAFY",
    "vegetable": "VEG-LEAFY",
    "青菜": "VEG-LEAFY",
    "菜": "VEG-LEAFY",
    "sayur": "VEG-LEAFY",
    "காய்கறி": "VEG-LEAFY",  # Tamil, native script
    "frozen vegetables": "VEG-FROZEN-MIX",
    # eggs
    "eggs": "EGGS-DOZEN",
    "egg": "EGGS-DOZEN",
    "鸡蛋": "EGGS-DOZEN",
    "telur": "EGGS-DOZEN",
    "முட்டை": "EGGS-DOZEN",  # Tamil, native script
    # coffee
    "coffee": "INSTANT-COFFEE",
    "咖啡": "INSTANT-COFFEE",
    "kopi": "INSTANT-COFFEE",
    "காபி": "INSTANT-COFFEE",  # Tamil, native script
    # tea
    "tea": "TEA-BAGS",
    "茶": "TEA-BAGS",
    "teh": "TEA-BAGS",
    "தேநீர்": "TEA-BAGS",  # Tamil, native script
    # tofu
    "tofu": "TOFU",
    "豆腐": "TOFU",
    "tauhu": "TOFU",
    # chicken
    "chicken": "CHICKEN-FROZEN",
    "鸡肉": "CHICKEN-FROZEN",
    "ayam": "CHICKEN-FROZEN",
    "கோழி": "CHICKEN-FROZEN",  # Tamil, native script
    # fish
    "fish": "FISH-FROZEN",
    "鱼": "FISH-FROZEN",
    "ikan": "FISH-FROZEN",
    "மீன்": "FISH-FROZEN",  # Tamil, native script
    # soft food
    "soft food": "SOFT-FOOD-PACK",
    "pureed food": "SOFT-FOOD-PACK",
    "soft meal": "SOFT-FOOD-PACK",
    # diapers
    "diapers": "DIAPERS-ADULT",
    "diaper": "DIAPERS-ADULT",
    "尿布": "DIAPERS-ADULT",
    "lampin": "DIAPERS-ADULT",
    # cereal / porridge
    "cereal": "INSTANT-CEREAL",
    "porridge": "INSTANT-CEREAL",
    "粥": "INSTANT-CEREAL",
    "கஞ்சி": "INSTANT-CEREAL",  # Tamil, native script
}
