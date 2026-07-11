"""Guarded executor for a candidate experiment launch plan.

The executor is intentionally narrow: it only runs command lines emitted by a
PASS candidate_experiment_launch.json, captures logs, and never connects to a
broker or upgrades deterministic decisions.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any, Callable, Literal

FOUNDATIONAL_EVIDENCE: tuple[tuple[str, str, str | None], ...] = (
    ("summary", "summary.json", None),
    ("run_manifest", "run_manifest.json", None),
    ("real_data_bootstrap", "real_data_bootstrap.json", "decision"),
    ("real_data_gate", "real_data_gate.json", "decision"),
    ("data_audit", "data_audit.json", "status"),
    ("robustness", "robustness_report.json", "status"),
    ("walk_forward", "walk_forward_report.json", "status"),
)

ExecutionDecision = Literal["PASS", "BLOCK", "DRY_RUN"]
StepStatus = Literal["PASS", "BLOCK", "SKIPPED"]

ALLOWED_EXAMPLE_COMMANDS = {
    "run_candidate_experiment_evidence.py",
    "run_candidate_walk_forward.py",
    "run_candidate_factor_diagnostics.py",
    "run_candidate_regime_validation.py",
    "run_candidate_stress_matrix.py",
    "run_candidate_selection.py",
    "run_llm_review.py",
    "run_paper_candidate_plan.py",
}

PROHIBITED_ACTIONS = [
    "Do not execute a candidate experiment while the launch decision is BLOCK.",
    "Do not execute command lines that are not emitted by candidate_experiment_launch.json.",
    "Do not run commands outside the research/paper evidence whitelist.",
    "Do not connect candidate experiment execution to real broker order submission.",
    "Do not treat execution PASS as profitability, paper promotion, or micro-live readiness.",
]


@dataclass(frozen=True, slots=True)
class CandidateExperimentExecutionStep:
    index: int
    command: str
    status: StepStatus
    returncode: int | None
    stdout_log: str
    stderr_log: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "command": self.command,
            "status": self.status,
            "returncode": self.returncode,
            "stdout_log": self.stdout_log,
            "stderr_log": self.stderr_log,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class CandidateExperimentExecutionReport:
    decision: ExecutionDecision
    launch_path: str
    report_dir: str
    experiment_dir: str
    selected_candidate: str
    run_id: str
    dry_run: bool
    steps: list[CandidateExperimentExecutionStep]
    blockers: list[str]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "launch_path": self.launch_path,
            "report_dir": self.report_dir,
            "experiment_dir": self.experiment_dir,
            "selected_candidate": self.selected_candidate,
            "run_id": self.run_id,
            "dry_run": self.dry_run,
            "steps": [step.to_dict() for step in self.steps],
            "blockers": self.blockers,
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Candidate Experiment Execution: {self.decision}",
            "",
            f"- Launch path: `{self.launch_path}`",
            f"- Report directory: `{self.report_dir}`",
            f"- Experiment directory: `{self.experiment_dir or 'none'}`",
            f"- Candidate: `{self.selected_candidate or 'none'}`",
            f"- Run ID: `{self.run_id or 'none'}`",
            f"- Dry run: `{self.dry_run}`",
            "",
            "This is a guarded research executor, not a trading instruction or profitability claim.",
            "",
            "## Steps",
            "",
            "| # | status | returncode | stdout | stderr | message |",
            "| ---: | --- | ---: | --- | --- | --- |",
        ]
        for step in self.steps:
            code = "" if step.returncode is None else str(step.returncode)
            lines.append(
                f"| {step.index} | `{step.status}` | {code} | `{step.stdout_log or '-'}` | "
                f"`{step.stderr_log or '-'}` | {step.message} |"
            )
        lines.extend(["", "## Blockers"])
        lines.extend(f"- {item}" for item in self.blockers) if self.blockers else lines.append("- None.")
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


Runner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]


def run_candidate_experiment_execution(
    report_dir: str | Path,
    *,
    launch_path: str | Path | None = None,
    dry_run: bool = False,
    runner: Runner | None = None,
) -> CandidateExperimentExecutionReport:
    root = Path(report_dir)
    launch_file = Path(launch_path) if launch_path else root / "candidate_experiment_launch.json"
    launch = _read_json(launch_file)
    if not launch:
        return _report(
            decision="BLOCK",
            launch_path=launch_file,
            report_dir=root,
            experiment_dir=Path(),
            selected_candidate="",
            run_id="",
            dry_run=dry_run,
            steps=[],
            blockers=[f"{launch_file} is missing or unreadable."],
        )
    launch_decision = str(launch.get("decision", "UNKNOWN")).upper()
    experiment_dir = Path(str(launch.get("experiment_dir") or ""))
    if launch_decision != "PASS":
        return _report(
            decision="BLOCK",
            launch_path=launch_file,
            report_dir=root,
            experiment_dir=experiment_dir,
            selected_candidate=str(launch.get("selected_candidate") or ""),
            run_id=str(launch.get("run_id") or ""),
            dry_run=dry_run,
            steps=[],
            blockers=[f"Launch decision is {launch_decision}; execution requires PASS."],
        )

    raw_commands = [str(command) for command in launch.get("command_sequence", []) or []]
    if not raw_commands:
        return _report(
            decision="BLOCK",
            launch_path=launch_file,
            report_dir=root,
            experiment_dir=experiment_dir,
            selected_candidate=str(launch.get("selected_candidate") or ""),
            run_id=str(launch.get("run_id") or ""),
            dry_run=dry_run,
            steps=[],
            blockers=["Launch plan has no command_sequence."],
        )
    if not str(experiment_dir):
        return _report(
            decision="BLOCK",
            launch_path=launch_file,
            report_dir=root,
            experiment_dir=experiment_dir,
            selected_candidate=str(launch.get("selected_candidate") or ""),
            run_id=str(launch.get("run_id") or ""),
            dry_run=dry_run,
            steps=[],
            blockers=["Launch plan has empty experiment_dir."],
        )

    logs_dir = experiment_dir / "execution_logs"
    if not dry_run:
        logs_dir.mkdir(parents=True, exist_ok=True)
    steps: list[CandidateExperimentExecutionStep] = []
    for index, command in enumerate(raw_commands, start=1):
        validation = _validated_args(command)
        stdout_log = logs_dir / f"{index:02d}_stdout.log"
        stderr_log = logs_dir / f"{index:02d}_stderr.log"
        if isinstance(validation, str):
            steps.append(
                CandidateExperimentExecutionStep(
                    index,
                    command,
                    "BLOCK",
                    None,
                    str(stdout_log),
                    str(stderr_log),
                    validation,
                )
            )
            break
        launch_scope_blocker = _launch_scope_blocker(validation, report_dir=root, experiment_dir=experiment_dir)
        if launch_scope_blocker:
            steps.append(
                CandidateExperimentExecutionStep(
                    index,
                    command,
                    "BLOCK",
                    None,
                    str(stdout_log),
                    str(stderr_log),
                    launch_scope_blocker,
                )
            )
            break
        if not dry_run:
            preflight_blocker = _pre_execution_blocker(validation, root)
            if preflight_blocker:
                steps.append(
                    CandidateExperimentExecutionStep(
                        index,
                        command,
                        "BLOCK",
                        None,
                        str(stdout_log),
                        str(stderr_log),
                        preflight_blocker,
                    )
                )
                break
        if dry_run:
            steps.append(
                CandidateExperimentExecutionStep(
                    index,
                    command,
                    "SKIPPED",
                    None,
                    str(stdout_log),
                    str(stderr_log),
                    "Dry run: command validated but was not executed.",
                )
            )
            continue
        completed = (runner or _subprocess_runner)(validation, root)
        stdout_log.write_text(completed.stdout or "", encoding="utf-8")
        stderr_log.write_text(completed.stderr or "", encoding="utf-8")
        status: StepStatus = "PASS" if completed.returncode == 0 else "BLOCK"
        steps.append(
            CandidateExperimentExecutionStep(
                index,
                command,
                status,
                completed.returncode,
                str(stdout_log),
                str(stderr_log),
                "Command completed." if status == "PASS" else "Command failed; execution stopped.",
            )
        )
        if status == "BLOCK":
            break

    return _report(
        decision=_decision(steps, dry_run=dry_run),
        launch_path=launch_file,
        report_dir=root,
        experiment_dir=experiment_dir,
        selected_candidate=str(launch.get("selected_candidate") or ""),
        run_id=str(launch.get("run_id") or ""),
        dry_run=dry_run,
        steps=steps,
        blockers=_blockers(steps),
    )


def write_candidate_experiment_execution(
    report: CandidateExperimentExecutionReport,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "candidate_experiment_execution.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "candidate_experiment_execution.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _validated_args(command: str) -> list[str] | str:
    try:
        parts = shlex.split(command, posix=False)
    except ValueError as exc:
        return f"Command cannot be parsed: {exc}"
    if len(parts) < 2:
        return "Command is too short."
    if Path(parts[0]).name.lower() not in {"python", "python.exe"}:
        return "Only python example commands are allowed."
    script = Path(parts[1])
    if script.parent.as_posix().replace("\\", "/") != "examples":
        return "Only scripts under examples/ are allowed."
    if script.name not in ALLOWED_EXAMPLE_COMMANDS:
        return f"{script.name} is not in the candidate experiment execution whitelist."
    if script.name.startswith("run_candidate_") and script.name not in {
        "run_candidate_experiment_evidence.py",
        "run_candidate_experiment_launch.py",
    }:
        if "--gate-report-dir" not in parts:
            return "Candidate research commands must include --gate-report-dir."
    if any(_forbidden_token(part) for part in parts):
        return "Command contains a forbidden live-trading or broker token."
    return [sys.executable, *parts[1:]]


def _launch_scope_blocker(args: list[str], *, report_dir: Path, experiment_dir: Path) -> str:
    script = Path(args[1]).name if len(args) > 1 else ""
    output_options = {
        "run_candidate_experiment_evidence.py": ["--output-dir"],
        "run_candidate_walk_forward.py": ["--output-dir"],
        "run_candidate_factor_diagnostics.py": ["--output-dir"],
        "run_candidate_regime_validation.py": ["--output-dir"],
        "run_candidate_stress_matrix.py": ["--output-dir"],
        "run_candidate_selection.py": ["--output-dir"],
        "run_llm_review.py": ["--report-dir"],
        "run_paper_candidate_plan.py": ["--report-dir", "--paper-state-dir"],
    }.get(script, [])
    for option in output_options:
        path = _option_path(args, option, cwd=report_dir)
        if path is None:
            return f"{script} must include {option} from the launch plan."
        if not _path_within(path, experiment_dir):
            return (
                f"{script} {option} must stay under launch experiment_dir: "
                f"requested={path}, experiment_dir={experiment_dir}."
            )

    source_dir = _option_path(args, "--source-report-dir", cwd=report_dir)
    if source_dir is not None and not _same_path(source_dir, report_dir):
        return (
            "Candidate experiment evidence must use the launch report_dir as --source-report-dir: "
            f"requested={source_dir}, report_dir={report_dir}."
        )
    gate_dir = _option_path(args, "--gate-report-dir", cwd=report_dir)
    if gate_dir is not None and not _same_path(gate_dir, report_dir):
        return (
            "Candidate research commands must use the launch report_dir as --gate-report-dir: "
            f"requested={gate_dir}, report_dir={report_dir}."
        )
    return ""


def _pre_execution_blocker(args: list[str], cwd: Path) -> str:
    script = Path(args[1]).name if len(args) > 1 else ""
    if script != "run_candidate_experiment_evidence.py":
        return ""
    source_dir = _option_path(args, "--source-report-dir", cwd=cwd)
    if source_dir is None:
        return "Candidate experiment evidence command must include --source-report-dir."
    blockers = _foundational_evidence_blockers(source_dir)
    if not blockers:
        return ""
    return (
        "Foundational evidence preflight failed before execution: "
        + "; ".join(blockers[:5])
        + ("." if len(blockers) <= 5 else f"; and {len(blockers) - 5} more.")
    )


def _option_path(args: list[str], option: str, *, cwd: Path) -> Path | None:
    try:
        index = args.index(option)
    except ValueError:
        return None
    if index + 1 >= len(args):
        return None
    path = Path(args[index + 1])
    return path if path.is_absolute() else cwd / path


def _path_within(path: Path, parent: Path) -> bool:
    resolved_path = _resolved(path)
    resolved_parent = _resolved(parent)
    return resolved_path == resolved_parent or resolved_parent in resolved_path.parents


def _same_path(left: Path, right: Path) -> bool:
    return _resolved(left) == _resolved(right)


def _resolved(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except OSError:
        return path.absolute()


def _foundational_evidence_blockers(source_dir: Path) -> list[str]:
    source_dirs = [source_dir, source_dir / "weekly"]
    blockers: list[str] = []
    for name, filename, status_key in FOUNDATIONAL_EVIDENCE:
        path = _find_source(filename, source_dirs)
        if path is None:
            blockers.append(f"{name} missing ({filename})")
            continue
        payload = _read_json(path)
        if not payload:
            blockers.append(f"{name} unreadable ({path})")
            continue
        status = _artifact_status(name, payload, status_key=status_key)
        if status != "PASS":
            blockers.append(f"{name} is {status} ({path})")
    return blockers


def _find_source(filename: str, source_dirs: list[Path]) -> Path | None:
    return next((root / filename for root in source_dirs if (root / filename).exists()), None)


def _artifact_status(name: str, payload: dict[str, Any], *, status_key: str | None) -> str:
    if name == "summary":
        assumptions = payload.get("assumptions", {})
        if isinstance(assumptions, dict) and assumptions.get("demo_data_used") is True:
            return "BLOCK"
        return "PASS"
    if name == "run_manifest":
        return "BLOCK" if payload.get("demo_data_used") is True else "PASS"
    if status_key is None:
        return "PASS"
    status = str(payload.get(status_key, "UNKNOWN") or "UNKNOWN").upper()
    if status in {"PASS", "WATCH", "BLOCK"}:
        return status
    return "BLOCK"


def _forbidden_token(token: str) -> bool:
    normalized = token.lower().replace("-", "_")
    forbidden = {"broker", "live", "micro_live", "order_submit", "real_order"}
    if "run_llm_review.py" in normalized:
        return False
    return any(value in normalized for value in forbidden)


def _subprocess_runner(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def _report(
    *,
    decision: ExecutionDecision,
    launch_path: Path,
    report_dir: Path,
    experiment_dir: Path,
    selected_candidate: str,
    run_id: str,
    dry_run: bool,
    steps: list[CandidateExperimentExecutionStep],
    blockers: list[str],
) -> CandidateExperimentExecutionReport:
    return CandidateExperimentExecutionReport(
        decision=decision,
        launch_path=str(launch_path),
        report_dir=str(report_dir),
        experiment_dir=str(experiment_dir) if str(experiment_dir) != "." else "",
        selected_candidate=selected_candidate,
        run_id=run_id,
        dry_run=dry_run,
        steps=steps,
        blockers=blockers,
        next_actions=_next_actions(decision),
        prohibited_actions=PROHIBITED_ACTIONS,
    )


def _decision(
    steps: list[CandidateExperimentExecutionStep],
    *,
    dry_run: bool,
) -> ExecutionDecision:
    if any(step.status == "BLOCK" for step in steps) or not steps:
        return "BLOCK"
    if dry_run:
        return "DRY_RUN"
    return "PASS"


def _blockers(steps: list[CandidateExperimentExecutionStep]) -> list[str]:
    return [
        f"step {step.index}: {step.message}"
        for step in steps
        if step.status == "BLOCK"
    ]


def _next_actions(decision: ExecutionDecision) -> list[str]:
    if decision == "PASS":
        return [
            "Run candidate_experiment_completion to verify required artifacts.",
            "Keep the experiment in research-only mode until completion and later gates pass.",
        ]
    if decision == "DRY_RUN":
        return [
            "Review validated commands, then rerun without --dry-run when ready.",
            "Do not infer any research result from dry-run execution.",
        ]
    return [
        "Fix launch or execution blockers before rerunning the executor.",
        "Do not continue to completion review while execution is BLOCK.",
    ]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
