from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from yeuxq.api.deps import get_container
from yeuxq.analysis.plugins.rule_predictor import UnsupportedPredictionHorizon

router = APIRouter(tags=["analyze"])


@router.get("/api/analyze")
def analyze(symbol: str = Query(...), period: str = Query("day")):
    return get_container().analyze.analyze(symbol, period)


@router.get("/api/predict")
def predict(symbol: str = Query(...), horizon: int = Query(5, ge=1, le=30)):
    try:
        return get_container().analyze.predict(symbol, horizon)
    except UnsupportedPredictionHorizon as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "unsupported_horizon",
                "requested": exc.requested,
                "supported": list(exc.supported),
            },
        ) from exc


@router.get("/api/features")
def features(symbol: str = Query(...)):
    return get_container().analyze.features(symbol)


@router.get("/api/chanlun_daily")
def chanlun_daily(
    symbol: str = Query(...),
    count: int = Query(250, ge=30, le=10000),
    period: str = Query("day"),
):
    return get_container().analyze.chanlun_daily(symbol, count, period)


@router.get("/api/chanlun_minute")
def chanlun_minute(symbol: str = Query(...)):
    return get_container().analyze.chanlun_minute(symbol)
