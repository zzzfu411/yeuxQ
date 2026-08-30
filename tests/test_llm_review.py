from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock, patch

import pandas as pd

from tests.selection_safe_fixtures import (
    selection_safe_robustness_payload as complete_selection_safe_robustness_payload,
)
from tests.statistical_evidence_fixtures import write_statistical_evidence_fixtures

from quantify.llm import LLMClient, LLMClientConfig, LLMReviewPromptBuilder, review_report
from quantify.research.walk_forward_protocol import (
    CANDIDATE_WALK_FORWARD_ARTIFACT,
    SELECTION_PROTOCOL,
    WALK_FORWARD_ARTIFACT,
)


def test_llm_review_blocks_demo_data_for_live(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {"demo_data_used": True},
        },
    )

    result = review_report(tmp_path, intended_stage="live")

    assert result.decision == "BLOCK"
    assert any(finding.code == "DEMO_DATA_FOR_LIVE" for finding in result.findings)


def test_llm_review_blocks_live_when_drawdown_is_too_high(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.30,
            "max_drawdown": 0.31,
            "sharpe_ratio": 1.1,
            "n_bars": 252,
            "assumptions": {"demo_data_used": False},
        },
    )

    result = review_report(tmp_path, intended_stage="micro_live")

    assert result.decision == "BLOCK"
    assert any(finding.code == "DRAWDOWN_BLOCK" for finding in result.findings)


def test_llm_review_blocks_demo_data_for_micro_live_ready(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {"demo_data_used": True},
        },
    )

    result = review_report(tmp_path, intended_stage="micro_live_ready")

    assert result.decision == "BLOCK"
    assert "connect_live_broker" in result.prohibited_actions


def test_llm_review_blocks_when_data_audit_blocks(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {
                "demo_data_used": False,
                "in_sample_end": "2020-12-31",
                "out_sample_start": "2021-01-01",
            },
        },
    )
    _write_json(
        tmp_path / "data_audit.json",
        {"status": "BLOCK", "findings": [{"severity": "BLOCK", "code": "MISSING_BARS"}]},
    )

    result = review_report(tmp_path, intended_stage="paper")

    assert result.decision == "BLOCK"
    assert any(finding.code == "DATA_AUDIT_BLOCK" for finding in result.findings)


def test_llm_review_surfaces_non_pit_universe_as_research_only(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {
                "demo_data_used": False,
                "in_sample_end": "2020-12-31",
                "out_sample_start": "2021-01-01",
            },
        },
    )
    _write_json(
        tmp_path / "data_audit.json",
        {
            "status": "WATCH",
            "findings": [
                {
                    "severity": "WATCH",
                    "code": "UNIVERSE_NOT_POINT_IN_TIME",
                    "message": "Current snapshot may contain survivorship bias.",
                    "evidence": {"universe_snapshot_mode": "current_spot_snapshot_research_only"},
                }
            ],
        },
    )

    paper = review_report(tmp_path, intended_stage="paper")
    ready = review_report(tmp_path, intended_stage="micro_live_ready")

    paper_finding = next(
        finding for finding in paper.findings if finding.code == "UNIVERSE_NOT_POINT_IN_TIME"
    )
    ready_finding = next(
        finding for finding in ready.findings if finding.code == "UNIVERSE_NOT_POINT_IN_TIME"
    )
    assert paper_finding.severity == "WATCH"
    assert ready_finding.severity == "BLOCK"
    assert (
        "UNIVERSE_NOT_POINT_IN_TIME"
        in next(
            finding for finding in paper.findings if finding.code == "DATA_AUDIT_WATCH"
        ).evidence["finding_codes"]
    )
    assert any("Point-in-time universe membership" in item for item in paper.missing_evidence)
    assert any("survivorship bias" in item for item in paper.next_experiments)


def test_llm_review_micro_live_ready_blocks_missing_audit_and_manifest(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {
                "demo_data_used": False,
                "in_sample_end": "2020-12-31",
                "out_sample_start": "2021-01-01",
            },
        },
        write_evidence=False,
    )

    result = review_report(tmp_path, intended_stage="micro_live_ready")

    assert result.decision == "BLOCK"
    assert any(finding.code == "MISSING_DATA_AUDIT" for finding in result.findings)
    assert any(finding.code == "MISSING_RUN_MANIFEST" for finding in result.findings)


def test_llm_review_warns_when_paper_manifest_has_no_data_version(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {
                "demo_data_used": False,
                "in_sample_end": "2020-12-31",
                "out_sample_start": "2021-01-01",
            },
        },
    )
    _write_json(
        tmp_path / "run_manifest.json",
        {"demo_data_used": False, "latest_bar_date": "2021-12-31", "data_version": {}},
    )

    result = review_report(tmp_path, intended_stage="paper")

    finding = next(item for item in result.findings if item.code == "MISSING_DATA_VERSION")
    assert finding.severity == "WATCH"
    assert any(item.startswith("Cache import metadata") for item in result.missing_evidence)
    assert "paper_trading_without_broker_credentials" in result.approved_actions
    assert "paper_trading" not in result.approved_actions


