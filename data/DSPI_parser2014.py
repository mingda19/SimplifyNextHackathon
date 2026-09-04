#!/usr/bin/env python
"""
DSPI wide -> tidy time-series matrix.

Turns SingStat's Domestic Supply Price Index export into a matrix where each
ROW is a month and each COLUMN is a commodity (i.e. one feature per commodity),
covering 2014-01 onwards.

Cleaning steps, in order:
  1. Parse the `YYYYMon` month headers into real dates.
  2. Transpose: months become rows, commodities become columns.
  3. Sort ascending by date.
  4. Drop every row before 2014-01.
  5. Drop every column with no data at all in the retained window.

Deliberately NOT done here (separate scripts, per the plan):
  - backfilling / imputation of gaps
  - feature selection of specific commodities
Missing values are left as empty cells so the backfill policy can see them.

    python data/DSPI_parser2014.py
    python data/DSPI_parser2014.py --start 2010-01 -o data/dspi_2010.csv
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
DEFAULT_IN = HERE / (
    "DomesticSupplyPriceIndexByCommodityGroup3DigitLevelBaseYear2023100Monthly.csv"
)
DEFAULT_OUT = HERE / "dspi_2014_onwards.csv"
DEFAULT_START = "2014-01"

# SingStat writes missing observations as the literal string `na`.
NA_TOKENS = ["na", "NA", "n.a.", "-", ""]

_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}
_COL_RE = re.compile(r"^(\d{4})([A-Za-z]{3})$")


def parse_month(col: str) -> pd.Timestamp | None:
    """`2026Jun` -> Timestamp('2026-06-01'). None if it isn't a month header."""
    m = _COL_RE.match(col.strip())
    if not m:
        return None
    month = _MONTHS.get(m.group(2).title())
    if month is None:
        return None
    return pd.Timestamp(year=int(m.group(1)), month=month, day=1)


def load_wide(path: Path) -> pd.DataFrame:
    """
    Read the raw export: one row per commodity, one column per month.

    Uses a real CSV parser rather than splitting on commas — many commodity
    names contain commas and are quoted ("Meat Of Bovine Animals, Fresh, ...").
    """
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    if df.columns[0] != "DataSeries":
        raise ValueError(f"expected first column 'DataSeries', got {df.columns[0]!r}")

    df["DataSeries"] = df["DataSeries"].str.strip()
    dupes = df["DataSeries"][df["DataSeries"].duplicated()].tolist()
    if dupes:
        raise ValueError(f"duplicate commodity names would collide on transpose: {dupes}")

    return df.set_index("DataSeries")


def transpose_to_timeseries(wide: pd.DataFrame) -> pd.DataFrame:
    """
    Months -> rows, commodities -> columns, sorted ascending by date.

    NOTE: the source columns are NOT in chronological order. The export is a
    rotated descending sequence — it starts at 1989Dec, counts down to 1974Jan,
    then jumps to 2026Jun and counts down to 1990Jan. Reading positionally
    would silently scramble the series, so every header is parsed into a real
    date and the frame is sorted by it.
    """
    dates = {col: parse_month(col) for col in wide.columns}
    unparsed = [c for c, d in dates.items() if d is None]
    if unparsed:
        raise ValueError(f"unparseable month headers: {unparsed[:10]}")

    ts = wide.T                                   # months -> rows
    ts.index = pd.DatetimeIndex([dates[c] for c in wide.columns], name="date")
    ts = ts.sort_index()                          # fix the rotation

    if ts.index.has_duplicates:
        dup = ts.index[ts.index.duplicated()].unique().tolist()
        raise ValueError(f"duplicate months in source: {dup[:10]}")

    # `na` -> NaN, everything else -> float
    ts = ts.replace(NA_TOKENS, pd.NA)
    ts = ts.apply(pd.to_numeric, errors="coerce")
    ts.columns.name = "commodity"
    return ts


def clean(ts: pd.DataFrame, start: str = DEFAULT_START) -> tuple[pd.DataFrame, dict]:
    """Cut to `start` onwards, then drop columns with no data in that window."""
    cutoff = pd.Timestamp(start)
    before_rows, before_cols = ts.shape

    ts = ts.loc[ts.index >= cutoff]

    # Columns are dropped based on the RETAINED window, not full history: a
    # commodity that only ever reported before 2014 is useless as a feature here.
    empty = ts.columns[ts.notna().sum() == 0].tolist()
    ts = ts.drop(columns=empty)

    stats = {
        "rows_before": before_rows,
        "rows_after": len(ts),
        "cols_before": before_cols,
        "cols_after": ts.shape[1],
        "dropped_empty": empty,
        "coverage": (ts.notna().sum().sum() / ts.size) if ts.size else 0.0,
    }
    return ts, stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-i", "--input", type=Path, default=DEFAULT_IN)
    ap.add_argument("-o", "--output", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--start", default=DEFAULT_START,
                    help=f"earliest month to keep, YYYY-MM (default {DEFAULT_START})")
    args = ap.parse_args()

    if not args.input.exists():
        print(f"input not found: {args.input}", file=sys.stderr)
        return 1

    wide = load_wide(args.input)
    ts = transpose_to_timeseries(wide)
    ts, st = clean(ts, args.start)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    # NaN -> empty cell, so the backfill script can see the gaps.
    ts.to_csv(args.output, index=True, na_rep="")

    print(f"  in   {args.input.name}")
    print(f"  out  {args.output}")
    print(f"  rows {st['rows_before']} -> {st['rows_after']}"
          f"   ({ts.index.min():%Y-%m} .. {ts.index.max():%Y-%m})")
    print(f"  cols {st['cols_before']} -> {st['cols_after']}"
          f"   ({len(st['dropped_empty'])} dropped, no data since {args.start})")
    print(f"  coverage {st['coverage']:.1%} non-missing"
          f"   ({int(ts.isna().sum().sum())} gaps left for the backfill script)")
    if st["dropped_empty"]:
        print("\n  dropped:")
        for name in st["dropped_empty"]:
            print(f"    - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
