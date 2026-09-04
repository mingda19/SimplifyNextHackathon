"""
Shared feature construction for both model shapes.

TARGET
------
The forward return over the horizon:  y = index[t+h] / index[t] - 1

Returns, not levels. The decision the forecaster serves is BUY_NOW / DEFER /
NEUTRAL, which is a question about direction and magnitude of change, not about
the absolute index. Returns are also far closer to stationary, which matters a
lot with only 120 training months.

PURGING (why row counts are lower than month counts)
----------------------------------------------------
A row at month t carries a target from month t+h. If t sits in train but t+h
lands in val, training on that row leaks validation data. So a row is kept in
split S only when BOTH t and t+h fall inside S. Rows straddling a boundary are
dropped. That costs h rows per split per boundary and is the honest thing to do.

SCALING
-------
Scalers are fit on train rows only and applied to val/test. Lag features look
strictly backwards, so letting them reach across a split boundary is not
leakage — in production you would genuinely have those prior months.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"

SPLITS = ("train", "val", "test")
LAGS = (1, 2, 3, 6, 12)
ROLLS = (3, 6, 12)


# ---------------------------------------------------------------- loading --
def load_splits(data_dir: Path = DATA) -> dict[str, pd.DataFrame]:
    out = {}
    for name in SPLITS:
        path = data_dir / f"{name}.csv"
        if not path.exists():
            raise SystemExit(f"missing {path} — run split_dataset.py first")
        out[name] = pd.read_csv(path, index_col="date", parse_dates=True).sort_index()
    return out


def load_matrix(data_dir: Path = DATA) -> tuple[pd.DataFrame, pd.Series]:
    """Full contiguous months x commodities matrix, plus a per-month split label."""
    parts = load_splits(data_dir)
    df = pd.concat([parts[s] for s in SPLITS]).sort_index()
    label = pd.concat([pd.Series(s, index=parts[s].index) for s in SPLITS]).sort_index()
    label.name = "split"
    if not df.index.is_monotonic_increasing or df.index.has_duplicates:
        raise ValueError("reassembled index is not clean")
    return df, label


def _assign_split(dates: pd.DatetimeIndex, label: pd.Series, horizon: int) -> pd.Series:
    """
    Split of row t, or NaN when the target at t+h crosses a boundary (purged).
    """
    pos = {d: i for i, d in enumerate(label.index)}
    out = []
    for d in dates:
        i = pos[d]
        j = i + horizon
        if j >= len(label):
            out.append(np.nan)
            continue
        s_now, s_fut = label.iloc[i], label.iloc[j]
        out.append(s_now if s_now == s_fut else np.nan)
    return pd.Series(out, index=dates, name="split")


# ------------------------------------------------------- pooled panel form --
def make_pooled(horizon: int, data_dir: Path = DATA) -> pd.DataFrame:
    """
    One row per (commodity, month). Features are that commodity's own history.

    Long format means ~26x more training rows than the multivariate shape, which
    is what makes it viable at this sample size.
    """
    df, label = load_matrix(data_dir)
    split_of = _assign_split(df.index, label, horizon)

    frames = []
    for col in df.columns:
        s = df[col]
        ret1 = s.pct_change()
        f = pd.DataFrame(index=s.index)
        for L in LAGS:
            f[f"ret_{L}"] = s.pct_change(L)
        for R in ROLLS:
            f[f"roll_mean_{R}"] = ret1.rolling(R).mean()
            f[f"roll_std_{R}"] = ret1.rolling(R).std()
        # position of the level within its own recent range
        f["z_12"] = (s - s.rolling(12).mean()) / s.rolling(12).std()
        m = s.index.month
        f["month_sin"] = np.sin(2 * np.pi * m / 12)
        f["month_cos"] = np.cos(2 * np.pi * m / 12)
        f["commodity"] = col
        f["y"] = s.shift(-horizon) / s - 1.0
        f["split"] = split_of.values
        frames.append(f.reset_index())

    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["y", "split"])
    out = out.dropna()                      # drop rows still warming up their lags
    out["commodity"] = out["commodity"].astype("category")
    return out


def pooled_feature_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if c not in ("date", "y", "split")]


# --------------------------------------------------------------- sequences --
def make_sequences_pooled(horizon: int, window: int = 12, data_dir: Path = DATA):
    """(N, window, 1) sequences of monthly returns per commodity, for the LSTM."""
    df, label = load_matrix(data_dir)
    split_of = _assign_split(df.index, label, horizon)
    ret = df.pct_change()

    Xs, ys, splits, meta = [], [], [], []
    for ci, col in enumerate(df.columns):
        r, s = ret[col], df[col]
        for i in range(window, len(df)):
            d = df.index[i]
            sp = split_of.loc[d]
            if pd.isna(sp):
                continue
            win = r.iloc[i - window + 1:i + 1].to_numpy()
            tgt = s.iloc[i + horizon] / s.iloc[i] - 1.0
            if np.isnan(win).any() or np.isnan(tgt):
                continue
            Xs.append(win[:, None])
            ys.append(tgt)
            splits.append(sp)
            meta.append((d, col, ci))
    return (np.asarray(Xs, dtype=np.float32),
            np.asarray(ys, dtype=np.float32),
            np.asarray(splits),
            pd.DataFrame(meta, columns=["date", "commodity", "commodity_id"]))


def build_features(s: pd.Series) -> pd.DataFrame:
    """Feature block for one commodity's index series. Backward-looking only."""
    ret1 = s.pct_change()
    f = pd.DataFrame(index=s.index)
    for L in LAGS:
        f[f"ret_{L}"] = s.pct_change(L)
    for R in ROLLS:
        f[f"roll_mean_{R}"] = ret1.rolling(R).mean()
        f[f"roll_std_{R}"] = ret1.rolling(R).std()
    f["z_12"] = (s - s.rolling(12).mean()) / s.rolling(12).std()
    m = s.index.month
    f["month_sin"] = np.sin(2 * np.pi * m / 12)
    f["month_cos"] = np.cos(2 * np.pi * m / 12)
    return f


def make_serving_features(data_dir: Path = DATA) -> pd.DataFrame:
    """
    Features for the LATEST available month of every commodity — no target.

    This is what the endpoint predicts from: the most recent observation is the
    decision point, and the forecast lands `horizon` months after it.
    """
    df, _ = load_matrix(data_dir)
    rows = []
    for col in df.columns:
        f = build_features(df[col])
        last = f.dropna().iloc[-1:]
        if last.empty:
            continue
        r = last.copy()
        r["commodity"] = col
        r["as_of"] = last.index[-1]
        r["latest_index"] = float(df[col].loc[last.index[-1]])
        rows.append(r.reset_index(drop=True))
    out = pd.concat(rows, ignore_index=True)
    cats = sorted(df.columns)
    out["commodity"] = pd.Categorical(out["commodity"], categories=cats)
    return out


def commodity_names(data_dir: Path = DATA) -> list[str]:
    df, _ = load_matrix(data_dir)
    return list(df.columns)
