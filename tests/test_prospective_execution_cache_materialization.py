from __future__ import annotations

import csv
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path

import pandas as pd
import yaml

from quantify.data.prospective_acquisition_journal import (
    ATTEMPT_LEDGER_FILENAME,
    record_prospective_acquisition_attempt,
)
from quantify.data.prospective_daily_acquisition import (
    build_prospective_daily_acquisition_preflight,
    handoff_prospective_daily_acquisition,
    run_prospective_daily_acquisition,
)
from quantify.data.provenance import logical_bar_fingerprint
from quantify.data.source_qa import (
    build_data_source_qa,
    build_data_source_qa_answers,
    build_source_qa_evidence_manifest,
    write_data_source_qa,
    write_data_source_qa_answers,
    write_source_qa_evidence_manifest,
)
from quantify.data.storage import BarStorage
from quantify.research.prospective_execution_cache_materialization import (
    ARTIFACT_FILENAME,
    CACHE_FILENAME,
    CLAIM_FILENAME,
    build_prospective_execution_cache_materialization_verification,
    materialize_prospective_execution_cache,
)
from quantify.research.prospective_trial_admission import build_prospective_trial_admission
from quantify.research.prospective_terminal_analysis import (
    ARTIFACT_FILENAME as TERMINAL_ARTIFACT_FILENAME,
    CLAIM_FILENAME as TERMINAL_CLAIM_FILENAME,
    RECEIPT_FILENAME as TERMINAL_RECEIPT_FILENAME,
    build_prospective_terminal_analysis_verification,
    run_prospective_terminal_analysis,
)
from quantify.research.prospective_trial_packet import (
    append_packet_preregistration,
    build_prospective_trial_packet,
    write_prospective_trial_packet,
)
from quantify.research.trial_registry import ResultEvent, verify_registry

REGISTRATION_TIME = datetime(2026, 7, 16, 0, 0, tzinfo=UTC)
POST_HOLDOUT_TIME = datetime(2026, 7, 21, 1, 0, tzinfo=UTC)
OPEN_DATES = ("2026-07-17", "2026-07-20")


def test_pre_holdout_blocks_without_writing_or_reading_sealed_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _prepared_trial(tmp_path, monkeypatch)
    output = tmp_path / "materialized"
    claim = paths["quarantine"] / CLAIM_FILENAME
    retained = next((paths["quarantine"] / "sealed_inputs").glob("*.csv"))
    retained_hash = _sha256(retained)
    _set_materialization_clock(monkeypatch, datetime(2026, 7, 20, 2, 0, tzinfo=UTC))

    report = _materialize(paths, output)

    assert report.status == "BLOCK"
    assert report.materialized is False
    assert _check_status(report, "POST_HOLDOUT_TIME_SEAL") == "BLOCK"
    assert "not evaluated" in next(
        item.message
        for item in report.checks
        if item.code == "COMPLETE_REVIEWED_SESSION_CONTINUITY"
    )
    assert not output.exists()
    assert not claim.exists()
    assert _sha256(retained) == retained_hash


def test_complete_evidence_replays_deterministically_without_changing_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _prepared_trial(tmp_path, monkeypatch)
    output = tmp_path / "materialized"
    source_hash = _sha256(paths["cache"])
    expected_fingerprint = _expected_logical_fingerprint(paths)
    _set_materialization_clock(monkeypatch, POST_HOLDOUT_TIME)

    report = _materialize(paths, output)

    assert report.status == "PASS", report.blockers
    assert report.materialized is True
    assert report.output_cache["logical_bar_fingerprint"] == expected_fingerprint
    assert report.output_cache["bar_end"] == "2026-07-20"
    assert report.output_cache["symbol_count"] == 2
    assert _sha256(paths["cache"]) == source_hash
    assert (output / CACHE_FILENAME).is_file()
    assert (output / ARTIFACT_FILENAME).is_file()
    assert (paths["quarantine"] / CLAIM_FILENAME).is_file()
    assert BarStorage(output / CACHE_FILENAME).load_calendar("2026-07-17", "2026-07-20") == list(
        OPEN_DATES
    )
    assert BarStorage(output / CACHE_FILENAME).load_index_constituents("000906", "2026-07-20") == [
        "000001",
        "600001",
    ]

    verification = build_prospective_execution_cache_materialization_verification(
        output / ARTIFACT_FILENAME,
        packet_dir=paths["packet_dir"],
        registry_path=paths["registry"],
    )
    assert verification.status == "PASS", verification.blockers
    assert verification.output_cache_path == str(output / CACHE_FILENAME)


