"""Strategy discovery plan for the first-million objective.

The plan translates the pre-registered candidate queue and current deterministic
readiness artifacts into an operator-facing execution matrix. It is not a
strategy signal, expected-return ranking, or trading permission.
"""
from __future__ import annotations

from dataclasses import dataclass
import csv
import json
from pathlib import Path
from typing import Any, Literal

from quantify.ops.recent_candidate_research import (
    build_recent_candidate_research_report,
    resolve_recent_candidate_research_dir,
)

DiscoveryDecision = Literal[
    "PREPARE_DATA",
    "RUN_RESEARCH",
    "REVIEW_COMPLETION",
    "PAPER_OBSERVE",
    "PAUSE",
]
DiscoveryStatus = Literal["PASS", "WATCH", "BLOCK"]

SELECTION_POLICY = [
    "Use pre-registered candidate priority until deterministic evidence permits comparison.",
    "Do not reorder candidates because a single backtest or LLM narrative looks attractive.",
    "Prefer the first READY candidate for launch; compare candidates only after required outputs pass completion review.",
    "Capital-goal fit must include required annual return, return margin, worst window return, drawdown, turnover, reject rate, and cost stress.",
    "Paper observation is required before any micro-live readiness claim, and human approval owns stage promotion.",
]

PROHIBITED_ACTIONS = [
    "Do not treat this discovery plan as a buy/sell signal or profit guarantee.",
    "Do not run research commands while the referenced candidate readiness item is BLOCKED.",
    "Do not promote candidates using template, demo, stale, or unaudited data.",
    "Do not connect any command or output here to real broker order submission.",
    "Do not let LLM output change candidate priority, deterministic gates, or human approval requirements.",
]

RANKING_REQUIRED_EVIDENCE = [
    "first_million_pipeline decision is not BLOCK.",
    "candidate_experiment_readiness decision is PASS or WATCH with at least one READY candidate.",
    "candidate_experiment_completion decision is PASS for a completed research run.",
    "candidate_selection.json exists with status PASS, ranked results, and selected_candidate.",
    "Ranking remains research-only until paper observation and human approval gates pass.",
]


@dataclass(frozen=True, slots=True)
class StrategyDiscoveryCandidate:
    priority: int
    candidate: str
    data_dependency: str
    evidence_scope: str
    readiness_status: str
    discovery_stage: str
    allowed_stage: str
    first_blocker: str
    next_command: str
    required_outputs: list[str]
    capital_goal_fit_tests: list[str]
    risk_budget_checks: list[str]
    paper_entry_requirements: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "priority": self.priority,
            "candidate": self.candidate,
            "data_dependency": self.data_dependency,
            "evidence_scope": self.evidence_scope,
            "readiness_status": self.readiness_status,
            "discovery_stage": self.discovery_stage,
            "allowed_stage": self.allowed_stage,
            "first_blocker": self.first_blocker,
            "next_command": self.next_command,
            "required_outputs": self.required_outputs,
            "capital_goal_fit_tests": self.capital_goal_fit_tests,
            "risk_budget_checks": self.risk_budget_checks,
            "paper_entry_requirements": self.paper_entry_requirements,
        }


@dataclass(frozen=True, slots=True)
class StrategyDiscoveryResearchFocus:
    status: str
    source: str
    candidate: str
    reason: str
    command: str
    candidate_count: int
    report_count: int
    advisory_only: bool
    evidence_status: str
    evidence_blockers: list[str]
    can_rank_candidates: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source": self.source,
            "candidate": self.candidate,
            "reason": self.reason,
            "command": self.command,
            "candidate_count": self.candidate_count,
            "report_count": self.report_count,
            "advisory_only": self.advisory_only,
            "evidence_status": self.evidence_status,
            "evidence_blockers": self.evidence_blockers,
            "can_rank_candidates": self.can_rank_candidates,
        }


