from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.paper import (
    evaluate_paper_stability,
    missing_paper_stability_report,
    write_paper_stability_report,
)


def test_paper_stability_passes_stable_paper_run(tmp_path: Path) -> None:
    _write_daily(tmp_path, periods=45, daily_return=0.001)
    _write_orders(tmp_path, statuses=["filled"] * 5)
    _write_state(tmp_path, broker_connection="none", order_count=5)

    report = evaluate_paper_stability(tmp_path)
    out = write_paper_stability_report(report, tmp_path)

    assert report.status == "PASS"
    assert report.observed_days == 45
    assert report.reject_rate == 0.0
    assert (out / "paper_stability.json").exists()
    assert "Paper Stability Review" in (out / "paper_stability.md").read_text(encoding="utf-8")


def test_paper_stability_blocks_broker_connection_and_reject_rate(tmp_path: Path) -> None:
    _write_daily(tmp_path, periods=45, daily_return=0.001)
    _write_orders(tmp_path, statuses=["filled", "rejected", "rejected", "filled"])
    _write_state(tmp_path, broker_connection="live", order_count=4, rejected_order_count=2)

    report = evaluate_paper_stability(tmp_path)

    assert report.status == "BLOCK"
    assert any(finding.code == "BROKER_CONNECTED" for finding in report.findings)
    assert any(finding.code == "PAPER_REJECT_RATE_BLOCK" for finding in report.findings)


def test_paper_stability_watches_short_observation_window(tmp_path: Path) -> None:
    _write_daily(tmp_path, periods=25, daily_return=0.001)
    _write_orders(tmp_path, statuses=["filled"])
    _write_state(tmp_path, broker_connection="none", observed_days=25, order_count=1)

    report = evaluate_paper_stability(tmp_path)

    assert report.status == "WATCH"
    assert any(finding.code == "SHORT_OBSERVATION_WINDOW" for finding in report.findings)


def test_paper_stability_blocks_state_daily_mismatch_and_duplicate_dates(tmp_path: Path) -> None:
    _write_daily(tmp_path, periods=45, daily_return=0.001)
    daily = pd.read_csv(tmp_path / "paper_daily.csv")
    pd.concat([daily, daily.iloc[[0]]], ignore_index=True).to_csv(tmp_path / "paper_daily.csv", index=False)
    _write_orders(tmp_path, statuses=["filled"])
    _write_state(tmp_path, broker_connection="none", order_count=1)

    report = evaluate_paper_stability(tmp_path)

    assert report.status == "BLOCK"
    assert any(finding.code == "PAPER_STATE_DAILY_MISMATCH" for finding in report.findings)
    assert any(finding.code == "DUPLICATE_PAPER_DAILY_DATES" for finding in report.findings)


def test_paper_stability_watches_large_daily_gap(tmp_path: Path) -> None:
    _write_daily_with_gap(tmp_path)
    _write_orders(tmp_path, statuses=["filled"])
    _write_state(tmp_path, broker_connection="none", observed_days=45, order_count=1)

    report = evaluate_paper_stability(tmp_path)

    assert report.status == "WATCH"
    assert any(finding.code == "PAPER_DAILY_GAPS" for finding in report.findings)
    assert report.metrics["large_calendar_gap_count"] == 1


def test_paper_stability_blocks_state_date_and_order_mismatch(tmp_path: Path) -> None:
    _write_daily(tmp_path, periods=45, daily_return=0.001)
    _write_orders(tmp_path, statuses=["filled"])
    _write_state(
        tmp_path,
        broker_connection="none",
        as_of="2024-03-29",
        order_count=10,
        rejected_order_count=2,
    )

    report = evaluate_paper_stability(tmp_path)

    assert report.status == "BLOCK"
    assert any(finding.code == "PAPER_STATE_DATE_MISMATCH" for finding in report.findings)
    assert any(finding.code == "PAPER_STATE_ORDER_MISMATCH" for finding in report.findings)


