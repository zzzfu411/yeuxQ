from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys

from quantify.research.candidate_experiment_queue import (
    build_candidate_experiment_queue,
    write_candidate_experiment_queue,
)
from quantify.research.candidate_experiment_run_packet import (
    build_candidate_experiment_run_packet_from_report,
    write_candidate_experiment_run_packet,
)
from quantify.utils.config import Config


def test_candidate_experiment_run_packet_blocks_when_no_ready_candidate(tmp_path: Path) -> None:
    _write_ready_report(tmp_path, source_qa_status="BLOCK")

    packet = build_candidate_experiment_run_packet_from_report(tmp_path, as_of="2026-06-08")
    out = write_candidate_experiment_run_packet(packet, tmp_path)

    payload = json.loads((out / "candidate_experiment_run_packet.json").read_text(encoding="utf-8"))
    markdown = (out / "candidate_experiment_run_packet.md").read_text(encoding="utf-8")

    assert packet.decision == "BLOCK"
    assert payload["command_bundle"] == []
    assert payload["capability_flags"]["can_enter_paper"] is False
    assert payload["capability_flags"]["can_enter_live"] is False
    assert payload["capability_flags"]["can_generate_broker_orders"] is False
    assert not _contains_forbidden_command(payload["command_bundle"])
    assert "research-only command bundle" in markdown


def test_candidate_experiment_run_packet_writes_complete_ohlcv_bundle(tmp_path: Path) -> None:
    _write_ready_report(tmp_path, pit_status="BLOCK")

    packet = build_candidate_experiment_run_packet_from_report(
        tmp_path,
        config_path=tmp_path / "research_recent.yaml",
        as_of="2026-06-08",
        run_id="packet_run",
    )
    out = write_candidate_experiment_run_packet(packet, tmp_path)
    payload = json.loads((out / "candidate_experiment_run_packet.json").read_text(encoding="utf-8"))
    rows = list(csv.DictReader((out / "candidate_experiment_run_packet.csv").open(encoding="utf-8")))
    commands = [item["command"] for item in payload["command_bundle"]]

    assert packet.decision == "PASS"
    assert payload["status"] == "RESEARCH_ONLY"
    assert payload["selected_candidate"] == "price_volume_defensive"
    assert payload["data_dependency"] == "ohlcv_only"
    assert payload["ohlcv_only"] is True
    assert all("run_candidate_experiment_run_packet.py" not in command for command in commands)
    assert any("run_candidate_experiment_launch.py" in command for command in commands)
    assert any("run_candidate_experiment_execution.py" in command and "--dry-run" in command for command in commands)
    assert any("run_candidate_experiment_execution.py" in command and "--dry-run" not in command for command in commands)
    assert any("run_candidate_stress_matrix.py" in command for command in commands)
    assert any("run_candidate_experiment_completion.py" in command for command in commands)
    assert any("run_candidate_next_experiments.py" in command for command in commands)
    assert any(path.endswith("candidate_stress_matrix.json") for path in payload["required_outputs"])
    assert any(path.endswith("candidate_stress_matrix.md") for path in payload["required_outputs"])
    assert any(path.endswith("candidate_stress_matrix.csv") for path in payload["required_outputs"])
    assert any("pending_output" in item for item in payload["missing_evidence"])
    assert any(row["phase"] == "explicit_execution" for row in rows)
    assert payload["capability_flags"]["can_execute_without_operator_opt_in"] is False
    assert not _contains_forbidden_command(payload["command_bundle"])


def test_candidate_experiment_run_packet_blocks_pit_candidate_by_default(tmp_path: Path) -> None:
    _write_ready_report(tmp_path, pit_status="PASS")

    packet = build_candidate_experiment_run_packet_from_report(
        tmp_path,
        candidate="core_multifactor",
        as_of="2026-06-08",
    )

    assert packet.decision == "BLOCK"
    assert packet.selected_candidate == "core_multifactor"
    assert packet.data_dependency == "ohlcv_plus_fundamentals"
    assert any("not OHLCV-only" in blocker for blocker in packet.blocked_by)
    assert packet.command_bundle == []


def test_candidate_experiment_run_packet_cli_returns_nonzero_on_block(tmp_path: Path) -> None:
    _write_ready_report(tmp_path, source_qa_status="BLOCK")

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_candidate_experiment_run_packet.py",
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

    payload = json.loads((tmp_path / "candidate_experiment_run_packet.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["decision"] == "BLOCK"


def _write_ready_report(
    root: Path,
    *,
    source_qa_status: str = "PASS",
    pit_status: str = "BLOCK",
) -> None:
    queue = build_candidate_experiment_queue(_cfg(root / "research.db"), as_of="2026-06-08")
    write_candidate_experiment_queue(queue, root)
    _write_json(
        root / "first_million_pipeline.json",
        {
            "stages": [
                {"name": "candidate_experiment_queue", "status": "PASS", "message": "queue"},
                {"name": "offline_data_package", "status": "WATCH", "message": "package"},
                {"name": "source_qa_preflight", "status": source_qa_status, "message": "source qa"},
                {"name": "data_source_qa_review", "status": source_qa_status, "message": "qa review"},
                {"name": "offline_data_intake", "status": "WATCH", "message": "intake"},
            ]
        },
    )
    _write_json(
        root / "real_data_handoff_checklist.json",
        {
            "evidence_paths": [
                {
                    "name": "ohlcv_minimum_path",
                    "status": "PASS",
                    "blocked_by": [],
                    "required_evidence": ["Audited OHLCV bars and source QA evidence."],
                },
                {
                    "name": "pit_fundamental_candidate_path",
                    "status": pit_status,
                    "blocked_by": [] if pit_status == "PASS" else ["fundamentals.csv is missing."],
                    "required_evidence": ["PIT fundamentals evidence."],
                },
            ]
        },
    )
    _write_json(
        root / "offline_data_package.json",
        {
            "source_metadata_summary": {
                "data_vendor_or_broker": "unit-test vendor",
                "terminal_or_product_name": "unit-test terminal",
                "exported_at_local_time": "2024-01-03 18:00:00",
                "price_adjustment": "qfq",
                "reviewed_by": "tester",
                "reviewed_at": "2024-01-03",
            }
        },
    )
    _write_json(root / "market_regime.json", {"status": "PASS", "label": "neutral", "as_of": "2026-06-08"})
    _write_json(
        root / "ohlcv_experiment_package.json",
        {"decision": "PASS", "candidate": "price_volume_defensive", "blockers": [], "watch_items": []},
    )


def _contains_forbidden_command(command_bundle: list[dict]) -> bool:
    text = "\n".join(str(item.get("command") or "").lower() for item in command_bundle)
    forbidden_tokens = ["broker", "micro_live", "real_order", "order_submit"]
    return any(token in text for token in forbidden_tokens)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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
