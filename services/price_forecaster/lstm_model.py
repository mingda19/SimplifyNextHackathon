#!/usr/bin/env python
"""
LSTM forecaster — artefact 2 of 2.

Sequence model over a rolling window of monthly returns.

  pooled       (N, window, 1) -> scalar. One sequence per (commodity, month),
               so ~2,700 training sequences: enough to train on.
  multivariate (N, window, 26) -> 26 outputs. ~115 training sequences for a
               recurrent model, which is very thin. Included for the comparison.

Kept deliberately small (32 hidden units, 1 layer, dropout) — with 120 months of
history, capacity buys memorisation, not skill.

    python lstm_model.py
    python lstm_model.py --shape pooled --horizon 1
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn

import dataset as D

HERE = Path(__file__).resolve().parent
ART = HERE / "artifacts"
SEED = 42
WINDOW = 12
DEVICE = torch.device("cpu")        # data is tiny; CPU is faster and deterministic

HIDDEN, LAYERS, DROPOUT = 27, 1, 0.1
EPOCHS, BATCH, LR, PATIENCE = 300, 60, 1e-3, 25


class LSTMForecaster(nn.Module):
    def __init__(self, n_in: int, n_out: int):
        super().__init__()
        self.lstm = nn.LSTM(n_in, HIDDEN, LAYERS, batch_first=True)
        self.drop = nn.Dropout(DROPOUT)
        self.head = nn.Linear(HIDDEN, n_out)

    def forward(self, x):
        out, _ = self.lstm(x)
        return self.head(self.drop(out[:, -1, :]))


def artefact_path(shape: str, horizon: int) -> Path:
    return ART / f"lstm_{shape}_h{horizon}.pt"


def meta_path(shape: str, horizon: int) -> Path:
    return ART / f"lstm_{shape}_h{horizon}.meta.json"


def _load(shape: str, horizon: int):
    if shape == "pooled":
        X, y, sp, meta = D.make_sequences_pooled(horizon, WINDOW)
        return X, y.reshape(-1, 1), sp, meta
    X, Y, sp, dates = D.make_sequences_multivariate(horizon, WINDOW)
    return X, Y, sp, dates


def train(shape: str, horizon: int, verbose: bool = True) -> dict:
    torch.manual_seed(SEED)
    np.random.seed(SEED)
    ART.mkdir(parents=True, exist_ok=True)

    X, Y, sp, _ = _load(shape, horizon)
    tr, va = sp == "train", sp == "val"

    # Standardise on TRAIN ONLY — val/test statistics must never inform scaling.
    mu, sd = X[tr].mean(), X[tr].std()
    sd = sd if sd > 1e-12 else 1.0
    ymu, ysd = Y[tr].mean(axis=0), Y[tr].std(axis=0)
    ysd = np.where(ysd < 1e-12, 1.0, ysd)

    def prep(mask):
        xs = torch.tensor((X[mask] - mu) / sd, dtype=torch.float32, device=DEVICE)
        ys = torch.tensor((Y[mask] - ymu) / ysd, dtype=torch.float32, device=DEVICE)
        return xs, ys

    xtr, ytr = prep(tr)
    xva, yva = prep(va)

    model = LSTMForecaster(X.shape[2], Y.shape[1]).to(DEVICE)
    opt = torch.optim.Adam(model.parameters(), lr=LR)
    lossf = nn.MSELoss()

    best, best_state, bad, best_epoch = float("inf"), None, 0, -1
    n = len(xtr)
    for epoch in range(EPOCHS):
        model.train()
        perm = torch.randperm(n, device=DEVICE)
        for i in range(0, n, BATCH):
            idx = perm[i:i + BATCH]
            opt.zero_grad()
            loss = lossf(model(xtr[idx]), ytr[idx])
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()

        model.eval()
        with torch.no_grad():
            vloss = lossf(model(xva), yva).item()
        if vloss < best - 1e-6:
            best, best_epoch, bad = vloss, epoch, 0
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= PATIENCE:
                break

    model.load_state_dict(best_state)
    torch.save(model.state_dict(), artefact_path(shape, horizon))
    meta = {"algo": "lstm", "shape": shape, "horizon": horizon, "window": WINDOW,
            "n_in": int(X.shape[2]), "n_out": int(Y.shape[1]),
            "x_mu": float(mu), "x_sd": float(sd),
            "y_mu": ymu.tolist(), "y_sd": ysd.tolist(),
            "n_train_rows": int(tr.sum()), "best_epoch": best_epoch,
            "best_val_mse_scaled": best,
            "hidden": HIDDEN, "layers": LAYERS, "dropout": DROPOUT}
    meta_path(shape, horizon).write_text(json.dumps(meta, indent=2))
    if verbose:
        print(f"  lstm {shape:12} h={horizon}  train_seq={int(tr.sum()):5} "
              f"in={X.shape[2]:2} out={Y.shape[1]:2}  best_epoch={best_epoch}")
    return meta


def predict(shape: str, horizon: int, split: str):
    path = artefact_path(shape, horizon)
    if not path.exists():
        raise SystemExit(f"missing {path} — run lstm_model.py first")
    meta = json.loads(meta_path(shape, horizon).read_text())

    X, Y, sp, extra = _load(shape, horizon)
    mask = sp == split
    model = LSTMForecaster(meta["n_in"], meta["n_out"]).to(DEVICE)
    model.load_state_dict(torch.load(path, map_location=DEVICE))
    model.eval()

    xs = torch.tensor((X[mask] - meta["x_mu"]) / meta["x_sd"],
                      dtype=torch.float32, device=DEVICE)
    with torch.no_grad():
        scaled = model(xs).cpu().numpy()
    pred = scaled * np.asarray(meta["y_sd"]) + np.asarray(meta["y_mu"])
    yt = Y[mask]

    if shape == "pooled":
        sub = extra[mask].reset_index(drop=True)
        long = pd.DataFrame({"date": sub["date"], "commodity": sub["commodity"],
                             "y_true": yt.ravel(), "y_pred": pred.ravel()})
    else:
        names = D.commodity_names()
        long = pd.DataFrame({
            "date": np.repeat(np.asarray(extra)[mask], len(names)),
            "commodity": np.tile(names, mask.sum()),
            "y_true": yt.ravel(), "y_pred": pred.ravel()})
    return yt.ravel(), pred.ravel(), long


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shape", choices=["pooled", "multivariate"], default=None)
    ap.add_argument("--horizon", type=int, choices=[1, 3], default=None)
    args = ap.parse_args()

    shapes = [args.shape] if args.shape else ["pooled", "multivariate"]
    horizons = [args.horizon] if args.horizon else [1, 3]
    print("training LSTM")
    for sh in shapes:
        for h in horizons:
            train(sh, h)
    print(f"\n  artefacts in {ART}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