def test_llm_review_blocks_micro_live_ready_without_data_version(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {
                "demo_data_used": False,
                "in_sample_end": "2020-12-31",
                "out_sample_start": "2021-01-01",
            },
        },
    )
    _write_json(
        tmp_path / "run_manifest.json",
        {"demo_data_used": False, "latest_bar_date": "2021-12-31", "data_version": {}},
    )

    result = review_report(tmp_path, intended_stage="micro_live_ready")

    assert result.decision == "BLOCK"
    finding = next(item for item in result.findings if item.code == "MISSING_DATA_VERSION")
    assert finding.severity == "BLOCK"


def test_llm_review_warns_when_acquisition_metadata_lacks_source_qa(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {
                "demo_data_used": False,
                "in_sample_end": "2020-12-31",
                "out_sample_start": "2021-01-01",
            },
        },
    )
    _write_json(
        tmp_path / "run_manifest.json",
        {
            "demo_data_used": False,
            "data_version": {
                "data_source": "akshare",
                "data_source_qa_status": "NOT_EVALUATED",
                "data_source_csv_qa_status": "NOT_EVALUATED",
            },
        },
    )

    result = review_report(tmp_path, intended_stage="paper")

    finding = next(item for item in result.findings if item.code == "INCOMPLETE_DATA_PROVENANCE")
    assert finding.severity == "WATCH"
    assert set(finding.evidence["gaps"]) == {
        "cache_logical_bar_fingerprint",
        "cache_logical_bar_fingerprint_algorithm",
        "cache_latest_import_batch_id",
        "cache_lineage_schema_version",
        "data_source_qa_status",
    }


def test_llm_review_blocks_manifest_demo_data_for_micro_live_ready(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {
                "demo_data_used": False,
                "in_sample_end": "2020-12-31",
                "out_sample_start": "2021-01-01",
            },
        },
    )
    _write_json(tmp_path / "run_manifest.json", {"demo_data_used": True})

    result = review_report(tmp_path, intended_stage="micro_live_ready")

    assert result.decision == "BLOCK"
    demo = next(finding for finding in result.findings if finding.code == "DEMO_DATA_FOR_LIVE")
    assert demo.evidence["manifest_demo_data_used"] is True


def test_llm_review_warns_on_execution_quality(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.09,
            "max_drawdown": 0.07,
            "sharpe_ratio": 0.9,
            "n_bars": 252,
            "assumptions": {"demo_data_used": False},
        },
        order_status=["filled", "rejected", "filled", "filled"],
    )

    result = review_report(tmp_path, intended_stage="paper")

    assert result.decision == "WATCH"
    assert any(finding.code == "ORDER_REJECT_WATCH" for finding in result.findings)


def test_llm_review_blocks_demo_symbols_hidden_by_false_summary_flag(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {
                "demo_data_used": False,
                "in_sample_end": "2020-12-31",
                "out_sample_start": "2021-01-01",
            },
        },
    )
    orders = pd.read_csv(tmp_path / "orders.csv")
    orders["symbol"] = ["DEMO001"] * len(orders)
    orders.to_csv(tmp_path / "orders.csv", index=False)

    result = review_report(tmp_path, intended_stage="paper")

    assert result.decision == "BLOCK"
    assert any(finding.code == "DEMO_SYMBOLS_IN_ARTIFACTS" for finding in result.findings)


def test_llm_review_warns_when_paper_stage_lacks_out_of_sample_split(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {"demo_data_used": False},
        },
    )

    result = review_report(tmp_path, intended_stage="paper")

    assert result.decision == "WATCH"
    assert any(finding.code == "MISSING_OUT_OF_SAMPLE_SPLIT" for finding in result.findings)
    assert result.missing_evidence
    assert result.next_experiments


def test_llm_review_requires_walk_forward_results_for_recorded_split(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {
                "demo_data_used": False,
                "start": "2020-01-01",
                "in_sample_end": "2020-12-31",
                "out_sample_start": "2021-01-01",
                "end": "2021-12-31",
            },
        },
    )

    result = review_report(tmp_path, intended_stage="paper")

    assert result.decision == "WATCH"
    assert any(finding.code == "MISSING_OUT_OF_SAMPLE_RESULTS" for finding in result.findings)


def test_llm_review_rejects_overlapping_sample_dates(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {
                "demo_data_used": False,
                "start": "2020-01-01",
                "in_sample_end": "2021-06-30",
                "out_sample_start": "2021-01-01",
                "end": "2021-12-31",
            },
        },
    )

    result = review_report(tmp_path, intended_stage="paper")

    assert result.decision == "WATCH"
    assert any(finding.code == "INVALID_OUT_OF_SAMPLE_SPLIT" for finding in result.findings)


