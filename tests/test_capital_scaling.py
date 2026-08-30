from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from tests.statistical_evidence_fixtures import write_statistical_evidence_fixtures

from quantify.readiness import (
    build_capital_scaling_plan,
    write_approval_record,
    write_capital_scaling_plan,
)


def test_capital_scaling_blocks_missing_readiness_and_paper(tmp_path: Path) -> None:
    _write_json(tmp_path / "run_manifest.json", {"demo_data_used": False})

    plan = build_capital_scaling_plan(
        tmp_path,
        current_capital=100_000,
        proposed_capital=120_000,
    )

    assert plan.decision == "BLOCK"
    assert plan.max_allowed_capital == 100_000
    assert any("micro_live_readiness" in blocker for blocker in plan.blockers)


def test_capital_scaling_passes_small_increment_with_full_evidence(tmp_path: Path) -> None:
    _write_full_scaling_evidence(tmp_path, observed_days=45)

    plan = build_capital_scaling_plan(
        tmp_path,
        current_capital=100_000,
        proposed_capital=120_000,
        max_increment_pct=0.25,
    )
    out = write_capital_scaling_plan(plan, tmp_path)

    assert plan.decision == "PASS"
    assert plan.max_allowed_capital == 125_000
    assert (out / "capital_scaling_plan.json").exists()


def test_capital_scaling_blocks_oversized_jump(tmp_path: Path) -> None:
    _write_full_scaling_evidence(tmp_path, observed_days=45)

    plan = build_capital_scaling_plan(
        tmp_path,
        current_capital=100_000,
        proposed_capital=200_000,
        max_increment_pct=0.25,
    )

    assert plan.decision == "BLOCK"
    assert any("exceeds max allowed" in blocker for blocker in plan.blockers)


def test_capital_scaling_blocks_stale_approval_snapshot(tmp_path: Path) -> None:
    _write_full_scaling_evidence(tmp_path, observed_days=45)
    (tmp_path / "target_portfolio.csv").write_text(
        "symbol,risk_flags\nBBB,LOW_LIQUIDITY\n", encoding="utf-8"
    )

    plan = build_capital_scaling_plan(
        tmp_path,
        current_capital=100_000,
        proposed_capital=110_000,
    )

    assert plan.decision == "BLOCK"
    assert any("APPROVAL_SNAPSHOT_MISMATCH" in blocker for blocker in plan.blockers)


def test_capital_scaling_blocks_tampered_manual_material_snapshot(tmp_path: Path) -> None:
    _write_full_scaling_evidence(tmp_path, observed_days=45)
    risk_budget = json.loads((tmp_path / "risk_budget.json").read_text(encoding="utf-8"))
    risk_budget["single_day_loss_stop"] = 0.2
    (tmp_path / "risk_budget.json").write_text(json.dumps(risk_budget), encoding="utf-8")

    plan = build_capital_scaling_plan(
        tmp_path,
        current_capital=100_000,
        proposed_capital=110_000,
    )

    assert plan.decision == "BLOCK"
    assert any("APPROVAL_SNAPSHOT_MISMATCH" in blocker for blocker in plan.blockers)


