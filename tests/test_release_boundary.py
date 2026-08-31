from __future__ import annotations

from pathlib import Path

from scripts.check_release_boundary import inspect_release_boundary, main


ROOT = Path(__file__).resolve().parents[1]


def test_release_boundary_contract_passes() -> None:
    assert inspect_release_boundary(ROOT) == []


def test_release_boundary_cli_reports_fail_closed_owner_actions(capsys) -> None:
    assert main(["--root", str(ROOT)]) == 0
    captured = capsys.readouterr()
    assert "canonical source only" in captured.out
    assert "owner actions remain BLOCK" in captured.out
