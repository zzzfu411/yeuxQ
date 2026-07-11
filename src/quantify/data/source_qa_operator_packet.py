"""Operator packet for filling source QA evidence.

This packet consolidates worksheet rows, attachment requirements, and command
order for a human data operator. It never creates answers or evidence files.
"""
from __future__ import annotations

from dataclasses import dataclass
import csv
import json
from pathlib import Path
from typing import Any, Literal

OperatorPacketDecision = Literal["PASS", "WATCH", "BLOCK"]

PROHIBITED_ACTIONS = [
    "Do not fabricate worksheet answers, screenshots, PDFs, notes, or approval records.",
    "Do not use generated todo files, templates, or this packet as source evidence.",
    "Do not convert a worksheet into data_source_qa_answers.json while preflight is BLOCK.",
    "Do not run guarded offline intake until source QA answers and evidence manifest pass deterministic review.",
    "Do not treat source QA readiness as strategy approval, profit evidence, or broker permission.",
    "Do not let LLM text sign off source evidence or human approval.",
]

FILL_WORKSHEET_COMMAND = (
    ".\\.venv\\Scripts\\python.exe examples\\fill_data_source_qa_evidence_worksheet.py "
    "--checklist data_exports\\data_source_qa.json "
    "--worksheet data_exports\\data_source_qa_evidence_worksheet.csv "
    "--output-dir data_exports "
    "--vendor \"<real-vendor-or-broker>\" "
    "--terminal \"<terminal-product-and-version>\" "
    "--operator \"<export-operator>\" "
    "--exported-at \"<local-export-time>\" "
    "--price-adjustment \"<raw-qfq-or-hfq>\" "
    "--license-scope \"<retained-license-scope>\" "
    "--reviewed-by \"<human-reviewer>\" "
    "--reviewed-at \"<review-date>\" "
    "--source-identity-evidence \"<retained-source-identity-evidence>\" "
    "--license-evidence \"<retained-license-evidence>\" "
    "--price-adjustment-evidence \"<retained-adjustment-evidence>\" "
    "--point-in-time-evidence \"<retained-pit-or-non-pit-limitation-evidence>\" "
    "--manual-signoff-evidence \"<retained-human-signoff-evidence>\""
)
WORKSHEET_PREFLIGHT_COMMAND = (
    ".\\.venv\\Scripts\\python.exe examples\\run_data_source_qa_worksheet_preflight.py "
    "--checklist data_exports\\data_source_qa.json "
    "--worksheet data_exports\\data_source_qa_evidence_worksheet.csv "
    "--output-dir data_exports"
)
STRICT_MANIFEST_COMMAND = (
    ".\\.venv\\Scripts\\python.exe examples\\write_source_qa_evidence_manifest.py "
    "--checklist data_exports\\data_source_qa.json "
    "--evidence-dir data_exports\\source_qa_evidence "
    "--output-dir data_exports --strict"
)
ANSWERS_COMMAND = (
    ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa_answers.py "
    "--checklist data_exports\\data_source_qa.json "
    "--worksheet data_exports\\data_source_qa_evidence_worksheet.csv "
    "--output data_exports\\data_source_qa_answers.json "
    "--evidence-manifest data_exports\\source_qa_evidence_manifest.json "
    "--require-evidence-manifest"
)
READINESS_COMMAND = (
    ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_evidence_readiness.py "
    "--checklist data_exports\\data_source_qa.json "
    "--worksheet data_exports\\data_source_qa_evidence_worksheet.csv "
    "--answers data_exports\\data_source_qa_answers.json "
    "--evidence-manifest data_exports\\source_qa_evidence_manifest.json "
    "--require-evidence-manifest --output-dir results\\first_million\\source_qa"
)
PIPELINE_REFRESH_COMMAND = (
    ".\\.venv\\Scripts\\python.exe examples\\run_first_million_pipeline.py "
    "--config config\\research_recent.yaml --data-dir data_exports "
    "--output-dir results\\first_million "
    "--source-qa-answers data_exports\\data_source_qa_answers.json "
    "--source-qa-evidence-manifest data_exports\\source_qa_evidence_manifest.json "
    "--require-source-qa-evidence-manifest --as-of <YYYY-MM-DD> --min-symbols 300 --no-registry"
)
COMMAND_SEQUENCE = [
    FILL_WORKSHEET_COMMAND,
    WORKSHEET_PREFLIGHT_COMMAND,
    STRICT_MANIFEST_COMMAND,
    ANSWERS_COMMAND,
    READINESS_COMMAND,
]


