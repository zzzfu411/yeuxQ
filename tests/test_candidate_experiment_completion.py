from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from tests.selection_safe_fixtures import selection_safe_walk_forward_payload

from quantify.research.candidate_experiment_completion import (
    build_candidate_experiment_completion,
    write_candidate_experiment_completion,
)


def test_candidate_experiment_completion_blocks_missing_launch(tmp_path: Path) -> None:
    review = build_candidate_experiment_completion(tmp_path, as_of="2026-06-08")
    out = write_candidate_experiment_completion(review, tmp_path)

    payload = json.loads((out / "candidate_experiment_completion.json").read_text(encoding="utf-8"))
    markdown = (out / "candidate_experiment_completion.md").read_text(encoding="utf-8")
    assert payload["decision"] == "BLOCK"
    assert payload["artifacts"][0]["status"] == "MISSING"
    assert "deterministic research-completion gate" in markdown


def test_candidate_experiment_completion_blocks_when_launch_blocks(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "candidate_experiment_launch.json",
        {
            "decision": "BLOCK",
            "as_of": "2026-06-08",
            "selected_candidate": "",
            "run_id": "",
            "experiment_dir": "",
        },
    )

    review = build_candidate_experiment_completion(tmp_path)

    assert review.decision == "BLOCK"
    assert review.launch_decision == "BLOCK"
    assert any("Launch plan is not PASS" in blocker for blocker in review.blockers)


def test_candidate_experiment_completion_blocks_missing_required_output(tmp_path: Path) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(tmp_path, experiment_dir)

    review = build_candidate_experiment_completion(tmp_path)

    assert review.decision == "BLOCK"
    assert any(artifact.status == "MISSING" for artifact in review.artifacts)
    assert any("candidate_walk_forward_report.json" in blocker for blocker in review.blockers)
    assert any("candidate_experiment_execution" in blocker for blocker in review.blockers)


def test_candidate_experiment_completion_blocks_required_output_outside_experiment_dir(
    tmp_path: Path,
) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    external = tmp_path / "external" / "candidate_walk_forward_report.json"
    _write_json(
        tmp_path / "candidate_experiment_launch.json",
        {
            "decision": "PASS",
            "as_of": "2026-06-08",
            "selected_candidate": "core_multifactor",
            "run_id": "run",
            "experiment_dir": str(experiment_dir),
            "required_outputs": [str(experiment_dir / "candidate_experiment_evidence.json"), str(external)],
        },
    )
    _write_json(external, {"status": "PASS", "best_candidate": "core_multifactor"})
    _write_execution(tmp_path, decision="PASS")

    review = build_candidate_experiment_completion(tmp_path)

    assert review.decision == "BLOCK"
    assert any("outside launch experiment_dir" in blocker for blocker in review.blockers)


def test_candidate_experiment_completion_blocks_empty_experiment_dir(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "candidate_experiment_launch.json",
        {
            "decision": "PASS",
            "as_of": "2026-06-08",
            "selected_candidate": "core_multifactor",
            "run_id": "run",
            "experiment_dir": "",
            "required_outputs": [str(tmp_path / "candidate_experiment_evidence.json")],
        },
    )
    _write_execution(tmp_path, decision="PASS")

    review = build_candidate_experiment_completion(tmp_path)

    assert review.decision == "BLOCK"
    assert any("empty experiment_dir" in blocker for blocker in review.blockers)


def test_candidate_experiment_completion_passes_complete_outputs(tmp_path: Path) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(tmp_path, experiment_dir)
    _write_required_outputs(experiment_dir, status="PASS")

    review = build_candidate_experiment_completion(tmp_path, as_of="2026-06-08")

    assert review.decision == "PASS"
    assert review.selected_candidate == "core_multifactor"
    assert review.blockers == []
    assert all(artifact.status == "PASS" for artifact in review.artifacts)


