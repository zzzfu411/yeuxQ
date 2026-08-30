"""Run multiple strategy candidates and score them against a capital goal."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from quantify.analytics.metrics import compute_report
from quantify.core.portfolio import Portfolio
from quantify.data.demo import is_mixed_demo_contaminated
from quantify.data.provider import DataProvider
from quantify.engine.paper_broker import PaperBroker, PaperBrokerConfig
from quantify.goal import CapitalGoal, StrategyCandidateScore, screen_strategy_candidate
from quantify.research.engine import ResearchEngine
from quantify.research.factors import (
    Factor,
    FactorPipeline,
    LiquidityFactor,
    LiquidityNeutralLongMomentumFactor,
    LongMomentumFactor,
    LowVolatilityFactor,
    MomentumFactor,
    QualityFactor,
    ShortMomentumFactor,
    ValueFactor,
    VeryLowVolatilityFactor,
)
from quantify.research.strategy import MultiFactorStrategyConfig, MultiFactorTargetStrategy
from quantify.research.turnover import summarize_turnover
from quantify.research.universe import UniverseConfig, UniverseFilter
from quantify.research.walk_forward_protocol import (
    CANDIDATE_WALK_FORWARD_ARTIFACT,
    SELECTION_PROTOCOL,
    validate_selection_safe_payload,
)


@dataclass(frozen=True, slots=True)
class CandidateSpec:
    name: str
    description: str
    factors: list[Factor]
    n_holdings: int
    max_weight: float
    rebalance: str
    trend_filter: bool = False
    trend_scale: float = 0.35
    trend_gate: str = "weak_trend"
    data_dependency: str = "ohlcv_plus_fundamentals"
    hold_rank_buffer: int = 0
    min_trade_weight: float = 0.0
    max_new_positions: int = 0
    score_smoothing_observations: int = 0
    score_smoothing_step_days: int = 20


@dataclass(frozen=True, slots=True)
class CandidateDataDependencyReview:
    status: str
    data_dependency: str
    required_fundamental_fields: list[str]
    field_coverage: dict[str, float]
    findings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "data_dependency": self.data_dependency,
            "required_fundamental_fields": self.required_fundamental_fields,
            "field_coverage": self.field_coverage,
            "findings": self.findings,
        }


@dataclass(frozen=True, slots=True)
class CandidateMarketRegimeReview:
    status: str
    regime_label: str
    regime_status: str
    alignment_status: str
    fit: str
    findings: list[str]
    alignment_findings: list[str]
    required_evidence: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "regime_label": self.regime_label,
            "regime_status": self.regime_status,
            "alignment_status": self.alignment_status,
            "fit": self.fit,
            "findings": self.findings,
            "alignment_findings": self.alignment_findings,
            "required_evidence": self.required_evidence,
        }


@dataclass(frozen=True, slots=True)
class CandidateWalkForwardReview:
    status: str
    window_count: int
    pass_count: int
    watch_count: int
    block_count: int
    positive_return_ratio: float
    worst_total_return: float
    worst_max_drawdown: float
    findings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "window_count": self.window_count,
            "pass_count": self.pass_count,
            "watch_count": self.watch_count,
            "block_count": self.block_count,
            "positive_return_ratio": self.positive_return_ratio,
            "worst_total_return": self.worst_total_return,
            "worst_max_drawdown": self.worst_max_drawdown,
            "findings": self.findings,
        }


@dataclass(frozen=True, slots=True)
class CandidateRegimeValidationReview:
    status: str
    known_regime_count: int
    adverse_regime_window_count: int
    pass_bucket_count: int
    watch_bucket_count: int
    block_bucket_count: int
    avg_total_return: float
    avg_max_drawdown: float
    avg_sharpe_ratio: float
    findings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "known_regime_count": self.known_regime_count,
            "adverse_regime_window_count": self.adverse_regime_window_count,
            "pass_bucket_count": self.pass_bucket_count,
            "watch_bucket_count": self.watch_bucket_count,
            "block_bucket_count": self.block_bucket_count,
            "avg_total_return": self.avg_total_return,
            "avg_max_drawdown": self.avg_max_drawdown,
            "avg_sharpe_ratio": self.avg_sharpe_ratio,
            "findings": self.findings,
        }


@dataclass(frozen=True, slots=True)
class CandidateCapitalGoalFitReview:
    status: str
    required_annual_return: float
    annual_return: float
    return_margin: float
    max_drawdown: float
    drawdown_budget: float
    worst_walk_forward_return: float
    worst_walk_forward_drawdown: float
    sharpe_ratio: float
    reject_rate: float
    avg_turnover_pct: float
    avg_maintenance_turnover_pct: float
    maintenance_turnover_observation_count: int
    findings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "required_annual_return": self.required_annual_return,
            "annual_return": self.annual_return,
            "return_margin": self.return_margin,
            "max_drawdown": self.max_drawdown,
            "drawdown_budget": self.drawdown_budget,
            "worst_walk_forward_return": self.worst_walk_forward_return,
            "worst_walk_forward_drawdown": self.worst_walk_forward_drawdown,
            "sharpe_ratio": self.sharpe_ratio,
            "reject_rate": self.reject_rate,
            "avg_turnover_pct": self.avg_turnover_pct,
            "avg_maintenance_turnover_pct": self.avg_maintenance_turnover_pct,
            "maintenance_turnover_observation_count": self.maintenance_turnover_observation_count,
            "findings": self.findings,
        }


@dataclass(frozen=True, slots=True)
class CandidateRunResult:
    spec: CandidateSpec
    score: StrategyCandidateScore
    metrics: dict[str, float | int]
    order_count: int
    reject_rate: float
    execution_initial_cash: float
    final_cash_ratio: float
    min_commission_hit_count: int
    below_lot_reject_count: int
    avg_turnover_pct: float
    initial_turnover_pct: float
    avg_maintenance_turnover_pct: float
    max_maintenance_turnover_pct: float
    maintenance_turnover_observation_count: int
    trend_filter_active_days: int
    data_dependency_review: CandidateDataDependencyReview
    market_regime_review: CandidateMarketRegimeReview
    candidate_walk_forward_review: CandidateWalkForwardReview
    candidate_regime_validation_review: CandidateRegimeValidationReview
    capital_goal_fit_review: CandidateCapitalGoalFitReview

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.spec.name,
            "description": self.spec.description,
            "factors": [factor.name for factor in self.spec.factors],
            "n_holdings": self.spec.n_holdings,
            "max_weight": self.spec.max_weight,
            "rebalance": self.spec.rebalance,
            "trend_filter": self.spec.trend_filter,
            "trend_scale": self.spec.trend_scale,
            "trend_gate": self.spec.trend_gate,
            "hold_rank_buffer": self.spec.hold_rank_buffer,
            "min_trade_weight": self.spec.min_trade_weight,
            "max_new_positions": self.spec.max_new_positions,
            "score_smoothing_observations": self.spec.score_smoothing_observations,
            "score_smoothing_step_days": self.spec.score_smoothing_step_days,
            "data_dependency": self.spec.data_dependency,
            "data_dependency_status": self.data_dependency_review.status,
            "data_dependency_review": self.data_dependency_review.to_dict(),
            "market_regime_status": self.market_regime_review.status,
            "market_regime_review": self.market_regime_review.to_dict(),
            "candidate_walk_forward_status": self.candidate_walk_forward_review.status,
            "candidate_walk_forward_review": self.candidate_walk_forward_review.to_dict(),
            "candidate_regime_validation_status": (
                self.candidate_regime_validation_review.status
            ),
            "candidate_regime_validation_review": (
                self.candidate_regime_validation_review.to_dict()
            ),
            "capital_goal_fit_status": self.capital_goal_fit_review.status,
            "capital_goal_fit_review": self.capital_goal_fit_review.to_dict(),
            "score": self.score.to_dict(),
            "metrics": self.metrics,
            "order_count": self.order_count,
            "reject_rate": self.reject_rate,
            "execution_initial_cash": self.execution_initial_cash,
            "final_cash_ratio": self.final_cash_ratio,
            "min_commission_hit_count": self.min_commission_hit_count,
            "below_lot_reject_count": self.below_lot_reject_count,
            "avg_turnover_pct": self.avg_turnover_pct,
            "initial_turnover_pct": self.initial_turnover_pct,
            "avg_maintenance_turnover_pct": self.avg_maintenance_turnover_pct,
            "max_maintenance_turnover_pct": self.max_maintenance_turnover_pct,
            "maintenance_turnover_observation_count": self.maintenance_turnover_observation_count,
            "trend_filter_active_days": self.trend_filter_active_days,
        }


@dataclass(frozen=True, slots=True)
class CandidateSelectionReport:
    status: str
    best_candidate: str
    top_candidate: str
    selected_candidate: str
    execution_initial_cash: float
    candidate_lock_selection_safe: bool
    selection_protocol: str
    evidence_inputs: dict[str, Any]
    results: list[CandidateRunResult]
    market_regime: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "best_candidate": self.best_candidate,
            "top_candidate": self.top_candidate,
            "selected_candidate": self.selected_candidate,
            "execution_initial_cash": self.execution_initial_cash,
            "candidate_lock_selection_safe": self.candidate_lock_selection_safe,
            "selection_protocol": self.selection_protocol,
            "evidence_inputs": self.evidence_inputs,
            "market_regime": self.market_regime or {},
            "results": [result.to_dict() for result in self.results],
        }

    def to_markdown(self) -> str:
        regime_label = (self.market_regime or {}).get("label", "unknown")
        regime_status = (self.market_regime or {}).get("status", "UNKNOWN")
        lines = [
            f"# Strategy Candidate Selection: {self.status}",
            "",
            f"- Selected candidate: `{self.selected_candidate or 'none'}`",
            f"- Top candidate: `{self.top_candidate or 'none'}`",
            f"- Execution initial cash: {self.execution_initial_cash:.2f}",
            f"- Candidate lock selection-safe: `{self.candidate_lock_selection_safe}`",
            f"- Market regime: `{regime_label}` (`{regime_status}`)",
            "",
            "| candidate | decision | dep | regime_fit | cwf | crv | goal_fit | score | annual_return | max_drawdown | sharpe | reject_rate | turnover | maintenance_turnover |",
            "| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for result in self.results:
            metrics = result.metrics
            lines.append(
                "| {name} | {decision} | {dep} | {regime} | {cwf} | {crv} | {goal_fit} | {score:.1f} | {ret:.2%} | {dd:.2%} | {sharpe:.2f} | {reject:.2%} | {turnover:.2%} | {maintenance:.2%} |".format(
                    name=result.spec.name,
                    decision=result.score.decision,
                    dep=result.data_dependency_review.status,
                    regime=result.market_regime_review.status,
                    cwf=result.candidate_walk_forward_review.status,
                    crv=result.candidate_regime_validation_review.status,
                    goal_fit=result.capital_goal_fit_review.status,
                    score=result.score.score,
                    ret=float(metrics.get("annualized_return", 0.0)),
                    dd=float(metrics.get("max_drawdown", 0.0)),
                    sharpe=float(metrics.get("sharpe_ratio", 0.0)),
                    reject=result.reject_rate,
                    turnover=result.avg_turnover_pct,
                    maintenance=result.avg_maintenance_turnover_pct,
                )
            )
        lines.extend(["", "## Notes"])
        for result in self.results:
            reasons = "; ".join(result.score.reasons)
            lines.append(f"- `{result.spec.name}`: {reasons}")
            for finding in result.data_dependency_review.findings:
                lines.append(f"  - Data dependency: {finding}")
            for finding in result.market_regime_review.findings:
                lines.append(f"  - Market regime: {finding}")
            for evidence in result.market_regime_review.required_evidence:
                lines.append(f"  - Market evidence required: {evidence}")
            for finding in result.candidate_walk_forward_review.findings:
                lines.append(f"  - Candidate walk-forward: {finding}")
            for finding in result.candidate_regime_validation_review.findings:
                lines.append(f"  - Candidate regime validation: {finding}")
            for finding in result.capital_goal_fit_review.findings:
                lines.append(f"  - Capital-goal fit: {finding}")
        lines.append("")
        lines.append("This is a research ranking, not a promise of profit or a live trading instruction.")
        return "\n".join(lines) + "\n"


class TrendFilteredTargetStrategy(MultiFactorTargetStrategy):
    """Reduce exposure when the broad universe trend is weak."""

    def __init__(
        self,
        universe_filter: UniverseFilter,
        factor_pipeline: FactorPipeline,
        config: MultiFactorStrategyConfig,
        trend_scale: float = 0.35,
        trend_gate: str = "weak_trend",
        market_regime: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(universe_filter, factor_pipeline, config)
        self.trend_scale = trend_scale
        self.trend_gate = trend_gate
        self.market_regime = market_regime or {}
        self.active_days = 0

    def on_rebalance(self, as_of: str, data: DataProvider, portfolio: Portfolio):
        targets = super().on_rebalance(as_of, data, portfolio)
        if not targets:
            return targets
        universe = self.universe_filter.symbols(as_of, data)
        if self.trend_gate == "defensive_or_worse":
            if self._defensive_gate_label(as_of, universe, data) in {"defensive", "risk_off"}:
                self.active_days += 1
                return [
                    type(target)(
                        timestamp=target.timestamp,
                        symbol=target.symbol,
                        target_weight=0.0,
                        score=target.score,
                    )
                    for target in targets
                ]
            return targets
        if _broad_trend_is_weak(as_of, universe, data):
            self.active_days += 1
            return [
                type(target)(
                    timestamp=target.timestamp,
                    symbol=target.symbol,
                    target_weight=target.target_weight * self.trend_scale,
                    score=target.score,
                )
                for target in targets
            ]
        return targets

    def _defensive_gate_label(
        self,
        as_of: str,
        universe: list[str],
        data: DataProvider,
    ) -> str:
        label = _normalized_market_regime_label(self.market_regime)
        regime_as_of = str(
            self.market_regime.get("as_of")
            or self.market_regime.get("end")
            or ""
        )
        if label != "unknown" and regime_as_of == as_of:
            return label
        return _normalized_market_regime_label(
            runtime_market_regime(data, as_of=as_of, symbols=universe)
        )


def default_candidate_specs(cfg) -> list[CandidateSpec]:
    base_holdings = int(cfg.strategy.n_holdings)
    base_weight = float(cfg.strategy.max_weight)
    rebalance = str(cfg.research.rebalance)
    return [
        CandidateSpec(
            name="price_volume_defensive",
            description=(
                "OHLCV-only defensive price-volume basket for data packages without point-in-time fundamentals."
            ),
            factors=[
                MomentumFactor(),
                ShortMomentumFactor(),
                LowVolatilityFactor(),
                VeryLowVolatilityFactor(),
                LiquidityFactor(),
            ],
            n_holdings=max(15, base_holdings),
            max_weight=min(base_weight, 0.04),
            rebalance=rebalance,
            data_dependency="ohlcv_only",
        ),
        CandidateSpec(
            name="low_turnover_price_volume",
            description=(
                "OHLCV-only low-turnover defensive basket using low volatility, liquidity, and slower momentum."
            ),
            factors=[
                LowVolatilityFactor(),
                VeryLowVolatilityFactor(),
                MomentumFactor(),
                LiquidityFactor(),
            ],
            n_holdings=max(40, base_holdings),
            max_weight=min(base_weight, 0.035),
            rebalance="quarterly",
            data_dependency="ohlcv_only",
        ),
        CandidateSpec(
            name="low_turnover_low_concentration_price_volume",
            description=(
                "OHLCV-only low-turnover defensive basket with lower concentration for cost and drawdown resilience."
            ),
            factors=[
                LowVolatilityFactor(),
                VeryLowVolatilityFactor(),
                MomentumFactor(),
                LiquidityFactor(),
            ],
            n_holdings=max(40, base_holdings),
            max_weight=min(base_weight, 0.0245),
            rebalance="quarterly",
            data_dependency="ohlcv_only",
        ),
        CandidateSpec(
            name="trend_filtered_price_volume",
            description=(
                "OHLCV-only defensive price-volume basket with broad-trend exposure reduction."
            ),
            factors=[
                MomentumFactor(),
                ShortMomentumFactor(),
                LowVolatilityFactor(),
                VeryLowVolatilityFactor(),
                LiquidityFactor(),
            ],
            n_holdings=max(30, base_holdings),
            max_weight=min(base_weight, 0.035),
            rebalance=rebalance,
            trend_filter=True,
            trend_scale=0.35,
            data_dependency="ohlcv_only",
        ),
        CandidateSpec(
            name="trend_filtered_quarterly_price_volume",
            description=(
                "OHLCV-only defensive price-volume basket with broad-trend exposure reduction and quarterly rebalance."
            ),
            factors=[
                MomentumFactor(),
                ShortMomentumFactor(),
                LowVolatilityFactor(),
                VeryLowVolatilityFactor(),
                LiquidityFactor(),
            ],
            n_holdings=max(30, base_holdings),
            max_weight=min(base_weight, 0.035),
            rebalance="quarterly",
            trend_filter=True,
            trend_scale=0.35,
            data_dependency="ohlcv_only",
        ),
        CandidateSpec(
            name="trend_filtered_quarterly_low_concentration_price_volume",
            description=(
                "OHLCV-only quarterly trend-filtered basket with lower concentration for drawdown and turnover resilience."
            ),
            factors=[
                MomentumFactor(),
                ShortMomentumFactor(),
                LowVolatilityFactor(),
                VeryLowVolatilityFactor(),
                LiquidityFactor(),
            ],
            n_holdings=max(30, base_holdings),
            max_weight=min(base_weight, 0.0245),
            rebalance="quarterly",
            trend_filter=True,
            trend_scale=0.35,
            data_dependency="ohlcv_only",
        ),
        CandidateSpec(
            name="defensive_scaled_quarterly_price_volume",
            description=(
                "OHLCV-only quarterly price-volume basket that keeps rebound participation but cuts exposure in defensive regimes."
            ),
            factors=[
                MomentumFactor(),
                ShortMomentumFactor(),
                LowVolatilityFactor(),
                VeryLowVolatilityFactor(),
                LiquidityFactor(),
            ],
            n_holdings=max(30, base_holdings),
            max_weight=min(base_weight, 0.03),
            rebalance="quarterly",
            trend_filter=True,
            trend_scale=0.15,
            trend_gate="defensive_or_worse",
            data_dependency="ohlcv_only",
        ),
        CandidateSpec(
            name="stable_universe_slow_signal_price_volume",
            description=(
                "OHLCV-only wide quarterly basket using slow momentum, very low volatility, and liquidity "
                "to test whether structural signal stability beats order-path turnover controls."
            ),
            factors=[
                VeryLowVolatilityFactor(),
                LowVolatilityFactor(),
                LongMomentumFactor(),
                LiquidityFactor(),
            ],
            n_holdings=max(80, base_holdings),
            max_weight=min(base_weight, 0.02),
            rebalance="quarterly",
            data_dependency="ohlcv_only",
        ),
        CandidateSpec(
            name="long_momentum_liquidity_monthly_price_volume",
            description=(
                "OHLCV-only component-ablation candidate using long momentum and liquidity after the "
                "slow-signal basket showed low-volatility dilution."
            ),
            factors=[
                LongMomentumFactor(),
                LiquidityFactor(),
            ],
            n_holdings=max(80, base_holdings),
            max_weight=min(base_weight, 0.02),
            rebalance="monthly",
            data_dependency="ohlcv_only",
        ),
        CandidateSpec(
            name="liquidity_neutral_momentum_guard_price_volume",
            description=(
                "OHLCV-only guarded candidate using liquidity-neutral long momentum and very low volatility "
                "after the long-momentum/liquidity ablation showed liquidity dependency and defensive losses."
            ),
            factors=[
                LiquidityNeutralLongMomentumFactor(),
                VeryLowVolatilityFactor(),
            ],
            n_holdings=max(100, base_holdings),
            max_weight=min(base_weight, 0.015),
            rebalance="quarterly",
            trend_filter=True,
            trend_scale=0.15,
            trend_gate="defensive_or_worse",
            data_dependency="ohlcv_only",
        ),
        CandidateSpec(
            name="defensive_cash_guard_price_volume",
            description=(
                "OHLCV-only defensive cash-guard basket with very low concentration and stronger weak-market exposure cuts."
            ),
            factors=[
                VeryLowVolatilityFactor(),
                LowVolatilityFactor(),
                LiquidityFactor(),
            ],
            n_holdings=max(60, base_holdings),
            max_weight=min(base_weight, 0.025),
            rebalance="quarterly",
            trend_filter=True,
            trend_scale=0.15,
            data_dependency="ohlcv_only",
        ),
        CandidateSpec(
            name="risk_off_cash_stop_price_volume",
            description=(
                "OHLCV-only defensive basket that moves fully to cash when the broad trend is weak."
            ),
            factors=[
                VeryLowVolatilityFactor(),
                LiquidityFactor(),
                LowVolatilityFactor(),
            ],
            n_holdings=max(80, base_holdings),
            max_weight=min(base_weight, 0.02),
            rebalance="monthly",
            trend_filter=True,
            trend_scale=0.0,
            data_dependency="ohlcv_only",
        ),
        CandidateSpec(
            name="regime_pause_price_volume",
            description=(
                "OHLCV-only defensive price-volume basket that pauses exposure when market regime is defensive or risk_off."
            ),
            factors=[
                MomentumFactor(),
                ShortMomentumFactor(),
                LowVolatilityFactor(),
                VeryLowVolatilityFactor(),
                LiquidityFactor(),
            ],
            n_holdings=max(30, base_holdings),
            max_weight=min(base_weight, 0.035),
            rebalance=rebalance,
            trend_filter=True,
            trend_scale=0.0,
            trend_gate="defensive_or_worse",
            data_dependency="ohlcv_only",
        ),
        CandidateSpec(
            name="core_multifactor",
            description="Balanced momentum, low-volatility, value, quality, and liquidity.",
            factors=[MomentumFactor(), LowVolatilityFactor(), ValueFactor(), QualityFactor(), LiquidityFactor()],
            n_holdings=base_holdings,
            max_weight=base_weight,
            rebalance=rebalance,
        ),
        CandidateSpec(
            name="defensive_low_vol",
            description="Low-volatility and liquidity focused defensive basket.",
            factors=[LowVolatilityFactor(), VeryLowVolatilityFactor(), LiquidityFactor(), QualityFactor()],
            n_holdings=max(10, base_holdings),
            max_weight=min(base_weight, 0.04),
            rebalance=rebalance,
        ),
        CandidateSpec(
            name="momentum_quality",
            description="Momentum plus quality, with liquidity control.",
            factors=[ShortMomentumFactor(), MomentumFactor(), QualityFactor(), LiquidityFactor()],
            n_holdings=max(10, base_holdings // 2),
            max_weight=base_weight,
            rebalance=rebalance,
        ),
        CandidateSpec(
            name="value_low_vol",
            description="Value plus low-volatility mean-reversion style basket.",
            factors=[ValueFactor(), LowVolatilityFactor(), VeryLowVolatilityFactor(), LiquidityFactor()],
            n_holdings=base_holdings,
            max_weight=base_weight,
            rebalance=rebalance,
        ),
        CandidateSpec(
            name="trend_filtered_core",
            description="Core multi-factor with broad-trend exposure reduction.",
            factors=[MomentumFactor(), LowVolatilityFactor(), ValueFactor(), QualityFactor(), LiquidityFactor()],
            n_holdings=base_holdings,
            max_weight=base_weight,
            rebalance=rebalance,
            trend_filter=True,
        ),
    ]


def candidate_specs_for_names(cfg, names: list[str] | None = None) -> list[CandidateSpec]:
    specs = default_candidate_specs(cfg)
    requested = {name for name in names or [] if name}
    if not requested:
        return specs
    return [spec for spec in specs if spec.name in requested]


def candidate_spec_by_name(cfg, name: str | None = None) -> CandidateSpec:
    specs = default_candidate_specs(cfg)
    if not name:
        return specs[0]
    for spec in specs:
        if spec.name == name:
            return spec
    available = ", ".join(spec.name for spec in specs)
    raise ValueError(f"Unknown candidate {name!r}; available candidates: {available}")


def run_candidate_selection(
    data: DataProvider,
    cfg,
    *,
    goal: CapitalGoal,
    data_audit_status: str,
    robustness_status: str,
    market_regime: dict[str, Any] | None = None,
    candidate_walk_forward: dict[str, Any] | None = None,
    candidate_regime_validation: dict[str, Any] | None = None,
    specs: list[CandidateSpec] | None = None,
) -> CandidateSelectionReport:
    effective_data_audit_status = (
        "BLOCK" if is_mixed_demo_contaminated(data.all_symbols()) else data_audit_status
    )
    results = [
        _run_candidate(
            data,
            cfg,
            goal,
            spec,
            effective_data_audit_status,
            robustness_status,
            market_regime,
            candidate_walk_forward,
            candidate_regime_validation,
        )
        for spec in (specs or default_candidate_specs(cfg))
    ]
    ranked = sorted(results, key=lambda result: result.score.score, reverse=True)
    top = ranked[0] if ranked else None
    selection_validation = validate_selection_safe_payload(
        candidate_walk_forward if isinstance(candidate_walk_forward, dict) else {},
        artifact_type=CANDIDATE_WALK_FORWARD_ARTIFACT,
    )
    if selection_validation.safe:
        locked_name = _candidate_walk_forward_selected_candidate(candidate_walk_forward)
        locked = next((result for result in ranked if result.spec.name == locked_name), None)
        status = locked.score.decision if locked is not None else "BLOCK"
        selected = locked if locked is not None and status != "BLOCK" else None
    else:
        selected = None
        status = "BLOCK"
    return CandidateSelectionReport(
        status=status,
        best_candidate=selected.spec.name if selected else "",
        top_candidate=top.spec.name if top else "",
        selected_candidate=selected.spec.name if selected else "",
        execution_initial_cash=float(goal.starting_capital),
        candidate_lock_selection_safe=selection_validation.safe,
        selection_protocol=SELECTION_PROTOCOL,
        evidence_inputs={
            "candidate_walk_forward_report.json": {
                "sha256": _payload_sha256(candidate_walk_forward),
                "selection_safe": selection_validation.safe,
                "validation_reasons": selection_validation.reasons,
            },
            "robustness_report.json": {
                "status": str(robustness_status or "UNKNOWN").upper(),
                "selection_safe": False,
                "evidence_role": "status_only_legacy_input",
            },
        },
        results=ranked,
        market_regime=market_regime or {},
    )


def write_candidate_selection_report(report: CandidateSelectionReport, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "candidate_selection.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "candidate_selection.md").write_text(report.to_markdown(), encoding="utf-8")
    pd.DataFrame([_flat_result(result) for result in report.results]).to_csv(
        root / "candidate_selection.csv",
        index=False,
    )
    return root


def _run_candidate(
    data: DataProvider,
    cfg,
    goal: CapitalGoal,
    spec: CandidateSpec,
    data_audit_status: str,
    robustness_status: str,
    market_regime: dict[str, Any] | None,
    candidate_walk_forward: dict[str, Any] | None,
    candidate_regime_validation: dict[str, Any] | None,
) -> CandidateRunResult:
    pipeline = FactorPipeline(factors=spec.factors)
    universe_filter = UniverseFilter(
        UniverseConfig(
            mode=cfg.universe.mode,
            index_code=cfg.universe.index_code,
            include_st=cfg.universe.include_st,
            min_history_days=cfg.universe.min_history_days,
        )
    )
    dependency_review = _review_data_dependency(data, cfg, spec, universe_filter)
    strategy_config = MultiFactorStrategyConfig(
        n_holdings=spec.n_holdings,
        max_weight=spec.max_weight,
        hold_rank_buffer=spec.hold_rank_buffer,
        min_trade_weight=spec.min_trade_weight,
        max_new_positions=spec.max_new_positions,
        score_smoothing_observations=spec.score_smoothing_observations,
        score_smoothing_step_days=spec.score_smoothing_step_days,
    )
    strategy: MultiFactorTargetStrategy
    if spec.trend_filter:
        strategy = TrendFilteredTargetStrategy(
            universe_filter,
            pipeline,
            strategy_config,
            trend_scale=spec.trend_scale,
            trend_gate=spec.trend_gate,
            market_regime=market_regime,
        )
    else:
        strategy = MultiFactorTargetStrategy(universe_filter, pipeline, strategy_config)
    broker = PaperBroker(
        PaperBrokerConfig(
            commission_rate=cfg.broker.commission_rate,
            min_commission=cfg.broker.min_commission,
            stamp_tax=cfg.broker.stamp_tax,
            slippage_bps=cfg.broker.slippage_bps,
            price_limit_pct=cfg.broker.price_limit_pct,
            lot_size=cfg.broker.lot_size,
        )
    )
    execution_initial_cash = float(goal.starting_capital)
    engine = ResearchEngine(
        data,
        strategy,
        broker,
        Portfolio(initial_cash=execution_initial_cash),
        pipeline,
        max_drawdown_stop=cfg.risk.max_drawdown_stop,
    )
    result = engine.run(cfg.research.start, cfg.research.end, rebalance=spec.rebalance)
    metrics = compute_report(
        result.equity_curve,
        result.fills,
        initial_equity=execution_initial_cash,
    ).to_dict()
    reject_count = sum(1 for order in result.orders if order.status == "rejected")
    reject_rate = reject_count / len(result.orders) if result.orders else 0.0
    below_lot_reject_count = sum(
        1 for order in result.orders if order.status == "rejected" and order.reason == "below_lot"
    )
    min_commission = float(broker.config.min_commission)
    min_commission_hit_count = sum(
        1
        for fill in result.fills
        if min_commission > 0 and abs(float(fill.commission) - min_commission) <= 1e-9
    )
    final_equity = float(metrics.get("final_equity", 0.0) or 0.0)
    final_cash_ratio = float(result.portfolio.cash) / final_equity if final_equity > 0 else 0.0
    turnover_summary = summarize_turnover(result.turnover)
    avg_turnover = float(turnover_summary["avg_turnover_pct"])
    avg_maintenance_turnover = float(turnover_summary["avg_maintenance_turnover_pct"])
    maintenance_turnover_count = int(turnover_summary["maintenance_turnover_observation_count"])
    score = screen_strategy_candidate(
        metrics,
        goal=goal,
        reject_rate=reject_rate,
        robustness_status=robustness_status,
        data_audit_status=data_audit_status,
    )
    score = _apply_data_dependency_score(score, dependency_review)
    market_review = _review_market_regime_fit(market_regime, spec, cfg)
    score = _apply_market_regime_score(score, market_review)
    walk_forward_review = _review_candidate_walk_forward(candidate_walk_forward, spec)
    score = _apply_candidate_walk_forward_score(score, walk_forward_review)
    regime_validation_review = _review_candidate_regime_validation(
        candidate_regime_validation,
        spec,
    )
    score = _apply_candidate_regime_validation_score(score, regime_validation_review)
    capital_fit = _review_capital_goal_fit(
        goal,
        metrics=metrics,
        reject_rate=reject_rate,
        avg_turnover=avg_turnover,
        avg_maintenance_turnover=avg_maintenance_turnover,
        maintenance_turnover_count=maintenance_turnover_count,
        walk_forward_review=walk_forward_review,
    )
    score = _apply_capital_goal_fit_score(score, capital_fit)
    return CandidateRunResult(
        spec=spec,
        score=score,
        metrics=metrics,
        order_count=len(result.orders),
        reject_rate=reject_rate,
        execution_initial_cash=execution_initial_cash,
        final_cash_ratio=final_cash_ratio,
        min_commission_hit_count=min_commission_hit_count,
        below_lot_reject_count=below_lot_reject_count,
        avg_turnover_pct=avg_turnover,
        initial_turnover_pct=float(turnover_summary["initial_turnover_pct"]),
        avg_maintenance_turnover_pct=avg_maintenance_turnover,
        max_maintenance_turnover_pct=float(turnover_summary["max_maintenance_turnover_pct"]),
        maintenance_turnover_observation_count=maintenance_turnover_count,
        trend_filter_active_days=getattr(strategy, "active_days", 0),
        data_dependency_review=dependency_review,
        market_regime_review=market_review,
        candidate_walk_forward_review=walk_forward_review,
        candidate_regime_validation_review=regime_validation_review,
        capital_goal_fit_review=capital_fit,
    )


def _broad_trend_is_weak(as_of: str, universe: list[str], data: DataProvider) -> bool:
    if not universe:
        return True
    close = data.close_matrix(universe, _lookback_start(as_of, 220), as_of)
    close = close.apply(pd.to_numeric, errors="coerce").where(lambda frame: frame > 0)
    close = close.dropna(how="all").ffill()
    if len(close) < 60:
        return False
    returns = close / close.shift(1) - 1
    market_returns = returns.mean(axis=1, skipna=True).dropna()
    if market_returns.empty:
        return False
    market_index = (1 + market_returns).cumprod()
    ret20 = _horizon_return(market_index, 20)
    ret60 = _horizon_return(market_index, 60)
    breadth20 = _breadth_above_ma(close, 20)
    breadth60 = _breadth_above_ma(close, 60)
    current_drawdown = _current_drawdown(market_index)
    if len(market_index) >= 120 and market_index.tail(60).mean() < market_index.tail(120).mean():
        return True
    if ret60 <= -0.05:
        return True
    if ret20 <= -0.03:
        return True
    if breadth60 < 0.40 and ret20 <= 0.0:
        return True
    if breadth20 < 0.35 and ret20 <= 0.0:
        return True
    return current_drawdown >= 0.10


def _horizon_return(series: pd.Series, horizon: int) -> float:
    if len(series) <= horizon:
        return 0.0
    return float(series.iloc[-1] / series.iloc[-(horizon + 1)] - 1)


def _breadth_above_ma(close: pd.DataFrame, window: int) -> float:
    if len(close) < window:
        return 0.5
    ma = close.rolling(window=window, min_periods=window).mean().iloc[-1]
    latest = close.iloc[-1]
    valid = latest.notna() & ma.notna()
    if int(valid.sum()) == 0:
        return 0.5
    return float((latest[valid] > ma[valid]).mean())


def _current_drawdown(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    peak = series.cummax().iloc[-1]
    if peak <= 0:
        return 0.0
    return float(1 - series.iloc[-1] / peak)


def _lookback_start(as_of: str, days: int) -> str:
    return (pd.Timestamp(as_of) - pd.Timedelta(days=days)).date().isoformat()


def runtime_market_regime(
    data: DataProvider,
    *,
    as_of: str,
    symbols: list[str] | None = None,
    lookback_days: int = 220,
) -> dict[str, Any]:
    from quantify.market import detect_market_regime

    start = _lookback_start(as_of, lookback_days)
    return detect_market_regime(data, start, as_of, symbols=symbols).to_dict()


def _selection_status(results: list[CandidateRunResult]) -> str:
    if any(result.score.decision == "PASS" for result in results):
        return "PASS"
    if any(result.score.decision == "WATCH" for result in results):
        return "WATCH"
    return "BLOCK"


def _selected_candidate(results: list[CandidateRunResult]) -> CandidateRunResult | None:
    return next((result for result in results if result.score.decision != "BLOCK"), None)


def _candidate_walk_forward_selection_safe(report: dict[str, Any] | None) -> bool:
    payload = report if isinstance(report, dict) else {}
    return validate_selection_safe_payload(
        payload,
        artifact_type=CANDIDATE_WALK_FORWARD_ARTIFACT,
    ).safe


def _candidate_walk_forward_selected_candidate(report: dict[str, Any] | None) -> str:
    if not isinstance(report, dict):
        return ""
    for key in ("selected_candidate", "best_candidate"):
        candidate = str(report.get(key) or "").strip()
        if candidate:
            return candidate
    return ""


def _payload_sha256(payload: dict[str, Any] | None) -> str:
    encoded = json.dumps(
        payload or {},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _apply_market_regime_score(
    score: StrategyCandidateScore,
    review: CandidateMarketRegimeReview,
) -> StrategyCandidateScore:
    reasons = list(score.reasons)
    adjusted = float(score.score)
    reasons.extend(review.findings)
    if review.status == "BLOCK":
        adjusted -= 20
        decision = "BLOCK"
    elif review.status == "WATCH":
        adjusted -= 10
        decision = "WATCH" if score.decision == "PASS" or adjusted < 80 else score.decision
    else:
        decision = score.decision
    if adjusted < 50:
        decision = "BLOCK"
    elif adjusted < 80 and decision == "PASS":
        decision = "WATCH"

    return StrategyCandidateScore(
        decision=decision,
        score=max(adjusted, 0.0),
        reasons=reasons,
        metrics=score.metrics,
    )


def _review_candidate_walk_forward(
    report: dict[str, Any] | None,
    spec: CandidateSpec,
) -> CandidateWalkForwardReview:
    payload = report if isinstance(report, dict) else {}
    selection_validation = validate_selection_safe_payload(
        payload,
        artifact_type=CANDIDATE_WALK_FORWARD_ARTIFACT,
    )
    if not selection_validation.safe:
        return CandidateWalkForwardReview(
            status="BLOCK",
            window_count=0,
            pass_count=0,
            watch_count=0,
            block_count=0,
            positive_return_ratio=0.0,
            worst_total_return=0.0,
            worst_max_drawdown=0.0,
            findings=[
                "candidate_walk_forward_report.json does not satisfy the selection-safe v2 "
                "contract: "
                + "; ".join(selection_validation.reasons)
            ],
        )
    summaries = report.get("summaries", [])
    selected = next(
        (
            item
            for item in summaries
            if isinstance(item, dict) and str(item.get("candidate", "")) == spec.name
        ),
        None,
    )
    if not isinstance(selected, dict):
        return CandidateWalkForwardReview(
            status="UNKNOWN",
            window_count=0,
            pass_count=0,
            watch_count=0,
            block_count=0,
            positive_return_ratio=0.0,
            worst_total_return=0.0,
            worst_max_drawdown=0.0,
            findings=[f"No candidate walk-forward summary exists for {spec.name}."],
        )

    status = str(selected.get("status", "UNKNOWN") or "UNKNOWN").upper()
    window_count = _int_value(selected.get("window_count"))
    pass_count = _int_value(selected.get("pass_count"))
    watch_count = _int_value(selected.get("watch_count"))
    block_count = _int_value(selected.get("block_count"))
    positive_ratio = _float_value(selected.get("positive_return_ratio"))
    worst_return = _float_value(selected.get("worst_total_return"))
    worst_drawdown = _float_value(selected.get("worst_max_drawdown"))
    findings = [f"Candidate walk-forward status is {status} across {window_count} windows."]
    missing = [
        key
        for key in ("positive_return_ratio", "worst_total_return", "worst_max_drawdown")
        if key not in selected
    ]
    if missing:
        findings.append(f"Missing candidate walk-forward stability fields: {', '.join(missing)}.")
        status = "WATCH" if status == "PASS" else status
    if status == "BLOCK":
        findings.append("At least one walk-forward stability blocker is present.")
    elif status == "WATCH":
        findings.append("Walk-forward stability is watch-only; do not treat ranking as promotion evidence.")
    if "positive_return_ratio" in selected and positive_ratio < 0.60:
        findings.append("Fewer than 60% of candidate walk-forward windows have positive returns.")
        status = "WATCH" if status == "PASS" else status
    if worst_return <= -0.10:
        findings.append("Worst candidate walk-forward window lost more than 10%.")
        status = "BLOCK"
    elif worst_return <= -0.05:
        findings.append("Worst candidate walk-forward window lost more than 5%.")
        status = "WATCH" if status == "PASS" else status
    if worst_drawdown >= 0.25:
        findings.append("Worst candidate walk-forward drawdown breached 25%.")
        status = "BLOCK"
    elif worst_drawdown >= 0.15:
        findings.append("Worst candidate walk-forward drawdown breached 15%.")
        status = "WATCH" if status == "PASS" else status

    return CandidateWalkForwardReview(
        status=status if status in {"PASS", "WATCH", "BLOCK", "UNKNOWN"} else "UNKNOWN",
        window_count=window_count,
        pass_count=pass_count,
        watch_count=watch_count,
        block_count=block_count,
        positive_return_ratio=positive_ratio,
        worst_total_return=worst_return,
        worst_max_drawdown=worst_drawdown,
        findings=findings,
    )


def _apply_candidate_walk_forward_score(
    score: StrategyCandidateScore,
    review: CandidateWalkForwardReview,
) -> StrategyCandidateScore:
    if review.status in {"PASS", "UNKNOWN"}:
        return score
    reasons = list(score.reasons)
    reasons.append(f"Candidate walk-forward gate is {review.status}: {'; '.join(review.findings)}")
    adjusted = float(score.score) - (40.0 if review.status == "BLOCK" else 15.0)
    decision = (
        "BLOCK"
        if score.decision == "BLOCK" or review.status == "BLOCK" or adjusted < 50
        else "WATCH"
    )
    return StrategyCandidateScore(
        decision=decision,
        score=max(adjusted, 0.0),
        reasons=reasons,
        metrics=score.metrics,
    )


def _review_candidate_regime_validation(
    report: dict[str, Any] | None,
    spec: CandidateSpec,
) -> CandidateRegimeValidationReview:
    if not report:
        return CandidateRegimeValidationReview(
            status="UNKNOWN",
            known_regime_count=0,
            adverse_regime_window_count=0,
            pass_bucket_count=0,
            watch_bucket_count=0,
            block_bucket_count=0,
            avg_total_return=0.0,
            avg_max_drawdown=0.0,
            avg_sharpe_ratio=0.0,
            findings=[
                "candidate_regime_validation_report.json was not supplied; "
                "cross-regime promotion evidence is missing."
            ],
        )
    summaries = report.get("summaries", [])
    selected = next(
        (
            item
            for item in summaries
            if isinstance(item, dict) and str(item.get("candidate", "")) == spec.name
        ),
        None,
    )
    if not isinstance(selected, dict):
        return CandidateRegimeValidationReview(
            status="UNKNOWN",
            known_regime_count=0,
            adverse_regime_window_count=0,
            pass_bucket_count=0,
            watch_bucket_count=0,
            block_bucket_count=0,
            avg_total_return=0.0,
            avg_max_drawdown=0.0,
            avg_sharpe_ratio=0.0,
            findings=[f"No candidate regime validation summary exists for {spec.name}."],
        )

    status = str(selected.get("status", "UNKNOWN") or "UNKNOWN").upper()
    report_status = str(report.get("status", "UNKNOWN") or "UNKNOWN").upper()
    warnings = [
        str(item)
        for item in report.get("warnings", [])
        if str(item).strip()
    ]
    known_count = _int_value(selected.get("known_regime_count"))
    adverse_count = _int_value(selected.get("adverse_regime_window_count"))
    pass_count = _int_value(selected.get("pass_bucket_count"))
    watch_count = _int_value(selected.get("watch_bucket_count"))
    block_count = _int_value(selected.get("block_bucket_count"))
    avg_return = _float_value(selected.get("avg_total_return"))
    avg_drawdown = _float_value(selected.get("avg_max_drawdown"))
    avg_sharpe = _float_value(selected.get("avg_sharpe_ratio"))
    findings = [
        (
            "Candidate regime validation status is "
            f"{status} across {known_count} known regimes and {adverse_count} adverse windows."
        )
    ]
    missing = [
        key
        for key in (
            "known_regime_count",
            "adverse_regime_window_count",
            "pass_bucket_count",
            "watch_bucket_count",
            "block_bucket_count",
        )
        if key not in selected
    ]
    if missing:
        findings.append(f"Missing candidate regime validation fields: {', '.join(missing)}.")
        status = "WATCH" if status == "PASS" else status
    if report_status == "BLOCK" and status != "BLOCK":
        findings.append("Overall candidate regime validation report is BLOCK.")
        status = "WATCH" if status == "PASS" else status
    elif report_status == "WATCH" and status == "PASS":
        findings.append("Overall candidate regime validation report is WATCH.")
        status = "WATCH"
    if warnings and status == "PASS":
        findings.append(f"Report-level regime validation warnings: {'; '.join(warnings)}")
        status = "WATCH"
    if status == "BLOCK":
        findings.append("Regime-stratified validation is BLOCK for this candidate.")
    elif status == "WATCH":
        findings.append("Regime-stratified validation is watch-only; keep as research evidence.")
    if block_count > 0:
        findings.append("At least one market-regime bucket is BLOCK.")
        status = "BLOCK"
    if known_count < 2:
        findings.append("Fewer than 2 known market regimes were validated for this candidate.")
        status = "WATCH" if status == "PASS" else status
    if adverse_count == 0:
        findings.append("No defensive or risk_off validation windows were observed.")
        status = "WATCH" if status == "PASS" else status
    if avg_return <= 0 and status == "PASS":
        findings.append("Average regime validation return is non-positive.")
        status = "WATCH"

    return CandidateRegimeValidationReview(
        status=status if status in {"PASS", "WATCH", "BLOCK", "UNKNOWN"} else "UNKNOWN",
        known_regime_count=known_count,
        adverse_regime_window_count=adverse_count,
        pass_bucket_count=pass_count,
        watch_bucket_count=watch_count,
        block_bucket_count=block_count,
        avg_total_return=avg_return,
        avg_max_drawdown=avg_drawdown,
        avg_sharpe_ratio=avg_sharpe,
        findings=findings,
    )


def _apply_candidate_regime_validation_score(
    score: StrategyCandidateScore,
    review: CandidateRegimeValidationReview,
) -> StrategyCandidateScore:
    if review.status == "PASS":
        return score
    reasons = list(score.reasons)
    reasons.append(
        f"Candidate regime validation gate is {review.status}: {'; '.join(review.findings)}"
    )
    if review.status == "UNKNOWN":
        adjusted = float(score.score)
    else:
        adjusted = float(score.score) - (40.0 if review.status == "BLOCK" else 15.0)
    decision = (
        "BLOCK"
        if score.decision == "BLOCK" or review.status == "BLOCK" or adjusted < 50
        else "WATCH"
    )
    return StrategyCandidateScore(
        decision=decision,
        score=max(adjusted, 0.0),
        reasons=reasons,
        metrics=score.metrics,
    )


def _review_capital_goal_fit(
    goal: CapitalGoal,
    *,
    metrics: dict[str, float | int],
    reject_rate: float,
    avg_turnover: float,
    avg_maintenance_turnover: float,
    maintenance_turnover_count: int,
    walk_forward_review: CandidateWalkForwardReview,
) -> CandidateCapitalGoalFitReview:
    annual_return = _float_value(metrics.get("annualized_return"))
    required = goal.required_annual_return()
    return_margin = annual_return - required
    max_drawdown = _float_value(metrics.get("max_drawdown"))
    sharpe = _float_value(metrics.get("sharpe_ratio"))
    worst_return = walk_forward_review.worst_total_return
    worst_drawdown = walk_forward_review.worst_max_drawdown
    findings: list[str] = []
    severities: list[str] = []

    if annual_return <= 0:
        severities.append("BLOCK")
        findings.append(
            f"Annualized return {annual_return:.2%} is not positive; it cannot support compounding research."
        )
    elif annual_return < required:
        severities.append("WATCH")
        findings.append(
            f"Annualized return {annual_return:.2%} is below required path {required:.2%}; keep as research-only."
        )
    elif return_margin < 0.05:
        severities.append("WATCH")
        findings.append(
            f"Annualized return margin is only {return_margin:.2%}; require more safety margin before paper promotion."
        )
    else:
        findings.append(f"Annualized return margin is {return_margin:.2%} above the required path.")

    if max_drawdown > goal.max_drawdown_budget:
        severities.append("BLOCK")
        findings.append(
            f"Max drawdown {max_drawdown:.2%} exceeds budget {goal.max_drawdown_budget:.2%}."
        )
    elif max_drawdown > goal.max_drawdown_budget * 0.75:
        severities.append("WATCH")
        findings.append(
            f"Max drawdown {max_drawdown:.2%} is close to budget {goal.max_drawdown_budget:.2%}."
        )
    else:
        findings.append(f"Max drawdown {max_drawdown:.2%} is inside the drawdown budget.")

    if walk_forward_review.status == "UNKNOWN":
        severities.append("WATCH")
        findings.append("Candidate walk-forward evidence is missing; goal fit is single-run only.")
    elif walk_forward_review.status == "BLOCK":
        severities.append("BLOCK")
        findings.append("Candidate walk-forward review is BLOCK.")
    elif walk_forward_review.status == "WATCH":
        severities.append("WATCH")
        findings.append("Candidate walk-forward review has WATCH findings.")
    if walk_forward_review.status != "UNKNOWN":
        if worst_return < -0.05:
            severities.append("WATCH")
            findings.append(f"Worst walk-forward return {worst_return:.2%} has weak downside resilience.")
        if worst_drawdown > goal.max_drawdown_budget:
            severities.append("BLOCK")
            findings.append(
                f"Worst walk-forward drawdown {worst_drawdown:.2%} exceeds budget {goal.max_drawdown_budget:.2%}."
            )
        elif worst_drawdown > goal.max_drawdown_budget * 0.75:
            severities.append("WATCH")
            findings.append(
                f"Worst walk-forward drawdown {worst_drawdown:.2%} is close to budget."
            )

    if sharpe < 0.8:
        severities.append("WATCH")
        findings.append(f"Sharpe {sharpe:.2f} is below the compounding watch level 0.80.")
    if reject_rate >= 0.20:
        severities.append("WATCH")
        findings.append(f"Reject rate {reject_rate:.2%} is high for stable paper execution.")
    if maintenance_turnover_count == 0 and avg_turnover >= 0.80:
        severities.append("WATCH")
        findings.append(
            f"Average turnover {avg_turnover:.2%} is high, but maintenance turnover is unobserved after initial deployment."
        )
    elif avg_maintenance_turnover >= 0.50:
        severities.append("WATCH")
        findings.append(
            f"Maintenance turnover {avg_maintenance_turnover:.2%} is high for small-capital compounding."
        )
    elif avg_turnover >= 0.80:
        severities.append("WATCH")
        findings.append(f"Average turnover {avg_turnover:.2%} is high including initial deployment.")

    status = _combine_review_status(severities)
    if status == "PASS":
        findings.append("Capital-goal fit review is PASS for research ranking; paper evidence is still required.")
    return CandidateCapitalGoalFitReview(
        status=status,
        required_annual_return=required,
        annual_return=annual_return,
        return_margin=return_margin,
        max_drawdown=max_drawdown,
        drawdown_budget=goal.max_drawdown_budget,
        worst_walk_forward_return=worst_return,
        worst_walk_forward_drawdown=worst_drawdown,
        sharpe_ratio=sharpe,
        reject_rate=reject_rate,
        avg_turnover_pct=avg_turnover,
        avg_maintenance_turnover_pct=avg_maintenance_turnover,
        maintenance_turnover_observation_count=maintenance_turnover_count,
        findings=findings,
    )


def _apply_capital_goal_fit_score(
    score: StrategyCandidateScore,
    review: CandidateCapitalGoalFitReview,
) -> StrategyCandidateScore:
    if review.status == "PASS":
        return score
    reasons = list(score.reasons)
    reasons.append(f"Capital-goal fit is {review.status}: {'; '.join(review.findings)}")
    adjusted = float(score.score) - (25.0 if review.status == "BLOCK" else 6.0)
    decision = "BLOCK" if review.status == "BLOCK" or adjusted < 50 else "WATCH"
    return StrategyCandidateScore(
        decision=decision,
        score=max(adjusted, 0.0),
        reasons=reasons,
        metrics=score.metrics,
    )


def _review_market_regime_fit(
    market_regime: dict[str, Any] | None,
    spec: CandidateSpec,
    cfg,
) -> CandidateMarketRegimeReview:
    label = str((market_regime or {}).get("label", "unknown") or "unknown")
    regime_status = str((market_regime or {}).get("status", "UNKNOWN") or "UNKNOWN")
    alignment_status, alignment_findings = _market_regime_alignment(market_regime or {}, cfg)
    required = [
        "Fresh market_regime.json from the same real-data cache and research window.",
        "Candidate regime validation across at least neutral plus adverse windows before promotion.",
        "Paper-only observation when market state is defensive, risk_off, unknown, or stale.",
    ]
    if not market_regime or regime_status == "BLOCK" or label == "unknown":
        return CandidateMarketRegimeReview(
            status="BLOCK" if alignment_status == "BLOCK" else "WATCH",
            regime_label=label,
            regime_status=regime_status,
            alignment_status=alignment_status,
            fit="insufficient_context",
            findings=[
                "Market regime evidence is missing, blocked, or unknown; keep candidate below PASS until market context is refreshed."
            ],
            alignment_findings=alignment_findings,
            required_evidence=required,
        )
    if alignment_status == "BLOCK":
        return CandidateMarketRegimeReview(
            status="BLOCK",
            regime_label=label,
            regime_status=regime_status,
            alignment_status=alignment_status,
            fit="misaligned_market_context",
            findings=[
                "Market regime evidence is stale, mismatched, or too narrow for this research window."
            ],
            alignment_findings=alignment_findings,
            required_evidence=required,
        )
    if label == "risk_off":
        return CandidateMarketRegimeReview(
            status="BLOCK",
            regime_label=label,
            regime_status=regime_status,
            alignment_status=alignment_status,
            fit="adverse_market_pause",
            findings=["Market regime is risk_off; do not promote candidate selection toward paper expansion."],
            alignment_findings=alignment_findings,
            required_evidence=[
                *required,
                "Wait for a new market regime report and adverse-window paper stability before reconsidering.",
            ],
        )
    if label == "defensive":
        defensive = _is_defensive_candidate(spec)
        return CandidateMarketRegimeReview(
            status="WATCH",
            regime_label=label,
            regime_status=regime_status,
            alignment_status=alignment_status,
            fit="defensive_fit" if defensive else "non_defensive_in_defensive_market",
            findings=[
                (
                    "Market regime is defensive; candidate is defensive-aligned but remains paper-only until drawdown stress passes."
                    if defensive
                    else "Market regime is defensive; non-defensive candidates require extra drawdown and liquidity stress."
                )
            ],
            alignment_findings=alignment_findings,
            required_evidence=required,
        )
    if alignment_status == "WATCH":
        return CandidateMarketRegimeReview(
            status="WATCH",
            regime_label=label,
            regime_status=regime_status,
            alignment_status=alignment_status,
            fit="weak_market_context",
            findings=[
                "Market regime context is usable only as WATCH evidence until alignment findings are resolved."
            ],
            alignment_findings=alignment_findings,
            required_evidence=required,
        )
    if label == "risk_on":
        return CandidateMarketRegimeReview(
            status="PASS",
            regime_label=label,
            regime_status=regime_status,
            alignment_status=alignment_status,
            fit="risk_on_context",
            findings=["Market regime is risk_on, but this does not relax data, robustness, paper, or approval gates."],
            alignment_findings=alignment_findings,
            required_evidence=required,
        )
    return CandidateMarketRegimeReview(
        status="PASS",
        regime_label=label,
        regime_status=regime_status,
        alignment_status=alignment_status,
        fit="neutral_context",
        findings=["Market regime is neutral; require normal robustness and paper evidence before promotion."],
        alignment_findings=alignment_findings,
        required_evidence=required,
    )


def _market_regime_alignment(market_regime: dict[str, Any], cfg) -> tuple[str, list[str]]:
    findings: list[str] = []
    if not market_regime:
        return "WATCH", ["market_regime.json is missing; run market regime detection before candidate selection."]
    expected_start = str(cfg.research.start)
    expected_end = str(cfg.research.end)
    regime_start = str(market_regime.get("start", "") or "")
    regime_end = str(market_regime.get("end", "") or "")
    regime_as_of = str(market_regime.get("as_of", "") or "")
    if regime_start and regime_start != expected_start:
        findings.append(f"Market regime start {regime_start} does not match research start {expected_start}.")
    elif not regime_start:
        findings.append("Market regime start is missing.")
    if regime_end and regime_end != expected_end:
        findings.append(f"Market regime end {regime_end} does not match research end {expected_end}.")
    elif not regime_end:
        findings.append("Market regime end is missing.")
    if regime_as_of and regime_as_of != expected_end:
        findings.append(f"Market regime as_of {regime_as_of} does not match research end {expected_end}.")
    elif not regime_as_of:
        findings.append("Market regime as_of is missing.")
    usable_symbols = _int_value(market_regime.get("usable_symbol_count"))
    trading_days = _int_value(market_regime.get("trading_day_count"))
    if usable_symbols and usable_symbols < 5:
        findings.append(f"Market regime has only {usable_symbols} usable symbols; breadth is fragile.")
    elif usable_symbols == 0:
        findings.append("Market regime usable_symbol_count is missing or zero.")
    if trading_days and trading_days < 60:
        findings.append(f"Market regime has only {trading_days} trading days; at least 60 are preferred.")
    elif trading_days == 0:
        findings.append("Market regime trading_day_count is missing or zero.")
    if any("does not match" in finding for finding in findings):
        return "BLOCK", findings
    if findings:
        return "WATCH", findings
    return "PASS", ["Market regime window, as_of date, breadth, and history align with the research run."]


def _int_value(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float_value(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _combine_review_status(statuses: list[str]) -> str:
    if any(status == "BLOCK" for status in statuses):
        return "BLOCK"
    if any(status == "WATCH" for status in statuses):
        return "WATCH"
    return "PASS"


def _is_defensive_candidate(spec: CandidateSpec) -> bool:
    factor_names = {factor.name for factor in spec.factors}
    text = f"{spec.name} {spec.description}".lower()
    return bool(
        spec.trend_filter
        or "defensive" in text
        or "regime_pause" in text
        or "low_vol" in text
        or "low_volatility_120d" in factor_names
        or "very_low_volatility" in factor_names
    )


def _normalized_market_regime_label(market_regime: dict[str, Any] | None) -> str:
    label = str((market_regime or {}).get("label", "unknown") or "unknown").strip().lower()
    if not label:
        return "unknown"
    compact = label.replace("-", "_").replace(" ", "_")
    if compact in {"risk_off", "riskoff"}:
        return "risk_off"
    if compact in {"risk_on", "riskon"}:
        return "risk_on"
    if "defensive" in compact or "adverse" in compact:
        return "defensive"
    if "neutral" in compact or "sideways" in compact or "choppy" in compact:
        return "neutral"
    return compact


def _review_data_dependency(
    data: DataProvider,
    cfg,
    spec: CandidateSpec,
    universe_filter: UniverseFilter,
) -> CandidateDataDependencyReview:
    required_fields = _required_fundamental_fields(spec)
    if spec.data_dependency == "ohlcv_only" or not required_fields:
        return CandidateDataDependencyReview(
            status="PASS",
            data_dependency=spec.data_dependency,
            required_fundamental_fields=required_fields,
            field_coverage={},
            findings=["Candidate is OHLCV-only; no valuation or quality fields are required."],
        )

    universe = universe_filter.symbols(cfg.research.end, data) or data.all_symbols()
    fundamentals = data.fundamentals(universe, cfg.research.end)
    if not universe:
        return CandidateDataDependencyReview(
            status="BLOCK",
            data_dependency=spec.data_dependency,
            required_fundamental_fields=required_fields,
            field_coverage={field: 0.0 for field in required_fields},
            findings=["No universe symbols are available to verify point-in-time fundamental coverage."],
        )
    if fundamentals.empty:
        return CandidateDataDependencyReview(
            status="BLOCK",
            data_dependency=spec.data_dependency,
            required_fundamental_fields=required_fields,
            field_coverage={field: 0.0 for field in required_fields},
            findings=[
                "Candidate requires point-in-time fundamentals, but no fundamentals are available at the research end date."
            ],
        )

    missing_columns = [field for field in required_fields if field not in fundamentals.columns]
    coverage = {
        field: (
            float(pd.to_numeric(fundamentals[field], errors="coerce").notna().sum()) / len(universe)
            if field in fundamentals.columns
            else 0.0
        )
        for field in required_fields
    }
    findings: list[str] = []
    if missing_columns:
        findings.append(f"Missing required fundamental columns: {', '.join(missing_columns)}.")
    for field, ratio in coverage.items():
        findings.append(f"{field} coverage at research end date is {ratio:.0%}.")

    if missing_columns or any(ratio < 0.50 for ratio in coverage.values()):
        status = "BLOCK"
    elif any(ratio < 0.80 for ratio in coverage.values()):
        status = "WATCH"
    else:
        status = "PASS"
    return CandidateDataDependencyReview(
        status=status,
        data_dependency=spec.data_dependency,
        required_fundamental_fields=required_fields,
        field_coverage=coverage,
        findings=findings or ["Required point-in-time fundamental fields have sufficient coverage."],
    )


def _required_fundamental_fields(spec: CandidateSpec) -> list[str]:
    factor_requirements = {
        "value_ep": "pe_ttm",
        "quality_roe": "roe",
    }
    return sorted(
        {
            field
            for factor in spec.factors
            if (field := factor_requirements.get(factor.name)) is not None
        }
    )


def _apply_data_dependency_score(
    score: StrategyCandidateScore,
    review: CandidateDataDependencyReview,
) -> StrategyCandidateScore:
    if review.status == "PASS":
        return score
    reasons = list(score.reasons)
    reasons.append(f"Data dependency gate is {review.status}: {'; '.join(review.findings)}")
    adjusted = float(score.score) - (50.0 if review.status == "BLOCK" else 15.0)
    decision = "BLOCK" if review.status == "BLOCK" or adjusted < 50 else "WATCH"
    return StrategyCandidateScore(
        decision=decision,
        score=max(adjusted, 0.0),
        reasons=reasons,
        metrics=score.metrics,
    )


def _flat_result(result: CandidateRunResult) -> dict[str, object]:
    return {
        "name": result.spec.name,
        "decision": result.score.decision,
        "score": result.score.score,
        "annualized_return": result.metrics.get("annualized_return", 0.0),
        "max_drawdown": result.metrics.get("max_drawdown", 0.0),
        "sharpe_ratio": result.metrics.get("sharpe_ratio", 0.0),
        "reject_rate": result.reject_rate,
        "execution_initial_cash": result.execution_initial_cash,
        "final_cash_ratio": result.final_cash_ratio,
        "min_commission_hit_count": result.min_commission_hit_count,
        "below_lot_reject_count": result.below_lot_reject_count,
        "avg_turnover_pct": result.avg_turnover_pct,
        "initial_turnover_pct": result.initial_turnover_pct,
        "avg_maintenance_turnover_pct": result.avg_maintenance_turnover_pct,
        "max_maintenance_turnover_pct": result.max_maintenance_turnover_pct,
        "maintenance_turnover_observation_count": result.maintenance_turnover_observation_count,
        "trend_filter_active_days": result.trend_filter_active_days,
        "hold_rank_buffer": result.spec.hold_rank_buffer,
        "min_trade_weight": result.spec.min_trade_weight,
        "max_new_positions": result.spec.max_new_positions,
        "score_smoothing_observations": result.spec.score_smoothing_observations,
        "score_smoothing_step_days": result.spec.score_smoothing_step_days,
        "data_dependency": result.spec.data_dependency,
        "data_dependency_status": result.data_dependency_review.status,
        "market_regime_status": result.market_regime_review.status,
        "market_regime_fit": result.market_regime_review.fit,
        "candidate_walk_forward_status": result.candidate_walk_forward_review.status,
        "candidate_regime_validation_status": (
            result.candidate_regime_validation_review.status
        ),
        "candidate_regime_known_count": (
            result.candidate_regime_validation_review.known_regime_count
        ),
        "candidate_regime_adverse_window_count": (
            result.candidate_regime_validation_review.adverse_regime_window_count
        ),
        "candidate_regime_block_bucket_count": (
            result.candidate_regime_validation_review.block_bucket_count
        ),
        "capital_goal_fit_status": result.capital_goal_fit_review.status,
        "capital_goal_required_annual_return": result.capital_goal_fit_review.required_annual_return,
        "capital_goal_return_margin": result.capital_goal_fit_review.return_margin,
        "capital_goal_avg_maintenance_turnover_pct": (
            result.capital_goal_fit_review.avg_maintenance_turnover_pct
        ),
        "capital_goal_worst_walk_forward_return": (
            result.capital_goal_fit_review.worst_walk_forward_return
        ),
        "capital_goal_worst_walk_forward_drawdown": (
            result.capital_goal_fit_review.worst_walk_forward_drawdown
        ),
        "candidate_walk_forward_positive_return_ratio": (
            result.candidate_walk_forward_review.positive_return_ratio
        ),
        "candidate_walk_forward_worst_total_return": (
            result.candidate_walk_forward_review.worst_total_return
        ),
        "candidate_walk_forward_worst_max_drawdown": (
            result.candidate_walk_forward_review.worst_max_drawdown
        ),
    }
