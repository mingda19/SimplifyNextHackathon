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
import re
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
# Two levels up from the local source tree (services/price_forecaster/forecast.py)
# lands on the real repo root -- but only when running from a checkout. The
# Docker image copies this service flat into /app with no repo root above it,
# so "two levels up" from /app is just "/", which has no `services/` dir.
# `len(HERE.parents) > 1` doesn't catch that case (`/app` still has 2 parents:
# `/app`, `/`), so it used to resolve to `/` in the container -- silently
# breaking `data/dspi_features.py` resolution below. Checking for a `services/`
# sibling is what actually tells the two layouts apart; fall back to HERE
# (`/app`) when it isn't there. load_dotenv below is then a no-op in the
# container and Compose's own `environment:` block is the config source
# instead -- data/dspi_features.py must still be copied to `/app/data/` in the
# Dockerfile for the fallback branch to resolve.
_candidate = HERE.parents[1] if len(HERE.parents) > 1 else HERE
REPO_ROOT = _candidate if (_candidate / "services").is_dir() else HERE

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


_STOP = {"and", "or", "of", "the", "n", "e", "s", "nes", "excl", "incl"}


def _norm(text: str) -> str:
    """Fold the spelling differences between the two systems into one form.

    Workstream 1 stores `dspi_series` in SingStat title case with words spelled
    out — "Vegetables, Roots And Tubers, Prepared Or Preserved, N.E.S." — while
    this service's catalogue keeps the DSPI raw form with ampersands and "Nes".
    Exact and substring matching resolved 1 of 29 real SKUs because of it.
    """
    t = text.lower().replace("&", " and ")
    return " ".join(re.findall(r"[a-z0-9]+", t))


def _tokens(text: str) -> set[str]:
    return {w for w in _norm(text).split() if w not in _STOP and len(w) > 2}


def _full_name_map() -> dict[str, str]:
    """full DSPI series name -> our alias.

    The served matrix uses short aliases ("cereal_prep"), so token-matching a
    ten-word SingStat title against a two-word alias never scores. The original
    names live in data/dspi_features.SELECTED; matching against those is what
    makes workstream 1's `dspi_series` resolvable at all.
    """
    if "fullmap" not in _cache:
        try:
            import sys
            sys.path.insert(0, str(REPO_ROOT / "data"))
            from dspi_features import SELECTED  # noqa: PLC0415
            _cache["fullmap"] = dict(SELECTED)
        except Exception:                          # noqa: BLE001
            _cache["fullmap"] = {}
    return _cache["fullmap"]


def _resolve(series: str) -> str | None:
    """Accept an alias ('rice'), either spelling of the DSPI name, or a variant."""
    cols = list(_state()["matrix"].columns)
    key = series.strip().lower()

    # 0 match against the FULL DSPI names, normalised
    full = _full_name_map()
    nk0 = _norm(series)
    for full_name, alias in full.items():
        if _norm(full_name) == nk0 and alias in cols:
            return alias
    scored0 = []
    for full_name, alias in full.items():
        if alias not in cols:
            continue
        a, b = _tokens(series), _tokens(full_name)
        if a and b:
            scored0.append((len(a & b) / len(a | b), alias))
    scored0.sort(reverse=True)
    if scored0 and scored0[0][0] >= 0.55 and (
            len(scored0) == 1 or scored0[0][0] - scored0[1][0] >= 0.10):
        return scored0[0][1]

    # 1 exact alias / column name
    lower = {c.lower(): c for c in cols}
    if key in lower:
        return lower[key]

    # 2 normalised exact (handles "And" vs "&", "N.E.S." vs "Nes", punctuation)
    nmap = {_norm(c): c for c in cols}
    nk = _norm(series)
    if nk in nmap:
        return nmap[nk]

    # 3 unambiguous substring, either direction
    hits = [c for c in cols if nk and (nk in _norm(c) or _norm(c) in nk)]
    if len(hits) == 1:
        return hits[0]

    # 4 best token overlap, but only when it is a clear winner. A weak match is
    #   worse than none: the agent would time a purchase against another
    #   commodity's price curve entirely.
    want = _tokens(series)
    if not want:
        return None
    scored = []
    for c in cols:
        have = _tokens(c)
        if not have:
            continue
        j = len(want & have) / len(want | have)
        scored.append((j, c))
    scored.sort(reverse=True)
    if scored and scored[0][0] >= 0.34 and (
            len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.08):
        return scored[0][1]
    return None


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

    calibration = st["calibration"]
    cal = calibration.get("realised_by_gate", {}).get(f"{CONFIDENCE_GATE:.2f}",
                                                        calibration.get("realised", {}))
    threshold = calibration.get("confidence_thresholds", {}).get(f"{CONFIDENCE_GATE:.2f}")
    matches_gate = threshold is not None and all(
        cal.get(split, {}).get("threshold") == threshold for split in ("val", "test"))
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
            "val_dir_acc_at_gate": cal.get("val", {}).get("dir_acc") if matches_gate else None,
            "test_dir_acc_at_gate": cal.get("test", {}).get("dir_acc") if matches_gate else None,
            "test_n_at_gate": cal.get("test", {}).get("n") if matches_gate else None,
            "ungated_test_dir_acc": cal.get("ungated_test_dir_acc"),
            "statistics_available_at_gate": matches_gate,
            "magnitude_threshold_at_gate": threshold,
            "measured_magnitude_threshold": cal.get("test", {}).get("threshold"),
            "warning": ("confidence is a calibrated estimate from validation, "
                        "not a measured guarantee; held-out support at this "
                        "gate is thin"),
        },
    }


def forecast_all(horizon_months: int = HORIZON) -> list[dict[str, Any]]:
    return [forecast(c, horizon_months) for c in available_series()]
