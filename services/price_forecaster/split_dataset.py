#!/usr/bin/env python
"""
Chronological train / val / test split of the final DSPI feature matrix.

    test  = last 10% of months  (the future)
    val   = the 10% before that
    train = the remaining 80%   (the past)

Split is by DATE, never shuffled: shuffling a time series leaks the future into
training and makes every downstream score meaningless.

The three CSVs hold raw index levels, not engineered features. Lag construction
happens in `dataset.py` on the reassembled series, so that val/test rows can use
the genuinely-prior months that precede them instead of losing the first `L`
rows of each split to a cold start. That is not leakage — lags only look
backwards — but scalers are still fit on train alone.

    python split_dataset.py
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
DEFAULT_IN = HERE.parents[1] / "data" / "dspi_features_final.csv"
OUT_DIR = HERE / "data"

TEST_FRAC = 0.10
VAL_FRAC = 0.10


def split(df: pd.DataFrame, test_frac=TEST_FRAC, val_frac=VAL_FRAC):
    n = len(df)
    n_test = max(1, round(n * test_frac))
    n_val = max(1, round(n * val_frac))
    n_train = n - n_val - n_test
    if n_train <= 0:
        raise ValueError(f"not enough rows to split: {n}")
    return df.iloc[:n_train], df.iloc[n_train:n_train + n_val], df.iloc[n_train + n_val:]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-i", "--input", type=Path, default=DEFAULT_IN)
    ap.add_argument("-o", "--outdir", type=Path, default=OUT_DIR)
    args = ap.parse_args()

    if not args.input.exists():
        raise SystemExit(f"missing {args.input} — run data/dspi_features.py --write first")

    df = pd.read_csv(args.input, index_col="date", parse_dates=True).sort_index()
    if df.isna().any().any():
        raise SystemExit("input has missing values; the split expects a complete matrix")

    train, val, test = split(df)
    args.outdir.mkdir(parents=True, exist_ok=True)
    for name, part in (("train", train), ("val", val), ("test", test)):
        path = args.outdir / f"{name}.csv"
        part.to_csv(path)
        print(f"  {name:5} {len(part):3} months  "
              f"{part.index.min():%Y-%m} .. {part.index.max():%Y-%m}  -> {path.name}")

    # boundaries must be contiguous and strictly ordered
    assert train.index.max() < val.index.min() < val.index.max() < test.index.min()
    print(f"\n  {len(df)} months x {df.shape[1]} commodities, chronological, no overlap")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
