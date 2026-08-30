"""Append-only audit journal for prospective provider acquisition attempts."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime, time
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
from typing import Any, BinaryIO, Iterator
from uuid import uuid4
from zoneinfo import ZoneInfo

from quantify.data.exchange_calendar_preflight import build_exchange_calendar_preflight
from quantify.data.prospective_daily_acquisition import ProspectiveDailyAcquisition

ATTEMPT_LEDGER_FILENAME = "prospective_acquisition_attempts.jsonl"
ATTEMPT_REPORTS_DIRECTORY = "acquisition_attempts"
ATTEMPT_SCHEMA_VERSION = 1
MARKET_TIMEZONE = "Asia/Shanghai"
GENESIS_HASH = "0" * 64
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_EVENT_FIELDS = {
    "schema_version",
    "sequence",
    "event_type",
    "trial_id",
    "candidate",
    "market_date",
    "attempted_at_utc",
    "status",
    "source_vendor",
    "akshare_version",
    "minimum_success_ratio",
    "requested_symbols",
    "successful_symbols",
    "failed_symbols",
    "success_ratio",
    "row_count",
    "provider_routes",
    "failure_count",
    "csv_sha256",
    "frozen_symbol_fingerprint",
    "calendar_evidence_status",
    "calendar_session_status",
    "calendar_csv_sha256",
    "calendar_metadata_sha256",
    "quarantine_root",
    "report_relative_path",
    "report_sha256",
    "network_access",
    "broker_access",
    "execution_cache_write_allowed",
    "holdout_analysis_allowed",
    "live_trading_allowed",
    "hash_algorithm",
    "previous_hash",
    "event_hash",
}


class ProspectiveAcquisitionJournalError(ValueError):
    """Raised when an acquisition-attempt journal or binding is invalid."""


def record_prospective_acquisition_attempt(
    report: ProspectiveDailyAcquisition,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Retain one provider-attempt summary and append its hash-bound event."""
    _validate_recordable_report(report)
    root = Path(output_dir).resolve()
    if root != Path(report.quarantine_root).resolve():
        raise ProspectiveAcquisitionJournalError(
            "attempt output_dir does not match the preflight-bound quarantine root"
        )
    calendar_csv_sha256, calendar_metadata_sha256 = _calendar_binding(report)
    verify_prospective_acquisition_attempts(root)

    report_bytes = _canonical_json(report.to_dict())
    report_sha256 = hashlib.sha256(report_bytes).hexdigest()
    relative_path = Path(ATTEMPT_REPORTS_DIRECTORY) / (
        f"{report.market_date}_{report_sha256[:16]}.json"
    )
    _write_exact_file(root / relative_path, report_bytes, report_sha256)

    payload = report.to_dict()
    return _append_attempt_event(
        root / ATTEMPT_LEDGER_FILENAME,
        {
            "trial_id": report.trial_id,
            "candidate": report.candidate,
            "market_date": report.market_date,
            "attempted_at_utc": report.evaluated_at_utc,
            "status": report.status,
            "source_vendor": report.source_vendor,
            "akshare_version": report.akshare_version,
            "minimum_success_ratio": report.minimum_success_ratio,
            "requested_symbols": report.requested_symbols,
            "successful_symbols": report.successful_symbols,
            "failed_symbols": report.failed_symbols,
            "success_ratio": report.success_ratio,
            "row_count": report.row_count,
            "provider_routes": dict(sorted(report.provider_routes.items())),
            "failure_count": len(report.failures),
            "csv_sha256": report.csv_sha256,
            "frozen_symbol_fingerprint": report.frozen_symbol_fingerprint,
            "calendar_evidence_status": report.calendar_evidence_status,
            "calendar_session_status": report.calendar_session_status,
            "calendar_csv_sha256": calendar_csv_sha256,
            "calendar_metadata_sha256": calendar_metadata_sha256,
            "quarantine_root": str(root),
            "report_relative_path": relative_path.as_posix(),
            "report_sha256": report_sha256,
            "network_access": payload["network_access"],
            "broker_access": payload["broker_access"],
            "execution_cache_write_allowed": report.execution_cache_write_allowed,
            "holdout_analysis_allowed": report.holdout_analysis_allowed,
            "live_trading_allowed": report.live_trading_allowed,
        },
    )


