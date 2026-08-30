"""Gate that verifies cached A-share data is real, recent, and broad enough."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from quantify.data.demo import is_demo_contaminated
from quantify.data.provider import DataProvider

RealDataDecision = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class RealDataFinding:
    severity: RealDataDecision
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
class RealDataGateResult:
    decision: RealDataDecision
    as_of: str
    start: str
    end: str
    latest_bar_date: str
    staleness_days: int | None
    symbol_count: int
    trading_day_count: int
    bar_count: int
    demo_data_used: bool
    findings: list[RealDataFinding]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "status": self.decision,
            "as_of": self.as_of,
            "start": self.start,
            "end": self.end,
            "latest_bar_date": self.latest_bar_date,
            "staleness_days": self.staleness_days,
            "symbol_count": self.symbol_count,
            "trading_day_count": self.trading_day_count,
            "bar_count": self.bar_count,
            "demo_data_used": self.demo_data_used,
            "findings": [finding.to_dict() for finding in self.findings],
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Real Data Gate: {self.decision}",
            "",
            f"- As of: `{self.as_of}`",
            f"- Period: `{self.start}` to `{self.end}`",
            f"- Latest bar date: `{self.latest_bar_date or 'missing'}`",
            f"- Staleness days: `{self.staleness_days if self.staleness_days is not None else 'n/a'}`",
            f"- Symbols: {self.symbol_count}",
            f"- Trading days: {self.trading_day_count}",
            f"- Bars: {self.bar_count}",
            f"- Demo data used: `{self.demo_data_used}`",
            "",
            "## Findings",
        ]
        if self.findings:
            for finding in self.findings:
                evidence = ", ".join(f"{key}={value}" for key, value in finding.evidence.items())
                lines.append(f"- `{finding.severity}` `{finding.code}`: {finding.message} ({evidence})")
        else:
            lines.append("- No real-data gate findings.")
        lines.extend(
            [
                "",
                "This gate only checks whether research evidence can be treated as recent real-data evidence.",
                "It does not approve live trading or broker connectivity.",
            ]
        )
        return "\n".join(lines) + "\n"


def evaluate_real_data_gate(
    data: DataProvider,
    start: str,
    end: str,
    *,
    as_of: str | None = None,
    min_symbols: int = 50,
    min_trading_days: int = 120,
    max_staleness_days: int = 10,
) -> RealDataGateResult:
    as_of_date = pd.Timestamp(as_of or date.today().isoformat()).date()
    symbols = data.all_symbols()
    days = data.trading_days(start, end)
    bars = data.bars(symbols, start, end) if symbols else pd.DataFrame()
    latest_bar_date = _latest_bar_date(bars)
    staleness_days = _staleness_days(latest_bar_date, as_of_date)
    demo_data_used = is_demo_contaminated(symbols)
    findings: list[RealDataFinding] = []

    if not symbols:
        findings.append(RealDataFinding("BLOCK", "NO_SYMBOLS", "No symbols are available.", {}))
    if bars.empty:
        findings.append(RealDataFinding("BLOCK", "NO_BARS", "No cached bars are available.", {}))
    if demo_data_used:
        findings.append(
            RealDataFinding(
                "BLOCK",
                "DEMO_DATA",
                "Demo symbols cannot be treated as recent real A-share evidence.",
                {"symbol_count": len(symbols)},
            )
        )
    if len(symbols) < min_symbols:
        findings.append(
            RealDataFinding(
                "WATCH",
                "LOW_SYMBOL_COVERAGE",
                "Symbol coverage is narrow for broad A-share candidate research.",
                {"symbol_count": len(symbols), "min_symbols": min_symbols},
            )
        )
    if len(days) < min_trading_days:
        findings.append(
            RealDataFinding(
                "WATCH",
                "SHORT_HISTORY",
                "Trading-day history is short for stable compounding research.",
                {"trading_day_count": len(days), "min_trading_days": min_trading_days},
            )
        )
    if staleness_days is None:
        findings.append(
            RealDataFinding(
                "BLOCK",
                "MISSING_LATEST_DATE",
                "Latest bar date cannot be determined.",
                {},
            )
        )
    elif staleness_days < 0:
        findings.append(
            RealDataFinding(
                "WATCH",
                "FUTURE_DATED_BARS",
                "Cached bars are dated after the gate as-of date.",
                {"latest_bar_date": latest_bar_date, "as_of": as_of_date.isoformat()},
            )
        )
    elif staleness_days > max_staleness_days:
        findings.append(
            RealDataFinding(
                "BLOCK",
                "STALE_DATA",
                "Latest cached bar is too old for recent-market review.",
                {
                    "latest_bar_date": latest_bar_date,
                    "as_of": as_of_date.isoformat(),
                    "staleness_days": staleness_days,
                    "max_staleness_days": max_staleness_days,
                },
            )
        )

    return RealDataGateResult(
        decision=_combine([finding.severity for finding in findings]),
        as_of=as_of_date.isoformat(),
        start=start,
        end=end,
        latest_bar_date=latest_bar_date or "",
        staleness_days=staleness_days,
        symbol_count=len(symbols),
        trading_day_count=len(days),
        bar_count=len(bars),
        demo_data_used=demo_data_used,
        findings=findings,
    )


def write_real_data_gate(result: RealDataGateResult, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "real_data_gate.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "real_data_gate.md").write_text(result.to_markdown(), encoding="utf-8")
    return root


def _latest_bar_date(bars: pd.DataFrame) -> str:
    if bars.empty or "date" not in bars:
        return ""
    values = pd.to_datetime(bars["date"], errors="coerce").dropna()
    if values.empty:
        return ""
    return values.max().date().isoformat()


def _staleness_days(latest_bar_date: str, as_of: date) -> int | None:
    if not latest_bar_date:
        return None
    return (as_of - pd.Timestamp(latest_bar_date).date()).days


def _combine(decisions: list[RealDataDecision]) -> RealDataDecision:
    if any(decision == "BLOCK" for decision in decisions):
        return "BLOCK"
    if any(decision == "WATCH" for decision in decisions):
        return "WATCH"
    return "PASS"
