#!/usr/bin/env python
"""
XGBoost forecaster — artefact 1 of 2.

Trains one model per (shape, horizon). Shapes:

  pooled       one model over all commodities; rows are (commodity, month) and
               features are that commodity's own lags. ~2,700 training rows.
  multivariate one model over months; every commodity's lags in, every
               commodity's forward return out. ~115 training rows against 78
               features, so expect it to overfit — that is the comparison.

    python xgboost_model.py                      # all shapes x all horizons
    python xgboost_model.py --shape pooled --horizon 1
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


def artefact_path(shape: str, horizon: int) -> Path:
    return ART / f"xgb_{shape}_h{horizon}.json"


def meta_path(shape: str, horizon: int) -> Path:
    return ART / f"xgb_{shape}_h{horizon}.meta.json"


# ------------------------------------------------------------------ train --
def train(shape: str, horizon: int, verbose: bool = True) -> dict:
    ART.mkdir(parents=True, exist_ok=True)

    if shape == "pooled":
        df = D.make_pooled(horizon)
        feats = D.pooled_feature_cols(df)
        tr, va = df[df.split == "train"], df[df.split == "val"]
        model = xgb.XGBRegressor(**PARAMS, enable_categorical=True,
                                 early_stopping_rounds=40, eval_metric="mae")
        model.fit(tr[feats], tr["y"], eval_set=[(va[feats], va["y"])], verbose=False)
        n_train, n_feat = len(tr), len(feats)
        cats = list(df["commodity"].cat.categories)
    else:
        X, Y, split = D.make_multivariate(horizon)
        tr, va = split == "train", split == "val"
        model = xgb.XGBRegressor(**PARAMS, multi_strategy="multi_output_tree",
                                 early_stopping_rounds=40, eval_metric="mae")
        model.fit(X[tr], Y[tr], eval_set=[(X[va], Y[va])], verbose=False)
        feats = list(X.columns)
        n_train, n_feat = int(tr.sum()), X.shape[1]
        cats = list(Y.columns)

    model.save_model(artefact_path(shape, horizon))
    meta = {"algo": "xgboost", "shape": shape, "horizon": horizon,
            "features": feats, "commodities": cats,
            "n_train_rows": n_train, "n_features": n_feat,
            "best_iteration": int(getattr(model, "best_iteration", -1) or -1),
            "params": {k: v for k, v in PARAMS.items()}}
    meta_path(shape, horizon).write_text(json.dumps(meta, indent=2))
    if verbose:
        print(f"  xgb {shape:12} h={horizon}  train_rows={n_train:5} "
              f"feats={n_feat:3}  best_iter={meta['best_iteration']}")
    return meta


# ---------------------------------------------------------------- predict --
def predict(shape: str, horizon: int, split: str):
    """Return (y_true, y_pred) flattened, plus a per-commodity frame."""
    path = artefact_path(shape, horizon)
    if not path.exists():
        raise SystemExit(f"missing {path} — run xgboost_model.py first")
    meta = json.loads(meta_path(shape, horizon).read_text())

    if shape == "pooled":
        df = D.make_pooled(horizon)
        sub = df[df.split == split]
        model = xgb.XGBRegressor(enable_categorical=True)
        model.load_model(path)
        pred = model.predict(sub[meta["features"]])
        return (sub["y"].to_numpy(), np.asarray(pred),
                pd.DataFrame({"date": sub["date"].values,
                              "commodity": sub["commodity"].astype(str).values,
                              "y_true": sub["y"].to_numpy(), "y_pred": pred}))

    X, Y, sp = D.make_multivariate(horizon)
    mask = sp == split
    model = xgb.XGBRegressor()
    model.load_model(path)
    pred = model.predict(X[mask])
    yt, yp = Y[mask].to_numpy(), np.asarray(pred)
    long = pd.DataFrame({
        "date": np.repeat(Y[mask].index.values, Y.shape[1]),
        "commodity": np.tile(list(Y.columns), mask.sum()),
        "y_true": yt.ravel(), "y_pred": yp.ravel()})
    return yt.ravel(), yp.ravel(), long


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shape", choices=["pooled", "multivariate"], default=None)
    ap.add_argument("--horizon", type=int, choices=[1, 3], default=None)
    args = ap.parse_args()

    shapes = [args.shape] if args.shape else ["pooled", "multivariate"]
    horizons = [args.horizon] if args.horizon else [1, 3]
    print("training XGBoost")
    for sh in shapes:
        for h in horizons:
            train(sh, h)
    print(f"\n  artefacts in {ART}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
