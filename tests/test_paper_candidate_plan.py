from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from quantify.paper import build_paper_candidate_plan, write_paper_candidate_plan


def test_paper_candidate_plan_blocks_missing_real_evidence(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "candidate_selection.json",
        {"status": "PASS", "best_candidate": "core_multifactor"},
    )

    plan = build_paper_candidate_plan(
        tmp_path,
        config_path="config/research_recent.yaml",
        paper_state_dir="results/paper/core",
    )

    assert plan.decision == "BLOCK"
    assert plan.candidate == "core_multifactor"
    assert not plan.command
    assert any("real_data_bootstrap" in blocker for blocker in plan.blockers)


def test_paper_candidate_plan_passes_and_writes_command(tmp_path: Path) -> None:
    _write_required_pass_artifacts(tmp_path)

    plan = build_paper_candidate_plan(
        tmp_path,
        config_path="config/research_recent.yaml",
        paper_state_dir="results/paper/core",
    )
    out = write_paper_candidate_plan(plan, tmp_path)

    assert plan.decision == "PASS"
    assert "--candidate core_multifactor" in plan.command
    assert (out / "paper_candidate_plan.json").exists()


def test_paper_candidate_plan_blocks_missing_completion_even_when_legacy_artifacts_pass(
    tmp_path: Path,
) -> None:
    _write_required_pass_artifacts(tmp_path, include_completion=False)

    plan = build_paper_candidate_plan(
        tmp_path,
        config_path="config/research_recent.yaml",
        paper_state_dir="results/paper/core",
    )

    assert plan.decision == "BLOCK"
    assert plan.command == ""
    assert any("candidate_experiment_completion.json is missing" in item for item in plan.blockers)


def test_paper_candidate_plan_blocks_completion_block_or_unknown(tmp_path: Path) -> None:
    _write_required_pass_artifacts(tmp_path)
    _write_completion(tmp_path, decision="BLOCK", blockers=["launch_contract_evidence: too few windows"])

    plan = build_paper_candidate_plan(
        tmp_path,
        config_path="config/research_recent.yaml",
        paper_state_dir="results/paper/core",
    )

    assert plan.decision == "BLOCK"
    assert "too few windows" in "\n".join(plan.blockers)


def test_paper_candidate_plan_blocks_incomplete_launch_contract_evidence(tmp_path: Path) -> None:
    _write_required_pass_artifacts(tmp_path)
    _write_completion(tmp_path, contract_evidence_status="WATCH")

    plan = build_paper_candidate_plan(
        tmp_path,
        config_path="config/research_recent.yaml",
        paper_state_dir="results/paper/core",
    )

    assert plan.decision == "BLOCK"
    assert any("launch_contract_evidence is WATCH" in item for item in plan.blockers)


def test_paper_candidate_plan_blocks_completion_candidate_mismatch(tmp_path: Path) -> None:
    _write_required_pass_artifacts(tmp_path)
    _write_completion(tmp_path, selected_candidate="price_volume_defensive")

    plan = build_paper_candidate_plan(
        tmp_path,
        config_path="config/research_recent.yaml",
        paper_state_dir="results/paper/core",
        candidate="core_multifactor",
    )

    assert plan.decision == "BLOCK"
    assert any("selected_candidate mismatch" in item for item in plan.blockers)


def test_paper_candidate_plan_blocks_run_manifest_without_provenance(
    tmp_path: Path,
) -> None:
    _write_required_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "run_manifest.json",
        {
            "demo_data_used": False,
            "in_sample_end": "2024-01-02",
            "out_sample_start": "2024-01-03",
            "data_version": {"data_source_qa_status": "PASS"},
        },
    )

    plan = build_paper_candidate_plan(
        tmp_path,
        config_path="config/research_recent.yaml",
        paper_state_dir="results/paper/core",
    )

    assert plan.decision == "BLOCK"
    assert any("run_manifest provenance blocker" in item for item in plan.blockers)


