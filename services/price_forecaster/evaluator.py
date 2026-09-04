#!/usr/bin/env python
"""
Score every trained artefact on the validation or test split.

    python evaluator.py --val
    python evaluator.py --test
    python evaluator.py --val --per-commodity
    python evaluator.py --val --algo xgboost --shape pooled

METRICS
-------
MAE / RMSE      error on the forward return, in return units (0.01 = 1pp).
DirAcc          share of months where the predicted SIGN was right. This is the
                metric that actually matters: BUY_NOW / DEFER is a directional
                call, and a model can have a fine MAE while being a coin flip on
                direction.
Skill           1 - MAE/MAE_zero. Above 0 beats "assume no change"; at or below
                0 the model adds nothing over doing nothing.

BASELINES
---------
zero            predict no change. Surprisingly hard to beat on monthly index
                data, and the honest bar for "is this model worth shipping".
drift           predict the trailing 12-month mean return — a naive trend rule,
                and the fairest directional comparison.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# MUST run before xgboost or torch is imported.
#
# xgboost (via sklearn) and torch each ship their own libomp on macOS. With both
# loaded and multithreaded in one process, predict calls either segfault (139) or
# deadlock. Pinning OpenMP to a single thread makes the two runtimes coexist.
# This is the only module that loads both, and the data is small enough that
# single-threaded costs nothing measurable.
# ---------------------------------------------------------------------------
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import argparse
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

import dataset as D
import lstm_model
import xgboost_model
import torch

torch.set_num_threads(1)
warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
ALGOS = {"xgboost": xgboost_model, "lstm": lstm_model}
HORIZON = 3          # pooled panel, 3-month horizon — the only shipped config


# ------------------------------------------------------------------ scoring --
def score(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    y_true = np.asarray(y_true, dtype=float).ravel()
    y_pred = np.asarray(y_pred, dtype=float).ravel()
    err = y_pred - y_true
    mae = float(np.mean(np.abs(err)))
    rmse = float(np.sqrt(np.mean(err ** 2)))

    # direction: ignore months where the true move was ~flat, they are noise
    live = np.abs(y_true) > 1e-6
    diracc = (float(np.mean(np.sign(y_pred[live]) == np.sign(y_true[live])))
              if live.any() else float("nan"))
    mae_zero = float(np.mean(np.abs(y_true)))
    return {"n": int(y_true.size), "mae": mae, "rmse": rmse,
            "dir_acc": diracc, "mae_zero": mae_zero,
            "skill": 1.0 - mae / mae_zero if mae_zero > 0 else float("nan")}


def baselines(split: str, horizon: int = HORIZON) -> dict[str, dict]:
    """Naive references computed on the same purged rows the models see."""
    df = D.make_pooled(horizon)
    sub = df[df.split == split]
    y = sub["y"].to_numpy()

    out = {"baseline:zero": score(y, np.zeros_like(y))}
    # drift = trailing 12m mean monthly return, scaled to the horizon
    drift = sub["roll_mean_12"].to_numpy() * horizon
    out["baseline:drift"] = score(y, drift)
    return out


def evaluate_one(algo: str, split: str):
    mod = ALGOS[algo]
    if not mod.artefact_path().exists():
        return None, None
    y_true, y_pred, long = mod.predict(split)
    return score(y_true, y_pred), long


# -------------------------------------------------------------------- runs --
def run(split: str, algos, per_commodity: bool) -> int:
    print(f"\n\033[1m  {split.upper()} SPLIT\033[0m   pooled panel, {HORIZON}-month horizon")

    rows, longs = [], {}
    for name, m in baselines(split).items():
        rows.append({"model": name, **m})
    for algo in algos:
        s_, long = evaluate_one(algo, split)
        if s_ is None:
            print(f"  (skipping {algo} — artefact not trained)")
            continue
        rows.append({"model": algo, **s_})
        longs[algo] = long

    if not rows:
        print("  nothing to score — train the models first")
        return 1

    df = pd.DataFrame(rows)
    print(f"\n  {'model':<18}{'n':>6}{'MAE':>10}{'RMSE':>10}{'DirAcc':>9}{'Skill':>9}")
    print("  " + "-" * 62)
    best_mae = df["mae"].min()
    for _, r in df.iterrows():
        star = " *" if r["mae"] == best_mae else "  "
        skill = f"{r['skill']:+.3f}" if np.isfinite(r["skill"]) else "     -"
        dacc = f"{r['dir_acc']:.1%}" if np.isfinite(r["dir_acc"]) else "    -"
        colour = "\033[32m" if r["skill"] > 0 else "\033[31m"
        print(f"  {r['model']:<18}{r['n']:>6}{r['mae']:>10.5f}{r['rmse']:>10.5f}"
              f"{dacc:>9}{colour}{skill:>9}\033[0m{star}")

    print("\n  * lowest MAE."
          "  Skill > 0 beats 'assume no change'; <= 0 means it does not.")

    if per_commodity:
        part = df[~df.model.str.startswith("baseline")]
        if not part.empty:
            b = part.loc[part["mae"].idxmin(), "model"]
            long = longs.get(b)
            if long is not None:
                print(f"\n\033[1m  PER-COMMODITY ({b})\033[0m")
                n_per = long.groupby("commodity").size().max()
                print(f"  \033[33mnote: only {n_per} observations per commodity — "
                      f"per-commodity DirAcc is very noisy\033[0m")
                g = (long.assign(ae=(long.y_pred - long.y_true).abs(),
                                 hit=np.sign(long.y_pred) == np.sign(long.y_true))
                     .groupby("commodity")
                     .agg(mae=("ae", "mean"), dir_acc=("hit", "mean"),
                          vol=("y_true", "std"))
                     .sort_values("mae"))
                print(f"\n    {'commodity':<20}{'MAE':>9}{'DirAcc':>9}{'vol':>9}")
                for name, r in g.iterrows():
                    print(f"    {str(name):<20}{r['mae']:>9.5f}"
                          f"{r['dir_acc']:>8.0%}{r['vol']:>9.5f}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--val", action="store_true", help="score the validation split")
    g.add_argument("--test", action="store_true", help="score the test split")
    ap.add_argument("--algo", choices=list(ALGOS), default=None)
    ap.add_argument("--per-commodity", action="store_true")
    args = ap.parse_args()

    if not args.val and not args.test:
        ap.error("pick one: --val or --test")

    split = "val" if args.val else "test"
    if split == "test":
        print("\n  \033[33mNOTE: the test split is the final held-out judgement."
              "\n  Tune on --val. Every extra look at --test erodes it.\033[0m")

    return run(split, [args.algo] if args.algo else list(ALGOS),
               args.per_commodity)


if __name__ == "__main__":
    raise SystemExit(main())