def test_incomplete_reviewed_session_continuity_blocks_with_zero_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _prepared_trial(tmp_path, monkeypatch, collect_dates=("2026-07-17",))
    output = tmp_path / "materialized"
    _set_materialization_clock(monkeypatch, POST_HOLDOUT_TIME)

    report = _materialize(paths, output)

    assert report.status == "BLOCK"
    assert _check_status(report, "COMPLETE_REVIEWED_SESSION_CONTINUITY") == "BLOCK"
    assert not output.exists()
    assert not (paths["quarantine"] / CLAIM_FILENAME).exists()


def test_legacy_frozen_prefix_without_lineage_is_rebuilt_only_in_new_cache(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _prepared_trial(tmp_path, monkeypatch, legacy_source=True)
    output = tmp_path / "materialized"
    source_hash = _sha256(paths["cache"])
    _set_materialization_clock(monkeypatch, POST_HOLDOUT_TIME)

    report = _materialize(paths, output)

    assert report.status == "PASS", report.blockers
    assert (
        report.source_development["source_lineage_status"] == "LEGACY_FROZEN_PREFIX_WITHOUT_LINEAGE"
    )
    assert _sha256(paths["cache"]) == source_hash
    verification = build_prospective_execution_cache_materialization_verification(
        output / ARTIFACT_FILENAME,
        packet_dir=paths["packet_dir"],
        registry_path=paths["registry"],
    )
    assert verification.status == "PASS", verification.blockers
    assert verification.promotion_metadata.cache_stats["provenance_lineage_record_count"] > 0


def test_tampered_attempt_journal_or_sealed_input_blocks_before_claim(
    tmp_path: Path,
    monkeypatch,
) -> None:
    journal_paths = _prepared_trial(tmp_path / "journal", monkeypatch)
    journal = journal_paths["quarantine"] / ATTEMPT_LEDGER_FILENAME
    journal.write_bytes(journal.read_bytes().replace(b'"sequence":1', b'"sequence":9', 1))
    _set_materialization_clock(monkeypatch, POST_HOLDOUT_TIME)

    journal_report = _materialize(journal_paths, tmp_path / "journal-output")

    assert journal_report.status == "BLOCK"
    assert _check_status(journal_report, "PROVIDER_ATTEMPT_JOURNAL") == "BLOCK"
    assert not (journal_paths["quarantine"] / CLAIM_FILENAME).exists()

    sealed_paths = _prepared_trial(tmp_path / "sealed", monkeypatch)
    retained = next((sealed_paths["quarantine"] / "sealed_inputs").glob("*.csv"))
    retained.write_bytes(retained.read_bytes() + b"\n")
    sealed_report = _materialize(sealed_paths, tmp_path / "sealed-output")

    assert sealed_report.status == "BLOCK"
    assert _check_status(sealed_report, "SEALED_COLLECTION_LEDGER") == "BLOCK"
    assert not (sealed_paths["quarantine"] / CLAIM_FILENAME).exists()


def test_one_time_claim_blocks_repeat_and_changed_cache_blocks_verification(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _prepared_trial(tmp_path, monkeypatch)
    first_output = tmp_path / "materialized"
    _set_materialization_clock(monkeypatch, POST_HOLDOUT_TIME)
    first = _materialize(paths, first_output)
    assert first.status == "PASS", first.blockers

    repeated = _materialize(paths, tmp_path / "replacement")

    assert repeated.status == "BLOCK"
    assert _check_status(repeated, "SINGLE_USE_OUTPUT_DIRECTORY") == "BLOCK"
    assert not (tmp_path / "replacement").exists()

    cache = first_output / CACHE_FILENAME
    with cache.open("ab") as handle:
        handle.write(b"changed")
    verification = build_prospective_execution_cache_materialization_verification(
        first_output / ARTIFACT_FILENAME,
        packet_dir=paths["packet_dir"],
        registry_path=paths["registry"],
    )
    assert verification.status == "BLOCK"
    assert _check_verification_status(verification, "MATERIALIZED_CACHE_BINDING") == "BLOCK"


def test_admission_requires_and_accepts_exact_materialization_binding(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _prepared_trial(tmp_path, monkeypatch)
    output = tmp_path / "materialized"
    _set_materialization_clock(monkeypatch, POST_HOLDOUT_TIME)
    monkeypatch.setattr(
        "quantify.research.prospective_trial_admission._runtime_now",
        lambda: POST_HOLDOUT_TIME,
    )

    without_artifact = _admission(paths)
    materialized = _materialize(paths, output)
    with_artifact = _admission(paths, output / ARTIFACT_FILENAME)

    assert without_artifact.status == "BLOCK"
    assert _check_status(without_artifact, "TERMINAL_EXECUTION_CACHE_BOUNDARY") == "BLOCK"
    assert materialized.status == "PASS", materialized.blockers
    assert with_artifact.status == "PASS", with_artifact.blockers
    assert with_artifact.execution_cache_source == "post_holdout_materialization"
    assert with_artifact.execution_cache_path == str(output / CACHE_FILENAME)
    assert with_artifact.materialization_verification is not None
    assert with_artifact.materialization_verification.status == "PASS"

    alternate = _write_market_evidence(tmp_path / "alternate-market")
    _write_csv(
        alternate["benchmark_csv"],
        [
            {"date": "2024-06-03", "value": "1000"},
            {"date": "2025-06-30", "value": "1050"},
            {"date": "2026-07-20", "value": "1101"},
        ],
    )
    metadata = json.loads(alternate["benchmark_metadata"].read_text(encoding="utf-8"))
    metadata["file_sha256"] = _sha256(alternate["benchmark_csv"])
    _write_json(alternate["benchmark_metadata"], metadata)
    mismatched = _admission(
        {**paths, **alternate},
        output / ARTIFACT_FILENAME,
    )
    assert mismatched.status == "BLOCK"
    assert _check_status(mismatched, "MATERIALIZATION_MARKET_EVIDENCE_BINDING") == "BLOCK"


def test_terminal_analysis_runs_once_and_appends_one_honest_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _prepared_trial(tmp_path, monkeypatch)
    materialization_output = tmp_path / "materialized"
    terminal_output = tmp_path / "terminal"
    _set_materialization_clock(monkeypatch, POST_HOLDOUT_TIME)
    monkeypatch.setattr(
        "quantify.research.prospective_trial_admission._runtime_now",
        lambda: POST_HOLDOUT_TIME,
    )
    monkeypatch.setattr(
        "quantify.research.prospective_terminal_analysis._runtime_now",
        lambda: POST_HOLDOUT_TIME,
    )
    materialized = _materialize(paths, materialization_output)
    assert materialized.status == "PASS", materialized.blockers
    cache_hash = _sha256(materialization_output / CACHE_FILENAME)

    terminal = _terminal(paths, materialization_output, terminal_output)

    assert terminal.status == "PASS"
    assert terminal.completed is True
    assert terminal.decision == "BLOCK"
    assert terminal.primary_metrics["total_return"] == 0.0
    assert terminal.benchmark_analysis["status"] == "BLOCK"
    assert _sha256(materialization_output / CACHE_FILENAME) == cache_hash
    assert (terminal_output / TERMINAL_ARTIFACT_FILENAME).is_file()
    assert (terminal_output / TERMINAL_RECEIPT_FILENAME).is_file()
    assert (paths["quarantine"] / TERMINAL_CLAIM_FILENAME).is_file()
    results = [
        event for event in verify_registry(paths["registry"]) if isinstance(event, ResultEvent)
    ]
    assert len(results) == 1
    assert results[0].result["decision"] == "BLOCK"
    assert results[0].result["terminal_artifact_sha256"] == terminal.artifact_sha256
    verification = build_prospective_terminal_analysis_verification(
        terminal_output / TERMINAL_ARTIFACT_FILENAME,
        packet_dir=paths["packet_dir"],
        registry_path=paths["registry"],
        materialization_artifact=materialization_output / ARTIFACT_FILENAME,
    )
    assert verification.status == "PASS", verification.blockers

    repeated = _terminal(paths, materialization_output, tmp_path / "terminal-replacement")
    assert repeated.status == "BLOCK"
    assert repeated.completed is False
    assert not (tmp_path / "terminal-replacement").exists()
    assert (
        len(
            [
                event
                for event in verify_registry(paths["registry"])
                if isinstance(event, ResultEvent)
            ]
        )
        == 1
    )

    summary = terminal_output / "summary.json"
    summary.write_bytes(summary.read_bytes() + b"\n")
    tampered = build_prospective_terminal_analysis_verification(
        terminal_output / TERMINAL_ARTIFACT_FILENAME,
        packet_dir=paths["packet_dir"],
        registry_path=paths["registry"],
        materialization_artifact=materialization_output / ARTIFACT_FILENAME,
    )
    assert tampered.status == "BLOCK"
    assert _check_verification_status(tampered, "TERMINAL_EVIDENCE_FILES") == "BLOCK"


def test_terminal_analysis_before_time_seal_writes_nothing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = _prepared_trial(tmp_path, monkeypatch)
    materialization_output = tmp_path / "materialized"
    _set_materialization_clock(monkeypatch, POST_HOLDOUT_TIME)
    materialized = _materialize(paths, materialization_output)
    assert materialized.status == "PASS", materialized.blockers
    sealed_time = datetime(2026, 7, 20, 2, 0, tzinfo=UTC)
    _set_materialization_clock(monkeypatch, sealed_time)
    monkeypatch.setattr(
        "quantify.research.prospective_trial_admission._runtime_now",
        lambda: sealed_time,
    )
    monkeypatch.setattr(
        "quantify.research.prospective_terminal_analysis._runtime_now",
        lambda: sealed_time,
    )
    output = tmp_path / "terminal"

    report = _terminal(paths, materialization_output, output)

    assert report.status == "BLOCK"
    assert report.completed is False
    assert not output.exists()
    assert not (paths["quarantine"] / TERMINAL_CLAIM_FILENAME).exists()
    assert not any(isinstance(event, ResultEvent) for event in verify_registry(paths["registry"]))


def _prepared_trial(
    tmp_path: Path,
    monkeypatch,
    *,
    collect_dates: tuple[str, ...] = OPEN_DATES,
    legacy_source: bool = False,
) -> dict[str, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "quantify.research.prospective_trial_packet._runtime_now",
        lambda: REGISTRATION_TIME,
    )
    cache = tmp_path / "development.db"
    bars = _development_bars()
    source_metadata = {
        "data_source": "akshare",
        "data_import_symbol_count": 2,
        "data_import_actual_bar_start": "2024-06-03",
        "data_import_actual_bar_end": "2026-07-14",
    }
    storage = BarStorage(cache)
    if legacy_source:
        storage.save_bars(bars)
        storage.save_metadata(source_metadata)
    else:
        storage.save_bars_with_lineage(
            bars,
            source_type="akshare_reviewed_export",
            source_reference="retained-development-export",
            cache_metadata=source_metadata,
            batch_id="development-prefix",
            imported_at_utc="2026-07-15T12:00:00+00:00",
        )
    plan = _write_plan(tmp_path / "protocol_plan.json")
    config = _write_config(tmp_path / "base.yaml", cache, end="2026-07-14")
    code = tmp_path / "frozen_candidate.py"
    code.write_text("VALUE = 1\n", encoding="utf-8")
    packet = build_prospective_trial_packet(
        plan_path=plan,
        base_config_path=config,
        development_cache_path=cache,
        execution_cache_path=cache,
        trial_id="guard-v1-materialization-test",
        candidate="liquidity_neutral_momentum_guard_price_volume",
        train_start="2024-06-03",
        train_end="2025-06-30",
        selection_start="2025-07-01",
        selection_end="2026-07-14",
        test_start="2026-07-17",
        test_end="2026-07-20",
        code_paths=[code],
    )
    assert packet.registry_append_allowed is True, packet.blockers
    packet_dir = write_prospective_trial_packet(packet, tmp_path / "packet")
    (packet_dir / "protocol_plan.json").write_bytes(plan.read_bytes())
    registry = tmp_path / "registry.jsonl"
    append_packet_preregistration(packet, registry)
    quarantine = tmp_path / "quarantine"
    for market_date in collect_dates:
        _collect_date(
            packet_dir=packet_dir,
            registry=registry,
            quarantine=quarantine,
            market_date=market_date,
            monkeypatch=monkeypatch,
        )
    qa = _write_source_qa(tmp_path, cache)
    calendar = _write_calendar(tmp_path / "calendar")
    market = _write_market_evidence(tmp_path / "market")
    return {
        "packet_dir": packet_dir,
        "registry": registry,
        "cache": cache,
        "quarantine": quarantine,
        **qa,
        **calendar,
        **market,
    }


def _collect_date(
    *,
    packet_dir: Path,
    registry: Path,
    quarantine: Path,
    market_date: str,
    monkeypatch,
) -> None:
    observed = datetime.fromisoformat(f"{market_date}T08:00:00+00:00")
    monkeypatch.setattr(
        "quantify.data.prospective_daily_acquisition._runtime_now",
        lambda value=observed: value,
    )
    monkeypatch.setattr(
        "quantify.research.sealed_holdout_intake._runtime_now",
        lambda value=observed: value,
    )
    preflight = build_prospective_daily_acquisition_preflight(
        packet_dir=packet_dir,
        trial_registry_path=registry,
        market_date=market_date,
        output_dir=quarantine,
        minimum_success_ratio=1.0,
    )
    assert preflight.status == "READY", preflight.blockers

    def fetch(symbol: str, start: str, end: str) -> tuple[pd.DataFrame, str]:
        assert start == market_date == end
        close = 10.0 if symbol == "000001" else 20.0
        return (
            pd.DataFrame(
                [
                    {
                        "symbol": symbol,
                        "date": market_date,
                        "open": close,
                        "high": close + 1.0,
                        "low": close - 1.0,
                        "close": close + 0.5,
                        "volume": 1000.0,
                        "amount": (close + 0.5) * 1000.0,
                    }
                ]
            ),
            "unit-test-provider",
        )

    acquisition = run_prospective_daily_acquisition(
        preflight,
        output_dir=quarantine,
        fetch_symbol=fetch,
        max_attempts=1,
        retry_delay_seconds=0,
    )
    assert acquisition.status == "PASS", acquisition.blockers
    record_prospective_acquisition_attempt(acquisition, quarantine)
    intake = handoff_prospective_daily_acquisition(
        acquisition,
        packet_dir=packet_dir,
        trial_registry_path=registry,
        output_dir=quarantine,
    )
    assert intake.status == "PASS", intake.blockers


def _write_source_qa(root: Path, cache: Path) -> dict[str, Path]:
    qa = root / "source_qa"
    config = _write_config(root / "qa_config.yaml", cache, end="2026-07-20")
    checklist = build_data_source_qa(
        config_path=config,
        output_dir=qa,
        as_of="2026-07-21",
    )
    write_data_source_qa(checklist, qa)
    answers = build_data_source_qa_answers(
        checklist_path=qa / "data_source_qa.json",
        data_vendor_or_broker="AKShare licensed unit-test provider",
        terminal_or_product_name="retained Eastmoney export terminal",
        export_operator="independent-test-operator",
        exported_at_local_time="2026-07-20 16:00:00",
        price_adjustment="qfq",
        price_adjustment_evidence="retained provider qfq setting receipt",
        license_or_usage_scope="research and paper trading only",
        license_evidence="retained research-use license record",
        point_in_time_evidence="PIT membership is retained separately; no fundamentals used",
        reviewed_by="independent-test-reviewer",
        reviewed_at="2026-07-20",
    )
    write_data_source_qa_answers(answers, qa / "data_source_qa_answers.json")
    evidence_dir = qa / "source_qa_evidence"
    for item in checklist.checklist:
        if item.review_stage == "source" and item.severity == "BLOCK_IF_NO":
            path = evidence_dir / f"{item.id}_evidence.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                f"Retained independent provider audit evidence for {item.id}; reviewed 2026-07-20.",
                encoding="utf-8",
            )
    manifest = build_source_qa_evidence_manifest(
        checklist_path=qa / "data_source_qa.json",
        evidence_dir=evidence_dir,
    )
    write_source_qa_evidence_manifest(manifest, qa)
    return {
        "source_qa_checklist": qa / "data_source_qa.json",
        "source_qa_answers": qa / "data_source_qa_answers.json",
        "source_qa_evidence_manifest": qa / "source_qa_evidence_manifest.json",
    }


def _write_calendar(root: Path) -> dict[str, Path]:
    root.mkdir()
    calendar_csv = root / "cn_a_share_calendar.csv"
    calendar_metadata = root / "cn_a_share_calendar.metadata.json"
    _write_csv(
        calendar_csv,
        [
            {"date": "2026-07-17", "is_open": "1"},
            {"date": "2026-07-18", "is_open": "0"},
            {"date": "2026-07-19", "is_open": "0"},
            {"date": "2026-07-20", "is_open": "1"},
        ],
    )
    _write_json(
        calendar_metadata,
        {
            "artifact_type": "reviewed_exchange_calendar",
            "schema_version": 1,
            "exchange_scope": "CN_A_SHARE",
            "timezone": "Asia/Shanghai",
            "date_column": "date",
            "is_open_column": "is_open",
            "coverage_start_date": "2026-07-17",
            "coverage_end_date": "2026-07-20",
            "source_vendor": "licensed-test-vendor",
            "source_dataset": "China A-share exchange calendar",
            "source_exported_at": "2026-07-20T18:00:00+08:00",
            "reviewed_by": "independent-test-reviewer",
            "reviewed_at": "2026-07-20T19:00:00+08:00",
            "file_sha256": _sha256(calendar_csv),
        },
    )
    return {"calendar_csv": calendar_csv, "calendar_metadata": calendar_metadata}


def _write_market_evidence(root: Path) -> dict[str, Path]:
    root.mkdir()
    benchmark_csv = root / "csi800_total_return.csv"
    benchmark_metadata = root / "csi800_total_return.metadata.json"
    membership_csv = root / "csi800_pit_membership.csv"
    membership_metadata = root / "csi800_pit_membership.metadata.json"
    _write_csv(
        benchmark_csv,
        [
            {"date": "2024-06-03", "value": "1000"},
            {"date": "2025-06-30", "value": "1050"},
            {"date": "2026-07-20", "value": "1100"},
        ],
    )
    membership_rows: list[dict[str, str]] = []
    for effective_date in ("2024-06-03", "2025-07-01", "2026-07-20"):
        for symbol in ("000001", "600001"):
            membership_rows.append(
                {
                    "index_code": "000906",
                    "effective_date": effective_date,
                    "symbol": symbol,
                }
            )
    _write_csv(membership_csv, membership_rows)
    provenance = {
        "coverage_start_date": "2024-06-03",
        "coverage_end_date": "2026-07-20",
        "source_vendor": "licensed-test-vendor",
        "source_exported_at": "2026-07-20T18:00:00+08:00",
        "reviewed_by": "independent-test-reviewer",
        "reviewed_at": "2026-07-20T19:00:00+08:00",
    }
    _write_json(
        benchmark_metadata,
        {
            "artifact_type": "reviewed_benchmark_series",
            "schema_version": 1,
            "symbol": "000906.SH",
            "name": "CSI 800 Total Return",
            "total_return": True,
            "series_kind": "equity",
            **provenance,
            "file_sha256": _sha256(benchmark_csv),
        },
    )
    _write_json(
        membership_metadata,
        {
            "artifact_type": "reviewed_pit_universe_membership",
            "schema_version": 1,
            "index_code": "000906",
            "point_in_time": True,
            "snapshot_mode": "point_in_time_history",
            "effective_date_column": "effective_date",
            "symbol_column": "symbol",
            "index_code_column": "index_code",
            "source_dataset": "CSI 800 historical constituents",
            **provenance,
            "file_sha256": _sha256(membership_csv),
        },
    )
    return {
        "benchmark_csv": benchmark_csv,
        "benchmark_metadata": benchmark_metadata,
        "membership_csv": membership_csv,
        "membership_metadata": membership_metadata,
    }


def _materialize(paths: dict[str, Path], output: Path):
    return materialize_prospective_execution_cache(
        packet_dir=paths["packet_dir"],
        registry_path=paths["registry"],
        quarantine_root=paths["quarantine"],
        source_qa_checklist=paths["source_qa_checklist"],
        source_qa_answers=paths["source_qa_answers"],
        source_qa_evidence_manifest=paths["source_qa_evidence_manifest"],
        calendar_csv=paths["calendar_csv"],
        calendar_metadata=paths["calendar_metadata"],
        benchmark_csv=paths["benchmark_csv"],
        benchmark_metadata=paths["benchmark_metadata"],
        membership_csv=paths["membership_csv"],
        membership_metadata=paths["membership_metadata"],
        minimum_members_per_snapshot=2,
        output_dir=output,
    )


def _admission(paths: dict[str, Path], artifact: Path | None = None):
    return build_prospective_trial_admission(
        packet_dir=paths["packet_dir"],
        registry_path=paths["registry"],
        benchmark_csv=paths["benchmark_csv"],
        benchmark_metadata=paths["benchmark_metadata"],
        membership_csv=paths["membership_csv"],
        membership_metadata=paths["membership_metadata"],
        minimum_members_per_snapshot=2,
        materialization_artifact=artifact,
    )


def _terminal(
    paths: dict[str, Path],
    materialization_output: Path,
    output: Path,
):
    return run_prospective_terminal_analysis(
        packet_dir=paths["packet_dir"],
        registry_path=paths["registry"],
        materialization_artifact=materialization_output / ARTIFACT_FILENAME,
        benchmark_csv=paths["benchmark_csv"],
        benchmark_metadata=paths["benchmark_metadata"],
        membership_csv=paths["membership_csv"],
        membership_metadata=paths["membership_metadata"],
        minimum_members_per_snapshot=2,
        output_dir=output,
    )


def _set_materialization_clock(monkeypatch, value: datetime) -> None:
    monkeypatch.setattr(
        "quantify.research.prospective_execution_cache_materialization._runtime_now",
        lambda: value,
    )
    monkeypatch.setattr(
        "quantify.data.exchange_calendar_preflight._runtime_now",
        lambda: value,
    )


def _expected_logical_fingerprint(paths: dict[str, Path]) -> str:
    rows = [tuple(row) for row in _development_bars().itertuples(index=False, name=None)]
    for retained in sorted((paths["quarantine"] / "sealed_inputs").glob("*.csv")):
        frame = pd.read_csv(retained, dtype={"symbol": str})
        rows.extend(tuple(row) for row in frame.itertuples(index=False, name=None))
    return logical_bar_fingerprint(sorted(rows, key=lambda row: (str(row[0]), str(row[1]))))


def _development_bars() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": symbol,
                "date": market_date,
                "open": close,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close + 0.1,
                "volume": 1000.0,
                "amount": (close + 0.1) * 1000.0,
            }
            for symbol, close in (("000001", 10.0), ("600001", 20.0))
            for market_date in ("2024-06-03", "2026-07-14")
        ]
    )


