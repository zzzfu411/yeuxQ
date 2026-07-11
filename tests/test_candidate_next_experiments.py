from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from quantify.research.candidate_next_experiments import (
    CandidateReportBundle,
    build_candidate_next_experiments_report,
    load_candidate_report_bundle,
    write_candidate_next_experiments_report,
)


def test_next_experiments_flag_low_turnover_blockers() -> None:
    report = build_candidate_next_experiments_report(
        [
            _bundle(
                "low_turnover_price_volume",
                annualized_return=-0.187,
                sharpe_ratio=-1.62,
                avg_turnover_pct=0.9334,
                return_margin=-0.42,
                worst_total_return=-0.0473,
            )
        ]
    )
    payload = report.to_dict()
    categories = {item["category"] for item in payload["experiments"]}

    assert payload["status"] == "RESEARCH_ONLY"
    assert payload["promotion_decision"] == "BLOCK"
    assert payload["can_satisfy_launch_gate"] is False
    assert payload["can_enter_paper"] is False
    assert payload["can_enter_micro_live_ready"] is False
    assert payload["can_generate_broker_orders"] is False
    assert "blocked_candidate_review" in categories
    assert "turnover_control" in categories
    assert "adverse_window_review" in categories
    assert "capital_goal_fit" in categories
    assert "missing_factor_diagnostics" in categories
    assert "missing_regime_validation" in categories
    turnover_items = [item for item in payload["experiments"] if item["category"] == "turnover_control"]
    assert turnover_items
    assert "--scenario stability_control" in turnover_items[0]["command_hint"]
    assert "--scenario score_smoothing" in turnover_items[0]["command_hint"]
    assert all(item["allowed_stage"] == "research" for item in payload["experiments"])
    assert all(item["can_enter_paper"] is False for item in payload["experiments"])
    assert all(item["can_generate_broker_orders"] is False for item in payload["experiments"])


def test_next_experiments_flag_trend_filter_ablation() -> None:
    report = build_candidate_next_experiments_report(
        [
            _bundle(
                "trend_filtered_price_volume",
                annualized_return=-0.1667,
                sharpe_ratio=-1.0,
                avg_turnover_pct=0.8275,
                trend_filter=True,
                trend_filter_active_days=3,
                worst_total_return=-0.0418,
            )
        ]
    )
    payload = report.to_dict()
    trend_items = [
        item for item in payload["experiments"] if item["category"] == "trend_filter_ablation"
    ]

    assert trend_items
    assert trend_items[0]["candidate"] == "trend_filtered_price_volume"
    assert "cash drag" in trend_items[0]["recommendation"]
    assert any("trend_filter_active_days=3" in item for item in trend_items[0]["evidence"])


def test_next_experiments_use_diagnostics_when_present() -> None:
    report = build_candidate_next_experiments_report(
        [
            _bundle(
                "price_volume_defensive",
                factor_diagnostics={
                    "status": "WATCH",
                    "component_count": 3,
                    "component_pass_count": 1,
                    "dependency_ratio": 1.8,
                    "findings": ["Best component dominates composite evidence."],
                },
                regime_summary={
                    "status": "WATCH",
                    "known_regime_count": 2,
                    "adverse_regime_window_count": 1,
                    "block_bucket_count": 0,
                    "notes": ["Defensive bucket is weak."],
                },
            )
        ]
    )
    categories = {item.category for item in report.experiments}

    assert "factor_dependency" in categories
    assert "regime_failure" in categories
    assert "missing_factor_diagnostics" not in categories
    assert "missing_regime_validation" not in categories
    by_category = {item.category: item for item in report.experiments}
    assert "run_candidate_research_precheck.py" in by_category["factor_dependency"].command_hint
    assert "run_candidate_factor_diagnostics.py" not in by_category["factor_dependency"].command_hint
    assert "run_candidate_research_precheck.py" in by_category["regime_failure"].command_hint
    assert "run_candidate_regime_validation.py" not in by_category["regime_failure"].command_hint