def test_llm_review_blocks_legacy_walk_forward_missing_v2_fields(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {
                "demo_data_used": False,
                "in_sample_end": "2020-12-31",
                "out_sample_start": "2021-01-01",
            },
        },
    )
    _write_json(
        tmp_path / "walk_forward_report.json",
        {
            "status": "PASS",
            "window_count": 1,
            "windows": [{"start": "2021-01-01", "end": "2021-03-31", "status": "PASS"}],
        },
    )

    result = review_report(tmp_path, intended_stage="paper")
    ready = review_report(tmp_path, intended_stage="micro_live_ready")

    finding = next(item for item in result.findings if item.code == "WALK_FORWARD_SELECTION_UNSAFE")
    ready_finding = next(
        item for item in ready.findings if item.code == "WALK_FORWARD_SELECTION_UNSAFE"
    )
    assert finding.severity == "BLOCK"
    assert ready_finding.severity == "BLOCK"
    assert "artifact_type must be walk_forward_report." in finding.evidence["reasons"]
    assert "schema_version must be 2." in finding.evidence["reasons"]
    markdown = result.to_markdown()
    assert "walk_forward_report_selection_safety_status: `UNSAFE`" in markdown
    assert "artifact_type must be walk_forward_report." in markdown


def test_llm_review_rejects_bare_true_candidate_as_out_of_sample_fallback(
    tmp_path: Path,
) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {
                "demo_data_used": False,
                "in_sample_end": "2020-12-31",
                "out_sample_start": "2021-01-01",
            },
        },
    )
    _write_json(
        tmp_path / "candidate_walk_forward_report.json",
        {
            "status": "PASS",
            "selection_safe": True,
            "window_count": 1,
            "windows": [{"start": "2021-01-01", "end": "2021-03-31", "status": "PASS"}],
        },
    )

    result = review_report(tmp_path, intended_stage="paper")
    findings = {finding.code: finding for finding in result.findings}

    unsafe = findings["CANDIDATE_WALK_FORWARD_SELECTION_UNSAFE"]
    assert unsafe.severity == "BLOCK"
    assert "artifact_type must be candidate_walk_forward_report." in unsafe.evidence["reasons"]
    assert findings["MISSING_OUT_OF_SAMPLE_RESULTS"].evidence["selection_safety_status"] == "UNSAFE"
    assert findings["MISSING_OUT_OF_SAMPLE_RESULTS"].evidence["eligible_window_count"] == 0


def test_llm_review_watches_malformed_protocol_at_research_stage(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {"demo_data_used": False},
        },
    )
    payload = _selection_safe_walk_forward_payload(status="PASS")
    payload["selection_protocol"] = "quantify.walk-forward-selection.v1"
    _write_json(tmp_path / "walk_forward_report.json", payload)

    result = review_report(tmp_path, intended_stage="research")

    finding = next(item for item in result.findings if item.code == "WALK_FORWARD_SELECTION_UNSAFE")
    assert finding.severity == "WATCH"
    assert f"selection_protocol must be {SELECTION_PROTOCOL}." in finding.evidence["reasons"]


def test_llm_review_accepts_complete_v2_selection_evidence(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {
                "demo_data_used": False,
                "in_sample_end": "2020-12-31",
                "out_sample_start": "2021-01-01",
            },
        },
    )
    _write_json(
        tmp_path / "walk_forward_report.json",
        _selection_safe_walk_forward_payload(status="PASS"),
    )
    _write_candidate_walk_forward(
        tmp_path,
        positive_return_ratio=1.0,
        worst_total_return=0.01,
        worst_max_drawdown=0.04,
    )
    _write_complete_statistical_evidence(tmp_path)

    result = review_report(tmp_path, intended_stage="paper")
    prompt = json.loads(LLMReviewPromptBuilder().build(result).user)
    finding_codes = {finding.code for finding in result.findings}

    assert result.decision == "PASS"
    assert "WALK_FORWARD_SELECTION_UNSAFE" not in finding_codes
    assert "CANDIDATE_WALK_FORWARD_SELECTION_UNSAFE" not in finding_codes
    assert prompt["selection_safety"]["walk_forward_report"]["status"] == "PASS"
    assert prompt["selection_safety"]["candidate_walk_forward_report"]["status"] == "PASS"
    assert prompt["selection_safety"]["walk_forward_report"]["reasons"] == []
    assert prompt["selection_safety"]["candidate_walk_forward_report"]["reasons"] == []
    assert "may not" in prompt["hard_rule"]
    assert "override any selection-safety status" in prompt["hard_rule"]