def verify_prospective_acquisition_attempts(
    output_dir: str | Path,
) -> list[dict[str, Any]]:
    """Verify the attempt hash chain and every referenced immutable report."""
    root = Path(output_dir).resolve()
    events = _read_attempt_ledger(root / ATTEMPT_LEDGER_FILENAME)
    for line_number, event in enumerate(events, start=1):
        relative = Path(str(event["report_relative_path"]))
        report_path = root / relative
        try:
            report_bytes = report_path.read_bytes()
        except OSError as exc:
            raise ProspectiveAcquisitionJournalError(
                f"line {line_number}: referenced attempt report cannot be read: {exc}"
            ) from exc
        if not hmac.compare_digest(
            hashlib.sha256(report_bytes).hexdigest(),
            str(event["report_sha256"]),
        ):
            raise ProspectiveAcquisitionJournalError(
                f"line {line_number}: referenced attempt report hash mismatch"
            )
        report_payload = _load_report(report_bytes, line_number)
        _validate_report_binding(event, report_payload, line_number, root)
    return events


def _validate_recordable_report(report: ProspectiveDailyAcquisition) -> None:
    if report.status not in {"PASS", "BLOCK"}:
        raise ProspectiveAcquisitionJournalError(
            "only completed PASS/BLOCK provider attempts can be journaled"
        )
    if report.requested_symbols < 1 or report.fetch_allowed:
        raise ProspectiveAcquisitionJournalError(
            "journal input must be a completed provider attempt with fetch disabled"
        )
    payload = report.to_dict()
    if payload["network_access"] is not True:
        raise ProspectiveAcquisitionJournalError(
            "journal input must record that provider network access occurred"
        )
    if (
        report.execution_cache_write_allowed
        or report.holdout_analysis_allowed
        or report.live_trading_allowed
        or payload["broker_access"] is not False
    ):
        raise ProspectiveAcquisitionJournalError(
            "provider attempt cannot grant cache, analysis, broker, or live permissions"
        )


def _calendar_binding(report: ProspectiveDailyAcquisition) -> tuple[str, str]:
    if report.calendar_evidence_status == "MISSING":
        if report.calendar_preflight is not None or report.calendar_session_status != "UNREVIEWED":
            raise ProspectiveAcquisitionJournalError(
                "omitted calendar evidence has inconsistent acquisition state"
            )
        return "", ""
    retained = report.calendar_preflight
    if (
        report.calendar_evidence_status != "PASS"
        or report.calendar_session_status != "OPEN"
        or retained is None
    ):
        raise ProspectiveAcquisitionJournalError(
            "journaled provider attempt requires omitted or PASS/open calendar evidence"
        )
    fresh = build_exchange_calendar_preflight(
        retained.calendar_csv_path,
        retained.metadata_path,
        required_start_date=report.market_date,
        required_end_date=report.market_date,
    )
    session = next(
        (item for item in fresh.sessions if str(item["date"]) == report.market_date),
        None,
    )
    if (
        fresh.status != "PASS"
        or fresh.csv_sha256 != retained.csv_sha256
        or fresh.metadata_sha256 != retained.metadata_sha256
        or session is None
        or session.get("is_open") is not True
    ):
        raise ProspectiveAcquisitionJournalError(
            "reviewed calendar evidence changed before attempt journaling"
        )
    return retained.csv_sha256, retained.metadata_sha256