def test_next_experiments_flag_stress_matrix_failure() -> None:
    bundle = _bundle("trend_filtered_price_volume")
    bundle = CandidateReportBundle(
        report_dir=bundle.report_dir,
        candidate_selection=bundle.candidate_selection,
        candidate_research_precheck=bundle.candidate_research_precheck,
        candidate_walk_forward=bundle.candidate_walk_forward,
        factor_diagnostics=bundle.factor_diagnostics,
        regime_validation=bundle.regime_validation,
        stress_matrix={
            "status": "RESEARCH_ONLY",
            "promotion_decision": "BLOCK",
            "summaries": [
                {
                    "candidate": "trend_filtered_price_volume",
                    "status": "WATCH",
                    "scenario_count": 6,
                    "pass_count": 0,
                    "watch_count": 6,
                    "block_count": 0,
                    "worst_total_return": -0.0439,
                    "worst_max_drawdown": 0.1068,
                    "max_turnover_pct": 0.9999,
                    "findings": ["No stress scenario reached PASS."],
                }
            ],
        },
    )
    report = build_candidate_next_experiments_report([bundle])
    stress_items = [item for item in report.experiments if item.category == "stress_matrix_failure"]

    assert stress_items
    assert stress_items[0].candidate == "trend_filtered_price_volume"
    assert any("pass_count=0" in item for item in stress_items[0].evidence)
    assert stress_items[0].can_enter_paper is False


def test_next_experiments_flags_turnover_control_ablation_failure() -> None:
    bundle = _bundle("defensive_scaled_quarterly_price_volume", avg_turnover_pct=0.90)
    bundle = CandidateReportBundle(
        report_dir=bundle.report_dir,
        candidate_selection=bundle.candidate_selection,
        candidate_research_precheck=bundle.candidate_research_precheck,
        candidate_walk_forward=bundle.candidate_walk_forward,
        factor_diagnostics=bundle.factor_diagnostics,
        regime_validation=bundle.regime_validation,
        stress_matrix={
            "status": "RESEARCH_ONLY",
            "promotion_decision": "BLOCK",
            "summaries": [
                {
                    "candidate": "defensive_scaled_quarterly_price_volume",
                    "status": "WATCH",
                    "scenario_count": 2,
                    "pass_count": 0,
                    "watch_count": 2,
                    "block_count": 0,
                    "worst_total_return": 0.03,
                    "worst_max_drawdown": 0.17,
                    "max_turnover_pct": 0.90,
                    "findings": ["At least one scenario has high turnover."],
                }
            ],
            "results": [
                {
                    "candidate": "defensive_scaled_quarterly_price_volume",
                    "scenario": "baseline",
                    "status": "WATCH",
                    "avg_turnover_pct": 0.8236,
                    "avg_maintenance_turnover_pct": 0.0,
                    "metrics": {"total_return": 0.0376, "max_drawdown": 0.1711},
                    "parameters": {"hold_rank_buffer": 0, "min_trade_weight": 0.0},
                },
                {
                    "candidate": "defensive_scaled_quarterly_price_volume",
                    "scenario": "turnover_control",
                    "status": "WATCH",
                    "avg_turnover_pct": 0.8236,
                    "avg_maintenance_turnover_pct": 0.0,
                    "metrics": {"total_return": 0.0376, "max_drawdown": 0.1711},
                    "parameters": {"hold_rank_buffer": 15, "min_trade_weight": 0.01},
                },
            ],
        },
    )

    report = build_candidate_next_experiments_report([bundle])
    items = [item for item in report.experiments if item.category == "turnover_control_ablation_failed"]

    assert items
    assert "Do not promote" in items[0].recommendation
    assert any("turnover_improvement=0.00%" in evidence for evidence in items[0].evidence)
    assert any("maintenance_turnover_improvement=0.00%" in evidence for evidence in items[0].evidence)
    assert "--scenario stability_control" in items[0].command_hint
    assert "--scenario score_smoothing" in items[0].command_hint
    assert items[0].can_enter_paper is False


