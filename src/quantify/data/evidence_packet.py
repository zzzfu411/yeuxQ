"""Action packet for collecting real A-share data evidence.

The packet is a human-facing bridge from current BLOCK data gates to the next
concrete export and source-QA steps. It does not weaken any deterministic gate.
"""
from __future__ import annotations

from dataclasses import dataclass
import csv
import json
from pathlib import Path
from typing import Any, Literal

from quantify.data.export_request import DataExportRequest, build_data_export_request
from quantify.data.csv_intake_preview import build_csv_intake_preview
from quantify.data.gap_action_plan import DataGapActionPlan, build_data_gap_action_plan
from quantify.data.source_qa import (
    REQUIRED_SOURCE_METADATA,
    build_data_source_qa,
    build_data_source_qa_evidence_worksheet_preflight,
    build_data_source_qa_review,
    validate_source_qa_attachment,
    weak_source_evidence,
)

PacketDecision = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class DataEvidenceActionPacket:
    decision: PacketDecision
    as_of: str | None
    data_dir: str
    config_path: str
    source_qa_answers_path: str
    current_blockers: list[dict[str, str]]
    watch_items: list[dict[str, str]]
    required_exports: list[dict[str, Any]]
    source_qa_fields_to_fill: list[str]
    source_metadata_fields_to_fill: list[str]
    source_qa_evidence_to_fill: list[dict[str, str]]
    source_qa_worksheet_status: dict[str, Any]
    source_qa_evidence_manifest_status: dict[str, Any]
    operator_checklist: list[str]
    immediate_commands: list[str]
    completion_criteria: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "as_of": self.as_of,
            "data_dir": self.data_dir,
            "config_path": self.config_path,
            "source_qa_answers_path": self.source_qa_answers_path,
            "current_blockers": self.current_blockers,
            "watch_items": self.watch_items,
            "required_exports": self.required_exports,
            "source_qa_fields_to_fill": self.source_qa_fields_to_fill,
            "source_metadata_fields_to_fill": self.source_metadata_fields_to_fill,
            "source_qa_evidence_to_fill": self.source_qa_evidence_to_fill,
            "source_qa_worksheet_status": self.source_qa_worksheet_status,
            "source_qa_evidence_manifest_status": self.source_qa_evidence_manifest_status,
            "operator_checklist": self.operator_checklist,
            "immediate_commands": self.immediate_commands,
            "completion_criteria": self.completion_criteria,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Data Evidence Action Packet: {self.decision}",
            "",
            f"- As of: `{self.as_of or 'unspecified'}`",
            f"- Data directory: `{self.data_dir}`",
            f"- Config: `{self.config_path}`",
            f"- Source QA answers: `{self.source_qa_answers_path}`",
            "",
            "## Current Blockers",
        ]
        if self.current_blockers:
            lines.extend(
                f"- `{item['name']}`: {item['message']} Next: {item['next_action']}"
                for item in self.current_blockers
            )
        else:
            lines.append("- None.")
        lines.extend(["", "## Watch Items"])
        if self.watch_items:
            lines.extend(
                f"- `{item['name']}`: {item['message']} Next: {item['next_action']}"
                for item in self.watch_items
            )
        else:
            lines.append("- None.")
        lines.extend(["", "## Required Exports", ""])
        lines.append("| file | required | columns |")
        lines.append("| --- | --- | --- |")
        for item in self.required_exports:
            required = "yes" if item["required"] else "recommended"
            lines.append(f"| `{item['file_name']}` | `{required}` | `{', '.join(item['columns'])}` |")
        lines.extend(["", "## Source QA Fields To Fill"])
        lines.extend(f"- `{field}`" for field in self.source_qa_fields_to_fill)
        lines.extend(["", "## Source QA Evidence To Fill"])
        for item in self.source_qa_evidence_to_fill:
            lines.append(
                f"- `{item['id']}` ({item['severity']}): {item['required_evidence']}"
            )
        worksheet = self.source_qa_worksheet_status
        lines.extend(["", "## Source QA Worksheet Status"])
        lines.append(f"- Path: `{worksheet.get('path', '')}`")
        lines.append(f"- Status: `{worksheet.get('status', 'UNKNOWN')}`")
        lines.append(f"- Rows total: {worksheet.get('row_count', 0)}")
        lines.append(f"- Rows complete: {worksheet.get('complete_row_count', 0)}")
        lines.append(f"- Rows missing: {worksheet.get('missing_row_count', 0)}")
        if worksheet.get("missing_rows"):
            lines.append("- Missing rows:")
            for item in worksheet.get("missing_rows", []):
                lines.append(
                    f"  - `{item['id']}` ({item['row_type']}): {item['message']}"
                )
        else:
            lines.append("- Missing rows: none.")
        if worksheet.get("next_command"):
            lines.append("- Next command after filling worksheet:")
            lines.append("")
            lines.append("```powershell")
            lines.append(str(worksheet["next_command"]))
            lines.append("```")
        manifest = self.source_qa_evidence_manifest_status
        lines.extend(["", "## Source QA Evidence Manifest Status"])
        lines.append(f"- Path: `{manifest.get('path', '')}`")
        lines.append(f"- Evidence directory: `{manifest.get('evidence_dir', '')}`")
        lines.append(f"- Status: `{manifest.get('status', 'UNKNOWN')}`")
        lines.append(f"- Required attachments: {manifest.get('required_attachment_count', 0)}")
        lines.append(f"- Valid required attachment ids: {manifest.get('valid_required_id_count', 0)}")
        lines.append(f"- Missing attachments: {manifest.get('missing_attachment_count', 0)}")
        lines.append(f"- Invalid attachments: {manifest.get('invalid_attachment_count', 0)}")
        if manifest.get("missing_attachments"):
            lines.append("- Missing attachment ids:")
            for item in manifest.get("missing_attachments", []):
                lines.append(f"  - `{item['id']}`: {item['required_evidence']}")
        else:
            lines.append("- Missing attachment ids: none.")
        if manifest.get("next_command"):
            lines.append("- Next command after adding attachment files:")
            lines.append("")
            lines.append("```powershell")
            lines.append(str(manifest["next_command"]))
            lines.append("```")
        lines.extend(["", "## Operator Checklist"])
        lines.extend(f"- {item}" for item in self.operator_checklist)
        lines.extend(["", "## Immediate Commands"])
        for command in self.immediate_commands:
            lines.append("")
            lines.append("```powershell")
            lines.append(command)
            lines.append("```")
        lines.extend(["", "## Completion Criteria"])
        lines.extend(f"- {item}" for item in self.completion_criteria)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class OperatorHandoffStatus:
    status: PacketDecision
    packet_decision: PacketDecision
    as_of: str | None
    operator_handoff_path: str
    total_task_count: int
    open_task_count: int
    p0_open_task_count: int
    p1_open_task_count: int
    source_qa_open_task_count: int
    source_qa_attachment_open_task_count: int
    data_export_open_task_count: int
    completed_task_count: int
    first_open_tasks: list[dict[str, str]]
    next_batch: dict[str, Any]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "packet_decision": self.packet_decision,
            "as_of": self.as_of,
            "operator_handoff_path": self.operator_handoff_path,
            "total_task_count": self.total_task_count,
            "open_task_count": self.open_task_count,
            "p0_open_task_count": self.p0_open_task_count,
            "p1_open_task_count": self.p1_open_task_count,
            "source_qa_open_task_count": self.source_qa_open_task_count,
            "source_qa_attachment_open_task_count": self.source_qa_attachment_open_task_count,
            "data_export_open_task_count": self.data_export_open_task_count,
            "completed_task_count": self.completed_task_count,
            "first_open_tasks": self.first_open_tasks,
            "next_batch": self.next_batch,
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Operator Handoff Status: {self.status}",
            "",
            f"- Packet decision: `{self.packet_decision}`",
            f"- As of: `{self.as_of or 'unspecified'}`",
            f"- Handoff: `{self.operator_handoff_path}`",
            f"- Total tasks: {self.total_task_count}",
            f"- Open tasks: {self.open_task_count}",
            f"- Open P0 tasks: {self.p0_open_task_count}",
            f"- Open P1 tasks: {self.p1_open_task_count}",
            f"- Completed tasks: {self.completed_task_count}",
            "",
            "This status only tracks the operator handoff queue. It is not a "
            "strategy approval, profitability claim, paper promotion, or live trading permission.",
            "",
            "## First Open Tasks",
            "",
        ]
        if self.first_open_tasks:
            lines.append("| priority | task type | item | status | target | next command | action |")
            lines.append("| --- | --- | --- | --- | --- | --- | --- |")
            for task in self.first_open_tasks:
                lines.append(
                    "| `{priority}` | `{task_type}` | `{item}` | `{status}` | `{target}` | "
                    "`{next_command}` | {action} |".format(
                        priority=task.get("priority", ""),
                        task_type=task.get("task_type", ""),
                        item=task.get("item", ""),
                        status=task.get("status", ""),
                        target=task.get("target", ""),
                        next_command=task.get("next_command", ""),
                        action=task.get("action", ""),
                    )
                )
        else:
            lines.append("- None.")
        batch = self.next_batch
        lines.extend(
            [
                "",
                "## Next Batch",
                "",
                f"- Status: `{batch.get('status', 'UNKNOWN')}`",
                f"- Priority: `{batch.get('priority', '')}`",
                f"- Task type: `{batch.get('task_type', '')}`",
                f"- Task count: {batch.get('task_count', 0)}",
                f"- Source artifacts: `{', '.join(batch.get('source_artifacts', []))}`",
                f"- Acceptance: {batch.get('acceptance_criteria', '')}",
            ]
        )
        if batch.get("next_command"):
            lines.extend(["", "Next command after completing this batch:", "", "```powershell"])
            lines.append(str(batch["next_command"]))
            lines.append("```")
        sample_tasks = batch.get("sample_tasks", [])
        if sample_tasks:
            lines.extend(["", "Batch tasks:", ""])
            lines.append("| item | target | action |")
            lines.append("| --- | --- | --- |")
            for task in sample_tasks:
                lines.append(
                    f"| `{task.get('item', '')}` | `{task.get('target', '')}` | {task.get('action', '')} |"
                )
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_data_evidence_action_packet(
    *,
    data_dir: str | Path = "data_exports",
    config_path: str | Path = "config/research_recent.yaml",
    source_qa_answers: str | Path | None = None,
    min_symbols: int = 300,
    as_of: str | None = None,
    encoding: str = "utf-8-sig",
    data_gap_plan: DataGapActionPlan | None = None,
    export_request: DataExportRequest | None = None,
) -> DataEvidenceActionPacket:
    root = Path(data_dir)
    plan = data_gap_plan or build_data_gap_action_plan(
        data_dir=root,
        config_path=config_path,
        source_qa_answers=source_qa_answers,
        min_symbols=min_symbols,
        as_of=as_of,
        encoding=encoding,
    )
    request = export_request or build_data_export_request(
        config_path=config_path,
        output_dir=root,
        min_symbols=min_symbols,
    )
    checklist = build_data_source_qa(
        config_path=config_path,
        output_dir=root,
        min_symbols=min_symbols,
        as_of=as_of,
    )
    blockers = [_item_dict(item) for item in plan.items if item.status == "BLOCK"]
    watch_items = [_item_dict(item) for item in plan.items if item.status == "WATCH"]
    metadata_fields = list(plan.required_source_metadata)
    source_evidence_to_fill = _source_qa_evidence_to_fill(checklist.to_dict())
    checklist_path = root / "data_source_qa.json"
    worksheet_status = _source_qa_worksheet_status(
        data_dir=root,
        checklist_path=checklist_path,
        source_qa_answers_path=Path(plan.source_qa_answers_path),
        encoding=encoding,
    )
    manifest_status = _source_qa_evidence_manifest_status(
        data_dir=root,
        checklist_path=checklist_path,
        source_qa_evidence=source_evidence_to_fill,
    )
    blockers.extend(_source_evidence_status_items(worksheet_status, manifest_status, status="BLOCK"))
    watch_items.extend(_source_evidence_status_items(worksheet_status, manifest_status, status="WATCH"))
    return DataEvidenceActionPacket(
        decision=_packet_decision(plan.decision, blockers, watch_items),
        as_of=as_of or plan.as_of,
        data_dir=plan.data_dir,
        config_path=plan.config_path,
        source_qa_answers_path=plan.source_qa_answers_path,
        current_blockers=blockers,
        watch_items=watch_items,
        required_exports=_required_exports(request),
        source_qa_fields_to_fill=metadata_fields,
        source_metadata_fields_to_fill=metadata_fields,
        source_qa_evidence_to_fill=source_evidence_to_fill,
        source_qa_worksheet_status=worksheet_status,
        source_qa_evidence_manifest_status=manifest_status,
        operator_checklist=_operator_checklist(request, plan),
        immediate_commands=_immediate_commands(plan),
        completion_criteria=_completion_criteria(request, min_symbols),
        prohibited_actions=[
            "Do not treat this packet as a trading signal, strategy approval, or profitability evidence.",
            "Do not fabricate source QA answers or evidence to make data gates pass.",
            "Do not run candidate experiments while this packet is BLOCK.",
            "Do not connect data exports, packet commands, or downstream outputs to real broker order submission.",
            "Do not let LLM text override deterministic source QA, import, audit, or readiness gates.",
        ],
    )


