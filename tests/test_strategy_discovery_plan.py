from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys

from quantify.ops.strategy_discovery_plan import (
    build_strategy_discovery_plan,
    write_strategy_discovery_plan,
)


def test_strategy_discovery_plan_blocks_on_current_data_evidence(tmp_path: Path) -> None:
    _write_blocked_artifacts(tmp_path)

    plan = build_strategy_discovery_plan(tmp_path, as_of="2026-06-10")
    out = write_strategy_discovery_plan(plan, tmp_path)

    payload = json.loads((out / "strategy_discovery_plan.json").read_text(encoding="utf-8"))
    markdown = (out / "strategy_discovery_plan.md").read_text(encoding="utf-8")
    rows = list(csv.DictReader((out / "strategy_discovery_plan.csv").open(encoding="utf-8-sig")))

    assert plan.decision == "PREPARE_DATA"
    assert plan.status == "BLOCK"
    assert payload["top_candidate"] == "price_volume_defensive"
    assert payload["top_candidate_basis"] == "pre_registered_priority_without_ranking"
    assert payload["can_rank_candidates"] is False
    assert payload["ranking_gate"]["status"] == "BLOCK"
    assert payload["ranking_gate"]["can_rank_candidates"] is False
    assert payload["ranking_gate"]["candidate_selection_status"] == "MISSING"
    assert any("candidate_selection.json is missing" in item for item in payload["ranking_gate"]["blocked_by"])
    assert payload["runnable_count"] == 0
    assert payload["blocked_count"] == 2
    assert payload["research_focus"]["status"] == "MISSING"
    assert payload["research_focus"]["advisory_only"] is True
    assert payload["candidates"][0]["discovery_stage"] == "WAITING_FOR_EVIDENCE"
    assert payload["candidates"][0]["allowed_stage"] == "blocked"
    assert "source_qa_preflight=BLOCK" in payload["candidates"][0]["first_blocker"]
    assert "Ranking Gate" in markdown
    assert any("recent_candidate_research" in item for item in payload["missing_evidence"])
    assert any("run_data_source_qa_worksheet_preflight.py" in item for item in payload["allowed_actions"])
    assert any("operator_next_batch" in item for item in payload["missing_evidence"])
    assert any("raw_bars_discovery" in item for item in payload["missing_evidence"])
    assert any("market_context_operator_packet" in item for item in payload["missing_evidence"])
    assert any("ohlcv_experiment_package" in item for item in payload["missing_evidence"])
    assert any("real_data_batch_onboarding" in item for item in payload["missing_evidence"])
    assert any("Do not treat this discovery plan" in item for item in payload["prohibited_actions"])
    assert rows[0]["candidate"] == "price_volume_defensive"
    assert "not a profit claim" in markdown


def test_strategy_discovery_plan_runs_research_when_candidate_ready(tmp_path: Path) -> None:
    _write_ready_artifacts(tmp_path)

    plan = build_strategy_discovery_plan(tmp_path, as_of="2026-06-10")

    assert plan.decision == "RUN_RESEARCH"
    assert plan.status == "PASS"
    assert plan.top_candidate == "price_volume_defensive"
    assert plan.top_candidate_basis == "first_ready_pre_registered_candidate"
    assert plan.can_rank_candidates is False
    assert plan.ranking_gate.status == "BLOCK"
    assert any("candidate_experiment_completion=BLOCK" in item for item in plan.ranking_gate.blocked_by)
    assert plan.runnable_count == 1
    assert plan.candidates[0].discovery_stage == "READY_TO_LAUNCH"
    assert plan.candidates[0].allowed_stage == "research_only"
    assert plan.allowed_actions[0].endswith("--candidate price_volume_defensive")
    assert "run_candidate_experiment_run_packet.py" in plan.allowed_actions[0]
    assert any("Capital-goal fit" in item or "capital-goal" in item for item in plan.selection_policy)