def test_llm_review_prompt_keeps_gate_authoritative(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {
                "demo_data_used": False,
                "in_sample_end": "2020-12-31",
                "out_sample_start": "2021-01-01",
            },
        },
    )
    _write_json(
        tmp_path / "walk_forward_report.json",
        _selection_safe_walk_forward_payload(status="PASS"),
    )
    _write_complete_statistical_evidence(tmp_path)
    result = review_report(tmp_path, intended_stage="paper")

    prompt = LLMReviewPromptBuilder().build(result)

    assert "deterministic gate decision is authoritative" in prompt.user
    assert "cannot upgrade the deterministic gate" in prompt.user
    assert "paper_stage_constraints" in prompt.user
    assert result.decision == "PASS"


def test_llm_review_research_missing_statistical_evidence_is_advisory_only(
    tmp_path: Path,
) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {"demo_data_used": False},
        },
    )

    result = review_report(tmp_path, intended_stage="research")
    finding_codes = {finding.code for finding in result.findings}

    assert result.decision == "PASS"
    assert not any(code.startswith("MISSING_BENCHMARK") for code in finding_codes)
    assert not any(code.startswith("MISSING_MULTIPLE_TESTING") for code in finding_codes)
    assert not any(code.startswith("MISSING_TRIAL_REGISTRY") for code in finding_codes)
    assert any("benchmark_report.json" in item for item in result.missing_evidence)
    assert any("multiple_testing_report.json" in item for item in result.missing_evidence)
    assert any("trial_registry_review.json" in item for item in result.missing_evidence)
    assert any("total-return benchmark" in item for item in result.next_experiments)
    assert any("DSR and CSCV/PBO" in item for item in result.next_experiments)
    assert any("Preregister" in item for item in result.next_experiments)


def test_llm_review_missing_statistical_evidence_is_stage_gated(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {
                "demo_data_used": False,
                "in_sample_end": "2020-12-31",
                "out_sample_start": "2021-01-01",
            },
        },
    )
    _write_json(
        tmp_path / "walk_forward_report.json",
        _selection_safe_walk_forward_payload(status="PASS"),
    )

    paper = review_report(tmp_path, intended_stage="paper")
    ready = review_report(tmp_path, intended_stage="micro_live_ready")
    paper_findings = {finding.code: finding for finding in paper.findings}
    ready_findings = {finding.code: finding for finding in ready.findings}

    assert paper.decision == "WATCH"
    assert paper_findings["MISSING_BENCHMARK_EVIDENCE"].severity == "WATCH"
    assert paper_findings["MISSING_MULTIPLE_TESTING_EVIDENCE"].severity == "WATCH"
    assert paper_findings["MISSING_TRIAL_REGISTRY_EVIDENCE"].severity == "WATCH"
    assert ready.decision == "BLOCK"
    assert ready_findings["MISSING_BENCHMARK_EVIDENCE"].severity == "BLOCK"
    assert ready_findings["MISSING_MULTIPLE_TESTING_EVIDENCE"].severity == "BLOCK"
    assert ready_findings["MISSING_TRIAL_REGISTRY_EVIDENCE"].severity == "BLOCK"


def test_llm_review_blocks_tampered_benchmark_and_candidate_mismatch(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {"demo_data_used": False},
        },
    )
    _write_complete_statistical_evidence(tmp_path)
    benchmark = json.loads((tmp_path / "benchmark_report.json").read_text(encoding="utf-8"))
    benchmark["identity"]["symbol"] = "000300"
    _write_json(tmp_path / "benchmark_report.json", benchmark)
    multiple_testing = json.loads(
        (tmp_path / "multiple_testing_report.json").read_text(encoding="utf-8")
    )
    multiple_testing["parameters"]["selected_candidate"] = "wrong_candidate"
    _write_json(tmp_path / "multiple_testing_report.json", multiple_testing)

    result = review_report(tmp_path, intended_stage="research")
    findings = {finding.code: finding for finding in result.findings}

    assert result.decision == "BLOCK"
    assert findings["INVALID_BENCHMARK_EVIDENCE_CONTRACT"].severity == "BLOCK"
    assert any(
        "run manifest index_code" in reason
        for reason in findings["INVALID_BENCHMARK_EVIDENCE_CONTRACT"].evidence["reasons"]
    )
    assert findings["INVALID_MULTIPLE_TESTING_EVIDENCE_CONTRACT"].severity == "BLOCK"
    assert any(
        "deterministic selected candidate" in reason
        for reason in findings["INVALID_MULTIPLE_TESTING_EVIDENCE_CONTRACT"].evidence["reasons"]
    )
    assert findings["INVALID_TRIAL_REGISTRY_EVIDENCE_CONTRACT"].severity == "BLOCK"


