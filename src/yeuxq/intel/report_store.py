"""Strict, root-confined storage for generated Markdown reports."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import math
import os
from pathlib import Path
import re
import secrets
import stat
import threading

from yeuxq.contracts import ContractValidationError, SymbolId


class ReportStoreError(RuntimeError):
    """Base class for report storage failures."""


class ReportValidationError(ReportStoreError, ValueError):
    """Raised when a report identifier or payload is invalid."""


class ReportPathError(ReportStoreError):
    """Raised when a filesystem object violates the configured root boundary."""


class ReportNotFoundError(ReportStoreError, FileNotFoundError):
    """Raised when a valid report identifier has no stored file."""


class ReportExpiredError(ReportNotFoundError):
    """Raised when a stored report is outside its retention window."""


class ReportKind(str, Enum):
    NEWS = "news"
    REPORT = "report"
    EARNINGS = "earnings"
    BRIEF = "brief"
    VISION = "vision"

    @classmethod
    def parse(cls, value: str | ReportKind) -> ReportKind:
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise ReportValidationError("report kind is invalid")
        try:
            return cls(value.strip().lower())
        except ValueError as exc:
            raise ReportValidationError("report kind is invalid") from exc


_REPORT_ID_PATTERN = re.compile(
    r"^(?P<subject>(?:[0-9]{6}(?:\.(?:SH|SZ|BJ))?|WATCH))_"
    r"(?P<kind>news|report|earnings|brief|vision)_"
    r"(?P<stamp>[0-9]{8}T[0-9]{12}Z)_"
    r"(?P<nonce>[0-9a-f]{12})\.md$",
    re.ASCII,
)


def _aware_utc(value: datetime | None = None) -> datetime:
    current = datetime.now(timezone.utc) if value is None else value
    if not isinstance(current, datetime) or current.tzinfo is None or current.utcoffset() is None:
        raise ReportValidationError("report time must be timezone-aware")
    return current.astimezone(timezone.utc)


def _subject(value: str | SymbolId, kind: ReportKind) -> str:
    if isinstance(value, str) and value.strip().upper() == "WATCH":
        if kind is not ReportKind.BRIEF:
            raise ReportValidationError("WATCH is only valid for brief reports")
        return "WATCH"
    if kind is ReportKind.BRIEF:
        raise ReportValidationError("brief reports require the WATCH subject")
    try:
        return SymbolId.parse(value).code
    except ContractValidationError as exc:
        raise ReportValidationError("report subject must be an ASCII market symbol") from exc


@dataclass(frozen=True, slots=True)
class ReportId:
    value: str
    subject: str
    kind: ReportKind
    created_at: datetime

    @classmethod
    def parse(cls, value: str | ReportId) -> ReportId:
        if isinstance(value, cls):
            return value
        if not isinstance(value, str) or len(value) > 128:
            raise ReportValidationError("report id is invalid")
        match = _REPORT_ID_PATTERN.fullmatch(value)
        if match is None:
            raise ReportValidationError("report id is invalid")
        kind = ReportKind(match.group("kind"))
        raw_subject = match.group("subject")
        subject = raw_subject if raw_subject == "WATCH" else SymbolId.parse(raw_subject).code
        if (subject == "WATCH") is not (kind is ReportKind.BRIEF):
            raise ReportValidationError("report id has an invalid subject-kind combination")
        try:
            created_at = datetime.strptime(match.group("stamp"), "%Y%m%dT%H%M%S%fZ").replace(
                tzinfo=timezone.utc
            )
        except ValueError as exc:
            raise ReportValidationError("report id timestamp is invalid") from exc
        return cls(value=value, subject=subject, kind=kind, created_at=created_at)

    @classmethod
    def new(
        cls,
        subject: str | SymbolId,
        kind: str | ReportKind,
        *,
        now: datetime | None = None,
    ) -> ReportId:
        parsed_kind = ReportKind.parse(kind)
        parsed_subject = _subject(subject, parsed_kind)
        created_at = _aware_utc(now)
        stamp = created_at.strftime("%Y%m%dT%H%M%S%fZ")
        return cls.parse(f"{parsed_subject}_{parsed_kind.value}_{stamp}_{secrets.token_hex(6)}.md")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class StoredReport:
    report_id: ReportId
    size_bytes: int
    expires_at: datetime
    purged_expired: int = 0
    purged_replaced: int = 0

    @property
    def subject(self) -> str:
        return self.report_id.subject

    @property
    def kind(self) -> ReportKind:
        return self.report_id.kind

    @property
    def created_at(self) -> datetime:
        return self.report_id.created_at

    def to_dict(self) -> dict[str, object]:
        return {
            "report_id": self.report_id.value,
            "subject": self.subject,
            "kind": self.kind.value,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "size_bytes": self.size_bytes,
            "purged_expired": self.purged_expired,
            "purged_replaced": self.purged_replaced,
        }


@dataclass(frozen=True, slots=True)
class ReportDocument:
    metadata: StoredReport
    markdown: str


_LOCAL_LOCKS: dict[str, threading.RLock] = {}
_LOCAL_LOCKS_GUARD = threading.Lock()


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
def _platform_lock(path: Path) -> Iterator[None]:
    flags = os.O_RDWR | os.O_CREAT
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "r+b") as handle:
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


class ReportStore:
    """Store reports under one fixed directory without user-derived paths."""

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        ttl_hours: float = 24.0,
        replace_same_kind: bool = True,
        max_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        raw_root = Path(root)
        if not raw_root.parts or ".." in raw_root.parts:
            raise ReportPathError("report root must be explicit and must not contain '..'")
        resolved_root = raw_root.resolve(strict=False)
        if resolved_root.parent == resolved_root:
            raise ReportPathError("filesystem roots cannot be used as the report root")
        if not isinstance(ttl_hours, (int, float)) or isinstance(ttl_hours, bool):
            raise ReportValidationError("ttl_hours must be a positive finite number")
        ttl = float(ttl_hours)
        if not math.isfinite(ttl) or ttl <= 0:
            raise ReportValidationError("ttl_hours must be a positive finite number")
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ReportValidationError("max_bytes must be a positive integer")
        self._root = resolved_root
        self._ttl = timedelta(hours=ttl)
        self._replace_same_kind = bool(replace_same_kind)
        self._max_bytes = max_bytes
        self._lock_path = self._root / ".report-store.lock"

    @property
    def root(self) -> Path:
        return self._root

    def _prepare_root(self) -> None:
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self._root.is_dir() or self._root.resolve(strict=True) != self._root:
            raise ReportPathError("report root changed or is not a directory")
        if self._lock_path.exists():
            mode = os.lstat(self._lock_path).st_mode
            if not stat.S_ISREG(mode) or not _is_within(
                self._root, self._lock_path.resolve(strict=True)
            ):
                raise ReportPathError("report lock is not a root-confined regular file")

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        self._prepare_root()
        with _local_lock(self._lock_path):
            self._prepare_root()
            with _platform_lock(self._lock_path):
                self._prepare_root()
                yield

    def _candidate(self, report_id: str | ReportId) -> tuple[ReportId, Path]:
        parsed = ReportId.parse(report_id)
        candidate = self._root / parsed.value
        if candidate.parent != self._root or not _is_within(
            self._root, candidate.resolve(strict=False)
        ):
            raise ReportPathError("report path escapes its configured root")
        return parsed, candidate

    def _existing(self, report_id: str | ReportId) -> tuple[ReportId, Path, os.stat_result]:
        parsed, candidate = self._candidate(report_id)
        try:
            details = os.lstat(candidate)
        except FileNotFoundError as exc:
            raise ReportNotFoundError("report does not exist") from exc
        if not stat.S_ISREG(details.st_mode):
            raise ReportPathError("report is not a regular file")
        if not _is_within(self._root, candidate.resolve(strict=True)):
            raise ReportPathError("report resolves outside its configured root")
        return parsed, candidate, details

    def _metadata(
        self,
        report_id: ReportId,
        details: os.stat_result,
        *,
        purged_expired: int = 0,
        purged_replaced: int = 0,
    ) -> StoredReport:
        return StoredReport(
            report_id=report_id,
            size_bytes=details.st_size,
            expires_at=report_id.created_at + self._ttl,
            purged_expired=purged_expired,
            purged_replaced=purged_replaced,
        )

    def _iter_unlocked(self) -> Iterator[tuple[ReportId, Path, os.stat_result]]:
        for candidate in self._root.iterdir():
            try:
                parsed = ReportId.parse(candidate.name)
                details = os.lstat(candidate)
            except (OSError, ReportValidationError):
                continue
            if not stat.S_ISREG(details.st_mode):
                continue
            try:
                resolved = candidate.resolve(strict=True)
            except OSError:
                continue
            if _is_within(self._root, resolved):
                yield parsed, candidate, details

    def _unlink_unlocked(self, report_id: ReportId, candidate: Path) -> bool:
        parsed, checked, _ = self._existing(report_id)
        if parsed != report_id or checked != candidate:
            raise ReportPathError("report changed during deletion")
        try:
            checked.unlink()
        except FileNotFoundError:
            return False
        except OSError:
            return False
        return True

    def _write_unlocked(self, report_id: ReportId, payload: bytes) -> Path:
        _, candidate = self._candidate(report_id)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(candidate, flags, 0o600)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short report write")
                view = view[written:]
            os.fsync(descriptor)
        except BaseException:
            os.close(descriptor)
            try:
                candidate.unlink()
            except OSError:
                pass
            raise
        else:
            os.close(descriptor)
        return candidate

    def _purge_expired_unlocked(self, reference: datetime, exclude: ReportId | None = None) -> int:
        removed = 0
        for report_id, candidate, _ in list(self._iter_unlocked()):
            if report_id == exclude or report_id.created_at + self._ttl > reference:
                continue
            if self._unlink_unlocked(report_id, candidate):
                removed += 1
        return removed

    def _purge_replaced_unlocked(self, keep: ReportId) -> int:
        removed = 0
        for report_id, candidate, _ in list(self._iter_unlocked()):
            if report_id == keep:
                continue
            if report_id.subject == keep.subject and report_id.kind is keep.kind:
                if self._unlink_unlocked(report_id, candidate):
                    removed += 1
        return removed

    def save(
        self,
        subject: str | SymbolId,
        kind: str | ReportKind,
        markdown: str,
        *,
        now: datetime | None = None,
    ) -> StoredReport:
        parsed_kind = ReportKind.parse(kind)
        parsed_subject = _subject(subject, parsed_kind)
        if not isinstance(markdown, str) or not markdown.strip():
            raise ReportValidationError("report markdown must be non-empty text")
        payload = markdown.encode("utf-8")
        if len(payload) > self._max_bytes:
            raise ReportValidationError("report markdown exceeds the configured size limit")
        reference = _aware_utc(now)
        with self._exclusive():
            for _ in range(8):
                report_id = ReportId.new(parsed_subject, parsed_kind, now=reference)
                try:
                    candidate = self._write_unlocked(report_id, payload)
                except FileExistsError:
                    continue
                break
            else:
                raise ReportStoreError("could not allocate a unique report id")
            details = os.lstat(candidate)
            expired = self._purge_expired_unlocked(reference, exclude=report_id)
            replaced = self._purge_replaced_unlocked(report_id) if self._replace_same_kind else 0
            return self._metadata(
                report_id,
                details,
                purged_expired=expired,
                purged_replaced=replaced,
            )

    def list(
        self,
        *,
        subject: str | SymbolId | None = None,
        limit: int = 40,
        now: datetime | None = None,
    ) -> list[StoredReport]:
        if type(limit) is not int or not 1 <= limit <= 80:
            raise ReportValidationError("report list limit must be between 1 and 80")
        normalized_subject: str | None = None
        if subject is not None:
            if isinstance(subject, str) and subject.strip().upper() == "WATCH":
                normalized_subject = "WATCH"
            else:
                try:
                    normalized_subject = SymbolId.parse(subject).code
                except ContractValidationError as exc:
                    raise ReportValidationError("report subject is invalid") from exc
        reference = _aware_utc(now)
        with self._exclusive():
            rows = [
                self._metadata(report_id, details)
                for report_id, _, details in self._iter_unlocked()
                if report_id.created_at + self._ttl > reference
                and (normalized_subject is None or report_id.subject == normalized_subject)
            ]
        rows.sort(key=lambda item: (item.created_at, item.report_id.value), reverse=True)
        return rows[:limit]

    def read(
        self,
        report_id: str | ReportId,
        *,
        now: datetime | None = None,
    ) -> ReportDocument:
        reference = _aware_utc(now)
        with self._exclusive():
            parsed, candidate, details = self._existing(report_id)
            metadata = self._metadata(parsed, details)
            if metadata.expires_at <= reference:
                raise ReportExpiredError("report does not exist or has expired")
            if details.st_size > self._max_bytes:
                raise ReportValidationError("stored report exceeds the configured size limit")
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(candidate, flags)
            try:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    raise ReportPathError("report is not a regular file")
                payload = bytearray()
                while True:
                    chunk = os.read(descriptor, min(65536, self._max_bytes + 1 - len(payload)))
                    if not chunk:
                        break
                    payload.extend(chunk)
                    if len(payload) > self._max_bytes:
                        raise ReportValidationError(
                            "stored report exceeds the configured size limit"
                        )
            finally:
                os.close(descriptor)
        try:
            markdown = bytes(payload).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ReportValidationError("stored report is not valid UTF-8") from exc
        return ReportDocument(metadata=metadata, markdown=markdown)

    def delete(self, report_id: str | ReportId) -> bool:
        with self._exclusive():
            parsed, candidate, _ = self._existing(report_id)
            return self._unlink_unlocked(parsed, candidate)

    def purge_expired(self, *, now: datetime | None = None) -> int:
        reference = _aware_utc(now)
        with self._exclusive():
            return self._purge_expired_unlocked(reference)


__all__ = [
    "ReportDocument",
    "ReportExpiredError",
    "ReportId",
    "ReportKind",
    "ReportNotFoundError",
    "ReportPathError",
    "ReportStore",
    "ReportStoreError",
    "ReportValidationError",
    "StoredReport",
]
