"""Operating rhythm reports for long-running quant research."""
from __future__ import annotations

from quantify.ops.data_coverage import (
    DataCoverageReport,
    analyze_data_coverage,
    write_data_coverage_report,
)
from quantify.ops.bootstrap import (
    RealDataBootstrapReport,
    build_real_data_bootstrap_report,
    write_real_data_bootstrap_report,
)
from quantify.ops.first_million_readiness import (
    FirstMillionReadinessCard,
    FirstMillionReadinessGate,
    build_first_million_readiness_card,
    write_first_million_readiness_card,
)
from quantify.ops.first_million_daily_brief import (
    FirstMillionDailyBrief,
    FirstMillionDailyBriefGate,
    FirstMillionDailyBriefRankingStatus,
    FirstMillionDailyBriefTask,
    build_first_million_daily_brief,
    write_first_million_daily_brief,
)
from quantify.ops.recent_candidate_research import (
    RecentCandidateResearchReport,
    RecentResearchCandidate,
    build_recent_candidate_research_report,
    discover_recent_candidate_report_dirs,
    resolve_recent_candidate_research_dir,
    write_recent_candidate_research_report,
)
from quantify.ops.first_million_resolution import (
    FirstMillionResolutionPlan,
    FirstMillionResolutionTask,
    build_first_million_resolution_plan,
    write_first_million_resolution_plan,
)
from quantify.ops.evidence_intake_kit import (
    EvidenceIntakeKit,
    EvidenceIntakeKitFile,
    build_evidence_intake_kit,
    write_evidence_intake_kit,
)
from quantify.ops.evidence_work_order import (
    EvidenceWorkBatch,
    EvidenceWorkOrder,
    build_evidence_work_order,
    write_evidence_work_order,
)
from quantify.ops.first_million_evidence_ranking_dashboard import (
    FirstMillionEvidenceRankingDashboard,
    FirstMillionEvidenceRankingDashboardItem,
    build_first_million_evidence_ranking_dashboard,
    write_first_million_evidence_ranking_dashboard,
)
from quantify.ops.data_intake_status import (
    DataIntakeStatusItem,
    DataIntakeStatusReport,
    build_data_intake_status,
    write_data_intake_status,
)
from quantify.ops.pipeline import WeeklyPipelineResult, run_weekly_pipeline
from quantify.ops.promotion import (
    StrategyPromotionReview,
    review_strategy_promotions,
    write_strategy_promotion_review,
)
from quantify.ops.real_data_gate import (
    RealDataGateResult,
    evaluate_real_data_gate,
    write_real_data_gate,
)
from quantify.ops.registry import CandidateRegistry, update_candidate_registry
from quantify.ops.strategy_discovery_plan import (
    StrategyDiscoveryCandidate,
    StrategyDiscoveryPlan,
    build_strategy_discovery_plan,
    write_strategy_discovery_plan,
)
from quantify.ops.weekly import (
    WeeklyReview,
    WeeklyReviewComponent,
    build_weekly_review,
    write_weekly_review,
)

__all__ = [
    "CandidateRegistry",
    "DataCoverageReport",
    "DataIntakeStatusItem",
    "DataIntakeStatusReport",
    "FirstMillionDailyBrief",
    "FirstMillionDailyBriefGate",
    "FirstMillionDailyBriefRankingStatus",
    "FirstMillionDailyBriefTask",
    "FirstMillionEvidenceRankingDashboard",
    "FirstMillionEvidenceRankingDashboardItem",
    "RecentCandidateResearchReport",
    "RecentResearchCandidate",
    "FirstMillionReadinessCard",
    "FirstMillionReadinessGate",
    "FirstMillionResolutionPlan",
    "FirstMillionResolutionTask",
    "EvidenceIntakeKit",
    "EvidenceIntakeKitFile",
    "EvidenceWorkBatch",
    "EvidenceWorkOrder",
    "RealDataBootstrapReport",
    "RealDataGateResult",
    "StrategyDiscoveryCandidate",
    "StrategyDiscoveryPlan",
    "StrategyPromotionReview",
    "WeeklyPipelineResult",
    "WeeklyReview",
    "WeeklyReviewComponent",
    "analyze_data_coverage",
    "build_first_million_daily_brief",
    "build_first_million_evidence_ranking_dashboard",
    "build_first_million_readiness_card",
    "build_first_million_resolution_plan",
    "build_recent_candidate_research_report",
    "build_evidence_intake_kit",
    "build_evidence_work_order",
    "build_data_intake_status",
    "build_strategy_discovery_plan",
    "build_weekly_review",
    "build_real_data_bootstrap_report",
    "discover_recent_candidate_report_dirs",
    "resolve_recent_candidate_research_dir",
    "evaluate_real_data_gate",
    "review_strategy_promotions",
    "run_weekly_pipeline",
    "update_candidate_registry",
    "write_data_coverage_report",
    "write_first_million_daily_brief",
    "write_first_million_evidence_ranking_dashboard",
    "write_first_million_readiness_card",
    "write_first_million_resolution_plan",
    "write_recent_candidate_research_report",
    "write_evidence_intake_kit",
    "write_evidence_work_order",
    "write_data_intake_status",
    "write_strategy_discovery_plan",
    "write_real_data_bootstrap_report",
    "write_real_data_gate",
    "write_strategy_promotion_review",
    "write_weekly_review",
]
