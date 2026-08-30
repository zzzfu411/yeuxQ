"""Append-only preregistration and result ledger for research trials.

The registry is canonical UTF-8 JSONL. Each event hashes its canonical content,
including the previous event hash, so every read can verify the complete chain.
This module records research evidence only and contains no live-trading behavior.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
from typing import Any, BinaryIO, Literal, TypeAlias

TRIAL_REGISTRY_SCHEMA_VERSION = 1
HASH_ALGORITHM = "sha256"
GENESIS_HASH = "0" * 64

EventType: TypeAlias = Literal["preregistration", "result"]
_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class TrialRegistryError(ValueError):
    """Base class for a registry that cannot be safely read or extended."""


class TrialRegistryFormatError(TrialRegistryError):
    """Raised when registry bytes are malformed or not canonical JSONL."""


class TrialRegistryIntegrityError(TrialRegistryError):
    """Raised when a sequence number or SHA-256 chain link does not verify."""


class TrialRegistryValidationError(TrialRegistryError):
    """Raised when a proposed or stored event violates the event schema."""


class DuplicateTrialError(TrialRegistryError):
    """Raised when a trial ID has already been preregistered."""


class DuplicateResultError(TrialRegistryError):
    """Raised when a result ID already exists in the registry."""


class UnknownTrialError(TrialRegistryError):
    """Raised when a result refers to a trial that is not preregistered."""


class TrialEventOrderError(TrialRegistryError):
    """Raised when otherwise valid events appear in an invalid order."""


@dataclass(frozen=True, slots=True)
class PreregistrationEvent:
    """Immutable view of a preregistration line in the registry."""

    schema_version: int
    sequence: int
    event_type: Literal["preregistration"]
    trial_id: str
    candidate: str
    hypothesis: str
    parameter_fingerprint: str
    data_fingerprint: str
    config_fingerprint: str
    train_boundary: Any
    selection_boundary: Any
    test_boundary: Any
    created_at: str
    prohibited_live_use: bool
    hash_algorithm: Literal["sha256"]
    previous_hash: str
    event_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "trial_id": self.trial_id,
            "candidate": self.candidate,
            "hypothesis": self.hypothesis,
            "parameter_fingerprint": self.parameter_fingerprint,
            "data_fingerprint": self.data_fingerprint,
            "config_fingerprint": self.config_fingerprint,
            "train_boundary": _json_copy(self.train_boundary),
            "selection_boundary": _json_copy(self.selection_boundary),
            "test_boundary": _json_copy(self.test_boundary),
            "created_at": self.created_at,
            "prohibited_live_use": self.prohibited_live_use,
            "hash_algorithm": self.hash_algorithm,
            "previous_hash": self.previous_hash,
            "event_hash": self.event_hash,
        }


@dataclass(frozen=True, slots=True)
class ResultEvent:
    """Immutable view of a result linked to a preregistered trial."""

    schema_version: int
    sequence: int
    event_type: Literal["result"]
    result_id: str
    trial_id: str
    result: dict[str, Any]
    created_at: str
    hash_algorithm: Literal["sha256"]
    previous_hash: str
    event_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "result_id": self.result_id,
            "trial_id": self.trial_id,
            "result": _json_copy(self.result),
            "created_at": self.created_at,
            "hash_algorithm": self.hash_algorithm,
            "previous_hash": self.previous_hash,
            "event_hash": self.event_hash,
        }


RegistryEvent: TypeAlias = PreregistrationEvent | ResultEvent

_PREREGISTRATION_FIELDS = {
    "schema_version",
    "sequence",
    "event_type",
    "trial_id",
    "candidate",
    "hypothesis",
    "parameter_fingerprint",
    "data_fingerprint",
    "config_fingerprint",
    "train_boundary",
    "selection_boundary",
    "test_boundary",
    "created_at",
    "prohibited_live_use",
    "hash_algorithm",
    "previous_hash",
    "event_hash",
}
_RESULT_FIELDS = {
    "schema_version",
    "sequence",
    "event_type",
    "result_id",
    "trial_id",
    "result",
    "created_at",
    "hash_algorithm",
    "previous_hash",
    "event_hash",
}


def append_preregistration(
    registry_path: str | Path,
    *,
    trial_id: str,
    candidate: str,
    hypothesis: str,
    parameter_fingerprint: str,
    data_fingerprint: str,
    config_fingerprint: str,
    train_boundary: Any,
    selection_boundary: Any,
    test_boundary: Any,
    created_at: str | None = None,
    prohibited_live_use: bool = True,
) -> PreregistrationEvent:
    """Verify the existing registry and append one unique preregistration."""
    trial_id = _validate_id(trial_id, "trial_id")
    candidate = _validate_text(candidate, "candidate")
    hypothesis = _validate_text(hypothesis, "hypothesis")
    parameter_fingerprint = _validate_text(parameter_fingerprint, "parameter_fingerprint")
    data_fingerprint = _validate_text(data_fingerprint, "data_fingerprint")
    config_fingerprint = _validate_text(config_fingerprint, "config_fingerprint")
    train_boundary = _normalize_boundary(train_boundary, "train_boundary")
    selection_boundary = _normalize_boundary(selection_boundary, "selection_boundary")
    test_boundary = _normalize_boundary(test_boundary, "test_boundary")
    created_at = _validate_timestamp(created_at or _utc_now(), "created_at")[0]
    if prohibited_live_use is not True:
        raise TrialRegistryValidationError("prohibited_live_use must be true")

    def build(events: list[RegistryEvent]) -> PreregistrationEvent:
        if any(
            isinstance(event, PreregistrationEvent) and event.trial_id == trial_id
            for event in events
        ):
            raise DuplicateTrialError(f"trial_id is already preregistered: {trial_id}")

        sequence, previous_hash = _next_link(events)
        payload: dict[str, Any] = {
            "schema_version": TRIAL_REGISTRY_SCHEMA_VERSION,
            "sequence": sequence,
            "event_type": "preregistration",
            "trial_id": trial_id,
            "candidate": candidate,
            "hypothesis": hypothesis,
            "parameter_fingerprint": parameter_fingerprint,
            "data_fingerprint": data_fingerprint,
            "config_fingerprint": config_fingerprint,
            "train_boundary": train_boundary,
            "selection_boundary": selection_boundary,
            "test_boundary": test_boundary,
            "created_at": created_at,
            "prohibited_live_use": True,
            "hash_algorithm": HASH_ALGORITHM,
            "previous_hash": previous_hash,
        }
        payload["event_hash"] = _payload_hash(payload)
        return _preregistration_from_payload(payload, sequence)

    event = _append_event(Path(registry_path), build)
    if not isinstance(event, PreregistrationEvent):  # pragma: no cover - internal invariant
        raise AssertionError("preregistration append produced the wrong event type")
    return event


def append_result(
    registry_path: str | Path,
    *,
    trial_id: str,
    result: Mapping[str, Any],
    created_at: str | None = None,
    result_id: str | None = None,
) -> ResultEvent:
    """Verify the registry and append a result for an existing trial.

    ``result_id`` defaults to ``<trial_id>:result``. Callers that intentionally
    retain several result records for one trial must provide distinct IDs.
    """
    trial_id = _validate_id(trial_id, "trial_id")
    result_id = _validate_id(result_id or f"{trial_id}:result", "result_id")
    normalized_result = _normalize_result(result)
    created_at, result_time = _validate_timestamp(created_at or _utc_now(), "created_at")

    def build(events: list[RegistryEvent]) -> ResultEvent:
        preregistration = next(
            (
                event
                for event in events
                if isinstance(event, PreregistrationEvent) and event.trial_id == trial_id
            ),
            None,
        )
        if preregistration is None:
            raise UnknownTrialError(f"result references unknown trial_id: {trial_id}")
        if any(isinstance(event, ResultEvent) and event.result_id == result_id for event in events):
            raise DuplicateResultError(f"result_id already exists: {result_id}")

        preregistration_time = _validate_timestamp(
            preregistration.created_at, "preregistration created_at"
        )[1]
        prior_result_times = [
            _validate_timestamp(event.created_at, "result created_at")[1]
            for event in events
            if isinstance(event, ResultEvent) and event.trial_id == trial_id
        ]
        if result_time < preregistration_time:
            raise TrialEventOrderError("result created_at precedes its preregistration")
        if prior_result_times and result_time < prior_result_times[-1]:
            raise TrialEventOrderError(
                "result created_at precedes an earlier result for the same trial"
            )

        sequence, previous_hash = _next_link(events)
        payload: dict[str, Any] = {
            "schema_version": TRIAL_REGISTRY_SCHEMA_VERSION,
            "sequence": sequence,
            "event_type": "result",
            "result_id": result_id,
            "trial_id": trial_id,
            "result": normalized_result,
            "created_at": created_at,
            "hash_algorithm": HASH_ALGORITHM,
            "previous_hash": previous_hash,
        }
        payload["event_hash"] = _payload_hash(payload)
        return _result_from_payload(payload, sequence)

    event = _append_event(Path(registry_path), build)
    if not isinstance(event, ResultEvent):  # pragma: no cover - internal invariant
        raise AssertionError("result append produced the wrong event type")
    return event


def read_registry(registry_path: str | Path) -> list[RegistryEvent]:
    """Read all events after verifying canonical encoding and the full chain."""
    path = Path(registry_path)
    try:
        with path.open("rb") as handle, _file_lock(handle, exclusive=False):
            return _parse_registry(handle.read())
    except FileNotFoundError:
        return []


def verify_registry(registry_path: str | Path) -> list[RegistryEvent]:
    """Verify and return registry events; no unverified read path is exposed."""
    return read_registry(registry_path)


def compute_event_hash(event: RegistryEvent | Mapping[str, Any]) -> str:
    """Compute the deterministic SHA-256 digest for an event payload."""
    payload = (
        event.to_dict() if isinstance(event, (PreregistrationEvent, ResultEvent)) else dict(event)
    )
    payload.pop("event_hash", None)
    return _payload_hash(payload)


def _append_event(
    path: Path,
    build: Callable[[list[RegistryEvent]], RegistryEvent],
) -> RegistryEvent:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle, _file_lock(handle, exclusive=True):
        handle.seek(0)
        prior_bytes = handle.read()
        events = _parse_registry(prior_bytes)
        event = build(events)
        encoded = _canonical_json(event.to_dict()) + b"\n"

        handle.seek(0, os.SEEK_END)
        if handle.tell() != len(prior_bytes):
            raise TrialRegistryIntegrityError("registry length changed while append lock was held")
        written = handle.write(encoded)
        if written != len(encoded):  # pragma: no cover - depends on an I/O failure
            raise OSError(f"short registry append: wrote {written} of {len(encoded)} bytes")
        handle.flush()
        os.fsync(handle.fileno())
        return event


def _parse_registry(raw: bytes) -> list[RegistryEvent]:
    if not raw:
        return []
    if not raw.endswith(b"\n"):
        raise TrialRegistryFormatError("registry is truncated: final JSONL line has no newline")

    events: list[RegistryEvent] = []
    preregistrations: dict[str, PreregistrationEvent] = {}
    result_ids: set[str] = set()
    latest_result_time: dict[str, datetime] = {}
    previous_hash = GENESIS_HASH

    for line_number, raw_line in enumerate(raw[:-1].split(b"\n"), start=1):
        if not raw_line:
            raise TrialRegistryFormatError(f"line {line_number}: blank JSONL lines are prohibited")
        payload = _load_canonical_line(raw_line, line_number)
        event = _event_from_payload(payload, line_number, previous_hash)

        if isinstance(event, PreregistrationEvent):
            if event.trial_id in preregistrations:
                raise DuplicateTrialError(
                    f"line {line_number}: duplicate preregistration for {event.trial_id}"
                )
            preregistrations[event.trial_id] = event
        else:
            preregistration = preregistrations.get(event.trial_id)
            if preregistration is None:
                raise UnknownTrialError(
                    f"line {line_number}: result precedes preregistration for {event.trial_id}"
                )
            if event.result_id in result_ids:
                raise DuplicateResultError(
                    f"line {line_number}: duplicate result_id {event.result_id}"
                )
            preregistration_time = _validate_timestamp(
                preregistration.created_at, "preregistration created_at"
            )[1]
            event_time = _validate_timestamp(event.created_at, "result created_at")[1]
            if event_time < preregistration_time:
                raise TrialEventOrderError(
                    f"line {line_number}: result created_at precedes preregistration"
                )
            if (
                event.trial_id in latest_result_time
                and event_time < latest_result_time[event.trial_id]
            ):
                raise TrialEventOrderError(
                    f"line {line_number}: results for {event.trial_id} are out of time order"
                )
            latest_result_time[event.trial_id] = event_time
            result_ids.add(event.result_id)

        events.append(event)
        previous_hash = event.event_hash
    return events


def _event_from_payload(
    payload: dict[str, Any],
    line_number: int,
    expected_previous_hash: str,
) -> RegistryEvent:
    event_type = payload.get("event_type")
    if event_type == "preregistration":
        event = _preregistration_from_payload(payload, line_number)
    elif event_type == "result":
        event = _result_from_payload(payload, line_number)
    else:
        raise TrialRegistryValidationError(
            f"line {line_number}: event_type must be 'preregistration' or 'result'"
        )

    if event.sequence != line_number:
        raise TrialRegistryIntegrityError(
            f"line {line_number}: expected sequence {line_number}, found {event.sequence}"
        )
    if not hmac.compare_digest(event.previous_hash, expected_previous_hash):
        raise TrialRegistryIntegrityError(f"line {line_number}: previous_hash does not match")
    expected_event_hash = compute_event_hash(payload)
    if not hmac.compare_digest(event.event_hash, expected_event_hash):
        raise TrialRegistryIntegrityError(f"line {line_number}: event_hash does not match")
    return event


def _preregistration_from_payload(
    payload: dict[str, Any], line_number: int
) -> PreregistrationEvent:
    _validate_common_payload(payload, _PREREGISTRATION_FIELDS, line_number)
    prohibited_live_use = payload["prohibited_live_use"]
    if prohibited_live_use is not True:
        raise TrialRegistryValidationError(f"line {line_number}: prohibited_live_use must be true")
    return PreregistrationEvent(
        schema_version=payload["schema_version"],
        sequence=payload["sequence"],
        event_type="preregistration",
        trial_id=_validate_id(payload["trial_id"], "trial_id", line_number),
        candidate=_validate_text(payload["candidate"], "candidate", line_number),
        hypothesis=_validate_text(payload["hypothesis"], "hypothesis", line_number),
        parameter_fingerprint=_validate_text(
            payload["parameter_fingerprint"], "parameter_fingerprint", line_number
        ),
        data_fingerprint=_validate_text(
            payload["data_fingerprint"], "data_fingerprint", line_number
        ),
        config_fingerprint=_validate_text(
            payload["config_fingerprint"], "config_fingerprint", line_number
        ),
        train_boundary=_normalize_boundary(
            payload["train_boundary"], "train_boundary", line_number
        ),
        selection_boundary=_normalize_boundary(
            payload["selection_boundary"], "selection_boundary", line_number
        ),
        test_boundary=_normalize_boundary(payload["test_boundary"], "test_boundary", line_number),
        created_at=_validate_timestamp(payload["created_at"], "created_at", line_number)[0],
        prohibited_live_use=True,
        hash_algorithm="sha256",
        previous_hash=_validate_hash(payload["previous_hash"], "previous_hash", line_number),
        event_hash=_validate_hash(payload["event_hash"], "event_hash", line_number),
    )


def _result_from_payload(payload: dict[str, Any], line_number: int) -> ResultEvent:
    _validate_common_payload(payload, _RESULT_FIELDS, line_number)
    return ResultEvent(
        schema_version=payload["schema_version"],
        sequence=payload["sequence"],
        event_type="result",
        result_id=_validate_id(payload["result_id"], "result_id", line_number),
        trial_id=_validate_id(payload["trial_id"], "trial_id", line_number),
        result=_normalize_result(payload["result"], line_number),
        created_at=_validate_timestamp(payload["created_at"], "created_at", line_number)[0],
        hash_algorithm="sha256",
        previous_hash=_validate_hash(payload["previous_hash"], "previous_hash", line_number),
        event_hash=_validate_hash(payload["event_hash"], "event_hash", line_number),
    )


def _validate_common_payload(
    payload: dict[str, Any], expected_fields: set[str], line_number: int
) -> None:
    actual_fields = set(payload)
    if actual_fields != expected_fields:
        missing = sorted(expected_fields - actual_fields)
        extra = sorted(actual_fields - expected_fields)
        raise TrialRegistryValidationError(
            f"line {line_number}: event fields differ from schema; missing={missing}, extra={extra}"
        )
    if type(payload["schema_version"]) is not int or (
        payload["schema_version"] != TRIAL_REGISTRY_SCHEMA_VERSION
    ):
        raise TrialRegistryValidationError(
            f"line {line_number}: unsupported schema_version {payload['schema_version']!r}"
        )
    if type(payload["sequence"]) is not int or payload["sequence"] < 1:
        raise TrialRegistryValidationError(
            f"line {line_number}: sequence must be a positive integer"
        )
    if payload["hash_algorithm"] != HASH_ALGORITHM:
        raise TrialRegistryValidationError(
            f"line {line_number}: hash_algorithm must be {HASH_ALGORITHM!r}"
        )


def _load_canonical_line(raw_line: bytes, line_number: int) -> dict[str, Any]:
    try:
        text = raw_line.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TrialRegistryFormatError(f"line {line_number}: invalid UTF-8") from exc
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, TrialRegistryFormatError) as exc:
        raise TrialRegistryFormatError(f"line {line_number}: malformed JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise TrialRegistryFormatError(f"line {line_number}: event must be a JSON object")
    try:
        canonical = _canonical_json(payload)
    except (TypeError, ValueError) as exc:  # pragma: no cover - parsed JSON is already constrained
        raise TrialRegistryFormatError(f"line {line_number}: invalid JSON value") from exc
    if canonical != raw_line:
        raise TrialRegistryFormatError(f"line {line_number}: JSON is not canonical")
    return payload


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TrialRegistryFormatError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise TrialRegistryFormatError(f"non-finite JSON number {value!r}")


def _validate_text(value: Any, field: str, line_number: int | None = None) -> str:
    prefix = f"line {line_number}: " if line_number is not None else ""
    if not isinstance(value, str) or not value or value != value.strip():
        raise TrialRegistryValidationError(
            f"{prefix}{field} must be a non-empty string without surrounding whitespace"
        )
    return value


def _validate_id(value: Any, field: str, line_number: int | None = None) -> str:
    value = _validate_text(value, field, line_number)
    if _ID_PATTERN.fullmatch(value) is None:
        prefix = f"line {line_number}: " if line_number is not None else ""
        raise TrialRegistryValidationError(
            f"{prefix}{field} must use 1-128 ASCII letters, digits, '.', '_', ':', '/', or '-'"
        )
    return value


def _validate_hash(value: Any, field: str, line_number: int) -> str:
    if not isinstance(value, str) or _HASH_PATTERN.fullmatch(value) is None:
        raise TrialRegistryValidationError(
            f"line {line_number}: {field} must be a lowercase SHA-256 digest"
        )
    return value


def _validate_timestamp(
    value: Any, field: str, line_number: int | None = None
) -> tuple[str, datetime]:
    value = _validate_text(value, field, line_number)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        prefix = f"line {line_number}: " if line_number is not None else ""
        raise TrialRegistryValidationError(
            f"{prefix}{field} must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        prefix = f"line {line_number}: " if line_number is not None else ""
        raise TrialRegistryValidationError(f"{prefix}{field} must include a UTC offset")
    return value, parsed


def _normalize_boundary(value: Any, field: str, line_number: int | None = None) -> Any:
    normalized = _normalize_json(value, field, line_number)
    if not isinstance(normalized, (str, list, dict)) or not normalized:
        prefix = f"line {line_number}: " if line_number is not None else ""
        raise TrialRegistryValidationError(
            f"{prefix}{field} must be a non-empty JSON string, array, or object"
        )
    return normalized


def _normalize_result(result: Any, line_number: int | None = None) -> dict[str, Any]:
    normalized = _normalize_json(result, "result", line_number)
    if not isinstance(normalized, dict) or not normalized:
        prefix = f"line {line_number}: " if line_number is not None else ""
        raise TrialRegistryValidationError(f"{prefix}result must be a non-empty JSON object")
    return normalized


def _normalize_json(value: Any, field: str, line_number: int | None = None) -> Any:
    prefix = f"line {line_number}: " if line_number is not None else ""
    try:
        encoded = _canonical_json(value)
        return json.loads(
            encoded.decode("utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (TypeError, ValueError, TrialRegistryFormatError) as exc:
        raise TrialRegistryValidationError(
            f"{prefix}{field} must contain only JSON values"
        ) from exc


def _json_copy(value: Any) -> Any:
    return json.loads(_canonical_json(value).decode("utf-8"))


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _payload_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(dict(payload))).hexdigest()


def _next_link(events: list[RegistryEvent]) -> tuple[int, str]:
    if not events:
        return 1, GENESIS_HASH
    return len(events) + 1, events[-1].event_hash


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


@contextmanager
def _file_lock(handle: BinaryIO, *, exclusive: bool) -> Iterator[None]:
    """Use the platform advisory lock when one is available."""
    if os.name == "nt":
        import msvcrt

        mode = msvcrt.LK_LOCK if exclusive else msvcrt.LK_RLCK
        handle.seek(0)
        msvcrt.locking(handle.fileno(), mode, 1)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    try:
        import fcntl
    except ImportError:  # pragma: no cover - unusual platform fallback
        yield
        return

    mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    fcntl.flock(handle.fileno(), mode)
    try:
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


read_trial_registry = read_registry
verify_trial_registry = verify_registry
