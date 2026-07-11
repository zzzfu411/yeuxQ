"""Preflight checklist for filling source QA answers without weakening gates."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal

from quantify.data.source_qa import (
    REQUIRED_SOURCE_METADATA,
    build_data_source_qa_review,
    placeholder_source_metadata_fields,
    weak_source_evidence,
)

PreflightStatus = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class SourceQAPreflightItem:
    kind: str
    status: PreflightStatus
    field: str
    message: str
    fix: str
    target: str = ""
    next_command: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "status": self.status,
            "field": self.field,
            "message": self.message,
            "fix": self.fix,
            "target": self.target,
            "next_command": self.next_command,
        }


@dataclass(frozen=True, slots=True)
class SourceQAPreflight:
    status: PreflightStatus
    checklist_path: str
    answers_path: str
    evidence_manifest_path: str
    require_evidence_manifest: bool
    items: list[SourceQAPreflightItem]
    next_commands: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checklist_path": self.checklist_path,
            "answers_path": self.answers_path,
            "evidence_manifest_path": self.evidence_manifest_path,
            "require_evidence_manifest": self.require_evidence_manifest,
            "items": [item.to_dict() for item in self.items],
            "next_commands": self.next_commands,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Source QA Preflight: {self.status}",
            "",
            f"- Checklist: `{self.checklist_path}`",
            f"- Answers: `{self.answers_path}`",
            f"- Evidence manifest: `{self.evidence_manifest_path or 'not supplied'}`",
            f"- Require evidence manifest: `{self.require_evidence_manifest}`",
            "",
            "## Items",
            "",
            "| kind | status | field | target | message | fix |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        if self.items:
            for item in self.items:
                lines.append(
                    f"| `{item.kind}` | `{item.status}` | `{item.field}` | "
                    f"`{item.target}` | {item.message} | {item.fix} |"
                )
        else:
            lines.append("| `none` | `PASS` | `n/a` | `` | No source-stage gaps detected. | Continue to source QA review. |")
        item_commands = [item.next_command for item in self.items if item.next_command]
        if item_commands:
            lines.extend(["", "## Item Commands"])
            for command in dict.fromkeys(item_commands):
                lines.append("")
                lines.append("```powershell")
                lines.append(command)
                lines.append("```")
        lines.extend(["", "## Next Commands"])
        for command in self.next_commands:
            lines.append("")
            lines.append("```powershell")
            lines.append(command)
            lines.append("```")
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_source_qa_preflight(
    *,
    checklist_path: str | Path = "data_exports/data_source_qa.json",
    answers_path: str | Path = "data_exports/data_source_qa_answers.json",
    evidence_manifest_path: str | Path | None = None,
    require_evidence_manifest: bool = False,
    output_dir: str | Path = "results/import/source_qa",
) -> SourceQAPreflight:
    checklist_file = Path(checklist_path)
    answers_file = Path(answers_path)
    manifest_file = (
        Path(evidence_manifest_path)
        if evidence_manifest_path is not None
        else (checklist_file.parent / "source_qa_evidence_manifest.json" if require_evidence_manifest else None)
    )
    items: list[SourceQAPreflightItem] = []
    manifest_command = _manifest_command(checklist_file=checklist_file, manifest_file=manifest_file)

    checklist = _read_json(checklist_file)
    answers = _read_json(answers_file)
    if not checklist_file.exists():
        items.append(
            SourceQAPreflightItem(
                "artifact",
                "BLOCK",
                "data_source_qa.json",
                "Source QA checklist is missing.",
                "Run write_data_source_qa.py before filling source answers.",
                str(checklist_file),
            )
        )
    if not answers_file.exists() or not answers:
        items.append(
            SourceQAPreflightItem(
                "artifact",
                "BLOCK",
                "data_source_qa_answers.json",
                "Source QA answers are missing or empty.",
                "Fill the evidence worksheet from real vendor/export evidence, then write data_source_qa_answers.json.",
                str(answers_file),
            )
        )

    metadata = answers.get("source_metadata", {}) if isinstance(answers, dict) else {}
    metadata = metadata if isinstance(metadata, dict) else {}
    for field in REQUIRED_SOURCE_METADATA:
        value = str(metadata.get(field, "")).strip()
        if not value:
            items.append(
                SourceQAPreflightItem(
                    "metadata",
                    "BLOCK",
                    field,
                    "Required source metadata is missing.",
                    f"Fill `{field}` from the real export batch, not from a placeholder.",
                    str(answers_file),
                )
            )
    for field in placeholder_source_metadata_fields(metadata):
        items.append(
            SourceQAPreflightItem(
                "metadata",
                "BLOCK",
                field,
                "Required source metadata looks like a placeholder.",
                f"Replace `{field}` with real vendor/export evidence.",
                str(answers_file),
            )
        )

    answer_map = _answer_map(answers.get("answers", {}) if isinstance(answers, dict) else {})
    for item in checklist.get("checklist", []) if isinstance(checklist, dict) else []:
        if not isinstance(item, dict) or str(item.get("review_stage", "source")) != "source":
            continue
        item_id = str(item.get("id", "")).strip()
        if not item_id:
            continue
        severity = str(item.get("severity", "INFO")).upper()
        answer = answer_map.get(item_id, {})
        answer_value = _answer_value(answer.get("answer"))
        evidence = str(answer.get("evidence", "")).strip()
        status: PreflightStatus = "BLOCK" if severity == "BLOCK_IF_NO" else "WATCH"
        if severity not in {"BLOCK_IF_NO", "WATCH_IF_NO"}:
            continue
        if answer_value != "yes":
            items.append(
                SourceQAPreflightItem(
                    "answer",
                    status,
                    item_id,
                    f"{severity} question is not answered yes.",
                    "Answer yes only when the evidence exists; otherwise keep the gate blocked.",
                    str(answers_file),
                )
            )
        elif not evidence:
            items.append(
                SourceQAPreflightItem(
                    "evidence",
                    status,
                    item_id,
                    f"{severity} question has no evidence note.",
                    "Add a concrete evidence note tied to the export, license, adjustment, or signoff.",
                    str(answers_file),
                )
            )
        elif weak_source_evidence(evidence):
            items.append(
                SourceQAPreflightItem(
                    "evidence",
                    status,
                    item_id,
                    f"{severity} question has placeholder or weak evidence.",
                    "Replace sample evidence with real vendor/export evidence.",
                    str(answers_file),
                )
            )

    review = build_data_source_qa_review(
        checklist_path=checklist_file,
        answers_path=answers_file,
        evidence_manifest_path=manifest_file,
        require_evidence_manifest=require_evidence_manifest,
    )
    items.extend(_manifest_items(review.to_dict(), manifest_file=manifest_file, next_command=manifest_command))
    output_root = Path(output_dir)
    status = _combine([item.status for item in items] + [review.status])
    return SourceQAPreflight(
        status=status,
        checklist_path=str(checklist_file),
        answers_path=str(answers_file),
        evidence_manifest_path=str(manifest_file or ""),
        require_evidence_manifest=require_evidence_manifest,
        items=items,
        next_commands=_next_commands(
            checklist_file=checklist_file,
            answers_file=answers_file,
            manifest_file=manifest_file,
            require_evidence_manifest=require_evidence_manifest,
            output_root=output_root,
            status=status,
        ),
        prohibited_actions=[
            "Do not invent vendor/export evidence to make source QA pass.",
            "Do not import offline data while this preflight is BLOCK.",
            "Do not run candidate experiments until source QA and guarded intake pass.",
            "Do not treat source QA preflight PASS as a profit claim or live trading permission.",
            "Do not connect this workflow to real broker order submission.",
        ],
    )


def write_source_qa_preflight(report: SourceQAPreflight, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "source_qa_preflight.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "source_qa_preflight.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _next_commands(
    *,
    checklist_file: Path,
    answers_file: Path,
    manifest_file: Path | None,
    require_evidence_manifest: bool,
    output_root: Path,
    status: PreflightStatus,
) -> list[str]:
    manifest_args = _manifest_review_args(manifest_file, require_evidence_manifest=require_evidence_manifest)
    if status == "PASS":
        return [
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_data_source_qa_review.py "
                f"--checklist {checklist_file} --answers {answers_file}{manifest_args} "
                f"--output-dir {output_root}"
            )
        ]
    commands = [
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa_evidence_worksheet.py "
            f"--checklist {checklist_file} --output-dir {answers_file.parent}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_data_source_qa_worksheet_preflight.py "
            f"--checklist {checklist_file} "
            f"--worksheet {answers_file.parent / 'data_source_qa_evidence_worksheet.csv'} "
            f"--output-dir {answers_file.parent}"
        ),
    ]
    manifest_command = _manifest_command(checklist_file=checklist_file, manifest_file=manifest_file)
    if manifest_command:
        commands.append(manifest_command)
    commands.extend(
        [
            (
                ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa_answers.py "
                f"--checklist {checklist_file} "
                f"--worksheet {answers_file.parent / 'data_source_qa_evidence_worksheet.csv'} "
                f"--output {answers_file}{manifest_args}"
            ),
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_preflight.py "
                f"--checklist {checklist_file} --answers {answers_file}{manifest_args} "
                f"--output-dir {output_root}"
            ),
        ]
    )
    return commands


def _manifest_items(
    review: dict[str, Any],
    *,
    manifest_file: Path | None,
    next_command: str,
) -> list[SourceQAPreflightItem]:
    items: list[SourceQAPreflightItem] = []
    for finding in review.get("findings", []) or []:
        if not isinstance(finding, dict):
            continue
        code = str(finding.get("code", ""))
        if not (
            code.startswith("SOURCE_QA_EVIDENCE_MANIFEST")
            or code.startswith("SOURCE_QA_EVIDENCE_ATTACHMENT")
        ):
            continue
        evidence = finding.get("evidence", {}) if isinstance(finding.get("evidence"), dict) else {}
        field = str(
            evidence.get("attachment_id")
            or evidence.get("id")
            or (manifest_file.name if manifest_file is not None else "source_qa_evidence_manifest.json")
        )
        target = str(evidence.get("target") or evidence.get("path") or manifest_file or "")
        items.append(
            SourceQAPreflightItem(
                "attachment" if "ATTACHMENT" in code else "evidence_manifest",
                _normalize_status(finding.get("severity")),
                field,
                f"{code}: {finding.get('message', '')}",
                _manifest_fix(code),
                target,
                next_command,
            )
        )
    return items


def _manifest_fix(code: str) -> str:
    if code in {"SOURCE_QA_EVIDENCE_MANIFEST_MISSING", "SOURCE_QA_EVIDENCE_MANIFEST_EMPTY"}:
        return "Add retained local evidence files, then generate source_qa_evidence_manifest.json."
    if code == "SOURCE_QA_EVIDENCE_ATTACHMENT_MISSING":
        return "Place the required retained attachment at the target path, then regenerate the manifest."
    if code in {
        "SOURCE_QA_EVIDENCE_ATTACHMENT_HASH_INVALID",
        "SOURCE_QA_EVIDENCE_ATTACHMENT_HASH_MISMATCH",
        "SOURCE_QA_EVIDENCE_ATTACHMENT_MISSING_FILE",
        "SOURCE_QA_EVIDENCE_ATTACHMENT_PLACEHOLDER",
    }:
        return "Replace or fix the local attachment file, then regenerate source_qa_evidence_manifest.json."
    return "Fix source_qa_evidence_manifest.json, then rerun strict source QA preflight."


def _manifest_review_args(
    manifest_file: Path | None,
    *,
    require_evidence_manifest: bool,
) -> str:
    parts = []
    if manifest_file is not None:
        parts.append(f"--evidence-manifest {manifest_file}")
    if require_evidence_manifest:
        parts.append("--require-evidence-manifest")
    return (" " + " ".join(parts)) if parts else ""


def _manifest_command(*, checklist_file: Path, manifest_file: Path | None) -> str:
    if manifest_file is None:
        return ""
    evidence_dir = manifest_file.parent / "source_qa_evidence"
    return (
        ".\\.venv\\Scripts\\python.exe examples\\write_source_qa_evidence_manifest.py "
        f"--checklist {checklist_file} --evidence-dir {evidence_dir} "
        f"--output-dir {manifest_file.parent} --strict"
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _answer_map(raw: object) -> dict[str, dict[str, Any]]:
    if isinstance(raw, dict):
        return {
            str(key): value if isinstance(value, dict) else {"answer": value}
            for key, value in raw.items()
        }
    if isinstance(raw, list):
        return {
            str(item["id"]): item
            for item in raw
            if isinstance(item, dict) and "id" in item
        }
    return {}


def _answer_value(value: object) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    text = str(value or "").strip().lower()
    if text in {"yes", "y", "true", "1", "pass", "ok", "confirmed"}:
        return "yes"
    if text in {"no", "n", "false", "0", "fail", "blocked"}:
        return "no"
    return "unknown"


def _combine(statuses: list[str]) -> PreflightStatus:
    if any(status == "BLOCK" for status in statuses):
        return "BLOCK"
    if any(status == "WATCH" for status in statuses):
        return "WATCH"
    return "PASS"


def _normalize_status(value: object) -> PreflightStatus:
    text = str(value or "WATCH").upper()
    if text == "PASS":
        return "PASS"
    if text == "BLOCK":
        return "BLOCK"
    return "WATCH"
