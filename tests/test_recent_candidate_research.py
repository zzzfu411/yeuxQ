from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from quantify.ops.recent_candidate_research import (
    build_recent_candidate_research_report,
    discover_recent_candidate_report_dirs,
    resolve_recent_candidate_research_dir,
    write_recent_candidate_research_report,
)


def test_recent_candidate_research_ranks_least_bad_candidate(tmp_path: Path) -> None:
    search_dir = tmp_path / "research_recent"
    _write_candidate_run(
        search_dir / "20260618_010000_low_turnover",
        candidate="low_turnover_price_volume",
        annualized_return=-0.1870,
        return_margin=-0.4231,
        max_drawdown=0.0779,
        sharpe_ratio=-1.62,
        avg_turnover_pct=0.9334,
        reject_rate=0.0,
        positive_return_ratio=0.6667,
    )
    _write_candidate_run(
        search_dir / "20260618_020000_defensive_cash_guard",
        candidate="defensive_cash_guard_price_volume",
        annualized_return=-0.1196,
        return_margin=-0.4531,
        max_drawdown=0.0559,
        sharpe_ratio=-1.33,
        avg_turnover_pct=0.8688,
        reject_rate=0.0,
        positive_return_ratio=0.3333,
    )

    report = build_recent_candidate_research_report(search_dir, as_of="2026-06-18")

    assert report.status == "RESEARCH_ONLY"
    assert report.report_count == 2
    assert report.candidate_count == 2
    assert report.best_research_candidate == "defensive_cash_guard_price_volume"
    assert report.candidate_summaries[0].candidate == "defensive_cash_guard_price_volume"
    assert "selection=BLOCK/BLOCK" in report.best_research_reason
    assert report.can_enter_paper is False
    assert report.can_generate_broker_orders is False


def test_recent_candidate_research_writer_and_cli_emit_files(tmp_path: Path) -> None:
    search_dir = tmp_path / "research_recent"
    output_dir = tmp_path / "first_million"
    run_dir = search_dir / "20260618_010000_trend_filtered"
    _write_candidate_run(
        run_dir,
        candidate="trend_filtered_price_volume",
        annualized_return=-0.1667,
        return_margin=-0.5002,
        max_drawdown=0.0967,
        sharpe_ratio=-1.00,
        avg_turnover_pct=0.8275,
        reject_rate=0.0390,
        positive_return_ratio=0.6667,
    )

    report = build_recent_candidate_research_report(search_dir, as_of="2026-06-18")
    out = write_recent_candidate_research_report(report, output_dir)
    payload = json.loads((out / "recent_candidate_research.json").read_text(encoding="utf-8"))

    assert payload["best_research_candidate"] == "trend_filtered_price_volume"
    assert (out / "recent_candidate_research.md").exists()
    assert (out / "recent_candidate_research.csv").exists()

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_recent_candidate_research.py",
            "--search-dir",
            str(search_dir),
            "--output-dir",
            str(output_dir),
            "--as-of",
            "2026-06-18",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    payload = json.loads((output_dir / "recent_candidate_research.json").read_text(encoding="utf-8"))
    assert payload["candidate_count"] == 1
    assert payload["status"] == "RESEARCH_ONLY"


def test_recent_candidate_research_discovery_filters_candidate_dirs(tmp_path: Path) -> None:
    search_dir = tmp_path / "research_recent"
    ignored = search_dir / "notes_only"
    ignored.mkdir(parents=True)
    _write_candidate_run(
        search_dir / "20260618_010000_a",
        candidate="a",
        annualized_return=-0.1,
        return_margin=-0.2,
        max_drawdown=0.05,
        sharpe_ratio=-0.5,
        avg_turnover_pct=0.8,
        reject_rate=0.0,
        positive_return_ratio=0.5,
    )
    _write_candidate_run(
        search_dir / "20260618_020000_b",
        candidate="b",
        annualized_return=-0.2,
        return_margin=-0.3,
        max_drawdown=0.06,
        sharpe_ratio=-0.7,
        avg_turnover_pct=0.9,
        reject_rate=0.0,
        positive_return_ratio=0.4,
    )

    dirs = discover_recent_candidate_report_dirs(search_dir, max_report_dirs=1)

    assert len(dirs) == 1
    assert dirs[0].name == "20260618_020000_b"


