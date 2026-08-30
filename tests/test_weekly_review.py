from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from quantify.ops import build_weekly_review, write_weekly_review
from tests.selection_safe_fixtures import (
    selection_safe_robustness_payload,
    selection_safe_walk_forward_payload,
)
from tests.statistical_evidence_fixtures import write_statistical_evidence_fixtures


def test_weekly_review_pauses_on_block_and_missing_evidence(tmp_path: Path) -> None:
    _write_bootstrap(tmp_path)
    _write_json(
        tmp_path / "data_audit.json", {"status": "PASS", "findings": [], "demo_data_used": False}
    )
    _write_json(
        tmp_path / "real_data_gate.json",
        {"decision": "PASS", "latest_bar_date": "2026-06-12", "staleness_days": 0},
    )
    _write_json(tmp_path / "data_coverage.json", {"status": "PASS", "average_coverage_ratio": 1.0})
    _write_json(tmp_path / "market_regime.json", {"status": "WATCH", "label": "defensive"})
    _write_json(tmp_path / "robustness_report.json", {"status": "BLOCK", "scenarios": []})
    _write_json(
        tmp_path / "walk_forward_report.json",
        {"status": "WATCH", "window_count": 3, "pass_count": 1},
    )
    _write_json(
        tmp_path / "candidate_walk_forward_report.json",
        {"status": "WATCH", "best_candidate": "defensive_low_vol", "candidate_count": 5},
    )
    _write_json(
        tmp_path / "candidate_factor_diagnostics.json", {"status": "WATCH", "candidate_count": 5}
    )
    _write_json(
        tmp_path / "candidate_regime_validation_report.json",
        {
            "status": "WATCH",
            "best_candidate": "defensive_low_vol",
            "regime_count": 1,
            "window_count": 3,
        },
    )
    _write_json(
        tmp_path / "candidate_experiment_launch.json",
        {
            "decision": "WATCH",
            "selected_candidate": "defensive_low_vol",
            "run_id": "run",
            "blocked_by": [],
        },
    )
    _write_json(
        tmp_path / "candidate_experiment_completion.json",
        {
            "decision": "WATCH",
            "selected_candidate": "defensive_low_vol",
            "blockers": [],
            "watch_items": ["llm_review.json: missing evidence"],
        },
    )
    _write_json(
        tmp_path / "candidate_selection.json",
        {"status": "WATCH", "best_candidate": "defensive_low_vol"},
    )
    _write_json(
        tmp_path / "recent_candidate_research.json",
        {
            "artifact_type": "recent_candidate_research",
            "status": "RESEARCH_ONLY",
            "best_research_candidate": "defensive_low_vol",
            "best_research_reason": "Recent research remains defensive-first while robustness is unresolved.",
            "best_research_command": "python examples/run_candidate_research_precheck.py --candidate defensive_low_vol",
            "candidate_count": 1,
            "report_count": 1,
            "can_enter_paper": False,
        },
    )
    _write_json(
        tmp_path / "llm_review.json",
        {"decision": "WATCH", "missing_evidence": [], "next_experiments": []},
    )
    _write_json(tmp_path / "paper_state.json", {"observed_days": 25, "broker_connection": "none"})
    _write_paper_daily_review(tmp_path, status="PASS")
    _write_paper_stability(tmp_path, status="WATCH")

    review = build_weekly_review(tmp_path, as_of="2026-06-12")
    out = write_weekly_review(tmp_path, as_of="2026-06-12")
    written = json.loads((out / "weekly_review.json").read_text(encoding="utf-8"))

    assert review.decision == "pause_and_fix"
    assert review.research_focus["best_research_candidate"] == "defensive_low_vol"
    assert any("robustness" in blocker for blocker in review.blockers)
    assert any(
        component.name == "benchmark_report" and component.status == "BLOCK"
        for component in review.components
    )
    assert any("benchmark_report.json" in action for action in review.required_actions)
    assert written["decision"] == "pause_and_fix"
    assert "Weekly Quant Review" in (out / "weekly_review.md").read_text(encoding="utf-8")


