"""Readiness card for an offline A-share data package."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from quantify.data.csv_contract import RESEARCH_CSV_SCHEMAS
from quantify.data.import_doctor import build_data_import_doctor
from quantify.data.source_qa import build_data_source_qa_review
from quantify.utils.config import load_config

PackageStatus = Literal["PASS", "WATCH", "BLOCK"]

_SOURCE_METADATA_KEYS = (
    "data_vendor_or_broker",
    "terminal_or_product_name",
    "export_operator",
    "exported_at_local_time",
    "market",
    "frequency",
    "date_range",
    "price_adjustment",
    "encoding",
    "license_or_usage_scope",
    "known_limitations",
    "reviewed_by",
    "reviewed_at",
)

_SOURCE_EVIDENCE_KEYS = {
    "source_identity": "source_identity_evidence",
    "price_adjustment": "price_adjustment_evidence",
    "license_scope": "license_scope_evidence",
    "point_in_time": "point_in_time_evidence",
    "manual_signoff": "manual_signoff_evidence",
}


@dataclass(frozen=True, slots=True)
class OfflineDataPackageItem:
    name: str
    status: PackageStatus
    artifact: str
    message: str
    next_action: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "artifact": self.artifact,
            "message": self.message,
            "next_action": self.next_action,
        }


@dataclass(frozen=True, slots=True)
class OfflineDataPackageReport:
    status: PackageStatus
    data_dir: str
    config_path: str
    source_qa_answers_path: str
    source_qa_evidence_manifest_path: str
    require_source_qa_evidence_manifest: bool
    as_of: str | None
    min_symbols: int
    items: list[OfflineDataPackageItem]
    csv_files: list[dict[str, Any]]
    source_metadata_summary: dict[str, Any]
    next_actions: list[str]
    next_commands: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "data_dir": self.data_dir,
            "config_path": self.config_path,
            "source_qa_answers_path": self.source_qa_answers_path,
            "source_qa_evidence_manifest_path": self.source_qa_evidence_manifest_path,
            "require_source_qa_evidence_manifest": self.require_source_qa_evidence_manifest,
            "as_of": self.as_of,
            "min_symbols": self.min_symbols,
            "items": [item.to_dict() for item in self.items],
            "csv_files": self.csv_files,
            "source_metadata_summary": self.source_metadata_summary,
            "next_actions": self.next_actions,
            "next_commands": self.next_commands,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Offline Data Package: {self.status}",
            "",
            f"- Data directory: `{self.data_dir}`",
            f"- Config: `{self.config_path}`",
            f"- Source QA answers: `{self.source_qa_answers_path}`",
            f"- Source QA evidence manifest: `{self.source_qa_evidence_manifest_path or 'not supplied'}`",
            f"- Require source QA evidence manifest: `{self.require_source_qa_evidence_manifest}`",
            f"- As of: `{self.as_of or 'unspecified'}`",
            f"- Minimum symbols: {self.min_symbols}",
            "",
            "This report checks whether an offline CSV data batch is ready for guarded intake.",
            "It is not a strategy recommendation, backtest result, or live trading permission.",
            "",
            "## Package Items",
            "",
            "| item | status | artifact | message | next action |",
            "| --- | --- | --- | --- | --- |",
        ]
        for item in self.items:
            lines.append(
                f"| `{item.name}` | `{item.status}` | `{item.artifact}` | "
                f"{item.message} | {item.next_action} |"
            )
        lines.extend(
            [
                "",
                "## CSV Files",
                "",
                "| role | exists | rows | symbols | period | sha256 | path |",
                "| --- | --- | ---: | ---: | --- | --- | --- |",
            ]
        )
        for item in self.csv_files:
            period = f"{item.get('start', '') or '-'} to {item.get('end', '') or '-'}"
            digest = str(item.get("sha256", ""))[:12] or "-"
            lines.append(
                f"| `{item.get('role', '')}` | `{item.get('exists', False)}` | "
                f"{item.get('row_count', 0)} | {item.get('symbol_count', 0)} | "
                f"`{period}` | `{digest}` | `{item.get('path', '')}` |"
            )
        lines.extend(["", "## Source Metadata Summary"])
        for key, value in self.source_metadata_summary.items():
            lines.append(f"- `{key}`: `{value}`")
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Next Commands"])
        lines.extend(f"- `{command}`" for command in self.next_commands)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_offline_data_package_report(
    *,
    data_dir: str | Path = "data_exports",
    config_path: str | Path = "config/research_recent.yaml",
    source_qa_answers: str | Path | None = None,
    source_qa_evidence_manifest: str | Path | None = None,
    require_source_qa_evidence_manifest: bool = False,
    min_symbols: int = 300,
    as_of: str | None = None,
    encoding: str = "utf-8-sig",
) -> OfflineDataPackageReport:
    root = Path(data_dir)
    cfg = load_config(config_path)
    answers_path = Path(source_qa_answers) if source_qa_answers else root / "data_source_qa_answers.json"
    checklist_path = root / "data_source_qa.json"
    evidence_manifest_path = (
        Path(source_qa_evidence_manifest)
        if source_qa_evidence_manifest
        else root / "source_qa_evidence_manifest.json"
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

    source_review = build_data_source_qa_review(
        checklist_path=checklist_path,
        answers_path=answers_path,
        evidence_manifest_path=review_evidence_manifest_path,
        require_evidence_manifest=require_source_qa_evidence_manifest,
    )
    doctor = build_data_import_doctor(
        data_dir=root,
        config_path=config_path,
        cache_path=cfg.data.cache_path,
        start=cfg.research.start,
        end=cfg.research.end,
        min_symbols=min_symbols,
        encoding=encoding,
    )
    doctor_payload = doctor.to_dict()
    source_payload = source_review.to_dict()
    items = [
        _checklist_item(checklist_path),
        _answers_item(answers_path),
        _source_review_item(source_payload, answers_path),
        _evidence_manifest_item(
            source_payload,
            evidence_manifest_path=review_evidence_manifest_path,
            require_manifest=require_source_qa_evidence_manifest,
        ),
        _csv_inventory_item(doctor_payload),
        _template_item(doctor_payload),
        _doctor_item(doctor_payload),
    ]
    status = _combine([item.status for item in items])
    return OfflineDataPackageReport(
        status=status,
        data_dir=str(root),
        config_path=str(config_path),
        source_qa_answers_path=str(answers_path),
        source_qa_evidence_manifest_path=str(review_evidence_manifest_path or ""),
        require_source_qa_evidence_manifest=require_source_qa_evidence_manifest,
        as_of=as_of,
        min_symbols=min_symbols,
        items=items,
        csv_files=_csv_files(doctor_payload, root),
        source_metadata_summary=_source_metadata_summary(source_payload, answers_path),
        next_actions=_next_actions(items),
        next_commands=_next_commands(
            config_path=config_path,
            data_dir=root,
            answers_path=answers_path,
            evidence_manifest_path=evidence_manifest_path,
            require_evidence_manifest=require_source_qa_evidence_manifest,
            min_symbols=min_symbols,
            as_of=as_of,
        ),
        prohibited_actions=[
            "Do not run strategy experiments while this data package is BLOCK.",
            "Do not use generated CSV template rows as real A-share evidence.",
            "Do not fill source QA answers without real vendor/export evidence.",
            "Do not bypass strict source QA evidence attachment review when it is required.",
            "Do not treat a package PASS as profitability evidence.",
            "Do not connect this package workflow to real broker order submission.",
        ],
    )


def write_offline_data_package_report(
    report: OfflineDataPackageReport,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "offline_data_package.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "offline_data_package.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _checklist_item(path: Path) -> OfflineDataPackageItem:
    if path.exists() and path.stat().st_size > 0:
        return OfflineDataPackageItem(
            "source_qa_checklist",
            "PASS",
            str(path),
            "Data source QA checklist exists.",
            "Keep checklist with the data package.",
        )
    return OfflineDataPackageItem(
        "source_qa_checklist",
        "BLOCK",
        str(path),
        "data_source_qa.json is missing.",
        "Run write_data_source_qa.py before filling source QA answers.",
    )


def _answers_item(path: Path) -> OfflineDataPackageItem:
    if path.exists() and path.stat().st_size > 0:
        return OfflineDataPackageItem(
            "source_qa_answers",
            "PASS",
            str(path),
            "Source QA answers file exists.",
            "Review source QA findings before intake.",
        )
    return OfflineDataPackageItem(
        "source_qa_answers",
        "BLOCK",
        str(path),
        "data_source_qa_answers.json is missing or empty.",
        "Fill source QA answers with real vendor/export evidence.",
    )


def _source_review_item(payload: dict[str, Any], answers_path: Path) -> OfflineDataPackageItem:
    status = _normalize(payload.get("status"))
    if status == "PASS":
        return OfflineDataPackageItem(
            "source_qa_review",
            "PASS",
            str(answers_path),
            "Source QA review passes.",
            "Continue to CSV inventory and import doctor checks.",
        )
    return OfflineDataPackageItem(
        "source_qa_review",
        status,
        str(answers_path),
        _first_finding_message(payload),
        _first(payload.get("next_actions", []), "Resolve source QA findings."),
    )


def _evidence_manifest_item(
    payload: dict[str, Any],
    *,
    evidence_manifest_path: Path | None,
    require_manifest: bool,
) -> OfflineDataPackageItem:
    if evidence_manifest_path is None and not require_manifest:
        return OfflineDataPackageItem(
            "source_qa_evidence_manifest",
            "PASS",
            "",
            "Strict source QA evidence manifest is not required for this package run.",
            "Use --require-source-qa-evidence-manifest before guarded real-data intake.",
        )
    manifest_findings = [
        item
        for item in payload.get("findings", []) or []
        if isinstance(item, dict) and str(item.get("code", "")).startswith("SOURCE_QA_EVIDENCE_")
    ]
    if manifest_findings:
        first = manifest_findings[0]
        severity = _normalize(first.get("severity"))
        return OfflineDataPackageItem(
            "source_qa_evidence_manifest",
            severity,
            str(evidence_manifest_path or ""),
            f"{first.get('code')}: {first.get('message')}",
            "Attach real retained evidence files, regenerate source_qa_evidence_manifest.json, then rerun the package report.",
        )
    if require_manifest:
        return OfflineDataPackageItem(
            "source_qa_evidence_manifest",
            "PASS",
            str(evidence_manifest_path or ""),
            "Strict source QA evidence manifest passes.",
            "Keep manifest and local evidence files immutable with this export batch.",
        )
    return OfflineDataPackageItem(
        "source_qa_evidence_manifest",
        "WATCH",
        str(evidence_manifest_path or ""),
        "Source QA evidence manifest was supplied but strict mode is not enabled.",
        "Review supplied attachments before guarded intake.",
    )


def _csv_inventory_item(payload: dict[str, Any]) -> OfflineDataPackageItem:
    missing_required = [str(item) for item in payload.get("missing_required_files", []) or []]
    missing_recommended = [str(item) for item in payload.get("missing_recommended_files", []) or []]
    if missing_required:
        return OfflineDataPackageItem(
            "csv_inventory",
            "BLOCK",
            ", ".join(missing_required),
            "Required CSV files are missing.",
            "Export or create required CSV files before source intake.",
        )
    if missing_recommended:
        return OfflineDataPackageItem(
            "csv_inventory",
            "WATCH",
            ", ".join(missing_recommended),
            "Recommended CSV files are missing.",
            "Add recommended files for audit depth or document why they are unavailable.",
        )
    return OfflineDataPackageItem(
        "csv_inventory",
        "PASS",
        str(payload.get("data_dir", "")),
        "All expected CSV files exist.",
        "Keep the export batch unchanged after validation.",
    )


def _template_item(payload: dict[str, Any]) -> OfflineDataPackageItem:
    finding = _finding(payload, "TEMPLATE_EXPORT_UNREPLACED")
    if finding:
        files = [str(item) for item in (finding.get("evidence", {}) or {}).get("template_files", [])]
        return OfflineDataPackageItem(
            "csv_template_rows",
            "BLOCK",
            ", ".join(files),
            "One or more CSV files still contain generated template sample rows.",
            "Replace every template row with recent real A-share daily exports.",
        )
    return OfflineDataPackageItem(
        "csv_template_rows",
        "PASS",
        str(payload.get("data_dir", "")),
        "No generated template sample rows were detected.",
        "Keep the validated export batch immutable.",
    )


def _doctor_item(payload: dict[str, Any]) -> OfflineDataPackageItem:
    status = _normalize(payload.get("status"))
    if status == "PASS":
        return OfflineDataPackageItem(
            "import_doctor",
            "PASS",
            "data_import_doctor.json",
            "Data import doctor has no BLOCK or WATCH findings.",
            "Run guarded offline intake.",
        )
    return OfflineDataPackageItem(
        "import_doctor",
        status,
        "data_import_doctor.json",
        _first_finding_message(payload),
        _first(payload.get("next_actions", []), "Fix import doctor findings."),
    )


def _csv_files(payload: dict[str, Any], data_dir: Path) -> list[dict[str, Any]]:
    validation = payload.get("validation", {}) if isinstance(payload.get("validation"), dict) else {}
    files = validation.get("files", []) if isinstance(validation, dict) else []
    if files:
        return [item for item in files if isinstance(item, dict)]
    return [
        {
            "role": schema.role,
            "path": str(data_dir / schema.file_name),
            "required": schema.required,
            "exists": (data_dir / schema.file_name).exists(),
            "row_count": 0,
            "symbol_count": 0,
            "start": "",
            "end": "",
            "sha256": "",
        }
        for schema in RESEARCH_CSV_SCHEMAS
    ]


def format_source_provenance(summary: dict[str, Any]) -> str:
    """Return a compact human provenance line from source metadata summary."""
    vendor = _present_summary(summary, "data_vendor_or_broker")
    terminal = _present_summary(summary, "terminal_or_product_name")
    exported_at = _present_summary(summary, "exported_at_local_time")
    adjustment = _present_summary(summary, "price_adjustment")
    reviewed_by = _present_summary(summary, "reviewed_by")
    reviewed_at = _present_summary(summary, "reviewed_at")
    parts = []
    if vendor or terminal:
        parts.append(f"source={vendor or 'unknown'} / {terminal or 'unknown'}")
    if exported_at:
        parts.append(f"exported_at={exported_at}")
    if adjustment:
        parts.append(f"adjustment={adjustment}")
    if reviewed_by or reviewed_at:
        parts.append(f"reviewed_by={reviewed_by or 'unknown'} at {reviewed_at or 'unknown'}")
    return "; ".join(parts)


def _source_metadata_summary(payload: dict[str, Any], answers_path: Path) -> dict[str, Any]:
    metadata = payload.get("source_metadata", {}) if isinstance(payload, dict) else {}
    missing = payload.get("missing_metadata", []) if isinstance(payload, dict) else []
    metadata = metadata if isinstance(metadata, dict) else {}
    fields = sorted(key for key, value in metadata.items() if str(value).strip())
    summary: dict[str, Any] = {
        "review_status": str(payload.get("status", "UNKNOWN")),
    }
    for key in _SOURCE_METADATA_KEYS:
        summary[key] = _source_value(metadata, key)
    answers = _read_json(answers_path)
    answer_map = answers.get("answers", {}) if isinstance(answers, dict) else {}
    answer_map = answer_map if isinstance(answer_map, dict) else {}
    for item_id, summary_key in _SOURCE_EVIDENCE_KEYS.items():
        summary[summary_key] = _answer_evidence(answer_map, item_id)
    summary.update(
        {
            "source_identity": _source_identity(summary),
            "human_review": _human_review(summary),
            "field_count": len(fields),
            "filled_fields": ", ".join(fields) if fields else "",
            "missing_metadata": ", ".join(str(item) for item in missing) if missing else "",
        }
    )
    return summary


def _source_value(metadata: dict[str, Any], key: str) -> str:
    return str(metadata.get(key, "") or "").strip() or "unspecified"


def _answer_evidence(answer_map: dict[str, Any], item_id: str) -> str:
    answer = answer_map.get(item_id, {})
    if not isinstance(answer, dict):
        return "unspecified"
    return str(answer.get("evidence", "") or "").strip() or "unspecified"


def _source_identity(summary: dict[str, Any]) -> str:
    vendor = _present_summary(summary, "data_vendor_or_broker")
    terminal = _present_summary(summary, "terminal_or_product_name")
    if vendor and terminal:
        return f"{vendor} / {terminal}"
    if vendor or terminal:
        return vendor or terminal
    return "unspecified"


def _human_review(summary: dict[str, Any]) -> str:
    reviewed_by = _present_summary(summary, "reviewed_by")
    reviewed_at = _present_summary(summary, "reviewed_at")
    if reviewed_by and reviewed_at:
        return f"{reviewed_by} at {reviewed_at}"
    if reviewed_by or reviewed_at:
        return reviewed_by or reviewed_at
    return "unspecified"


def _present_summary(summary: dict[str, Any], key: str) -> str:
    value = str(summary.get(key, "") or "").strip()
    return "" if value.lower() in {"", "none", "unspecified"} else value


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _next_actions(items: list[OfflineDataPackageItem]) -> list[str]:
    status_by_name = {item.name: item.status for item in items}
    actions: list[str] = []
    if status_by_name.get("source_qa_checklist") == "BLOCK":
        actions.append("Generate data_source_qa.json for the export batch.")
    if (
        status_by_name.get("source_qa_answers") == "BLOCK"
        or status_by_name.get("source_qa_review") == "BLOCK"
    ):
        actions.append("Fill data_source_qa_answers.json with real vendor/export evidence.")
    if status_by_name.get("source_qa_evidence_manifest") == "BLOCK":
        actions.append(
            "Prepare source QA evidence attachments using source_qa_evidence_attachment_plan.csv, then regenerate source_qa_evidence_manifest.json."
        )
    if status_by_name.get("csv_inventory") == "BLOCK":
        actions.append("Place required CSV exports in data_exports before validation.")
    if status_by_name.get("csv_template_rows") == "BLOCK":
        actions.append("Replace generated template rows with recent real A-share daily exports.")
    if status_by_name.get("import_doctor") == "BLOCK":
        actions.append("Rerun data import doctor after fixing source and CSV blockers.")
    if not actions and any(item.status == "WATCH" for item in items):
        actions.append("Review WATCH package evidence before guarded offline intake.")
    if not actions:
        actions.append("Run guarded offline data intake, then rerun first-million pipeline.")
    return actions


def _next_commands(
    *,
    config_path: str | Path,
    data_dir: Path,
    answers_path: Path,
    evidence_manifest_path: Path,
    require_evidence_manifest: bool,
    min_symbols: int,
    as_of: str | None,
) -> list[str]:
    as_of_arg = f" --as-of {as_of}" if as_of else ""
    manifest_args = (
        f" --source-qa-evidence-manifest {evidence_manifest_path}"
        if evidence_manifest_path
        else ""
    )
    require_manifest_arg = " --require-source-qa-evidence-manifest" if require_evidence_manifest else ""
    return [
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa.py "
            f"--config {config_path} --output-dir {data_dir} --min-symbols {min_symbols}{as_of_arg}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa_evidence_worksheet.py "
            f"--checklist {data_dir / 'data_source_qa.json'} --output-dir {data_dir}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_data_source_qa_worksheet_preflight.py "
            f"--checklist {data_dir / 'data_source_qa.json'} "
            f"--worksheet {data_dir / 'data_source_qa_evidence_worksheet.csv'} --output-dir {data_dir}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_source_qa_evidence_manifest.py "
            f"--checklist {data_dir / 'data_source_qa.json'} "
            f"--evidence-dir {data_dir / 'source_qa_evidence'} --output-dir {data_dir} --strict"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa_answers.py "
            f"--checklist {data_dir / 'data_source_qa.json'} "
            f"--worksheet {data_dir / 'data_source_qa_evidence_worksheet.csv'} "
            f"--output {answers_path} "
            f"--evidence-manifest {evidence_manifest_path} --require-evidence-manifest"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\normalize_vendor_bars.py "
            f"--input <raw-vendor-bars.csv> --output-dir {data_dir} "
            f"--min-symbols {min_symbols}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_offline_data_package.py "
            f"--data-dir {data_dir} --config {config_path} --source-qa-answers {answers_path} "
            f"{manifest_args}{require_manifest_arg} --min-symbols {min_symbols}{as_of_arg}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_offline_data_intake.py "
            f"--raw-bars-csv <raw-vendor-bars.csv> --data-dir {data_dir} "
            f"--config {config_path} --source-qa-answers {answers_path} "
            "--source-vendor <vendor-or-broker> --source-terminal <terminal-name> "
            "--source-operator <operator> --source-exported-at <local-time> "
            "--source-price-adjustment qfq --source-price-adjustment-evidence <evidence> "
            "--source-license-evidence <evidence> "
            "--source-point-in-time-evidence <evidence-or-non-pit-note> "
            "--source-reviewed-by <name> --source-reviewed-at <date> "
            f"--min-symbols {min_symbols} --min-trading-days 240{as_of_arg}"
        ),
    ]


def _finding(payload: dict[str, Any], code: str) -> dict[str, Any]:
    for finding in payload.get("findings", []) or []:
        if isinstance(finding, dict) and finding.get("code") == code:
            return finding
    return {}


def _first_finding_message(payload: dict[str, Any]) -> str:
    findings = payload.get("findings", []) or []
    if findings and isinstance(findings[0], dict):
        first = findings[0]
        code = str(first.get("code", "FINDING"))
        message = str(first.get("message", "Package evidence requires review."))
        return f"{code}: {message}"
    return "Package evidence requires review."


def _first(values: object, default: str) -> str:
    if isinstance(values, list) and values:
        return str(values[0])
    return default


def _combine(statuses: list[PackageStatus]) -> PackageStatus:
    if any(status == "BLOCK" for status in statuses):
        return "BLOCK"
    if any(status == "WATCH" for status in statuses):
        return "WATCH"
    return "PASS"


def _normalize(value: object) -> PackageStatus:
    text = str(value or "").upper()
    if text == "PASS":
        return "PASS"
    if text == "WATCH":
        return "WATCH"
    return "BLOCK"
