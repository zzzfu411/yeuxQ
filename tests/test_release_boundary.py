from __future__ import annotations

import json
from pathlib import Path

from scripts.check_release_boundary import inspect_release_boundary, main


ROOT = Path(__file__).resolve().parents[1]


def test_release_boundary_contract_passes() -> None:
    assert inspect_release_boundary(ROOT) == []
    assert "tmp_pytest_*/" in (ROOT / ".gitignore").read_text(encoding="utf-8")


def test_release_boundary_cli_reports_fail_closed_owner_actions(capsys) -> None:
    assert main(["--root", str(ROOT)]) == 0
    captured = capsys.readouterr()
    assert "canonical source only" in captured.out
    assert "owner actions remain BLOCK" in captured.out


def test_owner_release_attestation_is_pending_and_never_stores_credentials() -> None:
    attestation = json.loads(
        (ROOT / "integration" / "owner_release_attestation.json").read_text(encoding="utf-8")
    )
    assert attestation["status"] == "pending"
    assert attestation["donor_redistribution_rights"]["confirmed"] is False
    assert attestation["credential_rotation"] == {
        "required_count": 2,
        "confirmed": False,
        "confirmed_by": None,
        "confirmed_at": None,
        "credential_values_recorded": False,
    }
    assert attestation["public_disclosure"]["approved"] is False