def test_resolve_recent_candidate_research_dir_prefers_real_candidate_search_root(tmp_path: Path) -> None:
    _write_candidate_run(
        tmp_path / "research_recent" / "20260618_010000_a",
        candidate="a",
        annualized_return=-0.1,
        return_margin=-0.2,
        max_drawdown=0.05,
        sharpe_ratio=-0.5,
        avg_turnover_pct=0.8,
        reject_rate=0.0,
        positive_return_ratio=0.5,
    )
    _write_candidate_run(
        tmp_path / "research_recent_real_candidates" / "20260618_020000_b",
        candidate="b",
        annualized_return=0.1,
        return_margin=-0.1,
        max_drawdown=0.06,
        sharpe_ratio=0.7,
        avg_turnover_pct=0.9,
        reject_rate=0.0,
        positive_return_ratio=0.4,
    )

    resolved = resolve_recent_candidate_research_dir(tmp_path)

    assert resolved == tmp_path / "research_recent_real_candidates"


def test_recent_candidate_research_surfaces_candidate_specific_focus_actions(tmp_path: Path) -> None:
    search_dir = tmp_path / "research_recent"
    _write_candidate_run(
        search_dir / "20260618_030000_low_turnover_low_conc",
        candidate="low_turnover_low_concentration_price_volume",
        annualized_return=0.1246,
        return_margin=-0.1200,
        max_drawdown=0.1390,
        sharpe_ratio=0.81,
        avg_turnover_pct=0.7100,
        reject_rate=0.0,
        positive_return_ratio=0.50,
    )
    _write_candidate_run(
        search_dir / "20260618_040000_trend_filtered_quarterly",
        candidate="trend_filtered_quarterly_price_volume",
        annualized_return=0.2114,
        return_margin=-0.0800,
        max_drawdown=0.1830,
        sharpe_ratio=1.13,
        avg_turnover_pct=0.6200,
        reject_rate=0.0,
        positive_return_ratio=0.50,
    )

    report = build_recent_candidate_research_report(search_dir, as_of="2026-06-18")

    reasons = {item.candidate: item.reason for item in report.candidate_summaries}
    commands = {item.candidate: item.next_command for item in report.candidate_summaries}

    assert "focus=prove lower concentration is better than the baseline low-turnover variant" in reasons[
        "low_turnover_low_concentration_price_volume"
    ]
    assert "focus=prove quarterly cadence is better than the monthly trend-filtered baseline" in reasons[
        "trend_filtered_quarterly_price_volume"
    ]
    assert report.best_research_candidate == "trend_filtered_quarterly_price_volume"
    assert any("trend_filtered_quarterly_price_volume" in action for action in report.next_actions)
    assert any("direct cadence comparison against `trend_filtered_price_volume`" in action for action in report.next_actions)
    assert "--candidate low_turnover_price_volume" in commands["low_turnover_low_concentration_price_volume"]
    assert "--candidate trend_filtered_price_volume" in commands["trend_filtered_quarterly_price_volume"]


