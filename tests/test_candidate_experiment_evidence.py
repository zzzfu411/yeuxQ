from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.research.candidate_experiment_evidence import (
    sync_candidate_experiment_evidence,
    write_candidate_experiment_evidence,
)


def test_candidate_experiment_evidence_copies_foundational_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "weekly"
    experiment = tmp_path / "candidate_experiments" / "run"
    _write_foundational_artifacts(source)

    report = sync_candidate_experiment_evidence(source, experiment)
    out = write_candidate_experiment_evidence(report, experiment)

    payload = json.loads((out / "candidate_experiment_evidence.json").read_text(encoding="utf-8"))
    assert report.status == "PASS"
    assert payload["status"] == "PASS"
    assert (experiment / "summary.json").exists()
    assert (experiment / "run_manifest.json").exists()
    assert (experiment / "orders.csv").exists()
    assert all(item["status"] == "PASS" for item in payload["copied_artifacts"])


def test_candidate_experiment_evidence_blocks_demo_summary(tmp_path: Path) -> None:
    source = tmp_path / "weekly"
    experiment = tmp_path / "candidate_experiments" / "run"
    _write_foundational_artifacts(source, demo_data_used=True)

    report = sync_candidate_experiment_evidence(source, experiment)

    assert report.status == "BLOCK"
    assert any("summary" in blocker for blocker in report.blockers)


def test_candidate_experiment_evidence_cli_returns_nonzero_on_missing_required(
    tmp_path: Path,
) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_candidate_experiment_evidence.py",
            "--source-report-dir",
            str(tmp_path / "missing"),
            "--output-dir",
            str(tmp_path / "experiment"),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads(
        (tmp_path / "experiment" / "candidate_experiment_evidence.json").read_text(encoding="utf-8")
    )
    assert completed.returncode == 2
    assert payload["status"] == "BLOCK"
    assert any("summary" in blocker for blocker in payload["blockers"])


def _write_foundational_artifacts(source: Path, *, demo_data_used: bool = False) -> None:
    source.mkdir(parents=True, exist_ok=True)
    _write_json(
        source / "summary.json",
        {
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {
                "demo_data_used": demo_data_used,
                "in_sample_end": "2023-12-29",
                "out_sample_start": "2024-01-02",
            },
        },
    )
    _write_json(source / "run_manifest.json", {"demo_data_used": demo_data_used})
    _write_json(source / "real_data_bootstrap.json", {"decision": "PASS"})
    _write_json(source / "real_data_gate.json", {"decision": "PASS"})
    _write_json(source / "data_audit.json", {"status": "PASS"})
    _write_json(source / "robustness_report.json", {"status": "PASS"})
    _write_json(source / "walk_forward_report.json", {"status": "PASS"})
    _write_json(source / "market_regime.json", {"status": "PASS", "label": "neutral"})
    pd.DataFrame({"status": ["filled"], "symbol": ["600000"]}).to_csv(source / "orders.csv", index=False)
    pd.DataFrame({"turnover_pct": [0.1]}).to_csv(source / "turnover.csv", index=False)
    pd.DataFrame({"rank_ic": [0.05, 0.03, 0.04]}).to_csv(source / "factor_ic.csv", index=False)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