def test_paper_stability_blocks_mixed_candidate_history(tmp_path: Path) -> None:
    _write_daily(tmp_path, periods=45, daily_return=0.001)
    daily = pd.read_csv(tmp_path / "paper_daily.csv")
    daily.loc[daily.index[-1], "candidate"] = "other_candidate"
    daily.to_csv(tmp_path / "paper_daily.csv", index=False)
    _write_orders(tmp_path, statuses=["filled"])
    _write_state(tmp_path, broker_connection="none", order_count=1)

    report = evaluate_paper_stability(tmp_path)

    assert report.status == "BLOCK"
    assert any(finding.code == "MIXED_PAPER_DAILY_CANDIDATES" for finding in report.findings)


def test_paper_stability_cli_writes_outputs(tmp_path: Path) -> None:
    _write_daily(tmp_path, periods=45, daily_return=0.001)
    _write_orders(tmp_path, statuses=["filled"] * 3)
    _write_state(tmp_path, broker_connection="none", order_count=3)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_paper_stability.py",
            "--paper-dir",
            str(tmp_path),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((tmp_path / "paper_stability.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["status"] == "PASS"


def test_missing_paper_stability_report_blocks() -> None:
    report = missing_paper_stability_report("results/paper/core")

    assert report.status == "BLOCK"
    assert report.paper_dir == "results/paper/core"
    assert any(finding.code == "MISSING_CONTINUOUS_PAPER_RUN" for finding in report.findings)


def _write_state(
    root: Path,
    *,
    broker_connection: str,
    observed_days: int = 45,
    as_of: str | None = None,
    candidate: str = "core_multifactor",
    order_count: int = 0,
    rejected_order_count: int = 0,
) -> None:
    as_of = as_of or _latest_daily_date(root)
    (root / "paper_state.json").write_text(
        json.dumps(
            {
                "as_of": as_of,
                "observed_days": observed_days,
                "candidate": candidate,
                "initial_cash": 100_000,
                "cash": 20_000,
                "last_equity": 105_000,
                "order_count": order_count,
                "rejected_order_count": rejected_order_count,
                "broker_connection": broker_connection,
            }
        ),
        encoding="utf-8",
    )


def _write_daily(root: Path, *, periods: int, daily_return: float) -> None:
    dates = pd.bdate_range("2024-01-01", periods=periods)
    equity = [100_000 * (1 + daily_return) ** idx for idx in range(periods)]
    pd.DataFrame(
        {
            "date": [date.date().isoformat() for date in dates],
            "equity": equity,
            "cash": [20_000.0] * periods,
            "rebalanced": [idx % 20 == 0 for idx in range(periods)],
            "candidate": ["core_multifactor"] * periods,
            "broker_connection": ["none"] * periods,
        }
    ).to_csv(root / "paper_daily.csv", index=False)


def _write_daily_with_gap(root: Path) -> None:
    first = pd.bdate_range("2024-01-01", periods=30)
    second = pd.bdate_range("2024-03-01", periods=15)
    dates = first.append(second)
    equity = [100_000 * (1.001**idx) for idx in range(len(dates))]
    pd.DataFrame(
        {
            "date": [date.date().isoformat() for date in dates],
            "equity": equity,
            "cash": [20_000.0] * len(dates),
            "rebalanced": [idx % 20 == 0 for idx in range(len(dates))],
            "candidate": ["core_multifactor"] * len(dates),
            "broker_connection": ["none"] * len(dates),
        }
    ).to_csv(root / "paper_daily.csv", index=False)


def _write_orders(root: Path, *, statuses: list[str]) -> None:
    pd.DataFrame(
        {
            "timestamp": ["2024-01-02"] * len(statuses),
            "symbol": [f"AAA{idx}" for idx, _ in enumerate(statuses)],
            "direction": ["LONG"] * len(statuses),
            "quantity": [100] * len(statuses),
            "price": [10.0] * len(statuses),
            "status": statuses,
            "reason": [""] * len(statuses),
        }
    ).to_csv(root / "paper_orders.csv", index=False)


def _latest_daily_date(root: Path) -> str:
    path = root / "paper_daily.csv"
    if not path.exists():
        return "2024-03-29"
    daily = pd.read_csv(path)
    if daily.empty:
        return "2024-03-29"
    return str(daily["date"].iloc[-1])[:10]
