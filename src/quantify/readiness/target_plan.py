"""Manual target portfolio preparation for paper and micro-live readiness."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from quantify.core.portfolio import Portfolio
from quantify.data.provider import DataProvider
from quantify.research.candidates import (
    CandidateSpec,
    TrendFilteredTargetStrategy,
    candidate_spec_by_name,
)
from quantify.research.factors import FactorPipeline
from quantify.research.strategy import MultiFactorStrategyConfig, MultiFactorTargetStrategy
from quantify.research.universe import UniverseConfig, UniverseFilter


@dataclass(frozen=True, slots=True)
class ManualTargetRow:
    symbol: str
    industry: str
    target_weight: float
    score: float
    latest_price: float
    avg_amount_20d: float
    estimated_participation_rate: float
    target_value: float
    target_quantity: int
    estimated_cost: float
    current_quantity: int
    quantity_delta: int
    instruction: str
    reason: str
    risk_flags: str

    def to_dict(self) -> dict[str, str | float | int]:
        return {
            "symbol": self.symbol,
            "industry": self.industry,
            "target_weight": self.target_weight,
            "score": self.score,
            "latest_price": self.latest_price,
            "avg_amount_20d": self.avg_amount_20d,
            "estimated_participation_rate": self.estimated_participation_rate,
            "target_value": self.target_value,
            "target_quantity": self.target_quantity,
            "estimated_cost": self.estimated_cost,
            "current_quantity": self.current_quantity,
            "quantity_delta": self.quantity_delta,
            "instruction": self.instruction,
            "reason": self.reason,
            "risk_flags": self.risk_flags,
        }


@dataclass(frozen=True, slots=True)
class ManualTargetPlan:
    as_of: str
    candidate: str
    capital: float
    cash_buffer_pct: float
    lot_size: int
    target_count: int
    total_target_weight: float
    estimated_gross_exposure: float
    estimated_cash_buffer: float
    rows: list[ManualTargetRow]
    warnings: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "candidate": self.candidate,
            "capital": self.capital,
            "cash_buffer_pct": self.cash_buffer_pct,
            "lot_size": self.lot_size,
            "target_count": self.target_count,
            "total_target_weight": self.total_target_weight,
            "estimated_gross_exposure": self.estimated_gross_exposure,
            "estimated_cash_buffer": self.estimated_cash_buffer,
            "rows": [row.to_dict() for row in self.rows],
            "warnings": self.warnings,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            "# Manual Target Portfolio Plan",
            "",
            f"- As of: `{self.as_of}`",
            f"- Candidate: `{self.candidate}`",
            f"- Capital: {self.capital:.2f}",
            f"- Cash buffer: {self.cash_buffer_pct:.2%}",
            f"- Lot size: {self.lot_size}",
            f"- Targets: {self.target_count}",
            f"- Target weight sum: {self.total_target_weight:.2%}",
            f"- Estimated gross exposure: {self.estimated_gross_exposure:.2f}",
            f"- Estimated cash buffer: {self.estimated_cash_buffer:.2f}",
            "",
            "## Manual Reference Rows",
            "",
            "| symbol | industry | weight | price | target_qty | delta | participation | flags |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
        for row in self.rows:
            lines.append(
                "| {symbol} | {industry} | {weight:.2%} | {price:.2f} | {qty} | {delta} | {part:.2%} | `{flags}` |".format(
                    symbol=row.symbol,
                    industry=row.industry or "-",
                    weight=row.target_weight,
                    price=row.latest_price,
                    qty=row.target_quantity,
                    delta=row.quantity_delta,
                    part=row.estimated_participation_rate,
                    flags=row.risk_flags or "none",
                )
            )
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in self.warnings) if self.warnings else lines.append("- None.")
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {action}" for action in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_manual_target_plan(
    data: DataProvider,
    cfg,
    *,
    as_of: str | None = None,
    candidate: str | None = None,
    capital: float | None = None,
    cash_buffer_pct: float = 0.05,
    current_positions: pd.DataFrame | None = None,
) -> ManualTargetPlan:
    """Build target-position reference rows without creating executable orders."""
    plan_date = as_of or _latest_trading_day(data, cfg.research.start, cfg.research.end)
    selected = _select_candidate(cfg, candidate)
    capital_value = float(capital if capital is not None else cfg.research.initial_cash)
    _validate_manual_target_inputs(capital_value, cash_buffer_pct)
    lot_size = int(cfg.broker.lot_size)
    target_capital = capital_value * (1 - cash_buffer_pct)
    targets = _strategy_for_candidate(cfg, selected).on_rebalance(
        plan_date,
        data,
        Portfolio(initial_cash=capital_value),
    )
    target_by_symbol = {target.symbol: target for target in targets}
    current = _current_quantities(current_positions)
    row_symbols = _row_symbols(list(target_by_symbol), current)
    prices = data.latest_prices(row_symbols, plan_date)
    liquidity = _avg_amount_20d(data, row_symbols, plan_date)
    industries = _industries(data)
    tradability = _tradability_context(data, row_symbols, plan_date, cfg)
    rows = [
        _row(
            symbol,
            industries.get(symbol, ""),
            tradability.get(symbol, {}),
            target_by_symbol[symbol].target_weight if symbol in target_by_symbol else 0.0,
            target_by_symbol[symbol].score if symbol in target_by_symbol else 0.0,
            float(prices.get(symbol, 0.0) or 0.0),
            float(liquidity.get(symbol, 0.0) or 0.0),
            target_capital,
            lot_size,
            current.get(symbol, 0),
        )
        for symbol in row_symbols
    ]
    rows = [row for row in rows if row.target_quantity > 0 or row.current_quantity > 0]
    estimated_exposure = sum(row.estimated_cost for row in rows)
    warnings = _warnings(
        plan_date,
        selected,
        rows,
        capital_value,
        estimated_exposure,
        cash_buffer_pct,
    )
    return ManualTargetPlan(
        as_of=plan_date,
        candidate=selected.name,
        capital=capital_value,
        cash_buffer_pct=cash_buffer_pct,
        lot_size=lot_size,
        target_count=len(rows),
        total_target_weight=sum(row.target_weight for row in rows),
        estimated_gross_exposure=estimated_exposure,
        estimated_cash_buffer=max(capital_value - estimated_exposure, 0.0),
        rows=rows,
        warnings=warnings,
        prohibited_actions=[
            "Do not upload this CSV to a broker as an order basket.",
            "Do not trade without fresh data audit, readiness review, and human approval.",
            "Do not let LLM advisory text change quantities, symbols, or risk limits.",
            "Do not treat this plan as a guarantee of profit.",
        ],
    )


def _validate_manual_target_inputs(capital: float, cash_buffer_pct: float) -> None:
    if not math.isfinite(capital) or capital <= 0:
        raise ValueError("micro-live target capital must be a positive finite number")
    if not math.isfinite(cash_buffer_pct) or cash_buffer_pct < 0 or cash_buffer_pct >= 1:
        raise ValueError("micro-live cash buffer pct must be in the range [0, 1)")


def write_manual_target_plan(
    plan: ManualTargetPlan,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "target_portfolio.json").write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "target_portfolio.md").write_text(plan.to_markdown(), encoding="utf-8")
    rows = pd.DataFrame([row.to_dict() for row in plan.rows])
    if rows.empty:
        rows = pd.DataFrame(columns=list(ManualTargetRow.__annotations__))
    rows.to_csv(root / "target_portfolio.csv", index=False)
    manual = rows.copy()
    if manual.empty:
        manual = pd.DataFrame(
            columns=[
                "symbol",
                "target_quantity",
                "quantity_delta",
                "latest_price",
                "estimated_cost",
                "instruction",
            ]
        )
    manual["instruction"] = "MANUAL_REFERENCE_ONLY_NO_BROKER_ORDER"
    manual.to_csv(root / "manual_trade_sheet.csv", index=False)
    return root


def _strategy_for_candidate(
    cfg,
    spec: CandidateSpec,
) -> MultiFactorTargetStrategy:
    pipeline = FactorPipeline(factors=spec.factors)
    universe_filter = UniverseFilter(
        UniverseConfig(
            mode=cfg.universe.mode,
            index_code=cfg.universe.index_code,
            include_st=cfg.universe.include_st,
            min_history_days=cfg.universe.min_history_days,
        )
    )
    strategy_config = MultiFactorStrategyConfig(
        n_holdings=spec.n_holdings,
        max_weight=spec.max_weight,
        hold_rank_buffer=spec.hold_rank_buffer,
        min_trade_weight=spec.min_trade_weight,
        max_new_positions=spec.max_new_positions,
        score_smoothing_observations=spec.score_smoothing_observations,
        score_smoothing_step_days=spec.score_smoothing_step_days,
    )
    if spec.trend_filter:
        return TrendFilteredTargetStrategy(
            universe_filter,
            pipeline,
            strategy_config,
            trend_scale=spec.trend_scale,
            trend_gate=spec.trend_gate,
        )
    return MultiFactorTargetStrategy(universe_filter, pipeline, strategy_config)


def _row(
    symbol: str,
    industry: str,
    tradability: dict[str, bool],
    target_weight: float,
    score: float,
    price: float,
    avg_amount_20d: float,
    deployable_capital: float,
    lot_size: int,
    current_quantity: int,
) -> ManualTargetRow:
    target_value = deployable_capital * target_weight
    raw_qty = int(target_value // price) if price > 0 else 0
    target_qty = (raw_qty // lot_size) * lot_size if lot_size > 0 else raw_qty
    delta = target_qty - current_quantity
    instruction = "HOLD"
    if delta > 0:
        instruction = "MANUAL_BUY_REVIEW"
    elif delta < 0:
        instruction = "MANUAL_SELL_REVIEW"
    reason = "target_quantity_rounded_to_lot_size"
    if price <= 0:
        reason = "missing_latest_price"
    elif target_qty <= 0:
        reason = "target_value_below_one_lot"
    participation = (target_qty * price) / avg_amount_20d if avg_amount_20d > 0 else 0.0
    flags = _risk_flags(price, avg_amount_20d, participation, target_weight, tradability)
    return ManualTargetRow(
        symbol=symbol,
        industry=industry,
        target_weight=target_weight,
        score=score,
        latest_price=price,
        avg_amount_20d=avg_amount_20d,
        estimated_participation_rate=participation,
        target_value=target_value,
        target_quantity=target_qty,
        estimated_cost=target_qty * price,
        current_quantity=current_quantity,
        quantity_delta=delta,
        instruction=instruction,
        reason=reason,
        risk_flags=";".join(flags),
    )


def _select_candidate(cfg, name: str | None) -> CandidateSpec:
    return candidate_spec_by_name(cfg, name)


def _latest_trading_day(data: DataProvider, start: str, end: str) -> str:
    days = data.trading_days(start, end)
    if not days:
        raise ValueError("No trading days are available for target portfolio planning.")
    return days[-1]


def _current_quantities(frame: pd.DataFrame | None) -> dict[str, int]:
    if frame is None or frame.empty or "symbol" not in frame or "quantity" not in frame:
        return {}
    clean = frame.copy()
    if "date" in clean:
        latest = str(clean["date"].iloc[-1])[:10]
        clean = clean[clean["date"].astype(str).str[:10] == latest]
    quantities = pd.to_numeric(clean["quantity"], errors="coerce").fillna(0).astype(int)
    return dict(zip(clean["symbol"].astype(str), quantities, strict=False))


def _row_symbols(target_symbols: list[str], current: dict[str, int]) -> list[str]:
    return list(dict.fromkeys([*target_symbols, *current]))


def _warnings(
    as_of: str,
    spec: CandidateSpec,
    rows: list[ManualTargetRow],
    capital: float,
    exposure: float,
    cash_buffer_pct: float,
) -> list[str]:
    warnings = [
        "Manual target plan is not a broker order file and cannot approve live trading.",
        "Recompute this plan after every data update, approval change, or strategy parameter change.",
    ]
    if not rows:
        warnings.append("No target rows were generated; data or factor evidence may be missing.")
    missing_prices = [row.symbol for row in rows if row.latest_price <= 0]
    if missing_prices:
        warnings.append(f"Missing latest prices for {len(missing_prices)} symbols as of {as_of}.")
    if exposure > capital:
        warnings.append("Estimated exposure exceeds capital before fees; increase cash buffer or reduce weights.")
    if cash_buffer_pct < 0.03:
        warnings.append("Cash buffer is below 3%; manual execution may fail after fees, slippage, or lot rounding.")
    low_liquidity = [row.symbol for row in rows if "LOW_LIQUIDITY" in row.risk_flags]
    high_participation = [row.symbol for row in rows if "HIGH_PARTICIPATION" in row.risk_flags]
    blocked_tradability = [
        row.symbol
        for row in rows
        if any(flag in row.risk_flags for flag in ["ST", "DELISTED", "SUSPENDED", "LIMIT_UP", "LIMIT_DOWN"])
    ]
    if low_liquidity:
        warnings.append(f"{len(low_liquidity)} target rows have low or missing 20-day average amount.")
    if high_participation:
        warnings.append(f"{len(high_participation)} target rows exceed the participation-rate watch threshold.")
    if blocked_tradability:
        warnings.append(
            f"{len(blocked_tradability)} target rows have ST/delisting/suspension/limit-price execution flags."
        )
    industry_weights = _industry_weights(rows)
    if industry_weights:
        top_industry, top_weight = max(industry_weights.items(), key=lambda item: item[1])
        if top_industry and top_weight > 0.35:
            warnings.append(f"Top industry `{top_industry}` has {top_weight:.2%} target weight; check concentration.")
    if spec.trend_filter:
        warnings.append("Trend-filtered candidate can reduce exposure when broad trend is weak.")
    if spec.name == "regime_pause_price_volume":
        warnings.append(
            "Regime-pause candidate requires explicit pause/resume review notes; do not treat lower exposure as a generic trend tweak."
        )
    return warnings


def _avg_amount_20d(data: DataProvider, symbols: list[str], as_of: str) -> dict[str, float]:
    if not symbols:
        return {}
    start = (pd.Timestamp(as_of) - pd.Timedelta(days=35)).date().isoformat()
    bars = data.bars(symbols, start, as_of)
    if bars.empty or "amount" not in bars:
        return {}
    amount = pd.to_numeric(bars["amount"], errors="coerce").fillna(0.0)
    frame = bars.assign(amount=amount).sort_values(["symbol", "date"])
    avg = frame.groupby("symbol")["amount"].tail(20).groupby(frame["symbol"]).mean()
    return {str(symbol): float(value) for symbol, value in avg.items()}


def _industries(data: DataProvider) -> dict[str, str]:
    info = data.stock_info()
    if info.empty or "symbol" not in info:
        return {}
    if "industry" not in info:
        info = info.assign(industry="")
    return dict(zip(info["symbol"].astype(str), info["industry"].astype(str), strict=False))


def _tradability_context(
    data: DataProvider,
    symbols: list[str],
    as_of: str,
    cfg,
) -> dict[str, dict[str, bool]]:
    info = data.stock_info()
    info_by_symbol = info.set_index("symbol") if not info.empty and "symbol" in info else pd.DataFrame()
    suspended = data.suspended_symbols(as_of)
    today_prices = data.latest_prices(symbols, as_of)
    prev_prices = _previous_prices(data, symbols, as_of)
    limit_pct = float(_cfg_get(cfg.broker, "price_limit_pct", 0.10) or 0.10)
    context: dict[str, dict[str, bool]] = {}
    for symbol in symbols:
        row = info_by_symbol.loc[symbol] if not info_by_symbol.empty and symbol in info_by_symbol.index else {}
        name = str(row.get("name", "") if hasattr(row, "get") else "").upper()
        delist = str(row.get("delist_date", "") if hasattr(row, "get") else "").strip()
        is_st = bool(int(row.get("is_st", 0) or 0)) if hasattr(row, "get") else False
        today = float(today_prices.get(symbol, 0.0) or 0.0)
        prev = float(prev_prices.get(symbol, 0.0) or 0.0)
        pct_change = today / prev - 1 if prev > 0 and today > 0 else 0.0
        context[symbol] = {
            "is_st": is_st or "ST" in name,
            "is_delisted": bool(delist),
            "is_suspended": symbol in suspended,
            "is_limit_up": pct_change >= limit_pct * 0.99,
            "is_limit_down": pct_change <= -limit_pct * 0.99,
        }
    return context


def _previous_prices(data: DataProvider, symbols: list[str], as_of: str) -> dict[str, float]:
    days = data.trading_days((pd.Timestamp(as_of) - pd.Timedelta(days=10)).date().isoformat(), as_of)
    prior_days = [day for day in days if day < as_of]
    if not prior_days:
        return {}
    return data.latest_prices(symbols, prior_days[-1])


def _cfg_get(section, key: str, default):
    try:
        return getattr(section, key)
    except AttributeError:
        return default


def _risk_flags(
    price: float,
    avg_amount_20d: float,
    participation: float,
    target_weight: float,
    tradability: dict[str, bool],
) -> list[str]:
    flags = []
    if price <= 0:
        flags.append("MISSING_PRICE")
    if avg_amount_20d < 10_000_000:
        flags.append("LOW_LIQUIDITY")
    if participation > 0.05:
        flags.append("HIGH_PARTICIPATION")
    if target_weight > 0.08:
        flags.append("HIGH_WEIGHT")
    if tradability.get("is_st"):
        flags.append("ST")
    if tradability.get("is_delisted"):
        flags.append("DELISTED")
    if tradability.get("is_suspended"):
        flags.append("SUSPENDED")
    if tradability.get("is_limit_up"):
        flags.append("LIMIT_UP")
    if tradability.get("is_limit_down"):
        flags.append("LIMIT_DOWN")
    return flags


def _industry_weights(rows: list[ManualTargetRow]) -> dict[str, float]:
    weights: dict[str, float] = {}
    for row in rows:
        key = row.industry or "UNKNOWN"
        weights[key] = weights.get(key, 0.0) + row.target_weight
    return weights
