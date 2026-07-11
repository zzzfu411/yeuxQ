from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pandas as pd

from quantify.ops.evidence_intake_receiver import (
    receive_evidence_intake,
    write_evidence_intake_receipt,
)


def test_evidence_intake_receiver_reviews_then_applies_staged_files(tmp_path: Path) -> None:
    manifest = tmp_path / "kit" / "first_million_evidence_intake_manifest.csv"
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "reports"
    staging = tmp_path / "kit" / "incoming_source_qa_evidence" / "source_identity_receipt.txt"
    target = data_dir / "source_qa_evidence" / "source_identity_receipt.txt"
    staging.parent.mkdir(parents=True)
    staging.write_text(
        "Retained vendor terminal export receipt for Wind terminal, operator Alice, exported 2026-06-10 18:00.",
        encoding="utf-8",
    )
    _write_manifest(
        manifest,
        [
            {
                "item_type": "source_qa_attachment",
                "item_id": "source_identity",
                "required": "yes",
                "staging_path": str(staging),
                "target_path": str(target),
            }
        ],
    )

    review = receive_evidence_intake(
        manifest_path=manifest,
        data_dir=data_dir,
        report_dir=report_dir,
        as_of="2026-06-10",
    )
    assert review.decision == "WATCH"
    assert review.items[0].action == "would_copy"
    assert not target.exists()

    applied = receive_evidence_intake(
        manifest_path=manifest,
        data_dir=data_dir,
        report_dir=report_dir,
        as_of="2026-06-10",
        apply=True,
    )
    out = write_evidence_intake_receipt(applied, tmp_path / "kit")

    assert applied.decision == "PASS"
    assert applied.items[0].action == "copied"
    assert target.read_text(encoding="utf-8").startswith("Retained vendor terminal")
    assert (out / "first_million_evidence_intake_receipt.json").exists()


def test_evidence_intake_receiver_rejects_placeholder_staging_file(tmp_path: Path) -> None:
    manifest = tmp_path / "kit" / "first_million_evidence_intake_manifest.csv"
    data_dir = tmp_path / "data_exports"
    staging = tmp_path / "kit" / "incoming_source_qa_evidence" / "source_identity_placeholder.txt"
    target = data_dir / "source_qa_evidence" / "source_identity_receipt.txt"
    staging.parent.mkdir(parents=True)
    staging.write_text("placeholder evidence", encoding="utf-8")
    _write_manifest(
        manifest,
        [
            {
                "item_type": "source_qa_attachment",
                "item_id": "source_identity",
                "required": "yes",
                "staging_path": str(staging),
                "target_path": str(target),
            }
        ],
    )

    receipt = receive_evidence_intake(
        manifest_path=manifest,
        data_dir=data_dir,
        report_dir=tmp_path / "reports",
        as_of="2026-06-10",
        apply=True,
    )

    assert receipt.decision == "BLOCK"
    assert receipt.items[0].action == "rejected"
    assert "sample/template/placeholder" in receipt.items[0].message
    assert not target.exists()


def test_evidence_intake_receiver_rejects_bad_bars_csv(tmp_path: Path) -> None:
    manifest = tmp_path / "kit" / "first_million_evidence_intake_manifest.csv"
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "reports"
    config = tmp_path / "research_recent.yaml"
    staging = tmp_path / "kit" / "incoming_data_exports" / "bars.csv"
    target = data_dir / "raw" / "bars.csv"
    _write_config(config, tmp_path / "recent.db")
    staging.parent.mkdir(parents=True)
    pd.DataFrame({"symbol": ["600010.SH"], "date": ["2026-06-10"], "close": [10.0]}).to_csv(staging, index=False)
    _write_manifest(
        manifest,
        [
            {
                "item_type": "data_export_csv",
                "item_id": "bars.csv",
                "required": "yes",
                "staging_path": str(staging),
                "target_path": str(target),
            }
        ],
    )

    receipt = receive_evidence_intake(
        manifest_path=manifest,
        data_dir=data_dir,
        report_dir=report_dir,
        as_of="2026-06-10",
        apply=True,
        config_path=config,
        min_symbols=2,
    )

    assert receipt.decision == "BLOCK"
    assert receipt.items[0].action == "rejected"
    assert "Raw bars discovery rejects staging file" in receipt.items[0].message
    assert not target.exists()