def test_llm_review_statistical_pass_and_watch_cannot_upgrade_gate(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.30,
            "max_drawdown": 0.31,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {"demo_data_used": False},
        },
    )
    _write_complete_statistical_evidence(tmp_path)
    passing = review_report(tmp_path, intended_stage="research")
    passing_prompt = json.loads(LLMReviewPromptBuilder().build(passing).user)

    assert passing.decision == "BLOCK"
    assert all(
        evidence["contract_status"] == "PASS"
        for evidence in passing_prompt["statistical_evidence"].values()
    )
    assert passing.to_dict()["snapshot"]["benchmark_report"]["status"] == "PASS"
    assert passing.to_dict()["snapshot"]["multiple_testing_report"]["status"] == "PASS"
    assert passing.to_dict()["snapshot"]["trial_registry_review"]["status"] == "PASS"
    assert "benchmark_report_contract_valid: `True`" in passing.to_markdown()

    multiple_testing = json.loads(
        (tmp_path / "multiple_testing_report.json").read_text(encoding="utf-8")
    )
    multiple_testing["status"] = "WATCH"
    multiple_testing["diagnostics"]["deflated_sharpe_ratio"]["status"] = "WATCH"
    _write_json(tmp_path / "multiple_testing_report.json", multiple_testing)
    (tmp_path / "trial_registry_review.json").unlink()

    watching = review_report(tmp_path, intended_stage="research")
    watching_findings = {finding.code: finding for finding in watching.findings}
    paper = review_report(tmp_path, intended_stage="paper")
    paper_findings = {finding.code: finding for finding in paper.findings}
    ready = review_report(tmp_path, intended_stage="micro_live_ready")
    ready_findings = {finding.code: finding for finding in ready.findings}

    assert watching.decision == "BLOCK"
    assert watching_findings["MULTIPLE_TESTING_EVIDENCE_WATCH"].severity == "WATCH"
    assert paper_findings["MULTIPLE_TESTING_EVIDENCE_WATCH"].severity == "WATCH"
    assert ready_findings["MULTIPLE_TESTING_EVIDENCE_WATCH"].severity == "BLOCK"


def test_llm_review_integrates_general_watch_artifacts(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {
                "demo_data_used": False,
                "in_sample_end": "2020-12-31",
                "out_sample_start": "2021-01-01",
            },
        },
    )
    _write_json(
        tmp_path / "robustness_report.json",
        _selection_safe_robustness_payload(status="WATCH"),
    )
    _write_json(
        tmp_path / "walk_forward_report.json",
        _selection_safe_walk_forward_payload(status="WATCH"),
    )

    result = review_report(tmp_path, intended_stage="paper")

    findings = {finding.code: finding for finding in result.findings}
    assert result.decision == "WATCH"
    assert findings["ROBUSTNESS_WATCH"].severity == "WATCH"
    assert findings["WALK_FORWARD_WATCH"].severity == "WATCH"
    assert "MISSING_OUT_OF_SAMPLE_RESULTS" not in findings
    assert result.snapshot.robustness_report["status"] == "WATCH"
    assert result.snapshot.walk_forward_report["status"] == "WATCH"
    assert result.to_dict()["snapshot"]["robustness_report"]["status"] == "WATCH"
    assert not any("Parameter perturbation" in item for item in result.missing_evidence)
    assert not any("out-of-sample review" in item for item in result.next_experiments)
    assert not any("higher-cost stress test" in item for item in result.next_experiments)
    assert not any("Perturb n_holdings" in item for item in result.next_experiments)


def test_llm_review_does_not_downgrade_general_artifact_blocks(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {
                "demo_data_used": False,
                "in_sample_end": "2020-12-31",
                "out_sample_start": "2021-01-01",
            },
        },
    )
    _write_json(
        tmp_path / "robustness_report.json",
        {"status": "BLOCK", "scenarios": [{"name": "high_cost", "status": "BLOCK"}]},
    )
    _write_json(
        tmp_path / "walk_forward_report.json",
        _selection_safe_walk_forward_payload(status="BLOCK"),
    )

    result = review_report(tmp_path, intended_stage="paper")

    findings = {finding.code: finding for finding in result.findings}
    assert result.decision == "BLOCK"
    assert findings["ROBUSTNESS_BLOCK"].severity == "BLOCK"
    assert findings["WALK_FORWARD_BLOCK"].severity == "BLOCK"


def test_llm_client_missing_api_key_returns_advisory_error(tmp_path: Path) -> None:
    prompt = LLMReviewPromptBuilder().build(_passing_result(tmp_path))
    client = LLMClient(LLMClientConfig(api_key=None, model="test-model"))

    narrative = client.review(prompt)

    assert not narrative.ok
    assert "OPENAI_API_KEY" in narrative.error


def test_llm_client_posts_openai_compatible_request_body(tmp_path: Path) -> None:
    prompt = LLMReviewPromptBuilder().build(_passing_result(tmp_path))
    client = LLMClient(
        LLMClientConfig(
            base_url="https://example.test/v1",
            api_key="sk-test",
            model="test-model",
            timeout_seconds=3,
        )
    )
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=None)
    response.read.return_value = b'{"choices":[{"message":{"content":"advisory review text"}}]}'

    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        narrative = client.review(prompt)

    request = urlopen.call_args.args[0]
    body = json.loads(request.data.decode("utf-8"))
    assert narrative.ok
    assert narrative.content == "advisory review text"
    assert request.full_url == "https://example.test/v1/chat/completions"
    assert body["model"] == "test-model"
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["role"] == "user"


