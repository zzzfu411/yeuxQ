from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from tests.selection_safe_fixtures import selection_safe_robustness_payload
from tests.statistical_evidence_fixtures import write_statistical_evidence_fixtures

from quantify.ops import update_candidate_registry


def test_strategy_registry_accumulates_candidate_history(tmp_path: Path) -> None:
    run1 = tmp_path / "run1"
    run2 = tmp_path / "run2"
    _write_run(run1, annual_return=0.12, decision="WATCH")
    _write_run(run2, annual_return=0.20, decision="PASS")
    registry_path = tmp_path / "registry" / "strategy_registry.json"

    first = update_candidate_registry(run1, registry_path=registry_path)
    second = update_candidate_registry(run2, registry_path=registry_path)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    core = payload["candidates"]["core_multifactor"]["summary"]

    assert first.run_count == 1
    assert second.run_count == 2
    assert payload["runs"][0]["attestation_status"] == "PASS"
    assert payload["runs"][0]["selection_safety_status"] == "PASS"
    assert payload["runs"][0]["statistical_evidence_status"] == "PASS"
    assert payload["runs"][0]["promotion_eligible_real_observation"] is True
    assert payload["runs"][0]["cache_logical_bar_fingerprint"]
    assert payload["runs"][0]["cache_latest_import_batch_id"]
    assert core["observations"] == 2
    assert core["pass_count"] == 1
    assert core["watch_count"] == 1
    assert core["real_observation_count"] == 2
    assert core["unattested_observation_count"] == 0
    assert core["selection_unsafe_observation_count"] == 0
    assert core["statistical_unsafe_observation_count"] == 0
    assert core["demo_observation_count"] == 0
    assert core["promotion_eligible"] is False
    assert "3 real-data observations" in core["promotion_reason"]
    assert (registry_path.parent / "strategy_registry.md").exists()
    assert (run2 / "strategy_registry_snapshot.json").exists()