def test_evidence_intake_receiver_accepts_unique_alternate_raw_bars_csv(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "kit" / "first_million_evidence_intake_manifest.csv"
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "reports"
    config = tmp_path / "research_recent.yaml"
    staging = tmp_path / "kit" / "incoming_data_exports" / "broker_daily_bars.csv"
    target = data_dir / "raw" / "bars.csv"
    _write_config(config, tmp_path / "recent.db")
    staging.parent.mkdir(parents=True)
    _valid_bars().to_csv(staging, index=False)
    _write_manifest(
        manifest,
        [
            {
                "item_type": "data_export_csv",
                "item_id": "bars.csv",
                "required": "yes",
                "staging_path": str(staging.parent / "bars.csv"),
                "target_path": str(target),
            }
        ],
    )

    review = receive_evidence_intake(
        manifest_path=manifest,
        data_dir=data_dir,
        report_dir=report_dir,
        as_of="2026-06-10",
        config_path=config,
        min_symbols=2,
    )
    applied = receive_evidence_intake(
        manifest_path=manifest,
        data_dir=data_dir,
        report_dir=report_dir,
        as_of="2026-06-10",
        apply=True,
        config_path=config,
        min_symbols=2,
    )

    assert review.decision == "WATCH"
    assert review.items[0].action == "would_copy"
    assert review.items[0].staging_path == str(staging)
    assert applied.decision == "PASS"
    assert applied.items[0].action == "copied"
    assert target.exists()


def test_evidence_intake_receiver_reports_alternate_zip_without_copying(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "kit" / "first_million_evidence_intake_manifest.csv"
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "reports"
    config = tmp_path / "research_recent.yaml"
    staging = tmp_path / "kit" / "incoming_data_exports" / "broker_export.zip"
    target = data_dir / "raw" / "bars.csv"
    _write_config(config, tmp_path / "recent.db")
    staging.parent.mkdir(parents=True)
    with zipfile.ZipFile(staging, "w") as handle:
        handle.writestr("broker_daily_bars.csv", _valid_bars().to_csv(index=False))
    _write_manifest(
        manifest,
        [
            {
                "item_type": "data_export_csv",
                "item_id": "bars.csv",
                "required": "yes",
                "staging_path": str(staging.parent / "bars.csv"),
                "target_path": str(target),
            }
        ],
    )

    receipt = receive_evidence_intake(
        manifest_path=manifest,
        data_dir=data_dir,
        report_dir=report_dir,
        as_of="2026-06-10",
        apply=True,
        config_path=config,
        min_symbols=2,
    )

    assert receipt.decision == "BLOCK"
    assert receipt.items[0].action == "rejected"
    assert receipt.items[0].staging_path == str(staging)
    assert "extract" in receipt.items[0].message.lower()
    assert not target.exists()


def test_evidence_intake_receiver_cli_writes_receipt(tmp_path: Path) -> None:
    manifest = tmp_path / "kit" / "first_million_evidence_intake_manifest.csv"
    data_dir = tmp_path / "data_exports"
    output_dir = tmp_path / "kit"
    _write_manifest(
        manifest,
        [
            {
                "item_type": "source_qa_attachment",
                "item_id": "source_identity",
                "required": "yes",
                "staging_path": str(tmp_path / "kit" / "incoming_source_qa_evidence" / "missing.txt"),
                "target_path": str(data_dir / "source_qa_evidence" / "source_identity_receipt.txt"),
            }
        ],
    )

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_first_million_evidence_intake_receiver.py",
            "--manifest",
            str(manifest),
            "--data-dir",
            str(data_dir),
            "--report-dir",
            str(tmp_path / "reports"),
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
    payload = json.loads((output_dir / "first_million_evidence_intake_receipt.json").read_text(encoding="utf-8"))

    assert completed.returncode == 2
    assert payload["decision"] == "BLOCK"
    assert payload["items"][0]["action"] == "pending"


def _write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "item_type",
        "item_id",
        "required",
        "target_path",
        "staging_path",
        "current_state",
        "required_evidence",
        "acceptable_evidence",
        "unacceptable_evidence",
        "validation_command",
        "after_receipt_command",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def _write_config(path: Path, cache: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "research:",
                '  start: "2026-06-09"',
                '  end: "2026-06-10"',
                "  allow_demo_data: false",
                "data:",
                "  source: csv",
                f"  cache_path: '{cache}'",
                "  adjust: qfq",
            ]
        ),
        encoding="utf-8",
    )


def _valid_bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["600010.SH", "600010.SH", "000010.SZ", "000010.SZ"],
            "date": ["2026-06-09", "2026-06-10", "2026-06-09", "2026-06-10"],
            "open": [11.0, 11.1, 21.0, 21.1],
            "high": [11.5, 11.6, 21.5, 21.6],
            "low": [10.8, 11.0, 20.8, 21.0],
            "close": [11.2, 11.3, 21.2, 21.3],
            "volume": [1_500_000, 1_600_000, 2_500_000, 2_600_000],
            "amount": [16_800_000, 18_080_000, 53_000_000, 55_380_000],
        }
    )