def test_llm_client_model_override_wins_over_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    monkeypatch.setenv("OPENAI_MODEL", "env-model")

    config = LLMClientConfig.from_env(model="cli-model")

    assert config.model == "cli-model"
    assert config.api_key == "sk-env"


def test_cli_call_llm_without_key_writes_narrative_error(tmp_path: Path, monkeypatch) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {
                "demo_data_used": False,
                "in_sample_end": "2020-12-31",
                "out_sample_start": "2021-01-01",
            },
        },
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_llm_review.py",
            "--report-dir",
            str(tmp_path),
            "--stage",
            "paper",
            "--call-llm",
            "--model",
            "cli-model",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    narrative = (tmp_path / "llm_narrative.md").read_text(encoding="utf-8")
    narrative_json = json.loads((tmp_path / "llm_narrative.json").read_text(encoding="utf-8"))
    assert "OPENAI_API_KEY" in narrative
    assert narrative_json["model"] == "cli-model"


def test_llm_review_candidate_experiment_dir_without_summary_blocks_missing_artifacts(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "candidate_walk_forward_report.json",
        {
            "status": "PASS",
            "best_candidate": "price_volume_defensive",
            "window_count": 3,
            "summaries": [
                {
                    "candidate": "price_volume_defensive",
                    "avg_total_return": 0.06,
                    "avg_max_drawdown": 0.04,
                    "avg_sharpe_ratio": 0.9,
                }
            ],
        },
    )

    result = review_report(tmp_path, intended_stage="paper")

    assert result.decision == "BLOCK"
    assert result.snapshot.assumptions["review_mode"] == "candidate_experiment"
    assert any(finding.code == "CANDIDATE_ARTIFACT_MISSING" for finding in result.findings)


