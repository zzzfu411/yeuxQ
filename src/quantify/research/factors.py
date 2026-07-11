"""Built-in factor research pipeline."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from quantify.data.provider import DataProvider


class Factor(ABC):
    name: str
    higher_is_better: bool = True

    @abstractmethod
    def compute(self, as_of: str, universe: list[str], data: DataProvider) -> pd.Series:
        """Return raw cross-sectional factor values indexed by symbol."""


class MomentumFactor(Factor):
    name = "momentum_60d"
    higher_is_better = True

    def compute(self, as_of: str, universe: list[str], data: DataProvider) -> pd.Series:
        start = _lookback_start(as_of, 90)
        close = data.close_matrix(universe, start, as_of)
        if len(close) < 21:
            return pd.Series(dtype=float)
        past = close.shift(20)
        return (close.iloc[-1] / past.iloc[-1] - 1).rename(self.name)


class LongMomentumFactor(Factor):
    name = "long_momentum_120d_skip20d"
    higher_is_better = True

    def compute(self, as_of: str, universe: list[str], data: DataProvider) -> pd.Series:
        start = _lookback_start(as_of, 260)
        close = data.close_matrix(universe, start, as_of)
        if len(close) < 121:
            return pd.Series(dtype=float)
        return (close.iloc[-21] / close.iloc[-121] - 1).rename(self.name)


class ShortMomentumFactor(Factor):
    name = "momentum_20d"
    higher_is_better = True

    def compute(self, as_of: str, universe: list[str], data: DataProvider) -> pd.Series:
        start = _lookback_start(as_of, 45)
        close = data.close_matrix(universe, start, as_of)
        if len(close) < 21:
            return pd.Series(dtype=float)
        past = close.shift(20)
        return (close.iloc[-1] / past.iloc[-1] - 1).rename(self.name)


class LowVolatilityFactor(Factor):
    name = "low_volatility_60d"
    higher_is_better = True

    def compute(self, as_of: str, universe: list[str], data: DataProvider) -> pd.Series:
        start = _lookback_start(as_of, 90)
        close = data.close_matrix(universe, start, as_of)
        returns = close.pct_change().tail(60)
        vol = returns.std()
        return (-vol).rename(self.name)


class VeryLowVolatilityFactor(Factor):
    name = "low_volatility_120d"
    higher_is_better = True

    def compute(self, as_of: str, universe: list[str], data: DataProvider) -> pd.Series:
        start = _lookback_start(as_of, 180)
        close = data.close_matrix(universe, start, as_of)
        returns = close.pct_change().tail(120)
        vol = returns.std()
        return (-vol).rename(self.name)


class ValueFactor(Factor):
    name = "value_ep"
    higher_is_better = True

    def compute(self, as_of: str, universe: list[str], data: DataProvider) -> pd.Series:
        fundamentals = data.fundamentals(universe, as_of)
        if fundamentals.empty or "pe_ttm" not in fundamentals:
            return pd.Series(index=universe, dtype=float, name=self.name)
        pe = fundamentals.set_index("symbol")["pe_ttm"].astype(float)
        pe = pe.where(pe > 0)
        return (1 / pe).rename(self.name)


class QualityFactor(Factor):
    name = "quality_roe"
    higher_is_better = True

    def compute(self, as_of: str, universe: list[str], data: DataProvider) -> pd.Series:
        fundamentals = data.fundamentals(universe, as_of)
        if fundamentals.empty or "roe" not in fundamentals:
            return pd.Series(index=universe, dtype=float, name=self.name)
        return fundamentals.set_index("symbol")["roe"].astype(float).rename(self.name)


class LiquidityFactor(Factor):
    name = "liquidity_amount_20d"
    higher_is_better = True

    def compute(self, as_of: str, universe: list[str], data: DataProvider) -> pd.Series:
        start = _lookback_start(as_of, 35)
        bars = data.bars(universe, start, as_of)
        if bars.empty:
            return pd.Series(dtype=float)
        amount = bars.groupby("symbol")["amount"].tail(20).groupby(bars["symbol"]).mean()
        return np.log1p(amount.astype(float)).rename(self.name)


class LiquidityNeutralLongMomentumFactor(Factor):
    name = "liquidity_neutral_long_momentum_120d_skip20d"
    higher_is_better = True

    def compute(self, as_of: str, universe: list[str], data: DataProvider) -> pd.Series:
        start = _lookback_start(as_of, 260)
        close = data.close_matrix(universe, start, as_of)
        bars = data.bars(universe, start, as_of)
        if len(close) < 121 or bars.empty:
            return pd.Series(index=universe, dtype=float, name=self.name)
        momentum = (close.iloc[-21] / close.iloc[-121] - 1).rename("momentum")
        amount = bars.groupby("symbol")["amount"].tail(20).groupby(bars["symbol"]).mean()
        liquidity = np.log1p(amount.astype(float)).rename("liquidity")
        joined = pd.concat([momentum, liquidity], axis=1).reindex(universe)
        momentum_score = _normalize(joined["momentum"], 0.05)
        liquidity_score = _normalize(joined["liquidity"], 0.05)
        valid = momentum_score.notna() & liquidity_score.notna()
        if valid.sum() < 3:
            return pd.Series(index=universe, dtype=float, name=self.name)
        denominator = float((liquidity_score[valid] ** 2).sum())
        beta = float((momentum_score[valid] * liquidity_score[valid]).sum() / denominator) if denominator else 0.0
        residual = momentum_score - beta * liquidity_score
        return residual.rename(self.name)


@dataclass(frozen=True, slots=True)
class FactorPipelineConfig:
    winsorize_quantile: float = 0.05
    min_valid_ratio: float = 0.2


class FactorPipeline:
    """Compute raw factors, normalize cross-sectionally, and combine scores."""

    def __init__(
        self,
        factors: list[Factor] | None = None,
        config: FactorPipelineConfig | None = None,
    ) -> None:
        self.factors = factors or [
            MomentumFactor(),
            LowVolatilityFactor(),
            ValueFactor(),
            QualityFactor(),
            LiquidityFactor(),
        ]
        self.config = config or FactorPipelineConfig()

    def run(self, dates: list[str], universe: list[str], data: DataProvider) -> pd.DataFrame:
        frames = [self.run_one(day, universe, data) for day in dates]
        frames = [frame for frame in frames if not frame.empty]
        if not frames:
            return pd.DataFrame(columns=["date", "symbol", "factor_name", "value", "score"])
        return pd.concat(frames, ignore_index=True)

    def run_one(self, as_of: str, universe: list[str], data: DataProvider) -> pd.DataFrame:
        records: list[pd.DataFrame] = []
        for factor in self.factors:
            raw = factor.compute(as_of, universe, data)
            raw = raw.reindex(universe).astype(float)
            score = _normalize(raw, self.config.winsorize_quantile)
            if not factor.higher_is_better:
                score = -score
            frame = pd.DataFrame(
                {
                    "date": as_of,
                    "symbol": score.index,
                    "factor_name": factor.name,
                    "value": raw.values,
                    "score": score.values,
                }
            )
            records.append(frame)
        return pd.concat(records, ignore_index=True) if records else pd.DataFrame()

    def composite_scores(self, as_of: str, universe: list[str], data: DataProvider) -> pd.DataFrame:
        factor_scores = self.run_one(as_of, universe, data)
        if factor_scores.empty:
            return pd.DataFrame(columns=["date", "symbol", "score"])
        wide = factor_scores.pivot(index="symbol", columns="factor_name", values="score")
        valid_ratio = wide.notna().mean(axis=1)
        composite = wide.mean(axis=1, skipna=True)
        composite = composite.where(valid_ratio >= self.config.min_valid_ratio)
        return (
            composite.dropna()
            .sort_values(ascending=False)
            .rename("score")
            .reset_index()
            .assign(date=as_of)[["date", "symbol", "score"]]
        )


def rank_ic(scores: pd.Series, forward_returns: pd.Series) -> float:
    joined = pd.concat([scores.rename("score"), forward_returns.rename("forward")], axis=1).dropna()
    if len(joined) < 2:
        return 0.0
    corr = joined["score"].rank().corr(joined["forward"].rank())
    return 0.0 if pd.isna(corr) else float(corr)


def _normalize(values: pd.Series, q: float) -> pd.Series:
    clean = values.replace([np.inf, -np.inf], np.nan)
    if clean.notna().sum() < 2:
        return pd.Series(index=values.index, dtype=float)
    low = clean.quantile(q)
    high = clean.quantile(1 - q)
    clipped = clean.clip(lower=low, upper=high)
    mean = clipped.mean()
    std = clipped.std(ddof=0)
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=values.index)
    return (clipped - mean) / std


def _lookback_start(as_of: str, days: int) -> str:
    return (datetime.fromisoformat(as_of) - timedelta(days=days)).date().isoformat()
