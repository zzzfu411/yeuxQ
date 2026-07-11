from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from quantify.research.candidate_experiment_launch import (
    build_candidate_experiment_launch,
    build_candidate_experiment_launch_from_report,
    write_candidate_experiment_launch,
)
from quantify.research.candidate_experiment_design import (
    build_candidate_experiment_design_matrix,
    write_candidate_experiment_design_matrix,
)
from quantify.research.candidate_experiment_queue import (
    build_candidate_experiment_queue,
    write_candidate_experiment_queue,
)
from quantify.research.candidate_experiment_readiness import (
    build_candidate_experiment_readiness,
    write_candidate_experiment_readiness,
)
from quantify.utils.config import Config


def test_candidate_experiment_launch_blocks_when_readiness_blocks(tmp_path: Path) -> None:
    queue = build_candidate_experiment_queue(_cfg(tmp_path / "research.db"), as_of="2026-06-08")
    readiness = build_candidate_experiment_readiness(
        queue,
        stage_statuses={
            "candidate_experiment_queue": "PASS",
            "source_qa_preflight": "BLOCK",
            "data_source_qa_review": "BLOCK",
            "offline_data_intake": "BLOCK",
        },
        stage_messages={
            "source_qa_preflight": "data_source_qa_answers.json: Source QA answers are missing or empty.",
            "data_source_qa_review": "SOURCE_QA_ANSWERS_MISSING",
        },
        as_of="2026-06-08",
    )

    plan = build_candidate_experiment_launch(
        queue,
        readiness,
        report_dir=tmp_path,
        config_path=tmp_path / "research.yaml",
        as_of="2026-06-08",
    )
    out = write_candidate_experiment_launch(plan, tmp_path / "out")

    payload = json.loads((out / "candidate_experiment_launch.json").read_text(encoding="utf-8"))
    markdown = (out / "candidate_experiment_launch.md").read_text(encoding="utf-8")
    assert payload["decision"] == "BLOCK"
    assert payload["command_sequence"] == []
    assert any("source_qa_preflight=BLOCK" in blocker for blocker in payload["blocked_by"])
    assert any("data_source_qa_review=BLOCK" in blocker for blocker in payload["blocked_by"])
    assert "None while launch is BLOCK" in markdown
    assert "not a trading instruction" in markdown


def test_candidate_experiment_launch_passes_with_stable_run_id_and_rewritten_commands(
    tmp_path: Path,
) -> None:
    config = tmp_path / "research_recent.yaml"
    cfg = _cfg(tmp_path / "research.db")
    queue = build_candidate_experiment_queue(cfg, as_of="2026-06-08")
    write_candidate_experiment_design_matrix(
        build_candidate_experiment_design_matrix(cfg, queue=queue, as_of="2026-06-08"),
        tmp_path,
    )
    readiness = build_candidate_experiment_readiness(
        queue,
        stage_statuses={
            "candidate_experiment_queue": "PASS",
            "offline_data_package": "PASS",
            "source_qa_preflight": "PASS",
            "data_source_qa_review": "PASS",
            "offline_data_intake": "PASS",
        },
        as_of="2026-06-08",
    )

    plan = build_candidate_experiment_launch(
        queue,
        readiness,
        report_dir=tmp_path,
        config_path=config,
        as_of="2026-06-08",
    )

    assert plan.decision == "PASS"
    assert plan.selected_candidate == "price_volume_defensive"
    assert plan.run_id == "20260608_price_volume_defensive"
    evidence = {item.name: item.status for item in plan.evidence}
    assert evidence["candidate_experiment_design_matrix"] == "WAITING_FOR_REAL_DATA"
    assert plan.experiment_dir.endswith("candidate_experiments\\20260608_price_volume_defensive") or (
        "candidate_experiments/20260608_price_volume_defensive" in plan.experiment_dir
    )
    assert "run_candidate_experiment_evidence.py" in plan.command_sequence[0]
    assert f"--source-report-dir {tmp_path}" in plan.command_sequence[0]
    assert all("<timestamp>" not in command for command in plan.command_sequence)
    assert all(str(config) in command for command in plan.command_sequence[1:6])
    assert any("run_candidate_selection.py" in command for command in plan.command_sequence)
    assert any(output.endswith("candidate_experiment_evidence.json") for output in plan.required_outputs)
    assert any(output.endswith("candidate_stress_matrix.json") for output in plan.required_outputs)
    assert any("capital_goal_fit_review" in item for item in plan.capital_goal_fit_tests)
    assert plan.minimum_evidence_window["minimum_out_of_sample_trading_days"] == 240
    assert plan.minimum_evidence_window["requires_pit_fundamental_history"] is False
    assert any("Max drawdown" in item for item in plan.risk_budget_checks)
    assert any("manual review artifact" in item for item in plan.paper_entry_requirements)
    assert any("pre-registered" in item for item in plan.anti_overfit_controls)
    filtered_commands = [
        command
        for command in plan.command_sequence
        if any(
            script in command
            for script in [
                "run_candidate_walk_forward.py",
                "run_candidate_regime_validation.py",
                "run_candidate_stress_matrix.py",
                "run_candidate_selection.py",
            ]
        )
    ]
    assert filtered_commands
    assert all("--candidate price_volume_defensive" in command for command in filtered_commands)
    assert all(f"--gate-report-dir {tmp_path}" in command for command in filtered_commands)
    assert any("Do not connect launched experiments to real broker" in item for item in plan.prohibited_actions)


