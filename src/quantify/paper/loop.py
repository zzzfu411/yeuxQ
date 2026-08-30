"""Recoverable daily paper-trading loop for A-share research candidates."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from math import isclose
from pathlib import Path
from typing import Any

import pandas as pd

from quantify.core.event import Direction
from quantify.core.portfolio import Portfolio, Position
from quantify.data.provider import DataProvider
from quantify.engine.paper_broker import PaperBroker, PaperBrokerConfig, PaperOrder
from quantify.research.candidates import (
    CandidateSpec,
    TrendFilteredTargetStrategy,
    candidate_spec_by_name,
)
from quantify.research.engine import _rebalance_days
from quantify.research.factors import FactorPipeline
from quantify.research.strategy import MultiFactorStrategyConfig, MultiFactorTargetStrategy
from quantify.research.universe import UniverseConfig, UniverseFilter


@dataclass(frozen=True, slots=True)
class PaperLoopState:
    as_of: str
    observed_days: int
    candidate: str
    initial_cash: float
    cash: float
    last_equity: float
    position_count: int
    order_count: int
    rejected_order_count: int
    broker_connection: str = "none"
    run_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "observed_days": self.observed_days,
            "candidate": self.candidate,
            "initial_cash": self.initial_cash,
            "cash": self.cash,
            "last_equity": self.last_equity,
            "position_count": self.position_count,
            "order_count": self.order_count,
            "rejected_order_count": self.rejected_order_count,
            "broker_connection": self.broker_connection,
            "run_context": self.run_context,
        }

    def to_markdown(self) -> str:
        return (
            "# Paper Loop Daily Review\n\n"
            f"- As of: `{self.as_of}`\n"
            f"- Candidate: `{self.candidate}`\n"
            f"- Observed days: {self.observed_days}\n"
            f"- Initial cash: {self.initial_cash:.2f}\n"
            f"- Cash: {self.cash:.2f}\n"
            f"- Last equity: {self.last_equity:.2f}\n"
            f"- Position count: {self.position_count}\n"
            f"- Orders: {self.order_count}\n"
            f"- Rejected orders: {self.rejected_order_count}\n"
            f"- Broker connection: `{self.broker_connection}`\n\n"
            "This is a recoverable paper loop. It does not connect to a real broker.\n"
        )


@dataclass(frozen=True, slots=True)
class PaperLoopResult:
    state: PaperLoopState
    run_days: list[str]
    rebalance_days: list[str]
    orders: list[PaperOrder] = field(default_factory=list)
    positions: list[dict[str, Any]] = field(default_factory=list)
    daily: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.to_dict(),
            "run_days": self.run_days,
            "rebalance_days": self.rebalance_days,
            "orders": [_order_dict(order) for order in self.orders],
            "positions": self.positions,
            "daily": self.daily,
        }


def run_paper_loop(
    data: DataProvider,
    cfg,
    *,
    state_dir: str | Path,
    start: str | None = None,
    end: str | None = None,
    candidate: str | None = None,
    initial_cash: float | None = None,
    expected_cache_sha256: str | None = None,
    expected_dataset_fingerprint: str | None = None,
) -> PaperLoopResult:
    """Advance a local paper account over cached daily bars.

    The loop writes only local simulation state. It never opens broker
    connections and never creates unattended live orders.
    """
    root = Path(state_dir)
    root.mkdir(parents=True, exist_ok=True)
    spec = _select_candidate(cfg, candidate)
    requested_start = start or cfg.research.start
    requested_end = end or cfg.research.end
    days = data.trading_days(requested_start, requested_end)
    if not days:
        raise ValueError("No trading days are available for paper loop.")
    prior_state = _read_json(root / "paper_state.json")
    broker_config = _broker_config(cfg)
    run_context = _paper_run_context(data, cfg, spec, broker_config)
    _validate_expected_data_identity(
        run_context,
        expected_cache_sha256=expected_cache_sha256,
        expected_dataset_fingerprint=expected_dataset_fingerprint,
    )
    resolved_initial_cash = _resolve_initial_cash(cfg, prior_state, initial_cash)
    _validate_prior_paper_context(root, prior_state, spec.name, run_context)
    run_days = _pending_days(days, str(prior_state.get("as_of", "")))
    portfolio = _restore_portfolio(
        root,
        resolved_initial_cash,
        as_of=str(prior_state.get("as_of", "")),
    )
    broker = PaperBroker(broker_config)
    strategy = _strategy_for_candidate(cfg, spec)
    schedule_start = min(str(cfg.research.start), str(requested_start))
    schedule_days = data.trading_days(schedule_start, requested_end)
    rebalance_set = set(_rebalance_days(schedule_days, spec.rebalance))
    previous_day = {
        day: schedule_days[index - 1]
        for index, day in enumerate(schedule_days)
        if index > 0
    }
    all_symbols = data.all_symbols()
    prior_as_of = str(prior_state.get("as_of", "") or "")
    last_prices = data.latest_prices(all_symbols, prior_as_of) if prior_as_of else {}
    prev_prices: dict[str, float] = {}
    new_orders: list[PaperOrder] = []
    daily_rows: list[dict[str, Any]] = []
    position_rows: list[dict[str, Any]] = []

    for index, day in enumerate(run_days):
        signal_date = previous_day.get(day, "")
        if not prior_state and index == 0:
            signal_date = ""
        rebalanced = bool(signal_date and signal_date in rebalance_set)
        day_orders: list[PaperOrder] = []
        targets = []
        turnover = 0.0
        if rebalanced:
            targets = strategy.on_rebalance(signal_date, data, portfolio)
        portfolio.on_new_day(datetime.fromisoformat(day).date())
        if rebalanced:
            prev_prices = data.latest_prices(all_symbols, signal_date)
            execution_prices = data.open_prices(all_symbols, day)
            execution_targets = [
                replace(target, timestamp=datetime.fromisoformat(day)) for target in targets
            ]
            result = broker.rebalance(
                execution_targets,
                execution_prices,
                portfolio,
                suspended=data.suspended_symbols(day),
                prev_closes=prev_prices,
            )
            day_orders = result.orders
            turnover = result.turnover
            new_orders.extend(result.orders)
        prices = data.latest_prices(all_symbols, day)
        if prices:
            last_prices = prices
        equity = portfolio.total_equity(last_prices)
        target_metrics = _target_deviation_metrics(targets, portfolio, last_prices, equity)
        daily_rows.append(
            {
                "date": day,
                "signal_date": signal_date if rebalanced else "",
                "execution_date": day if rebalanced else "",
                "candidate": spec.name,
                "cash": portfolio.cash,
                "equity": equity,
                "position_count": _position_count(portfolio),
                "rebalanced": rebalanced,
                "order_count": len(day_orders),
                "filled_order_count": _filled_count(day_orders),
                "rejected_order_count": _rejected_count(day_orders),
                "rejected_reasons": json.dumps(_rejected_reason_counts(day_orders), ensure_ascii=False),
                "turnover": turnover,
                "turnover_rate": turnover / equity if equity else 0.0,
                **target_metrics,
                "broker_connection": "none",
            }
        )
        position_rows.extend(_snapshot_positions(day, portfolio, last_prices))

    all_orders = _read_orders(root / "paper_orders.csv") + new_orders
    all_daily = _merge_records(_read_csv_records(root / "paper_daily.csv"), daily_rows, key="date")
    latest_prices = last_prices or data.latest_prices(all_symbols, days[-1])
    state = PaperLoopState(
        as_of=run_days[-1] if run_days else str(prior_state.get("as_of", "")),
        observed_days=len(all_daily),
        candidate=spec.name,
        initial_cash=portfolio.initial_cash,
        cash=portfolio.cash,
        last_equity=portfolio.total_equity(latest_prices),
        position_count=_position_count(portfolio),
        order_count=len(all_orders),
        rejected_order_count=_rejected_count(all_orders),
        run_context=run_context,
    )
    positions = position_rows or _snapshot_positions(state.as_of, portfolio, latest_prices)
    result = PaperLoopResult(
        state=state,
        run_days=run_days,
        rebalance_days=[day for day in run_days if previous_day.get(day) in rebalance_set],
        orders=new_orders,
        positions=positions,
        daily=daily_rows,
    )
    _write_outputs(root, result, all_orders, all_daily, portfolio, latest_prices)
    return result


def _write_outputs(
    root: Path,
    result: PaperLoopResult,
    all_orders: list[PaperOrder],
    all_daily: list[dict[str, Any]],
    portfolio: Portfolio,
    latest_prices: dict[str, float],
) -> None:
    (root / "paper_state.json").write_text(
        json.dumps(result.state.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    pd.DataFrame([_order_dict(order) for order in all_orders]).to_csv(root / "paper_orders.csv", index=False)
    pd.DataFrame(_snapshot_positions(result.state.as_of, portfolio, latest_prices)).to_csv(
        root / "paper_positions.csv",
        index=False,
    )
    pd.DataFrame(all_daily).to_csv(root / "paper_daily.csv", index=False)
    review = _paper_daily_review_payload(
        result.state,
        all_orders,
        all_daily,
        _snapshot_positions(result.state.as_of, portfolio, latest_prices),
    )
    (root / "paper_daily_review.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "paper_daily_review.md").write_text(_paper_daily_review_markdown(review), encoding="utf-8")
    (root / "paper_loop_run.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _restore_portfolio(root: Path, initial_cash: float, *, as_of: str = "") -> Portfolio:
    state = _read_json(root / "paper_state.json")
    portfolio = Portfolio(initial_cash=initial_cash)
    if state:
        portfolio.cash = float(state.get("cash", initial_cash) or initial_cash)
    if as_of:
        portfolio._current_day = datetime.fromisoformat(as_of).date()
    positions = _read_csv(root / "paper_positions.csv")
    if positions.empty:
        return portfolio
    for row in positions.itertuples(index=False):
        symbol = str(row.symbol)
        qty = int(getattr(row, "quantity", 0) or 0)
        if qty <= 0:
            continue
        available = int(getattr(row, "available_qty", qty) or qty)
        avg_cost = float(getattr(row, "avg_cost", getattr(row, "price", 0.0)) or 0.0)
        portfolio.positions[symbol] = Position(
            symbol=symbol,
            total_qty=qty,
            available_qty=available,
            avg_cost=avg_cost,
            bought_today=0,
        )
    return portfolio


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


def _select_candidate(cfg, name: str | None) -> CandidateSpec:
    return candidate_spec_by_name(cfg, name)


def _resolve_initial_cash(cfg, prior_state: dict[str, Any], initial_cash: float | None) -> float:
    requested = float(cfg.research.initial_cash if initial_cash is None else initial_cash)
    if "initial_cash" not in prior_state:
        return requested
    existing = float(prior_state["initial_cash"])
    if initial_cash is not None and not isclose(requested, existing, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(
            "Existing paper_state.json has initial_cash "
            f"{existing}; cannot continue with {requested}. Use a separate state_dir."
        )
    return existing


def _validate_prior_paper_context(
    root: Path,
    prior_state: dict[str, Any],
    candidate: str,
    run_context: dict[str, Any],
) -> None:
    existing_candidate = str(prior_state.get("candidate", "") or "")
    if existing_candidate and existing_candidate != candidate:
        raise ValueError(
            "Existing paper_state.json belongs to candidate "
            f"{existing_candidate!r}; use a separate state_dir for {candidate!r}."
        )
    existing_context = prior_state.get("run_context")
    if prior_state and (not isinstance(existing_context, dict) or not existing_context):
        raise ValueError(
            "Existing paper_state.json is missing run_context; refusing an unsafe legacy "
            "resume. Use a separate state_dir."
        )
    if isinstance(existing_context, dict) and existing_context:
        changed_sections = sorted(
            section
            for section, current_value in run_context.items()
            if existing_context.get(section) != current_value
        )
        if changed_sections:
            raise ValueError(
                "Existing paper_state.json run context differs for "
                f"{changed_sections!r}; use a separate state_dir."
            )
    existing_daily = _read_csv(root / "paper_daily.csv")
    if existing_daily.empty or "candidate" not in existing_daily:
        return
    candidates = {
        str(item)
        for item in existing_daily["candidate"].dropna().unique().tolist()
        if str(item)
    }
    if candidates and candidates != {candidate}:
        raise ValueError(
            "Existing paper_daily.csv contains candidate history "
            f"{sorted(candidates)!r}; use a separate state_dir for {candidate!r}."
        )


def _paper_run_context(
    data: DataProvider,
    cfg,
    spec: CandidateSpec,
    broker_config: PaperBrokerConfig,
) -> dict[str, Any]:
    cache_path = Path(data.storage.db_path).resolve()
    metadata = data.storage.load_metadata()
    return {
        "backend": {
            "type": "local_paper",
            "broker_connection": "none",
        },
        "data": {
            "provider": f"{type(data).__module__}.{type(data).__qualname__}",
            "cache_path": str(cache_path),
            "cache_sha256": _file_sha256(cache_path),
            "dataset_fingerprint": _dataset_fingerprint(metadata),
            "logical_bar_fingerprint": str(
                metadata.get("cache_logical_bar_fingerprint", "") or ""
            ),
            "import_batch_id": str(metadata.get("cache_latest_import_batch_id", "") or ""),
            "source": str(cfg.data.get("source", "") or ""),
        },
        "universe": {
            "mode": str(cfg.universe.mode),
            "index_code": str(cfg.universe.index_code),
            "include_st": bool(cfg.universe.include_st),
            "min_history_days": int(cfg.universe.min_history_days),
        },
        "strategy": {
            "candidate": spec.name,
            "factors": [
                f"{type(factor).__module__}.{type(factor).__qualname__}" for factor in spec.factors
            ],
            "n_holdings": spec.n_holdings,
            "max_weight": spec.max_weight,
            "rebalance": spec.rebalance,
            "trend_filter": spec.trend_filter,
            "trend_scale": spec.trend_scale,
            "trend_gate": spec.trend_gate,
            "hold_rank_buffer": spec.hold_rank_buffer,
            "min_trade_weight": spec.min_trade_weight,
            "max_new_positions": spec.max_new_positions,
            "score_smoothing_observations": spec.score_smoothing_observations,
            "score_smoothing_step_days": spec.score_smoothing_step_days,
        },
        "broker": asdict(broker_config),
    }


def _validate_expected_data_identity(
    run_context: dict[str, Any],
    *,
    expected_cache_sha256: str | None,
    expected_dataset_fingerprint: str | None,
) -> None:
    data_context = run_context.get("data", {})
    current_cache_sha256 = str(data_context.get("cache_sha256", "") or "")
    current_fingerprint = str(data_context.get("dataset_fingerprint", "") or "")
    if expected_cache_sha256 and current_cache_sha256 != expected_cache_sha256:
        raise ValueError(
            "Paper cache_sha256 does not match the selected research manifest; "
            "regenerate the paper plan."
        )
    if expected_dataset_fingerprint and current_fingerprint != expected_dataset_fingerprint:
        raise ValueError(
            "Paper dataset fingerprint does not match the selected research manifest; "
            "regenerate the paper plan."
        )


def _dataset_fingerprint(metadata: dict[str, str]) -> str:
    return str(
        metadata.get("csv_dataset_fingerprint")
        or metadata.get("raw_vendor_bars_sha256")
        or ""
    ).strip()


def _file_sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _broker_config(cfg) -> PaperBrokerConfig:
    return PaperBrokerConfig(
        commission_rate=cfg.broker.commission_rate,
        min_commission=cfg.broker.min_commission,
        stamp_tax=cfg.broker.stamp_tax,
        slippage_bps=cfg.broker.slippage_bps,
        price_limit_pct=cfg.broker.price_limit_pct,
        lot_size=cfg.broker.lot_size,
    )


def _snapshot_positions(day: str, portfolio: Portfolio, prices: dict[str, float]) -> list[dict[str, Any]]:
    rows = []
    equity = max(portfolio.total_equity(prices), 1.0)
    for symbol, pos in portfolio.positions.items():
        if pos.total_qty <= 0:
            continue
        price = float(prices.get(symbol, pos.avg_cost) or pos.avg_cost)
        market_value = pos.total_qty * price
        rows.append(
            {
                "date": day,
                "symbol": symbol,
                "quantity": pos.total_qty,
                "available_qty": pos.available_qty,
                "price": price,
                "market_value": market_value,
                "weight": market_value / equity,
                "avg_cost": pos.avg_cost,
            }
        )
    return rows


def _order_dict(order: PaperOrder) -> dict[str, str | int | float]:
    return {
        "timestamp": order.timestamp.date().isoformat(),
        "symbol": order.symbol,
        "direction": order.direction.value,
        "quantity": order.quantity,
        "price": order.price,
        "status": order.status,
        "reason": order.reason,
    }


def _read_orders(path: Path) -> list[PaperOrder]:
    frame = _read_csv(path)
    if frame.empty:
        return []
    orders = []
    for row in frame.itertuples(index=False):
        orders.append(
            PaperOrder(
                timestamp=datetime.fromisoformat(str(row.timestamp)[:10]),
                symbol=str(row.symbol),
                direction=Direction(str(row.direction)),
                quantity=int(getattr(row, "quantity", 0) or 0),
                price=float(getattr(row, "price", 0.0) or 0.0),
                status=str(getattr(row, "status", "")),
                reason=str(getattr(row, "reason", "") or ""),
            )
        )
    return orders


def _pending_days(days: list[str], as_of: str) -> list[str]:
    if not as_of:
        return days
    return [day for day in days if day > as_of]


def _position_count(portfolio: Portfolio) -> int:
    return sum(1 for position in portfolio.positions.values() if position.total_qty > 0)


def _rejected_count(orders: list[PaperOrder]) -> int:
    return sum(1 for order in orders if order.status == "rejected")


def _filled_count(orders: list[PaperOrder]) -> int:
    return sum(1 for order in orders if order.status == "filled")


def _rejected_reason_counts(orders: list[PaperOrder]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for order in orders:
        if order.status != "rejected":
            continue
        reason = order.reason or "unknown"
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def _target_deviation_metrics(
    targets,
    portfolio: Portfolio,
    prices: dict[str, float],
    equity: float,
) -> dict[str, str | int | float]:
    target_weights = {target.symbol: float(target.target_weight) for target in targets}
    if not target_weights:
        return {
            "target_count": 0,
            "target_weight_sum": 0.0,
            "max_abs_target_deviation": 0.0,
            "max_deviation_symbol": "",
            "max_deviation_actual_weight": 0.0,
            "max_deviation_target_weight": 0.0,
        }
    equity = max(float(equity), 1.0)
    symbols = sorted(set(target_weights) | set(portfolio.positions))
    worst_symbol = ""
    worst_actual = 0.0
    worst_target = 0.0
    worst_deviation = 0.0
    for symbol in symbols:
        position = portfolio.positions.get(symbol)
        actual = 0.0
        if position and position.total_qty > 0:
            price = float(prices.get(symbol, position.avg_cost) or position.avg_cost)
            actual = position.total_qty * price / equity
        target = target_weights.get(symbol, 0.0)
        deviation = abs(actual - target)
        if deviation > worst_deviation:
            worst_symbol = symbol
            worst_actual = actual
            worst_target = target
            worst_deviation = deviation
    return {
        "target_count": len(target_weights),
        "target_weight_sum": sum(target_weights.values()),
        "max_abs_target_deviation": worst_deviation,
        "max_deviation_symbol": worst_symbol,
        "max_deviation_actual_weight": worst_actual,
        "max_deviation_target_weight": worst_target,
    }


def _paper_daily_review_payload(
    state: PaperLoopState,
    all_orders: list[PaperOrder],
    all_daily: list[dict[str, Any]],
    positions: list[dict[str, Any]],
) -> dict[str, Any]:
    latest = all_daily[-1] if all_daily else {}
    latest_date = str(latest.get("date", state.as_of) or state.as_of)
    latest_rejections = [
        order for order in all_orders if order.status == "rejected" and order.timestamp.date().isoformat() == latest_date
    ]
    cumulative_rejections = _rejected_reason_counts(all_orders)
    latest_rejection_reasons = _rejected_reason_counts(latest_rejections)
    max_deviation = float(latest.get("max_abs_target_deviation", 0.0) or 0.0)
    reject_rate = state.rejected_order_count / state.order_count if state.order_count else 0.0
    status = _paper_daily_review_status(
        broker_connection=state.broker_connection,
        latest_rejected_count=len(latest_rejections),
        max_target_deviation=max_deviation,
        cumulative_reject_rate=reject_rate,
    )
    return {
        "status": status,
        "as_of": state.as_of,
        "candidate": state.candidate,
        "signal_date": str(latest.get("signal_date", "") or ""),
        "execution_date": str(latest.get("execution_date", "") or ""),
        "state": state.to_dict(),
        "latest_day": latest,
        "execution_quality": {
            "order_count": state.order_count,
            "rejected_order_count": state.rejected_order_count,
            "reject_rate": reject_rate,
            "latest_order_count": int(latest.get("order_count", 0) or 0),
            "latest_rejected_order_count": len(latest_rejections),
            "latest_rejected_reasons": latest_rejection_reasons,
            "cumulative_rejected_reasons": cumulative_rejections,
        },
        "target_deviation": {
            "target_count": int(latest.get("target_count", 0) or 0),
            "target_weight_sum": float(latest.get("target_weight_sum", 0.0) or 0.0),
            "max_abs_target_deviation": max_deviation,
            "max_deviation_symbol": str(latest.get("max_deviation_symbol", "") or ""),
            "actual_weight": float(latest.get("max_deviation_actual_weight", 0.0) or 0.0),
            "target_weight": float(latest.get("max_deviation_target_weight", 0.0) or 0.0),
        },
        "top_positions": sorted(
            positions,
            key=lambda row: float(row.get("weight", 0.0) or 0.0),
            reverse=True,
        )[:10],
        "manual_review_questions": _paper_daily_questions(
            latest=latest,
            latest_rejected_count=len(latest_rejections),
            max_target_deviation=max_deviation,
            cumulative_reject_rate=reject_rate,
        ),
        "prohibited_actions": [
            "Do not submit unattended live broker orders from paper artifacts.",
            "Do not treat a clean paper day as permission to increase capital.",
            "Do not let LLM advisory text change deterministic paper/readiness gates.",
        ],
    }


def _paper_daily_review_status(
    *,
    broker_connection: str,
    latest_rejected_count: int,
    max_target_deviation: float,
    cumulative_reject_rate: float,
) -> str:
    if broker_connection not in {"", "none"}:
        return "BLOCK"
    if latest_rejected_count > 0 or max_target_deviation >= 0.02 or cumulative_reject_rate >= 0.10:
        return "WATCH"
    return "PASS"


def _paper_daily_questions(
    *,
    latest: dict[str, Any],
    latest_rejected_count: int,
    max_target_deviation: float,
    cumulative_reject_rate: float,
) -> list[str]:
    questions = ["Confirm the paper loop did not connect to a real broker."]
    candidate = str(latest.get("candidate", "") or "")
    if not bool(latest.get("rebalanced", False)):
        questions.append("No rebalance was scheduled today; confirm positions and cash still reconciled.")
    if latest_rejected_count:
        questions.append("Explain each latest rejected order before the next rebalance.")
    if max_target_deviation >= 0.02:
        questions.append("Explain the largest target-vs-actual weight deviation.")
    if cumulative_reject_rate >= 0.10:
        questions.append("Reduce target weights or add cash buffers before treating execution as stable.")
    if candidate == "regime_pause_price_volume":
        questions.append("Confirm any regime pause or resume was explicit, reviewed, and not just broad-trend drift.")
    return questions


def _paper_daily_review_markdown(payload: dict[str, Any]) -> str:
    state = payload["state"]
    latest = payload.get("latest_day", {})
    execution = payload.get("execution_quality", {})
    deviation = payload.get("target_deviation", {})
    lines = [
        f"# Paper Loop Daily Review: {payload['status']}",
        "",
        f"- As of: `{payload['as_of']}`",
        f"- Candidate: `{payload['candidate']}`",
        f"- Observed days: {state['observed_days']}",
        f"- Cash: {float(state['cash']):.2f}",
        f"- Last equity: {float(state['last_equity']):.2f}",
        f"- Position count: {state['position_count']}",
        f"- Broker connection: `{state['broker_connection']}`",
        "",
        "## Latest Day",
        f"- Signal date: `{payload.get('signal_date', '') or 'none'}`",
        f"- Execution date: `{payload.get('execution_date', '') or 'none'}`",
        f"- Rebalanced: `{bool(latest.get('rebalanced', False))}`",
        f"- Orders: {int(latest.get('order_count', 0) or 0)}",
        f"- Filled orders: {int(latest.get('filled_order_count', 0) or 0)}",
        f"- Rejected orders: {int(latest.get('rejected_order_count', 0) or 0)}",
        f"- Turnover rate: {float(latest.get('turnover_rate', 0.0) or 0.0):.2%}",
        "",
        "## Execution Quality",
        f"- Cumulative orders: {execution.get('order_count', 0)}",
        f"- Cumulative rejected orders: {execution.get('rejected_order_count', 0)}",
        f"- Cumulative reject rate: {float(execution.get('reject_rate', 0.0) or 0.0):.2%}",
        f"- Latest rejected reasons: {_format_counts(execution.get('latest_rejected_reasons', {}))}",
        f"- Cumulative rejected reasons: {_format_counts(execution.get('cumulative_rejected_reasons', {}))}",
        "",
        "## Target Deviation",
        f"- Target count: {deviation.get('target_count', 0)}",
        f"- Target weight sum: {float(deviation.get('target_weight_sum', 0.0) or 0.0):.2%}",
        f"- Max absolute deviation: {float(deviation.get('max_abs_target_deviation', 0.0) or 0.0):.2%}",
        f"- Max deviation symbol: `{deviation.get('max_deviation_symbol', '') or 'none'}`",
        "",
        "## Top Positions",
    ]
    positions = payload.get("top_positions", [])
    if positions:
        for row in positions:
            lines.append(
                "- "
                f"`{row.get('symbol', '')}` qty={int(row.get('quantity', 0) or 0)} "
                f"weight={float(row.get('weight', 0.0) or 0.0):.2%}"
            )
    else:
        lines.append("- None.")
    lines.extend(["", "## Manual Review Questions"])
    lines.extend(f"- {item}" for item in payload.get("manual_review_questions", []))
    lines.extend(["", "## Prohibited Actions"])
    lines.extend(f"- {item}" for item in payload.get("prohibited_actions", []))
    return "\n".join(lines) + "\n"


def _format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in counts.items())


def _merge_records(
    existing: list[dict[str, Any]],
    new: list[dict[str, Any]],
    *,
    key: str,
) -> list[dict[str, Any]]:
    merged = {str(row.get(key)): row for row in existing if row.get(key)}
    for row in new:
        merged[str(row.get(key))] = row
    return [merged[item] for item in sorted(merged)]


def _read_csv_records(path: Path) -> list[dict[str, Any]]:
    frame = _read_csv(path)
    return frame.to_dict("records") if not frame.empty else []


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
