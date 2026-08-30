from __future__ import annotations

import json
from pathlib import Path

from quantify.research.selection_evidence import (
    build_selection_evidence_manifest,
    canonical_payload_sha256,
    write_selection_evidence_manifest,
)
from tests.selection_safe_fixtures import (
    selection_safe_robustness_payload,
    selection_safe_walk_forward_payload,
)


def test_selection_evidence_manifest_binds_complete_artifacts(tmp_path: Path) -> None:
    candidate = "locked_candidate"
    candidate_payload = selection_safe_walk_forward_payload(candidate=candidate)
    _write_valid_bundle(tmp_path, candidate_payload=candidate_payload)

    manifest = build_selection_evidence_manifest(tmp_path)
    out = write_selection_evidence_manifest(manifest, tmp_path)

    assert manifest.status == "PASS"
    assert manifest.selected_candidate == candidate
    assert manifest.run_manifest_sha256
    assert manifest.artifact_set_sha256
    assert all(item.selection_safe for item in manifest.artifacts)
    assert (out / "selection_evidence_manifest.json").exists()
    assert "Selection Evidence Manifest" in (
        out / "selection_evidence_manifest.md"
    ).read_text(encoding="utf-8")


def test_selection_evidence_manifest_blocks_legacy_boolean_payload(tmp_path: Path) -> None:
    candidate_payload = {"status": "PASS", "selection_safe": True}
    _write_valid_bundle(tmp_path, candidate_payload=candidate_payload)

    manifest = build_selection_evidence_manifest(tmp_path)

    assert manifest.status == "BLOCK"
    assert any("schema_version" in blocker for blocker in manifest.blockers)


def test_selection_evidence_manifest_detects_post_selection_tampering(tmp_path: Path) -> None:
    candidate_payload = selection_safe_walk_forward_payload(candidate="locked_candidate")
    _write_valid_bundle(tmp_path, candidate_payload=candidate_payload)
    candidate_payload["warnings"] = ["tampered after selection"]
    _write_json(tmp_path / "candidate_walk_forward_report.json", candidate_payload)

    manifest = build_selection_evidence_manifest(tmp_path)

    assert manifest.status == "BLOCK"
    assert any("does not bind" in blocker for blocker in manifest.blockers)


def test_selection_evidence_manifest_blocks_candidate_identity_mismatch(tmp_path: Path) -> None:
    candidate_payload = selection_safe_walk_forward_payload(candidate="locked_candidate")
    _write_valid_bundle(
        tmp_path,
        candidate_payload=candidate_payload,
        selected_candidate="different_candidate",
    )

    manifest = build_selection_evidence_manifest(tmp_path)

    assert manifest.status == "BLOCK"
    assert any("does not match" in blocker for blocker in manifest.blockers)


def _write_valid_bundle(
    root: Path,
    *,
    candidate_payload: dict[str, object],
    selected_candidate: str = "locked_candidate",
) -> None:
    _write_json(root / "run_manifest.json", {"purpose": "unit_test"})
    _write_json(root / "robustness_report.json", selection_safe_robustness_payload())
    _write_json(root / "walk_forward_report.json", selection_safe_walk_forward_payload())
    _write_json(root / "candidate_walk_forward_report.json", candidate_payload)
    _write_json(
        root / "candidate_selection.json",
        {
            "status": "PASS",
            "selected_candidate": selected_candidate,
            "candidate_lock_selection_safe": True,
            "evidence_inputs": {
                "candidate_walk_forward_report.json": {
                    "sha256": canonical_payload_sha256(candidate_payload),
                }
            },
        },
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
