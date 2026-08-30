"""Strict local preflight for reviewed A-share exchange-calendar evidence."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Literal
from zoneinfo import ZoneInfo

CalendarStatus = Literal["PASS", "BLOCK"]

ARTIFACT_TYPE = "reviewed_exchange_calendar"
SCHEMA_VERSION = 1
EXCHANGE_SCOPE = "CN_A_SHARE"
MARKET_TIMEZONE = "Asia/Shanghai"
_HASH_PATTERN = re.compile(r"[0-9a-fA-F]{64}\Z")
_ISO_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_PLACEHOLDERS = {
    "",
    "missing",
    "n/a",
    "na",
    "none",
    "not provided",
    "not_provided",
    "tbd",
    "todo",
    "unknown",
}


@dataclass(frozen=True, slots=True)
class CalendarEvidenceCheck:
    code: str
    status: CalendarStatus
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "status": self.status, "message": self.message}


@dataclass(frozen=True, slots=True)
class ExchangeCalendarPreflight:
    artifact_type: str
    schema_version: int
    status: CalendarStatus
    evaluated_at_utc: str
    calendar_csv_path: str
    metadata_path: str
    csv_sha256: str
    metadata_sha256: str
    required_start_date: str
    required_end_date: str
    declared_start_date: str
    declared_end_date: str
    observed_start_date: str
    observed_end_date: str
    calendar_day_count: int
    open_session_count: int
    closed_day_count: int
    sessions: tuple[dict[str, Any], ...]
    metadata: dict[str, Any]
    checks: tuple[CalendarEvidenceCheck, ...]
    blockers: tuple[str, ...]
    next_actions: tuple[str, ...]
    prohibited_actions: tuple[str, ...]

    @property
    def sufficient(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "schema_version": self.schema_version,
            "operation": "read_only_reviewed_exchange_calendar_preflight",
            "network_access": False,
            "broker_access": False,
            "status": self.status,
            "sufficient": self.sufficient,
            "evaluated_at_utc": self.evaluated_at_utc,
            "calendar_csv": {
                "path": self.calendar_csv_path,
                "sha256": self.csv_sha256,
                "observed_start_date": self.observed_start_date,
                "observed_end_date": self.observed_end_date,
                "calendar_day_count": self.calendar_day_count,
                "open_session_count": self.open_session_count,
                "closed_day_count": self.closed_day_count,
            },
            "metadata_json": {
                "path": self.metadata_path,
                "sha256": self.metadata_sha256,
            },
            "required_coverage": {
                "start_date": self.required_start_date,
                "end_date": self.required_end_date,
            },
            "declared_coverage": {
                "start_date": self.declared_start_date,
                "end_date": self.declared_end_date,
            },
            "sessions": list(self.sessions),
            "metadata": self.metadata,
            "checks": [item.to_dict() for item in self.checks],
            "blockers": list(self.blockers),
            "next_actions": list(self.next_actions),
            "prohibited_actions": list(self.prohibited_actions),
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Exchange Calendar Preflight: {self.status}",
            "",
            f"- Calendar CSV: `{self.calendar_csv_path}`",
            f"- CSV SHA-256: `{self.csv_sha256 or 'unavailable'}`",
            f"- Metadata: `{self.metadata_path}`",
            f"- Required coverage: `{self.required_start_date}` to `{self.required_end_date}`",
            f"- Declared coverage: `{self.declared_start_date or 'unavailable'}` to `{self.declared_end_date or 'unavailable'}`",
            f"- Observed coverage: `{self.observed_start_date or 'unavailable'}` to `{self.observed_end_date or 'unavailable'}`",
            f"- Calendar/open/closed rows: `{self.calendar_day_count}` / `{self.open_session_count}` / `{self.closed_day_count}`",
            "",
            "This is a read-only evidence preflight. PASS cannot approve a strategy, open "
            "the holdout, write an execution cache, or authorize trading.",
            "",
            "## Checks",
            "",
        ]
        lines.extend(
            f"- `{item.status}` `{item.code}`: {item.message}" for item in self.checks
        )
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- {item}" for item in self.blockers or ("None.",))
        lines.extend(["", "## Next Actions", ""])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Prohibited Actions", ""])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        lines.append("")
        return "\n".join(lines)


def build_exchange_calendar_preflight(
    calendar_csv: str | Path,
    metadata_json: str | Path,
    *,
    required_start_date: str,
    required_end_date: str,
) -> ExchangeCalendarPreflight:
    """Validate exact daily open/closed evidence without network or mutation."""
    evaluated_at = _runtime_now()
    csv_path = Path(calendar_csv)
    metadata_path = Path(metadata_json)
    checks: list[CalendarEvidenceCheck] = []

    required_start = _iso_date(required_start_date)
    required_end = _iso_date(required_end_date)
    required_ready = (
        required_start is not None
        and required_end is not None
        and required_start <= required_end
    )
    _check(
        checks,
        "REQUIRED_COVERAGE",
        required_ready,
        "Required calendar coverage is a valid closed date range."
        if required_ready
        else "Required start/end must be valid YYYY-MM-DD values in ascending order.",
    )

    csv_bytes, csv_error = _read_file(csv_path, "calendar CSV")
    metadata_bytes, metadata_error = _read_file(metadata_path, "calendar metadata")
    csv_sha256 = hashlib.sha256(csv_bytes).hexdigest() if csv_bytes is not None else ""
    metadata_sha256 = (
        hashlib.sha256(metadata_bytes).hexdigest() if metadata_bytes is not None else ""
    )
    _check(
        checks,
        "CALENDAR_CSV_READABLE",
        not csv_error,
        "Calendar CSV exists and is readable." if not csv_error else csv_error,
    )
    _check(
        checks,
        "CALENDAR_METADATA_READABLE",
        not metadata_error,
        "Calendar metadata exists and is readable." if not metadata_error else metadata_error,
    )

    metadata, metadata_parse_error = _parse_metadata(metadata_bytes)
    _check(
        checks,
        "METADATA_JSON_CONTRACT",
        not metadata_parse_error,
        "Metadata is a strict UTF-8 JSON object without duplicate keys."
        if not metadata_parse_error
        else metadata_parse_error,
    )
    _validate_metadata_identity(metadata, checks)
    declared_start = _iso_date(metadata.get("coverage_start_date"))
    declared_end = _iso_date(metadata.get("coverage_end_date"))
    declared_ready = (
        declared_start is not None
        and declared_end is not None
        and declared_start <= declared_end
    )
    _check(
        checks,
        "DECLARED_COVERAGE",
        declared_ready,
        "Metadata declares a valid closed coverage range."
        if declared_ready
        else "Metadata coverage_start_date/coverage_end_date is invalid.",
    )
    coverage_ready = (
        declared_ready
        and required_ready
        and declared_start is not None
        and declared_end is not None
        and required_start is not None
        and required_end is not None
        and declared_start <= required_start
        and declared_end >= required_end
    )
    _check(
        checks,
        "REQUIRED_COVERAGE_SPANNED",
        coverage_ready,
        "Declared calendar coverage spans the required range."
        if coverage_ready
        else "Declared calendar coverage does not span the required range.",
    )

    exported_at = _aware_datetime(metadata.get("source_exported_at"))
    reviewed_at = _aware_datetime(metadata.get("reviewed_at"))
    timestamps_ready = (
        exported_at is not None
        and reviewed_at is not None
        and exported_at <= reviewed_at <= evaluated_at
    )
    _check(
        checks,
        "SOURCE_REVIEW_TIMESTAMPS",
        timestamps_ready,
        "Export/review timestamps are timezone-aware, ordered, and not future-dated."
        if timestamps_ready
        else "Export/review timestamps must be timezone-aware, ordered, and not future-dated.",
    )
    export_covers = (
        exported_at is not None
        and declared_end is not None
        and declared_end
        <= exported_at.astimezone(ZoneInfo(MARKET_TIMEZONE)).date()
    )
    _check(
        checks,
        "EXPORT_COVERS_DECLARED_END",
        export_covers,
        "Declared coverage end is no later than the source export date."
        if export_covers
        else "Declared coverage end cannot be later than the source export date.",
    )
    hash_ready = (
        bool(csv_sha256)
        and isinstance(metadata.get("file_sha256"), str)
        and metadata["file_sha256"].lower() == csv_sha256
    )
    _check(
        checks,
        "CSV_SHA256_BINDING",
        hash_ready,
        "Calendar CSV SHA-256 matches reviewed metadata."
        if hash_ready
        else "Calendar CSV SHA-256 does not match metadata file_sha256.",
    )

    sessions, csv_errors = _parse_calendar_csv(csv_bytes)
    _check(
        checks,
        "CALENDAR_CSV_CONTRACT",
        not csv_errors,
        "Calendar CSV dates and strict is_open values are valid."
        if not csv_errors
        else "; ".join(csv_errors),
    )
    observed_dates = [_iso_date(str(item["date"])) for item in sessions]
    observed = [item for item in observed_dates if item is not None]
    observed_start = min(observed) if observed else None
    observed_end = max(observed) if observed else None
    exact_coverage = _exact_daily_coverage(sessions, declared_start, declared_end)
    _check(
        checks,
        "EXACT_DAILY_COVERAGE",
        exact_coverage,
        "CSV contains exactly one row for every natural day in declared coverage."
        if exact_coverage
        else "CSV must contain exactly one row for every natural day in declared coverage.",
    )
    weekend_ready = not any(
        _iso_date(str(item["date"])) is not None
        and _iso_date(str(item["date"])).weekday() >= 5  # type: ignore[union-attr]
        and item["is_open"] is True
        for item in sessions
    )
    _check(
        checks,
        "WEEKEND_CLOSED",
        weekend_ready,
        "All Saturday/Sunday rows are closed."
        if weekend_ready
        else "A-share Saturday/Sunday rows cannot be marked open.",
    )
    open_count = sum(item["is_open"] is True for item in sessions)
    _check(
        checks,
        "OPEN_SESSIONS_PRESENT",
        open_count > 0,
        f"Calendar contains {open_count} open session(s)."
        if open_count > 0
        else "Calendar must contain at least one open session.",
    )

    blockers = tuple(dict.fromkeys(item.message for item in checks if item.status == "BLOCK"))
    status: CalendarStatus = "BLOCK" if blockers else "PASS"
    return ExchangeCalendarPreflight(
        artifact_type="exchange_calendar_preflight",
        schema_version=1,
        status=status,
        evaluated_at_utc=evaluated_at.replace(microsecond=0).isoformat(),
        calendar_csv_path=str(csv_path),
        metadata_path=str(metadata_path),
        csv_sha256=csv_sha256,
        metadata_sha256=metadata_sha256,
        required_start_date=required_start_date,
        required_end_date=required_end_date,
        declared_start_date=declared_start.isoformat() if declared_start else "",
        declared_end_date=declared_end.isoformat() if declared_end else "",
        observed_start_date=observed_start.isoformat() if observed_start else "",
        observed_end_date=observed_end.isoformat() if observed_end else "",
        calendar_day_count=len(sessions),
        open_session_count=open_count,
        closed_day_count=len(sessions) - open_count,
        sessions=tuple(sessions),
        metadata=metadata,
        checks=tuple(checks),
        blockers=blockers,
        next_actions=(
            ("Use this reviewed calendar in prospective collection continuity.",)
            if status == "PASS"
            else (
                "Provide a complete natural-day calendar and real reviewed metadata; do not create placeholder closure evidence.",
            )
        ),
        prohibited_actions=(
            "Do not treat calendar PASS as source-QA, strategy, paper, or live-trading approval.",
            "Do not infer missing dates as market closures; every natural day must have an explicit row.",
            "Do not edit CSV bytes after reviewer hash binding.",
            "Do not connect this workflow to a broker or generate orders.",
        ),
    )


def write_exchange_calendar_preflight(
    report: ExchangeCalendarPreflight,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    json_path = root / "exchange_calendar_preflight.json"
    markdown_path = root / "exchange_calendar_preflight.md"
    protected = {Path(report.calendar_csv_path).resolve(), Path(report.metadata_path).resolve()}
    if json_path.resolve() in protected or markdown_path.resolve() in protected:
        raise OSError("calendar preflight output must not overwrite external evidence inputs")
    root.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, allow_nan=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(report.to_markdown(), encoding="utf-8")
    return root


def _validate_metadata_identity(
    metadata: dict[str, Any],
    checks: list[CalendarEvidenceCheck],
) -> None:
    expected = {
        "artifact_type": ARTIFACT_TYPE,
        "schema_version": SCHEMA_VERSION,
        "exchange_scope": EXCHANGE_SCOPE,
        "timezone": MARKET_TIMEZONE,
        "date_column": "date",
        "is_open_column": "is_open",
    }
    identity_ready = all(metadata.get(key) == value for key, value in expected.items())
    _check(
        checks,
        "METADATA_IDENTITY",
        identity_ready,
        "Metadata artifact, schema, exchange, timezone, and column identities match."
        if identity_ready
        else "Metadata identity fields do not match the reviewed A-share calendar contract.",
    )
    required_text = (
        "source_vendor",
        "source_dataset",
        "source_exported_at",
        "reviewed_by",
        "reviewed_at",
        "file_sha256",
    )
    provenance_ready = all(
        isinstance(metadata.get(field), str)
        and not _placeholder(str(metadata[field]))
        for field in required_text
    ) and isinstance(metadata.get("file_sha256"), str) and bool(
        _HASH_PATTERN.fullmatch(str(metadata["file_sha256"]))
    )
    _check(
        checks,
        "METADATA_PROVENANCE",
        provenance_ready,
        "Source, dataset, reviewer, timestamps, and SHA-256 are concrete."
        if provenance_ready
        else "Metadata source/reviewer/hash provenance is missing, placeholder, or malformed.",
    )


def _parse_calendar_csv(raw: bytes | None) -> tuple[list[dict[str, Any]], list[str]]:
    if raw is None:
        return [], []
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], ["Calendar CSV must be UTF-8 or UTF-8 with BOM."]
    try:
        table = list(csv.reader(text.splitlines()))
    except csv.Error as exc:
        return [], [f"Calendar CSV parse failed: {exc}."]
    if not table:
        return [], ["Calendar CSV is empty."]
    header = [item.strip() for item in table[0]]
    errors: list[str] = []
    if len(header) != len(set(header)):
        errors.append("Calendar CSV contains duplicate headers.")
    if header != ["date", "is_open"]:
        errors.append("Calendar CSV header must be exactly: date,is_open.")
    if errors:
        return [], errors
    date_index = header.index("date")
    open_index = header.index("is_open")
    sessions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row_number, row in enumerate(table[1:], start=2):
        if len(row) != len(header):
            errors.append(f"Row {row_number} does not match header width.")
            continue
        date_text = row[date_index].strip()
        open_text = row[open_index].strip()
        if _iso_date(date_text) is None:
            errors.append(f"Row {row_number} date must be YYYY-MM-DD.")
            continue
        if date_text in seen:
            errors.append(f"Row {row_number} duplicates date {date_text}.")
            continue
        seen.add(date_text)
        if open_text not in {"0", "1"}:
            errors.append(f"Row {row_number} is_open must be exactly 0 or 1.")
            continue
        sessions.append({"date": date_text, "is_open": open_text == "1"})
    sessions.sort(key=lambda item: str(item["date"]))
    return sessions, list(dict.fromkeys(errors))


def _exact_daily_coverage(
    sessions: list[dict[str, Any]],
    declared_start: date | None,
    declared_end: date | None,
) -> bool:
    if declared_start is None or declared_end is None or declared_end < declared_start:
        return False
    expected: list[str] = []
    current = declared_start
    while current <= declared_end:
        expected.append(current.isoformat())
        current += timedelta(days=1)
    return [str(item["date"]) for item in sessions] == expected


def _parse_metadata(raw: bytes | None) -> tuple[dict[str, Any], str]:
    if raw is None:
        return {}, ""
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return {}, f"Calendar metadata JSON is invalid: {exc}."
    if not isinstance(payload, dict):
        return {}, "Calendar metadata root must be an object."
    return payload, ""


def _read_file(path: Path, label: str) -> tuple[bytes | None, str]:
    try:
        if not path.is_file():
            return None, f"Required {label} is missing or not a file: {path}."
        return path.read_bytes(), ""
    except OSError as exc:
        return None, f"Required {label} cannot be read: {path}: {exc}."


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON key {key!r}")
        payload[key] = value
    return payload


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value!r}")


def _check(
    checks: list[CalendarEvidenceCheck],
    code: str,
    passed: bool,
    message: str,
) -> None:
    checks.append(CalendarEvidenceCheck(code, "PASS" if passed else "BLOCK", message))


def _placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in _PLACEHOLDERS or normalized.startswith("<")


def _iso_date(value: Any) -> date | None:
    if not isinstance(value, str) or not _ISO_DATE_PATTERN.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _aware_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _runtime_now() -> datetime:
    return datetime.now(UTC)
