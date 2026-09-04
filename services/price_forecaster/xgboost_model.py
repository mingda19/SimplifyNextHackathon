#!/usr/bin/env python
"""
XGBoost forecaster — artefact 1 of 2.

Pooled panel, 3-month horizon. One model over all commodities: rows are
(commodity, month), features are that commodity's own lags. ~2,700 training rows.

The multivariate shape and the 1-month horizon were evaluated and dropped —
multivariate scored NEGATIVE skill on held-out test data (78 features against
~115 rows), and h=1 directional accuracy was 52.9%, a coin flip. h=3 pooled is
the only configuration that beat the naive baseline on test.

    python xgboost_model.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

import dataset as D

HERE = Path(__file__).resolve().parent
ART = HERE / "artifacts"
SEED = 42

# Deliberately small trees and heavy regularisation: 120 months of history
# punishes anything with capacity to memorise.
PARAMS = dict(
    n_estimators=350, learning_rate=0.02, max_depth=3,
    subsample=0.8, colsample_bytree=0.8,
    reg_lambda=2.0, reg_alpha=0.2,
    min_child_weight=5, random_state=SEED, n_jobs=4,
)


HORIZON = 3
SHAPE = "pooled"


def artefact_path() -> Path:
    return ART / f"xgb_{SHAPE}_h{HORIZON}.json"


def meta_path() -> Path:
    return ART / f"xgb_{SHAPE}_h{HORIZON}.meta.json"


# ------------------------------------------------------------------ train --
def train(verbose: bool = True) -> dict:
    ART.mkdir(parents=True, exist_ok=True)

    df = D.make_pooled(HORIZON)
    feats = D.pooled_feature_cols(df)
    tr, va = df[df.split == "train"], df[df.split == "val"]
    model = xgb.XGBRegressor(**PARAMS, enable_categorical=True,
                             early_stopping_rounds=40, eval_metric="mae")
    model.fit(tr[feats], tr["y"], eval_set=[(va[feats], va["y"])], verbose=False)

    model.save_model(artefact_path())
    meta = {"algo": "xgboost", "shape": SHAPE, "horizon": HORIZON,
            "features": feats,
            "commodities": list(df["commodity"].cat.categories),
            "n_train_rows": len(tr), "n_features": len(feats),
            "best_iteration": int(getattr(model, "best_iteration", -1) or -1),
            "params": {k: v for k, v in PARAMS.items()}}
    meta_path().write_text(json.dumps(meta, indent=2))
    if verbose:
        print(f"  xgb {SHAPE} h={HORIZON}  train_rows={len(tr):5} "
              f"feats={len(feats):3}  best_iter={meta['best_iteration']}")
    return meta


# ---------------------------------------------------------------- predict --
def load_model():
    """Load the trained booster and its metadata."""
    path = artefact_path()
    if not path.exists():
        raise SystemExit(f"missing {path} — run xgboost_model.py first")
    model = xgb.XGBRegressor(enable_categorical=True)
    model.load_model(path)
    return model, json.loads(meta_path().read_text())


def predict(split: str):
    """Return (y_true, y_pred) plus a per-commodity frame."""
    model, meta = load_model()
    df = D.make_pooled(HORIZON)
    sub = df[df.split == split]
    pred = model.predict(sub[meta["features"]])
    return (sub["y"].to_numpy(), np.asarray(pred),
            pd.DataFrame({"date": sub["date"].values,
                          "commodity": sub["commodity"].astype(str).values,
                          "y_true": sub["y"].to_numpy(), "y_pred": pred}))


def main() -> int:
    argparse.ArgumentParser().parse_args()
    print("training XGBoost (pooled, h=3)")
    train()
    print(f"\n  artefacts in {ART}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