def test_candidate_experiment_completion_watches_legacy_launch_missing_long_term_controls(
    tmp_path: Path,
) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    required = [
        "candidate_experiment_evidence.json",
        "candidate_walk_forward_report.json",
        "candidate_factor_diagnostics.json",
        "candidate_regime_validation_report.json",
        "candidate_stress_matrix.json",
        "candidate_selection.json",
        "llm_review.json",
    ]
    _write_json(
        tmp_path / "candidate_experiment_launch.json",
        {
            "decision": "PASS",
            "as_of": "2026-06-08",
            "selected_candidate": "core_multifactor",
            "run_id": "run",
            "experiment_dir": str(experiment_dir),
            "required_outputs": [str(experiment_dir / item) for item in required],
        },
    )
    _write_required_outputs(experiment_dir, status="PASS")

    review = build_candidate_experiment_completion(tmp_path)

    assert review.decision == "WATCH"
    assert any("launch_contract" in item for item in review.watch_items)
    assert any("capital_goal_fit_tests" in item for item in review.watch_items)
    assert any("minimum_evidence_window" in item for item in review.watch_items)


def test_candidate_experiment_completion_blocks_below_minimum_walk_forward_windows(
    tmp_path: Path,
) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(tmp_path, experiment_dir)
    _write_required_outputs(experiment_dir, status="PASS")
    _write_json(
        experiment_dir / "candidate_walk_forward_report.json",
        {
            "status": "PASS",
            "best_candidate": "core_multifactor",
            "candidate_count": 1,
            "window_count": 3,
            "summaries": [{"candidate": "core_multifactor"}],
            "windows": [{"candidate": "core_multifactor"} for _ in range(3)],
        },
    )

    review = build_candidate_experiment_completion(tmp_path)

    assert review.decision == "BLOCK"
    assert any("launch_contract_evidence" in blocker for blocker in review.blockers)
    assert any("below launch minimum 6" in blocker for blocker in review.blockers)


def test_candidate_experiment_completion_watches_missing_adverse_regime_windows(
    tmp_path: Path,
) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(tmp_path, experiment_dir)
    _write_required_outputs(experiment_dir, status="PASS")
    _write_json(
        experiment_dir / "candidate_regime_validation_report.json",
        {
            "status": "PASS",
            "best_candidate": "core_multifactor",
            "candidate_count": 1,
            "regime_count": 2,
            "adverse_regime_window_count": 0,
            "summaries": [{"candidate": "core_multifactor", "adverse_regime_window_count": 0}],
            "buckets": [{"candidate": "core_multifactor"}],
            "windows": [{"candidate": "core_multifactor"}],
        },
    )

    review = build_candidate_experiment_completion(tmp_path)

    assert review.decision == "WATCH"
    assert any("launch_contract_evidence" in item for item in review.watch_items)
    assert any("no adverse-regime windows" in item for item in review.watch_items)


def test_candidate_experiment_completion_blocks_capital_goal_fit_block(
    tmp_path: Path,
) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(tmp_path, experiment_dir)
    _write_required_outputs(experiment_dir, status="PASS")
    _write_json(
        experiment_dir / "candidate_selection.json",
        {
            "status": "PASS",
            "best_candidate": "core_multifactor",
            "selected_candidate": "core_multifactor",
            "top_candidate": "core_multifactor",
            "results": [
                {
                    "name": "core_multifactor",
                    "capital_goal_fit_status": "BLOCK",
                    "capital_goal_fit_review": {"status": "BLOCK"},
                }
            ],
        },
    )

    review = build_candidate_experiment_completion(tmp_path)

    assert review.decision == "BLOCK"
    assert any("launch_contract_evidence" in blocker for blocker in review.blockers)
    assert any("BLOCK capital_goal_fit_review" in blocker for blocker in review.blockers)


def test_candidate_experiment_completion_blocks_missing_drawdown_budget(
    tmp_path: Path,
) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(tmp_path, experiment_dir)
    _write_required_outputs(experiment_dir, status="PASS")
    _write_json(
        experiment_dir / "candidate_selection.json",
        {
            "status": "PASS",
            "best_candidate": "core_multifactor",
            "selected_candidate": "core_multifactor",
            "top_candidate": "core_multifactor",
            "results": [
                {
                    "name": "core_multifactor",
                    "capital_goal_fit_status": "PASS",
                    "capital_goal_fit_review": {"status": "PASS"},
                }
            ],
        },
    )

    review = build_candidate_experiment_completion(tmp_path)

    assert review.decision == "BLOCK"
    assert any("missing drawdown_budget" in blocker for blocker in review.blockers)


