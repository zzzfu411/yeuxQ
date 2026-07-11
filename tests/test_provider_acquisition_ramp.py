from __future__ import annotations

import json
from pathlib import Path

import pytest

from examples import run_provider_acquisition_ramp as cli
from quantify.data.provider_acquisition_ramp import (
    parse_stage_sizes,
    parse_symbols,
    run_provider_acquisition_ramp,
    write_provider_acquisition_ramp,
)
from quantify.data.research_importer import ImportFailure, ResearchImportReport


def test_provider_acquisition_ramp_stops_after_block_and_writes_reports(tmp_path: Path) -> None:
    calls: list[int] = []

    def fake_importer(**kwargs) -> ResearchImportReport:
        size = int(kwargs["size"])
        calls.append(size)
        if size == 2:
            return _import_report(size=size, status="PASS", imported=size, rows=4, days=2)
        return _import_report(
            size=size,
            status="BLOCK",
            imported=0,
            rows=0,
            days=0,
            failure="ConnectionError: Max retries exceeded",
            network_blocked=True,
        )

    report = run_provider_acquisition_ramp(
        cache_path=tmp_path / "research.db",
        start="2024-01-02",
        end="2024-01-03",
        stage_sizes=[2, 20, 100],
        output_dir=tmp_path / "ramp",
        importer=fake_importer,
    )
    out = write_provider_acquisition_ramp(report, tmp_path / "ramp")
    payload = json.loads((out / "provider_acquisition_ramp.json").read_text(encoding="utf-8"))
    markdown = (out / "provider_acquisition_ramp.md").read_text(encoding="utf-8")

    assert calls == [2, 20]
    assert report.status == "BLOCK"
    assert [stage.status for stage in report.stages] == ["PASS", "BLOCK"]
    assert payload["executed_stage_count"] == 2
    assert payload["configured_stage_sizes"] == [2, 20, 100]
    assert payload["source_qa_provenance_status"] == "NOT_EVALUATED"
    assert payload["promotion_gate_effect"] == "NONE"
    assert any("skipped stage sizes" in action for action in payload["next_actions"])
    assert any("promotion-ready gates" in action for action in payload["prohibited_actions"])
    assert (tmp_path / "ramp" / "stage_01_size_2" / "data_import.json").exists()
    assert (tmp_path / "ramp" / "stage_02_size_20" / "data_import.md").exists()
    assert "cannot make promotion-ready gates pass" in markdown


def test_provider_acquisition_ramp_keeps_watch_as_watch(tmp_path: Path) -> None:
    def fake_importer(**kwargs) -> ResearchImportReport:
        size = int(kwargs["size"])
        return _import_report(
            size=size,
            status="PASS",
            requested=max(size - 1, 1),
            imported=max(size - 1, 1),
            rows=max(size - 1, 1),
            days=1,
        )

    report = run_provider_acquisition_ramp(
        cache_path=tmp_path / "research.db",
        start="2024-01-02",
        end="2024-01-03",
        stage_sizes=[2, 3],
        output_dir=tmp_path / "ramp",
        importer=fake_importer,
    )

    assert report.status == "WATCH"
    assert all(stage.status == "WATCH" for stage in report.stages)
    assert all("WATCH is not PASS" in stage.message for stage in report.stages)
    assert not any(stage.status == "PASS" for stage in report.stages)


def test_provider_acquisition_ramp_unsupported_provider_blocks_without_network(
    tmp_path: Path,
) -> None:
    report = run_provider_acquisition_ramp(
        cache_path=tmp_path / "research.db",
        start="2024-01-02",
        end="2024-01-03",
        stage_sizes=[2],
        provider="other",
        output_dir=tmp_path / "ramp",
    )

    assert report.status == "BLOCK"
    assert report.stages[0].status == "BLOCK"
    assert "Unsupported provider" in report.stages[0].message


def test_parse_stage_sizes_and_symbols() -> None:
    assert parse_stage_sizes("2,20;100 300") == [2, 20, 100, 300]
    assert parse_symbols("600001, 000001;600001") == ["600001", "000001"]
    with pytest.raises(ValueError, match="positive"):
        parse_stage_sizes("2,0")


