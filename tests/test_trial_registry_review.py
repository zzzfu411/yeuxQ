from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

from quantify.research.evidence_validation import validate_trial_registry_review_payload
from quantify.research.trial_registry import append_preregistration, append_result
from quantify.research.trial_registry_review import (
    REQUIRED_EVIDENCE_FILES,
    build_trial_registry_review,
    write_trial_registry_review,
)

_CANDIDATE = "locked_candidate"
_CONFIG_SHA256 = "a" * 64
_CACHE_SHA256 = "b" * 64
_LOGICAL_FINGERPRINT = "c" * 64


def test_trial_registry_review_passes_and_binds_current_artifacts(tmp_path: Path) -> None:
    report_dir = tmp_path / "report"
    registry = tmp_path / "trials.jsonl"
    _write_report_bundle(report_dir, include_optional=True)
    _append_bound_trial(registry, report_dir)

    review = build_trial_registry_review(registry, report_dir)
    out = write_trial_registry_review(review, report_dir)

    assert review.status == "PASS"
    assert review.artifact_type == "trial_registry_review"
    assert review.schema_version == 1
    assert review.selected_candidate == _CANDIDATE
    assert review.matched_trial_id == "trial-001"
    assert review.matched_result_id == "trial-001:final"
    assert review.registry_sha256 == _sha256(registry)
    assert review.registry_tail_hash
    assert review.can_upgrade_deterministic_gate is False
    assert {item.filename for item in review.bound_evidence} == {
        *REQUIRED_EVIDENCE_FILES,
        "multiple_testing_report.json",
        "benchmark_report.json",
    }
    assert all(item.matches for item in review.bound_evidence)

    payload = json.loads((out / "trial_registry_review.json").read_text(encoding="utf-8"))
    markdown = (out / "trial_registry_review.md").read_text(encoding="utf-8")
    assert payload["status"] == "PASS"
    assert payload["can_upgrade_deterministic_gate"] is False
    assert "Trial Registry Review: PASS" in markdown

    validation = validate_trial_registry_review_payload(
        payload,
        expected_candidate=_CANDIDATE,
        report_dir=report_dir,
    )
    assert validation.valid is True

    _write_json(report_dir / "benchmark_report.json", {"status": "WATCH", "changed": True})
    changed = validate_trial_registry_review_payload(
        payload,
        expected_candidate=_CANDIDATE,
        report_dir=report_dir,
    )
    assert changed.valid is False
    assert any("benchmark_report.json" in reason for reason in changed.reasons)


def test_trial_registry_review_blocks_selected_candidate_without_preregistration(
    tmp_path: Path,
) -> None:
    report_dir = tmp_path / "report"
    registry = tmp_path / "trials.jsonl"
    _write_report_bundle(report_dir)
    _append_bound_trial(
        registry,
        report_dir,
        preregistered_candidate="other_candidate",
        result_candidate=_CANDIDATE,
    )

    review = build_trial_registry_review(registry, report_dir)

    assert review.status == "BLOCK"
    assert review.matched_trial_id == ""
    assert any("has no preregistration" in blocker for blocker in review.blockers)
    assert review.can_upgrade_deterministic_gate is False


@pytest.mark.parametrize(
    ("mismatch", "blocker_text"),
    [
        ("config", "config_fingerprint"),
        ("data", "data_fingerprint"),
        ("artifact", "robustness_report.json"),
    ],
)
def test_trial_registry_review_blocks_fingerprint_mismatches(
    tmp_path: Path,
    mismatch: str,
    blocker_text: str,
) -> None:
    report_dir = tmp_path / "report"
    registry = tmp_path / "trials.jsonl"
    _write_report_bundle(report_dir)
    _append_bound_trial(
        registry,
        report_dir,
        config_fingerprint="d" * 64 if mismatch == "config" else _CONFIG_SHA256,
        data_fingerprint="e" * 64 if mismatch == "data" else _LOGICAL_FINGERPRINT,
    )
    if mismatch == "artifact":
        _write_json(
            report_dir / "robustness_report.json",
            {"artifact_type": "robustness_report", "status": "PASS", "tampered": True},
        )

    review = build_trial_registry_review(registry, report_dir)

    assert review.status == "BLOCK"
    assert any(blocker_text in blocker for blocker in review.blockers)
    assert review.can_upgrade_deterministic_gate is False


def test_trial_registry_review_cli_writes_block_for_tampered_registry(tmp_path: Path) -> None:
    report_dir = tmp_path / "report"
    registry = tmp_path / "trials.jsonl"
    _write_report_bundle(report_dir)
    _append_bound_trial(registry, report_dir)
    tampered = registry.read_bytes().replace(
        b'"candidate":"locked_candidate"',
        b'"candidate":"forged_candidate"',
    )
    assert tampered != registry.read_bytes()
    registry.write_bytes(tampered)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_trial_registry_review.py",
            "--registry",
            str(registry),
            "--report-dir",
            str(report_dir),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2, completed.stderr
    summary = json.loads(completed.stdout)
    payload = json.loads((report_dir / "trial_registry_review.json").read_text(encoding="utf-8"))
    assert summary["status"] == "BLOCK"
    assert summary["can_upgrade_deterministic_gate"] is False
    assert payload["status"] == "BLOCK"
    assert payload["registry_sha256"] == _sha256(registry)
    assert payload["registry_tail_hash"] == ""
    assert any("hash-chain verification failed" in blocker for blocker in payload["blockers"])
    assert (report_dir / "trial_registry_review.md").exists()


