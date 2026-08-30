"""Read-only, root-confined projection of advisory report files."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import stat

from yeuxq.contracts import ContractValidationError, SymbolId
from yeuxq.intel.report_store import (
    ReportExpiredError,
    ReportId,
    ReportNotFoundError,
    ReportPathError,
    ReportValidationError,
)


def _utc_now(value: datetime | None = None) -> datetime:
    current = datetime.now(timezone.utc) if value is None else value
    if current.tzinfo is None or current.utcoffset() is None:
        raise ReportValidationError("report time must be timezone-aware")
    return current.astimezone(timezone.utc)


def _within(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


class ReportReadFacade:
    """List and read existing reports without creating, locking, purging or deleting."""

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        ttl_hours: float,
        max_bytes: int,
    ) -> None:
        candidate = Path(root).resolve(strict=False)
        if candidate.parent == candidate:
            raise ReportPathError("filesystem roots cannot be used as the report root")
        if not isinstance(ttl_hours, (int, float)) or isinstance(ttl_hours, bool):
            raise ReportValidationError("ttl_hours must be positive")
        if float(ttl_hours) <= 0:
            raise ReportValidationError("ttl_hours must be positive")
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ReportValidationError("max_bytes must be positive")
        self._root = candidate
        self._ttl = timedelta(hours=float(ttl_hours))
        self._max_bytes = max_bytes

    @property
    def root(self) -> Path:
        return self._root

    def _subject(self, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip().upper()
        if normalized == "WATCH":
            return normalized
        try:
            return SymbolId.parse(normalized).code
        except ContractValidationError as exc:
            raise ReportValidationError("report subject is invalid") from exc

    def _metadata(
        self,
        report_id: ReportId,
        details: os.stat_result,
        reference: datetime,
    ) -> dict[str, object]:
        expires_at = report_id.created_at + self._ttl
        remain = max(0, int((expires_at - reference).total_seconds()))
        return {
            "report_id": report_id.value,
            "subject": report_id.subject,
            "symbol": report_id.subject,
            "kind": report_id.kind.value,
            "created_at": report_id.created_at.isoformat(),
            "stamp": report_id.created_at.strftime("%Y-%m-%d %H:%M UTC"),
            "expires_at": expires_at.isoformat(),
            "ttl_remain_sec": remain,
            "size_bytes": details.st_size,
        }

    def _checked_existing(self, report_id: str | ReportId) -> tuple[ReportId, Path, os.stat_result]:
        parsed = ReportId.parse(report_id)
        candidate = self._root / parsed.value
        if candidate.parent != self._root or not _within(
            self._root, candidate.resolve(strict=False)
        ):
            raise ReportPathError("report path escapes its configured root")
        try:
            details = os.lstat(candidate)
        except FileNotFoundError as exc:
            raise ReportNotFoundError("report does not exist") from exc
        if not stat.S_ISREG(details.st_mode):
            raise ReportPathError("report is not a regular file")
        if not _within(self._root, candidate.resolve(strict=True)):
            raise ReportPathError("report resolves outside its configured root")
        return parsed, candidate, details

    def list(
        self,
        *,
        subject: str | None = None,
        limit: int = 30,
        now: datetime | None = None,
    ) -> list[dict[str, object]]:
        if type(limit) is not int or not 1 <= limit <= 80:
            raise ReportValidationError("report list limit must be between 1 and 80")
        normalized_subject = self._subject(subject)
        reference = _utc_now(now)
        if not self._root.is_dir():
            return []
        rows: list[dict[str, object]] = []
        try:
            candidates = list(self._root.iterdir())
        except OSError as exc:
            raise ReportPathError("report root is unavailable") from exc
        for candidate in candidates:
            try:
                parsed, checked, details = self._checked_existing(candidate.name)
            except (OSError, ReportValidationError, ReportPathError, ReportNotFoundError):
                continue
            if checked != candidate or details.st_size > self._max_bytes:
                continue
            if parsed.created_at + self._ttl <= reference:
                continue
            if normalized_subject is not None and parsed.subject != normalized_subject:
                continue
            rows.append(self._metadata(parsed, details, reference))
        rows.sort(key=lambda item: (str(item["created_at"]), str(item["report_id"])), reverse=True)
        return rows[:limit]

    def read(
        self,
        report_id: str | ReportId,
        *,
        now: datetime | None = None,
    ) -> dict[str, object]:
        reference = _utc_now(now)
        parsed, candidate, details = self._checked_existing(report_id)
        metadata = self._metadata(parsed, details, reference)
        if parsed.created_at + self._ttl <= reference:
            raise ReportExpiredError("report does not exist or has expired")
        if details.st_size > self._max_bytes:
            raise ReportValidationError("stored report exceeds the configured size limit")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(candidate, flags)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or opened.st_size > self._max_bytes:
                raise ReportPathError("report changed during read")
            payload = bytearray()
            while True:
                chunk = os.read(descriptor, min(65536, self._max_bytes + 1 - len(payload)))
                if not chunk:
                    break
                payload.extend(chunk)
                if len(payload) > self._max_bytes:
                    raise ReportValidationError("stored report exceeds the configured size limit")
        finally:
            os.close(descriptor)
        try:
            markdown = bytes(payload).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ReportValidationError("stored report is not valid UTF-8") from exc
        return {**metadata, "ok": True, "markdown": markdown}


__all__ = ["ReportReadFacade"]
