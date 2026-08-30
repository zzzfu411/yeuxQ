from __future__ import annotations

from pathlib import Path
import sys

import examples.run_walk_forward as walk_forward_cli
from examples.run_research import _load_config as load_research_config
from examples.run_robustness import _load_config as load_robustness_config
from examples.run_robustness import _select_scenarios
from examples.run_candidate_selection import _load_config as load_candidate_selection_config
from examples.run_candidate_research_precheck import _load_config as load_candidate_precheck_config
from examples.run_candidate_walk_forward import _load_config as load_candidate_walk_forward_config
from examples.run_walk_forward import _load_config as load_walk_forward_config


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


def test_run_walk_forward_cache_override_preserves_config(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    _write_config(config, tmp_path / "original.db")

    cfg = load_walk_forward_config(str(config), cache_path=str(tmp_path / "override.db"))

    assert cfg.data.cache_path == str(tmp_path / "override.db")
    assert cfg.research.start == "2024-01-02"
    assert cfg.universe.index_code == "000906"


def test_run_walk_forward_cli_uses_cache_override(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "config.yaml"
    original_cache = tmp_path / "original.db"
    override_cache = tmp_path / "override.db"
    output_dir = tmp_path / "output"
    _write_config(config, original_cache)

    storage = object()
    report = type("Report", (), {"status": "PASS"})()
    calls: dict[str, object] = {}

    def fake_storage(cache_path: str):
        calls["storage_cache_path"] = cache_path
        return storage

    def fake_provider(received_storage):
        assert received_storage is storage
        calls["provider_storage"] = received_storage
        created_provider = type(
            "Provider",
            (),
            {
                "all_symbols": lambda self: ["000001"],
                "trading_days": lambda self, start, end: [start, end],
            },
        )()
        calls["provider"] = created_provider
        return created_provider

    def fake_run_walk_forward(received_provider, cfg, **kwargs):
        calls["report_provider"] = received_provider
        calls["report_cache_path"] = cfg.data.cache_path
        calls["report_strategy_holdings"] = cfg.strategy.n_holdings
        calls["report_kwargs"] = kwargs
        return report

    def fake_write_report(received_report, received_output_dir):
        calls["written_report"] = received_report
        calls["output_dir"] = received_output_dir
        return received_output_dir

    monkeypatch.setattr(walk_forward_cli, "BarStorage", fake_storage)
    monkeypatch.setattr(walk_forward_cli, "DataProvider", fake_provider)
    monkeypatch.setattr(walk_forward_cli, "run_walk_forward", fake_run_walk_forward)
    monkeypatch.setattr(walk_forward_cli, "write_walk_forward_report", fake_write_report)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_walk_forward.py",
            "--config",
            str(config),
            "--cache",
            str(override_cache),
            "--output-dir",
            str(output_dir),
            "--train-days",
            "90",
            "--test-days",
            "30",
            "--step-days",
            "30",
        ],
    )

    walk_forward_cli.main()

    assert calls["storage_cache_path"] == str(override_cache)
    assert calls["provider_storage"] is storage
    assert calls["report_provider"] is calls["provider"]
    assert calls["report_cache_path"] == str(override_cache)
    assert calls["report_strategy_holdings"] == 2
    assert calls["report_kwargs"] == {
        "train_days": 90,
        "purge_days": 5,
        "selection_days": 20,
        "embargo_days": 5,
        "test_days": 30,
        "step_days": 30,
        "mode": "expanding",
    }
    assert calls["written_report"] is report
    assert calls["output_dir"] == output_dir


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
