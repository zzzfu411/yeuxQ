"""Closeout roll-up for source QA evidence readiness.

The closeout is a single operator-facing cover sheet over the source QA
operator packet, evidence inbox, and deterministic evidence readiness report.
It never creates answers, evidence, approvals, strategy permission, or broker
instructions.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from quantify.data.source_qa_evidence_inbox import (
    SourceQAEvidenceInboxReport,
    build_source_qa_evidence_inbox,
)
from quantify.data.source_qa_operator_packet import (
    SourceQAOperatorPacket,
    build_source_qa_operator_packet,
)
from quantify.data.source_qa_readiness import (
    SourceQAEvidenceReadiness,
    build_source_qa_evidence_readiness,
)

SourceQACloseoutDecision = Literal["PASS", "WATCH", "BLOCK"]

PROHIBITED_ACTIONS = [
    "Do not treat this closeout as source evidence, strategy approval, paper approval, or live trading permission.",
    "Do not close a source QA action without changing retained real vendor/export evidence.",
    "Do not fabricate worksheet answers, evidence attachments, manifests, review notes, or approvals.",
    "Do not use LLM text, generated templates, or this closeout as evidence.",
    "Do not run guarded offline intake unless deterministic source QA readiness is PASS and downstream data gates allow it.",
    "Do not connect this workflow to real broker order submission.",
]


@dataclass(frozen=True, slots=True)
class SourceQACloseoutAction:
    sequence: int
    priority: str
    status: SourceQACloseoutDecision
    category: str
    item: str
    target: str
    action: str
    acceptance_criteria: str
    command: str
    source_artifact: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "sequence": self.sequence,
            "priority": self.priority,
            "status": self.status,
            "category": self.category,
            "item": self.item,
            "target": self.target,
            "action": self.action,
            "acceptance_criteria": self.acceptance_criteria,
            "command": self.command,
            "source_artifact": self.source_artifact,
        }


@dataclass(frozen=True, slots=True)
class SourceQACloseoutArtifact:
    name: str
    path: str
    status: str
    exists: bool

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "name": self.name,
            "path": self.path,
            "status": self.status,
            "exists": self.exists,
        }


@dataclass(frozen=True, slots=True)
class SourceQACloseoutNextStep:
    sequence: int
    status: SourceQACloseoutDecision
    title: str
    objective: str
    required_items: list[str]
    command: str
    acceptance_criteria: str
    blocks_stage: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "status": self.status,
            "title": self.title,
            "objective": self.objective,
            "required_items": self.required_items,
            "command": self.command,
            "acceptance_criteria": self.acceptance_criteria,
            "blocks_stage": self.blocks_stage,
        }


@dataclass(frozen=True, slots=True)
class SourceQACloseout:
    decision: SourceQACloseoutDecision
    as_of: str
    data_dir: str
    report_dir: str
    checklist_path: str
    worksheet_path: str
    answers_path: str
    evidence_dir: str
    evidence_manifest_path: str
    require_evidence_manifest: bool
    component_statuses: dict[str, str]
    artifact_manifest: list[SourceQACloseoutArtifact]
    counts: dict[str, int]
    allowed_next_stage: str
    next_action: str
    next_steps: list[SourceQACloseoutNextStep]
    actions: list[SourceQACloseoutAction]
    command_sequence: list[str]
    capability_flags: dict[str, bool]
    acceptance_criteria: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "as_of": self.as_of,
            "data_dir": self.data_dir,
            "report_dir": self.report_dir,
            "checklist_path": self.checklist_path,
            "worksheet_path": self.worksheet_path,
            "answers_path": self.answers_path,
            "evidence_dir": self.evidence_dir,
            "evidence_manifest_path": self.evidence_manifest_path,
            "require_evidence_manifest": self.require_evidence_manifest,
            "component_statuses": self.component_statuses,
            "artifact_manifest": [artifact.to_dict() for artifact in self.artifact_manifest],
            "counts": self.counts,
            "allowed_next_stage": self.allowed_next_stage,
            "next_action": self.next_action,
            "next_steps": [step.to_dict() for step in self.next_steps],
            "actions": [action.to_dict() for action in self.actions],
            "command_sequence": self.command_sequence,
            "capability_flags": self.capability_flags,
            "acceptance_criteria": self.acceptance_criteria,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Source QA Closeout: {self.decision}",
            "",
            f"- As of: `{self.as_of}`",
            f"- Data directory: `{self.data_dir}`",
            f"- Report directory: `{self.report_dir}`",
            f"- Checklist: `{self.checklist_path}`",
            f"- Worksheet: `{self.worksheet_path}`",
            f"- Answers: `{self.answers_path}`",
            f"- Evidence directory: `{self.evidence_dir}`",
            f"- Evidence manifest: `{self.evidence_manifest_path}`",
            f"- Require evidence manifest: `{self.require_evidence_manifest}`",
            "",
            "This closeout is a roll-up over deterministic source QA artifacts. It does not create evidence, approve strategy research, approve paper trading, or authorize live orders.",
            "",
            "## Component Status",
            "",
            "| component | status |",
            "| --- | --- |",
        ]
        for name, status in self.component_statuses.items():
            lines.append(f"| `{name}` | `{status}` |")
        lines.extend(["", "## Artifact Manifest", "", "| artifact | status | exists | path |", "| --- | --- | --- | --- |"])
        for artifact in self.artifact_manifest:
            lines.append(
                f"| `{artifact.name}` | `{artifact.status}` | `{str(artifact.exists).lower()}` | `{artifact.path}` |"
            )
        lines.extend(["", "## Counts", "", "| metric | value |", "| --- | ---: |"])
        for name, value in self.counts.items():
            lines.append(f"| `{name}` | {value} |")
        lines.extend(
            [
                "",
                "## Next Action",
                "",
                f"- Allowed next stage: `{self.allowed_next_stage}`",
                f"- {self.next_action or 'None.'}",
            ]
        )
        lines.extend(["", "## Minimum Next Steps", ""])
        if self.next_steps:
            for step in self.next_steps:
                lines.extend(
                    [
                        f"### {step.sequence}. `{step.title}`",
                        "",
                        f"- Status: `{step.status}`",
                        f"- Blocks stage: `{step.blocks_stage}`",
                        f"- Objective: {step.objective}",
                        f"- Acceptance: {step.acceptance_criteria}",
                    ]
                )
                if step.required_items:
                    lines.append("- Required items:")
                    lines.extend(f"  - {item}" for item in step.required_items)
                if step.command:
                    lines.extend(["", "```powershell", step.command, "```", ""])
        else:
            lines.append("- None.")
        lines.extend(["", "## Actions", ""])
        if self.actions:
            lines.append("| seq | priority | status | category | item | target | command |")
            lines.append("| ---: | --- | --- | --- | --- | --- | --- |")
            for action in self.actions:
                lines.append(
                    f"| {action.sequence} | `{action.priority}` | `{action.status}` | `{action.category}` | `{action.item}` | `{action.target}` | `{_cell(action.command)}` |"
                )
        else:
            lines.append("- None.")
        lines.extend(["", "## Command Sequence"])
        for index, command in enumerate(self.command_sequence, start=1):
            lines.extend(["", f"{index}.", "", "```powershell", command, "```"])
        lines.extend(["", "## Capability Flags", "", "| flag | value |", "| --- | --- |"])
        for name, value in self.capability_flags.items():
            lines.append(f"| `{name}` | `{str(value).lower()}` |")
        lines.extend(["", "## Acceptance Criteria"])
        lines.extend(f"- {item}" for item in self.acceptance_criteria)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_source_qa_closeout(
    *,
    data_dir: str | Path = "data_exports",
    report_dir: str | Path = "results/first_million",
    checklist_path: str | Path | None = None,
    worksheet_path: str | Path | None = None,
    answers_path: str | Path | None = None,
    evidence_dir: str | Path | None = None,
    evidence_manifest_path: str | Path | None = None,
    require_evidence_manifest: bool = True,
    as_of: str | None = None,
    encoding: str = "utf-8-sig",
    operator_packet: SourceQAOperatorPacket | None = None,
    evidence_inbox: SourceQAEvidenceInboxReport | None = None,
    evidence_readiness: SourceQAEvidenceReadiness | None = None,
) -> SourceQACloseout:
    data_root = Path(data_dir)
    report_root = Path(report_dir)
    checklist_file = Path(checklist_path) if checklist_path else data_root / "data_source_qa.json"
    worksheet_file = Path(worksheet_path) if worksheet_path else data_root / "data_source_qa_evidence_worksheet.csv"
    answers_file = Path(answers_path) if answers_path else data_root / "data_source_qa_answers.json"
    evidence_root = Path(evidence_dir) if evidence_dir else data_root / "source_qa_evidence"
    manifest_file = (
        Path(evidence_manifest_path)
        if evidence_manifest_path
        else data_root / "source_qa_evidence_manifest.json"
    )
    packet = operator_packet or build_source_qa_operator_packet(
        data_dir=data_root,
        report_dir=report_root,
        as_of=as_of,
    )
    inbox = evidence_inbox or build_source_qa_evidence_inbox(
        data_dir=data_root,
        report_dir=report_root,
        checklist_path=checklist_file,
        evidence_dir=evidence_root,
        manifest_path=manifest_file,
        as_of=as_of,
    )
    readiness = evidence_readiness or build_source_qa_evidence_readiness(
        checklist_path=checklist_file,
        worksheet_path=worksheet_file,
        answers_path=answers_file,
        evidence_manifest_path=manifest_file,
        review_artifact_path=report_root / "source_qa" / "data_source_qa_review.json",
        evidence_dir=evidence_root,
        require_evidence_manifest=require_evidence_manifest,
        encoding=encoding,
    )
    packet_payload = packet.to_dict()
    inbox_payload = inbox.to_dict()
    readiness_payload = readiness.to_dict()
    component_statuses = {
        "source_qa_operator_packet": _status(packet_payload.get("decision")),
        "source_qa_evidence_inbox": _status(inbox_payload.get("status")),
        "source_qa_evidence_readiness": _status(readiness_payload.get("status")),
    }
    decision = _combine_status(component_statuses.values())
    actions = _actions(
        packet_payload=packet_payload,
        inbox_payload=inbox_payload,
        readiness_payload=readiness_payload,
    )
    effective_as_of = str(as_of or packet_payload.get("as_of") or inbox_payload.get("as_of") or "<YYYY-MM-DD>")
    counts = _counts(
        actions=actions,
        packet_payload=packet_payload,
        inbox_payload=inbox_payload,
        readiness_payload=readiness_payload,
    )
    return SourceQACloseout(
        decision=decision,
        as_of=str(as_of or packet_payload.get("as_of") or inbox_payload.get("as_of") or "unspecified"),
        data_dir=str(data_root),
        report_dir=str(report_root),
        checklist_path=str(checklist_file),
        worksheet_path=str(worksheet_file),
        answers_path=str(answers_file),
        evidence_dir=str(evidence_root),
        evidence_manifest_path=str(manifest_file),
        require_evidence_manifest=require_evidence_manifest,
        component_statuses=component_statuses,
        artifact_manifest=_artifact_manifest(
            report_root=report_root,
            checklist_file=checklist_file,
            worksheet_file=worksheet_file,
            answers_file=answers_file,
            evidence_root=evidence_root,
            manifest_file=manifest_file,
            component_statuses=component_statuses,
            readiness_payload=readiness_payload,
        ),
        counts=counts,
        allowed_next_stage=_allowed_next_stage(decision, actions),
        next_action=_next_action(decision, actions),
        next_steps=_next_steps(
            decision=decision,
            actions=actions,
            data_root=data_root,
            report_root=report_root,
            as_of=effective_as_of,
        ),
        actions=actions,
        command_sequence=_command_sequence(
            decision=decision,
            actions=actions,
            packet_payload=packet_payload,
            inbox_payload=inbox_payload,
            readiness_payload=readiness_payload,
            report_root=report_root,
            data_root=data_root,
            as_of=effective_as_of,
        ),
        capability_flags={
            "source_qa_closeout_passed": decision == "PASS",
            "source_qa_evidence_complete": decision == "PASS",
            "can_run_guarded_intake_by_itself": False,
            "can_enter_candidate_research_by_itself": False,
            "can_enter_paper": False,
            "can_enter_micro_live": False,
            "can_enter_live": False,
            "can_generate_broker_orders": False,
            "can_override_deterministic_gates": False,
        },
        acceptance_criteria=[
            "source_qa_operator_packet has no missing worksheet rows or required attachments.",
            "source_qa_evidence_inbox maps every required attachment to retained non-placeholder local evidence.",
            "source_qa_evidence_readiness is PASS with strict evidence manifest review enabled when required.",
            "Downstream guarded intake and candidate research still run their own deterministic gates.",
            "Paper, micro-live, live trading, and broker order generation remain prohibited by this closeout.",
        ],
        prohibited_actions=PROHIBITED_ACTIONS,
    )


def write_source_qa_closeout(closeout: SourceQACloseout, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "source_qa_closeout.json").write_text(
        json.dumps(closeout.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "source_qa_closeout.md").write_text(closeout.to_markdown(), encoding="utf-8")
    with (root / "source_qa_closeout.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        fieldnames = [
            "sequence",
            "priority",
            "status",
            "category",
            "item",
            "target",
            "action",
            "acceptance_criteria",
            "command",
            "source_artifact",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(action.to_dict() for action in closeout.actions)
    return root


def _actions(
    *,
    packet_payload: dict[str, Any],
    inbox_payload: dict[str, Any],
    readiness_payload: dict[str, Any],
) -> list[SourceQACloseoutAction]:
    actions: list[SourceQACloseoutAction] = []
    seen: set[tuple[str, str]] = set()
    for item in packet_payload.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("item_type") or "")
        item_id = str(item.get("item_id") or "").strip()
        if not item_id:
            continue
        category = "source_qa_attachment" if item_type == "attachment" else "source_qa_worksheet"
        key = (category, item_id)
        if key in seen:
            continue
        seen.add(key)
        actions.append(
            SourceQACloseoutAction(
                sequence=len(actions) + 1,
                priority="P0",
                status="BLOCK",
                category=category,
                item=item_id,
                target=str(item.get("target") or ""),
                action=_packet_action(category, item),
                acceptance_criteria=_packet_acceptance(category),
                command=str(item.get("command_after_completion") or ""),
                source_artifact="source_qa_operator_packet.json",
            )
        )
    for item in inbox_payload.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        status = _status(item.get("status"))
        if status == "PASS":
            continue
        item_id = str(item.get("item_id") or "").strip()
        if not item_id:
            continue
        category = "source_qa_attachment"
        key = (category, item_id)
        if key in seen:
            continue
        seen.add(key)
        actions.append(
            SourceQACloseoutAction(
                sequence=len(actions) + 1,
                priority="P0" if status == "BLOCK" else "P1",
                status=status,
                category=category,
                item=item_id,
                target=str(item.get("target_path") or ""),
                action=str(item.get("message") or "Review retained source QA evidence file."),
                acceptance_criteria="A retained local evidence file is present, non-placeholder, and accepted by strict source QA review.",
                command=str(item.get("next_command") or ""),
                source_artifact="source_qa_evidence_inbox.json",
            )
        )
    for section in readiness_payload.get("sections", []) or []:
        if not isinstance(section, dict):
            continue
        status = _status(section.get("status"))
        if status == "PASS":
            continue
        blockers = [str(item) for item in section.get("blockers", []) or [] if str(item).strip()]
        if not blockers:
            blockers = [str(section.get("summary") or "Readiness section is not PASS.")]
        for blocker in blockers[:3]:
            item_name = f"{section.get('name', 'section')}: {blocker}"
            key = ("source_qa_readiness", item_name)
            if key in seen:
                continue
            seen.add(key)
            actions.append(
                SourceQACloseoutAction(
                    sequence=len(actions) + 1,
                    priority="P0" if status == "BLOCK" else "P1",
                    status=status,
                    category="source_qa_readiness",
                    item=item_name,
                    target=str(section.get("artifact") or ""),
                    action="Fix the underlying worksheet, answers, manifest, or strict review blocker.",
                    acceptance_criteria="Rerun source QA evidence readiness and confirm this section is PASS.",
                    command=str(section.get("next_command") or ""),
                    source_artifact="source_qa_evidence_readiness.json",
                )
            )
    return actions


def _packet_action(category: str, item: dict[str, Any]) -> str:
    if category == "source_qa_attachment":
        return (
            "Attach retained local source evidence; do not use generated files. "
            f"Required evidence: {item.get('evidence_required', '')}"
        ).strip()
    return (
        "Fill the worksheet row from retained vendor/export evidence; do not use placeholders. "
        f"Answer required: {item.get('answer_required', '')}"
    ).strip()


def _packet_acceptance(category: str) -> str:
    if category == "source_qa_attachment":
        return "Strict source QA evidence manifest includes the retained file with a valid sha256 and accepted id."
    return "Worksheet preflight is not BLOCK and the row is converted into data_source_qa_answers.json only after strict review."


def _artifact_manifest(
    *,
    report_root: Path,
    checklist_file: Path,
    worksheet_file: Path,
    answers_file: Path,
    evidence_root: Path,
    manifest_file: Path,
    component_statuses: dict[str, str],
    readiness_payload: dict[str, Any],
) -> list[SourceQACloseoutArtifact]:
    strict_review = _strict_review_artifact(readiness_payload)
    worksheet_status = _section_status(
        readiness_payload,
        "worksheet_preflight",
        fallback="PASS" if worksheet_file.exists() else "BLOCK",
    )
    answers_status = _section_status(
        readiness_payload,
        "answers_preflight",
        fallback="PASS" if answers_file.exists() else "BLOCK",
    )
    manifest_status = _section_status(
        readiness_payload,
        "manifest_preflight",
        fallback="PASS" if manifest_file.exists() else "BLOCK",
    )
    artifacts = [
        ("source_qa_operator_packet", report_root / "source_qa_operator_packet.json", component_statuses["source_qa_operator_packet"]),
        ("source_qa_evidence_inbox", report_root / "source_qa_evidence_inbox.json", component_statuses["source_qa_evidence_inbox"]),
        ("source_qa_evidence_readiness", report_root / "source_qa" / "source_qa_evidence_readiness.json", component_statuses["source_qa_evidence_readiness"]),
        ("strict_source_qa_review", strict_review, _strict_review_status(readiness_payload)),
        ("data_source_qa_checklist", checklist_file, "PASS" if checklist_file.exists() else "BLOCK"),
        ("data_source_qa_worksheet", worksheet_file, worksheet_status),
        ("data_source_qa_answers", answers_file, answers_status),
        ("source_qa_evidence_manifest", manifest_file, manifest_status),
        ("source_qa_evidence_dir", evidence_root, "PASS" if evidence_root.exists() else "BLOCK"),
    ]
    return [
        SourceQACloseoutArtifact(
            name=name,
            path=str(path),
            status=status,
            exists=path.exists(),
        )
        for name, path, status in artifacts
    ]


def _strict_review_artifact(readiness_payload: dict[str, Any]) -> Path:
    for section in readiness_payload.get("sections", []) or []:
        if isinstance(section, dict) and section.get("name") == "strict_source_qa_review":
            artifact = str(section.get("artifact") or "").strip()
            if artifact:
                return Path(artifact)
    return Path("data_exports") / "data_source_qa_review.json"


def _strict_review_status(readiness_payload: dict[str, Any]) -> str:
    return _section_status(readiness_payload, "strict_source_qa_review", fallback="BLOCK")


def _section_status(
    readiness_payload: dict[str, Any],
    name: str,
    *,
    fallback: str,
) -> str:
    for section in readiness_payload.get("sections", []) or []:
        if isinstance(section, dict) and section.get("name") == name:
            return _status(section.get("status"))
    return _status(fallback)


def _counts(
    *,
    actions: list[SourceQACloseoutAction],
    packet_payload: dict[str, Any],
    inbox_payload: dict[str, Any],
    readiness_payload: dict[str, Any],
) -> dict[str, int]:
    sections = readiness_payload.get("sections", []) or []
    blocking_sections = [
        item
        for item in sections
        if isinstance(item, dict) and _status(item.get("status")) == "BLOCK"
    ]
    watch_sections = [
        item
        for item in sections
        if isinstance(item, dict) and _status(item.get("status")) == "WATCH"
    ]
    return {
        "missing_worksheet_count": _int(packet_payload.get("missing_worksheet_count")),
        "missing_attachment_count": _int(packet_payload.get("missing_attachment_count")),
        "inbox_required_item_count": _int(inbox_payload.get("required_item_count")),
        "inbox_matched_item_count": _int(inbox_payload.get("matched_item_count")),
        "inbox_missing_item_count": _int(inbox_payload.get("missing_item_count")),
        "inbox_invalid_file_count": _int(inbox_payload.get("invalid_file_count")),
        "readiness_blocking_section_count": len(blocking_sections),
        "readiness_watch_section_count": len(watch_sections),
        "open_action_count": sum(1 for action in actions if action.status in {"BLOCK", "WATCH"}),
    }


def _allowed_next_stage(
    decision: SourceQACloseoutDecision,
    actions: list[SourceQACloseoutAction],
) -> str:
    if decision == "PASS":
        return "GUARDED_OFFLINE_INTAKE"
    open_actions = [action for action in actions if action.status in {"BLOCK", "WATCH"}]
    if not open_actions:
        return "RUN_READINESS"
    if any(action.category != "source_qa_readiness" for action in open_actions):
        return "COLLECT_EVIDENCE"
    return "RUN_READINESS"


def _next_action(
    decision: SourceQACloseoutDecision,
    actions: list[SourceQACloseoutAction],
) -> str:
    open_actions = [action for action in actions if action.status in {"BLOCK", "WATCH"}]
    if open_actions:
        first = open_actions[0]
        return f"Start with `{first.category}/{first.item}`: {first.action}"
    if decision == "PASS":
        return "Source QA evidence closeout is PASS; continue only to guarded offline intake and downstream deterministic gates."
    return "Rerun source QA closeout after changing retained evidence artifacts."


def _next_steps(
    *,
    decision: SourceQACloseoutDecision,
    actions: list[SourceQACloseoutAction],
    data_root: Path,
    report_root: Path,
    as_of: str,
) -> list[SourceQACloseoutNextStep]:
    open_actions = [action for action in actions if action.status in {"BLOCK", "WATCH"}]
    if decision == "PASS":
        return [
            SourceQACloseoutNextStep(
                sequence=1,
                status="PASS",
                title="continue_to_guarded_offline_intake",
                objective="Source QA closeout passed; continue only through downstream deterministic gates.",
                required_items=[],
                command=(
                    ".\\.venv\\Scripts\\python.exe examples\\run_first_million_pipeline.py "
                    "--config config\\research_recent.yaml "
                    f"--data-dir {data_root} --output-dir {report_root} "
                    f"--source-qa-answers {data_root / 'data_source_qa_answers.json'} "
                    f"--source-qa-evidence-manifest {data_root / 'source_qa_evidence_manifest.json'} "
                    f"--require-source-qa-evidence-manifest --as-of {as_of} --min-symbols 300 --no-registry"
                ),
                acceptance_criteria="Downstream offline intake, data audit, candidate launch, paper, and approval gates still pass on their own.",
                blocks_stage="none",
            )
        ]
    if not open_actions:
        return [
            SourceQACloseoutNextStep(
                sequence=1,
                status="WATCH",
                title="rerun_source_qa_readiness",
                objective="No open collection action was found, but closeout is not PASS.",
                required_items=[],
                command=_closeout_command(data_root=data_root, report_root=report_root, as_of=as_of),
                acceptance_criteria="source_qa_closeout.json is PASS or lists concrete collection actions.",
                blocks_stage="guarded_offline_intake",
            )
        ]

    steps: list[SourceQACloseoutNextStep] = []
    attachment_actions = [
        action for action in open_actions if action.category == "source_qa_attachment"
    ]
    worksheet_actions = [
        action for action in open_actions if action.category == "source_qa_worksheet"
    ]
    readiness_actions = [
        action for action in open_actions if action.category == "source_qa_readiness"
    ]
    if attachment_actions:
        steps.append(
            SourceQACloseoutNextStep(
                sequence=len(steps) + 1,
                status=_combine_status(action.status for action in attachment_actions),
                title="attach_retained_source_qa_evidence",
                objective=(
                    "Add real retained source/vendor evidence files under "
                    f"{data_root / 'source_qa_evidence'}; generated plans or templates are not evidence."
                ),
                required_items=_action_items(attachment_actions),
                command=_first_command(attachment_actions)
                or (
                    ".\\.venv\\Scripts\\python.exe examples\\write_source_qa_evidence_manifest.py "
                    f"--checklist {data_root / 'data_source_qa.json'} "
                    f"--evidence-dir {data_root / 'source_qa_evidence'} "
                    f"--output-dir {data_root} --strict"
                ),
                acceptance_criteria="Every required attachment is present, non-placeholder, hashed, and accepted by the strict source QA manifest review.",
                blocks_stage="source_qa_answers",
            )
        )
    if worksheet_actions:
        steps.append(
            SourceQACloseoutNextStep(
                sequence=len(steps) + 1,
                status=_combine_status(action.status for action in worksheet_actions),
                title="fill_source_qa_worksheet",
                objective="Fill missing worksheet rows from retained vendor/export evidence.",
                required_items=_action_items(worksheet_actions),
                command=_first_command(worksheet_actions),
                acceptance_criteria="Worksheet preflight is not BLOCK and no placeholder values remain.",
                blocks_stage="source_qa_answers",
            )
        )
    if readiness_actions or attachment_actions or worksheet_actions:
        validation_commands = [
            ".\\.venv\\Scripts\\python.exe examples\\run_data_source_qa_worksheet_preflight.py "
            f"--checklist {data_root / 'data_source_qa.json'} "
            f"--worksheet {data_root / 'data_source_qa_evidence_worksheet.csv'} "
            f"--output-dir {data_root}",
            ".\\.venv\\Scripts\\python.exe examples\\write_source_qa_evidence_manifest.py "
            f"--checklist {data_root / 'data_source_qa.json'} "
            f"--evidence-dir {data_root / 'source_qa_evidence'} --output-dir {data_root} --strict",
            ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa_answers.py "
            f"--checklist {data_root / 'data_source_qa.json'} "
            f"--worksheet {data_root / 'data_source_qa_evidence_worksheet.csv'} "
            f"--output {data_root / 'data_source_qa_answers.json'} "
            f"--evidence-manifest {data_root / 'source_qa_evidence_manifest.json'} "
            "--require-evidence-manifest",
            ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_evidence_readiness.py "
            f"--checklist {data_root / 'data_source_qa.json'} "
            f"--worksheet {data_root / 'data_source_qa_evidence_worksheet.csv'} "
            f"--answers {data_root / 'data_source_qa_answers.json'} "
            f"--evidence-manifest {data_root / 'source_qa_evidence_manifest.json'} "
            f"--require-evidence-manifest --output-dir {report_root / 'source_qa'}",
            _closeout_command(data_root=data_root, report_root=report_root, as_of=as_of),
        ]
        steps.append(
            SourceQACloseoutNextStep(
                sequence=len(steps) + 1,
                status=_combine_status(action.status for action in open_actions),
                title="rerun_strict_source_qa_review",
                objective="Regenerate answers only after worksheet and attachment evidence are complete, then refresh closeout.",
                required_items=_action_items(readiness_actions),
                command="\n".join(validation_commands),
                acceptance_criteria="source_qa_closeout.json is PASS before guarded offline intake can even be considered.",
                blocks_stage="guarded_offline_intake",
            )
        )
    return steps


def _action_items(actions: list[SourceQACloseoutAction], *, limit: int = 12) -> list[str]:
    items = [f"{action.item}: {action.target}".strip() for action in actions]
    if len(items) <= limit:
        return items
    remaining = len(items) - limit
    return [*items[:limit], f"... {remaining} more item(s) in source_qa_closeout.csv"]


def _first_command(actions: list[SourceQACloseoutAction]) -> str:
    for action in actions:
        if action.command:
            return action.command
    return ""


def _closeout_command(*, data_root: Path, report_root: Path, as_of: str) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_closeout.py "
        f"--data-dir {data_root} --report-dir {report_root} "
        "--checklist {checklist} --worksheet {worksheet} --answers {answers} "
        "--evidence-manifest {manifest} --require-evidence-manifest "
        "--output-dir {report_dir} --as-of {as_of}".format(
            checklist=data_root / "data_source_qa.json",
            worksheet=data_root / "data_source_qa_evidence_worksheet.csv",
            answers=data_root / "data_source_qa_answers.json",
            manifest=data_root / "source_qa_evidence_manifest.json",
            report_dir=report_root,
            as_of=as_of,
        )
    )


def _command_sequence(
    *,
    decision: SourceQACloseoutDecision,
    actions: list[SourceQACloseoutAction],
    packet_payload: dict[str, Any],
    inbox_payload: dict[str, Any],
    readiness_payload: dict[str, Any],
    report_root: Path,
    data_root: Path,
    as_of: str,
) -> list[str]:
    commands = [action.command for action in actions if action.command]
    commands.extend(str(item) for item in packet_payload.get("command_sequence", []) or [] if item)
    commands.extend(str(item) for item in inbox_payload.get("next_commands", []) or [] if item)
    commands.extend(str(item) for item in readiness_payload.get("next_commands", []) or [] if item)
    commands.append(
        ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_closeout.py "
        f"--data-dir {data_root} --report-dir {report_root} "
        "--checklist {checklist} --worksheet {worksheet} --answers {answers} "
        "--evidence-manifest {manifest} --require-evidence-manifest "
        "--output-dir {report_dir} --as-of {as_of}".format(
            checklist=data_root / "data_source_qa.json",
            worksheet=data_root / "data_source_qa_evidence_worksheet.csv",
            answers=data_root / "data_source_qa_answers.json",
            manifest=data_root / "source_qa_evidence_manifest.json",
            report_dir=report_root,
            as_of=as_of,
        )
    )
    if decision == "PASS":
        commands.append(
            ".\\.venv\\Scripts\\python.exe examples\\run_first_million_pipeline.py "
            "--config config\\research_recent.yaml "
            f"--data-dir {data_root} --output-dir {report_root} "
            f"--source-qa-answers {data_root / 'data_source_qa_answers.json'} "
            f"--source-qa-evidence-manifest {data_root / 'source_qa_evidence_manifest.json'} "
            f"--require-source-qa-evidence-manifest --as-of {as_of} --min-symbols 300 --no-registry"
        )
    return _dedupe([command.strip() for command in commands if command.strip()])[:20]


def _combine_status(statuses: Any) -> SourceQACloseoutDecision:
    normalized = [_status(status) for status in statuses]
    if any(status == "BLOCK" for status in normalized):
        return "BLOCK"
    if any(status == "WATCH" for status in normalized):
        return "WATCH"
    return "PASS"


def _status(value: object) -> SourceQACloseoutDecision:
    text = str(value or "").strip().upper()
    if text == "PASS":
        return "PASS"
    if text == "WATCH":
        return "WATCH"
    return "BLOCK"


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _cell(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")
