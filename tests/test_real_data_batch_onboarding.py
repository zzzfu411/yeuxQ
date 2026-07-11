from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.data.ohlcv_experiment_package import build_ohlcv_experiment_package_preflight
from quantify.data.real_data_batch_onboarding import (
    build_real_data_batch_onboarding,
    write_real_data_batch_onboarding,
)
from quantify.data.source_qa import build_data_source_qa, build_data_source_qa_answers, write_data_source_qa, write_data_source_qa_answers
from quantify.data.source_qa_operator_packet import build_source_qa_operator_packet


def test_real_data_batch_onboarding_blocks_without_raw_bars_and_source_evidence(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    _write_config(config, cache)

    onboarding = build_real_data_batch_onboarding(
        data_dir=data_dir,
        report_dir=report_dir,
        config_path=config,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
        source_qa_packet=build_source_qa_operator_packet(data_dir=data_dir, report_dir=report_dir, as_of="2024-01-03"),
    )
    out = write_real_data_batch_onboarding(onboarding, report_dir)

    payload = json.loads((out / "real_data_batch_onboarding.json").read_text(encoding="utf-8"))
    markdown = (out / "real_data_batch_onboarding.md").read_text(encoding="utf-8")
    rows = (out / "real_data_batch_onboarding.csv").read_text(encoding="utf-8-sig")

    assert payload["decision"] == "BLOCK"
    assert any("raw_bars_csv" in item for item in payload["blockers"])
    assert any("source_qa_answers" in item for item in payload["blockers"])
    assert any("normalize_vendor_bars.py" in command for command in payload["command_sequence"])
    assert "not a strategy signal" in markdown
    assert "raw_bars_csv" in rows


def test_real_data_batch_onboarding_watches_after_raw_and_preflight_exist(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    raw = tmp_path / "raw_vendor_bars.csv"
    _write_config(config, cache)
    _write_raw_bars(raw)
    _write_replaced_export(data_dir)
    _write_source_qa_answers(data_dir, config)
    _write_json(report_dir / "market_context_snapshot.json", _market_snapshot())
    source_packet = build_source_qa_operator_packet(data_dir=data_dir, report_dir=report_dir, as_of="2024-01-03")
    ohlcv = build_ohlcv_experiment_package_preflight(
        data_dir=data_dir,
        report_dir=report_dir,
        config_path=config,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
    )

    onboarding = build_real_data_batch_onboarding(
        data_dir=data_dir,
        report_dir=report_dir,
        config_path=config,
        raw_bars_csv=raw,
        min_symbols=2,
        min_trading_days=2,
        as_of="2024-01-03",
        source_qa_packet=source_packet,
        ohlcv_package=ohlcv,
    )

    assert onboarding.decision == "BLOCK"
    assert not any("raw_bars_csv" in item for item in onboarding.blockers)
    assert any(step.name == "raw_bars_csv" and step.status == "PASS" for step in onboarding.steps)
    assert any(step.name == "ohlcv_experiment_package" and step.status == "WATCH" for step in onboarding.steps)
    assert any("guarded_offline_intake" in item for item in onboarding.blockers)
    assert any("first_million_pipeline.py" in command for command in onboarding.command_sequence)
    assert any("Candidate readiness" in item for item in onboarding.acceptance_criteria)


def test_real_data_batch_onboarding_cli_returns_nonzero_on_block(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    report_dir = tmp_path / "first_million"
    config = tmp_path / "research_recent.yaml"
    cache = tmp_path / "recent.db"
    _write_config(config, cache)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_real_data_batch_onboarding.py",
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

    payload = json.loads((report_dir / "real_data_batch_onboarding.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["decision"] == "BLOCK"


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
            ]
        ),
        encoding="utf-8",
    )


def _write_source_qa_answers(data_dir: Path, config: Path) -> None:
    checklist = build_data_source_qa(config_path=config, output_dir=data_dir, min_symbols=2, as_of="2024-01-03")
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
        point_in_time_evidence="OHLCV-only; no PIT fundamentals.",
        reviewed_by="tester",
        reviewed_at="2024-01-03",
    )
    write_data_source_qa_answers(answers, data_dir / "data_source_qa_answers.json")


def _write_raw_bars(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _bars().to_csv(path, index=False)


def _write_replaced_export(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    _bars().to_csv(data_dir / "bars.csv", index=False)


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


def _market_snapshot() -> dict[str, object]:
    return {
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
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
