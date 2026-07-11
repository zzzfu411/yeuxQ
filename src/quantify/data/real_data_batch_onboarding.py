"""Operator-facing onboarding plan for a real A-share data batch.

This report turns the current blocked data state into a concrete sequence for
bringing a broker/vendor raw bars export into the guarded research workflow. It
does not create source evidence, import data, approve a strategy, or connect to
any broker.
"""
from __future__ import annotations

from dataclasses import dataclass
import csv
import json
from pathlib import Path
from typing import Any, Literal

from quantify.data.ohlcv_experiment_package import OhlcvExperimentPackagePreflight
from quantify.data.raw_bars_discovery import RawBarsDiscoveryReport
from quantify.data.source_qa_operator_packet import SourceQAOperatorPacket
from quantify.utils.config import load_config

OnboardingDecision = Literal["PASS", "WATCH", "BLOCK"]

PROHIBITED_ACTIONS = [
    "Do not fabricate raw bars, source QA worksheet answers, evidence attachments, or market context.",
    "Do not treat onboarding PASS/WATCH as strategy profitability evidence.",
    "Do not run candidate research while OHLCV experiment package or candidate readiness is BLOCK.",
    "Do not use OHLCV-only onboarding for valuation, quality, or PIT-fundamental claims.",
    "Do not promote any output to paper or micro-live without downstream deterministic gates and human approval.",
    "Do not connect this workflow to real broker order submission.",
]


@dataclass(frozen=True, slots=True)
class RealDataBatchStep:
    name: str
    status: OnboardingDecision
    artifact: str
    message: str
    next_command: str
    acceptance_criteria: str
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "artifact": self.artifact,
            "message": self.message,
            "next_command": self.next_command,
            "acceptance_criteria": self.acceptance_criteria,
            "required": self.required,
        }