def test_strategy_discovery_plan_allows_ranking_only_after_completion_and_selection(
    tmp_path: Path,
) -> None:
    _write_ready_artifacts(tmp_path)
    _write_json(
        tmp_path / "candidate_experiment_completion.json",
        {
            "decision": "PASS",
            "selected_candidate": "price_volume_defensive",
            "run_id": "20260610_price_volume_defensive",
        },
    )
    _write_json(
        tmp_path / "candidate_selection.json",
        {
            "status": "PASS",
            "selected_candidate": "price_volume_defensive",
            "top_candidate": "price_volume_defensive",
            "results": [
                {
                    "name": "price_volume_defensive",
                    "capital_goal_fit_status": "PASS",
                }
            ],
        },
    )

    plan = build_strategy_discovery_plan(tmp_path, as_of="2026-06-10")
    out = write_strategy_discovery_plan(plan, tmp_path)
    payload = json.loads((out / "strategy_discovery_plan.json").read_text(encoding="utf-8"))
    markdown = (out / "strategy_discovery_plan.md").read_text(encoding="utf-8")

    assert plan.decision == "PAPER_OBSERVE"
    assert plan.can_rank_candidates is True
    assert plan.ranking_gate.status == "PASS"
    assert plan.ranking_gate.blocked_by == []
    assert payload["can_rank_candidates"] is True
    assert payload["ranking_gate"]["status"] == "PASS"
    assert payload["ranking_gate"]["ranked_candidate_count"] == 1
    assert payload["ranking_gate"]["top_ranked_candidate"] == "price_volume_defensive"
    assert "Can rank candidates: `True`" in markdown


def test_strategy_discovery_plan_downgrades_focus_when_evidence_is_blocked(
    tmp_path: Path,
) -> None:
    _write_blocked_artifacts(tmp_path)
    _write_json(
        tmp_path / "recent_candidate_research.json",
        {
            "artifact_type": "recent_candidate_research",
            "status": "RESEARCH_ONLY",
            "report_count": 3,
            "candidate_count": 2,
            "best_research_candidate": "defensive_scaled_quarterly_price_volume",
            "best_research_reason": "Research-only rollup favors the defensive scaled candidate.",
            "best_research_command": "python examples/run_candidate_research_precheck.py --candidate defensive_scaled_quarterly_price_volume",
        },
    )

    plan = build_strategy_discovery_plan(tmp_path, as_of="2026-06-10")
    out = write_strategy_discovery_plan(plan, tmp_path)
    payload = json.loads((out / "strategy_discovery_plan.json").read_text(encoding="utf-8"))
    markdown = (out / "strategy_discovery_plan.md").read_text(encoding="utf-8")

    assert payload["research_focus"]["candidate"] == "defensive_scaled_quarterly_price_volume"
    assert payload["research_focus"]["status"] == "BLOCKED_EVIDENCE"
    assert payload["research_focus"]["evidence_status"] == "BLOCK"
    assert payload["research_focus"]["can_rank_candidates"] is False
    assert "first_million_pipeline=BLOCK" in payload["research_focus"]["evidence_blockers"]
    assert "Use this only as a research hypothesis" in payload["research_focus"]["reason"]
    assert "Can rank candidates: `False`" in markdown


def test_strategy_discovery_plan_reviews_completion_after_launch(tmp_path: Path) -> None:
    _write_ready_artifacts(tmp_path)
    _write_json(
        tmp_path / "candidate_experiment_launch.json",
        {
            "decision": "PASS",
            "selected_candidate": "price_volume_defensive",
            "run_id": "20260610_price_volume_defensive",
            "experiment_dir": str(tmp_path / "candidate_experiments" / "20260610_price_volume_defensive"),
            "command_sequence": [
                "python examples/run_candidate_experiment_evidence.py --output-dir exp",
                "python examples/run_candidate_walk_forward.py --output-dir exp",
            ],
            "required_outputs": ["exp/candidate_experiment_evidence.json"],
        },
    )
    _write_json(
        tmp_path / "candidate_experiment_completion.json",
        {
            "decision": "BLOCK",
            "selected_candidate": "price_volume_defensive",
            "run_id": "20260610_price_volume_defensive",
        },
    )

    plan = build_strategy_discovery_plan(tmp_path, as_of="2026-06-10")

    assert plan.decision == "REVIEW_COMPLETION"
    assert plan.status == "WATCH"
    assert plan.candidates[0].discovery_stage == "LAUNCHED_PENDING_COMPLETION"
    assert plan.candidates[0].next_command.startswith("python examples/run_candidate_experiment_evidence.py")
    assert plan.allowed_actions[-1].endswith("--report-dir {} --as-of 2026-06-10".format(tmp_path))