def test_candidate_experiment_launch_allows_ready_candidate_when_readiness_watches(
    tmp_path: Path,
) -> None:
    queue = build_candidate_experiment_queue(_cfg(tmp_path / "research.db"), as_of="2026-06-08")
    readiness = build_candidate_experiment_readiness(
        queue,
        stage_statuses={
            "candidate_experiment_queue": "PASS",
            "offline_data_package": "WATCH",
            "source_qa_preflight": "PASS",
            "data_source_qa_review": "PASS",
            "offline_data_intake": "WATCH",
        },
        stage_messages={
            "offline_data_package": "Recommended CSV files are missing.",
            "offline_data_intake": "CSV validation has WATCH evidence.",
        },
        handoff_payload={
            "evidence_paths": [
                {"name": "ohlcv_minimum_path", "status": "PASS", "blocked_by": []},
                {
                    "name": "pit_fundamental_candidate_path",
                    "status": "BLOCK",
                    "blocked_by": ["fundamentals.csv is missing."],
                },
            ]
        },
        as_of="2026-06-08",
    )

    plan = build_candidate_experiment_launch(
        queue,
        readiness,
        report_dir=tmp_path,
        config_path=tmp_path / "research.yaml",
        as_of="2026-06-08",
    )
    blocked_plan = build_candidate_experiment_launch(
        queue,
        readiness,
        report_dir=tmp_path,
        config_path=tmp_path / "research.yaml",
        candidate="core_multifactor",
        as_of="2026-06-08",
    )

    assert readiness.decision == "WATCH"
    assert plan.decision == "PASS"
    assert plan.selected_candidate == "price_volume_defensive"
    assert blocked_plan.decision == "BLOCK"
    assert "No READY candidate experiment is available." in blocked_plan.blocked_by


def test_candidate_experiment_launch_from_report_cli_returns_block_on_blocked_readiness(
    tmp_path: Path,
) -> None:
    queue = build_candidate_experiment_queue(_cfg(tmp_path / "research.db"), as_of="2026-06-08")
    write_candidate_experiment_queue(queue, tmp_path)
    (tmp_path / "first_million_pipeline.json").write_text(
        json.dumps(
            {
                "stages": [
                    {"name": "candidate_experiment_queue", "status": "PASS", "message": "queue"},
                    {"name": "source_qa_preflight", "status": "BLOCK", "message": "preflight blocked"},
                    {
                        "name": "data_source_qa_review",
                        "status": "BLOCK",
                        "message": "SOURCE_QA_ANSWERS_MISSING",
                    },
                    {"name": "offline_data_intake", "status": "BLOCK", "message": "stopped"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_candidate_experiment_launch.py",
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

    plan = build_candidate_experiment_launch_from_report(tmp_path, as_of="2026-06-08")
    payload = json.loads((tmp_path / "candidate_experiment_launch.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert plan.decision == "BLOCK"
    assert payload["decision"] == "BLOCK"


def test_candidate_experiment_launch_from_report_passes_when_pipeline_gates_pass(
    tmp_path: Path,
) -> None:
    queue = build_candidate_experiment_queue(_cfg(tmp_path / "research.db"), as_of="2026-06-08")
    write_candidate_experiment_queue(queue, tmp_path)
    write_candidate_experiment_readiness(
        build_candidate_experiment_readiness(
            queue,
            stage_statuses={
                "candidate_experiment_queue": "PASS",
                "offline_data_package": "PASS",
                "source_qa_preflight": "PASS",
                "data_source_qa_review": "PASS",
                "offline_data_intake": "PASS",
            },
            as_of="2026-06-08",
        ),
        tmp_path,
    )
    (tmp_path / "first_million_pipeline.json").write_text(
        json.dumps(
            {
                "stages": [
                    {"name": "candidate_experiment_queue", "status": "PASS", "message": "queue"},
                    {"name": "offline_data_package", "status": "PASS", "message": "pass"},
                    {"name": "source_qa_preflight", "status": "PASS", "message": "pass"},
                    {"name": "data_source_qa_review", "status": "PASS", "message": "pass"},
                    {"name": "offline_data_intake", "status": "PASS", "message": "pass"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "market_regime.json").write_text(
        json.dumps({"status": "PASS", "label": "neutral"}, ensure_ascii=False),
        encoding="utf-8",
    )

    plan = build_candidate_experiment_launch_from_report(
        tmp_path,
        config_path=tmp_path / "research.yaml",
        candidate="defensive_low_vol",
        as_of="2026-06-08",
        run_id="manual_run",
    )

    assert plan.decision == "PASS"
    assert plan.selected_candidate == "defensive_low_vol"
    assert plan.run_id == "manual_run"
    assert any("defensive_low_vol" in command for command in plan.command_sequence)
    assert any("--candidate defensive_low_vol" in command for command in plan.command_sequence)


def _cfg(cache_path: Path) -> Config:
    return Config(
        {
            "research": {
                "start": "2024-01-02",
                "end": "2024-01-03",
                "initial_cash": 1_000_000.0,
                "rebalance": "monthly",
            },
            "universe": {
                "mode": "all_a",
                "index_code": "000906",
                "include_st": False,
                "min_history_days": 1,
            },
            "strategy": {"n_holdings": 5, "max_weight": 0.10},
            "broker": {
                "commission_rate": 0.0,
                "min_commission": 0.0,
                "stamp_tax": 0.0,
                "slippage_bps": 0.0,
                "price_limit_pct": 0.10,
                "lot_size": 100,
            },
            "risk": {"max_drawdown_stop": 0.2},
            "data": {"cache_path": str(cache_path), "source": "csv"},
            "output": {"results_dir": str(cache_path.parent)},
        }
    )
