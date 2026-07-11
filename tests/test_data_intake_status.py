from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from quantify.ops.data_intake_status import build_data_intake_status, write_data_intake_status


def test_data_intake_status_blocks_when_source_evidence_and_raw_bars_are_missing(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    _write_blocked_artifacts(data_dir, report_dir)

    report = build_data_intake_status(report_dir=report_dir, data_dir=data_dir, as_of="2026-07-06")
    out = write_data_intake_status(report, report_dir)

    payload = json.loads((out / "data_intake_status.json").read_text(encoding="utf-8"))
    markdown = (out / "data_intake_status.md").read_text(encoding="utf-8")

    assert payload["decision"] == "BLOCK"
    assert payload["summary"]["source_evidence_missing"] == 5
    assert payload["summary"]["worksheet_fill_ready"] is False
    assert payload["next_area"] == "operator_next_batch"
    assert any(item["area"] == "raw_bars_csv" and item["status"] == "BLOCK" for item in payload["items"])
    assert any(item["area"] == "source_qa_worksheet_fill_command" for item in payload["items"])
    assert any("run_data_intake_status.py" in item for item in payload["command_sequence"])
    assert "cannot approve data" in markdown


def test_data_intake_status_cli_returns_nonzero_on_block(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    _write_blocked_artifacts(data_dir, report_dir)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_data_intake_status.py",
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
    payload = json.loads((report_dir / "data_intake_status.json").read_text(encoding="utf-8"))
    assert payload["decision"] == "BLOCK"


def _write_blocked_artifacts(data_dir: Path, report_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        report_dir / "first_million_evidence_work_order.json",
        {
            "decision": "BLOCK",
            "next_batch_id": "source_qa_worksheet",
            "open_batch_count": 3,
            "batches": [
                {
                    "batch_id": "source_qa_worksheet",
                    "status": "BLOCK",
                    "title": "Fill source QA worksheet rows from retained evidence.",
                    "target_artifact": str(data_dir / "data_source_qa_evidence_worksheet.csv"),
                    "command_after_completion": "fill worksheet",
                }
            ],
        },
    )
    _write_json(
        report_dir / "source_qa_evidence_inbox.json",
        {
            "status": "BLOCK",
            "matched_item_count": 0,
            "missing_item_count": 5,
            "invalid_file_count": 0,
            "worksheet_fill_command_ready": False,
            "worksheet_fill_command_status": "BLOCK",
            "worksheet_fill_command_blockers": [
                "source_identity: target_path value is not ready evidence."
            ],
            "worksheet_fill_command": "fill worksheet",
            "next_commands": ["scan inbox"],
        },
    )
    _write_json(
        report_dir / "source_qa" / "source_qa_evidence_readiness.json",
        {
            "status": "BLOCK",
            "sections": [
                {
                    "name": "answers_preflight",
                    "status": "BLOCK",
                    "blockers": ["data_source_qa_answers.json is missing."],
                },
                {
                    "name": "manifest_preflight",
                    "status": "BLOCK",
                    "blockers": ["source_identity attachment is missing."],
                },
            ],
        },
    )
    _write_json(
        report_dir / "source_qa_closeout.json",
        {
            "decision": "BLOCK",
            "counts": {
                "open_action_count": 3,
                "missing_worksheet_count": 2,
                "missing_attachment_count": 5,
            },
            "next_action": "Fill source QA evidence.",
            "command_sequence": ["run closeout"],
        },
    )
    _write_json(
        report_dir / "raw_bars_discovery.json",
        {
            "status": "BLOCK",
            "best_candidate": "",
            "candidates": [],
            "dropzone_kit": {"dropzone_dir": str(data_dir / "raw")},
            "next_commands": ["scan raw bars"],
        },
    )
    _write_json(
        report_dir / "ohlcv_intake_closeout.json",
        {
            "decision": "BLOCK",
            "source_qa_status": "BLOCK",
            "raw_discovery_status": "BLOCK",
            "offline_intake_status": "NOT_RUN",
            "blockers": ["source QA is BLOCK."],
            "command_sequence": ["run ohlcv closeout"],
        },
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