def test_next_experiments_flags_stability_control_ablation_failure() -> None:
    bundle = _bundle("defensive_scaled_quarterly_price_volume", avg_turnover_pct=0.90)
    bundle = CandidateReportBundle(
        report_dir=bundle.report_dir,
        candidate_selection=bundle.candidate_selection,
        candidate_research_precheck=bundle.candidate_research_precheck,
        candidate_walk_forward=bundle.candidate_walk_forward,
        factor_diagnostics=bundle.factor_diagnostics,
        regime_validation=bundle.regime_validation,
        stress_matrix={
            "status": "RESEARCH_ONLY",
            "promotion_decision": "BLOCK",
            "summaries": [
                {
                    "candidate": "defensive_scaled_quarterly_price_volume",
                    "status": "WATCH",
                    "scenario_count": 2,
                    "pass_count": 0,
                    "watch_count": 2,
                    "block_count": 0,
                    "worst_total_return": 0.03,
                    "worst_max_drawdown": 0.17,
                    "max_turnover_pct": 0.90,
                    "findings": ["At least one scenario has high maintenance turnover."],
                }
            ],
            "results": [
                {
                    "candidate": "defensive_scaled_quarterly_price_volume",
                    "scenario": "baseline",
                    "status": "WATCH",
                    "avg_turnover_pct": 0.8236,
                    "avg_maintenance_turnover_pct": 0.8270,
                    "metrics": {"total_return": 0.0376, "max_drawdown": 0.1711},
                    "parameters": {"hold_rank_buffer": 0, "min_trade_weight": 0.0},
                },
                {
                    "candidate": "defensive_scaled_quarterly_price_volume",
                    "scenario": "stability_control",
                    "status": "WATCH",
                    "avg_turnover_pct": 0.8236,
                    "avg_maintenance_turnover_pct": 0.8270,
                    "metrics": {"total_return": 0.0376, "max_drawdown": 0.1711},
                    "parameters": {
                        "hold_rank_buffer": 30,
                        "min_trade_weight": 0.02,
                        "max_new_positions": 6,
                    },
                },
            ],
        },
    )

    report = build_candidate_next_experiments_report([bundle])
    items = [item for item in report.experiments if item.category == "stability_control_ablation_failed"]

    assert items
    assert "signal smoothing" in items[0].recommendation
    assert any("maintenance_turnover_improvement=0.00%" in evidence for evidence in items[0].evidence)
    assert any("max_new_positions=6" in evidence for evidence in items[0].evidence)
    assert "--scenario score_smoothing" in items[0].command_hint
    assert items[0].can_enter_paper is False


