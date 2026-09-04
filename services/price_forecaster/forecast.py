"""
Serving logic for /price/forecast.

Produces the BUY_NOW / DEFER / NEUTRAL recommendation the orchestrator's
`sense` node consumes, gated on calibrated directional confidence.

THE GATE
--------
The model emits a point estimate of the 3-month forward return, not a
probability. `calibrate.py` fits |y_pred| -> P(sign correct) on validation.
A recommendation is only emitted when that confidence clears CONFIDENCE_GATE
(default 0.60, override with PRICE_CONFIDENCE_GATE). Below it, NEUTRAL.

READ THIS BEFORE TRUSTING `confidence`
--------------------------------------
The calibration is fitted on 312 validation observations. At the 0.60 crossing
it selects the top ~5% of predictions — 17 validation rows and only 5 test rows.
Held-out evidence at that threshold is too thin to confirm 60%, and the served
`confidence` is therefore a calibrated ESTIMATE, not a measured hit rate. The
response carries `calibration` so the caller can see the realised numbers rather
than take the estimate on faith.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dotenv import load_dotenv

import calibrate
import dataset as D
import xgboost_model as X

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]

# The root .env is the single control point for the whole project. Without this
# the gate could only be changed by editing source, and a teammate setting
# PRICE_CONFIDENCE_GATE in .env would be silently ignored.
load_dotenv(REPO_ROOT / ".env")

HORIZON = 3

# PRODUCTION MODEL. XGBoost pooled h=3 is the only artefact served.
# The LSTM is a benchmark arm — it early-stops at epoch ~2 and converges to
# predicting the mean, so it must never reach the serving path. `_state()`
# asserts the loaded artefact matches this constant.
PROD_MODEL = "xgboost_pooled_h3"

# Directional-confidence gate. 0.60 is what held-out data supports; 0.70 was
# tried and abandoned (validation 88% on 17 obs vs test 40% on 5).
CONFIDENCE_GATE = float(os.getenv("PRICE_CONFIDENCE_GATE", "0.60"))

_MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

_cache: dict[str, Any] = {}


def _state() -> dict[str, Any]:
    if not _cache:
        model, meta = X.load_model()
        served = f"{meta['algo']}_{meta['shape']}_h{meta['horizon']}"
        if served != PROD_MODEL:
            raise RuntimeError(
                f"serving path loaded {served!r}, expected {PROD_MODEL!r}")
        matrix, _ = D.load_matrix()
        serving = D.make_serving_features()
        preds = model.predict(serving[meta["features"]])
        _cache.update(model=model, meta=meta, matrix=matrix,
                      serving=serving.assign(y_pred=preds),
                      calibration=calibrate.load())
    return _cache


def _resolve(series: str) -> str | None:
    """Accept an alias ('rice'), the DSPI name, or any case variant."""
    cols = list(_state()["matrix"].columns)
    lower = {c.lower(): c for c in cols}
    key = series.strip().lower()
    if key in lower:
        return lower[key]
    hits = [c for c in cols if key in c.lower()]
    return hits[0] if len(hits) == 1 else None


def available_series() -> list[str]:
    return list(_state()["matrix"].columns)


def _seasonal_low_months(s: pd.Series, k: int = 2) -> list[str]:
    """Months whose average month-on-month return is lowest."""
    r = s.pct_change()
    by_month = r.groupby(r.index.month).mean()
    return [_MON[m - 1] for m in by_month.nsmallest(k).index]


def forecast(series: str, horizon_months: int = HORIZON) -> dict[str, Any]:
    st = _state()
    col = _resolve(series)
    if col is None:
        raise KeyError(series)

    s = st["matrix"][col]
    row = st["serving"][st["serving"]["commodity"].astype(str) == col].iloc[0]
    as_of: pd.Timestamp = row["as_of"]

    y_pred = float(row["y_pred"])
    conf = calibrate.confidence(abs(y_pred), st["calibration"])
    gated = conf >= CONFIDENCE_GATE

    if not gated:
        rec = "NEUTRAL"
    elif y_pred > 0:
        rec = "BUY_NOW"
    else:
        rec = "DEFER"

    pct3 = float(s.iloc[-1] / s.iloc[-4] - 1) * 100 if len(s) > 3 else float("nan")
    pct12 = float(s.iloc[-1] / s.iloc[-13] - 1) * 100 if len(s) > 12 else float("nan")
    direction = "rising" if pct3 > 0.25 else "falling" if pct3 < -0.25 else "flat"

    # data_lag_months: how stale the newest observation is, right now
    today = date.today()
    lag = (today.year - as_of.year) * 12 + (today.month - as_of.month)

    if rec == "BUY_NOW":
        rationale = (
            f"Model projects {y_pred * 100:+.2f}% over {horizon_months} months "
            f"(confidence {conf:.0%}, gate {CONFIDENCE_GATE:.0%}). "
            f"Trailing 3m {pct3:+.2f}%. Buying now avoids the projected rise.")
    elif rec == "DEFER":
        rationale = (
            f"Model projects {y_pred * 100:+.2f}% over {horizon_months} months "
            f"(confidence {conf:.0%}, gate {CONFIDENCE_GATE:.0%}). "
            f"Deferring captures the projected fall, stock cover permitting.")
    else:
        rationale = (
            f"Projected move {y_pred * 100:+.2f}% over {horizon_months} months "
            f"carries only {conf:.0%} directional confidence, below the "
            f"{CONFIDENCE_GATE:.0%} gate. No timing signal — order on stock need.")

    cal = st["calibration"].get("realised", {})
    return {
        # -- contract the orchestrator's sense node reads ------------------
        "series": col,
        "as_of": f"{as_of:%Y-%m}",
        "data_lag_months": max(lag, 0),
        "latest_index": round(float(s.iloc[-1]), 3),
        "pct_change_3m": round(pct3, 2),
        "pct_change_12m": round(pct12, 2),
        "direction": direction,
        "seasonal_low_months": _seasonal_low_months(s),
        "recommendation": rec,
        "confidence": round(conf, 3),
        "rationale": rationale,
        # -- provenance, so the agent never quotes confidence bare ---------
        "horizon_months": horizon_months,
        "predicted_change_pct": round(y_pred * 100, 3),
        "model": PROD_MODEL,
        "gate": {
            "threshold": CONFIDENCE_GATE,
            "passed": bool(gated),
            "calibrated_on": "validation (312 obs)",
        },
        "calibration": {
            "val_dir_acc_at_gate": cal.get("val", {}).get("dir_acc"),
            "test_dir_acc_at_gate": cal.get("test", {}).get("dir_acc"),
            "test_n_at_gate": cal.get("test", {}).get("n"),
            "ungated_test_dir_acc": cal.get("ungated_test_dir_acc"),
            "warning": ("confidence is a calibrated estimate from validation, "
                        "not a measured guarantee; held-out support at this "
                        "gate is thin"),
        },
    }


def forecast_all(horizon_months: int = HORIZON) -> list[dict[str, Any]]:
    return [forecast(c, horizon_months) for c in available_series()]
