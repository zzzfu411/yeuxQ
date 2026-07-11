"""Launch plan for the next pre-registered candidate experiment.

The launch plan is a reproducibility bridge between readiness gates and the
actual research commands. It never proves profitability and never grants live
trading permission.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from quantify.research.candidate_experiment_queue import (
    CandidateExperiment,
    CandidateExperimentQueue,
)
from quantify.research.candidate_experiment_readiness import (
    CandidateExperimentReadiness,
    build_candidate_experiment_readiness_from_report,
)

LaunchDecision = Literal["PASS", "BLOCK"]

PROHIBITED_ACTIONS = [
    "Do not run launch commands while the launch decision is BLOCK.",
    "Do not treat an experiment launch plan as profitability evidence.",
    "Do not connect launched experiments to real broker order submission.",
    "Do not change the selected candidate, config, data cache, or output directory after launch without a new launch plan.",
    "Do not let LLM output override the deterministic launch decision.",
]


@dataclass(frozen=True, slots=True)
class CandidateExperimentLaunchEvidence:
    name: str
    status: str
    artifact: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "artifact": self.artifact,
        }


@dataclass(frozen=True, slots=True)
class CandidateExperimentLaunchPlan:
    decision: LaunchDecision
    as_of: str | None
    selected_candidate: str
    run_id: str
    report_dir: str
    experiment_dir: str
    config_path: str
    blocked_by: list[str]
    evidence: list[CandidateExperimentLaunchEvidence]
    command_sequence: list[str]
    required_outputs: list[str]
    success_criteria: list[str]
    falsification_tests: list[str]
    stop_conditions: list[str]
    capital_goal_fit_tests: list[str]
    minimum_evidence_window: dict[str, Any]
    risk_budget_checks: list[str]
    paper_entry_requirements: list[str]
    anti_overfit_controls: list[str]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "as_of": self.as_of,
            "selected_candidate": self.selected_candidate,
            "run_id": self.run_id,
            "report_dir": self.report_dir,
            "experiment_dir": self.experiment_dir,
            "config_path": self.config_path,
            "blocked_by": self.blocked_by,
            "evidence": [item.to_dict() for item in self.evidence],
            "command_sequence": self.command_sequence,
            "required_outputs": self.required_outputs,
            "success_criteria": self.success_criteria,
            "falsification_tests": self.falsification_tests,
            "stop_conditions": self.stop_conditions,
            "capital_goal_fit_tests": self.capital_goal_fit_tests,
            "minimum_evidence_window": self.minimum_evidence_window,
            "risk_budget_checks": self.risk_budget_checks,
            "paper_entry_requirements": self.paper_entry_requirements,
            "anti_overfit_controls": self.anti_overfit_controls,
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Candidate Experiment Launch: {self.decision}",
            "",
            f"- As of: `{self.as_of or 'unspecified'}`",
            f"- Selected candidate: `{self.selected_candidate or 'none'}`",
            f"- Run ID: `{self.run_id or 'none'}`",
            f"- Experiment directory: `{self.experiment_dir or 'none'}`",
            f"- Config: `{self.config_path}`",
            "",
            "This launch plan is a guarded research work order, not a trading instruction.",
            "",
            "## Evidence",
            "",
            "| item | status | artifact |",
            "| --- | --- | --- |",
        ]
        for item in self.evidence:
            lines.append(f"| `{item.name}` | `{item.status}` | `{item.artifact}` |")
        lines.extend(["", "## Blockers"])
        lines.extend(f"- {item}" for item in self.blocked_by) if self.blocked_by else lines.append("- None.")
        lines.extend(["", "## Command Sequence"])
        if self.command_sequence:
            lines.extend(f"- `{command}`" for command in self.command_sequence)
        else:
            lines.append("- None while launch is BLOCK.")
        lines.extend(["", "## Required Outputs"])
        lines.extend(f"- `{item}`" for item in self.required_outputs) if self.required_outputs else lines.append("- None.")
        lines.extend(["", "## Success Criteria"])
        lines.extend(f"- {item}" for item in self.success_criteria) if self.success_criteria else lines.append("- None.")
        lines.extend(["", "## Falsification Tests"])
        lines.extend(f"- {item}" for item in self.falsification_tests) if self.falsification_tests else lines.append("- None.")
        lines.extend(["", "## Stop Conditions"])
        lines.extend(f"- {item}" for item in self.stop_conditions) if self.stop_conditions else lines.append("- None.")
        lines.extend(["", "## Capital Goal Fit Tests"])
        lines.extend(f"- {item}" for item in self.capital_goal_fit_tests) if self.capital_goal_fit_tests else lines.append("- None.")
        lines.extend(["", "## Minimum Evidence Window"])
        if self.minimum_evidence_window:
            lines.extend(f"- `{key}`: {value}" for key, value in self.minimum_evidence_window.items())
        else:
            lines.append("- None.")
        lines.extend(["", "## Risk Budget Checks"])
        lines.extend(f"- {item}" for item in self.risk_budget_checks) if self.risk_budget_checks else lines.append("- None.")
        lines.extend(["", "## Paper Entry Requirements"])
        lines.extend(f"- {item}" for item in self.paper_entry_requirements) if self.paper_entry_requirements else lines.append("- None.")
        lines.extend(["", "## Anti-Overfit Controls"])
        lines.extend(f"- {item}" for item in self.anti_overfit_controls) if self.anti_overfit_controls else lines.append("- None.")
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_candidate_experiment_launch(
    queue: CandidateExperimentQueue,
    readiness: CandidateExperimentReadiness,
    *,
    report_dir: str | Path,
    config_path: str | Path = "config/research_recent.yaml",
    candidate: str | None = None,
    as_of: str | None = None,
    run_id: str | None = None,
) -> CandidateExperimentLaunchPlan:
    root = Path(report_dir)
    selected = _select_candidate(readiness, candidate)
    evidence = _evidence(root)
    blockers = list(readiness.blockers)
    if readiness.decision == "BLOCK":
        return _blocked_plan(
            report_dir=root,
            config_path=config_path,
            as_of=as_of or readiness.as_of,
            selected_candidate=candidate or "",
            evidence=evidence,
            blocked_by=blockers,
            next_actions=readiness.next_actions,
        )
    if not selected:
        return _blocked_plan(
            report_dir=root,
            config_path=config_path,
            as_of=as_of or readiness.as_of,
            selected_candidate=candidate or "",
            evidence=evidence,
            blocked_by=["No READY candidate experiment is available."],
            next_actions=["Rerun candidate experiment readiness after the queue and data gates pass."],
        )

    experiment = _experiment_by_candidate(queue, selected)
    if experiment is None:
        return _blocked_plan(
            report_dir=root,
            config_path=config_path,
            as_of=as_of or readiness.as_of,
            selected_candidate=selected,
            evidence=evidence,
            blocked_by=[f"Candidate `{selected}` is READY but missing from candidate_experiment_queue.json."],
            next_actions=["Regenerate candidate_experiment_queue.json and rerun the launch plan."],
        )

    resolved_run_id = run_id or _default_run_id(as_of or readiness.as_of, selected)
    experiment_dir = root / "candidate_experiments" / resolved_run_id
    commands = [
        _rewrite_command(
            command,
            report_dir=root,
            config_path=Path(config_path),
            experiment_dir=experiment_dir,
            candidate=selected,
        )
        for command in experiment.command_sequence
    ]
    return CandidateExperimentLaunchPlan(
        decision="PASS",
        as_of=as_of or readiness.as_of,
        selected_candidate=selected,
        run_id=resolved_run_id,
        report_dir=str(root),
        experiment_dir=str(experiment_dir),
        config_path=str(config_path),
        blocked_by=[],
        evidence=evidence,
        command_sequence=commands,
        required_outputs=[str(experiment_dir / artifact) for artifact in experiment.artifacts],
        success_criteria=experiment.success_criteria,
        falsification_tests=experiment.falsification_tests,
        stop_conditions=experiment.stop_conditions,
        capital_goal_fit_tests=experiment.capital_goal_fit_tests,
        minimum_evidence_window=experiment.minimum_evidence_window,
        risk_budget_checks=experiment.risk_budget_checks,
        paper_entry_requirements=experiment.paper_entry_requirements,
        anti_overfit_controls=experiment.anti_overfit_controls,
        next_actions=[
            "Run the command sequence in order and keep every output under the experiment directory.",
            "After outputs exist, rerun weekly review and LLM advisory review without changing the deterministic gate.",
            "Keep the strategy in research or paper stage until paper stability and human approval gates pass.",
        ],
        prohibited_actions=PROHIBITED_ACTIONS,
    )


def build_candidate_experiment_launch_from_report(
    report_dir: str | Path,
    *,
    config_path: str | Path = "config/research_recent.yaml",
    candidate: str | None = None,
    as_of: str | None = None,
    run_id: str | None = None,
) -> CandidateExperimentLaunchPlan:
    root = Path(report_dir)
    queue = _queue_from_payload(_read_json(root / "candidate_experiment_queue.json"))
    readiness = build_candidate_experiment_readiness_from_report(root, as_of=as_of)
    return build_candidate_experiment_launch(
        queue,
        readiness,
        report_dir=root,
        config_path=config_path,
        candidate=candidate,
        as_of=as_of,
        run_id=run_id,
    )


def write_candidate_experiment_launch(
    plan: CandidateExperimentLaunchPlan,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "candidate_experiment_launch.json").write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "candidate_experiment_launch.md").write_text(plan.to_markdown(), encoding="utf-8")
    return root


def _blocked_plan(
    *,
    report_dir: Path,
    config_path: str | Path,
    as_of: str | None,
    selected_candidate: str,
    evidence: list[CandidateExperimentLaunchEvidence],
    blocked_by: list[str],
    next_actions: list[str],
) -> CandidateExperimentLaunchPlan:
    return CandidateExperimentLaunchPlan(
        decision="BLOCK",
        as_of=as_of,
        selected_candidate=selected_candidate,
        run_id="",
        report_dir=str(report_dir),
        experiment_dir="",
        config_path=str(config_path),
        blocked_by=blocked_by,
        evidence=evidence,
        command_sequence=[],
        required_outputs=[],
        success_criteria=[],
        falsification_tests=[],
        stop_conditions=[],
        capital_goal_fit_tests=[],
        minimum_evidence_window={},
        risk_budget_checks=[],
        paper_entry_requirements=[],
        anti_overfit_controls=[],
        next_actions=next_actions,
        prohibited_actions=PROHIBITED_ACTIONS,
    )


def _select_candidate(readiness: CandidateExperimentReadiness, candidate: str | None) -> str:
    ready_items = sorted(
        (item for item in readiness.items if item.status == "READY"),
        key=lambda item: item.priority,
    )
    if candidate:
        return candidate if any(item.candidate == candidate for item in ready_items) else ""
    return ready_items[0].candidate if ready_items else ""


def _experiment_by_candidate(
    queue: CandidateExperimentQueue,
    candidate: str,
) -> CandidateExperiment | None:
    return next((item for item in queue.experiments if item.candidate == candidate), None)


def _default_run_id(as_of: str | None, candidate: str) -> str:
    date = re.sub(r"[^0-9]", "", as_of or "") or "unspecified"
    return f"{date}_{_slug(candidate)}"


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text.strip().lower()).strip("_")
    return slug or "candidate"


def _rewrite_command(
    command: str,
    *,
    report_dir: Path,
    config_path: Path,
    experiment_dir: Path,
    candidate: str,
) -> str:
    paper_dir = experiment_dir / "paper"
    rewritten = command.replace("config/research_recent.yaml", str(config_path))
    rewritten = rewritten.replace("results/research/<timestamp>", str(experiment_dir))
    rewritten = rewritten.replace("--source-report-dir results/research", f"--source-report-dir {report_dir}")
    rewritten = rewritten.replace(f"results/paper/{candidate}", str(paper_dir))
    rewritten = _with_gate_report_dir(rewritten, report_dir)
    return _with_candidate_filter(rewritten, candidate)


def _with_gate_report_dir(command: str, report_dir: Path) -> str:
    gated_scripts = {
        "run_candidate_walk_forward.py",
        "run_candidate_factor_diagnostics.py",
        "run_candidate_regime_validation.py",
        "run_candidate_stress_matrix.py",
        "run_candidate_selection.py",
    }
    if not any(script in command for script in gated_scripts):
        return command
    if " --gate-report-dir " in command:
        return command
    return f"{command} --gate-report-dir {report_dir}"


def _with_candidate_filter(command: str, candidate: str) -> str:
    filterable = {
        "run_candidate_walk_forward.py",
        "run_candidate_regime_validation.py",
        "run_candidate_selection.py",
    }
    if not any(script in command for script in filterable):
        return command
    if " --candidate " in command:
        return command
    return f"{command} --candidate {candidate}"


def _evidence(root: Path) -> list[CandidateExperimentLaunchEvidence]:
    artifacts = [
        ("first_million_pipeline", root / "first_million_pipeline.json"),
        ("candidate_experiment_queue", root / "candidate_experiment_queue.json"),
        (
            "candidate_experiment_design_matrix",
            root / "candidate_experiment_design_matrix.json",
        ),
        ("candidate_experiment_readiness", root / "candidate_experiment_readiness.json"),
        ("data_gap_action_plan", root / "data_gap_action_plan.json"),
        ("source_qa_preflight", root / "source_qa" / "source_qa_preflight.json"),
        ("data_source_qa_review", root / "source_qa" / "data_source_qa_review.json"),
        ("offline_data_intake", root / "offline_intake" / "offline_data_intake.json"),
        ("capital_goal_status", root / "goal" / "capital_goal_status.json"),
    ]
    return [
        CandidateExperimentLaunchEvidence(name, _artifact_status(path), str(path))
        for name, path in artifacts
    ]


def _artifact_status(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    payload = _read_json(path)
    for key in ("decision", "status", "weekly_decision"):
        value = payload.get(key)
        if value:
            return str(value)
    return "PRESENT"


def _queue_from_payload(payload: dict[str, Any]) -> CandidateExperimentQueue:
    experiments = [
        CandidateExperiment(
            priority=int(item.get("priority", 99)),
            candidate=str(item.get("candidate", "")),
            data_dependency=str(item.get("data_dependency", "unknown")),
            intended_regimes=[str(value) for value in item.get("intended_regimes", []) or []],
            objective=str(item.get("objective", "")),
            rationale=str(item.get("rationale", "")),
            required_inputs=[str(value) for value in item.get("required_inputs", []) or []],
            command_sequence=[str(value) for value in item.get("command_sequence", []) or []],
            success_criteria=[str(value) for value in item.get("success_criteria", []) or []],
            falsification_tests=[str(value) for value in item.get("falsification_tests", []) or []],
            stop_conditions=[str(value) for value in item.get("stop_conditions", []) or []],
            artifacts=[str(value) for value in item.get("artifacts", []) or []],
            prohibited_actions=[str(value) for value in item.get("prohibited_actions", []) or []],
            capital_goal_fit_tests=[
                str(value) for value in item.get("capital_goal_fit_tests", []) or []
            ],
            minimum_evidence_window=_dict_payload(item.get("minimum_evidence_window")),
            risk_budget_checks=[str(value) for value in item.get("risk_budget_checks", []) or []],
            paper_entry_requirements=[
                str(value) for value in item.get("paper_entry_requirements", []) or []
            ],
            anti_overfit_controls=[str(value) for value in item.get("anti_overfit_controls", []) or []],
        )
        for item in payload.get("experiments", []) or []
        if isinstance(item, dict)
    ]
    return CandidateExperimentQueue(
        status=str(payload.get("status", "UNKNOWN")),
        as_of=str(payload.get("as_of") or "") or None,
        experiment_count=len(experiments),
        experiments=experiments,
        required_evidence_before_running=[
            str(value) for value in payload.get("required_evidence_before_running", []) or []
        ],
        prohibited_actions=[str(value) for value in payload.get("prohibited_actions", []) or []],
    )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _dict_payload(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