@dataclass(frozen=True, slots=True)
class SourceQAOperatorItem:
    item_type: str
    item_id: str
    target: str
    current_state: str
    answer_required: str
    evidence_required: str
    acceptable_evidence: str
    unacceptable_evidence: str
    command_after_completion: str

    def to_dict(self) -> dict[str, str]:
        return {
            "item_type": self.item_type,
            "item_id": self.item_id,
            "target": self.target,
            "current_state": self.current_state,
            "answer_required": self.answer_required,
            "evidence_required": self.evidence_required,
            "acceptable_evidence": self.acceptable_evidence,
            "unacceptable_evidence": self.unacceptable_evidence,
            "command_after_completion": self.command_after_completion,
        }


@dataclass(frozen=True, slots=True)
class SourceQAEvidenceDropzoneKit:
    evidence_dir: str
    readme_path: str
    worksheet_path: str
    manifest_path: str
    answers_path: str
    required_files: list[dict[str, str]]
    checklist: list[str]
    command_sequence: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_dir": self.evidence_dir,
            "readme_path": self.readme_path,
            "worksheet_path": self.worksheet_path,
            "manifest_path": self.manifest_path,
            "answers_path": self.answers_path,
            "required_files": self.required_files,
            "checklist": self.checklist,
            "command_sequence": self.command_sequence,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            "# Source QA Evidence Dropzone Kit",
            "",
            f"- Evidence directory: `{self.evidence_dir}`",
            f"- Worksheet: `{self.worksheet_path}`",
            f"- Manifest: `{self.manifest_path}`",
            f"- Answers: `{self.answers_path}`",
            "",
            "Place retained source-QA evidence files here before generating the strict manifest. "
            "This kit is an operator instruction sheet only; it does not create evidence, answer source QA, "
            "approve data, approve a strategy, or connect to a broker.",
            "",
            "## Required Files",
            "",
        ]
        if self.required_files:
            lines.append("| id | suggested file | required evidence | do not use |")
            lines.append("| --- | --- | --- | --- |")
            for item in self.required_files:
                lines.append(
                    "| `{id}` | `{path}` | {required} | {bad} |".format(
                        id=item.get("id", ""),
                        path=item.get("path", ""),
                        required=_cell(item.get("required_evidence", "")),
                        bad=_cell(item.get("unacceptable_evidence", "")),
                    )
                )
        else:
            lines.append("- No missing attachment files are currently listed.")
        lines.extend(["", "## Checklist"])
        lines.extend(f"- {item}" for item in self.checklist)
        lines.extend(["", "## Command Sequence"])
        for index, command in enumerate(self.command_sequence, start=1):
            lines.extend(["", f"{index}.", "", "```powershell", command, "```"])
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class SourceQAOperatorPacket:
    decision: OperatorPacketDecision
    as_of: str
    data_dir: str
    report_dir: str
    worksheet_path: str
    evidence_dir: str
    dropzone_kit: SourceQAEvidenceDropzoneKit
    missing_worksheet_count: int
    missing_attachment_count: int
    items: list[SourceQAOperatorItem]
    command_sequence: list[str]
    acceptance_criteria: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "as_of": self.as_of,
            "data_dir": self.data_dir,
            "report_dir": self.report_dir,
            "worksheet_path": self.worksheet_path,
            "evidence_dir": self.evidence_dir,
            "dropzone_kit": self.dropzone_kit.to_dict(),
            "missing_worksheet_count": self.missing_worksheet_count,
            "missing_attachment_count": self.missing_attachment_count,
            "items": [item.to_dict() for item in self.items],
            "command_sequence": self.command_sequence,
            "acceptance_criteria": self.acceptance_criteria,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Source QA Operator Packet: {self.decision}",
            "",
            f"- As of: `{self.as_of}`",
            f"- Data directory: `{self.data_dir}`",
            f"- Report directory: `{self.report_dir}`",
            f"- Worksheet: `{self.worksheet_path}`",
            f"- Evidence directory: `{self.evidence_dir}`",
            f"- Dropzone README: `{self.dropzone_kit.readme_path}`",
            f"- Missing worksheet items: {self.missing_worksheet_count}",
            f"- Missing attachment items: {self.missing_attachment_count}",
            "",
            "This packet is a human evidence collection aid. It does not create source QA answers, does not create evidence files, and does not approve strategy research.",
            "",
            "## Fill Items",
            "",
        ]
        if self.items:
            lines.append("| type | id | target | state | answer | evidence | do not use |")
            lines.append("| --- | --- | --- | --- | --- | --- | --- |")
            for item in self.items:
                lines.append(
                    f"| `{item.item_type}` | `{item.item_id}` | `{item.target}` | "
                    f"`{item.current_state}` | {_cell(item.answer_required)} | "
                    f"{_cell(item.evidence_required)} | {_cell(item.unacceptable_evidence)} |"
                )
        else:
            lines.append("- None.")
        lines.extend(["", "## Command Sequence"])
        for index, command in enumerate(self.command_sequence, start=1):
            lines.extend(["", f"{index}.", "", "```powershell", command, "```"])
        lines.extend(["", "## Acceptance Criteria"])
        lines.extend(f"- {item}" for item in self.acceptance_criteria)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_source_qa_operator_packet(
    *,
    data_dir: str | Path = "data_exports",
    report_dir: str | Path = "results/first_million",
    as_of: str | None = None,
) -> SourceQAOperatorPacket:
    data_root = Path(data_dir)
    report_root = Path(report_dir)
    worksheet_path = data_root / "data_source_qa_evidence_worksheet.csv"
    evidence_dir = data_root / "source_qa_evidence"
    worksheet_rows = _worksheet_items(report_root / "source_qa_worksheet_todo.csv", worksheet_path)
    attachment_rows = _attachment_items(report_root / "source_qa_evidence_attachment_plan.csv")
    items = [*worksheet_rows, *attachment_rows]
    decision = _decision(worksheet_rows, attachment_rows)
    dropzone_kit = _dropzone_kit(
        data_root=data_root,
        report_root=report_root,
        worksheet_path=worksheet_path,
        evidence_dir=evidence_dir,
        attachment_rows=attachment_rows,
    )
    return SourceQAOperatorPacket(
        decision=decision,
        as_of=str(as_of or _read_as_of(report_root) or "unspecified"),
        data_dir=str(data_root),
        report_dir=str(report_root),
        worksheet_path=str(worksheet_path),
        evidence_dir=str(evidence_dir),
        dropzone_kit=dropzone_kit,
        missing_worksheet_count=len(worksheet_rows),
        missing_attachment_count=len(attachment_rows),
        items=items,
        command_sequence=_command_sequence(decision),
        acceptance_criteria=[
            "Every worksheet item has a non-placeholder answer and evidence note from retained source material.",
            "Every required attachment exists under data_exports\\source_qa_evidence and is recorded in source_qa_evidence_manifest.json with matching sha256.",
            "data_source_qa_worksheet_preflight.json is not BLOCK before writing data_source_qa_answers.json.",
            "source_qa_evidence_readiness.json is PASS before guarded offline intake or candidate experiments.",
            "The packet remains research/paper-only and never creates broker instructions.",
        ],
        prohibited_actions=PROHIBITED_ACTIONS,
    )


