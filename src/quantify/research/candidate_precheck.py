"""Research-only candidate precheck boundary report.

The precheck is deliberately weaker than a guarded candidate experiment launch:
it helps compare research ideas on an existing cache, but it cannot promote a
candidate into paper, micro-live readiness, live trading, or broker execution.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PRECHECK_STATUS = "RESEARCH_ONLY"
PROMOTION_DECISION = "BLOCK"


DEFAULT_ALLOWED_ACTIONS = [
    "Compare candidate hypotheses and decide which experiment to preregister next.",
    "Use findings to refine factors, rebalance cadence, turnover controls, and stress tests.",
    "Attach the output to a human research note as non-promotional evidence.",
]
DEFAULT_PROHIBITED_ACTIONS = [
    "Do not pass this directory as --gate-report-dir for guarded candidate CLIs.",
    "Do not treat a research precheck PASS/WATCH as candidate_experiment_launch approval.",
    "Do not enter paper, micro_live_ready, micro_live, or live trading from this output.",
    "Do not connect this output to a broker or generate broker order instructions.",
    "Do not let LLM output upgrade this deterministic promotion decision.",
]
DEFAULT_MISSING_PROMOTION_EVIDENCE = [
    "PASS source QA, guarded offline intake, data audit, and run manifest from the first-million pipeline.",
    "PASS candidate_experiment_readiness.json and candidate_experiment_launch.json.",
    "candidate_experiment_completion.json confirming every required artifact exists.",
    "LLM advisory review that does not change deterministic gates.",
    "Paper-stage stability records and human approval before any micro-live readiness claim.",
]


@dataclass(frozen=True, slots=True)
class CandidateResearchPrecheckReport:
    status: str
    promotion_decision: str
    candidates: list[str]
    generated_artifacts: list[str]
    missing_promotion_evidence: list[str]
    allowed_actions: list[str]
    prohibited_actions: list[str]
    research_selection_status: str
    research_top_candidate: str
    research_selected_candidate: str
    walk_forward_status: str
    factor_diagnostics_status: str
    regime_validation_status: str
    selection_scope: str
    selection_start: str
    selection_end: str
    can_satisfy_launch_gate: bool = False
    can_enter_paper: bool = False
    can_enter_micro_live_ready: bool = False
    can_generate_broker_orders: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": "candidate_research_precheck",
            "status": self.status,
            "promotion_decision": self.promotion_decision,
            "candidates": self.candidates,
            "generated_artifacts": self.generated_artifacts,
            "missing_promotion_evidence": self.missing_promotion_evidence,
            "allowed_actions": self.allowed_actions,
            "prohibited_actions": self.prohibited_actions,
            "research_selection_status": self.research_selection_status,
            "research_top_candidate": self.research_top_candidate,
            "research_selected_candidate": self.research_selected_candidate,
            "walk_forward_status": self.walk_forward_status,
            "factor_diagnostics_status": self.factor_diagnostics_status,
            "regime_validation_status": self.regime_validation_status,
            "selection_scope": self.selection_scope,
            "selection_start": self.selection_start,
            "selection_end": self.selection_end,
            "can_satisfy_launch_gate": self.can_satisfy_launch_gate,
            "can_enter_paper": self.can_enter_paper,
            "can_enter_micro_live_ready": self.can_enter_micro_live_ready,
            "can_generate_broker_orders": self.can_generate_broker_orders,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Candidate Research Precheck: {self.status}",
            "",
            f"- Promotion decision: `{self.promotion_decision}`",
            f"- Research top candidate: `{self.research_top_candidate or 'none'}`",
            f"- Research selected candidate: `{self.research_selected_candidate or 'none'}`",
            f"- Research selection status: `{self.research_selection_status}`",
            f"- Walk-forward status: `{self.walk_forward_status}`",
            f"- Factor diagnostics status: `{self.factor_diagnostics_status}`",
            f"- Regime validation status: `{self.regime_validation_status}`",
            f"- Selection scope: `{self.selection_scope}`",
            f"- Selection window: `{self.selection_start or 'unspecified'}` to `{self.selection_end or 'unspecified'}`",
            "",
            "This is a research-only precheck. It cannot satisfy a candidate launch gate, cannot enter paper, and cannot generate broker orders.",
            "",
            "## Candidates",
        ]
        lines.extend(f"- `{candidate}`" for candidate in self.candidates) if self.candidates else lines.append("- None.")
        lines.extend(["", "## Generated Artifacts"])
        lines.extend(f"- `{artifact}`" for artifact in self.generated_artifacts)
        lines.extend(["", "## Missing Promotion Evidence"])
        lines.extend(f"- {item}" for item in self.missing_promotion_evidence)
        lines.extend(["", "## Allowed Actions"])
        lines.extend(f"- {item}" for item in self.allowed_actions)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_candidate_research_precheck_report(
    *,
    candidates: list[str],
    generated_artifacts: list[str],
    candidate_selection: dict[str, Any] | None = None,
    candidate_walk_forward: dict[str, Any] | None = None,
    factor_diagnostics: dict[str, Any] | None = None,
    regime_validation: dict[str, Any] | None = None,
    selection_scope: str = "latest_precheck_window",
    selection_start: str = "",
    selection_end: str = "",
) -> CandidateResearchPrecheckReport:
    missing = list(DEFAULT_MISSING_PROMOTION_EVIDENCE)
    if selection_scope != "full_sample":
        missing.append(
            "Full-sample candidate_selection.json was not generated; precheck selection is limited to a recent research window."
        )
    if factor_diagnostics is None:
        missing.append("candidate_factor_diagnostics.json was not generated in this precheck run.")
    if regime_validation is None:
        missing.append("candidate_regime_validation_report.json was not generated in this precheck run.")
    return CandidateResearchPrecheckReport(
        status=PRECHECK_STATUS,
        promotion_decision=PROMOTION_DECISION,
        candidates=candidates,
        generated_artifacts=generated_artifacts,
        missing_promotion_evidence=missing,
        allowed_actions=list(DEFAULT_ALLOWED_ACTIONS),
        prohibited_actions=list(DEFAULT_PROHIBITED_ACTIONS),
        research_selection_status=_status(candidate_selection),
        research_top_candidate=str((candidate_selection or {}).get("top_candidate", "") or ""),
        research_selected_candidate=str((candidate_selection or {}).get("selected_candidate", "") or ""),
        walk_forward_status=_status(candidate_walk_forward),
        factor_diagnostics_status=_status(factor_diagnostics, skipped="SKIPPED"),
        regime_validation_status=_status(regime_validation, skipped="SKIPPED"),
        selection_scope=selection_scope,
        selection_start=selection_start,
        selection_end=selection_end,
    )


def write_candidate_research_precheck_report(
    report: CandidateResearchPrecheckReport,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    markdown = report.to_markdown()
    (root / "candidate_research_precheck.json").write_text(payload, encoding="utf-8")
    (root / "candidate_research_precheck.md").write_text(markdown, encoding="utf-8")
    (root / "research_precheck_notice.json").write_text(payload, encoding="utf-8")
    (root / "research_precheck_notice.md").write_text(markdown, encoding="utf-8")
    return root


def _status(payload: dict[str, Any] | None, *, skipped: str = "UNKNOWN") -> str:
    if payload is None:
        return skipped
    return str(payload.get("status", "UNKNOWN") or "UNKNOWN").upper()
