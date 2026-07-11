from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.ops import run_weekly_pipeline
from quantify.utils.config import Config


def test_weekly_pipeline_writes_offline_evidence_chain(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path / "research.db", tmp_path / "results")
    registry_path = tmp_path / "registry" / "strategy_registry.json"

    result = run_weekly_pipeline(
        cfg,
        output_dir=tmp_path / "weekly",
        review_stage="paper",
        registry_path=registry_path,
        walk_forward_train_days=40,
        walk_forward_test_days=30,
        walk_forward_step_days=30,
    )
    out = Path(result.output_dir)

    assert (out / "summary.json").exists()
    assert (out / "run_manifest.json").exists()
    assert (out / "run_manifest.md").exists()
    assert (out / "real_data_bootstrap.json").exists()
    assert (out / "real_data_gate.json").exists()
    assert (out / "data_coverage.json").exists()
    assert (out / "data_coverage.csv").exists()
    assert (out / "data_audit.json").exists()
    assert (out / "market_regime.json").exists()
    assert (out / "robustness_report.json").exists()
    assert (out / "walk_forward_report.json").exists()
    assert (out / "candidate_walk_forward_report.json").exists()
    assert (out / "candidate_factor_diagnostics.json").exists()
    assert (out / "candidate_regime_validation_report.json").exists()
    assert (out / "candidate_selection.json").exists()
    assert (out / "paper_state.json").exists()
    assert (out / "paper_daily_review.json").exists()
    assert (out / "paper_stability.json").exists()
    assert (out / "llm_review.json").exists()
    assert (out / "recent_candidate_research.json").exists()
    assert (out / "paper_candidate_plan.json").exists()
    assert (out / "llm_prompt.md").exists()
    assert (out / "weekly_review.json").exists()
    assert (out / "weekly_pipeline.json").exists()
    assert (out / "strategy_registry_snapshot.json").exists()
    assert (out / "strategy_promotion_review.json").exists()
    assert (out / "capital_goal_status.json").exists()
    assert (out / "capital_goal_status.md").exists()
    assert registry_path.exists()
    assert not (out / "approval_record.json").exists()
    assert not (out / "manual_trade_sheet.csv").exists()

    pipeline = json.loads((out / "weekly_pipeline.json").read_text(encoding="utf-8"))
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    selection = json.loads((out / "candidate_selection.json").read_text(encoding="utf-8"))
    assert pipeline["weekly_decision"] in {"research_only", "pause_and_fix", "continue_paper"}
    assert summary["evidence"]["data_audit_status"] in {"PASS", "WATCH", "BLOCK"}
    assert selection["results"]
    assert "candidate_regime_validation_status" in selection["results"][0]
    assert selection["results"][0]["candidate_regime_validation_status"] in {"PASS", "WATCH", "BLOCK"}
    assert summary["evidence"]["run_manifest_purpose"] == "weekly_pipeline"
    assert "run_manifest_cache_sha256" in summary["evidence"]
    assert any(stage["name"] == "llm_review" for stage in pipeline["stages"])
    assert any(stage["name"] == "recent_candidate_research" for stage in pipeline["stages"])
    assert any(stage["name"] == "real_data_bootstrap" for stage in pipeline["stages"])
    assert any(stage["name"] == "run_manifest" for stage in pipeline["stages"])
    assert any(stage["name"] == "real_data_gate" for stage in pipeline["stages"])
    assert any(stage["name"] == "data_coverage" for stage in pipeline["stages"])
    assert any(stage["name"] == "walk_forward" for stage in pipeline["stages"])
    assert any(stage["name"] == "candidate_walk_forward" for stage in pipeline["stages"])
    assert any(stage["name"] == "candidate_factor_diagnostics" for stage in pipeline["stages"])
    assert any(stage["name"] == "candidate_regime_validation" for stage in pipeline["stages"])
    assert any(stage["name"] == "paper_stability" for stage in pipeline["stages"])
    assert any(stage["name"] == "paper_candidate_plan" for stage in pipeline["stages"])
    assert any(stage["name"] == "strategy_registry" for stage in pipeline["stages"])
    assert any(stage["name"] == "strategy_promotion_review" for stage in pipeline["stages"])
    assert any(stage["name"] == "capital_goal_status" for stage in pipeline["stages"])
    capital_stage = next(stage for stage in pipeline["stages"] if stage["name"] == "capital_goal_status")
    assert capital_stage.get("message")


