"""Guarded offline CSV intake pipeline for recent A-share research data."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from quantify.data.csv_contract import validate_research_csvs, write_csv_validation_report
from quantify.data.csv_research_importer import import_research_csvs
from quantify.data.import_doctor import build_data_import_doctor, write_data_import_doctor_report
from quantify.data.provider import DataProvider
from quantify.data.research_importer import write_import_report
from quantify.data.source_qa import (
    build_data_source_qa_answers,
    build_data_source_qa_review,
    write_data_source_qa_answers,
    write_data_source_qa_review,
)
from quantify.data.storage import BarStorage
from quantify.data.vendor_bars_normalizer import (
    normalize_vendor_bars,
    write_vendor_bars_normalization_report,
)
from quantify.ops.bootstrap import (
    build_real_data_bootstrap_report,
    write_real_data_bootstrap_report,
)
from quantify.utils.config import load_config

IntakeStatus = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class OfflineIntakeStep:
    name: str
    status: IntakeStatus
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
class OfflineDataIntakeReport:
    status: IntakeStatus
    data_dir: str
    config_path: str
    cache_path: str
    start: str
    end: str
    min_symbols: int
    steps: list[OfflineIntakeStep]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "data_dir": self.data_dir,
            "config_path": self.config_path,
            "cache_path": self.cache_path,
            "start": self.start,
            "end": self.end,
            "min_symbols": self.min_symbols,
            "steps": [step.to_dict() for step in self.steps],
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Offline Data Intake: {self.status}",
            "",
            f"- Data directory: `{self.data_dir}`",
            f"- Config: `{self.config_path}`",
            f"- Cache: `{self.cache_path}`",
            f"- Period: `{self.start}` to `{self.end}`",
            f"- Minimum symbols: {self.min_symbols}",
            "",
            "## Steps",
            "",
            "| step | status | artifact | message |",
            "| --- | --- | --- | --- |",
        ]
        for step in self.steps:
            lines.append(f"| `{step.name}` | `{step.status}` | `{step.artifact}` | {step.message} |")
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {action}" for action in self.next_actions)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {action}" for action in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def run_offline_data_intake(
    *,
    data_dir: str | Path = "data_exports",
    config_path: str | Path = "config/research_recent.yaml",
    cache_path: str | Path | None = None,
    output_dir: str | Path = "results/import/offline_intake",
    start: str | None = None,
    end: str | None = None,
    min_symbols: int = 300,
    min_trading_days: int = 240,
    as_of: str | None = None,
    encoding: str = "utf-8-sig",
    raw_bars_csv: str | Path | None = None,
    source_vendor: str | None = None,
    source_terminal: str | None = None,
    source_operator: str | None = None,
    source_exported_at: str | None = None,
    source_price_adjustment: str | None = None,
    source_price_adjustment_evidence: str | None = None,
    source_license_scope: str = "research and paper trading only",
    source_license_evidence: str | None = None,
    source_point_in_time_evidence: str | None = None,
    source_reviewed_by: str | None = None,
    source_reviewed_at: str | None = None,
    source_known_limitations: str = "",
    max_staleness_days: int = 10,
    min_coverage_ratio: float = 0.95,
    source_qa_checklist: str | Path | None = None,
    source_qa_answers: str | Path | None = None,
    source_qa_evidence_manifest: str | Path | None = None,
    require_source_qa_evidence_manifest: bool = False,
) -> OfflineDataIntakeReport:
    """Run doctor, validation, import, and bootstrap with hard stops on BLOCK."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    cfg = load_config(config_path)
    resolved_start = start or str(cfg.research.start)
    resolved_end = end or str(cfg.research.end)
    cache = Path(cache_path or cfg.data.cache_path)
    data_root = Path(data_dir)
    steps: list[OfflineIntakeStep] = []
    normalization = None
    source_qa_review = None

    if raw_bars_csv is not None:
        normalization = normalize_vendor_bars(
            input_path=raw_bars_csv,
            output_dir=data_root,
            encoding=encoding,
            start=resolved_start,
            end=resolved_end,
            min_symbols=min_symbols,
        )
        write_vendor_bars_normalization_report(normalization, out)
        steps.append(
            OfflineIntakeStep(
                "vendor_bars_normalization",
                normalization.status,
                str(out / "vendor_bars_normalization.json"),
                _normalization_message(normalization.to_dict()),
            )
        )
        if normalization.status == "BLOCK":
            return _final_report(
                data_dir=data_root,
                config_path=config_path,
                cache=cache,
                start=resolved_start,
                end=resolved_end,
                min_symbols=min_symbols,
                steps=steps,
                output_dir=out,
                next_actions=normalization.next_actions,
            )

    checklist_path = Path(source_qa_checklist) if source_qa_checklist else data_root / "data_source_qa.json"
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
    supplied_source_answer_fields = {
        "source_vendor": source_vendor,
        "source_terminal": source_terminal,
        "source_operator": source_operator,
        "source_exported_at": source_exported_at,
        "source_price_adjustment": source_price_adjustment,
        "source_price_adjustment_evidence": source_price_adjustment_evidence,
        "source_license_evidence": source_license_evidence,
        "source_point_in_time_evidence": source_point_in_time_evidence,
        "source_reviewed_by": source_reviewed_by,
        "source_reviewed_at": source_reviewed_at,
    }
    if any(value is not None for value in supplied_source_answer_fields.values()):
        missing_fields = [
            name for name, value in supplied_source_answer_fields.items() if not str(value or "").strip()
        ]
        if missing_fields:
            steps.append(
                OfflineIntakeStep(
                    "source_qa_answers",
                    "BLOCK",
                    str(answers_path),
                    f"Missing required source QA answer fields: {', '.join(missing_fields)}",
                )
            )
            return _final_report(
                data_dir=data_root,
                config_path=config_path,
                cache=cache,
                start=resolved_start,
                end=resolved_end,
                min_symbols=min_symbols,
                steps=steps,
                output_dir=out,
                next_actions=[
                    "Provide every --source-* evidence argument, or write data_source_qa_answers.json separately."
                ],
            )
        if not checklist_path.exists():
            steps.append(
                OfflineIntakeStep(
                    "source_qa_answers",
                    "BLOCK",
                    str(answers_path),
                    "data_source_qa.json is required before source QA answers can be generated.",
                )
            )
            return _final_report(
                data_dir=data_root,
                config_path=config_path,
                cache=cache,
                start=resolved_start,
                end=resolved_end,
                min_symbols=min_symbols,
                steps=steps,
                output_dir=out,
                next_actions=["Run write_data_source_qa.py, then rerun offline intake with source evidence."],
            )
        answers = build_data_source_qa_answers(
            checklist_path=checklist_path,
            data_vendor_or_broker=str(source_vendor),
            terminal_or_product_name=str(source_terminal),
            export_operator=str(source_operator),
            exported_at_local_time=str(source_exported_at),
            price_adjustment=str(source_price_adjustment),
            price_adjustment_evidence=str(source_price_adjustment_evidence),
            license_or_usage_scope=source_license_scope,
            license_evidence=str(source_license_evidence),
            point_in_time_evidence=str(source_point_in_time_evidence),
            reviewed_by=str(source_reviewed_by),
            reviewed_at=str(source_reviewed_at),
            encoding=encoding,
            known_limitations=source_known_limitations,
        )
        write_data_source_qa_answers(answers, answers_path)
        steps.append(
            OfflineIntakeStep(
                "source_qa_answers",
                "PASS",
                str(answers_path),
                "Wrote source QA answers from explicit user-supplied evidence fields.",
            )
        )
    should_review_source_qa = (
        checklist_path.exists()
        or source_qa_checklist is not None
        or source_qa_answers is not None
        or source_qa_evidence_manifest is not None
        or require_source_qa_evidence_manifest
    )
    if should_review_source_qa:
        source_qa_review = build_data_source_qa_review(
            checklist_path=checklist_path,
            answers_path=answers_path,
            evidence_manifest_path=review_evidence_manifest_path,
            require_evidence_manifest=require_source_qa_evidence_manifest,
        )
        write_data_source_qa_review(source_qa_review, out)
        steps.append(
            OfflineIntakeStep(
                "source_qa",
                source_qa_review.status,
                str(out / "data_source_qa_review.json"),
                _source_qa_message(source_qa_review.to_dict()),
            )
        )
        if source_qa_review.status == "BLOCK":
            return _final_report(
                data_dir=data_root,
                config_path=config_path,
                cache=cache,
                start=resolved_start,
                end=resolved_end,
                min_symbols=min_symbols,
                steps=steps,
                output_dir=out,
                next_actions=source_qa_review.next_actions,
            )

    doctor = build_data_import_doctor(
        data_dir=data_root,
        config_path=config_path,
        cache_path=cache,
        start=resolved_start,
        end=resolved_end,
        min_symbols=min_symbols,
        encoding=encoding,
    )
    write_data_import_doctor_report(doctor, out)
    steps.append(
        OfflineIntakeStep(
            "doctor",
            doctor.status,
            str(out / "data_import_doctor.json"),
            _doctor_message(doctor.to_dict()),
        )
    )
    if doctor.status == "BLOCK":
        return _final_report(
            data_dir=data_root,
            config_path=config_path,
            cache=cache,
            start=resolved_start,
            end=resolved_end,
            min_symbols=min_symbols,
            steps=steps,
            output_dir=out,
            next_actions=doctor.next_actions,
        )

    paths = _csv_paths(data_root)
    validation = validate_research_csvs(
        bars_csv=paths["bars"],
        stock_info_csv=paths["stock_info"] if paths["stock_info"].exists() else None,
        fundamentals_csv=paths["fundamentals"] if paths["fundamentals"].exists() else None,
        calendar_csv=paths["calendar"] if paths["calendar"].exists() else None,
        suspensions_csv=paths["suspensions"] if paths["suspensions"].exists() else None,
        index_constituents_csv=paths["index_constituents"] if paths["index_constituents"].exists() else None,
        start=resolved_start,
        end=resolved_end,
        min_symbols=min_symbols,
        encoding=encoding,
    )
    write_csv_validation_report(validation, out)
    steps.append(
        OfflineIntakeStep(
            "csv_validation",
            validation.status,
            str(out / "csv_validation.json"),
            _validation_message(validation.to_dict()),
        )
    )
    source_csv_review = None
    if should_review_source_qa:
        source_csv_review = build_data_source_qa_review(
            checklist_path=checklist_path,
            answers_path=answers_path,
            review_stage="csv_validation",
            validation_report_path=out / "csv_validation.json",
            evidence_manifest_path=review_evidence_manifest_path,
        )
        write_data_source_qa_review(source_csv_review, out)
        steps.append(
            OfflineIntakeStep(
                "source_csv_qa",
                source_csv_review.status,
                str(out / "data_source_csv_qa_review.json"),
                _source_qa_message(source_csv_review.to_dict()),
            )
        )
        if source_csv_review.status == "BLOCK":
            return _final_report(
                data_dir=data_root,
                config_path=config_path,
                cache=cache,
                start=resolved_start,
                end=resolved_end,
                min_symbols=min_symbols,
                steps=steps,
                output_dir=out,
                next_actions=source_csv_review.next_actions,
            )
    if validation.status == "BLOCK":
        return _final_report(
            data_dir=data_root,
            config_path=config_path,
            cache=cache,
            start=resolved_start,
            end=resolved_end,
            min_symbols=min_symbols,
            steps=steps,
            output_dir=out,
            next_actions=["Fix csv_validation.md BLOCK findings before writing the research cache."],
        )

    metadata = {
        "csv_validation_status": validation.status,
        "csv_dataset_fingerprint": validation.dataset_fingerprint,
        "csv_validation_report": str(out / "csv_validation.json"),
        "offline_intake_report": str(out / "offline_data_intake.json"),
    }
    metadata.update(_tdx_day_export_metadata(data_root))
    if source_qa_review is not None:
        metadata.update(
            {
                "data_source_qa_status": source_qa_review.status,
                "data_source_qa_review": str(out / "data_source_qa_review.json"),
                **_source_qa_provenance_metadata(
                    checklist_path=checklist_path,
                    answers_path=answers_path,
                    evidence_manifest_path=evidence_manifest_path,
                    require_evidence_manifest=require_source_qa_evidence_manifest,
                ),
            }
        )
    if normalization is not None:
        metadata.update(
            {
                "raw_vendor_bars_path": normalization.input_path,
                "raw_vendor_bars_sha256": normalization.raw_sha256,
                "raw_vendor_bars_size_bytes": normalization.raw_size_bytes,
                "raw_vendor_bars_modified_at_utc": normalization.raw_modified_at_utc,
                "vendor_bars_normalization_status": normalization.status,
                "vendor_bars_normalization_report": str(out / "vendor_bars_normalization.json"),
                "vendor_bars_normalized_output": normalization.output_bars_csv,
            }
        )
    if source_csv_review is not None:
        metadata.update(
            {
                "data_source_csv_qa_status": source_csv_review.status,
                "data_source_csv_qa_review": str(out / "data_source_csv_qa_review.json"),
            }
        )
    import_report = import_research_csvs(
        BarStorage(cache),
        bars_csv=paths["bars"],
        stock_info_csv=paths["stock_info"] if paths["stock_info"].exists() else None,
        fundamentals_csv=paths["fundamentals"] if paths["fundamentals"].exists() else None,
        calendar_csv=paths["calendar"] if paths["calendar"].exists() else None,
        suspensions_csv=paths["suspensions"] if paths["suspensions"].exists() else None,
        index_constituents_csv=paths["index_constituents"] if paths["index_constituents"].exists() else None,
        index_code=str(getattr(cfg.universe, "index_code", "000906")),
        encoding=encoding,
        metadata=metadata,
    )
    if validation.status == "WATCH" and import_report.status == "PASS":
        import_report = replace(import_report, status="WATCH")
    write_import_report(import_report, out)
    import_status = _normalize(import_report.status)
    steps.append(
        OfflineIntakeStep(
            "import",
            import_status,
            str(out / "data_import.json"),
            f"imported_symbols={import_report.imported_symbols}, bar_rows={import_report.bar_rows}",
        )
    )
    if import_status == "BLOCK":
        return _final_report(
            data_dir=data_root,
            config_path=config_path,
            cache=cache,
            start=resolved_start,
            end=resolved_end,
            min_symbols=min_symbols,
            steps=steps,
            output_dir=out,
            next_actions=["Fix data_import.md failures before running bootstrap."],
        )

    bootstrap = build_real_data_bootstrap_report(
        DataProvider(BarStorage(cache)),
        cfg,
        config_path=config_path,
        cache_path=cache,
        as_of=as_of,
        min_symbols=min_symbols,
        min_trading_days=min_trading_days,
        max_staleness_days=max_staleness_days,
        min_coverage_ratio=min_coverage_ratio,
        cache_exists_before_open=cache.exists(),
        cache_size_before_open=cache.stat().st_size if cache.exists() else 0,
    )
    write_real_data_bootstrap_report(bootstrap, out)
    steps.append(
        OfflineIntakeStep(
            "real_data_bootstrap",
            bootstrap.decision,
            str(out / "real_data_bootstrap.json"),
            f"symbols={bootstrap.symbol_count}, trading_days={bootstrap.trading_day_count}, latest={bootstrap.latest_bar_date or 'missing'}",
        )
    )
    next_actions = (
        ["Run weekly pipeline on the imported cache only after reviewing all WATCH evidence."]
        if bootstrap.decision != "BLOCK"
        else ["Fix real_data_bootstrap.md BLOCK findings before strategy research."]
    )
    return _final_report(
        data_dir=data_root,
        config_path=config_path,
        cache=cache,
        start=resolved_start,
        end=resolved_end,
        min_symbols=min_symbols,
        steps=steps,
        output_dir=out,
        next_actions=next_actions,
    )


