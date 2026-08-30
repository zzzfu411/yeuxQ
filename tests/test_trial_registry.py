from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from quantify.research.trial_registry import (
    GENESIS_HASH,
    DuplicateTrialError,
    PreregistrationEvent,
    ResultEvent,
    TrialRegistryFormatError,
    TrialRegistryIntegrityError,
    UnknownTrialError,
    append_preregistration,
    append_result,
    compute_event_hash,
    read_registry,
    verify_registry,
)


def test_append_and_read_preregistration_and_result(tmp_path: Path) -> None:
    registry = tmp_path / "trials.jsonl"

    preregistration = _append_preregistration(registry)
    result = append_result(
        registry,
        trial_id="trial-001",
        result={"decision": "PASS", "metrics": {"sharpe_ratio": 1.25}},
        created_at="2026-07-16T10:00:00+00:00",
    )

    events = read_registry(registry)
    assert events == [preregistration, result]
    assert verify_registry(registry) == events
    assert isinstance(events[0], PreregistrationEvent)
    assert isinstance(events[1], ResultEvent)
    assert events[0].to_dict()["prohibited_live_use"] is True
    assert events[1].trial_id == events[0].trial_id
    assert events[1].previous_hash == events[0].event_hash
    assert [event.sequence for event in events] == [1, 2]


def test_duplicate_preregistration_is_rejected_without_appending(tmp_path: Path) -> None:
    registry = tmp_path / "trials.jsonl"
    _append_preregistration(registry)
    prior_bytes = registry.read_bytes()

    with pytest.raises(DuplicateTrialError, match="already preregistered"):
        _append_preregistration(registry)

    assert registry.read_bytes() == prior_bytes


def test_result_before_registration_is_rejected(tmp_path: Path) -> None:
    registry = tmp_path / "trials.jsonl"

    with pytest.raises(UnknownTrialError, match="unknown trial_id"):
        append_result(
            registry,
            trial_id="trial-001",
            result={"decision": "BLOCK"},
            created_at="2026-07-16T10:00:00+00:00",
        )

    assert registry.read_bytes() == b""


def test_result_append_preserves_every_prior_byte(tmp_path: Path) -> None:
    registry = tmp_path / "trials.jsonl"
    _append_preregistration(registry)
    prior_bytes = registry.read_bytes()

    append_result(
        registry,
        trial_id="trial-001",
        result={"decision": "WATCH", "reason": "needs another fold"},
        created_at="2026-07-16T10:00:00+00:00",
    )

    current_bytes = registry.read_bytes()
    assert current_bytes.startswith(prior_bytes)
    assert current_bytes[: len(prior_bytes)] == prior_bytes
    assert current_bytes[len(prior_bytes) :].count(b"\n") == 1


def test_hash_is_deterministic_and_independently_verifiable(tmp_path: Path) -> None:
    first_path = tmp_path / "first.jsonl"
    second_path = tmp_path / "second.jsonl"
    first = _append_preregistration(first_path)
    second = _append_preregistration(second_path)

    assert first_path.read_bytes() == second_path.read_bytes()
    assert first.event_hash == second.event_hash
    assert first.previous_hash == GENESIS_HASH

    payload = json.loads(first_path.read_text(encoding="utf-8"))
    stored_hash = payload.pop("event_hash")
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert stored_hash == hashlib.sha256(canonical).hexdigest()
    assert stored_hash == compute_event_hash(first)


def test_tamper_is_detected_and_registry_cannot_be_extended(tmp_path: Path) -> None:
    registry = tmp_path / "trials.jsonl"
    _append_preregistration(registry)
    tampered = registry.read_bytes().replace(b'"candidate":"momentum"', b'"candidate":"reversal"')
    assert tampered != registry.read_bytes()
    registry.write_bytes(tampered)

    with pytest.raises(TrialRegistryIntegrityError, match="event_hash does not match"):
        read_registry(registry)
    with pytest.raises(TrialRegistryIntegrityError, match="event_hash does not match"):
        append_result(
            registry,
            trial_id="trial-001",
            result={"decision": "PASS"},
            created_at="2026-07-16T10:00:00+00:00",
        )
    assert registry.read_bytes() == tampered


def test_truncated_final_line_fails_closed(tmp_path: Path) -> None:
    registry = tmp_path / "trials.jsonl"
    _append_preregistration(registry)
    truncated = registry.read_bytes()[:-1]
    registry.write_bytes(truncated)

    with pytest.raises(TrialRegistryFormatError, match="truncated"):
        read_registry(registry)
    with pytest.raises(TrialRegistryFormatError, match="truncated"):
        append_result(
            registry,
            trial_id="trial-001",
            result={"decision": "PASS"},
            created_at="2026-07-16T10:00:00+00:00",
        )
    assert registry.read_bytes() == truncated


def _append_preregistration(path: Path) -> PreregistrationEvent:
    return append_preregistration(
        path,
        trial_id="trial-001",
        candidate="momentum",
        hypothesis="Positive twelve-month returns persist over the test window.",
        parameter_fingerprint="parameters-sha256-001",
        data_fingerprint="data-sha256-001",
        config_fingerprint="config-sha256-001",
        train_boundary={"start": "2020-01-01", "end": "2023-12-31"},
        selection_boundary={"start": "2024-01-01", "end": "2024-12-31"},
        test_boundary={"start": "2025-01-01", "end": "2025-12-31"},
        created_at="2026-07-16T09:00:00+00:00",
        prohibited_live_use=True,
    )
