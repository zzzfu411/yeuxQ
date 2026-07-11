"""Run a multi-factor A-share research simulation.

Usage:
    uv run python examples/run_research.py --config config/research.yaml
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from loguru import logger

from quantify.audit import audit_data, write_data_audit
from quantify.core.portfolio import Portfolio
from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.engine.paper_broker import PaperBroker, PaperBrokerConfig
from quantify.ops.run_manifest import build_run_manifest, write_run_manifest
from quantify.research.demo_data import seed_demo_data
from quantify.research.engine import ResearchEngine
from quantify.research.factors import FactorPipeline
from quantify.research.report import research_evidence_digest, write_research_report
from quantify.research.strategy import MultiFactorStrategyConfig, MultiFactorTargetStrategy
from quantify.research.universe import UniverseConfig, UniverseFilter
from quantify.utils.config import Config, load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Run multi-factor research simulation.")
    parser.add_argument("--config", default="config/research.yaml", help="YAML config path")
    parser.add_argument("--cache", default=None, help="Override config data.cache_path")
    args = parser.parse_args()
    cfg = _load_config(args.config, cache_path=args.cache)

    storage = BarStorage(cfg.data.cache_path)
    provider = DataProvider(storage)
    demo_used = _ensure_data(provider, storage, cfg)

    universe_filter = UniverseFilter(
        UniverseConfig(
            mode=cfg.universe.mode,
            index_code=cfg.universe.index_code,
            include_st=cfg.universe.include_st,
            min_history_days=cfg.universe.min_history_days,
        )
    )
    factor_pipeline = FactorPipeline()
    strategy = MultiFactorTargetStrategy(
        universe_filter,
        factor_pipeline,
        MultiFactorStrategyConfig(
            n_holdings=cfg.strategy.n_holdings,
            max_weight=cfg.strategy.max_weight,
        ),
    )
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
    portfolio = Portfolio(initial_cash=cfg.research.initial_cash)
    engine = ResearchEngine(
        provider,
        strategy,
        broker,
        portfolio,
        factor_pipeline,
        max_drawdown_stop=cfg.risk.max_drawdown_stop,
    )
    result = engine.run(cfg.research.start, cfg.research.end, rebalance=cfg.research.rebalance)

    run_dir = Path(cfg.output.results_dir) / datetime.now().strftime("%Y%m%d_%H%M%S")
    trading_days = provider.trading_days(cfg.research.start, cfg.research.end)
    all_symbols = provider.all_symbols()
    demo_like = demo_used or _looks_like_demo_data(all_symbols)
    assumptions = {
        "data_source": cfg.data.source,
        "cache_path": cfg.data.cache_path,
        "demo_data_used": demo_like,
        "start": cfg.research.start,
        "end": cfg.research.end,
        "universe": cfg.universe.mode,
        "rebalance": cfg.research.rebalance,
        "in_sample_end": cfg.research.in_sample_end,
        "out_sample_start": cfg.research.out_sample_start,
        "n_holdings": cfg.strategy.n_holdings,
        "max_weight": cfg.strategy.max_weight,
        "symbol_count": len(all_symbols),
        "trading_day_count": len(trading_days),
        "notice": "Research simulation only; no broker or live trading connection.",
    }
    audit = audit_data(
        provider,
        cfg.research.start,
        cfg.research.end,
        data_source=cfg.data.source,
        cache_path=cfg.data.cache_path,
        demo_data_used=demo_like,
    )
    manifest = build_run_manifest(
        provider,
        cfg,
        storage=storage,
        config_path=args.config,
        purpose="research",
        demo_data_used=demo_like,
    )
    out = write_research_report(
        result,
        run_dir,
        title="A-share multi-factor research",
        assumptions=assumptions,
        evidence=research_evidence_digest(audit=audit, manifest=manifest),
    )
    logger.info("Research report written to {}", out.resolve())
    write_data_audit(audit, run_dir)
    logger.info("Data audit written to {}", (run_dir / "data_audit.md").resolve())
    write_run_manifest(manifest, run_dir)
    logger.info("Run manifest written to {}", (run_dir / "run_manifest.md").resolve())
    if demo_used:
        logger.warning("Demo data was used because the local research cache was empty.")
    elif demo_like:
        logger.warning("Cached data appears to be deterministic demo data.")


def _ensure_data(provider: DataProvider, storage: BarStorage, cfg) -> bool:
    symbols = provider.all_symbols()
    days = provider.trading_days(cfg.research.start, cfg.research.end)
    if symbols and days:
        if _looks_like_demo_data(symbols) and not cfg.research.allow_demo_data:
            raise RuntimeError(
                "Cached data appears to be deterministic demo data. "
                "Import real research data or set allow_demo_data=true for tutorials."
            )
        return False
    if not cfg.research.allow_demo_data:
        raise RuntimeError(
            "No cached research data found. Download/seed data first or set allow_demo_data=true."
        )
    logger.warning("No cached research data found; seeding deterministic demo data.")
    seed_demo_data(storage, cfg.research.start, cfg.research.end)
    return True


def _looks_like_demo_data(symbols: list[str]) -> bool:
    return bool(symbols) and all(symbol.startswith("DEMO") for symbol in symbols)

def _load_config(path: str, *, cache_path: str | None = None) -> Config:
    cfg = load_config(path)
    if cache_path is None:
        return cfg
    payload = cfg.to_dict()
    data = dict(payload.get("data", {}))
    data["cache_path"] = cache_path
    return Config({**payload, "data": data})


if __name__ == "__main__":
    main()
