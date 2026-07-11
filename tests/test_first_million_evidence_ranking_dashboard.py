from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys

from quantify.ops.first_million_evidence_ranking_dashboard import (
    build_first_million_evidence_ranking_dashboard,
    write_first_million_evidence_ranking_dashboard,
)


def test_first_million_evidence_ranking_dashboard_blocks_when_chain_is_incomplete(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    _write_blocked_artifacts(data_dir, report_dir)

    dashboard = build_first_million_evidence_ranking_dashboard(
        report_dir=report_dir,
        data_dir=data_dir,
        as_of="2026-07-06",
    )
    out = write_first_million_evidence_ranking_dashboard(dashboard, report_dir)

    payload = json.loads(
        (out / "first_million_evidence_ranking_dashboard.json").read_text(encoding="utf-8")
    )
    markdown = (out / "first_million_evidence_ranking_dashboard.md").read_text(encoding="utf-8")
    rows = list(
        csv.DictReader(
            (out / "first_million_evidence_ranking_dashboard.csv").open(encoding="utf-8-sig")
        )
    )

    assert payload["decision"] == "BLOCK"
    assert payload["next_area"] == "source_qa_worksheet"
    assert payload["can_rank_candidates"] is False
    assert payload["top_candidate"] == "price_volume_defensive"
    assert payload["top_candidate_basis"] == "pre_registered_priority_without_ranking"
    assert payload["summary"]["source_evidence_missing"] == 5
    assert payload["summary"]["ranking_gate_status"] == "BLOCK"
    assert "first_million_pipeline=BLOCK" in payload["summary"]["first_ranking_blocker"]
    assert any(item["area"] == "strategy_ranking_gate" for item in payload["items"])
    assert any("run_first_million_evidence_ranking_dashboard.py" in item for item in payload["command_sequence"])
    assert any("real broker" in item for item in payload["prohibited_actions"])
    assert rows[0]["area"] == "source_qa_worksheet"
    assert "First Million Evidence Ranking Dashboard" in markdown
    assert "cannot rank candidates" in markdown


def test_first_million_evidence_ranking_dashboard_passes_only_when_chain_passes(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    _write_pass_artifacts(data_dir, report_dir)

    dashboard = build_first_million_evidence_ranking_dashboard(
        report_dir=report_dir,
        data_dir=data_dir,
        as_of="2026-07-06",
    )

    assert dashboard.decision == "PASS"
    assert dashboard.next_area == ""
    assert dashboard.can_rank_candidates is True
    assert dashboard.top_candidate == "price_volume_defensive"
    assert all(item.status == "PASS" for item in dashboard.items)


def test_first_million_evidence_ranking_dashboard_cli_returns_nonzero_on_block(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    _write_blocked_artifacts(data_dir, report_dir)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_first_million_evidence_ranking_dashboard.py",
            "--report-dir",
            str(report_dir),
            "--data-dir",
            str(data_dir),
            "--as-of",
            "2026-07-06",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    payload = json.loads(
        (report_dir / "first_million_evidence_ranking_dashboard.json").read_text(encoding="utf-8")
    )
    assert payload["decision"] == "BLOCK"


def _write_blocked_artifacts(data_dir: Path, report_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        report_dir / "data_intake_status.json",
        {
            "decision": "BLOCK",
            "next_action": "Fill source QA worksheet rows from retained evidence.",
            "summary": {
                "worksheet_fill_ready": False,
            },
            "command_sequence": ["run data intake"],
        },
    )
    _write_json(
        report_dir / "source_qa_closeout.json",
        {
            "decision": "BLOCK",
            "counts": {"missing_worksheet_count": 13},
            "next_action": "Fill source QA worksheet rows from retained evidence.",
        },
    )
    _write_json(
        report_dir / "source_qa_evidence_inbox.json",
        {
            "status": "BLOCK",
            "missing_item_count": 5,
            "invalid_file_count": 2,
            "next_actions": ["Add retained local evidence files."],
            "next_commands": ["scan source evidence inbox"],
        },
    )
    _write_json(
        report_dir / "raw_bars_discovery.json",
        {
            "status": "BLOCK",
            "best_candidate": "",
            "candidates": [{"message": "No candidate raw bars CSV files were found."}],
            "next_commands": ["scan raw bars"],
        },
    )
    _write_json(
        report_dir / "ohlcv_intake_closeout.json",
        {
            "decision": "BLOCK",
            "blockers": ["source QA is BLOCK."],
        },
    )
    _write_json(
        report_dir / "market_index_discovery.json",
        {
            "status": "BLOCK",
            "candidates": [{"findings": ["No candidate index CSV files were found."]}],
        },
    )
    _write_json(
        report_dir / "market_context_operator_packet.json",
        {
            "decision": "BLOCK",
            "items": [{"item_type": "preferred_artifact", "item_id": "market_regime"}],
            "command_sequence": ["run market context packet"],
        },
    )
    _write_json(
        report_dir / "ohlcv_experiment_package.json",
        {
            "decision": "BLOCK",
            "launch_research_allowed": False,
            "bars": {"symbol_count": 2, "trading_day_count": 0},
            "blockers": ["bars_csv is not real recent OHLCV evidence."],
        },
    )
    _write_json(
        report_dir / "candidate_experiment_readiness.json",
        {
            "decision": "BLOCK",
            "runnable_count": 0,
            "blocked_count": 2,
            "blockers": ["source_qa_preflight=BLOCK"],
        },
    )
    _write_json(
        report_dir / "candidate_experiment_completion.json",
        {
            "decision": "BLOCK",
            "selected_candidate": "",
            "blockers": ["No completed research run exists."],
        },
    )
    _write_json(
        report_dir / "strategy_discovery_plan.json",
        {
            "decision": "PREPARE_DATA",
            "status": "BLOCK",
            "top_candidate": "price_volume_defensive",
            "top_candidate_basis": "pre_registered_priority_without_ranking",
            "can_rank_candidates": False,
            "ranking_gate": {
                "status": "BLOCK",
                "can_rank_candidates": False,
                "basis": "pre-registered candidate priority only; formal ranking is disabled",
                "candidate_selection_status": "MISSING",
                "ranked_candidate_count": 0,
                "top_ranked_candidate": "",
                "blocked_by": [
                    "first_million_pipeline=BLOCK; current evidence cannot support candidate ranking.",
                    "candidate_selection.json is missing; no deterministic ranking report exists.",
                ],
            },
        },
    )


def _write_pass_artifacts(data_dir: Path, report_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        report_dir / "data_intake_status.json",
        {"decision": "PASS", "summary": {"worksheet_fill_ready": True}, "command_sequence": []},
    )
    _write_json(
        report_dir / "source_qa_closeout.json",
        {"decision": "PASS", "counts": {"missing_worksheet_count": 0}},
    )
    _write_json(
        report_dir / "source_qa_evidence_inbox.json",
        {"status": "PASS", "missing_item_count": 0, "invalid_file_count": 0},
    )
    _write_json(
        report_dir / "raw_bars_discovery.json",
        {"status": "PASS", "best_candidate": "data_exports/raw/bars.csv"},
    )
    _write_json(report_dir / "ohlcv_intake_closeout.json", {"decision": "PASS"})
    _write_json(report_dir / "market_index_discovery.json", {"status": "PASS"})
    _write_json(report_dir / "market_context_operator_packet.json", {"decision": "PASS"})
    _write_json(
        report_dir / "ohlcv_experiment_package.json",
        {
            "decision": "PASS",
            "launch_research_allowed": True,
            "bars": {"symbol_count": 300, "trading_day_count": 240},
        },
    )
    _write_json(
        report_dir / "candidate_experiment_readiness.json",
        {"decision": "PASS", "runnable_count": 1, "blocked_count": 0},
    )
    _write_json(
        report_dir / "candidate_experiment_completion.json",
        {"decision": "PASS", "selected_candidate": "price_volume_defensive"},
    )
    _write_json(
        report_dir / "strategy_discovery_plan.json",
        {
            "decision": "PAPER_OBSERVE",
            "status": "WATCH",
            "top_candidate": "price_volume_defensive",
            "top_candidate_basis": "first_ready_pre_registered_candidate",
            "can_rank_candidates": True,
            "ranking_gate": {
                "status": "PASS",
                "can_rank_candidates": True,
                "candidate_selection_status": "PASS",
                "ranked_candidate_count": 1,
                "top_ranked_candidate": "price_volume_defensive",
                "blocked_by": [],
            },
        },
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