def test_next_experiments_flags_score_smoothing_ablation_failure() -> None:
    bundle = _bundle("defensive_scaled_quarterly_price_volume", avg_turnover_pct=0.90)
    bundle = CandidateReportBundle(
        report_dir=bundle.report_dir,
        candidate_selection=bundle.candidate_selection,
        candidate_research_precheck=bundle.candidate_research_precheck,
        candidate_walk_forward=bundle.candidate_walk_forward,
        factor_diagnostics=bundle.factor_diagnostics,
        regime_validation=bundle.regime_validation,
        stress_matrix={
            "status": "RESEARCH_ONLY",
            "promotion_decision": "BLOCK",
            "summaries": [
                {
                    "candidate": "defensive_scaled_quarterly_price_volume",
                    "status": "WATCH",
                    "scenario_count": 2,
                    "pass_count": 0,
                    "watch_count": 2,
                    "block_count": 0,
                    "worst_total_return": 0.03,
                    "worst_max_drawdown": 0.17,
                    "max_turnover_pct": 0.90,
                    "findings": ["At least one scenario has high maintenance turnover."],
                }
            ],
            "results": [
                {
                    "candidate": "defensive_scaled_quarterly_price_volume",
                    "scenario": "baseline",
                    "status": "WATCH",
                    "avg_turnover_pct": 0.8236,
                    "avg_maintenance_turnover_pct": 0.8270,
                    "metrics": {"total_return": 0.0376, "max_drawdown": 0.1711},
                    "parameters": {
                        "score_smoothing_observations": 0,
                        "score_smoothing_step_days": 20,
                    },
                },
                {
                    "candidate": "defensive_scaled_quarterly_price_volume",
                    "scenario": "score_smoothing",
                    "status": "WATCH",
                    "avg_turnover_pct": 0.8236,
                    "avg_maintenance_turnover_pct": 0.8270,
                    "metrics": {"total_return": 0.0376, "max_drawdown": 0.1711},
                    "parameters": {
                        "score_smoothing_observations": 3,
                        "score_smoothing_step_days": 20,
                    },
                },
            ],
        },
    )

    report = build_candidate_next_experiments_report([bundle])
    items = [item for item in report.experiments if item.category == "score_smoothing_ablation_failed"]

    assert items
    assert "smoothed-score" in items[0].recommendation
    assert any("score_smoothing_observations=3" in evidence for evidence in items[0].evidence)
    assert any("maintenance_turnover_improvement=0.00%" in evidence for evidence in items[0].evidence)
    assert "--candidate stable_universe_slow_signal_price_volume" in items[0].command_hint
    assert "--full-sample-selection" in items[0].command_hint
    assert items[0].can_enter_paper is False


def test_next_experiments_add_low_concentration_head_to_head_follow_up() -> None:
    bundle = _bundle(
        "low_turnover_low_concentration_price_volume",
        annualized_return=-0.041,
        max_drawdown=0.139,
        sharpe_ratio=0.81,
        avg_turnover_pct=0.71,
        worst_total_return=-0.021,
    )
    bundle = CandidateReportBundle(
        report_dir=bundle.report_dir,
        candidate_selection=bundle.candidate_selection,
        candidate_research_precheck=bundle.candidate_research_precheck,
        candidate_walk_forward=bundle.candidate_walk_forward,
        factor_diagnostics=bundle.factor_diagnostics,
        regime_validation=bundle.regime_validation,
        stress_matrix={
            "status": "RESEARCH_ONLY",
            "promotion_decision": "BLOCK",
            "summaries": [
                {
                    "candidate": "low_turnover_low_concentration_price_volume",
                    "status": "WATCH",
                    "scenario_count": 5,
                    "pass_count": 0,
                    "watch_count": 5,
                    "block_count": 0,
                    "worst_total_return": -0.021,
                    "worst_max_drawdown": 0.139,
                    "max_turnover_pct": 0.71,
                    "findings": ["No stress scenario reached PASS."],
                }
            ],
        },
    )

    report = build_candidate_next_experiments_report([bundle])
    items = [item for item in report.experiments if item.category == "low_concentration_vs_baseline"]

    assert items
    assert items[0].candidate == "low_turnover_low_concentration_price_volume"
    assert "low_turnover_price_volume" in items[0].recommendation
    assert "--candidate low_turnover_price_volume" in items[0].command_hint
    assert "--candidate low_turnover_low_concentration_price_volume" in items[0].command_hint


