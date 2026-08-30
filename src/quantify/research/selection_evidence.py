"""Immutable digest binding for selection and robustness evidence."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from quantify.research.walk_forward_protocol import (
    CANDIDATE_WALK_FORWARD_ARTIFACT,
    WALK_FORWARD_ARTIFACT,
    validate_robustness_selection_safe_payload,
    validate_selection_safe_payload,
)

SelectionEvidenceStatus = Literal["PASS", "WATCH", "BLOCK"]
SELECTION_EVIDENCE_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class SelectionEvidenceItem:
    filename: str
    exists: bool
    file_sha256: str
    canonical_payload_sha256: str
    selection_safe: bool
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "exists": self.exists,
            "file_sha256": self.file_sha256,
            "canonical_payload_sha256": self.canonical_payload_sha256,
            "selection_safe": self.selection_safe,
            "reasons": self.reasons,
        }


@dataclass(frozen=True, slots=True)
class SelectionEvidenceManifest:
    status: SelectionEvidenceStatus
    report_dir: str
    run_manifest_sha256: str
    selected_candidate: str
    candidate_selection_status: str
    artifact_set_sha256: str
    artifacts: list[SelectionEvidenceItem]
    blockers: list[str]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": "selection_evidence_manifest",
            "schema_version": SELECTION_EVIDENCE_SCHEMA_VERSION,
            "status": self.status,
            "report_dir": self.report_dir,
            "run_manifest_sha256": self.run_manifest_sha256,
            "selected_candidate": self.selected_candidate,
            "candidate_selection_status": self.candidate_selection_status,
            "artifact_set_sha256": self.artifact_set_sha256,
            "artifacts": [item.to_dict() for item in self.artifacts],
            "blockers": self.blockers,
            "warnings": self.warnings,
            "prohibited_actions": [
                "Do not edit selection artifacts after this manifest is generated.",
                "Do not treat a manifest PASS as live-trading approval.",
                "Do not bypass paper, readiness, human approval, or broker boundaries.",
            ],
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Selection Evidence Manifest: {self.status}",
            "",
            f"- Report directory: `{self.report_dir}`",
            f"- Selected candidate: `{self.selected_candidate or 'none'}`",
            f"- Candidate selection status: `{self.candidate_selection_status}`",
            f"- Run manifest SHA-256: `{self.run_manifest_sha256 or 'missing'}`",
            f"- Artifact-set SHA-256: `{self.artifact_set_sha256}`",
            "",
            "## Artifacts",
            "",
            "| file | exists | selection_safe | file_sha256 | canonical_sha256 | reasons |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for item in self.artifacts:
            lines.append(
                f"| `{item.filename}` | `{item.exists}` | `{item.selection_safe}` | "
                f"`{item.file_sha256 or 'missing'}` | "
                f"`{item.canonical_payload_sha256 or 'missing'}` | "
                f"{_cell('; '.join(item.reasons) or 'none')} |"
            )
        lines.extend(["", "## Blockers"])
        lines.extend(f"- {item}" for item in self.blockers) if self.blockers else lines.append("- None.")
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {item}" for item in self.warnings) if self.warnings else lines.append("- None.")
        return "\n".join(lines) + "\n"


def build_selection_evidence_manifest(
    report_dir: str | Path,
) -> SelectionEvidenceManifest:
    root = Path(report_dir)
    specs = (
        ("robustness_report.json", "robustness"),
        ("walk_forward_report.json", WALK_FORWARD_ARTIFACT),
        ("candidate_walk_forward_report.json", CANDIDATE_WALK_FORWARD_ARTIFACT),
    )
    artifacts = [_evidence_item(root / filename, artifact_type) for filename, artifact_type in specs]
    blockers = [
        f"{item.filename}: " + "; ".join(item.reasons)
        for item in artifacts
        if not item.selection_safe
    ]
    warnings: list[str] = []
    run_manifest_path = root / "run_manifest.json"
    run_manifest_sha256 = _file_sha256(run_manifest_path)
    if not run_manifest_sha256:
        blockers.append("run_manifest.json is missing or empty.")

    selection = _read_json(root / "candidate_selection.json")
    candidate_report = _read_json(root / "candidate_walk_forward_report.json")
    selection_status = str(selection.get("status", "UNKNOWN") or "UNKNOWN").upper()
    selected_candidate = str(selection.get("selected_candidate") or "").strip()
    locked_candidate = str(
        candidate_report.get("selected_candidate") or candidate_report.get("best_candidate") or ""
    ).strip()
    if not selection:
        blockers.append("candidate_selection.json is missing or unreadable.")
    if selection.get("candidate_lock_selection_safe") is not True:
        blockers.append("candidate_selection.json candidate_lock_selection_safe is not exactly true.")
    if selection_status == "BLOCK" or selection_status not in {"PASS", "WATCH"}:
        blockers.append(f"candidate_selection.json status is {selection_status}.")
    elif selection_status == "WATCH":
        warnings.append("candidate_selection.json is WATCH.")
    if not selected_candidate:
        blockers.append("candidate_selection.json has no selected_candidate.")
    elif selected_candidate != locked_candidate:
        blockers.append(
            "candidate_selection.json selected_candidate does not match the pretest-locked candidate."
        )
    candidate_item = next(
        item for item in artifacts if item.filename == "candidate_walk_forward_report.json"
    )
    recorded_digest = str(
        (
            (selection.get("evidence_inputs", {}) or {}).get(
                "candidate_walk_forward_report.json",
                {},
            )
            or {}
        ).get("sha256", "")
    )
    if recorded_digest != candidate_item.canonical_payload_sha256:
        blockers.append(
            "candidate_selection.json does not bind the current candidate walk-forward payload hash."
        )
    artifact_set_sha256 = canonical_payload_sha256(
        {
            "run_manifest_sha256": run_manifest_sha256,
            "artifacts": [item.to_dict() for item in artifacts],
            "selected_candidate": selected_candidate,
        }
    )
    status: SelectionEvidenceStatus
    if blockers:
        status = "BLOCK"
    elif warnings:
        status = "WATCH"
    else:
        status = "PASS"
    return SelectionEvidenceManifest(
        status=status,
        report_dir=str(root),
        run_manifest_sha256=run_manifest_sha256,
        selected_candidate=selected_candidate,
        candidate_selection_status=selection_status,
        artifact_set_sha256=artifact_set_sha256,
        artifacts=artifacts,
        blockers=blockers,
        warnings=warnings,
    )


def write_selection_evidence_manifest(
    manifest: SelectionEvidenceManifest,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "selection_evidence_manifest.json").write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "selection_evidence_manifest.md").write_text(
        manifest.to_markdown(),
        encoding="utf-8",
    )
    return root


def canonical_payload_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _evidence_item(path: Path, artifact_type: str) -> SelectionEvidenceItem:
    payload = _read_json(path)
    if artifact_type == "robustness":
        validation = validate_robustness_selection_safe_payload(payload)
    else:
        validation = validate_selection_safe_payload(payload, artifact_type=artifact_type)
    return SelectionEvidenceItem(
        filename=path.name,
        exists=path.exists(),
        file_sha256=_file_sha256(path),
        canonical_payload_sha256=canonical_payload_sha256(payload) if payload else "",
        selection_safe=validation.safe,
        reasons=validation.reasons,
    )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _file_sha256(path: Path) -> str:
    if not path.exists() or not path.is_file() or path.stat().st_size == 0:
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
