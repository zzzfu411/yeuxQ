from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.data.csv_contract import write_research_csv_templates
from quantify.data.import_doctor import build_data_import_doctor, write_data_import_doctor_report


def test_data_import_doctor_blocks_missing_export_directory(tmp_path: Path) -> None:
    missing = tmp_path / "data_exports"
    config = tmp_path / "research_recent.yaml"
    config.write_text(
        "\n".join(
            [
                "research:",
                '  start: "2024-06-03"',
                '  end: "2026-06-05"',
                "data:",
                '  cache_path: "./data_cache/research_recent.db"',
                "  adjust: qfq",
                "universe:",
                "  mode: all_a",
                '  index_code: "000906"',
                "  include_st: false",
                "  min_history_days: 120",
            ]
        ),
        encoding="utf-8",
    )

    report = build_data_import_doctor(data_dir=missing, config_path=config, min_symbols=300)

    assert report.status == "BLOCK"
    assert report.start == "2024-06-03"
    assert report.end == "2026-06-05"
    assert report.missing_required_files == [str(missing / "bars.csv")]
    assert report.export_requirements["price_adjustment"] == "qfq"
    assert report.export_requirements["minimum_universe"]["mode"] == "all_a"
    assert report.export_requirements["minimum_universe"]["index_code"] == "000906"
    assert report.export_requirements["minimum_universe"]["include_st"] is False
    assert report.export_requirements["minimum_universe"]["min_history_days"] == 120
    assert any(finding.code == "DATA_EXPORT_DIR_MISSING" for finding in report.findings)
    assert "run_real_data_bootstrap.py" in report.commands[-1].command
    assert "--as-of 2026-06-08" not in report.commands[-1].command


def test_data_import_doctor_omits_empty_period_args_in_tdx_command(tmp_path: Path) -> None:
    missing = tmp_path / "data_exports"

    report = build_data_import_doctor(data_dir=missing, min_symbols=300)

    tdx_command = next(command.command for command in report.commands if command.name == "run_tdx_ohlcv_intake")
    normalize_command = next(command.command for command in report.commands if command.name == "normalize_vendor_bars")
    assert "--start  --end" not in tdx_command
    assert tdx_command.endswith("--min-symbols 300")
    assert "--start  --end" not in normalize_command
    assert normalize_command.endswith("--min-symbols 300")


def test_data_import_doctor_orders_vendor_normalizer_before_validation(tmp_path: Path) -> None:
    missing = tmp_path / "data_exports"

    report = build_data_import_doctor(data_dir=missing, min_symbols=300)
    command_names = [command.name for command in report.commands]

    assert "normalize_vendor_bars" in command_names
    assert command_names.index("write_templates") < command_names.index("normalize_vendor_bars")
    assert command_names.index("normalize_vendor_bars") < command_names.index("validate_csv")
    normalizer = next(command for command in report.commands if command.name == "normalize_vendor_bars")
    assert "normalize_vendor_bars.py" in normalizer.command
    assert "strategy approval" in normalizer.reason
    assert "live trading permission" in normalizer.reason


