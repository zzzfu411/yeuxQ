from __future__ import annotations

import json
from pathlib import Path

from scripts.check_release_boundary import inspect_release_boundary, main


ROOT = Path(__file__).resolve().parents[1]


def test_release_boundary_contract_passes() -> None:
    assert inspect_release_boundary(ROOT) == []
    assert "tmp_pytest_*/" in (ROOT / ".gitignore").read_text(encoding="utf-8")


def test_release_boundary_cli_reports_verified_owner_attestation(capsys) -> None:
    assert main(["--root", str(ROOT)]) == 0
    captured = capsys.readouterr()
    assert "canonical source only" in captured.out
    assert "owner attestation verified" in captured.out


def test_owner_release_attestation_is_complete_and_never_stores_credentials() -> None:
    attestation = json.loads(
        (ROOT / "integration" / "owner_release_attestation.json").read_text(encoding="utf-8")
    )
    assert attestation["status"] == "complete"
    rights = attestation["donor_redistribution_rights"]
    assert rights["confirmed"] is True
    assert rights["confirmed_by"] == "zzzfu411"
    assert rights["confirmed_at"]
    assert rights["basis"]
    rotation = attestation["credential_rotation"]
    assert rotation["required_count"] == 2
    assert rotation["confirmed"] is True
    assert rotation["confirmed_by"] == "zzzfu411"
    assert rotation["confirmed_at"]
    assert rotation["credential_values_recorded"] is False
    disclosure = attestation["public_disclosure"]
    assert disclosure["approved"] is True
    assert disclosure["approved_by"] == "zzzfu411"
    assert disclosure["approved_at"]
    assert disclosure["approved_candidate_commit"] == (
        "b59affee29baa48c9953b2d6485693caa41f0558"
    )
