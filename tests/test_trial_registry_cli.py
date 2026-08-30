from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

_SCRIPT = Path("examples/run_trial_registry.py")
_PREREGISTRATION_PAYLOAD: dict[str, Any] = {
    "trial_id": "trial-001",
    "candidate": "momentum",
    "hypothesis": "Positive twelve-month returns persist over the test window.",
    "parameter_fingerprint": "parameters-sha256-001",
    "data_fingerprint": "data-sha256-001",
    "config_fingerprint": "config-sha256-001",
    "train_boundary": {"start": "2020-01-01", "end": "2023-12-31"},
    "selection_boundary": {"start": "2024-01-01", "end": "2024-12-31"},
    "test_boundary": {"start": "2025-01-01", "end": "2025-12-31"},
    "created_at": "2026-07-16T09:00:00+00:00",
    "prohibited_live_use": True,
}


def test_cli_preregisters_records_result_and_verifies(tmp_path: Path) -> None:
    registry = tmp_path / "trials.jsonl"
    preregistration_payload = tmp_path / "preregistration.json"
    result_payload = tmp_path / "result.json"
    _write_json(preregistration_payload, _preregistration_payload())
    _write_json(
        result_payload,
        {
            "trial_id": "trial-001",
            "result_id": "trial-001:final",
            "result": {
                "decision": "PASS",
                "metrics": {"sharpe_ratio": 1.25, "max_drawdown": -0.12},
            },
            "created_at": "2026-07-16T10:00:00+00:00",
        },
    )

    preregistration = _run("preregister", registry, preregistration_payload)
    assert preregistration.returncode == 0, preregistration.stderr
    preregistration_summary = json.loads(preregistration.stdout)
    assert preregistration_summary["status"] == "APPENDED"
    assert preregistration_summary["event"]["event_type"] == "preregistration"
    assert preregistration_summary["event"]["prohibited_live_use"] is True
    prior_bytes = registry.read_bytes()

    result = _run("record-result", registry, result_payload)
    assert result.returncode == 0, result.stderr
    result_summary = json.loads(result.stdout)
    assert result_summary["status"] == "APPENDED"
    assert result_summary["event"]["event_type"] == "result"
    assert result_summary["event"]["trial_id"] == "trial-001"
    assert registry.read_bytes().startswith(prior_bytes)

    verification = _run("verify", registry)
    assert verification.returncode == 0, verification.stderr
    summary = json.loads(verification.stdout)
    assert summary == {
        "command": "verify",
        "event_count": 2,
        "hash_algorithm": "sha256",
        "last_event_hash": result_summary["event"]["event_hash"],
        "preregistration_count": 1,
        "registry_path": str(registry),
        "result_count": 1,
        "schema_version": 1,
        "status": "PASS",
        "trial_count": 1,
        "trial_ids": ["trial-001"],
        "valid": True,
    }


def test_cli_rejects_result_before_registration(tmp_path: Path) -> None:
    registry = tmp_path / "trials.jsonl"
    result_payload = tmp_path / "result.json"
    _write_json(
        result_payload,
        {
            "trial_id": "trial-001",
            "result": {"decision": "BLOCK"},
            "created_at": "2026-07-16T10:00:00+00:00",
        },
    )

    completed = _run("record-result", registry, result_payload)

    assert completed.returncode == 1
    assert completed.stdout == ""
    failure = json.loads(completed.stderr)
    assert failure["status"] == "FAIL"
    assert failure["error_type"] == "UnknownTrialError"
    assert not registry.exists()


@pytest.mark.parametrize("damage", ["tamper", "truncate"])
def test_cli_verify_fails_for_damaged_registry(tmp_path: Path, damage: str) -> None:
    registry = tmp_path / "trials.jsonl"
    preregistration_payload = tmp_path / "preregistration.json"
    _write_json(preregistration_payload, _preregistration_payload())
    completed = _run("preregister", registry, preregistration_payload)
    assert completed.returncode == 0, completed.stderr

    original = registry.read_bytes()
    if damage == "tamper":
        damaged = original.replace(b'"candidate":"momentum"', b'"candidate":"reversal"')
        assert damaged != original
    else:
        damaged = original[:-1]
    registry.write_bytes(damaged)

    verification = _run("verify", registry)

    assert verification.returncode == 1
    assert verification.stderr == ""
    failure = json.loads(verification.stdout)
    assert failure["status"] == "FAIL"
    assert failure["valid"] is False
    assert failure["error_type"] in {
        "TrialRegistryFormatError",
        "TrialRegistryIntegrityError",
    }


@pytest.mark.parametrize(
    ("payload_text", "message"),
    [
        ("[]", "must be a JSON object"),
        ('{"value":NaN}', "non-finite number"),
        (
            json.dumps({**_PREREGISTRATION_PAYLOAD, "prohibited_live_use": False}),
            "requires explicit prohibited_live_use=true",
        ),
    ],
)
def test_cli_rejects_invalid_preregistration_payloads(
    tmp_path: Path,
    payload_text: str,
    message: str,
) -> None:
    registry = tmp_path / "trials.jsonl"
    payload_path = tmp_path / "invalid.json"
    payload_path.write_text(payload_text, encoding="utf-8")

    completed = _run("preregister", registry, payload_path)

    assert completed.returncode == 1
    failure = json.loads(completed.stderr)
    assert failure["status"] == "FAIL"
    assert failure["error_type"] == "PayloadError"
    assert message in failure["error"]
    assert not registry.exists()


def _run(
    command: str,
    registry: Path,
    payload: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, str(_SCRIPT), command, "--registry", str(registry)]
    if payload is not None:
        args.extend(["--payload", str(payload)])
    return subprocess.run(
        args,
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )


def _preregistration_payload() -> dict[str, Any]:
    return dict(_PREREGISTRATION_PAYLOAD)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2),
        encoding="utf-8",
    )