def test_trial_registry_review_by_trial_id_supports_unselected_falsification(
    tmp_path: Path,
) -> None:
    report_dir = tmp_path / "report"
    registry = tmp_path / "trials.jsonl"
    _write_report_bundle(report_dir)
    _write_json(
        report_dir / "candidate_selection.json",
        {"status": "BLOCK", "selected_candidate": ""},
    )
    _append_bound_trial(registry, report_dir)

    review = build_trial_registry_review(
        registry,
        report_dir,
        trial_id="trial-001",
    )

    assert review.status == "PASS"
    assert review.selected_candidate == _CANDIDATE
    assert review.matched_trial_id == "trial-001"


def test_trial_registry_review_blocks_multiple_results_for_one_trial(tmp_path: Path) -> None:
    report_dir = tmp_path / "report"
    registry = tmp_path / "trials.jsonl"
    _write_report_bundle(report_dir)
    _append_bound_trial(registry, report_dir)
    append_result(
        registry,
        trial_id="trial-001",
        result_id="trial-001:replacement",
        result={
            "candidate": _CANDIDATE,
            "artifact_fingerprints": _artifact_fingerprints(report_dir),
        },
        created_at="2026-07-16T11:00:00+00:00",
    )

    review = build_trial_registry_review(
        registry,
        report_dir,
        trial_id="trial-001",
    )

    assert review.status == "BLOCK"
    assert review.matched_result_id == "trial-001:final"
    assert any("multiple result events" in blocker for blocker in review.blockers)


def _write_report_bundle(root: Path, *, include_optional: bool = False) -> None:
    root.mkdir(parents=True)
    _write_json(
        root / "run_manifest.json",
        {
            "created_at_utc": "2026-07-16T09:00:00+00:00",
            "config_sha256": _CONFIG_SHA256,
            "cache_sha256": _CACHE_SHA256,
            "start": "2020-01-01",
            "end": "2024-12-31",
            "in_sample_end": "2023-12-31",
            "out_sample_start": "2024-01-01",
            "data_version": {
                "cache_logical_bar_fingerprint": _LOGICAL_FINGERPRINT,
                "csv_dataset_fingerprint": "f" * 64,
                "raw_vendor_bars_sha256": "1" * 64,
            },
        },
    )
    _write_json(
        root / "robustness_report.json",
        {"artifact_type": "robustness_report", "status": "PASS"},
    )
    _write_json(
        root / "walk_forward_report.json",
        {"artifact_type": "walk_forward_report", "status": "PASS"},
    )
    _write_json(
        root / "candidate_walk_forward_report.json",
        {
            "artifact_type": "candidate_walk_forward_report",
            "status": "PASS",
            "selected_candidate": _CANDIDATE,
        },
    )
    _write_json(
        root / "candidate_selection.json",
        {"status": "PASS", "selected_candidate": _CANDIDATE},
    )
    _write_json(
        root / "selection_evidence_manifest.json",
        {"artifact_type": "selection_evidence_manifest", "schema_version": 1},
    )
    if include_optional:
        _write_json(
            root / "multiple_testing_report.json",
            {"artifact_type": "multiple_testing_report", "schema_version": 1},
        )
        _write_json(
            root / "benchmark_report.json",
            {"artifact_type": "benchmark_report", "schema_version": 1},
        )


def _append_bound_trial(
    registry: Path,
    report_dir: Path,
    *,
    preregistered_candidate: str = _CANDIDATE,
    result_candidate: str = _CANDIDATE,
    config_fingerprint: str = _CONFIG_SHA256,
    data_fingerprint: str = _LOGICAL_FINGERPRINT,
) -> None:
    append_preregistration(
        registry,
        trial_id="trial-001",
        candidate=preregistered_candidate,
        hypothesis="The locked candidate remains robust out of sample.",
        parameter_fingerprint="2" * 64,
        data_fingerprint=data_fingerprint,
        config_fingerprint=config_fingerprint,
        train_boundary={"start": "2020-01-01", "end": "2022-12-31"},
        selection_boundary={"start": "2023-01-01", "end": "2023-12-31"},
        test_boundary={"start": "2024-01-01", "end": "2024-12-31"},
        created_at="2026-07-16T08:00:00+00:00",
        prohibited_live_use=True,
    )
    append_result(
        registry,
        trial_id="trial-001",
        result_id="trial-001:final",
        result={
            "candidate": result_candidate,
            "artifact_fingerprints": _artifact_fingerprints(report_dir),
        },
        created_at="2026-07-16T10:00:00+00:00",
    )


def _artifact_fingerprints(root: Path) -> dict[str, str]:
    filenames = list(REQUIRED_EVIDENCE_FILES)
    filenames.extend(
        filename
        for filename in ("multiple_testing_report.json", "benchmark_report.json")
        if (root / filename).exists()
    )
    return {filename: _sha256(root / filename) for filename in filenames}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2),
        encoding="utf-8",
    )