def test_weekly_review_continue_paper_when_core_gates_pass(tmp_path: Path) -> None:
    _write_bootstrap(tmp_path)
    _write_json(
        tmp_path / "data_audit.json", {"status": "PASS", "findings": [], "demo_data_used": False}
    )
    _write_json(
        tmp_path / "real_data_gate.json",
        {"decision": "PASS", "latest_bar_date": "2026-06-12", "staleness_days": 0},
    )
    _write_json(tmp_path / "data_coverage.json", {"status": "PASS", "average_coverage_ratio": 1.0})
    _write_json(tmp_path / "market_regime.json", {"status": "PASS", "label": "neutral"})
    _write_json(
        tmp_path / "robustness_report.json", {"status": "PASS", "scenarios": [{"name": "baseline"}]}
    )
    _write_json(
        tmp_path / "walk_forward_report.json",
        {"status": "PASS", "window_count": 3, "pass_count": 3},
    )
    _write_json(
        tmp_path / "candidate_walk_forward_report.json",
        {"status": "PASS", "best_candidate": "core_multifactor", "candidate_count": 5},
    )
    _write_json(
        tmp_path / "candidate_factor_diagnostics.json", {"status": "PASS", "candidate_count": 5}
    )
    _write_json(
        tmp_path / "candidate_regime_validation_report.json",
        {
            "status": "PASS",
            "best_candidate": "core_multifactor",
            "regime_count": 2,
            "window_count": 3,
        },
    )
    _write_json(
        tmp_path / "candidate_experiment_launch.json",
        {
            "decision": "PASS",
            "selected_candidate": "core_multifactor",
            "run_id": "run",
            "blocked_by": [],
        },
    )
    _write_json(
        tmp_path / "candidate_experiment_completion.json",
        {
            "decision": "PASS",
            "selected_candidate": "core_multifactor",
            "blockers": [],
            "watch_items": [],
        },
    )
    _write_json(
        tmp_path / "candidate_selection.json",
        {"status": "PASS", "best_candidate": "core_multifactor"},
    )
    _write_json(
        tmp_path / "recent_candidate_research.json",
        {
            "artifact_type": "recent_candidate_research",
            "status": "RESEARCH_ONLY",
            "best_research_candidate": "core_multifactor",
            "best_research_reason": "Cross-run research evidence currently points to core_multifactor.",
            "best_research_command": "python examples/run_candidate_research_precheck.py --candidate core_multifactor",
            "candidate_count": 2,
            "report_count": 4,
            "can_enter_paper": False,
        },
    )
    _write_json(
        tmp_path / "llm_review.json",
        {"decision": "PASS", "missing_evidence": [], "next_experiments": []},
    )
    _write_json(tmp_path / "paper_state.json", {"observed_days": 25, "broker_connection": "none"})
    _write_paper_daily_review(tmp_path, status="PASS")
    _write_paper_stability(tmp_path, status="PASS")
    _write_json(tmp_path / "micro_live_readiness.json", {"decision": "PASS", "findings": []})
    write_statistical_evidence_fixtures(tmp_path)

    review = build_weekly_review(tmp_path, as_of="2026-06-12")

    assert review.decision == "continue_paper"
    assert not review.blockers
    assert any(component.name == "recent_candidate_research" for component in review.components)
    assert any(component.name == "paper_daily_review" for component in review.components)
    assert all(
        "unattended live broker orders" not in action.lower() for action in review.required_actions
    )