def write_offline_data_intake_report(report: OfflineDataIntakeReport, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "offline_data_intake.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "offline_data_intake.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _final_report(
    *,
    data_dir: Path,
    config_path: str | Path,
    cache: Path,
    start: str,
    end: str,
    min_symbols: int,
    steps: list[OfflineIntakeStep],
    output_dir: Path,
    next_actions: list[str],
) -> OfflineDataIntakeReport:
    report = OfflineDataIntakeReport(
        status=_combine([step.status for step in steps]),
        data_dir=str(data_dir),
        config_path=str(config_path),
        cache_path=str(cache),
        start=start,
        end=end,
        min_symbols=min_symbols,
        steps=steps,
        next_actions=next_actions,
        prohibited_actions=[
            "Do not import template sample rows into the research cache.",
            "Do not run strategy research while this intake report is BLOCK.",
            "Do not connect offline CSV intake to a real broker order workflow.",
            "Do not treat imported data or a backtest as a promise of profit.",
        ],
    )
    write_offline_data_intake_report(report, output_dir)
    return report


def _csv_paths(data_dir: Path) -> dict[str, Path]:
    return {
        "bars": data_dir / "bars.csv",
        "stock_info": data_dir / "stock_info.csv",
        "fundamentals": data_dir / "fundamentals.csv",
        "calendar": data_dir / "calendar.csv",
        "suspensions": data_dir / "suspensions.csv",
        "index_constituents": data_dir / "index_constituents.csv",
    }


def _tdx_day_export_metadata(data_dir: Path) -> dict[str, Any]:
    report_path = data_dir / "tdx_day_export.json"
    if not report_path.exists():
        return {}
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    status = _normalize(payload.get("status", "BLOCK"))
    if status == "BLOCK":
        return {}
    return {
        "tdx_day_export_report": str(report_path),
        "tdx_day_export_sha256": _file_sha256(report_path),
        "tdx_day_export_status": status,
        "tdx_day_input_dir": str(payload.get("input_dir", "") or ""),
        "tdx_day_symbol_count": int(payload.get("symbol_count", 0) or 0),
        "tdx_day_row_count": int(payload.get("row_count", 0) or 0),
        "tdx_day_start": str(payload.get("start", "") or ""),
        "tdx_day_end": str(payload.get("end", "") or ""),
        "tdx_day_discovered_files": int(payload.get("discovered_files", 0) or 0),
        "tdx_day_converted_files": int(payload.get("converted_files", 0) or 0),
    }


def _source_qa_provenance_metadata(
    *,
    checklist_path: Path,
    answers_path: Path,
    evidence_manifest_path: Path,
    require_evidence_manifest: bool,
) -> dict[str, str]:
    metadata = {
        "data_source_qa_checklist_path": str(checklist_path),
        "data_source_qa_checklist_sha256": _file_sha256(checklist_path),
        "data_source_qa_answers_path": str(answers_path),
        "data_source_qa_answers_sha256": _file_sha256(answers_path),
        "data_source_qa_require_evidence_manifest": str(require_evidence_manifest),
    }
    if evidence_manifest_path.exists():
        metadata.update(
            {
                "data_source_qa_evidence_manifest_path": str(evidence_manifest_path),
                "data_source_qa_evidence_manifest_sha256": _file_sha256(evidence_manifest_path),
            }
        )
    return metadata


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _doctor_message(payload: dict[str, Any]) -> str:
    findings = payload.get("findings", []) or []
    blocks = [finding for finding in findings if finding.get("severity") == "BLOCK"]
    if blocks:
        first = blocks[0]
        return f"{first.get('code')}: {first.get('message')}"
    return "Data import doctor completed without BLOCK findings."


def _validation_message(payload: dict[str, Any]) -> str:
    metrics = payload.get("metrics", {}) or {}
    return (
        f"symbols={metrics.get('bars_symbol_count', 0)}, "
        f"bars_start={metrics.get('bars_start', '')}, bars_end={metrics.get('bars_end', '')}"
    )


def _normalization_message(payload: dict[str, Any]) -> str:
    findings = payload.get("findings", []) or []
    blocks = [finding for finding in findings if finding.get("severity") == "BLOCK"]
    if blocks:
        first = blocks[0]
        return f"{first.get('code')}: {first.get('message')}"
    return (
        f"rows={payload.get('normalized_row_count', 0)}, "
        f"symbols={payload.get('symbol_count', 0)}, "
        f"period={payload.get('normalized_start', '')} to {payload.get('normalized_end', '')}"
    )


def _source_qa_message(payload: dict[str, Any]) -> str:
    findings = payload.get("findings", []) or []
    blocks = [finding for finding in findings if finding.get("severity") == "BLOCK"]
    if blocks:
        first = blocks[0]
        return f"{first.get('code')}: {first.get('message')}"
    watches = [finding for finding in findings if finding.get("severity") == "WATCH"]
    if watches:
        first = watches[0]
        return f"{first.get('code')}: {first.get('message')}"
    return "Data source QA review completed without BLOCK or WATCH findings."


def _normalize(status: str) -> IntakeStatus:
    text = str(status).upper()
    if text == "PASS":
        return "PASS"
    if text == "WATCH":
        return "WATCH"
    return "BLOCK"


def _combine(statuses: list[IntakeStatus]) -> IntakeStatus:
    if any(status == "BLOCK" for status in statuses):
        return "BLOCK"
    if any(status == "WATCH" for status in statuses):
        return "WATCH"
    return "PASS"
