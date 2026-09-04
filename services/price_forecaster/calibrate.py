#!/usr/bin/env python
"""
Fit the directional-confidence calibrator, and honestly measure it.

The model emits a point estimate, not a probability. To gate on "70% confidence"
we need a mapping from predicted magnitude |y_pred| to P(the sign is right).

Fitted on VALIDATION with a smooth logistic curve rather than raw bins: the top
validation buckets hold ~20 observations each, and raw bin rates there reach 88%
purely by chance. A logistic fit on log-magnitude shrinks that toward the base
rate instead of extrapolating noise.

The honest number is then measured on TEST and stored alongside, so the served
`confidence` can never be quoted without its realised counterpart.

    python calibrate.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

import xgboost_model as X

ART = Path(__file__).resolve().parent / "artifacts"
CAL_PATH = ART / "calibration.json"
FLOOR = 1e-5


def _frame(split: str) -> pd.DataFrame:
    _, _, long = X.predict(split)
    return long.assign(mag=np.abs(long.y_pred),
                       hit=(np.sign(long.y_pred) == np.sign(long.y_true)).astype(int))


def fit() -> dict:
    val, test = _frame("val"), _frame("test")

    Xv = np.log(np.maximum(val["mag"].to_numpy(), FLOOR)).reshape(-1, 1)
    clf = LogisticRegression().fit(Xv, val["hit"].to_numpy())
    coef, intercept = float(clf.coef_[0][0]), float(clf.intercept_[0])

    def conf(mag):
        z = coef * np.log(np.maximum(np.asarray(mag, float), FLOOR)) + intercept
        return 1.0 / (1.0 + np.exp(-z))

    # magnitude at which the smooth curve crosses each confidence level
    levels = {}
    grid = np.linspace(FLOOR, 0.15, 20000)
    cg = conf(grid)
    for lvl in (0.60, 0.65, 0.70, 0.75, 0.80):
        idx = np.where(cg >= lvl)[0]
        levels[f"{lvl:.2f}"] = float(grid[idx[0]]) if len(idx) else None

    # realised accuracy at the 0.70 crossing, on BOTH splits
    t70 = levels["0.70"]
    realised = {}
    if t70 is not None:
        for name, d in (("val", val), ("test", test)):
            m = d["mag"] >= t70
            realised[name] = {
                "threshold": t70,
                "coverage": float(m.mean()),
                "n": int(m.sum()),
                "dir_acc": float(d.loc[m, "hit"].mean()) if m.sum() else None,
            }
        realised["ungated_test_dir_acc"] = float(test["hit"].mean())

    cal = {"model": "xgb_pooled_h3", "method": "logistic_on_log_magnitude",
           "fitted_on": "val", "coef": coef, "intercept": intercept,
           "magnitude_floor": FLOOR,
           "confidence_thresholds": levels, "realised": realised}
    ART.mkdir(parents=True, exist_ok=True)
    CAL_PATH.write_text(json.dumps(cal, indent=2))
    return cal


def load() -> dict:
    if not CAL_PATH.exists():
        raise SystemExit(f"missing {CAL_PATH} — run calibrate.py first")
    return json.loads(CAL_PATH.read_text())


def confidence(mag: float, cal: dict | None = None) -> float:
    cal = cal or load()
    z = cal["coef"] * np.log(max(float(mag), cal["magnitude_floor"])) + cal["intercept"]
    return float(1.0 / (1.0 + np.exp(-z)))


def main() -> int:
    cal = fit()
    print("  logistic calibration fitted on VAL")
    print(f"    P(correct) = sigmoid({cal['coef']:.3f} * ln|pred| "
          f"{cal['intercept']:+.3f})")
    print("\n  |pred| needed to reach each confidence level:")
    for lvl, t in cal["confidence_thresholds"].items():
        print(f"    {float(lvl):.0%}  ->  |pred| >= {t:.4f}" if t
              else f"    {float(lvl):.0%}  ->  unreachable")
    r = cal["realised"]
    if r:
        print(f"\n  \033[1mrealised accuracy at the 70% gate "
              f"(|pred| >= {r['val']['threshold']:.4f}):\033[0m")
        for s in ("val", "test"):
            d = r[s]
            acc = f"{d['dir_acc']:.1%}" if d["dir_acc"] is not None else "n/a"
            print(f"    {s:5} coverage {d['coverage']:>4.0%} (n={d['n']:>3})  "
                  f"DirAcc {acc}")
        print(f"    ungated test DirAcc for comparison: "
              f"{r['ungated_test_dir_acc']:.1%}")
        gap = r["test"]["dir_acc"]
        if gap is not None and gap < 0.70:
            print(f"\n  \033[33mNOTE: a 70% val-calibrated gate realises "
                  f"{gap:.1%} on held-out test.\033[0m")
            print("  \033[33mThe confidence served is a calibrated estimate, not a "
                  "guarantee.\033[0m")
    print(f"\n  wrote {CAL_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
