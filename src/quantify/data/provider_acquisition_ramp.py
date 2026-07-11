"""Research-only staged provider acquisition ramp for A-share daily bars.

This module deliberately reports provider/AKShare acquisition viability only.
It does not validate source QA, provenance, promotion readiness, or trading
readiness, even when every acquisition stage completes.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Literal

from quantify.data.research_importer import (
    ImportFailure,
    ResearchImportReport,
    import_research_data,
    write_import_report,
)
from quantify.data.storage import BarStorage

RampStatus = Literal["PASS", "WATCH", "BLOCK"]
RampImporter = Callable[..., ResearchImportReport]

PROHIBITED_ACTIONS = [
    "Do not treat AKShare/provider ramp PASS as source QA/provenance PASS.",
    "Do not let provider ramp output satisfy or bypass promotion-ready gates.",
    "Do not treat WATCH as PASS; WATCH stages require review, retry, or explicit downstream handling.",
    "Do not use provider ramp artifacts as paper-trading, live-trading, or broker-order permission.",
    "Do not let LLM/operator notes upgrade deterministic data, source QA, or promotion gates.",
]


@dataclass(frozen=True, slots=True)
class ProviderAcquisitionStage:
    index: int
    size: int
    status: RampStatus
    artifacts: dict[str, str]
    message: str
    import_status: str
    requested_symbols: int
    imported_symbols: int
    failed_symbols: int
    bar_rows: int
    calendar_days: int
    network_blocked: bool = False
    failure_stage: str = ""
    recommended_route: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "size": self.size,
            "status": self.status,
            "artifacts": self.artifacts,
            "message": self.message,
            "import_status": self.import_status,
            "requested_symbols": self.requested_symbols,
            "imported_symbols": self.imported_symbols,
            "failed_symbols": self.failed_symbols,
            "bar_rows": self.bar_rows,
            "calendar_days": self.calendar_days,
            "network_blocked": self.network_blocked,
            "failure_stage": self.failure_stage,
            "recommended_route": self.recommended_route,
        }


@dataclass(frozen=True, slots=True)
class ProviderAcquisitionRampReport:
    status: RampStatus
    provider: str
    start: str
    end: str
    cache_path: str
    configured_stage_sizes: list[int]
    stages: list[ProviderAcquisitionStage]
    research_only: bool
    source_qa_provenance_status: str
    promotion_gate_effect: str
    next_actions: list[str] = field(default_factory=list)
    prohibited_actions: list[str] = field(default_factory=lambda: list(PROHIBITED_ACTIONS))

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "provider": self.provider,
            "start": self.start,
            "end": self.end,
            "cache_path": self.cache_path,
            "configured_stage_sizes": self.configured_stage_sizes,
            "executed_stage_count": len(self.stages),
            "stages": [stage.to_dict() for stage in self.stages],
            "research_only": self.research_only,
            "source_qa_provenance_status": self.source_qa_provenance_status,
            "promotion_gate_effect": self.promotion_gate_effect,
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Provider Acquisition Ramp: {self.status}",
            "",
            f"- Provider: `{self.provider}`",
            f"- Period: `{self.start}` to `{self.end}`",
            f"- Cache path: `{self.cache_path}`",
            f"- Configured stage sizes: `{', '.join(str(size) for size in self.configured_stage_sizes)}`",
            f"- Executed stages: {len(self.stages)}",
            f"- Research only: `{self.research_only}`",
            f"- Source QA/provenance status: `{self.source_qa_provenance_status}`",
            f"- Promotion gate effect: `{self.promotion_gate_effect}`",
            "",
            "This is a research-only acquisition smoke/ramp for AKShare/provider data. "
            "It is not source QA/provenance PASS and cannot make promotion-ready gates pass.",
            "",
            "## Stages",
            "",
            "| Stage | Size | Status | Imported | Rows | Artifacts | Message |",
            "|---:|---:|---|---:|---:|---|---|",
        ]
        if self.stages:
            for stage in self.stages:
                artifacts = ", ".join(
                    f"{name}=`{path}`" for name, path in stage.artifacts.items()
                )
                lines.append(
                    "| "
                    f"{stage.index} | {stage.size} | {stage.status} | "
                    f"{stage.imported_symbols}/{stage.requested_symbols} | "
                    f"{stage.bar_rows} | {_escape_md(artifacts or 'none')} | "
                    f"{_escape_md(stage.message)} |"
                )
        else:
            lines.append("| 0 | 0 | BLOCK | 0/0 | 0 | none | No stages executed. |")
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {action}" for action in self.next_actions) if self.next_actions else lines.append("- None.")
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {action}" for action in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def run_provider_acquisition_ramp(
    *,
    cache_path: str | Path,
    start: str,
    end: str,
    stage_sizes: Iterable[int],
    output_dir: str | Path | None = None,
    provider: str = "akshare",
    adjust: str = "qfq",
    index_code: str = "000906",
    include_st: bool = False,
    include_bj: bool = False,
    symbols: Sequence[str] | None = None,
    importer: RampImporter | None = None,
) -> ProviderAcquisitionRampReport:
    """Run bounded provider imports, increasing size until BLOCK or completion."""
    sizes = normalize_stage_sizes(stage_sizes)
    root = Path(output_dir) if output_dir is not None else None
    stage_importer = importer or import_provider_stage
    clean_symbols = parse_symbols(symbols)
    stages: list[ProviderAcquisitionStage] = []

    for index, size in enumerate(sizes, start=1):
        stage_dir = root / f"stage_{index:02d}_size_{size}" if root is not None else None
        try:
            import_report = stage_importer(
                provider=provider,
                cache_path=cache_path,
                start=start,
                end=end,
                size=size,
                adjust=adjust,
                index_code=index_code,
                include_st=include_st,
                include_bj=include_bj,
                symbols=clean_symbols or None,
            )
        except Exception as exc:  # noqa: BLE001 - ramp reports should preserve failures.
            import_report = _blocked_import_report(
                cache_path=cache_path,
                start=start,
                end=end,
                size=size,
                reason=f"{type(exc).__name__}: {exc}",
                failure_stage="provider_import",
            )
        artifacts = _write_stage_artifacts(import_report, stage_dir)
        status = _stage_status(import_report, target_size=size)
        stage = ProviderAcquisitionStage(
            index=index,
            size=size,
            status=status,
            artifacts=artifacts,
            message=_stage_message(import_report, target_size=size, status=status),
            import_status=str(import_report.status).upper(),
            requested_symbols=import_report.requested_symbols,
            imported_symbols=import_report.imported_symbols,
            failed_symbols=import_report.failed_symbols,
            bar_rows=import_report.bar_rows,
            calendar_days=import_report.calendar_days,
            network_blocked=import_report.network_blocked,
            failure_stage=import_report.failure_stage,
            recommended_route=import_report.recommended_route,
        )
        stages.append(stage)
        if stage.status == "BLOCK":
            break

    status = _overall_status(stages)
    return ProviderAcquisitionRampReport(
        status=status,
        provider=provider,
        start=start,
        end=end,
        cache_path=str(cache_path),
        configured_stage_sizes=sizes,
        stages=stages,
        research_only=True,
        source_qa_provenance_status="NOT_EVALUATED",
        promotion_gate_effect="NONE",
        next_actions=_next_actions(status, stages, sizes),
        prohibited_actions=list(PROHIBITED_ACTIONS),
    )


def import_provider_stage(
    *,
    provider: str,
    cache_path: str | Path,
    start: str,
    end: str,
    size: int,
    adjust: str = "qfq",
    index_code: str = "000906",
    include_st: bool = False,
    include_bj: bool = False,
    symbols: Sequence[str] | None = None,
) -> ResearchImportReport:
    """Default provider stage importer backed by the existing research importer."""
    if provider.lower() != "akshare":
        return _blocked_import_report(
            cache_path=cache_path,
            start=start,
            end=end,
            size=size,
            reason=f"Unsupported provider for default ramp importer: {provider}",
            failure_stage="provider_selection",
        )
    storage = BarStorage(cache_path)
    return import_research_data(
        storage,
        start,
        end,
        limit=size,
        adjust=adjust,
        index_code=index_code,
        include_st=include_st,
        include_bj=include_bj,
        symbols=list(symbols) if symbols else None,
    )


def write_provider_acquisition_ramp(
    report: ProviderAcquisitionRampReport,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "provider_acquisition_ramp.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "provider_acquisition_ramp.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def normalize_stage_sizes(stage_sizes: Iterable[int]) -> list[int]:
    sizes: list[int] = []
    for raw in stage_sizes:
        size = int(raw)
        if size <= 0:
            raise ValueError("stage sizes must be positive integers")
        sizes.append(size)
    if not sizes:
        raise ValueError("at least one stage size is required")
    return sizes


def parse_stage_sizes(value: str | Iterable[int]) -> list[int]:
    if isinstance(value, str):
        tokens = value.replace(",", " ").replace(";", " ").split()
        if not tokens:
            raise ValueError("at least one stage size is required")
        try:
            return normalize_stage_sizes(int(token) for token in tokens)
        except ValueError as exc:
            raise ValueError(f"invalid --stage-sizes value {value!r}: {exc}") from exc
    return normalize_stage_sizes(value)


def parse_symbols(value: str | Sequence[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_values = value.replace(",", " ").replace(";", " ").split()
    else:
        raw_values = [str(item) for item in value]
    seen: set[str] = set()
    symbols: list[str] = []
    for raw in raw_values:
        symbol = raw.strip()
        if not symbol or symbol in seen:
            continue
        symbols.append(symbol)
        seen.add(symbol)
    return symbols


def _write_stage_artifacts(
    import_report: ResearchImportReport,
    stage_dir: Path | None,
) -> dict[str, str]:
    if stage_dir is None:
        return {}
    out = write_import_report(import_report, stage_dir)
    return {
        "data_import_json": str(out / "data_import.json"),
        "data_import_md": str(out / "data_import.md"),
    }


def _stage_status(import_report: ResearchImportReport, *, target_size: int) -> RampStatus:
    import_status = _normalize_status(import_report.status)
    if import_status == "BLOCK":
        return "BLOCK"
    if (
        import_report.imported_symbols <= 0
        or import_report.bar_rows <= 0
        or import_report.calendar_days <= 0
    ):
        return "BLOCK"
    if import_status == "WATCH":
        return "WATCH"
    if import_report.failed_symbols > 0:
        return "WATCH"
    if import_report.requested_symbols < target_size:
        return "WATCH"
    if import_report.imported_symbols < import_report.requested_symbols:
        return "WATCH"
    return "PASS"


def _stage_message(
    import_report: ResearchImportReport,
    *,
    target_size: int,
    status: RampStatus,
) -> str:
    if status == "BLOCK":
        reason = _first_failure_reason(import_report) or "no usable provider bars were imported"
        network = " network/proxy" if import_report.network_blocked else ""
        return (
            f"Stage size {target_size} BLOCK:{network} provider acquisition failed "
            f"at `{import_report.failure_stage or 'bars'}`: {reason}"
        )
    if status == "WATCH":
        reasons: list[str] = []
        if _normalize_status(import_report.status) == "WATCH":
            reasons.append("underlying import report is WATCH")
        if import_report.failed_symbols > 0:
            reasons.append(f"{import_report.failed_symbols} symbols failed")
        if import_report.requested_symbols < target_size:
            reasons.append(
                f"target size {target_size} was not fully exercised "
                f"(requested={import_report.requested_symbols})"
            )
        if import_report.imported_symbols < import_report.requested_symbols:
            reasons.append(
                f"only {import_report.imported_symbols}/{import_report.requested_symbols} symbols imported"
            )
        if not reasons:
            reasons.append("provider acquisition needs review")
        return f"Stage size {target_size} WATCH: {'; '.join(reasons)}. WATCH is not PASS."
    return (
        f"Stage size {target_size} PASS: imported {import_report.imported_symbols} symbols "
        f"and {import_report.bar_rows} rows. This is acquisition evidence only, "
        "not source QA/provenance PASS."
    )


def _overall_status(stages: list[ProviderAcquisitionStage]) -> RampStatus:
    if not stages or any(stage.status == "BLOCK" for stage in stages):
        return "BLOCK"
    if any(stage.status == "WATCH" for stage in stages):
        return "WATCH"
    return "PASS"


def _next_actions(
    status: RampStatus,
    stages: list[ProviderAcquisitionStage],
    configured_stage_sizes: list[int],
) -> list[str]:
    if status == "BLOCK":
        blocked = next((stage for stage in stages if stage.status == "BLOCK"), None)
        blocked_stage = f"stage {blocked.index} size {blocked.size}" if blocked else "the first stage"
        skipped = configured_stage_sizes[len(stages) :]
        actions = [
            f"Stop the provider ramp at {blocked_stage}; inspect that stage's data_import.md/json.",
            "Fix provider/network failures or switch to guarded offline CSV/TDX intake before retrying.",
            "Keep source QA/provenance and promotion-ready gates blocked until their own evidence passes.",
        ]
        if skipped:
            actions.append(f"Do not run skipped stage sizes yet: {', '.join(str(size) for size in skipped)}.")
        return actions
    if status == "WATCH":
        return [
            "Review WATCH stages and rerun them; do not relabel a WATCH ramp as PASS.",
            "Broaden acquisition only after partial imports, underfilled stages, and failed symbols are resolved.",
            "Run source QA/provenance, bootstrap, audit, and promotion gates separately after acquisition.",
        ]
    return [
        "Treat ramp PASS only as bounded provider acquisition viability evidence.",
        "Run source QA/provenance review, real_data_bootstrap, data_audit, and promotion gates separately.",
        "Retain all stage artifacts as research-only evidence; do not connect this workflow to broker orders.",
    ]


def _blocked_import_report(
    *,
    cache_path: str | Path,
    start: str,
    end: str,
    size: int,
    reason: str,
    failure_stage: str,
) -> ResearchImportReport:
    network_blocked = _looks_like_network_block(reason)
    return ResearchImportReport(
        status="BLOCK",
        start=start,
        end=end,
        cache_path=str(cache_path),
        requested_symbols=size,
        imported_symbols=0,
        failed_symbols=size,
        bar_rows=0,
        calendar_days=0,
        failures=[ImportFailure("provider_ramp", reason)],
        notes=["Provider acquisition ramp stage failed; no demo data was generated."],
        metadata={
            "actual_bar_start": "",
            "actual_bar_end": "",
            "actual_bar_symbol_count": 0,
            "failure_stage": failure_stage,
            "network_blocked": network_blocked,
            "requested_start": start,
            "requested_end": end,
        },
        failure_stage=failure_stage,
        network_blocked=network_blocked,
        recommended_route="offline_csv_or_tdx" if network_blocked else "retry_provider_or_offline_csv",
        next_actions=[
            "Inspect provider acquisition failure before retrying the ramp.",
            "Use guarded offline CSV/TDX intake if provider access remains unavailable.",
        ],
    )


def _normalize_status(value: object) -> RampStatus:
    status = str(value or "").upper()
    if status in {"PASS", "WATCH", "BLOCK"}:
        return status  # type: ignore[return-value]
    return "WATCH"


def _first_failure_reason(import_report: ResearchImportReport) -> str:
    if not import_report.failures:
        return ""
    return import_report.failures[0].reason


def _looks_like_network_block(reason: str) -> bool:
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
    text = reason.lower()
    return any(marker in text for marker in markers)


def _escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
