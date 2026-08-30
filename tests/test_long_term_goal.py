from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.audit import audit_data, write_data_audit
from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.paper import write_paper_daily_review
from quantify.readiness import (
    evaluate_micro_live_readiness,
    write_approval_record,
    write_readiness_outputs,
)
from quantify.research.demo_data import seed_demo_data
from quantify.research.robustness import RobustnessScenario, run_robustness, write_robustness_report
from quantify.research.selection_evidence import (
    build_selection_evidence_manifest,
    canonical_payload_sha256,
    write_selection_evidence_manifest,
)
from quantify.utils.config import Config
from tests.selection_safe_fixtures import (
    selection_safe_robustness_payload,
    selection_safe_walk_forward_payload,
)
from tests.statistical_evidence_fixtures import write_statistical_evidence_fixtures


def test_data_audit_detects_invalid_ohlc_and_missing_bars(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "q.db")
    storage.save_calendar(["2024-01-02", "2024-01-03"])
    storage.save_stock_info(pd.DataFrame({"symbol": ["AAA", "BBB"], "name": ["正常", "ST风险"]}))
    storage.save_bars(
        pd.DataFrame(
            {
                "symbol": ["AAA", "BBB"],
                "date": ["2024-01-02", "2024-01-02"],
                "open": [10.0, 10.0],
                "high": [9.0, 11.0],
                "low": [8.0, 9.0],
                "close": [10.0, 10.0],
                "volume": [1000, 0],
                "amount": [10000, 0],
            }
        )
    )

    report = audit_data(DataProvider(storage), "2024-01-02", "2024-01-03")
    out = write_data_audit(report, tmp_path / "audit")

    assert report.status == "BLOCK"
    assert any(finding.code == "INVALID_OHLC" for finding in report.findings)
    assert (out / "data_audit.json").exists()
    assert "Data Audit" in (out / "data_audit.md").read_text(encoding="utf-8")


def test_data_audit_treats_demo_symbols_as_demo_even_when_not_seeded_this_run(
    tmp_path: Path,
) -> None:
    storage = BarStorage(tmp_path / "demo.db")
    seed_demo_data(storage, "2020-01-01", "2020-01-31")

    report = audit_data(
        DataProvider(storage),
        "2020-01-01",
        "2020-01-31",
        demo_data_used=False,
    )

    assert report.demo_data_used is True
    assert any(finding.code == "DEMO_DATA" for finding in report.findings)


def test_data_audit_treats_mixed_demo_and_real_symbols_as_demo(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "mixed.db")
    symbols = ["DEMO001", "600000"]
    storage.save_calendar(["2024-01-02"])
    storage.save_stock_info(
        pd.DataFrame(
            {
                "symbol": symbols,
                "name": ["Demo", "Real"],
            }
        )
    )
    storage.save_bars(
        pd.DataFrame(
            {
                "symbol": symbols,
                "date": ["2024-01-02", "2024-01-02"],
                "open": [10.0, 20.0],
                "high": [10.2, 20.2],
                "low": [9.8, 19.8],
                "close": [10.1, 20.1],
                "volume": [1_000_000, 1_000_000],
                "amount": [10_100_000, 20_100_000],
            }
        )
    )
    storage.save_fundamentals(
        pd.DataFrame(
            {
                "symbol": symbols,
                "date": ["2024-01-02", "2024-01-02"],
            }
        )
    )

    report = audit_data(DataProvider(storage), "2024-01-02", "2024-01-02")

    assert report.demo_data_used is True
    assert report.status == "WATCH"
    assert [finding.code for finding in report.findings] == ["DEMO_DATA"]


def test_data_audit_surfaces_non_pit_akshare_universe_snapshot(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "akshare_snapshot.db")
    storage.save_calendar(["2024-01-02"])
    storage.save_stock_info(pd.DataFrame({"symbol": ["600000"], "name": ["bank"]}))
    storage.save_bars(
        pd.DataFrame(
            {
                "symbol": ["600000"],
                "date": ["2024-01-02"],
                "open": [10.0],
                "high": [10.2],
                "low": [9.8],
                "close": [10.1],
                "volume": [1_000_000],
                "amount": [10_100_000],
            }
        )
    )
    storage.save_fundamentals(
        pd.DataFrame({"symbol": ["600000"], "date": ["2024-01-02"]})
    )
    storage.save_metadata(
        {
            "data_source": "akshare",
            "data_import_universe_snapshot_mode": "current_spot_snapshot_research_only",
            "data_import_universe_snapshot_asof_utc": "2024-01-02T10:00:00+00:00",
            "data_import_universe_point_in_time": "false",
        }
    )

    report = audit_data(DataProvider(storage), "2024-01-02", "2024-01-02")
    finding = next(
        item for item in report.findings if item.code == "UNIVERSE_NOT_POINT_IN_TIME"
    )

    assert report.status == "WATCH"
    assert finding.severity == "WATCH"
    assert finding.evidence["universe_snapshot_mode"] == "current_spot_snapshot_research_only"
    assert report.metrics["universe_point_in_time"] is False


