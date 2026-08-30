from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from yeuxq.services.research_facade import (
    AUTHORITY,
    InvalidRunIdError,
    ResearchReadinessFacade,
    UnsafeResearchPathError,
)


def _risk_budget() -> dict:
    return {
        "manual_reference_only": True,
        "auto_order_submission": False,
        "max_position_pct": 0.05,
        "max_strategy_drawdown_stop": 0.15,
        "single_day_loss_stop": 0.02,
        "max_capital_increase_without_new_review": 0.0,
    }


def _payload(decision: str = "PASS") -> dict:
    findings = []
    if decision != "PASS":
        findings = [
            {
                "severity": decision,
                "code": f"CANONICAL_{decision}",
                "message": f"Canonical readiness is {decision}.",
            }
        ]
    return {"decision": decision, "findings": findings, "risk_budget": _risk_budget()}


def _write_run(root: Path, run_id: str, payload: dict) -> Path:
    run = root / run_id
    run.mkdir()
    artifact = run / "micro_live_readiness.json"
    artifact.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return artifact


def test_reads_only_canonical_fields_with_hash_mtime_and_fixed_authority(tmp_path: Path) -> None:
    artifact = _write_run(tmp_path, "20260830_120000", _payload("PASS"))
    raw = artifact.read_bytes()

    view = ResearchReadinessFacade(tmp_path).read("20260830_120000")

    assert view["decision"] == "PASS"
    assert view["findings"] == []
    assert view["risk_budget"] == _risk_budget()
    assert view["reason"] is None
    assert view["authority"] == AUTHORITY == "src/quantify/readiness"
    assert view["read_only"] is True
    assert view["broker_access"] is False
    assert view["live_trading_allowed"] is False
    assert view["artifact_sha256"] == hashlib.sha256(raw).hexdigest()
    assert view["artifact_mtime"].endswith("+00:00")
    assert view["artifact_size_bytes"] == len(raw)


@pytest.mark.parametrize(
    "run_id",
    [
        "../outside",
        "..",
        ".",
        "/absolute",
        r"C:\outside",
        r"nested\run",
        "nested/run",
        "has.dot",
        "",
    ],
)
def test_rejects_traversal_absolute_paths_and_separators(tmp_path: Path, run_id: str) -> None:
    facade = ResearchReadinessFacade(tmp_path)

    with pytest.raises(InvalidRunIdError):
        facade.read(run_id)


def test_rejects_run_directory_symlink_escape(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    _write_run(outside, "source", _payload())
    try:
        (allowed / "escaped_run").symlink_to(outside / "source", target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    with pytest.raises(UnsafeResearchPathError):
        ResearchReadinessFacade(allowed).read("escaped_run")


def test_rejects_readiness_file_symlink_escape(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    run = allowed / "safe_run"
    outside = tmp_path / "outside.json"
    run.mkdir(parents=True)
    outside.write_text(json.dumps(_payload()), encoding="utf-8")
    try:
        (run / "micro_live_readiness.json").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"file symlinks are unavailable: {exc}")

    with pytest.raises(UnsafeResearchPathError):
        ResearchReadinessFacade(allowed).read("safe_run")


def test_read_does_not_write_or_change_the_artifact(tmp_path: Path) -> None:
    artifact = _write_run(tmp_path, "read_only_run", _payload("WATCH"))
    before_bytes = artifact.read_bytes()
    before_stat = artifact.stat()
    facade = ResearchReadinessFacade(tmp_path)

    with patch.object(Path, "write_text", side_effect=AssertionError("unexpected write")):
        view = facade.get_readiness("read_only_run")

    after_stat = artifact.stat()
    assert view["decision"] == "WATCH"
    assert artifact.read_bytes() == before_bytes
    assert after_stat.st_size == before_stat.st_size
    assert after_stat.st_mtime_ns == before_stat.st_mtime_ns


def test_observation_and_llm_fields_cannot_upgrade_canonical_block(tmp_path: Path) -> None:
    payload = _payload("BLOCK")
    payload.update(
        {
            "observation_decision": "PASS",
            "llm_decision": "PASS",
            "donor_score": 100,
        }
    )
    _write_run(tmp_path, "blocked_run", payload)

    view = ResearchReadinessFacade(tmp_path).read("blocked_run")

    assert view["decision"] == "BLOCK"
    assert view["reason"] is None
    assert view["findings"][0]["code"] == "CANONICAL_BLOCK"
    assert "observation_decision" not in view
    assert "llm_decision" not in view
    assert "donor_score" not in view


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ("{not-json", "READINESS_INVALID"),
        (
            json.dumps({"decision": "APPROVE", "findings": [], "risk_budget": _risk_budget()}),
            "READINESS_INVALID",
        ),
        (json.dumps({"llm_decision": "PASS", "observation_decision": "PASS"}), "READINESS_INVALID"),
        (
            json.dumps(
                {
                    "decision": "PASS",
                    "findings": [{"severity": "BLOCK", "code": "CONFLICT", "message": "blocked"}],
                    "risk_budget": _risk_budget(),
                }
            ),
            "READINESS_INVALID",
        ),
    ],
)
def test_corrupt_unknown_and_conflicting_artifacts_fail_closed(
    tmp_path: Path,
    content: str,
    reason: str,
) -> None:
    run = tmp_path / "invalid_run"
    run.mkdir()
    artifact = run / "micro_live_readiness.json"
    artifact.write_text(content, encoding="utf-8")

    view = ResearchReadinessFacade(tmp_path).read("invalid_run")

    assert view["decision"] == "BLOCK"
    assert view["reason"] == reason
    assert view["findings"][0]["severity"] == "BLOCK"
    assert view["risk_budget"]["max_position_pct"] == 0.0
    assert view["artifact_sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()


def test_missing_run_and_missing_artifact_fail_closed_with_reasons(tmp_path: Path) -> None:
    (tmp_path / "empty_run").mkdir()
    facade = ResearchReadinessFacade(tmp_path)

    missing_run = facade.read("unknown_run")
    missing_artifact = facade.read("empty_run")

    assert missing_run["decision"] == missing_artifact["decision"] == "BLOCK"
    assert missing_run["reason"] == "RUN_NOT_FOUND"
    assert missing_artifact["reason"] == "READINESS_MISSING"
    assert missing_run["artifact_sha256"] is None
    assert missing_artifact["artifact_mtime"] is None


def test_list_run_ids_is_safe_sorted_and_bounded(tmp_path: Path) -> None:
    for name in ("run_001", "run_003", "run_002", ".hidden"):
        (tmp_path / name).mkdir()
    (tmp_path / "not_a_run").write_text("file", encoding="utf-8")

    facade = ResearchReadinessFacade(tmp_path)

    assert facade.list_run_ids(limit=2) == ["run_003", "run_002"]
    with pytest.raises(ValueError):
        facade.list_run_ids(limit=0)
    with pytest.raises(ValueError):
        facade.list_run_ids(limit=201)