def test_weekly_pipeline_can_prepare_micro_live_readiness_materials(
    tmp_path: Path,
) -> None:
    cfg = _cfg(tmp_path / "research.db", tmp_path / "results")

    result = run_weekly_pipeline(
        cfg,
        output_dir=tmp_path / "weekly_prepare_micro",
        registry_path=None,
        walk_forward_train_days=40,
        walk_forward_test_days=30,
        walk_forward_step_days=30,
        prepare_micro_live_readiness=True,
        micro_live_candidate="price_volume_defensive",
        micro_live_capital=100_000,
    )
    out = Path(result.output_dir)

    pipeline = json.loads((out / "weekly_pipeline.json").read_text(encoding="utf-8"))
    llm_review = json.loads((out / "llm_review.json").read_text(encoding="utf-8"))
    readiness = json.loads((out / "micro_live_readiness.json").read_text(encoding="utf-8"))
    manual = pd.read_csv(out / "manual_trade_sheet.csv")

    assert llm_review["intended_stage"] == "micro_live_ready"
    assert (out / "target_portfolio.json").exists()
    assert (out / "target_portfolio.csv").exists()
    assert (out / "manual_trade_sheet.csv").exists()
    assert (out / "risk_budget.json").exists()
    assert (out / "micro_live_readiness.md").exists()
    assert not (out / "approval_record.json").exists()
    assert any(stage["name"] == "manual_target_plan" for stage in pipeline["stages"])
    assert any(stage["name"] == "micro_live_readiness" for stage in pipeline["stages"])
    readiness_stage = next(stage for stage in pipeline["stages"] if stage["name"] == "micro_live_readiness")
    assert "REAL_DATA_BOOTSTRAP_BLOCK" in readiness_stage["message"]
    assert readiness["decision"] == "BLOCK"
    assert any(finding["code"] == "MISSING_APPROVAL" for finding in readiness["findings"])
    assert "instruction" in manual.columns
    assert set(manual["instruction"]) <= {"MANUAL_REFERENCE_ONLY_NO_BROKER_ORDER"}


def test_weekly_pipeline_cli_writes_artifacts(tmp_path: Path) -> None:
    cfg_path = tmp_path / "research.yaml"
    cfg_path.write_text(_cfg_yaml(tmp_path / "research.db", tmp_path / "results"), encoding="utf-8")
    output_dir = tmp_path / "weekly_cli"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_weekly_pipeline.py",
            "--config",
            str(cfg_path),
            "--output-dir",
            str(output_dir),
            "--years",
            "8",
            "--wf-train-days",
            "40",
            "--wf-test-days",
            "30",
            "--wf-step-days",
            "30",
            "--registry",
            str(tmp_path / "registry_cli.json"),
            "--prepare-micro-live-readiness",
            "--micro-live-candidate",
            "price_volume_defensive",
            "--micro-live-capital",
            "100000",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert (output_dir / "weekly_pipeline.json").exists()
    assert (output_dir / "weekly_review.md").exists()
    assert (output_dir / "target_portfolio.json").exists()
    assert (output_dir / "manual_trade_sheet.csv").exists()
    assert (output_dir / "micro_live_readiness.json").exists()
    assert not (output_dir / "approval_record.json").exists()
    review = json.loads((output_dir / "llm_review.json").read_text(encoding="utf-8"))
    readiness = json.loads((output_dir / "micro_live_readiness.json").read_text(encoding="utf-8"))
    assert review["intended_stage"] == "micro_live_ready"
    assert readiness["decision"] == "BLOCK"


def test_weekly_pipeline_cli_accepts_cache_override(tmp_path: Path) -> None:
    cfg_path = tmp_path / "research.yaml"
    default_cache = tmp_path / "default.db"
    override_cache = tmp_path / "override.db"
    cfg_path.write_text(_cfg_yaml(default_cache, tmp_path / "results"), encoding="utf-8")
    output_dir = tmp_path / "weekly_cli_override"
    _seed_minimal_cache(override_cache)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_weekly_pipeline.py",
            "--config",
            str(cfg_path),
            "--cache",
            str(override_cache),
            "--output-dir",
            str(output_dir),
            "--wf-train-days",
            "2",
            "--wf-test-days",
            "1",
            "--wf-step-days",
            "1",
            "--no-registry",
            "--review-stage",
            "research",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    review = json.loads((output_dir / "llm_review.json").read_text(encoding="utf-8"))
    assert manifest["cache_path"] == str(override_cache)
    assert review["intended_stage"] == "research"


def test_weekly_pipeline_uses_continuous_paper_state_dir(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path / "research.db", tmp_path / "results")
    paper_dir = tmp_path / "paper"
    paper_dir.mkdir()
    _write_stable_paper_dir(paper_dir)

    result = run_weekly_pipeline(
        cfg,
        output_dir=tmp_path / "weekly_with_paper",
        registry_path=None,
        paper_state_dir=paper_dir,
    )
    out = Path(result.output_dir)
    stability = json.loads((out / "paper_stability.json").read_text(encoding="utf-8"))
    daily_review = json.loads((out / "paper_daily_review.json").read_text(encoding="utf-8"))
    goal_status = json.loads((out / "capital_goal_status.json").read_text(encoding="utf-8"))

    assert stability["status"] == "PASS"
    assert stability["paper_dir"] == str(paper_dir)
    assert daily_review["as_of"] == "2024-03-01"
    assert daily_review["state"]["observed_days"] == 45
    assert any(
        item["name"] == "paper_stability" and item["status"] == "PASS"
        for item in goal_status["evidence"]
    )


