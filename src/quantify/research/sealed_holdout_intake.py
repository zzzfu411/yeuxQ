"""Retain prospective daily bars without opening the sealed holdout.

This quarantine intake preserves exact CSV bytes and an append-only hash chain.
It never writes the execution cache, calculates candidate results, upgrades
source QA, or authorizes paper/live trading.
"""

from __future__ import annotations

from contextlib import contextmanager
import csv
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time
import hashlib
import hmac
import io
import json
import math
import os
from pathlib import Path
import re
from typing import Any, BinaryIO, Iterator, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd

from quantify.data.provenance import logical_bar_fingerprint
from quantify.research.prospective_trial_packet import (
    ProspectiveTrialPacketVerification,
    build_prospective_trial_packet_verification,
)
from quantify.research.trial_registry import (
    PreregistrationEvent,
    ResultEvent,
    TrialRegistryError,
    verify_registry,
)

IntakeStatus = Literal["PASS", "BLOCK"]

MARKET_TIMEZONE = "Asia/Shanghai"
LEDGER_FILENAME = "sealed_holdout_collection.jsonl"
LEDGER_SCHEMA_VERSION = 1
GENESIS_HASH = "0" * 64
REQUIRED_COLUMNS = ("symbol", "date", "open", "high", "low", "close", "volume", "amount")
EVENT_FIELDS = {
    "schema_version",
    "sequence",
    "event_type",
    "trial_id",
    "candidate",
    "market_date",
    "source_vendor",
    "source_reference",
    "source_exported_at",
    "price_adjustment",
    "raw_filename",
    "raw_sha256",
    "canonical_bar_fingerprint",
    "row_count",
    "symbol_count",
    "retained_relative_path",
    "evidence_role",
    "received_at_utc",
    "hash_algorithm",
    "previous_hash",
    "event_hash",
}
PROHIBITED_ACTIONS = (
    "Do not use quarantined rows as source-QA, PIT-universe, benchmark, strategy, paper, or live evidence.",
    "Do not load quarantined rows into the execution cache until reviewed source QA and guarded replay pass.",
    "Do not calculate, inspect, rank, tune, or publish candidate results during the sealed holdout.",
    "Do not replace an already retained market date with a different file or rewrite the collection ledger.",
    "Do not generate or submit broker orders from this workflow.",
)
_SYMBOL_PATTERN = re.compile(r"\d{6}\Z")
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_PLACEHOLDERS = {
    "",
    "missing",
    "na",
    "n/a",
    "none",
    "not provided",
    "not_provided",
    "tbd",
    "todo",
    "unknown",
}


class SealedHoldoutIntakeError(ValueError):
    """The quarantine intake or collection ledger cannot be trusted."""


@dataclass(frozen=True, slots=True)
class IntakeCheck:
    code: str
    status: IntakeStatus
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "status": self.status, "message": self.message}


