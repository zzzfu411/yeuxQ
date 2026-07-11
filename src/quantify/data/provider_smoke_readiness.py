"""Provider smoke-readiness report for recent A-share data acquisition.

The report is intentionally diagnostic.  A PASS means the provider endpoint
worked for the supplied import report; it does not mean the resulting cache is
research-ready, source-QA approved, or usable for trading.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

import pandas as pd

ProviderSmokeStatus = Literal["PASS", "WATCH", "BLOCK"]


PROHIBITED_ACTIONS = [
    "Do not treat provider smoke PASS as source-QA approval.",
    "Do not treat provider smoke PASS as research-cache readiness.",
    "Do not run candidate experiments until deterministic data, source QA, and bootstrap gates pass.",
    "Do not connect provider smoke output to a real broker or order workflow.",
    "Do not let LLM output upgrade deterministic provider, data, or trading gates.",
]


@dataclass(frozen=True, slots=True)
class ProviderSmokeReadiness:
    status: ProviderSmokeStatus
    provider: str
    as_of: str
    latest_import_report_path: str
    attempted: bool
    report_status: str
    start: str
    end: str
    actual_bar_start: str
    actual_bar_end: str
    requested_symbols: int
    imported_symbols: int
    failed_symbols: int
    bar_rows: int
    calendar_days: int
    network_blocked: bool
    failure_stage: str
    recommended_route: str
    covers_requested_end: bool
    end_lag_days: int | None
    endpoint_viability: ProviderSmokeStatus
    data_sufficiency_status: ProviderSmokeStatus
    blockers: list[str]
    watch_items: list[str]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "provider": self.provider,
            "as_of": self.as_of,
            "latest_import_report_path": self.latest_import_report_path,
            "attempted": self.attempted,
            "report_status": self.report_status,
            "start": self.start,
            "end": self.end,
            "actual_bar_start": self.actual_bar_start,
            "actual_bar_end": self.actual_bar_end,
            "requested_symbols": self.requested_symbols,
            "imported_symbols": self.imported_symbols,
            "failed_symbols": self.failed_symbols,
            "bar_rows": self.bar_rows,
            "calendar_days": self.calendar_days,
            "network_blocked": self.network_blocked,
            "failure_stage": self.failure_stage,
            "recommended_route": self.recommended_route,
            "covers_requested_end": self.covers_requested_end,
            "end_lag_days": self.end_lag_days,
            "endpoint_viability": self.endpoint_viability,
            "data_sufficiency_status": self.data_sufficiency_status,
            "blockers": self.blockers,
            "watch_items": self.watch_items,
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Provider Smoke Readiness: {self.status}",
            "",
            f"- Provider: `{self.provider}`",
            f"- As of: `{self.as_of}`",
            f"- Latest import report: `{self.latest_import_report_path or 'not supplied'}`",
            f"- Attempted: `{self.attempted}`",
            f"- Import status: `{self.report_status or 'MISSING'}`",
            f"- Endpoint viability: `{self.endpoint_viability}`",
            f"- Data sufficiency: `{self.data_sufficiency_status}`",
            f"- Period: `{self.start or 'missing'}` to `{self.end or 'missing'}`",
            f"- Actual bars: `{self.actual_bar_start or 'missing'}` to `{self.actual_bar_end or 'missing'}`",
            f"- Requested/imported/failed symbols: {self.requested_symbols}/{self.imported_symbols}/{self.failed_symbols}",
            f"- Rows/calendar days: {self.bar_rows}/{self.calendar_days}",
            f"- Network blocked: `{self.network_blocked}`",
            f"- Failure stage: `{self.failure_stage or 'none'}`",
            f"- Recommended route: `{self.recommended_route or 'none'}`",
            "",
            "This report only checks provider endpoint viability from an import report. "
            "It cannot approve source QA, research, paper trading, or live trading.",
            "",
            "## Blockers",
        ]
        lines.extend(f"- {item}" for item in self.blockers) if self.blockers else lines.append("- None.")
        lines.extend(["", "## Watch Items"])
        lines.extend(f"- {item}" for item in self.watch_items) if self.watch_items else lines.append("- None.")
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_provider_smoke_readiness(
    *,
    latest_import_report_path: str | Path | None = "results/import/recent/data_import.json",
    requested_end: str = "",
    provider: str = "akshare",
    as_of: str | None = None,
    min_symbols: int = 300,
    min_trading_days: int = 240,
) -> ProviderSmokeReadiness:
    """Build a diagnostic readiness card from a provider import report."""
    report_path = Path(latest_import_report_path) if latest_import_report_path else None
    payload = _read_json(report_path) if report_path is not None else {}
    now = as_of or date.today().isoformat()
    if not payload:
        path_text = str(report_path or "")
        return ProviderSmokeReadiness(
            status="WATCH",
            provider=provider,
            as_of=now,
            latest_import_report_path=path_text,
            attempted=False,
            report_status="MISSING",
            start="",
            end="",
            actual_bar_start="",
            actual_bar_end="",
            requested_symbols=0,
            imported_symbols=0,
            failed_symbols=0,
            bar_rows=0,
            calendar_days=0,
            network_blocked=False,
            failure_stage="",
            recommended_route="try_provider_or_offline_csv",
            covers_requested_end=False,
            end_lag_days=None,
            endpoint_viability="WATCH",
            data_sufficiency_status="BLOCK",
            blockers=[],
            watch_items=[f"{Path(path_text).name or 'data_import.json'} is missing or unreadable."],
            next_actions=[
                "Run a tiny provider smoke import with explicit symbols, or continue with guarded offline CSV/TDX intake.",
                "Do not treat a missing provider smoke report as data readiness.",
            ],
            prohibited_actions=PROHIBITED_ACTIONS,
        )

    report_status = str(payload.get("status") or "UNKNOWN").upper()
    start = str(payload.get("start") or "")
    end = str(payload.get("end") or "")
    metadata = payload.get("metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    requested = _int(payload.get("requested_symbols"))
    imported = _int(payload.get("imported_symbols"))
    failed = _int(payload.get("failed_symbols"))
    bar_rows = _int(payload.get("bar_rows"))
    calendar_days = _int(payload.get("calendar_days"))
    has_positive_bars = imported > 0 and bar_rows > 0 and calendar_days > 0
    actual_start = _actual_coverage_value(
        metadata,
        "actual_bar_start",
        fallback=start,
        allow_fallback=has_positive_bars,
    )
    actual_end = _actual_coverage_value(
        metadata,
        "actual_bar_end",
        fallback=end,
        allow_fallback=has_positive_bars,
    )
    reasons = _failure_reasons(payload.get("failures", []))
    network_blocked = _bool(payload.get("network_blocked")) or _network_blocked(reasons)
    failure_stage = str(payload.get("failure_stage") or metadata.get("failure_stage") or "").strip()
    recommended_route = str(payload.get("recommended_route") or metadata.get("recommended_route") or "").strip()
    end_lag_days = _end_lag_days(actual_end, requested_end)
    covers_requested_end = bool(requested_end) and end_lag_days is not None and end_lag_days <= 0

    endpoint_viability = _endpoint_viability(
        report_status=report_status,
        imported_symbols=imported,
        failed_symbols=failed,
        bar_rows=bar_rows,
        calendar_days=calendar_days,
        network_blocked=network_blocked,
    )
    data_sufficiency = _data_sufficiency(
        imported_symbols=imported,
        calendar_days=calendar_days,
        actual_bar_end=actual_end,
        requested_end=requested_end,
        min_symbols=min_symbols,
        min_trading_days=min_trading_days,
    )
    blockers = _blockers(
        endpoint_viability=endpoint_viability,
        network_blocked=network_blocked,
        report_status=report_status,
        reasons=reasons,
        imported_symbols=imported,
        bar_rows=bar_rows,
        calendar_days=calendar_days,
        path=str(report_path),
    )
    watch_items = _watch_items(
        endpoint_viability=endpoint_viability,
        data_sufficiency=data_sufficiency,
        report_status=report_status,
        failed_symbols=failed,
        actual_bar_start=actual_start,
        actual_bar_end=actual_end,
        requested_end=requested_end,
        end_lag_days=end_lag_days,
        imported_symbols=imported,
        calendar_days=calendar_days,
        min_symbols=min_symbols,
        min_trading_days=min_trading_days,
    )
    return ProviderSmokeReadiness(
        status=_overall_status(endpoint_viability, watch_items),
        provider=provider,
        as_of=now,
        latest_import_report_path=str(report_path),
        attempted=True,
        report_status=report_status,
        start=start,
        end=end,
        actual_bar_start=actual_start,
        actual_bar_end=actual_end,
        requested_symbols=requested,
        imported_symbols=imported,
        failed_symbols=failed,
        bar_rows=bar_rows,
        calendar_days=calendar_days,
        network_blocked=network_blocked,
        failure_stage=failure_stage,
        recommended_route=recommended_route or _recommended_route(endpoint_viability, network_blocked),
        covers_requested_end=covers_requested_end,
        end_lag_days=end_lag_days,
        endpoint_viability=endpoint_viability,
        data_sufficiency_status=data_sufficiency,
        blockers=blockers,
        watch_items=watch_items,
        next_actions=_next_actions(
            endpoint_viability=endpoint_viability,
            data_sufficiency=data_sufficiency,
            network_blocked=network_blocked,
            recommended_route=recommended_route,
        ),
        prohibited_actions=PROHIBITED_ACTIONS,
    )


def write_provider_smoke_readiness(
    report: ProviderSmokeReadiness,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "provider_smoke_readiness.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "provider_smoke_readiness.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _endpoint_viability(
    *,
    report_status: str,
    imported_symbols: int,
    failed_symbols: int,
    bar_rows: int,
    calendar_days: int,
    network_blocked: bool,
) -> ProviderSmokeStatus:
    if network_blocked:
        return "BLOCK"
    if report_status == "BLOCK" or imported_symbols <= 0 or bar_rows <= 0 or calendar_days <= 0:
        return "BLOCK"
    if report_status == "WATCH" or failed_symbols > 0:
        return "WATCH"
    return "PASS"


def _data_sufficiency(
    *,
    imported_symbols: int,
    calendar_days: int,
    actual_bar_end: str,
    requested_end: str,
    min_symbols: int,
    min_trading_days: int,
) -> ProviderSmokeStatus:
    if imported_symbols <= 0 or calendar_days <= 0:
        return "BLOCK"
    end_lag = _end_lag_days(actual_bar_end, requested_end)
    if (
        imported_symbols >= min_symbols
        and calendar_days >= min_trading_days
        and (not requested_end or (end_lag is not None and end_lag <= 0))
    ):
        return "PASS"
    return "WATCH"


def _overall_status(
    endpoint_viability: ProviderSmokeStatus,
    watch_items: list[str],
) -> ProviderSmokeStatus:
    if endpoint_viability == "BLOCK":
        return "BLOCK"
    if endpoint_viability == "WATCH":
        return "WATCH"
    return "WATCH" if watch_items else "PASS"


def _blockers(
    *,
    endpoint_viability: ProviderSmokeStatus,
    network_blocked: bool,
    report_status: str,
    reasons: list[str],
    imported_symbols: int,
    bar_rows: int,
    calendar_days: int,
    path: str,
) -> list[str]:
    if endpoint_viability != "BLOCK":
        return []
    if network_blocked:
        return [f"Provider smoke is network/proxy blocked; report={path}."]
    if report_status == "BLOCK":
        reason = reasons[0] if reasons else "provider import returned BLOCK"
        return [f"Provider smoke import failed: {reason}"]
    return [
        (
            "Provider smoke imported no usable bars "
            f"(symbols={imported_symbols}, rows={bar_rows}, calendar_days={calendar_days})."
        )
    ]


def _watch_items(
    *,
    endpoint_viability: ProviderSmokeStatus,
    data_sufficiency: ProviderSmokeStatus,
    report_status: str,
    failed_symbols: int,
    actual_bar_start: str,
    actual_bar_end: str,
    requested_end: str,
    end_lag_days: int | None,
    imported_symbols: int,
    calendar_days: int,
    min_symbols: int,
    min_trading_days: int,
) -> list[str]:
    items: list[str] = []
    if endpoint_viability == "WATCH":
        items.append(
            f"Provider smoke is partial ({report_status}); failed_symbols={failed_symbols}."
        )
    if imported_symbols > 0 and (not actual_bar_start or not actual_bar_end):
        items.append("Provider smoke report is missing actual_bar_start/actual_bar_end coverage metadata.")
    if requested_end and end_lag_days is not None and end_lag_days > 0:
        items.append(
            f"Provider smoke actual bars end at {actual_bar_end}, {end_lag_days} days before requested research end {requested_end}."
        )
    if data_sufficiency == "WATCH":
        items.append(
            
                "Smoke sample is not sufficient for broad research by itself "
                f"(symbols={imported_symbols}/{min_symbols}, trading_days={calendar_days}/{min_trading_days})."
            
        )
    return items


def _next_actions(
    *,
    endpoint_viability: ProviderSmokeStatus,
    data_sufficiency: ProviderSmokeStatus,
    network_blocked: bool,
    recommended_route: str,
) -> list[str]:
    if endpoint_viability == "BLOCK" and network_blocked:
        return [
            "Use guarded offline CSV/TDX intake until provider network/proxy access is fixed.",
            "Keep the failed smoke report attached to downstream readiness as route evidence.",
        ]
    if endpoint_viability == "BLOCK":
        return [
            "Inspect data_import.md and retry provider smoke with explicit symbols before any broad import.",
            "If provider failures persist, switch to guarded offline CSV/TDX intake.",
        ]
    if data_sufficiency == "PASS":
        return [
            "Run real_data_bootstrap and data_audit on the imported cache before strategy research.",
            "Keep source QA, deterministic review, and human approval as separate gates.",
        ]
    actions = [
        "Provider endpoint smoke is usable; next run a broader bounded import into an isolated recent cache.",
        "Then run real_data_bootstrap, data_audit, and first-million pipeline against that cache/report.",
    ]
    if recommended_route:
        actions.append(f"Current provider report recommends route `{recommended_route}` if broad import is not viable.")
    return actions


def _recommended_route(endpoint_viability: ProviderSmokeStatus, network_blocked: bool) -> str:
    if network_blocked:
        return "offline_csv_or_tdx"
    if endpoint_viability == "BLOCK":
        return "retry_provider_or_offline_csv"
    return "provider_broad_import_then_bootstrap"


def _failure_reasons(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    reasons = []
    for item in value:
        if isinstance(item, dict):
            reason = str(item.get("reason") or "").strip()
            if reason:
                reasons.append(reason)
    return reasons


def _network_blocked(reasons: list[str]) -> bool:
    markers = [
        "proxyerror",
        "unable to connect to proxy",
        "remotedisconnected",
        "winerror 10013",
        "connectionerror",
        "failed to establish a new connection",
        "max retries exceeded",
        "temporary failure in name resolution",
        "name resolution",
        "connection refused",
    ]
    text = "\n".join(reasons).lower()
    return any(marker in text for marker in markers)


def _end_lag_days(actual_end: str, requested_end: str) -> int | None:
    if not actual_end or not requested_end:
        return None
    try:
        return (pd.Timestamp(requested_end).date() - pd.Timestamp(actual_end).date()).days
    except (TypeError, ValueError):
        return None


def _actual_coverage_value(
    metadata: dict[str, Any],
    key: str,
    *,
    fallback: str,
    allow_fallback: bool,
) -> str:
    if key in metadata:
        return str(metadata.get(key) or "")
    return fallback if allow_fallback else ""


def _int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
