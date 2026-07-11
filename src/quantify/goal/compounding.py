"""Compounding-path review for the first-million capital objective."""
from __future__ import annotations

import json
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any, Literal

from quantify.goal.planner import CapitalGoal

CompoundingDecision = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class CompoundingPathFinding:
    severity: CompoundingDecision
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class CompoundingPathReview:
    decision: CompoundingDecision
    goal: dict[str, float | int]
    report_dir: str
    selected_candidate: str
    projected_capital_at_horizon: float
    capital_shortfall: float
    evidence: dict[str, str]
    findings: list[CompoundingPathFinding]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "goal": self.goal,
            "report_dir": self.report_dir,
            "selected_candidate": self.selected_candidate,
            "projected_capital_at_horizon": self.projected_capital_at_horizon,
            "capital_shortfall": self.capital_shortfall,
            "evidence": self.evidence,
            "findings": [finding.to_dict() for finding in self.findings],
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Compounding Path Review: {self.decision}",
            "",
            f"- Report directory: `{self.report_dir}`",
            f"- Selected candidate: `{self.selected_candidate or 'none'}`",
            f"- Starting capital: {float(self.goal['starting_capital']):.2f}",
            f"- Target capital: {float(self.goal['target_capital']):.2f}",
            f"- Horizon years: {float(self.goal['years']):.1f}",
            f"- Required annual return: {float(self.goal['required_annual_return']):.2%}",
            f"- Projected capital at horizon: {self.projected_capital_at_horizon:.2f}",
            f"- Capital shortfall: {self.capital_shortfall:.2f}",
            "",
            "This review checks whether current evidence can support the capital path. It is not a profit guarantee.",
            "",
            "## Evidence",
        ]
        lines.extend(f"- {key}: `{value}`" for key, value in self.evidence.items())
        lines.extend(["", "## Findings"])
        lines.extend(
            f"- `{finding.severity}` `{finding.code}`: {finding.message}"
            for finding in self.findings
        )
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_compounding_path_review(
    report_dir: str | Path,
    *,
    goal: CapitalGoal,
    min_paper_days: int = 40,
    min_sharpe: float = 0.8,
) -> CompoundingPathReview:
    root = Path(report_dir)
    selection = _read_json(root / "candidate_selection.json")
    completion = _read_json(root / "candidate_experiment_completion.json")
    launch = _read_json(root / "candidate_experiment_launch.json")
    readiness = _read_json(root / "candidate_experiment_readiness.json")
    goal_status = _read_json(root / "goal" / "capital_goal_status.json")
    paper_stability = _read_json(root / "paper_stability.json")
    approval = _read_json(root / "approval_record.json")
    strategy_brief = _read_json(root / "first_million_strategy_brief.json")

    selected_candidate = _selected_candidate(selection, launch)
    candidate_payload = _candidate_payload(selection, selected_candidate)
    metrics = _dict_payload(candidate_payload.get("metrics"))
    annual_return = _float(metrics.get("annualized_return"))
    max_drawdown = _float(metrics.get("max_drawdown"))
    sharpe = _float(metrics.get("sharpe_ratio"))
    projected = _projected_capital(goal, annual_return)
    findings = _findings(
        goal=goal,
        selected_candidate=selected_candidate,
        annual_return=annual_return,
        max_drawdown=max_drawdown,
        sharpe=sharpe,
        selection=selection,
        completion=completion,
        launch=launch,
        readiness=readiness,
        goal_status=goal_status,
        paper_stability=paper_stability,
        approval=approval,
        strategy_brief=strategy_brief,
        min_paper_days=min_paper_days,
        min_sharpe=min_sharpe,
    )
    decision = _combine([finding.severity for finding in findings])
    return CompoundingPathReview(
        decision=decision,
        goal=goal.to_dict(),
        report_dir=str(root),
        selected_candidate=selected_candidate,
        projected_capital_at_horizon=projected,
        capital_shortfall=max(float(goal.target_capital) - projected, 0.0),
        evidence={
            "candidate_selection": str(selection.get("status", "MISSING") or "MISSING"),
            "candidate_experiment_launch": str(launch.get("decision", "MISSING") or "MISSING"),
            "candidate_experiment_completion": str(completion.get("decision", "MISSING") or "MISSING"),
            "candidate_experiment_readiness": str(readiness.get("decision", "MISSING") or "MISSING"),
            "capital_goal_status": str(goal_status.get("decision", "MISSING") or "MISSING"),
            "paper_stability": str(paper_stability.get("status", "MISSING") or "MISSING"),
            "approval_record": "PASS" if approval else "MISSING",
            "strategy_brief": str(strategy_brief.get("decision", "MISSING") or "MISSING"),
        },
        findings=findings,
        next_actions=_next_actions(findings),
        prohibited_actions=[
            "Do not claim the strategy can compound to the target until this review is PASS.",
            "Do not use a single backtest or missing candidate selection as capital-path evidence.",
            "Do not scale capital while paper stability or human approval is missing.",
            "Do not connect this review to real broker order submission.",
            "Do not let LLM output override this deterministic review.",
        ],
    )