@dataclass(frozen=True, slots=True)
class SealedHoldoutIntakeReport:
    artifact_type: str
    schema_version: int
    status: IntakeStatus
    evaluated_at_utc: str
    evaluated_market_date: str
    market_timezone: str
    trial_id: str
    candidate: str
    market_date: str
    source_vendor: str
    source_reference: str
    source_exported_at: str
    price_adjustment: str
    input_path: str
    raw_sha256: str
    canonical_bar_fingerprint: str
    row_count: int
    symbol_count: int
    ledger_path: str
    retained_path: str
    ledger_event: dict[str, Any] | None
    existing_event: dict[str, Any] | None
    idempotent: bool
    retention_allowed: bool
    execution_cache_write_allowed: bool
    holdout_analysis_allowed: bool
    promotion_eligible: bool
    paper_trading_allowed: bool
    live_trading_allowed: bool
    checks: tuple[IntakeCheck, ...]
    blockers: tuple[str, ...]
    next_actions: tuple[str, ...]
    prohibited_actions: tuple[str, ...]
    packet_verification: ProspectiveTrialPacketVerification

    @property
    def retained(self) -> bool:
        return bool(self.retained_path and (self.ledger_event or self.existing_event))

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "schema_version": self.schema_version,
            "operation": "sealed_holdout_raw_csv_quarantine",
            "network_access": False,
            "broker_access": False,
            "status": self.status,
            "evaluated_at_utc": self.evaluated_at_utc,
            "evaluated_market_date": self.evaluated_market_date,
            "market_timezone": self.market_timezone,
            "trial_id": self.trial_id,
            "candidate": self.candidate,
            "market_date": self.market_date,
            "source_declaration": {
                "review_status": "NOT_EVALUATED",
                "source_vendor": self.source_vendor,
                "source_reference": self.source_reference,
                "source_exported_at": self.source_exported_at,
                "price_adjustment": self.price_adjustment,
            },
            "input": {
                "path": self.input_path,
                "raw_sha256": self.raw_sha256,
                "canonical_bar_fingerprint": self.canonical_bar_fingerprint,
                "row_count": self.row_count,
                "symbol_count": self.symbol_count,
            },
            "ledger_path": self.ledger_path,
            "retained_path": self.retained_path,
            "ledger_event": self.ledger_event,
            "existing_event": self.existing_event,
            "idempotent": self.idempotent,
            "retention_allowed": self.retention_allowed,
            "retained": self.retained,
            "execution_cache_write_allowed": self.execution_cache_write_allowed,
            "holdout_analysis_allowed": self.holdout_analysis_allowed,
            "promotion_eligible": self.promotion_eligible,
            "paper_trading_allowed": self.paper_trading_allowed,
            "live_trading_allowed": self.live_trading_allowed,
            "checks": [item.to_dict() for item in self.checks],
            "blockers": list(self.blockers),
            "next_actions": list(self.next_actions),
            "prohibited_actions": list(self.prohibited_actions),
            "packet_verification": self.packet_verification.to_dict(),
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Sealed Holdout Intake: {self.status}",
            "",
            f"- Trial: `{self.trial_id or 'unavailable'}`",
            f"- Candidate: `{self.candidate or 'unavailable'}`",
            f"- Market date: `{self.market_date or 'unavailable'}`",
            f"- Evaluated market date: `{self.evaluated_market_date}` ({self.market_timezone})",
            f"- Raw SHA-256: `{self.raw_sha256 or 'unavailable'}`",
            f"- Canonical bar fingerprint: `{self.canonical_bar_fingerprint or 'unavailable'}`",
            f"- Rows / symbols: `{self.row_count}` / `{self.symbol_count}`",
            f"- Retention allowed: `{self.retention_allowed}`",
            f"- Retained: `{self.retained}`",
            f"- Idempotent replay: `{self.idempotent}`",
            f"- Execution-cache write allowed: `{self.execution_cache_write_allowed}`",
            f"- Holdout analysis allowed: `{self.holdout_analysis_allowed}`",
            f"- Promotion eligible: `{self.promotion_eligible}`",
            f"- Paper/live allowed: `{self.paper_trading_allowed}` / `{self.live_trading_allowed}`",
            "",
            "A PASS here means only that exact raw bytes were eligible for immutable quarantine. "
            "Source identity and usage rights remain NOT_EVALUATED.",
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


