from __future__ import annotations

import json
from pathlib import Path

import pytest

from quantify.paper.plan import build_paper_candidate_plan
from quantify.readiness.gate import evaluate_micro_live_readiness
from quantify.research.candidate_experiment_completion import (
    build_candidate_experiment_completion,
)


_MISSING = object()


@pytest.mark.parametrize(
    ("filename", "finding_code"),
    [
        ("walk_forward_report.json", "WALK_FORWARD_SELECTION_UNSAFE"),
        (
            "candidate_walk_forward_report.json",
            "CANDIDATE_WALK_FORWARD_SELECTION_UNSAFE",
        ),
    ],
)
@pytest.mark.parametrize("selection_safe", [_MISSING, False, "true", True])
def test_readiness_blocks_non_true_walk_forward_selection_safety(
    tmp_path: Path,
    filename: str,
    finding_code: str,
    selection_safe: object,
) -> None:
    payload = _selection_payload(selection_safe)
    _write_json(tmp_path / filename, payload)

    result = evaluate_micro_live_readiness(tmp_path)

    finding = next(item for item in result.findings if item.code == finding_code)
    assert finding.severity == "BLOCK"
    assert finding.message.startswith(
        f"{filename} does not satisfy the selection-safe v2 contract:"
    )


def test_readiness_keeps_missing_walk_forward_findings(tmp_path: Path) -> None:
    result = evaluate_micro_live_readiness(tmp_path)
    codes = {item.code for item in result.findings}

    assert "MISSING_WALK_FORWARD" in codes
    assert "MISSING_CANDIDATE_WALK_FORWARD" in codes
    assert "WALK_FORWARD_SELECTION_UNSAFE" not in codes
    assert "CANDIDATE_WALK_FORWARD_SELECTION_UNSAFE" not in codes


def test_readiness_blocks_diagnostic_only_robustness(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "robustness_report.json",
        {
            "artifact_type": "robustness_report",
            "schema_version": 2,
            "selection_protocol": "quantify.full-sample-robustness.v1",
            "selection_safe": False,
            "test_used_for_selection": False,
            "evidence_role": "diagnostic_only",
            "status": "PASS",
        },
    )

    result = evaluate_micro_live_readiness(tmp_path)

    finding = next(item for item in result.findings if item.code == "ROBUSTNESS_SELECTION_UNSAFE")
    assert finding.severity == "BLOCK"
    assert "diagnostic-only" in finding.message


@pytest.mark.parametrize(
    "filename",
    ["walk_forward_report.json", "candidate_walk_forward_report.json"],
)
@pytest.mark.parametrize("selection_safe", [_MISSING, False, "true", True])
def test_paper_plan_blocks_non_true_walk_forward_selection_safety(
    tmp_path: Path,
    filename: str,
    selection_safe: object,
) -> None:
    _write_json(tmp_path / "candidate_selection.json", {"status": "PASS", "selected_candidate": "core"})
    _write_json(tmp_path / filename, _selection_payload(selection_safe))

    plan = build_paper_candidate_plan(
        tmp_path,
        config_path="config/research.yaml",
        paper_state_dir=tmp_path / "paper",
    )

    evidence = next(item for item in plan.required_evidence if item["artifact"] == filename)
    assert evidence["status"] == "BLOCK"
    assert evidence["message"].startswith(
        f"{filename} does not satisfy the selection-safe v2 contract:"
    )
    assert evidence["message"] in plan.blockers


def test_paper_plan_accepts_complete_v2_selection_contract(tmp_path: Path) -> None:
    _write_json(tmp_path / "candidate_selection.json", {"status": "PASS", "selected_candidate": "core"})
    for filename in ("walk_forward_report.json", "candidate_walk_forward_report.json"):
        _write_json(tmp_path / filename, _complete_selection_payload(filename))

    plan = build_paper_candidate_plan(
        tmp_path,
        config_path="config/research.yaml",
        paper_state_dir=tmp_path / "paper",
    )

    statuses = {
        item["artifact"]: item["status"]
        for item in plan.required_evidence
        if item["artifact"] in {"walk_forward_report.json", "candidate_walk_forward_report.json"}
    }
    assert statuses == {
        "walk_forward_report.json": "PASS",
        "candidate_walk_forward_report.json": "PASS",
    }


