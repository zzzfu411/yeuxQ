"""Action plan for closing first-million data evidence gaps."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from quantify.data.csv_contract import RESEARCH_CSV_SCHEMAS
from quantify.data.import_doctor import build_data_import_doctor
from quantify.data.source_qa import build_data_source_qa_review, placeholder_source_metadata_fields
from quantify.data.source_qa_preflight import build_source_qa_preflight
from quantify.utils.config import load_config

DataGapStatus = Literal["PASS", "WATCH", "BLOCK"]

REQUIRED_SOURCE_METADATA = [
    "data_vendor_or_broker",
    "terminal_or_product_name",
    "export_operator",
    "exported_at_local_time",
    "price_adjustment",
    "license_or_usage_scope",
    "reviewed_by",
    "reviewed_at",
]


@dataclass(frozen=True, slots=True)
class DataGapItem:
    name: str
    status: DataGapStatus
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
class DataGapActionPlan:
    decision: DataGapStatus
    data_dir: str
    config_path: str
    source_qa_answers_path: str
    as_of: str | None
    items: list[DataGapItem]
    required_source_metadata: list[str]
    expected_csv_files: list[dict[str, Any]]
    next_actions: list[str]
    next_commands: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "data_dir": self.data_dir,
            "config_path": self.config_path,
            "source_qa_answers_path": self.source_qa_answers_path,
            "as_of": self.as_of,
            "items": [item.to_dict() for item in self.items],
            "required_source_metadata": self.required_source_metadata,
            "expected_csv_files": self.expected_csv_files,
            "next_actions": self.next_actions,
            "next_commands": self.next_commands,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Data Gap Action Plan: {self.decision}",
            "",
            f"- Data directory: `{self.data_dir}`",
            f"- Config: `{self.config_path}`",
            f"- Source QA answers: `{self.source_qa_answers_path}`",
            f"- As of: `{self.as_of or 'unspecified'}`",
            "",
            "## Gap Items",
            "",
            "| item | status | artifact | message | next action |",
            "| --- | --- | --- | --- | --- |",
        ]
        for item in self.items:
            lines.append(
                f"| `{item.name}` | `{item.status}` | `{item.artifact}` | "
                f"{item.message} | {item.next_action} |"
            )
        lines.extend(["", "## Required Source Metadata"])
        lines.extend(f"- `{field}`" for field in self.required_source_metadata)
        lines.extend(["", "## Expected CSV Files", ""])
        lines.append("| file | required | columns |")
        lines.append("| --- | --- | --- |")
        for file_item in self.expected_csv_files:
            required = "yes" if file_item["required"] else "recommended"
            lines.append(
                f"| `{file_item['file_name']}` | `{required}` | `{', '.join(file_item['columns'])}` |"
            )
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Next Commands"])
        lines.extend(f"- `{command}`" for command in self.next_commands)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_data_gap_action_plan(
    *,
    data_dir: str | Path = "data_exports",
    config_path: str | Path = "config/research_recent.yaml",
    source_qa_answers: str | Path | None = None,
    min_symbols: int = 300,
    as_of: str | None = None,
    encoding: str = "utf-8-sig",
) -> DataGapActionPlan:
    root = Path(data_dir)
    cfg = load_config(config_path)
    answers_path = Path(source_qa_answers) if source_qa_answers else root / "data_source_qa_answers.json"
    checklist_path = root / "data_source_qa.json"
    items: list[DataGapItem] = []

    items.append(_data_dir_item(root))
    items.append(_answers_item(answers_path))
    items.append(_source_metadata_item(answers_path))
    items.append(_source_preflight_item(checklist_path, answers_path))
    items.append(_source_review_item(checklist_path, answers_path))

    doctor = build_data_import_doctor(
        data_dir=root,
        config_path=config_path,
        cache_path=cfg.data.cache_path,
        start=cfg.research.start,
        end=cfg.research.end,
        min_symbols=min_symbols,
        encoding=encoding,
    )
    tdx_report = _tdx_export_item(root)
    if tdx_report is not None:
        items.append(tdx_report)
    items.extend(_csv_file_items(root))
    items.append(_template_item(doctor.to_dict()))
    items.append(_doctor_item(doctor.to_dict()))

    decision = _combine([item.status for item in items])
    return DataGapActionPlan(
        decision=decision,
        data_dir=str(root),
        config_path=str(config_path),
        source_qa_answers_path=str(answers_path),
        as_of=as_of,
        items=items,
        required_source_metadata=REQUIRED_SOURCE_METADATA,
        expected_csv_files=[
            {
                "role": schema.role,
                "file_name": schema.file_name,
                "required": schema.required,
                "columns": schema.columns,
            }
            for schema in RESEARCH_CSV_SCHEMAS
        ],
        next_actions=_next_actions(items),
        next_commands=_next_commands(
            config_path=config_path,
            data_dir=root,
            answers_path=answers_path,
            min_symbols=min_symbols,
            as_of=as_of,
            tdx_detected=tdx_report is not None,
        ),
        prohibited_actions=[
            "Do not run candidate experiments while this plan is BLOCK.",
            "Do not use generated CSV template rows as real A-share evidence.",
            "Do not fill source QA answers without real vendor/export evidence.",
            "Do not treat a data gap PASS as a profitable strategy or live trading permission.",
            "Do not connect this data workflow to real broker order submission.",
        ],
    )


def write_data_gap_action_plan(plan: DataGapActionPlan, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "data_gap_action_plan.json").write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "data_gap_action_plan.md").write_text(plan.to_markdown(), encoding="utf-8")
    return root


def _data_dir_item(root: Path) -> DataGapItem:
    if root.exists():
        return DataGapItem("data_dir", "PASS", str(root), "Data export directory exists.", "Keep files immutable after validation.")
    return DataGapItem(
        "data_dir",
        "BLOCK",
        str(root),
        "Data export directory is missing.",
        "Create data_exports or rerun write_data_export_templates.py.",
    )


def _answers_item(path: Path) -> DataGapItem:
    if path.exists() and path.stat().st_size > 0:
        return DataGapItem(
            "source_qa_answers",
            "PASS",
            str(path),
            "Source QA answers file exists.",
            "Review source metadata and evidence quality.",
        )
    return DataGapItem(
        "source_qa_answers",
        "BLOCK",
        str(path),
        "data_source_qa_answers.json is missing or empty.",
        "Fill the source QA evidence worksheet, then write data_source_qa_answers.json with real vendor/export evidence.",
    )


def _source_metadata_item(path: Path) -> DataGapItem:
    payload = _read_json(path)
    metadata = payload.get("source_metadata", {}) if isinstance(payload, dict) else {}
    missing = [
        field
        for field in REQUIRED_SOURCE_METADATA
        if not str(metadata.get(field, "") if isinstance(metadata, dict) else "").strip()
    ]
    if not path.exists():
        return DataGapItem(
            "source_metadata",
            "BLOCK",
            str(path),
            "Source metadata cannot be checked because answers are missing.",
            "Fill all required source metadata fields from real export evidence.",
        )
    if missing:
        return DataGapItem(
            "source_metadata",
            "BLOCK",
            str(path),
            "Required source metadata fields are missing: " + ", ".join(missing),
            "Complete missing source metadata fields before offline intake.",
        )
    placeholders = placeholder_source_metadata_fields(metadata if isinstance(metadata, dict) else {})
    if placeholders:
        return DataGapItem(
            "source_metadata",
            "BLOCK",
            str(path),
            "Required source metadata fields contain placeholder values: "
            + ", ".join(placeholders),
            "Replace placeholder metadata with real vendor/export evidence.",
        )
    return DataGapItem(
        "source_metadata",
        "PASS",
        str(path),
        "Required source metadata fields are filled.",
        "Keep source evidence with the export batch.",
    )


def _source_preflight_item(checklist_path: Path, answers_path: Path) -> DataGapItem:
    report = build_source_qa_preflight(
        checklist_path=checklist_path,
        answers_path=answers_path,
        output_dir="results/import/source_qa",
    )
    if report.status == "PASS":
        return DataGapItem(
            "source_qa_preflight",
            "PASS",
            str(answers_path),
            "Source QA preflight has no unresolved source-stage gaps.",
            "Continue to deterministic source QA review.",
        )
    first = report.items[0] if report.items else None
    detail = f"{first.field}: {first.message}" if first is not None else "Source QA preflight is unresolved."
    return DataGapItem(
        "source_qa_preflight",
        report.status,
        str(answers_path),
        detail,
        "Resolve source QA preflight findings before source QA review or offline intake.",
    )


def _source_review_item(checklist_path: Path, answers_path: Path) -> DataGapItem:
    if not checklist_path.exists():
        return DataGapItem(
            "source_qa_review",
            "WATCH",
            str(checklist_path),
            "data_source_qa.json is missing; source QA checklist should be generated.",
            "Run write_data_source_qa.py before filling answers.",
        )
    review = build_data_source_qa_review(checklist_path=checklist_path, answers_path=answers_path)
    if review.status == "PASS":
        return DataGapItem(
            "source_qa_review",
            "PASS",
            str(answers_path),
            "Source QA review passes.",
            "Continue to CSV doctor and guarded offline intake.",
        )
    return DataGapItem(
        "source_qa_review",
        review.status,
        str(answers_path),
        _first_finding_message(review.to_dict()),
        "Resolve source QA findings before writing the research cache.",
    )


def _csv_file_items(root: Path) -> list[DataGapItem]:
    items: list[DataGapItem] = []
    for schema in RESEARCH_CSV_SCHEMAS:
        path = root / schema.file_name
        if path.exists():
            status: DataGapStatus = "PASS"
            message = f"{schema.file_name} exists."
            action = "Replace sample rows with real export rows if not already done."
        elif schema.required:
            status = "BLOCK"
            message = f"Required CSV file {schema.file_name} is missing."
            action = f"Export or create {schema.file_name} with required columns."
        else:
            status = "WATCH"
            message = f"Recommended CSV file {schema.file_name} is missing."
            action = f"Add {schema.file_name} for audit depth, or document why it is unavailable."
        items.append(DataGapItem(f"csv_{schema.role}", status, str(path), message, action))
    return items


def _tdx_export_item(root: Path) -> DataGapItem | None:
    path = root / "tdx_day_export.json"
    if not path.exists():
        return None
    payload = _read_json(path)
    status = _normalize_status(payload.get("status", "BLOCK"))
    symbols = int(payload.get("symbol_count", 0) or 0)
    rows = int(payload.get("row_count", 0) or 0)
    period = f"{payload.get('start', '') or 'missing'} to {payload.get('end', '') or 'missing'}"
    if status == "PASS":
        return DataGapItem(
            "tdx_day_export",
            "PASS",
            str(path),
            f"TDX .day conversion exists; symbols={symbols}, rows={rows}, period={period}.",
            "Fill TDX source QA with real license, adjustment, export-time, and human review evidence.",
        )
    if status == "WATCH":
        return DataGapItem(
            "tdx_day_export",
            "WATCH",
            str(path),
            f"TDX .day conversion has WATCH findings; symbols={symbols}, rows={rows}, period={period}.",
            "Review TDX conversion coverage before guarded offline intake.",
        )
    return DataGapItem(
        "tdx_day_export",
        "BLOCK",
        str(path),
        f"TDX .day conversion is BLOCK; symbols={symbols}, rows={rows}, period={period}.",
        "Fix TDX conversion before source QA or offline intake.",
    )


def _template_item(doctor_payload: dict[str, Any]) -> DataGapItem:
    template_finding = _finding(doctor_payload, "TEMPLATE_EXPORT_UNREPLACED")
    if template_finding:
        files = template_finding.get("evidence", {}).get("template_files", [])
        return DataGapItem(
            "csv_template_rows",
            "BLOCK",
            ", ".join(str(file) for file in files),
            "One or more CSV files still contain generated template sample rows.",
            "Replace every template sample row with recent real A-share daily exports.",
        )
    return DataGapItem(
        "csv_template_rows",
        "PASS",
        str(doctor_payload.get("data_dir", "")),
        "No generated template sample rows were detected by the import doctor.",
        "Keep the validated export batch unchanged.",
    )


def _doctor_item(doctor_payload: dict[str, Any]) -> DataGapItem:
    status = _normalize_status(doctor_payload.get("status", "BLOCK"))
    if status == "PASS":
        return DataGapItem(
            "import_doctor",
            "PASS",
            "data_import_doctor.json",
            "Data import doctor has no BLOCK or WATCH findings.",
            "Proceed to guarded offline intake after source QA passes.",
        )
    return DataGapItem(
        "import_doctor",
        status,
        "data_import_doctor.json",
        _first_finding_message(doctor_payload),
        "Fix data import doctor findings before offline intake.",
    )


def _next_actions(items: list[DataGapItem]) -> list[str]:
    names = {item.name for item in items if item.status == "BLOCK"}
    all_names = {item.name for item in items}
    actions: list[str] = []
    if (
        "source_qa_answers" in names
        or "source_metadata" in names
        or "source_qa_preflight" in names
        or "source_qa_review" in names
    ):
        if "tdx_day_export" in all_names:
            actions.append(
                "Fill the source QA evidence worksheet, then write TDX source QA answers "
                "with real terminal, export time, license, adjustment, and human review evidence; "
                "keep the path OHLCV-only unless separate PIT evidence exists."
            )
        else:
            actions.append(
                "Fill the source QA evidence worksheet, then write data_source_qa_answers.json "
                "with real vendor, terminal, export time, license, adjustment, and human review evidence."
            )
    if "tdx_day_export" in names:
        actions.append("Fix TDX .day conversion before source QA or offline intake.")
    if "csv_template_rows" in names:
        actions.append("Replace all generated template CSV rows with recent real A-share daily exports.")
    if "import_doctor" in names:
        actions.append("Rerun data import doctor after source QA answers and real CSV exports are in place.")
    if not actions:
        actions.append("Run guarded offline data intake, then rerun first-million pipeline.")
    return actions


def _next_commands(
    *,
    config_path: str | Path,
    data_dir: Path,
    answers_path: Path,
    min_symbols: int,
    as_of: str | None,
    tdx_detected: bool,
) -> list[str]:
    as_of_arg = f" --as-of {as_of}" if as_of else ""
    checklist_command = (
        ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa.py "
        f"--config {config_path} --output-dir {data_dir} --min-symbols {min_symbols}{as_of_arg}"
    )
    if tdx_detected:
        return [
            checklist_command,
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa_evidence_worksheet.py "
            f"--checklist {data_dir / 'data_source_qa.json'} --output-dir {data_dir}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_tdx_source_qa_answers.py "
                f"--checklist {data_dir / 'data_source_qa.json'} --output {answers_path} "
                f"--tdx-export-report {data_dir / 'tdx_day_export.json'} --input-dir <tdx-vipdoc-or-lday-dir> "
                "--operator <operator> --exported-at <local-time> --price-adjustment qfq "
                "--price-adjustment-evidence <real-tdx-adjustment-evidence> "
                "--license-evidence <real-license-evidence> --reviewed-by <name> --reviewed-at <date>"
            ),
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_preflight.py "
                f"--checklist {data_dir / 'data_source_qa.json'} --answers {answers_path} "
                "--output-dir results\\import\\source_qa"
            ),
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_data_import_doctor.py "
                f"--data-dir {data_dir} --config {config_path} --min-symbols {min_symbols} "
                "--encoding auto --output-dir results\\import\\doctor"
            ),
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_csv_intake_preview.py "
                f"--data-dir {data_dir} --encoding auto --output-dir results\\import\\csv_preview"
            ),
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_offline_data_intake.py "
                f"--data-dir {data_dir} --config {config_path} --output-dir results\\import\\offline_intake "
                f"--source-qa-answers {answers_path} --min-symbols {min_symbols} --min-trading-days 240{as_of_arg}"
            ),
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_first_million_pipeline.py "
                f"--config {config_path} --data-dir {data_dir} --output-dir results\\first_million "
                "--tdx-input-dir <tdx-vipdoc-or-lday-dir> --tdx-operator <operator> "
                "--tdx-exported-at <local-time> --tdx-price-adjustment qfq "
                "--tdx-price-adjustment-evidence <real-tdx-adjustment-evidence> "
                "--tdx-license-evidence <real-license-evidence> --tdx-reviewed-by <name> "
                f"--tdx-reviewed-at <date> --min-symbols {min_symbols} --min-trading-days 240{as_of_arg}"
            ),
        ]
    return [
        checklist_command,
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
            f"--evidence-manifest {data_dir / 'source_qa_evidence_manifest.json'} "
            "--require-evidence-manifest"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_preflight.py "
            f"--checklist {data_dir / 'data_source_qa.json'} --answers {answers_path} "
            f"--evidence-manifest {data_dir / 'source_qa_evidence_manifest.json'} "
            "--require-evidence-manifest "
            "--output-dir results\\import\\source_qa"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_evidence_readiness.py "
            f"--checklist {data_dir / 'data_source_qa.json'} "
            f"--worksheet {data_dir / 'data_source_qa_evidence_worksheet.csv'} "
            f"--answers {answers_path} "
            f"--evidence-manifest {data_dir / 'source_qa_evidence_manifest.json'} "
            "--require-evidence-manifest --output-dir results\\import\\source_qa"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_data_import_doctor.py "
            f"--data-dir {data_dir} --config {config_path} --min-symbols {min_symbols} "
            "--encoding auto --output-dir results\\import\\doctor"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_csv_intake_preview.py "
            f"--data-dir {data_dir} --encoding auto --output-dir results\\import\\csv_preview"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_offline_data_intake.py "
            f"--data-dir {data_dir} --config {config_path} --output-dir results\\import\\offline_intake "
            f"--source-qa-answers {answers_path} --min-symbols {min_symbols} --min-trading-days 240{as_of_arg}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_first_million_pipeline.py "
            f"--config {config_path} --data-dir {data_dir} --output-dir results\\first_million "
            f"--source-qa-answers {answers_path} --min-symbols {min_symbols} --min-trading-days 240{as_of_arg}"
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
        message = str(first.get("message", "Data evidence gap is unresolved."))
        return f"{code}: {message}"
    return "Data evidence gap is unresolved."


def _combine(statuses: list[DataGapStatus]) -> DataGapStatus:
    if any(status == "BLOCK" for status in statuses):
        return "BLOCK"
    if any(status == "WATCH" for status in statuses):
        return "WATCH"
    return "PASS"


def _normalize_status(value: object) -> DataGapStatus:
    text = str(value).upper()
    if text == "PASS":
        return "PASS"
    if text == "WATCH":
        return "WATCH"
    return "BLOCK"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
