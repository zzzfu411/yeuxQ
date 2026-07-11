"""Preflight an OHLCV-only research experiment data package.

The report answers a narrow operational question: whether the current recent
A-share CSV/source/market-context evidence is enough to launch the first
OHLCV-only candidate research experiment. It never approves paper trading,
live trading, broker connectivity, or profitability claims.
"""
from __future__ import annotations

from dataclasses import dataclass
import csv
import json
from pathlib import Path
from typing import Any, Literal

from quantify.data.csv_intake_preview import CSVIntakePreview, build_csv_intake_preview
from quantify.data.csv_research_importer import _normalize_bars, _read_csv
from quantify.data.gap_action_plan import DataGapActionPlan, build_data_gap_action_plan
from quantify.data.offline_package import (
    OfflineDataPackageReport,
    build_offline_data_package_report,
    format_source_provenance,
)
from quantify.data.real_data_handoff import (
    RealDataHandoffChecklist,
    build_real_data_handoff_checklist,
)
from quantify.market import (
    MarketContextReadiness,
    build_market_context_readiness_from_payload,
    build_market_context_readiness_from_report,
)

ExperimentPackageDecision = Literal["PASS", "WATCH", "BLOCK"]

CANDIDATE = "price_volume_defensive"
EVIDENCE_SCOPE = "OHLCV_ONLY"

PROHIBITED_ACTIONS = [
    "Do not treat this package preflight as a buy/sell signal, expected-return estimate, or profitability claim.",
    "Do not run candidate research while this preflight is BLOCK.",
    "Do not use OHLCV-only evidence for valuation, quality, accounting, or PIT-fundamental claims.",
    "Do not promote any output from this package to paper or micro-live without downstream deterministic gates.",
    "Do not connect this workflow to real broker order submission.",
    "Do not let LLM output override this deterministic preflight decision.",
]


@dataclass(frozen=True, slots=True)
class OhlcvExperimentPackageCheck:
    name: str
    status: ExperimentPackageDecision
    artifact: str
    message: str
    next_action: str
    decision_relevant: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "artifact": self.artifact,
            "message": self.message,
            "next_action": self.next_action,
            "decision_relevant": self.decision_relevant,
        }


