"""Unified readiness report for source QA evidence collection."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal

from quantify.data.source_qa import (
    build_data_source_qa_evidence_worksheet_preflight,
    build_data_source_qa_review,
    build_source_qa_evidence_manifest_preflight,
)
from quantify.data.source_qa_preflight import build_source_qa_preflight

ReadinessStatus = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class SourceQAEvidenceReadinessSection:
    name: str
    status: ReadinessStatus
    artifact: str
    summary: str
    blockers: list[str]
    next_command: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "artifact": self.artifact,
            "summary": self.summary,
            "blockers": self.blockers,
            "next_command": self.next_command,
        }


@dataclass(frozen=True, slots=True)
class SourceQAEvidenceReadiness:
    status: ReadinessStatus
    checklist_path: str
    worksheet_path: str
    answers_path: str
    evidence_manifest_path: str
    require_evidence_manifest: bool
    sections: list[SourceQAEvidenceReadinessSection]
    next_commands: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checklist_path": self.checklist_path,
            "worksheet_path": self.worksheet_path,
            "answers_path": self.answers_path,
            "evidence_manifest_path": self.evidence_manifest_path,
            "require_evidence_manifest": self.require_evidence_manifest,
            "sections": [section.to_dict() for section in self.sections],
            "next_commands": self.next_commands,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Source QA Evidence Readiness: {self.status}",
            "",
            f"- Checklist: `{self.checklist_path}`",
            f"- Worksheet: `{self.worksheet_path}`",
            f"- Answers: `{self.answers_path}`",
            f"- Evidence manifest: `{self.evidence_manifest_path}`",
            f"- Require evidence manifest: `{self.require_evidence_manifest}`",
            "",
            "## Sections",
            "",
            "| section | status | artifact | summary |",
            "| --- | --- | --- | --- |",
        ]
        for section in self.sections:
            lines.append(
                f"| `{section.name}` | `{section.status}` | `{section.artifact}` | {section.summary} |"
            )
        blocking_sections = [section for section in self.sections if section.blockers]
        if blocking_sections:
            lines.extend(["", "## Blockers"])
            for section in blocking_sections:
                lines.append(f"- `{section.name}`")
                lines.extend(f"  - {item}" for item in section.blockers[:8])
        lines.extend(["", "## Next Commands"])
        for command in self.next_commands:
            lines.append("")
            lines.append("```powershell")
            lines.append(command)
            lines.append("```")
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_source_qa_evidence_readiness(
    *,
    checklist_path: str | Path = "data_exports/data_source_qa.json",
    worksheet_path: str | Path = "data_exports/data_source_qa_evidence_worksheet.csv",
    answers_path: str | Path = "data_exports/data_source_qa_answers.json",
    evidence_manifest_path: str | Path = "data_exports/source_qa_evidence_manifest.json",
    review_artifact_path: str | Path | None = None,
    evidence_dir: str | Path | None = None,
    require_evidence_manifest: bool = True,
    encoding: str = "utf-8-sig",
) -> SourceQAEvidenceReadiness:
    checklist_file = Path(checklist_path)
    worksheet_file = Path(worksheet_path)
    answers_file = Path(answers_path)
    manifest_file = Path(evidence_manifest_path)
    review_artifact = Path(review_artifact_path) if review_artifact_path else checklist_file.parent / "data_source_qa_review.json"
    evidence_root = Path(evidence_dir) if evidence_dir is not None else manifest_file.parent / "source_qa_evidence"

    worksheet = build_data_source_qa_evidence_worksheet_preflight(
        checklist_path=checklist_file,
        worksheet_path=worksheet_file,
        encoding=encoding,
    )
    answers = build_source_qa_preflight(
        checklist_path=checklist_file,
        answers_path=answers_file,
        evidence_manifest_path=manifest_file if require_evidence_manifest else None,
        require_evidence_manifest=require_evidence_manifest,
    )
    manifest = build_source_qa_evidence_manifest_preflight(
        checklist_path=checklist_file,
        manifest_path=manifest_file,
        evidence_dir=evidence_root,
    )
    review = build_data_source_qa_review(
        checklist_path=checklist_file,
        answers_path=answers_file,
        evidence_manifest_path=manifest_file if require_evidence_manifest else None,
        require_evidence_manifest=require_evidence_manifest,
    )
    sections = [
        SourceQAEvidenceReadinessSection(
            name="worksheet_preflight",
            status=worksheet.status,
            artifact=str(worksheet_file),
            summary=_worksheet_summary(worksheet.to_dict()),
            blockers=_worksheet_blockers(worksheet.to_dict()),
            next_command=_first_command(worksheet.next_commands),
        ),
        SourceQAEvidenceReadinessSection(
            name="answers_preflight",
            status=answers.status,
            artifact=str(answers_file),
            summary=_answers_summary(answers.to_dict()),
            blockers=_answers_blockers(answers.to_dict()),
            next_command=_first_command(answers.next_commands),
        ),
        SourceQAEvidenceReadinessSection(
            name="manifest_preflight",
            status=manifest.status,
            artifact=str(manifest_file),
            summary=_manifest_summary(manifest.to_dict()),
            blockers=_manifest_blockers(manifest.to_dict()),
            next_command=_first_command(manifest.next_commands),
        ),
        SourceQAEvidenceReadinessSection(
            name="strict_source_qa_review",
            status=review.status,
            artifact=str(review_artifact),
            summary=_review_summary(review.to_dict()),
            blockers=_review_blockers(review.to_dict()),
        ),
    ]
    status = _combine_status([section.status for section in sections])
    return SourceQAEvidenceReadiness(
        status=status,
        checklist_path=str(checklist_file),
        worksheet_path=str(worksheet_file),
        answers_path=str(answers_file),
        evidence_manifest_path=str(manifest_file),
        require_evidence_manifest=require_evidence_manifest,
        sections=sections,
        next_commands=_readiness_next_commands(sections),
        prohibited_actions=[
            "Do not fabricate worksheet rows, answers, or evidence attachments to make readiness pass.",
            "Do not treat readiness PASS as strategy approval, profitability evidence, or live trading permission.",
            "Do not import offline data until deterministic source QA and data intake gates pass.",
            "Do not let LLM text override source QA evidence requirements.",
            "Do not connect this workflow to real broker order submission.",
        ],
    )


def write_source_qa_evidence_readiness(
    report: SourceQAEvidenceReadiness,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "source_qa_evidence_readiness.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "source_qa_evidence_readiness.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _combine_status(statuses: list[ReadinessStatus]) -> ReadinessStatus:
    if any(status == "BLOCK" for status in statuses):
        return "BLOCK"
    if any(status == "WATCH" for status in statuses):
        return "WATCH"
    return "PASS"


def _first_command(commands: list[str]) -> str:
    return next((command for command in commands if command), "")


def _readiness_next_commands(sections: list[SourceQAEvidenceReadinessSection]) -> list[str]:
    commands = [
        section.next_command
        for section in sections
        if section.status == "BLOCK" and section.next_command
    ]
    if commands:
        return list(dict.fromkeys(commands))
    commands = [
        section.next_command
        for section in sections
        if section.status == "WATCH" and section.next_command
    ]
    return list(dict.fromkeys(commands)) or [
        ".\\.venv\\Scripts\\python.exe examples\\run_data_source_qa_review.py "
        "--checklist data_exports\\data_source_qa.json "
        "--answers data_exports\\data_source_qa_answers.json "
        "--evidence-manifest data_exports\\source_qa_evidence_manifest.json "
        "--require-evidence-manifest --output-dir results\\import\\source_qa"
    ]


def _worksheet_summary(payload: dict[str, Any]) -> str:
    return f"rows={payload.get('row_count', 0)}, findings={len(payload.get('findings', []) or [])}"


def _answers_summary(payload: dict[str, Any]) -> str:
    return f"items={len(payload.get('items', []) or [])}, require_manifest={payload.get('require_evidence_manifest')}"


def _manifest_summary(payload: dict[str, Any]) -> str:
    return (
        f"required={len(payload.get('required_attachment_ids', []) or [])}, "
        f"missing={len(payload.get('missing_required_ids', []) or [])}, "
        f"invalid={payload.get('invalid_attachment_count', 0)}"
    )


def _review_summary(payload: dict[str, Any]) -> str:
    return f"findings={len(payload.get('findings', []) or [])}"


def _worksheet_blockers(payload: dict[str, Any]) -> list[str]:
    return _finding_blockers(payload.get("findings", []), key="field_or_question_id")


def _answers_blockers(payload: dict[str, Any]) -> list[str]:
    return [
        f"{item.get('field', 'source_qa')}: {item.get('message', '')}"
        for item in payload.get("items", []) or []
        if isinstance(item, dict) and item.get("status") in {"BLOCK", "WATCH"}
    ]


def _manifest_blockers(payload: dict[str, Any]) -> list[str]:
    return _finding_blockers(payload.get("findings", []), key="item_id")


def _review_blockers(payload: dict[str, Any]) -> list[str]:
    return [
        f"{item.get('code', 'SOURCE_QA')}: {item.get('message', '')}"
        for item in payload.get("findings", []) or []
        if isinstance(item, dict) and item.get("severity") in {"BLOCK", "WATCH"}
    ]


def _finding_blockers(findings: Any, *, key: str) -> list[str]:
    return [
        f"{item.get(key, 'source_qa')}: {item.get('message', '')}"
        for item in findings or []
        if isinstance(item, dict) and item.get("status") in {"BLOCK", "WATCH"}
    ]