def test_strategy_discovery_plan_surfaces_recent_research_focus(tmp_path: Path) -> None:
    _write_ready_artifacts(tmp_path)
    _write_json(
        tmp_path / "recent_candidate_research.json",
        {
            "artifact_type": "recent_candidate_research",
            "status": "RESEARCH_ONLY",
            "report_count": 3,
            "candidate_count": 2,
            "best_research_candidate": "defensive_cash_guard_price_volume",
            "best_research_reason": "Most recent research evidence favors the defensive cash guard path.",
            "best_research_command": "python examples/run_candidate_research_precheck.py --candidate defensive_cash_guard_price_volume",
        },
    )

    plan = build_strategy_discovery_plan(tmp_path, as_of="2026-06-10")

    assert plan.research_focus.candidate == "defensive_cash_guard_price_volume"
    assert plan.research_focus.status == "PASS"
    assert plan.research_focus.advisory_only is True
    assert plan.research_focus.evidence_status == "PASS"
    assert plan.research_focus.can_rank_candidates is True
    assert "defensive cash guard" in plan.research_focus.reason.lower()


def test_strategy_discovery_plan_prefers_daily_brief_focus_when_rollup_is_stale(tmp_path: Path) -> None:
    _write_ready_artifacts(tmp_path)
    _write_json(
        tmp_path / "recent_candidate_research.json",
        {
            "artifact_type": "recent_candidate_research",
            "status": "RESEARCH_ONLY",
            "report_count": 1,
            "candidate_count": 1,
            "best_research_candidate": "defensive_cash_guard_price_volume",
            "best_research_reason": "Older cached rollup still points at the defensive path.",
            "best_research_command": "python examples/run_candidate_research_precheck.py --candidate defensive_cash_guard_price_volume",
        },
    )
    _write_json(
        tmp_path / "first_million_daily_brief.json",
        {
            "as_of": "2026-06-18",
            "commands": [],
            "research_focus": {
                "artifact_type": "recent_candidate_research",
                "status": "RESEARCH_ONLY",
                "report_count": 3,
                "candidate_count": 2,
                "best_research_candidate": "trend_filtered_quarterly_price_volume",
                "best_research_reason": "Newer real-candidate rollup favors the quarterly trend-filtered variant.",
                "best_research_command": "python examples/run_candidate_research_precheck.py --candidate trend_filtered_quarterly_price_volume",
            },
        },
    )

    plan = build_strategy_discovery_plan(tmp_path, as_of="2026-06-18")

    assert plan.research_focus.candidate == "trend_filtered_quarterly_price_volume"
    assert "quarterly" in plan.research_focus.reason.lower()


def test_strategy_discovery_plan_rebuilds_latest_real_candidate_focus(tmp_path: Path) -> None:
    _write_ready_artifacts(tmp_path)
    _write_json(
        tmp_path / "recent_candidate_research.json",
        {
            "artifact_type": "recent_candidate_research",
            "status": "RESEARCH_ONLY",
            "report_count": 12,
            "candidate_count": 5,
            "best_research_candidate": "defensive_cash_guard_price_volume",
            "best_research_reason": "Older stale rollup still favors defensive cash guard.",
            "best_research_command": "python examples/run_candidate_research_precheck.py --candidate defensive_cash_guard_price_volume",
        },
    )
    _write_recent_candidate_run_dir(
        tmp_path / "research_recent_real_candidates" / "20260618_new_variants_precheck",
        candidate="trend_filtered_quarterly_price_volume",
    )

    plan = build_strategy_discovery_plan(tmp_path, as_of="2026-06-18")

    assert plan.research_focus.candidate == "trend_filtered_quarterly_price_volume"
    assert "quarterly" in plan.research_focus.reason.lower()