def test_weekly_review_surfaces_paper_daily_watch(tmp_path: Path) -> None:
    _write_bootstrap(tmp_path)
    _write_json(
        tmp_path / "data_audit.json", {"status": "PASS", "findings": [], "demo_data_used": False}
    )
    _write_json(
        tmp_path / "real_data_gate.json",
        {"decision": "PASS", "latest_bar_date": "2026-06-12", "staleness_days": 0},
    )
    _write_json(tmp_path / "data_coverage.json", {"status": "PASS", "average_coverage_ratio": 1.0})
    _write_json(tmp_path / "market_regime.json", {"status": "PASS", "label": "neutral"})
    _write_json(tmp_path / "robustness_report.json", {"status": "PASS", "scenarios": []})
    _write_json(
        tmp_path / "walk_forward_report.json",
        {"status": "PASS", "window_count": 3, "pass_count": 3},
    )
    _write_json(
        tmp_path / "candidate_walk_forward_report.json",
        {"status": "PASS", "best_candidate": "core_multifactor", "candidate_count": 5},
    )
    _write_json(
        tmp_path / "candidate_factor_diagnostics.json", {"status": "PASS", "candidate_count": 5}
    )
    _write_json(
        tmp_path / "candidate_regime_validation_report.json",
        {
            "status": "PASS",
            "best_candidate": "core_multifactor",
            "regime_count": 2,
            "window_count": 3,
        },
    )
    _write_json(
        tmp_path / "candidate_experiment_launch.json",
        {
            "decision": "PASS",
            "selected_candidate": "core_multifactor",
            "run_id": "run",
            "blocked_by": [],
        },
    )
    _write_json(
        tmp_path / "candidate_experiment_completion.json",
        {
            "decision": "PASS",
            "selected_candidate": "core_multifactor",
            "blockers": [],
            "watch_items": [],
        },
    )
    _write_json(
        tmp_path / "candidate_selection.json",
        {"status": "PASS", "best_candidate": "core_multifactor"},
    )
    _write_json(
        tmp_path / "recent_candidate_research.json",
        {
            "artifact_type": "recent_candidate_research",
            "status": "RESEARCH_ONLY",
            "best_research_candidate": "core_multifactor",
            "best_research_reason": "Recent research still leans core_multifactor while paper execution has a watch item.",
            "best_research_command": "python examples/run_candidate_research_precheck.py --candidate core_multifactor",
            "candidate_count": 2,
            "report_count": 4,
            "can_enter_paper": False,
        },
    )
    _write_json(
        tmp_path / "llm_review.json",
        {"decision": "PASS", "missing_evidence": [], "next_experiments": []},
    )
    _write_json(tmp_path / "paper_state.json", {"observed_days": 25, "broker_connection": "none"})
    _write_paper_daily_review(tmp_path, status="WATCH", latest_rejected=1)
    _write_paper_stability(tmp_path, status="PASS")
    _write_json(tmp_path / "micro_live_readiness.json", {"decision": "PASS", "findings": []})
    write_statistical_evidence_fixtures(tmp_path)

    review = build_weekly_review(tmp_path, as_of="2026-06-12")

    assert review.decision == "research_only"
    assert any("paper_daily_review" in item for item in review.watch_items)


def test_weekly_review_surfaces_micro_live_readiness_finding(
    tmp_path: Path,
) -> None:
    _write_all_core_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "micro_live_readiness.json",
        {
            "decision": "BLOCK",
            "findings": [
                {
                    "severity": "BLOCK",
                    "code": "MISSING_APPROVAL",
                    "message": "approval_record.json is required.",
                }
            ],
        },
    )

    review = build_weekly_review(tmp_path, as_of="2026-06-12")
    out = write_weekly_review(tmp_path, as_of="2026-06-12")
    markdown = (out / "weekly_review.md").read_text(encoding="utf-8")

    assert review.decision == "pause_and_fix"
    assert any("MISSING_APPROVAL" in blocker for blocker in review.blockers)
    assert "approval_record.json is required" in markdown


def test_weekly_review_blocks_candidate_mismatch_in_statistical_evidence(
    tmp_path: Path,
) -> None:
    _write_all_core_pass_artifacts(tmp_path)
    payload = json.loads((tmp_path / "multiple_testing_report.json").read_text(encoding="utf-8"))
    payload["parameters"]["selected_candidate"] = "defensive_low_vol"
    _write_json(tmp_path / "multiple_testing_report.json", payload)

    review = build_weekly_review(tmp_path, as_of="2026-06-12")

    component = next(item for item in review.components if item.name == "multiple_testing_report")
    assert review.decision == "pause_and_fix"
    assert component.status == "BLOCK"
    assert "does not match the deterministic selected candidate" in component.summary
    assert any("multiple_testing_report.json" in action for action in review.required_actions)


