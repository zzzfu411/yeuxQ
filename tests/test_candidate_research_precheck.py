from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.data.storage import BarStorage
from quantify.research.candidate_precheck import build_candidate_research_precheck_report
from quantify.research.demo_data import seed_demo_data


def test_candidate_research_precheck_cli_runs_without_launch_gate_for_real_config(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "research.db"
    seed_demo_data(BarStorage(cache), "2020-01-01", "2020-12-31")
    cfg_path = tmp_path / "research_recent.yaml"
    cfg_path.write_text(_cfg_yaml(cache).replace("allow_demo_data: true", "allow_demo_data: false"), encoding="utf-8")
    output_dir = tmp_path / "precheck"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_candidate_research_precheck.py",
            "--config",
            str(cfg_path),
            "--output-dir",
            str(output_dir),
            "--candidate",
            "price_volume_defensive",
            "--train-days",
            "40",
            "--test-days",
            "30",
            "--step-days",
            "30",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    payload = json.loads((output_dir / "candidate_research_precheck.json").read_text(encoding="utf-8"))
    notice = json.loads((output_dir / "research_precheck_notice.json").read_text(encoding="utf-8"))
    selection = json.loads((output_dir / "candidate_selection.json").read_text(encoding="utf-8"))
    assert payload == notice
    assert payload["status"] == "RESEARCH_ONLY"
    assert payload["promotion_decision"] == "BLOCK"
    assert payload["can_satisfy_launch_gate"] is False
    assert payload["can_enter_paper"] is False
    assert payload["can_enter_micro_live_ready"] is False
    assert payload["can_generate_broker_orders"] is False
    assert payload["factor_diagnostics_status"] == "SKIPPED"
    assert payload["regime_validation_status"] == "SKIPPED"
    assert payload["selection_scope"] == "latest_precheck_window"
    assert payload["selection_start"]
    assert payload["selection_end"]
    assert payload["walk_forward_status"] in {"PASS", "WATCH", "BLOCK"}
    assert payload["candidates"] == ["price_volume_defensive"]
    assert "candidate_research_precheck.json" in payload["generated_artifacts"]
    assert any("--gate-report-dir" in item for item in payload["prohibited_actions"])
    assert any("Full-sample candidate_selection" in item for item in payload["missing_promotion_evidence"])
    assert any("candidate_factor_diagnostics.json was not generated" in item for item in payload["missing_promotion_evidence"])
    assert len(selection["results"]) == 1
    assert selection["results"][0]["candidate_walk_forward_status"] != "UNKNOWN"
    walk_forward = json.loads((output_dir / "candidate_walk_forward_report.json").read_text(encoding="utf-8"))
    assert walk_forward["window_count"] == 3
    assert any("limited to the latest 3" in warning for warning in walk_forward["warnings"])
    assert (output_dir / "candidate_walk_forward_report.md").exists()
    assert (output_dir / "candidate_selection.csv").exists()
    next_experiments = json.loads(
        (output_dir / "candidate_next_experiments.json").read_text(encoding="utf-8")
    )
    assert next_experiments["status"] == "RESEARCH_ONLY"
    assert next_experiments["promotion_decision"] == "BLOCK"
    assert next_experiments["can_enter_paper"] is False
    assert next_experiments["can_generate_broker_orders"] is False
    assert (output_dir / "candidate_next_experiments.md").exists()
    assert (output_dir / "candidate_next_experiments.csv").exists()


def test_candidate_research_precheck_cli_can_include_optional_evidence(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "research.db"
    _seed_small_cache(cache)
    cfg_path = tmp_path / "research.yaml"
    cfg_path.write_text(_cfg_yaml(cache), encoding="utf-8")
    output_dir = tmp_path / "precheck"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_candidate_research_precheck.py",
            "--config",
            str(cfg_path),
            "--output-dir",
            str(output_dir),
            "--candidate",
            "low_turnover_price_volume",
            "--train-days",
            "40",
            "--test-days",
            "30",
            "--step-days",
            "30",
            "--include-factor-diagnostics",
            "--include-regime-validation",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((output_dir / "candidate_research_precheck.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["candidates"] == ["low_turnover_price_volume"]
    assert payload["factor_diagnostics_status"] in {"PASS", "WATCH", "BLOCK"}
    assert payload["regime_validation_status"] in {"PASS", "WATCH", "BLOCK"}
    assert (output_dir / "candidate_factor_diagnostics.json").exists()
    assert (output_dir / "candidate_regime_validation_report.json").exists()


def test_candidate_research_precheck_report_fences_promotion() -> None:
    report = build_candidate_research_precheck_report(
        candidates=["low_turnover_price_volume"],
        generated_artifacts=["candidate_walk_forward_report.json", "candidate_selection.json"],
        candidate_selection={
            "status": "PASS",
            "top_candidate": "low_turnover_price_volume",
            "selected_candidate": "low_turnover_price_volume",
        },
        candidate_walk_forward={"status": "WATCH"},
    )
    payload = report.to_dict()
    markdown = report.to_markdown()

    assert payload["status"] == "RESEARCH_ONLY"
    assert payload["promotion_decision"] == "BLOCK"
    assert payload["research_selection_status"] == "PASS"
    assert payload["research_top_candidate"] == "low_turnover_price_volume"
    assert payload["can_satisfy_launch_gate"] is False
    assert payload["can_enter_paper"] is False
    assert payload["selection_scope"] == "latest_precheck_window"
    assert payload["factor_diagnostics_status"] == "SKIPPED"
    assert payload["regime_validation_status"] == "SKIPPED"
    assert "cannot satisfy a candidate launch gate" in markdown
    assert "Do not enter paper" in markdown


def _cfg_yaml(cache_path: Path) -> str:
    return f"""
research:
  start: "2020-01-01"
  end: "2020-12-31"
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
"""


def _seed_small_cache(cache: Path) -> None:
    storage = BarStorage(cache)
    symbols = [f"600{i:03d}" for i in range(1, 9)]
    dates = pd.bdate_range("2020-01-01", "2020-12-31")
    storage.save_calendar(dates)
    storage.save_stock_info(
        pd.DataFrame(
            {
                "symbol": symbols,
                "name": [f"alpha_{i}" for i, _symbol in enumerate(symbols, start=1)],
                "exchange": ["SSE"] * len(symbols),
                "list_date": ["2015-01-01"] * len(symbols),
                "delist_date": [""] * len(symbols),
                "industry": ["test"] * len(symbols),
                "is_st": [0] * len(symbols),
            }
        )
    )
    frames = []
    for idx, symbol in enumerate(symbols, start=1):
        close = 10.0 + idx + pd.Series(range(len(dates)), dtype=float) * (0.0002 + idx * 0.00002) * 10
        volume = 1_000_000 + idx * 10_000
        frames.append(
            pd.DataFrame(
                {
                    "symbol": symbol,
                    "date": [day.date().isoformat() for day in dates],
                    "open": close * 0.999,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": volume,
                    "amount": close * volume,
                }
            )
        )
    storage.save_bars(pd.concat(frames, ignore_index=True))