def test_recent_candidate_research_prioritizes_liquidity_neutral_lineage_review(
    tmp_path: Path,
) -> None:
    search_dir = tmp_path / "research_recent"
    _write_candidate_run(
        search_dir / "20260705_liquidity_neutral_guard",
        candidate="liquidity_neutral_momentum_guard_price_volume",
        annualized_return=0.2160,
        return_margin=-0.1175,
        max_drawdown=0.0813,
        sharpe_ratio=1.52,
        avg_turnover_pct=0.6837,
        reject_rate=0.0,
        positive_return_ratio=0.3333,
    )

    report = build_recent_candidate_research_report(search_dir, as_of="2026-07-05")

    assert report.status == "RESEARCH_ONLY"
    assert report.best_research_candidate == "liquidity_neutral_momentum_guard_price_volume"
    assert "focus=close the slow-signal to liquidity-neutral guarded lineage" in (
        report.best_research_reason
    )
    assert "--candidate stable_universe_slow_signal_price_volume" in (
        report.best_research_command
    )
    assert "--candidate long_momentum_liquidity_monthly_price_volume" in (
        report.best_research_command
    )
    assert "--candidate liquidity_neutral_momentum_guard_price_volume" in (
        report.best_research_command
    )
    assert any("three-candidate lineage review" in action for action in report.next_actions)
    assert report.can_enter_paper is False
    assert report.can_enter_micro_live_ready is False
    assert report.can_generate_broker_orders is False


def _write_candidate_run(
    report_dir: Path,
    *,
    candidate: str,
    annualized_return: float,
    return_margin: float,
    max_drawdown: float,
    sharpe_ratio: float,
    avg_turnover_pct: float,
    reject_rate: float,
    positive_return_ratio: float,
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        report_dir / "candidate_selection.json",
        {
            "status": "BLOCK",
            "top_candidate": candidate,
            "selected_candidate": "",
            "results": [
                {
                    "name": candidate,
                    "score": {"decision": "BLOCK", "score": 0.0},
                    "metrics": {
                        "annualized_return": annualized_return,
                        "max_drawdown": max_drawdown,
                        "sharpe_ratio": sharpe_ratio,
                    },
                    "avg_turnover_pct": avg_turnover_pct,
                    "reject_rate": reject_rate,
                    "capital_goal_fit_review": {
                        "status": "BLOCK",
                        "return_margin": return_margin,
                        "findings": ["Annual return is below required path."],
                    },
                }
            ],
        },
    )
    _write_json(
        report_dir / "candidate_research_precheck.json",
        {
            "status": "RESEARCH_ONLY",
            "promotion_decision": "BLOCK",
            "candidates": [candidate],
            "missing_promotion_evidence": [
                "PASS source QA, guarded offline intake, data audit, and run manifest evidence."
            ],
        },
    )
    _write_json(
        report_dir / "candidate_walk_forward_report.json",
        {
            "status": "WATCH",
            "summaries": [
                {
                    "candidate": candidate,
                    "status": "WATCH",
                    "window_count": 3,
                    "positive_return_ratio": positive_return_ratio,
                    "worst_total_return": annualized_return / 4.0,
                    "worst_max_drawdown": max_drawdown,
                }
            ],
        },
    )
    _write_json(
        report_dir / "candidate_factor_diagnostics.json",
        {
            "status": "WATCH",
            "diagnostics": [
                {
                    "candidate": candidate,
                    "status": "WATCH",
                    "component_count": 3,
                    "component_pass_count": 0,
                    "dependency_ratio": 0.0,
                    "findings": ["WATCH: component PASS ratio 0% is below 40%."],
                }
            ],
        },
    )
    _write_json(
        report_dir / "candidate_regime_validation_report.json",
        {
            "status": "WATCH",
            "summaries": [
                {
                    "candidate": candidate,
                    "status": "WATCH",
                    "known_regime_count": 2,
                    "adverse_regime_window_count": 2,
                    "block_bucket_count": 0,
                    "notes": ["Regime-stratified validation is watch-only."],
                }
            ],
        },
    )
    _write_json(
        report_dir / "candidate_stress_matrix.json",
        {
            "status": "RESEARCH_ONLY",
            "promotion_decision": "BLOCK",
            "summaries": [
                {
                    "candidate": candidate,
                    "status": "WATCH",
                    "scenario_count": 4,
                    "pass_count": 0,
                    "watch_count": 4,
                    "block_count": 0,
                    "worst_total_return": annualized_return / 5.0,
                    "worst_max_drawdown": max_drawdown,
                    "max_turnover_pct": avg_turnover_pct,
                    "findings": ["No stress scenario reached PASS."],
                }
            ],
        },
    )


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