def test_candidate_experiment_completion_does_not_require_paper_plan(
    tmp_path: Path,
) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(tmp_path, experiment_dir)
    _write_required_outputs(experiment_dir, status="PASS")

    review = build_candidate_experiment_completion(tmp_path)

    assert review.decision == "PASS"
    assert not any("paper_candidate_plan.json" in blocker for blocker in review.blockers)


def test_candidate_experiment_completion_blocks_below_minimum_total_trading_days(
    tmp_path: Path,
) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(tmp_path, experiment_dir)
    _write_required_outputs(experiment_dir, status="PASS")
    _write_json(
        experiment_dir / "run_manifest.json",
        {
            "demo_data_used": False,
            "trading_day_count": 360,
            "in_sample_end": "2023-12-29",
            "out_sample_start": "2024-01-02",
            "out_of_sample_trading_day_count": 240,
        },
    )

    review = build_candidate_experiment_completion(tmp_path)

    assert review.decision == "BLOCK"
    assert any("Total trading-day evidence=360" in blocker for blocker in review.blockers)


def test_candidate_experiment_completion_blocks_below_minimum_out_of_sample_days(
    tmp_path: Path,
) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(tmp_path, experiment_dir)
    _write_required_outputs(experiment_dir, status="PASS")
    _write_json(
        experiment_dir / "run_manifest.json",
        {
            "demo_data_used": False,
            "trading_day_count": 720,
            "in_sample_end": "2023-12-29",
            "out_sample_start": "2024-01-02",
            "out_of_sample_trading_day_count": 120,
        },
    )

    review = build_candidate_experiment_completion(tmp_path)

    assert review.decision == "BLOCK"
    assert any("Out-of-sample trading-day evidence=120" in blocker for blocker in review.blockers)


def test_candidate_experiment_completion_blocks_walk_forward_tail_loss(
    tmp_path: Path,
) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(tmp_path, experiment_dir)
    _write_required_outputs(experiment_dir, status="PASS")
    _write_json(
        experiment_dir / "candidate_walk_forward_report.json",
        _candidate_walk_forward_payload(worst_total_return=-0.12),
    )

    review = build_candidate_experiment_completion(tmp_path)

    assert review.decision == "BLOCK"
    assert any("worst_total_return=-12.00%" in blocker for blocker in review.blockers)


def test_candidate_experiment_completion_blocks_walk_forward_drawdown_budget_breach(
    tmp_path: Path,
) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(tmp_path, experiment_dir)
    _write_required_outputs(experiment_dir, status="PASS")
    _write_json(
        experiment_dir / "candidate_walk_forward_report.json",
        _candidate_walk_forward_payload(worst_max_drawdown=0.25),
    )

    review = build_candidate_experiment_completion(tmp_path)

    assert review.decision == "BLOCK"
    assert any("exceeds drawdown budget" in blocker for blocker in review.blockers)


def test_candidate_experiment_completion_blocks_candidate_selection_mismatch(
    tmp_path: Path,
) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(tmp_path, experiment_dir)
    _write_required_outputs(experiment_dir, status="PASS")
    _write_json(
        experiment_dir / "candidate_selection.json",
        {
            "status": "PASS",
            "selected_candidate": "price_volume_defensive",
            "best_candidate": "price_volume_defensive",
            "top_candidate": "price_volume_defensive",
            "results": [{"name": "price_volume_defensive"}],
        },
    )

    review = build_candidate_experiment_completion(tmp_path)

    assert review.decision == "BLOCK"
    assert any("candidate_selection.json" in blocker for blocker in review.blockers)
    assert any("selected_candidate=price_volume_defensive" in blocker for blocker in review.blockers)


