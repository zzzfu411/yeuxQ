"""Tamper-evident append-only storage for :class:`TrendObservation` values."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import threading
from typing import Iterator

from .contracts import (
    ContractValidationError,
    SHA256_PATTERN,
    TrendObservation,
    canonical_json_bytes,
    canonical_sha256,
)


GENESIS_HASH = "0" * 64
STORE_SCHEMA_VERSION = 1
DEFAULT_LOG_NAME = "observations.jsonl"
_RECORD_FIELDS = {
    "schema_version",
    "prev_hash",
    "observation_hash",
    "observation",
    "record_hash",
}
_LOCAL_LOCKS: dict[str, threading.RLock] = {}
_LOCAL_LOCKS_GUARD = threading.Lock()


class ObservationStoreError(RuntimeError):
    """Base class for storage failures."""


class ObservationIntegrityError(ObservationStoreError):
    """Raised when a stored line or its hash chain is not trustworthy."""


class DuplicateObservationError(ObservationStoreError):
    """Raised when an observation ID has already been appended."""


class PathTraversalError(ObservationStoreError, ValueError):
    """Raised when a log path could escape its configured root."""


@dataclass(frozen=True, slots=True)
class StoredObservation:
    """Validated representation of one hash-chained JSONL record."""

    line_number: int
    observation: TrendObservation
    observation_hash: str
    prev_hash: str
    record_hash: str


def _local_lock(path: Path) -> threading.RLock:
    key = os.path.normcase(str(path))
    with _LOCAL_LOCKS_GUARD:
        return _LOCAL_LOCKS.setdefault(key, threading.RLock())


def _is_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


@contextmanager
def _platform_file_lock(path: Path) -> Iterator[None]:
    """Hold a cooperative cross-process one-byte lock."""

    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
            os.fsync(handle.fileno())
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class ObservationStore:
    """Append-only canonical JSONL store with duplicate and tamper rejection.

    ``root`` normally names a directory and ``relative_path`` names a log
    beneath it.  For convenience, a direct ``.jsonl`` path may be supplied as
    ``root`` while omitting ``relative_path``.  Absolute relative paths and any
    ``..`` component are rejected before filesystem access.
    """

    def __init__(
        self,
        root: str | os.PathLike[str],
        relative_path: str | os.PathLike[str] | None = None,
    ) -> None:
        raw_root = Path(root)
        if ".." in raw_root.parts:
            raise PathTraversalError("store root must not contain '..'")

        if relative_path is None and raw_root.suffix.lower() == ".jsonl":
            base = raw_root.parent.resolve(strict=False)
            target = raw_root.resolve(strict=False)
        else:
            base = raw_root.resolve(strict=False)
            relative = Path(DEFAULT_LOG_NAME if relative_path is None else relative_path)
            if relative.is_absolute() or ".." in relative.parts:
                raise PathTraversalError("observation log must be a relative path without '..'")
            target = (base / relative).resolve(strict=False)

        if not _is_within(base, target):
            raise PathTraversalError("observation log escapes the configured root")
        if target.suffix.lower() != ".jsonl":
            raise PathTraversalError("observation log must use the .jsonl suffix")

        self._root = base
        self._path = target
        self._lock_path = target.with_suffix(target.suffix + ".lock")
        if not _is_within(base, self._lock_path):
            raise PathTraversalError("observation lock file escapes the configured root")

    @property
    def root(self) -> Path:
        return self._root

    @property
    def path(self) -> Path:
        return self._path

    def _prepare_paths(self) -> None:
        # Resolve on every operation so an intervening symlink cannot redirect
        # writes outside the boundary accepted by the constructor.
        resolved_parent = self._path.parent.resolve(strict=False)
        if not _is_within(self._root, resolved_parent):
            raise PathTraversalError("observation log parent escaped the configured root")
        if self._path.exists() and not _is_within(self._root, self._path.resolve(strict=True)):
            raise PathTraversalError("observation log resolves outside the configured root")
        if self._lock_path.exists() and not _is_within(
            self._root, self._lock_path.resolve(strict=True)
        ):
            raise PathTraversalError("observation lock resolves outside the configured root")
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        self._prepare_paths()
        with _local_lock(self._lock_path):
            with _platform_file_lock(self._lock_path):
                self._prepare_paths()
                yield

    def append(self, observation: TrendObservation) -> str:
        """Validate and append one observation, returning its record hash.

        The existing chain is checked while holding the same lock used for the
        append.  Consequently a duplicate ID or any prior corruption blocks
        the write instead of extending an untrustworthy journal.
        """

        if not isinstance(observation, TrendObservation):
            raise TypeError("observation must be a TrendObservation")
        with self._exclusive():
            records = self._read_records_unlocked()
            known_ids = {record.observation.observation_id for record in records}
            if observation.observation_id in known_ids:
                raise DuplicateObservationError(
                    f"observation_id already exists: {observation.observation_id}"
                )
            previous_hash = records[-1].record_hash if records else GENESIS_HASH
            observation_payload = observation.to_dict()
            unsigned_record = {
                "schema_version": STORE_SCHEMA_VERSION,
                "prev_hash": previous_hash,
                "observation_hash": canonical_sha256(observation_payload),
                "observation": observation_payload,
            }
            record_hash = canonical_sha256(unsigned_record)
            payload = {**unsigned_record, "record_hash": record_hash}
            encoded = canonical_json_bytes(payload) + b"\n"
            self._append_bytes_unlocked(encoded)
            return record_hash

    def _append_bytes_unlocked(self, encoded: bytes) -> None:
        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        descriptor = os.open(self._path, flags, 0o600)
        try:
            written = os.write(descriptor, encoded)
            if written != len(encoded):
                raise ObservationStoreError(
                    f"short append: wrote {written} of {len(encoded)} bytes"
                )
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _read_records_unlocked(self) -> list[StoredObservation]:
        if not self._path.exists():
            return []
        if not self._path.is_file():
            raise ObservationIntegrityError("observation log is not a regular file")
        raw = self._path.read_bytes()
        if not raw:
            return []
        if not raw.endswith(b"\n"):
            raise ObservationIntegrityError("observation log ends with a partial record")

        records: list[StoredObservation] = []
        previous_hash = GENESIS_HASH
        observation_ids: set[str] = set()
        for line_number, line in enumerate(raw.splitlines(keepends=True), start=1):
            raw_payload = line[:-1]
            if not raw_payload or raw_payload.endswith(b"\r"):
                raise ObservationIntegrityError(f"line {line_number} is not canonical JSONL")
            try:
                value = json.loads(raw_payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ObservationIntegrityError(f"line {line_number} is invalid JSON") from exc
            if not isinstance(value, dict):
                raise ObservationIntegrityError(f"line {line_number} must contain an object")
            if set(value) != _RECORD_FIELDS:
                raise ObservationIntegrityError(f"line {line_number} has invalid record fields")
            if canonical_json_bytes(value) != raw_payload:
                raise ObservationIntegrityError(f"line {line_number} is not canonical JSON")
            if value["schema_version"] != STORE_SCHEMA_VERSION:
                raise ObservationIntegrityError(f"line {line_number} has an unknown schema version")
            if value["prev_hash"] != previous_hash:
                raise ObservationIntegrityError(
                    f"line {line_number} breaks the previous-hash chain"
                )
            for hash_field in ("prev_hash", "observation_hash", "record_hash"):
                hash_value = value[hash_field]
                if not isinstance(hash_value, str) or SHA256_PATTERN.fullmatch(hash_value) is None:
                    raise ObservationIntegrityError(
                        f"line {line_number} has an invalid {hash_field}"
                    )
            if canonical_sha256(value["observation"]) != value["observation_hash"]:
                raise ObservationIntegrityError(
                    f"line {line_number} has a mismatched observation hash"
                )
            unsigned_record = {key: value[key] for key in value if key != "record_hash"}
            if canonical_sha256(unsigned_record) != value["record_hash"]:
                raise ObservationIntegrityError(f"line {line_number} has a mismatched record hash")
            try:
                observation = TrendObservation.from_dict(value["observation"])
            except (ContractValidationError, KeyError, TypeError, ValueError) as exc:
                raise ObservationIntegrityError(
                    f"line {line_number} contains an invalid observation"
                ) from exc
            if observation.observation_id in observation_ids:
                raise ObservationIntegrityError(
                    f"line {line_number} repeats observation_id {observation.observation_id!r}"
                )
            observation_ids.add(observation.observation_id)
            records.append(
                StoredObservation(
                    line_number=line_number,
                    observation=observation,
                    observation_hash=value["observation_hash"],
                    prev_hash=value["prev_hash"],
                    record_hash=value["record_hash"],
                )
            )
            previous_hash = value["record_hash"]
        return records

    def records(self) -> tuple[StoredObservation, ...]:
        """Return an immutable snapshot after validating the complete chain."""

        with self._exclusive():
            return tuple(self._read_records_unlocked())

    def read_all(self) -> tuple[TrendObservation, ...]:
        return tuple(record.observation for record in self.records())

    def get(self, observation_id: str) -> TrendObservation | None:
        for observation in self.read_all():
            if observation.observation_id == observation_id:
                return observation
        return None

    def verify_integrity(self) -> bool:
        """Validate canonical encoding, all payload hashes, and the full chain."""

        self.records()
        return True

    def validate(self) -> str:
        """Validate the log and return its current chain head."""

        records = self.records()
        return records[-1].record_hash if records else GENESIS_HASH

    @property
    def last_record_hash(self) -> str:
        return self.validate()

    def __len__(self) -> int:
        return len(self.records())


AppendOnlyObservationStore = ObservationStore


__all__ = [
    "AppendOnlyObservationStore",
    "DEFAULT_LOG_NAME",
    "DuplicateObservationError",
    "GENESIS_HASH",
    "ObservationIntegrityError",
    "ObservationStore",
    "ObservationStoreError",
    "PathTraversalError",
    "StoredObservation",
]