def test_next_experiments_add_quarterly_trend_head_to_head_follow_up() -> None:
    bundle = _bundle(
        "trend_filtered_quarterly_price_volume",
        annualized_return=0.2114,
        max_drawdown=0.183,
        sharpe_ratio=1.13,
        avg_turnover_pct=0.62,
        trend_filter=True,
        trend_filter_active_days=12,
        worst_total_return=-0.018,
    )
    bundle = CandidateReportBundle(
        report_dir=bundle.report_dir,
        candidate_selection=bundle.candidate_selection,
        candidate_research_precheck=bundle.candidate_research_precheck,
        candidate_walk_forward=bundle.candidate_walk_forward,
        factor_diagnostics=bundle.factor_diagnostics,
        regime_validation=bundle.regime_validation,
        stress_matrix={
            "status": "RESEARCH_ONLY",
            "promotion_decision": "BLOCK",
            "summaries": [
                {
                    "candidate": "trend_filtered_quarterly_price_volume",
                    "status": "WATCH",
                    "scenario_count": 7,
                    "pass_count": 0,
                    "watch_count": 7,
                    "block_count": 0,
                    "worst_total_return": -0.018,
                    "worst_max_drawdown": 0.183,
                    "max_turnover_pct": 0.62,
                    "findings": ["No stress scenario reached PASS."],
                }
            ],
        },
    )

    report = build_candidate_next_experiments_report([bundle])
    items = [item for item in report.experiments if item.category == "quarterly_trend_vs_baseline"]

    assert items
    assert items[0].candidate == "trend_filtered_quarterly_price_volume"
    assert "trend_filtered_price_volume" in items[0].recommendation
    assert any("trend_filter_active_days=12" in evidence for evidence in items[0].evidence)
    assert "--candidate trend_filtered_price_volume" in items[0].command_hint
    assert "--candidate trend_filtered_quarterly_price_volume" in items[0].command_hint


def test_next_experiments_add_liquidity_neutral_guard_lineage_follow_up() -> None:
    bundle = _bundle(
        "liquidity_neutral_momentum_guard_price_volume",
        annualized_return=0.2160,
        max_drawdown=0.0813,
        sharpe_ratio=1.52,
        avg_turnover_pct=0.6837,
        worst_total_return=-0.0298,
    )
    bundle = CandidateReportBundle(
        report_dir=bundle.report_dir,
        candidate_selection=bundle.candidate_selection,
        candidate_research_precheck=bundle.candidate_research_precheck,
        candidate_walk_forward=bundle.candidate_walk_forward,
        factor_diagnostics=bundle.factor_diagnostics,
        regime_validation=bundle.regime_validation,
        stress_matrix={
            "status": "RESEARCH_ONLY",
            "promotion_decision": "BLOCK",
            "summaries": [
                {
                    "candidate": "liquidity_neutral_momentum_guard_price_volume",
                    "status": "WATCH",
                    "scenario_count": 4,
                    "pass_count": 0,
                    "watch_count": 4,
                    "block_count": 0,
                    "worst_total_return": -0.0236,
                    "worst_max_drawdown": 0.1049,
                    "max_turnover_pct": 0.9129,
                    "findings": ["No stress scenario reached PASS."],
                }
            ],
        },
    )

    report = build_candidate_next_experiments_report([bundle])
    payload = report.to_dict()
    items = [
        item
        for item in report.experiments
        if item.category == "liquidity_neutral_guard_lineage_review"
    ]

    assert payload["status"] == "RESEARCH_ONLY"
    assert payload["promotion_decision"] == "BLOCK"
    assert payload["can_enter_paper"] is False
    assert payload["can_enter_micro_live_ready"] is False
    assert payload["can_generate_broker_orders"] is False
    assert items
    assert items[0].candidate == "liquidity_neutral_momentum_guard_price_volume"
    assert "three-candidate lineage review" in items[0].recommendation
    assert "stable_universe_slow_signal_price_volume" in items[0].recommendation
    assert "long_momentum_liquidity_monthly_price_volume" in items[0].recommendation
    assert "--candidate stable_universe_slow_signal_price_volume" in items[0].command_hint
    assert "--candidate long_momentum_liquidity_monthly_price_volume" in items[0].command_hint
    assert (
        "--candidate liquidity_neutral_momentum_guard_price_volume"
        in items[0].command_hint
    )
    assert any("lineage=stable_universe" in evidence for evidence in items[0].evidence)
    assert items[0].allowed_stage == "research"
    assert items[0].can_enter_paper is False
    assert items[0].can_enter_micro_live_ready is False
    assert items[0].can_generate_broker_orders is False