def test_provider_acquisition_ramp_cli_uses_injected_runner_and_returns_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "research.yaml"
    output_dir = tmp_path / "out"
    cache = tmp_path / "research.db"
    _write_config(config, cache)
    captured: dict[str, object] = {}

    def fake_runner(**kwargs) -> object:
        captured.update(kwargs)
        return run_provider_acquisition_ramp(
            cache_path=kwargs["cache_path"],
            start=kwargs["start"],
            end=kwargs["end"],
            stage_sizes=[2],
            provider=kwargs["provider"],
            importer=lambda **_: _import_report(
                size=2,
                status="BLOCK",
                imported=0,
                rows=0,
                days=0,
                failure="provider down",
            ),
        )

    monkeypatch.setattr(cli, "run_provider_acquisition_ramp", fake_runner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_provider_acquisition_ramp.py",
            "--config",
            str(config),
            "--cache",
            str(cache),
            "--output-dir",
            str(output_dir),
            "--stage-sizes",
            "2,20",
            "--symbols",
            "600001,000001",
            "--provider",
            "akshare",
            "--include-st",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        cli.main()

    payload = json.loads((output_dir / "provider_acquisition_ramp.json").read_text(encoding="utf-8"))
    assert exc.value.code == 2
    assert captured["stage_sizes"] == [2, 20]
    assert captured["symbols"] == ["600001", "000001"]
    assert captured["include_st"] is True
    assert payload["status"] == "BLOCK"
    assert payload["research_only"] is True


def test_provider_acquisition_ramp_cli_defaults_to_isolated_tmp_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "research.yaml"
    config_cache = tmp_path / "config_research.db"
    output_dir = tmp_path / "out"
    _write_config(config, config_cache)
    captured: dict[str, object] = {}

    def fake_runner(**kwargs) -> object:
        captured.update(kwargs)
        return run_provider_acquisition_ramp(
            cache_path=kwargs["cache_path"],
            start=kwargs["start"],
            end=kwargs["end"],
            stage_sizes=[2],
            provider=kwargs["provider"],
            importer=lambda **_: _import_report(
                size=2,
                status="PASS",
                imported=2,
                rows=4,
                days=2,
            ),
        )

    monkeypatch.setattr(cli, "run_provider_acquisition_ramp", fake_runner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_provider_acquisition_ramp.py",
            "--config",
            str(config),
            "--output-dir",
            str(output_dir),
            "--stage-sizes",
            "2",
        ],
    )

    cli.main()

    payload = json.loads((output_dir / "provider_acquisition_ramp.json").read_text(encoding="utf-8"))
    assert captured["cache_path"] == cli.DEFAULT_RAMP_CACHE
    assert str(config_cache) not in payload["cache_path"]
    assert payload["research_only"] is True


def _import_report(
    *,
    size: int,
    status: str,
    imported: int,
    rows: int,
    days: int,
    requested: int | None = None,
    failure: str = "",
    network_blocked: bool = False,
) -> ResearchImportReport:
    failures = [ImportFailure("600001", failure)] if failure else []
    return ResearchImportReport(
        status=status,
        start="2024-01-02",
        end="2024-01-03",
        cache_path="research.db",
        requested_symbols=size if requested is None else requested,
        imported_symbols=imported,
        failed_symbols=len(failures),
        bar_rows=rows,
        calendar_days=days,
        failures=failures,
        notes=[],
        metadata={
            "actual_bar_start": "2024-01-02" if imported else "",
            "actual_bar_end": "2024-01-03" if imported else "",
            "actual_bar_symbol_count": imported,
        },
        failure_stage="bars" if failure else "",
        network_blocked=network_blocked,
        recommended_route="offline_csv_or_tdx" if network_blocked else "",
        next_actions=[],
    )


def _write_config(path: Path, cache: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "research:",
                '  start: "2024-01-02"',
                '  end: "2024-01-03"',
                "data:",
                f"  cache_path: '{cache}'",
                "  adjust: qfq",
                "universe:",
                "  index_code: '000906'",
            ]
        ),
        encoding="utf-8",
    )
