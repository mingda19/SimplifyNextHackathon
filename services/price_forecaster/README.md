# price_forecaster

Workstream 3. Answers one question per commodity: **are prices heading up or
down over the next 1 or 3 months**, so the orchestrator can buy early or hold off.

## Pipeline

```
data/dspi_2014_onwards.csv          <- data/DSPI_parser2014.py   (transpose + 2014 cut)
data/dspi_features_final.csv        <- data/dspi_features.py     (26 storable commodities)
services/price_forecaster/data/{train,val,test}.csv
                                    <- split_dataset.py          (120 / 15 / 15 months)
artifacts/{xgb,lstm}_{shape}_h{1,3}.{json,pt}
                                    <- xgboost_model.py, lstm_model.py
```

```bash
python ../../data/dspi_features.py --write
python split_dataset.py
python xgboost_model.py
python lstm_model.py
python evaluator.py --val
python evaluator.py --test
```

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
