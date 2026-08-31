from __future__ import annotations

import csv
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

from quantify.analytics.dashboard import DashboardInputError, build_dashboard, write_dashboard


def _write_report(root: Path, *, include_gates: bool = True, malicious: bool = False) -> None:
    root.mkdir(parents=True, exist_ok=True)
    title = '<img src=x onerror="alert(1)">' if malicious else "演示研究"
    _write_json(
        root / "summary.json",
        {
            "title": title,
            "initial_equity": 100_000,
            "final_equity": 112_000,
            "total_return": 0.12,
            "annualized_return": 0.10,
            "annualized_volatility": 0.15,
            "sharpe_ratio": 1.1,
            "max_drawdown": 0.08,
            "n_round_trips": 4,
            "win_rate": 0.75,
            "n_bars": 6,
            "assumptions": {
                "data_source": "fixture",
                "start": "2024-01-01",
                "end": "2024-01-08",
            },
            "evidence": {"data_audit_status": "WATCH"},
            "risk_notice": "Historical backtests do not predict or guarantee future profits.",
        },
    )
    _write_csv(
        root / "equity.csv",
        ["timestamp", "equity"],
        [
            ["2024-01-01", "100000"],
            ["2024-01-02", "101000"],
            ["2024-01-03", "99000"],
            ["2024-01-04", "103000"],
            ["2024-01-05", "102000"],
            ["2024-01-08", "112000"],
        ],
    )
    _write_csv(
        root / "factor_ic.csv",
        ["date", "rank_ic"],
        [["2024-01-01", "0.10"], ["2024-01-02", "-0.04"], ["2024-01-03", "0.08"]],
    )
    _write_csv(
        root / "turnover.csv",
        ["date", "turnover", "turnover_pct"],
        [["2024-01-01", "1000", "0.05"], ["2024-01-02", "1200", "0.15"]],
    )
    _write_csv(
        root / "orders.csv",
        ["timestamp", "symbol", "direction", "quantity", "price", "status", "reason"],
        [
            ["2024-01-01", "AAA", "LONG", "100", "10", "filled", ""],
            ["2024-01-02", "AAA", "EXIT", "100", "9", "rejected", "t_plus_one"],
            ["2024-01-03", "BBB", "LONG", "100", "20", "rejected", "cash"],
        ],
    )
    symbol = '<script>alert("x")</script>' if malicious else "AAA"
    _write_csv(
        root / "positions.csv",
        ["date", "symbol", "quantity", "available_qty", "price", "market_value", "weight"],
        [["2024-01-08", symbol, "100", "100", "10", "1000", "0.01"]],
    )
    if include_gates:
        _write_json(
            root / "data_audit.json",
            {"status": "WATCH", "findings": [{"code": "MISSING_BARS", "message": "示例提示"}]},
        )
        _write_json(
            root / "llm_review.json",
            {"decision": "BLOCK", "findings": [{"code": "DEMO", "message": "仅供演示"}]},
        )


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def test_build_dashboard_is_self_contained_and_escapes_report_values(tmp_path: Path) -> None:
    _write_report(tmp_path, malicious=True)

    output = build_dashboard(tmp_path)

    assert output.startswith("<!doctype html>")
    assert '<html lang="zh-CN">' in output
    assert output.count('<svg class="chart"') == 5
    assert "均值" in output and "stroke-dasharray" in output
    assert "风险提示：历史回测不代表未来收益" in output
    assert "总收益" in output and "12.00%" in output
    assert 'data-gate="data-audit"' in output
    assert 'data-gate="llm-review"' in output
    assert "t_plus_one" in output and "cash" in output
    assert "<script>alert" not in output
    assert "&lt;script&gt;alert" in output
    assert "<img src=x" not in output
    assert not re.search(r"(?:src|href)=[\"'](?:https?:)?//", output, re.IGNORECASE)


def test_missing_or_malformed_optional_evidence_fails_closed(tmp_path: Path) -> None:
    _write_report(tmp_path, include_gates=False)
    (tmp_path / "data_audit.json").write_text("{not-json", encoding="utf-8")

    output = build_dashboard(tmp_path)

    assert "按安全默认 BLOCK" in output
    assert "llm_review.json 未提供" in output
    assert "data_audit.json 无法读取" in output
    assert "暂无拒单记录" not in output  # orders.csv is still present


def test_conflicting_gate_fields_fail_closed(tmp_path: Path) -> None:
    _write_report(tmp_path)
    _write_json(tmp_path / "llm_review.json", {"decision": "PASS", "status": "BLOCK"})

    output = build_dashboard(tmp_path)

    assert 'data-gate="llm-review"' in output
    llm_card = output.split('data-gate="llm-review"', 1)[1].split("</article>", 1)[0]
    assert ">BLOCK<" in llm_card
    assert "状态字段冲突" in llm_card


def test_dashboard_tolerates_missing_csvs_and_unknown_gate(tmp_path: Path) -> None:
    _write_report(tmp_path, include_gates=False)
    for filename in ("equity.csv", "factor_ic.csv", "turnover.csv", "orders.csv", "positions.csv"):
        (tmp_path / filename).unlink()
    _write_json(tmp_path / "data_audit.json", {"status": "future-state"})

    output = build_dashboard(tmp_path)

    assert output.count('<svg class="chart"') == 5
    assert "未知状态，按安全默认 BLOCK" in output
    assert output.count("暂无可用数据") >= 3
    assert "暂无可用持仓数据" in output


def test_required_summary_is_validated(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build_dashboard(tmp_path)

    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "summary.json").write_text("[]", encoding="utf-8")
    with pytest.raises(DashboardInputError):
        build_dashboard(tmp_path)


def test_write_dashboard_default_and_cli_smoke(tmp_path: Path) -> None:
    _write_report(tmp_path)
    written = write_dashboard(tmp_path)
    assert written == tmp_path / "dashboard.html"
    assert written.is_file()
    assert written.read_text(encoding="utf-8").count('<svg class="chart"') == 5

    output = tmp_path / "nested" / "dashboard.html"
    completed = subprocess.run(
        [
            sys.executable,
            "examples/build_report_dashboard.py",
            "--report-dir",
            str(tmp_path),
            "--output",
            str(output),
            "--title",
            "CLI 演示",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert output.is_file()
    assert "CLI 演示" in output.read_text(encoding="utf-8")


def test_cli_returns_nonzero_for_missing_report(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "examples/build_report_dashboard.py",
            "--report-dir",
            str(tmp_path / "missing"),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert not (tmp_path / "missing").exists()
