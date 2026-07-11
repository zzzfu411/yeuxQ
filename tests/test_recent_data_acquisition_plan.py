from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.data.acquisition_plan import (
    build_recent_data_acquisition_plan,
    build_recent_data_acquisition_plan_from_config,
    write_recent_data_acquisition_plan,
)
from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.utils.config import Config, load_config


def test_recent_config_disables_demo_fallback() -> None:
    cfg = load_config("config/research_recent.yaml")

    assert cfg.research.allow_demo_data is False
    assert "research_recent.db" in cfg.data.cache_path
    assert cfg.research.out_sample_start >= "2025-01-01"


def test_recent_data_acquisition_plan_blocks_unready_cache(tmp_path: Path) -> None:
    cache = tmp_path / "recent.db"
    storage = BarStorage(cache)
    _seed_narrow_stale_data(storage)
    cfg = _cfg(cache)

    plan = build_recent_data_acquisition_plan(
        DataProvider(storage),
        cfg,
        config_path=tmp_path / "recent.yaml",
        as_of="2026-06-08",
        min_symbols=300,
        import_limit=500,
    )
    out = write_recent_data_acquisition_plan(plan, tmp_path / "out")

    assert plan.status == "BLOCK"
    assert plan.current_symbol_count == 5
    assert any("not ready" in blocker for blocker in plan.blockers)
    assert (out / "recent_data_acquisition_plan.json").exists()


