from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys

from quantify.ops.evidence_intake_kit import build_evidence_intake_kit, write_evidence_intake_kit


def test_evidence_intake_kit_builds_staging_manifest_without_fake_evidence(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    _write_source_attachment_plan(report_dir, data_dir)
    _write_data_export_todo(report_dir)
    _write_json(
        report_dir / "market_index_discovery.json",
        {"status": "BLOCK", "best_candidate": "", "candidates": []},
    )

    kit = build_evidence_intake_kit(report_dir=report_dir, data_dir=data_dir, as_of="2026-06-10")
    out = write_evidence_intake_kit(kit)

    payload = json.loads((out / "first_million_evidence_intake_kit.json").read_text(encoding="utf-8"))
    rows = list(
        csv.DictReader((out / "first_million_evidence_intake_manifest.csv").open(encoding="utf-8-sig"))
    )

    assert kit.decision == "BLOCK"
    assert payload["file_count"] == 4
    assert {row["item_type"] for row in rows} == {
        "source_qa_attachment",
        "data_export_csv",
        "market_index_csv",
    }
    assert (out / "incoming_source_qa_evidence" / "README.md").exists()
    assert (out / "incoming_data_exports" / "README.md").exists()
    assert (out / "incoming_market_indices" / "README.md").exists()
    assert not (data_dir / "source_qa_evidence" / "source_identity_receipt.png").exists()
    assert not (data_dir / "raw" / "bars.csv").exists()
    assert not (data_dir / "indices" / "indices.csv").exists()
    assert any("run_first_million_evidence_intake_receiver.py" in command for command in payload["command_sequence"])
    assert any("run_first_million_pipeline.py" in command for command in payload["command_sequence"])


def test_evidence_intake_kit_cli_returns_nonzero_when_required_files_open(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    output_dir = tmp_path / "kit"
    _write_source_attachment_plan(report_dir, data_dir)
    _write_data_export_todo(report_dir)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_first_million_evidence_intake_kit.py",
            "--report-dir",
            str(report_dir),
            "--data-dir",
            str(data_dir),
            "--output-dir",
            str(output_dir),
            "--as-of",
            "2026-06-10",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads(
        (output_dir / "first_million_evidence_intake_kit.json").read_text(encoding="utf-8")
    )
    assert completed.returncode == 2
    assert payload["decision"] == "BLOCK"


def _write_source_attachment_plan(report_dir: Path, data_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    with (report_dir / "source_qa_evidence_attachment_plan.csv").open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "id",
                "suggested_file",
                "current_state",
                "required_evidence",
                "acceptance_criteria",
                "do_not_use",
                "next_command",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "id": "source_identity",
                "suggested_file": str(data_dir / "source_qa_evidence" / "source_identity_receipt.png"),
                "current_state": "missing",
                "required_evidence": "Vendor export receipt.",
                "acceptance_criteria": "Manifest contains retained file id/path/sha256.",
                "do_not_use": "generated receipt",
                "next_command": "write manifest",
            }
        )


def _write_data_export_todo(report_dir: Path) -> None:
    with (report_dir / "data_export_todo.csv").open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "file_name",
                "required",
                "current_state",
                "columns",
                "acceptance_criteria",
            ],
        )
        writer.writeheader()
        writer.writerows(
            [
                {
                    "file_name": "bars.csv",
                    "required": "yes",
                    "current_state": "missing",
                    "columns": "symbol, date, open, high, low, close, volume, amount",
                    "acceptance_criteria": "Recent daily OHLCV rows.",
                },
                {
                    "file_name": "stock_info.csv",
                    "required": "recommended",
                    "current_state": "missing",
                    "columns": "symbol, name, exchange",
                    "acceptance_criteria": "Same export batch audit file.",
                },
            ]
        )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