def write_source_qa_operator_packet(
    packet: SourceQAOperatorPacket,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "source_qa_operator_packet.json").write_text(
        json.dumps(packet.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "source_qa_operator_packet.md").write_text(packet.to_markdown(), encoding="utf-8")
    with (root / "source_qa_operator_packet.csv").open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        fieldnames = [
            "item_type",
            "item_id",
            "target",
            "current_state",
            "answer_required",
            "evidence_required",
            "acceptable_evidence",
            "unacceptable_evidence",
            "command_after_completion",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(item.to_dict() for item in packet.items)
    return root


def write_source_qa_evidence_dropzone_kit(packet: SourceQAOperatorPacket) -> Path:
    kit = packet.dropzone_kit
    evidence_dir = Path(kit.evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    readme = Path(kit.readme_path)
    readme.write_text(kit.to_markdown(), encoding="utf-8")
    return readme


def _dropzone_kit(
    *,
    data_root: Path,
    report_root: Path,
    worksheet_path: Path,
    evidence_dir: Path,
    attachment_rows: list[SourceQAOperatorItem],
) -> SourceQAEvidenceDropzoneKit:
    required_files = [
        {
            "id": item.item_id,
            "path": item.target,
            "required_evidence": item.evidence_required,
            "acceptable_evidence": item.acceptable_evidence,
            "unacceptable_evidence": item.unacceptable_evidence,
        }
        for item in attachment_rows
    ]
    readme = evidence_dir / "README_source_qa_evidence_dropzone.md"
    manifest = data_root / "source_qa_evidence_manifest.json"
    answers = data_root / "data_source_qa_answers.json"
    return SourceQAEvidenceDropzoneKit(
        evidence_dir=str(evidence_dir),
        readme_path=str(readme),
        worksheet_path=str(worksheet_path),
        manifest_path=str(manifest),
        answers_path=str(answers),
        required_files=required_files,
        checklist=[
            "Copy retained vendor, broker, terminal, license, adjustment, PIT/limitation, and human-review evidence files into the evidence directory.",
            "Use filenames that include the source QA id when practical, for example source_identity_receipt.png or price_adjustment_qfq.png.",
            "Fill data_source_qa_evidence_worksheet.csv from the retained evidence; do not use placeholders or generated examples.",
            "Run worksheet preflight before converting worksheet rows into data_source_qa_answers.json.",
            "Regenerate source_qa_evidence_manifest.json with --strict after every evidence-file change.",
            "Rerun source QA evidence readiness and the first-million pipeline after the manifest and answers pass deterministic review.",
        ],
        command_sequence=[
            FILL_WORKSHEET_COMMAND,
            WORKSHEET_PREFLIGHT_COMMAND,
            STRICT_MANIFEST_COMMAND,
            ANSWERS_COMMAND,
            READINESS_COMMAND,
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_evidence_inbox.py "
                f"--data-dir {data_root} --report-dir {report_root}"
            ),
            PIPELINE_REFRESH_COMMAND,
        ],
        prohibited_actions=PROHIBITED_ACTIONS,
    )


def _worksheet_items(path: Path, worksheet_path: Path) -> list[SourceQAOperatorItem]:
    rows = _read_csv_rows(path)
    items: list[SourceQAOperatorItem] = []
    command = FILL_WORKSHEET_COMMAND
    for row in rows:
        item_id = str(row.get("id") or "").strip()
        if not item_id:
            continue
        row_type = str(row.get("row_type") or "")
        answer_required = _answer_requirement(row)
        evidence_required = str(row.get("required_evidence") or "")
        items.append(
            SourceQAOperatorItem(
                item_type=f"worksheet_{row_type}",
                item_id=item_id,
                target=f"{worksheet_path} row {row.get('row_number', '')}".strip(),
                current_state=str(row.get("message") or "missing"),
                answer_required=answer_required,
                evidence_required=evidence_required,
                acceptable_evidence=_acceptable_worksheet_evidence(item_id, row_type),
                unacceptable_evidence=_unacceptable_worksheet_evidence(item_id),
                command_after_completion=command,
            )
        )
    return items


def _attachment_items(path: Path) -> list[SourceQAOperatorItem]:
    rows = _read_csv_rows(path)
    command = STRICT_MANIFEST_COMMAND
    return [
        SourceQAOperatorItem(
            item_type="attachment",
            item_id=str(row.get("id") or ""),
            target=str(row.get("suggested_file") or ""),
            current_state=str(row.get("current_state") or "missing"),
            answer_required="Add a retained local evidence file; do not type an answer in this packet.",
            evidence_required=str(row.get("required_evidence") or ""),
            acceptable_evidence=_acceptable_attachment_evidence(str(row.get("id") or "")),
            unacceptable_evidence=str(row.get("do_not_use") or "generated placeholders"),
            command_after_completion=_strict_manifest_command(str(row.get("next_command") or command)),
        )
        for row in rows
        if str(row.get("id") or "").strip()
    ]


def _strict_manifest_command(command: str) -> str:
    if "write_source_qa_evidence_manifest.py" not in command or "--strict" in command:
        return command
    return f"{command} --strict"


def _answer_requirement(row: dict[str, str]) -> str:
    row_type = str(row.get("row_type") or "")
    item_id = str(row.get("id") or "")
    if row_type == "source_question":
        return "Answer yes only if the required evidence exists and is retained locally."
    if item_id == "price_adjustment":
        return "Confirm the exported OHLC adjustment method, e.g. qfq, and cite the export setting."
    if item_id == "license_or_usage_scope":
        return "State the allowed scope, e.g. research and paper trading only, backed by retained evidence."
    if item_id == "reviewed_at":
        return "Record the human review date or timestamp."
    if item_id == "reviewed_by":
        return "Record the human reviewer name or identifier."
    return "Fill the value from the real vendor/export record."


def _acceptable_worksheet_evidence(item_id: str, row_type: str) -> str:
    if row_type == "metadata":
        return "Vendor/export metadata, terminal export dialog, retained export receipt, or human review note with date."
    values = {
        "source_identity": "Vendor receipt or metadata showing vendor, product, operator, and export time.",
        "license_scope": "Vendor terms, account permission, or retained license note tied to the export account.",
        "price_adjustment": "Screenshot or export metadata showing raw/qfq/hfq setting for the exported bars.",
        "point_in_time": "Vendor documentation for PIT fields, or explicit retained note limiting non-PIT data to research-only.",
        "manual_signoff": "Reviewer/date note matching reviewed_by and reviewed_at metadata.",
    }
    return values.get(item_id, "Retained source evidence tied to the export batch.")


def _unacceptable_worksheet_evidence(item_id: str) -> str:
    values = {
        "source_identity": "Unlabeled vendor names, generated receipts, or notes without export timestamp.",
        "license_scope": "Assumed public web text or generic marketing copy without account/vendor context.",
        "price_adjustment": "Unverified qfq labels, mixed raw/qfq/hfq files, or screenshots without the setting visible.",
        "point_in_time": "Vague PIT claims, survivorship-only notes, or after-the-fact fundamentals assertions.",
        "manual_signoff": "Unsigned notes, LLM-generated approvals, or review notes without reviewer/date.",
    }
    return values.get(item_id, "Placeholders, generated examples, or unverifiable notes.")


def _acceptable_attachment_evidence(item_id: str) -> str:
    values = {
        "source_identity": "Image/PDF/text receipt that clearly identifies vendor, terminal/product, operator, and export time.",
        "license_scope": "Retained license/account permission evidence for research and paper-trading use.",
        "price_adjustment": "Retained export setting screenshot or metadata showing qfq/raw/hfq.",
        "point_in_time": "Retained vendor PIT documentation or explicit non-PIT limitation note.",
        "manual_signoff": "Signed or attributable human review note with reviewed_by and reviewed_at.",
    }
    return values.get(item_id, "Retained local evidence file accepted by strict source QA review.")


def _decision(
    worksheet_rows: list[SourceQAOperatorItem],
    attachment_rows: list[SourceQAOperatorItem],
) -> OperatorPacketDecision:
    if worksheet_rows or attachment_rows:
        return "BLOCK"
    return "PASS"


def _command_sequence(decision: OperatorPacketDecision) -> list[str]:
    if decision == "PASS":
        return [
            READINESS_COMMAND,
            PIPELINE_REFRESH_COMMAND,
        ]
    return COMMAND_SEQUENCE


def _read_as_of(report_root: Path) -> str:
    for name in ("first_million_daily_brief.json", "data_evidence_action_packet.json"):
        payload = _read_json(report_root / name)
        text = str(payload.get("as_of") or "")
        if text:
            return text
    return ""


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except UnicodeDecodeError:
        with path.open("r", newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except OSError:
        return []


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _cell(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")