def test_next_experiments_add_stress_pass_lower_concentration_variant_candidate() -> None:
    bundle = _bundle(
        "trend_filtered_quarterly_price_volume",
        annualized_return=0.1572,
        max_drawdown=0.138,
        sharpe_ratio=1.14,
        avg_turnover_pct=0.7306,
        trend_filter=True,
        trend_filter_active_days=9,
        worst_total_return=0.012,
    )
    bundle = CandidateReportBundle(
        report_dir=bundle.report_dir,
        candidate_selection=bundle.candidate_selection,
        candidate_research_precheck=bundle.candidate_research_precheck,
        candidate_walk_forward=bundle.candidate_walk_forward,
        factor_diagnostics=bundle.factor_diagnostics,
        regime_validation=bundle.regime_validation,
        stress_matrix={
            "status": "RESEARCH_ONLY",
            "promotion_decision": "BLOCK",
            "summaries": [
                {
                    "candidate": "trend_filtered_quarterly_price_volume",
                    "status": "WATCH",
                    "scenario_count": 7,
                    "pass_count": 1,
                    "watch_count": 6,
                    "block_count": 0,
                    "worst_total_return": 0.012,
                    "worst_max_drawdown": 0.138,
                    "max_turnover_pct": 0.7306,
                    "findings": ["lower_concentration scenario reached PASS."],
                }
            ],
            "results": [
                {
                    "candidate": "trend_filtered_quarterly_price_volume",
                    "scenario": "lower_concentration",
                    "status": "PASS",
                    "metrics": {
                        "total_return": 0.503,
                        "annualized_return": 0.1572,
                        "max_drawdown": 0.138,
                        "sharpe_ratio": 1.14,
                    },
                    "avg_turnover_pct": 0.7306,
                    "reject_rate": 0.0,
                    "parameters": {
                        "n_holdings": 40,
                        "max_weight": 0.0245,
                        "rebalance": "quarterly",
                    },
                }
            ],
        },
    )

    report = build_candidate_next_experiments_report([bundle])
    items = [
        item for item in report.experiments if item.category == "stress_pass_variant_candidate"
    ]

    assert items
    assert items[0].candidate == "trend_filtered_quarterly_price_volume"
    assert "trend_filtered_quarterly_low_concentration_price_volume" in items[0].recommendation
    assert "lower_concentration_status=PASS" in items[0].evidence
    assert "--candidate trend_filtered_quarterly_price_volume" in items[0].command_hint
    assert (
        "--candidate trend_filtered_quarterly_low_concentration_price_volume"
        in items[0].command_hint
    )
    assert items[0].allowed_stage == "research"
    assert items[0].can_enter_paper is False
    assert items[0].can_generate_broker_orders is False


