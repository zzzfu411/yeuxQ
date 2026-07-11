from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from quantify.research.candidate_hypotheses import (
    CandidateHypothesis,
    CandidateHypothesisCatalog,
    build_candidate_hypothesis_catalog,
)
from quantify.research.candidate_experiment_queue import (
    build_candidate_experiment_queue,
    write_candidate_experiment_queue,
)
from quantify.utils.config import Config


EXPECTED_EXPERIMENT_KEYS = {
    "priority",
    "candidate",
    "data_dependency",
    "intended_regimes",
    "objective",
    "rationale",
    "required_inputs",
    "command_sequence",
    "success_criteria",
    "falsification_tests",
    "stop_conditions",
    "artifacts",
    "prohibited_actions",
    "capital_goal_fit_tests",
    "minimum_evidence_window",
    "risk_budget_checks",
    "paper_entry_requirements",
    "anti_overfit_controls",
}
EXPECTED_ARTIFACTS = [
    "candidate_experiment_evidence.json",
    "candidate_walk_forward_report.json",
    "candidate_factor_diagnostics.json",
    "candidate_regime_validation_report.json",
    "candidate_stress_matrix.json",
    "candidate_selection.json",
    "llm_review.json",
]


def test_candidate_experiment_queue_writes_ordered_research_plan(tmp_path: Path) -> None:
    queue = build_candidate_experiment_queue(_cfg(tmp_path / "research.db"), as_of="2026-06-08")
    out = write_candidate_experiment_queue(queue, tmp_path / "out")

    payload = json.loads((out / "candidate_experiment_queue.json").read_text(encoding="utf-8"))
    markdown = (out / "candidate_experiment_queue.md").read_text(encoding="utf-8")
    names = [item["candidate"] for item in payload["experiments"]]

    assert payload["status"] == "WAITING_FOR_REAL_DATA"
    assert payload["experiment_count"] == 18
    assert names == [
        "price_volume_defensive",
        "low_turnover_price_volume",
        "low_turnover_low_concentration_price_volume",
        "trend_filtered_price_volume",
        "trend_filtered_quarterly_price_volume",
        "trend_filtered_quarterly_low_concentration_price_volume",
        "defensive_scaled_quarterly_price_volume",
        "stable_universe_slow_signal_price_volume",
        "long_momentum_liquidity_monthly_price_volume",
        "liquidity_neutral_momentum_guard_price_volume",
        "defensive_cash_guard_price_volume",
        "risk_off_cash_stop_price_volume",
        "regime_pause_price_volume",
        "core_multifactor",
        "defensive_low_vol",
        "trend_filtered_core",
        "value_low_vol",
        "momentum_quality",
    ]
    ohlcv = payload["experiments"][0]
    assert ohlcv["candidate"] == "price_volume_defensive"
    assert ohlcv["data_dependency"] == "ohlcv_only"
    assert "defensive" in ohlcv["intended_regimes"]
    assert any("point-in-time fundamentals are not required" in item for item in ohlcv["required_inputs"])
    low_turnover = payload["experiments"][1]
    assert low_turnover["candidate"] == "low_turnover_price_volume"
    assert low_turnover["data_dependency"] == "ohlcv_only"
    assert any("turnover" in item.lower() for item in low_turnover["success_criteria"])
    low_turnover_low_conc = payload["experiments"][2]
    assert low_turnover_low_conc["candidate"] == "low_turnover_low_concentration_price_volume"
    assert low_turnover_low_conc["data_dependency"] == "ohlcv_only"
    assert any("lower concentration" in item.lower() for item in low_turnover_low_conc["success_criteria"])
    filtered = payload["experiments"][3]
    assert filtered["candidate"] == "trend_filtered_price_volume"
    assert filtered["data_dependency"] == "ohlcv_only"
    assert any("cash drag" in item.lower() for item in filtered["success_criteria"])
    filtered_quarterly = payload["experiments"][4]
    assert filtered_quarterly["candidate"] == "trend_filtered_quarterly_price_volume"
    assert filtered_quarterly["data_dependency"] == "ohlcv_only"
    assert any("quarterly" in item.lower() for item in filtered_quarterly["success_criteria"])
    filtered_quarterly_low_conc = payload["experiments"][5]
    assert (
        filtered_quarterly_low_conc["candidate"]
        == "trend_filtered_quarterly_low_concentration_price_volume"
    )
    assert filtered_quarterly_low_conc["data_dependency"] == "ohlcv_only"
    assert any(
        "lower concentration" in item.lower()
        for item in filtered_quarterly_low_conc["success_criteria"]
    )
    defensive_scaled = payload["experiments"][6]
    assert defensive_scaled["candidate"] == "defensive_scaled_quarterly_price_volume"
    assert defensive_scaled["data_dependency"] == "ohlcv_only"
    assert any("defensive bucket" in item.lower() for item in defensive_scaled["success_criteria"])
    assert any("neutral bucket" in item.lower() for item in defensive_scaled["success_criteria"])
    slow_signal = payload["experiments"][7]
    assert slow_signal["candidate"] == "stable_universe_slow_signal_price_volume"
    assert slow_signal["data_dependency"] == "ohlcv_only"
    assert any("maintenance turnover" in item.lower() for item in slow_signal["success_criteria"])
    assert any("long momentum" in item.lower() for item in slow_signal["falsification_tests"])
    long_momentum_liquidity = payload["experiments"][8]
    assert long_momentum_liquidity["candidate"] == "long_momentum_liquidity_monthly_price_volume"
    assert long_momentum_liquidity["data_dependency"] == "ohlcv_only"
    assert "component ablation" in long_momentum_liquidity["rationale"].lower()
    assert any("monthly versus quarterly" in item.lower() for item in long_momentum_liquidity["falsification_tests"])
    assert any("single-component dependency" in item.lower() for item in long_momentum_liquidity["stop_conditions"])
    liquidity_neutral_guard = payload["experiments"][9]
    assert liquidity_neutral_guard["candidate"] == "liquidity_neutral_momentum_guard_price_volume"
    assert liquidity_neutral_guard["data_dependency"] == "ohlcv_only"
    assert "liquidity-neutral" in liquidity_neutral_guard["objective"].lower()
    assert any("defensive bucket" in item.lower() for item in liquidity_neutral_guard["success_criteria"])
    assert any("trend-filter-off" in item.lower() for item in liquidity_neutral_guard["falsification_tests"])
    cash_guard = payload["experiments"][10]
    assert cash_guard["candidate"] == "defensive_cash_guard_price_volume"
    assert cash_guard["data_dependency"] == "ohlcv_only"
    assert any("cash guard" in item.lower() for item in cash_guard["capital_goal_fit_tests"])
    cash_stop = payload["experiments"][11]
    assert cash_stop["candidate"] == "risk_off_cash_stop_price_volume"
    assert cash_stop["data_dependency"] == "ohlcv_only"
    assert "cash stop" in cash_stop["objective"].lower()
    regime_pause = payload["experiments"][12]
    assert regime_pause["candidate"] == "regime_pause_price_volume"
    assert regime_pause["data_dependency"] == "ohlcv_only"
    assert "explicit regime-pause" in regime_pause["objective"].lower()
    assert any("generic broad-trend tweak" in item.lower() for item in regime_pause["success_criteria"])
    assert all(item["command_sequence"] for item in payload["experiments"])
    assert all(item["success_criteria"] for item in payload["experiments"])
    assert all(item["falsification_tests"] for item in payload["experiments"])
    assert all(item["stop_conditions"] for item in payload["experiments"])
    assert all(item["capital_goal_fit_tests"] for item in payload["experiments"])
    assert all(item["minimum_evidence_window"] for item in payload["experiments"])
    assert all(item["risk_budget_checks"] for item in payload["experiments"])
    assert all(item["paper_entry_requirements"] for item in payload["experiments"])
    assert all(item["anti_overfit_controls"] for item in payload["experiments"])
    assert "not a strategy ranking or live trading instruction" in markdown
    assert "Do not connect experiments to real broker order submission." in markdown