def write_data_evidence_action_packet(
    packet: DataEvidenceActionPacket,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "data_evidence_action_packet.json").write_text(
        json.dumps(packet.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "data_evidence_action_packet.md").write_text(packet.to_markdown(), encoding="utf-8")
    _write_source_qa_worksheet_todo(packet, root)
    _write_source_qa_attachment_todo(packet, root)
    _write_data_export_todo(packet, root)
    _write_operator_handoff(packet, root)
    status = build_operator_handoff_status(
        packet=packet,
        operator_handoff_path=root / "operator_handoff.csv",
    )
    write_operator_handoff_status(status, root)
    return root


def build_operator_handoff_status(
    *,
    packet: DataEvidenceActionPacket,
    operator_handoff_path: str | Path,
    rows: list[dict[str, str]] | None = None,
) -> OperatorHandoffStatus:
    path = Path(operator_handoff_path)
    handoff_rows = rows if rows is not None else _read_handoff_rows(path)
    open_rows = [row for row in handoff_rows if _handoff_row_open(row)]
    p0_rows = [row for row in open_rows if str(row.get("priority", "")).upper() == "P0"]
    p1_rows = [row for row in open_rows if str(row.get("priority", "")).upper() != "P0"]
    source_rows = [
        row for row in open_rows if str(row.get("task_type", "")).startswith("source_qa_")
    ]
    source_attachment_rows = [
        row for row in open_rows if row.get("task_type") == "source_qa_attachment"
    ]
    export_rows = [row for row in open_rows if row.get("task_type") == "data_export"]
    status = _operator_status(packet.decision, p0_open=len(p0_rows), p1_open=len(p1_rows))
    return OperatorHandoffStatus(
        status=status,
        packet_decision=packet.decision,
        as_of=packet.as_of,
        operator_handoff_path=str(path),
        total_task_count=len(handoff_rows),
        open_task_count=len(open_rows),
        p0_open_task_count=len(p0_rows),
        p1_open_task_count=len(p1_rows),
        source_qa_open_task_count=len(source_rows),
        source_qa_attachment_open_task_count=len(source_attachment_rows),
        data_export_open_task_count=len(export_rows),
        completed_task_count=max(len(handoff_rows) - len(open_rows), 0),
        first_open_tasks=_first_open_tasks(open_rows),
        next_batch=_next_operator_batch(open_rows),
        next_actions=_operator_status_next_actions(packet, source_rows, export_rows, open_rows),
        prohibited_actions=_operator_status_prohibited_actions(),
    )


def write_operator_handoff_status(
    status: OperatorHandoffStatus,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "operator_handoff_status.json").write_text(
        json.dumps(status.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "operator_handoff_status.md").write_text(status.to_markdown(), encoding="utf-8")
    return root


def _item_dict(item: Any) -> dict[str, str]:
    return {
        "name": str(item.name),
        "status": str(item.status),
        "artifact": str(item.artifact),
        "message": str(item.message),
        "next_action": str(item.next_action),
    }


def _source_evidence_status_items(
    worksheet_status: dict[str, Any],
    manifest_status: dict[str, Any],
    *,
    status: str,
) -> list[dict[str, str]]:
    rows = []
    if str(worksheet_status.get("status", "")).upper() == status:
        rows.append(
            {
                "name": "source_qa_worksheet",
                "status": status,
                "artifact": str(worksheet_status.get("path", "")),
                "message": str(worksheet_status.get("message", ""))
                or "Source QA worksheet requires operator action.",
                "next_action": str(worksheet_status.get("next_command", "")),
            }
        )
    if str(manifest_status.get("status", "")).upper() == status:
        rows.append(
            {
                "name": "source_qa_evidence_manifest",
                "status": status,
                "artifact": str(manifest_status.get("path", "")),
                "message": _manifest_status_message(manifest_status),
                "next_action": str(manifest_status.get("next_command", "")),
            }
        )
    return rows


def _manifest_status_message(status: dict[str, Any]) -> str:
    return (
        "Source QA evidence manifest requires operator action: "
        f"missing={status.get('missing_attachment_count', 0)}, "
        f"invalid={status.get('invalid_attachment_count', 0)}, "
        f"errors={status.get('manifest_error_count', 0)}."
    )


def _packet_decision(
    plan_decision: str,
    blockers: list[dict[str, str]],
    watch_items: list[dict[str, str]],
) -> PacketDecision:
    if blockers or str(plan_decision).upper() == "BLOCK":
        return "BLOCK"
    if watch_items or str(plan_decision).upper() == "WATCH":
        return "WATCH"
    return "PASS"


def _required_exports(request: DataExportRequest) -> list[dict[str, Any]]:
    return [
        {
            "role": item["role"],
            "file_name": item["file_name"],
            "required": item["required"],
            "columns": item["columns"],
            "description": item["description"],
        }
        for item in request.files
    ]


def _source_qa_evidence_to_fill(checklist: dict[str, Any]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for item in checklist.get("checklist", []) or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("review_stage", "")) != "source":
            continue
        items.append(
            {
                "id": str(item.get("id", "")),
                "severity": str(item.get("severity", "")),
                "question": str(item.get("question", "")),
                "required_evidence": str(item.get("required_evidence", "")),
                "why_it_matters": str(item.get("why_it_matters", "")),
            }
        )
    return items


def _source_qa_evidence_manifest_status(
    *,
    data_dir: Path,
    checklist_path: Path,
    source_qa_evidence: list[dict[str, str]],
) -> dict[str, Any]:
    manifest_path = data_dir / "source_qa_evidence_manifest.json"
    evidence_dir = data_dir / "source_qa_evidence"
    required = [
        item
        for item in source_qa_evidence
        if str(item.get("severity", "")).upper() == "BLOCK_IF_NO"
    ]
    required_by_id = {str(item.get("id", "")).strip(): item for item in required}
    next_command = _source_qa_evidence_manifest_command(
        checklist_path=checklist_path,
        evidence_dir=evidence_dir,
        data_dir=data_dir,
    )
    manifest_errors: list[dict[str, str]] = []
    invalid_attachments: list[dict[str, str]] = []
    valid_required_ids: set[str] = set()
    valid_item_count = 0
    items: list[Any] = []

    if manifest_path.exists():
        manifest = _read_json(manifest_path)
        if not isinstance(manifest, dict):
            manifest_errors.append(
                {
                    "code": "manifest_invalid",
                    "message": "source_qa_evidence_manifest.json must be a JSON object.",
                }
            )
        else:
            raw_items = manifest.get("items", [])
            if isinstance(raw_items, list):
                items = raw_items
            else:
                manifest_errors.append(
                    {
                        "code": "manifest_items_invalid",
                        "message": "source_qa_evidence_manifest.json items must be a list.",
                    }
                )

    for index, raw_item in enumerate(items, start=1):
        if not isinstance(raw_item, dict):
            invalid_attachments.append(
                _invalid_attachment(
                    item_id="",
                    path="",
                    code="manifest_item_invalid",
                    message=f"Manifest item {index} must be an object.",
                )
            )
            continue
        item_id = str(raw_item.get("id", "")).strip()
        path_text = str(raw_item.get("path", "")).strip()
        sha256 = str(raw_item.get("sha256", "")).strip().lower()
        invalid = _attachment_validation_error(
            item_id=item_id,
            path_text=path_text,
            sha256=sha256,
        )
        if invalid:
            invalid_attachments.append(invalid)
            continue
        valid_item_count += 1
        if item_id in required_by_id:
            valid_required_ids.add(item_id)

    invalid_by_id = {
        str(item.get("id", "")): item
        for item in invalid_attachments
        if str(item.get("id", ""))
    }
    missing_attachments = [
        _missing_attachment_row(
            item,
            manifest_path=manifest_path,
            evidence_dir=evidence_dir,
            manifest_exists=manifest_path.exists(),
            manifest_item_count=len(items),
            next_command=next_command,
            invalid_attachment=invalid_by_id.get(item_id),
        )
        for item_id, item in required_by_id.items()
        if item_id not in valid_required_ids
    ]
    missing_ids = {str(item.get("id", "")) for item in missing_attachments}
    invalid_attachment_ids = [
        str(item.get("id", ""))
        for item in invalid_attachments
        if str(item.get("id", "")).strip()
    ]
    status = (
        "BLOCK"
        if missing_attachments or invalid_attachments or manifest_errors
        else "PASS"
    )
    return {
        "status": status,
        "path": str(manifest_path),
        "evidence_dir": str(evidence_dir),
        "checklist_path": str(checklist_path),
        "exists": manifest_path.exists(),
        "item_count": len(items),
        "valid_item_count": valid_item_count,
        "required_attachment_count": len(required),
        "valid_required_id_count": len(valid_required_ids),
        "missing_attachment_count": len(missing_attachments),
        "invalid_attachment_count": len(invalid_attachments),
        "manifest_error_count": len(manifest_errors),
        "required_attachment_ids": list(required_by_id),
        "valid_required_ids": sorted(valid_required_ids),
        "missing_attachment_ids": [str(item.get("id", "")) for item in missing_attachments],
        "invalid_attachment_ids": list(dict.fromkeys(invalid_attachment_ids)),
        "missing_attachments": missing_attachments,
        "invalid_attachments": [
            item for item in invalid_attachments if str(item.get("id", "")) not in missing_ids
        ],
        "all_invalid_attachments": invalid_attachments,
        "invalid_attachment_targets": [
            {
                "id": str(item.get("id", "")),
                "path": str(item.get("path", "")),
                "current_state": str(item.get("current_state", "")),
                "message": str(item.get("message", "")),
            }
            for item in invalid_attachments
        ],
        "manifest_errors": manifest_errors,
        "next_command": next_command,
    }


def _source_qa_evidence_manifest_command(
    *,
    checklist_path: Path,
    evidence_dir: Path,
    data_dir: Path,
) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\write_source_qa_evidence_manifest.py "
        f"--checklist {checklist_path} --evidence-dir {evidence_dir} --output-dir {data_dir} "
        "--strict"
    )


def _attachment_validation_error(
    *,
    item_id: str,
    path_text: str,
    sha256: str,
) -> dict[str, str] | None:
    error = validate_source_qa_attachment(item_id=item_id, path_text=path_text, sha256=sha256)
    if error is None:
        return None
    return _invalid_attachment(
        item_id=item_id,
        path=path_text,
        code=str(error.get("code", "attachment_invalid")),
        message=str(error.get("message", "Manifest attachment is invalid.")),
    )


def _invalid_attachment(
    *,
    item_id: str,
    path: str,
    code: str,
    message: str,
) -> dict[str, str]:
    return {
        "id": item_id,
        "path": path,
        "current_state": code,
        "message": message,
    }


def _missing_attachment_row(
    item: dict[str, str],
    *,
    manifest_path: Path,
    evidence_dir: Path,
    manifest_exists: bool,
    manifest_item_count: int,
    next_command: str,
    invalid_attachment: dict[str, str] | None = None,
) -> dict[str, str]:
    item_id = str(item.get("id", "")).strip()
    current_state = str(invalid_attachment.get("current_state", "")) if invalid_attachment else ""
    if not current_state:
        current_state = (
            "manifest_missing"
            if not manifest_exists
            else ("manifest_empty" if manifest_item_count == 0 else "attachment_missing_or_invalid")
        )
    suggested_file = evidence_dir / _source_qa_attachment_file_name(item_id)
    action = (
        str(invalid_attachment.get("message", ""))
        if invalid_attachment
        else (
            "Attach a real local evidence file for this source QA item, then regenerate "
            "source_qa_evidence_manifest.json."
        )
    )
    return {
        "id": item_id,
        "severity": str(item.get("severity", "")),
        "question": str(item.get("question", "")),
        "required_evidence": str(item.get("required_evidence", "")),
        "manifest_path": str(manifest_path),
        "evidence_dir": str(evidence_dir),
        "target": str(suggested_file),
        "current_state": current_state,
        "action": action,
        "acceptance_criteria": (
            "A local retained evidence file exists, the manifest records its id/path/sha256, "
            "and strict source QA review accepts the attachment."
        ),
        "next_command": next_command,
    }


def _source_qa_attachment_file_name(item_id: str) -> str:
    names = {
        "source_identity": "source_identity_receipt.png",
        "license_scope": "license_scope_note.pdf",
        "price_adjustment": "price_adjustment_qfq.png",
        "point_in_time": "point_in_time_note.md",
        "manual_signoff": "manual_signoff.md",
    }
    return names.get(item_id, f"{_safe_file_stem(item_id)}_evidence.txt")


def _safe_file_stem(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"_", "-"} else "_" for char in value) or "evidence"


