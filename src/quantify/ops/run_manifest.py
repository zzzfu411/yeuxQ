"""Reproducible run manifest for research and weekly evidence artifacts."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage


@dataclass(frozen=True, slots=True)
class RunManifest:
    created_at_utc: str
    purpose: str
    config_path: str
    config_sha256: str
    cache_path: str
    cache_exists: bool
    cache_size_bytes: int
    cache_sha256: str
    data_source: str
    start: str
    end: str
    in_sample_end: str
    out_sample_start: str
    demo_data_used: bool
    symbol_count: int
    trading_day_count: int
    latest_bar_date: str
    data_version: dict[str, str]
    research_parameters: dict[str, Any]
    safety_boundary: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at_utc": self.created_at_utc,
            "purpose": self.purpose,
            "config_path": self.config_path,
            "config_sha256": self.config_sha256,
            "cache_path": self.cache_path,
            "cache_exists": self.cache_exists,
            "cache_size_bytes": self.cache_size_bytes,
            "cache_sha256": self.cache_sha256,
            "data_source": self.data_source,
            "start": self.start,
            "end": self.end,
            "in_sample_end": self.in_sample_end,
            "out_sample_start": self.out_sample_start,
            "demo_data_used": self.demo_data_used,
            "symbol_count": self.symbol_count,
            "trading_day_count": self.trading_day_count,
            "latest_bar_date": self.latest_bar_date,
            "data_version": self.data_version,
            "research_parameters": self.research_parameters,
            "safety_boundary": self.safety_boundary,
        }

    def to_markdown(self) -> str:
        lines = [
            "# Run Manifest",
            "",
            f"- Purpose: `{self.purpose}`",
            f"- Created at UTC: `{self.created_at_utc}`",
            f"- Config path: `{self.config_path}`",
            f"- Config sha256: `{self.config_sha256 or 'missing'}`",
            f"- Cache path: `{self.cache_path}`",
            f"- Cache exists: `{self.cache_exists}`",
            f"- Cache size bytes: {self.cache_size_bytes}",
            f"- Cache sha256: `{self.cache_sha256 or 'missing'}`",
            f"- Data source: `{self.data_source}`",
            f"- Period: `{self.start}` to `{self.end}`",
            f"- In-sample end: `{self.in_sample_end or 'missing'}`",
            f"- Out-sample start: `{self.out_sample_start or 'missing'}`",
            f"- Demo data used: `{self.demo_data_used}`",
            f"- Symbols: {self.symbol_count}",
            f"- Trading days: {self.trading_day_count}",
            f"- Latest bar date: `{self.latest_bar_date or 'missing'}`",
            "",
            "## Data Version",
        ]
        if self.data_version:
            lines.extend(f"- {key}: `{value}`" for key, value in self.data_version.items())
        else:
            lines.append("- No import metadata recorded in cache.")
        lines.extend(["", "## Research Parameters"])
        lines.extend(f"- {key}: `{value}`" for key, value in self.research_parameters.items())
        lines.extend(["", "## Safety Boundary"])
        lines.extend(f"- {item}" for item in self.safety_boundary)
        return "\n".join(lines) + "\n"


def build_run_manifest(
    data: DataProvider,
    cfg,
    *,
    storage: BarStorage,
    config_path: str | Path = "",
    purpose: str = "research",
    demo_data_used: bool = False,
) -> RunManifest:
    symbols = data.all_symbols()
    days = data.trading_days(cfg.research.start, cfg.research.end)
    latest_bar_date = _latest_bar_date(storage, symbols)
    cache = Path(cfg.data.cache_path)
    config = Path(config_path) if str(config_path) else None
    return RunManifest(
        created_at_utc=datetime.now(tz=UTC).replace(microsecond=0).isoformat(),
        purpose=purpose,
        config_path=str(config_path),
        config_sha256=_file_sha256(config) if config else "",
        cache_path=str(cache),
        cache_exists=cache.exists(),
        cache_size_bytes=cache.stat().st_size if cache.exists() else 0,
        cache_sha256=_file_sha256(cache) if cache.exists() else "",
        data_source=str(getattr(cfg.data, "source", "")),
        start=str(cfg.research.start),
        end=str(cfg.research.end),
        in_sample_end=str(getattr(cfg.research, "in_sample_end", "")),
        out_sample_start=str(getattr(cfg.research, "out_sample_start", "")),
        demo_data_used=demo_data_used,
        symbol_count=len(symbols),
        trading_day_count=len(days),
        latest_bar_date=latest_bar_date,
        data_version=storage.load_metadata(),
        research_parameters=_research_parameters(cfg),
        safety_boundary=[
            "Research and paper evidence only; no live broker connection.",
            "LLM outputs are advisory and cannot change deterministic gates.",
            "Historical backtests do not guarantee future profits.",
            "Manual approval is required before any micro-live preparation.",
        ],
    )


def write_run_manifest(manifest: RunManifest, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "run_manifest.json").write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "run_manifest.md").write_text(manifest.to_markdown(), encoding="utf-8")
    return root


def _latest_bar_date(storage: BarStorage, symbols: list[str]) -> str:
    dates = [date for symbol in symbols if (date := storage.last_date(symbol))]
    return max(dates) if dates else ""


def _file_sha256(path: Path | None) -> str:
    if path is None or not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _research_parameters(cfg) -> dict[str, Any]:
    return {
        "initial_cash": _cfg_get(cfg.research, "initial_cash"),
        "rebalance": _cfg_get(cfg.research, "rebalance"),
        "universe_mode": _cfg_get(cfg.universe, "mode"),
        "index_code": _cfg_get(cfg.universe, "index_code"),
        "include_st": _cfg_get(cfg.universe, "include_st"),
        "min_history_days": _cfg_get(cfg.universe, "min_history_days"),
        "strategy_name": _cfg_get(cfg.strategy, "name"),
        "n_holdings": _cfg_get(cfg.strategy, "n_holdings"),
        "max_weight": _cfg_get(cfg.strategy, "max_weight"),
        "max_drawdown_stop": _cfg_get(cfg.risk, "max_drawdown_stop"),
        "commission_rate": _cfg_get(cfg.broker, "commission_rate"),
        "stamp_tax": _cfg_get(cfg.broker, "stamp_tax"),
        "slippage_bps": _cfg_get(cfg.broker, "slippage_bps"),
        "price_limit_pct": _cfg_get(cfg.broker, "price_limit_pct"),
        "lot_size": _cfg_get(cfg.broker, "lot_size"),
    }


def _cfg_get(section, key: str, default: Any = "") -> Any:
    try:
        return getattr(section, key)
    except AttributeError:
        return default