def test_paper_candidate_plan_ignores_blocked_top_candidate(tmp_path: Path) -> None:
    _write_required_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "candidate_selection.json",
        {
            "status": "BLOCK",
            "selected_candidate": "",
            "best_candidate": "",
            "top_candidate": "low_vol_test",
        },
    )

    plan = build_paper_candidate_plan(
        tmp_path,
        config_path="config/research_recent.yaml",
        paper_state_dir="results/paper/core",
    )

    assert plan.decision == "BLOCK"
    assert plan.candidate == ""
    assert plan.command == ""
    assert "No candidate is selected" in "\n".join(plan.blockers)


def test_paper_candidate_plan_cli_writes_outputs(tmp_path: Path) -> None:
    _write_required_pass_artifacts(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_paper_candidate_plan.py",
            "--report-dir",
            str(tmp_path),
            "--config",
            "config/research_recent.yaml",
            "--paper-state-dir",
            "results/paper/core",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((tmp_path / "paper_candidate_plan.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["decision"] == "PASS"


def test_paper_candidate_plan_cli_returns_nonzero_on_block(tmp_path: Path) -> None:
    _write_required_pass_artifacts(tmp_path, include_completion=False)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_paper_candidate_plan.py",
            "--report-dir",
            str(tmp_path),
            "--config",
            "config/research_recent.yaml",
            "--paper-state-dir",
            "results/paper/core",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((tmp_path / "paper_candidate_plan.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["decision"] == "BLOCK"


def _write_required_pass_artifacts(root: Path, *, include_completion: bool = True) -> None:
    for name, key in [
        ("real_data_bootstrap.json", "decision"),
        ("real_data_gate.json", "decision"),
        ("data_audit.json", "status"),
        ("robustness_report.json", "status"),
        ("walk_forward_report.json", "status"),
        ("candidate_walk_forward_report.json", "status"),
        ("candidate_factor_diagnostics.json", "status"),
        ("candidate_regime_validation_report.json", "status"),
        ("candidate_selection.json", "status"),
        ("llm_review.json", "decision"),
    ]:
        payload = {key: "PASS"}
        if name == "candidate_selection.json":
            payload["best_candidate"] = "core_multifactor"
            payload["selected_candidate"] = "core_multifactor"
        _write_json(root / name, payload)
    _write_json(
        root / "run_manifest.json",
        {
            "demo_data_used": False,
            "in_sample_end": "2024-01-02",
            "out_sample_start": "2024-01-03",
            "data_version": {
                "csv_dataset_fingerprint": "unit-test-csv-fingerprint",
                "data_source_qa_status": "PASS",
                "data_source_csv_qa_status": "PASS",
                **_source_qa_metadata(root),
            },
        },
    )
    if include_completion:
        _write_completion(root)


def _write_completion(
    root: Path,
    *,
    decision: str = "PASS",
    selected_candidate: str = "core_multifactor",
    contract_status: str = "PASS",
    contract_evidence_status: str = "PASS",
    blockers: list[str] | None = None,
) -> None:
    _write_json(
        root / "candidate_experiment_completion.json",
        {
            "decision": decision,
            "selected_candidate": selected_candidate,
            "blockers": blockers or [],
            "watch_items": [],
            "artifacts": [
                {"name": "launch_contract", "status": contract_status},
                {"name": "launch_contract_evidence", "status": contract_evidence_status},
            ],
        },
    )


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _source_qa_metadata(root: Path) -> dict[str, str]:
    checklist = root / "data_source_qa.json"
    answers = root / "data_source_qa_answers.json"
    evidence_manifest = root / "source_qa_evidence_manifest.json"
    checklist.write_text('{"checklist":"unit-test"}', encoding="utf-8")
    answers.write_text('{"answers":"unit-test"}', encoding="utf-8")
    evidence_manifest.write_text('{"evidence":"unit-test"}', encoding="utf-8")
    return {
        "data_source_qa_checklist_path": str(checklist),
        "data_source_qa_checklist_sha256": _sha256(checklist),
        "data_source_qa_answers_path": str(answers),
        "data_source_qa_answers_sha256": _sha256(answers),
        "data_source_qa_evidence_manifest_path": str(evidence_manifest),
        "data_source_qa_evidence_manifest_sha256": _sha256(evidence_manifest),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
