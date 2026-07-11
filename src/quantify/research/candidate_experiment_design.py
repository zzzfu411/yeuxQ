"""Pre-registered experiment design matrix for strategy candidates.

The design matrix makes the anti-overfit test plan explicit before real-data
results are available. It does not run research, rank candidates, approve paper
trading, or generate broker instructions.
"""
from __future__ import annotations

from dataclasses import dataclass
import csv
import json
from pathlib import Path
from typing import Any

from quantify.research.candidate_experiment_queue import (
    CandidateExperimentQueue,
    build_candidate_experiment_queue,
)
from quantify.research.candidate_stress_matrix import default_candidate_stress_scenarios
from quantify.research.candidates import CandidateSpec, default_candidate_specs


DESIGN_STATUS = "WAITING_FOR_REAL_DATA"
REQUIRED_BEFORE_EXECUTION = [
    "first_million_pipeline decision is not BLOCK.",
    "Source QA answers and retained evidence manifest pass deterministic review.",
    "Guarded offline intake and run manifest prove recent non-template A-share daily data.",
    "candidate_experiment_readiness has at least one READY candidate.",
    "candidate_experiment_run_packet allows an explicit research-only command bundle.",
]
COMMON_REQUIRED_OUTPUTS = [
    "candidate_walk_forward_report.json",
    "candidate_factor_diagnostics.json",
    "candidate_regime_validation_report.json",
    "candidate_stress_matrix.json",
    "candidate_selection.json",
    "llm_review.json",
]
COMMON_PROHIBITED_ACTIONS = [
    "Do not treat this design matrix as a strategy ranking or profit claim.",
    "Do not run a scenario while candidate readiness or launch gates are BLOCK.",
    "Do not change scenario coverage after seeing attractive backtest results without recording a new design matrix.",
    "Do not connect any command here to real broker order submission.",
    "Do not let LLM output modify scenario requirements, deterministic gates, or human approval requirements.",
]


@dataclass(frozen=True, slots=True)
class CandidateExperimentDesignRow:
    priority: int
    candidate: str
    scenario: str
    scenario_family: str
    data_dependency: str
    n_holdings: int
    max_weight: float
    rebalance: str
    cost_multiplier: float
    trend_filter: bool
    trend_scale: float
    trend_gate: str
    hold_rank_buffer: int
    min_trade_weight: float
    max_new_positions: int
    score_smoothing_observations: int
    score_smoothing_step_days: int
    required_outputs: list[str]
    pass_conditions: list[str]
    falsification_role: str
    command_hint: str
    allowed_stage: str = "research"
    status: str = "PLANNED"
    can_enter_paper: bool = False
    can_generate_broker_orders: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "priority": self.priority,
            "candidate": self.candidate,
            "scenario": self.scenario,
            "scenario_family": self.scenario_family,
            "data_dependency": self.data_dependency,
            "n_holdings": self.n_holdings,
            "max_weight": self.max_weight,
            "rebalance": self.rebalance,
            "cost_multiplier": self.cost_multiplier,
            "trend_filter": self.trend_filter,
            "trend_scale": self.trend_scale,
            "trend_gate": self.trend_gate,
            "hold_rank_buffer": self.hold_rank_buffer,
            "min_trade_weight": self.min_trade_weight,
            "max_new_positions": self.max_new_positions,
            "score_smoothing_observations": self.score_smoothing_observations,
            "score_smoothing_step_days": self.score_smoothing_step_days,
            "required_outputs": self.required_outputs,
            "pass_conditions": self.pass_conditions,
            "falsification_role": self.falsification_role,
            "command_hint": self.command_hint,
            "allowed_stage": self.allowed_stage,
            "status": self.status,
            "can_enter_paper": self.can_enter_paper,
            "can_generate_broker_orders": self.can_generate_broker_orders,
        }