def test_candidate_experiment_queue_has_stable_executable_contract(tmp_path: Path) -> None:
    queue = build_candidate_experiment_queue(_cfg(tmp_path / "research.db"), as_of="2026-06-08")
    payload = queue.to_dict()
    priorities = [item["priority"] for item in payload["experiments"]]

    assert priorities == sorted(priorities)
    assert len(priorities) == len(set(priorities))
    assert payload["required_evidence_before_running"] == [
        "Passing source QA review with filled data_source_qa_answers.json.",
        "Passing offline intake with non-template recent A-share daily bars.",
        "A run manifest tying config, cache, sample windows, and data fingerprints together.",
        "Data audit, real data gate, and data coverage reports with no unresolved BLOCK.",
    ]
    assert payload["prohibited_actions"] == [
        "Do not treat queue priority as expected return.",
        "Do not skip earlier evidence gates because a later backtest looks attractive.",
        "Do not connect experiments to real broker order submission.",
        "Do not let LLM output change queue priority or deterministic decisions.",
    ]
    for experiment in payload["experiments"]:
        assert set(experiment) == EXPECTED_EXPERIMENT_KEYS
        assert experiment["artifacts"] == EXPECTED_ARTIFACTS
        assert experiment["prohibited_actions"] == payload["prohibited_actions"]
        assert _scripts(experiment["command_sequence"]) == [
            "run_candidate_experiment_evidence.py",
            "run_candidate_walk_forward.py",
            "run_candidate_factor_diagnostics.py",
            "run_candidate_regime_validation.py",
            "run_candidate_stress_matrix.py",
            "run_candidate_selection.py",
            "run_llm_review.py",
        ]
        assert "--starting-capital 100000 --target-capital 1000000 --years 8" in (
            experiment["command_sequence"][5]
        )
        assert experiment["command_sequence"][6].endswith("--stage paper")
        assert f"--candidate {experiment['candidate']}" in experiment["command_sequence"][2]
        assert f"--candidate {experiment['candidate']}" in experiment["command_sequence"][4]
        assert "broker order" not in " ".join(experiment["command_sequence"]).lower()


