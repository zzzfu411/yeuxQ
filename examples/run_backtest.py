"""Run an end-to-end backtest from a YAML config file.

Usage:
    uv run python examples/run_backtest.py --config config/default.yaml

Outputs go to ./results/<timestamp>/
    summary.json   — performance metrics
    trades.csv     — every fill
    equity.csv     — net-worth time series
    equity.png     — chart of equity + drawdown + buy/sell markers
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
from loguru import logger

from quantify.analytics.metrics import compute_report
from quantify.analytics.plot import plot_equity
from quantify.core.portfolio import Portfolio
from quantify.data.akshare_feed import AkshareFeed
from quantify.data.storage import BarStorage
from quantify.engine.backtest import BacktestEngine
from quantify.engine.broker_sim import BrokerConfig, BrokerSim
from quantify.risk.manager import RiskConfig, RiskManager
from quantify.risk.sizer import FixedPctSizer
from quantify.strategy.dual_ma import DualMAStrategy
from quantify.utils.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/default.yaml", help="YAML config path")
    args = parser.parse_args()

    cfg = load_config(args.config)

    # ---- Data feed (only akshare in MVP) ----
    if cfg.data.source != "akshare":
        raise NotImplementedError(f"data.source={cfg.data.source!r} not supported in MVP")
    storage = BarStorage(cfg.data.cache_path)
    feed = AkshareFeed(storage=storage, adjust=cfg.data.adjust)

    # ---- Strategy (only dual_ma in MVP) ----
    if cfg.strategy.name != "dual_ma":
        raise NotImplementedError(f"strategy.name={cfg.strategy.name!r} not supported in MVP")
    strategy = DualMAStrategy(**cfg.strategy.params.to_dict())
    universe: list[str] = cfg.strategy.params.universe

    # ---- Broker / Portfolio / Risk ----
    broker = BrokerSim(BrokerConfig(
        commission_rate=cfg.backtest.commission_rate,
        min_commission=cfg.backtest.min_commission,
        stamp_tax=cfg.backtest.stamp_tax,
        slippage_bps=cfg.backtest.slippage_bps,
    ))
    portfolio = Portfolio(initial_cash=cfg.backtest.initial_cash)

    if cfg.risk.sizer != "fixed_pct":
        raise NotImplementedError(f"risk.sizer={cfg.risk.sizer!r} not supported in MVP")
    sizer = FixedPctSizer(pct=cfg.risk.sizer_param)
    risk = RiskManager(
        RiskConfig(
            max_position_pct=cfg.risk.max_position_pct,
            max_drawdown_stop=cfg.risk.max_drawdown_stop,
        ),
        sizer=sizer,
    )

    # ---- Run backtest ----
    engine = BacktestEngine(feed, strategy, broker, risk, portfolio)
    engine.run(symbols=universe, start=cfg.backtest.start, end=cfg.backtest.end)

    # ---- Report ----
    if not portfolio.equity_curve:
        logger.error("Empty equity curve. Did you download data first? "
                     "(Try: uv run python examples/download_data.py)")
        return

    report = compute_report(portfolio.equity_curve, fills=portfolio.trade_log)
    logger.info("=== Performance ===")
    for k, v in report.to_dict().items():
        if isinstance(v, float):
            logger.info("  {:24s} {:>12.4f}", k, v)
        else:
            logger.info("  {:24s} {:>12}", k, v)

    # ---- Persist outputs ----
    results_root = Path(cfg.output.results_dir)
    run_dir = results_root / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "summary.json").write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    pd.DataFrame(
        [
            {
                "timestamp": ts.isoformat(),
                "symbol": f.symbol,
                "direction": f.direction.value,
                "quantity": f.quantity,
                "fill_price": f.fill_price,
                "commission": f.commission,
                "tax": f.tax,
            }
            for f in portfolio.trade_log
            for ts in [f.timestamp]
        ]
    ).to_csv(run_dir / "trades.csv", index=False)

    pd.DataFrame(
        portfolio.equity_curve, columns=["timestamp", "equity"],
    ).to_csv(run_dir / "equity.csv", index=False)

    plot_equity(
        portfolio.equity_curve,
        portfolio.trade_log,
        run_dir / "equity.png",
        title=f"DualMA backtest: {','.join(universe)} {cfg.backtest.start}~{cfg.backtest.end}",
    )

    logger.info("Outputs written to: {}", run_dir.resolve())


if __name__ == "__main__":
    main()