def _cfg(cache_path: Path, results_dir: Path) -> Config:
    return Config(
        {
            "research": {
                "start": "2020-01-01",
                "end": "2020-06-30",
                "in_sample_end": "2020-05-15",
                "out_sample_start": "2020-05-18",
                "initial_cash": 1_000_000.0,
                "rebalance": "monthly",
                "allow_demo_data": True,
            },
            "data": {"source": "demo", "cache_path": str(cache_path)},
            "universe": {
                "mode": "all_a",
                "index_code": "000906",
                "include_st": False,
                "min_history_days": 20,
            },
            "strategy": {"n_holdings": 5, "max_weight": 0.10},
            "risk": {"max_drawdown_stop": 0.2},
            "broker": {
                "commission_rate": 0.0,
                "min_commission": 0.0,
                "stamp_tax": 0.0,
                "slippage_bps": 0.0,
                "price_limit_pct": 0.10,
                "lot_size": 100,
            },
            "output": {"results_dir": str(results_dir)},
        }
    )


def _seed_minimal_cache(cache: Path) -> None:
    from quantify.data.storage import BarStorage

    storage = BarStorage(cache)
    storage.save_calendar(["2020-01-02", "2020-01-03", "2020-01-06"])
    storage.save_stock_info(
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
        )
    )
    storage.save_bars(
        pd.DataFrame(
            {
                "symbol": ["600010", "600010", "600010", "000010", "000010", "000010"],
                "date": ["2020-01-02", "2020-01-03", "2020-01-06", "2020-01-02", "2020-01-03", "2020-01-06"],
                "open": [11.0, 11.1, 11.2, 21.0, 21.1, 21.2],
                "high": [11.5, 11.6, 11.7, 21.5, 21.6, 21.7],
                "low": [10.8, 11.0, 11.1, 20.8, 21.0, 21.1],
                "close": [11.2, 11.3, 11.4, 21.2, 21.3, 21.4],
                "volume": [1_500_000, 1_600_000, 1_700_000, 2_500_000, 2_600_000, 2_700_000],
                "amount": [16_800_000, 18_080_000, 19_380_000, 53_000_000, 55_380_000, 57_780_000],
            }
        )
    )


def _cfg_yaml(cache_path: Path, results_dir: Path) -> str:
    return f"""
research:
  start: "2020-01-01"
  end: "2020-06-30"
  in_sample_end: "2020-05-15"
  out_sample_start: "2020-05-18"
  initial_cash: 1000000.0
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
output:
  results_dir: "{results_dir.as_posix()}"
"""


def _write_stable_paper_dir(root: Path) -> None:
    (root / "paper_state.json").write_text(
        json.dumps(
            {
                "as_of": "2024-03-29",
                "observed_days": 45,
                "candidate": "core_multifactor",
                "initial_cash": 100_000,
                "cash": 20_000,
                "last_equity": 105_000,
                "position_count": 1,
                "order_count": 3,
                "rejected_order_count": 0,
                "broker_connection": "none",
            }
        ),
        encoding="utf-8",
    )
    dates = pd.bdate_range("2024-01-01", periods=45)
    equity = [100_000 * (1.001**idx) for idx in range(45)]
    pd.DataFrame(
        {
            "date": [date.date().isoformat() for date in dates],
            "equity": equity,
            "cash": [20_000.0] * 45,
            "rebalanced": [idx % 20 == 0 for idx in range(45)],
            "candidate": ["core_multifactor"] * 45,
            "broker_connection": ["none"] * 45,
        }
    ).to_csv(root / "paper_daily.csv", index=False)
    state = json.loads((root / "paper_state.json").read_text(encoding="utf-8"))
    state["as_of"] = str(dates[-1].date())
    (root / "paper_state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(
        {
            "timestamp": ["2024-01-02"] * 3,
            "symbol": ["AAA", "BBB", "CCC"],
            "direction": ["LONG"] * 3,
            "quantity": [100] * 3,
            "price": [10.0] * 3,
            "status": ["filled"] * 3,
            "reason": [""] * 3,
        }
    ).to_csv(root / "paper_orders.csv", index=False)
    pd.DataFrame(
        {
            "date": [str(dates[-1].date())],
            "symbol": ["AAA"],
            "quantity": [100],
            "available_qty": [100],
            "price": [10.0],
            "market_value": [1_000.0],
            "weight": [0.01],
        }
    ).to_csv(root / "paper_positions.csv", index=False)