def test_capital_scaling_blocks_invalid_approval_fields(tmp_path: Path) -> None:
    _write_full_scaling_evidence(tmp_path, observed_days=45)
    approval = json.loads((tmp_path / "approval_record.json").read_text(encoding="utf-8"))
    approval["approval_notes"] = ""
    (tmp_path / "approval_record.json").write_text(
        json.dumps(approval, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    plan = build_capital_scaling_plan(
        tmp_path,
        current_capital=100_000,
        proposed_capital=110_000,
    )

    assert plan.decision == "BLOCK"
    assert any("INVALID_APPROVAL" in blocker for blocker in plan.blockers)


def test_capital_scaling_blocks_run_manifest_without_source_qa_provenance(tmp_path: Path) -> None:
    _write_full_scaling_evidence(tmp_path, observed_days=45)
    _write_json(
        tmp_path / "run_manifest.json",
        {
            "demo_data_used": False,
            "in_sample_end": "2024-01-02",
            "out_sample_start": "2024-01-03",
            "data_version": {"data_source_qa_status": "PASS"},
        },
    )

    plan = build_capital_scaling_plan(
        tmp_path,
        current_capital=100_000,
        proposed_capital=110_000,
    )

    assert plan.decision == "BLOCK"
    assert any("RUN_MANIFEST:" in blocker for blocker in plan.blockers)


def test_capital_scaling_cli_writes_outputs(tmp_path: Path) -> None:
    _write_full_scaling_evidence(tmp_path, observed_days=45)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_capital_scaling_plan.py",
            "--report-dir",
            str(tmp_path),
            "--current-capital",
            "100000",
            "--proposed-capital",
            "120000",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((tmp_path / "capital_scaling_plan.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["decision"] == "PASS"


def _write_full_scaling_evidence(root: Path, *, observed_days: int) -> None:
    candidate = "price_volume_defensive"
    checklist = root / "data_source_qa.json"
    answers = root / "data_source_qa_answers.json"
    evidence_manifest = root / "source_qa_evidence_manifest.json"
    checklist.write_text('{"checklist":"unit-test"}', encoding="utf-8")
    answers.write_text('{"answers":"unit-test"}', encoding="utf-8")
    evidence_manifest.write_text('{"evidence":"unit-test"}', encoding="utf-8")
    _write_json(root / "capital_goal_status.json", {"decision": "PASS"})
    _write_json(root / "micro_live_readiness.json", {"decision": "PASS"})
    _write_json(root / "paper_stability.json", {"status": "PASS", "observed_days": observed_days})
    _write_json(
        root / "run_manifest.json",
        {
            "cache_path": "unit-test-cache.db",
            "demo_data_used": False,
            "in_sample_end": "2024-01-02",
            "out_sample_start": "2024-01-03",
            "data_version": {
                "data_source": "local_csv",
                "cache_logical_bar_fingerprint": "unit-test-logical-bars",
                "cache_logical_bar_fingerprint_algorithm": "sha256:quantify.logical-bars.v1",
                "cache_latest_import_batch_id": "unit-test-import-batch",
                "cache_lineage_schema_version": "1",
                "csv_dataset_fingerprint": "unit-test-csv-fingerprint",
                "data_source_qa_status": "PASS",
                "data_source_csv_qa_status": "PASS",
                "data_source_qa_checklist_path": str(checklist),
                "data_source_qa_checklist_sha256": _sha256(checklist),
                "data_source_qa_answers_path": str(answers),
                "data_source_qa_answers_sha256": _sha256(answers),
                "data_source_qa_evidence_manifest_path": str(evidence_manifest),
                "data_source_qa_evidence_manifest_sha256": _sha256(evidence_manifest),
            },
        },
    )
    _write_json(
        root / "promotion_metadata_check.json",
        {
            "status": "PASS",
            "cache_path": "unit-test-cache.db",
            "metadata": {
                "cache_logical_bar_fingerprint": "unit-test-logical-bars",
                "cache_latest_import_batch_id": "unit-test-import-batch",
            },
            "cache_stats": {
                "bar_count": 100,
                "logical_bar_fingerprint_actual": "unit-test-logical-bars",
                "latest_import_batch_id": "unit-test-import-batch",
                "provenance_current_lineage_count": 100,
                "provenance_mismatched_current_lineage_count": 0,
            },
            "blockers": [],
        },
    )
    _write_json(root / "real_data_bootstrap.json", {"decision": "PASS"})
    _write_json(root / "real_data_gate.json", {"decision": "PASS"})
    _write_json(root / "data_coverage.json", {"status": "PASS"})
    _write_json(root / "market_context_readiness.json", {"decision": "PASS"})
    _write_json(root / "llm_review.json", {"decision": "PASS"})
    _write_json(root / "data_audit.json", {"status": "PASS"})
    _write_json(root / "robustness_report.json", {"status": "PASS"})
    _write_json(root / "walk_forward_report.json", {"status": "PASS"})
    _write_json(
        root / "candidate_walk_forward_report.json",
        {
            "status": "PASS",
            "best_candidate": candidate,
            "summaries": [{"candidate": candidate, "status": "PASS"}],
        },
    )
    _write_json(
        root / "candidate_regime_validation_report.json",
        {
            "status": "PASS",
            "best_candidate": candidate,
            "summaries": [{"candidate": candidate, "status": "PASS"}],
        },
    )
    _write_json(
        root / "candidate_selection.json",
        {
            "status": "PASS",
            "selected_candidate": candidate,
            "results": [{"name": candidate, "score": {"decision": "PASS"}}],
        },
    )
    _write_json(
        root / "candidate_experiment_completion.json",
        {
            "decision": "PASS",
            "selected_candidate": candidate,
            "run_id": "unit-test-run",
            "launch_decision": "PASS",
            "artifacts": [{"name": "candidate_selection.json", "status": "PASS"}],
        },
    )
    _write_json(
        root / "paper_state.json",
        {"observed_days": observed_days, "broker_connection": "none", "candidate": candidate},
    )
    _write_json(root / "paper_daily_review.json", {"status": "PASS"})
    (root / "target_portfolio.csv").write_text("symbol,risk_flags\nAAA,\n", encoding="utf-8")
    _write_json(root / "target_portfolio.json", {"candidate": candidate, "rows": []})
    write_statistical_evidence_fixtures(root, candidate=candidate)
    write_approval_record(root, approved_by="tester", approval_notes="capital scaling test")


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
