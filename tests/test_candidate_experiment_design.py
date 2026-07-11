from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys

from quantify.research.candidate_experiment_design import (
    build_candidate_experiment_design_matrix,
    write_candidate_experiment_design_matrix,
)
from quantify.research.candidate_experiment_queue import build_candidate_experiment_queue
from quantify.research.candidate_hypotheses import (
    CandidateHypothesis,
    CandidateHypothesisCatalog,
    build_candidate_hypothesis_catalog,
)
from quantify.utils.config import Config


BASE_SCENARIOS = {
    "baseline",
    "wider_basket",
    "lower_concentration",
    "rebalance_alt",
    "turnover_control",
    "stability_control",
    "score_smoothing",
    "high_cost",
}
TREND_SCENARIOS = BASE_SCENARIOS | {"trend_filter_off", "trend_filter_stronger"}


def test_candidate_experiment_design_matrix_preregisters_scenario_coverage(
    tmp_path: Path,
) -> None:
    matrix = build_candidate_experiment_design_matrix(
        _cfg(tmp_path / "research.db"),
        as_of="2026-06-08",
    )
    payload = matrix.to_dict()
    rows = payload["rows"]

    assert payload["artifact_type"] == "candidate_experiment_design_matrix"
    assert payload["status"] == "WAITING_FOR_REAL_DATA"
    assert payload["candidate_count"] == 18
    assert payload["scenario_count"] == 162
    assert payload["can_run_research"] is False
    assert payload["can_enter_paper"] is False
    assert payload["can_generate_broker_orders"] is False
    assert "price_volume_defensive" == payload["candidates"][0]
    assert "first_million_pipeline decision is not BLOCK." in payload["required_before_execution"]
    assert any("Do not treat this design matrix as a strategy ranking" in item for item in payload["prohibited_actions"])

    by_candidate = _rows_by_candidate(rows)
    assert {row["scenario"] for row in by_candidate["price_volume_defensive"]} == BASE_SCENARIOS
    assert {row["scenario"] for row in by_candidate["trend_filtered_price_volume"]} == TREND_SCENARIOS
    assert {row["scenario"] for row in by_candidate["trend_filtered_core"]} == TREND_SCENARIOS

    price_volume_rows = by_candidate["price_volume_defensive"]
    assert all(row["allowed_stage"] == "research" for row in price_volume_rows)
    assert all(row["status"] == "PLANNED" for row in price_volume_rows)
    assert all(row["can_enter_paper"] is False for row in rows)
    assert all(row["can_generate_broker_orders"] is False for row in rows)
    assert all("candidate_selection.json" in row["required_outputs"] for row in rows)
    assert all("llm_review.json" in row["required_outputs"] for row in rows)


def test_candidate_experiment_design_matrix_maps_stress_scenarios_to_roles(
    tmp_path: Path,
) -> None:
    matrix = build_candidate_experiment_design_matrix(_cfg(tmp_path / "research.db"))
    rows = _rows_by_key(matrix.to_dict()["rows"])

    assert rows[("price_volume_defensive", "baseline")]["scenario_family"] == "baseline"
    assert rows[("price_volume_defensive", "wider_basket")]["scenario_family"] == "concentration"
    assert rows[("price_volume_defensive", "lower_concentration")]["scenario_family"] == "concentration"
    assert rows[("price_volume_defensive", "rebalance_alt")]["scenario_family"] == "rebalance"
    assert rows[("price_volume_defensive", "turnover_control")]["scenario_family"] == "turnover_stability"
    assert rows[("price_volume_defensive", "stability_control")]["scenario_family"] == "turnover_stability"
    assert rows[("price_volume_defensive", "score_smoothing")]["scenario_family"] == "turnover_stability"
    assert rows[("price_volume_defensive", "high_cost")]["scenario_family"] == "cost_stress"
    assert (
        rows[("trend_filtered_price_volume", "trend_filter_off")]["scenario_family"]
        == "trend_filter_ablation"
    )

    high_cost = rows[("price_volume_defensive", "high_cost")]
    assert high_cost["cost_multiplier"] == 2.0
    assert any("Higher cost assumptions" in item for item in high_cost["pass_conditions"])
    assert "harsher execution costs" in high_cost["falsification_role"]

    smoothing = rows[("price_volume_defensive", "score_smoothing")]
    assert smoothing["score_smoothing_observations"] >= 3
    assert "score smoothing" in smoothing["falsification_role"].lower()

    command = rows[("trend_filtered_price_volume", "trend_filter_off")]["command_hint"]
    assert "run_candidate_stress_matrix.py" in command
    assert "--candidate trend_filtered_price_volume" in command
    assert "--scenario trend_filter_off" in command
    assert "broker" not in command.lower()