def build_sealed_holdout_intake(
    *,
    packet_dir: str | Path,
    trial_registry_path: str | Path,
    daily_bars_csv: str | Path,
    output_dir: str | Path,
    source_vendor: str,
    source_reference: str,
    source_exported_at: str,
    price_adjustment: str,
    workspace_root: str | Path | None = None,
) -> SealedHoldoutIntakeReport:
    """Validate one daily CSV for quarantine without writing any evidence."""
    root = _workspace_root(workspace_root)
    packet_root = _resolve_path(packet_dir, root)
    registry_path = _resolve_path(trial_registry_path, root)
    input_path = _resolve_path(daily_bars_csv, root)
    output_root = _resolve_path(output_dir, root)
    ledger_path = output_root / LEDGER_FILENAME
    evaluated_at = _runtime_now()
    market_now = evaluated_at.astimezone(ZoneInfo(MARKET_TIMEZONE))

    packet, packet_error = _load_json_object(packet_root / "prospective_trial_packet.json")
    verification = build_prospective_trial_packet_verification(
        packet_root,
        registry_path,
        workspace_root=root,
    )
    trial_id = _text(packet.get("trial_id"))
    candidate = _text(packet.get("candidate"))
    boundaries = packet.get("boundaries") if isinstance(packet.get("boundaries"), dict) else {}
    test_start = _boundary_date(boundaries, "test", "start")
    test_end = _boundary_date(boundaries, "test", "end")
    frozen_adjustment = _frozen_adjustment(packet)

    checks: list[IntakeCheck] = []
    _check(
        checks,
        "PACKET_INTEGRITY",
        not packet_error and verification.status == "PASS",
        "Frozen packet, code, config, prefix, and trial-registry binding verify."
        if not packet_error and verification.status == "PASS"
        else "Frozen packet integrity or trial-registry binding does not verify.",
    )

    result_count, registry_error = _terminal_result_count(registry_path, trial_id)
    _check(
        checks,
        "TERMINAL_RESULT_ABSENT",
        not registry_error and result_count == 0,
        "No terminal result exists for this trial."
        if not registry_error and result_count == 0
        else _terminal_result_message(result_count, registry_error),
    )

    source_vendor = source_vendor.strip()
    source_reference = source_reference.strip()
    source_fields_ready = not _placeholder(source_vendor) and not _placeholder(source_reference)
    _check(
        checks,
        "SOURCE_DECLARATION_PRESENT",
        source_fields_ready,
        "Source vendor and retained source reference are present as unreviewed declarations."
        if source_fields_ready
        else "Source vendor and source reference must be concrete, non-placeholder declarations.",
    )
    source_exported_at = source_exported_at.strip()
    exported_at = _aware_datetime(source_exported_at)
    export_ready = exported_at is not None and exported_at <= evaluated_at
    _check(
        checks,
        "SOURCE_EXPORT_TIMESTAMP",
        export_ready,
        "Source export timestamp is timezone-aware and not future-dated."
        if export_ready
        else "Source export timestamp must include a UTC offset and cannot be future-dated.",
    )
    adjustment = price_adjustment.strip().lower()
    adjustment_ready = adjustment in {"raw", "qfq", "hfq"} and (
        not frozen_adjustment or adjustment == frozen_adjustment
    )
    _check(
        checks,
        "PRICE_ADJUSTMENT_MATCH",
        adjustment_ready,
        f"Declared adjustment {adjustment!r} matches the frozen configuration."
        if adjustment_ready
        else (
            "Price adjustment must be raw/qfq/hfq and match the frozen configuration; "
            f"declared={adjustment or 'missing'!r}, frozen={frozen_adjustment or 'missing'!r}."
        ),
    )

    raw_bytes, file_error = _read_bytes(input_path)
    raw_sha256 = hashlib.sha256(raw_bytes).hexdigest() if raw_bytes is not None else ""
    rows, csv_errors = _validate_daily_csv(raw_bytes)
    market_dates = sorted({row[1] for row in rows})
    market_date = market_dates[0] if len(market_dates) == 1 else ""
    canonical_fingerprint = logical_bar_fingerprint(
        sorted(rows, key=lambda row: (str(row[0]), str(row[1])))
    ) if rows and not csv_errors else ""
    file_ready = raw_bytes is not None and not file_error and not csv_errors
    _check(
        checks,
        "DAILY_CSV_CONTRACT",
        file_ready,
        "Daily CSV has canonical columns, one market date, unique symbols, and valid OHLCVA rows."
        if file_ready
        else "; ".join([item for item in (file_error, *csv_errors) if item]),
    )

    observed_date = _iso_date(market_date)
    boundary_ready = (
        observed_date is not None
        and test_start is not None
        and test_end is not None
        and test_start <= observed_date <= test_end
    )
    _check(
        checks,
        "REGISTERED_HOLDOUT_DATE",
        boundary_ready,
        "CSV market date is inside the frozen prospective test interval."
        if boundary_ready
        else _boundary_message(observed_date, test_start, test_end),
    )
    weekday_ready = observed_date is not None and observed_date.weekday() < 5
    _check(
        checks,
        "MARKET_DATE_WEEKDAY",
        weekday_ready,
        "CSV market date is a weekday."
        if weekday_ready
        else "Daily A-share CSV market date cannot be a Saturday or Sunday.",
    )
    close_ready = _market_close_ready(observed_date, market_now)
    _check(
        checks,
        "DAILY_BAR_FINALIZED",
        close_ready,
        "Market date is not future-dated and same-day intake is after the A-share close buffer."
        if close_ready
        else "Daily bars cannot be retained before 15:30 Asia/Shanghai on their market date.",
    )
    export_covers_date = _export_covers_market_date(exported_at, observed_date)
    _check(
        checks,
        "EXPORT_COVERS_MARKET_DATE",
        export_covers_date,
        "Source export occurred no earlier than the retained market date close."
        if export_covers_date
        else "Source export must occur after the retained market date has closed.",
    )

    ledger_events, ledger_error = _read_collection_ledger(ledger_path)
    if not ledger_error:
        ledger_error = _retained_files_error(output_root, ledger_events)
    existing = next(
        (
            event
            for event in ledger_events
            if event["trial_id"] == trial_id and event["market_date"] == market_date
        ),
        None,
    )
    ledger_ready = not ledger_error and (
        existing is None or hmac.compare_digest(str(existing["raw_sha256"]), raw_sha256)
    )
    _check(
        checks,
        "COLLECTION_LEDGER_ADMISSION",
        ledger_ready,
        "Collection ledger verifies and this date is new."
        if ledger_ready and existing is None
        else (
            "Identical market-date evidence is already retained; replay is idempotent."
            if ledger_ready
            else ledger_error or "A different raw file is already retained for this market date."
        ),
    )
    _check(
        checks,
        "QUARANTINE_ONLY_BOUNDARY",
        True,
        "Successful intake remains unreviewed quarantine and cannot write the execution cache.",
    )

    blockers = tuple(dict.fromkeys(item.message for item in checks if item.status == "BLOCK"))
    retention_allowed = not blockers
    retained_path = str(output_root / str(existing["retained_relative_path"])) if existing else ""
    return SealedHoldoutIntakeReport(
        artifact_type="sealed_holdout_intake",
        schema_version=1,
        status="PASS" if retention_allowed else "BLOCK",
        evaluated_at_utc=evaluated_at.replace(microsecond=0).isoformat(),
        evaluated_market_date=market_now.date().isoformat(),
        market_timezone=MARKET_TIMEZONE,
        trial_id=trial_id,
        candidate=candidate,
        market_date=market_date,
        source_vendor=source_vendor,
        source_reference=source_reference,
        source_exported_at=source_exported_at,
        price_adjustment=adjustment,
        input_path=str(input_path),
        raw_sha256=raw_sha256,
        canonical_bar_fingerprint=canonical_fingerprint,
        row_count=len(rows),
        symbol_count=len({str(row[0]) for row in rows}),
        ledger_path=str(ledger_path),
        retained_path=retained_path,
        ledger_event=None,
        existing_event=existing,
        idempotent=existing is not None and ledger_ready,
        retention_allowed=retention_allowed,
        execution_cache_write_allowed=False,
        holdout_analysis_allowed=False,
        promotion_eligible=False,
        paper_trading_allowed=False,
        live_trading_allowed=False,
        checks=tuple(checks),
        blockers=blockers,
        next_actions=_next_actions(checks, retained=existing is not None),
        prohibited_actions=PROHIBITED_ACTIONS,
        packet_verification=verification,
    )