def test_llm_review_cli_writes_candidate_experiment_review_without_summary(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "candidate_experiment_evidence.json", {"status": "PASS", "copied_artifacts": []}
    )
    _write_json(
        tmp_path / "candidate_walk_forward_report.json",
        {
            "status": "PASS",
            "best_candidate": "price_volume_defensive",
            "window_count": 3,
            "summaries": [
                {
                    "candidate": "price_volume_defensive",
                    "avg_total_return": 0.06,
                    "avg_max_drawdown": 0.04,
                    "avg_sharpe_ratio": 0.9,
                }
            ],
        },
    )
    _write_json(tmp_path / "candidate_factor_diagnostics.json", {"status": "PASS"})
    _write_json(tmp_path / "candidate_regime_validation_report.json", {"status": "PASS"})
    _write_json(
        tmp_path / "candidate_selection.json",
        {"status": "PASS", "best_candidate": "price_volume_defensive"},
    )

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_llm_review.py",
            "--report-dir",
            str(tmp_path),
            "--stage",
            "paper",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((tmp_path / "llm_review.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["snapshot"]["summary"]["assumptions"]["review_mode"] == "candidate_experiment"
    assert (tmp_path / "llm_prompt.md").exists()


def test_llm_review_includes_candidate_walk_forward_tail_metrics_in_prompt(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "candidate_experiment_evidence.json", {"status": "PASS", "copied_artifacts": []}
    )
    _write_candidate_walk_forward(
        tmp_path,
        positive_return_ratio=1.0,
        worst_total_return=0.01,
        worst_max_drawdown=0.04,
    )
    _write_json(tmp_path / "candidate_factor_diagnostics.json", {"status": "PASS"})
    _write_json(tmp_path / "candidate_regime_validation_report.json", {"status": "PASS"})
    _write_json(
        tmp_path / "candidate_selection.json",
        {"status": "PASS", "best_candidate": "price_volume_defensive"},
    )

    result = review_report(tmp_path, intended_stage="paper")
    prompt = LLMReviewPromptBuilder().build(result)
    markdown = result.to_markdown()

    summary = result.snapshot.summary
    assert summary["candidate_walk_forward_positive_return_ratio"] == 1.0
    assert summary["candidate_walk_forward_worst_total_return"] == 0.01
    assert "candidate_walk_forward_positive_return_ratio" in prompt.user
    assert "candidate_walk_forward_worst_total_return" in prompt.user
    assert "candidate_walk_forward_worst_max_drawdown" in markdown


def test_llm_review_warns_on_low_candidate_walk_forward_positive_ratio(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "candidate_experiment_evidence.json", {"status": "PASS", "copied_artifacts": []}
    )
    _write_candidate_walk_forward(
        tmp_path,
        status="PASS",
        positive_return_ratio=0.50,
        worst_total_return=0.01,
        worst_max_drawdown=0.04,
    )
    _write_json(tmp_path / "candidate_factor_diagnostics.json", {"status": "PASS"})
    _write_json(tmp_path / "candidate_regime_validation_report.json", {"status": "PASS"})
    _write_json(
        tmp_path / "candidate_selection.json",
        {"status": "PASS", "best_candidate": "price_volume_defensive"},
    )

    result = review_report(tmp_path, intended_stage="paper")

    assert result.decision == "WATCH"
    assert any(
        finding.code == "LOW_CANDIDATE_WALK_FORWARD_POSITIVE_RATIO" for finding in result.findings
    )
    assert any("forward window" in item for item in result.next_experiments)


def test_llm_review_blocks_candidate_walk_forward_tail_loss(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "candidate_experiment_evidence.json", {"status": "PASS", "copied_artifacts": []}
    )
    _write_candidate_walk_forward(
        tmp_path,
        status="PASS",
        positive_return_ratio=0.67,
        worst_total_return=-0.12,
        worst_max_drawdown=0.08,
    )
    _write_json(tmp_path / "candidate_factor_diagnostics.json", {"status": "PASS"})
    _write_json(tmp_path / "candidate_regime_validation_report.json", {"status": "PASS"})
    _write_json(
        tmp_path / "candidate_selection.json",
        {"status": "PASS", "best_candidate": "price_volume_defensive"},
    )

    result = review_report(tmp_path, intended_stage="paper")

    assert result.decision == "BLOCK"
    assert any(finding.code == "CANDIDATE_WALK_FORWARD_TAIL_LOSS" for finding in result.findings)
    assert any("tail-window post-mortem" in item for item in result.next_experiments)


def test_llm_review_flags_missing_candidate_walk_forward_tail_metrics(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "candidate_experiment_evidence.json", {"status": "PASS", "copied_artifacts": []}
    )
    payload = _selection_safe_walk_forward_payload(
        status="PASS",
        candidate=True,
        window_count=3,
    )
    payload["summaries"] = [
        {
            "candidate": "price_volume_defensive",
            "status": "PASS",
            "window_count": 3,
            "avg_total_return": 0.06,
            "avg_max_drawdown": 0.04,
            "avg_sharpe_ratio": 0.9,
        }
    ]
    _write_json(tmp_path / "candidate_walk_forward_report.json", payload)
    _write_json(tmp_path / "candidate_factor_diagnostics.json", {"status": "PASS"})
    _write_json(tmp_path / "candidate_regime_validation_report.json", {"status": "PASS"})
    _write_json(
        tmp_path / "candidate_selection.json",
        {"status": "PASS", "best_candidate": "price_volume_defensive"},
    )

    result = review_report(tmp_path, intended_stage="paper")

    assert result.decision == "WATCH"
    assert any(
        finding.code == "CANDIDATE_WALK_FORWARD_METRICS_MISSING" for finding in result.findings
    )
    assert any("tail-risk metrics" in item for item in result.missing_evidence)


def _passing_result(report_dir: Path):
    _write_report(
        report_dir,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {
                "demo_data_used": False,
                "in_sample_end": "2020-12-31",
                "out_sample_start": "2021-01-01",
            },
        },
    )
    return review_report(report_dir, intended_stage="paper")


def _write_report(
    report_dir: Path,
    summary: dict[str, object],
    order_status: list[str] | None = None,
    write_evidence: bool = True,
) -> None:
    (report_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False),
        encoding="utf-8",
    )
    if write_evidence:
        assumptions = summary.get("assumptions", {})
        assumptions = assumptions if isinstance(assumptions, dict) else {}
        demo = bool(assumptions.get("demo_data_used", False))
        _write_json(report_dir / "data_audit.json", {"status": "PASS", "demo_data_used": demo})
        _write_json(
            report_dir / "run_manifest.json",
            {
                "demo_data_used": demo,
                "latest_bar_date": "2021-12-31",
                "data_version": {
                    "data_source": "local_csv",
                    "cache_logical_bar_fingerprint": "unit-test-logical-fingerprint",
                    "cache_logical_bar_fingerprint_algorithm": "sha256:quantify.logical-bars.v1",
                    "cache_latest_import_batch_id": "unit-test-import-batch",
                    "cache_lineage_schema_version": "1",
                    "csv_dataset_fingerprint": "unit-test-fingerprint",
                    "data_source_qa_status": "PASS",
                    "data_source_csv_qa_status": "PASS",
                },
            },
        )
    pd.DataFrame(
        {
            "status": order_status or ["filled", "filled"],
            "symbol": ["AAA"] * len(order_status or ["filled", "filled"]),
        }
    ).to_csv(report_dir / "orders.csv", index=False)
    pd.DataFrame({"turnover_pct": [0.1, 0.2, 0.15]}).to_csv(
        report_dir / "turnover.csv",
        index=False,
    )
    pd.DataFrame({"rank_ic": [0.05, 0.02, 0.01]}).to_csv(
        report_dir / "factor_ic.csv",
        index=False,
    )


