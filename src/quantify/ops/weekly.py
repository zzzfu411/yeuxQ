"""Weekly operating review for research-to-paper quant workflows."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

WeeklyDecision = Literal["continue_paper", "research_only", "pause_and_fix"]
ComponentStatus = Literal["PASS", "WATCH", "BLOCK", "MISSING", "UNKNOWN"]


@dataclass(frozen=True, slots=True)
class WeeklyReviewComponent:
    name: str
    status: ComponentStatus
    source_file: str
    summary: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "source_file": self.source_file,
            "summary": self.summary,
        }


@dataclass(frozen=True, slots=True)
class WeeklyReview:
    as_of: str
    report_dir: str
    decision: WeeklyDecision
    components: list[WeeklyReviewComponent]
    research_focus: dict[str, Any]
    blockers: list[str]
    watch_items: list[str]
    required_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "report_dir": self.report_dir,
            "decision": self.decision,
            "components": [component.to_dict() for component in self.components],
            "research_focus": self.research_focus,
            "blockers": self.blockers,
            "watch_items": self.watch_items,
            "required_actions": self.required_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Weekly Quant Review: {self.decision}",
            "",
            f"- As of: `{self.as_of}`",
            f"- Report directory: `{self.report_dir}`",
            "",
            "## Research Focus",
            "",
            f"- Source: `{self.research_focus.get('artifact_type', 'recent_candidate_research')}`",
            f"- Candidate: `{self.research_focus.get('best_research_candidate', 'none')}`",
            f"- Reason: {self.research_focus.get('best_research_reason', 'No recent research focus is available.')}",
            f"- Command: `{self.research_focus.get('best_research_command', 'none')}`",
            f"- Advisory only: `{not bool(self.research_focus.get('can_enter_paper', False))}`",
            "",
            "## Evidence Matrix",
            "",
            "| component | status | source | summary |",
            "| --- | --- | --- | --- |",
        ]
        for component in self.components:
            lines.append(
                f"| {component.name} | `{component.status}` | `{component.source_file}` | {component.summary} |"
            )

        lines.extend(["", "## Blockers"])
        lines.extend(f"- {item}" for item in self.blockers) if self.blockers else lines.append("- None.")
        lines.extend(["", "## Watch Items"])
        lines.extend(f"- {item}" for item in self.watch_items) if self.watch_items else lines.append("- None.")
        lines.extend(["", "## Required Actions"])
        lines.extend(f"- {item}" for item in self.required_actions)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_weekly_review(report_dir: str | Path, *, as_of: str | None = None) -> WeeklyReview:
    root = Path(report_dir)
    research_focus = _read_json(root / "recent_candidate_research.json")
    components = [
        _component(root, "real_data_bootstrap", "real_data_bootstrap.json", status_key="decision"),
        _component(root, "real_data_gate", "real_data_gate.json", status_key="decision"),
        _component(root, "data_coverage", "data_coverage.json", status_key="status"),
        _component(root, "data_audit", "data_audit.json", status_key="status"),
        _component(root, "market_regime", "market_regime.json", status_key="status"),
        _component(root, "robustness", "robustness_report.json", status_key="status"),
        _component(root, "walk_forward", "walk_forward_report.json", status_key="status"),
        _component(root, "candidate_walk_forward", "candidate_walk_forward_report.json", status_key="status"),
        _component(root, "candidate_factor_diagnostics", "candidate_factor_diagnostics.json", status_key="status"),
        _component(
            root,
            "candidate_regime_validation",
            "candidate_regime_validation_report.json",
            status_key="status",
        ),
        _component(root, "candidate_experiment_launch", "candidate_experiment_launch.json", status_key="decision"),
        _component(
            root,
            "candidate_experiment_completion",
            "candidate_experiment_completion.json",
            status_key="decision",
        ),
        _component(root, "candidate_selection", "candidate_selection.json", status_key="status"),
        _component(root, "recent_candidate_research", "recent_candidate_research.json", status_key="status"),
        _component(root, "llm_review", "llm_review.json", status_key="decision"),
        _component(root, "paper_state", "paper_state.json", status_key=None),
        _component(root, "paper_daily_review", "paper_daily_review.json", status_key="status"),
        _component(root, "paper_stability", "paper_stability.json", status_key="status"),
        _component(root, "readiness", "micro_live_readiness.json", status_key="decision"),
    ]
    blockers = _blockers(components)
    watch_items = _watch_items(components)
    decision = _decision(components)
    return WeeklyReview(
        as_of=as_of or date.today().isoformat(),
        report_dir=str(root),
        decision=decision,
        components=components,
        research_focus=research_focus,
        blockers=blockers,
        watch_items=watch_items,
        required_actions=_required_actions(decision, components),
        prohibited_actions=_prohibited_actions(),
    )


def write_weekly_review(report_dir: str | Path, *, as_of: str | None = None) -> Path:
    root = Path(report_dir)
    root.mkdir(parents=True, exist_ok=True)
    review = build_weekly_review(root, as_of=as_of)
    (root / "weekly_review.json").write_text(
        json.dumps(review.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "weekly_review.md").write_text(review.to_markdown(), encoding="utf-8")
    return root


def _component(
    root: Path,
    name: str,
    filename: str,
    *,
    status_key: str | None,
) -> WeeklyReviewComponent:
    path = root / filename
    if not path.exists():
        return WeeklyReviewComponent(
            name=name,
            status="MISSING",
            source_file=filename,
            summary=f"{filename} is missing.",
        )
    payload = _read_json(path)
    if not payload:
        return WeeklyReviewComponent(
            name=name,
            status="UNKNOWN",
            source_file=filename,
            summary=f"{filename} could not be parsed or is empty.",
        )
    if name == "paper_state":
        return _paper_component(filename, payload)
    if name == "recent_candidate_research":
        return _recent_research_component(filename, payload)
    status = _normalize_status(payload.get(status_key or "status"))
    return WeeklyReviewComponent(
        name=name,
        status=status,
        source_file=filename,
        summary=_summary(name, payload, status),
    )


def _paper_component(filename: str, payload: dict[str, Any]) -> WeeklyReviewComponent:
    broker = str(payload.get("broker_connection", "none"))
    observed_days = int(payload.get("observed_days", 0) or 0)
    if broker not in {"", "none"}:
        status: ComponentStatus = "BLOCK"
        summary = "Paper state reports a broker connection; this violates the manual-only boundary."
    elif observed_days < 20:
        status = "WATCH"
        summary = f"Paper run has only {observed_days} observed days; 20+ are required for this weekly gate."
    else:
        status = "PASS"
        summary = f"Paper run has {observed_days} observed days and no broker connection."
    return WeeklyReviewComponent(
        name="paper_state",
        status=status,
        source_file=filename,
        summary=summary,
    )


def _recent_research_component(filename: str, payload: dict[str, Any]) -> WeeklyReviewComponent:
    candidate_count = int(payload.get("candidate_count", 0) or 0)
    status: ComponentStatus = "PASS" if candidate_count > 0 else "WATCH"
    return WeeklyReviewComponent(
        name="recent_candidate_research",
        status=status,
        source_file=filename,
        summary=_summary("recent_candidate_research", payload, status),
    )


def _summary(name: str, payload: dict[str, Any], status: ComponentStatus) -> str:
    if name == "market_regime":
        label = payload.get("label", "unknown")
        return f"Market regime is {label}; status {status}."
    if name == "candidate_selection":
        selected = payload.get("selected_candidate") or payload.get("best_candidate") or "none"
        top = payload.get("top_candidate") or selected
        return f"Selected candidate is {selected or 'none'}; top={top or 'none'}; selection status {status}."
    if name == "recent_candidate_research":
        best = payload.get("best_research_candidate", "none")
        candidates = payload.get("candidate_count", 0)
        reports = payload.get("report_count", 0)
        return (
            f"Recent research focus is {best or 'none'}; candidates={candidates}, "
            f"reports={reports}; advisory only."
        )
    if name == "llm_review":
        missing_count = len(payload.get("missing_evidence", []) or [])
        next_count = len(payload.get("next_experiments", []) or [])
        return f"Deterministic review is {status}; missing evidence={missing_count}, next experiments={next_count}."
    if name == "readiness":
        finding_count = len(payload.get("findings", []) or [])
        issue = _first_issue(payload)
        suffix = f"; {issue}" if issue else ""
        return f"Micro-live readiness decision is {status}; findings={finding_count}{suffix}."
    if name == "paper_stability":
        observed = payload.get("observed_days", "unknown")
        drawdown = float(payload.get("max_drawdown", 0.0) or 0.0)
        reject = float(payload.get("reject_rate", 0.0) or 0.0)
        return f"Paper stability is {status}; observed_days={observed}, drawdown={drawdown:.2%}, reject_rate={reject:.2%}."
    if name == "paper_daily_review":
        state = payload.get("state", {}) or {}
        execution = payload.get("execution_quality", {}) or {}
        deviation = payload.get("target_deviation", {}) or {}
        equity = float(state.get("last_equity", 0.0) or 0.0)
        cash = float(state.get("cash", state.get("cash_estimate", 0.0)) or 0.0)
        cash_weight = cash / equity if equity else 0.0
        latest_rejected = int(execution.get("latest_rejected_order_count", 0) or 0)
        max_deviation = float(deviation.get("max_abs_target_deviation", 0.0) or 0.0)
        return (
            f"Paper daily review is {status}; equity={equity:.2f}, cash_weight={cash_weight:.2%}, "
            f"positions={state.get('position_count', 'unknown')}, latest_rejected={latest_rejected}, "
            f"max_target_deviation={max_deviation:.2%}."
        )
    if name == "robustness":
        scenario_count = len(payload.get("scenarios", []) or [])
        return f"Robustness status is {status}; scenarios={scenario_count}."
    if name == "walk_forward":
        window_count = payload.get("window_count", "unknown")
        pass_count = payload.get("pass_count", "unknown")
        return f"Walk-forward status is {status}; windows={window_count}, pass_count={pass_count}."
    if name == "candidate_walk_forward":
        best = payload.get("best_candidate", "none")
        candidates = payload.get("candidate_count", "unknown")
        return f"Candidate walk-forward is {status}; best={best or 'none'}, candidates={candidates}."
    if name == "candidate_factor_diagnostics":
        candidates = payload.get("candidate_count", "unknown")
        warnings = len(payload.get("warnings", []) or [])
        return f"Candidate factor diagnostics is {status}; candidates={candidates}, warnings={warnings}."
    if name == "candidate_regime_validation":
        best = payload.get("best_candidate", "none")
        regimes = payload.get("regime_count", "unknown")
        windows = payload.get("window_count", "unknown")
        return (
            f"Candidate regime validation is {status}; best={best or 'none'}, "
            f"regimes={regimes}, windows={windows}."
        )
    if name == "candidate_experiment_launch":
        candidate = payload.get("selected_candidate", "none")
        run_id = payload.get("run_id", "none")
        blockers = len(payload.get("blocked_by", []) or [])
        return (
            f"Candidate experiment launch is {status}; candidate={candidate or 'none'}, "
            f"run_id={run_id or 'none'}, blockers={blockers}."
        )
    if name == "candidate_experiment_completion":
        candidate = payload.get("selected_candidate", "none")
        blockers = len(payload.get("blockers", []) or [])
        watches = len(payload.get("watch_items", []) or [])
        return (
            f"Candidate experiment completion is {status}; candidate={candidate or 'none'}, "
            f"blockers={blockers}, watch_items={watches}."
        )
    if name == "data_audit":
        finding_count = len(payload.get("findings", []) or [])
        demo = payload.get("demo_data_used", "unknown")
        return f"Data audit status is {status}; findings={finding_count}, demo_data_used={demo}."
    if name == "data_coverage":
        avg = float(payload.get("average_coverage_ratio", 0.0) or 0.0)
        short = payload.get("short_history_symbol_count", "unknown")
        stale = payload.get("stale_symbol_count", "unknown")
        return f"Data coverage is {status}; avg_coverage={avg:.2%}, short_symbols={short}, stale_symbols={stale}."
    if name == "real_data_bootstrap":
        cache_exists = payload.get("cache_exists", "unknown")
        demo_fallback = payload.get("allow_demo_data", "unknown")
        latest = payload.get("latest_bar_date", "missing")
        return (
            f"Real-data bootstrap is {status}; cache_exists={cache_exists}, "
            f"allow_demo_data={demo_fallback}, latest_bar_date={latest}."
        )
    if name == "real_data_gate":
        latest = payload.get("latest_bar_date", "missing")
        staleness = payload.get("staleness_days", "n/a")
        return f"Real-data gate is {status}; latest_bar_date={latest}, staleness_days={staleness}."
    return f"{name} status is {status}."


def _decision(components: list[WeeklyReviewComponent]) -> WeeklyDecision:
    statuses = [component.status for component in components]
    if any(status == "BLOCK" for status in statuses):
        return "pause_and_fix"
    missing_required = {
        component.name
        for component in components
        if component.status in {"MISSING", "UNKNOWN"} and component.name != "readiness"
    }
    if missing_required:
        return "pause_and_fix"
    if any(status in {"WATCH", "MISSING", "UNKNOWN"} for status in statuses):
        return "research_only"
    return "continue_paper"


def _blockers(components: list[WeeklyReviewComponent]) -> list[str]:
    blockers = []
    for component in components:
        if component.status == "BLOCK" or component.status in {"MISSING", "UNKNOWN"} and component.name != "readiness":
            blockers.append(f"{component.name}: {component.summary}")
    return blockers


def _watch_items(components: list[WeeklyReviewComponent]) -> list[str]:
    return [
        f"{component.name}: {component.summary}"
        for component in components
        if component.status in {"WATCH", "MISSING", "UNKNOWN"} and component.name == "readiness"
        or component.status == "WATCH"
    ]


def _required_actions(
    decision: WeeklyDecision,
    components: list[WeeklyReviewComponent],
) -> list[str]:
    if decision == "pause_and_fix":
        actions = [
            "Fix BLOCK or missing evidence before the next weekly review.",
            "Keep the strategy in research/paper-only mode.",
            "Write a short post-mortem for each blocker and rerun the affected gate.",
        ]
    elif decision == "research_only":
        actions = [
            "Run the missing experiments and keep candidate strategies out of promotion.",
            "Continue paper observation without increasing capital or broker connectivity.",
            "Review WATCH items before the next rebalance.",
        ]
    else:
        actions = [
            "Continue paper observation with the current risk budget.",
            "Do not change capital, broker connectivity, or strategy parameters without a new review.",
            "Prepare the next weekly review after the next data update.",
        ]
    if any(component.name == "readiness" and component.status in {"MISSING", "WATCH"} for component in components):
        actions.append("Readiness is not fully proven; do not generate live broker instructions.")
    return actions


def _prohibited_actions() -> list[str]:
    return [
        "Do not submit unattended live broker orders.",
        "Do not let LLM advisory text upgrade deterministic decisions.",
        "Do not increase capital after a single weekly report.",
        "Do not treat candidate ranking as a promise of profit or a live trading instruction.",
    ]


def _first_issue(payload: dict[str, Any]) -> str:
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
            if not isinstance(finding, dict):
                continue
            code = str(finding.get("code") or "").strip()
            message = str(finding.get("message") or "").strip()
            if code and message:
                return f"{code}: {message}"
            if message:
                return message
    return ""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _normalize_status(value: object) -> ComponentStatus:
    text = str(value or "").upper()
    if text in {"PASS", "WATCH", "BLOCK"}:
        return text  # type: ignore[return-value]
    return "UNKNOWN"