@dataclass(frozen=True, slots=True)
class CandidateExperimentDesignMatrix:
    status: str
    as_of: str | None
    candidate_count: int
    scenario_count: int
    candidates: list[str]
    required_before_execution: list[str]
    rows: list[CandidateExperimentDesignRow]
    command_sequence: list[str]
    prohibited_actions: list[str]
    can_run_research: bool = False
    can_enter_paper: bool = False
    can_generate_broker_orders: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": "candidate_experiment_design_matrix",
            "status": self.status,
            "as_of": self.as_of,
            "candidate_count": self.candidate_count,
            "scenario_count": self.scenario_count,
            "candidates": self.candidates,
            "required_before_execution": self.required_before_execution,
            "rows": [row.to_dict() for row in self.rows],
            "command_sequence": self.command_sequence,
            "prohibited_actions": self.prohibited_actions,
            "can_run_research": self.can_run_research,
            "can_enter_paper": self.can_enter_paper,
            "can_generate_broker_orders": self.can_generate_broker_orders,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Candidate Experiment Design Matrix: {self.status}",
            "",
            f"- As of: `{self.as_of or 'unspecified'}`",
            f"- Candidates: {self.candidate_count}",
            f"- Scenarios: {self.scenario_count}",
            f"- Can run research: `{self.can_run_research}`",
            "",
            "This matrix pre-registers scenario coverage before results are available. It is not a strategy ranking, paper approval, or broker workflow.",
            "",
            "## Required Before Execution",
        ]
        lines.extend(f"- {item}" for item in self.required_before_execution)
        lines.extend(
            [
                "",
                "## Scenario Matrix",
                "",
                "| priority | candidate | scenario | family | holdings | max_weight | rebalance | cost | trend | command |",
                "| ---: | --- | --- | --- | ---: | ---: | --- | ---: | --- | --- |",
            ]
        )
        for row in self.rows:
            lines.append(
                "| {priority} | `{candidate}` | `{scenario}` | `{family}` | {holdings} | {weight:.2%} | `{rebalance}` | {cost:.2f} | `{trend}` | `{command}` |".format(
                    priority=row.priority,
                    candidate=row.candidate,
                    scenario=row.scenario,
                    family=row.scenario_family,
                    holdings=row.n_holdings,
                    weight=row.max_weight,
                    rebalance=row.rebalance,
                    cost=row.cost_multiplier,
                    trend=row.trend_filter,
                    command=row.command_hint,
                )
            )
        lines.extend(["", "## Command Sequence"])
        for index, command in enumerate(self.command_sequence, start=1):
            lines.extend(["", f"{index}.", "", "```powershell", command, "```"])
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_candidate_experiment_design_matrix(
    cfg,
    *,
    as_of: str | None = None,
    queue: CandidateExperimentQueue | None = None,
) -> CandidateExperimentDesignMatrix:
    experiment_queue = queue or build_candidate_experiment_queue(cfg, as_of=as_of)
    specs = _specs_by_name(cfg)
    rows: list[CandidateExperimentDesignRow] = []
    for experiment in experiment_queue.experiments:
        spec = specs.get(experiment.candidate)
        if spec is None:
            rows.append(_bespoke_row(experiment.priority, experiment.candidate))
            continue
        scenarios = default_candidate_stress_scenarios(spec)
        for scenario in scenarios:
            rows.append(
                CandidateExperimentDesignRow(
                    priority=experiment.priority,
                    candidate=experiment.candidate,
                    scenario=scenario.name,
                    scenario_family=_scenario_family(scenario.name),
                    data_dependency=experiment.data_dependency,
                    n_holdings=scenario.n_holdings,
                    max_weight=scenario.max_weight,
                    rebalance=scenario.rebalance,
                    cost_multiplier=scenario.cost_multiplier,
                    trend_filter=scenario.trend_filter,
                    trend_scale=scenario.trend_scale,
                    trend_gate=scenario.trend_gate,
                    hold_rank_buffer=scenario.hold_rank_buffer,
                    min_trade_weight=scenario.min_trade_weight,
                    max_new_positions=scenario.max_new_positions,
                    score_smoothing_observations=scenario.score_smoothing_observations,
                    score_smoothing_step_days=scenario.score_smoothing_step_days,
                    required_outputs=list(COMMON_REQUIRED_OUTPUTS),
                    pass_conditions=_pass_conditions(scenario.name),
                    falsification_role=_falsification_role(scenario.name),
                    command_hint=_scenario_command(experiment.candidate, scenario.name),
                )
            )
    candidates = list(dict.fromkeys(row.candidate for row in rows))
    return CandidateExperimentDesignMatrix(
        status=DESIGN_STATUS,
        as_of=as_of,
        candidate_count=len(candidates),
        scenario_count=len(rows),
        candidates=candidates,
        required_before_execution=list(REQUIRED_BEFORE_EXECUTION),
        rows=rows,
        command_sequence=_command_sequence(candidates),
        prohibited_actions=list(COMMON_PROHIBITED_ACTIONS),
    )


