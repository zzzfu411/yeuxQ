from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys

from quantify.ops.evidence_work_order import build_evidence_work_order, write_evidence_work_order


def test_evidence_work_order_orders_batches_without_creating_evidence(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    _write_operator_handoff(report_dir)
    _write_intake_kit(report_dir, data_dir)

    order = build_evidence_work_order(report_dir=report_dir, data_dir=data_dir, as_of="2026-06-10")
    out = write_evidence_work_order(order, report_dir)

    payload = json.loads((out / "first_million_evidence_work_order.json").read_text(encoding="utf-8"))
    rows = list(
        csv.DictReader((out / "first_million_evidence_work_order.csv").open(encoding="utf-8-sig"))
    )

    assert order.decision == "BLOCK"
    assert payload["next_batch_id"] == "source_qa_worksheet"
    assert [batch["batch_id"] for batch in payload["batches"][:3]] == [
        "source_qa_worksheet",
        "source_qa_attachments",
        "raw_bars_csv",
    ]
    assert payload["batches"][0]["status"] == "BLOCK"
    assert payload["batches"][1]["status"] == "BLOCK"
    assert payload["batches"][2]["status"] == "BLOCK"
    assert "fill_data_source_qa_evidence_worksheet.py is only a typing aid" in payload["batches"][0]["gate_note"]
    assert rows[0]["batch_id"] == "source_qa_worksheet"
    assert not (data_dir / "source_qa_evidence" / "source_identity_receipt.png").exists()
    assert not (data_dir / "raw" / "bars.csv").exists()


def test_evidence_work_order_cli_returns_nonzero_on_open_batches(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    _write_operator_handoff(report_dir)
    _write_intake_kit(report_dir, data_dir)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_first_million_evidence_work_order.py",
            "--report-dir",
            str(report_dir),
            "--data-dir",
            str(data_dir),
            "--as-of",
            "2026-06-10",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((report_dir / "first_million_evidence_work_order.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["decision"] == "BLOCK"


def _write_operator_handoff(report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    with (report_dir / "operator_handoff.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "task_type",
                "priority",
                "status",
                "target",
                "source_artifact",
                "row_number",
                "id",
                "file_name",
                "next_command",
            ],
        )
        writer.writeheader()
        writer.writerows(
            [
                {
                    "task_type": "source_qa_worksheet",
                    "priority": "P0",
                    "status": "BLOCK",
                    "target": "data_exports\\data_source_qa_evidence_worksheet.csv",
                    "source_artifact": "source_qa_worksheet_todo.csv",
                    "row_number": "2",
                    "id": "data_vendor_or_broker",
                    "file_name": "",
                    "next_command": "run worksheet",
                },
                {
                    "task_type": "source_qa_attachment",
                    "priority": "P0",
                    "status": "BLOCK",
                    "target": "data_exports\\source_qa_evidence\\source_identity_receipt.png",
                    "source_artifact": "source_qa_attachment_todo.csv",
                    "row_number": "",
                    "id": "source_identity",
                    "file_name": "",
                    "next_command": "write manifest",
                },
            ]
        )
    _write_json(
        report_dir / "operator_handoff_status.json",
        {"status": "BLOCK", "open_task_count": 2},
    )


def _write_intake_kit(report_dir: Path, data_dir: Path) -> None:
    _write_json(
        report_dir / "evidence_intake_kit" / "first_million_evidence_intake_kit.json",
        {
            "decision": "BLOCK",
            "files": [
                {
                    "item_type": "source_qa_attachment",
                    "item_id": "source_identity",
                    "current_state": "missing",
                    "target_path": str(data_dir / "source_qa_evidence" / "source_identity_receipt.png"),
                },
                {
                    "item_type": "data_export_csv",
                    "item_id": "bars.csv",
                    "current_state": "template_sample_rows",
                    "target_path": str(data_dir / "raw" / "bars.csv"),
                },
                {
                    "item_type": "market_index_csv",
                    "item_id": "broad_a_share_index_daily",
                    "current_state": "missing",
                    "target_path": str(data_dir / "indices" / "indices.csv"),
                },
            ],
        },
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
