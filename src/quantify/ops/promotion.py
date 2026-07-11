"""Promotion review for strategy registry candidates."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal

from quantify.goal import CapitalGoal

PromotionDecision = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class StrategyPromotionFinding:
    severity: PromotionDecision
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class StrategyPromotionCandidate:
    name: str
    decision: PromotionDecision
    real_observations: int
    real_pass_count: int
    real_candidate_walk_forward_observations: int
    real_candidate_walk_forward_pass_count: int
    real_candidate_walk_forward_pass_ratio: float
    real_candidate_walk_forward_positive_return_ratio: float
    real_worst_candidate_walk_forward_return: float
    real_worst_candidate_walk_forward_drawdown: float
    real_candidate_regime_observations: int
    real_candidate_regime_pass_count: int
    real_candidate_regime_adverse_windows: float
    real_avg_annualized_return: float
    required_annual_return: float
    real_avg_max_drawdown: float
    drawdown_budget: float
    real_avg_sharpe_ratio: float
    findings: list[StrategyPromotionFinding]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "decision": self.decision,
            "real_observations": self.real_observations,
            "real_pass_count": self.real_pass_count,
            "real_candidate_walk_forward_observations": self.real_candidate_walk_forward_observations,
            "real_candidate_walk_forward_pass_count": self.real_candidate_walk_forward_pass_count,
            "real_candidate_walk_forward_pass_ratio": self.real_candidate_walk_forward_pass_ratio,
            "real_candidate_walk_forward_positive_return_ratio": self.real_candidate_walk_forward_positive_return_ratio,
            "real_worst_candidate_walk_forward_return": self.real_worst_candidate_walk_forward_return,
            "real_worst_candidate_walk_forward_drawdown": self.real_worst_candidate_walk_forward_drawdown,
            "real_candidate_regime_observations": self.real_candidate_regime_observations,
            "real_candidate_regime_pass_count": self.real_candidate_regime_pass_count,
            "real_candidate_regime_adverse_windows": self.real_candidate_regime_adverse_windows,
            "real_avg_annualized_return": self.real_avg_annualized_return,
            "required_annual_return": self.required_annual_return,
            "real_avg_max_drawdown": self.real_avg_max_drawdown,
            "drawdown_budget": self.drawdown_budget,
            "real_avg_sharpe_ratio": self.real_avg_sharpe_ratio,
            "findings": [finding.to_dict() for finding in self.findings],
        }


@dataclass(frozen=True, slots=True)
class StrategyPromotionReview:
    decision: PromotionDecision
    goal: dict[str, float | int]
    registry_path: str
    candidates: list[StrategyPromotionCandidate]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "goal": self.goal,
            "registry_path": self.registry_path,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Strategy Promotion Review: {self.decision}",
            "",
            f"- Registry path: `{self.registry_path}`",
            f"- Required annual return: {float(self.goal['required_annual_return']):.2%}",
            f"- Drawdown budget: {float(self.goal['max_drawdown_budget']):.2%}",
            "",
            "| candidate | decision | real_obs | real_pass | cwf_obs | cwf_pass | cwf_pass_ratio | cwf_positive | cwf_worst_return | cwf_worst_drawdown | regime_obs | regime_pass | adverse_windows | real_return | required_return | real_drawdown | drawdown_budget | sharpe |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for candidate in self.candidates:
            lines.append(
                "| {name} | `{decision}` | {obs} | {passes} | {cwf_obs} | {cwf_pass} | {cwf_ratio:.2%} | {cwf_positive:.2%} | {cwf_worst_return:.2%} | {cwf_worst_drawdown:.2%} | {regime_obs} | {regime_pass} | {adverse:.1f} | {ret:.2%} | {req:.2%} | {dd:.2%} | {budget:.2%} | {sharpe:.2f} |".format(
                    name=candidate.name,
                    decision=candidate.decision,
                    obs=candidate.real_observations,
                    passes=candidate.real_pass_count,
                    cwf_obs=candidate.real_candidate_walk_forward_observations,
                    cwf_pass=candidate.real_candidate_walk_forward_pass_count,
                    cwf_ratio=candidate.real_candidate_walk_forward_pass_ratio,
                    cwf_positive=candidate.real_candidate_walk_forward_positive_return_ratio,
                    cwf_worst_return=candidate.real_worst_candidate_walk_forward_return,
                    cwf_worst_drawdown=candidate.real_worst_candidate_walk_forward_drawdown,
                    regime_obs=candidate.real_candidate_regime_observations,
                    regime_pass=candidate.real_candidate_regime_pass_count,
                    adverse=candidate.real_candidate_regime_adverse_windows,
                    ret=candidate.real_avg_annualized_return,
                    req=candidate.required_annual_return,
                    dd=candidate.real_avg_max_drawdown,
                    budget=candidate.drawdown_budget,
                    sharpe=candidate.real_avg_sharpe_ratio,
                )
            )
        lines.extend(["", "## Findings"])
        for candidate in self.candidates:
            lines.append(f"- `{candidate.name}`")
            for finding in candidate.findings:
                lines.append(f"  - `{finding.severity}` `{finding.code}`: {finding.message}")
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {action}" for action in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def review_strategy_promotions(
    registry_path: str | Path,
    *,
    goal: CapitalGoal,
    min_real_observations: int = 3,
    min_real_passes: int = 2,
    min_candidate_walk_forward_observations: int = 3,
    min_candidate_walk_forward_passes: int = 2,
    min_candidate_walk_forward_pass_ratio: float = 0.60,
    min_candidate_regime_observations: int = 3,
    min_candidate_regime_passes: int = 1,
    require_adverse_regime_windows: bool = True,
    min_sharpe: float = 0.8,
) -> StrategyPromotionReview:
    registry_file = Path(registry_path)
    payload = _read_json(registry_file)
    candidates = [
        _candidate_review(
            summary,
            goal=goal,
            min_real_observations=min_real_observations,
            min_real_passes=min_real_passes,
            min_candidate_walk_forward_observations=min_candidate_walk_forward_observations,
            min_candidate_walk_forward_passes=min_candidate_walk_forward_passes,
            min_candidate_walk_forward_pass_ratio=min_candidate_walk_forward_pass_ratio,
            min_candidate_regime_observations=min_candidate_regime_observations,
            min_candidate_regime_passes=min_candidate_regime_passes,
            require_adverse_regime_windows=require_adverse_regime_windows,
            min_sharpe=min_sharpe,
        )
        for summary in _candidate_summaries(payload)
    ]
    candidates.sort(
        key=lambda candidate: (
            _decision_rank(candidate.decision),
            candidate.real_pass_count,
            candidate.real_avg_annualized_return,
            -candidate.real_avg_max_drawdown,
        ),
        reverse=True,
    )
    return StrategyPromotionReview(
        decision=_overall_decision(candidates),
        goal=goal.to_dict(),
        registry_path=str(registry_file),
        candidates=candidates,
        prohibited_actions=[
            "Do not treat PASS as permission for live trading.",
            "Do not promote demo-only candidates.",
            "Do not bypass data audit, robustness review, paper trading, LLM review, or human approval.",
            "Do not submit or generate unattended broker orders.",
        ],
    )


def write_strategy_promotion_review(
    registry_path: str | Path,
    output_dir: str | Path,
    *,
    goal: CapitalGoal,
    min_real_observations: int = 3,
    min_real_passes: int = 2,
    min_candidate_walk_forward_observations: int = 3,
    min_candidate_walk_forward_passes: int = 2,
    min_candidate_walk_forward_pass_ratio: float = 0.60,
    min_candidate_regime_observations: int = 3,
    min_candidate_regime_passes: int = 1,
    require_adverse_regime_windows: bool = True,
    min_sharpe: float = 0.8,
) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    review = review_strategy_promotions(
        registry_path,
        goal=goal,
        min_real_observations=min_real_observations,
        min_real_passes=min_real_passes,
        min_candidate_walk_forward_observations=min_candidate_walk_forward_observations,
        min_candidate_walk_forward_passes=min_candidate_walk_forward_passes,
        min_candidate_walk_forward_pass_ratio=min_candidate_walk_forward_pass_ratio,
        min_candidate_regime_observations=min_candidate_regime_observations,
        min_candidate_regime_passes=min_candidate_regime_passes,
        require_adverse_regime_windows=require_adverse_regime_windows,
        min_sharpe=min_sharpe,
    )
    (out / "strategy_promotion_review.json").write_text(
        json.dumps(review.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out / "strategy_promotion_review.md").write_text(review.to_markdown(), encoding="utf-8")
    return out


def _candidate_review(
    summary: dict[str, Any],
    *,
    goal: CapitalGoal,
    min_real_observations: int,
    min_real_passes: int,
    min_candidate_walk_forward_observations: int,
    min_candidate_walk_forward_passes: int,
    min_candidate_walk_forward_pass_ratio: float,
    min_candidate_regime_observations: int,
    min_candidate_regime_passes: int,
    require_adverse_regime_windows: bool,
    min_sharpe: float,
) -> StrategyPromotionCandidate:
    findings: list[StrategyPromotionFinding] = []
    real_obs = int(summary.get("real_observation_count", 0) or 0)
    real_passes = int(summary.get("real_pass_count", 0) or 0)
    real_blocks = int(summary.get("real_block_count", 0) or 0)
    wf_obs = int(summary.get("real_candidate_walk_forward_observation_count", 0) or 0)
    wf_passes = int(summary.get("real_candidate_walk_forward_pass_count", 0) or 0)
    wf_blocks = int(summary.get("real_candidate_walk_forward_block_count", 0) or 0)
    wf_pass_ratio = _float(summary.get("real_avg_candidate_walk_forward_pass_ratio"))
    wf_positive_ratio = _float(summary.get("real_avg_candidate_walk_forward_positive_return_ratio"))
    wf_worst_return = _float(summary.get("real_worst_candidate_walk_forward_return"))
    wf_worst_drawdown = _float(summary.get("real_worst_candidate_walk_forward_drawdown"))
    regime_obs = int(summary.get("real_candidate_regime_observation_count", 0) or 0)
    regime_passes = int(summary.get("real_candidate_regime_pass_count", 0) or 0)
    regime_blocks = int(summary.get("real_candidate_regime_block_count", 0) or 0)
    adverse_windows = _float(summary.get("real_avg_candidate_regime_adverse_window_count"))
    real_return = _float(summary.get("real_avg_annualized_return"))
    real_drawdown = _float(summary.get("real_avg_max_drawdown"))
    real_sharpe = _float(summary.get("real_avg_sharpe_ratio"))
    required = goal.required_annual_return()

    if real_obs < min_real_observations:
        findings.append(
            StrategyPromotionFinding(
                "BLOCK",
                "INSUFFICIENT_REAL_OBSERVATIONS",
                f"Needs at least {min_real_observations} real-data observations.",
            )
        )
    if real_passes < min_real_passes:
        findings.append(
            StrategyPromotionFinding(
                "BLOCK",
                "INSUFFICIENT_REAL_PASS_COUNT",
                f"Needs at least {min_real_passes} PASS observations on real data.",
            )
        )
    if real_blocks:
        findings.append(
            StrategyPromotionFinding(
                "BLOCK",
                "REAL_HISTORY_BLOCK",
                "Real-data history contains BLOCK observations.",
            )
        )
    if wf_obs < min_candidate_walk_forward_observations:
        findings.append(
            StrategyPromotionFinding(
                "BLOCK",
                "INSUFFICIENT_CANDIDATE_WALK_FORWARD_OBSERVATIONS",
                f"Needs at least {min_candidate_walk_forward_observations} real-data candidate walk-forward observations.",
            )
        )
    if wf_passes < min_candidate_walk_forward_passes:
        findings.append(
            StrategyPromotionFinding(
                "BLOCK",
                "INSUFFICIENT_CANDIDATE_WALK_FORWARD_PASS_COUNT",
                f"Needs at least {min_candidate_walk_forward_passes} PASS candidate walk-forward observations on real data.",
            )
        )
    if wf_blocks:
        findings.append(
            StrategyPromotionFinding(
                "BLOCK",
                "CANDIDATE_WALK_FORWARD_BLOCK",
                "Real-data candidate walk-forward history contains BLOCK observations.",
            )
        )
    if wf_obs and wf_pass_ratio < min_candidate_walk_forward_pass_ratio:
        findings.append(
            StrategyPromotionFinding(
                "WATCH",
                "LOW_CANDIDATE_WALK_FORWARD_PASS_RATIO",
                f"Average candidate walk-forward PASS ratio is below {min_candidate_walk_forward_pass_ratio:.0%}.",
            )
        )
    if wf_obs and wf_positive_ratio < 0.60:
        findings.append(
            StrategyPromotionFinding(
                "WATCH",
                "LOW_CANDIDATE_WALK_FORWARD_POSITIVE_RATIO",
                "Average candidate walk-forward positive-return ratio is below 60%.",
            )
        )
    if wf_obs and wf_worst_return <= -0.10:
        findings.append(
            StrategyPromotionFinding(
                "BLOCK",
                "CANDIDATE_WALK_FORWARD_TAIL_LOSS",
                "Worst real-data candidate walk-forward window lost more than 10%.",
            )
        )
    elif wf_obs and wf_worst_return <= -0.05:
        findings.append(
            StrategyPromotionFinding(
                "WATCH",
                "CANDIDATE_WALK_FORWARD_TAIL_WATCH",
                "Worst real-data candidate walk-forward window lost more than 5%.",
            )
        )
    if regime_obs < min_candidate_regime_observations:
        findings.append(
            StrategyPromotionFinding(
                "BLOCK",
                "INSUFFICIENT_CANDIDATE_REGIME_OBSERVATIONS",
                f"Needs at least {min_candidate_regime_observations} real-data candidate regime validation observations.",
            )
        )
    if regime_passes < min_candidate_regime_passes:
        findings.append(
            StrategyPromotionFinding(
                "BLOCK",
                "INSUFFICIENT_CANDIDATE_REGIME_PASS_COUNT",
                f"Needs at least {min_candidate_regime_passes} PASS candidate regime validation observations on real data.",
            )
        )
    if regime_blocks:
        findings.append(
            StrategyPromotionFinding(
                "BLOCK",
                "CANDIDATE_REGIME_BLOCK",
                "Real-data candidate regime validation history contains BLOCK observations.",
            )
        )
    if require_adverse_regime_windows and adverse_windows <= 0:
        findings.append(
            StrategyPromotionFinding(
                "BLOCK",
                "MISSING_ADVERSE_REGIME_WINDOWS",
                "Needs defensive or risk_off regime windows before promotion discussion.",
            )
        )
    if real_return < required:
        findings.append(
            StrategyPromotionFinding(
                "WATCH",
                "RETURN_BELOW_GOAL_PATH",
                "Real-data average annualized return is below the capital-goal path.",
            )
        )
    if real_drawdown > goal.max_drawdown_budget:
        findings.append(
            StrategyPromotionFinding(
                "BLOCK",
                "DRAWDOWN_OVER_BUDGET",
                "Real-data average drawdown exceeds the drawdown budget.",
            )
        )
    if real_sharpe < min_sharpe:
        findings.append(
            StrategyPromotionFinding(
                "WATCH",
                "LOW_REAL_SHARPE",
                f"Real-data average Sharpe is below {min_sharpe:.2f}.",
            )
        )
    if not findings:
        findings.append(
            StrategyPromotionFinding(
                "PASS",
                "PAPER_REVIEW_CANDIDATE",
                "Candidate can enter deeper paper-stage review; this is not a live trading instruction.",
            )
        )

    return StrategyPromotionCandidate(
        name=str(summary.get("name", "")),
        decision=_combine([finding.severity for finding in findings]),
        real_observations=real_obs,
        real_pass_count=real_passes,
        real_candidate_walk_forward_observations=wf_obs,
        real_candidate_walk_forward_pass_count=wf_passes,
        real_candidate_walk_forward_pass_ratio=wf_pass_ratio,
        real_candidate_walk_forward_positive_return_ratio=wf_positive_ratio,
        real_worst_candidate_walk_forward_return=wf_worst_return,
        real_worst_candidate_walk_forward_drawdown=wf_worst_drawdown,
        real_candidate_regime_observations=regime_obs,
        real_candidate_regime_pass_count=regime_passes,
        real_candidate_regime_adverse_windows=adverse_windows,
        real_avg_annualized_return=real_return,
        required_annual_return=required,
        real_avg_max_drawdown=real_drawdown,
        drawdown_budget=goal.max_drawdown_budget,
        real_avg_sharpe_ratio=real_sharpe,
        findings=findings,
    )


def _candidate_summaries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = payload.get("candidates", {}) or {}
    return [
        candidate.get("summary", {})
        for candidate in candidates.values()
        if candidate.get("summary")
    ]


def _overall_decision(candidates: list[StrategyPromotionCandidate]) -> PromotionDecision:
    if any(candidate.decision == "PASS" for candidate in candidates):
        return "PASS"
    if any(candidate.decision == "WATCH" for candidate in candidates):
        return "WATCH"
    return "BLOCK"


def _combine(decisions: list[PromotionDecision]) -> PromotionDecision:
    if any(decision == "BLOCK" for decision in decisions):
        return "BLOCK"
    if any(decision == "WATCH" for decision in decisions):
        return "WATCH"
    return "PASS"


def _decision_rank(decision: PromotionDecision) -> int:
    return {"PASS": 2, "WATCH": 1, "BLOCK": 0}[decision]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"candidates": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