def _source_qa_worksheet_status(
    *,
    data_dir: Path,
    checklist_path: Path,
    source_qa_answers_path: Path,
    encoding: str,
) -> dict[str, Any]:
    answers_present = bool(_read_json(source_qa_answers_path))
    manifest_path = data_dir / "source_qa_evidence_manifest.json"
    answer_gaps = (
        _source_qa_answer_gaps(
            checklist_path=checklist_path,
            answers_path=source_qa_answers_path,
        )
        if answers_present
        else []
    )
    csv_path = data_dir / "data_source_qa_evidence_worksheet.csv"
    json_path = data_dir / "data_source_qa_evidence_worksheet.json"
    worksheet_path = csv_path if csv_path.exists() else json_path
    if not worksheet_path.exists():
        return {
            "status": _source_qa_status_from_gaps(answer_gaps) if answers_present else "MISSING",
            "path": str(csv_path),
            "row_count": 0,
            "complete_row_count": 0,
            "missing_row_count": len(answer_gaps),
            "missing_rows": answer_gaps,
            "next_command": (
                ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa_evidence_worksheet.py "
                f"--checklist {checklist_path} --output-dir {data_dir}"
            ),
        }
    rows = _read_worksheet_rows(worksheet_path, encoding=encoding)
    if answers_present:
        missing_rows = _annotate_answer_gaps(answer_gaps, rows)
    else:
        missing_rows = _worksheet_preflight_missing_rows(
            checklist_path=checklist_path,
            worksheet_path=worksheet_path,
            encoding=encoding,
        )
    complete_count = len(rows) - len(missing_rows)
    return {
        "status": (
            "ANSWERS_PRESENT"
            if answers_present and not missing_rows
            else ("PASS" if not missing_rows else _source_qa_status_from_gaps(missing_rows))
        ),
        "path": str(worksheet_path),
        "row_count": len(rows),
        "complete_row_count": complete_count,
        "missing_row_count": len(missing_rows),
        "missing_rows": missing_rows,
        "next_command": (
            ".\\.venv\\Scripts\\python.exe examples\\run_data_source_qa_worksheet_preflight.py "
            f"--checklist {checklist_path} --worksheet {worksheet_path} --output-dir {data_dir}"
        ),
        "answers_command": (
            ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa_answers.py "
            f"--checklist {checklist_path} --worksheet {worksheet_path} "
            f"--output {source_qa_answers_path} "
            f"--evidence-manifest {manifest_path} --require-evidence-manifest"
        ),
    }


