from __future__ import annotations

import json
from pathlib import Path
import struct
import subprocess
import sys

from quantify.data.source_qa import (
    build_data_source_qa_answers,
    build_data_source_qa_review,
    write_data_source_qa_answers,
)
from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.data.tdx_day import export_tdx_day_to_csv
from quantify.data.tdx_intake import run_tdx_ohlcv_intake
from quantify.data.tdx_source_qa import (
    TDX_OHLCV_ONLY_PIT_NOTE,
    build_tdx_source_qa_answers,
    write_tdx_source_qa_answers,
    write_tdx_source_qa_support_artifacts,
)


def test_tdx_ohlcv_intake_blocks_after_conversion_without_source_qa(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "vipdoc"
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "out"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    _write_day_file(input_dir / "sh" / "lday" / "sh600010.day", symbol_base=10.0)
    _write_day_file(input_dir / "sz" / "lday" / "sz000010.day", symbol_base=20.0)
    _write_config(config, cache)

    report = run_tdx_ohlcv_intake(
        input_dir=input_dir,
        data_dir=data_dir,
        output_dir=output,
        config_path=config,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
    )

    step_status = {step.name: step.status for step in report.steps}
    assert report.status == "BLOCK"
    assert step_status["tdx_day_discovery"] == "PASS"
    assert step_status["tdx_day_export"] == "PASS"
    assert step_status["real_data_handoff"] == "BLOCK"
    assert step_status["offline_data_package"] == "BLOCK"
    assert step_status["guarded_offline_intake"] == "SKIPPED"
    assert (data_dir / "bars.csv").exists()
    assert (data_dir / "data_source_qa.json").exists()
    assert not cache.exists()


def test_tdx_ohlcv_intake_runs_guarded_intake_with_source_qa(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "vipdoc"
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "out"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    _write_day_file(input_dir / "sh" / "lday" / "sh600010.day", symbol_base=10.0)
    _write_day_file(input_dir / "sz" / "lday" / "sz000010.day", symbol_base=20.0)
    _write_config(config, cache)
    _write_source_answers_after_checklist(data_dir, config)

    report = run_tdx_ohlcv_intake(
        input_dir=input_dir,
        data_dir=data_dir,
        output_dir=output,
        config_path=config,
        source_qa_answers=data_dir / "data_source_qa_answers.json",
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
        run_guarded_intake=True,
    )

    step_status = {step.name: step.status for step in report.steps}
    assert report.status == "WATCH"
    assert step_status["real_data_handoff"] == "WATCH"
    assert step_status["offline_data_package"] == "WATCH"
    assert step_status["guarded_offline_intake"] == "WATCH"
    assert set(DataProvider(BarStorage(cache)).all_symbols()) == {"000010", "600010"}
    assert (output / "offline_intake" / "offline_data_intake.json").exists()


def test_tdx_ohlcv_intake_strict_manifest_blocks_when_missing(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "vipdoc"
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "out"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    manifest = data_dir / "source_qa_evidence_manifest.json"
    _write_day_file(input_dir / "sh" / "lday" / "sh600010.day", symbol_base=10.0)
    _write_day_file(input_dir / "sz" / "lday" / "sz000010.day", symbol_base=20.0)
    _write_config(config, cache)
    _write_source_answers_after_checklist(data_dir, config)

    report = run_tdx_ohlcv_intake(
        input_dir=input_dir,
        data_dir=data_dir,
        output_dir=output,
        config_path=config,
        source_qa_answers=data_dir / "data_source_qa_answers.json",
        source_qa_evidence_manifest=manifest,
        require_source_qa_evidence_manifest=True,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
        run_guarded_intake=True,
    )

    payload = json.loads((output / "tdx_ohlcv_intake.json").read_text(encoding="utf-8"))
    offline_payload = json.loads(
        (output / "offline_intake" / "offline_data_intake.json").read_text(encoding="utf-8")
    )
    step_by_name = {step["name"]: step for step in payload["steps"]}
    offline_step_by_name = {step["name"]: step for step in offline_payload["steps"]}
    assert report.status == "BLOCK"
    assert payload["require_source_qa_evidence_manifest"] is True
    assert payload["source_qa_evidence_manifest_path"] == str(manifest)
    assert step_by_name["guarded_offline_intake"]["status"] == "BLOCK"
    assert offline_step_by_name["source_qa"]["status"] == "BLOCK"
    assert "SOURCE_QA_EVIDENCE_MANIFEST_MISSING" in offline_step_by_name["source_qa"]["message"]
    assert not cache.exists()


def test_tdx_ohlcv_intake_strict_manifest_records_metadata_when_present(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "vipdoc"
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "out"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    manifest = data_dir / "source_qa_evidence_manifest.json"
    _write_day_file(input_dir / "sh" / "lday" / "sh600010.day", symbol_base=10.0)
    _write_day_file(input_dir / "sz" / "lday" / "sz000010.day", symbol_base=20.0)
    _write_config(config, cache)
    _write_tdx_source_answers_and_support(input_dir, data_dir, config)

    report = run_tdx_ohlcv_intake(
        input_dir=input_dir,
        data_dir=data_dir,
        output_dir=output,
        config_path=config,
        source_qa_answers=data_dir / "data_source_qa_answers.json",
        source_qa_evidence_manifest=manifest,
        require_source_qa_evidence_manifest=True,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
        run_guarded_intake=True,
    )

    payload = json.loads((output / "tdx_ohlcv_intake.json").read_text(encoding="utf-8"))
    offline_payload = json.loads(
        (output / "offline_intake" / "offline_data_intake.json").read_text(encoding="utf-8")
    )
    import_payload = json.loads((output / "offline_intake" / "data_import.json").read_text(encoding="utf-8"))
    step_status = {step["name"]: step["status"] for step in payload["steps"]}
    offline_step_status = {step["name"]: step["status"] for step in offline_payload["steps"]}
    metadata = BarStorage(cache).load_metadata()
    assert report.status in {"PASS", "WATCH"}
    assert payload["require_source_qa_evidence_manifest"] is True
    assert payload["source_qa_evidence_manifest_path"] == str(manifest)
    assert step_status["guarded_offline_intake"] in {"PASS", "WATCH"}
    assert offline_step_status["source_qa"] == "PASS"
    assert offline_step_status["import"] in {"PASS", "WATCH"}
    for item in [metadata, import_payload["metadata"]]:
        assert item["data_source_qa_require_evidence_manifest"] == "True"
        assert item["data_source_qa_evidence_manifest_path"] == str(manifest)
        assert len(item["data_source_qa_evidence_manifest_sha256"]) == 64


def test_tdx_ohlcv_intake_cli_returns_nonzero_on_missing_source_qa(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "vipdoc"
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "out"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    _write_day_file(input_dir / "sh" / "lday" / "sh600010.day", symbol_base=10.0)
    _write_config(config, cache)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_tdx_ohlcv_intake.py",
            "--input-dir",
            str(input_dir),
            "--data-dir",
            str(data_dir),
            "--output-dir",
            str(output),
            "--config",
            str(config),
            "--min-symbols",
            "1",
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

    payload = json.loads((output / "tdx_ohlcv_intake.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["status"] == "BLOCK"
    assert any(step["name"] == "real_data_handoff" for step in payload["steps"])


def test_tdx_ohlcv_intake_cli_records_strict_manifest_args(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "vipdoc"
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "out"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    _write_day_file(input_dir / "sh" / "lday" / "sh600010.day", symbol_base=10.0)
    _write_config(config, cache)
    _write_source_answers_after_checklist(data_dir, config)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_tdx_ohlcv_intake.py",
            "--input-dir",
            str(input_dir),
            "--data-dir",
            str(data_dir),
            "--output-dir",
            str(output),
            "--config",
            str(config),
            "--source-qa-answers",
            str(data_dir / "data_source_qa_answers.json"),
            "--source-qa-evidence-manifest",
            str(data_dir / "source_qa_evidence_manifest.json"),
            "--require-source-qa-evidence-manifest",
            "--run-guarded-intake",
            "--min-symbols",
            "1",
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

    payload = json.loads((output / "tdx_ohlcv_intake.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["status"] == "BLOCK"
    assert payload["require_source_qa_evidence_manifest"] is True
    assert payload["source_qa_evidence_manifest_path"] == str(data_dir / "source_qa_evidence_manifest.json")


def test_tdx_source_qa_answers_pass_source_review_and_record_ohlcv_boundary(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "vipdoc"
    data_dir = tmp_path / "data_exports"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    _write_day_file(input_dir / "sh" / "lday" / "sh600010.day", symbol_base=10.0)
    _write_config(config, cache)
    _write_source_qa_checklist(data_dir, config)
    export_tdx_day_to_csv(input_dir=input_dir, output_dir=data_dir, start="2024-01-02", end="2024-01-03")

    answers = build_tdx_source_qa_answers(
        checklist_path=data_dir / "data_source_qa.json",
        tdx_export_report=data_dir / "tdx_day_export.json",
        input_dir=input_dir,
        export_operator="tester",
        exported_at_local_time="2024-01-03 18:00:00",
        price_adjustment="qfq",
        price_adjustment_evidence="TDX settings panel recorded qfq before conversion",
        license_evidence="operator account permits local research and paper-trading review",
        reviewed_by="tester",
        reviewed_at="2024-01-03",
    )
    write_tdx_source_qa_answers(answers, data_dir / "data_source_qa_answers.json")

    review = build_data_source_qa_review(
        checklist_path=data_dir / "data_source_qa.json",
        answers_path=data_dir / "data_source_qa_answers.json",
    )

    assert review.status == "PASS"
    assert answers["source_metadata"]["tdx_symbol_count"] == 1
    assert "OHLCV-only" in answers["source_metadata"]["candidate_scope"]
    assert TDX_OHLCV_ONLY_PIT_NOTE in answers["answers"]["point_in_time"]["evidence"]
    assert answers["answers"]["calendar"]["answer"] == ""


def test_write_tdx_source_qa_answers_cli_writes_reviewable_answers(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "vipdoc"
    data_dir = tmp_path / "data_exports"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    _write_day_file(input_dir / "sh" / "lday" / "sh600010.day", symbol_base=10.0)
    _write_config(config, cache)
    _write_source_qa_checklist(data_dir, config)
    export_tdx_day_to_csv(input_dir=input_dir, output_dir=data_dir, start="2024-01-02", end="2024-01-03")

    completed = subprocess.run(
        [
            sys.executable,
            "examples/write_tdx_source_qa_answers.py",
            "--checklist",
            str(data_dir / "data_source_qa.json"),
            "--output",
            str(data_dir / "data_source_qa_answers.json"),
            "--tdx-export-report",
            str(data_dir / "tdx_day_export.json"),
            "--input-dir",
            str(input_dir),
            "--operator",
            "tester",
            "--exported-at",
            "2024-01-03 18:00:00",
            "--price-adjustment",
            "qfq",
            "--price-adjustment-evidence",
            "TDX settings panel recorded qfq before conversion",
            "--license-evidence",
            "operator account permits local research and paper-trading review",
            "--reviewed-by",
            "tester",
            "--reviewed-at",
            "2024-01-03",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((data_dir / "data_source_qa_answers.json").read_text(encoding="utf-8"))
    review = build_data_source_qa_review(
        checklist_path=data_dir / "data_source_qa.json",
        answers_path=data_dir / "data_source_qa_answers.json",
    )
    assert completed.returncode == 0
    assert payload["source_metadata"]["data_vendor_or_broker"] == "TongDaXin local .day files"
    assert payload["source_metadata"]["tdx_row_count"] == 2
    assert review.status == "PASS"


def test_write_tdx_source_qa_support_artifacts_writes_manifestable_files(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "vipdoc"
    data_dir = tmp_path / "data_exports"
    cache = tmp_path / "recent.db"
    config = tmp_path / "research_recent.yaml"
    _write_day_file(input_dir / "sh" / "lday" / "sh600010.day", symbol_base=10.0)
    _write_config(config, cache)
    _write_source_qa_checklist(data_dir, config)
    export_tdx_day_to_csv(input_dir=input_dir, output_dir=data_dir, start="2024-01-02", end="2024-01-03")

    answers = build_tdx_source_qa_answers(
        checklist_path=data_dir / "data_source_qa.json",
        tdx_export_report=data_dir / "tdx_day_export.json",
        input_dir=input_dir,
        export_operator="tester",
        exported_at_local_time="2024-01-03 18:00:00",
        price_adjustment="qfq",
        price_adjustment_evidence="TDX settings panel recorded qfq before conversion",
        license_evidence="operator account permits local research and paper-trading review",
        reviewed_by="tester",
        reviewed_at="2024-01-03",
    )
    support = write_tdx_source_qa_support_artifacts(
        answers,
        checklist_path=data_dir / "data_source_qa.json",
        worksheet_path=data_dir / "data_source_qa_evidence_worksheet.csv",
        evidence_dir=data_dir / "source_qa_evidence",
        manifest_path=data_dir / "source_qa_evidence_manifest.json",
    )

    manifest = json.loads((data_dir / "source_qa_evidence_manifest.json").read_text(encoding="utf-8"))
    assert support["worksheet_preflight_status"] == "PASS"
    assert (data_dir / "data_source_qa_evidence_worksheet.csv").exists()
    assert (data_dir / "source_qa_evidence" / "source_identity_receipt.md").exists()
    assert (data_dir / "source_qa_evidence" / "license_scope_note.md").exists()
    assert (data_dir / "source_qa_evidence" / "price_adjustment_qfq.md").exists()
    assert (data_dir / "source_qa_evidence" / "point_in_time_note.md").exists()
    assert (data_dir / "source_qa_evidence" / "manual_signoff.md").exists()
    assert len(manifest["items"]) >= 5


def _write_config(path: Path, cache: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "research:",
                '  start: "2024-01-02"',
                '  end: "2024-01-03"',
                '  in_sample_end: "2024-01-02"',
                '  out_sample_start: "2024-01-03"',
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
            ]
        ),
        encoding="utf-8",
    )


def _write_source_answers_after_checklist(data_dir: Path, config: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_source_qa_checklist(data_dir, config)
    answers = build_data_source_qa_answers(
        checklist_path=data_dir / "data_source_qa.json",
        data_vendor_or_broker="TongDaXin local files",
        terminal_or_product_name="unit-test TDX",
        export_operator="tester",
        exported_at_local_time="2024-01-03 18:00:00",
        price_adjustment="qfq",
        price_adjustment_evidence="unit-test adjustment evidence",
        license_or_usage_scope="research and paper trading only",
        license_evidence="unit-test license evidence",
        point_in_time_evidence="OHLCV-only path; no fundamentals used",
        reviewed_by="tester",
        reviewed_at="2024-01-03",
    )
    write_data_source_qa_answers(answers, data_dir / "data_source_qa_answers.json")


def _write_tdx_source_answers_and_support(input_dir: Path, data_dir: Path, config: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    _write_source_qa_checklist(data_dir, config)
    export_tdx_day_to_csv(input_dir=input_dir, output_dir=data_dir, start="2024-01-02", end="2024-01-03")
    answers = build_tdx_source_qa_answers(
        checklist_path=data_dir / "data_source_qa.json",
        tdx_export_report=data_dir / "tdx_day_export.json",
        input_dir=input_dir,
        export_operator="tester",
        exported_at_local_time="2024-01-03 18:00:00",
        price_adjustment="qfq",
        price_adjustment_evidence="TDX settings panel recorded qfq before conversion",
        license_evidence="operator account permits local research and paper-trading review",
        reviewed_by="tester",
        reviewed_at="2024-01-03",
    )
    write_tdx_source_qa_answers(answers, data_dir / "data_source_qa_answers.json")
    write_tdx_source_qa_support_artifacts(
        answers,
        checklist_path=data_dir / "data_source_qa.json",
        worksheet_path=data_dir / "data_source_qa_evidence_worksheet.csv",
        evidence_dir=data_dir / "source_qa_evidence",
        manifest_path=data_dir / "source_qa_evidence_manifest.json",
    )


def _write_source_qa_checklist(data_dir: Path, config: Path) -> None:
    from quantify.data.source_qa import build_data_source_qa, write_data_source_qa

    checklist = build_data_source_qa(
        config_path=config,
        output_dir=data_dir,
        min_symbols=2,
        as_of="2024-01-03",
    )
    write_data_source_qa(checklist, data_dir)


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