def test_data_audit_accepts_explicit_point_in_time_universe_metadata(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "pit_universe.db")
    storage.save_metadata(
        {
            "data_source": "akshare",
            "data_import_universe_snapshot_mode": "point_in_time_history",
            "data_import_universe_point_in_time": "true",
        }
    )

    report = audit_data(DataProvider(storage), "2024-01-02", "2024-01-02")

    assert not any(item.code == "UNIVERSE_NOT_POINT_IN_TIME" for item in report.findings)


def test_data_audit_surfaces_tradability_risk_findings(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "tradability.db")
    storage.save_calendar(["2024-01-02", "2024-01-03", "2024-01-04"])
    storage.save_stock_info(
        pd.DataFrame(
            {
                "symbol": ["AAA", "BBB", "CCC"],
                "name": ["正常", "ST风险", "退市风险"],
                "delist_date": ["", "", "2024-01-04"],
                "is_st": [0, 1, 0],
            }
        )
    )
    rows = []
    closes = {
        "AAA": [10.0, 11.0, 9.9],
        "BBB": [20.0, 20.2, 20.3],
        "CCC": [30.0, 30.1, 30.2],
    }
    for symbol, values in closes.items():
        for day, close in zip(["2024-01-02", "2024-01-03", "2024-01-04"], values, strict=True):
            rows.append(
                {
                    "symbol": symbol,
                    "date": day,
                    "open": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": 1_000_000,
                    "amount": close * 1_000_000,
                }
            )
    storage.save_bars(pd.DataFrame(rows))
    storage.save_fundamentals(
        pd.DataFrame(
            {
                "symbol": ["AAA", "BBB", "CCC"],
                "date": ["2024-01-04"] * 3,
                "pe_ttm": [10.0, 11.0, 12.0],
            }
        )
    )
    storage.save_suspensions(pd.DataFrame({"symbol": ["BBB"], "date": ["2024-01-03"]}))

    report = audit_data(DataProvider(storage), "2024-01-02", "2024-01-04")
    findings = {finding.code: finding for finding in report.findings}

    assert report.status == "BLOCK"
    assert findings["ST_SYMBOLS_PRESENT"].severity == "WATCH"
    assert findings["DELISTED_SYMBOLS_PRESENT"].severity == "BLOCK"
    assert findings["SUSPENSIONS_PRESENT"].evidence["suspension_symbol_day_count"] == 1
    assert findings["PRICE_LIMIT_EVENTS_PRESENT"].evidence["limit_up_count"] == 1
    assert findings["PRICE_LIMIT_EVENTS_PRESENT"].evidence["limit_down_count"] == 1
    assert findings["DELISTED_SYMBOLS_PRESENT"].evidence["examples"][0]["symbol"] == "CCC"


def test_robustness_report_marks_scenario_subset_as_diagnostic(tmp_path: Path) -> None:
    storage = BarStorage(tmp_path / "research.db")
    seed_demo_data(storage, "2020-01-01", "2020-06-30")
    provider = DataProvider(storage)
    cfg = _cfg(tmp_path / "research.db")
    scenarios = [
        RobustnessScenario(
            name="baseline",
            n_holdings=5,
            max_weight=0.10,
            rebalance="monthly",
            commission_rate=0.0,
            min_commission=0.0,
            stamp_tax=0.0,
            slippage_bps=0.0,
        )
    ]

    report = run_robustness(
        provider,
        cfg,
        scenarios,
        train_days=20,
        purge_days=2,
        selection_days=5,
        embargo_days=2,
        test_days=20,
        step_days=20,
    )
    out = write_robustness_report(report, tmp_path / "robustness")

    assert len(report.scenarios) == 1
    assert report.selection_safe is False
    assert report.status == "WATCH"
    assert any("missing required promotion scenarios" in item for item in report.warnings)
    assert report.scenarios[0].order_count > 0
    payload = json.loads((out / "robustness_report.json").read_text(encoding="utf-8"))
    assert payload["selection_protocol"] == "quantify.robustness-selection.v2"
    assert payload["scenario_matrix_frozen"] is True
    assert payload["test_used_for_selection"] is False
    assert "Robustness Report" in (out / "robustness_report.md").read_text(encoding="utf-8")


def test_paper_daily_review_outputs_manual_artifacts(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)

    out = write_paper_daily_review(tmp_path)

    review = json.loads((out / "paper_daily_review.json").read_text(encoding="utf-8"))

    assert not (out / "paper_state.json").exists()
    assert not (out / "paper_orders.csv").exists()
    assert not (out / "paper_positions.csv").exists()
    assert (out / "research_execution_preview.json").exists()
    assert (out / "paper_daily_review.json").exists()
    assert review["status"] == "BLOCK"
    assert review["code"] == "NO_CONTINUOUS_PAPER_RUN"
    assert review["state"]["observed_days"] == 0
    assert "not continuous paper evidence" in (
        out / "paper_daily_review.md"
    ).read_text(encoding="utf-8")