def test_recent_data_acquisition_plan_uses_guarded_offline_intake_runbook(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "recent.db"
    storage = BarStorage(cache)
    cfg = _cfg(cache)

    plan = build_recent_data_acquisition_plan(
        DataProvider(storage),
        cfg,
        config_path=tmp_path / "recent.yaml",
        as_of="2026-06-08",
        min_symbols=300,
        import_limit=500,
    )

    step_by_name = {step.name: step for step in plan.steps}
    assert "write_source_qa_checklist" in step_by_name
    assert "write_raw_bars_dropzone_kit" in step_by_name
    assert "preflight_source_qa_worksheet" in step_by_name
    assert "write_source_qa_answers_from_worksheet" in step_by_name
    assert "write_source_qa_evidence_manifest" in step_by_name
    assert "review_source_qa_strict" in step_by_name
    assert "review_source_qa_evidence_readiness" in step_by_name
    assert "guarded_offline_intake" in step_by_name
    assert "--as-of 2026-06-08" in step_by_name["write_source_qa_checklist"].command
    assert "run_raw_bars_discovery.py" in step_by_name["write_raw_bars_dropzone_kit"].command
    assert "--search-dir data_exports\\raw" in step_by_name["write_raw_bars_dropzone_kit"].command
    assert "--write-dropzone-kit" in step_by_name["write_raw_bars_dropzone_kit"].command
    assert "--min-symbols 300" in step_by_name["write_raw_bars_dropzone_kit"].command
    assert "run_data_source_qa_worksheet_preflight.py" in step_by_name["preflight_source_qa_worksheet"].command
    assert "write_data_source_qa_answers.py" in step_by_name["write_source_qa_answers_from_worksheet"].command
    assert "--require-evidence-manifest" in step_by_name["write_source_qa_answers_from_worksheet"].command
    assert "write_source_qa_evidence_manifest.py" in step_by_name["write_source_qa_evidence_manifest"].command
    assert "--strict" in step_by_name["write_source_qa_evidence_manifest"].command
    assert "--require-evidence-manifest" in step_by_name["review_source_qa_strict"].command
    assert "run_source_qa_evidence_readiness.py" in step_by_name["review_source_qa_evidence_readiness"].command
    assert "run_offline_data_intake.py" in step_by_name["guarded_offline_intake"].command
    assert "--source-qa-evidence-manifest" in step_by_name["guarded_offline_intake"].command
    assert "--require-source-qa-evidence-manifest" in step_by_name["guarded_offline_intake"].command
    assert not any(
        step.name == "offline_csv_import" or "examples/import_research_csv.py" in step.command
        for step in plan.steps
    )


def test_recent_data_acquisition_plan_summarizes_network_blocked_import(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "recent.db"
    storage = BarStorage(cache)
    cfg = _cfg(cache)
    import_report = tmp_path / "data_import.json"
    _write_json(
        import_report,
        {
            "status": "BLOCK",
            "start": "2024-06-03",
            "end": "2026-06-05",
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
    )

    plan = build_recent_data_acquisition_plan(
        DataProvider(storage),
        cfg,
        config_path=tmp_path / "recent.yaml",
        as_of="2026-06-08",
        min_symbols=300,
        import_limit=500,
        latest_import_report_path=import_report,
    )
    out = write_recent_data_acquisition_plan(plan, tmp_path / "out")

    payload = json.loads((out / "recent_data_acquisition_plan.json").read_text(encoding="utf-8"))
    attempt = payload["latest_import_attempt"]
    assert plan.status == "BLOCK"
    assert attempt["attempted"] is True
    assert attempt["network_blocked"] is True
    assert attempt["actual_bar_start"] == ""
    assert attempt["actual_bar_end"] == ""
    assert attempt["covers_requested_end"] is False
    assert attempt["end_lag_days"] is None
    assert attempt["evidence_status"] == "BLOCK"
    assert "offline CSV" in attempt["next_action"]
    assert "TDX/OHLCV-only" in attempt["next_action"]
    diagnose_step = next(step for step in payload["steps"] if step["name"] == "diagnose_offline_csv")
    assert "--latest-import-report" in diagnose_step["command"]
    assert str(import_report) in diagnose_step["command"]


def test_recent_data_acquisition_plan_keeps_empty_actual_coverage_when_import_failed(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "recent.db"
    storage = BarStorage(cache)
    cfg = _cfg(cache)
    import_report = tmp_path / "data_import.json"
    _write_json(
        import_report,
        {
            "status": "BLOCK",
            "start": "2024-06-03",
            "end": "2026-06-05",
            "requested_symbols": 2,
            "imported_symbols": 0,
            "failed_symbols": 2,
            "bar_rows": 0,
            "calendar_days": 0,
            "failures": [{"symbol": "000001", "reason": "ProxyError: Unable to connect to proxy"}],
            "metadata": {
                "actual_bar_start": "",
                "actual_bar_end": "",
                "actual_bar_symbol_count": 0,
            },
        },
    )

    plan = build_recent_data_acquisition_plan(
        DataProvider(storage),
        cfg,
        config_path=tmp_path / "recent.yaml",
        as_of="2026-06-08",
        min_symbols=300,
        import_limit=500,
        latest_import_report_path=import_report,
    )

    assert plan.latest_import_attempt.actual_bar_start == ""
    assert plan.latest_import_attempt.actual_bar_end == ""
    assert plan.latest_import_attempt.covers_requested_end is False
    assert plan.latest_import_attempt.evidence_status == "BLOCK"
    assert "network/proxy" in plan.latest_import_attempt.message
    assert "offline" in plan.latest_import_attempt.next_action.lower()


def test_recent_data_acquisition_plan_honors_top_level_network_blocked(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "recent.db"
    storage = BarStorage(cache)
    cfg = _cfg(cache)
    import_report = tmp_path / "data_import.json"
    _write_json(
        import_report,
        {
            "status": "BLOCK",
            "start": "2024-06-03",
            "end": "2026-06-05",
            "requested_symbols": 2,
            "imported_symbols": 0,
            "failed_symbols": 2,
            "bar_rows": 0,
            "calendar_days": 0,
            "network_blocked": True,
            "failure_stage": "symbol_list",
            "recommended_route": "offline_csv_or_tdx",
            "failures": [{"symbol": "000001", "reason": "provider blocked by local policy"}],
        },
    )

    plan = build_recent_data_acquisition_plan(
        DataProvider(storage),
        cfg,
        config_path=tmp_path / "recent.yaml",
        as_of="2026-06-08",
        min_symbols=300,
        import_limit=500,
        latest_import_report_path=import_report,
    )

    assert plan.status == "BLOCK"
    assert plan.latest_import_attempt.network_blocked is True
    assert plan.latest_import_attempt.failure_stage == "symbol_list"
    assert plan.latest_import_attempt.recommended_route == "offline_csv_or_tdx"
    assert plan.latest_import_attempt.actual_bar_start == ""
    assert plan.latest_import_attempt.actual_bar_end == ""
    assert "network/proxy" in plan.latest_import_attempt.message


def test_recent_data_acquisition_plan_blocks_stale_successful_import_report(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "recent.db"
    storage = BarStorage(cache)
    _seed_ready_recent_data(storage, periods=130, symbols=5)
    cfg = _cfg(cache)
    import_report = tmp_path / "data_import.json"
    _write_json(
        import_report,
        {
            "status": "PASS",
            "start": "2024-06-03",
            "end": "2026-06-05",
            "requested_symbols": 5,
            "imported_symbols": 5,
            "failed_symbols": 0,
            "bar_rows": 650,
            "calendar_days": 130,
            "failures": [],
            "metadata": {
                "actual_bar_start": "2024-06-03",
                "actual_bar_end": "2026-05-01",
                "actual_bar_symbol_count": 5,
            },
        },
    )

    plan = build_recent_data_acquisition_plan(
        DataProvider(storage),
        cfg,
        config_path=tmp_path / "recent.yaml",
        as_of="2026-06-08",
        min_symbols=5,
        import_limit=500,
        latest_import_report_path=import_report,
    )

    assert plan.status == "BLOCK"
    assert plan.bootstrap_decision == "PASS"
    assert plan.latest_import_attempt.status == "PASS"
    assert plan.latest_import_attempt.evidence_status == "BLOCK"
    assert plan.latest_import_attempt.end == "2026-06-05"
    assert plan.latest_import_attempt.actual_bar_end == "2026-05-01"
    assert plan.latest_import_attempt.end_lag_days == 35
    assert any("before requested research end" in blocker for blocker in plan.blockers)


def test_recent_data_acquisition_plan_from_config_preserves_missing_cache_evidence(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "missing_recent.db"
    cfg_path = tmp_path / "recent.yaml"
    cfg_path.write_text(_cfg_yaml(cache), encoding="utf-8")

    plan = build_recent_data_acquisition_plan_from_config(
        config_path=cfg_path,
        as_of="2026-06-08",
        min_symbols=300,
        import_limit=500,
    )

    assert plan.status == "BLOCK"
    assert any("not ready" in blocker for blocker in plan.blockers)
    assert not cache.exists() or cache.stat().st_size > 0


def test_recent_data_acquisition_plan_from_config_uses_cache_override(tmp_path: Path) -> None:
    config_cache = tmp_path / "config_default.db"
    override_cache = tmp_path / "override_recent.db"
    cfg_path = tmp_path / "recent.yaml"
    cfg_path.write_text(_cfg_yaml(config_cache), encoding="utf-8")
    _seed_ready_recent_data(BarStorage(override_cache), periods=260, symbols=5)

    plan = build_recent_data_acquisition_plan_from_config(
        config_path=cfg_path,
        cache_path=override_cache,
        as_of="2026-06-08",
        min_symbols=5,
        import_limit=500,
    )

    assert plan.cache_path == str(override_cache)
    assert plan.current_symbol_count == 5
    assert plan.current_latest_bar_date == "2026-06-05"
    assert str(config_cache) not in plan.cache_path


def test_recent_data_acquisition_plan_cli_writes_outputs(tmp_path: Path) -> None:
    cache = tmp_path / "recent.db"
    cfg_path = tmp_path / "recent.yaml"
    cfg_path.write_text(_cfg_yaml(cache), encoding="utf-8")
    out = tmp_path / "out"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_recent_data_plan.py",
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

    payload = json.loads((out / "recent_data_acquisition_plan.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["status"] == "BLOCK"
    assert payload["steps"]


def _seed_narrow_stale_data(storage: BarStorage) -> None:
    dates = pd.bdate_range("2021-01-01", periods=20)
    symbols = [f"{600000 + idx:06d}" for idx in range(5)]
    storage.save_calendar([date.date().isoformat() for date in dates])
    storage.save_stock_info(pd.DataFrame({"symbol": symbols, "name": symbols}))
    rows = []
    for symbol in symbols:
        for idx, date in enumerate(dates):
            close = 10 + idx * 0.01
            rows.append(
                {
                    "symbol": symbol,
                    "date": date.date().isoformat(),
                    "open": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": 1_000_000,
                    "amount": close * 1_000_000,
                }
            )
    storage.save_bars(pd.DataFrame(rows))


def _seed_ready_recent_data(storage: BarStorage, *, periods: int, symbols: int) -> None:
    dates = pd.bdate_range(end="2026-06-05", periods=periods)
    names = [f"{600000 + idx:06d}" for idx in range(symbols)]
    storage.save_calendar([date.date().isoformat() for date in dates])
    storage.save_stock_info(
        pd.DataFrame(
            {
                "symbol": names,
                "name": names,
                "exchange": ["SSE"] * symbols,
                "list_date": ["2020-01-01"] * symbols,
                "delist_date": [""] * symbols,
                "industry": ["test"] * symbols,
                "is_st": [0] * symbols,
            }
        )
    )
    rows = []
    for symbol in names:
        for idx, date in enumerate(dates):
            close = 10 + idx * 0.01
            rows.append(
                {
                    "symbol": symbol,
                    "date": date.date().isoformat(),
                    "open": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": 1_000_000,
                    "amount": close * 1_000_000,
                }
            )
    storage.save_bars(pd.DataFrame(rows))


def _cfg(cache_path: Path) -> Config:
    return Config(
        {
            "research": {
                "start": "2024-06-03",
                "end": "2026-06-05",
                "in_sample_end": "2025-06-30",
                "out_sample_start": "2025-07-01",
                "allow_demo_data": False,
            },
            "data": {"source": "akshare", "cache_path": str(cache_path)},
        }
    )


def _cfg_yaml(cache_path: Path) -> str:
    return f"""
research:
  start: "2024-06-03"
  end: "2026-06-05"
  in_sample_end: "2025-06-30"
  out_sample_start: "2025-07-01"
  allow_demo_data: false
data:
  source: akshare
  cache_path: "{cache_path.as_posix()}"
"""


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