def test_data_import_doctor_blocks_unreplaced_template_export(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    write_research_csv_templates(data_dir)

    report = build_data_import_doctor(
        data_dir=data_dir,
        cache_path=tmp_path / "research.db",
        start="2024-01-02",
        end="2024-01-03",
        min_symbols=2,
    )

    assert report.status == "BLOCK"
    assert any(finding.code == "TEMPLATE_EXPORT_UNREPLACED" for finding in report.findings)


def test_data_import_doctor_explains_network_blocked_template_next_steps(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    write_research_csv_templates(data_dir)
    import_report = tmp_path / "data_import.json"
    _write_network_blocked_import_report(import_report)

    report = build_data_import_doctor(
        data_dir=data_dir,
        cache_path=tmp_path / "research.db",
        start="2024-01-02",
        end="2024-01-03",
        min_symbols=2,
        latest_import_report_path=import_report,
    )
    out = write_data_import_doctor_report(report, tmp_path / "doctor")

    assert report.status == "BLOCK"
    assert report.latest_import_attempt is not None
    assert report.latest_import_attempt.network_blocked is True
    assert report.commands[0].name == "discover_tdx_day"
    assert report.commands[1].name == "run_tdx_ohlcv_intake"
    assert report.commands[2].name == "write_templates"
    assert report.commands[3].name == "normalize_vendor_bars"
    assert any("TDX/OHLCV-only path" in action for action in report.next_actions)
    assert any("Broker/vendor CSV path" in action for action in report.next_actions)
    assert any("normalize_vendor_bars.py" in action for action in report.next_actions)
    markdown = (out / "data_import_doctor.md").read_text(encoding="utf-8")
    assert "Network blocked" in markdown


def test_data_import_doctor_explains_network_blocked_stale_csv_next_steps(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    data_dir.mkdir()
    _bars().to_csv(data_dir / "bars.csv", index=False)
    import_report = tmp_path / "data_import.json"
    _write_network_blocked_import_report(import_report)

    report = build_data_import_doctor(
        data_dir=data_dir,
        cache_path=tmp_path / "research.db",
        start="2024-01-02",
        end="2024-02-20",
        min_symbols=2,
        latest_import_report_path=import_report,
    )

    assert report.status == "BLOCK"
    assert any(finding.code == "BARS_END_BEFORE_EXPECTED" for finding in report.findings)
    assert any("stale before the configured research end date" in action for action in report.next_actions)
    assert any("run_tdx_ohlcv_intake.py" in action for action in report.next_actions)
    assert any("normalize_vendor_bars.py" in action for action in report.next_actions)
    assert any("run_offline_data_intake.py" in action for action in report.next_actions)


def test_data_import_doctor_honors_top_level_network_blocked(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data_exports"
    write_research_csv_templates(data_dir)
    import_report = tmp_path / "data_import.json"
    _write_json(
        import_report,
        {
            "status": "BLOCK",
            "start": "2024-01-02",
            "end": "2024-01-03",
            "requested_symbols": 2,
            "imported_symbols": 0,
            "failed_symbols": 2,
            "bar_rows": 0,
            "calendar_days": 0,
            "network_blocked": True,
            "failures": [{"symbol": "000001", "reason": "provider denied request"}],
        },
    )

    report = build_data_import_doctor(
        data_dir=data_dir,
        cache_path=tmp_path / "research.db",
        start="2024-01-02",
        end="2024-01-03",
        min_symbols=2,
        latest_import_report_path=import_report,
    )

    assert report.latest_import_attempt is not None
    assert report.latest_import_attempt.network_blocked is True
    assert "network/proxy" in report.latest_import_attempt.message
    assert any("TDX/OHLCV-only path" in action for action in report.next_actions)


def test_data_import_doctor_passes_complete_replaced_export(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    _write_replaced_export(data_dir)

    report = build_data_import_doctor(
        data_dir=data_dir,
        cache_path=tmp_path / "research.db",
        start="2024-01-02",
        end="2024-01-03",
        min_symbols=2,
    )
    out = write_data_import_doctor_report(report, tmp_path / "doctor")

    assert report.status == "PASS"
    assert report.validation is not None
    assert report.export_requirements["required_files"] == ["bars.csv"]
    assert report.missing_required_files == []
    assert report.missing_recommended_files == []
    assert (out / "data_import_doctor.json").exists()
    markdown = (out / "data_import_doctor.md").read_text(encoding="utf-8")
    assert "Price adjustment" in markdown
    assert "Import the validated CSV files" in markdown


def test_data_import_doctor_cli_writes_outputs(tmp_path: Path) -> None:
    data_dir = tmp_path / "data_exports"
    output = tmp_path / "out"
    _write_replaced_export(data_dir)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_data_import_doctor.py",
            "--data-dir",
            str(data_dir),
            "--cache",
            str(tmp_path / "research.db"),
            "--start",
            "2024-01-02",
            "--end",
            "2024-01-03",
            "--min-symbols",
            "2",
            "--output-dir",
            str(output),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((output / "data_import_doctor.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["status"] == "PASS"
    assert payload["export_requirements"]["quality_floor"]["no_template_rows"] is True
    assert (output / "data_import_doctor.md").exists()


def _write_replaced_export(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
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
    ).to_csv(data_dir / "bars.csv", index=False)
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
    pd.DataFrame(
        {
            "symbol": ["600010", "000010"],
            "date": ["2024-01-02", "2024-01-02"],
            "pe_ttm": [9.0, 11.0],
            "pb": [1.0, 1.3],
            "roe": [0.09, 0.11],
            "market_cap": [9_000_000_000, 11_000_000_000],
            "turnover_rate": [0.015, 0.025],
        }
    ).to_csv(data_dir / "fundamentals.csv", index=False)
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
    pd.DataFrame(
        {
            "index_code": ["000906", "000906"],
            "date": ["2024-01-02", "2024-01-02"],
            "symbol": ["600010", "000010"],
        }
    ).to_csv(data_dir / "index_constituents.csv", index=False)


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


def _write_network_blocked_import_report(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "status": "BLOCK",
                "start": "2024-01-02",
                "end": "2024-01-03",
                "requested_symbols": 2,
                "imported_symbols": 0,
                "failed_symbols": 2,
                "bar_rows": 0,
                "calendar_days": 0,
                "failures": [
                    {
                        "symbol": "000001",
                        "reason": "ProxyError: Unable to connect to proxy",
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