def test_weekly_review_cli_writes_artifacts(tmp_path: Path) -> None:
    _write_bootstrap(tmp_path)
    _write_json(
        tmp_path / "data_audit.json", {"status": "PASS", "findings": [], "demo_data_used": False}
    )
    _write_json(
        tmp_path / "real_data_gate.json",
        {"decision": "PASS", "latest_bar_date": "2026-06-12", "staleness_days": 0},
    )
    _write_json(tmp_path / "data_coverage.json", {"status": "PASS", "average_coverage_ratio": 1.0})
    _write_json(tmp_path / "market_regime.json", {"status": "PASS", "label": "neutral"})
    _write_json(tmp_path / "robustness_report.json", {"status": "PASS", "scenarios": []})
    _write_json(
        tmp_path / "walk_forward_report.json",
        {"status": "PASS", "window_count": 3, "pass_count": 3},
    )
    _write_json(
        tmp_path / "candidate_walk_forward_report.json",
        {"status": "PASS", "best_candidate": "core_multifactor", "candidate_count": 5},
    )
    _write_json(
        tmp_path / "candidate_factor_diagnostics.json", {"status": "PASS", "candidate_count": 5}
    )
    _write_json(
        tmp_path / "candidate_regime_validation_report.json",
        {
            "status": "PASS",
            "best_candidate": "core_multifactor",
            "regime_count": 2,
            "window_count": 3,
        },
    )
    _write_json(
        tmp_path / "candidate_experiment_launch.json",
        {
            "decision": "PASS",
            "selected_candidate": "core_multifactor",
            "run_id": "run",
            "blocked_by": [],
        },
    )
    _write_json(
        tmp_path / "candidate_experiment_completion.json",
        {
            "decision": "PASS",
            "selected_candidate": "core_multifactor",
            "blockers": [],
            "watch_items": [],
        },
    )
    _write_json(
        tmp_path / "candidate_selection.json",
        {"status": "WATCH", "best_candidate": "core_multifactor"},
    )
    _write_json(
        tmp_path / "recent_candidate_research.json",
        {
            "artifact_type": "recent_candidate_research",
            "status": "RESEARCH_ONLY",
            "best_research_candidate": "core_multifactor",
            "best_research_reason": "Recent candidate rollup is advisory-only and does not clear weekly gates.",
            "best_research_command": "python examples/run_candidate_research_precheck.py --candidate core_multifactor",
            "candidate_count": 2,
            "report_count": 4,
            "can_enter_paper": False,
        },
    )
    _write_json(
        tmp_path / "llm_review.json",
        {"decision": "WATCH", "missing_evidence": [], "next_experiments": []},
    )
    _write_json(tmp_path / "paper_state.json", {"observed_days": 25, "broker_connection": "none"})
    _write_paper_daily_review(tmp_path, status="PASS")
    _write_paper_stability(tmp_path, status="PASS")

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_weekly_review.py",
            "--report-dir",
            str(tmp_path),
            "--as-of",
            "2026-06-12",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert (tmp_path / "weekly_review.json").exists()
    assert (tmp_path / "weekly_review.md").exists()


def test_weekly_review_pauses_when_candidate_completion_missing(tmp_path: Path) -> None:
    _write_bootstrap(tmp_path)
    _write_json(
        tmp_path / "data_audit.json", {"status": "PASS", "findings": [], "demo_data_used": False}
    )
    _write_json(
        tmp_path / "real_data_gate.json",
        {"decision": "PASS", "latest_bar_date": "2026-06-12", "staleness_days": 0},
    )
    _write_json(tmp_path / "data_coverage.json", {"status": "PASS", "average_coverage_ratio": 1.0})
    _write_json(tmp_path / "market_regime.json", {"status": "PASS", "label": "neutral"})
    _write_json(tmp_path / "robustness_report.json", {"status": "PASS", "scenarios": []})
    _write_json(
        tmp_path / "walk_forward_report.json",
        {"status": "PASS", "window_count": 3, "pass_count": 3},
    )
    _write_json(
        tmp_path / "candidate_walk_forward_report.json",
        {"status": "PASS", "best_candidate": "core_multifactor", "candidate_count": 5},
    )
    _write_json(
        tmp_path / "candidate_factor_diagnostics.json", {"status": "PASS", "candidate_count": 5}
    )
    _write_json(
        tmp_path / "candidate_regime_validation_report.json",
        {
            "status": "PASS",
            "best_candidate": "core_multifactor",
            "regime_count": 2,
            "window_count": 3,
        },
    )
    _write_json(
        tmp_path / "candidate_experiment_launch.json",
        {
            "decision": "PASS",
            "selected_candidate": "core_multifactor",
            "run_id": "run",
            "blocked_by": [],
        },
    )
    _write_json(
        tmp_path / "candidate_selection.json",
        {"status": "PASS", "best_candidate": "core_multifactor"},
    )
    _write_json(
        tmp_path / "recent_candidate_research.json",
        {
            "artifact_type": "recent_candidate_research",
            "status": "RESEARCH_ONLY",
            "best_research_candidate": "core_multifactor",
            "best_research_reason": "Recent candidate evidence exists but completion evidence is missing.",
            "best_research_command": "python examples/run_candidate_research_precheck.py --candidate core_multifactor",
            "candidate_count": 2,
            "report_count": 4,
            "can_enter_paper": False,
        },
    )
    _write_json(
        tmp_path / "llm_review.json",
        {"decision": "PASS", "missing_evidence": [], "next_experiments": []},
    )
    _write_json(tmp_path / "paper_state.json", {"observed_days": 25, "broker_connection": "none"})
    _write_paper_daily_review(tmp_path, status="PASS")
    _write_paper_stability(tmp_path, status="PASS")
    _write_json(tmp_path / "micro_live_readiness.json", {"decision": "PASS", "findings": []})

    review = build_weekly_review(tmp_path, as_of="2026-06-12")

    assert review.decision == "pause_and_fix"
    assert any("candidate_experiment_completion" in blocker for blocker in review.blockers)