@dataclass(frozen=True, slots=True)
class OhlcvExperimentPackagePreflight:
    decision: ExperimentPackageDecision
    candidate: str
    evidence_scope: str
    allowed_stage: str
    launch_research_allowed: bool
    data_dir: str
    report_dir: str
    config_path: str
    as_of: str | None
    min_symbols: int
    min_trading_days: int
    bars: dict[str, Any]
    source_qa: dict[str, Any]
    market_context: dict[str, Any]
    evidence_path: dict[str, Any]
    recommended_files: list[dict[str, Any]]
    checks: list[OhlcvExperimentPackageCheck]
    blockers: list[str]
    watch_items: list[str]
    missing_evidence: list[str]
    next_actions: list[str]
    next_commands: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "candidate": self.candidate,
            "evidence_scope": self.evidence_scope,
            "allowed_stage": self.allowed_stage,
            "launch_research_allowed": self.launch_research_allowed,
            "data_dir": self.data_dir,
            "report_dir": self.report_dir,
            "config_path": self.config_path,
            "as_of": self.as_of,
            "min_symbols": self.min_symbols,
            "min_trading_days": self.min_trading_days,
            "bars": self.bars,
            "source_qa": self.source_qa,
            "market_context": self.market_context,
            "evidence_path": self.evidence_path,
            "recommended_files": self.recommended_files,
            "checks": [check.to_dict() for check in self.checks],
            "blockers": self.blockers,
            "watch_items": self.watch_items,
            "missing_evidence": self.missing_evidence,
            "next_actions": self.next_actions,
            "next_commands": self.next_commands,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# OHLCV Experiment Package: {self.decision}",
            "",
            f"- Candidate: `{self.candidate}`",
            f"- Evidence scope: `{self.evidence_scope}`",
            f"- Allowed stage: `{self.allowed_stage}`",
            f"- Launch research allowed: `{self.launch_research_allowed}`",
            f"- Data directory: `{self.data_dir}`",
            f"- Report directory: `{self.report_dir}`",
            f"- Config: `{self.config_path}`",
            f"- As of: `{self.as_of or 'unspecified'}`",
            f"- Minimum symbols: {self.min_symbols}",
            f"- Minimum trading days: {self.min_trading_days}",
            "",
            "This preflight only checks whether an OHLCV-only research experiment can start. It is not a strategy signal, paper-trading approval, or live-trading permission.",
            "",
            "## Bars Coverage",
            "",
            "| state | preview | rows | normalized | symbols | trading days | period | sha256 |",
            "| --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
        ]
        period = f"{self.bars.get('start', '') or '-'} to {self.bars.get('end', '') or '-'}"
        lines.append(
            "| `{state}` | `{preview}` | {rows} | {normalized} | {symbols} | {days} | `{period}` | `{sha}` |".format(
                state=self.bars.get("state", "unknown"),
                preview=self.bars.get("preview_status", "UNKNOWN"),
                rows=self.bars.get("raw_rows", 0),
                normalized=self.bars.get("normalized_rows", 0),
                symbols=self.bars.get("symbol_count", 0),
                days=self.bars.get("trading_day_count", 0),
                period=period,
                sha=str(self.bars.get("sha256", ""))[:12] or "-",
            )
        )
        lines.extend(
            [
                "",
                "## Source QA",
                "",
                f"- Answers status: `{self.source_qa.get('answers_status', 'UNKNOWN')}`",
                f"- Review status: `{self.source_qa.get('review_status', 'UNKNOWN')}`",
                f"- Evidence manifest status: `{self.source_qa.get('evidence_manifest_status', 'UNKNOWN')}`",
                f"- Provenance: {self.source_qa.get('provenance', 'unspecified')}",
                "",
                "## Market Context",
                "",
                f"- Source: `{self.market_context.get('source', 'missing')}`",
                f"- Decision: `{self.market_context.get('decision', 'UNKNOWN')}`",
                f"- Label: `{self.market_context.get('label', 'unknown')}`",
                f"- Artifact: `{self.market_context.get('artifact', '') or 'missing'}`",
                f"- Note: {self.market_context.get('note', '')}",
                "",
                "## Checks",
                "",
                "| check | status | relevant | artifact | message | next action |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for check in self.checks:
            lines.append(
                f"| `{check.name}` | `{check.status}` | `{check.decision_relevant}` | "
                f"`{check.artifact}` | {_cell(check.message)} | {_cell(check.next_action)} |"
            )
        lines.extend(["", "## Recommended Files"])
        if self.recommended_files:
            lines.extend(
                f"- `{item.get('role')}`: `{item.get('state')}` ({item.get('message')})"
                for item in self.recommended_files
            )
        else:
            lines.append("- None.")
        lines.extend(["", "## Blockers"])
        lines.extend(f"- {item}" for item in self.blockers) if self.blockers else lines.append("- None.")
        lines.extend(["", "## Watch Items"])
        lines.extend(f"- {item}" for item in self.watch_items) if self.watch_items else lines.append("- None.")
        lines.extend(["", "## Missing Evidence"])
        lines.extend(f"- {item}" for item in self.missing_evidence) if self.missing_evidence else lines.append("- None.")
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Next Commands"])
        for command in self.next_commands:
            lines.extend(["", "```powershell", command, "```"])
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_ohlcv_experiment_package_preflight(
    *,
    data_dir: str | Path = "data_exports",
    report_dir: str | Path = "results/first_million",
    config_path: str | Path = "config/research_recent.yaml",
    source_qa_answers: str | Path | None = None,
    source_qa_evidence_manifest: str | Path | None = None,
    require_source_qa_evidence_manifest: bool = False,
    min_symbols: int = 300,
    min_trading_days: int = 240,
    as_of: str | None = None,
    encoding: str = "utf-8-sig",
    csv_preview: CSVIntakePreview | None = None,
    data_gap_plan: DataGapActionPlan | None = None,
    offline_package: OfflineDataPackageReport | None = None,
    real_data_handoff: RealDataHandoffChecklist | None = None,
    market_context_readiness: MarketContextReadiness | None = None,
) -> OhlcvExperimentPackagePreflight:
    """Build the deterministic OHLCV-only package preflight."""
    data_root = Path(data_dir)
    report_root = Path(report_dir)
    answers_path = Path(source_qa_answers) if source_qa_answers else data_root / "data_source_qa_answers.json"
    evidence_manifest_path = (
        Path(source_qa_evidence_manifest)
        if source_qa_evidence_manifest
        else data_root / "source_qa_evidence_manifest.json"
    )
    review_evidence_manifest_path = (
        evidence_manifest_path
        if (
            source_qa_evidence_manifest is not None
            or require_source_qa_evidence_manifest
            or evidence_manifest_path.exists()
        )
        else None
    )
    preview = csv_preview or build_csv_intake_preview(data_dir=data_root, encoding=encoding)
    gap = data_gap_plan or build_data_gap_action_plan(
        data_dir=data_root,
        config_path=config_path,
        source_qa_answers=answers_path,
        min_symbols=min_symbols,
        as_of=as_of,
        encoding=encoding,
    )
    package = offline_package or build_offline_data_package_report(
        data_dir=data_root,
        config_path=config_path,
        source_qa_answers=answers_path,
        source_qa_evidence_manifest=review_evidence_manifest_path,
        require_source_qa_evidence_manifest=require_source_qa_evidence_manifest,
        min_symbols=min_symbols,
        as_of=as_of,
        encoding=encoding,
    )
    handoff = real_data_handoff or build_real_data_handoff_checklist(
        data_dir=data_root,
        config_path=config_path,
        source_qa_answers=answers_path,
        source_qa_evidence_manifest=review_evidence_manifest_path,
        require_source_qa_evidence_manifest=require_source_qa_evidence_manifest,
        min_symbols=min_symbols,
        min_trading_days=min_trading_days,
        as_of=as_of,
        encoding=encoding,
        data_gap_plan=gap,
        offline_package=package,
    )
    market = market_context_readiness or build_market_context_readiness_from_report(
        report_root,
        as_of=as_of,
    )
    bars = _bars_summary(data_root, preview, package, handoff, encoding=encoding)
    source_qa = _source_qa_summary(package, answers_path, review_evidence_manifest_path)
    market_summary = _market_summary(market)
    evidence_path = _ohlcv_path(handoff)
    recommended_files = _recommended_file_summary(handoff)
    checks = [
        _candidate_check(),
        _bars_check(bars, min_symbols=min_symbols, min_trading_days=min_trading_days),
        *_source_qa_checks(source_qa),
        _evidence_path_check(evidence_path),
        _recommended_files_check(recommended_files),
        _market_check(market_summary),
        _pit_boundary_check(handoff),
    ]
    decision_checks = [check for check in checks if check.decision_relevant]
    blockers = _messages(decision_checks, "BLOCK")
    watch_items = _messages(decision_checks, "WATCH")
    decision: ExperimentPackageDecision = "BLOCK" if blockers else "WATCH" if watch_items else "PASS"
    return OhlcvExperimentPackagePreflight(
        decision=decision,
        candidate=CANDIDATE,
        evidence_scope=EVIDENCE_SCOPE,
        allowed_stage="none" if decision == "BLOCK" else "guarded_research_only",
        launch_research_allowed=decision != "BLOCK",
        data_dir=str(data_root),
        report_dir=str(report_root),
        config_path=str(config_path),
        as_of=as_of,
        min_symbols=min_symbols,
        min_trading_days=min_trading_days,
        bars=bars,
        source_qa=source_qa,
        market_context=market_summary,
        evidence_path=evidence_path,
        recommended_files=recommended_files,
        checks=checks,
        blockers=blockers,
        watch_items=watch_items,
        missing_evidence=_missing_evidence(checks),
        next_actions=_next_actions(decision, blockers, watch_items),
        next_commands=_next_commands(
            decision=decision,
            data_dir=data_root,
            report_dir=report_root,
            config_path=config_path,
            answers_path=answers_path,
            evidence_manifest_path=evidence_manifest_path,
            require_source_qa_evidence_manifest=require_source_qa_evidence_manifest,
            min_symbols=min_symbols,
            min_trading_days=min_trading_days,
            as_of=as_of,
        ),
        prohibited_actions=PROHIBITED_ACTIONS,
    )


def build_ohlcv_experiment_package_preflight_from_payload(
    *,
    data_dir: str | Path = "data_exports",
    report_dir: str | Path = "results/first_million",
    config_path: str | Path = "config/research_recent.yaml",
    source_qa_answers: str | Path | None = None,
    source_qa_evidence_manifest: str | Path | None = None,
    require_source_qa_evidence_manifest: bool = False,
    min_symbols: int = 300,
    min_trading_days: int = 240,
    as_of: str | None = None,
    encoding: str = "utf-8-sig",
    market_context: dict[str, Any] | None = None,
) -> OhlcvExperimentPackagePreflight:
    """Build a preflight with an explicit market context payload."""
    market = (
        build_market_context_readiness_from_payload(market_context, as_of=as_of)
        if market_context is not None
        else None
    )
    return build_ohlcv_experiment_package_preflight(
        data_dir=data_dir,
        report_dir=report_dir,
        config_path=config_path,
        source_qa_answers=source_qa_answers,
        source_qa_evidence_manifest=source_qa_evidence_manifest,
        require_source_qa_evidence_manifest=require_source_qa_evidence_manifest,
        min_symbols=min_symbols,
        min_trading_days=min_trading_days,
        as_of=as_of,
        encoding=encoding,
        market_context_readiness=market,
    )


def write_ohlcv_experiment_package_preflight(
    preflight: OhlcvExperimentPackagePreflight,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "ohlcv_experiment_package.json").write_text(
        json.dumps(preflight.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "ohlcv_experiment_package.md").write_text(preflight.to_markdown(), encoding="utf-8")
    _write_checks_csv(preflight, root / "ohlcv_experiment_package.csv")
    return root


def _write_checks_csv(preflight: OhlcvExperimentPackagePreflight, path: Path) -> None:
    fieldnames = [
        "name",
        "status",
        "decision_relevant",
        "artifact",
        "message",
        "next_action",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for check in preflight.checks:
            writer.writerow(check.to_dict())


def _bars_summary(
    root: Path,
    preview: CSVIntakePreview,
    package: OfflineDataPackageReport,
    handoff: RealDataHandoffChecklist,
    *,
    encoding: str,
) -> dict[str, Any]:
    preview_item = next((item for item in preview.items if item.role == "bars"), None)
    package_file = _package_file(package, "bars")
    handoff_file = _handoff_file(handoff, "bars")
    profile = _read_bars_profile(root / "bars.csv", encoding=encoding)
    return {
        "path": str(root / "bars.csv"),
        "state": str((handoff_file or {}).get("state") or "missing"),
        "preview_status": preview_item.status if preview_item else "MISSING",
        "preview_message": preview_item.message if preview_item else "bars.csv is missing.",
        "missing_columns": preview_item.missing_columns if preview_item else ["symbol", "date", "open", "high", "low", "close", "volume"],
        "raw_rows": _first_int(profile.get("raw_rows"), preview_item.raw_rows if preview_item else 0, package_file.get("row_count")),
        "normalized_rows": _first_int(
            profile.get("normalized_rows"),
            preview_item.normalized_rows if preview_item else 0,
            package_file.get("normalized_row_count"),
            package_file.get("normalized_rows"),
        ),
        "symbol_count": _first_int(
            profile.get("symbol_count"),
            preview_item.symbol_count if preview_item else 0,
            package_file.get("symbol_count"),
        ),
        "trading_day_count": _first_int(profile.get("trading_day_count"), 0),
        "start": str(profile.get("start") or (preview_item.start if preview_item else "") or package_file.get("start", "")),
        "end": str(profile.get("end") or (preview_item.end if preview_item else "") or package_file.get("end", "")),
        "sha256": str(package_file.get("sha256", "")),
    }


def _read_bars_profile(path: Path, *, encoding: str) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = _read_csv(path, encoding)
        bars = _normalize_bars(raw)
    except Exception:  # noqa: BLE001 - details are already in csv_intake_preview/import doctor.
        return {}
    if bars.empty:
        return {"raw_rows": len(raw), "normalized_rows": 0, "symbol_count": 0, "trading_day_count": 0}
    return {
        "raw_rows": len(raw),
        "normalized_rows": len(bars),
        "symbol_count": int(bars["symbol"].nunique()),
        "trading_day_count": int(bars["date"].nunique()),
        "start": str(bars["date"].min()),
        "end": str(bars["date"].max()),
    }


def _source_qa_summary(
    package: OfflineDataPackageReport,
    answers_path: Path,
    evidence_manifest_path: Path | None,
) -> dict[str, Any]:
    items = {item.name: item for item in package.items}
    answers = items.get("source_qa_answers")
    review = items.get("source_qa_review")
    manifest = items.get("source_qa_evidence_manifest")
    summary = package.source_metadata_summary
    return {
        "answers_path": str(answers_path),
        "answers_status": answers.status if answers else "BLOCK",
        "answers_message": answers.message if answers else "Source QA answers were not checked.",
        "review_status": review.status if review else "BLOCK",
        "review_message": review.message if review else "Source QA review was not checked.",
        "evidence_manifest_path": str(evidence_manifest_path or ""),
        "evidence_manifest_status": manifest.status if manifest else "PASS",
        "evidence_manifest_message": manifest.message if manifest else "Source QA evidence manifest was not required.",
        "provenance": format_source_provenance(summary) or "unspecified",
        "metadata": summary,
    }


def _market_summary(market: MarketContextReadiness) -> dict[str, Any]:
    payload = market.to_dict()
    return {
        "decision": market.decision,
        "source": market.source,
        "label": market.label,
        "artifact": market.artifact,
        "artifact_status": market.artifact_status,
        "artifact_as_of": market.artifact_as_of,
        "target_as_of": market.target_as_of,
        "blockers": payload.get("blockers", []),
        "watch_items": payload.get("watch_items", []),
        "note": market.note,
    }


def _ohlcv_path(handoff: RealDataHandoffChecklist) -> dict[str, Any]:
    paths = handoff.to_dict().get("evidence_paths", [])
    for item in paths:
        if isinstance(item, dict) and item.get("name") == "ohlcv_minimum_path":
            return item
    return {
        "name": "ohlcv_minimum_path",
        "status": "BLOCK",
        "blocked_by": ["ohlcv_minimum_path is missing from real_data_handoff_checklist."],
        "next_action": "Regenerate real_data_handoff_checklist.json.",
        "required_evidence": ["Audited OHLCV bars and source QA evidence."],
    }


def _recommended_file_summary(handoff: RealDataHandoffChecklist) -> list[dict[str, Any]]:
    roles = {"stock_info", "calendar", "suspensions"}
    rows = []
    for item in handoff.to_dict().get("file_requirements", []) or []:
        if not isinstance(item, dict) or item.get("role") not in roles:
            continue
        state = str(item.get("state") or "missing")
        preview_status = str(item.get("preview_status") or "UNKNOWN")
        if state == "present" and preview_status == "PASS":
            continue
        rows.append(
            {
                "role": str(item.get("role")),
                "file_name": str(item.get("file_name")),
                "state": state,
                "preview_status": preview_status,
                "message": str(item.get("preview_message") or item.get("note") or "Recommended audit file requires review."),
                "path": str(item.get("path") or ""),
            }
        )
    return rows


def _candidate_check() -> OhlcvExperimentPackageCheck:
    return OhlcvExperimentPackageCheck(
        "candidate_scope",
        "PASS",
        "candidate_experiment_queue.json",
        f"{CANDIDATE} is the only candidate covered by this OHLCV-only package preflight.",
        "Keep PIT-fundamental candidates parked until their own evidence path passes.",
    )


def _bars_check(
    bars: dict[str, Any],
    *,
    min_symbols: int,
    min_trading_days: int,
) -> OhlcvExperimentPackageCheck:
    if bars.get("state") in {"missing", "template_sample_rows"}:
        return OhlcvExperimentPackageCheck(
            "bars_csv",
            "BLOCK",
            str(bars.get("path") or "bars.csv"),
            f"bars.csv state is {bars.get('state')}; real non-template OHLCV rows are required.",
            "Replace bars.csv with recent real A-share daily OHLCV exports.",
        )
    if bars.get("preview_status") == "BLOCK":
        missing = ", ".join(str(item) for item in bars.get("missing_columns", []) or [])
        return OhlcvExperimentPackageCheck(
            "bars_csv",
            "BLOCK",
            str(bars.get("path") or "bars.csv"),
            f"bars.csv preview is BLOCK: {bars.get('preview_message')} Missing columns={missing}.",
            "Fix bars.csv column mapping and rerun the preflight.",
        )
    if int(bars.get("normalized_rows", 0) or 0) <= 0:
        return OhlcvExperimentPackageCheck(
            "bars_csv",
            "BLOCK",
            str(bars.get("path") or "bars.csv"),
            "bars.csv has no normalized OHLCV rows.",
            "Replace bars.csv with usable daily OHLCV rows.",
        )
    symbol_count = int(bars.get("symbol_count", 0) or 0)
    trading_day_count = int(bars.get("trading_day_count", 0) or 0)
    coverage_gaps = []
    if symbol_count < min_symbols:
        coverage_gaps.append(f"symbols={symbol_count}/{min_symbols}")
    if trading_day_count < min_trading_days:
        coverage_gaps.append(f"trading_days={trading_day_count}/{min_trading_days}")
    if coverage_gaps:
        return OhlcvExperimentPackageCheck(
            "bars_coverage",
            "BLOCK",
            str(bars.get("path") or "bars.csv"),
            (
                "bars.csv coverage is below the OHLCV research minimum: "
                + ", ".join(coverage_gaps)
                + ". Small packages are schema/import smoke evidence only, not candidate research evidence."
            ),
            "Supply a recent broad A-share daily OHLCV export that meets the configured symbol and trading-day minimums.",
        )
    if bars.get("preview_status") == "WATCH":
        return OhlcvExperimentPackageCheck(
            "bars_csv",
            "WATCH",
            str(bars.get("path") or "bars.csv"),
            str(bars.get("preview_message") or "bars.csv has preview warnings."),
            "Keep WATCH evidence with the research launch packet.",
        )
    return OhlcvExperimentPackageCheck(
        "bars_csv",
        "PASS",
        str(bars.get("path") or "bars.csv"),
        (
            f"bars.csv is non-template and normalized; rows={bars.get('normalized_rows', 0)}, "
            f"symbols={bars.get('symbol_count', 0)}, trading_days={bars.get('trading_day_count', 0)}."
        ),
        "Continue to source QA, market context, and guarded offline intake.",
    )


def _source_qa_checks(source_qa: dict[str, Any]) -> list[OhlcvExperimentPackageCheck]:
    checks = []
    checks.append(
        _status_check(
            name="source_qa_answers",
            status=str(source_qa.get("answers_status") or "BLOCK"),
            artifact=str(source_qa.get("answers_path") or "data_source_qa_answers.json"),
            message=str(source_qa.get("answers_message") or "Source QA answers require review."),
            next_action="Fill data_source_qa_answers.json from real vendor/export evidence.",
        )
    )
    checks.append(
        _status_check(
            name="source_qa_review",
            status=str(source_qa.get("review_status") or "BLOCK"),
            artifact=str(source_qa.get("answers_path") or "data_source_qa_answers.json"),
            message=str(source_qa.get("review_message") or "Source QA review requires review."),
            next_action="Resolve deterministic source QA findings before OHLCV research launch.",
        )
    )
    checks.append(
        _status_check(
            name="source_qa_evidence_manifest",
            status=str(source_qa.get("evidence_manifest_status") or "PASS"),
            artifact=str(source_qa.get("evidence_manifest_path") or "source_qa_evidence_manifest.json"),
            message=str(source_qa.get("evidence_manifest_message") or "Source QA evidence manifest passes or is not required."),
            next_action="Attach retained source evidence and regenerate source_qa_evidence_manifest.json if strict mode is required.",
        )
    )
    return checks


def _status_check(
    *,
    name: str,
    status: str,
    artifact: str,
    message: str,
    next_action: str,
) -> OhlcvExperimentPackageCheck:
    normalized = _normalize_status(status)
    if normalized == "PASS":
        return OhlcvExperimentPackageCheck(name, "PASS", artifact, message, "Keep evidence immutable with this data batch.")
    if normalized == "WATCH":
        return OhlcvExperimentPackageCheck(name, "WATCH", artifact, message, next_action)
    return OhlcvExperimentPackageCheck(name, "BLOCK", artifact, message, next_action)


def _evidence_path_check(path: dict[str, Any]) -> OhlcvExperimentPackageCheck:
    status = _normalize_status(path.get("status"))
    if status == "PASS":
        return OhlcvExperimentPackageCheck(
            "ohlcv_minimum_path",
            "PASS",
            "real_data_handoff_checklist.json",
            "OHLCV minimum evidence path passes for price_volume_defensive.",
            "Run guarded offline intake before candidate experiment launch.",
        )
    blocked_by = [str(item) for item in path.get("blocked_by", []) or []]
    message = blocked_by[0] if blocked_by else str(path.get("next_action") or "OHLCV minimum path requires review.")
    return OhlcvExperimentPackageCheck(
        "ohlcv_minimum_path",
        status,
        "real_data_handoff_checklist.json",
        message,
        str(path.get("next_action") or "Resolve OHLCV minimum path evidence."),
    )


def _recommended_files_check(files: list[dict[str, Any]]) -> OhlcvExperimentPackageCheck:
    if not files:
        return OhlcvExperimentPackageCheck(
            "ohlcv_audit_files",
            "PASS",
            "real_data_handoff_checklist.json",
            "stock_info.csv, calendar.csv, and suspensions.csv are present and preview clean for OHLCV audit depth.",
            "Continue with guarded offline intake.",
        )
    labels = ", ".join(f"{item.get('file_name')}={item.get('state')}/{item.get('preview_status')}" for item in files)
    return OhlcvExperimentPackageCheck(
        "ohlcv_audit_files",
        "WATCH",
        "real_data_handoff_checklist.json",
        f"Recommended OHLCV audit files require review: {labels}.",
        "Add or fix stock_info.csv, calendar.csv, and suspensions.csv for stronger execution/data audit evidence.",
    )


def _market_check(market: dict[str, Any]) -> OhlcvExperimentPackageCheck:
    status = _normalize_status(market.get("decision"))
    if status == "PASS":
        return OhlcvExperimentPackageCheck(
            "market_context",
            "PASS",
            str(market.get("artifact") or "market_regime.json"),
            f"Market context passes via {market.get('source')} ({market.get('label')}).",
            "Continue with research-only candidate launch after data intake gates pass.",
        )
    messages = [str(item) for item in market.get("blockers", []) or market.get("watch_items", []) or []]
    message = messages[0] if messages else "Market context requires review."
    return OhlcvExperimentPackageCheck(
        "market_context",
        status,
        str(market.get("artifact") or "market_regime.json"),
        message,
        "Generate cache-derived market_regime.json or attach a reviewed market_context_snapshot.json.",
    )


def _pit_boundary_check(handoff: RealDataHandoffChecklist) -> OhlcvExperimentPackageCheck:
    paths = {
        str(item.get("name")): item
        for item in handoff.to_dict().get("evidence_paths", []) or []
        if isinstance(item, dict)
    }
    pit = paths.get("pit_fundamental_candidate_path", {})
    status = str(pit.get("status") or "NOT_REVIEWED")
    return OhlcvExperimentPackageCheck(
        "pit_candidate_boundary",
        "PASS",
        "real_data_handoff_checklist.json",
        f"PIT-fundamental path is `{status}` and remains outside this OHLCV-only preflight.",
        "Do not run value, quality, or PIT-fundamental candidates from this package decision.",
        decision_relevant=False,
    )


def _messages(
    checks: list[OhlcvExperimentPackageCheck],
    status: ExperimentPackageDecision,
) -> list[str]:
    return _dedupe(f"{check.name}: {check.message}" for check in checks if check.status == status)


def _missing_evidence(checks: list[OhlcvExperimentPackageCheck]) -> list[str]:
    return _dedupe(
        f"{check.name}: {check.next_action}"
        for check in checks
        if check.decision_relevant and check.status in {"BLOCK", "WATCH"}
    )


def _next_actions(
    decision: ExperimentPackageDecision,
    blockers: list[str],
    watch_items: list[str],
) -> list[str]:
    if decision == "BLOCK":
        actions = []
        if any("bars_csv" in item or "ohlcv_minimum_path" in item for item in blockers):
            actions.append("Replace bars.csv with real recent A-share OHLCV rows and rerun the package preflight.")
        if any("source_qa" in item for item in blockers):
            actions.append("Fill source QA answers and retained evidence from real vendor/export records.")
        if any("market_context" in item for item in blockers):
            actions.append(
                "Generate market_regime.json from audited cache data, or run market_index_discovery before attaching a reviewed market_context_snapshot.json."
            )
        actions.append("Keep all candidate research, paper planning, and live actions blocked until this preflight is no longer BLOCK.")
        return _dedupe(actions)
    actions = [
        f"Launch only the {CANDIDATE} OHLCV-only research path after guarded offline intake and candidate readiness confirm it.",
        "Keep PIT-fundamental candidates parked until fundamentals and PIT provenance pass their own gate.",
        "Keep paper/live/micro-live stages prohibited; this preflight only opens research work.",
    ]
    if decision == "WATCH":
        actions.insert(0, "Carry WATCH evidence into the experiment report and rerun the preflight after closing audit gaps.")
    if watch_items:
        actions.append("Review WATCH items before interpreting any backtest or factor diagnostic output.")
    return _dedupe(actions)


def _next_commands(
    *,
    decision: ExperimentPackageDecision,
    data_dir: Path,
    report_dir: Path,
    config_path: str | Path,
    answers_path: Path,
    evidence_manifest_path: Path,
    require_source_qa_evidence_manifest: bool,
    min_symbols: int,
    min_trading_days: int,
    as_of: str | None,
) -> list[str]:
    as_of_arg = f" --as-of {as_of}" if as_of else ""
    manifest_arg = f" --source-qa-evidence-manifest {evidence_manifest_path}"
    require_arg = " --require-source-qa-evidence-manifest" if require_source_qa_evidence_manifest else ""
    review_command = (
        ".\\.venv\\Scripts\\python.exe examples\\run_ohlcv_experiment_package.py "
        f"--data-dir {data_dir} --report-dir {report_dir} --config {config_path} "
        f"--source-qa-answers {answers_path}{manifest_arg}{require_arg} "
        f"--min-symbols {min_symbols} --min-trading-days {min_trading_days}{as_of_arg}"
    )
    if decision == "BLOCK":
        return [
            review_command,
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_operator_packet.py "
                f"--data-dir {data_dir} --report-dir {report_dir}{as_of_arg}"
            ),
        ]
    return [
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_offline_data_intake.py "
            f"--data-dir {data_dir} --config {config_path} --output-dir {report_dir / 'offline_intake'} "
            f"--source-qa-answers {answers_path} --min-symbols {min_symbols} "
            f"--min-trading-days {min_trading_days}{as_of_arg}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_first_million_pipeline.py "
            f"--config {config_path} --data-dir {data_dir} --output-dir {report_dir} "
            f"--source-qa-answers {answers_path} --min-symbols {min_symbols} "
            f"--min-trading-days {min_trading_days}{as_of_arg}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_candidate_experiment_launch.py "
            f"--report-dir {report_dir} --config {config_path} --candidate {CANDIDATE}{as_of_arg}"
        ),
    ]


def _package_file(package: OfflineDataPackageReport, role: str) -> dict[str, Any]:
    return next((item for item in package.csv_files if item.get("role") == role), {})


def _handoff_file(handoff: RealDataHandoffChecklist, role: str) -> dict[str, Any]:
    return next(
        (item for item in handoff.to_dict().get("file_requirements", []) if item.get("role") == role),
        {},
    )


def _first_int(*values: object) -> int:
    for value in values:
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _normalize_status(value: object) -> ExperimentPackageDecision:
    text = str(value or "").upper()
    if text == "PASS":
        return "PASS"
    if text == "WATCH":
        return "WATCH"
    return "BLOCK"


def _dedupe(values: Any) -> list[str]:
    seen: set[str] = set()
    result = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
