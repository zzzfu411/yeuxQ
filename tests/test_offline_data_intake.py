from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

import pandas as pd

from quantify.data.csv_contract import write_research_csv_templates
from quantify.data.offline_intake import run_offline_data_intake
from quantify.data.provider import DataProvider
from quantify.data.source_qa import (
    build_data_source_qa,
    build_data_source_qa_review,
    build_source_qa_evidence_manifest,
    write_data_source_qa,
    write_source_qa_evidence_manifest,
)
from quantify.data.storage import BarStorage
from quantify.data.tdx_day import export_tdx_day_to_csv
from quantify.ops.run_manifest import build_run_manifest
from quantify.utils.config import load_config


def test_offline_data_intake_blocks_unreplaced_templates_before_cache_write(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    cache = tmp_path / "recent.db"
    output = tmp_path / "out"
    config = tmp_path / "research_recent.yaml"
    write_research_csv_templates(data_dir)
    _write_config(config, cache, start="2024-01-02", end="2024-01-03")

    report = run_offline_data_intake(
        data_dir=data_dir,
        config_path=config,
        output_dir=output,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
    )

    assert report.status == "BLOCK"
    assert report.steps == [
        report.steps[0],
    ]
    assert report.steps[0].name == "doctor"
    assert "TEMPLATE_EXPORT_UNREPLACED" in report.steps[0].message
    assert not (output / "data_import.json").exists()
    assert not cache.exists()


def test_offline_data_intake_imports_replaced_csv_and_bootstraps(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    cache = tmp_path / "recent.db"
    output = tmp_path / "out"
    config = tmp_path / "research_recent.yaml"
    _write_replaced_export(data_dir)
    _write_config(config, cache, start="2024-01-02", end="2024-01-03")

    report = run_offline_data_intake(
        data_dir=data_dir,
        config_path=config,
        output_dir=output,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
    )

    assert report.status == "PASS"
    assert [step.name for step in report.steps] == [
        "doctor",
        "csv_validation",
        "import",
        "real_data_bootstrap",
    ]
    assert (output / "offline_data_intake.json").exists()
    assert (output / "data_import.json").exists()
    assert (output / "real_data_bootstrap.json").exists()
    assert set(DataProvider(BarStorage(cache)).all_symbols()) == {"000010", "600010"}


def test_offline_data_intake_normalizes_raw_bars_before_guarded_import(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    cache = tmp_path / "recent.db"
    output = tmp_path / "out"
    config = tmp_path / "research_recent.yaml"
    raw_bars = tmp_path / "raw_vendor_bars.csv"
    _write_raw_vendor_bars(raw_bars)
    _write_optional_metadata(data_dir)
    _write_config(config, cache, start="2024-01-02", end="2024-01-03")

    report = run_offline_data_intake(
        raw_bars_csv=raw_bars,
        data_dir=data_dir,
        config_path=config,
        output_dir=output,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
    )

    assert report.status == "PASS"
    assert [step.name for step in report.steps] == [
        "vendor_bars_normalization",
        "doctor",
        "csv_validation",
        "import",
        "real_data_bootstrap",
    ]
    normalization_payload = json.loads(
        (output / "vendor_bars_normalization.json").read_text(encoding="utf-8")
    )
    import_payload = json.loads((output / "data_import.json").read_text(encoding="utf-8"))
    metadata = BarStorage(cache).load_metadata()
    assert normalization_payload["raw_sha256"] == _sha256(raw_bars)
    assert import_payload["metadata"]["raw_vendor_bars_sha256"] == _sha256(raw_bars)
    assert metadata["raw_vendor_bars_sha256"] == _sha256(raw_bars)
    assert metadata["raw_vendor_bars_size_bytes"] == str(raw_bars.stat().st_size)
    assert metadata["vendor_bars_normalization_status"] == "PASS"
    assert metadata["vendor_bars_normalization_report"] == str(
        output / "vendor_bars_normalization.json"
    )
    assert (output / "vendor_bars_normalization.json").exists()
    assert (data_dir / "bars.csv").exists()
    assert set(DataProvider(BarStorage(cache)).all_symbols()) == {"000010", "600010"}


def test_offline_data_intake_retains_tdx_day_export_metadata(tmp_path: Path) -> None:
    input_dir = tmp_path / "vipdoc"
    data_dir = tmp_path / "data_exports"
    cache = tmp_path / "recent.db"
    output = tmp_path / "out"
    config = tmp_path / "research_recent.yaml"
    _write_day_file(input_dir / "sh" / "lday" / "sh600010.day", symbol_base=10.0)
    _write_day_file(input_dir / "sz" / "lday" / "sz000010.day", symbol_base=20.0)
    _write_config(config, cache, start="2024-01-02", end="2024-01-03")
    export_tdx_day_to_csv(
        input_dir=input_dir,
        output_dir=data_dir,
        start="2024-01-02",
        end="2024-01-03",
    )

    report = run_offline_data_intake(
        data_dir=data_dir,
        config_path=config,
        output_dir=output,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
    )

    export_hash = _sha256(data_dir / "tdx_day_export.json")
    import_payload = json.loads((output / "data_import.json").read_text(encoding="utf-8"))
    storage = BarStorage(cache)
    cache_metadata = storage.load_metadata()
    manifest = build_run_manifest(
        DataProvider(storage),
        load_config(config),
        storage=storage,
        config_path=config,
        purpose="unit_test",
    )
    assert report.status == "WATCH"
    for metadata in [import_payload["metadata"], cache_metadata, manifest.data_version]:
        assert metadata["tdx_day_export_report"] == str(data_dir / "tdx_day_export.json")
        assert metadata["tdx_day_export_sha256"] == export_hash
        assert metadata["tdx_day_export_status"] == "PASS"
        assert metadata["tdx_day_input_dir"] == str(input_dir)
        assert str(metadata["tdx_day_symbol_count"]) == "2"
        assert str(metadata["tdx_day_row_count"]) == "4"
        assert metadata["tdx_day_start"] == "2024-01-02"
        assert metadata["tdx_day_end"] == "2024-01-03"


def test_offline_data_intake_blocks_invalid_raw_bars_before_doctor(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    cache = tmp_path / "recent.db"
    output = tmp_path / "out"
    config = tmp_path / "research_recent.yaml"
    raw_bars = tmp_path / "raw_vendor_bars.csv"
    _write_raw_vendor_bars(raw_bars, drop_close=True)
    _write_config(config, cache, start="2024-01-02", end="2024-01-03")

    report = run_offline_data_intake(
        raw_bars_csv=raw_bars,
        data_dir=data_dir,
        config_path=config,
        output_dir=output,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
    )

    assert report.status == "BLOCK"
    assert [step.name for step in report.steps] == ["vendor_bars_normalization"]
    assert "RAW_VENDOR_BARS_INVALID" in report.steps[0].message
    assert not (data_dir / "bars.csv").exists()
    assert not cache.exists()


def test_offline_data_intake_blocks_source_qa_before_doctor(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    cache = tmp_path / "recent.db"
    output = tmp_path / "out"
    config = tmp_path / "research_recent.yaml"
    _write_replaced_export(data_dir)
    _write_config(config, cache, start="2024-01-02", end="2024-01-03")
    checklist = build_data_source_qa(
        config_path=config,
        output_dir=data_dir,
        min_symbols=2,
        as_of="2024-01-03",
    )
    write_data_source_qa(checklist, data_dir)

    report = run_offline_data_intake(
        data_dir=data_dir,
        config_path=config,
        output_dir=output,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
    )

    assert report.status == "BLOCK"
    assert [step.name for step in report.steps] == ["source_qa"]
    assert "SOURCE_QA_ANSWERS_MISSING" in report.steps[0].message
    assert (output / "data_source_qa_review.json").exists()
    assert not (output / "data_import.json").exists()
    assert not cache.exists()


def test_offline_data_intake_runs_source_and_csv_qa_when_answers_exist(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    cache = tmp_path / "recent.db"
    output = tmp_path / "out"
    config = tmp_path / "research_recent.yaml"
    _write_replaced_export(data_dir)
    _write_config(config, cache, start="2024-01-02", end="2024-01-03")
    checklist = build_data_source_qa(
        config_path=config,
        output_dir=data_dir,
        min_symbols=2,
        as_of="2024-01-03",
    )
    write_data_source_qa(checklist, data_dir)
    _write_source_answers(data_dir / "data_source_qa_answers.json", checklist.to_dict())

    report = run_offline_data_intake(
        data_dir=data_dir,
        config_path=config,
        output_dir=output,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
    )

    assert report.status == "PASS"
    assert [step.name for step in report.steps] == [
        "source_qa",
        "doctor",
        "csv_validation",
        "source_csv_qa",
        "import",
        "real_data_bootstrap",
    ]
    assert (output / "data_source_qa_review.json").exists()
    assert (output / "data_source_csv_qa_review.json").exists()
    assert (output / "data_import.json").exists()
    import_payload = json.loads((output / "data_import.json").read_text(encoding="utf-8"))
    cache_metadata = BarStorage(cache).load_metadata()
    for metadata in [import_payload["metadata"], cache_metadata]:
        assert metadata["data_source_qa_checklist_path"] == str(data_dir / "data_source_qa.json")
        assert metadata["data_source_qa_checklist_sha256"] == _sha256(
            data_dir / "data_source_qa.json"
        )
        assert metadata["data_source_qa_answers_path"] == str(data_dir / "data_source_qa_answers.json")
        assert metadata["data_source_qa_answers_sha256"] == _sha256(
            data_dir / "data_source_qa_answers.json"
        )
    assert set(DataProvider(BarStorage(cache)).all_symbols()) == {"000010", "600010"}


def test_offline_data_intake_records_custom_source_qa_paths(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    cache = tmp_path / "recent.db"
    output = tmp_path / "out"
    config = tmp_path / "research_recent.yaml"
    qa_dir = tmp_path / "qa_bundle"
    checklist_path = qa_dir / "source_checklist.json"
    answers_path = qa_dir / "source_answers.json"
    _write_replaced_export(data_dir)
    _write_config(config, cache, start="2024-01-02", end="2024-01-03")
    checklist = build_data_source_qa(
        config_path=config,
        output_dir=qa_dir,
        min_symbols=2,
        as_of="2024-01-03",
    )
    qa_dir.mkdir(parents=True, exist_ok=True)
    checklist_path.write_text(
        json.dumps(checklist.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_source_answers(answers_path, checklist.to_dict())

    report = run_offline_data_intake(
        data_dir=data_dir,
        config_path=config,
        output_dir=output,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
        source_qa_checklist=checklist_path,
        source_qa_answers=answers_path,
    )

    metadata = BarStorage(cache).load_metadata()
    assert report.status == "PASS"
    assert metadata["data_source_qa_checklist_path"] == str(checklist_path)
    assert metadata["data_source_qa_checklist_sha256"] == _sha256(checklist_path)
    assert metadata["data_source_qa_answers_path"] == str(answers_path)
    assert metadata["data_source_qa_answers_sha256"] == _sha256(answers_path)


def test_offline_data_intake_strict_manifest_blocks_missing_attachments(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    cache = tmp_path / "recent.db"
    output = tmp_path / "out"
    config = tmp_path / "research_recent.yaml"
    _write_replaced_export(data_dir)
    _write_config(config, cache, start="2024-01-02", end="2024-01-03")
    checklist = build_data_source_qa(
        config_path=config,
        output_dir=data_dir,
        min_symbols=2,
        as_of="2024-01-03",
    )
    write_data_source_qa(checklist, data_dir)
    _write_source_answers(data_dir / "data_source_qa_answers.json", checklist.to_dict())
    manifest = build_source_qa_evidence_manifest(
        checklist_path=data_dir / "data_source_qa.json",
        evidence_dir=data_dir / "source_qa_evidence",
    )
    write_source_qa_evidence_manifest(manifest, data_dir)

    report = run_offline_data_intake(
        data_dir=data_dir,
        config_path=config,
        output_dir=output,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
        require_source_qa_evidence_manifest=True,
    )

    assert report.status == "BLOCK"
    assert [step.name for step in report.steps] == ["source_qa"]
    assert "SOURCE_QA_EVIDENCE_MANIFEST_EMPTY" in report.steps[0].message
    assert not cache.exists()


def test_offline_data_intake_records_source_qa_manifest_metadata(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    cache = tmp_path / "recent.db"
    output = tmp_path / "out"
    config = tmp_path / "research_recent.yaml"
    evidence_dir = data_dir / "source_qa_evidence"
    _write_replaced_export(data_dir)
    _write_config(config, cache, start="2024-01-02", end="2024-01-03")
    checklist = build_data_source_qa(
        config_path=config,
        output_dir=data_dir,
        min_symbols=2,
        as_of="2024-01-03",
    )
    write_data_source_qa(checklist, data_dir)
    _write_source_answers(data_dir / "data_source_qa_answers.json", checklist.to_dict())
    for item in checklist.checklist:
        if item.review_stage == "source" and item.severity == "BLOCK_IF_NO":
            _write_evidence_file(evidence_dir / f"{item.id}_evidence.txt", item.id)
    manifest = build_source_qa_evidence_manifest(
        checklist_path=data_dir / "data_source_qa.json",
        evidence_dir=evidence_dir,
    )
    write_source_qa_evidence_manifest(manifest, data_dir)

    report = run_offline_data_intake(
        data_dir=data_dir,
        config_path=config,
        output_dir=output,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
        require_source_qa_evidence_manifest=True,
    )

    import_payload = json.loads((output / "data_import.json").read_text(encoding="utf-8"))
    metadata = BarStorage(cache).load_metadata()
    for payload in [import_payload["metadata"], metadata]:
        assert payload["data_source_qa_evidence_manifest_path"] == str(
            data_dir / "source_qa_evidence_manifest.json"
        )
        assert payload["data_source_qa_evidence_manifest_sha256"] == _sha256(
            data_dir / "source_qa_evidence_manifest.json"
        )
        assert payload["data_source_qa_require_evidence_manifest"] == "True"
    assert report.status == "PASS"


def test_offline_data_intake_writes_source_answers_from_explicit_evidence(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    cache = tmp_path / "recent.db"
    output = tmp_path / "out"
    config = tmp_path / "research_recent.yaml"
    raw_bars = tmp_path / "raw_vendor_bars.csv"
    _write_raw_vendor_bars(raw_bars)
    _write_optional_metadata(data_dir)
    _write_config(config, cache, start="2024-01-02", end="2024-01-03")
    checklist = build_data_source_qa(
        config_path=config,
        output_dir=data_dir,
        min_symbols=2,
        as_of="2024-01-03",
    )
    write_data_source_qa(checklist, data_dir)

    report = run_offline_data_intake(
        raw_bars_csv=raw_bars,
        data_dir=data_dir,
        config_path=config,
        output_dir=output,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
        source_vendor="unit-test vendor",
        source_terminal="unit-test terminal",
        source_operator="tester",
        source_exported_at="2024-01-03 18:00:00",
        source_price_adjustment="qfq",
        source_price_adjustment_evidence="vendor export setting says qfq",
        source_license_evidence="unit-test license note",
        source_point_in_time_evidence="fundamentals and constituents are PIT snapshots",
        source_reviewed_by="tester",
        source_reviewed_at="2024-01-03",
    )

    review = build_data_source_qa_review(
        checklist_path=data_dir / "data_source_qa.json",
        answers_path=data_dir / "data_source_qa_answers.json",
    )
    assert report.status == "PASS"
    assert [step.name for step in report.steps] == [
        "vendor_bars_normalization",
        "source_qa_answers",
        "source_qa",
        "doctor",
        "csv_validation",
        "source_csv_qa",
        "import",
        "real_data_bootstrap",
    ]
    assert review.status == "PASS"
    assert (data_dir / "data_source_qa_answers.json").exists()
    assert (output / "data_source_qa_review.json").exists()


def test_offline_data_intake_blocks_partial_source_answer_fields(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    cache = tmp_path / "recent.db"
    output = tmp_path / "out"
    config = tmp_path / "research_recent.yaml"
    raw_bars = tmp_path / "raw_vendor_bars.csv"
    _write_raw_vendor_bars(raw_bars)
    _write_optional_metadata(data_dir)
    _write_config(config, cache, start="2024-01-02", end="2024-01-03")
    checklist = build_data_source_qa(
        config_path=config,
        output_dir=data_dir,
        min_symbols=2,
        as_of="2024-01-03",
    )
    write_data_source_qa(checklist, data_dir)

    report = run_offline_data_intake(
        raw_bars_csv=raw_bars,
        data_dir=data_dir,
        config_path=config,
        output_dir=output,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
        source_vendor="unit-test vendor",
    )

    assert report.status == "BLOCK"
    assert [step.name for step in report.steps] == [
        "vendor_bars_normalization",
        "source_qa_answers",
    ]
    assert "source_terminal" in report.steps[1].message
    assert not (data_dir / "data_source_qa_answers.json").exists()
    assert not cache.exists()


def test_offline_data_intake_cli_writes_report_and_returns_nonzero_on_block(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "out"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    write_research_csv_templates(data_dir)
    _write_config(config, cache, start="2024-01-02", end="2024-01-03")

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_offline_data_intake.py",
            "--data-dir",
            str(data_dir),
            "--config",
            str(config),
            "--output-dir",
            str(output),
            "--min-symbols",
            "2",
            "--min-trading-days",
            "2",
            "--as-of",
            "2024-01-03",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((output / "offline_data_intake.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["status"] == "BLOCK"
    assert payload["steps"][0]["name"] == "doctor"


def test_offline_data_intake_cli_accepts_raw_bars_csv(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "out"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    raw_bars = tmp_path / "raw_vendor_bars.csv"
    _write_raw_vendor_bars(raw_bars)
    _write_optional_metadata(data_dir)
    _write_config(config, cache, start="2024-01-02", end="2024-01-03")

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_offline_data_intake.py",
            "--raw-bars-csv",
            str(raw_bars),
            "--data-dir",
            str(data_dir),
            "--config",
            str(config),
            "--output-dir",
            str(output),
            "--min-symbols",
            "2",
            "--min-trading-days",
            "2",
            "--as-of",
            "2024-01-03",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((output / "offline_data_intake.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["status"] == "PASS"
    assert payload["steps"][0]["name"] == "vendor_bars_normalization"
    assert (output / "vendor_bars_normalization.json").exists()


def test_offline_data_intake_cli_accepts_source_evidence_fields(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "out"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    raw_bars = tmp_path / "raw_vendor_bars.csv"
    _write_raw_vendor_bars(raw_bars)
    _write_optional_metadata(data_dir)
    _write_config(config, cache, start="2024-01-02", end="2024-01-03")
    checklist = build_data_source_qa(
        config_path=config,
        output_dir=data_dir,
        min_symbols=2,
        as_of="2024-01-03",
    )
    write_data_source_qa(checklist, data_dir)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_offline_data_intake.py",
            "--raw-bars-csv",
            str(raw_bars),
            "--data-dir",
            str(data_dir),
            "--config",
            str(config),
            "--output-dir",
            str(output),
            "--min-symbols",
            "2",
            "--min-trading-days",
            "2",
            "--as-of",
            "2024-01-03",
            "--source-vendor",
            "unit-test vendor",
            "--source-terminal",
            "unit-test terminal",
            "--source-operator",
            "tester",
            "--source-exported-at",
            "2024-01-03 18:00:00",
            "--source-price-adjustment",
            "qfq",
            "--source-price-adjustment-evidence",
            "vendor export setting says qfq",
            "--source-license-evidence",
            "unit-test license note",
            "--source-point-in-time-evidence",
            "fundamentals and constituents are PIT snapshots",
            "--source-reviewed-by",
            "tester",
            "--source-reviewed-at",
            "2024-01-03",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((output / "offline_data_intake.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["status"] == "PASS"
    assert payload["steps"][1]["name"] == "source_qa_answers"
    assert (data_dir / "data_source_qa_answers.json").exists()


def _write_config(path: Path, cache: Path, *, start: str, end: str) -> None:
    path.write_text(
        "\n".join(
            [
                "research:",
                f'  start: "{start}"',
                f'  end: "{end}"',
                f'  in_sample_end: "{start}"',
                f'  out_sample_start: "{end}"',
                "  allow_demo_data: false",
                "data:",
                "  source: csv",
                f"  cache_path: '{cache}'",
                "  adjust: qfq",
                "universe:",
                "  index_code: '000906'",
                "  mode: all_a",
                "  include_st: false",
                "  min_history_days: 1",
                "strategy:",
                "  name: price_volume_defensive",
                "  n_holdings: 2",
                "  max_weight: 0.10",
                "risk:",
                "  max_drawdown_stop: 0.2",
                "broker:",
                "  commission_rate: 0.0",
                "  stamp_tax: 0.0",
                "  slippage_bps: 0.0",
                "  price_limit_pct: 0.10",
                "  lot_size: 100",
            ]
        ),
        encoding="utf-8",
    )


def _write_replaced_export(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "symbol": ["600010", "600010", "000010", "000010"],
            "date": ["2024-01-02", "2024-01-03", "2024-01-02", "2024-01-03"],
            "open": [11.0, 11.1, 21.0, 21.1],
            "high": [11.5, 11.6, 21.5, 21.6],
            "low": [10.8, 11.0, 20.8, 21.0],
            "close": [11.2, 11.3, 21.2, 21.3],
            "volume": [1_500_000, 1_600_000, 2_500_000, 2_600_000],
            "amount": [16_800_000, 18_080_000, 53_000_000, 55_380_000],
        }
    ).to_csv(data_dir / "bars.csv", index=False)
    pd.DataFrame(
        {
            "symbol": ["600010", "000010"],
            "name": ["RealishSSE", "RealishSZSE"],
            "exchange": ["SSE", "SZSE"],
            "list_date": ["2001-01-01", "2002-01-01"],
            "delist_date": ["", ""],
            "industry": ["industry_a", "industry_b"],
            "is_st": [0, 0],
        }
    ).to_csv(data_dir / "stock_info.csv", index=False)
    pd.DataFrame(
        {
            "symbol": ["600010", "000010"],
            "date": ["2024-01-02", "2024-01-02"],
            "pe_ttm": [9.0, 11.0],
            "pb": [1.0, 1.3],
            "roe": [0.09, 0.11],
            "market_cap": [9_000_000_000, 11_000_000_000],
            "turnover_rate": [0.015, 0.025],
        }
    ).to_csv(data_dir / "fundamentals.csv", index=False)
    pd.DataFrame({"date": ["2024-01-02", "2024-01-03", "2024-01-04"], "is_open": [1, 1, 0]}).to_csv(
        data_dir / "calendar.csv",
        index=False,
    )
    pd.DataFrame(
        {
            "symbol": ["600010", "000010"],
            "date": ["2024-01-03", "2024-01-03"],
            "is_suspended": [0, 0],
        }
    ).to_csv(data_dir / "suspensions.csv", index=False)
    pd.DataFrame(
        {
            "index_code": ["000906", "000906"],
            "date": ["2024-01-02", "2024-01-02"],
            "symbol": ["600010", "000010"],
        }
    ).to_csv(data_dir / "index_constituents.csv", index=False)


def _write_optional_metadata(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "symbol": ["600010", "000010"],
            "name": ["RealishSSE", "RealishSZSE"],
            "exchange": ["SSE", "SZSE"],
            "list_date": ["2001-01-01", "2002-01-01"],
            "delist_date": ["", ""],
            "industry": ["industry_a", "industry_b"],
            "is_st": [0, 0],
        }
    ).to_csv(data_dir / "stock_info.csv", index=False)
    pd.DataFrame(
        {
            "symbol": ["600010", "000010"],
            "date": ["2024-01-02", "2024-01-02"],
            "pe_ttm": [9.0, 11.0],
            "pb": [1.0, 1.3],
            "roe": [0.09, 0.11],
            "market_cap": [9_000_000_000, 11_000_000_000],
            "turnover_rate": [0.015, 0.025],
        }
    ).to_csv(data_dir / "fundamentals.csv", index=False)
    pd.DataFrame({"date": ["2024-01-02", "2024-01-03", "2024-01-04"], "is_open": [1, 1, 0]}).to_csv(
        data_dir / "calendar.csv",
        index=False,
    )
    pd.DataFrame(
        {
            "symbol": ["600010", "000010"],
            "date": ["2024-01-03", "2024-01-03"],
            "is_suspended": [0, 0],
        }
    ).to_csv(data_dir / "suspensions.csv", index=False)
    pd.DataFrame(
        {
            "index_code": ["000906", "000906"],
            "date": ["2024-01-02", "2024-01-02"],
            "symbol": ["600010", "000010"],
        }
    ).to_csv(data_dir / "index_constituents.csv", index=False)


def _write_raw_vendor_bars(path: Path, *, drop_close: bool = False) -> None:
    frame = pd.DataFrame(
        {
            "证券代码": ["600010.SH", "600010.SH", "SZ000010", "SZ000010"],
            "交易日期": [20240102, 20240103, 20240102, 20240103],
            "开盘价": [11.0, 11.1, 21.0, 21.1],
            "最高价": [11.5, 11.6, 21.5, 21.6],
            "最低价": [10.8, 11.0, 20.8, 21.0],
            "收盘价": [11.2, 11.3, 21.2, 21.3],
            "成交量": [1_500_000, 1_600_000, 2_500_000, 2_600_000],
            "成交额": [16_800_000, 18_080_000, 53_000_000, 55_380_000],
        }
    )
    if drop_close:
        frame = frame.drop(columns=["收盘价"])
    frame.to_csv(path, index=False)


def _write_day_file(path: Path, *, symbol_base: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = struct.Struct("<IIIIIfII")
    rows = [
        record.pack(
            20240102,
            int(symbol_base * 100),
            int((symbol_base + 0.5) * 100),
            int((symbol_base - 0.2) * 100),
            int((symbol_base + 0.2) * 100),
            float((symbol_base + 0.2) * 1_000_000),
            1_000_000,
            0,
        ),
        record.pack(
            20240103,
            int((symbol_base + 0.2) * 100),
            int((symbol_base + 0.8) * 100),
            int((symbol_base + 0.1) * 100),
            int((symbol_base + 0.6) * 100),
            float((symbol_base + 0.6) * 1_100_000),
            1_100_000,
            0,
        ),
    ]
    path.write_bytes(b"".join(rows))


def _write_source_answers(path: Path, checklist: dict) -> None:
    answers = {
        item["id"]: {
            "answer": "yes",
            "evidence": f"source evidence for {item['id']}",
            "notes": "",
        }
        for item in checklist["checklist"]
        if item["review_stage"] == "source"
    }
    payload = {
        "source_metadata": {
            "data_vendor_or_broker": "unit-test vendor",
            "terminal_or_product_name": "unit-test terminal",
            "export_operator": "tester",
            "exported_at_local_time": "2024-01-03 18:00:00",
            "market": "A-share equities",
            "frequency": "daily",
            "date_range": "2024-01-02 to 2024-01-03",
            "price_adjustment": "qfq",
            "encoding": "utf-8-sig",
            "license_or_usage_scope": "research and paper trading only",
            "known_limitations": "none",
            "reviewed_by": "tester",
            "reviewed_at": "2024-01-03",
        },
        "answers": answers,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_evidence_file(path: Path, item_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"auditable local evidence for {item_id}", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