def test_candidate_experiment_completion_blocks_multi_candidate_walk_forward(
    tmp_path: Path,
) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(tmp_path, experiment_dir)
    _write_required_outputs(experiment_dir, status="PASS")
    payload = _candidate_walk_forward_payload()
    payload["candidate_count"] = 2
    payload["summaries"].append(
        {
            "candidate": "price_volume_defensive",
            "status": "PASS",
            "window_count": 6,
        }
    )
    payload["selections"].extend(
        {
            "candidate": "price_volume_defensive",
            "window": window["window"],
            "rank": 2,
        }
        for window in payload["windows"]
    )
    _write_json(experiment_dir / "candidate_walk_forward_report.json", payload)

    review = build_candidate_experiment_completion(tmp_path)

    assert review.decision == "BLOCK"
    assert any("candidate_walk_forward_report.json" in blocker for blocker in review.blockers)
    assert any("candidate_count=2" in blocker for blocker in review.blockers)


def test_candidate_experiment_completion_blocks_factor_diagnostics_without_identity(
    tmp_path: Path,
) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(tmp_path, experiment_dir)
    _write_required_outputs(experiment_dir, status="PASS")
    _write_json(
        experiment_dir / "candidate_factor_diagnostics.json",
        {"status": "PASS", "candidate_count": 1, "diagnostics": [], "warnings": []},
    )

    review = build_candidate_experiment_completion(tmp_path)

    assert review.decision == "BLOCK"
    assert any("candidate_factor_diagnostics.json" in blocker for blocker in review.blockers)
    assert any("Candidate identity missing" in blocker for blocker in review.blockers)


def test_candidate_experiment_completion_watches_watch_outputs(tmp_path: Path) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(tmp_path, experiment_dir)
    _write_required_outputs(experiment_dir, status="PASS")
    _write_json(experiment_dir / "llm_review.json", {"decision": "WATCH", "missing_evidence": []})

    review = build_candidate_experiment_completion(tmp_path)

    assert review.decision == "WATCH"
    assert any("llm_review.json" in item for item in review.watch_items)


def test_candidate_experiment_completion_watches_dry_run_execution(tmp_path: Path) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(tmp_path, experiment_dir)
    _write_required_outputs(experiment_dir, status="PASS")
    _write_execution(tmp_path, decision="DRY_RUN")

    review = build_candidate_experiment_completion(tmp_path)

    assert review.decision == "WATCH"
    assert any("dry-run" in item for item in review.watch_items)


def test_candidate_experiment_completion_blocks_failed_execution(tmp_path: Path) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(tmp_path, experiment_dir)
    _write_required_outputs(experiment_dir, status="PASS")
    _write_execution(tmp_path, decision="BLOCK", blockers=["step 2: command failed"])

    review = build_candidate_experiment_completion(tmp_path)

    assert review.decision == "BLOCK"
    assert any("step 2" in blocker for blocker in review.blockers)


def test_candidate_experiment_completion_blocks_execution_candidate_mismatch(
    tmp_path: Path,
) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(tmp_path, experiment_dir)
    _write_required_outputs(experiment_dir, status="PASS")
    _write_execution(tmp_path, decision="PASS", selected_candidate="price_volume_defensive")

    review = build_candidate_experiment_completion(tmp_path)

    assert review.decision == "BLOCK"
    assert any("Execution identity mismatch" in blocker for blocker in review.blockers)
    assert any("selected_candidate=price_volume_defensive" in blocker for blocker in review.blockers)


def test_candidate_experiment_completion_blocks_execution_experiment_dir_mismatch(
    tmp_path: Path,
) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    wrong_dir = tmp_path / "candidate_experiments" / "other"
    _write_launch(tmp_path, experiment_dir)
    _write_required_outputs(experiment_dir, status="PASS")
    _write_execution(tmp_path, decision="PASS", experiment_dir=wrong_dir)

    review = build_candidate_experiment_completion(tmp_path)

    assert review.decision == "BLOCK"
    assert any("Execution identity mismatch" in blocker for blocker in review.blockers)
    assert any("experiment_dir=" in blocker for blocker in review.blockers)