def _source_qa_answer_gaps(
    *,
    checklist_path: Path,
    answers_path: Path,
) -> list[dict[str, str]]:
    review = build_data_source_qa_review(
        checklist_path=checklist_path,
        answers_path=answers_path,
        review_stage="source",
    )
    gaps: list[dict[str, str]] = []
    for finding in review.findings:
        if finding.code == "SOURCE_METADATA_MISSING":
            for field in finding.evidence.get("missing_metadata", []) or []:
                gaps.append(_answer_gap_row("metadata", str(field), "REQUIRED", "missing"))
        elif finding.code == "SOURCE_METADATA_PLACEHOLDER":
            for field in finding.evidence.get("placeholder_metadata", []) or []:
                gaps.append(_answer_gap_row("metadata", str(field), "REQUIRED", "placeholder"))
        elif finding.code in {
            "SOURCE_QA_BLOCK_ANSWER",
            "SOURCE_QA_EVIDENCE_MISSING",
            "SOURCE_QA_EVIDENCE_PLACEHOLDER",
            "SOURCE_QA_WATCH_ANSWER",
            "SOURCE_QA_WATCH_EVIDENCE_MISSING",
            "SOURCE_QA_WATCH_EVIDENCE_PLACEHOLDER",
        }:
            item_id = str(finding.evidence.get("id", "")).strip()
            if item_id:
                gaps.append(
                    _answer_gap_row(
                        "source_question",
                        item_id,
                        "WATCH_IF_NO" if finding.severity == "WATCH" else "BLOCK_IF_NO",
                        finding.code.lower(),
                    )
                )
    return _dedupe_missing_rows(gaps)


def _answer_gap_row(row_type: str, item_id: str, severity: str, reason: str) -> dict[str, str]:
    if row_type == "metadata":
        return {
            "row_number": "",
            "row_type": row_type,
            "id": item_id,
            "severity": severity,
            "cli_argument": "",
            "question_or_field": item_id,
            "required_evidence": "Real source metadata from the export batch.",
            "message": f"Update data_source_qa_answers.json: metadata is {reason}.",
        }
    return {
        "row_number": "",
        "row_type": row_type,
        "id": item_id,
        "severity": severity,
        "cli_argument": "",
        "question_or_field": item_id,
        "required_evidence": "Concrete evidence tied to vendor/export/license/adjustment/signoff.",
        "message": f"Update data_source_qa_answers.json: source QA evidence is {reason}.",
    }