@dataclass(frozen=True, slots=True)
class RealDataBatchOnboarding:
    decision: OnboardingDecision
    as_of: str | None
    data_dir: str
    report_dir: str
    config_path: str
    raw_bars_csv: str
    cache_path: str
    research_start: str
    research_end: str
    min_symbols: int
    min_trading_days: int
    steps: list[RealDataBatchStep]
    blockers: list[str]
    watch_items: list[str]
    next_actions: list[str]
    command_sequence: list[str]
    acceptance_criteria: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "as_of": self.as_of,
            "data_dir": self.data_dir,
            "report_dir": self.report_dir,
            "config_path": self.config_path,
            "raw_bars_csv": self.raw_bars_csv,
            "cache_path": self.cache_path,
            "research_start": self.research_start,
            "research_end": self.research_end,
            "min_symbols": self.min_symbols,
            "min_trading_days": self.min_trading_days,
            "steps": [step.to_dict() for step in self.steps],
            "blockers": self.blockers,
            "watch_items": self.watch_items,
            "next_actions": self.next_actions,
            "command_sequence": self.command_sequence,
            "acceptance_criteria": self.acceptance_criteria,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Real Data Batch Onboarding: {self.decision}",
            "",
            f"- As of: `{self.as_of or 'unspecified'}`",
            f"- Raw bars CSV: `{self.raw_bars_csv or 'not supplied'}`",
            f"- Data directory: `{self.data_dir}`",
            f"- Report directory: `{self.report_dir}`",
            f"- Config: `{self.config_path}`",
            f"- Cache path: `{self.cache_path}`",
            f"- Research window: `{self.research_start}` to `{self.research_end}`",
            f"- Minimum symbols: {self.min_symbols}",
            f"- Minimum trading days: {self.min_trading_days}",
            "",
            "This onboarding plan is a data-operator workflow for recent A-share evidence. It is not a strategy signal, profit claim, paper approval, or live-trading permission.",
            "",
            "## Steps",
            "",
            "| step | status | required | artifact | message | acceptance |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for step in self.steps:
            lines.append(
                f"| `{step.name}` | `{step.status}` | `{step.required}` | `{step.artifact}` | "
                f"{_cell(step.message)} | {_cell(step.acceptance_criteria)} |"
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
        lines.extend(["", "## Acceptance Criteria"])
        lines.extend(f"- {item}" for item in self.acceptance_criteria)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_real_data_batch_onboarding(
    *,
    data_dir: str | Path = "data_exports",
    report_dir: str | Path = "results/first_million",
    config_path: str | Path = "config/research_recent.yaml",
    raw_bars_csv: str | Path | None = None,
    source_qa_answers: str | Path | None = None,
    source_qa_evidence_manifest: str | Path | None = None,
    require_source_qa_evidence_manifest: bool = False,
    min_symbols: int = 300,
    min_trading_days: int = 240,
    as_of: str | None = None,
    encoding: str = "utf-8-sig",
    source_qa_packet: SourceQAOperatorPacket | None = None,
    ohlcv_package: OhlcvExperimentPackagePreflight | None = None,
    raw_bars_discovery: RawBarsDiscoveryReport | None = None,
) -> RealDataBatchOnboarding:
    data_root = Path(data_dir)
    report_root = Path(report_dir)
    cfg = load_config(config_path)
    answers_path = Path(source_qa_answers) if source_qa_answers else data_root / "data_source_qa_answers.json"
    manifest_path = (
        Path(source_qa_evidence_manifest)
        if source_qa_evidence_manifest
        else data_root / "source_qa_evidence_manifest.json"
    )
    raw_path = Path(raw_bars_csv) if raw_bars_csv else None
    steps = [
        _raw_bars_discovery_step(raw_bars_discovery),
        _raw_bars_step(raw_path),
        _normalize_step(
            raw_path=raw_path,
            data_dir=data_root,
            report_dir=report_root,
            config_path=config_path,
            min_symbols=min_symbols,
            start=str(cfg.research.start),
            end=str(cfg.research.end),
            encoding=encoding,
        ),
        _source_qa_step(source_qa_packet),
        _source_qa_answers_step(answers_path),
        _source_qa_manifest_step(manifest_path, require_manifest=require_source_qa_evidence_manifest),
        _market_context_step(report_root),
        _ohlcv_preflight_step(ohlcv_package),
        _offline_intake_step(
            data_dir=data_root,
            report_dir=report_root,
            config_path=config_path,
            answers_path=answers_path,
            min_symbols=min_symbols,
            min_trading_days=min_trading_days,
            as_of=as_of,
        ),
        _pipeline_refresh_step(
            data_dir=data_root,
            report_dir=report_root,
            config_path=config_path,
            answers_path=answers_path,
            manifest_path=manifest_path,
            require_manifest=require_source_qa_evidence_manifest,
            min_symbols=min_symbols,
            min_trading_days=min_trading_days,
            as_of=as_of,
        ),
    ]
    blockers = [f"{step.name}: {step.message}" for step in steps if step.required and step.status == "BLOCK"]
    watch_items = [f"{step.name}: {step.message}" for step in steps if step.status == "WATCH"]
    decision: OnboardingDecision = "BLOCK" if blockers else "WATCH" if watch_items else "PASS"
    return RealDataBatchOnboarding(
        decision=decision,
        as_of=as_of,
        data_dir=str(data_root),
        report_dir=str(report_root),
        config_path=str(config_path),
        raw_bars_csv=str(raw_path or ""),
        cache_path=str(cfg.data.cache_path),
        research_start=str(cfg.research.start),
        research_end=str(cfg.research.end),
        min_symbols=min_symbols,
        min_trading_days=min_trading_days,
        steps=steps,
        blockers=blockers,
        watch_items=watch_items,
        next_actions=_next_actions(decision, blockers, watch_items),
        command_sequence=_commands(steps),
        acceptance_criteria=_acceptance_criteria(),
        prohibited_actions=PROHIBITED_ACTIONS,
    )


def write_real_data_batch_onboarding(
    onboarding: RealDataBatchOnboarding,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "real_data_batch_onboarding.json").write_text(
        json.dumps(onboarding.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "real_data_batch_onboarding.md").write_text(onboarding.to_markdown(), encoding="utf-8")
    _write_steps_csv(onboarding, root / "real_data_batch_onboarding.csv")
    return root


def _write_steps_csv(onboarding: RealDataBatchOnboarding, path: Path) -> None:
    fieldnames = [
        "name",
        "status",
        "required",
        "artifact",
        "message",
        "next_command",
        "acceptance_criteria",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for step in onboarding.steps:
            writer.writerow(step.to_dict())


def _raw_bars_step(raw_path: Path | None) -> RealDataBatchStep:
    if raw_path is None:
        return RealDataBatchStep(
            "raw_bars_csv",
            "BLOCK",
            "<raw-vendor-bars.csv>",
            "No raw broker/vendor bars CSV path was supplied.",
            "",
            "A retained raw CSV exists and its path is recorded in the onboarding report.",
        )
    if not raw_path.exists():
        return RealDataBatchStep(
            "raw_bars_csv",
            "BLOCK",
            str(raw_path),
            "Supplied raw broker/vendor bars CSV does not exist.",
            "",
            "The raw CSV path exists and can be read locally.",
        )
    if raw_path.stat().st_size <= 0:
        return RealDataBatchStep(
            "raw_bars_csv",
            "BLOCK",
            str(raw_path),
            "Supplied raw broker/vendor bars CSV is empty.",
            "",
            "The raw CSV is non-empty and retained with the data batch.",
        )
    return RealDataBatchStep(
        "raw_bars_csv",
        "PASS",
        str(raw_path),
        f"Raw broker/vendor bars CSV is present; size={raw_path.stat().st_size} bytes.",
        "",
        "Raw CSV exists, is non-empty, and remains immutable after normalization.",
    )


def _raw_bars_discovery_step(report: RawBarsDiscoveryReport | None) -> RealDataBatchStep:
    if report is None:
        return RealDataBatchStep(
            "raw_bars_discovery",
            "WATCH",
            "raw_bars_discovery.json",
            "Raw bars discovery was not supplied to this direct onboarding call.",
            ".\\.venv\\Scripts\\python.exe examples\\run_raw_bars_discovery.py --search-dir <raw-bars-directory> --config config\\research_recent.yaml --output-dir results\\first_million",
            "raw_bars_discovery.json lists a PASS/WATCH raw broker/vendor bars CSV candidate.",
            required=False,
        )
    if report.status == "PASS":
        return RealDataBatchStep(
            "raw_bars_discovery",
            "PASS",
            "raw_bars_discovery.json",
            f"Best raw bars candidate: {report.best_candidate}.",
            report.next_commands[0] if report.next_commands else "",
            "Best candidate is retained and ready for normalization after source QA evidence is prepared.",
            required=False,
        )
    if report.status == "WATCH":
        return RealDataBatchStep(
            "raw_bars_discovery",
            "WATCH",
            "raw_bars_discovery.json",
            f"Best raw bars candidate has WATCH findings: {report.best_candidate or 'none'}.",
            report.next_commands[0] if report.next_commands else "",
            "Review raw candidate WATCH findings before normalization.",
            required=False,
        )
    return RealDataBatchStep(
        "raw_bars_discovery",
        "BLOCK",
        "raw_bars_discovery.json",
        "No usable raw broker/vendor bars CSV candidate was discovered.",
        report.next_commands[0] if report.next_commands else "",
        "Place a retained raw bars CSV in a scanned directory or pass --raw-bars-csv explicitly.",
        required=False,
    )


def _normalize_step(
    *,
    raw_path: Path | None,
    data_dir: Path,
    report_dir: Path,
    config_path: str | Path,
    min_symbols: int,
    start: str,
    end: str,
    encoding: str,
) -> RealDataBatchStep:
    raw = str(raw_path) if raw_path else "<raw-vendor-bars.csv>"
    command = (
        ".\\.venv\\Scripts\\python.exe examples\\normalize_vendor_bars.py "
        f"--input {raw} --output-dir {data_dir} --report-dir {report_dir} "
        f"--encoding {encoding} --start {start} --end {end} --min-symbols {min_symbols}"
    )
    bars = data_dir / "bars.csv"
    if not bars.exists():
        return RealDataBatchStep(
            "normalize_vendor_bars",
            "BLOCK",
            str(bars),
            "data_exports\\bars.csv does not exist yet.",
            command,
            "bars.csv is written from the retained raw CSV and normalization report is not BLOCK.",
        )
    return RealDataBatchStep(
        "normalize_vendor_bars",
        "WATCH",
        str(bars),
        "bars.csv exists, but onboarding still requires source QA, coverage, and OHLCV preflight evidence.",
        command,
        "vendor_bars_normalization.json records raw hash, normalized rows, symbols, and period.",
    )


def _source_qa_step(packet: SourceQAOperatorPacket | None) -> RealDataBatchStep:
    if packet is None:
        return RealDataBatchStep(
            "source_qa_operator_packet",
            "WATCH",
            "source_qa_operator_packet.json",
            "Source QA operator packet is not supplied to this direct onboarding call.",
            ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_operator_packet.py --data-dir data_exports --report-dir results\\first_million",
            "source_qa_operator_packet.json exists and lists no missing worksheet or attachment items.",
        )
    if packet.decision == "PASS":
        return RealDataBatchStep(
            "source_qa_operator_packet",
            "PASS",
            "source_qa_operator_packet.json",
            "Source QA operator packet has no missing worksheet or attachment items.",
            "",
            "No source QA operator items remain open.",
        )
    return RealDataBatchStep(
        "source_qa_operator_packet",
        packet.decision,
        "source_qa_operator_packet.json",
        (
            f"Source QA operator packet has {packet.missing_worksheet_count} missing worksheet "
            f"and {packet.missing_attachment_count} missing attachment items."
        ),
        packet.command_sequence[0] if packet.command_sequence else "",
        "Every source QA worksheet row and required retained evidence attachment is complete.",
    )


def _source_qa_answers_step(path: Path) -> RealDataBatchStep:
    if path.exists() and path.stat().st_size > 0:
        return RealDataBatchStep(
            "source_qa_answers",
            "PASS",
            str(path),
            "data_source_qa_answers.json exists.",
            "",
            "Source QA answers are generated from a preflighted worksheet or explicit retained evidence.",
        )
    return RealDataBatchStep(
        "source_qa_answers",
        "BLOCK",
        str(path),
        "data_source_qa_answers.json is missing or empty.",
        ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa_answers.py "
        "--checklist data_exports\\data_source_qa.json "
        "--worksheet data_exports\\data_source_qa_evidence_worksheet.csv "
        "--output data_exports\\data_source_qa_answers.json "
        "--evidence-manifest data_exports\\source_qa_evidence_manifest.json "
        "--require-evidence-manifest",
        "data_source_qa_answers.json exists and deterministic source QA review is not BLOCK.",
    )


def _source_qa_manifest_step(path: Path, *, require_manifest: bool) -> RealDataBatchStep:
    if path.exists() and path.stat().st_size > 0:
        status: OnboardingDecision = "PASS" if require_manifest else "WATCH"
        message = (
            "source_qa_evidence_manifest.json exists."
            if require_manifest
            else "source_qa_evidence_manifest.json exists; strict source QA mode should still be used before intake."
        )
        return RealDataBatchStep(
            "source_qa_evidence_manifest",
            status,
            str(path),
            message,
            "",
            "Strict source QA evidence readiness is PASS before guarded offline intake.",
        )
    return RealDataBatchStep(
        "source_qa_evidence_manifest",
        "BLOCK" if require_manifest else "WATCH",
        str(path),
        "source_qa_evidence_manifest.json is missing or empty.",
        ".\\.venv\\Scripts\\python.exe examples\\write_source_qa_evidence_manifest.py --checklist data_exports\\data_source_qa.json --evidence-dir data_exports\\source_qa_evidence --output-dir data_exports --strict",
        "Required retained evidence files are hashed into source_qa_evidence_manifest.json.",
    )


def _market_context_step(report_dir: Path) -> RealDataBatchStep:
    regime = report_dir / "market_regime.json"
    snapshot = report_dir / "market_context_snapshot.json"
    if regime.exists():
        return RealDataBatchStep(
            "market_context",
            "PASS",
            str(regime),
            "Cache-derived market_regime.json exists.",
            "",
            "market_context_readiness.json is PASS or WATCH and cannot override data gates.",
        )
    if snapshot.exists():
        return RealDataBatchStep(
            "market_context",
            "WATCH",
            str(snapshot),
            "Only reviewed market_context_snapshot.json is available; it is advisory and cannot replace market_regime.json.",
            ".\\.venv\\Scripts\\python.exe examples\\run_market_regime.py --config config\\research_recent.yaml --output-dir results\\first_million",
            "Prefer cache-derived market_regime.json after guarded offline intake.",
        )
    return RealDataBatchStep(
        "market_context",
        "BLOCK",
        str(regime),
        "No market_regime.json or reviewed market_context_snapshot.json is available.",
        ".\\.venv\\Scripts\\python.exe examples\\run_market_index_discovery.py --search-dir data_exports\\indices --output-dir results\\first_million --as-of <YYYY-MM-DD>",
        "Market context evidence exists and remains advisory only.",
    )


def _ohlcv_preflight_step(package: OhlcvExperimentPackagePreflight | None) -> RealDataBatchStep:
    if package is None:
        return RealDataBatchStep(
            "ohlcv_experiment_package",
            "WATCH",
            "ohlcv_experiment_package.json",
            "OHLCV experiment package preflight was not supplied to this direct onboarding call.",
            ".\\.venv\\Scripts\\python.exe examples\\run_ohlcv_experiment_package.py --data-dir data_exports --report-dir results\\first_million --config config\\research_recent.yaml --source-qa-answers data_exports\\data_source_qa_answers.json --source-qa-evidence-manifest data_exports\\source_qa_evidence_manifest.json --require-source-qa-evidence-manifest --min-symbols 300 --min-trading-days 240",
            "ohlcv_experiment_package.json is PASS or WATCH before candidate research launch.",
        )
    return RealDataBatchStep(
        "ohlcv_experiment_package",
        package.decision,
        "ohlcv_experiment_package.json",
        _first([*package.blockers, *package.watch_items], "OHLCV experiment package passes."),
        package.next_commands[0] if package.next_commands else "",
        "OHLCV package is not BLOCK and only opens guarded research for price_volume_defensive.",
    )


def _offline_intake_step(
    *,
    data_dir: Path,
    report_dir: Path,
    config_path: str | Path,
    answers_path: Path,
    min_symbols: int,
    min_trading_days: int,
    as_of: str | None,
) -> RealDataBatchStep:
    as_of_arg = f" --as-of {as_of}" if as_of else ""
    command = (
        ".\\.venv\\Scripts\\python.exe examples\\run_offline_data_intake.py "
        f"--data-dir {data_dir} --config {config_path} --output-dir {report_dir / 'offline_intake'} "
        f"--source-qa-answers {answers_path} --min-symbols {min_symbols} "
        f"--min-trading-days {min_trading_days}{as_of_arg}"
    )
    artifact = report_dir / "offline_intake" / "offline_data_intake.json"
    return RealDataBatchStep(
        "guarded_offline_intake",
        "WATCH" if artifact.exists() else "BLOCK",
        str(artifact),
        "Guarded offline intake evidence must be refreshed after raw bars, source QA, and OHLCV preflight pass.",
        command,
        "offline_data_intake.json is PASS or WATCH and writes a traceable local research cache.",
    )


def _pipeline_refresh_step(
    *,
    data_dir: Path,
    report_dir: Path,
    config_path: str | Path,
    answers_path: Path,
    manifest_path: Path,
    require_manifest: bool,
    min_symbols: int,
    min_trading_days: int,
    as_of: str | None,
) -> RealDataBatchStep:
    as_of_arg = f" --as-of {as_of}" if as_of else ""
    require_arg = " --require-source-qa-evidence-manifest" if require_manifest else ""
    command = (
        ".\\.venv\\Scripts\\python.exe examples\\run_first_million_pipeline.py "
        f"--config {config_path} --data-dir {data_dir} --output-dir {report_dir} "
        f"--source-qa-answers {answers_path} --source-qa-evidence-manifest {manifest_path}"
        f"{require_arg} --min-symbols {min_symbols} --min-trading-days {min_trading_days}{as_of_arg}"
    )
    return RealDataBatchStep(
        "refresh_first_million_pipeline",
        "WATCH",
        str(report_dir / "first_million_pipeline.json"),
        "Refresh the full first-million evidence set after onboarding inputs change.",
        command,
        "first_million_pipeline.json records the updated data batch and still owns the final BLOCK/WATCH/PASS state.",
        required=False,
    )


def _next_actions(
    decision: OnboardingDecision,
    blockers: list[str],
    watch_items: list[str],
) -> list[str]:
    if decision == "BLOCK":
        actions = []
        if any("raw_bars_csv" in item for item in blockers):
            actions.append("Export or locate the retained raw broker/vendor daily bars CSV.")
        if any("normalize_vendor_bars" in item for item in blockers):
            actions.append("Normalize the raw bars CSV into data_exports\\bars.csv and keep the normalization report.")
        if any("source_qa" in item for item in blockers):
            actions.append("Fill source QA worksheet rows and attach retained evidence files.")
        if any("market_context" in item for item in blockers):
            actions.append("Attach reviewed market context evidence before candidate readiness.")
        if any("ohlcv_experiment_package" in item for item in blockers):
            actions.append("Make the OHLCV experiment package preflight PASS/WATCH before candidate research.")
        actions.append("Rerun first-million pipeline after the data batch evidence changes.")
        return _dedupe(actions)
    if decision == "WATCH":
        return [
            "Review WATCH onboarding steps and keep their evidence with the data batch.",
            "Rerun first-million pipeline, then candidate readiness, before launching any research experiment.",
        ]
    return [
        "Run guarded offline intake and first-million pipeline refresh.",
        "Launch candidate research only if candidate_experiment_readiness is not BLOCK.",
    ]


def _commands(steps: list[RealDataBatchStep]) -> list[str]:
    return _dedupe(step.next_command for step in steps if step.next_command)


def _acceptance_criteria() -> list[str]:
    return [
        "Raw bars export path is retained and immutable; normalization report records raw sha256.",
        "bars.csv meets configured symbol and trading-day coverage minimums.",
        "Source QA answers and strict retained evidence manifest pass deterministic review.",
        "Market context evidence exists and remains advisory only.",
        "OHLCV experiment package is PASS/WATCH before price_volume_defensive research launch.",
        "Candidate readiness remains the final research-launch gate; onboarding cannot override it.",
    ]


def _first(values: list[str], default: str) -> str:
    return next((value for value in values if str(value or "").strip()), default)


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
