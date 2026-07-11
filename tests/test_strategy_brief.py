from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from quantify.ops.strategy_brief import (
    build_first_million_strategy_brief,
    write_first_million_strategy_brief,
)
from quantify.research.candidate_experiment_readiness import (
    build_candidate_experiment_readiness,
)
from quantify.research.candidate_hypotheses import build_candidate_hypothesis_catalog
from quantify.research.candidate_experiment_queue import build_candidate_experiment_queue
from quantify.utils.config import load_config


def test_strategy_brief_prepares_data_when_source_evidence_is_missing(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    _write_config(config)
    cfg = load_config(config)
    catalog = build_candidate_hypothesis_catalog(cfg, as_of="2026-06-09")
    queue = build_candidate_experiment_queue(cfg, as_of="2026-06-09", catalog=catalog)
    readiness = build_candidate_experiment_readiness(
        queue,
        stage_statuses={
            "candidate_experiment_queue": "PASS",
            "source_qa_preflight": "BLOCK",
            "data_source_qa_review": "BLOCK",
            "offline_data_package": "BLOCK",
            "offline_data_intake": "BLOCK",
        },
        stage_messages={
            "source_qa_preflight": "data_source_qa_answers.json is missing or empty.",
            "data_source_qa_review": "SOURCE_QA_ANSWERS_MISSING",
            "offline_data_package": "template rows remain.",
            "offline_data_intake": "source QA is BLOCK.",
        },
        as_of="2026-06-09",
    )

    brief = build_first_million_strategy_brief(
        readiness=readiness,
        hypothesis_catalog=catalog,
        data_gap_plan={
            "decision": "BLOCK",
            "items": [
                {
                    "name": "source_qa_answers",
                    "status": "BLOCK",
                    "message": "data_source_qa_answers.json is missing or empty.",
                }
            ],
        },
        data_evidence_packet={
            "decision": "BLOCK",
            "current_blockers": [
                {
                    "name": "source_qa_answers",
                    "status": "BLOCK",
                    "message": "data_source_qa_answers.json is missing or empty.",
                    "next_action": "Fill data_source_qa_answers.json from real vendor evidence.",
                }
            ],
            "watch_items": [],
            "immediate_commands": ["run source qa"],
        },
        offline_package={"status": "BLOCK", "items": []},
        market_regime={},
        as_of="2026-06-09",
    )
    out = write_first_million_strategy_brief(brief, tmp_path / "out")

    payload = json.loads((out / "first_million_strategy_brief.json").read_text(encoding="utf-8"))
    assert brief.decision == "PREPARE_DATA"
    assert brief.market_context_status == "MISSING"
    assert payload["data_evidence_decision"] == "BLOCK"
    assert "real vendor evidence" in payload["data_evidence_next_action"]
    assert payload["candidate_actions"][0]["status"] == "BLOCKED"
    assert "data_evidence.source_qa_answers" in "\n".join(payload["missing_evidence"])
    assert "data_evidence_action_packet.md first" in payload["next_actions"][0]
    assert "Fill the source QA evidence worksheet" in "\n".join(payload["next_actions"])
    assert (out / "first_million_strategy_brief.md").exists()


def test_strategy_brief_uses_snapshot_as_watch_context_without_promoting_data(
    tmp_path: Path,
) -> None:
    config = tmp_path / "research_recent.yaml"
    _write_config(config)
    cfg = load_config(config)
    catalog = build_candidate_hypothesis_catalog(cfg, as_of="2026-06-09")
    queue = build_candidate_experiment_queue(cfg, as_of="2026-06-09", catalog=catalog)
    readiness = build_candidate_experiment_readiness(
        queue,
        stage_statuses={
            "candidate_experiment_queue": "PASS",
            "source_qa_preflight": "BLOCK",
            "data_source_qa_review": "BLOCK",
            "offline_data_package": "BLOCK",
            "offline_data_intake": "BLOCK",
        },
        stage_messages={
            "source_qa_preflight": "data_source_qa_answers.json is missing or empty.",
            "data_source_qa_review": "SOURCE_QA_ANSWERS_MISSING",
            "offline_data_package": "template rows remain.",
            "offline_data_intake": "source QA is BLOCK.",
        },
        as_of="2026-06-09",
    )

    brief = build_first_million_strategy_brief(
        readiness=readiness,
        hypothesis_catalog=catalog,
        data_gap_plan={"decision": "BLOCK", "items": []},
        data_evidence_packet={
            "decision": "BLOCK",
            "current_blockers": [
                {
                    "name": "csv_template_rows",
                    "status": "BLOCK",
                    "message": "Generated template rows remain.",
                    "next_action": "Replace templates with real exports.",
                }
            ],
            "watch_items": [],
        },
        offline_package={"status": "BLOCK", "items": []},
        market_context_snapshot={
            "status": "PASS",
            "label": "risk_on",
            "artifact_type": "market_context_snapshot",
        },
        as_of="2026-06-09",
    )
    out = write_first_million_strategy_brief(brief, tmp_path / "out")

    payload = json.loads((out / "first_million_strategy_brief.json").read_text(encoding="utf-8"))
    assert payload["decision"] == "PREPARE_DATA"
    assert payload["data_evidence_decision"] == "BLOCK"
    assert payload["market_context_label"] == "risk_on"
    assert payload["market_context_status"] == "WATCH"
    assert payload["market_context_source"] == "market_context_snapshot"
    assert "market_regime.json" in "\n".join(payload["missing_evidence"])
    assert "market_context_snapshot" in "\n".join(payload["prohibited_actions"])


def test_strategy_brief_uses_passed_packet_command_for_prepare_data_next_action(
    tmp_path: Path,
) -> None:
    config = tmp_path / "research_recent.yaml"
    _write_config(config)
    cfg = load_config(config)
    catalog = build_candidate_hypothesis_catalog(cfg, as_of="2026-06-09")
    queue = build_candidate_experiment_queue(cfg, as_of="2026-06-09", catalog=catalog)
    readiness = build_candidate_experiment_readiness(
        queue,
        stage_statuses={
            "candidate_experiment_queue": "PASS",
            "offline_data_package": "BLOCK",
            "offline_data_intake": "BLOCK",
        },
        stage_messages={
            "offline_data_package": "offline package is blocked.",
            "offline_data_intake": "source QA is BLOCK.",
        },
        as_of="2026-06-09",
    )

    brief = build_first_million_strategy_brief(
        readiness=readiness,
        hypothesis_catalog=catalog,
        data_gap_plan={"decision": "PASS", "items": []},
        data_evidence_packet={
            "decision": "PASS",
            "current_blockers": [],
            "watch_items": [],
            "immediate_commands": ["Run guarded offline data intake."],
        },
        offline_package={"status": "BLOCK", "items": []},
        market_regime={},
        as_of="2026-06-09",
    )

    assert brief.decision == "PREPARE_DATA"
    assert brief.data_evidence_decision == "PASS"
    assert brief.next_actions[0].endswith("Run guarded offline data intake.")


def test_strategy_brief_surfaces_compounding_goal_gap(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    _write_config(config)
    cfg = load_config(config)
    catalog = build_candidate_hypothesis_catalog(cfg, as_of="2026-06-09")
    queue = build_candidate_experiment_queue(cfg, as_of="2026-06-09", catalog=catalog)
    readiness = build_candidate_experiment_readiness(
        queue,
        stage_statuses={
            "candidate_experiment_queue": "PASS",
            "offline_data_package": "PASS",
            "source_qa_preflight": "PASS",
            "data_source_qa_review": "PASS",
            "offline_data_intake": "PASS",
        },
        handoff_payload={
            "evidence_paths": [
                {"name": "ohlcv_minimum_path", "status": "PASS", "blocked_by": []},
                {"name": "pit_fundamental_candidate_path", "status": "PASS", "blocked_by": []},
            ]
        },
        market_context={
            "source": "market_regime",
            "payload": {"status": "PASS", "label": "neutral", "as_of": "2026-06-09"},
            "artifact": str(tmp_path / "market_regime.json"),
        },
        as_of="2026-06-09",
    )

    brief = build_first_million_strategy_brief(
        readiness=readiness,
        hypothesis_catalog=catalog,
        data_gap_plan={"decision": "PASS", "items": []},
        data_evidence_packet={"decision": "PASS", "current_blockers": [], "watch_items": []},
        offline_package={"status": "PASS", "items": []},
        market_regime={"status": "PASS", "label": "neutral", "context_source": "market_regime"},
        capital_goal_status={
            "decision": "BLOCK",
            "best_candidate": "price_volume_defensive",
            "goal": {"required_annual_return": 0.333},
            "blockers": ["candidate_selection: selected_candidate is missing."],
        },
        compounding_path_review={
            "decision": "BLOCK",
            "selected_candidate": "",
            "goal": {"required_annual_return": 0.333},
            "projected_capital_at_horizon": 180_000,
            "capital_shortfall": 820_000,
            "findings": [
                {
                    "severity": "BLOCK",
                    "code": "NO_SELECTED_CANDIDATE",
                    "message": "No selected candidate exists.",
                }
            ],
        },
        candidate_selection={
            "status": "WATCH",
            "top_candidate": "price_volume_defensive",
            "selected_candidate": "",
        },
        as_of="2026-06-09",
    )
    out = write_first_million_strategy_brief(brief, tmp_path / "out")
    payload = json.loads((out / "first_million_strategy_brief.json").read_text(encoding="utf-8"))
    markdown = (out / "first_million_strategy_brief.md").read_text(encoding="utf-8")

    assert payload["compounding_goal"]["status"] == "BLOCK"
    assert payload["compounding_goal"]["selected_candidate"] == "price_volume_defensive"
    assert payload["compounding_goal"]["capital_shortfall"] == 820_000
    assert any("selected_candidate" in item for item in payload["compounding_goal"]["gap_items"])
    assert any("compounding_goal:" in item for item in payload["missing_evidence"])
    assert any("Resolve compounding goal gaps" in item for item in payload["next_actions"])
    assert "## Compounding Goal Gap" in markdown


def test_strategy_brief_cli_writes_from_pipeline_artifacts(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    report_dir = tmp_path / "first_million"
    _write_config(config)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_first_million_pipeline.py",
            "--config",
            str(config),
            "--data-dir",
            str(tmp_path / "data_exports"),
            "--output-dir",
            str(report_dir),
            "--min-symbols",
            "2",
            "--min-trading-days",
            "2",
            "--as-of",
            "2026-06-09",
            "--no-registry",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_first_million_strategy_brief.py",
            "--report-dir",
            str(report_dir),
            "--config",
            str(config),
            "--as-of",
            "2026-06-09",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads(
        (report_dir / "first_million_strategy_brief.json").read_text(encoding="utf-8")
    )
    assert completed.returncode == 0
    assert payload["decision"] == "PREPARE_DATA"
    assert payload["top_research_candidate"] == "price_volume_defensive"


def test_strategy_brief_cli_prefers_weekly_regime_over_snapshot(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    report_dir = tmp_path / "first_million"
    _write_config(config)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_first_million_pipeline.py",
            "--config",
            str(config),
            "--data-dir",
            str(tmp_path / "data_exports"),
            "--output-dir",
            str(report_dir),
            "--min-symbols",
            "2",
            "--min-trading-days",
            "2",
            "--as-of",
            "2026-06-09",
            "--no-registry",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2
    (report_dir / "weekly").mkdir()
    (report_dir / "weekly" / "market_regime.json").write_text(
        json.dumps({"status": "PASS", "label": "neutral", "context_source": "market_regime"}),
        encoding="utf-8",
    )
    (report_dir / "market_context_snapshot.json").write_text(
        json.dumps({"status": "PASS", "label": "risk_on", "artifact_type": "market_context_snapshot"}),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_first_million_strategy_brief.py",
            "--report-dir",
            str(report_dir),
            "--config",
            str(config),
            "--as-of",
            "2026-06-09",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads(
        (report_dir / "first_million_strategy_brief.json").read_text(encoding="utf-8")
    )
    assert completed.returncode == 0
    assert payload["market_context_label"] == "neutral"
    assert payload["market_context_source"] == "market_regime"


def test_strategy_brief_reorders_ready_candidates_by_market_fit_from_snapshot(
    tmp_path: Path,
) -> None:
    config = tmp_path / "research_recent.yaml"
    _write_config(config)
    cfg = load_config(config)
    catalog = build_candidate_hypothesis_catalog(cfg, as_of="2026-06-09")
    queue = build_candidate_experiment_queue(cfg, as_of="2026-06-09", catalog=catalog)
    readiness = build_candidate_experiment_readiness(
        queue,
        stage_statuses={
            "candidate_experiment_queue": "PASS",
            "offline_data_package": "PASS",
            "source_qa_preflight": "PASS",
            "data_source_qa_review": "PASS",
            "offline_data_intake": "PASS",
        },
        handoff_payload={
            "evidence_paths": [
                {"name": "ohlcv_minimum_path", "status": "PASS", "blocked_by": []},
                {"name": "pit_fundamental_candidate_path", "status": "PASS", "blocked_by": []},
            ]
        },
        market_context={
            "source": "market_context_snapshot",
            "payload": {
                "artifact_type": "market_context_snapshot",
                "status": "PASS",
                "label": "risk_on",
                "as_of": "2026-06-09",
                "source": "reviewed index export",
                "reviewed_by": "tester",
                "reviewed_at": "2026-06-09",
                "index_metrics": [
                    {
                        "name": "CSI300",
                        "return_20d": 0.04,
                        "return_60d": 0.08,
                        "return_120d": 0.12,
                        "max_drawdown": 0.06,
                        "annualized_volatility": 0.18,
                    }
                ],
                "can_replace_market_regime": False,
                "can_approve_strategy": False,
                "can_generate_broker_orders": False,
            },
            "artifact": str(tmp_path / "market_context_snapshot.json"),
        },
        as_of="2026-06-09",
    )

    brief = build_first_million_strategy_brief(
        readiness=readiness,
        hypothesis_catalog=catalog,
        data_gap_plan={"decision": "PASS", "items": []},
        data_evidence_packet={
            "decision": "PASS",
            "current_blockers": [],
            "watch_items": [],
            "immediate_commands": ["Continue guarded research."],
        },
        offline_package={"status": "PASS", "items": []},
        market_context_snapshot={
            "artifact_type": "market_context_snapshot",
            "status": "PASS",
            "label": "risk_on",
        },
        as_of="2026-06-09",
    )

    assert brief.decision == "PAPER_ONLY"
    assert brief.top_research_candidate == "core_multifactor"
    assert brief.candidate_actions[0].candidate == "core_multifactor"
    assert "market_regime_fit=WATCH/intended_regime" in brief.candidate_actions[0].reason
    assert brief.candidate_actions[1].candidate == "momentum_quality"
    assert "opportunistic_only" in "\n".join(
        item.reason for item in brief.candidate_actions if item.candidate == "price_volume_defensive"
    )
    assert any(
        item.candidate == "price_volume_defensive"
        and "Refresh cache-derived market_regime.json" in item.next_command
        for item in brief.candidate_actions
    )


def test_strategy_brief_pushes_risk_off_pause_candidates_to_the_bottom(
    tmp_path: Path,
) -> None:
    config = tmp_path / "research_recent.yaml"
    _write_config(config)
    cfg = load_config(config)
    catalog = build_candidate_hypothesis_catalog(cfg, as_of="2026-06-09")
    queue = build_candidate_experiment_queue(cfg, as_of="2026-06-09", catalog=catalog)
    readiness = build_candidate_experiment_readiness(
        queue,
        stage_statuses={
            "candidate_experiment_queue": "PASS",
            "offline_data_package": "PASS",
            "source_qa_preflight": "PASS",
            "data_source_qa_review": "PASS",
            "offline_data_intake": "PASS",
        },
        handoff_payload={
            "evidence_paths": [
                {"name": "ohlcv_minimum_path", "status": "PASS", "blocked_by": []},
                {"name": "pit_fundamental_candidate_path", "status": "PASS", "blocked_by": []},
            ]
        },
        market_context={
            "source": "market_regime",
            "payload": {"status": "PASS", "label": "risk_off", "as_of": "2026-06-09"},
            "artifact": str(tmp_path / "market_regime.json"),
        },
        as_of="2026-06-09",
    )

    brief = build_first_million_strategy_brief(
        readiness=readiness,
        hypothesis_catalog=catalog,
        data_gap_plan={"decision": "PASS", "items": []},
        data_evidence_packet={
            "decision": "PASS",
            "current_blockers": [],
            "watch_items": [],
            "immediate_commands": ["Continue guarded research."],
        },
        offline_package={"status": "PASS", "items": []},
        market_regime={"status": "PASS", "label": "risk_off", "context_source": "market_regime"},
        as_of="2026-06-09",
    )

    assert brief.decision == "PAUSE"
    assert brief.top_research_candidate == "price_volume_defensive"
    assert brief.candidate_actions[-1].candidate == "momentum_quality"
    assert all(
        ("risk_off_pause" in item.reason and item.next_command == "")
        for item in brief.candidate_actions
        if item.candidate in {"price_volume_defensive", "core_multifactor", "momentum_quality"}
    )


def _write_config(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "research:",
                '  start: "2024-01-02"',
                '  end: "2024-01-03"',
                '  in_sample_end: "2024-01-02"',
                '  out_sample_start: "2024-01-03"',
                "  initial_cash: 1000000.0",
                "  rebalance: monthly",
                "  allow_demo_data: false",
                "data:",
                "  source: csv",
                f"  cache_path: '{path.parent / 'recent.db'}'",
                "  adjust: qfq",
                "universe:",
                "  index_code: '000906'",
                "  mode: all_a",
                "  include_st: false",
                "  min_history_days: 1",
                "strategy:",
                "  n_holdings: 2",
                "  max_weight: 0.10",
                "risk:",
                "  max_drawdown_stop: 0.2",
                "broker:",
                "  commission_rate: 0.0",
                "  min_commission: 0.0",
                "  stamp_tax: 0.0",
                "  slippage_bps: 0.0",
                "  price_limit_pct: 0.10",
                "  lot_size: 100",
                "output:",
                f"  results_dir: '{path.parent / 'results'}'",
            ]
        ),
        encoding="utf-8",
    )