def _selection_safe_walk_forward_payload(
    *,
    status: str,
    candidate: bool = False,
    window_count: int = 1,
) -> dict[str, object]:
    periods = [
        {
            "train": ("2020-12-21", "2020-12-22"),
            "purge": ("2020-12-23", "2020-12-23"),
            "selection": ("2020-12-24", "2020-12-24"),
            "embargo": ("2020-12-25", "2020-12-25"),
            "test": ("2021-01-01", "2021-01-04"),
        },
        {
            "train": ("2021-01-05", "2021-01-06"),
            "purge": ("2021-01-07", "2021-01-07"),
            "selection": ("2021-01-08", "2021-01-08"),
            "embargo": ("2021-01-11", "2021-01-11"),
            "test": ("2021-02-01", "2021-02-02"),
        },
        {
            "train": ("2021-02-03", "2021-02-04"),
            "purge": ("2021-02-05", "2021-02-05"),
            "selection": ("2021-02-08", "2021-02-08"),
            "embargo": ("2021-02-09", "2021-02-09"),
            "test": ("2021-03-01", "2021-03-02"),
        },
    ]
    windows: list[dict[str, object]] = []
    for index, period in enumerate(periods[:window_count], start=1):
        name = f"wf_{index:02d}"
        phases = {
            "name": name,
            "mode": "expanding",
            **{
                phase: {
                    "start": boundaries[0],
                    "end": boundaries[1],
                    "trading_day_count": 2 if phase in {"train", "test"} else 1,
                }
                for phase, boundaries in period.items()
            },
        }
        window: dict[str, object] = {
            "window": name,
            "start": period["test"][0],
            "end": period["test"][1],
            "status": status,
            "phases": phases,
        }
        if candidate:
            window.update(
                {
                    "candidate": "price_volume_defensive",
                    "selection_rank": 1,
                }
            )
        windows.append(window)

    payload: dict[str, object] = {
        "artifact_type": (CANDIDATE_WALK_FORWARD_ARTIFACT if candidate else WALK_FORWARD_ARTIFACT),
        "schema_version": 2,
        "selection_protocol": SELECTION_PROTOCOL,
        "selection_safe": True,
        "test_used_for_selection": False,
        "configuration": {
            "mode": "expanding",
            "train_days": 2,
            "purge_days": 1,
            "selection_days": 1,
            "embargo_days": 1,
            "test_days": 2,
            "step_days": 2,
        },
        "status": status,
        "window_count": len(windows),
        "windows": windows,
    }
    if candidate:
        payload.update(
            {
                "candidate_count": 1,
                "selected_candidate": "price_volume_defensive",
                "best_candidate": "price_volume_defensive",
                "selections": [
                    {
                        "window": window["window"],
                        "candidate": "price_volume_defensive",
                        "rank": 1,
                    }
                    for window in windows
                ],
            }
        )
    return payload


def _selection_safe_robustness_payload(*, status: str) -> dict[str, object]:
    return complete_selection_safe_robustness_payload(status=status)


def _write_candidate_walk_forward(
    report_dir: Path,
    *,
    status: str = "PASS",
    positive_return_ratio: float,
    worst_total_return: float,
    worst_max_drawdown: float,
) -> None:
    payload = _selection_safe_walk_forward_payload(
        status=status,
        candidate=True,
        window_count=3,
    )
    payload["summaries"] = [
        {
            "candidate": "price_volume_defensive",
            "status": status,
            "window_count": 3,
            "pass_count": 3 if status == "PASS" else 1,
            "watch_count": 0 if status == "PASS" else 2,
            "block_count": 1 if status == "BLOCK" else 0,
            "avg_total_return": 0.06,
            "avg_max_drawdown": 0.04,
            "avg_sharpe_ratio": 0.9,
            "positive_return_ratio": positive_return_ratio,
            "worst_total_return": worst_total_return,
            "worst_max_drawdown": worst_max_drawdown,
        }
    ]
    _write_json(report_dir / "candidate_walk_forward_report.json", payload)


def _write_complete_statistical_evidence(report_dir: Path) -> None:
    candidate = "price_volume_defensive"
    if not (report_dir / "robustness_report.json").exists():
        _write_json(
            report_dir / "robustness_report.json",
            _selection_safe_robustness_payload(status="PASS"),
        )
    if not (report_dir / "walk_forward_report.json").exists():
        _write_json(
            report_dir / "walk_forward_report.json",
            _selection_safe_walk_forward_payload(status="PASS"),
        )
    if not (report_dir / "candidate_walk_forward_report.json").exists():
        _write_candidate_walk_forward(
            report_dir,
            positive_return_ratio=1.0,
            worst_total_return=0.01,
            worst_max_drawdown=0.04,
        )
    _write_json(
        report_dir / "candidate_selection.json",
        {
            "status": "PASS",
            "selected_candidate": candidate,
            "best_candidate": candidate,
        },
    )
    write_statistical_evidence_fixtures(report_dir, candidate=candidate)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
