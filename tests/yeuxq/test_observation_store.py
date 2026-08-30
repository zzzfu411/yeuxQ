from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json

import pytest

from yeuxq.contracts import SHANGHAI_TZ, TrendObservation, canonical_sha256
from yeuxq.observation_store import (
    DuplicateObservationError,
    GENESIS_HASH,
    ObservationIntegrityError,
    ObservationStore,
    PathTraversalError,
)


def _observation(observation_id: str, *, minute: int = 0) -> TrendObservation:
    event_time = datetime(2026, 8, 30, 10, minute, tzinfo=SHANGHAI_TZ)
    return TrendObservation(
        observation_id=observation_id,
        symbol="600519.SH",
        event_time=event_time,
        received_at=event_time + timedelta(seconds=1),
        timeframe="1m",
        source="test-source",
        engine="test-engine",
        version="1.0.0",
        data_fingerprint=canonical_sha256({"id": observation_id}),
        code_fingerprint=canonical_sha256({"code": "abc"}),
        config_fingerprint=canonical_sha256({"window": 5}),
        reason_codes=("TREND_CONFIRMED",),
        stale_after=event_time + timedelta(minutes=1),
        action="HOLD",
    )


def test_store_appends_canonical_hash_chain_and_reads_validated_snapshot(tmp_path) -> None:
    store = ObservationStore(tmp_path)
    first = _observation("obs-1")
    second = _observation("obs-2", minute=1)

    first_hash = store.append(first)
    second_hash = store.append(second)

    assert store.verify_integrity() is True
    assert store.read_all() == (first, second)
    assert store.last_record_hash == second_hash
    assert len(store) == 2
    lines = store.path.read_text(encoding="utf-8").splitlines()
    payloads = [json.loads(line) for line in lines]
    assert payloads[0]["prev_hash"] == GENESIS_HASH
    assert payloads[0]["record_hash"] == first_hash
    assert payloads[1]["prev_hash"] == first_hash
    assert payloads[1]["record_hash"] == second_hash
    assert lines[0].encode("utf-8") == __import__(
        "yeuxq.contracts", fromlist=["canonical_json_bytes"]
    ).canonical_json_bytes(payloads[0])


def test_duplicate_id_is_rejected_without_modifying_log(tmp_path) -> None:
    store = ObservationStore(tmp_path)
    store.append(_observation("same-id"))
    before = store.path.read_bytes()

    with pytest.raises(DuplicateObservationError, match="same-id"):
        store.append(_observation("same-id", minute=1))

    assert store.path.read_bytes() == before


def test_payload_tampering_is_detected_and_blocks_future_append(tmp_path) -> None:
    store = ObservationStore(tmp_path)
    store.append(_observation("obs-1"))
    tampered = store.path.read_bytes().replace(b'"action":"HOLD"', b'"action":"SELL"')
    store.path.write_bytes(tampered)

    with pytest.raises(ObservationIntegrityError, match="observation hash"):
        store.verify_integrity()
    with pytest.raises(ObservationIntegrityError):
        store.append(_observation("obs-2", minute=1))


def test_previous_hash_tampering_is_detected(tmp_path) -> None:
    store = ObservationStore(tmp_path)
    store.append(_observation("obs-1"))
    store.append(_observation("obs-2", minute=1))
    lines = store.path.read_text(encoding="utf-8").splitlines()
    second = json.loads(lines[1])
    second["prev_hash"] = GENESIS_HASH
    # Re-encoding is canonical, so this specifically exercises chain validation.
    from yeuxq.contracts import canonical_json

    store.path.write_bytes((lines[0] + "\n" + canonical_json(second) + "\n").encode("utf-8"))

    with pytest.raises(ObservationIntegrityError, match="previous-hash chain"):
        store.verify_integrity()


def test_partial_line_is_rejected(tmp_path) -> None:
    store = ObservationStore(tmp_path)
    store.append(_observation("obs-1"))
    store.path.write_bytes(store.path.read_bytes().removesuffix(b"\n"))

    with pytest.raises(ObservationIntegrityError, match="partial"):
        store.read_all()


@pytest.mark.parametrize("relative", ["../escape.jsonl", "nested/../../escape.jsonl"])
def test_store_rejects_path_traversal(tmp_path, relative: str) -> None:
    with pytest.raises(PathTraversalError):
        ObservationStore(tmp_path, relative)


def test_store_rejects_absolute_relative_path(tmp_path) -> None:
    with pytest.raises(PathTraversalError):
        ObservationStore(tmp_path, tmp_path / "absolute.jsonl")


def test_direct_jsonl_path_is_supported(tmp_path) -> None:
    store = ObservationStore(tmp_path / "journal.jsonl")
    store.append(_observation("obs-direct"))

    assert store.path == (tmp_path / "journal.jsonl").resolve()
    assert store.get("obs-direct") == _observation("obs-direct")
    assert store.get("missing") is None


def test_concurrent_stores_produce_one_valid_chain(tmp_path) -> None:
    path = tmp_path / "concurrent.jsonl"

    def append(index: int) -> str:
        return ObservationStore(path).append(_observation(f"obs-{index}", minute=index))

    with ThreadPoolExecutor(max_workers=4) as executor:
        hashes = list(executor.map(append, range(8)))

    store = ObservationStore(path)
    assert len(set(hashes)) == 8
    assert store.verify_integrity() is True
    assert {item.observation_id for item in store.read_all()} == {
        f"obs-{index}" for index in range(8)
    }