def write_candidate_experiment_design_matrix(
    matrix: CandidateExperimentDesignMatrix,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "candidate_experiment_design_matrix.json").write_text(
        json.dumps(matrix.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "candidate_experiment_design_matrix.md").write_text(
        matrix.to_markdown(),
        encoding="utf-8",
    )
    with (root / "candidate_experiment_design_matrix.csv").open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        fieldnames = [
            "priority",
            "candidate",
            "scenario",
            "scenario_family",
            "data_dependency",
            "n_holdings",
            "max_weight",
            "rebalance",
            "cost_multiplier",
            "trend_filter",
            "trend_scale",
            "trend_gate",
            "hold_rank_buffer",
            "min_trade_weight",
            "max_new_positions",
            "score_smoothing_observations",
            "score_smoothing_step_days",
            "required_outputs",
            "pass_conditions",
            "falsification_role",
            "command_hint",
            "allowed_stage",
            "status",
            "can_enter_paper",
            "can_generate_broker_orders",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in matrix.rows:
            payload = row.to_dict()
            payload["required_outputs"] = "; ".join(row.required_outputs)
            payload["pass_conditions"] = "; ".join(row.pass_conditions)
            writer.writerow(payload)
    return root


def _specs_by_name(cfg) -> dict[str, CandidateSpec]:
    return {spec.name: spec for spec in default_candidate_specs(cfg)}


def _bespoke_row(priority: int, candidate: str) -> CandidateExperimentDesignRow:
    return CandidateExperimentDesignRow(
        priority=priority,
        candidate=candidate,
        scenario="bespoke_plan_required",
        scenario_family="bespoke_review",
        data_dependency="unknown",
        n_holdings=0,
        max_weight=0.0,
        rebalance="unknown",
        cost_multiplier=1.0,
        trend_filter=False,
        trend_scale=0.0,
        trend_gate="unknown",
        hold_rank_buffer=0,
        min_trade_weight=0.0,
        max_new_positions=0,
        score_smoothing_observations=0,
        score_smoothing_step_days=0,
        required_outputs=list(COMMON_REQUIRED_OUTPUTS),
        pass_conditions=["Write and approve a bespoke scenario design before running this candidate."],
        falsification_role="Unknown candidate cannot be compared until its falsification tests are reviewed.",
        command_hint=(
            "python examples/write_candidate_experiment_queue.py --config config/research_recent.yaml "
            "--output-dir results/first_million"
        ),
    )


def _scenario_family(name: str) -> str:
    if name == "baseline":
        return "baseline"
    if name in {"wider_basket", "lower_concentration"}:
        return "concentration"
    if name == "rebalance_alt":
        return "rebalance"
    if name in {"turnover_control", "stability_control", "score_smoothing"}:
        return "turnover_stability"
    if name == "high_cost":
        return "cost_stress"
    if name.startswith("trend_filter"):
        return "trend_filter_ablation"
    return "custom"


def _pass_conditions(name: str) -> list[str]:
    common = [
        "Scenario has no BLOCK finding in candidate_stress_matrix.json.",
        "Walk-forward, factor diagnostics, and regime validation remain non-BLOCK.",
        "Capital-goal return margin, drawdown, turnover, and reject-rate evidence are retained.",
    ]
    if name == "baseline":
        return [*common, "Baseline is not enough for ranking unless required stress scenarios also pass."]
    if name == "high_cost":
        return [*common, "Higher cost assumptions do not turn the candidate into BLOCK."]
    if name in {"wider_basket", "lower_concentration"}:
        return [*common, "Diversification changes do not destroy return margin or increase reject risk."]
    if name == "rebalance_alt":
        return [*common, "Alternative rebalance cadence does not expose a one-cadence accident."]
    if name in {"turnover_control", "stability_control", "score_smoothing"}:
        return [*common, "Turnover reduction is meaningful and does not raise stale-position drawdown."]
    if name.startswith("trend_filter"):
        return [*common, "Cash drag and missed-rebound cost are explicitly measured."]
    return common


def _falsification_role(name: str) -> str:
    roles = {
        "baseline": "Reference run; cannot be used alone for formal ranking.",
        "wider_basket": "Tests whether signal survives a broader basket.",
        "lower_concentration": "Tests whether concentration drives return or drawdown.",
        "rebalance_alt": "Tests whether the result is dependent on one rebalance cadence.",
        "turnover_control": "Tests whether lower turnover can be achieved without harming exits.",
        "stability_control": "Tests stronger holding and trade-size controls for stale-position risk.",
        "score_smoothing": "Tests whether score smoothing reduces noise or merely delays exits.",
        "high_cost": "Tests whether the candidate survives harsher execution costs.",
        "trend_filter_off": "Tests whether the trend filter is actually adding value.",
        "trend_filter_stronger": "Tests whether stronger defensive exposure creates cash-drag failure.",
    }
    return roles.get(name, "Candidate-specific stress or ablation role.")


def _scenario_command(candidate: str, scenario: str) -> str:
    return (
        "python examples/run_candidate_stress_matrix.py --config config/research_recent.yaml "
        "--output-dir results/research/<timestamp> "
        f"--candidate {candidate} --scenario {scenario}"
    )


def _command_sequence(candidates: list[str]) -> list[str]:
    if not candidates:
        return []
    first = candidates[0]
    return [
        "python examples/run_candidate_experiment_run_packet.py --report-dir results/first_million --config config/research_recent.yaml",
        (
            "python examples/run_candidate_stress_matrix.py --config config/research_recent.yaml "
            f"--output-dir results/research/<timestamp> --candidate {first}"
        ),
        (
            "python examples/run_candidate_selection.py --config config/research_recent.yaml "
            "--output-dir results/research/<timestamp> --starting-capital 100000 --target-capital 1000000 --years 8"
        ),
    ]