def test_candidate_experiment_design_matrix_writes_json_markdown_and_csv(
    tmp_path: Path,
) -> None:
    matrix = build_candidate_experiment_design_matrix(
        _cfg(tmp_path / "research.db"),
        as_of="2026-06-08",
    )
    out = write_candidate_experiment_design_matrix(matrix, tmp_path / "out")

    payload = json.loads((out / "candidate_experiment_design_matrix.json").read_text(encoding="utf-8"))
    markdown = (out / "candidate_experiment_design_matrix.md").read_text(encoding="utf-8")
    with (out / "candidate_experiment_design_matrix.csv").open(encoding="utf-8-sig", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))

    assert payload["as_of"] == "2026-06-08"
    assert payload["scenario_count"] == len(csv_rows)
    assert "not a strategy ranking, paper approval, or broker workflow" in markdown
    assert "| `price_volume_defensive` | `baseline` |" in markdown
    assert "Do not connect any command here to real broker order submission." in markdown
    assert csv_rows[0]["candidate"] == "price_volume_defensive"
    assert csv_rows[0]["can_enter_paper"] == "False"
    assert csv_rows[0]["can_generate_broker_orders"] == "False"


def test_candidate_experiment_design_matrix_parks_unknown_candidate_behind_bespoke_plan(
    tmp_path: Path,
) -> None:
    cfg = _cfg(tmp_path / "research.db")
    known = build_candidate_hypothesis_catalog(cfg, as_of="2026-06-08").candidates[0]
    unknown = CandidateHypothesis(
        name="new_unreviewed_alpha",
        description="Unreviewed alpha",
        hypothesis="Needs bespoke review.",
        intended_regimes=["unknown"],
        factors=["momentum_63"],
        key_risks=["No reviewed risk profile."],
        required_validation_gates=["Reviewed validation plan."],
        automatic_downgrade_conditions=["Downgrade until reviewed."],
        paper_readiness_requirements=["Do not enter paper."],
        prohibited_actions=["Do not trade."],
        n_holdings=10,
        max_weight=0.10,
        rebalance="monthly",
        data_dependency="ohlcv_only",
        trend_filter=False,
        trend_scale=0.35,
    )
    catalog = CandidateHypothesisCatalog(
        status="RESEARCH_ONLY",
        as_of="2026-06-08",
        candidate_count=2,
        candidates=[unknown, known],
        required_evidence_before_screening=[],
        prohibited_actions=[],
    )
    queue = build_candidate_experiment_queue(cfg, as_of="2026-06-08", catalog=catalog)

    matrix = build_candidate_experiment_design_matrix(cfg, queue=queue, as_of="2026-06-08")
    rows = matrix.to_dict()["rows"]
    bespoke = [row for row in rows if row["candidate"] == "new_unreviewed_alpha"]

    assert len(bespoke) == 1
    assert bespoke[0]["priority"] == 99
    assert bespoke[0]["scenario"] == "bespoke_plan_required"
    assert bespoke[0]["scenario_family"] == "bespoke_review"
    assert any("bespoke scenario design" in item for item in bespoke[0]["pass_conditions"])
    assert bespoke[0]["can_enter_paper"] is False
    assert bespoke[0]["can_generate_broker_orders"] is False


def test_candidate_experiment_design_matrix_cli_writes_outputs(tmp_path: Path) -> None:
    cfg_path = tmp_path / "research.yaml"
    cfg_path.write_text(_cfg_yaml(tmp_path / "research.db"), encoding="utf-8")
    out = tmp_path / "design"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/write_candidate_experiment_design_matrix.py",
            "--config",
            str(cfg_path),
            "--output-dir",
            str(out),
            "--as-of",
            "2026-06-08",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    payload = json.loads((out / "candidate_experiment_design_matrix.json").read_text(encoding="utf-8"))
    assert payload["as_of"] == "2026-06-08"
    assert (out / "candidate_experiment_design_matrix.md").exists()
    assert (out / "candidate_experiment_design_matrix.csv").exists()


def _rows_by_candidate(rows: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(str(row["candidate"]), []).append(row)
    return grouped


def _rows_by_key(
    rows: list[dict[str, object]],
) -> dict[tuple[str, str], dict[str, object]]:
    return {(str(row["candidate"]), str(row["scenario"])): row for row in rows}


def _cfg(cache_path: Path) -> Config:
    return Config(
        {
            "research": {
                "start": "2024-01-02",
                "end": "2024-01-03",
                "initial_cash": 1_000_000.0,
                "rebalance": "monthly",
            },
            "universe": {
                "mode": "all_a",
                "index_code": "000906",
                "include_st": False,
                "min_history_days": 1,
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
            "data": {"cache_path": str(cache_path), "source": "csv"},
            "output": {"results_dir": str(cache_path.parent)},
        }
    )


def _cfg_yaml(cache_path: Path) -> str:
    return f"""
research:
  start: "2024-01-02"
  end: "2024-01-03"
  in_sample_end: "2024-01-02"
  out_sample_start: "2024-01-03"
  initial_cash: 1000000.0
  rebalance: monthly
  allow_demo_data: false
data:
  source: csv
  cache_path: "{cache_path.as_posix()}"
  adjust: qfq
universe:
  mode: all_a
  index_code: "000906"
  include_st: false
  min_history_days: 1
strategy:
  name: multi_factor
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
  results_dir: "{cache_path.parent.as_posix()}"
"""
