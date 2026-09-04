#!/usr/bin/env python
"""
price_forecaster HTTP service — workstream 3.

Serves the contract the orchestrator's `sense` node calls (see
services/orchestrator/services.py::get_price_forecast).

    uvicorn app:app --port 8003 --reload
    make serve
"""
from __future__ import annotations

import os

os.environ.setdefault("OMP_NUM_THREADS", "1")

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

import forecast as F  # noqa: E402

app = FastAPI(title="price_forecaster",
              description="3-month commodity price direction for charity procurement",
              version="1.0.0")


@app.get("/health")
def health():
    """Liveness. The orchestrator degrades gracefully if this is unreachable."""
    try:
        n = len(F.available_series())
        gated = sum(r["gate"]["passed"] for r in F.forecast_all())
        return {"status": "ok", "series": n,
                "model": F.PROD_MODEL, "benchmark_only": ["lstm_pooled_h3"],
                "gate": F.CONFIDENCE_GATE,
                "series_emitting_signal": gated}
    except Exception as exc:                       # noqa: BLE001
        return JSONResponse(status_code=503,
                            content={"status": "degraded", "detail": str(exc)})


@app.get("/price/series")
def series():
    """Every commodity the forecaster can serve."""
    return {"series": F.available_series()}


@app.get("/price/forecast")
def price_forecast(
    series: str = Query("Rice", description="DSPI series name or alias"),
    horizon_months: int = Query(3, ge=3, le=3,
                                description="only 3 is supported; h=1 was dropped"),
):
    try:
        return F.forecast(series, horizon_months)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail={"code": "UNKNOWN_SERIES", "message": f"no series matching {series!r}",
                    "hint": "GET /price/series for the full list"})


@app.get("/price/forecast/all")
def price_forecast_all(horizon_months: int = Query(3, ge=3, le=3)):
    """Whole basket in one call — cheaper for the agent's sense phase."""
    return {"forecasts": F.forecast_all(horizon_months)}