def test_strategy_discovery_plan_cli_returns_nonzero_on_block(tmp_path: Path) -> None:
    _write_blocked_artifacts(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_strategy_discovery_plan.py",
            "--report-dir",
            str(tmp_path),
            "--as-of",
            "2026-06-10",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((tmp_path / "strategy_discovery_plan.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["decision"] == "PREPARE_DATA"


def _write_blocked_artifacts(root: Path) -> None:
    _write_json(root / "first_million_pipeline.json", {"decision": "BLOCK"})
    _write_json(
        root / "candidate_experiment_queue.json",
        {
            "as_of": "2026-06-10",
            "experiments": [
                _experiment("price_volume_defensive", 1, "ohlcv_only"),
                _experiment("core_multifactor", 2, "ohlcv_plus_fundamentals"),
            ],
        },
    )
    _write_json(
        root / "candidate_experiment_readiness.json",
        {
            "decision": "BLOCK",
            "as_of": "2026-06-10",
            "runnable_count": 0,
            "blocked_count": 2,
            "blockers": ["source_qa_preflight=BLOCK"],
            "items": [
                _readiness_item(
                    "price_volume_defensive",
                    1,
                    "ohlcv_only",
                    "OHLCV_ONLY",
                    "BLOCKED",
                    ["source_qa_preflight=BLOCK: data_source_qa_answers.json is missing."],
                ),
                _readiness_item(
                    "core_multifactor",
                    2,
                    "ohlcv_plus_fundamentals",
                    "PIT_FUNDAMENTAL_REQUIRED",
                    "BLOCKED",
                    ["pit_fundamental_candidate_path: fundamentals.csv still contains generated template rows."],
                ),
            ],
        },
    )
    _write_json(root / "candidate_experiment_launch.json", {"decision": "BLOCK"})
    _write_json(root / "candidate_experiment_completion.json", {"decision": "BLOCK"})
    _write_json(root / "first_million_strategy_brief.json", {"decision": "PREPARE_DATA"})
    _write_json(
        root / "ohlcv_experiment_package.json",
        {
            "decision": "BLOCK",
            "blockers": ["bars_coverage: bars.csv coverage is below the OHLCV research minimum."],
            "watch_items": [],
        },
    )
    _write_json(
        root / "real_data_batch_onboarding.json",
        {
            "decision": "BLOCK",
            "blockers": ["raw_bars_csv: No raw broker/vendor bars CSV path was supplied."],
            "watch_items": [],
        },
    )
    _write_json(
        root / "market_context_operator_packet.json",
        {
            "decision": "BLOCK",
            "readiness_source": "missing",
            "readiness_decision": "BLOCK",
            "missing_item_count": 1,
            "items": [
                {
                    "item_type": "preferred_artifact",
                    "item_id": "market_regime",
                    "required_value": "Generate cache-derived market_regime.json.",
                }
            ],
        },
    )
    _write_json(
        root / "first_million_daily_brief.json",
        {
            "as_of": "2026-06-10",
            "commands": [
                ".\\.venv\\Scripts\\python.exe examples\\run_data_source_qa_worksheet_preflight.py --checklist data_exports\\data_source_qa.json --worksheet data_exports\\data_source_qa_evidence_worksheet.csv --output-dir data_exports"
            ],
            "missing_evidence": ["operator_next_batch: 13 source_qa_worksheet tasks remain."],
        },
    )
    _write_json(
        root / "raw_bars_discovery.json",
        {
            "status": "BLOCK",
            "best_candidate": "",
            "candidates": [{"message": "No candidate raw bars CSV files were found."}],
        },
    )


def _write_ready_artifacts(root: Path) -> None:
    _write_json(root / "first_million_pipeline.json", {"decision": "WATCH"})
    _write_json(
        root / "candidate_experiment_queue.json",
        {
            "as_of": "2026-06-10",
            "experiments": [
                _experiment("price_volume_defensive", 1, "ohlcv_only"),
                _experiment("core_multifactor", 2, "ohlcv_plus_fundamentals"),
            ],
        },
    )
    _write_json(
        root / "candidate_experiment_readiness.json",
        {
            "decision": "WATCH",
            "as_of": "2026-06-10",
            "runnable_count": 1,
            "blocked_count": 1,
            "items": [
                _readiness_item(
                    "price_volume_defensive",
                    1,
                    "ohlcv_only",
                    "OHLCV_ONLY",
                    "READY",
                    [],
                    next_command="python examples/run_candidate_experiment_evidence.py --output-dir exp",
                ),
                _readiness_item(
                    "core_multifactor",
                    2,
                    "ohlcv_plus_fundamentals",
                    "PIT_FUNDAMENTAL_REQUIRED",
                    "BLOCKED",
                    ["pit_fundamental_candidate_path: fundamentals.csv missing PIT evidence."],
                ),
            ],
        },
    )
    _write_json(root / "candidate_experiment_launch.json", {"decision": "BLOCK"})
    _write_json(root / "candidate_experiment_completion.json", {"decision": "BLOCK"})
    _write_json(root / "first_million_strategy_brief.json", {"decision": "RUN_RESEARCH"})
    _write_json(
        root / "ohlcv_experiment_package.json",
        {
            "decision": "PASS",
            "blockers": [],
            "watch_items": [],
        },
    )
    _write_json(
        root / "real_data_batch_onboarding.json",
        {
            "decision": "PASS",
            "blockers": [],
            "watch_items": [],
        },
    )
    _write_json(
        root / "market_context_operator_packet.json",
        {
            "decision": "PASS",
            "readiness_source": "market_regime",
            "readiness_decision": "PASS",
            "missing_item_count": 0,
            "items": [],
        },
    )
    _write_json(root / "first_million_daily_brief.json", {"as_of": "2026-06-10", "commands": []})
    _write_json(
        root / "raw_bars_discovery.json",
        {
            "status": "PASS",
            "best_candidate": "raw.csv",
            "candidates": [{"message": "Normalizable raw bars CSV."}],
        },
    )


def _experiment(candidate: str, priority: int, data_dependency: str) -> dict:
    return {
        "priority": priority,
        "candidate": candidate,
        "data_dependency": data_dependency,
        "artifacts": [
            "candidate_experiment_evidence.json",
            "candidate_walk_forward_report.json",
            "candidate_factor_diagnostics.json",
            "candidate_regime_validation_report.json",
            "candidate_stress_matrix.json",
            "candidate_selection.json",
            "llm_review.json",
        ],
        "capital_goal_fit_tests": [
            "Run candidate_selection with capital-goal fit review.",
        ],
        "risk_budget_checks": ["Max drawdown and turnover stay inside configured budgets."],
        "paper_entry_requirements": ["No unresolved BLOCK before paper observation."],
    }


def _readiness_item(
    candidate: str,
    priority: int,
    data_dependency: str,
    evidence_scope: str,
    status: str,
    blocked_by: list[str],
    *,
    next_command: str = "",
) -> dict:
    return {
        "priority": priority,
        "candidate": candidate,
        "data_dependency": data_dependency,
        "evidence_scope": evidence_scope,
        "status": status,
        "blocked_by": blocked_by,
        "warnings": [],
        "next_command": next_command,
    }


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_recent_candidate_run_dir(report_dir: Path, *, candidate: str) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        report_dir / "candidate_selection.json",
        {
            "status": "BLOCK",
            "top_candidate": candidate,
            "selected_candidate": "",
            "results": [
                {
                    "name": candidate,
                    "score": {"decision": "BLOCK", "score": 0.0},
                    "metrics": {
                        "annualized_return": 0.2114,
                        "max_drawdown": 0.1830,
                        "sharpe_ratio": 1.13,
                    },
                    "avg_turnover_pct": 1.0001,
                    "reject_rate": 0.0505,
                    "capital_goal_fit_review": {
                        "status": "WATCH",
                        "return_margin": -0.1221,
                        "findings": ["Annual return is still below the required path after costs."],
                    },
                }
            ],
        },
    )
    _write_json(
        report_dir / "candidate_research_precheck.json",
        {
            "status": "RESEARCH_ONLY",
            "promotion_decision": "BLOCK",
            "candidates": [candidate],
            "missing_promotion_evidence": [
                "PASS source QA, guarded offline intake, data audit, and run manifest evidence."
            ],
        },
    )
    _write_json(
        report_dir / "candidate_walk_forward_report.json",
        {
            "status": "WATCH",
            "summaries": [
                {
                    "candidate": candidate,
                    "status": "WATCH",
                    "window_count": 1,
                    "positive_return_ratio": 0.0,
                    "worst_total_return": -0.0294,
                    "worst_max_drawdown": 0.1830,
                }
            ],
        },
    )
    _write_json(
        report_dir / "candidate_stress_matrix.json",
        {
            "status": "RESEARCH_ONLY",
            "promotion_decision": "BLOCK",
            "summaries": [
                {
                    "candidate": candidate,
                    "status": "WATCH",
                    "scenario_count": 4,
                    "pass_count": 1,
                    "watch_count": 3,
                    "block_count": 0,
                    "worst_total_return": -0.04,
                    "worst_max_drawdown": 0.1830,
                    "max_turnover_pct": 1.0001,
                    "findings": ["Only one stress scenario reached PASS."],
                }
            ],
        },
    )