def _append_attempt_event(path: Path, event_body: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle, _file_lock(handle, exclusive=True):
        handle.seek(0)
        prior = handle.read()
        events = _parse_attempt_ledger(prior)
        event = {
            "schema_version": ATTEMPT_SCHEMA_VERSION,
            "sequence": len(events) + 1,
            "event_type": "provider_acquisition_attempt",
            **event_body,
            "hash_algorithm": "sha256",
            "previous_hash": events[-1]["event_hash"] if events else GENESIS_HASH,
        }
        event["event_hash"] = _event_hash(event)
        _validate_attempt_event(event, len(events) + 1, str(event["previous_hash"]))
        encoded = _canonical_json(event) + b"\n"
        handle.seek(0, os.SEEK_END)
        if handle.tell() != len(prior):
            raise ProspectiveAcquisitionJournalError(
                "acquisition-attempt ledger changed while append lock was held"
            )
        if handle.write(encoded) != len(encoded):  # pragma: no cover - filesystem failure
            raise OSError("short acquisition-attempt ledger append")
        handle.flush()
        os.fsync(handle.fileno())
        return event


def _read_attempt_ledger(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("rb") as handle, _file_lock(handle, exclusive=False):
            return _parse_attempt_ledger(handle.read())
    except FileNotFoundError:
        return []
    except ProspectiveAcquisitionJournalError:
        raise
    except OSError as exc:
        raise ProspectiveAcquisitionJournalError(
            f"acquisition-attempt ledger cannot be read: {exc}"
        ) from exc


def _parse_attempt_ledger(raw: bytes) -> list[dict[str, Any]]:
    if not raw:
        return []
    if not raw.endswith(b"\n"):
        raise ProspectiveAcquisitionJournalError("acquisition-attempt ledger is truncated")
    events: list[dict[str, Any]] = []
    previous_hash = GENESIS_HASH
    for line_number, raw_line in enumerate(raw[:-1].split(b"\n"), start=1):
        if not raw_line:
            raise ProspectiveAcquisitionJournalError(
                f"line {line_number}: blank ledger lines are prohibited"
            )
        payload = _load_json_object(raw_line, line_number, "event")
        if _canonical_json(payload) != raw_line:
            raise ProspectiveAcquisitionJournalError(
                f"line {line_number}: event is not canonical JSON"
            )
        _validate_attempt_event(payload, line_number, previous_hash)
        events.append(payload)
        previous_hash = str(payload["event_hash"])
    return events


def _validate_attempt_event(
    event: dict[str, Any],
    line_number: int,
    previous_hash: str,
) -> None:
    prefix = f"line {line_number}: "
    if set(event) != _EVENT_FIELDS:
        raise ProspectiveAcquisitionJournalError(prefix + "event fields differ from schema")
    if event["schema_version"] != ATTEMPT_SCHEMA_VERSION or event["sequence"] != line_number:
        raise ProspectiveAcquisitionJournalError(prefix + "schema or sequence is invalid")
    if (
        event["event_type"] != "provider_acquisition_attempt"
        or event["hash_algorithm"] != "sha256"
    ):
        raise ProspectiveAcquisitionJournalError(prefix + "event type or hash algorithm is invalid")
    if event["previous_hash"] != previous_hash or not _valid_hash(event["previous_hash"]):
        raise ProspectiveAcquisitionJournalError(prefix + "previous hash is invalid")
    if not _valid_hash(event["event_hash"]) or not hmac.compare_digest(
        str(event["event_hash"]), _event_hash(event)
    ):
        raise ProspectiveAcquisitionJournalError(prefix + "event hash mismatch")
    for field in ("trial_id", "candidate", "source_vendor", "akshare_version"):
        if not _clean_text(event[field]):
            raise ProspectiveAcquisitionJournalError(prefix + f"{field} is invalid")
    if event["source_vendor"] != "akshare":
        raise ProspectiveAcquisitionJournalError(prefix + "source vendor is invalid")
    market_date = _parsed_date(event["market_date"])
    attempted_at = _utc_datetime(event["attempted_at_utc"])
    if market_date is None or attempted_at is None:
        raise ProspectiveAcquisitionJournalError(prefix + "market date or attempt timestamp is invalid")
    market_attempted_at = attempted_at.astimezone(ZoneInfo(MARKET_TIMEZONE))
    if market_date > market_attempted_at.date() or (
        market_date == market_attempted_at.date()
        and market_attempted_at.time().replace(tzinfo=None) < time(15, 30)
    ):
        raise ProspectiveAcquisitionJournalError(
            prefix + "provider attempt precedes the requested market-date close buffer"
        )
    if event["status"] not in {"PASS", "BLOCK"}:
        raise ProspectiveAcquisitionJournalError(prefix + "status is invalid")
    requested = event["requested_symbols"]
    successful = event["successful_symbols"]
    failed = event["failed_symbols"]
    if (
        type(requested) is not int
        or requested < 1
        or type(successful) is not int
        or successful < 0
        or type(failed) is not int
        or failed < 0
        or successful + failed != requested
        or type(event["failure_count"]) is not int
        or event["failure_count"] != failed
        or type(event["row_count"]) is not int
        or event["row_count"] != successful
    ):
        raise ProspectiveAcquisitionJournalError(prefix + "symbol/failure/row counts are invalid")
    minimum = event["minimum_success_ratio"]
    ratio = event["success_ratio"]
    if (
        not _finite_number(minimum)
        or not 0 < float(minimum) <= 1
        or not _finite_number(ratio)
        or not math.isclose(float(ratio), successful / requested, abs_tol=1e-12)
    ):
        raise ProspectiveAcquisitionJournalError(prefix + "success ratio is invalid")
    should_pass = successful > 0 and float(ratio) >= float(minimum)
    if (event["status"] == "PASS") != should_pass:
        raise ProspectiveAcquisitionJournalError(prefix + "status disagrees with provider coverage")
    routes = event["provider_routes"]
    if (
        not isinstance(routes, dict)
        or any(not _clean_text(key) or type(value) is not int or value < 1 for key, value in routes.items())
        or sum(routes.values()) != successful
    ):
        raise ProspectiveAcquisitionJournalError(prefix + "provider route counts are invalid")
    csv_sha256 = event["csv_sha256"]
    if (successful > 0 and not _valid_hash(csv_sha256)) or (
        successful == 0 and csv_sha256 != ""
    ):
        raise ProspectiveAcquisitionJournalError(prefix + "CSV hash is invalid")
    if not _valid_hash(event["frozen_symbol_fingerprint"]):
        raise ProspectiveAcquisitionJournalError(prefix + "frozen symbol fingerprint is invalid")
    _validate_calendar_fields(event, prefix)
    if not _clean_text(event["quarantine_root"]):
        raise ProspectiveAcquisitionJournalError(prefix + "quarantine root is invalid")
    if not _valid_hash(event["report_sha256"]):
        raise ProspectiveAcquisitionJournalError(prefix + "report hash is invalid")
    relative = Path(str(event["report_relative_path"]))
    expected = Path(ATTEMPT_REPORTS_DIRECTORY) / (
        f"{event['market_date']}_{str(event['report_sha256'])[:16]}.json"
    )
    if relative.is_absolute() or ".." in relative.parts or relative != expected:
        raise ProspectiveAcquisitionJournalError(prefix + "report path is unsafe or inconsistent")
    if (
        event["network_access"] is not True
        or event["broker_access"] is not False
        or event["execution_cache_write_allowed"] is not False
        or event["holdout_analysis_allowed"] is not False
        or event["live_trading_allowed"] is not False
    ):
        raise ProspectiveAcquisitionJournalError(prefix + "safety-boundary flags are invalid")


def _validate_calendar_fields(event: dict[str, Any], prefix: str) -> None:
    evidence_status = event["calendar_evidence_status"]
    session_status = event["calendar_session_status"]
    csv_hash = event["calendar_csv_sha256"]
    metadata_hash = event["calendar_metadata_sha256"]
    omitted = (
        evidence_status == "MISSING"
        and session_status == "UNREVIEWED"
        and csv_hash == ""
        and metadata_hash == ""
    )
    reviewed = (
        evidence_status == "PASS"
        and session_status == "OPEN"
        and _valid_hash(csv_hash)
        and _valid_hash(metadata_hash)
    )
    if not omitted and not reviewed:
        raise ProspectiveAcquisitionJournalError(prefix + "calendar evidence fields are invalid")


def _validate_report_binding(
    event: dict[str, Any],
    report: dict[str, Any],
    line_number: int,
    journal_root: Path,
) -> None:
    expected = {
        "artifact_type": "prospective_daily_acquisition",
        "status": event["status"],
        "trial_id": event["trial_id"],
        "candidate": event["candidate"],
        "market_date": event["market_date"],
        "evaluated_at_utc": event["attempted_at_utc"],
        "minimum_success_ratio": event["minimum_success_ratio"],
        "requested_symbols": event["requested_symbols"],
        "successful_symbols": event["successful_symbols"],
        "failed_symbols": event["failed_symbols"],
        "success_ratio": event["success_ratio"],
        "row_count": event["row_count"],
        "provider_routes": event["provider_routes"],
        "csv_sha256": event["csv_sha256"],
        "frozen_symbol_fingerprint": event["frozen_symbol_fingerprint"],
        "calendar_evidence_status": event["calendar_evidence_status"],
        "calendar_session_status": event["calendar_session_status"],
        "quarantine_root": event["quarantine_root"],
        "source_vendor": event["source_vendor"],
        "akshare_version": event["akshare_version"],
        "network_access": True,
        "broker_access": False,
        "execution_cache_write_allowed": False,
        "holdout_analysis_allowed": False,
        "live_trading_allowed": False,
    }
    if any(report.get(key) != value for key, value in expected.items()):
        raise ProspectiveAcquisitionJournalError(
            f"line {line_number}: immutable report does not match its ledger event"
        )
    if Path(str(report["quarantine_root"])).resolve() != journal_root:
        raise ProspectiveAcquisitionJournalError(
            f"line {line_number}: immutable report quarantine root does not match journal root"
        )
    calendar = report.get("calendar_preflight")
    if event["calendar_evidence_status"] == "MISSING":
        calendar_matches = calendar is None
    else:
        calendar_matches = (
            isinstance(calendar, dict)
            and isinstance(calendar.get("calendar_csv"), dict)
            and isinstance(calendar.get("metadata_json"), dict)
            and calendar["calendar_csv"].get("sha256")
            == event["calendar_csv_sha256"]
            and calendar["metadata_json"].get("sha256")
            == event["calendar_metadata_sha256"]
        )
    if not calendar_matches:
        raise ProspectiveAcquisitionJournalError(
            f"line {line_number}: immutable report calendar binding is inconsistent"
        )
    failures = report.get("failures")
    if not isinstance(failures, list) or len(failures) != event["failure_count"]:
        raise ProspectiveAcquisitionJournalError(
            f"line {line_number}: immutable report failure count is inconsistent"
        )
    if "csv_bytes" in report:
        raise ProspectiveAcquisitionJournalError(
            f"line {line_number}: immutable report must not retain raw CSV bytes"
        )


def _load_report(raw: bytes, line_number: int) -> dict[str, Any]:
    payload = _load_json_object(raw, line_number, "report")
    if _canonical_json(payload) != raw:
        raise ProspectiveAcquisitionJournalError(
            f"line {line_number}: referenced attempt report is not canonical JSON"
        )
    return payload


def _load_json_object(raw: bytes, line_number: int, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ProspectiveAcquisitionJournalError(
            f"line {line_number}: malformed {label} JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ProspectiveAcquisitionJournalError(
            f"line {line_number}: {label} must be a JSON object"
        )
    return payload


def _write_exact_file(path: Path, payload: bytes, expected_sha256: str) -> None:
    if path.exists():
        if not path.is_file() or _file_sha256(path) != expected_sha256:
            raise ProspectiveAcquisitionJournalError(
                f"attempt report already exists with different bytes: {path}"
            )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            if handle.write(payload) != len(payload):  # pragma: no cover - filesystem failure
                raise OSError("short acquisition-attempt report write")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _event_hash(event: dict[str, Any]) -> str:
    payload = dict(event)
    payload.pop("event_hash", None)
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON key {key!r}")
        payload[key] = value
    return payload


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value!r}")


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and _HASH_PATTERN.fullmatch(value) is not None


def _parsed_date(value: Any) -> date | None:
    if not isinstance(value, str) or _DATE_PATTERN.fullmatch(value) is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _utc_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        return None
    return parsed


def _clean_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


def _finite_number(value: Any) -> bool:
    return type(value) in {int, float} and math.isfinite(float(value))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def _file_lock(handle: BinaryIO, *, exclusive: bool) -> Iterator[None]:
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
    except ImportError:  # pragma: no cover - unsupported platform
        yield
        return
    mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    fcntl.flock(handle.fileno(), mode)
    try:
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
