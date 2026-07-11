from __future__ import annotations

from pathlib import Path

from examples.run_research import _load_config as load_research_config
from examples.run_robustness import _load_config as load_robustness_config
from examples.run_robustness import _select_scenarios
from examples.run_candidate_selection import _load_config as load_candidate_selection_config
from examples.run_candidate_research_precheck import _load_config as load_candidate_precheck_config
from examples.run_candidate_walk_forward import _load_config as load_candidate_walk_forward_config


def test_run_research_cache_override_preserves_config(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    _write_config(config, tmp_path / "original.db")

    cfg = load_research_config(str(config), cache_path=str(tmp_path / "override.db"))

    assert cfg.data.cache_path == str(tmp_path / "override.db")
    assert cfg.research.start == "2024-01-02"
    assert cfg.universe.index_code == "000906"


def test_run_robustness_cache_override_preserves_config(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    _write_config(config, tmp_path / "original.db")

    cfg = load_robustness_config(str(config), cache_path=str(tmp_path / "override.db"))

    assert cfg.data.cache_path == str(tmp_path / "override.db")
    assert cfg.research.end == "2024-01-03"
    assert cfg.strategy.n_holdings == 2


def test_run_robustness_selects_named_scenarios(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    _write_config(config, tmp_path / "original.db")
    cfg = load_robustness_config(str(config))

    scenarios = _select_scenarios(cfg, ["baseline", "high_cost"])

    assert [scenario.name for scenario in scenarios] == ["baseline", "high_cost"]


def test_candidate_cli_cache_overrides_preserve_config(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    _write_config(config, tmp_path / "original.db")

    selection_cfg = load_candidate_selection_config(str(config), cache_path=str(tmp_path / "selection.db"))
    walk_cfg = load_candidate_walk_forward_config(str(config), cache_path=str(tmp_path / "walk.db"))
    precheck_cfg = load_candidate_precheck_config(str(config), cache_path=str(tmp_path / "precheck.db"))

    assert selection_cfg.data.cache_path == str(tmp_path / "selection.db")
    assert walk_cfg.data.cache_path == str(tmp_path / "walk.db")
    assert precheck_cfg.data.cache_path == str(tmp_path / "precheck.db")
    assert selection_cfg.research.start == "2024-01-02"
    assert walk_cfg.strategy.n_holdings == 2
    assert precheck_cfg.universe.index_code == "000906"


def _write_config(path: Path, cache: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "research:",
                '  start: "2024-01-02"',
                '  end: "2024-01-03"',
                '  in_sample_end: "2024-01-02"',
                '  out_sample_start: "2024-01-03"',
                "  initial_cash: 1000000.0",
                "  rebalance: monthly",
                "  allow_demo_data: false",
                "data:",
                "  source: akshare",
                f"  cache_path: '{cache}'",
                "  adjust: qfq",
                "universe:",
                "  index_code: '000906'",
                "  mode: all_a",
                "  include_st: false",
                "  min_history_days: 1",
                "strategy:",
                "  n_holdings: 2",
                "  max_weight: 0.10",
                "risk:",
                "  max_drawdown_stop: 0.2",
                "broker:",
                "  commission_rate: 0.0",
                "  min_commission: 0.0",
                "  stamp_tax: 0.0",
                "  slippage_bps: 0.0",
                "  price_limit_pct: 0.10",
                "  lot_size: 100",
                "output:",
                f"  results_dir: '{path.parent / 'results'}'",
            ]
        ),
        encoding="utf-8",
    )
