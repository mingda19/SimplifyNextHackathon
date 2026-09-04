#!/usr/bin/env python
"""
DSPI feature selection for the charity price forecaster.

SELECTION RULE
--------------
A price forecast is only actionable if the charity can act on it: buy early
when prices are rising, hold off when they are falling. That requires the good
to be STORABLE. Short-shelf-life items are excluded regardless of how important
they are, because you cannot stockpile them.

So this is NOT "what does a charity need most". It is "what can a charity
usefully time the purchase of".

Excluded on perishability despite being core basket items: fresh/chilled/frozen
fish, fresh meat and offal, fresh bovine meat, eggs, fresh vegetables, fresh
fruit and nuts, butter and milk fats.

Kept from the same aisles because the ambient/canned/dry form stores for months:
canned fish, canned meat, preserved vegetables, preserved fruit, rice, flour,
cereal preparations, starches, cooking oils, sugar, spices, coffee.

`Milk & Cream & Milk Products` is kept on the strength of milk powder, the most
common long-life charity staple, even though the SITC line also bundles fresh
milk. See MIXED_LINE_NOTES.

Non-food goods are kept where they store indefinitely: soap, paper goods, pest
control, clothing, footwear, furniture and bedding, linens, toys.

Deliberately excluded: food-adjacent goods (cheese, juices, confectionery,
cocoa, seafood, oilseeds), medical and pharmaceutical lines, household
electrical and base-metal equipment, and fuel. Metals, machinery, chemicals,
plastics, electronics, vehicles and construction were never candidates.

Run this file to validate every name against the parsed CSV, and to write the
final feature matrix:

    python data/dspi_features.py            # validate + report
    python data/dspi_features.py --write    # also emit dspi_features_final.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PARSED = HERE / "dspi_2014_onwards.csv"
FINAL = HERE / "dspi_features_final.csv"

# --------------------------------------------------------------------------
# SELECTED — storable goods a charity can usefully time the purchase of.
# Aliases are used for chart labels, SKU joins and `items.dspi_series`.
# --------------------------------------------------------------------------
SELECTED: dict[str, str] = {
    # -- dry staples -------------------------------------------------------
    "Rice": "rice",
    "Meal & Flour Of Wheat & Flour Of Meslin": "wheat_flour",
    "Cereal Preparations & Preparations Of Flour Or Starch Of Fruits Or Vegetables": "cereal_prep",
    "Starches, Inulin & Wheat Gluten; Albuminoidal Substances; Glues": "starch",
    # -- canned / preserved produce ----------------------------------------
    "Vegetables, Roots & Tubers, Prepared Or Preserved Nes": "veg_preserved",
    "Fruit, Preserved, & Fruit Preparations Excl Fruit Juices": "fruit_preserved",
    # -- canned protein ----------------------------------------------------
    "Fish, Crustaceans, Molluscs & Other Aquatic Invertebrates, Prepared Or Preserved Nes": "fish_canned",
    "Meat & Edible Meat Offal, Prepared Or Preserved Nes": "meat_canned",
    # -- dairy (milk powder) -----------------------------------------------
    "Milk & Cream & Milk Products Other Than Butter Or Cheese": "milk",
    # -- cooking essentials -------------------------------------------------
    "Fixed Vegetable Fats & Oils, 'Soft', Crude, Refined Or Fractionated": "veg_oil_soft",
    "Fixed Vegetable Fats & Oils, Crude, Refined Or Fractionated, Other Than Soft": "veg_oil_other",
    "Sugars, Molasses & Honey": "sugar",
    "Spices": "spices",
    # -- prepared foods & beverages ----------------------------------------
    "Edible Products & Preparations Nes": "edible_prep",
    "Coffee & Coffee Substitutes": "coffee",
    "Non-Alcoholic Beverages Nes": "beverages_nonalc",
    # -- household consumables ---------------------------------------------
    "Soap, Cleansing & Polishing Preparations": "soap",
    "Paper & Paperboard, Cut To Size Or Shape, & Articles Of Paper Or Paperboard": "paper_goods",
    "Insecticides, Rodenticides, Fungicides, Herbicides, Anti-Sprouting Products & Plant-Growth Regulators, Disinfectants & Similar Products, In Forms Or Packings For Sale Or As Preparations Or Articles": "pest_control",
    # -- clothing drives ----------------------------------------------------
    "Articles Of Apparel, Of Textile Fabrics, Whether Or Not Knitted Or Crocheted Nes": "apparel",
    "Men's Or Boys' Coats, Capes, Jackets, Suits, Blazers, Trousers, Shorts, Shirts, Underwear, Nightwear & Similar Articles Of Textile Fabrics, Not Knitted Or Crocheted Excl Subgroup 845.2": "apparel_mens",
    "Women's Or Girls' Coats, Capes, Jackets, Suits, Trousers, Shorts, Shirts, Dresses & Skirts, Underwear, Nightwear & Similar Articles Of Textile Fabrics, Not Knitted Or Crocheted Excl Subgroup 845.2": "apparel_womens",
    "Footwear": "footwear",
    # -- durable goods for homes & shelters ---------------------------------
    "Furniture & Parts Thereof; Bedding, Mattresses, Mattress Supports, Cushions & Similar Stuffed Furnishings": "furniture_bedding",
    "Made-Up Articles, Wholly Or Chiefly Of Textile Materials Nes": "linens",
    "Baby Carriages, Toys, Games & Sporting Goods": "toys_baby",
}

# Excluded on the storability rule, NOT on relevance. These remain important to
# charities — they simply cannot be stockpiled, so a price forecast on them is
# not actionable. Kept here so the decision is visible rather than implicit.
EXCLUDED_PERISHABLE: dict[str, str] = {
    "Vegetables, Fresh, Chilled, Frozen Or Simply Preserved Incl Dried Leguminous Vegetables; Roots, Tubers & Other Edible Vegetable Products Nes, Fresh Or Dried": "fresh produce",
    "Fruit & Nuts Excl Oil Nuts, Fresh Or Dried": "fresh produce",
    "Fish, Fresh (Live Or Dead), Chilled Or Frozen": "fresh protein",
    "Meat Of Bovine Animals, Fresh, Chilled Or Frozen": "fresh protein",
    "Other Meat & Edible Meat Offal, Fresh, Chilled Or Frozen Excl Meat & Meat Offal Unfit Or Unsuitable For Human Consumption": "fresh protein",
    "Eggs, Birds, & Egg Yolks, Fresh, Dried Or Otherwise Preserved, Sweetened Or Not; Egg Albumin": "short shelf life",
    "Butter & Other Fats & Oils Derived From Milk": "chilled dairy",
}

# SITC lines that bundle storable and perishable goods together. The call made
# is recorded here so it can be revisited without re-deriving the reasoning.
MIXED_LINE_NOTES: dict[str, str] = {
    "milk": "KEPT — line bundles fresh milk with milk POWDER; powder is the "
            "long-life charity staple and dominates charity procurement.",
    "veg_preserved": "KEPT — 'prepared or preserved' only; the fresh line is separate.",
    "fruit_preserved": "KEPT — 'preserved' only; excludes fruit juices.",
    "fish_canned": "KEPT — 'prepared or preserved'; the fresh line is excluded.",
    "meat_canned": "KEPT — 'prepared or preserved'; fresh meat lines excluded.",
}


def load_frame():
    import pandas as pd
    if not PARSED.exists():
        raise SystemExit(f"run DSPI_parser2014.py first — {PARSED} not found")
    return pd.read_csv(PARSED, index_col="date", parse_dates=True)


def build_final(df=None):
    """Return the final feature matrix: months x selected commodities (aliased)."""
    import pandas as pd  # noqa: F401
    df = load_frame() if df is None else df
    missing = [c for c in SELECTED if c not in df.columns]
    if missing:
        raise SystemExit(f"{len(missing)} selected column(s) not in parsed CSV: {missing[:3]}")
    out = df[list(SELECTED)].rename(columns=SELECTED)
    out.columns.name = "commodity"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="emit dspi_features_final.csv")
    args = ap.parse_args()

    df = load_frame()
    cols = set(df.columns)
    complete = {c for c in df.columns if df[c].notna().all()}

    bad = [n for n in (*SELECTED, *EXCLUDED_PERISHABLE) if n not in cols]
    not_complete = [n for n in SELECTED if n not in complete]
    if bad:
        print("  ERROR names absent from the parsed CSV:")
        for n in bad:
            print(f"    - {n[:88]}")
        return 1
    if not_complete:
        print("  ERROR selected an incomplete column:")
        for n in not_complete:
            print(f"    - {n[:88]}")
        return 1

    print(f"  parsed columns             : {len(cols)} ({len(complete)} complete)")
    print(f"  SELECTED (storable)        : {len(SELECTED)}")
    print(f"  excluded — perishable      : {len(EXCLUDED_PERISHABLE)}")
    print(f"  excluded — not relevant    : "
          f"{len(complete) - len(SELECTED) - len(EXCLUDED_PERISHABLE)}")
    print("\n  all names validated against the parsed CSV")

    if args.write:
        final = build_final(df)
        final.to_csv(FINAL, na_rep="")
        print(f"\n  wrote {FINAL}")
        print(f"        {final.shape[0]} months x {final.shape[1]} commodities "
              f"({final.index.min():%Y-%m} .. {final.index.max():%Y-%m})")
        print(f"        missing cells: {int(final.isna().sum().sum())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