def test_strategy_registry_does_not_promote_demo_only_history(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry" / "strategy_registry.json"
    for idx in range(3):
        run = tmp_path / f"demo_run_{idx}"
        _write_run(run, annual_return=0.50, decision="PASS", demo_data_used=True)
        update_candidate_registry(run, registry_path=registry_path)

    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    summary = payload["candidates"]["core_multifactor"]["summary"]

    assert summary["demo_observation_count"] == 3
    assert summary["real_observation_count"] == 0
    assert summary["promotion_eligible"] is False
    assert "real-data observations" in summary["promotion_reason"]


def test_strategy_registry_excludes_unattested_non_demo_observation(tmp_path: Path) -> None:
    run = tmp_path / "unattested_run"
    registry_path = tmp_path / "registry" / "strategy_registry.json"
    _write_run(run, annual_return=0.50, decision="PASS", attested=False)

    update_candidate_registry(run, registry_path=registry_path)

    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    run_record = payload["runs"][0]
    candidate = payload["candidates"]["core_multifactor"]
    history = candidate["history"][0]
    summary = candidate["summary"]
    assert run_record["attestation_status"] == "UNATTESTED"
    assert run_record["cache_logical_bar_fingerprint"] == ""
    assert history["attestation_status"] == "UNATTESTED"
    assert history["attested_real_observation"] is False
    assert history["promotion_eligible_real_observation"] is False
    assert summary["real_observation_count"] == 0
    assert summary["unattested_observation_count"] == 1
    assert summary["selection_unsafe_observation_count"] == 0
    assert "excluded because data attestation did not pass" in summary["promotion_reason"]


def test_strategy_registry_includes_attested_selection_safe_observation(tmp_path: Path) -> None:
    run = tmp_path / "safe_run"
    registry_path = tmp_path / "registry" / "strategy_registry.json"
    _write_run(run, annual_return=0.20, decision="PASS")

    update_candidate_registry(run, registry_path=registry_path)

    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    run_record = payload["runs"][0]
    candidate = payload["candidates"]["core_multifactor"]
    history = candidate["history"][0]
    summary = candidate["summary"]
    assert run_record["attestation_status"] == "PASS"
    assert run_record["walk_forward_selection_safe"] is True
    assert run_record["candidate_walk_forward_selection_safe"] is True
    assert run_record["selection_safe"] is True
    assert run_record["statistical_evidence_safe"] is True
    assert run_record["promotion_eligible_real_observation"] is True
    assert history["attested_real_observation"] is True
    assert history["selection_safe"] is True
    assert history["promotion_eligible_real_observation"] is True
    assert summary["real_observation_count"] == 1
    assert summary["selection_unsafe_observation_count"] == 0
    assert summary["statistical_unsafe_observation_count"] == 0


def test_strategy_registry_excludes_missing_statistical_evidence(tmp_path: Path) -> None:
    run = tmp_path / "missing_statistical_evidence"
    registry_path = tmp_path / "registry" / "strategy_registry.json"
    _write_run(
        run,
        annual_return=0.20,
        decision="PASS",
        statistical_evidence=False,
    )

    update_candidate_registry(run, registry_path=registry_path)

    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    run_record = payload["runs"][0]
    summary = payload["candidates"]["core_multifactor"]["summary"]
    assert run_record["attested_real_observation"] is True
    assert run_record["selection_safe"] is True
    assert run_record["statistical_evidence_safe"] is False
    assert run_record["promotion_eligible_real_observation"] is False
    assert summary["real_observation_count"] == 0
    assert summary["statistical_unsafe_observation_count"] == 1
    assert "benchmark, multiple-testing" in summary["promotion_reason"]


def test_strategy_registry_excludes_legacy_missing_selection_safety(tmp_path: Path) -> None:
    run = tmp_path / "legacy_run"
    registry_path = tmp_path / "registry" / "strategy_registry.json"
    _write_run(
        run,
        annual_return=0.20,
        decision="PASS",
        walk_forward_selection_safe=None,
        candidate_walk_forward_selection_safe=None,
    )

    update_candidate_registry(run, registry_path=registry_path)

    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    run_record = payload["runs"][0]
    candidate = payload["candidates"]["core_multifactor"]
    history = candidate["history"][0]
    summary = candidate["summary"]
    assert run_record["attestation_status"] == "PASS"
    assert run_record["attested_real_observation"] is True
    assert run_record["walk_forward_selection_safe"] is False
    assert run_record["candidate_walk_forward_selection_safe"] is False
    assert run_record["selection_safety_status"] == "UNSAFE"
    assert "walk_forward_report.json" in run_record["selection_safety_reason"]
    assert "candidate_walk_forward_report.json" in run_record["selection_safety_reason"]
    assert run_record["promotion_eligible_real_observation"] is False
    assert history["attestation_status"] == "PASS"
    assert history["selection_safe"] is False
    assert history["promotion_eligible_real_observation"] is False
    assert summary["real_observation_count"] == 0
    assert summary["unattested_observation_count"] == 0
    assert summary["selection_unsafe_observation_count"] == 1
    assert "walk-forward selection safety did not pass" in summary["promotion_reason"]


def test_strategy_registry_excludes_diagnostic_only_robustness(tmp_path: Path) -> None:
    run = tmp_path / "diagnostic_robustness"
    registry_path = tmp_path / "registry" / "strategy_registry.json"
    _write_run(
        run,
        annual_return=0.20,
        decision="PASS",
        robustness_selection_safe=False,
    )

    update_candidate_registry(run, registry_path=registry_path)

    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    run_record = payload["runs"][0]
    summary = payload["candidates"]["core_multifactor"]["summary"]
    assert run_record["attestation_status"] == "PASS"
    assert run_record["robustness_selection_safe"] is False
    assert run_record["selection_safety_status"] == "UNSAFE"
    assert "robustness_report.json" in run_record["selection_safety_reason"]
    assert summary["real_observation_count"] == 0
    assert summary["selection_unsafe_observation_count"] == 1


def test_strategy_registry_requires_csv_specific_attestation_for_csv_route(
    tmp_path: Path,
) -> None:
    run = tmp_path / "csv_run"
    registry_path = tmp_path / "registry" / "strategy_registry.json"
    _write_run(
        run,
        annual_return=0.20,
        decision="PASS",
        data_source="local_csv",
        csv_attested=False,
    )

    update_candidate_registry(run, registry_path=registry_path)

    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    run_record = payload["runs"][0]
    summary = payload["candidates"]["core_multifactor"]["summary"]
    assert run_record["attestation_status"] == "UNATTESTED"
    assert "csv_dataset_fingerprint" in run_record["attestation_reason"]
    assert "data_source_csv_qa_status=PASS" in run_record["attestation_reason"]
    assert summary["real_observation_count"] == 0
    assert summary["unattested_observation_count"] == 1


def test_strategy_registry_marks_real_strategy_eligible_after_repeated_passes(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry" / "strategy_registry.json"
    for idx, decision in enumerate(["PASS", "WATCH", "PASS"]):
        run = tmp_path / f"real_run_{idx}"
        _write_run(
            run,
            annual_return=0.22,
            decision=decision,
            demo_data_used=False,
            candidate_walk_forward_status="PASS",
            candidate_regime_status="PASS",
        )
        update_candidate_registry(run, registry_path=registry_path)

    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    summary = payload["candidates"]["core_multifactor"]["summary"]

    assert summary["real_observation_count"] == 3
    assert summary["selection_unsafe_observation_count"] == 0
    assert summary["real_pass_count"] == 2
    assert summary["real_candidate_walk_forward_observation_count"] == 3
    assert summary["real_candidate_walk_forward_pass_count"] == 3
    assert summary["real_avg_candidate_walk_forward_positive_return_ratio"] == 1.0
    assert summary["real_worst_candidate_walk_forward_return"] == 0.01
    assert summary["real_worst_candidate_walk_forward_drawdown"] == 0.06
    assert summary["real_candidate_regime_observation_count"] == 3
    assert summary["real_candidate_regime_pass_count"] == 3
    assert summary["promotion_eligible"] is True
    assert "not a live trading instruction" in summary["promotion_reason"]


def test_strategy_registry_requires_candidate_walk_forward_for_promotion(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry" / "strategy_registry.json"
    for idx, decision in enumerate(["PASS", "WATCH", "PASS"]):
        run = tmp_path / f"real_run_{idx}"
        _write_run(run, annual_return=0.22, decision=decision, demo_data_used=False)
        update_candidate_registry(run, registry_path=registry_path)

    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    summary = payload["candidates"]["core_multifactor"]["summary"]

    assert summary["real_observation_count"] == 3
    assert summary["real_candidate_walk_forward_observation_count"] == 0
    assert summary["promotion_eligible"] is False
    assert "candidate walk-forward" in summary["promotion_reason"]


def test_strategy_registry_requires_candidate_regime_validation_for_promotion(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry" / "strategy_registry.json"
    for idx, decision in enumerate(["PASS", "WATCH", "PASS"]):
        run = tmp_path / f"real_run_{idx}"
        _write_run(
            run,
            annual_return=0.22,
            decision=decision,
            demo_data_used=False,
            candidate_walk_forward_status="PASS",
        )
        update_candidate_registry(run, registry_path=registry_path)

    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    summary = payload["candidates"]["core_multifactor"]["summary"]

    assert summary["real_candidate_walk_forward_observation_count"] == 3
    assert summary["real_candidate_regime_observation_count"] == 0
    assert summary["promotion_eligible"] is False
    assert "candidate regime validation" in summary["promotion_reason"]


def test_strategy_registry_blocks_promotion_on_candidate_walk_forward_tail_loss(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry" / "strategy_registry.json"
    for idx, decision in enumerate(["PASS", "WATCH", "PASS"]):
        run = tmp_path / f"real_run_{idx}"
        _write_run(
            run,
            annual_return=0.22,
            decision=decision,
            demo_data_used=False,
            candidate_walk_forward_status="PASS",
            candidate_regime_status="PASS",
            candidate_walk_forward_worst_return=-0.12 if idx == 2 else 0.01,
        )
        update_candidate_registry(run, registry_path=registry_path)

    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    summary = payload["candidates"]["core_multifactor"]["summary"]

    assert summary["real_worst_candidate_walk_forward_return"] == -0.12
    assert summary["promotion_eligible"] is False
    assert "lost more than 10%" in summary["promotion_reason"]


def test_strategy_registry_cli_updates_json(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_run(run_dir, annual_return=0.12, decision="WATCH")
    registry_path = tmp_path / "strategy_registry.json"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/update_strategy_registry.py",
            "--report-dir",
            str(run_dir),
            "--registry",
            str(registry_path),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert registry_path.exists()
    assert "core_multifactor" in registry_path.read_text(encoding="utf-8")


def _write_run(
    root: Path,
    *,
    annual_return: float,
    decision: str,
    demo_data_used: bool = False,
    candidate_walk_forward_status: str | None = None,
    candidate_regime_status: str | None = None,
    candidate_walk_forward_positive_ratio: float = 1.0,
    candidate_walk_forward_worst_return: float = 0.01,
    candidate_walk_forward_worst_drawdown: float = 0.06,
    walk_forward_selection_safe: object = True,
    candidate_walk_forward_selection_safe: object = True,
    attested: bool = True,
    data_source: str = "akshare",
    csv_attested: bool = True,
    robustness_selection_safe: object = True,
    statistical_evidence: bool = True,
) -> None:
    root.mkdir(parents=True)
    (root / "candidate_selection.json").write_text(
        json.dumps(
            {
                "status": decision,
                "best_candidate": "core_multifactor",
                "market_regime": {"label": "neutral", "status": "PASS"},
                "results": [
                    {
                        "name": "core_multifactor",
                        "description": "Core test candidate",
                        "factors": ["momentum", "low_volatility"],
                        "score": {"decision": decision, "score": 80.0},
                        "metrics": {
                            "annualized_return": annual_return,
                            "max_drawdown": 0.08,
                            "sharpe_ratio": 1.1,
                        },
                        "reject_rate": 0.0,
                        "avg_turnover_pct": 0.2,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "weekly_review.json").write_text(json.dumps({"decision": "research_only"}), encoding="utf-8")
    (root / "data_audit.json").write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    robustness_payload: dict[str, object] = selection_safe_robustness_payload()
    if robustness_selection_safe is not True:
        robustness_payload = {"status": "PASS"}
        if robustness_selection_safe is not None:
            robustness_payload["selection_safe"] = robustness_selection_safe
    (root / "robustness_report.json").write_text(
        json.dumps(robustness_payload),
        encoding="utf-8",
    )
    (root / "llm_review.json").write_text(json.dumps({"decision": "WATCH"}), encoding="utf-8")
    walk_forward_payload = _selection_contract_payload(candidate=False)
    if walk_forward_selection_safe is not True:
        walk_forward_payload = {}
    if walk_forward_selection_safe is not None:
        walk_forward_payload["selection_safe"] = walk_forward_selection_safe
    (root / "walk_forward_report.json").write_text(
        json.dumps(walk_forward_payload), encoding="utf-8"
    )
    candidate_walk_forward_payload = _selection_contract_payload(candidate=True)
    if candidate_walk_forward_selection_safe is not True:
        candidate_walk_forward_payload = {}
    if candidate_walk_forward_selection_safe is not None:
        candidate_walk_forward_payload["selection_safe"] = candidate_walk_forward_selection_safe
    if candidate_walk_forward_status is not None:
        candidate_walk_forward_payload.update(
            {
                "status": candidate_walk_forward_status,
                "best_candidate": "core_multifactor",
                "summaries": [
                    {
                        "candidate": "core_multifactor",
                        "status": candidate_walk_forward_status,
                        "window_count": 3,
                        "pass_count": 3 if candidate_walk_forward_status == "PASS" else 1,
                        "watch_count": 0 if candidate_walk_forward_status == "PASS" else 2,
                        "block_count": 0,
                        "avg_total_return": 0.04,
                        "avg_max_drawdown": 0.05,
                        "avg_sharpe_ratio": 1.0,
                        "avg_reject_rate": 0.0,
                        "positive_return_ratio": candidate_walk_forward_positive_ratio,
                        "worst_total_return": candidate_walk_forward_worst_return,
                        "worst_max_drawdown": candidate_walk_forward_worst_drawdown,
                        "notes": [],
                    }
                ],
            }
        )
    (root / "candidate_walk_forward_report.json").write_text(
        json.dumps(candidate_walk_forward_payload),
        encoding="utf-8",
    )
    if candidate_regime_status is not None:
        (root / "candidate_regime_validation_report.json").write_text(
            json.dumps(
                {
                    "status": candidate_regime_status,
                    "best_candidate": "core_multifactor",
                    "summaries": [
                        {
                            "candidate": "core_multifactor",
                            "status": candidate_regime_status,
                            "regime_count": 2,
                            "known_regime_count": 2,
                            "adverse_regime_window_count": 1,
                            "pass_bucket_count": 2 if candidate_regime_status == "PASS" else 0,
                            "watch_bucket_count": 0 if candidate_regime_status == "PASS" else 2,
                            "block_bucket_count": 0,
                            "avg_total_return": 0.04,
                            "avg_max_drawdown": 0.05,
                            "avg_sharpe_ratio": 1.0,
                            "notes": [],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
    (root / "summary.json").write_text(
        json.dumps({"assumptions": {"demo_data_used": demo_data_used}}),
        encoding="utf-8",
    )
    data_version = {
        "data_source": data_source,
        "cache_logical_bar_fingerprint": "logical-bars-fingerprint-v1" if attested else "",
        "cache_logical_bar_fingerprint_algorithm": "sha256:quantify.logical-bars.v1",
        "cache_latest_import_batch_id": "import-batch-v1",
        "cache_lineage_schema_version": "1",
        "data_source_qa_status": "PASS",
    }
    if "csv" in data_source.lower():
        data_version.update(
            {
                "csv_dataset_fingerprint": "csv-dataset-fingerprint-v1"
                if csv_attested
                else "",
                "data_source_csv_qa_status": "PASS" if csv_attested else "NOT_EVALUATED",
            }
        )
    (root / "run_manifest.json").write_text(
        json.dumps(
            {
                "data_source": data_source,
                "demo_data_used": demo_data_used,
                "data_version": data_version,
            }
        ),
        encoding="utf-8",
    )
    if (
        statistical_evidence
        and attested
        and walk_forward_selection_safe is True
        and candidate_walk_forward_selection_safe is True
        and robustness_selection_safe is True
    ):
        write_statistical_evidence_fixtures(root, candidate="core_multifactor")


def _selection_contract_payload(*, candidate: bool) -> dict[str, object]:
    phases = {
        "name": "wf_01",
        "mode": "expanding",
        "train": {"start": "d01", "end": "d02", "trading_day_count": 2},
        "purge": {"start": "", "end": "", "trading_day_count": 0},
        "selection": {"start": "d03", "end": "d03", "trading_day_count": 1},
        "embargo": {"start": "", "end": "", "trading_day_count": 0},
        "test": {"start": "d04", "end": "d04", "trading_day_count": 1},
    }
    window: dict[str, object] = {
        "name": "wf_01",
        "start": "d04",
        "end": "d04",
        "phases": phases,
    }
    payload: dict[str, object] = {
        "artifact_type": "candidate_walk_forward_report" if candidate else "walk_forward_report",
        "schema_version": 2,
        "selection_protocol": "quantify.walk-forward-selection.v2",
        "selection_safe": True,
        "test_used_for_selection": False,
        "configuration": {
            "mode": "expanding",
            "train_days": 2,
            "purge_days": 0,
            "selection_days": 1,
            "embargo_days": 0,
            "test_days": 1,
            "step_days": 1,
        },
        "window_count": 1,
        "windows": [window],
    }
    if candidate:
        window.update({"candidate": "core_multifactor", "window": "wf_01", "selection_rank": 1})
        payload.update(
            {
                "candidate_count": 1,
                "selected_candidate": "core_multifactor",
                "best_candidate": "core_multifactor",
                "selections": [
                    {
                        "candidate": "core_multifactor",
                        "window": "wf_01",
                        "rank": 1,
                    }
                ],
            }
        )
    return payload