def test_readiness_blocks_without_approval_and_writes_manual_sheet(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    _write_target_portfolio(tmp_path, risk_flags="")

    out = write_readiness_outputs(tmp_path)
    readiness = json.loads((out / "micro_live_readiness.json").read_text(encoding="utf-8"))
    manual = pd.read_csv(out / "manual_trade_sheet.csv")

    assert readiness["decision"] == "BLOCK"
    assert any(finding["code"] == "MISSING_APPROVAL" for finding in readiness["findings"])
    assert (out / "manual_trade_sheet.csv").exists()
    assert int(manual["target_quantity"].iloc[0]) == 400
    assert set(manual["instruction"]) == {"MANUAL_REFERENCE_ONLY_NO_BROKER_ORDER"}


def test_readiness_blocks_missing_walk_forward_evidence(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    _write_target_portfolio(tmp_path, risk_flags="")
    (tmp_path / "walk_forward_report.json").unlink()
    write_approval_record(tmp_path, approved_by="tester", approval_notes="manual approval test")

    out = write_readiness_outputs(tmp_path)
    readiness = json.loads((out / "micro_live_readiness.json").read_text(encoding="utf-8"))

    assert readiness["decision"] == "BLOCK"
    assert any(finding["code"] == "MISSING_WALK_FORWARD" for finding in readiness["findings"])


def test_readiness_blocks_missing_statistical_evidence(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    _write_target_portfolio(tmp_path, risk_flags="")
    (tmp_path / "benchmark_report.json").unlink()
    write_approval_record(tmp_path, approved_by="tester", approval_notes="manual approval test")

    readiness = evaluate_micro_live_readiness(tmp_path)

    assert readiness.decision == "BLOCK"
    assert any(finding.code == "MISSING_BENCHMARK_REPORT" for finding in readiness.findings)


def test_readiness_blocks_non_pass_statistical_evidence(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    _write_target_portfolio(tmp_path, risk_flags="")
    benchmark = json.loads((tmp_path / "benchmark_report.json").read_text(encoding="utf-8"))
    benchmark["status"] = "WATCH"
    for evidence in benchmark["evidence"]:
        evidence["status"] = "WATCH"
    (tmp_path / "benchmark_report.json").write_text(
        json.dumps(benchmark, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_approval_record(tmp_path, approved_by="tester", approval_notes="manual approval test")

    readiness = evaluate_micro_live_readiness(tmp_path)

    assert readiness.decision == "BLOCK"
    assert any(
        finding.code == "BENCHMARK_REPORT_STATUS_NOT_PASS" for finding in readiness.findings
    )


def test_readiness_blocks_tampered_benchmark_identity_and_input(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    _write_target_portfolio(tmp_path, risk_flags="")
    benchmark_path = tmp_path / "benchmark_report.json"
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    benchmark["identity"]["symbol"] = "000300.SH"
    benchmark["benchmark_metadata"]["symbol"] = "000300.SH"
    benchmark_path.write_text(
        json.dumps(benchmark, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (tmp_path / "reviewed_benchmark.csv").open("a", encoding="utf-8") as handle:
        handle.write("\n")
    write_approval_record(tmp_path, approved_by="tester", approval_notes="manual approval test")

    readiness = evaluate_micro_live_readiness(tmp_path)

    assert readiness.decision == "BLOCK"
    assert any(
        finding.code == "BENCHMARK_REPORT_CONTRACT_INVALID"
        for finding in readiness.findings
    )


def test_readiness_blocks_invalid_trial_artifact_binding(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    _write_target_portfolio(tmp_path, risk_flags="")
    multiple_path = tmp_path / "multiple_testing_report.json"
    multiple_path.write_text(
        multiple_path.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    write_approval_record(tmp_path, approved_by="tester", approval_notes="manual approval test")

    readiness = evaluate_micro_live_readiness(tmp_path)

    assert readiness.decision == "BLOCK"
    assert any(
        finding.code == "TRIAL_REGISTRY_REVIEW_CONTRACT_INVALID"
        for finding in readiness.findings
    )


def test_readiness_blocks_missing_market_context_readiness(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    _write_target_portfolio(tmp_path, risk_flags="")
    (tmp_path / "market_context_readiness.json").unlink()
    write_approval_record(tmp_path, approved_by="tester", approval_notes="manual approval test")

    out = write_readiness_outputs(tmp_path)
    readiness = json.loads((out / "micro_live_readiness.json").read_text(encoding="utf-8"))

    assert readiness["decision"] == "BLOCK"
    assert any(
        finding["code"] == "MISSING_MARKET_CONTEXT_READINESS" for finding in readiness["findings"]
    )


def test_readiness_watches_market_context_readiness_watch(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    _write_target_portfolio(tmp_path, risk_flags="")
    (tmp_path / "market_context_readiness.json").write_text(
        json.dumps({"decision": "WATCH"}),
        encoding="utf-8",
    )
    write_approval_record(tmp_path, approved_by="tester", approval_notes="manual approval test")

    out = write_readiness_outputs(tmp_path)
    readiness = json.loads((out / "micro_live_readiness.json").read_text(encoding="utf-8"))

    assert readiness["decision"] == "WATCH"
    assert any(
        finding["code"] == "MARKET_CONTEXT_READINESS_WATCH" for finding in readiness["findings"]
    )


def test_readiness_blocks_unknown_llm_decision(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    _write_target_portfolio(tmp_path, risk_flags="")
    (tmp_path / "llm_review.json").write_text(json.dumps({"decision": "UNKNOWN"}), encoding="utf-8")
    write_approval_record(tmp_path, approved_by="tester", approval_notes="manual approval test")

    out = write_readiness_outputs(tmp_path)
    readiness = json.loads((out / "micro_live_readiness.json").read_text(encoding="utf-8"))

    assert readiness["decision"] == "BLOCK"
    assert any(finding["code"] == "UNKNOWN_LLM_REVIEW" for finding in readiness["findings"])


def test_readiness_blocks_missing_paper_daily_review(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    _write_target_portfolio(tmp_path, risk_flags="")
    (tmp_path / "paper_daily_review.json").unlink()
    write_approval_record(tmp_path, approved_by="tester", approval_notes="manual approval test")

    out = write_readiness_outputs(tmp_path)
    readiness = json.loads((out / "micro_live_readiness.json").read_text(encoding="utf-8"))

    assert readiness["decision"] == "BLOCK"
    assert any(finding["code"] == "MISSING_PAPER_DAILY_REVIEW" for finding in readiness["findings"])


def test_readiness_blocks_missing_run_manifest(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    _write_target_portfolio(tmp_path, risk_flags="")
    (tmp_path / "run_manifest.json").unlink()
    write_approval_record(tmp_path, approved_by="tester", approval_notes="manual approval test")

    out = write_readiness_outputs(tmp_path)
    readiness = json.loads((out / "micro_live_readiness.json").read_text(encoding="utf-8"))

    assert readiness["decision"] == "BLOCK"
    assert any(finding["code"] == "MISSING_RUN_MANIFEST" for finding in readiness["findings"])


def test_readiness_blocks_run_manifest_without_source_qa_provenance(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    _write_target_portfolio(tmp_path, risk_flags="")
    (tmp_path / "run_manifest.json").write_text(
        json.dumps(
            {
                "demo_data_used": False,
                "in_sample_end": "2024-01-02",
                "out_sample_start": "2024-01-03",
                "data_version": {"data_source_qa_status": "PASS"},
            }
        ),
        encoding="utf-8",
    )
    write_approval_record(tmp_path, approved_by="tester", approval_notes="manual approval test")

    out = write_readiness_outputs(tmp_path)
    readiness = json.loads((out / "micro_live_readiness.json").read_text(encoding="utf-8"))

    assert readiness["decision"] == "BLOCK"
    assert any(
        finding["code"] == "RUN_MANIFEST_PROMOTION_METADATA_BLOCK"
        for finding in readiness["findings"]
    )


def test_readiness_blocks_mixed_candidate_pass_artifacts(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    _write_target_portfolio(tmp_path, risk_flags="")
    (tmp_path / "candidate_experiment_completion.json").write_text(
        json.dumps(
            {
                "decision": "PASS",
                "selected_candidate": "different_candidate",
                "run_id": "different-run",
                "launch_decision": "PASS",
                "artifacts": [{"name": "candidate_selection.json", "status": "PASS"}],
            }
        ),
        encoding="utf-8",
    )
    write_approval_record(tmp_path, approved_by="tester", approval_notes="manual approval test")

    readiness = evaluate_micro_live_readiness(tmp_path)

    assert readiness.decision == "BLOCK"
    assert any(
        finding.code == "CANDIDATE_EVIDENCE_IDENTITY_MISMATCH" for finding in readiness.findings
    )


def test_readiness_blocks_paper_cache_from_different_research_run(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    _write_target_portfolio(tmp_path, risk_flags="")
    paper_state = json.loads((tmp_path / "paper_state.json").read_text(encoding="utf-8"))
    paper_state["run_context"]["data"]["cache_sha256"] = "different-cache-hash"
    (tmp_path / "paper_state.json").write_text(
        json.dumps(paper_state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_approval_record(tmp_path, approved_by="tester", approval_notes="manual approval test")

    readiness = evaluate_micro_live_readiness(tmp_path)

    assert readiness.decision == "BLOCK"
    assert any(finding.code == "PAPER_CACHE_IDENTITY_MISMATCH" for finding in readiness.findings)


def test_readiness_watches_paper_daily_review_watch(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    _write_target_portfolio(tmp_path, risk_flags="")
    (tmp_path / "paper_daily_review.json").write_text(
        json.dumps({"status": "WATCH"}), encoding="utf-8"
    )
    write_approval_record(tmp_path, approved_by="tester", approval_notes="manual approval test")

    out = write_readiness_outputs(tmp_path)
    readiness = json.loads((out / "micro_live_readiness.json").read_text(encoding="utf-8"))

    assert readiness["decision"] == "WATCH"
    assert any(finding["code"] == "PAPER_DAILY_REVIEW_WATCH" for finding in readiness["findings"])


def test_readiness_blocks_approval_without_notes(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    _write_target_portfolio(tmp_path, risk_flags="")
    write_approval_record(tmp_path, approved_by="tester", approval_notes="")

    out = write_readiness_outputs(tmp_path)
    readiness = json.loads((out / "micro_live_readiness.json").read_text(encoding="utf-8"))

    assert readiness["decision"] == "BLOCK"
    assert any(finding["code"] == "INVALID_APPROVAL" for finding in readiness["findings"])


def test_readiness_blocks_target_portfolio_execution_risk_flags(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    _write_target_portfolio(tmp_path, risk_flags="LIMIT_UP;HIGH_PARTICIPATION")
    write_approval_record(tmp_path, approved_by="tester", approval_notes="manual approval test")

    out = write_readiness_outputs(tmp_path)
    readiness = json.loads((out / "micro_live_readiness.json").read_text(encoding="utf-8"))

    assert readiness["decision"] == "BLOCK"
    assert any(
        finding["code"] == "TARGET_EXECUTION_RISK_FLAGS" for finding in readiness["findings"]
    )
    assert any(finding["code"] == "TARGET_WATCH_RISK_FLAGS" for finding in readiness["findings"])


def test_readiness_watches_target_portfolio_nonblocking_risk_flags(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    _write_target_portfolio(tmp_path, risk_flags="LOW_LIQUIDITY;HIGH_WEIGHT")
    write_approval_record(tmp_path, approved_by="tester", approval_notes="manual approval test")

    out = write_readiness_outputs(tmp_path)
    readiness = json.loads((out / "micro_live_readiness.json").read_text(encoding="utf-8"))

    assert readiness["decision"] == "WATCH"
    assert any(finding["code"] == "TARGET_WATCH_RISK_FLAGS" for finding in readiness["findings"])


def test_readiness_blocks_when_approval_snapshot_is_stale(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    _write_target_portfolio(tmp_path, risk_flags="")
    write_approval_record(tmp_path, approved_by="tester", approval_notes="manual approval test")
    _write_target_portfolio(tmp_path, risk_flags="LOW_LIQUIDITY")

    out = write_readiness_outputs(tmp_path)
    readiness = json.loads((out / "micro_live_readiness.json").read_text(encoding="utf-8"))

    assert readiness["decision"] == "BLOCK"
    assert any(finding["code"] == "APPROVAL_SNAPSHOT_MISMATCH" for finding in readiness["findings"])


def test_readiness_blocks_invalid_price_and_csv_json_row_mismatch(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    _write_target_portfolio(tmp_path, risk_flags="")
    target = pd.read_csv(tmp_path / "target_portfolio.csv")
    target.loc[0, "latest_price"] = 0.0
    target.to_csv(tmp_path / "target_portfolio.csv", index=False)
    write_approval_record(tmp_path, approved_by="tester", approval_notes="manual approval test")

    readiness = evaluate_micro_live_readiness(tmp_path)

    assert readiness.decision == "BLOCK"
    codes = {finding.code for finding in readiness.findings}
    assert "TARGET_PORTFOLIO_INVALID_PRICE" in codes
    assert "TARGET_PORTFOLIO_ROW_MISMATCH" in codes


def test_readiness_blocks_target_portfolio_over_capital(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    _write_target_portfolio(tmp_path, risk_flags="")
    target = pd.read_csv(tmp_path / "target_portfolio.csv")
    target.loc[0, "target_value"] = 150_000.0
    target.loc[0, "target_quantity"] = 15_000
    target.loc[0, "quantity_delta"] = 14_700
    target.loc[0, "estimated_cost"] = 150_000.0
    target.to_csv(tmp_path / "target_portfolio.csv", index=False)
    plan = json.loads((tmp_path / "target_portfolio.json").read_text(encoding="utf-8"))
    plan["rows"][0].update(
        {
            "target_value": 150_000.0,
            "target_quantity": 15_000,
            "quantity_delta": 14_700,
            "estimated_cost": 150_000.0,
        }
    )
    plan["estimated_gross_exposure"] = 150_000.0
    plan["estimated_cash_buffer"] = 0.0
    (tmp_path / "target_portfolio.json").write_text(json.dumps(plan), encoding="utf-8")
    write_approval_record(tmp_path, approved_by="tester", approval_notes="manual approval test")

    readiness = evaluate_micro_live_readiness(tmp_path)

    assert readiness.decision == "BLOCK"
    assert any(
        finding.code == "TARGET_PORTFOLIO_CAPITAL_EXCEEDED" for finding in readiness.findings
    )


def test_readiness_blocks_target_quantity_not_aligned_to_lot_size(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    _write_target_portfolio(tmp_path, risk_flags="")
    target = pd.read_csv(tmp_path / "target_portfolio.csv")
    target.loc[0, "target_quantity"] = 450
    target.loc[0, "quantity_delta"] = 150
    target.loc[0, "estimated_cost"] = 4_500.0
    target.to_csv(tmp_path / "target_portfolio.csv", index=False)
    plan = json.loads((tmp_path / "target_portfolio.json").read_text(encoding="utf-8"))
    plan["rows"][0].update(
        {"target_quantity": 450, "quantity_delta": 150, "estimated_cost": 4_500.0}
    )
    plan["estimated_gross_exposure"] = 4_500.0
    plan["estimated_cash_buffer"] = 95_500.0
    (tmp_path / "target_portfolio.json").write_text(json.dumps(plan), encoding="utf-8")
    write_approval_record(tmp_path, approved_by="tester", approval_notes="manual approval test")

    readiness = evaluate_micro_live_readiness(tmp_path)

    assert readiness.decision == "BLOCK"
    assert any(finding.code == "TARGET_QUANTITY_NOT_LOT_ALIGNED" for finding in readiness.findings)


def test_readiness_blocks_tampered_manual_trade_sheet_core_fields(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    _write_target_portfolio(tmp_path, risk_flags="")
    write_approval_record(tmp_path, approved_by="tester", approval_notes="manual approval test")
    manual = pd.read_csv(tmp_path / "manual_trade_sheet.csv")
    manual.loc[0, "target_quantity"] = 300
    manual.to_csv(tmp_path / "manual_trade_sheet.csv", index=False)

    readiness = evaluate_micro_live_readiness(tmp_path)

    assert readiness.decision == "BLOCK"
    assert any(
        finding.code == "MANUAL_TRADE_SHEET_TARGET_MISMATCH" for finding in readiness.findings
    )
    assert any(finding.code == "APPROVAL_SNAPSHOT_MISMATCH" for finding in readiness.findings)


def test_readiness_blocks_tampered_risk_budget(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    _write_target_portfolio(tmp_path, risk_flags="")
    write_approval_record(tmp_path, approved_by="tester", approval_notes="manual approval test")
    risk_budget = json.loads((tmp_path / "risk_budget.json").read_text(encoding="utf-8"))
    risk_budget["max_position_pct"] = 0.5
    (tmp_path / "risk_budget.json").write_text(json.dumps(risk_budget), encoding="utf-8")

    readiness = evaluate_micro_live_readiness(tmp_path)

    assert readiness.decision == "BLOCK"
    assert any(finding.code == "RISK_BUDGET_MISMATCH" for finding in readiness.findings)
    assert any(finding.code == "APPROVAL_SNAPSHOT_MISMATCH" for finding in readiness.findings)


def test_readiness_approval_locks_generated_manual_materials(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    _write_target_portfolio(tmp_path, risk_flags="")

    write_readiness_outputs(tmp_path)
    write_approval_record(tmp_path, approved_by="tester", approval_notes="manual approval test")
    out = write_readiness_outputs(tmp_path)

    readiness = json.loads((out / "micro_live_readiness.json").read_text(encoding="utf-8"))
    approval = json.loads((out / "approval_record.json").read_text(encoding="utf-8"))
    assert readiness["decision"] == "PASS"
    assert {
        "manual_trade_sheet.csv",
        "risk_budget.json",
        "benchmark_report.json",
        "multiple_testing_report.json",
        "trial_registry_review.json",
    }.issubset(approval["evidence_snapshot"])


def test_readiness_blocks_non_manual_trade_sheet_instruction(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    _write_target_portfolio(tmp_path, risk_flags="")
    write_approval_record(tmp_path, approved_by="tester", approval_notes="manual approval test")
    manual = pd.read_csv(tmp_path / "manual_trade_sheet.csv")
    manual["instruction"] = "BROKER_ORDER_SUBMIT"
    manual.to_csv(tmp_path / "manual_trade_sheet.csv", index=False)

    readiness = evaluate_micro_live_readiness(tmp_path)

    assert readiness.decision == "BLOCK"
    assert any(
        finding.code == "MANUAL_TRADE_SHEET_NOT_MANUAL_ONLY" for finding in readiness.findings
    )


def test_readiness_with_approval_still_blocks_demo_data(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=True)
    _write_target_portfolio(tmp_path, risk_flags="")
    write_approval_record(tmp_path, approved_by="tester", approval_notes="manual approval test")

    out = write_readiness_outputs(tmp_path)
    readiness = json.loads((out / "micro_live_readiness.json").read_text(encoding="utf-8"))

    assert readiness["decision"] == "BLOCK"
    assert any(finding["code"] == "DEMO_DATA" for finding in readiness["findings"])


def test_readiness_blocks_when_paper_stability_blocks(tmp_path: Path) -> None:
    _write_report_artifacts(tmp_path)
    _write_gate_artifacts(tmp_path, demo_data_used=False)
    (tmp_path / "paper_stability.json").write_text(
        json.dumps({"status": "BLOCK"}), encoding="utf-8"
    )
    _write_target_portfolio(tmp_path, risk_flags="")
    write_approval_record(tmp_path, approved_by="tester", approval_notes="manual approval test")

    out = write_readiness_outputs(tmp_path)
    readiness = json.loads((out / "micro_live_readiness.json").read_text(encoding="utf-8"))

    assert readiness["decision"] == "BLOCK"
    assert any(finding["code"] == "PAPER_STABILITY_BLOCK" for finding in readiness["findings"])


def test_readiness_cli_can_build_manual_target_plan_before_review(tmp_path: Path) -> None:
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    cache = tmp_path / "research.db"
    seed_demo_data(BarStorage(cache), "2020-01-01", "2020-12-31")
    cfg_path = tmp_path / "research.yaml"
    cfg_path.write_text(_cfg_yaml(cache), encoding="utf-8")
    _write_report_artifacts(report_dir)
    _write_gate_artifacts(report_dir, demo_data_used=False)
    write_approval_record(report_dir, approved_by="tester", approval_notes="manual approval test")

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_readiness.py",
            "--report-dir",
            str(report_dir),
            "--build-target-plan",
            "--config",
            str(cfg_path),
            "--as-of",
            "2020-12-31",
            "--candidate",
            "price_volume_defensive",
            "--capital",
            "100000",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )
    manual = pd.read_csv(report_dir / "manual_trade_sheet.csv")
    readiness = json.loads((report_dir / "micro_live_readiness.json").read_text(encoding="utf-8"))

    assert completed.returncode == 0
    assert (report_dir / "target_portfolio.csv").exists()
    assert (report_dir / "target_portfolio.json").exists()
    assert not manual.empty
    assert set(manual["instruction"]) == {"MANUAL_REFERENCE_ONLY_NO_BROKER_ORDER"}
    assert readiness["decision"] in {"PASS", "WATCH", "BLOCK"}


def _cfg(cache_path: Path) -> Config:
    return Config(
        {
            "research": {
                "start": "2020-04-01",
                "end": "2020-06-30",
                "initial_cash": 1_000_000.0,
                "rebalance": "monthly",
            },
            "universe": {
                "mode": "all_a",
                "index_code": "000906",
                "include_st": False,
                "min_history_days": 20,
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
            "data": {"cache_path": str(cache_path), "source": "demo"},
            "output": {"results_dir": str(cache_path.parent)},
        }
    )


def _cfg_yaml(cache_path: Path) -> str:
    return f"""
research:
  start: "2020-01-01"
  end: "2020-12-31"
  initial_cash: 100000.0
  rebalance: monthly
  allow_demo_data: true
data:
  source: demo
  cache_path: "{cache_path.as_posix()}"
universe:
  mode: all_a
  index_code: "000906"
  include_st: false
  min_history_days: 20
strategy:
  n_holdings: 5
  max_weight: 0.10
risk:
  max_drawdown_stop: 0.2
broker:
  commission_rate: 0.0
  min_commission: 0.0
  stamp_tax: 0.0
  slippage_bps: 0.0
  price_limit_pct: 0.10
  lot_size: 100
"""


def _write_report_artifacts(root: Path) -> None:
    pd.DataFrame(
        {"timestamp": ["2024-01-02", "2024-01-03"], "equity": [1_000_000, 1_010_000]}
    ).to_csv(
        root / "equity.csv",
        index=False,
    )
    pd.DataFrame(
        {
            "date": ["2024-01-03"],
            "symbol": ["AAA"],
            "quantity": [1000],
            "price": [10.0],
            "market_value": [10_000.0],
            "weight": [0.01],
        }
    ).to_csv(root / "positions.csv", index=False)
    pd.DataFrame({"status": ["filled"], "symbol": ["AAA"]}).to_csv(root / "orders.csv", index=False)


def _write_gate_artifacts(root: Path, *, demo_data_used: bool) -> None:
    candidate = "price_volume_defensive"
    (root / "real_data_bootstrap.json").write_text(
        json.dumps({"decision": "PASS"}), encoding="utf-8"
    )
    (root / "real_data_gate.json").write_text(json.dumps({"decision": "PASS"}), encoding="utf-8")
    (root / "data_coverage.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    (root / "market_context_readiness.json").write_text(
        json.dumps({"decision": "PASS", "source": "market_regime", "label": "neutral"}),
        encoding="utf-8",
    )
    (root / "llm_review.json").write_text(
        json.dumps(
            {
                "decision": "PASS",
                "snapshot": {
                    "summary": {
                        "assumptions": {
                            "demo_data_used": demo_data_used,
                            "max_weight": 0.05,
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "data_audit.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    (root / "robustness_report.json").write_text(
        json.dumps(selection_safe_robustness_payload()),
        encoding="utf-8",
    )
    (root / "walk_forward_report.json").write_text(
        json.dumps(selection_safe_walk_forward_payload()),
        encoding="utf-8",
    )
    (root / "candidate_walk_forward_report.json").write_text(
        json.dumps(selection_safe_walk_forward_payload(candidate=candidate)),
        encoding="utf-8",
    )
    (root / "candidate_regime_validation_report.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "best_candidate": candidate,
                "summaries": [{"candidate": candidate, "status": "PASS"}],
            }
        ),
        encoding="utf-8",
    )
    (root / "candidate_selection.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "selected_candidate": candidate,
                "candidate_lock_selection_safe": True,
                "evidence_inputs": {
                    "candidate_walk_forward_report.json": {
                        "sha256": canonical_payload_sha256(
                            selection_safe_walk_forward_payload(candidate=candidate)
                        )
                    }
                },
                "results": [{"name": candidate, "score": {"decision": "PASS"}}],
            }
        ),
        encoding="utf-8",
    )
    (root / "candidate_experiment_completion.json").write_text(
        json.dumps(
            {
                "decision": "PASS",
                "selected_candidate": candidate,
                "run_id": "unit-test-run",
                "launch_decision": "PASS",
                "artifacts": [{"name": "candidate_selection.json", "status": "PASS"}],
            }
        ),
        encoding="utf-8",
    )
    (root / "paper_state.json").write_text(
        json.dumps(
            {
                "observed_days": 25,
                "broker_connection": "none",
                "candidate": candidate,
                "run_context": {
                    "data": {
                        "cache_sha256": "unit-test-cache-hash",
                        "dataset_fingerprint": "unit-test-csv-fingerprint",
                        "logical_bar_fingerprint": "unit-test-logical-bars",
                        "import_batch_id": "unit-test-import-batch",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "paper_daily_review.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    (root / "paper_stability.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    _write_run_manifest(root, demo_data_used=demo_data_used)
    _write_promotion_metadata_check(root)
    write_selection_evidence_manifest(build_selection_evidence_manifest(root), root)
    write_statistical_evidence_fixtures(root, candidate=candidate)


def _write_target_portfolio(root: Path, *, risk_flags: str) -> None:
    candidate = "price_volume_defensive"
    row = {
        "symbol": "AAA",
        "industry": "Technology",
        "target_weight": 0.05,
        "score": 1.25,
        "latest_price": 10.0,
        "avg_amount_20d": 4_000_000.0,
        "estimated_participation_rate": 0.001,
        "target_value": 4_750.0,
        "target_quantity": 400,
        "estimated_cost": 4_000.0,
        "current_quantity": 300,
        "quantity_delta": 100,
        "instruction": "MANUAL_BUY_REVIEW",
        "reason": "target_quantity_rounded_to_lot_size",
        "risk_flags": risk_flags,
    }
    pd.DataFrame([row]).to_csv(root / "target_portfolio.csv", index=False)
    (root / "target_portfolio.json").write_text(
        json.dumps(
            {
                "as_of": "2024-01-03",
                "candidate": candidate,
                "capital": 100_000.0,
                "cash_buffer_pct": 0.05,
                "lot_size": 100,
                "target_count": 1,
                "total_target_weight": 0.05,
                "estimated_gross_exposure": 4_000.0,
                "estimated_cash_buffer": 96_000.0,
                "rows": [row],
                "warnings": [],
                "prohibited_actions": ["manual only"],
            }
        ),
        encoding="utf-8",
    )


def _write_run_manifest(root: Path, *, demo_data_used: bool) -> None:
    checklist = root / "data_source_qa.json"
    answers = root / "data_source_qa_answers.json"
    evidence_manifest = root / "source_qa_evidence_manifest.json"
    checklist.write_text('{"checklist":"unit-test"}', encoding="utf-8")
    answers.write_text('{"answers":"unit-test"}', encoding="utf-8")
    evidence_manifest.write_text('{"evidence":"unit-test"}', encoding="utf-8")
    (root / "run_manifest.json").write_text(
        json.dumps(
            {
                "cache_path": "unit-test-cache.db",
                "cache_sha256": "unit-test-cache-hash",
                "demo_data_used": demo_data_used,
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
            }
        ),
        encoding="utf-8",
    )


def _write_promotion_metadata_check(root: Path) -> None:
    (root / "promotion_metadata_check.json").write_text(
        json.dumps(
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
            }
        ),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