def test_candidate_experiment_completion_blocks_execution_run_id_mismatch(
    tmp_path: Path,
) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(tmp_path, experiment_dir)
    _write_required_outputs(experiment_dir, status="PASS")
    _write_execution(tmp_path, decision="PASS", run_id="other")

    review = build_candidate_experiment_completion(tmp_path)

    assert review.decision == "BLOCK"
    assert any("Execution identity mismatch" in blocker for blocker in review.blockers)
    assert any("run_id=other" in blocker for blocker in review.blockers)


def test_candidate_experiment_completion_blocks_legacy_execution_without_identity(
    tmp_path: Path,
) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(tmp_path, experiment_dir)
    _write_required_outputs(experiment_dir, status="PASS")
    _write_json(
        tmp_path / "candidate_experiment_execution.json",
        {
            "decision": "PASS",
            "steps": [{"status": "PASS"}, {"status": "PASS"}],
            "blockers": [],
        },
    )

    review = build_candidate_experiment_completion(tmp_path)

    assert review.decision == "BLOCK"
    assert any("selected_candidate=missing" in blocker for blocker in review.blockers)
    assert any("run_id=missing" in blocker for blocker in review.blockers)
    assert any("experiment_dir=missing" in blocker for blocker in review.blockers)


def test_candidate_experiment_completion_blocks_pass_launch_missing_identity(
    tmp_path: Path,
) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_json(
        tmp_path / "candidate_experiment_launch.json",
        {
            "decision": "PASS",
            "as_of": "2026-06-08",
            "selected_candidate": "",
            "run_id": "",
            "experiment_dir": str(experiment_dir),
            "required_outputs": [str(experiment_dir / "candidate_experiment_evidence.json")],
        },
    )
    _write_json(
        experiment_dir / "candidate_experiment_evidence.json",
        {"status": "PASS", "blockers": [], "watch_items": []},
    )
    _write_execution(tmp_path, decision="PASS")

    review = build_candidate_experiment_completion(tmp_path)

    assert review.decision == "BLOCK"
    assert any("launch selected_candidate=missing" in blocker for blocker in review.blockers)
    assert any("launch run_id=missing" in blocker for blocker in review.blockers)