def retain_sealed_holdout_intake(
    report: SealedHoldoutIntakeReport,
    *,
    daily_bars_csv: str | Path,
    output_dir: str | Path,
) -> SealedHoldoutIntakeReport:
    """Commit a validated file to quarantine and append one hash-bound event."""
    if not report.retention_allowed:
        raise SealedHoldoutIntakeError("BLOCK intake cannot retain evidence")
    output_root = Path(output_dir).resolve()
    input_path = Path(daily_bars_csv).resolve()
    raw_bytes = input_path.read_bytes()
    if hashlib.sha256(raw_bytes).hexdigest() != report.raw_sha256:
        raise SealedHoldoutIntakeError("daily CSV changed after intake validation")
    if report.idempotent and report.existing_event is not None:
        retained = output_root / str(report.existing_event["retained_relative_path"])
        if not retained.is_file() or _file_sha256(retained) != report.raw_sha256:
            raise SealedHoldoutIntakeError("idempotent ledger event points to missing or changed raw bytes")
        committed = replace(report, retained_path=str(retained))
        write_sealed_holdout_intake_report(committed, output_root)
        return committed

    relative_path = Path("sealed_inputs") / (
        f"{report.market_date}_{report.raw_sha256[:16]}.csv"
    )
    retained_path = output_root / relative_path
    _retain_exact_bytes(retained_path, raw_bytes, report.raw_sha256)
    ledger_path = output_root / LEDGER_FILENAME
    event = _append_collection_event(
        ledger_path,
        {
            "trial_id": report.trial_id,
            "candidate": report.candidate,
            "market_date": report.market_date,
            "source_vendor": report.source_vendor,
            "source_reference": report.source_reference,
            "source_exported_at": report.source_exported_at,
            "price_adjustment": report.price_adjustment,
            "raw_filename": input_path.name,
            "raw_sha256": report.raw_sha256,
            "canonical_bar_fingerprint": report.canonical_bar_fingerprint,
            "row_count": report.row_count,
            "symbol_count": report.symbol_count,
            "retained_relative_path": relative_path.as_posix(),
            "evidence_role": "unreviewed_quarantine",
            "received_at_utc": report.evaluated_at_utc,
        },
    )
    committed = replace(
        report,
        retained_path=str(retained_path),
        ledger_event=event,
        existing_event=None,
        idempotent=False,
    )
    write_sealed_holdout_intake_report(committed, output_root)
    return committed


def write_sealed_holdout_intake_report(
    report: SealedHoldoutIntakeReport,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report.to_dict(), ensure_ascii=False, allow_nan=False, indent=2)
    markdown = report.to_markdown()
    (root / "sealed_holdout_intake.json").write_text(payload, encoding="utf-8")
    (root / "sealed_holdout_intake.md").write_text(markdown, encoding="utf-8")
    if report.retained:
        event = report.ledger_event or report.existing_event or {}
        event_hash = str(event.get("event_hash") or report.raw_sha256)
        reports = root / "intake_reports"
        reports.mkdir(parents=True, exist_ok=True)
        stem = f"{report.market_date}_{event_hash[:16]}"
        (reports / f"{stem}.json").write_text(payload, encoding="utf-8")
        (reports / f"{stem}.md").write_text(markdown, encoding="utf-8")
    return root