def _annotate_answer_gaps(
    answer_gaps: list[dict[str, str]],
    worksheet_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    worksheet_by_key = {
        (str(row.get("row_type", "")), str(row.get("id", ""))): row
        for row in _worksheet_rows_with_numbers(worksheet_rows)
    }
    annotated: list[dict[str, str]] = []
    for gap in answer_gaps:
        key = (str(gap.get("row_type", "")), str(gap.get("id", "")))
        row = dict(gap)
        worksheet_row = worksheet_by_key.get(key)
        if worksheet_row:
            for field in (
                "row_number",
                "cli_argument",
                "question_or_field",
                "required_evidence",
            ):
                if not row.get(field) and worksheet_row.get(field):
                    row[field] = str(worksheet_row[field])
        annotated.append(row)
    return _dedupe_missing_rows(annotated)


def _worksheet_rows_with_numbers(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    numbered = []
    for index, row in enumerate(rows, start=2):
        item = {str(key): str(value or "") for key, value in row.items()}
        item["id"] = item.get("field_or_question_id", "")
        item["row_number"] = str(index)
        numbered.append(item)
    return numbered


def _dedupe_missing_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (str(row.get("row_type", "")), str(row.get("id", "")))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _source_qa_status_from_gaps(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "ANSWERS_PRESENT"
    if any(str(row.get("severity", "")).upper() in {"REQUIRED", "BLOCK_IF_NO"} for row in rows):
        return "BLOCK"
    return "WATCH"


def _read_worksheet_rows(path: Path, *, encoding: str) -> list[dict[str, str]]:
    if path.suffix.lower() == ".json":
        payload = _read_json(path)
        rows = payload.get("rows", []) if isinstance(payload, dict) else []
        return [
            {str(key): str(value or "") for key, value in row.items()}
            for row in rows
            if isinstance(row, dict)
        ]
    try:
        with path.open("r", newline="", encoding=encoding) as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except UnicodeDecodeError:
        with path.open("r", newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]


def _worksheet_missing_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    for index, row in enumerate(rows, start=2):
        row_type = str(row.get("row_type", "")).strip()
        item_id = str(row.get("field_or_question_id", "")).strip()
        answer = str(row.get("answer", "")).strip()
        evidence = str(row.get("evidence", "")).strip()
        severity = str(row.get("severity", "")).strip()
        if row_type == "metadata" and item_id in REQUIRED_SOURCE_METADATA:
            if not answer or weak_source_evidence(answer):
                missing.append(
                    {
                        "row_number": str(index),
                        "row_type": row_type,
                        "id": item_id,
                        "severity": severity,
                        "cli_argument": str(row.get("cli_argument", "")).strip(),
                        "question_or_field": str(row.get("question_or_field", "")).strip(),
                        "required_evidence": str(row.get("required_evidence", "")).strip(),
                        "message": "Fill the metadata answer from real export evidence.",
                    }
                )
            continue
        if row_type != "source_question":
            continue
        if severity not in {"BLOCK_IF_NO", "WATCH_IF_NO"}:
            continue
        if not evidence or weak_source_evidence(evidence):
            missing.append(
                {
                    "row_number": str(index),
                    "row_type": row_type,
                    "id": item_id,
                    "severity": severity,
                    "cli_argument": str(row.get("cli_argument", "")).strip(),
                    "question_or_field": str(row.get("question_or_field", "")).strip(),
                    "required_evidence": str(row.get("required_evidence", "")).strip(),
                    "message": "Add concrete evidence for this source QA question.",
                }
            )
    return missing


def _worksheet_preflight_missing_rows(
    *,
    checklist_path: Path,
    worksheet_path: Path,
    encoding: str,
) -> list[dict[str, str]]:
    report = build_data_source_qa_evidence_worksheet_preflight(
        checklist_path=checklist_path,
        worksheet_path=worksheet_path,
        encoding=encoding,
    )
    rows: list[dict[str, str]] = []
    for finding in report.findings:
        rows.append(
            {
                "row_number": str(finding.row_number or ""),
                "row_type": finding.row_type,
                "id": finding.field_or_question_id,
                "severity": finding.severity,
                "cli_argument": "",
                "question_or_field": str(
                    finding.evidence.get("row", {}).get("question_or_field", "")
                    if isinstance(finding.evidence.get("row"), dict)
                    else ""
                ),
                "required_evidence": str(
                    finding.evidence.get("row", {}).get("required_evidence", "")
                    if isinstance(finding.evidence.get("row"), dict)
                    else ""
                )
                or "Real source QA evidence from the export batch.",
                "message": finding.message,
                "current_state": finding.code.lower(),
                "preflight_status": finding.status,
            }
        )
    return _dedupe_missing_rows(rows)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_source_qa_worksheet_todo(
    packet: DataEvidenceActionPacket,
    output_dir: Path,
) -> None:
    worksheet = packet.source_qa_worksheet_status
    rows = _source_qa_worksheet_todo_rows(packet)
    csv_path = output_dir / "source_qa_worksheet_todo.csv"
    fieldnames = [
        "row_number",
        "row_type",
        "id",
        "severity",
        "cli_argument",
        "question_or_field",
        "required_evidence",
        "message",
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: str(row.get(key, "")) for key in fieldnames})

    md_lines = [
        f"# Source QA Worksheet Todo: {worksheet.get('status', 'UNKNOWN')}",
        "",
        f"- Worksheet: `{worksheet.get('path', '')}`",
        f"- Missing rows: {worksheet.get('missing_row_count', 0)}",
        "",
        "This todo file is an operator aid. It does not approve data, strategy research, paper trading, or live trading.",
        "",
        "## Missing Rows",
        "",
    ]
    if rows:
        md_lines.append("| row | type | id | severity | CLI argument | required evidence |")
        md_lines.append("| ---: | --- | --- | --- | --- | --- |")
        for row in rows:
            md_lines.append(
                "| {row_number} | {row_type} | `{id}` | `{severity}` | `{cli}` | {evidence} |".format(
                    row_number=str(row.get("row_number", "")),
                    row_type=str(row.get("row_type", "")),
                    id=str(row.get("id", "")),
                    severity=str(row.get("severity", "")),
                    cli=str(row.get("cli_argument", "")),
                    evidence=str(row.get("required_evidence", "")),
                )
            )
    else:
        md_lines.append("- None.")
    next_command = str(worksheet.get("next_command") or "").strip()
    if next_command:
        md_lines.extend(["", "## Next Command", "", "```powershell", next_command, "```"])
    md_lines.extend(
        [
            "",
            "## Safety",
            "- Fill these rows only from real vendor, terminal, export, license, and review evidence.",
            "- Do not invent evidence to make source QA pass.",
            "- Source QA answers must still pass deterministic preflight and review.",
        ]
    )
    (output_dir / "source_qa_worksheet_todo.md").write_text(
        "\n".join(md_lines) + "\n",
        encoding="utf-8",
    )


def _write_source_qa_attachment_todo(
    packet: DataEvidenceActionPacket,
    output_dir: Path,
) -> None:
    status = packet.source_qa_evidence_manifest_status
    rows = _source_qa_attachment_todo_rows(packet)
    csv_path = output_dir / "source_qa_attachment_todo.csv"
    fieldnames = [
        "id",
        "severity",
        "target",
        "manifest_path",
        "evidence_dir",
        "current_state",
        "action",
        "required_evidence",
        "acceptance_criteria",
        "next_command",
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: str(row.get(key, "")) for key in fieldnames})

    md_lines = [
        f"# Source QA Attachment Todo: {status.get('status', 'UNKNOWN')}",
        "",
        f"- Manifest: `{status.get('path', '')}`",
        f"- Evidence directory: `{status.get('evidence_dir', '')}`",
        f"- Missing attachments: {status.get('missing_attachment_count', 0)}",
        f"- Invalid attachments: {status.get('invalid_attachment_count', 0)}",
        "",
        (
            "This todo file is an operator aid for local evidence attachments. "
            "It does not approve data, strategy research, paper trading, or live trading."
        ),
        "",
        "## Missing Required Attachments",
        "",
    ]
    if rows:
        md_lines.append("| id | severity | suggested file | current state | required evidence |")
        md_lines.append("| --- | --- | --- | --- | --- |")
        for row in rows:
            md_lines.append(
                "| `{id}` | `{severity}` | `{target}` | `{current_state}` | {evidence} |".format(
                    id=row["id"],
                    severity=row["severity"],
                    target=row["target"],
                    current_state=row["current_state"],
                    evidence=row["required_evidence"],
                )
            )
    else:
        md_lines.append("- None.")
    invalid_rows = status.get("invalid_attachments", []) or []
    if invalid_rows:
        md_lines.extend(["", "## Invalid Manifest Attachments", ""])
        md_lines.append("| id | path | state | message |")
        md_lines.append("| --- | --- | --- | --- |")
        for row in invalid_rows:
            md_lines.append(
                "| `{id}` | `{path}` | `{state}` | {message} |".format(
                    id=str(row.get("id", "")),
                    path=str(row.get("path", "")),
                    state=str(row.get("current_state", "")),
                    message=str(row.get("message", "")),
                )
            )
    errors = status.get("manifest_errors", []) or []
    if errors:
        md_lines.extend(["", "## Manifest Errors", ""])
        for error in errors:
            md_lines.append(f"- `{error.get('code', '')}`: {error.get('message', '')}")
    next_command = str(status.get("next_command") or "").strip()
    if next_command:
        md_lines.extend(["", "## Next Command", "", "```powershell", next_command, "```"])
    md_lines.extend(
        [
            "",
            "## Safety",
            "- Attach only real local files that can be retained for research audit.",
            "- Do not fabricate screenshots, PDFs, or notes to make source QA pass.",
            "- Strict source QA review must still verify the manifest before intake or research use.",
        ]
    )
    (output_dir / "source_qa_attachment_todo.md").write_text(
        "\n".join(md_lines) + "\n",
        encoding="utf-8",
    )
    _write_source_qa_evidence_folder_plan(packet, output_dir, rows)


def _write_source_qa_evidence_folder_plan(
    packet: DataEvidenceActionPacket,
    output_dir: Path,
    rows: list[dict[str, str]],
) -> None:
    status = packet.source_qa_evidence_manifest_status
    evidence_dir = Path(str(status.get("evidence_dir") or Path(packet.data_dir) / "source_qa_evidence"))
    evidence_dir.mkdir(parents=True, exist_ok=True)
    plan_path = output_dir / "source_qa_evidence_attachment_plan.csv"
    fieldnames = [
        "id",
        "suggested_file",
        "current_state",
        "required_evidence",
        "acceptance_criteria",
        "do_not_use",
        "next_command",
    ]
    with plan_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "id": str(row.get("id", "")),
                    "suggested_file": str(row.get("target", "")),
                    "current_state": str(row.get("current_state", "")),
                    "required_evidence": str(row.get("required_evidence", "")),
                    "acceptance_criteria": str(row.get("acceptance_criteria", "")),
                    "do_not_use": _source_qa_attachment_do_not_use(str(row.get("id", ""))),
                    "next_command": str(row.get("next_command", "")),
                }
            )

    plan_lines = [
        f"# Source QA Evidence Attachment Plan: {status.get('status', 'UNKNOWN')}",
        "",
        f"- Evidence directory: `{evidence_dir}`",
        f"- Manifest: `{status.get('path', '')}`",
        f"- Required missing/invalid attachments: {len(rows)}",
        "",
        "This plan tells the operator where to place real retained evidence files. It does not create evidence, approve source QA, or permit research/paper/live trading.",
        "",
        "## Attachments",
        "",
    ]
    if rows:
        plan_lines.append("| id | suggested file | state | required evidence | do not use |")
        plan_lines.append("| --- | --- | --- | --- | --- |")
        for row in rows:
            item_id = str(row.get("id", ""))
            plan_lines.append(
                "| `{id}` | `{target}` | `{state}` | {required} | {forbidden} |".format(
                    id=item_id,
                    target=str(row.get("target", "")),
                    state=str(row.get("current_state", "")),
                    required=str(row.get("required_evidence", "")),
                    forbidden=_source_qa_attachment_do_not_use(item_id),
                )
            )
    else:
        plan_lines.append("- None.")
    next_command = str(status.get("next_command") or "").strip()
    if next_command:
        plan_lines.extend(
            [
                "",
                "## After Adding Files",
                "",
                "```powershell",
                next_command,
                "```",
            ]
        )
    plan_lines.extend(
        [
            "",
            "## Safety",
            "- Keep the original evidence files or screenshots with enough context to reproduce the export.",
            "- Do not use generated placeholder files, edited screenshots, or unverifiable notes.",
            "- Regenerate the manifest after every file change so sha256 hashes match the retained files.",
            "- Deterministic source QA review must still pass before guarded intake can proceed.",
        ]
    )
    (output_dir / "source_qa_evidence_attachment_plan.md").write_text(
        "\n".join(plan_lines) + "\n",
        encoding="utf-8",
    )
    readme_lines = [
        "# Source QA Evidence Folder",
        "",
        "Place only real local evidence files in this directory. The manifest command hashes these files; it does not verify that their content is truthful.",
        "",
        "Suggested current attachments are listed in:",
        "",
        f"- `{plan_path}`",
        f"- `{output_dir / 'source_qa_evidence_attachment_plan.md'}`",
        "",
        "After adding or replacing files, run:",
        "",
        "```powershell",
        str(status.get("next_command") or ""),
        "```",
        "",
        "Do not put fabricated screenshots, blank PDFs, generated placeholders, or files you are not allowed to retain here.",
        "Passing this folder check is not a strategy approval and never permits real broker order submission.",
    ]
    (evidence_dir / "README.md").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")


def _source_qa_attachment_do_not_use(item_id: str) -> str:
    values = {
        "source_identity": "unlabeled screenshots, copied vendor names without terminal/export timestamp, or generated receipts",
        "license_scope": "assumed license text, copied public marketing pages, or notes without account/vendor context",
        "price_adjustment": "unverified adjustment labels, mixed raw/qfq/hfq exports, or screenshots without the setting visible",
        "point_in_time": "after-the-fact fundamentals claims, survivorship-only notes, or vague PIT assertions",
        "manual_signoff": "unsigned notes, LLM-generated approvals, or signoff without reviewer/date",
    }
    return values.get(item_id, "generated placeholders, weak notes, or unverifiable files")


def _write_data_export_todo(
    packet: DataEvidenceActionPacket,
    output_dir: Path,
) -> None:
    rows = _data_export_todo_rows(packet)
    fieldnames = [
        "file_name",
        "required",
        "status",
        "action",
        "columns",
        "acceptance_criteria",
        "exists",
        "row_count",
        "symbol_count",
        "start",
        "end",
        "template_rows_detected",
        "current_state",
        "preview_status",
        "raw_columns",
        "mapped_columns",
        "missing_columns",
        "preview_message",
    ]
    csv_path = output_dir / "data_export_todo.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    md_lines = [
        "# Data Export Todo",
        "",
        f"- Data directory: `{packet.data_dir}`",
        f"- As of: `{packet.as_of or 'unspecified'}`",
        "",
        "This todo file is an operator aid. It does not approve data, strategy research, paper trading, or live trading.",
        "",
        "## Files",
        "",
        "| file | required | status | current state | preview | missing columns | rows | symbols | period | action |",
        "| --- | --- | --- | --- | --- | --- | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        period = _period_label(row.get("start", ""), row.get("end", ""))
        md_lines.append(
            "| `{file_name}` | `{required}` | `{status}` | `{current_state}` | `{preview_status}` | "
            "`{missing_columns}` | {row_count} | {symbol_count} | `{period}` | {action} |".format(
                period=period,
                **row,
            )
        )
    md_lines.extend(
        [
            "",
            "## Global Acceptance Criteria",
            "- `bars.csv` must cover the configured recent A-share research window.",
            "- `bars.csv` must include at least the configured minimum symbol count.",
            "- Generated template/sample rows must be fully replaced with real exports.",
            "- Source QA answers and preflight must pass before guarded offline intake.",
            "- This workflow must not connect to a real broker or place orders.",
        ]
    )
    (output_dir / "data_export_todo.md").write_text(
        "\n".join(md_lines) + "\n",
        encoding="utf-8",
    )