def test_candidate_experiment_queue_adds_long_term_goal_controls(tmp_path: Path) -> None:
    queue = build_candidate_experiment_queue(_cfg(tmp_path / "research.db"), as_of="2026-06-08")
    payload = queue.to_dict()

    for experiment in payload["experiments"]:
        minimum_window = experiment["minimum_evidence_window"]
        assert minimum_window["minimum_total_trading_days"] == 720
        assert minimum_window["minimum_out_of_sample_trading_days"] == 240
        assert minimum_window["minimum_walk_forward_windows"] == 6
        assert minimum_window["sample_split_required"] is True
        assert "4-8" in minimum_window["minimum_paper_observation_weeks_before_micro_live_ready"]
        assert any("capital_goal_fit_review" in item for item in experiment["capital_goal_fit_tests"])
        assert any("starting_capital=100000" in item for item in experiment["capital_goal_fit_tests"])
        assert any("Max drawdown" in item for item in experiment["risk_budget_checks"])
        assert any("configured holdings=" in item for item in experiment["risk_budget_checks"])
        assert any("no unresolved BLOCK" in item for item in experiment["paper_entry_requirements"])
        assert any("must not connect to a real broker" in item for item in experiment["paper_entry_requirements"])
        assert any("pre-registered" in item for item in experiment["anti_overfit_controls"])
        assert any("cannot upgrade deterministic gates" in item for item in experiment["anti_overfit_controls"])


def test_candidate_experiment_queue_fences_ohlcv_only_candidate(tmp_path: Path) -> None:
    queue = build_candidate_experiment_queue(_cfg(tmp_path / "research.db"), as_of="2026-06-08")
    experiments = {item.candidate: item.to_dict() for item in queue.experiments}
    ohlcv = experiments["price_volume_defensive"]

    assert ohlcv["priority"] == 1
    assert ohlcv["data_dependency"] == "ohlcv_only"
    assert ohlcv["minimum_evidence_window"]["requires_pit_fundamental_history"] is False
    assert any("calendar, stock_info, and source QA" in item for item in ohlcv["required_inputs"])
    assert any("point-in-time fundamentals are not required" in item for item in ohlcv["required_inputs"])
    assert any("cannot validate valuation or accounting quality claims" in item for item in ohlcv["required_inputs"])
    assert any("without using fundamentals" in item for item in ohlcv["success_criteria"])
    assert any("adding vetted PIT fundamentals" in item for item in ohlcv["falsification_tests"])
    assert any("adjustment, source license, or export timestamp" in item for item in ohlcv["stop_conditions"])
    assert any("liquidity screen in disguise" in item for item in ohlcv["stop_conditions"])

    for candidate, experiment in experiments.items():
        if candidate in {
            "price_volume_defensive",
            "low_turnover_price_volume",
            "low_turnover_low_concentration_price_volume",
            "trend_filtered_price_volume",
            "trend_filtered_quarterly_price_volume",
            "trend_filtered_quarterly_low_concentration_price_volume",
            "defensive_scaled_quarterly_price_volume",
            "stable_universe_slow_signal_price_volume",
            "long_momentum_liquidity_monthly_price_volume",
            "liquidity_neutral_momentum_guard_price_volume",
            "defensive_cash_guard_price_volume",
            "risk_off_cash_stop_price_volume",
            "regime_pause_price_volume",
        }:
            continue
        assert experiment["minimum_evidence_window"]["requires_pit_fundamental_history"] is True
        assert not any("point-in-time fundamentals are not required" in item for item in experiment["required_inputs"])


