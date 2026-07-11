"""Close the raw-OHLCV discovery loop into guarded offline intake.

The closeout is deliberately conservative: it checks deterministic source QA
before it allows raw broker/vendor bars to be normalized or imported. It never
approves strategy research, paper promotion, or broker order submission.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from quantify.data.offline_intake import OfflineDataIntakeReport, run_offline_data_intake
from quantify.data.raw_bars_discovery import (
    RawBarsDiscoveryReport,
    build_raw_bars_discovery_report,
    write_raw_bars_discovery_report,
)
from quantify.data.source_qa import (
    build_data_source_qa,
    build_data_source_qa_review,
    write_data_source_qa,
    write_data_source_qa_review,
)
from quantify.data.storage import BarStorage
from quantify.utils.config import load_config

CloseoutDecision = Literal["PASS", "WATCH", "BLOCK"]

PROHIBITED_ACTIONS = [
    "Do not normalize raw OHLCV before deterministic source QA is PASS.",
    "Do not treat closeout PASS/WATCH as strategy profitability evidence.",
    "Do not use this report to upgrade candidate, paper, micro-live, or approval gates.",
    "Do not use OHLCV-only evidence for PIT fundamental, valuation, or quality claims.",
    "Do not connect this workflow to real broker order submission.",
]


@dataclass(frozen=True, slots=True)
class OhlcvIntakeCloseoutStep:
    name: str
    status: CloseoutDecision
    artifact: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "artifact": self.artifact,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class OhlcvIntakeCloseout:
    decision: CloseoutDecision
    as_of: str | None
    data_dir: str
    report_dir: str
    config_path: str
    raw_bars_csv: str
    raw_sha256: str
    source_qa_status: str
    raw_discovery_status: str
    offline_intake_status: str
    cache_path: str
    csv_dataset_fingerprint: str
    normalized_row_count: int
    symbol_count: int
    normalized_start: str
    normalized_end: str
    latest_bar_date: str
    cache_metadata: dict[str, str]
    steps: list[OhlcvIntakeCloseoutStep]
    blockers: list[str]
    watch_items: list[str]
    next_actions: list[str]
    command_sequence: list[str]
    prohibited_actions: list[str]
    offline_intake_report: OfflineDataIntakeReport | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "as_of": self.as_of,
            "data_dir": self.data_dir,
            "report_dir": self.report_dir,
            "config_path": self.config_path,
            "raw_bars_csv": self.raw_bars_csv,
            "raw_sha256": self.raw_sha256,
            "source_qa_status": self.source_qa_status,
            "raw_discovery_status": self.raw_discovery_status,
            "offline_intake_status": self.offline_intake_status,
            "cache_path": self.cache_path,
            "csv_dataset_fingerprint": self.csv_dataset_fingerprint,
            "normalized_row_count": self.normalized_row_count,
            "symbol_count": self.symbol_count,
            "normalized_start": self.normalized_start,
            "normalized_end": self.normalized_end,
            "latest_bar_date": self.latest_bar_date,
            "cache_metadata": self.cache_metadata,
            "steps": [step.to_dict() for step in self.steps],
            "blockers": self.blockers,
            "watch_items": self.watch_items,
            "next_actions": self.next_actions,
            "command_sequence": self.command_sequence,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# OHLCV Intake Closeout: {self.decision}",
            "",
            f"- As of: `{self.as_of or 'unspecified'}`",
            f"- Raw bars CSV: `{self.raw_bars_csv or 'none'}`",
            f"- Raw sha256: `{self.raw_sha256 or 'missing'}`",
            f"- Source QA: `{self.source_qa_status}`",
            f"- Raw discovery: `{self.raw_discovery_status}`",
            f"- Offline intake: `{self.offline_intake_status}`",
            f"- CSV fingerprint: `{self.csv_dataset_fingerprint or 'missing'}`",
            f"- Cache: `{self.cache_path}`",
            f"- Latest bar: `{self.latest_bar_date or 'missing'}`",
            "",
            "This closeout is a data-evidence bridge only. It is not a strategy signal, paper approval, profit claim, or live-trading permission.",
            "",
            "## Steps",
            "",
            "| step | status | artifact | message |",
            "| --- | --- | --- | --- |",
        ]
        for step in self.steps:
            lines.append(
                f"| `{step.name}` | `{step.status}` | `{step.artifact}` | {_cell(step.message)} |"
            )
        lines.extend(["", "## Blockers"])
        lines.extend(f"- {item}" for item in self.blockers) if self.blockers else lines.append("- None.")
        lines.extend(["", "## Watch Items"])
        lines.extend(f"- {item}" for item in self.watch_items) if self.watch_items else lines.append("- None.")
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Command Sequence"])
        for index, command in enumerate(self.command_sequence, start=1):
            lines.extend(["", f"{index}.", "", "```powershell", command, "```"])
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def run_ohlcv_intake_closeout(
    *,
    data_dir: str | Path = "data_exports",
    report_dir: str | Path = "results/first_million",
    config_path: str | Path = "config/research_recent.yaml",
    cache_path: str | Path | None = None,
    raw_bars_csv: str | Path | None = None,
    source_qa_answers: str | Path | None = None,
    source_qa_evidence_manifest: str | Path | None = None,
    require_source_qa_evidence_manifest: bool = True,
    min_symbols: int = 300,
    min_trading_days: int = 240,
    as_of: str | None = None,
    encoding: str = "utf-8-sig",
    max_staleness_days: int = 10,
    min_coverage_ratio: float = 0.95,
    raw_bars_discovery: RawBarsDiscoveryReport | None = None,
    run_guarded_intake: bool = True,
) -> OhlcvIntakeCloseout:
    data_root = Path(data_dir)
    report_root = Path(report_dir)
    closeout_dir = report_root / "ohlcv_intake_closeout"
    source_qa_dir = closeout_dir
    intake_dir = report_root / "offline_intake"
    closeout_dir.mkdir(parents=True, exist_ok=True)
    source_qa_dir.mkdir(parents=True, exist_ok=True)
    cfg = load_config(config_path)
    cache = Path(cache_path or cfg.data.cache_path)
    checklist_path = data_root / "data_source_qa.json"
    answers_path = Path(source_qa_answers) if source_qa_answers else data_root / "data_source_qa_answers.json"
    manifest_path = (
        Path(source_qa_evidence_manifest)
        if source_qa_evidence_manifest
        else data_root / "source_qa_evidence_manifest.json"
    )
    if not checklist_path.exists():
        checklist = build_data_source_qa(
            config_path=config_path,
            output_dir=data_root,
            min_symbols=min_symbols,
            as_of=as_of,
        )
        write_data_source_qa(checklist, data_root)

    review_manifest = (
        manifest_path
        if (
            source_qa_evidence_manifest is not None
            or require_source_qa_evidence_manifest
            or manifest_path.exists()
        )
        else None
    )
    source_review = build_data_source_qa_review(
        checklist_path=checklist_path,
        answers_path=answers_path,
        evidence_manifest_path=review_manifest,
        require_evidence_manifest=require_source_qa_evidence_manifest,
    )
    write_data_source_qa_review(source_review, source_qa_dir)
    steps = [
        OhlcvIntakeCloseoutStep(
            "source_qa",
            _normalize(source_review.status),
            str(source_qa_dir / "data_source_qa_review.json"),
            _source_qa_message(source_review.to_dict()),
        )
    ]
    discovery = raw_bars_discovery or build_raw_bars_discovery_report(
        search_dirs=[Path(raw_bars_csv)] if raw_bars_csv is not None else [data_root / "raw", data_root],
        config_path=config_path,
        output_dir=report_root,
        data_output_dir=data_root,
        min_symbols=min_symbols,
        start=str(cfg.research.start),
        end=str(cfg.research.end),
        encoding=encoding if encoding else "auto",
    )
    write_raw_bars_discovery_report(discovery, report_root)
    raw_path = Path(raw_bars_csv) if raw_bars_csv is not None else _raw_best_candidate(discovery)
    steps.append(
        OhlcvIntakeCloseoutStep(
            "raw_bars_discovery",
            _normalize(discovery.status),
            str(report_root / "raw_bars_discovery.json"),
            _raw_discovery_message(discovery.to_dict()),
        )
    )
    if source_review.status == "BLOCK":
        return _closeout_report(
            decision="BLOCK",
            as_of=as_of,
            data_root=data_root,
            report_root=report_root,
            config_path=config_path,
            cache=cache,
            raw_path=raw_path,
            source_qa_status=source_review.status,
            raw_discovery_status=discovery.status,
            steps=steps,
            blockers=_source_qa_blockers(source_review.to_dict()),
            watch_items=[],
            next_actions=source_review.next_actions,
            command_sequence=_blocked_source_commands(
                data_root=data_root,
                report_root=report_root,
                config_path=config_path,
                as_of=as_of,
            ),
        )
    source_watch_items = []
    if source_review.status == "WATCH":
        source_watch_items.append(f"source_qa: {_source_qa_message(source_review.to_dict())}")
    if raw_path is None or discovery.status == "BLOCK":
        return _closeout_report(
            decision="BLOCK",
            as_of=as_of,
            data_root=data_root,
            report_root=report_root,
            config_path=config_path,
            cache=cache,
            raw_path=raw_path,
            source_qa_status=source_review.status,
            raw_discovery_status=discovery.status,
            steps=steps,
            blockers=["raw_bars_discovery: no PASS/WATCH raw broker/vendor bars CSV candidate is available."],
            watch_items=source_watch_items,
            next_actions=discovery.next_actions,
            command_sequence=discovery.next_commands,
        )
    watch_items = list(source_watch_items)
    if discovery.status == "WATCH":
        watch_items.append("raw_bars_discovery: review WATCH findings before using the cache for research.")
    if not run_guarded_intake:
        steps.append(
            OhlcvIntakeCloseoutStep(
                "guarded_offline_intake",
                "WATCH",
                str(intake_dir / "offline_data_intake.json"),
                "Guarded intake was not executed by this closeout call.",
            )
        )
        return _closeout_report(
            decision="WATCH",
            as_of=as_of,
            data_root=data_root,
            report_root=report_root,
            config_path=config_path,
            cache=cache,
            raw_path=raw_path,
            source_qa_status=source_review.status,
            raw_discovery_status=discovery.status,
            steps=steps,
            blockers=[],
            watch_items=[*watch_items, "guarded_offline_intake: not executed."],
            next_actions=["Run the guarded OHLCV intake closeout with intake enabled."],
            command_sequence=[
                _closeout_command(
                    data_root=data_root,
                    report_root=report_root,
                    config_path=config_path,
                    raw_path=raw_path,
                    as_of=as_of,
                    min_symbols=min_symbols,
                    min_trading_days=min_trading_days,
                )
            ],
        )

    intake = run_offline_data_intake(
        raw_bars_csv=raw_path,
        data_dir=data_root,
        config_path=config_path,
        cache_path=cache,
        output_dir=intake_dir,
        min_symbols=min_symbols,
        min_trading_days=min_trading_days,
        as_of=as_of,
        encoding=encoding,
        source_qa_checklist=checklist_path,
        source_qa_answers=answers_path,
        source_qa_evidence_manifest=manifest_path,
        require_source_qa_evidence_manifest=require_source_qa_evidence_manifest,
        max_staleness_days=max_staleness_days,
        min_coverage_ratio=min_coverage_ratio,
    )
    steps.append(
        OhlcvIntakeCloseoutStep(
            "guarded_offline_intake",
            intake.status,
            str(intake_dir / "offline_data_intake.json"),
            _offline_intake_message(intake.to_dict()),
        )
    )
    decision = _combine([step.status for step in steps])
    blockers = []
    if intake.status == "BLOCK":
        blockers.append(f"guarded_offline_intake: {_first_issue(intake.to_dict())}")
    if intake.status == "WATCH":
        watch_items.append(f"guarded_offline_intake: {_first_issue(intake.to_dict())}")
    closeout = _closeout_report(
        decision=decision,
        as_of=as_of,
        data_root=data_root,
        report_root=report_root,
        config_path=config_path,
        cache=cache,
        raw_path=raw_path,
        source_qa_status=source_review.status,
        raw_discovery_status=discovery.status,
        steps=steps,
        blockers=blockers,
        watch_items=watch_items,
        next_actions=_next_actions(decision, intake.next_actions),
        command_sequence=[
            _pipeline_refresh_command(
                data_root=data_root,
                report_root=report_root,
                config_path=config_path,
                answers_path=answers_path,
                manifest_path=manifest_path,
                as_of=as_of,
                min_symbols=min_symbols,
                min_trading_days=min_trading_days,
            )
        ],
        offline_intake_report=intake,
    )
    write_ohlcv_intake_closeout(closeout, report_root)
    return closeout


def write_ohlcv_intake_closeout(closeout: OhlcvIntakeCloseout, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "ohlcv_intake_closeout.json").write_text(
        json.dumps(closeout.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "ohlcv_intake_closeout.md").write_text(closeout.to_markdown(), encoding="utf-8")
    _write_steps_csv(closeout, root / "ohlcv_intake_closeout.csv")
    closeout_dir = root / "ohlcv_intake_closeout"
    closeout_dir.mkdir(parents=True, exist_ok=True)
    (closeout_dir / "ohlcv_intake_closeout.json").write_text(
        json.dumps(closeout.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (closeout_dir / "ohlcv_intake_closeout.md").write_text(closeout.to_markdown(), encoding="utf-8")
    _write_steps_csv(closeout, closeout_dir / "ohlcv_intake_closeout.csv")
    return root


def _closeout_report(
    *,
    decision: CloseoutDecision,
    as_of: str | None,
    data_root: Path,
    report_root: Path,
    config_path: str | Path,
    cache: Path,
    raw_path: Path | None,
    source_qa_status: str,
    raw_discovery_status: str,
    steps: list[OhlcvIntakeCloseoutStep],
    blockers: list[str],
    watch_items: list[str],
    next_actions: list[str],
    command_sequence: list[str],
    offline_intake_report: OfflineDataIntakeReport | None = None,
) -> OhlcvIntakeCloseout:
    normalization = _read_json(report_root / "offline_intake" / "vendor_bars_normalization.json")
    validation = _read_json(report_root / "offline_intake" / "csv_validation.json")
    bootstrap = _read_json(report_root / "offline_intake" / "real_data_bootstrap.json")
    cache_metadata = BarStorage(cache).load_metadata() if cache.exists() else {}
    closeout = OhlcvIntakeCloseout(
        decision=decision,
        as_of=as_of,
        data_dir=str(data_root),
        report_dir=str(report_root),
        config_path=str(config_path),
        raw_bars_csv=str(raw_path or ""),
        raw_sha256=str(normalization.get("raw_sha256") or _raw_candidate_sha(raw_path) or ""),
        source_qa_status=str(source_qa_status or "MISSING"),
        raw_discovery_status=str(raw_discovery_status or "MISSING"),
        offline_intake_status=str(offline_intake_report.status if offline_intake_report else "NOT_RUN"),
        cache_path=str(cache),
        csv_dataset_fingerprint=str(
            validation.get("dataset_fingerprint")
            or cache_metadata.get("csv_dataset_fingerprint")
            or ""
        ),
        normalized_row_count=_int(normalization.get("normalized_row_count")),
        symbol_count=_int(
            normalization.get("symbol_count")
            or (validation.get("metrics", {}) or {}).get("bars_symbol_count")
        ),
        normalized_start=str(normalization.get("normalized_start") or ""),
        normalized_end=str(normalization.get("normalized_end") or ""),
        latest_bar_date=str(bootstrap.get("latest_bar_date") or ""),
        cache_metadata=cache_metadata,
        steps=steps,
        blockers=_dedupe(blockers),
        watch_items=_dedupe(watch_items),
        next_actions=_dedupe(next_actions) or ["Rerun first-million pipeline after fixing closeout evidence."],
        command_sequence=_dedupe(command_sequence),
        prohibited_actions=PROHIBITED_ACTIONS,
        offline_intake_report=offline_intake_report,
    )
    write_ohlcv_intake_closeout(closeout, report_root)
    return closeout


def _write_steps_csv(closeout: OhlcvIntakeCloseout, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "status", "artifact", "message"])
        writer.writeheader()
        for step in closeout.steps:
            writer.writerow(step.to_dict())


def _raw_best_candidate(discovery: RawBarsDiscoveryReport) -> Path | None:
    text = str(discovery.best_candidate or "").strip()
    return Path(text) if text else None


def _source_qa_message(payload: dict[str, Any]) -> str:
    findings = payload.get("findings", []) or []
    for severity in ("BLOCK", "WATCH"):
        for finding in findings:
            if isinstance(finding, dict) and finding.get("severity") == severity:
                return f"{finding.get('code')}: {finding.get('message')}"
    return "Source QA review is PASS."


def _source_qa_blockers(payload: dict[str, Any]) -> list[str]:
    findings = payload.get("findings", []) or []
    blockers = [
        f"source_qa {item.get('code', 'SOURCE_QA')}: {item.get('message', '')}"
        for item in findings
        if isinstance(item, dict) and item.get("severity") in {"BLOCK", "WATCH"}
    ]
    return blockers or ["source_qa: deterministic source QA is not PASS."]


def _raw_discovery_message(payload: dict[str, Any]) -> str:
    best = str(payload.get("best_candidate") or "none")
    candidates = payload.get("candidates", []) or []
    for candidate in candidates:
        if isinstance(candidate, dict) and str(candidate.get("path") or "") == best:
            return str(candidate.get("message") or f"best={best}")
    return f"best={best}, candidates={len(candidates)}"


def _offline_intake_message(payload: dict[str, Any]) -> str:
    steps = payload.get("steps", []) or []
    for step in steps:
        if isinstance(step, dict) and step.get("status") == "BLOCK":
            return f"{step.get('name', 'step')}: {step.get('message', '')}"
    for step in steps:
        if isinstance(step, dict) and step.get("status") == "WATCH":
            return f"{step.get('name', 'step')}: {step.get('message', '')}"
    return "Guarded offline intake completed without BLOCK findings."


def _first_issue(payload: dict[str, Any]) -> str:
    for action in payload.get("next_actions", []) or []:
        text = str(action or "").strip()
        if text:
            return text
    return _offline_intake_message(payload)


def _next_actions(decision: CloseoutDecision, intake_actions: list[str]) -> list[str]:
    if decision == "BLOCK":
        return intake_actions or ["Fix closeout blockers before rerunning guarded offline intake."]
    if decision == "WATCH":
        return [
            "Review closeout WATCH evidence before launching candidate research.",
            "Rerun first-million pipeline so downstream gates see the refreshed cache metadata.",
        ]
    return [
        "Rerun first-million pipeline so candidate readiness uses the refreshed cache metadata.",
        "Run candidate research only if deterministic candidate_experiment_readiness is not BLOCK.",
    ]


def _blocked_source_commands(
    *,
    data_root: Path,
    report_root: Path,
    config_path: str | Path,
    as_of: str | None,
) -> list[str]:
    as_of_arg = f" --as-of {as_of}" if as_of else ""
    return [
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa_answers.py "
            f"--checklist {data_root / 'data_source_qa.json'} "
            f"--worksheet {data_root / 'data_source_qa_evidence_worksheet.csv'} "
            f"--output {data_root / 'data_source_qa_answers.json'} "
            f"--evidence-manifest {data_root / 'source_qa_evidence_manifest.json'} "
            "--require-evidence-manifest"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_ohlcv_intake_closeout.py "
            f"--data-dir {data_root} --report-dir {report_root} --config {config_path}{as_of_arg}"
        ),
    ]


def _closeout_command(
    *,
    data_root: Path,
    report_root: Path,
    config_path: str | Path,
    raw_path: Path,
    as_of: str | None,
    min_symbols: int,
    min_trading_days: int,
) -> str:
    as_of_arg = f" --as-of {as_of}" if as_of else ""
    return (
        ".\\.venv\\Scripts\\python.exe examples\\run_ohlcv_intake_closeout.py "
        f"--data-dir {data_root} --report-dir {report_root} --config {config_path} "
        f"--raw-bars-csv {raw_path} --min-symbols {min_symbols} "
        f"--min-trading-days {min_trading_days}{as_of_arg}"
    )


def _pipeline_refresh_command(
    *,
    data_root: Path,
    report_root: Path,
    config_path: str | Path,
    answers_path: Path,
    manifest_path: Path,
    as_of: str | None,
    min_symbols: int,
    min_trading_days: int,
) -> str:
    as_of_arg = f" --as-of {as_of}" if as_of else ""
    return (
        ".\\.venv\\Scripts\\python.exe examples\\run_first_million_pipeline.py "
        f"--config {config_path} --data-dir {data_root} --output-dir {report_root} "
        f"--source-qa-answers {answers_path} --source-qa-evidence-manifest {manifest_path} "
        "--require-source-qa-evidence-manifest "
        f"--min-symbols {min_symbols} --min-trading-days {min_trading_days}{as_of_arg}"
    )


def _raw_candidate_sha(path: Path | None) -> str:
    if path is None or not path.exists():
        return ""
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize(status: object) -> CloseoutDecision:
    text = str(status or "").upper()
    if text == "PASS":
        return "PASS"
    if text == "WATCH":
        return "WATCH"
    return "BLOCK"


def _combine(statuses: list[CloseoutDecision]) -> CloseoutDecision:
    if any(status == "BLOCK" for status in statuses):
        return "BLOCK"
    if any(status == "WATCH" for status in statuses):
        return "WATCH"
    return "PASS"


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value or "").strip()))


def _cell(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")
