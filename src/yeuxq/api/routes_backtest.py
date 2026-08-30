from __future__ import annotations

from pydantic import BaseModel, Field

from fastapi import APIRouter

from yeuxq.api.deps import get_container

router = APIRouter(tags=["backtest"])


class BacktestRequest(BaseModel):
    symbol: str
    horizon: int = Field(5, ge=1, le=30)
    min_score: int = Field(60, ge=40, le=95)
    lookback: int = Field(250, ge=60, le=500)
    point_in_time: bool = True
    commission: float = Field(0.00025, ge=0, le=0.01)
    stamp_duty: float = Field(0.0005, ge=0, le=0.01)
    slippage: float = Field(0.001, ge=0, le=0.02)
    entry_mode: str = "next_open"


@router.post("/api/backtest")
def backtest(req: BacktestRequest):
    return get_container().backtest.run(
        symbol=req.symbol,
        horizon=req.horizon,
        min_score=req.min_score,
        lookback=req.lookback,
        point_in_time=req.point_in_time,
        commission=req.commission,
        stamp_duty=req.stamp_duty,
        slippage=req.slippage,
        entry_mode=req.entry_mode,
    )


class CompareRequest(BaseModel):
    symbols: list[str] = Field(
        default_factory=lambda: ["600519", "000001", "601318", "300750", "600036", "000858"]
    )
    horizon: int = Field(5, ge=1, le=20)
    min_score: int = Field(60, ge=40, le=90)
    lookback: int = Field(250, ge=120, le=500)
    train_ratio: float = Field(0.7, ge=0.5, le=0.85)


@router.post("/api/backtest/compare")
def backtest_compare(req: CompareRequest):
    """多票 × 三套规则 × 训练/验证分段。可能需数分钟。"""
    return get_container().backtest.compare(
        symbols=req.symbols,
        horizon=req.horizon,
        min_score=req.min_score,
        lookback=req.lookback,
        train_ratio=req.train_ratio,
    )