def test_candidate_experiment_completion_cli_returns_nonzero_on_block(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_candidate_experiment_completion.py",
            "--report-dir",
            str(tmp_path),
            "--as-of",
            "2026-06-08",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((tmp_path / "candidate_experiment_completion.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["decision"] == "BLOCK"


def _write_launch(root: Path, experiment_dir: Path) -> None:
    required = [
        "candidate_experiment_evidence.json",
        "candidate_walk_forward_report.json",
        "candidate_factor_diagnostics.json",
        "candidate_regime_validation_report.json",
        "candidate_selection.json",
        "llm_review.json",
    ]
    _write_json(
        root / "candidate_experiment_launch.json",
        {
            "decision": "PASS",
            "as_of": "2026-06-08",
            "selected_candidate": "core_multifactor",
            "run_id": "run",
            "experiment_dir": str(experiment_dir),
            "required_outputs": [str(experiment_dir / item) for item in required],
            "capital_goal_fit_tests": [
                "Run candidate_selection with starting_capital=100000, target_capital=1000000, years=8."
            ],
            "minimum_evidence_window": {
                "minimum_total_trading_days": 720,
                "minimum_out_of_sample_trading_days": 240,
                "minimum_walk_forward_windows": 6,
                "sample_split_required": True,
            },
            "risk_budget_checks": ["Max drawdown and turnover stay inside configured budgets."],
            "paper_entry_requirements": ["Paper output remains a manual review artifact."],
            "anti_overfit_controls": ["Candidate priority is pre-registered before seeing results."],
        },
    )


def _write_required_outputs(experiment_dir: Path, *, status: str) -> None:
    experiment_dir.mkdir(parents=True, exist_ok=True)
    _write_execution(experiment_dir.parent.parent, decision="PASS")
    _write_json(
        experiment_dir / "summary.json",
        {
            "trading_day_count": 720,
            "n_bars": 720,
            "assumptions": {
                "demo_data_used": False,
                "in_sample_end": "2023-12-29",
                "out_sample_start": "2024-01-02",
                "out_of_sample_trading_day_count": 240,
            },
        },
    )
    _write_json(
        experiment_dir / "run_manifest.json",
        {
            "demo_data_used": False,
            "trading_day_count": 720,
            "in_sample_end": "2023-12-29",
            "out_sample_start": "2024-01-02",
            "out_of_sample_trading_day_count": 240,
        },
    )
    _write_json(
        experiment_dir / "candidate_experiment_evidence.json",
        {"status": status, "blockers": [], "watch_items": []},
    )
    _write_json(
        experiment_dir / "candidate_walk_forward_report.json",
        _candidate_walk_forward_payload(status=status),
    )
    _write_json(
        experiment_dir / "candidate_factor_diagnostics.json",
        {
            "status": status,
            "candidate_count": 1,
            "diagnostics": [{"candidate": "core_multifactor"}],
            "warnings": [],
        },
    )
    _write_json(
        experiment_dir / "candidate_regime_validation_report.json",
        {
            "status": status,
            "best_candidate": "core_multifactor",
            "candidate_count": 1,
            "regime_count": 2,
            "adverse_regime_window_count": 1,
            "summaries": [{"candidate": "core_multifactor", "adverse_regime_window_count": 1}],
            "buckets": [{"candidate": "core_multifactor"}],
            "windows": [{"candidate": "core_multifactor"}],
        },
    )
    _write_json(
        experiment_dir / "candidate_stress_matrix.json",
        {
            "status": "RESEARCH_ONLY",
            "promotion_decision": "BLOCK",
            "stress_status": status,
            "candidate_count": 1,
            "scenario_count": 5,
            "summaries": [
                {
                    "candidate": "core_multifactor",
                    "status": status,
                    "scenario_count": 5,
                    "pass_count": 5 if status == "PASS" else 0,
                    "watch_count": 0 if status == "PASS" else 5,
                    "block_count": 1 if status == "BLOCK" else 0,
                }
            ],
            "results": [{"candidate": "core_multifactor", "scenario": "baseline"}],
        },
    )
    _write_json(
        experiment_dir / "candidate_selection.json",
        {
            "status": status,
            "best_candidate": "core_multifactor",
            "selected_candidate": "core_multifactor",
            "top_candidate": "core_multifactor",
            "results": [
                {
                    "name": "core_multifactor",
                    "capital_goal_fit_status": status,
                    "capital_goal_fit_review": {
                        "status": status,
                        "drawdown_budget": 0.20,
                        "return_margin": 0.08,
                    },
                }
            ],
        },
    )
    _write_json(
        experiment_dir / "llm_review.json",
        {"decision": status, "missing_evidence": []},
    )


def _candidate_walk_forward_payload(
    *,
    status: str = "PASS",
    worst_total_return: float = 0.01,
    worst_max_drawdown: float = 0.04,
    positive_return_ratio: float = 1.0,
) -> dict:
    payload = selection_safe_walk_forward_payload(
        status=status,
        candidate="core_multifactor",
        window_count=6,
    )
    summary = payload["summaries"][0]
    summary.update(
        {
            "pass_count": 6 if status == "PASS" else 3,
            "watch_count": 0 if status == "PASS" else 3,
            "block_count": 1 if status == "BLOCK" else 0,
            "positive_return_ratio": positive_return_ratio,
            "worst_total_return": worst_total_return,
            "worst_max_drawdown": worst_max_drawdown,
            "avg_total_return": 0.06,
            "avg_max_drawdown": 0.04,
            "avg_sharpe_ratio": 1.0,
            "avg_reject_rate": 0.02,
        }
    )
    for window in payload["windows"]:
        window["test_trading_days"] = 40
    return payload


def _write_execution(
    root: Path,
    *,
    decision: str,
    blockers: list[str] | None = None,
    selected_candidate: str = "core_multifactor",
    run_id: str = "run",
    experiment_dir: Path | None = None,
) -> None:
    _write_json(
        root / "candidate_experiment_execution.json",
        {
            "decision": decision,
            "selected_candidate": selected_candidate,
            "run_id": run_id,
            "experiment_dir": str(experiment_dir or root / "candidate_experiments" / run_id),
            "steps": [{"status": "PASS"}, {"status": "PASS"}],
            "blockers": blockers or [],
        },
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
