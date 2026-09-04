# price_forecaster

Workstream 3. Answers one question per commodity: **are prices heading up or
down over the next 1 or 3 months**, so the orchestrator can buy early or hold off.

## Pipeline

```
data/dspi_2014_onwards.csv          <- data/DSPI_parser2014.py   (transpose + 2014 cut)
data/dspi_features_final.csv        <- data/dspi_features.py     (26 storable commodities)
services/price_forecaster/data/{train,val,test}.csv
                                    <- split_dataset.py          (120 / 15 / 15 months)
artifacts/xgb_pooled_h3.json / lstm_pooled_h3.pt
                                    <- xgboost_model.py, lstm_model.py
artifacts/calibration.json          <- calibrate.py
```

```bash
python ../../data/dspi_features.py --write
python split_dataset.py
python xgboost_model.py
python lstm_model.py
python calibrate.py
python evaluator.py --val
python evaluator.py --test
uvicorn app:app --port 8003        # or: make forecaster-serve
```

## Endpoint

`GET /price/forecast?series=Rice&horizon_months=3` — the contract
`orchestrator/services.py::get_price_forecast` calls. Also `/price/series`,
`/price/forecast/all`, `/health`.

Set `FAKE_PRICING=0` to point the orchestrator at the live service while the
other workstreams stay on fixtures.

## Scope: pooled panel, 3-month horizon only

The multivariate shape and h=1 were evaluated and **dropped**:

| config | test DirAcc | test skill |
|---|---|---|
| pooled h=3 | **58.5%** | +0.014 |
| pooled h=1 | 52.9% | +0.010 |
| multivariate h=3 | 53.7% | -0.033 |
| multivariate h=1 | 52.6% | -0.017 |

Multivariate scored negative skill on held-out data — worse than assuming no
change — which is what 78 features against ~115 rows buys you. h=1 was a coin
flip.

## The confidence gate

`PRICE_CONFIDENCE_GATE` (default 0.70). `calibrate.py` fits |y_pred| ->
P(sign correct) on validation with a logistic curve, and a recommendation is
emitted only above the gate. Currently 6 of 26 commodities clear 0.70.

**The gate's honest limits.** At the 0.70 crossing (|pred| >= 0.0082) validation
shows 88% accuracy on 17 observations, but test shows 40% on 5. Five
observations is noise, and the held-out data does not confirm 70% at any usable
coverage — the best supported reading is the |pred| >= 0.003-0.004 band, where
test gives 61-62% at 12-52% coverage against 58.3% ungated. The served
`confidence` is a calibrated estimate, not a measured hit rate, and every
response carries a `calibration` block with the realised numbers so the agent
can never quote it bare.

## Design decisions

**Only storable goods.** A forecast is actionable only if you can stockpile.
Fresh produce, fresh meat and fish, eggs and butter are excluded despite being
core charity items — see `data/dspi_features.py`.

**Target is the forward return**, `index[t+h]/index[t] - 1`, not the level.
The decision is directional, and returns are far closer to stationary with only
120 training months.

**Purged splits.** A row at month `t` whose target lands at `t+h` in a different
split is dropped. Without that, training rows leak validation data.

**Scalers fit on train only.** Lag features may reach backwards across a split
boundary — that is not leakage, you would genuinely have those months in
production — but no statistic is ever computed on val or test.

## Known issue: OpenMP

`evaluator.py` is the only module that loads xgboost and torch together. On
macOS each ships its own `libomp`; multithreaded, they segfault (139) or
deadlock. The module pins `OMP_NUM_THREADS=1` **before** importing either. Do
not move those lines below the imports.