def test_paper_plan_blocks_diagnostic_only_robustness(tmp_path: Path) -> None:
    _write_json(tmp_path / "candidate_selection.json", {"status": "PASS", "selected_candidate": "core"})
    _write_json(
        tmp_path / "robustness_report.json",
        {
            "artifact_type": "robustness_report",
            "schema_version": 2,
            "selection_protocol": "quantify.full-sample-robustness.v1",
            "selection_safe": False,
            "test_used_for_selection": False,
            "evidence_role": "diagnostic_only",
            "status": "PASS",
        },
    )

    plan = build_paper_candidate_plan(
        tmp_path,
        config_path="config/research.yaml",
        paper_state_dir=tmp_path / "paper",
    )

    evidence = next(
        item for item in plan.required_evidence if item["artifact"] == "robustness_report.json"
    )
    assert evidence["status"] == "BLOCK"
    assert "diagnostic-only" in evidence["message"]


@pytest.mark.parametrize("selection_safe", [_MISSING, False, "true", True])
def test_candidate_completion_blocks_unsafe_walk_forward_evidence(
    tmp_path: Path,
    selection_safe: object,
) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    walk_forward_path = experiment_dir / "candidate_walk_forward_report.json"
    _write_json(
        tmp_path / "candidate_experiment_launch.json",
        {
            "decision": "PASS",
            "selected_candidate": "core",
            "run_id": "run",
            "experiment_dir": str(experiment_dir),
            "required_outputs": [str(walk_forward_path)],
        },
    )
    _write_json(
        tmp_path / "candidate_experiment_execution.json",
        {
            "decision": "PASS",
            "selected_candidate": "core",
            "run_id": "run",
            "experiment_dir": str(experiment_dir),
            "steps": [],
        },
    )
    payload = _selection_payload(selection_safe)
    payload.update(
        {
            "best_candidate": "core",
            "candidate_count": 1,
            "window_count": 1,
            "summaries": [{"candidate": "core"}],
            "windows": [{"candidate": "core"}],
        }
    )
    _write_json(walk_forward_path, payload)

    review = build_candidate_experiment_completion(tmp_path)

    artifact = next(item for item in review.artifacts if item.name == walk_forward_path.name)
    message = "candidate_walk_forward_report.json does not satisfy the selection-safe v2 contract"
    assert review.decision == "BLOCK"
    assert artifact.status == "BLOCK"
    assert artifact.message.startswith(message)
    assert any(message in blocker for blocker in review.blockers)


def _selection_payload(selection_safe: object) -> dict[str, object]:
    payload: dict[str, object] = {"status": "PASS"}
    if selection_safe is not _MISSING:
        payload["selection_safe"] = selection_safe
    return payload


def _complete_selection_payload(filename: str) -> dict[str, object]:
    candidate = filename == "candidate_walk_forward_report.json"
    configuration = {
        "mode": "expanding",
        "train_days": 2,
        "purge_days": 0,
        "selection_days": 1,
        "embargo_days": 0,
        "test_days": 1,
        "step_days": 1,
    }
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
        "configuration": configuration,
        "status": "PASS",
        "window_count": 1,
        "windows": [window],
    }
    if candidate:
        window.update(
            {
                "candidate": "core",
                "window": "wf_01",
                "selection_rank": 1,
            }
        )
        payload.update(
            {
                "candidate_count": 1,
                "selected_candidate": "core",
                "best_candidate": "core",
                "selections": [
                    {
                        "candidate": "core",
                        "window": "wf_01",
                        "rank": 1,
                    }
                ],
            }
        )
    return payload


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