@dataclass(frozen=True, slots=True)
class StrategyDiscoveryRankingGate:
    status: DiscoveryStatus
    can_rank_candidates: bool
    basis: str
    candidate_selection_artifact: str
    candidate_selection_status: str
    ranked_candidate_count: int
    top_ranked_candidate: str
    blocked_by: list[str]
    required_evidence: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "can_rank_candidates": self.can_rank_candidates,
            "basis": self.basis,
            "candidate_selection_artifact": self.candidate_selection_artifact,
            "candidate_selection_status": self.candidate_selection_status,
            "ranked_candidate_count": self.ranked_candidate_count,
            "top_ranked_candidate": self.top_ranked_candidate,
            "blocked_by": self.blocked_by,
            "required_evidence": self.required_evidence,
        }


@dataclass(frozen=True, slots=True)
class StrategyDiscoveryPlan:
    decision: DiscoveryDecision
    status: DiscoveryStatus
    as_of: str
    report_dir: str
    pipeline_decision: str
    readiness_decision: str
    launch_decision: str
    completion_decision: str
    top_candidate: str
    top_candidate_basis: str
    runnable_count: int
    blocked_count: int
    can_rank_candidates: bool
    ranking_gate: StrategyDiscoveryRankingGate
    research_focus: StrategyDiscoveryResearchFocus
    candidates: list[StrategyDiscoveryCandidate]
    allowed_actions: list[str]
    missing_evidence: list[str]
    selection_policy: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "status": self.status,
            "as_of": self.as_of,
            "report_dir": self.report_dir,
            "pipeline_decision": self.pipeline_decision,
            "readiness_decision": self.readiness_decision,
            "launch_decision": self.launch_decision,
            "completion_decision": self.completion_decision,
            "top_candidate": self.top_candidate,
            "top_candidate_basis": self.top_candidate_basis,
            "runnable_count": self.runnable_count,
            "blocked_count": self.blocked_count,
            "can_rank_candidates": self.can_rank_candidates,
            "ranking_gate": self.ranking_gate.to_dict(),
            "research_focus": self.research_focus.to_dict(),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "allowed_actions": self.allowed_actions,
            "missing_evidence": self.missing_evidence,
            "selection_policy": self.selection_policy,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Strategy Discovery Plan: {self.decision}",
            "",
            f"- Status: `{self.status}`",
            f"- As of: `{self.as_of}`",
            f"- Report directory: `{self.report_dir}`",
            f"- Pipeline decision: `{self.pipeline_decision}`",
            f"- Readiness decision: `{self.readiness_decision}`",
            f"- Launch decision: `{self.launch_decision}`",
            f"- Completion decision: `{self.completion_decision}`",
            f"- Top candidate: `{self.top_candidate or 'none'}`",
            f"- Top candidate basis: `{self.top_candidate_basis}`",
            f"- Runnable candidates: {self.runnable_count}",
            f"- Blocked candidates: {self.blocked_count}",
            f"- Can rank candidates: `{self.can_rank_candidates}`",
            "",
            "This plan organizes strategy discovery only. It is not a profit claim, capital allocation permission, or broker workflow.",
            "",
            "## Ranking Gate",
            "",
            f"- Status: `{self.ranking_gate.status}`",
            f"- Can rank candidates: `{self.ranking_gate.can_rank_candidates}`",
            f"- Basis: {self.ranking_gate.basis}",
            f"- Candidate selection artifact: `{self.ranking_gate.candidate_selection_artifact or 'none'}`",
            f"- Candidate selection status: `{self.ranking_gate.candidate_selection_status}`",
            f"- Ranked candidates: {self.ranking_gate.ranked_candidate_count}",
            f"- Top ranked candidate: `{self.ranking_gate.top_ranked_candidate or 'none'}`",
            "",
            "### Ranking Blockers",
        ]
        lines.extend(
            f"- {item}" for item in self.ranking_gate.blocked_by
        ) if self.ranking_gate.blocked_by else lines.append("- None.")
        lines.extend(["", "### Required Ranking Evidence"])
        lines.extend(f"- {item}" for item in self.ranking_gate.required_evidence)
        lines.extend(
            [
                "",
                "## Research Focus",
                "",
                f"- Status: `{self.research_focus.status}`",
                f"- Source: `{self.research_focus.source or 'none'}`",
                f"- Candidate: `{self.research_focus.candidate or 'none'}`",
                f"- Reason: {self.research_focus.reason or 'No recent research focus is available.'}",
                f"- Command: `{self.research_focus.command or 'none'}`",
                f"- Candidate count: {self.research_focus.candidate_count}",
                f"- Report count: {self.research_focus.report_count}",
                f"- Advisory only: `{self.research_focus.advisory_only}`",
                f"- Evidence status: `{self.research_focus.evidence_status}`",
                f"- Can rank candidates: `{self.research_focus.can_rank_candidates}`",
                *(
                    ["- Evidence blockers:"]
                    + [f"  - {item}" for item in self.research_focus.evidence_blockers]
                    if self.research_focus.evidence_blockers
                    else []
                ),
                "",
                "## Candidate Matrix",
                "",
                "| priority | candidate | scope | readiness | stage | allowed | first blocker | next command |",
                "| ---: | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for candidate in self.candidates:
            lines.append(
                f"| {candidate.priority} | `{candidate.candidate}` | "
                f"`{candidate.evidence_scope}` | `{candidate.readiness_status}` | "
                f"`{candidate.discovery_stage}` | `{candidate.allowed_stage}` | "
                f"{_cell(candidate.first_blocker or 'none')} | `{candidate.next_command or 'none'}` |"
            )
        lines.extend(["", "## Allowed Actions"])
        if self.allowed_actions:
            for index, action in enumerate(self.allowed_actions, start=1):
                lines.extend(["", f"{index}.", "", "```powershell", action, "```"])
        else:
            lines.append("- None.")
        lines.extend(["", "## Missing Evidence"])
        lines.extend(f"- {item}" for item in self.missing_evidence) if self.missing_evidence else lines.append("- None.")
        lines.extend(["", "## Selection Policy"])
        lines.extend(f"- {item}" for item in self.selection_policy)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_strategy_discovery_plan(
    report_dir: str | Path = "results/first_million",
    *,
    as_of: str | None = None,
    config_path: str | Path = "config/research_recent.yaml",
) -> StrategyDiscoveryPlan:
    root = Path(report_dir)
    pipeline = _read_json(root / "first_million_pipeline.json")
    queue = _read_json(root / "candidate_experiment_queue.json")
    readiness = _read_json(root / "candidate_experiment_readiness.json")
    launch = _read_json(root / "candidate_experiment_launch.json")
    completion = _read_json(root / "candidate_experiment_completion.json")
    candidate_selection_path = _first_existing_path(
        root / "candidate_selection.json",
        root / "weekly" / "candidate_selection.json",
    )
    candidate_selection = _read_json(candidate_selection_path) if candidate_selection_path else {}
    strategy_brief = _read_json(root / "first_million_strategy_brief.json")
    daily_brief = _read_json(root / "first_million_daily_brief.json")
    recent_research = _recent_research(root, daily_brief)
    evidence_inbox = _read_json(root / "source_qa_evidence_inbox.json")
    raw_bars_discovery = _read_json(root / "raw_bars_discovery.json")
    ohlcv_package = _read_json(root / "ohlcv_experiment_package.json")
    onboarding = _read_json(root / "real_data_batch_onboarding.json")
    market_packet = _read_json(root / "market_context_operator_packet.json")

    resolved_as_of = _first_nonempty(
        as_of,
        readiness.get("as_of"),
        queue.get("as_of"),
        daily_brief.get("as_of"),
        "unspecified",
    )
    candidates = _candidates(
        queue=queue,
        readiness=readiness,
        launch=launch,
        completion=completion,
    )
    pipeline_decision = _status(pipeline.get("decision"), missing="MISSING")
    readiness_decision = _status(readiness.get("decision"), missing="MISSING")
    launch_decision = _status(launch.get("decision"), missing="MISSING")
    completion_decision = _status(completion.get("decision"), missing="MISSING")
    decision = _decision(
        pipeline_decision=pipeline_decision,
        readiness_decision=readiness_decision,
        launch_decision=launch_decision,
        completion_decision=completion_decision,
        strategy_decision=str(strategy_brief.get("decision") or ""),
        has_ready=any(candidate.readiness_status == "READY" for candidate in candidates),
    )
    status = _status_for_decision(decision, candidates)
    research_evidence_blockers = _research_evidence_blockers(
        pipeline_decision=pipeline_decision,
        readiness_decision=readiness_decision,
        launch_decision=launch_decision,
        completion_decision=completion_decision,
        daily_brief=daily_brief,
        strategy_brief=strategy_brief,
    )
    ranking_gate = _ranking_gate(
        pipeline_decision=pipeline_decision,
        readiness_decision=readiness_decision,
        completion_decision=completion_decision,
        candidate_selection=candidate_selection,
        candidate_selection_path=candidate_selection_path,
        candidates=candidates,
        research_evidence_blockers=research_evidence_blockers,
    )
    return StrategyDiscoveryPlan(
        decision=decision,
        status=status,
        as_of=resolved_as_of,
        report_dir=str(root),
        pipeline_decision=pipeline_decision,
        readiness_decision=readiness_decision,
        launch_decision=launch_decision,
        completion_decision=completion_decision,
        top_candidate=_top_candidate(candidates),
        top_candidate_basis=_top_candidate_basis(candidates),
        runnable_count=sum(1 for candidate in candidates if candidate.readiness_status == "READY"),
        blocked_count=sum(1 for candidate in candidates if candidate.readiness_status == "BLOCKED"),
        can_rank_candidates=ranking_gate.can_rank_candidates,
        ranking_gate=ranking_gate,
        research_focus=_research_focus(
            recent_research,
            evidence_blockers=research_evidence_blockers,
        ),
        candidates=candidates,
        allowed_actions=_allowed_actions(
            decision=decision,
            root=root,
            as_of=resolved_as_of,
            config_path=config_path,
            candidates=candidates,
            launch=launch,
            daily_brief=daily_brief,
        ),
        missing_evidence=_missing_evidence(
            readiness,
            strategy_brief,
            daily_brief,
            evidence_inbox,
            raw_bars_discovery,
            ohlcv_package,
            onboarding,
            market_packet,
            recent_research,
        ),
        selection_policy=SELECTION_POLICY,
        prohibited_actions=PROHIBITED_ACTIONS,
    )


def write_strategy_discovery_plan(
    plan: StrategyDiscoveryPlan,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "strategy_discovery_plan.json").write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "strategy_discovery_plan.md").write_text(plan.to_markdown(), encoding="utf-8")
    _write_candidate_csv(plan, root / "strategy_discovery_plan.csv")
    return root


def _write_candidate_csv(plan: StrategyDiscoveryPlan, path: Path) -> None:
    fieldnames = [
        "priority",
        "candidate",
        "data_dependency",
        "evidence_scope",
        "readiness_status",
        "discovery_stage",
        "allowed_stage",
        "first_blocker",
        "next_command",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for candidate in plan.candidates:
            payload = candidate.to_dict()
            writer.writerow({field: payload.get(field, "") for field in fieldnames})


def _candidates(
    *,
    queue: dict[str, Any],
    readiness: dict[str, Any],
    launch: dict[str, Any],
    completion: dict[str, Any],
) -> list[StrategyDiscoveryCandidate]:
    readiness_items = {
        str(item.get("candidate") or ""): item
        for item in readiness.get("items", []) or []
        if isinstance(item, dict)
    }
    experiments = [
        item
        for item in queue.get("experiments", []) or []
        if isinstance(item, dict) and str(item.get("candidate") or "").strip()
    ]
    if not experiments:
        experiments = list(readiness_items.values())
    candidates = []
    for experiment in experiments:
        name = str(experiment.get("candidate") or "")
        readiness_item = readiness_items.get(name, {})
        required_outputs = _required_outputs(name, launch, experiment)
        candidates.append(
            StrategyDiscoveryCandidate(
                priority=_int(experiment.get("priority") or readiness_item.get("priority")),
                candidate=name,
                data_dependency=str(
                    experiment.get("data_dependency")
                    or readiness_item.get("data_dependency")
                    or ""
                ),
                evidence_scope=str(readiness_item.get("evidence_scope") or _scope(experiment)),
                readiness_status=str(readiness_item.get("status") or "NOT_REVIEWED"),
                discovery_stage=_stage(name, readiness_item, launch, completion),
                allowed_stage=_allowed_stage(name, readiness_item, launch, completion),
                first_blocker=_first_blocker(readiness_item),
                next_command=_next_command(name, readiness_item, launch, completion),
                required_outputs=required_outputs,
                capital_goal_fit_tests=[
                    str(item) for item in experiment.get("capital_goal_fit_tests", []) or []
                ],
                risk_budget_checks=[
                    str(item) for item in experiment.get("risk_budget_checks", []) or []
                ],
                paper_entry_requirements=[
                    str(item) for item in experiment.get("paper_entry_requirements", []) or []
                ],
            )
        )
    return sorted(candidates, key=lambda item: item.priority)


def _stage(
    name: str,
    readiness_item: dict[str, Any],
    launch: dict[str, Any],
    completion: dict[str, Any],
) -> str:
    if _completion_candidate(completion) == name and _status(completion.get("decision")) == "PASS":
        return "RESEARCH_COMPLETE"
    if _launch_candidate(launch) == name and _status(launch.get("decision")) == "PASS":
        return "LAUNCHED_PENDING_COMPLETION"
    if str(readiness_item.get("status") or "").upper() == "READY":
        return "READY_TO_LAUNCH"
    if readiness_item:
        return "WAITING_FOR_EVIDENCE"
    return "NOT_REVIEWED"


def _allowed_stage(
    name: str,
    readiness_item: dict[str, Any],
    launch: dict[str, Any],
    completion: dict[str, Any],
) -> str:
    stage = _stage(name, readiness_item, launch, completion)
    if stage == "RESEARCH_COMPLETE":
        return "paper_observation_candidate"
    if stage in {"READY_TO_LAUNCH", "LAUNCHED_PENDING_COMPLETION"}:
        return "research_only"
    return "blocked"


def _next_command(
    name: str,
    readiness_item: dict[str, Any],
    launch: dict[str, Any],
    completion: dict[str, Any],
) -> str:
    if _completion_candidate(completion) == name and _status(completion.get("decision")) == "PASS":
        return "python examples/run_paper_candidate_plan.py --report-dir results/first_million"
    if _launch_candidate(launch) == name and _status(launch.get("decision")) == "PASS":
        commands = launch.get("command_sequence", []) or []
        return str(commands[0]) if commands else (
            "python examples/run_candidate_experiment_execution.py --report-dir results/first_million"
        )
    command = str(readiness_item.get("next_command") or "").strip()
    if command:
        return command
    if str(readiness_item.get("status") or "").upper() == "READY":
        return "python examples/run_candidate_experiment_launch.py --report-dir results/first_million"
    return ""


def _decision(
    *,
    pipeline_decision: str,
    readiness_decision: str,
    launch_decision: str,
    completion_decision: str,
    strategy_decision: str,
    has_ready: bool,
) -> DiscoveryDecision:
    if completion_decision == "PASS":
        return "PAPER_OBSERVE"
    if launch_decision == "PASS":
        return "REVIEW_COMPLETION"
    if has_ready and readiness_decision in {"PASS", "WATCH"}:
        return "RUN_RESEARCH"
    if pipeline_decision == "BLOCK" or strategy_decision == "PREPARE_DATA":
        return "PREPARE_DATA"
    if readiness_decision == "BLOCK":
        return "PAUSE"
    return "PAUSE"


def _status_for_decision(
    decision: DiscoveryDecision,
    candidates: list[StrategyDiscoveryCandidate],
) -> DiscoveryStatus:
    if decision == "PREPARE_DATA":
        return "BLOCK"
    if decision in {"REVIEW_COMPLETION", "PAPER_OBSERVE"}:
        return "WATCH"
    if decision == "RUN_RESEARCH":
        return "PASS" if any(item.discovery_stage == "READY_TO_LAUNCH" for item in candidates) else "WATCH"
    return "BLOCK"


def _allowed_actions(
    *,
    decision: DiscoveryDecision,
    root: Path,
    as_of: str,
    config_path: str | Path,
    candidates: list[StrategyDiscoveryCandidate],
    launch: dict[str, Any],
    daily_brief: dict[str, Any],
) -> list[str]:
    if decision == "PREPARE_DATA":
        return _dedupe([str(item) for item in daily_brief.get("commands", []) or [] if item])[:8]
    if decision == "RUN_RESEARCH":
        ready = next((item for item in candidates if item.discovery_stage == "READY_TO_LAUNCH"), None)
        candidate_arg = f" --candidate {ready.candidate}" if ready else ""
        return [
            (
                f"python examples/run_candidate_experiment_run_packet.py --report-dir {root} "
                f"--config {config_path} --as-of {as_of}{candidate_arg}"
            )
        ]
    if decision == "REVIEW_COMPLETION":
        commands = [str(item) for item in launch.get("command_sequence", []) or [] if item]
        commands.append(f"python examples/run_candidate_experiment_completion.py --report-dir {root} --as-of {as_of}")
        return _dedupe(commands)
    if decision == "PAPER_OBSERVE":
        return [
            f"python examples/run_paper_candidate_plan.py --report-dir {root} --as-of {as_of}",
            f"python examples/run_first_million_readiness.py --report-dir {root} --as-of {as_of}",
        ]
    return [f"python examples/run_first_million_daily_brief.py --report-dir {root} --as-of {as_of}"]


def _missing_evidence(
    readiness: dict[str, Any],
    strategy_brief: dict[str, Any],
    daily_brief: dict[str, Any],
    evidence_inbox: dict[str, Any],
    raw_bars_discovery: dict[str, Any],
    ohlcv_package: dict[str, Any],
    onboarding: dict[str, Any],
    market_packet: dict[str, Any],
    recent_research: dict[str, Any],
) -> list[str]:
    values = [
        *[str(item) for item in daily_brief.get("missing_evidence", []) or []],
        *[str(item) for item in strategy_brief.get("missing_evidence", []) or []],
        *[str(item) for item in readiness.get("blockers", []) or []],
    ]
    if not recent_research:
        values.append("recent_candidate_research: no recent candidate research rollup is available.")
    elif _int(recent_research.get("candidate_count")) <= 0:
        values.append("recent_candidate_research: recent candidate research produced no candidate summaries.")
    if _status(market_packet.get("decision")) != "PASS":
        values.append(f"market_context_operator_packet: {_first_issue(market_packet)}")
    if _status(evidence_inbox.get("status")) != "PASS":
        values.append(f"source_qa_evidence_inbox: {_first_issue(evidence_inbox)}")
    if _status(raw_bars_discovery.get("status")) != "PASS":
        values.append(f"raw_bars_discovery: {_first_issue(raw_bars_discovery)}")
    if _status(ohlcv_package.get("decision")) != "PASS":
        values.append(f"ohlcv_experiment_package: {_first_issue(ohlcv_package)}")
    if _status(onboarding.get("decision")) != "PASS":
        values.append(f"real_data_batch_onboarding: {_first_issue(onboarding)}")
    return _dedupe(values)[:20]


def _required_outputs(
    name: str,
    launch: dict[str, Any],
    experiment: dict[str, Any],
) -> list[str]:
    if _launch_candidate(launch) == name and launch.get("required_outputs"):
        return [str(item) for item in launch.get("required_outputs", []) or []]
    return [str(item) for item in experiment.get("artifacts", []) or []]


def _top_candidate(candidates: list[StrategyDiscoveryCandidate]) -> str:
    ready = next((item for item in candidates if item.readiness_status == "READY"), None)
    if ready:
        return ready.candidate
    return candidates[0].candidate if candidates else ""


def _top_candidate_basis(candidates: list[StrategyDiscoveryCandidate]) -> str:
    if any(item.readiness_status == "READY" for item in candidates):
        return "first_ready_pre_registered_candidate"
    if candidates:
        return "pre_registered_priority_without_ranking"
    return "none"


def _ranking_gate(
    *,
    pipeline_decision: str,
    readiness_decision: str,
    completion_decision: str,
    candidate_selection: dict[str, Any],
    candidate_selection_path: Path | None,
    candidates: list[StrategyDiscoveryCandidate],
    research_evidence_blockers: list[str],
) -> StrategyDiscoveryRankingGate:
    candidate_selection_status = _candidate_selection_status(candidate_selection)
    ranked_count = _selection_result_count(candidate_selection)
    top_ranked = _selection_top_candidate(candidate_selection)
    selected = str(candidate_selection.get("selected_candidate") or "").strip()
    blockers: list[str] = []
    if pipeline_decision == "BLOCK":
        blockers.append("first_million_pipeline=BLOCK; current evidence cannot support candidate ranking.")
    if readiness_decision == "BLOCK":
        blockers.append("candidate_experiment_readiness=BLOCK; no candidate can be ranked yet.")
    if not any(candidate.readiness_status == "READY" for candidate in candidates):
        blockers.append("No READY candidate exists; ranking would only restate pre-registered priority.")
    if completion_decision != "PASS":
        blockers.append(
            f"candidate_experiment_completion={completion_decision}; completed research evidence is required."
        )
    if candidate_selection_path is None:
        blockers.append("candidate_selection.json is missing; no deterministic ranking report exists.")
    elif candidate_selection_status != "PASS":
        blockers.append(f"candidate_selection={candidate_selection_status}; formal ranking requires PASS.")
    if ranked_count <= 0:
        blockers.append("candidate_selection results are empty.")
    if not selected:
        blockers.append("candidate_selection selected_candidate is empty.")
    for blocker in research_evidence_blockers:
        if blocker and blocker not in blockers:
            blockers.append(blocker)
        if len(blockers) >= 10:
            break
    blockers = _dedupe(blockers)
    can_rank = (
        not blockers
        and candidate_selection_status == "PASS"
        and completion_decision == "PASS"
        and ranked_count > 0
        and bool(selected)
    )
    return StrategyDiscoveryRankingGate(
        status="PASS" if can_rank else "BLOCK",
        can_rank_candidates=can_rank,
        basis=(
            "deterministic candidate_selection PASS after completed research evidence"
            if can_rank
            else "pre-registered candidate priority only; formal ranking is disabled"
        ),
        candidate_selection_artifact=str(candidate_selection_path) if candidate_selection_path else "",
        candidate_selection_status=candidate_selection_status,
        ranked_candidate_count=ranked_count,
        top_ranked_candidate=top_ranked,
        blocked_by=blockers,
        required_evidence=list(RANKING_REQUIRED_EVIDENCE),
    )


def _candidate_selection_status(payload: dict[str, Any]) -> str:
    if not payload:
        return "MISSING"
    return _status(
        payload.get("status")
        or payload.get("decision")
        or payload.get("selection_status"),
        missing="UNKNOWN",
    )


def _selection_result_count(payload: dict[str, Any]) -> int:
    results = payload.get("results")
    return len(results) if isinstance(results, list) else 0


def _selection_top_candidate(payload: dict[str, Any]) -> str:
    for key in ("selected_candidate", "top_candidate", "best_candidate"):
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    results = payload.get("results")
    if isinstance(results, list) and results:
        first = results[0]
        if isinstance(first, dict):
            return str(first.get("name") or first.get("candidate") or "").strip()
    return ""


def _recent_research(root: Path, daily_brief: dict[str, Any]) -> dict[str, Any]:
    focus = daily_brief.get("research_focus")
    focus_payload = focus if isinstance(focus, dict) else {}
    payload = _read_json(root / "recent_candidate_research.json")
    rebuilt = build_recent_candidate_research_report(
        resolve_recent_candidate_research_dir(root),
        as_of=str(daily_brief.get("as_of") or "") or None,
    ).to_dict()
    candidates = [
        item
        for item in (payload, focus_payload, rebuilt)
        if _has_recent_research_evidence(item)
    ]
    if not candidates:
        return {}
    candidates.sort(
        key=lambda item: (
            _research_focus_preference(item),
            -_int(item.get("report_count")),
            -_int(item.get("candidate_count")),
        )
    )
    return candidates[0]


def _research_focus(
    payload: dict[str, Any],
    *,
    evidence_blockers: list[str],
) -> StrategyDiscoveryResearchFocus:
    candidate_count = _int(payload.get("candidate_count"))
    evidence_status = "BLOCK" if evidence_blockers else ("PASS" if candidate_count > 0 else "WATCH")
    reason = str(payload.get("best_research_reason") or "")
    if evidence_blockers and reason:
        reason = (
            f"{reason} Evidence blocker: {evidence_blockers[0]}. "
            "Use this only as a research hypothesis, not as candidate ranking or paper permission."
        )
    return StrategyDiscoveryResearchFocus(
        status=_research_focus_status(payload, evidence_blockers=evidence_blockers),
        source=str(payload.get("artifact_type") or "recent_candidate_research"),
        candidate=str(payload.get("best_research_candidate") or ""),
        reason=reason,
        command=str(payload.get("best_research_command") or ""),
        candidate_count=candidate_count,
        report_count=_int(payload.get("report_count")),
        advisory_only=True,
        evidence_status=evidence_status,
        evidence_blockers=evidence_blockers,
        can_rank_candidates=bool(candidate_count > 0 and not evidence_blockers),
    )


def _research_focus_status(payload: dict[str, Any], *, evidence_blockers: list[str]) -> str:
    if not payload:
        return "MISSING"
    if evidence_blockers:
        return "BLOCKED_EVIDENCE"
    if _int(payload.get("candidate_count")) > 0:
        return "PASS"
    return "WATCH"


def _research_evidence_blockers(
    *,
    pipeline_decision: str,
    readiness_decision: str,
    launch_decision: str,
    completion_decision: str,
    daily_brief: dict[str, Any],
    strategy_brief: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if pipeline_decision == "BLOCK":
        blockers.append("first_million_pipeline=BLOCK")
    if readiness_decision == "BLOCK":
        blockers.append("candidate_experiment_readiness=BLOCK")
    strategy_decision = str(strategy_brief.get("decision") or "").upper()
    if strategy_decision in {"PREPARE_DATA", "PAUSE"}:
        blockers.append(f"first_million_strategy_brief={strategy_decision}")
    for item in daily_brief.get("missing_evidence", []) or []:
        text = str(item or "").strip()
        if text:
            blockers.append(text)
        if len(blockers) >= 8:
            break
    return _dedupe(blockers)[:8]


def _research_focus_preference(payload: dict[str, Any]) -> int:
    search_dir = str(payload.get("search_dir") or "").lower().replace("/", "\\")
    if "research_recent_real_candidates" in search_dir:
        return 0
    if "research_recent_real_cache" in search_dir:
        return 1
    if "research_recent" in search_dir:
        return 2
    return 3


def _has_recent_research_evidence(payload: dict[str, Any]) -> bool:
    if not payload:
        return False
    return (
        _int(payload.get("report_count")) > 0
        or _int(payload.get("candidate_count")) > 0
        or bool(str(payload.get("best_research_candidate") or "").strip())
    )


def _first_blocker(readiness_item: dict[str, Any]) -> str:
    for key in ("blocked_by", "warnings"):
        values = readiness_item.get(key)
        if isinstance(values, list):
            for value in values:
                text = str(value or "").strip()
                if text:
                    return text
    return ""


def _scope(experiment: dict[str, Any]) -> str:
    dependency = str(experiment.get("data_dependency") or "")
    return "OHLCV_ONLY" if dependency == "ohlcv_only" else "PIT_FUNDAMENTAL_REQUIRED"


def _launch_candidate(payload: dict[str, Any]) -> str:
    return str(payload.get("selected_candidate") or "").strip()


def _completion_candidate(payload: dict[str, Any]) -> str:
    return str(payload.get("selected_candidate") or "").strip()


def _status(value: object, *, missing: str = "UNKNOWN") -> str:
    text = str(value or "").strip().upper()
    return text or missing


def _first_nonempty(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _first_issue(payload: dict[str, Any]) -> str:
    for key in ("blockers", "watch_items", "missing_evidence", "next_actions"):
        values = payload.get(key)
        if isinstance(values, list):
            for value in values:
                text = str(value or "").strip()
                if text:
                    return text
    items = payload.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                item_type = str(item.get("item_type") or "item").strip()
                item_id = str(item.get("item_id") or "unknown").strip()
                required = str(item.get("required_value") or item.get("current_state") or "").strip()
                return f"{item_type}/{item_id}: {required}".strip()
    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if isinstance(candidate, dict):
                text = str(candidate.get("message") or "").strip()
                if text:
                    return text
    return "review required"


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if str(value or "").strip()))


def _cell(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def _first_existing_path(*paths: Path) -> Path | None:
    return next((path for path in paths if path.exists()), None)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