def write_compounding_path_review(review: CompoundingPathReview, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "compounding_path_review.json").write_text(
        json.dumps(review.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "compounding_path_review.md").write_text(review.to_markdown(), encoding="utf-8")
    return root


def _findings(
    *,
    goal: CapitalGoal,
    selected_candidate: str,
    annual_return: float,
    max_drawdown: float,
    sharpe: float,
    selection: dict[str, Any],
    completion: dict[str, Any],
    launch: dict[str, Any],
    readiness: dict[str, Any],
    goal_status: dict[str, Any],
    paper_stability: dict[str, Any],
    approval: dict[str, Any],
    strategy_brief: dict[str, Any],
    min_paper_days: int,
    min_sharpe: float,
) -> list[CompoundingPathFinding]:
    findings: list[CompoundingPathFinding] = []
    if not selected_candidate:
        findings.append(
            CompoundingPathFinding(
                "BLOCK",
                "NO_SELECTED_CANDIDATE",
                "No selected candidate exists; run guarded candidate selection after data gates pass.",
            )
        )
    if str(selection.get("status", "")).upper() != "PASS":
        findings.append(
            CompoundingPathFinding(
                "BLOCK",
                "CANDIDATE_SELECTION_NOT_PASS",
                "candidate_selection.json is missing or not PASS.",
            )
        )
    if str(readiness.get("decision", "")).upper() == "BLOCK":
        findings.append(
            CompoundingPathFinding(
                "BLOCK",
                "EXPERIMENT_READINESS_BLOCK",
                "Candidate experiment readiness is BLOCK.",
            )
        )
    if str(launch.get("decision", "")).upper() != "PASS":
        findings.append(
            CompoundingPathFinding(
                "BLOCK",
                "EXPERIMENT_LAUNCH_NOT_PASS",
                "Candidate experiment launch is missing or not PASS.",
            )
        )
    if str(completion.get("decision", "")).upper() != "PASS":
        findings.append(
            CompoundingPathFinding(
                "BLOCK",
                "EXPERIMENT_COMPLETION_NOT_PASS",
                "Candidate experiment completion is missing or not PASS.",
            )
        )
    if str(goal_status.get("decision", "")).upper() != "PASS":
        issue = _first_issue(goal_status)
        suffix = f" First blocker: {issue}" if issue else ""
        findings.append(
            CompoundingPathFinding(
                "BLOCK",
                "CAPITAL_GOAL_STATUS_NOT_PASS",
                f"capital_goal_status.json is missing or not PASS.{suffix}",
            )
        )
    if annual_return < goal.required_annual_return():
        findings.append(
            CompoundingPathFinding(
                "WATCH" if selected_candidate else "BLOCK",
                "RETURN_BELOW_REQUIRED_PATH",
                "Selected candidate annualized return is below the required compounding path.",
            )
        )
    if max_drawdown > goal.max_drawdown_budget:
        findings.append(
            CompoundingPathFinding(
                "BLOCK",
                "DRAWDOWN_OVER_BUDGET",
                "Selected candidate drawdown exceeds the capital-goal drawdown budget.",
            )
        )
    if sharpe < min_sharpe:
        findings.append(
            CompoundingPathFinding(
                "WATCH" if selected_candidate else "BLOCK",
                "SHARPE_BELOW_MINIMUM",
                f"Selected candidate Sharpe is below {min_sharpe:.2f}.",
            )
        )
    observed_days = int(paper_stability.get("observed_days", 0) or 0)
    if str(paper_stability.get("status", "")).upper() != "PASS" or observed_days < min_paper_days:
        findings.append(
            CompoundingPathFinding(
                "BLOCK",
                "PAPER_STABILITY_MISSING",
                f"Paper stability is not PASS with at least {min_paper_days} observed days.",
            )
        )
    if not _approval_complete(approval):
        findings.append(
            CompoundingPathFinding(
                "BLOCK",
                "HUMAN_APPROVAL_MISSING",
                "A complete approval_record.json is required before treating the path as deployable.",
            )
        )
    if str(strategy_brief.get("decision", "")).upper() in {"PREPARE_DATA", "PAUSE"}:
        findings.append(
            CompoundingPathFinding(
                "BLOCK",
                "STRATEGY_BRIEF_NOT_RUNNABLE",
                "First-million strategy brief is not in a runnable research state.",
            )
        )
    if not findings:
        findings.append(
            CompoundingPathFinding(
                "PASS",
                "COMPOUNDING_PATH_REVIEW_REQUIRED",
                "Evidence supports deeper manual review of the compounding path; this is still not a profit guarantee.",
            )
        )
    return findings


def _next_actions(findings: list[CompoundingPathFinding]) -> list[str]:
    codes = {finding.code for finding in findings}
    actions: list[str] = []
    if "NO_SELECTED_CANDIDATE" in codes or "CANDIDATE_SELECTION_NOT_PASS" in codes:
        actions.append("Complete real-data candidate experiments and candidate_selection.json before capital-path review.")
    if "EXPERIMENT_READINESS_BLOCK" in codes or "EXPERIMENT_LAUNCH_NOT_PASS" in codes:
        actions.append("Resolve candidate experiment readiness and launch blockers.")
    if "EXPERIMENT_COMPLETION_NOT_PASS" in codes:
        actions.append("Execute the guarded candidate experiment and complete every required output.")
    if "CAPITAL_GOAL_STATUS_NOT_PASS" in codes:
        actions.append("Resolve capital_goal_status blockers, starting with data/source gates.")
    if "RETURN_BELOW_REQUIRED_PATH" in codes:
        actions.append("Reject or keep researching candidates whose verified return is below the compounding path.")
    if "PAPER_STABILITY_MISSING" in codes:
        actions.append("Run 4-8 weeks of paper observation and produce paper_stability.json/md.")
    if "HUMAN_APPROVAL_MISSING" in codes:
        actions.append("Record human approval only after deterministic data, research, and paper gates pass.")
    if "STRATEGY_BRIEF_NOT_RUNNABLE" in codes:
        actions.append("Follow first_million_strategy_brief next actions before pursuing compounding claims.")
    return _dedupe(actions) or ["Continue evidence accumulation; do not increase capital without a fresh review."]


def _selected_candidate(selection: dict[str, Any], launch: dict[str, Any]) -> str:
    return str(
        selection.get("selected_candidate")
        or selection.get("best_candidate")
        or launch.get("selected_candidate")
        or ""
    )


def _candidate_payload(selection: dict[str, Any], selected_candidate: str) -> dict[str, Any]:
    results = selection.get("results", []) or []
    for item in results:
        if isinstance(item, dict) and str(item.get("name", "")) == selected_candidate:
            return item
    return results[0] if results and isinstance(results[0], dict) else {}


def _projected_capital(goal: CapitalGoal, annual_return: float) -> float:
    if annual_return <= -1:
        return 0.0
    return float(goal.starting_capital) * ((1.0 + annual_return) ** float(goal.years))


def _approval_complete(approval: dict[str, Any]) -> bool:
    return bool(
        approval.get("approval_required") is True
        and str(approval.get("approved_by", "")).strip()
        and str(approval.get("approved_at", "")).strip()
        and str(approval.get("approval_notes", "")).strip()
    )


def _first_issue(payload: dict[str, Any]) -> str:
    for key in ("blockers", "watch_items", "next_actions"):
        values = payload.get(key)
        if isinstance(values, list):
            for value in values:
                text = str(value or "").strip()
                if text:
                    return text
    evidence = payload.get("evidence")
    if isinstance(evidence, list):
        for item in evidence:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "").upper()
            if status == "PASS":
                continue
            name = str(item.get("name") or "evidence")
            message = str(item.get("message") or status or "requires review")
            return f"{name}: {message}"
    return ""


def _combine(severities: list[CompoundingDecision]) -> CompoundingDecision:
    if any(severity == "BLOCK" for severity in severities):
        return "BLOCK"
    if any(severity == "WATCH" for severity in severities):
        return "WATCH"
    return "PASS"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _dict_payload(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(value: object) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    return out if isfinite(out) else 0.0


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