def _write_json(path: Path, payload: dict) -> None:
    if path.name == "robustness_report.json":
        payload = selection_safe_robustness_payload(status=str(payload.get("status", "PASS")))
    elif path.name == "walk_forward_report.json":
        payload = selection_safe_walk_forward_payload(status=str(payload.get("status", "PASS")))
    elif path.name == "candidate_walk_forward_report.json":
        candidate = str(payload.get("best_candidate") or "core_multifactor")
        payload = selection_safe_walk_forward_payload(
            status=str(payload.get("status", "PASS")),
            candidate=candidate,
        )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_bootstrap(root: Path) -> None:
    _write_json(
        root / "real_data_bootstrap.json",
        {
            "decision": "PASS",
            "cache_exists": True,
            "allow_demo_data": False,
            "latest_bar_date": "2026-06-12",
        },
    )


def _write_paper_stability(root: Path, *, status: str) -> None:
    _write_json(
        root / "paper_stability.json",
        {
            "status": status,
            "observed_days": 40,
            "max_drawdown": 0.03,
            "reject_rate": 0.0,
        },
    )


def _write_paper_daily_review(root: Path, *, status: str, latest_rejected: int = 0) -> None:
    _write_json(
        root / "paper_daily_review.json",
        {
            "status": status,
            "state": {
                "last_equity": 105_000.0,
                "cash": 20_000.0,
                "position_count": 3,
                "broker_connection": "none",
            },
            "execution_quality": {
                "latest_rejected_order_count": latest_rejected,
                "reject_rate": 0.0,
            },
            "target_deviation": {"max_abs_target_deviation": 0.0},
        },
    )


def _write_all_core_pass_artifacts(root: Path) -> None:
    _write_bootstrap(root)
    _write_json(
        root / "data_audit.json", {"status": "PASS", "findings": [], "demo_data_used": False}
    )
    _write_json(
        root / "real_data_gate.json",
        {"decision": "PASS", "latest_bar_date": "2026-06-12", "staleness_days": 0},
    )
    _write_json(root / "data_coverage.json", {"status": "PASS", "average_coverage_ratio": 1.0})
    _write_json(root / "market_regime.json", {"status": "PASS", "label": "neutral"})
    _write_json(root / "robustness_report.json", {"status": "PASS", "scenarios": []})
    _write_json(
        root / "walk_forward_report.json", {"status": "PASS", "window_count": 3, "pass_count": 3}
    )
    _write_json(
        root / "candidate_walk_forward_report.json",
        {"status": "PASS", "best_candidate": "core_multifactor", "candidate_count": 5},
    )
    _write_json(
        root / "candidate_factor_diagnostics.json", {"status": "PASS", "candidate_count": 5}
    )
    _write_json(
        root / "candidate_regime_validation_report.json",
        {
            "status": "PASS",
            "best_candidate": "core_multifactor",
            "regime_count": 2,
            "window_count": 3,
        },
    )
    _write_json(
        root / "candidate_experiment_launch.json",
        {
            "decision": "PASS",
            "selected_candidate": "core_multifactor",
            "run_id": "run",
            "blocked_by": [],
        },
    )
    _write_json(
        root / "candidate_experiment_completion.json",
        {
            "decision": "PASS",
            "selected_candidate": "core_multifactor",
            "blockers": [],
            "watch_items": [],
        },
    )
    _write_json(
        root / "candidate_selection.json", {"status": "PASS", "best_candidate": "core_multifactor"}
    )
    _write_json(
        root / "recent_candidate_research.json",
        {
            "artifact_type": "recent_candidate_research",
            "status": "RESEARCH_ONLY",
            "best_research_candidate": "core_multifactor",
            "best_research_reason": "Cross-run research evidence currently points to core_multifactor.",
            "best_research_command": "python examples/run_candidate_research_precheck.py --candidate core_multifactor",
            "candidate_count": 2,
            "report_count": 4,
            "can_enter_paper": False,
        },
    )
    _write_json(
        root / "llm_review.json",
        {"decision": "PASS", "missing_evidence": [], "next_experiments": []},
    )
    _write_json(root / "paper_state.json", {"observed_days": 25, "broker_connection": "none"})
    _write_paper_daily_review(root, status="PASS")
    _write_paper_stability(root, status="PASS")
    write_statistical_evidence_fixtures(root)
