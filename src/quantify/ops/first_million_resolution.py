"""Resolution plan for blocked first-million pipeline runs.

The plan turns deterministic gate output into an operator-facing queue. It
does not override any gate and it does not mark evidence as complete.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

ResolutionDecision = Literal["PASS", "WATCH", "BLOCK"]
ResolutionPriority = Literal["P0", "P1", "P2"]

PROHIBITED_ACTIONS = [
    "Do not close a resolution task without changing the underlying evidence artifact.",
    "Do not use this plan to upgrade deterministic PASS/WATCH/BLOCK gates.",
    "Do not fabricate source QA answers, evidence attachments, CSV rows, paper records, or approvals.",
    "Do not treat this plan as a strategy signal, profit claim, or capital allocation permission.",
    "Do not connect this workflow to real broker order submission.",
    "Do not let LLM output modify task status, deterministic gate status, or human approval requirements.",
]

_DATA_STAGE_NAMES = {
    "recent_data_acquisition_plan",
    "data_source_selection",
    "data_gap_action_plan",
    "data_evidence_action_packet",
    "evidence_intake_kit",
    "evidence_work_order",
    "operator_handoff_status",
    "csv_intake_preview",
    "source_qa_preflight",
    "data_intake_router",
    "tdx_day_discovery",
    "tdx_day_export",
    "vendor_bars_normalization",
    "offline_data_package",
    "real_data_handoff_checklist",
    "data_source_qa_review",
    "offline_data_intake",
    "run_manifest",
}

_DOWNSTREAM_STAGE_NAMES = {
    "weekly_pipeline",
    "market_index_discovery",
    "market_context_readiness",
    "candidate_experiment_readiness",
    "first_million_strategy_brief",
    "candidate_experiment_launch",
    "candidate_experiment_execution",
    "candidate_experiment_completion",
    "capital_goal_status",
    "compounding_path_review",
    "first_million_readiness",
    "market_context_snapshot",
}


@dataclass(frozen=True, slots=True)
class FirstMillionResolutionTask:
    priority: ResolutionPriority
    status: str
    category: str
    item: str
    target: str
    source_stage: str
    source_artifact: str
    action: str
    acceptance_criteria: str
    command: str
    gate_note: str

    def to_dict(self) -> dict[str, str]:
        return {
            "priority": self.priority,
            "status": self.status,
            "category": self.category,
            "item": self.item,
            "target": self.target,
            "source_stage": self.source_stage,
            "source_artifact": self.source_artifact,
            "action": self.action,
            "acceptance_criteria": self.acceptance_criteria,
            "command": self.command,
            "gate_note": self.gate_note,
        }


@dataclass(frozen=True, slots=True)
class FirstMillionResolutionPlan:
    decision: ResolutionDecision
    as_of: str
    report_dir: str
    pipeline_decision: str
    task_counts: dict[str, int]
    tasks: list[FirstMillionResolutionTask]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "as_of": self.as_of,
            "report_dir": self.report_dir,
            "pipeline_decision": self.pipeline_decision,
            "task_counts": self.task_counts,
            "tasks": [task.to_dict() for task in self.tasks],
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# First Million Resolution Plan: {self.decision}",
            "",
            f"- As of: `{self.as_of}`",
            f"- Report directory: `{self.report_dir}`",
            f"- Pipeline decision: `{self.pipeline_decision}`",
            f"- P0 open tasks: {self.task_counts.get('P0', 0)}",
            f"- P1 open tasks: {self.task_counts.get('P1', 0)}",
            f"- P2 waiting tasks: {self.task_counts.get('P2', 0)}",
            "",
            "This plan is an execution queue for existing deterministic blockers. It is not a gate override, strategy recommendation, or live trading instruction.",
            "",
            "## Top Tasks",
            "",
        ]
        if self.tasks:
            lines.append("| priority | status | category | item | target | action | acceptance | command | artifact |")
            lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
            for task in self.tasks[:20]:
                command = task.command.replace("|", "\\|")
                acceptance = task.acceptance_criteria.replace("|", "\\|")
                lines.append(
                    f"| `{task.priority}` | `{task.status}` | `{task.category}` | "
                    f"`{task.item}` | `{task.target}` | {task.action} | {acceptance} | "
                    f"`{command}` | `{task.source_artifact}` |"
                )
            command_tasks = [task for task in self.tasks[:20] if task.command]
            if command_tasks:
                lines.extend(["", "## Top Commands"])
                for index, task in enumerate(command_tasks[:8], start=1):
                    lines.extend(
                        [
                            "",
                            f"{index}. `{task.item}`",
                            "",
                            "```powershell",
                            task.command,
                            "```",
                        ]
                    )
        else:
            lines.append("- None.")
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_first_million_resolution_plan(
    report_dir: str | Path,
    *,
    as_of: str | None = None,
    pipeline_payload: dict[str, Any] | None = None,
) -> FirstMillionResolutionPlan:
    """Build an operator queue from the current first-million report directory."""
    root = Path(report_dir)
    pipeline = pipeline_payload or _read_json(root / "first_million_pipeline.json")
    pipeline_decision = str(pipeline.get("decision") or "UNKNOWN").upper()
    stages = _list_of_dicts(pipeline.get("stages"))

    tasks = _operator_handoff_tasks(root)
    has_p0_operator_tasks = any(task.priority == "P0" for task in tasks)
    tasks.extend(_stage_tasks(root, stages, has_p0_operator_tasks=has_p0_operator_tasks))
    tasks.extend(_candidate_matrix_tasks(root, has_p0_operator_tasks=has_p0_operator_tasks))
    tasks = _dedupe_tasks(tasks)
    tasks = sorted(tasks, key=_task_sort_key)

    decision = _decision(pipeline_decision, tasks)
    return FirstMillionResolutionPlan(
        decision=decision,
        as_of=as_of or str(pipeline.get("as_of") or date.today().isoformat()),
        report_dir=str(root),
        pipeline_decision=pipeline_decision,
        task_counts=_task_counts(tasks),
        tasks=tasks,
        next_actions=_next_actions(tasks, pipeline_decision),
        prohibited_actions=PROHIBITED_ACTIONS,
    )


def write_first_million_resolution_plan(
    plan: FirstMillionResolutionPlan,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "first_million_resolution_plan.json").write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "first_million_resolution_plan.md").write_text(
        plan.to_markdown(),
        encoding="utf-8",
    )
    with (root / "first_million_resolution_plan.csv").open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        fieldnames = [
            "priority",
            "status",
            "category",
            "item",
            "target",
            "source_stage",
            "source_artifact",
            "action",
            "acceptance_criteria",
            "command",
            "gate_note",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(task.to_dict() for task in plan.tasks)
    return root


def _operator_handoff_tasks(root: Path) -> list[FirstMillionResolutionTask]:
    rows = _read_csv_rows(root / "operator_handoff.csv")
    tasks: list[FirstMillionResolutionTask] = []
    for row in rows:
        if not _handoff_row_open(row):
            continue
        task_type = str(row.get("task_type") or "operator_handoff").strip()
        source_artifact = str(row.get("source_artifact") or "operator_handoff.csv").strip()
        target = str(row.get("target") or "").strip()
        item = _handoff_item(row)
        action = str(row.get("action") or "").strip() or f"Resolve {item} in {task_type}."
        tasks.append(
            FirstMillionResolutionTask(
                priority=_normalize_priority(row.get("priority"), row.get("status")),
                status="OPEN",
                category=task_type,
                item=item,
                target=target,
                source_stage="operator_handoff",
                source_artifact=_artifact_path(root, source_artifact),
                action=action,
                acceptance_criteria=str(row.get("acceptance_criteria") or "").strip()
                or _default_acceptance(task_type),
                command=str(row.get("next_command") or "").strip(),
                gate_note=str(row.get("gate_note") or "").strip()
                or "Rerun deterministic gates after changing this evidence.",
            )
        )
    return tasks


def _stage_tasks(
    root: Path,
    stages: list[dict[str, Any]],
    *,
    has_p0_operator_tasks: bool,
) -> list[FirstMillionResolutionTask]:
    tasks = []
    for stage in stages:
        status = str(stage.get("status") or "").upper()
        name = str(stage.get("name") or "unknown_stage")
        if status not in {"BLOCK", "WATCH", "SKIPPED", "MISSING", "UNKNOWN"}:
            continue
        if has_p0_operator_tasks and name in _DATA_STAGE_NAMES:
            priority: ResolutionPriority = "P1"
            task_status = "OPEN"
        elif name in _DOWNSTREAM_STAGE_NAMES or status == "SKIPPED":
            priority = "P2"
            task_status = "WAITING"
        elif status == "WATCH":
            priority = "P1"
            task_status = "WATCH"
        else:
            priority = "P0"
            task_status = "OPEN"
        artifact = str(stage.get("artifact") or "").strip()
        resolved_artifact = _resolve_artifact(root, artifact) if artifact else None
        payload = _read_json(resolved_artifact) if resolved_artifact else {}
        tasks.append(
            FirstMillionResolutionTask(
                priority=priority,
                status=task_status,
                category=_stage_category(name),
                item=name,
                target=str(resolved_artifact or ""),
                source_stage=name,
                source_artifact=artifact,
                action=_stage_action(stage, payload, status),
                acceptance_criteria=_stage_acceptance(name, status),
                command=_first_command(payload),
                gate_note="This stage task is informational; only the owning deterministic gate can clear it.",
            )
        )
    return tasks


def _candidate_matrix_tasks(
    root: Path,
    *,
    has_p0_operator_tasks: bool,
) -> list[FirstMillionResolutionTask]:
    path = root / "candidate_experiment_readiness_matrix.csv"
    rows = _read_csv_rows(path)
    tasks = []
    if any(
        str(row.get("market_context_source") or "").lower() == "missing"
        and str(row.get("market_context_status") or "").upper() == "BLOCK"
        for row in rows
    ):
        tasks.append(
            FirstMillionResolutionTask(
                priority="P2" if has_p0_operator_tasks else "P1",
                status="WAITING" if has_p0_operator_tasks else "OPEN",
                category="market_context",
                item="market_regime_or_reviewed_snapshot",
                target=str(root / "market_regime.json"),
                source_stage="candidate_experiment_readiness",
                source_artifact=str(path),
                action=(
                    "Generate cache-derived market_regime.json from audited recent A-share daily data, "
                    "or attach a reviewed market_context_snapshot.json as temporary advisory context."
                ),
                acceptance_criteria=(
                    "candidate_experiment_readiness_matrix.csv shows market_context_source=market_regime "
                    "with PASS, or reviewed snapshot context keeps readiness at WATCH without launching paper."
                ),
                command=(
                    ".\\.venv\\Scripts\\python.exe examples\\run_market_regime.py --config "
                    "config\\research_recent.yaml --output-dir results\\first_million"
                ),
                gate_note=(
                    "Market context is evidence for candidate research only; it cannot override source QA, "
                    "data intake, or completion gates."
                ),
            )
        )
    for row in rows:
        status = str(row.get("status") or "").upper()
        if status in {"READY", "PASS"}:
            continue
        candidate = str(row.get("candidate") or "").strip()
        if not candidate:
            continue
        first_blocker = str(row.get("first_blocker") or "").strip()
        tasks.append(
            FirstMillionResolutionTask(
                priority="P2" if has_p0_operator_tasks else "P1",
                status="WAITING" if has_p0_operator_tasks else "OPEN",
                category="candidate_experiment",
                item=candidate,
                target=candidate,
                source_stage="candidate_experiment_readiness",
                source_artifact=str(path),
                action=first_blocker or "Resolve candidate experiment readiness blockers.",
                acceptance_criteria=(
                    "Candidate row becomes READY under candidate_experiment_readiness without "
                    "weakening data dependency gates."
                ),
                command=str(row.get("next_command") or "").strip(),
                gate_note="Candidate tasks must wait for source QA, offline intake, and data handoff gates.",
            )
        )
    return tasks


def _decision(
    pipeline_decision: str,
    tasks: list[FirstMillionResolutionTask],
) -> ResolutionDecision:
    if pipeline_decision == "BLOCK":
        return "BLOCK"
    if any(task.priority == "P0" for task in tasks):
        return "BLOCK"
    if pipeline_decision == "WATCH" or tasks:
        return "WATCH"
    return "PASS"


def _next_actions(
    tasks: list[FirstMillionResolutionTask],
    pipeline_decision: str,
) -> list[str]:
    if not tasks:
        if pipeline_decision == "PASS":
            return [
                "No open resolution tasks; continue only through deterministic review and human approval."
            ]
        return ["Rerun first-million pipeline to refresh missing resolution evidence."]
    actions = []
    for priority in ("P0", "P1", "P2"):
        for task in tasks:
            if task.priority == priority:
                action = _task_next_action(task)
                if action not in actions:
                    actions.append(action)
            if len(actions) >= 5:
                return actions
    return actions


def _task_next_action(task: FirstMillionResolutionTask) -> str:
    pieces = [task.action]
    if task.target:
        pieces.append(f"Target: {task.target}.")
    if task.command:
        pieces.append(f"Run: {task.command}")
    if task.acceptance_criteria:
        pieces.append(f"Done when: {task.acceptance_criteria}")
    return " ".join(piece for piece in pieces if piece)


def _task_counts(tasks: list[FirstMillionResolutionTask]) -> dict[str, int]:
    return {
        "total": len(tasks),
        "P0": sum(1 for task in tasks if task.priority == "P0"),
        "P1": sum(1 for task in tasks if task.priority == "P1"),
        "P2": sum(1 for task in tasks if task.priority == "P2"),
        "open": sum(1 for task in tasks if task.status == "OPEN"),
        "waiting": sum(1 for task in tasks if task.status == "WAITING"),
        "watch": sum(1 for task in tasks if task.status == "WATCH"),
    }


def _dedupe_tasks(tasks: list[FirstMillionResolutionTask]) -> list[FirstMillionResolutionTask]:
    seen: set[tuple[str, str, str]] = set()
    deduped = []
    for task in tasks:
        key = (task.category, task.item, task.action)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(task)
    return deduped


def _task_sort_key(task: FirstMillionResolutionTask) -> tuple[int, int, str, str]:
    priority_rank = {"P0": 0, "P1": 1, "P2": 2}.get(task.priority, 9)
    category_rank = {
        "source_qa_worksheet": 0,
        "source_qa_attachment": 1,
        "data_export": 2,
        "data_gate": 3,
        "source_qa": 4,
        "offline_intake": 5,
        "market_context": 6,
        "candidate_experiment": 7,
        "goal_review": 8,
    }.get(task.category, 8)
    return (priority_rank, category_rank, task.source_stage, _task_item_order(task))


def _task_item_order(task: FirstMillionResolutionTask) -> str:
    if task.category == "source_qa_worksheet" and task.item.startswith("row "):
        row_text = task.item.split(":", 1)[0].replace("row", "").strip()
        try:
            return f"{int(row_text):06d}:{task.item}"
        except ValueError:
            return task.item
    return task.item


def _handoff_row_open(row: dict[str, str]) -> bool:
    status = str(row.get("status") or "").upper()
    if status in {"BLOCK", "WATCH"}:
        return True
    if row.get("task_type") == "data_export":
        current_state = str(row.get("current_state") or "")
        return current_state in {"missing", "template_sample_rows", "empty"}
    return False


def _handoff_item(row: dict[str, str]) -> str:
    task_type = str(row.get("task_type") or "")
    if task_type == "source_qa_worksheet":
        row_number = str(row.get("row_number") or "").strip()
        item_id = str(row.get("id") or "").strip()
        return f"row {row_number}: {item_id}" if row_number else item_id
    if task_type == "source_qa_attachment":
        return str(row.get("id") or row.get("target") or "source_qa_attachment")
    return str(row.get("file_name") or row.get("id") or row.get("target") or task_type)


def _normalize_priority(priority: object, status: object) -> ResolutionPriority:
    text = str(priority or "").upper()
    if text in {"P0", "P1", "P2"}:
        return text  # type: ignore[return-value]
    return "P0" if str(status or "").upper() == "BLOCK" else "P1"


def _stage_category(name: str) -> str:
    if name in {
        "source_qa_preflight",
        "data_source_qa_review",
        "data_gap_action_plan",
        "data_evidence_action_packet",
        "operator_handoff_status",
        "evidence_intake_kit",
        "evidence_work_order",
    }:
        return "source_qa"
    if name in {"offline_data_intake", "offline_data_package", "data_intake_router"}:
        return "offline_intake"
    if name in {
        "market_context_readiness",
        "market_index_discovery",
        "market_context_snapshot",
    }:
        return "market_context"
    if name in {
        "candidate_experiment_readiness",
        "candidate_experiment_launch",
        "candidate_experiment_execution",
        "candidate_experiment_completion",
        "weekly_pipeline",
        "first_million_strategy_brief",
    }:
        return "candidate_experiment"
    if name in {"capital_goal_status", "compounding_path_review", "first_million_readiness"}:
        return "goal_review"
    return "data_gate" if name in _DATA_STAGE_NAMES else "pipeline_gate"


def _stage_action(
    stage: dict[str, Any],
    payload: dict[str, Any],
    status: str,
) -> str:
    blocker = _first_text(payload.get("blockers"))
    if blocker:
        return blocker
    current_blocker = _first_text(payload.get("current_blockers"))
    if current_blocker:
        return current_blocker
    next_action = _first_text(payload.get("next_actions"))
    if next_action:
        return next_action
    next_command = _first_text(payload.get("next_commands"))
    if next_command:
        return next_command
    if status == "SKIPPED":
        return "Wait until upstream source QA and offline intake gates are PASS, then rerun this stage."
    message = str(stage.get("message") or "").strip()
    if message:
        return message
    return f"Resolve {stage.get('name', 'pipeline stage')} and rerun first-million pipeline."


def _stage_acceptance(name: str, status: str) -> str:
    if status == "SKIPPED":
        return f"{name} is regenerated after upstream gates pass."
    if name in _DATA_STAGE_NAMES:
        return f"{name} is PASS after rerunning deterministic data/source gates."
    if name in _DOWNSTREAM_STAGE_NAMES:
        return f"{name} is no longer BLOCK after upstream evidence and required experiments pass."
    return f"{name} is no longer {status} after deterministic review."


def _first_command(payload: dict[str, Any]) -> str:
    command = _first_text(payload.get("next_commands"))
    if command:
        return command
    commands = payload.get("immediate_commands")
    command = _first_text(commands)
    if command:
        return command
    steps = payload.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, dict) and step.get("command"):
                return str(step["command"])
    return ""


def _default_acceptance(task_type: str) -> str:
    if task_type == "source_qa_worksheet":
        return "Worksheet row is filled from real export evidence and source QA answers are regenerated."
    if task_type == "source_qa_attachment":
        return "Attachment exists locally and is included in source_qa_evidence_manifest.json."
    if task_type == "data_export":
        return "CSV file is present, non-template, schema-valid, and traceable to the export batch."
    return "The referenced operator task is resolved and deterministic gates are rerun."


def _artifact_path(root: Path, artifact: str) -> str:
    path = Path(artifact)
    if path.is_absolute():
        return str(path)
    return str(root / path)


def _resolve_artifact(root: Path, artifact: str) -> Path:
    path = Path(artifact)
    if path.is_absolute():
        return path
    if path.exists():
        return path
    root_relative = root / path
    if root_relative.exists():
        return root_relative
    return root / path.name


def _first_text(values: object) -> str:
    if isinstance(values, list):
        for value in values:
            if isinstance(value, dict):
                parts = [
                    str(value.get(key) or "").strip()
                    for key in ("name", "code", "message", "next_action")
                    if str(value.get(key) or "").strip()
                ]
                if parts:
                    return ": ".join(parts)
            text = str(value or "").strip()
            if text:
                return text
    return ""


def _list_of_dicts(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except UnicodeDecodeError:
        with path.open("r", newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except OSError:
        return []
