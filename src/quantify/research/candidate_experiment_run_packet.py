"""Research-only command packet for a candidate experiment run.

The packet is an operator-facing wrapper around launch, guarded dry-run,
explicit execution, completion review, stress evidence, and next-experiment
diagnosis. It never runs commands by itself and never grants paper/live access.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from quantify.research.candidate_experiment_launch import (
    CandidateExperimentLaunchPlan,
    build_candidate_experiment_launch_from_report,
)

RunPacketDecision = Literal["PASS", "BLOCK"]

ARTIFACT_TYPE = "candidate_experiment_run_packet"
STATUS = "RESEARCH_ONLY"
PROHIBITED_ACTIONS = [
    "Do not execute packet commands while packet decision is BLOCK.",
    "Do not bypass the guarded executor by running launch-plan commands manually without review.",
    "Do not treat this packet as paper approval, live approval, profitability evidence, or a buy/sell signal.",
    "Do not connect any packet command to real broker order submission.",
    "Do not let LLM output upgrade deterministic gates, queue priority, or human approval requirements.",
]
ALLOWED_ACTIONS = [
    "Write a candidate_experiment_launch plan for the selected research-only candidate.",
    "Validate launch-plan commands with the guarded executor in dry-run mode.",
    "Run the guarded executor only after explicit operator opt-in.",
    "Review completion and generate next-experiment diagnostics from resulting research artifacts.",
]


@dataclass(frozen=True, slots=True)
class CandidateExperimentRunPacketCommand:
    index: int
    phase: str
    command: str
    execution_mode: str
    purpose: str
    requires_explicit_operator_opt_in: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "phase": self.phase,
            "command": self.command,
            "execution_mode": self.execution_mode,
            "purpose": self.purpose,
            "requires_explicit_operator_opt_in": self.requires_explicit_operator_opt_in,
        }


@dataclass(frozen=True, slots=True)
class CandidateExperimentRunPacket:
    artifact_type: str
    status: str
    decision: RunPacketDecision
    as_of: str | None
    report_dir: str
    config_path: str
    selected_candidate: str
    data_dependency: str
    run_id: str
    experiment_dir: str
    launch_decision: str
    ohlcv_only: bool
    blocked_by: list[str]
    command_bundle: list[CandidateExperimentRunPacketCommand]
    launch_command_sequence: list[str]
    required_outputs: list[str]
    missing_evidence: list[str]
    capability_flags: dict[str, bool]
    allowed_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "status": self.status,
            "decision": self.decision,
            "as_of": self.as_of,
            "report_dir": self.report_dir,
            "config_path": self.config_path,
            "selected_candidate": self.selected_candidate,
            "data_dependency": self.data_dependency,
            "run_id": self.run_id,
            "experiment_dir": self.experiment_dir,
            "launch_decision": self.launch_decision,
            "ohlcv_only": self.ohlcv_only,
            "blocked_by": self.blocked_by,
            "command_bundle": [command.to_dict() for command in self.command_bundle],
            "launch_command_sequence": self.launch_command_sequence,
            "required_outputs": self.required_outputs,
            "missing_evidence": self.missing_evidence,
            "capability_flags": self.capability_flags,
            "allowed_actions": self.allowed_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Candidate Experiment Run Packet: {self.decision}",
            "",
            f"- Status: `{self.status}`",
            f"- As of: `{self.as_of or 'unspecified'}`",
            f"- Candidate: `{self.selected_candidate or 'none'}`",
            f"- Data dependency: `{self.data_dependency or 'unknown'}`",
            f"- Run ID: `{self.run_id or 'none'}`",
            f"- Experiment directory: `{self.experiment_dir or 'none'}`",
            f"- Launch decision: `{self.launch_decision or 'unknown'}`",
            f"- OHLCV-only packet: `{self.ohlcv_only}`",
            "",
            "This packet is a research-only command bundle. It does not execute commands, approve paper/live trading, or generate broker orders.",
            "",
            "## Command Bundle",
        ]
        if self.command_bundle:
            for command in self.command_bundle:
                opt_in = "explicit opt-in required" if command.requires_explicit_operator_opt_in else "review step"
                lines.extend(
                    [
                        "",
                        f"{command.index}. `{command.phase}` - {opt_in}",
                        "",
                        "```powershell",
                        command.command,
                        "```",
                        "",
                        f"- Mode: `{command.execution_mode}`",
                        f"- Purpose: {command.purpose}",
                    ]
                )
        else:
            lines.append("- None while packet is BLOCK.")
        lines.extend(["", "## Launch Command Sequence"])
        if self.launch_command_sequence:
            lines.extend(f"- `{command}`" for command in self.launch_command_sequence)
        else:
            lines.append("- None.")
        lines.extend(["", "## Required Outputs"])
        lines.extend(f"- `{item}`" for item in self.required_outputs) if self.required_outputs else lines.append("- None.")
        lines.extend(["", "## Missing Evidence"])
        lines.extend(f"- {item}" for item in self.missing_evidence) if self.missing_evidence else lines.append("- None.")
        lines.extend(["", "## Capability Flags"])
        lines.extend(f"- `{key}`: `{value}`" for key, value in self.capability_flags.items())
        lines.extend(["", "## Blockers"])
        lines.extend(f"- {item}" for item in self.blocked_by) if self.blocked_by else lines.append("- None.")
        lines.extend(["", "## Allowed Actions"])
        lines.extend(f"- {item}" for item in self.allowed_actions)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"

    def to_csv_rows(self) -> list[dict[str, Any]]:
        return [
            {
                "index": command.index,
                "phase": command.phase,
                "execution_mode": command.execution_mode,
                "requires_explicit_operator_opt_in": command.requires_explicit_operator_opt_in,
                "purpose": command.purpose,
                "command": command.command,
            }
            for command in self.command_bundle
        ]


def build_candidate_experiment_run_packet_from_report(
    report_dir: str | Path,
    *,
    config_path: str | Path = "config/research_recent.yaml",
    candidate: str | None = None,
    as_of: str | None = None,
    run_id: str | None = None,
    ohlcv_only: bool = True,
) -> CandidateExperimentRunPacket:
    root = Path(report_dir)
    launch = build_candidate_experiment_launch_from_report(
        root,
        config_path=config_path,
        candidate=candidate,
        as_of=as_of,
        run_id=run_id,
    )
    return build_candidate_experiment_run_packet(
        launch,
        report_dir=root,
        config_path=config_path,
        as_of=as_of,
        ohlcv_only=ohlcv_only,
    )


def build_candidate_experiment_run_packet(
    launch: CandidateExperimentLaunchPlan,
    *,
    report_dir: str | Path,
    config_path: str | Path = "config/research_recent.yaml",
    as_of: str | None = None,
    ohlcv_only: bool = True,
) -> CandidateExperimentRunPacket:
    root = Path(report_dir)
    selected_candidate = launch.selected_candidate
    data_dependency = _candidate_data_dependency(root, selected_candidate)
    blockers = list(launch.blocked_by)
    if launch.decision == "PASS" and ohlcv_only and data_dependency != "ohlcv_only":
        blockers.append(
            "Selected candidate is not OHLCV-only: "
            f"candidate={selected_candidate or 'none'}, data_dependency={data_dependency or 'unknown'}."
        )
    decision: RunPacketDecision = "BLOCK" if blockers or launch.decision != "PASS" else "PASS"
    required_outputs = _required_outputs(launch) if decision == "PASS" else []
    command_bundle = _command_bundle(
        launch,
        report_dir=root,
        config_path=Path(config_path),
        as_of=as_of or launch.as_of,
    ) if decision == "PASS" else []
    return CandidateExperimentRunPacket(
        artifact_type=ARTIFACT_TYPE,
        status=STATUS,
        decision=decision,
        as_of=as_of or launch.as_of,
        report_dir=str(root),
        config_path=str(config_path),
        selected_candidate=selected_candidate,
        data_dependency=data_dependency,
        run_id=launch.run_id,
        experiment_dir=launch.experiment_dir,
        launch_decision=launch.decision,
        ohlcv_only=ohlcv_only,
        blocked_by=blockers or ([] if decision == "PASS" else [f"Launch decision is {launch.decision}."]),
        command_bundle=command_bundle,
        launch_command_sequence=launch.command_sequence if decision == "PASS" else [],
        required_outputs=required_outputs,
        missing_evidence=_missing_evidence(required_outputs, blockers),
        capability_flags=_capability_flags(),
        allowed_actions=list(ALLOWED_ACTIONS),
        prohibited_actions=list(PROHIBITED_ACTIONS),
    )


def write_candidate_experiment_run_packet(
    packet: CandidateExperimentRunPacket,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "candidate_experiment_run_packet.json").write_text(
        json.dumps(packet.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "candidate_experiment_run_packet.md").write_text(
        packet.to_markdown(),
        encoding="utf-8",
    )
    _write_csv(root / "candidate_experiment_run_packet.csv", packet.to_csv_rows())
    return root


def _command_bundle(
    launch: CandidateExperimentLaunchPlan,
    *,
    report_dir: Path,
    config_path: Path,
    as_of: str | None,
) -> list[CandidateExperimentRunPacketCommand]:
    commands: list[CandidateExperimentRunPacketCommand] = []
    commands.append(
        CandidateExperimentRunPacketCommand(
            index=1,
            phase="write_launch",
            command=_launch_command(launch, report_dir=report_dir, config_path=config_path, as_of=as_of),
            execution_mode="manual_setup",
            purpose="Write or refresh candidate_experiment_launch.json before executing research.",
        )
    )
    for command in launch.command_sequence:
        commands.append(
            CandidateExperimentRunPacketCommand(
                index=len(commands) + 1,
                phase="launch_plan_step",
                command=command,
                execution_mode="guarded_executor_step",
                purpose=_command_purpose(command),
                requires_explicit_operator_opt_in=True,
            )
        )
    commands.append(
        CandidateExperimentRunPacketCommand(
            index=len(commands) + 1,
            phase="dry_run_execution",
            command=f"python examples/run_candidate_experiment_execution.py --report-dir {report_dir} --dry-run",
            execution_mode="dry_run",
            purpose="Validate the launch-plan whitelist, output scope, and gate-report bindings without running research.",
        )
    )
    commands.append(
        CandidateExperimentRunPacketCommand(
            index=len(commands) + 1,
            phase="explicit_execution",
            command=f"python examples/run_candidate_experiment_execution.py --report-dir {report_dir}",
            execution_mode="explicit_opt_in",
            purpose="Run whitelisted launch-plan research commands and capture logs after operator opt-in.",
            requires_explicit_operator_opt_in=True,
        )
    )
    commands.append(
        CandidateExperimentRunPacketCommand(
            index=len(commands) + 1,
            phase="completion_review",
            command=_completion_command(report_dir, as_of=as_of),
            execution_mode="deterministic_review",
            purpose="Verify every required research artifact from the launch plan.",
        )
    )
    commands.append(
        CandidateExperimentRunPacketCommand(
            index=len(commands) + 1,
            phase="next_experiments",
            command=(
                "python examples/run_candidate_next_experiments.py "
                f"--report-dir {launch.experiment_dir} --output-dir {launch.experiment_dir}"
            ),
            execution_mode="research_diagnosis",
            purpose="Convert incomplete or blocked candidate evidence into the next research-only work queue.",
        )
    )
    return commands


def _launch_command(
    launch: CandidateExperimentLaunchPlan,
    *,
    report_dir: Path,
    config_path: Path,
    as_of: str | None,
) -> str:
    parts = [
        "python examples/run_candidate_experiment_launch.py",
        f"--report-dir {report_dir}",
        f"--config {config_path}",
    ]
    if as_of:
        parts.append(f"--as-of {as_of}")
    if launch.selected_candidate:
        parts.append(f"--candidate {launch.selected_candidate}")
    if launch.run_id:
        parts.append(f"--run-id {launch.run_id}")
    return " ".join(parts)


def _completion_command(report_dir: Path, *, as_of: str | None) -> str:
    command = f"python examples/run_candidate_experiment_completion.py --report-dir {report_dir}"
    if as_of:
        command += f" --as-of {as_of}"
    return command


def _command_purpose(command: str) -> str:
    mapping = {
        "run_candidate_experiment_evidence.py": "Copy foundational evidence into the candidate experiment directory.",
        "run_candidate_walk_forward.py": "Run selected-candidate walk-forward validation.",
        "run_candidate_factor_diagnostics.py": "Run factor ablation and component-dependency diagnostics.",
        "run_candidate_regime_validation.py": "Validate selected-candidate behavior across market regimes.",
        "run_candidate_stress_matrix.py": "Run parameter, turnover, concentration, and cost stress scenarios.",
        "run_candidate_selection.py": "Score the selected candidate against the capital-goal feasibility screen.",
        "run_llm_review.py": "Generate deterministic review artifacts and optional advisory prompt/narrative.",
    }
    return next((purpose for script, purpose in mapping.items() if script in command), "Run a launch-plan research step.")


def _required_outputs(launch: CandidateExperimentLaunchPlan) -> list[str]:
    outputs = list(launch.required_outputs)
    experiment_dir = Path(launch.experiment_dir) if launch.experiment_dir else Path()
    stress_json = experiment_dir / "candidate_stress_matrix.json"
    stress_md = experiment_dir / "candidate_stress_matrix.md"
    stress_csv = experiment_dir / "candidate_stress_matrix.csv"
    for item in (stress_json, stress_md, stress_csv):
        text = str(item)
        if text and text not in outputs:
            outputs.append(text)
    return outputs


def _missing_evidence(required_outputs: list[str], blockers: list[str]) -> list[str]:
    if blockers:
        return list(blockers)
    return [
        f"pending_output: {path}"
        for path in required_outputs
        if path and not Path(path).exists()
    ]


def _capability_flags() -> dict[str, bool]:
    return {
        "can_enter_paper": False,
        "can_enter_live": False,
        "can_enter_micro_live_ready": False,
        "can_generate_broker_orders": False,
        "can_submit_real_orders": False,
        "can_execute_without_operator_opt_in": False,
    }


def _candidate_data_dependency(root: Path, candidate: str) -> str:
    queue = _read_json(root / "candidate_experiment_queue.json")
    for item in queue.get("experiments", []) or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("candidate") or "").strip() == candidate:
            return str(item.get("data_dependency") or "").strip()
    return ""


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "index",
        "phase",
        "execution_mode",
        "requires_explicit_operator_opt_in",
        "purpose",
        "command",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
