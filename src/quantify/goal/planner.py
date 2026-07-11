"""Convert a wealth target into measurable quant-system requirements."""
from __future__ import annotations

from dataclasses import dataclass
import json
from math import isfinite
from pathlib import Path
from typing import Any, Literal

StrategyDecision = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class CapitalGoal:
    target_capital: float = 1_000_000.0
    starting_capital: float = 100_000.0
    years: float = 5.0
    max_drawdown_budget: float = 0.20
    min_safety_cash_months: int = 12

    def required_annual_return(self) -> float:
        if self.starting_capital <= 0 or self.target_capital <= self.starting_capital:
            return 0.0
        return (self.target_capital / self.starting_capital) ** (1 / self.years) - 1

    def to_dict(self) -> dict[str, float | int]:
        return {
            "target_capital": self.target_capital,
            "starting_capital": self.starting_capital,
            "years": self.years,
            "required_annual_return": self.required_annual_return(),
            "max_drawdown_budget": self.max_drawdown_budget,
            "min_safety_cash_months": self.min_safety_cash_months,
        }


@dataclass(frozen=True, slots=True)
class CapitalGoalPlan:
    goal: CapitalGoal
    status: StrategyDecision
    feasibility_notes: list[str]
    operating_rules: list[str]
    yearly_path: list[dict[str, float]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal.to_dict(),
            "status": self.status,
            "feasibility_notes": self.feasibility_notes,
            "operating_rules": self.operating_rules,
            "yearly_path": self.yearly_path,
        }

    def to_markdown(self) -> str:
        required = self.goal.required_annual_return()
        lines = [
            f"# Capital Goal Plan: {self.status}",
            "",
            f"- Target capital: {self.goal.target_capital:.2f}",
            f"- Starting capital: {self.goal.starting_capital:.2f}",
            f"- Horizon years: {self.goal.years:.1f}",
            f"- Required annual return: {required:.2%}",
            f"- Max drawdown budget: {self.goal.max_drawdown_budget:.2%}",
            "",
            "## Feasibility Notes",
        ]
        lines.extend(f"- {note}" for note in self.feasibility_notes)
        lines.extend(["", "## Operating Rules"])
        lines.extend(f"- {rule}" for rule in self.operating_rules)
        lines.extend(["", "## Yearly Path", ""])
        lines.append("| year | capital | cumulative_return |")
        lines.append("| ---: | ---: | ---: |")
        for row in self.yearly_path:
            lines.append(
                f"| {int(row['year'])} | {row['capital']:.2f} | {row['cumulative_return']:.2%} |"
            )
        return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class StrategyCandidateScore:
    decision: StrategyDecision
    score: float
    reasons: list[str]
    metrics: dict[str, float | int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "score": self.score,
            "reasons": self.reasons,
            "metrics": self.metrics,
        }


def build_capital_goal_plan(goal: CapitalGoal) -> CapitalGoalPlan:
    required = goal.required_annual_return()
    notes = []
    status: StrategyDecision = "PASS"
    if required > 0.35:
        status = "BLOCK"
        notes.append(
            "Required annual return is above 35%; this is not a stable compounding target for a first live system."
        )
    elif required > 0.20:
        status = "WATCH"
        notes.append(
            "Required annual return is above 20%; treat this as an aggressive research target, not a promise."
        )
    else:
        notes.append("Required annual return is within a range that can be researched cautiously.")

    notes.append("No strategy should be promoted unless it survives out-of-sample and cost stress tests.")
    rules = [
        "Keep emergency cash outside the strategy capital.",
        "Use A-share daily, long-only, no leverage strategies first.",
        "Stop promotion when deterministic gates return BLOCK.",
        "Require paper trading evidence before any manual micro-live reference sheet.",
        "Do not increase capital without a new data audit, robustness report, and approval record.",
    ]
    return CapitalGoalPlan(
        goal=goal,
        status=status,
        feasibility_notes=notes,
        operating_rules=rules,
        yearly_path=_yearly_path(goal),
    )


def screen_strategy_candidate(
    metrics: dict[str, float | int],
    *,
    goal: CapitalGoal,
    reject_rate: float = 0.0,
    robustness_status: str = "UNKNOWN",
    data_audit_status: str = "UNKNOWN",
) -> StrategyCandidateScore:
    reasons = []
    score = 100.0
    annual_return = _float(metrics.get("annualized_return", 0.0))
    max_drawdown = _float(metrics.get("max_drawdown", 0.0))
    sharpe = _float(metrics.get("sharpe_ratio", 0.0))
    required = goal.required_annual_return()

    if data_audit_status == "BLOCK" or robustness_status == "BLOCK":
        reasons.append("Data audit or robustness report is BLOCK.")
        score -= 50
    if annual_return < required:
        reasons.append("Annualized return is below the required capital-goal path.")
        score -= 25
    if max_drawdown > goal.max_drawdown_budget:
        reasons.append("Max drawdown exceeds the drawdown budget.")
        score -= 25
    if sharpe < 0.8:
        reasons.append("Sharpe ratio is below the minimum watch level for compounding research.")
        score -= 15
    if reject_rate >= 0.20:
        reasons.append("Order rejection rate is too high for a stable paper workflow.")
        score -= 15
    if robustness_status == "WATCH" or data_audit_status == "WATCH":
        reasons.append("Data audit or robustness report has WATCH findings.")
        score -= 10

    decision: StrategyDecision
    if score < 50 or data_audit_status == "BLOCK" or robustness_status == "BLOCK":
        decision = "BLOCK"
    elif score < 80 or reasons:
        decision = "WATCH"
    else:
        decision = "PASS"
    return StrategyCandidateScore(
        decision=decision,
        score=max(score, 0.0),
        reasons=reasons or ["Candidate satisfies the current capital-goal research thresholds."],
        metrics={
            "annualized_return": annual_return,
            "required_annual_return": required,
            "max_drawdown": max_drawdown,
            "drawdown_budget": goal.max_drawdown_budget,
            "sharpe_ratio": sharpe,
            "reject_rate": reject_rate,
        },
    )


def write_goal_plan(plan: CapitalGoalPlan, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "capital_goal_plan.json").write_text(
        json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "capital_goal_plan.md").write_text(plan.to_markdown(), encoding="utf-8")
    return root


def _yearly_path(goal: CapitalGoal) -> list[dict[str, float]]:
    required = goal.required_annual_return()
    rows = []
    for year in range(0, int(goal.years) + 1):
        capital = goal.starting_capital * ((1 + required) ** year)
        rows.append(
            {
                "year": float(year),
                "capital": capital,
                "cumulative_return": capital / goal.starting_capital - 1,
            }
        )
    if goal.years % 1:
        capital = goal.starting_capital * ((1 + required) ** goal.years)
        rows.append(
            {
                "year": goal.years,
                "capital": capital,
                "cumulative_return": capital / goal.starting_capital - 1,
            }
        )
    return rows


def _float(value: float | int | object) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    return out if isfinite(out) else 0.0
