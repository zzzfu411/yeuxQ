from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from quantify.market import (
    build_market_context_readiness_from_payload,
    build_market_context_readiness_from_report,
    write_market_context_readiness,
)


def test_market_context_readiness_blocks_missing_context(tmp_path: Path) -> None:
    readiness = build_market_context_readiness_from_report(tmp_path, as_of="2026-06-09")
    out = write_market_context_readiness(readiness, tmp_path)

    payload = json.loads((out / "market_context_readiness.json").read_text(encoding="utf-8"))
    markdown = (out / "market_context_readiness.md").read_text(encoding="utf-8")

    assert readiness.decision == "BLOCK"
    assert readiness.source == "missing"
    assert payload["findings"][0]["code"] == "MARKET_CONTEXT_MISSING"
    assert "run_market_regime.py" in payload["next_actions"][0]
    assert "cannot override" in markdown


def test_market_context_readiness_passes_cache_market_regime(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "market_regime.json",
        {"status": "PASS", "label": "neutral", "as_of": "2026-06-09"},
    )

    readiness = build_market_context_readiness_from_report(tmp_path, as_of="2026-06-09")

    assert readiness.decision == "PASS"
    assert readiness.source == "market_regime"
    assert readiness.label == "neutral"
    assert readiness.findings == []
    assert readiness.to_candidate_review()["status"] == "PASS"


def test_market_context_readiness_watches_reviewed_snapshot(tmp_path: Path) -> None:
    _write_reviewed_snapshot(tmp_path)

    readiness = build_market_context_readiness_from_report(tmp_path, as_of="2026-06-09")
    review = readiness.to_candidate_review()

    assert readiness.decision == "WATCH"
    assert readiness.source == "market_context_snapshot"
    assert any(item.code == "SNAPSHOT_ADVISORY_ONLY" for item in readiness.findings)
    assert review["status"] == "WATCH"
    assert "Only market_context_snapshot" in review["message"]


def test_market_context_readiness_blocks_incomplete_snapshot(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "market_context_snapshot.json",
        {
            "artifact_type": "market_context_snapshot",
            "status": "PASS",
            "label": "risk_on",
            "can_replace_market_regime": False,
        },
    )

    readiness = build_market_context_readiness_from_report(tmp_path, as_of="2026-06-09")
    codes = {item.code for item in readiness.findings}

    assert readiness.decision == "BLOCK"
    assert "SNAPSHOT_REVIEW_METADATA_MISSING" in codes
    assert "SNAPSHOT_INDEX_METRICS_MISSING" in codes


def test_market_context_readiness_blocks_stale_market_regime() -> None:
    readiness = build_market_context_readiness_from_payload(
        {
            "source": "market_regime",
            "payload": {"status": "PASS", "label": "neutral", "as_of": "2026-05-01"},
            "artifact": "market_regime.json",
        },
        as_of="2026-06-09",
        max_staleness_days=7,
    )

    assert readiness.decision == "BLOCK"
    assert any(item.code == "MARKET_CONTEXT_STALE" for item in readiness.findings)


def test_market_context_readiness_cli_returns_nonzero_on_block(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_market_context_readiness.py",
            "--report-dir",
            str(tmp_path),
            "--as-of",
            "2026-06-09",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((tmp_path / "market_context_readiness.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["decision"] == "BLOCK"


def _write_reviewed_snapshot(root: Path) -> None:
    _write_json(
        root / "market_context_snapshot.json",
        {
            "artifact_type": "market_context_snapshot",
            "status": "PASS",
            "label": "neutral",
            "as_of": "2026-06-09",
            "source": "reviewed index CSV export",
            "reviewed_by": "tester",
            "reviewed_at": "2026-06-09",
            "index_metrics": [
                {
                    "name": "CSI300",
                    "return_20d": 0.01,
                    "return_60d": 0.02,
                    "return_120d": 0.03,
                    "max_drawdown": 0.06,
                    "annualized_volatility": 0.20,
                }
            ],
            "can_replace_market_regime": False,
            "can_approve_strategy": False,
            "can_generate_broker_orders": False,
        },
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