def test_next_experiments_writer_and_cli_emit_three_files(tmp_path: Path) -> None:
    report_dir = tmp_path / "precheck"
    report_dir.mkdir()
    _write_bundle_files(report_dir, _bundle("low_turnover_price_volume"))

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_candidate_next_experiments.py",
            "--report-dir",
            str(report_dir),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((report_dir / "candidate_next_experiments.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["status"] == "RESEARCH_ONLY"
    assert payload["promotion_decision"] == "BLOCK"
    assert (report_dir / "candidate_next_experiments.md").exists()
    assert (report_dir / "candidate_next_experiments.csv").exists()
    loaded = load_candidate_report_bundle(report_dir)
    assert loaded.candidate_selection["results"][0]["name"] == "low_turnover_price_volume"


def test_next_experiments_writer_keeps_research_only_boundaries(tmp_path: Path) -> None:
    report = build_candidate_next_experiments_report([_bundle("low_turnover_price_volume")])
    out = write_candidate_next_experiments_report(report, tmp_path)
    payload = json.loads((out / "candidate_next_experiments.json").read_text(encoding="utf-8"))
    markdown = (out / "candidate_next_experiments.md").read_text(encoding="utf-8")
    csv_text = (out / "candidate_next_experiments.csv").read_text(encoding="utf-8")

    assert payload["status"] == "RESEARCH_ONLY"
    assert payload["promotion_decision"] == "BLOCK"
    assert "cannot satisfy a launch gate" in markdown
    assert "can_generate_broker_orders" in csv_text


def _bundle(
    candidate: str,
    *,
    annualized_return: float = -0.10,
    max_drawdown: float = 0.08,
    sharpe_ratio: float = -0.50,
    reject_rate: float = 0.03,
    avg_turnover_pct: float = 0.85,
    avg_maintenance_turnover_pct: float = 0.0,
    return_margin: float = -0.25,
    trend_filter: bool = False,
    trend_filter_active_days: int = 0,
    worst_total_return: float = -0.03,
    factor_diagnostics: dict | None = None,
    regime_summary: dict | None = None,
) -> CandidateReportBundle:
    return CandidateReportBundle(
        report_dir="results/research_recent/test_precheck",
        candidate_selection={
            "status": "BLOCK",
            "top_candidate": candidate,
            "selected_candidate": "",
            "results": [
                {
                    "name": candidate,
                    "trend_filter": trend_filter,
                    "score": {"decision": "BLOCK", "score": 20.0},
                    "metrics": {
                        "annualized_return": annualized_return,
                        "max_drawdown": max_drawdown,
                        "sharpe_ratio": sharpe_ratio,
                    },
                    "reject_rate": reject_rate,
                    "avg_turnover_pct": avg_turnover_pct,
                    "avg_maintenance_turnover_pct": avg_maintenance_turnover_pct,
                    "trend_filter_active_days": trend_filter_active_days,
                    "capital_goal_fit_review": {
                        "status": "BLOCK",
                        "return_margin": return_margin,
                        "findings": ["Annual return is below required path."],
                    },
                }
            ],
        },
        candidate_research_precheck={
            "status": "RESEARCH_ONLY",
            "promotion_decision": "BLOCK",
            "candidates": [candidate],
            "missing_promotion_evidence": [
                "candidate_factor_diagnostics.json was not generated in this precheck run.",
                "candidate_regime_validation_report.json was not generated in this precheck run.",
            ],
        },
        candidate_walk_forward={
            "status": "WATCH",
            "summaries": [
                {
                    "candidate": candidate,
                    "status": "WATCH",
                    "window_count": 3,
                    "positive_return_ratio": 0.6667,
                    "worst_total_return": worst_total_return,
                    "worst_max_drawdown": 0.0967,
                    "trend_filter_active_days": trend_filter_active_days,
                }
            ],
        },
        factor_diagnostics={
            "status": factor_diagnostics["status"],
            "diagnostics": [{"candidate": candidate, **factor_diagnostics}],
        }
        if factor_diagnostics
        else {},
        regime_validation={
            "status": regime_summary["status"],
            "summaries": [{"candidate": candidate, **regime_summary}],
        }
        if regime_summary
        else {},
    )


def _write_bundle_files(report_dir: Path, bundle: CandidateReportBundle) -> None:
    (report_dir / "candidate_selection.json").write_text(
        json.dumps(bundle.candidate_selection),
        encoding="utf-8",
    )
    (report_dir / "candidate_research_precheck.json").write_text(
        json.dumps(bundle.candidate_research_precheck),
        encoding="utf-8",
    )
    (report_dir / "candidate_walk_forward_report.json").write_text(
        json.dumps(bundle.candidate_walk_forward),
        encoding="utf-8",
    )
    if bundle.factor_diagnostics:
        (report_dir / "candidate_factor_diagnostics.json").write_text(
            json.dumps(bundle.factor_diagnostics),
            encoding="utf-8",
        )
    if bundle.regime_validation:
        (report_dir / "candidate_regime_validation_report.json").write_text(
            json.dumps(bundle.regime_validation),
            encoding="utf-8",
        )