def test_candidate_experiment_queue_contains_candidate_specific_anti_overfit_tests(
    tmp_path: Path,
) -> None:
    queue = build_candidate_experiment_queue(_cfg(tmp_path / "research.db"), as_of="2026-06-08")
    experiments = {item.candidate: item.to_dict() for item in queue.experiments}

    assert _contains(experiments["price_volume_defensive"], "Remove liquidity and low-volatility")
    assert _contains(experiments["low_turnover_price_volume"], "monthly versus quarterly")
    assert _contains(experiments["low_turnover_low_concentration_price_volume"], "original and lowered max_weight")
    assert _contains(experiments["trend_filtered_price_volume"], "missed-rebound cost")
    assert _contains(experiments["trend_filtered_quarterly_price_volume"], "monthly and quarterly cadence")
    assert _contains(
        experiments["trend_filtered_quarterly_low_concentration_price_volume"],
        "original and lower max_weight",
    )
    assert _contains(
        experiments["defensive_scaled_quarterly_price_volume"],
        "weak_trend and defensive_or_worse",
    )
    assert _contains(
        experiments["stable_universe_slow_signal_price_volume"],
        "quarterly and monthly cadence",
    )
    assert _contains(
        experiments["long_momentum_liquidity_monthly_price_volume"],
        "monthly versus quarterly cadence",
    )
    assert _contains(
        experiments["liquidity_neutral_momentum_guard_price_volume"],
        "trend-filter-off",
    )
    assert _contains(experiments["defensive_cash_guard_price_volume"], "trend-filter-off")
    assert _contains(experiments["risk_off_cash_stop_price_volume"], "full-cash")
    assert _contains(experiments["regime_pause_price_volume"], "pause-on versus pause-off")
    assert _contains(experiments["core_multifactor"], "Remove each factor component")
    assert _contains(experiments["defensive_low_vol"], "slippage and commission")
    assert _contains(experiments["trend_filtered_core"], "filtered and unfiltered core")
    assert _contains(experiments["value_low_vol"], "valuation fields removed or lagged")
    assert _contains(experiments["momentum_quality"], "hot industry or theme")
    for experiment in experiments.values():
        assert any("Any deterministic gate returns BLOCK." == item for item in experiment["stop_conditions"])
        assert any("demo-only, stale, template-based" in item for item in experiment["stop_conditions"])
        assert any("one factor component" in item for item in experiment["stop_conditions"])
        assert any("traceable rejects and fills" in item for item in experiment["stop_conditions"])
        assert any("Human approval is missing" in item for item in experiment["stop_conditions"])


def test_candidate_experiment_queue_parks_unknown_candidates_behind_bespoke_plan(
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
    experiments = [item.to_dict() for item in queue.experiments]
    parked = experiments[-1]

    assert [item["candidate"] for item in experiments] == ["price_volume_defensive", "new_unreviewed_alpha"]
    assert parked["priority"] == 99
    assert "bespoke experiment profile" in parked["objective"]
    assert any("candidate-specific falsification tests" in item for item in parked["falsification_tests"])
    assert any("Stop until a bespoke profile exists" in item for item in parked["stop_conditions"])
    assert any("bespoke capital-goal fit tests" in item for item in parked["capital_goal_fit_tests"])


def test_candidate_experiment_queue_markdown_renders_contract_sections(tmp_path: Path) -> None:
    queue = build_candidate_experiment_queue(_cfg(tmp_path / "research.db"), as_of="2026-06-08")
    markdown = queue.to_markdown()

    for experiment in queue.experiments:
        assert f"### {experiment.priority}. `{experiment.candidate}`" in markdown
        assert f"- Data dependency: `{experiment.data_dependency}`" in markdown
        assert "Intended regimes:" in markdown
    assert "Command sequence:" in markdown
    assert "Minimum evidence window:" in markdown
    assert "Capital goal fit tests:" in markdown
    assert "Risk budget checks:" in markdown
    assert "Paper entry requirements:" in markdown
    assert "Anti-overfit controls:" in markdown
    assert "Success criteria:" in markdown
    assert "Falsification tests:" in markdown
    assert "Stop conditions:" in markdown


def test_candidate_experiment_queue_cli_writes_outputs(tmp_path: Path) -> None:
    cfg_path = tmp_path / "research.yaml"
    cfg_path.write_text(_cfg_yaml(tmp_path / "research.db"), encoding="utf-8")
    out = tmp_path / "queue"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/write_candidate_experiment_queue.py",
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
    payload = json.loads((out / "candidate_experiment_queue.json").read_text(encoding="utf-8"))
    assert payload["as_of"] == "2026-06-08"
    assert (out / "candidate_experiment_queue.md").exists()


def _scripts(commands: list[str]) -> list[str]:
    scripts: list[str] = []
    for command in commands:
        parts = command.split()
        scripts.append(Path(next(part for part in parts if part.endswith(".py"))).name)
    return scripts


def _contains(experiment: dict[str, object], needle: str) -> bool:
    values: list[str] = []
    for key in [
        "required_inputs",
        "success_criteria",
        "falsification_tests",
        "stop_conditions",
        "capital_goal_fit_tests",
        "risk_budget_checks",
        "paper_entry_requirements",
        "anti_overfit_controls",
    ]:
        raw = experiment.get(key, [])
        if isinstance(raw, list):
            values.extend(str(item) for item in raw)
    return needle in "\n".join(values)


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
