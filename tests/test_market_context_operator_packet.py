from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys

from quantify.market import (
    build_market_context_operator_packet,
    write_market_context_operator_packet,
)


def test_market_context_operator_packet_blocks_missing_context(tmp_path: Path) -> None:
    packet = build_market_context_operator_packet(tmp_path, as_of="2026-06-10")
    out = write_market_context_operator_packet(packet, tmp_path)

    payload = json.loads((out / "market_context_operator_packet.json").read_text(encoding="utf-8"))
    markdown = (out / "market_context_operator_packet.md").read_text(encoding="utf-8")
    rows = list(csv.DictReader((out / "market_context_operator_packet.csv").open(encoding="utf-8-sig")))

    assert packet.decision == "BLOCK"
    assert payload["readiness_source"] == "missing"
    assert payload["missing_item_count"] >= 2
    assert payload["items"][0]["item_type"] == "preferred_artifact"
    assert payload["items"][0]["item_id"] == "market_regime"
    assert any(item["item_id"] == "as_of" for item in payload["items"])
    assert any(item["item_id"] == "index_metrics" for item in payload["items"])
    assert any("run_market_index_discovery.py" in item for item in payload["command_sequence"])
    assert any("write_market_context_snapshot.py" in item for item in payload["command_sequence"])
    assert any("run_market_context_readiness.py" in item for item in payload["command_sequence"])
    assert any("Do not fabricate" in item for item in payload["prohibited_actions"])
    assert rows[0]["item_id"] == "market_regime"
    assert "cannot replace `market_regime.json`" in markdown


def test_market_context_operator_packet_watches_with_reviewed_snapshot(tmp_path: Path) -> None:
    _write_json(tmp_path / "market_context_snapshot.json", _reviewed_snapshot())

    packet = build_market_context_operator_packet(tmp_path, as_of="2026-06-10")

    assert packet.decision == "WATCH"
    assert packet.readiness_source == "market_context_snapshot"
    assert packet.missing_item_count == 1
    assert packet.items[0].item_id == "market_regime"
    assert "cache-derived market_regime.json" in packet.items[0].required_value


def test_market_context_operator_packet_passes_with_cache_market_regime(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "market_regime.json",
        {"status": "PASS", "label": "neutral", "as_of": "2026-06-10"},
    )

    packet = build_market_context_operator_packet(tmp_path, as_of="2026-06-10")

    assert packet.decision == "PASS"
    assert packet.readiness_source == "market_regime"
    assert packet.missing_item_count == 0
    assert packet.items == []


def test_market_context_operator_packet_cli_returns_nonzero_on_block(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_market_context_operator_packet.py",
            "--report-dir",
            str(tmp_path),
            "--as-of",
            "2026-06-10",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((tmp_path / "market_context_operator_packet.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["decision"] == "BLOCK"


def _reviewed_snapshot() -> dict[str, object]:
    return {
        "artifact_type": "market_context_snapshot",
        "status": "PASS",
        "label": "neutral",
        "as_of": "2026-06-10",
        "source": "reviewed index CSV export",
        "reviewed_by": "tester",
        "reviewed_at": "2026-06-10",
        "index_metrics": [
            {
                "name": "CSI300",
                "return_20d": 0.01,
                "return_60d": 0.02,
                "return_120d": 0.03,
                "max_drawdown": 0.06,
                "annualized_volatility": 0.20,
                "breadth_above_ma20": 0.55,
                "breadth_above_ma60": 0.50,
                "note": "rows reviewed by tester.",
            }
        ],
        "can_replace_market_regime": False,
        "can_approve_strategy": False,
        "can_generate_broker_orders": False,
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