def verify_collection_ledger(
    path: str | Path,
    *,
    quarantine_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    events, error = _read_collection_ledger(Path(path))
    if error:
        raise SealedHoldoutIntakeError(error)
    if quarantine_root is not None:
        retained_error = _retained_files_error(Path(quarantine_root), events)
        if retained_error:
            raise SealedHoldoutIntakeError(retained_error)
    return events


def load_verified_sealed_daily_bars(
    path: str | Path,
    event: dict[str, Any],
) -> pd.DataFrame:
    """Load one ledger-bound CSV after recomputing its strict row identity."""
    input_path = Path(path)
    try:
        raw = input_path.read_bytes()
    except OSError as exc:
        raise SealedHoldoutIntakeError(
            f"sealed input cannot be read: {input_path}: {exc}"
        ) from exc
    actual_hash = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(actual_hash, str(event.get("raw_sha256") or "")):
        raise SealedHoldoutIntakeError("sealed input SHA-256 does not match its ledger event")
    rows, errors = _validate_daily_csv(raw)
    if errors:
        raise SealedHoldoutIntakeError("sealed input contract failed: " + "; ".join(errors))
    fingerprint = logical_bar_fingerprint(
        sorted(rows, key=lambda row: (str(row[0]), str(row[1])))
    )
    if not hmac.compare_digest(
        fingerprint,
        str(event.get("canonical_bar_fingerprint") or ""),
    ):
        raise SealedHoldoutIntakeError(
            "sealed input canonical bar fingerprint does not match its ledger event"
        )
    market_dates = {str(row[1]) for row in rows}
    symbols = {str(row[0]) for row in rows}
    if (
        market_dates != {str(event.get("market_date") or "")}
        or len(rows) != event.get("row_count")
        or len(symbols) != event.get("symbol_count")
    ):
        raise SealedHoldoutIntakeError(
            "sealed input date or row/symbol counts do not match its ledger event"
        )
    return pd.DataFrame(rows, columns=REQUIRED_COLUMNS)


def _validate_daily_csv(raw_bytes: bytes | None) -> tuple[list[tuple[Any, ...]], list[str]]:
    if raw_bytes is None:
        return [], []
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        return [], ["Daily CSV must be UTF-8 or UTF-8 with BOM."]
    try:
        table = list(csv.reader(io.StringIO(text, newline="")))
    except csv.Error as exc:
        return [], [f"Daily CSV parse failed: {exc}."]
    if not table:
        return [], ["Daily CSV is empty."]
    header = [item.strip() for item in table[0]]
    errors: list[str] = []
    if len(header) != len(set(header)):
        errors.append("Daily CSV contains duplicate column names.")
    missing = [column for column in REQUIRED_COLUMNS if column not in header]
    if missing:
        errors.append("Daily CSV is missing required columns: " + ", ".join(missing) + ".")
    if errors:
        return [], errors
    malformed = [index for index, row in enumerate(table[1:], start=2) if len(row) != len(header)]
    if malformed:
        return [], [f"Daily CSV rows do not match header width: {malformed[:10]}."]
    if len(table) == 1:
        return [], ["Daily CSV has no data rows."]

    indices = {column: header.index(column) for column in REQUIRED_COLUMNS}
    rows: list[tuple[Any, ...]] = []
    keys: set[tuple[str, str]] = set()
    dates: set[str] = set()
    for row_number, raw in enumerate(table[1:], start=2):
        symbol = raw[indices["symbol"]].strip()
        date_text = raw[indices["date"]].strip()
        if _SYMBOL_PATTERN.fullmatch(symbol) is None:
            errors.append(f"Row {row_number} symbol must be six digits.")
            continue
        if _iso_date(date_text) is None:
            errors.append(f"Row {row_number} date must be YYYY-MM-DD.")
            continue
        key = (symbol, date_text)
        if key in keys:
            errors.append(f"Row {row_number} duplicates symbol/date {symbol}/{date_text}.")
            continue
        keys.add(key)
        dates.add(date_text)
        numbers: list[float] = []
        numeric_error = False
        for column in REQUIRED_COLUMNS[2:]:
            try:
                number = float(raw[indices[column]])
            except ValueError:
                numeric_error = True
                break
            if not math.isfinite(number):
                numeric_error = True
                break
            numbers.append(number)
        if numeric_error:
            errors.append(f"Row {row_number} contains invalid or non-finite OHLCVA values.")
            continue
        open_, high, low, close, volume, amount = numbers
        if min(open_, high, low, close) <= 0:
            errors.append(f"Row {row_number} OHLC prices must be positive.")
        elif high < max(open_, low, close) or low > min(open_, high, close):
            errors.append(f"Row {row_number} violates OHLC high/low ordering.")
        elif volume < 0 or amount < 0:
            errors.append(f"Row {row_number} volume and amount must be non-negative.")
        else:
            rows.append((symbol, date_text, *numbers))
    if len(dates) != 1:
        errors.append("Daily CSV must contain exactly one market date.")
    return rows, list(dict.fromkeys(errors))


def _append_collection_event(path: Path, event_body: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle, _file_lock(handle, exclusive=True):
        handle.seek(0)
        prior = handle.read()
        events = _parse_collection_ledger(prior)
        existing = next(
            (
                event
                for event in events
                if event["trial_id"] == event_body["trial_id"]
                and event["market_date"] == event_body["market_date"]
            ),
            None,
        )
        if existing is not None:
            if hmac.compare_digest(str(existing["raw_sha256"]), str(event_body["raw_sha256"])):
                return existing
            raise SealedHoldoutIntakeError(
                "a different raw file is already retained for this trial market date"
            )
        event = {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "sequence": len(events) + 1,
            "event_type": "sealed_daily_bars",
            **event_body,
            "hash_algorithm": "sha256",
            "previous_hash": events[-1]["event_hash"] if events else GENESIS_HASH,
        }
        event["event_hash"] = _event_hash(event)
        encoded = _canonical_json(event) + b"\n"
        handle.seek(0, os.SEEK_END)
        if handle.tell() != len(prior):
            raise SealedHoldoutIntakeError("collection ledger changed while append lock was held")
        if handle.write(encoded) != len(encoded):  # pragma: no cover - filesystem failure
            raise OSError("short collection-ledger append")
        handle.flush()
        os.fsync(handle.fileno())
        return event


def _read_collection_ledger(path: Path) -> tuple[list[dict[str, Any]], str]:
    try:
        with path.open("rb") as handle, _file_lock(handle, exclusive=False):
            return _parse_collection_ledger(handle.read()), ""
    except FileNotFoundError:
        return [], ""
    except (OSError, SealedHoldoutIntakeError) as exc:
        return [], f"Collection ledger cannot be verified: {type(exc).__name__}: {exc}"


def _parse_collection_ledger(raw: bytes) -> list[dict[str, Any]]:
    if not raw:
        return []
    if not raw.endswith(b"\n"):
        raise SealedHoldoutIntakeError("collection ledger is truncated")
    events: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    previous_hash = GENESIS_HASH
    for line_number, raw_line in enumerate(raw[:-1].split(b"\n"), start=1):
        if not raw_line:
            raise SealedHoldoutIntakeError(f"line {line_number}: blank lines are prohibited")
        try:
            payload = json.loads(
                raw_line.decode("utf-8"),
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise SealedHoldoutIntakeError(f"line {line_number}: malformed JSON: {exc}") from exc
        if not isinstance(payload, dict) or _canonical_json(payload) != raw_line:
            raise SealedHoldoutIntakeError(f"line {line_number}: event is not canonical JSON")
        _validate_collection_event(payload, line_number, previous_hash)
        key = (str(payload["trial_id"]), str(payload["market_date"]))
        if key in seen:
            raise SealedHoldoutIntakeError(f"line {line_number}: duplicate trial market date")
        seen.add(key)
        events.append(payload)
        previous_hash = str(payload["event_hash"])
    return events


def _validate_collection_event(
    event: dict[str, Any],
    line_number: int,
    previous_hash: str,
) -> None:
    if set(event) != EVENT_FIELDS:
        raise SealedHoldoutIntakeError(f"line {line_number}: event fields differ from schema")
    if event["schema_version"] != LEDGER_SCHEMA_VERSION or event["sequence"] != line_number:
        raise SealedHoldoutIntakeError(f"line {line_number}: schema or sequence is invalid")
    if event["event_type"] != "sealed_daily_bars" or event["hash_algorithm"] != "sha256":
        raise SealedHoldoutIntakeError(f"line {line_number}: event type or hash algorithm is invalid")
    if event["evidence_role"] != "unreviewed_quarantine":
        raise SealedHoldoutIntakeError(f"line {line_number}: evidence role is invalid")
    if event["previous_hash"] != previous_hash:
        raise SealedHoldoutIntakeError(f"line {line_number}: previous hash mismatch")
    if _HASH_PATTERN.fullmatch(str(event["previous_hash"])) is None:
        raise SealedHoldoutIntakeError(f"line {line_number}: previous hash is invalid")
    if not isinstance(event["event_hash"], str) or _HASH_PATTERN.fullmatch(event["event_hash"]) is None:
        raise SealedHoldoutIntakeError(f"line {line_number}: event hash is invalid")
    if not hmac.compare_digest(str(event["event_hash"]), _event_hash(event)):
        raise SealedHoldoutIntakeError(f"line {line_number}: event hash mismatch")
    if _HASH_PATTERN.fullmatch(str(event["raw_sha256"])) is None:
        raise SealedHoldoutIntakeError(f"line {line_number}: raw SHA-256 is invalid")
    if _HASH_PATTERN.fullmatch(str(event["canonical_bar_fingerprint"])) is None:
        raise SealedHoldoutIntakeError(f"line {line_number}: canonical fingerprint is invalid")
    if type(event["row_count"]) is not int or event["row_count"] < 1:
        raise SealedHoldoutIntakeError(f"line {line_number}: row count is invalid")
    if type(event["symbol_count"]) is not int or event["symbol_count"] < 1:
        raise SealedHoldoutIntakeError(f"line {line_number}: symbol count is invalid")
    if event["symbol_count"] > event["row_count"]:
        raise SealedHoldoutIntakeError(f"line {line_number}: symbol count exceeds row count")
    for field in ("trial_id", "candidate", "source_vendor", "source_reference", "raw_filename"):
        value = event[field]
        if not isinstance(value, str) or _placeholder(value):
            raise SealedHoldoutIntakeError(f"line {line_number}: {field} is invalid")
    if Path(str(event["raw_filename"])).name != event["raw_filename"]:
        raise SealedHoldoutIntakeError(f"line {line_number}: raw filename is not a basename")
    if _iso_date(event["market_date"]) is None:
        raise SealedHoldoutIntakeError(f"line {line_number}: market date is invalid")
    if event["price_adjustment"] not in {"raw", "qfq", "hfq"}:
        raise SealedHoldoutIntakeError(f"line {line_number}: price adjustment is invalid")
    if _aware_datetime(event["source_exported_at"]) is None:
        raise SealedHoldoutIntakeError(f"line {line_number}: source export timestamp is invalid")
    exported_at = _aware_datetime(event["source_exported_at"])
    received_at = _aware_datetime(event["received_at_utc"])
    if received_at is None or received_at.utcoffset() != UTC.utcoffset(received_at):
        raise SealedHoldoutIntakeError(f"line {line_number}: receive timestamp is invalid")
    if exported_at is not None and received_at is not None and exported_at > received_at:
        raise SealedHoldoutIntakeError(f"line {line_number}: source export follows receipt")
    market_date = _iso_date(event["market_date"])
    if market_date is None or market_date.weekday() >= 5:
        raise SealedHoldoutIntakeError(f"line {line_number}: market date is not a weekday")
    if not _export_covers_market_date(exported_at, market_date):
        raise SealedHoldoutIntakeError(f"line {line_number}: source export precedes market close")
    retained = Path(str(event["retained_relative_path"]))
    if retained.is_absolute() or ".." in retained.parts or retained.parts[:1] != ("sealed_inputs",):
        raise SealedHoldoutIntakeError(f"line {line_number}: retained path is unsafe")
    expected_retained = Path("sealed_inputs") / (
        f"{event['market_date']}_{str(event['raw_sha256'])[:16]}.csv"
    )
    if retained != expected_retained:
        raise SealedHoldoutIntakeError(f"line {line_number}: retained path is not hash-bound")


def _retained_files_error(root: Path, events: list[dict[str, Any]]) -> str:
    resolved_root = root.resolve()
    for event in events:
        retained = (root / str(event["retained_relative_path"])).resolve()
        try:
            retained.relative_to(resolved_root)
        except ValueError:
            return "Collection ledger retained path escapes the quarantine root."
        if not retained.is_file():
            return f"Collection ledger retained file is missing: {retained}."
        try:
            actual = _file_sha256(retained)
        except OSError as exc:
            return f"Collection ledger retained file cannot be read: {retained}: {exc}."
        if not hmac.compare_digest(actual, str(event["raw_sha256"])):
            return f"Collection ledger retained file hash mismatch: {retained}."
        source_reference = str(event["source_reference"])
        if "|sha256=" in source_reference:
            source_path_text, source_hash = source_reference.rsplit("|sha256=", 1)
            source_path = Path(source_path_text)
            if _HASH_PATTERN.fullmatch(source_hash) is None:
                return "Collection ledger source-reference SHA-256 is invalid."
            if not source_path.is_file():
                return f"Collection ledger source-reference file is missing: {source_path}."
            try:
                actual_source_hash = _file_sha256(source_path)
            except OSError as exc:
                return f"Collection ledger source-reference file cannot be read: {source_path}: {exc}."
            if not hmac.compare_digest(actual_source_hash, source_hash):
                return f"Collection ledger source-reference hash mismatch: {source_path}."
    return ""


def _retain_exact_bytes(path: Path, raw: bytes, expected_hash: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_file() or _file_sha256(path) != expected_hash:
            raise SealedHoldoutIntakeError("retained raw path exists with different bytes")
        return
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            if handle.write(raw) != len(raw):  # pragma: no cover - filesystem failure
                raise OSError("short retained-file write")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _terminal_result_count(path: Path, trial_id: str) -> tuple[int, str]:
    try:
        events = verify_registry(path)
    except (OSError, TrialRegistryError) as exc:
        return 0, f"{type(exc).__name__}: {exc}"
    preregistrations = sum(
        isinstance(event, PreregistrationEvent) and event.trial_id == trial_id
        for event in events
    )
    if preregistrations != 1:
        return 0, f"expected one preregistration, found {preregistrations}"
    return sum(
        isinstance(event, ResultEvent) and event.trial_id == trial_id for event in events
    ), ""


def _terminal_result_message(count: int, error: str) -> str:
    if error:
        return f"Trial registry cannot be verified: {error}."
    return f"Trial already has {count} terminal result event(s); further collection is blocked."


def _market_close_ready(observed: date | None, market_now: datetime) -> bool:
    if observed is None or observed > market_now.date():
        return False
    if observed < market_now.date():
        return True
    return market_now.time().replace(tzinfo=None) >= time(15, 30)


def _export_covers_market_date(exported: datetime | None, observed: date | None) -> bool:
    if exported is None or observed is None:
        return False
    shanghai = exported.astimezone(ZoneInfo(MARKET_TIMEZONE))
    if shanghai.date() > observed:
        return True
    return shanghai.date() == observed and shanghai.time().replace(tzinfo=None) >= time(15, 0)


def _boundary_message(
    observed: date | None,
    start: date | None,
    end: date | None,
) -> str:
    return (
        f"CSV market date {observed or 'invalid'} must be inside the frozen test interval "
        f"{start or 'invalid'} to {end or 'invalid'}."
    )


def _next_actions(checks: list[IntakeCheck], *, retained: bool) -> tuple[str, ...]:
    blocked = {item.code for item in checks if item.status == "BLOCK"}
    actions: list[str] = []
    if "PACKET_INTEGRITY" in blocked or "TERMINAL_RESULT_ABSENT" in blocked:
        actions.append("Restore and verify the frozen packet and trial registry before retaining data.")
    if "SOURCE_DECLARATION_PRESENT" in blocked or "SOURCE_EXPORT_TIMESTAMP" in blocked:
        actions.append("Provide the real vendor/export reference and timezone-aware export timestamp; do not invent them.")
    if "DAILY_CSV_CONTRACT" in blocked:
        actions.append("Export one finalized canonical daily CSV with valid symbol/date/OHLCVA rows.")
    if blocked & {
        "REGISTERED_HOLDOUT_DATE",
        "MARKET_DATE_WEEKDAY",
        "DAILY_BAR_FINALIZED",
        "EXPORT_COVERS_MARKET_DATE",
    }:
        actions.append("Retain only finalized bars inside the registered prospective test interval after market close.")
    if "COLLECTION_LEDGER_ADMISSION" in blocked:
        actions.append("Do not replace prior evidence; investigate the retained bytes and append-only ledger.")
    if not blocked and retained:
        actions.append("Evidence is already retained; do not append a duplicate event or inspect candidate results.")
    elif not blocked:
        actions.append("Retain the exact CSV bytes and append one hash-bound quarantine event.")
    actions.append("Complete source QA separately before any guarded replay into an execution cache.")
    return tuple(dict.fromkeys(actions))


def _frozen_adjustment(packet: dict[str, Any]) -> str:
    execution = packet.get("execution_config")
    if not isinstance(execution, dict):
        return ""
    data = execution.get("data")
    return _text(data.get("adjust")).lower() if isinstance(data, dict) else ""


def _boundary_date(boundaries: dict[str, Any], section: str, field: str) -> date | None:
    value = boundaries.get(section)
    return _iso_date(value.get(field)) if isinstance(value, dict) else None


def _iso_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _aware_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _read_bytes(path: Path) -> tuple[bytes | None, str]:
    try:
        if not path.is_file():
            return None, f"Daily CSV does not exist or is not a file: {path}."
        return path.read_bytes(), ""
    except OSError as exc:
        return None, f"Daily CSV cannot be read: {exc}."


def _load_json_object(path: Path) -> tuple[dict[str, Any], str]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return {}, f"{type(exc).__name__}: {exc}"
    return (payload, "") if isinstance(payload, dict) else ({}, "packet root is not an object")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON key {key!r}")
        payload[key] = value
    return payload


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value!r}")


def _event_hash(event: dict[str, Any]) -> str:
    payload = dict(event)
    payload.pop("event_hash", None)
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check(checks: list[IntakeCheck], code: str, passed: bool, message: str) -> None:
    checks.append(IntakeCheck(code, "PASS" if passed else "BLOCK", message))


def _placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in _PLACEHOLDERS or normalized.startswith("<")


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _workspace_root(value: str | Path | None) -> Path:
    return Path(value).resolve() if value is not None else Path(__file__).resolve().parents[3]


def _resolve_path(value: str | Path, root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _runtime_now() -> datetime:
    return datetime.now(UTC)


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
    except ImportError:  # pragma: no cover - unusual platform fallback
        yield
        return
    mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    fcntl.flock(handle.fileno(), mode)
    try:
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
