"""Paper-trading reporting helpers."""
from __future__ import annotations

from quantify.paper.daily import PaperDailyState, write_paper_daily_review
from quantify.paper.loop import PaperLoopResult, PaperLoopState, run_paper_loop
from quantify.paper.plan import (
    PaperCandidatePlan,
    build_paper_candidate_plan,
    write_paper_candidate_plan,
)
from quantify.paper.stability import (
    PaperStabilityReport,
    evaluate_paper_stability,
    missing_paper_stability_report,
    write_paper_stability_report,
)

__all__ = [
    "PaperDailyState",
    "PaperCandidatePlan",
    "PaperLoopResult",
    "PaperLoopState",
    "PaperStabilityReport",
    "build_paper_candidate_plan",
    "evaluate_paper_stability",
    "missing_paper_stability_report",
    "run_paper_loop",
    "write_paper_candidate_plan",
    "write_paper_daily_review",
    "write_paper_stability_report",
]