def _source_qa_worksheet_todo_rows(packet: DataEvidenceActionPacket) -> list[dict[str, str]]:
    worksheet = packet.source_qa_worksheet_status
    status = str(worksheet.get("status") or "")
    if status == "ANSWERS_PRESENT":
        return []
    if status == "MISSING":
        return [
            {
                "row_number": "",
                "row_type": "worksheet",
                "id": "data_source_qa_evidence_worksheet",
                "severity": "BLOCK_IF_NO",
                "cli_argument": "--output-dir",
                "question_or_field": "Create source QA evidence worksheet",
                "required_evidence": "Generated worksheet file before source QA evidence collection.",
                "message": "Create or refresh data_source_qa_evidence_worksheet.csv before filling source QA answers.",
            }
        ]
    return [
        {str(key): str(value) for key, value in item.items()}
        for item in worksheet.get("missing_rows", []) or []
        if isinstance(item, dict)
    ]


def _source_qa_attachment_todo_rows(packet: DataEvidenceActionPacket) -> list[dict[str, str]]:
    status = packet.source_qa_evidence_manifest_status
    if str(status.get("status", "")).upper() == "PASS":
        return []
    rows: list[dict[str, str]] = []
    for item in status.get("missing_attachments", []) or []:
        if not isinstance(item, dict):
            continue
        rows.append({str(key): str(value) for key, value in item.items()})
    next_command = str(status.get("next_command") or "")
    for item in status.get("invalid_attachments", []) or []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id", ""))
        rows.append(
            {
                "id": item_id,
                "severity": "BLOCK_IF_NO",
                "target": str(item.get("path", "")),
                "manifest_path": str(status.get("path", "")),
                "evidence_dir": str(status.get("evidence_dir", "")),
                "current_state": str(item.get("current_state", "invalid_attachment")),
                "action": str(item.get("message", "Fix invalid source QA evidence attachment.")),
                "required_evidence": "Valid local evidence attachment with matching manifest sha256.",
                "acceptance_criteria": (
                    "The manifest item has id/path/sha256, the local file exists, and sha256 "
                    "matches the current retained file."
                ),
                "next_command": next_command,
            }
        )
    return rows


def _data_export_todo_rows(packet: DataEvidenceActionPacket) -> list[dict[str, str]]:
    blocker_by_name = {
        str(item.get("name", "")): item
        for item in packet.current_blockers
        if isinstance(item, dict)
    }
    template_blocker = blocker_by_name.get("csv_template_rows")
    doctor_blocker = blocker_by_name.get("import_doctor")
    preview_by_file = _csv_preview_by_file(data_dir=Path(packet.data_dir))
    return [
        _data_export_todo_row(
            item,
            data_dir=Path(packet.data_dir),
            template_blocker=template_blocker,
            doctor_blocker=doctor_blocker,
            preview_by_file=preview_by_file,
        )
        for item in packet.required_exports
    ]


def _data_export_todo_row(
    item: dict[str, Any],
    *,
    data_dir: Path,
    template_blocker: dict[str, str] | None,
    doctor_blocker: dict[str, str] | None,
    preview_by_file: dict[str, dict[str, Any]],
) -> dict[str, str]:
    file_name = str(item.get("file_name", ""))
    required = "yes" if item.get("required") else "recommended"
    columns = ", ".join(str(column) for column in item.get("columns", []) or [])
    path = _export_path(item, data_dir=data_dir)
    observation = _csv_file_observation(path, columns=str(item.get("columns", []) or ""))
    preview = preview_by_file.get(file_name, {})
    missing_columns = ", ".join(str(column) for column in preview.get("missing_columns", []) or [])
    raw_columns = ", ".join(str(column) for column in preview.get("raw_columns", []) or [])
    mapped_columns = ", ".join(str(column) for column in preview.get("mapped_columns", []) or [])
    preview_status = str(preview.get("status") or ("MISSING" if not observation["exists"] else "UNKNOWN"))
    preview_message = str(preview.get("message") or "")
    template_detected = (
        template_blocker is not None
        and file_name in str(template_blocker.get("artifact", ""))
    )
    actions = []
    if template_detected:
        actions.append("Replace generated template rows with real recent A-share export rows.")
    if doctor_blocker and file_name == "bars.csv":
        actions.append(str(doctor_blocker.get("message", "")))
    if not actions:
        actions.append("Provide or verify this file from the same real export batch.")
    status = "BLOCK" if any("Replace generated template" in action for action in actions) else "WATCH"
    if doctor_blocker and file_name == "bars.csv":
        status = "BLOCK"
    return {
        "file_name": file_name,
        "required": required,
        "status": status,
        "action": " ".join(action for action in actions if action),
        "columns": columns,
        "acceptance_criteria": _file_acceptance_criteria(file_name, required),
        "exists": "yes" if observation["exists"] else "no",
        "row_count": str(observation["row_count"]),
        "symbol_count": str(observation["symbol_count"]),
        "start": observation["start"],
        "end": observation["end"],
        "template_rows_detected": "yes" if template_detected else "no",
        "current_state": _export_current_state(
            exists=observation["exists"],
            template_detected=template_detected,
            row_count=observation["row_count"],
        ),
        "preview_status": preview_status,
        "raw_columns": raw_columns,
        "mapped_columns": mapped_columns,
        "missing_columns": missing_columns,
        "preview_message": preview_message,
    }


def _write_operator_handoff(
    packet: DataEvidenceActionPacket,
    output_dir: Path,
) -> None:
    rows = _operator_handoff_rows(packet)
    fieldnames = [
        "task_type",
        "priority",
        "status",
        "target",
        "source_artifact",
        "row_number",
        "file_name",
        "id",
        "required",
        "severity",
        "cli_argument",
        "action",
        "required_evidence",
        "acceptance_criteria",
        "current_state",
        "row_count",
        "symbol_count",
        "start",
        "end",
        "template_rows_detected",
        "preview_status",
        "raw_columns",
        "mapped_columns",
        "missing_columns",
        "preview_message",
        "next_command",
        "gate_note",
    ]
    csv_path = output_dir / "operator_handoff.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: str(row.get(key, "")) for key in fieldnames})

    md_lines = [
        f"# Real Data Operator Handoff: {packet.decision}",
        "",
        f"- Data directory: `{packet.data_dir}`",
        f"- Config: `{packet.config_path}`",
        f"- As of: `{packet.as_of or 'unspecified'}`",
        f"- Source QA answers: `{packet.source_qa_answers_path}`",
        "",
        (
            "This handoff is an operator checklist. It does not approve data, "
            "strategy research, paper trading, live trading, or profitability claims."
        ),
        "",
        "## Linked Todo Files",
        "- `source_qa_worksheet_todo.csv`: row-level source QA evidence gaps.",
        "- `source_qa_attachment_todo.csv`: local source QA evidence attachment gaps.",
        "- `data_export_todo.csv`: file-level CSV export actions.",
        "",
        "## Blocking Summary",
        "",
    ]
    if packet.current_blockers:
        md_lines.extend(
            f"- `{item['name']}`: {item['message']} Next: {item['next_action']}"
            for item in packet.current_blockers
        )
    else:
        md_lines.append("- None.")
    md_lines.extend(["", "## Source QA Worksheet Tasks", ""])
    source_rows = [row for row in rows if row["task_type"] == "source_qa_worksheet"]
    if source_rows:
        md_lines.append("| row | id | severity | action | required evidence |")
        md_lines.append("| ---: | --- | --- | --- | --- |")
        for row in source_rows:
            md_lines.append(
                "| {row_number} | `{id}` | `{severity}` | {action} | {evidence} |".format(
                    row_number=row["row_number"],
                    id=row["id"],
                    severity=row["severity"],
                    action=row["action"],
                    evidence=row["required_evidence"],
                )
            )
    else:
        md_lines.append("- None.")

    md_lines.extend(["", "## Source QA Attachment Tasks", ""])
    attachment_rows = [row for row in rows if row["task_type"] == "source_qa_attachment"]
    if attachment_rows:
        md_lines.append("| id | severity | suggested file | current state | action |")
        md_lines.append("| --- | --- | --- | --- | --- |")
        for row in attachment_rows:
            md_lines.append(
                "| `{id}` | `{severity}` | `{target}` | `{current_state}` | {action} |".format(
                    id=row["id"],
                    severity=row["severity"],
                    target=row["target"],
                    current_state=row["current_state"],
                    action=row["action"],
                )
            )
    else:
        md_lines.append("- None.")

    md_lines.extend(["", "## Data Export Tasks", ""])
    export_rows = [row for row in rows if row["task_type"] == "data_export"]
    if export_rows:
        md_lines.append(
            "| file | required | status | current state | preview | missing columns | rows | symbols | period | action |"
        )
        md_lines.append("| --- | --- | --- | --- | --- | --- | ---: | ---: | --- | --- |")
        for row in export_rows:
            period = _period_label(row.get("start", ""), row.get("end", ""))
            md_lines.append(
                "| `{file_name}` | `{required}` | `{status}` | `{current_state}` | `{preview_status}` | "
                "`{missing_columns}` | {row_count} | {symbol_count} | `{period}` | {action} |".format(
                    file_name=row["file_name"],
                    required=row["required"],
                    status=row["status"],
                    current_state=row["current_state"],
                    preview_status=row.get("preview_status", ""),
                    missing_columns=row.get("missing_columns", ""),
                    row_count=row["row_count"],
                    symbol_count=row["symbol_count"],
                    period=period,
                    action=row["action"],
                )
            )
    else:
        md_lines.append("- None.")

    md_lines.extend(
        [
            "",
            "## Unified Queue",
            "",
        ]
    )
    if rows:
        md_lines.append("| task | priority | status | item | action |")
        md_lines.append("| --- | --- | --- | --- | --- |")
        for row in rows:
            item_label = _handoff_item_label(row)
            md_lines.append(
                "| `{task_type}` | `{priority}` | `{status}` | {item} | {action} |".format(
                    task_type=row["task_type"],
                    priority=row["priority"],
                    status=row["status"],
                    item=item_label,
                    action=row["action"],
                )
            )
    else:
        md_lines.append("- None.")

    md_lines.extend(
        [
            "",
            "## Commands After Evidence Is Ready",
        ]
    )
    if packet.immediate_commands:
        for command in packet.immediate_commands:
            md_lines.extend(["", "```powershell", command, "```"])
    else:
        md_lines.append("- None.")

    md_lines.extend(["", "## Completion Criteria"])
    md_lines.extend(f"- {item}" for item in packet.completion_criteria)
    md_lines.extend(["", "## Safety Boundary"])
    md_lines.extend(f"- {item}" for item in packet.prohibited_actions)
    (output_dir / "operator_handoff.md").write_text(
        "\n".join(md_lines) + "\n",
        encoding="utf-8",
    )


