"""Pre-flight checklist for real A-share research data readiness."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal

from quantify.data.provider import DataProvider
from quantify.ops.data_coverage import DataCoverageReport, analyze_data_coverage
from quantify.ops.real_data_gate import RealDataGateResult, evaluate_real_data_gate

BootstrapDecision = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class BootstrapFinding:
    severity: BootstrapDecision
    code: str
    message: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class RealDataBootstrapReport:
    decision: BootstrapDecision
    config_path: str
    cache_path: str
    data_source: str
    start: str
    end: str
    in_sample_end: str
    out_sample_start: str
    allow_demo_data: bool
    cache_exists: bool
    cache_size_bytes: int
    symbol_count: int
    trading_day_count: int
    latest_bar_date: str
    real_data_gate: dict[str, Any]
    data_coverage: dict[str, Any]
    findings: list[BootstrapFinding]
    required_files: list[dict[str, str]]
    next_commands: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "status": self.decision,
            "config_path": self.config_path,
            "cache_path": self.cache_path,
            "data_source": self.data_source,
            "start": self.start,
            "end": self.end,
            "in_sample_end": self.in_sample_end,
            "out_sample_start": self.out_sample_start,
            "allow_demo_data": self.allow_demo_data,
            "cache_exists": self.cache_exists,
            "cache_size_bytes": self.cache_size_bytes,
            "symbol_count": self.symbol_count,
            "trading_day_count": self.trading_day_count,
            "latest_bar_date": self.latest_bar_date,
            "real_data_gate": self.real_data_gate,
            "data_coverage": self.data_coverage,
            "findings": [finding.to_dict() for finding in self.findings],
            "required_files": self.required_files,
            "next_commands": self.next_commands,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Real Data Bootstrap: {self.decision}",
            "",
            f"- Config path: `{self.config_path}`",
            f"- Cache path: `{self.cache_path}`",
            f"- Cache exists: `{self.cache_exists}`",
            f"- Cache size: `{self.cache_size_bytes}` bytes",
            f"- Data source: `{self.data_source}`",
            f"- Period: `{self.start}` to `{self.end}`",
            f"- In-sample end: `{self.in_sample_end or 'missing'}`",
            f"- Out-sample start: `{self.out_sample_start or 'missing'}`",
            f"- Allow demo data: `{self.allow_demo_data}`",
            f"- Symbols: {self.symbol_count}",
            f"- Trading days: {self.trading_day_count}",
            f"- Latest bar date: `{self.latest_bar_date or 'missing'}`",
            f"- Real data gate: `{self.real_data_gate.get('decision', 'UNKNOWN')}`",
            f"- Data coverage: `{self.data_coverage.get('status', 'UNKNOWN')}`",
            "",
            "## Findings",
        ]
        if self.findings:
            for finding in self.findings:
                evidence = ", ".join(f"{key}={value}" for key, value in finding.evidence.items())
                lines.append(f"- `{finding.severity}` `{finding.code}`: {finding.message} ({evidence or 'n/a'})")
        else:
            lines.append("- No bootstrap findings.")
        lines.extend(["", "## Required Offline CSV Inputs", ""])
        lines.append("| file | required | columns |")
        lines.append("| --- | --- | --- |")
        for row in self.required_files:
            lines.append(f"| `{row['file']}` | `{row['required']}` | `{row['columns']}` |")
        lines.extend(["", "## Next Commands"])
        lines.extend(f"- `{command}`" for command in self.next_commands)
        lines.extend(
            [
                "",
                "This checklist is read-only. It does not download data, connect to a broker, or approve live trading.",
            ]
        )
        return "\n".join(lines) + "\n"


def build_real_data_bootstrap_report(
    data: DataProvider,
    cfg,
    *,
    config_path: str | Path = "",
    cache_path: str | Path | None = None,
    as_of: str | None = None,
    min_symbols: int = 50,
    min_trading_days: int = 120,
    max_staleness_days: int = 10,
    min_coverage_ratio: float = 0.95,
    cache_exists_before_open: bool | None = None,
    cache_size_before_open: int | None = None,
) -> RealDataBootstrapReport:
    """Build a local-cache readiness checklist before weekly research runs."""
    cache = Path(cache_path or cfg.data.cache_path)
    start = str(cfg.research.start)
    end = str(cfg.research.end)
    symbols = data.all_symbols()
    days = data.trading_days(start, end)
    real_gate = evaluate_real_data_gate(
        data,
        start,
        end,
        as_of=as_of,
        min_symbols=min_symbols,
        min_trading_days=min_trading_days,
        max_staleness_days=max_staleness_days,
    )
    coverage = analyze_data_coverage(
        data,
        start,
        end,
        min_coverage_ratio=min_coverage_ratio,
    )
    cache_exists = cache_exists_before_open if cache_exists_before_open is not None else cache.exists()
    cache_size = cache_size_before_open if cache_size_before_open is not None else (
        cache.stat().st_size if cache.exists() else 0
    )
    findings = _bootstrap_findings(
        cfg=cfg,
        cache=cache,
        cache_exists=cache_exists,
        cache_size_bytes=cache_size,
        real_gate=real_gate,
        coverage=coverage,
        min_symbols=min_symbols,
        min_trading_days=min_trading_days,
    )
    return RealDataBootstrapReport(
        decision=_combine([finding.severity for finding in findings]),
        config_path=str(config_path),
        cache_path=str(cache),
        data_source=str(getattr(cfg.data, "source", "")),
        start=start,
        end=end,
        in_sample_end=str(getattr(cfg.research, "in_sample_end", "")),
        out_sample_start=str(getattr(cfg.research, "out_sample_start", "")),
        allow_demo_data=bool(getattr(cfg.research, "allow_demo_data", False)),
        cache_exists=cache_exists,
        cache_size_bytes=cache_size,
        symbol_count=len(symbols),
        trading_day_count=len(days),
        latest_bar_date=real_gate.latest_bar_date,
        real_data_gate=real_gate.to_dict(),
        data_coverage=coverage.to_dict(),
        findings=findings,
        required_files=_required_files(),
        next_commands=_next_commands(config_path, cache),
    )


def write_real_data_bootstrap_report(
    report: RealDataBootstrapReport,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "real_data_bootstrap.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "real_data_bootstrap.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _bootstrap_findings(
    *,
    cfg,
    cache: Path,
    cache_exists: bool,
    cache_size_bytes: int,
    real_gate: RealDataGateResult,
    coverage: DataCoverageReport,
    min_symbols: int,
    min_trading_days: int,
) -> list[BootstrapFinding]:
    findings: list[BootstrapFinding] = []
    if not cache_exists:
        findings.append(
            BootstrapFinding(
                "BLOCK",
                "CACHE_MISSING",
                "Research cache file does not exist.",
                {"cache_path": str(cache)},
            )
        )
    elif cache_size_bytes == 0:
        findings.append(
            BootstrapFinding(
                "BLOCK",
                "CACHE_EMPTY",
                "Research cache file exists but is empty.",
                {"cache_path": str(cache)},
            )
        )
    if bool(getattr(cfg.research, "allow_demo_data", False)):
        findings.append(
            BootstrapFinding(
                "WATCH",
                "DEMO_FALLBACK_ENABLED",
                "allow_demo_data=true is useful for tutorials but unsafe for real-data evidence.",
                {"allow_demo_data": True},
            )
        )
    if not str(getattr(cfg.research, "in_sample_end", "")) or not str(
        getattr(cfg.research, "out_sample_start", "")
    ):
        findings.append(
            BootstrapFinding(
                "WATCH",
                "MISSING_SAMPLE_SPLIT",
                "Research config should define in_sample_end and out_sample_start.",
                {
                    "in_sample_end": str(getattr(cfg.research, "in_sample_end", "")),
                    "out_sample_start": str(getattr(cfg.research, "out_sample_start", "")),
                },
            )
        )
    if real_gate.demo_data_used:
        findings.append(
            BootstrapFinding(
                "BLOCK",
                "DEMO_DATA",
                "Cached symbols look like deterministic demo data.",
                {"symbol_count": real_gate.symbol_count},
            )
        )
    if real_gate.decision == "BLOCK":
        findings.append(
            BootstrapFinding(
                "BLOCK",
                "REAL_DATA_GATE_BLOCK",
                "Recent real-data gate blocks the cache for research evidence.",
                {"real_data_gate": real_gate.decision},
            )
        )
    elif real_gate.decision == "WATCH":
        findings.append(
            BootstrapFinding(
                "WATCH",
                "REAL_DATA_GATE_WATCH",
                "Recent real-data gate has warnings that should be resolved.",
                {"real_data_gate": real_gate.decision},
            )
        )
    if coverage.status == "BLOCK":
        findings.append(
            BootstrapFinding(
                "BLOCK",
                "DATA_COVERAGE_BLOCK",
                "Coverage diagnostics block the cache.",
                {"data_coverage": coverage.status},
            )
        )
    elif coverage.status == "WATCH":
        findings.append(
            BootstrapFinding(
                "WATCH",
                "DATA_COVERAGE_WATCH",
                "Coverage diagnostics have warnings.",
                {
                    "average_coverage_ratio": round(coverage.average_coverage_ratio, 6),
                    "short_history_symbol_count": coverage.short_history_symbol_count,
                },
            )
        )
    if real_gate.symbol_count < min_symbols:
        findings.append(
            BootstrapFinding(
                "WATCH",
                "SYMBOL_COUNT_BELOW_TARGET",
                "Symbol count is below the configured bootstrap target.",
                {"symbol_count": real_gate.symbol_count, "min_symbols": min_symbols},
            )
        )
    if real_gate.trading_day_count < min_trading_days:
        findings.append(
            BootstrapFinding(
                "WATCH",
                "TRADING_DAYS_BELOW_TARGET",
                "Trading-day count is below the configured bootstrap target.",
                {"trading_day_count": real_gate.trading_day_count, "min_trading_days": min_trading_days},
            )
        )
    if not findings:
        findings.append(
            BootstrapFinding(
                "PASS",
                "CACHE_READY_FOR_WEEKLY_PIPELINE",
                "Local cache is ready for offline weekly research and paper-stage review.",
                {},
            )
        )
    return findings


def _required_files() -> list[dict[str, str]]:
    return [
        {
            "file": "bars.csv",
            "required": "yes",
            "columns": "symbol,date,open,high,low,close,volume,amount",
        },
        {
            "file": "stock_info.csv",
            "required": "recommended",
            "columns": "symbol,name,exchange,list_date,delist_date,industry,is_st",
        },
        {
            "file": "fundamentals.csv",
            "required": "recommended",
            "columns": "symbol,date,pe_ttm,pb,roe,market_cap,turnover_rate",
        },
        {
            "file": "calendar.csv",
            "required": "recommended",
            "columns": "date,is_open",
        },
        {
            "file": "suspensions.csv",
            "required": "recommended",
            "columns": "symbol,date,is_suspended",
        },
        {
            "file": "index_constituents.csv",
            "required": "recommended",
            "columns": "index_code,date,symbol",
        },
    ]


def _next_commands(config_path: str | Path, cache: Path) -> list[str]:
    cfg_arg = str(config_path or "config/research.yaml")
    return [
        (
            ".\\.venv\\Scripts\\python.exe examples/write_data_export_templates.py "
            "--output-dir data_exports"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples/validate_research_csv.py "
            "--bars-csv data_exports\\bars.csv "
            "--stock-info-csv data_exports\\stock_info.csv "
            "--fundamentals-csv data_exports\\fundamentals.csv "
            "--calendar-csv data_exports\\calendar.csv "
            "--suspensions-csv data_exports\\suspensions.csv "
            "--index-constituents-csv data_exports\\index_constituents.csv "
            "--output-dir results\\import\\csv_validation"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples/import_research_csv.py "
            f"--cache {cache} --bars-csv data_exports\\bars.csv "
            "--stock-info-csv data_exports\\stock_info.csv "
            "--fundamentals-csv data_exports\\fundamentals.csv "
            "--calendar-csv data_exports\\calendar.csv "
            "--suspensions-csv data_exports\\suspensions.csv "
            "--index-constituents-csv data_exports\\index_constituents.csv "
            "--validate "
            "--output-dir results\\import\\csv"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples/run_real_data_bootstrap.py "
            f"--config {cfg_arg} --output-dir results\\bootstrap"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples/run_weekly_pipeline.py "
            f"--config {cfg_arg} --starting-capital 100000 --target-capital 1000000 --years 8"
        ),
    ]


def _combine(decisions: list[BootstrapDecision]) -> BootstrapDecision:
    if any(decision == "BLOCK" for decision in decisions):
        return "BLOCK"
    if any(decision == "WATCH" for decision in decisions):
        return "WATCH"
    return "PASS"