def _write_plan(path: Path) -> Path:
    _write_json(
        path,
        {
            "plan_id": "guard_v1_materialization_test",
            "candidate": "liquidity_neutral_momentum_guard_price_volume",
            "development_data": {"end": "2026-07-14", "independent_holdout": False},
            "hypothesis": "The frozen guard survives a fresh prospective holdout.",
            "required_data": ["reviewed source QA", "PIT CSI 800"],
            "required_tests": ["terminal holdout"],
            "stop_conditions": ["Stop on deterministic BLOCK."],
        },
    )
    return path


def _write_config(path: Path, cache: Path, *, end: str) -> Path:
    payload = {
        "research": {
            "start": "2024-06-03",
            "end": end,
            "in_sample_end": "2025-06-30",
            "out_sample_start": "2025-07-01",
            "initial_cash": 1_000_000.0,
            "rebalance": "monthly",
            "allow_demo_data": False,
        },
        "data": {"source": "akshare", "cache_path": str(cache), "adjust": "qfq"},
        "universe": {
            "mode": "all_a",
            "index_code": "000906",
            "include_st": False,
            "min_history_days": 1,
        },
        "strategy": {"name": "multi_factor", "n_holdings": 2, "max_weight": 0.5},
        "risk": {"max_drawdown_stop": 0.2},
        "broker": {
            "commission_rate": 0.00025,
            "min_commission": 5.0,
            "stamp_tax": 0.0005,
            "slippage_bps": 5,
            "price_limit_pct": 0.1,
            "lot_size": 100,
        },
        "output": {"results_dir": str(path.parent / "results")},
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _check_status(report, code: str) -> str:
    return next(item.status for item in report.checks if item.code == code)


def _check_verification_status(report, code: str) -> str:
    return next(item.status for item in report.checks if item.code == code)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
