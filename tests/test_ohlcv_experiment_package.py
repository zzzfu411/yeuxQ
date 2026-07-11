from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.data.csv_contract import write_research_csv_templates
from quantify.data.ohlcv_experiment_package import (
    build_ohlcv_experiment_package_preflight,
    write_ohlcv_experiment_package_preflight,
)
from quantify.data.source_qa import (
    build_data_source_qa,
    build_data_source_qa_answers,
    write_data_source_qa,
    write_data_source_qa_answers,
)


def test_ohlcv_experiment_package_blocks_template_rows_and_missing_source_qa(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    write_research_csv_templates(data_dir)
    _write_config(config, cache)

    preflight = build_ohlcv_experiment_package_preflight(
        data_dir=data_dir,
        report_dir=report_dir,
        config_path=config,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
    )
    out = write_ohlcv_experiment_package_preflight(preflight, report_dir)

    payload = json.loads((out / "ohlcv_experiment_package.json").read_text(encoding="utf-8"))
    rows = (out / "ohlcv_experiment_package.csv").read_text(encoding="utf-8-sig")
    markdown = (out / "ohlcv_experiment_package.md").read_text(encoding="utf-8")

    assert payload["decision"] == "BLOCK"
    assert payload["candidate"] == "price_volume_defensive"
    assert payload["allowed_stage"] == "none"
    assert payload["launch_research_allowed"] is False
    assert payload["bars"]["state"] == "template_sample_rows"
    assert any("bars_csv" in item for item in payload["blockers"])
    assert any("source_qa_answers" in item for item in payload["blockers"])
    assert any("market_context" in item for item in payload["blockers"])
    assert "source_qa_answers" in rows
    assert "not a strategy signal" in markdown
    assert any("real broker order submission" in item for item in payload["prohibited_actions"])


def test_ohlcv_experiment_package_watches_with_ohlcv_only_snapshot_context(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    _write_bars_only_export(data_dir)
    _write_config(config, cache)
    _write_source_qa_answers(data_dir, config)
    _write_reviewed_market_snapshot(report_dir)

    preflight = build_ohlcv_experiment_package_preflight(
        data_dir=data_dir,
        report_dir=report_dir,
        config_path=config,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
    )

    assert preflight.decision == "WATCH"
    assert preflight.launch_research_allowed is True
    assert preflight.allowed_stage == "guarded_research_only"
    assert preflight.bars["state"] == "present"
    assert preflight.bars["symbol_count"] == 2
    assert preflight.bars["trading_day_count"] == 2
    assert preflight.source_qa["review_status"] == "PASS"
    assert preflight.market_context["source"] == "market_context_snapshot"
    assert preflight.market_context["decision"] == "WATCH"
    assert any("OHLCV-only" in item for item in preflight.prohibited_actions)
    assert any("PIT-fundamental candidates" in item for item in preflight.next_actions)


def test_ohlcv_experiment_package_passes_with_cache_market_regime(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    _write_full_export(data_dir)
    _write_config(config, cache)
    _write_source_qa_answers(data_dir, config)
    _write_json(report_dir / "market_regime.json", {"status": "PASS", "label": "neutral", "as_of": "2024-01-03"})

    preflight = build_ohlcv_experiment_package_preflight(
        data_dir=data_dir,
        report_dir=report_dir,
        config_path=config,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
    )

    assert preflight.decision == "PASS"
    assert preflight.launch_research_allowed is True
    assert preflight.market_context["source"] == "market_regime"
    assert preflight.evidence_path["status"] == "PASS"
    assert not preflight.blockers
    assert any("research" in command for command in preflight.next_commands)


def test_ohlcv_experiment_package_blocks_small_smoke_coverage(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    _write_full_export(data_dir)
    _write_config(config, cache)
    _write_source_qa_answers(data_dir, config)
    _write_json(report_dir / "market_regime.json", {"status": "PASS", "label": "neutral", "as_of": "2024-01-03"})

    preflight = build_ohlcv_experiment_package_preflight(
        data_dir=data_dir,
        report_dir=report_dir,
        config_path=config,
        min_symbols=300,
        min_trading_days=240,
        as_of="2024-01-03",
    )

    assert preflight.decision == "BLOCK"
    assert preflight.launch_research_allowed is False
    assert any("bars_coverage" in item for item in preflight.blockers)
    assert any("schema/import smoke evidence only" in item for item in preflight.blockers)


def test_ohlcv_experiment_package_cli_writes_block_report(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    write_research_csv_templates(data_dir)
    _write_config(config, cache)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_ohlcv_experiment_package.py",
            "--data-dir",
            str(data_dir),
            "--report-dir",
            str(report_dir),
            "--config",
            str(config),
            "--min-symbols",
            "2",
            "--min-trading-days",
            "2",
            "--as-of",
            "2024-01-03",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((report_dir / "ohlcv_experiment_package.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["decision"] == "BLOCK"
    assert (report_dir / "ohlcv_experiment_package.md").exists()
    assert (report_dir / "ohlcv_experiment_package.csv").exists()


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
                "  source: csv",
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


def _write_source_qa_answers(data_dir: Path, config: Path) -> None:
    checklist = build_data_source_qa(
        config_path=config,
        output_dir=data_dir,
        min_symbols=2,
        as_of="2024-01-03",
    )
    write_data_source_qa(checklist, data_dir)
    answers = build_data_source_qa_answers(
        checklist_path=data_dir / "data_source_qa.json",
        data_vendor_or_broker="unit-test vendor",
        terminal_or_product_name="unit-test terminal",
        export_operator="tester",
        exported_at_local_time="2024-01-03 18:00:00",
        price_adjustment="qfq",
        price_adjustment_evidence="vendor export setting says qfq",
        license_or_usage_scope="research and paper trading only",
        license_evidence="unit-test license note",
        point_in_time_evidence=(
            "OHLCV-only package; PIT fundamentals and PIT index constituents are not supplied, "
            "so fundamental-dependent candidates remain blocked."
        ),
        reviewed_by="tester",
        reviewed_at="2024-01-03",
    )
    write_data_source_qa_answers(answers, data_dir / "data_source_qa_answers.json")


def _write_bars_only_export(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    _bars().to_csv(data_dir / "bars.csv", index=False)


def _write_full_export(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    _bars().to_csv(data_dir / "bars.csv", index=False)
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
    ).to_csv(data_dir / "stock_info.csv", index=False)
    pd.DataFrame({"date": ["2024-01-02", "2024-01-03", "2024-01-04"], "is_open": [1, 1, 0]}).to_csv(
        data_dir / "calendar.csv",
        index=False,
    )
    pd.DataFrame(
        {
            "symbol": ["600010", "000010"],
            "date": ["2024-01-03", "2024-01-03"],
            "is_suspended": [0, 0],
        }
    ).to_csv(data_dir / "suspensions.csv", index=False)


def _bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["600010", "600010", "000010", "000010"],
            "date": ["2024-01-02", "2024-01-03", "2024-01-02", "2024-01-03"],
            "open": [11.0, 11.1, 21.0, 21.1],
            "high": [11.5, 11.6, 21.5, 21.6],
            "low": [10.8, 11.0, 20.8, 21.0],
            "close": [11.2, 11.3, 21.2, 21.3],
            "volume": [1_500_000, 1_600_000, 2_500_000, 2_600_000],
            "amount": [16_800_000, 18_080_000, 53_000_000, 55_380_000],
        }
    )


def _write_reviewed_market_snapshot(root: Path) -> None:
    _write_json(
        root / "market_context_snapshot.json",
        {
            "artifact_type": "market_context_snapshot",
            "status": "PASS",
            "label": "risk_on",
            "as_of": "2024-01-03",
            "source": "unit-test reviewed index export",
            "reviewed_by": "tester",
            "reviewed_at": "2024-01-03",
            "index_metrics": [
                {
                    "name": "CSI300",
                    "return_20d": 0.01,
                    "return_60d": 0.02,
                    "return_120d": 0.03,
                    "max_drawdown": 0.05,
                    "annualized_volatility": 0.18,
                }
            ],
            "can_replace_market_regime": False,
            "can_approve_strategy": False,
            "can_generate_broker_orders": False,
        },
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