def _operator_handoff_rows(packet: DataEvidenceActionPacket) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    worksheet_next_command = str(packet.source_qa_worksheet_status.get("next_command") or "")
    gate_note = _operator_handoff_gate_note()
    for row in _source_qa_worksheet_todo_rows(packet):
        status = _source_qa_handoff_status(row)
        rows.append(
            {
                "task_type": "source_qa_worksheet",
                "priority": _handoff_priority(status),
                "status": status,
                "target": str(packet.source_qa_worksheet_status.get("path", "")),
                "source_artifact": "source_qa_worksheet_todo.csv",
                "row_number": str(row.get("row_number", "")),
                "file_name": "",
                "id": str(row.get("id", "")),
                "required": "yes",
                "severity": str(row.get("severity", "")),
                "cli_argument": str(row.get("cli_argument", "")),
                "action": str(row.get("message", "")),
                "required_evidence": str(row.get("required_evidence", "")),
                "current_state": str(row.get("current_state", "")),
                "preflight_status": str(row.get("preflight_status", "")),
                "acceptance_criteria": (
                    "Fill this worksheet row from real export evidence, then pass "
                    "data_source_qa_worksheet_preflight before regenerating "
                    "data_source_qa_answers.json."
                ),
                "next_command": worksheet_next_command,
                "gate_note": gate_note,
            }
        )
    for row in _source_qa_attachment_todo_rows(packet):
        status = _source_qa_handoff_status(row)
        rows.append(
            {
                "task_type": "source_qa_attachment",
                "priority": _handoff_priority(status),
                "status": status,
                "target": str(row.get("target", "")),
                "source_artifact": "source_qa_attachment_todo.csv",
                "row_number": "",
                "file_name": "",
                "id": str(row.get("id", "")),
                "required": "yes",
                "severity": str(row.get("severity", "")),
                "cli_argument": "",
                "action": str(row.get("action", "")),
                "required_evidence": str(row.get("required_evidence", "")),
                "acceptance_criteria": str(row.get("acceptance_criteria", "")),
                "current_state": str(row.get("current_state", "")),
                "next_command": str(row.get("next_command", "")),
                "gate_note": gate_note,
            }
        )
    for row in _data_export_todo_rows(packet):
        status = str(row.get("status", "WATCH"))
        file_name = str(row.get("file_name", ""))
        rows.append(
            {
                "task_type": "data_export",
                "priority": _handoff_priority(status),
                "status": status,
                "target": str(Path(packet.data_dir) / file_name),
                "source_artifact": "data_export_todo.csv",
                "row_number": "",
                "file_name": file_name,
                "id": file_name,
                "required": str(row.get("required", "")),
                "severity": status,
                "cli_argument": "",
                "action": str(row.get("action", "")),
                "required_evidence": str(row.get("columns", "")),
                "acceptance_criteria": str(row.get("acceptance_criteria", "")),
                "current_state": str(row.get("current_state", "")),
                "row_count": str(row.get("row_count", "")),
                "symbol_count": str(row.get("symbol_count", "")),
                "start": str(row.get("start", "")),
                "end": str(row.get("end", "")),
                "template_rows_detected": str(row.get("template_rows_detected", "")),
                "preview_status": str(row.get("preview_status", "")),
                "raw_columns": str(row.get("raw_columns", "")),
                "mapped_columns": str(row.get("mapped_columns", "")),
                "missing_columns": str(row.get("missing_columns", "")),
                "preview_message": str(row.get("preview_message", "")),
                "next_command": _handoff_next_command(packet),
                "gate_note": gate_note,
            }
        )
    return rows


def _source_qa_handoff_status(row: dict[str, str]) -> str:
    preflight_status = str(row.get("preflight_status", "")).upper()
    if preflight_status == "BLOCK":
        return "BLOCK"
    if preflight_status == "WATCH":
        return "WATCH"
    severity = str(row.get("severity", ""))
    if str(row.get("row_type", "")) == "metadata" or severity == "BLOCK_IF_NO":
        return "BLOCK"
    if severity == "WATCH_IF_NO":
        return "WATCH"
    return "WATCH"


def _handoff_priority(status: str) -> str:
    return "P0" if status == "BLOCK" else "P1"


def _handoff_item_label(row: dict[str, str]) -> str:
    if row.get("row_number"):
        return "`row {row_number}: {id}`".format(
            row_number=str(row.get("row_number", "")),
            id=str(row.get("id", "")),
        )
    if str(row.get("task_type", "")) == "source_qa_attachment":
        return "`attachment: {id}`".format(id=str(row.get("id", "")))
    return "`{file_name}`".format(file_name=str(row.get("file_name", "")))


def _handoff_next_command(packet: DataEvidenceActionPacket) -> str:
    for command in packet.immediate_commands:
        if "run_first_million_pipeline.py" in command or "run_offline_data_intake.py" in command:
            return command
    return packet.immediate_commands[-1] if packet.immediate_commands else ""


def _operator_handoff_gate_note() -> str:
    return (
        "Operator handoff is an execution aid only; deterministic source QA, import, "
        "audit, readiness gates, and human approval still decide stage access."
    )


def _export_path(item: dict[str, Any], *, data_dir: Path) -> Path:
    raw = str(item.get("path") or item.get("file_path") or "")
    if raw:
        return Path(raw)
    file_name = str(item.get("file_name", ""))
    return data_dir / file_name


def _csv_file_observation(path: Path, *, columns: str) -> dict[str, Any]:
    if not path.exists():
        return {
            "exists": False,
            "row_count": 0,
            "symbol_count": 0,
            "start": "",
            "end": "",
        }
    rows = _read_csv_rows(path)
    symbols = {
        str(row.get("symbol", "")).strip()
        for row in rows
        if str(row.get("symbol", "")).strip()
    }
    dates = sorted(
        {
            str(row.get("date", "")).strip()
            for row in rows
            if str(row.get("date", "")).strip()
        }
    )
    return {
        "exists": True,
        "row_count": len(rows),
        "symbol_count": len(symbols),
        "start": dates[0] if dates else "",
        "end": dates[-1] if dates else "",
        "columns": columns,
    }


