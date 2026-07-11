"""Daily operator brief for the first-million objective.

The brief is a thin roll-up over existing deterministic artifacts. It does not
clear gates, create evidence, choose strategies, or authorize live trading.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from typing import Any, Literal

from quantify.ops.recent_candidate_research import (
    build_recent_candidate_research_report,
    resolve_recent_candidate_research_dir,
)

DailyBriefDecision = Literal["PASS", "WATCH", "BLOCK"]

PROHIBITED_ACTIONS = [
    "Do not treat this brief as a profit claim, strategy signal, or capital allocation permission.",
    "Do not use this brief to upgrade deterministic PASS/WATCH/BLOCK gates.",
    "Do not close tasks without changing the underlying evidence artifact.",
    "Do not fabricate source QA answers, evidence attachments, CSV rows, paper records, or approvals.",
    "Do not connect this workflow to real broker order submission.",
    "Do not let LLM output modify task status, deterministic gates, or human approval requirements.",
]


@dataclass(frozen=True, slots=True)
class FirstMillionDailyBriefTask:
    priority: str
    status: str
    category: str
    item: str
    target: str
    action: str
    acceptance_criteria: str
    command: str
    source_artifact: str

    def to_dict(self) -> dict[str, str]:
        return {
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
class FirstMillionDailyBriefGate:
    name: str
    status: str
    artifact: str
    summary: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "artifact": self.artifact,
            "summary": self.summary,
        }


@dataclass(frozen=True, slots=True)
class FirstMillionDailyBriefRankingStatus:
    status: str
    can_rank_candidates: bool
    top_candidate: str
    top_candidate_basis: str
    ranking_gate_basis: str
    candidate_selection_status: str
    ranked_candidate_count: int
    top_ranked_candidate: str
    first_blocker: str
    blocked_by: list[str]
    required_evidence: list[str]
    artifact: str
    rerun_command: str
    advisory_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "can_rank_candidates": self.can_rank_candidates,
            "top_candidate": self.top_candidate,
            "top_candidate_basis": self.top_candidate_basis,
            "ranking_gate_basis": self.ranking_gate_basis,
            "candidate_selection_status": self.candidate_selection_status,
            "ranked_candidate_count": self.ranked_candidate_count,
            "top_ranked_candidate": self.top_ranked_candidate,
            "first_blocker": self.first_blocker,
            "blocked_by": self.blocked_by,
            "required_evidence": self.required_evidence,
            "artifact": self.artifact,
            "rerun_command": self.rerun_command,
            "advisory_only": self.advisory_only,
        }


@dataclass(frozen=True, slots=True)
class FirstMillionDailyBrief:
    decision: DailyBriefDecision
    as_of: str
    report_dir: str
    pipeline_decision: str
    operator_status: dict[str, Any]
    open_task_counts: dict[str, int]
    today_focus: dict[str, Any]
    research_focus: dict[str, Any]
    strategy_goal_gap: dict[str, Any]
    ranking_status: FirstMillionDailyBriefRankingStatus
    gate_summary: list[FirstMillionDailyBriefGate]
    missing_evidence: list[str]
    top_tasks: list[FirstMillionDailyBriefTask]
    commands: list[str]
    blocked_strategy_scope: list[str]
    next_review_command: str
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "as_of": self.as_of,
            "report_dir": self.report_dir,
            "pipeline_decision": self.pipeline_decision,
            "operator_status": self.operator_status,
            "open_task_counts": self.open_task_counts,
            "today_focus": self.today_focus,
            "research_focus": self.research_focus,
            "strategy_goal_gap": self.strategy_goal_gap,
            "ranking_status": self.ranking_status.to_dict(),
            "gate_summary": [gate.to_dict() for gate in self.gate_summary],
            "missing_evidence": self.missing_evidence,
            "top_tasks": [task.to_dict() for task in self.top_tasks],
            "commands": self.commands,
            "blocked_strategy_scope": self.blocked_strategy_scope,
            "next_review_command": self.next_review_command,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# First Million Daily Brief: {self.decision}",
            "",
            f"- As of: `{self.as_of}`",
            f"- Report directory: `{self.report_dir}`",
            f"- Pipeline decision: `{self.pipeline_decision}`",
            f"- Open P0 tasks: {self.open_task_counts.get('P0', 0)}",
            f"- Open P1 tasks: {self.open_task_counts.get('P1', 0)}",
            "",
            "This brief is an operator checklist over deterministic evidence. It is not a gate override, strategy recommendation, profit claim, or live trading instruction.",
            "",
            "## Today Focus",
        ]
        if self.today_focus:
            lines.extend(
                [
                    f"- Source: `{self.today_focus.get('source', '')}`",
                    f"- Priority: `{self.today_focus.get('priority', '')}`",
                    f"- Task type: `{self.today_focus.get('task_type', '')}`",
                    f"- Task count: {self.today_focus.get('task_count', 0)}",
                    f"- Target: `{self.today_focus.get('target', '')}`",
                    f"- Acceptance: {self.today_focus.get('acceptance_criteria', '')}",
                ]
            )
            sample_items = self.today_focus.get("sample_items", [])
            if sample_items:
                lines.extend(["", "Sample tasks:"])
                lines.extend(f"- `{item}`" for item in sample_items)
        else:
            lines.append("- No focused batch is available; rerun the pipeline to refresh evidence.")

        lines.extend(["", "## Research Focus"])
        if self.research_focus:
            lines.extend(
                [
                    f"- Source: `{self.research_focus.get('artifact_type', '')}`",
                    f"- Best candidate: `{self.research_focus.get('best_research_candidate', '')}`",
                    f"- Best reason: {self.research_focus.get('best_research_reason', '')}",
                    f"- Candidate count: {self.research_focus.get('candidate_count', 0)}",
                ]
            )
        else:
            lines.append("- No recent candidate research rollup is available.")

        lines.extend(["", "## Strategy Goal Gap"])
        if self.strategy_goal_gap:
            lines.extend(
                [
                    f"- Status: `{self.strategy_goal_gap.get('status', 'MISSING')}`",
                    f"- Selected candidate: `{self.strategy_goal_gap.get('selected_candidate', 'none') or 'none'}`",
                    f"- Top candidate: `{self.strategy_goal_gap.get('top_candidate', 'none') or 'none'}`",
                    f"- Candidate selection: `{self.strategy_goal_gap.get('candidate_selection_status', 'MISSING')}`",
                    f"- Capital goal: `{self.strategy_goal_gap.get('capital_goal_status', 'MISSING')}`",
                    f"- Compounding path: `{self.strategy_goal_gap.get('compounding_path_decision', 'MISSING')}`",
                    f"- Required annual return: {_pct(self.strategy_goal_gap.get('required_annual_return', 0.0))}",
                    f"- Projected capital: {_money(self.strategy_goal_gap.get('projected_capital_at_horizon', 0.0))}",
                    f"- Capital shortfall: {_money(self.strategy_goal_gap.get('capital_shortfall', 0.0))}",
                ]
            )
            gap_items = self.strategy_goal_gap.get("gap_items", [])
            if gap_items:
                lines.extend(["", "Goal gap items:"])
                lines.extend(f"- {item}" for item in gap_items[:6])
        else:
            lines.append("- Strategy brief goal-gap evidence is missing.")

        lines.extend(["", "## Ranking Status"])
        lines.extend(
            [
                f"- Status: `{self.ranking_status.status}`",
                f"- Can rank candidates: `{self.ranking_status.can_rank_candidates}`",
                f"- Top candidate: `{self.ranking_status.top_candidate or 'none'}`",
                f"- Top candidate basis: `{self.ranking_status.top_candidate_basis or 'none'}`",
                f"- Ranking basis: {self.ranking_status.ranking_gate_basis}",
                f"- Candidate selection: `{self.ranking_status.candidate_selection_status}`",
                f"- Ranked candidates: {self.ranking_status.ranked_candidate_count}",
                f"- Top ranked candidate: `{self.ranking_status.top_ranked_candidate or 'none'}`",
                f"- First blocker: {self.ranking_status.first_blocker or 'none'}",
                f"- Advisory only: `{self.ranking_status.advisory_only}`",
            ]
        )
        if self.ranking_status.blocked_by:
            lines.extend(["", "Ranking blockers:"])
            lines.extend(f"- {item}" for item in self.ranking_status.blocked_by[:6])
        if self.ranking_status.artifact:
            lines.append(f"- Artifact: `{self.ranking_status.artifact}`")
        lines.extend(["", "Rerun ranking gate after evidence changes:", "", "```powershell", self.ranking_status.rerun_command, "```"])

        lines.extend(
            [
                "",
                "## Gate Summary",
                "",
                "| gate | status | artifact | summary |",
                "| --- | --- | --- | --- |",
            ]
        )
        for gate in self.gate_summary:
            lines.append(
                f"| `{gate.name}` | `{gate.status}` | `{gate.artifact}` | {_markdown_cell(gate.summary)} |"
            )

        lines.extend(["", "## Missing Evidence"])
        lines.extend(f"- {item}" for item in self.missing_evidence) if self.missing_evidence else lines.append("- None.")

        lines.extend(["", "## Top Tasks", ""])
        if self.top_tasks:
            lines.append("| priority | status | category | item | target | action | command |")
            lines.append("| --- | --- | --- | --- | --- | --- | --- |")
            for task in self.top_tasks:
                lines.append(
                    f"| `{task.priority}` | `{task.status}` | `{task.category}` | "
                    f"`{task.item}` | `{task.target}` | {_markdown_cell(task.action)} | "
                    f"`{task.command}` |"
                )
        else:
            lines.append("- None.")

        lines.extend(["", "## Commands"])
        if self.commands:
            for index, command in enumerate(self.commands, start=1):
                lines.extend(["", f"{index}.", "", "```powershell", command, "```"])
        else:
            lines.append("- None.")

        lines.extend(["", "## Strategy Scope"])
        lines.extend(f"- {item}" for item in self.blocked_strategy_scope)
        lines.extend(["", "## Next Review", "", "```powershell", self.next_review_command, "```"])
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_first_million_daily_brief(
    report_dir: str | Path = "results/first_million",
    *,
    as_of: str | None = None,
    recent_research_dir: str | Path | None = None,
    pipeline_payload: dict[str, Any] | None = None,
    resolution_payload: dict[str, Any] | None = None,
) -> FirstMillionDailyBrief:
    """Build the operator-facing daily brief from existing report artifacts."""
    root = Path(report_dir)
    pipeline = pipeline_payload or _read_json(root / "first_million_pipeline.json")
    resolution = resolution_payload or _read_json(root / "first_million_resolution_plan.json")
    operator = _read_json(root / "operator_handoff_status.json")
    source_readiness = _read_json(root / "source_qa" / "source_qa_evidence_readiness.json")
    source_closeout = _read_json(root / "source_qa_closeout.json")
    evidence_inbox = _read_json(root / "source_qa_evidence_inbox.json")
    data_intake_status = _read_json(root / "data_intake_status.json")
    evidence_intake_kit = _read_json(
        root / "evidence_intake_kit" / "first_million_evidence_intake_kit.json"
    )
    evidence_work_order = _read_json(root / "first_million_evidence_work_order.json")
    raw_bars_discovery = _read_json(root / "raw_bars_discovery.json")
    ohlcv_closeout = _read_json(root / "ohlcv_intake_closeout.json")
    market_index_discovery = _read_json(root / "market_index_discovery.json")
    market = _read_json(root / "market_context_readiness.json")
    market_packet = _read_json(root / "market_context_operator_packet.json")
    ohlcv_package = _read_json(root / "ohlcv_experiment_package.json")
    onboarding = _read_json(root / "real_data_batch_onboarding.json")
    candidate = _read_json(root / "candidate_experiment_readiness.json")
    readiness = _read_json(root / "first_million_readiness.json")
    run_manifest = _read_json(_first_existing([root / "run_manifest.json", root / "weekly" / "run_manifest.json"]))
    micro_live_readiness = _read_json(
        _first_existing([root / "micro_live_readiness.json", root / "weekly" / "micro_live_readiness.json"])
    )
    capital_scaling = _read_json(
        _first_existing([root / "capital_scaling_plan.json", root / "weekly" / "capital_scaling_plan.json"])
    )
    strategy_brief = _read_json(root / "first_million_strategy_brief.json")
    strategy_discovery = _read_json(root / "strategy_discovery_plan.json")
    evidence_ranking_dashboard = _read_json(root / "first_million_evidence_ranking_dashboard.json")
    strategy_goal_gap = _strategy_goal_gap(strategy_brief)

    resolved_as_of = as_of or _first_nonempty(
        pipeline.get("as_of"),
        resolution.get("as_of"),
        operator.get("as_of"),
        candidate.get("as_of"),
        date.today().isoformat(),
    )
    selected_recent_research_dir = _recent_research_dir(root, recent_research_dir)
    recent_research = build_recent_candidate_research_report(
        selected_recent_research_dir,
        as_of=resolved_as_of,
    )
    pipeline_decision = _status(pipeline.get("decision"), missing="MISSING")
    ranking_status = _ranking_status(root, strategy_discovery, as_of=resolved_as_of)
    tasks = _resolution_tasks(resolution)
    if not tasks:
        tasks = _operator_tasks(operator)
    top_tasks = tasks[:12]
    today_focus = _today_focus(operator, top_tasks, pipeline_decision, recent_research.to_dict())
    gate_summary = _gate_summary(
        root,
        pipeline,
        operator,
        source_readiness,
        source_closeout,
        evidence_inbox,
        data_intake_status,
        evidence_intake_kit,
        evidence_work_order,
        raw_bars_discovery,
        ohlcv_closeout,
        market_index_discovery,
        market,
        market_packet,
        ohlcv_package,
        onboarding,
        candidate,
        resolution,
        readiness,
        run_manifest,
        micro_live_readiness,
        capital_scaling,
        recent_research.to_dict(),
        strategy_discovery,
        evidence_ranking_dashboard,
    )
    decision = _decision(gate_summary, pipeline_decision)
    next_review_command = (
        ".\\.venv\\Scripts\\python.exe examples\\run_first_million_daily_brief.py "
        f"--report-dir {root} --as-of {resolved_as_of}"
    )
    commands = _commands(
        today_focus=today_focus,
        top_tasks=top_tasks,
        source_readiness=source_readiness,
        source_closeout=source_closeout,
        evidence_inbox=evidence_inbox,
        data_intake_status=data_intake_status,
        evidence_intake_kit=evidence_intake_kit,
        evidence_work_order=evidence_work_order,
        raw_bars_discovery=raw_bars_discovery,
        ohlcv_closeout=ohlcv_closeout,
        market_index_discovery=market_index_discovery,
        market=market,
        market_packet=market_packet,
        ohlcv_package=ohlcv_package,
        onboarding=onboarding,
        recent_research_dir=selected_recent_research_dir,
        root=root,
        as_of=resolved_as_of,
        next_review_command=next_review_command,
    )
    return FirstMillionDailyBrief(
        decision=decision,
        as_of=resolved_as_of,
        report_dir=str(root),
        pipeline_decision=pipeline_decision,
        operator_status=_operator_status(operator),
        open_task_counts=_open_task_counts(operator, resolution),
        today_focus=today_focus,
        research_focus=recent_research.to_dict(),
        strategy_goal_gap=strategy_goal_gap,
        ranking_status=ranking_status,
        gate_summary=gate_summary,
        missing_evidence=_missing_evidence(
            operator,
            source_readiness,
            source_closeout,
            evidence_inbox,
            data_intake_status,
            evidence_intake_kit,
            evidence_work_order,
            raw_bars_discovery,
            ohlcv_closeout,
            market_index_discovery,
            market,
            market_packet,
            ohlcv_package,
            onboarding,
            candidate,
            resolution,
            run_manifest,
            micro_live_readiness,
            capital_scaling,
            recent_research.to_dict(),
            strategy_goal_gap,
            ranking_status,
        ),
        top_tasks=top_tasks,
        commands=commands,
        blocked_strategy_scope=_blocked_strategy_scope(
            candidate,
            market,
            market_index_discovery,
            market_packet,
            ohlcv_closeout,
            ohlcv_package,
            onboarding,
            data_intake_status,
            micro_live_readiness,
            capital_scaling,
            pipeline_decision,
            recent_research.to_dict(),
            ranking_status,
        ),
        next_review_command=next_review_command,
        prohibited_actions=PROHIBITED_ACTIONS,
    )


def write_first_million_daily_brief(
    brief: FirstMillionDailyBrief,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "first_million_daily_brief.json").write_text(
        json.dumps(brief.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "first_million_daily_brief.md").write_text(brief.to_markdown(), encoding="utf-8")
    return root


def _gate_summary(
    root: Path,
    pipeline: dict[str, Any],
    operator: dict[str, Any],
    source_readiness: dict[str, Any],
    source_closeout: dict[str, Any],
    evidence_inbox: dict[str, Any],
    data_intake_status: dict[str, Any],
    evidence_intake_kit: dict[str, Any],
    evidence_work_order: dict[str, Any],
    raw_bars_discovery: dict[str, Any],
    ohlcv_closeout: dict[str, Any],
    market_index_discovery: dict[str, Any],
    market: dict[str, Any],
    market_packet: dict[str, Any],
    ohlcv_package: dict[str, Any],
    onboarding: dict[str, Any],
    candidate: dict[str, Any],
    resolution: dict[str, Any],
    readiness: dict[str, Any],
    run_manifest: dict[str, Any],
    micro_live_readiness: dict[str, Any],
    capital_scaling: dict[str, Any],
    recent_research: dict[str, Any],
    strategy_discovery: dict[str, Any],
    evidence_ranking_dashboard: dict[str, Any],
) -> list[FirstMillionDailyBriefGate]:
    gates = [
        _gate(
            "first_million_pipeline",
            _status(pipeline.get("decision"), missing="MISSING"),
            root / "first_million_pipeline.json",
            _pipeline_summary(pipeline),
        ),
        _gate(
            "operator_handoff_status",
            _status(operator.get("status"), missing="MISSING"),
            root / "operator_handoff_status.json",
            _operator_summary(operator),
        ),
        _gate(
            "source_qa_evidence_readiness",
            _status(source_readiness.get("status"), missing="MISSING"),
            root / "source_qa" / "source_qa_evidence_readiness.json",
            _source_readiness_summary(source_readiness),
        ),
        _gate(
            "source_qa_closeout",
            _status(source_closeout.get("decision"), missing="MISSING"),
            root / "source_qa_closeout.json",
            _source_qa_closeout_summary(source_closeout),
        ),
        _gate(
            "source_qa_evidence_inbox",
            _status(evidence_inbox.get("status"), missing="MISSING"),
            root / "source_qa_evidence_inbox.json",
            _source_qa_evidence_inbox_summary(evidence_inbox),
        ),
        _gate(
            "data_intake_status",
            _status(data_intake_status.get("decision"), missing="MISSING"),
            root / "data_intake_status.json",
            _data_intake_status_summary(data_intake_status),
        ),
        _gate(
            "evidence_intake_kit",
            _status(evidence_intake_kit.get("decision"), missing="MISSING"),
            root / "evidence_intake_kit" / "first_million_evidence_intake_kit.json",
            _evidence_intake_kit_summary(evidence_intake_kit),
        ),
        _gate(
            "evidence_work_order",
            _status(evidence_work_order.get("decision"), missing="MISSING"),
            root / "first_million_evidence_work_order.json",
            _evidence_work_order_summary(evidence_work_order),
        ),
        _gate(
            "raw_bars_discovery",
            _status(raw_bars_discovery.get("status"), missing="MISSING"),
            root / "raw_bars_discovery.json",
            _raw_bars_discovery_summary(raw_bars_discovery),
        ),
        _gate(
            "ohlcv_intake_closeout",
            _status(ohlcv_closeout.get("decision"), missing="MISSING"),
            root / "ohlcv_intake_closeout.json",
            _ohlcv_closeout_summary(ohlcv_closeout),
        ),
        _gate(
            "market_index_discovery",
            _status(market_index_discovery.get("status"), missing="MISSING"),
            root / "market_index_discovery.json",
            _market_index_discovery_summary(market_index_discovery),
        ),
        _gate(
            "market_context_readiness",
            _status(market.get("decision"), missing="MISSING"),
            root / "market_context_readiness.json",
            _market_summary(market),
        ),
        _gate(
            "market_context_operator_packet",
            _status(market_packet.get("decision"), missing="MISSING"),
            root / "market_context_operator_packet.json",
            _market_packet_summary(market_packet),
        ),
        _gate(
            "ohlcv_experiment_package",
            _status(ohlcv_package.get("decision"), missing="MISSING"),
            root / "ohlcv_experiment_package.json",
            _ohlcv_package_summary(ohlcv_package),
        ),
        _gate(
            "real_data_batch_onboarding",
            _status(onboarding.get("decision"), missing="MISSING"),
            root / "real_data_batch_onboarding.json",
            _onboarding_summary(onboarding),
        ),
        _gate(
            "candidate_experiment_readiness",
            _status(candidate.get("decision"), missing="MISSING"),
            root / "candidate_experiment_readiness.json",
            _candidate_summary(candidate),
        ),
        _gate(
            "recent_candidate_research",
            _status(recent_research.get("status"), missing="MISSING"),
            root / "recent_candidate_research.json",
            _recent_candidate_research_summary(recent_research),
        ),
        _gate(
            "first_million_resolution_plan",
            _status(resolution.get("decision"), missing="MISSING"),
            root / "first_million_resolution_plan.json",
            _resolution_summary(resolution),
        ),
        _gate(
            "first_million_readiness",
            _status(readiness.get("decision"), missing="MISSING"),
            root / "first_million_readiness.json",
            _readiness_summary(readiness),
        ),
        _gate(
            "run_manifest",
            _run_manifest_status(run_manifest),
            _first_existing([root / "run_manifest.json", root / "weekly" / "run_manifest.json"])
            or root / "run_manifest.json",
            _run_manifest_summary(run_manifest),
        ),
        _gate(
            "micro_live_readiness",
            _optional_status(micro_live_readiness, "decision"),
            _first_existing([root / "micro_live_readiness.json", root / "weekly" / "micro_live_readiness.json"])
            or root / "micro_live_readiness.json",
            _micro_live_readiness_summary(micro_live_readiness),
        ),
        _gate(
            "capital_scaling_plan",
            _optional_status(capital_scaling, "decision"),
            _first_existing([root / "capital_scaling_plan.json", root / "weekly" / "capital_scaling_plan.json"])
            or root / "capital_scaling_plan.json",
            _capital_scaling_summary(capital_scaling),
        ),
    ]
    if strategy_discovery:
        gates.append(
            _gate(
                "strategy_discovery_plan",
                _status(strategy_discovery.get("status") or strategy_discovery.get("decision"), missing="MISSING"),
                root / "strategy_discovery_plan.json",
                _strategy_discovery_summary(strategy_discovery),
            )
        )
    if evidence_ranking_dashboard:
        gates.append(
            _gate(
                "first_million_evidence_ranking_dashboard",
                _status(evidence_ranking_dashboard.get("decision"), missing="MISSING"),
                root / "first_million_evidence_ranking_dashboard.json",
                _evidence_ranking_dashboard_summary(evidence_ranking_dashboard),
            )
        )
    return gates


def _gate(name: str, status: str, artifact: Path, summary: str) -> FirstMillionDailyBriefGate:
    return FirstMillionDailyBriefGate(
        name=name,
        status=status,
        artifact=str(artifact),
        summary=summary,
    )


def _resolution_tasks(payload: dict[str, Any]) -> list[FirstMillionDailyBriefTask]:
    tasks = payload.get("tasks", []) if isinstance(payload, dict) else []
    return [
        FirstMillionDailyBriefTask(
            priority=str(item.get("priority") or ""),
            status=str(item.get("status") or ""),
            category=str(item.get("category") or ""),
            item=str(item.get("item") or ""),
            target=str(item.get("target") or ""),
            action=str(item.get("action") or ""),
            acceptance_criteria=str(item.get("acceptance_criteria") or ""),
            command=str(item.get("command") or ""),
            source_artifact=str(item.get("source_artifact") or ""),
        )
        for item in tasks
        if isinstance(item, dict)
    ]


def _operator_tasks(payload: dict[str, Any]) -> list[FirstMillionDailyBriefTask]:
    rows = payload.get("first_open_tasks", []) if isinstance(payload, dict) else []
    return [
        FirstMillionDailyBriefTask(
            priority=str(item.get("priority") or ""),
            status=str(item.get("status") or ""),
            category=str(item.get("task_type") or ""),
            item=str(item.get("item") or ""),
            target=str(item.get("target") or ""),
            action=str(item.get("action") or ""),
            acceptance_criteria=str(item.get("required_evidence") or ""),
            command=str(item.get("next_command") or ""),
            source_artifact=str(item.get("source_artifact") or ""),
        )
        for item in rows
        if isinstance(item, dict)
    ]


def _today_focus(
    operator: dict[str, Any],
    top_tasks: list[FirstMillionDailyBriefTask],
    pipeline_decision: str,
    recent_research: dict[str, Any],
) -> dict[str, Any]:
    batch = operator.get("next_batch") if isinstance(operator, dict) else {}
    if isinstance(batch, dict) and int(batch.get("task_count") or 0) > 0:
        sample_tasks = [
            str(item.get("item") or item.get("target") or "")
            for item in batch.get("sample_tasks", []) or []
            if isinstance(item, dict)
        ][:8]
        return {
            "source": "operator_handoff_status",
            "status": str(batch.get("status") or ""),
            "priority": str(batch.get("priority") or ""),
            "task_type": str(batch.get("task_type") or ""),
            "task_count": int(batch.get("task_count") or 0),
            "target": _first_sample_target(batch),
            "source_artifacts": [str(item) for item in batch.get("source_artifacts", []) or []],
            "acceptance_criteria": str(batch.get("acceptance_criteria") or ""),
            "command": str(batch.get("next_command") or ""),
            "sample_items": sample_tasks,
        }
    if top_tasks:
        first = top_tasks[0]
        return {
            "source": "first_million_resolution_plan",
            "status": first.status,
            "priority": first.priority,
            "task_type": first.category,
            "task_count": 1,
            "target": first.target,
            "source_artifacts": [first.source_artifact] if first.source_artifact else [],
            "acceptance_criteria": first.acceptance_criteria,
            "command": first.command,
            "sample_items": [first.item],
        }
    if _int(recent_research.get("candidate_count")) > 0:
        candidate = str(recent_research.get("best_research_candidate") or "")
        command = str(recent_research.get("best_research_command") or "")
        reason = str(recent_research.get("best_research_reason") or "")
        return {
            "source": "recent_candidate_research",
            "status": str(recent_research.get("status") or ""),
            "priority": "P1",
            "task_type": "candidate_research",
            "task_count": 1,
            "target": candidate,
            "source_artifacts": ["recent_candidate_research.json"],
            "acceptance_criteria": "Collect more research evidence without upgrading deterministic gates.",
            "command": command,
            "sample_items": [reason] if reason else ([candidate] if candidate else []),
        }
    if pipeline_decision == "PASS":
        return {
            "source": "first_million_pipeline",
            "status": "PASS",
            "priority": "P1",
            "task_type": "review",
            "task_count": 1,
            "target": "manual approval record",
            "source_artifacts": ["first_million_pipeline.json"],
            "acceptance_criteria": "Continue only through deterministic review and human approval.",
            "command": "",
            "sample_items": ["Review PASS evidence before expanding paper scope."],
        }
    return {}


def _first_sample_target(batch: dict[str, Any]) -> str:
    for item in batch.get("sample_tasks", []) or []:
        if isinstance(item, dict) and str(item.get("target") or "").strip():
            return str(item.get("target"))
    return ""


def _decision(gates: list[FirstMillionDailyBriefGate], pipeline_decision: str) -> DailyBriefDecision:
    if pipeline_decision == "MISSING":
        return "BLOCK"
    statuses = {gate.status for gate in gates}
    if "BLOCK" in statuses:
        return "BLOCK"
    if pipeline_decision == "BLOCK":
        return "BLOCK"
    if statuses.intersection({"WATCH", "SKIPPED", "MISSING", "UNKNOWN"}):
        return "WATCH"
    return "PASS"


def _operator_status(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {
            "status": "MISSING",
            "open_task_count": 0,
            "p0_open_task_count": 0,
            "p1_open_task_count": 0,
            "next_batch_task_type": "",
            "next_batch_task_count": 0,
        }
    batch = payload.get("next_batch", {}) if isinstance(payload.get("next_batch"), dict) else {}
    return {
        "status": _status(payload.get("status"), missing="MISSING"),
        "open_task_count": _int(payload.get("open_task_count")),
        "p0_open_task_count": _int(payload.get("p0_open_task_count")),
        "p1_open_task_count": _int(payload.get("p1_open_task_count")),
        "source_qa_open_task_count": _int(payload.get("source_qa_open_task_count")),
        "source_qa_attachment_open_task_count": _int(
            payload.get("source_qa_attachment_open_task_count")
        ),
        "data_export_open_task_count": _int(payload.get("data_export_open_task_count")),
        "next_batch_task_type": str(batch.get("task_type") or ""),
        "next_batch_task_count": _int(batch.get("task_count")),
    }


def _open_task_counts(
    operator: dict[str, Any],
    resolution: dict[str, Any],
) -> dict[str, int]:
    counts = resolution.get("task_counts") if isinstance(resolution, dict) else {}
    if isinstance(counts, dict) and counts:
        return {
            "total": _int(counts.get("total")),
            "P0": _int(counts.get("P0")),
            "P1": _int(counts.get("P1")),
            "P2": _int(counts.get("P2")),
            "open": _int(counts.get("open")),
            "waiting": _int(counts.get("waiting")),
            "watch": _int(counts.get("watch")),
        }
    return {
        "total": _int(operator.get("open_task_count")),
        "P0": _int(operator.get("p0_open_task_count")),
        "P1": _int(operator.get("p1_open_task_count")),
        "P2": 0,
        "open": _int(operator.get("open_task_count")),
        "waiting": 0,
        "watch": 0,
    }


def _missing_evidence(
    operator: dict[str, Any],
    source_readiness: dict[str, Any],
    source_closeout: dict[str, Any],
    evidence_inbox: dict[str, Any],
    data_intake_status: dict[str, Any],
    evidence_intake_kit: dict[str, Any],
    evidence_work_order: dict[str, Any],
    raw_bars_discovery: dict[str, Any],
    ohlcv_closeout: dict[str, Any],
    market_index_discovery: dict[str, Any],
    market: dict[str, Any],
    market_packet: dict[str, Any],
    ohlcv_package: dict[str, Any],
    onboarding: dict[str, Any],
    candidate: dict[str, Any],
    resolution: dict[str, Any],
    run_manifest: dict[str, Any],
    micro_live_readiness: dict[str, Any],
    capital_scaling: dict[str, Any],
    recent_research: dict[str, Any],
    strategy_goal_gap: dict[str, Any],
    ranking_status: FirstMillionDailyBriefRankingStatus,
) -> list[str]:
    items: list[str] = []
    batch = operator.get("next_batch") if isinstance(operator, dict) else {}
    if isinstance(batch, dict) and _int(batch.get("task_count")) > 0:
        items.append(
            "operator_next_batch: {count} `{task_type}` tasks remain in {artifacts}.".format(
                count=_int(batch.get("task_count")),
                task_type=str(batch.get("task_type") or "operator"),
                artifacts=", ".join(str(item) for item in batch.get("source_artifacts", []) or []),
            )
        )
    items.extend(_strategy_goal_gap_missing_evidence(strategy_goal_gap))
    if ranking_status.artifact and ranking_status.status != "PASS":
        items.append(
            "strategy_ranking: formal candidate ranking is disabled; {issue}".format(
                issue=ranking_status.first_blocker or ranking_status.ranking_gate_basis,
            )
        )
    for section in source_readiness.get("sections", []) or []:
        if not isinstance(section, dict) or _status(section.get("status")) == "PASS":
            continue
        for blocker in section.get("blockers", []) or []:
            items.append(f"source_qa/{section.get('name', 'section')}: {blocker}")
            if len(items) >= 8:
                break
            if len(items) >= 8:
                break
    if _status(source_closeout.get("decision")) != "PASS":
        items.append(f"source_qa_closeout: {_first_issue(source_closeout)}")
    if _status(evidence_inbox.get("status")) != "PASS":
        items.append(f"source_qa_evidence_inbox: {_first_issue(evidence_inbox)}")
    fill_issue = _source_qa_evidence_inbox_fill_issue(evidence_inbox)
    if fill_issue:
        items.append(f"source_qa_evidence_inbox_fill: {fill_issue}")
    if _status(data_intake_status.get("decision")) != "PASS":
        items.append(f"data_intake_status: {_data_intake_status_issue(data_intake_status)}")
    if _status(evidence_intake_kit.get("decision")) != "PASS":
        items.append(f"evidence_intake_kit: {_first_issue(evidence_intake_kit)}")
    if _status(evidence_work_order.get("decision")) != "PASS":
        items.append(f"evidence_work_order: {_first_issue(evidence_work_order)}")
    if _status(raw_bars_discovery.get("status")) != "PASS":
        items.append(f"raw_bars_discovery: {_raw_bars_discovery_issue(raw_bars_discovery)}")
    if _status(ohlcv_closeout.get("decision")) != "PASS":
        items.append(f"ohlcv_intake_closeout: {_first_issue(ohlcv_closeout)}")
    if _status(market_index_discovery.get("status")) != "PASS":
        items.append(f"market_index_discovery: {_first_issue(market_index_discovery)}")
    if _status(market.get("decision")) != "PASS":
        items.append(f"market_context: {_first_issue(market)}")
    if _status(market_packet.get("decision")) != "PASS":
        items.append(f"market_context_operator_packet: {_first_issue(market_packet)}")
    if _status(ohlcv_package.get("decision")) != "PASS":
        items.append(f"ohlcv_experiment_package: {_first_issue(ohlcv_package)}")
    if _status(onboarding.get("decision")) != "PASS":
        items.append(f"real_data_batch_onboarding: {_first_issue(onboarding)}")
    if _status(candidate.get("decision")) != "PASS":
        items.append(
            "candidate_experiment_readiness: runnable={runnable}, blocked={blocked}. {issue}".format(
                runnable=_int(candidate.get("runnable_count")),
                blocked=_int(candidate.get("blocked_count")),
                issue=_first_issue(candidate),
            )
        )
    if _run_manifest_status(run_manifest) != "PASS":
        items.append(f"run_manifest: {_run_manifest_summary(run_manifest)}")
    if micro_live_readiness and _status(micro_live_readiness.get("decision")) != "PASS":
        items.append(f"micro_live_readiness: {_micro_live_readiness_summary(micro_live_readiness)}")
    if capital_scaling and _status(capital_scaling.get("decision")) != "PASS":
        items.append(f"capital_scaling_plan: {_capital_scaling_summary(capital_scaling)}")
    if _int(recent_research.get("candidate_count")) <= 0:
        items.append("recent_candidate_research: no recent candidate research evidence is available.")
    elif recent_research.get("missing_evidence"):
        items.append(
            "recent_candidate_research: best_candidate={candidate}; {issue}".format(
                candidate=str(recent_research.get("best_research_candidate") or "none"),
                issue=str((recent_research.get("missing_evidence") or ["no issue text"])[0]),
            )
        )
    counts = resolution.get("task_counts") if isinstance(resolution, dict) else {}
    if isinstance(counts, dict) and _int(counts.get("total")) > 0:
        items.append(
            "resolution_queue: P0={p0}, P1={p1}, P2={p2}; clear P0 evidence before downstream work.".format(
                p0=_int(counts.get("P0")),
                p1=_int(counts.get("P1")),
                p2=_int(counts.get("P2")),
            )
        )
    return _dedupe([item for item in items if item.strip()])[:24]


def _strategy_goal_gap(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload:
        return {
            "status": "MISSING",
            "selected_candidate": "",
            "top_candidate": "",
            "candidate_selection_status": "MISSING",
            "capital_goal_status": "MISSING",
            "compounding_path_decision": "MISSING",
            "required_annual_return": 0.0,
            "projected_capital_at_horizon": 0.0,
            "capital_shortfall": 0.0,
            "gap_items": ["first_million_strategy_brief.json is missing."],
            "can_claim_compounding_path": False,
        }
    raw = payload.get("compounding_goal")
    if not isinstance(raw, dict):
        return {
            "status": "MISSING",
            "selected_candidate": "",
            "top_candidate": str(payload.get("top_research_candidate") or ""),
            "candidate_selection_status": "MISSING",
            "capital_goal_status": "MISSING",
            "compounding_path_decision": "MISSING",
            "required_annual_return": 0.0,
            "projected_capital_at_horizon": 0.0,
            "capital_shortfall": 0.0,
            "gap_items": ["strategy brief does not contain compounding_goal."],
            "can_claim_compounding_path": False,
        }
    return {
        "status": _status(raw.get("status"), missing="MISSING"),
        "selected_candidate": str(raw.get("selected_candidate") or ""),
        "top_candidate": str(raw.get("top_candidate") or payload.get("top_research_candidate") or ""),
        "candidate_selection_status": _status(raw.get("candidate_selection_status"), missing="MISSING"),
        "capital_goal_status": _status(raw.get("capital_goal_status"), missing="MISSING"),
        "compounding_path_decision": _status(raw.get("compounding_path_decision"), missing="MISSING"),
        "required_annual_return": _float(raw.get("required_annual_return")),
        "projected_capital_at_horizon": _float(raw.get("projected_capital_at_horizon")),
        "capital_shortfall": _float(raw.get("capital_shortfall")),
        "gap_items": [str(item) for item in raw.get("gap_items", []) or [] if str(item).strip()],
        "can_claim_compounding_path": bool(raw.get("can_claim_compounding_path")),
    }


def _strategy_goal_gap_missing_evidence(strategy_goal_gap: dict[str, Any]) -> list[str]:
    status = _status(strategy_goal_gap.get("status"), missing="MISSING")
    if status == "PASS":
        return []
    gap_items = strategy_goal_gap.get("gap_items", []) or []
    if gap_items:
        return [f"strategy_goal_gap: {item}" for item in gap_items[:3]]
    return [
        "strategy_goal_gap: compounding goal evidence is missing or not PASS; "
        "rerun first-million strategy brief after data gates change."
    ]


def _ranking_status(
    root: Path,
    strategy_discovery: dict[str, Any],
    *,
    as_of: str,
) -> FirstMillionDailyBriefRankingStatus:
    rerun_command = (
        ".\\.venv\\Scripts\\python.exe examples\\run_strategy_discovery_plan.py "
        f"--report-dir {root} --config config\\research_recent.yaml --as-of {as_of}"
    )
    if not strategy_discovery:
        return FirstMillionDailyBriefRankingStatus(
            status="MISSING",
            can_rank_candidates=False,
            top_candidate="",
            top_candidate_basis="none",
            ranking_gate_basis=(
                "strategy_discovery_plan.json has not been generated yet; "
                "rerun strategy discovery after the daily brief or pipeline refresh."
            ),
            candidate_selection_status="MISSING",
            ranked_candidate_count=0,
            top_ranked_candidate="",
            first_blocker="strategy_discovery_plan.json is missing.",
            blocked_by=["strategy_discovery_plan.json is missing."],
            required_evidence=[],
            artifact="",
            rerun_command=rerun_command,
        )
    gate = strategy_discovery.get("ranking_gate")
    ranking_gate = gate if isinstance(gate, dict) else {}
    blocked_by = ranking_gate.get("blocked_by")
    blockers = [str(item) for item in blocked_by or [] if str(item).strip()] if isinstance(blocked_by, list) else []
    required_evidence = ranking_gate.get("required_evidence")
    required = (
        [str(item) for item in required_evidence or [] if str(item).strip()]
        if isinstance(required_evidence, list)
        else []
    )
    return FirstMillionDailyBriefRankingStatus(
        status=_status(ranking_gate.get("status"), missing=_status(strategy_discovery.get("status"), missing="MISSING")),
        can_rank_candidates=bool(
            strategy_discovery.get("can_rank_candidates") or ranking_gate.get("can_rank_candidates")
        ),
        top_candidate=str(strategy_discovery.get("top_candidate") or ""),
        top_candidate_basis=str(strategy_discovery.get("top_candidate_basis") or "none"),
        ranking_gate_basis=str(ranking_gate.get("basis") or "review strategy_discovery_plan.json"),
        candidate_selection_status=_status(ranking_gate.get("candidate_selection_status"), missing="MISSING"),
        ranked_candidate_count=_int(ranking_gate.get("ranked_candidate_count")),
        top_ranked_candidate=str(ranking_gate.get("top_ranked_candidate") or ""),
        first_blocker=blockers[0] if blockers else "",
        blocked_by=blockers,
        required_evidence=required,
        artifact=str(root / "strategy_discovery_plan.json"),
        rerun_command=rerun_command,
    )


def _commands(
    *,
    today_focus: dict[str, Any],
    top_tasks: list[FirstMillionDailyBriefTask],
    source_readiness: dict[str, Any],
    source_closeout: dict[str, Any],
    evidence_inbox: dict[str, Any],
    data_intake_status: dict[str, Any],
    evidence_intake_kit: dict[str, Any],
    evidence_work_order: dict[str, Any],
    raw_bars_discovery: dict[str, Any],
    ohlcv_closeout: dict[str, Any],
    market_index_discovery: dict[str, Any],
    market: dict[str, Any],
    market_packet: dict[str, Any],
    ohlcv_package: dict[str, Any],
    onboarding: dict[str, Any],
    recent_research_dir: Path,
    root: Path,
    as_of: str,
    next_review_command: str,
) -> list[str]:
    commands: list[str] = []
    focus_command = str(today_focus.get("command") or "").strip()
    if focus_command:
        commands.append(focus_command)
    commands.extend(task.command for task in top_tasks if task.command)
    commands.extend(str(item) for item in source_readiness.get("next_commands", []) or [] if item)
    if _status(source_closeout.get("decision")) != "PASS":
        commands.append(
            ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_operator_packet.py "
            f"--data-dir data_exports --report-dir results\\first_million --as-of {as_of} "
            "--write-dropzone-kit"
        )
        commands.append(
            ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_closeout.py "
            f"--data-dir data_exports --report-dir results\\first_million --output-dir results\\first_million --as-of {as_of}"
        )
        commands.extend(str(item) for item in source_closeout.get("command_sequence", []) or [] if item)
    if _status(evidence_inbox.get("status")) == "BLOCK":
        commands.append(
            ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_evidence_inbox.py "
            "--data-dir data_exports --report-dir results\\first_million"
        )
        commands.extend(str(item) for item in evidence_inbox.get("next_commands", []) or [] if item)
    if _status(data_intake_status.get("decision")) != "PASS":
        next_command = str(data_intake_status.get("next_command") or "").strip()
        if next_command:
            commands.append(next_command)
        commands.append(
            ".\\.venv\\Scripts\\python.exe examples\\run_data_intake_status.py "
            f"--report-dir results\\first_million --data-dir data_exports --as-of {as_of}"
        )
    if _status(evidence_intake_kit.get("decision")) != "PASS":
        commands.append(
            ".\\.venv\\Scripts\\python.exe examples\\run_first_million_evidence_intake_kit.py "
            f"--report-dir results\\first_million --data-dir data_exports --as-of {as_of}"
        )
        commands.extend(str(item) for item in evidence_intake_kit.get("command_sequence", []) or [] if item)
    if _status(evidence_work_order.get("decision")) != "PASS":
        commands.append(
            ".\\.venv\\Scripts\\python.exe examples\\run_first_million_evidence_work_order.py "
            f"--report-dir results\\first_million --data-dir data_exports --as-of {as_of}"
        )
    if any(task.category == "source_qa_worksheet" for task in top_tasks):
        commands.append(
            ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa_answers.py "
            "--checklist data_exports\\data_source_qa.json "
            "--worksheet data_exports\\data_source_qa_evidence_worksheet.csv "
            "--output data_exports\\data_source_qa_answers.json "
            "--evidence-manifest data_exports\\source_qa_evidence_manifest.json "
            "--require-evidence-manifest"
        )
    if any(task.category == "source_qa_attachment" for task in top_tasks):
        commands.append(
            ".\\.venv\\Scripts\\python.exe examples\\write_source_qa_evidence_manifest.py "
            "--checklist data_exports\\data_source_qa.json "
            "--evidence-dir data_exports\\source_qa_evidence --output-dir data_exports --strict"
        )
    if _status(raw_bars_discovery.get("status")) == "BLOCK":
        dropzone_dir = _raw_bars_dropzone_dir(raw_bars_discovery)
        commands.append(
            ".\\.venv\\Scripts\\python.exe examples\\run_raw_bars_discovery.py "
            f"--search-dir {dropzone_dir} --config config\\research_recent.yaml "
            "--output-dir results\\first_million --data-output-dir data_exports "
            "--write-dropzone-kit --min-symbols 300"
        )
        commands.extend(str(item) for item in raw_bars_discovery.get("next_commands", []) or [] if item)
    if _status(ohlcv_closeout.get("decision")) != "PASS":
        commands.append(
            ".\\.venv\\Scripts\\python.exe examples\\run_ohlcv_intake_closeout.py "
            "--data-dir data_exports --report-dir results\\first_million "
            "--config config\\research_recent.yaml "
            "--source-qa-answers data_exports\\data_source_qa_answers.json "
            "--source-qa-evidence-manifest data_exports\\source_qa_evidence_manifest.json "
            "--require-source-qa-evidence-manifest "
            f"--as-of {as_of} --min-symbols 300 --min-trading-days 240"
        )
        commands.extend(str(item) for item in ohlcv_closeout.get("command_sequence", []) or [] if item)
    if _status(market_index_discovery.get("status")) != "PASS":
        commands.append(
            ".\\.venv\\Scripts\\python.exe examples\\run_market_index_discovery.py "
            "--search-dir data_exports\\indices --output-dir results\\first_million "
            f"--as-of {as_of}"
        )
        commands.extend(str(item) for item in market_index_discovery.get("next_commands", []) or [] if item)
    if _status(market.get("decision")) == "BLOCK":
        commands.append(
            ".\\.venv\\Scripts\\python.exe examples\\run_market_regime.py "
            "--config config\\research_recent.yaml --output-dir results\\first_million"
        )
    if _status(market_packet.get("decision")) == "BLOCK":
        commands.append(
            ".\\.venv\\Scripts\\python.exe examples\\run_market_context_operator_packet.py "
            f"--report-dir results\\first_million --as-of {as_of}"
        )
        commands.extend(str(item) for item in market_packet.get("command_sequence", []) or [] if item)
    if _status(ohlcv_package.get("decision")) == "BLOCK":
        commands.append(
            ".\\.venv\\Scripts\\python.exe examples\\run_ohlcv_experiment_package.py "
            "--data-dir data_exports --report-dir results\\first_million "
            "--config config\\research_recent.yaml "
            "--source-qa-answers data_exports\\data_source_qa_answers.json "
            "--source-qa-evidence-manifest data_exports\\source_qa_evidence_manifest.json "
            "--require-source-qa-evidence-manifest "
            f"--as-of {as_of} --min-symbols 300 --min-trading-days 240"
        )
    if _status(onboarding.get("decision")) == "BLOCK":
        commands.append(
            ".\\.venv\\Scripts\\python.exe examples\\run_real_data_batch_onboarding.py "
            "--data-dir data_exports --report-dir results\\first_million "
            "--config config\\research_recent.yaml "
            "--source-qa-answers data_exports\\data_source_qa_answers.json "
            "--source-qa-evidence-manifest data_exports\\source_qa_evidence_manifest.json "
            "--require-source-qa-evidence-manifest "
            f"--as-of {as_of} --min-symbols 300 --min-trading-days 240"
        )
    recent_research_command = (
        ".\\.venv\\Scripts\\python.exe examples\\run_recent_candidate_research.py "
        f"--search-dir {recent_research_dir} --output-dir {root} --as-of {as_of}"
    )
    strategy_discovery_command = (
        ".\\.venv\\Scripts\\python.exe examples\\run_strategy_discovery_plan.py "
        f"--report-dir {root} --config config\\research_recent.yaml --as-of {as_of}"
    )
    pipeline_refresh_command = _pipeline_refresh_command(root, as_of)
    guaranteed_tail = _dedupe(
        [
            recent_research_command,
            strategy_discovery_command,
            pipeline_refresh_command,
            next_review_command,
        ]
    )
    deduped = _dedupe([command.strip() for command in commands if command.strip()])
    head = [command for command in deduped if command not in guaranteed_tail]
    limit = max(0, 24 - len(guaranteed_tail))
    return head[:limit] + guaranteed_tail


def _pipeline_refresh_command(root: Path, as_of: str) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\run_first_million_pipeline.py "
        "--config config\\research_recent.yaml --data-dir data_exports "
        f"--output-dir {root} "
        "--source-qa-answers data_exports\\data_source_qa_answers.json "
        "--source-qa-evidence-manifest data_exports\\source_qa_evidence_manifest.json "
        "--require-source-qa-evidence-manifest "
        "--latest-import-report results\\import\\recent\\data_import.json "
        f"--as-of {as_of} --min-symbols 300 --no-registry"
    )


def _blocked_strategy_scope(
    candidate: dict[str, Any],
    market: dict[str, Any],
    market_index_discovery: dict[str, Any],
    market_packet: dict[str, Any],
    ohlcv_closeout: dict[str, Any],
    ohlcv_package: dict[str, Any],
    onboarding: dict[str, Any],
    data_intake_status: dict[str, Any],
    micro_live_readiness: dict[str, Any],
    capital_scaling: dict[str, Any],
    pipeline_decision: str,
    recent_research: dict[str, Any],
    ranking_status: FirstMillionDailyBriefRankingStatus,
) -> list[str]:
    items: list[str] = []
    scopes = candidate.get("scope_summary") if isinstance(candidate, dict) else {}
    if isinstance(scopes, dict) and scopes:
        for scope, summary in scopes.items():
            if not isinstance(summary, dict):
                continue
            items.append(
                "{scope}: ready={ready}/{total}, blocked={blocked}; {note}".format(
                    scope=scope,
                    ready=_int(summary.get("ready")),
                    total=_int(summary.get("total")),
                    blocked=_int(summary.get("blocked")),
                    note=str(summary.get("note") or "review required"),
                )
            )
    else:
        items.append("Candidate experiment scope is not available until readiness artifacts exist.")
    if _status(market.get("decision")) == "BLOCK":
        items.append("Market context is BLOCK, so candidate experiments remain research-blocked.")
    if _status(market_index_discovery.get("status")) == "BLOCK":
        items.append(
            "Market index discovery is BLOCK, so reviewed index CSV evidence for snapshot-only context is still missing."
        )
    if _status(market_packet.get("decision")) == "BLOCK":
        items.append("Market context operator packet is BLOCK, so reviewed market-context evidence is still missing.")
    if _status(ohlcv_closeout.get("decision")) == "BLOCK":
        items.append("OHLCV intake closeout is BLOCK, so discovered raw bars have not reached guarded intake.")
    if _status(ohlcv_package.get("decision")) == "BLOCK":
        items.append("OHLCV experiment package is BLOCK, so price_volume_defensive cannot launch research.")
    if _status(onboarding.get("decision")) == "BLOCK":
        items.append("Real-data batch onboarding is BLOCK, so no recent-data candidate research should start.")
    if _status(data_intake_status.get("decision")) == "BLOCK":
        items.append("Data intake status is BLOCK, so no strategy ranking or paper promotion should start.")
    if ranking_status.artifact and not ranking_status.can_rank_candidates:
        items.append(
            "Formal strategy ranking is disabled: {basis}; first blocker: {blocker}".format(
                basis=ranking_status.top_candidate_basis or ranking_status.ranking_gate_basis,
                blocker=ranking_status.first_blocker or "review strategy_discovery_plan.json",
            )
        )
    if micro_live_readiness and _status(micro_live_readiness.get("decision")) == "BLOCK":
        items.append("Micro-live readiness is BLOCK, so no manual micro-live preparation should be promoted.")
    if capital_scaling and _status(capital_scaling.get("decision")) == "BLOCK":
        items.append("Capital scaling plan is BLOCK, so do not increase capital.")
    if _int(recent_research.get("candidate_count")) > 0:
        items.append(
            "Recent research focus is {candidate}; {reason}".format(
                candidate=str(recent_research.get("best_research_candidate") or "none"),
                reason=str(recent_research.get("best_research_reason") or "research-only evidence remains incomplete."),
            )
        )
    else:
        items.append("Recent candidate research rollup is missing, so there is no current cross-run research focus.")
    if pipeline_decision == "BLOCK":
        items.append("First-million pipeline is BLOCK; do not run paper promotion or capital scaling.")
    return items


def _pipeline_summary(payload: dict[str, Any]) -> str:
    stages = payload.get("stages", []) if isinstance(payload, dict) else []
    if not isinstance(stages, list):
        stages = []
    blocked = sum(
        1
        for item in stages
        if isinstance(item, dict) and _status(item.get("status")) == "BLOCK"
    )
    skipped = sum(
        1
        for item in stages
        if isinstance(item, dict) and _status(item.get("status")) == "SKIPPED"
    )
    return f"stages={len(stages)}, blocked={blocked}, skipped={skipped}"


def _operator_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "operator handoff status is missing"
    batch = payload.get("next_batch", {}) if isinstance(payload.get("next_batch"), dict) else {}
    return (
        f"open={_int(payload.get('open_task_count'))}, "
        f"P0={_int(payload.get('p0_open_task_count'))}, "
        f"next={batch.get('task_type', '')}:{_int(batch.get('task_count'))}"
    )


def _source_readiness_summary(payload: dict[str, Any]) -> str:
    sections = payload.get("sections", []) if isinstance(payload, dict) else []
    blocking = [
        str(section.get("name") or "")
        for section in sections
        if isinstance(section, dict) and _status(section.get("status")) == "BLOCK"
    ]
    return f"blocking_sections={', '.join(blocking) if blocking else 'none'}"


def _source_qa_closeout_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "source QA closeout is missing"
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    return "open_actions={open_actions}, worksheet_missing={worksheet}, attachment_missing={attachments}; {issue}".format(
        open_actions=_int(counts.get("open_action_count")),
        worksheet=_int(counts.get("missing_worksheet_count")),
        attachments=_int(counts.get("missing_attachment_count")),
        issue=_first_issue(payload),
    )


def _source_qa_evidence_inbox_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "source QA evidence inbox is missing"
    fill_status = str(payload.get("worksheet_fill_command_status") or "UNKNOWN")
    fill_ready = str(bool(payload.get("worksheet_fill_command_ready"))).lower()
    blockers = payload.get("worksheet_fill_command_blockers")
    blocker_count = len(blockers) if isinstance(blockers, list) else 0
    return (
        "required={required}, missing={missing}, invalid={invalid}, scanned={scanned}, "
        "fill={fill_status}/ready={fill_ready}/blockers={blockers}; {issue}"
    ).format(
        required=_int(payload.get("required_item_count")),
        missing=_int(payload.get("missing_item_count")),
        invalid=_int(payload.get("invalid_file_count")),
        scanned=_int(payload.get("scanned_file_count")),
        fill_status=fill_status,
        fill_ready=fill_ready,
        blockers=blocker_count,
        issue=_first_issue(payload),
    )


def _source_qa_evidence_inbox_fill_issue(payload: dict[str, Any]) -> str:
    if not payload:
        return ""
    status = _status(payload.get("worksheet_fill_command_status"), missing="UNKNOWN")
    ready = bool(payload.get("worksheet_fill_command_ready"))
    blockers = payload.get("worksheet_fill_command_blockers")
    warnings = payload.get("worksheet_fill_command_warnings")
    if isinstance(blockers, list) and blockers:
        return str(blockers[0])
    if not ready and status != "PASS":
        return "worksheet_fill_command is not ready; evidence arguments still include missing target paths or placeholders."
    if isinstance(warnings, list) and warnings:
        return str(warnings[0])
    return ""


def _data_intake_status_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "data intake status is missing"
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return "next={next_area}, raw={raw}, source_evidence={source}, worksheet_ready={ready}; {issue}".format(
        next_area=str(payload.get("next_area") or "none"),
        raw=str(summary.get("raw_bars_status") or "UNKNOWN"),
        source=str(summary.get("source_evidence_status") or "UNKNOWN"),
        ready=str(bool(summary.get("worksheet_fill_ready"))).lower(),
        issue=_data_intake_status_issue(payload),
    )


def _data_intake_status_issue(payload: dict[str, Any]) -> str:
    if not payload:
        return "data_intake_status.json is missing; rerun first-million pipeline."
    next_action = str(payload.get("next_action") or "").strip()
    if next_action:
        return next_action
    for item in payload.get("items", []) or []:
        if isinstance(item, dict) and _status(item.get("status")) != "PASS":
            return str(item.get("next_action") or item.get("current_state") or "intake item requires review")
    return "review data_intake_status.json"


def _evidence_intake_kit_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "evidence intake kit is missing"
    return "files={count}, kit={kit_dir}; {issue}".format(
        count=_int(payload.get("file_count")),
        kit_dir=str(payload.get("kit_dir") or "missing"),
        issue=_first_issue(payload),
    )


def _evidence_work_order_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "evidence work order is missing"
    return "open_batches={count}, next={next_batch}; {issue}".format(
        count=_int(payload.get("open_batch_count")),
        next_batch=str(payload.get("next_batch_id") or "none"),
        issue=_first_issue(payload),
    )


def _raw_bars_discovery_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "raw bars discovery is missing"
    kit = payload.get("dropzone_kit") if isinstance(payload.get("dropzone_kit"), dict) else {}
    dropzone = str(kit.get("dropzone_dir") or "data_exports\\raw")
    readme = str(kit.get("readme_path") or "")
    suffix = f", dropzone={dropzone}"
    if readme:
        suffix += f", readme={readme}"
    return "best={best}, candidates={count}; {issue}".format(
        best=str(payload.get("best_candidate") or "none"),
        count=len(payload.get("candidates", []) or []),
        issue=f"{_first_issue(payload)}{suffix}",
    )


def _raw_bars_discovery_issue(payload: dict[str, Any]) -> str:
    issue = _first_issue(payload)
    kit = payload.get("dropzone_kit") if isinstance(payload.get("dropzone_kit"), dict) else {}
    readme = str(kit.get("readme_path") or "").strip()
    if readme:
        return f"{issue}; dropzone_readme={readme}"
    return issue


def _raw_bars_dropzone_dir(payload: dict[str, Any]) -> str:
    kit = payload.get("dropzone_kit") if isinstance(payload.get("dropzone_kit"), dict) else {}
    return str(kit.get("dropzone_dir") or "data_exports\\raw")


def _ohlcv_closeout_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "OHLCV intake closeout is missing"
    return "source_qa={source}, raw={raw}, intake={intake}, latest={latest}; {issue}".format(
        source=str(payload.get("source_qa_status") or "MISSING"),
        raw=str(payload.get("raw_discovery_status") or "MISSING"),
        intake=str(payload.get("offline_intake_status") or "MISSING"),
        latest=str(payload.get("latest_bar_date") or "missing"),
        issue=_first_issue(payload),
    )


def _market_index_discovery_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "market index discovery is missing"
    return "best={best}, candidates={count}; {issue}".format(
        best=str(payload.get("best_candidate") or "none"),
        count=len(payload.get("candidates", []) or []),
        issue=_first_issue(payload),
    )


def _market_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "market context readiness is missing"
    return "{source}:{label}; {issue}".format(
        source=str(payload.get("source") or "unknown"),
        label=str(payload.get("label") or "unknown"),
        issue=_first_issue(payload),
    )


def _market_packet_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "market context operator packet is missing"
    return "readiness={source}/{decision}, missing_items={count}; {issue}".format(
        source=str(payload.get("readiness_source") or "unknown"),
        decision=str(payload.get("readiness_decision") or "UNKNOWN"),
        count=_int(payload.get("missing_item_count")),
        issue=_first_issue(payload),
    )


def _ohlcv_package_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "OHLCV experiment package preflight is missing"
    bars = payload.get("bars") if isinstance(payload.get("bars"), dict) else {}
    return (
        "allowed={allowed}, bars={state}, symbols={symbols}, trading_days={days}; {issue}".format(
            allowed=str(payload.get("launch_research_allowed", False)),
            state=str(bars.get("state") or "unknown"),
            symbols=_int(bars.get("symbol_count")),
            days=_int(bars.get("trading_day_count")),
            issue=_first_issue(payload),
        )
    )


def _onboarding_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "real-data batch onboarding is missing"
    steps = payload.get("steps", []) if isinstance(payload, dict) else []
    blocked = sum(
        1
        for item in steps
        if isinstance(item, dict) and _status(item.get("status")) == "BLOCK"
    )
    watch = sum(
        1
        for item in steps
        if isinstance(item, dict) and _status(item.get("status")) == "WATCH"
    )
    return f"steps={len(steps)}, blocked={blocked}, watch={watch}; {_first_issue(payload)}"


def _candidate_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "candidate experiment readiness is missing"
    return (
        f"runnable={_int(payload.get('runnable_count'))}, "
        f"blocked={_int(payload.get('blocked_count'))}; {_first_issue(payload)}"
    )


def _recent_candidate_research_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "recent candidate research rollup is missing"
    return "reports={reports}, candidates={candidates}, best={best}; {reason}".format(
        reports=_int(payload.get("report_count")),
        candidates=_int(payload.get("candidate_count")),
        best=str(payload.get("best_research_candidate") or "none"),
        reason=str(payload.get("best_research_reason") or "no best-candidate reason"),
    )


def _strategy_discovery_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "strategy discovery plan is missing"
    ranking_gate = payload.get("ranking_gate")
    gate = ranking_gate if isinstance(ranking_gate, dict) else {}
    blocked_by = gate.get("blocked_by")
    first_blocker = ""
    if isinstance(blocked_by, list):
        first_blocker = next((str(item) for item in blocked_by if str(item).strip()), "")
    if not first_blocker:
        first_blocker = str(gate.get("basis") or "review strategy_discovery_plan.json")
    return (
        "decision={decision}, can_rank={can_rank}, top={top}, basis={basis}; {issue}".format(
            decision=str(payload.get("decision") or "MISSING"),
            can_rank=str(bool(payload.get("can_rank_candidates") or gate.get("can_rank_candidates"))).lower(),
            top=str(payload.get("top_candidate") or "none"),
            basis=str(payload.get("top_candidate_basis") or "none"),
            issue=first_blocker,
        )
    )


def _evidence_ranking_dashboard_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "evidence ranking dashboard is missing"
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    return "next={next_area}, can_rank={can_rank}, top={top}, first_blocker={blocker}".format(
        next_area=str(payload.get("next_area") or "none"),
        can_rank=str(bool(payload.get("can_rank_candidates"))).lower(),
        top=str(payload.get("top_candidate") or "none"),
        blocker=str(summary.get("first_ranking_blocker") or payload.get("next_action") or "none"),
    )


def _recent_research_dir(root: Path, override: str | Path | None) -> Path:
    return resolve_recent_candidate_research_dir(root, override)


def _resolution_summary(payload: dict[str, Any]) -> str:
    counts = payload.get("task_counts") if isinstance(payload, dict) else {}
    if not isinstance(counts, dict):
        return "resolution plan is missing"
    return (
        f"total={_int(counts.get('total'))}, P0={_int(counts.get('P0'))}, "
        f"P1={_int(counts.get('P1'))}, P2={_int(counts.get('P2'))}"
    )


def _readiness_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "first-million readiness card is missing"
    blockers = payload.get("blockers", []) or []
    if blockers:
        return str(blockers[0])
    watches = payload.get("watch_items", []) or []
    if watches:
        return str(watches[0])
    gates = payload.get("gates", []) or []
    return f"gates={len(gates)}"


def _run_manifest_status(payload: dict[str, Any]) -> str:
    if not payload:
        return "MISSING"
    if payload.get("demo_data_used") is True:
        return "BLOCK"
    if not str(payload.get("in_sample_end", "") or "").strip():
        return "BLOCK"
    if not str(payload.get("out_sample_start", "") or "").strip():
        return "BLOCK"
    data_version = payload.get("data_version", {})
    if not isinstance(data_version, dict):
        return "BLOCK"
    if not str(data_version.get("csv_dataset_fingerprint", "") or "").strip():
        return "BLOCK"
    if str(data_version.get("data_source_qa_status", "")).upper() != "PASS":
        return "BLOCK"
    if str(data_version.get("data_source_csv_qa_status", "")).upper() != "PASS":
        return "BLOCK"
    return "PASS"


def _run_manifest_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "run_manifest.json is missing"
    if payload.get("demo_data_used") is True:
        return "run_manifest demo_data_used=true"
    if not str(payload.get("in_sample_end", "") or "").strip():
        return "run_manifest missing in_sample_end"
    if not str(payload.get("out_sample_start", "") or "").strip():
        return "run_manifest missing out_sample_start"
    data_version = payload.get("data_version", {})
    if not isinstance(data_version, dict):
        return "run_manifest data_version is invalid"
    fingerprint = str(data_version.get("csv_dataset_fingerprint", "") or "")
    if not fingerprint:
        return "run_manifest missing csv_dataset_fingerprint"
    source_status = str(data_version.get("data_source_qa_status", "") or "MISSING").upper()
    csv_status = str(data_version.get("data_source_csv_qa_status", "") or "MISSING").upper()
    if source_status != "PASS" or csv_status != "PASS":
        return f"run_manifest source QA status is {source_status}/{csv_status}"
    return (
        f"latest={payload.get('latest_bar_date', '') or 'missing'}, "
        f"symbols={_int(payload.get('symbol_count'))}, "
        f"trading_days={_int(payload.get('trading_day_count'))}, "
        f"csv_fingerprint={fingerprint[:12]}"
    )


def _micro_live_readiness_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "micro-live readiness has not been prepared; optional downstream gate is not evaluated"
    findings = payload.get("findings", []) if isinstance(payload, dict) else []
    if isinstance(findings, list):
        for finding in findings:
            if isinstance(finding, dict) and _status(finding.get("severity")) in {"BLOCK", "WATCH"}:
                code = str(finding.get("code") or "finding")
                message = str(finding.get("message") or "micro-live readiness requires review")
                return f"{code}: {message}"
    return f"decision={_status(payload.get('decision'), missing='MISSING')}, findings={len(findings or [])}"


def _capital_scaling_summary(payload: dict[str, Any]) -> str:
    if not payload:
        return "capital scaling plan has not been generated; optional downstream gate is not evaluated"
    blockers = payload.get("blockers", []) if isinstance(payload, dict) else []
    if blockers:
        return str(blockers[0])
    return (
        f"current={payload.get('current_capital', 0)}, "
        f"proposed={payload.get('proposed_capital', 0)}, "
        f"max_allowed={payload.get('max_allowed_capital', 0)}"
    )


def _first_issue(payload: dict[str, Any]) -> str:
    next_action = str(payload.get("next_action") or "").strip()
    if next_action:
        return next_action
    for key in ("blockers", "watch_items", "next_actions"):
        values = payload.get(key)
        if isinstance(values, list):
            for value in values:
                text = str(value or "").strip()
                if text:
                    return text
    findings = payload.get("findings")
    if isinstance(findings, list):
        for finding in findings:
            if isinstance(finding, dict):
                text = str(finding.get("message") or "").strip()
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
    files = payload.get("files")
    if isinstance(files, list):
        for item in files:
            if isinstance(item, dict):
                item_type = str(item.get("item_type") or "file").strip()
                item_id = str(item.get("item_id") or "unknown").strip()
                target = str(item.get("target_path") or "").strip()
                return f"{item_type}/{item_id}: collect real file for {target}".strip()
    batches = payload.get("batches")
    if isinstance(batches, list):
        for batch in batches:
            if isinstance(batch, dict) and str(batch.get("status") or "").upper() != "PASS":
                batch_id = str(batch.get("batch_id") or "batch").strip()
                title = str(batch.get("title") or "").strip()
                return f"{batch_id}: {title}".strip()
    actions = payload.get("actions")
    if isinstance(actions, list):
        for action in actions:
            if isinstance(action, dict) and str(action.get("status") or "").upper() != "PASS":
                category = str(action.get("category") or "action").strip()
                item = str(action.get("item") or "unknown").strip()
                text = str(action.get("action") or "").strip()
                return f"{category}/{item}: {text}".strip()
    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if isinstance(candidate, dict):
                text = str(candidate.get("message") or "").strip()
                if text:
                    return text
                findings = candidate.get("findings")
                if isinstance(findings, list):
                    for finding in findings:
                        text = str(finding or "").strip()
                        if text:
                            return text
    return "no current issue text"


def _status(value: object, *, missing: str = "UNKNOWN") -> str:
    text = str(value or "").strip().upper()
    return text or missing


def _optional_status(payload: dict[str, Any], key: str) -> str:
    if not payload:
        return "PASS"
    return _status(payload.get(key), missing="MISSING")


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


def _float(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _pct(value: object) -> str:
    return f"{_float(value):.2%}"


def _money(value: object) -> str:
    return f"{_float(value):,.0f}"


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _first_existing(paths: list[Path]) -> Path | None:
    return next((path for path in paths if path.exists()), None)


def _markdown_cell(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def _read_json(path: Path) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