def _csv_preview_by_file(*, data_dir: Path) -> dict[str, dict[str, Any]]:
    preview = build_csv_intake_preview(data_dir=data_dir)
    return {item.file_name: item.to_dict() for item in preview.items}


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except UnicodeDecodeError:
        with path.open("r", newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except OSError:
        return []


def _read_handoff_rows(path: Path) -> list[dict[str, str]]:
    return _read_csv_rows(path)


def _handoff_row_open(row: dict[str, str]) -> bool:
    status = str(row.get("status", "")).upper()
    if status in {"BLOCK", "WATCH"}:
        return True
    if row.get("task_type") == "data_export":
        state = str(row.get("current_state", ""))
        return state in {"missing", "template_sample_rows", "empty"}
    return False


def _operator_status(
    packet_decision: PacketDecision,
    *,
    p0_open: int,
    p1_open: int,
) -> PacketDecision:
    if packet_decision == "BLOCK" or p0_open:
        return "BLOCK"
    if packet_decision == "WATCH" or p1_open:
        return "WATCH"
    return "PASS"


def _first_open_tasks(rows: list[dict[str, str]], *, limit: int = 8) -> list[dict[str, str]]:
    ordered = sorted(
        rows,
        key=lambda row: (
            0 if str(row.get("priority", "")).upper() == "P0" else 1,
            _task_type_order(str(row.get("task_type", ""))),
            _row_number_order(str(row.get("row_number", ""))),
            str(row.get("file_name", "")),
        ),
    )
    return [
        {
            "priority": str(row.get("priority", "")),
            "task_type": str(row.get("task_type", "")),
            "item": _handoff_status_item(row),
            "status": str(row.get("status", "")),
            "target": str(row.get("target", "")),
            "next_command": str(row.get("next_command", "")),
            "current_state": str(row.get("current_state", "")),
            "required_evidence": str(row.get("required_evidence", "")),
            "source_artifact": str(row.get("source_artifact", "")),
            "action": str(row.get("action", "")),
        }
        for row in ordered[:limit]
    ]


def _next_operator_batch(rows: list[dict[str, str]], *, limit: int = 8) -> dict[str, Any]:
    ordered = sorted(
        rows,
        key=lambda row: (
            0 if str(row.get("priority", "")).upper() == "P0" else 1,
            _task_type_order(str(row.get("task_type", ""))),
            _row_number_order(str(row.get("row_number", ""))),
            str(row.get("file_name", "")),
        ),
    )
    if not ordered:
        return {
            "status": "PASS",
            "priority": "",
            "task_type": "",
            "task_count": 0,
            "sample_tasks": [],
            "source_artifacts": [],
            "acceptance_criteria": "No open operator handoff tasks remain.",
            "next_command": "",
            "gate_note": "Continue through deterministic source QA, import, audit, readiness, and approval gates.",
        }
    first = ordered[0]
    priority = str(first.get("priority", ""))
    task_type = str(first.get("task_type", ""))
    batch_rows = [
        row
        for row in ordered
        if str(row.get("priority", "")) == priority and str(row.get("task_type", "")) == task_type
    ]
    return {
        "status": "BLOCK" if priority == "P0" else "WATCH",
        "priority": priority,
        "task_type": task_type,
        "task_count": len(batch_rows),
        "sample_tasks": _first_open_tasks(batch_rows, limit=limit),
        "source_artifacts": sorted({str(row.get("source_artifact", "")) for row in batch_rows if row.get("source_artifact")}),
        "acceptance_criteria": _batch_acceptance(task_type),
        "next_command": str(batch_rows[0].get("next_command", "")),
        "gate_note": _operator_handoff_gate_note(),
    }


def _batch_acceptance(task_type: str) -> str:
    if task_type == "source_qa_worksheet":
        return (
            "Every row in this batch is filled from real vendor/export evidence, "
            "then data_source_qa_worksheet_preflight passes before data_source_qa_answers.json is regenerated."
        )
    if task_type == "source_qa_attachment":
        return (
            "Every attachment in this batch points to retained, non-placeholder local evidence, "
            "then source_qa_evidence_manifest.json is regenerated."
        )
    if task_type == "data_export":
        return (
            "Every CSV in this batch is replaced by a real, non-template export with schema-valid rows "
            "and enough A-share coverage for the configured gate."
        )
    return "Complete this operator batch, then rerun the deterministic gate that produced it."


def _handoff_status_item(row: dict[str, str]) -> str:
    if str(row.get("task_type", "")) == "source_qa_worksheet":
        if not str(row.get("row_number", "")).strip():
            return str(row.get("id", ""))
        return f"row {row.get('row_number', '')}: {row.get('id', '')}"
    if str(row.get("task_type", "")) == "source_qa_attachment":
        return f"attachment: {row.get('id', '')}"
    return str(row.get("file_name") or row.get("id") or row.get("target") or "")


def _task_type_order(task_type: str) -> int:
    if task_type == "source_qa_worksheet":
        return 0
    if task_type == "source_qa_attachment":
        return 1
    if task_type == "data_export":
        return 2
    return 3


def _row_number_order(value: str) -> int:
    text = value.strip()
    if not text:
        return 0
    try:
        return int(text)
    except ValueError:
        return 999_999


def _operator_status_next_actions(
    packet: DataEvidenceActionPacket,
    source_rows: list[dict[str, str]],
    export_rows: list[dict[str, str]],
    open_rows: list[dict[str, str]],
) -> list[str]:
    actions: list[str] = []
    if source_rows:
        worksheet_rows = [
            row for row in source_rows if row.get("task_type") == "source_qa_worksheet"
        ]
        attachment_rows = [
            row for row in source_rows if row.get("task_type") == "source_qa_attachment"
        ]
        if worksheet_rows:
            actions.append(
                (
                    f"Fill {len(worksheet_rows)} open source QA worksheet rows using "
                    "source_qa_worksheet_todo.csv, then run worksheet preflight before "
                    "regenerating data_source_qa_answers.json."
                )
            )
            command = str(worksheet_rows[0].get("next_command") or "").strip()
            if command:
                actions.append(f"After filling source QA worksheet evidence, run worksheet preflight: {command}")
        if attachment_rows:
            actions.append(
                (
                    f"Prepare {len(attachment_rows)} local source QA evidence attachments using "
                    "source_qa_attachment_todo.csv, then regenerate source_qa_evidence_manifest.json."
                )
            )
            command = str(attachment_rows[0].get("next_command") or "").strip()
            if command:
                actions.append(f"After adding source QA attachments, run: {command}")
    if export_rows:
        files = ", ".join(str(row.get("file_name", "")) for row in export_rows[:6])
        actions.append(
            (
                f"Replace or verify {len(export_rows)} data export files using "
                f"data_export_todo.csv. First files: {files}."
            )
        )
    if not open_rows and packet.decision != "PASS":
        actions.append(
            "Operator queue has no open rows, but deterministic packet decision is not PASS; rerun data gap and source QA reviews."
        )
    if not actions:
        actions.append(
            "Operator queue has no open rows; continue with deterministic source QA, offline intake, audit, robustness, and paper gates."
        )
    elif not any("deterministic" in action for action in actions):
        actions.append(
            "After operator tasks change, rerun deterministic source QA, offline intake, audit, readiness, and goal gates."
        )
    return actions


def _operator_status_prohibited_actions() -> list[str]:
    return [
        "Do not treat operator handoff status as a strategy signal or profitability evidence.",
        "Do not use a PASS operator queue to bypass source QA, offline intake, data audit, robustness, paper, or approval gates.",
        "Do not fabricate worksheet evidence or CSV rows to close handoff tasks.",
        "Do not connect this workflow to real broker order submission.",
        "Do not let LLM text override deterministic gates or human approval.",
    ]


def _export_current_state(
    *,
    exists: bool,
    template_detected: bool,
    row_count: int,
) -> str:
    if not exists:
        return "missing"
    if template_detected:
        return "template_sample_rows"
    if row_count <= 0:
        return "empty"
    return "present_needs_validation"


def _period_label(start: object, end: object) -> str:
    left = str(start or "-")
    right = str(end or "-")
    return f"{left} to {right}"


def _file_acceptance_criteria(file_name: str, required: str) -> str:
    if file_name == "bars.csv":
        return "Recent daily OHLCV rows; configured date range; minimum symbol count; consistent adjustment."
    if required == "yes":
        return "Required file must be present, non-template, and schema-valid."
    return "Recommended audit file should come from the same export batch or be explicitly unavailable."


def _operator_checklist(
    request: DataExportRequest,
    plan: DataGapActionPlan,
) -> list[str]:
    checklist = [
        (
            f"Export A-share daily bars from {request.start} to {request.end}; "
            f"target at least {request.min_symbols} symbols and use {request.price_adjustment} adjustment."
        ),
        "Record the vendor or broker terminal name, product version if available, operator, and local export timestamp.",
        "Keep screenshots, export logs, or terminal settings that prove price adjustment, license scope, and export time.",
        "Fill data_source_qa_evidence_worksheet.csv before generating data_source_qa_answers.json.",
        "Run source QA preflight and data import doctor before guarded offline intake.",
    ]
    if any(item.name == "tdx_day_export" for item in plan.items):
        checklist.append(
            "For TongDaXin .day data, record the exact vipdoc/lday directory and keep the path OHLCV-only unless separate PIT evidence exists."
        )
    return checklist


def _immediate_commands(plan: DataGapActionPlan) -> list[str]:
    if plan.decision == "PASS":
        return plan.next_commands[-2:]
    return plan.next_commands[:8]


def _completion_criteria(request: DataExportRequest, min_symbols: int) -> list[str]:
    return [
        f"bars.csv covers {request.start} through {request.end} with at least {min_symbols} symbols.",
        "data_source_qa_answers.json is filled from real evidence and source QA preflight is PASS.",
        "Data import doctor has no BLOCK findings and no generated template rows remain.",
        "Guarded offline intake writes a research cache and preserves source traceability.",
        "first_million_pipeline rerun still blocks live trading but can advance to candidate readiness only after data gates pass.",
    ]
