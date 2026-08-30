"""Post-close acquisition for a frozen prospective A-share universe.

The collector reads the frozen development universe through SQLite read-only,
fetches one finalized date into a scratch cache with persistence disabled, and
hands a deterministic canonical CSV to sealed quarantine.  It never runs the
candidate or writes the frozen execution cache.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, time
import csv
import hashlib
import io
import json
from importlib.metadata import PackageNotFoundError, version
import math
import os
from pathlib import Path
import re
import sqlite3
import time as time_module
from typing import Any, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd

from quantify.data.akshare_feed import AkshareFeed
from quantify.data.exchange_calendar_preflight import (
    ExchangeCalendarPreflight,
    build_exchange_calendar_preflight,
)
from quantify.research.prospective_trial_packet import (
    ProspectiveTrialPacketVerification,
    build_prospective_trial_packet_verification,
)
from quantify.research.sealed_holdout_intake import (
    SealedHoldoutIntakeError,
    SealedHoldoutIntakeReport,
    build_sealed_holdout_intake,
    retain_sealed_holdout_intake,
    verify_collection_ledger,
)
from quantify.research.trial_registry import (
    PreregistrationEvent,
    ResultEvent,
    TrialRegistryError,
    verify_registry,
)

AcquisitionStatus = Literal[
    "READY",
    "PASS",
    "ALREADY_RETAINED",
    "MARKET_CLOSED",
    "BLOCK",
]
FetchSymbol = Callable[[str, str, str], tuple[pd.DataFrame, str]]

MARKET_TIMEZONE = "Asia/Shanghai"
CANONICAL_COLUMNS = ("symbol", "date", "open", "high", "low", "close", "volume", "amount")
PROHIBITED_ACTIONS = (
    "Do not run this collector before the A-share close buffer or for dates outside the frozen test interval.",
    "Do not write fetched rows to the frozen development or execution cache.",
    "Do not use acquisition PASS as source-QA, PIT-universe, strategy, paper, or live evidence.",
    "Do not calculate or inspect candidate results from acquired rows during the sealed holdout.",
    "Do not connect this workflow to a broker or generate orders.",
)
_SYMBOL_PATTERN = re.compile(r"\d{6}\Z")


@dataclass(frozen=True, slots=True)
class AcquisitionCheck:
    code: str
    status: Literal["PASS", "BLOCK"]
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "status": self.status, "message": self.message}


@dataclass(frozen=True, slots=True)
class SymbolAcquisitionFailure:
    symbol: str
    attempts: int
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"symbol": self.symbol, "attempts": self.attempts, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class ProspectiveDailyAcquisition:
    artifact_type: str
    schema_version: int
    status: AcquisitionStatus
    evaluated_at_utc: str
    evaluated_market_date: str
    market_timezone: str
    trial_id: str
    candidate: str
    market_date: str
    test_start: str
    test_end: str
    development_cutoff: str
    development_cache_path: str
    quarantine_root: str
    frozen_symbol_count: int
    frozen_symbol_fingerprint: str
    price_adjustment: str
    minimum_success_ratio: float
    requested_symbols: int
    successful_symbols: int
    failed_symbols: int
    success_ratio: float
    row_count: int
    provider_routes: dict[str, int]
    failures: tuple[SymbolAcquisitionFailure, ...]
    source_vendor: str
    source_exported_at: str
    akshare_version: str
    csv_sha256: str
    csv_bytes: bytes = field(repr=False)
    calendar_evidence_status: str = "MISSING"
    calendar_session_status: str = "UNREVIEWED"
    existing_event: dict[str, Any] | None = None
    fetch_allowed: bool = False
    execution_cache_write_allowed: bool = False
    holdout_analysis_allowed: bool = False
    promotion_eligible: bool = False
    paper_trading_allowed: bool = False
    live_trading_allowed: bool = False
    checks: tuple[AcquisitionCheck, ...] = ()
    blockers: tuple[str, ...] = ()
    next_actions: tuple[str, ...] = ()
    prohibited_actions: tuple[str, ...] = PROHIBITED_ACTIONS
    packet_verification: ProspectiveTrialPacketVerification | None = None
    calendar_preflight: ExchangeCalendarPreflight | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "schema_version": self.schema_version,
            "operation": "post_close_frozen_universe_acquisition",
            "network_access": self.status == "PASS" or self.requested_symbols > 0,
            "broker_access": False,
            "status": self.status,
            "evaluated_at_utc": self.evaluated_at_utc,
            "evaluated_market_date": self.evaluated_market_date,
            "market_timezone": self.market_timezone,
            "trial_id": self.trial_id,
            "candidate": self.candidate,
            "market_date": self.market_date,
            "test_interval": {"start": self.test_start, "end": self.test_end},
            "development_cutoff": self.development_cutoff,
            "development_cache_path": self.development_cache_path,
            "quarantine_root": self.quarantine_root,
            "frozen_symbol_count": self.frozen_symbol_count,
            "frozen_symbol_fingerprint": self.frozen_symbol_fingerprint,
            "price_adjustment": self.price_adjustment,
            "minimum_success_ratio": self.minimum_success_ratio,
            "requested_symbols": self.requested_symbols,
            "successful_symbols": self.successful_symbols,
            "failed_symbols": self.failed_symbols,
            "success_ratio": self.success_ratio,
            "row_count": self.row_count,
            "provider_routes": self.provider_routes,
            "failures": [item.to_dict() for item in self.failures],
            "source_vendor": self.source_vendor,
            "source_review_status": "NOT_EVALUATED",
            "source_exported_at": self.source_exported_at,
            "akshare_version": self.akshare_version,
            "csv_sha256": self.csv_sha256,
            "calendar_evidence_status": self.calendar_evidence_status,
            "calendar_session_status": self.calendar_session_status,
            "existing_event": self.existing_event,
            "fetch_allowed": self.fetch_allowed,
            "execution_cache_write_allowed": self.execution_cache_write_allowed,
            "holdout_analysis_allowed": self.holdout_analysis_allowed,
            "promotion_eligible": self.promotion_eligible,
            "paper_trading_allowed": self.paper_trading_allowed,
            "live_trading_allowed": self.live_trading_allowed,
            "checks": [item.to_dict() for item in self.checks],
            "blockers": list(self.blockers),
            "next_actions": list(self.next_actions),
            "prohibited_actions": list(self.prohibited_actions),
            "packet_verification": (
                self.packet_verification.to_dict() if self.packet_verification else None
            ),
            "calendar_preflight": (
                self.calendar_preflight.to_dict() if self.calendar_preflight else None
            ),
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Prospective Daily Acquisition: {self.status}",
            "",
            f"- Trial: `{self.trial_id or 'unavailable'}`",
            f"- Candidate: `{self.candidate or 'unavailable'}`",
            f"- Market date: `{self.market_date}`",
            f"- Quarantine root: `{self.quarantine_root}`",
            f"- Calendar evidence: `{self.calendar_evidence_status}`",
            f"- Calendar session: `{self.calendar_session_status}`",
            f"- Frozen symbols: `{self.frozen_symbol_count}`",
            f"- Adjustment: `{self.price_adjustment or 'unavailable'}`",
            f"- Fetch allowed: `{self.fetch_allowed}`",
            f"- Success: `{self.successful_symbols}/{self.requested_symbols}` ({self.success_ratio:.2%})",
            f"- Rows: `{self.row_count}`",
            f"- CSV SHA-256: `{self.csv_sha256 or 'unavailable'}`",
            f"- Execution-cache write allowed: `{self.execution_cache_write_allowed}`",
            f"- Holdout analysis allowed: `{self.holdout_analysis_allowed}`",
            "",
            "Acquisition output remains unreviewed quarantine input. PASS does not approve "
            "source QA, strategy performance, paper trading, or live trading.",
            "",
            "## Checks",
            "",
        ]
        lines.extend(
            f"- `{item.status}` `{item.code}`: {item.message}" for item in self.checks
        )
        lines.extend(["", "## Failures", ""])
        lines.extend(
            f"- `{item.symbol}` ({item.attempts} attempts): {item.reason}"
            for item in self.failures[:100]
        ) if self.failures else lines.append("- None.")
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- {item}" for item in self.blockers or ("None.",))
        lines.extend(["", "## Next Actions", ""])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Prohibited Actions", ""])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        lines.append("")
        return "\n".join(lines)


def build_prospective_daily_acquisition_preflight(
    *,
    packet_dir: str | Path,
    trial_registry_path: str | Path,
    output_dir: str | Path,
    market_date: str | None = None,
    minimum_success_ratio: float = 0.95,
    calendar_csv: str | Path | None = None,
    calendar_metadata: str | Path | None = None,
    workspace_root: str | Path | None = None,
) -> ProspectiveDailyAcquisition:
    """Build a no-network post-close preflight for one frozen market date."""
    root = _workspace_root(workspace_root)
    packet_root = _resolve_path(packet_dir, root)
    registry_path = _resolve_path(trial_registry_path, root)
    output_root = _resolve_path(output_dir, root).resolve()
    now = _runtime_now()
    market_now = now.astimezone(ZoneInfo(MARKET_TIMEZONE))
    requested_date = market_date.strip() if isinstance(market_date, str) else market_now.date().isoformat()
    observed_date = _iso_date(requested_date)

    packet, packet_error = _load_json_object(packet_root / "prospective_trial_packet.json")
    verification = build_prospective_trial_packet_verification(
        packet_root,
        registry_path,
        workspace_root=root,
    )
    trial_id = _text(packet.get("trial_id"))
    candidate = _text(packet.get("candidate"))
    development_cutoff = _text(packet.get("development_cutoff"))
    boundaries = packet.get("boundaries") if isinstance(packet.get("boundaries"), dict) else {}
    test_start = _boundary_text(boundaries, "test", "start")
    test_end = _boundary_text(boundaries, "test", "end")
    test_start_date = _iso_date(test_start)
    test_end_date = _iso_date(test_end)
    development_cache = _development_cache_path(packet, root)
    adjustment = _frozen_adjustment(packet)
    checks: list[AcquisitionCheck] = []
    _check(
        checks,
        "PACKET_INTEGRITY",
        not packet_error and verification.status == "PASS",
        "Frozen packet, code, config, prefix, and registry binding verify."
        if not packet_error and verification.status == "PASS"
        else "Frozen packet integrity or registry binding does not verify.",
    )
    result_count, registry_error = _result_count(registry_path, trial_id)
    _check(
        checks,
        "TERMINAL_RESULT_ABSENT",
        not registry_error and result_count == 0,
        "Registry contains one preregistration and no terminal result."
        if not registry_error and result_count == 0
        else registry_error or f"Trial already has {result_count} terminal result event(s).",
    )
    ratio_ready = math.isfinite(minimum_success_ratio) and 0 < minimum_success_ratio <= 1
    _check(
        checks,
        "MINIMUM_SUCCESS_RATIO",
        ratio_ready,
        "Minimum success ratio is inside (0, 1]."
        if ratio_ready
        else "Minimum success ratio must be finite and inside (0, 1].",
    )

    calendar_report: ExchangeCalendarPreflight | None = None
    calendar_input_supplied = calendar_csv is not None or calendar_metadata is not None
    calendar_pair_ready = (calendar_csv is None) == (calendar_metadata is None)
    calendar_session_open: bool | None = None
    if not calendar_pair_ready:
        _check(
            checks,
            "REVIEWED_CALENDAR_INPUT_PAIR",
            False,
            "Calendar CSV and metadata must be supplied together.",
        )
    elif calendar_csv is not None and calendar_metadata is not None:
        if observed_date is None:
            _check(
                checks,
                "REVIEWED_CALENDAR_EVIDENCE",
                False,
                "Reviewed calendar cannot be validated because market_date is invalid.",
            )
        else:
            calendar_report = build_exchange_calendar_preflight(
                _resolve_path(calendar_csv, root),
                _resolve_path(calendar_metadata, root),
                required_start_date=observed_date.isoformat(),
                required_end_date=observed_date.isoformat(),
            )
            calendar_ready = calendar_report.status == "PASS"
            _check(
                checks,
                "REVIEWED_CALENDAR_EVIDENCE",
                calendar_ready,
                "Reviewed exchange calendar passes strict preflight for the requested date."
                if calendar_ready
                else "Reviewed exchange calendar preflight is BLOCK.",
            )
            if calendar_ready:
                matching_session = next(
                    (
                        item
                        for item in calendar_report.sessions
                        if str(item["date"]) == observed_date.isoformat()
                    ),
                    None,
                )
                calendar_session_open = (
                    matching_session["is_open"]
                    if matching_session is not None
                    and isinstance(matching_session.get("is_open"), bool)
                    else None
                )
                _check(
                    checks,
                    "REVIEWED_CALENDAR_SESSION",
                    calendar_session_open is not None,
                    "Reviewed calendar contains an explicit open/closed row for the requested date."
                    if calendar_session_open is not None
                    else "Reviewed calendar does not contain the requested date.",
                )

    calendar_pass = calendar_report is not None and calendar_report.status == "PASS"
    reviewed_closed = calendar_pass and calendar_session_open is False
    inside_test_interval = (
        observed_date is not None
        and test_start_date is not None
        and test_end_date is not None
        and test_start_date <= observed_date <= test_end_date
    )
    date_ready = (
        inside_test_interval
        and observed_date is not None
        and (
            calendar_pass and calendar_session_open is not None
            or not calendar_pass and observed_date.weekday() < 5
        )
    )
    date_message = (
        "Requested reviewed open session is inside the frozen prospective test interval."
        if calendar_pass and calendar_session_open is True and date_ready
        else "Requested reviewed market-closed date is inside the frozen prospective test interval."
        if reviewed_closed and date_ready
        else "Requested weekday is inside the frozen prospective test interval."
        if date_ready
        else (
            f"Requested date {requested_date!r} must be a reviewed calendar date or "
            f"conservative weekday inside {test_start or 'invalid'} to {test_end or 'invalid'}."
        )
    )
    _check(
        checks,
        "FROZEN_MARKET_DATE",
        date_ready,
        date_message,
    )
    close_ready = reviewed_closed or _post_close(observed_date, market_now)
    _check(
        checks,
        "POST_CLOSE_TIME",
        close_ready,
        "Reviewed market-closed date requires no provider collection."
        if reviewed_closed
        else "Requested date is finalized under the 15:30 Asia/Shanghai close buffer."
        if close_ready
        else "Network acquisition is prohibited before 15:30 Asia/Shanghai on the requested date.",
    )

    symbols, universe_error = _load_frozen_symbols(development_cache, development_cutoff)
    expected_symbols = int(
        (packet.get("development_data") or {}).get("symbol_count") or 0
    ) if isinstance(packet.get("development_data"), dict) else 0
    universe_ready = (
        not universe_error
        and bool(symbols)
        and all(_SYMBOL_PATTERN.fullmatch(item) for item in symbols)
        and (expected_symbols == 0 or len(symbols) == expected_symbols)
    )
    _check(
        checks,
        "FROZEN_UNIVERSE",
        universe_ready,
        f"Read {len(symbols)} frozen symbols from the development cache through {development_cutoff}."
        if universe_ready
        else universe_error or (
            f"Frozen symbol count mismatch: observed={len(symbols)}, expected={expected_symbols}."
        ),
    )
    adjustment_ready = adjustment in {"raw", "qfq", "hfq"}
    _check(
        checks,
        "FROZEN_ADJUSTMENT",
        adjustment_ready,
        f"Frozen price adjustment is {adjustment!r}."
        if adjustment_ready
        else "Frozen price adjustment must be raw, qfq, or hfq.",
    )

    existing_event: dict[str, Any] | None = None
    ledger_error = ""
    ledger_path = output_root / "sealed_holdout_collection.jsonl"
    try:
        events = verify_collection_ledger(ledger_path, quarantine_root=output_root)
    except (OSError, SealedHoldoutIntakeError) as exc:
        events = []
        ledger_error = f"{type(exc).__name__}: {exc}"
    else:
        existing_event = next(
            (
                event
                for event in events
                if event["trial_id"] == trial_id and event["market_date"] == requested_date
            ),
            None,
        )
        if existing_event is not None:
            retained = output_root / str(existing_event["retained_relative_path"])
            if not retained.is_file() or _file_sha256(retained) != existing_event["raw_sha256"]:
                ledger_error = "Existing collection event points to missing or changed retained bytes."
    ledger_ready = not ledger_error
    _check(
        checks,
        "QUARANTINE_LEDGER",
        ledger_ready,
        "Quarantine ledger verifies and has no conflicting retained bytes."
        if ledger_ready
        else f"Quarantine ledger cannot be trusted: {ledger_error}",
    )
    journal_error = ""
    try:
        from quantify.data.prospective_acquisition_journal import (
            ProspectiveAcquisitionJournalError,
            verify_prospective_acquisition_attempts,
        )

        verify_prospective_acquisition_attempts(output_root)
    except ProspectiveAcquisitionJournalError as exc:
        journal_error = f"{type(exc).__name__}: {exc}"
    _check(
        checks,
        "ACQUISITION_ATTEMPT_JOURNAL",
        not journal_error,
        "Prior provider-attempt reports and append-only hash chain verify."
        if not journal_error
        else f"Provider-attempt journal cannot be trusted: {journal_error}",
    )
    if reviewed_closed:
        _check(
            checks,
            "REVIEWED_MARKET_CLOSED_EMPTY",
            existing_event is None,
            "Reviewed market-closed date has no retained collection event."
            if existing_event is None
            else "A reviewed market-closed date already has retained bars and requires investigation.",
        )
    _check(
        checks,
        "NON_PERSISTENT_BOUNDARY",
        True,
        "Acquisition feed has persistence disabled and receives no storage handle.",
    )

    blockers = tuple(dict.fromkeys(item.message for item in checks if item.status == "BLOCK"))
    if blockers:
        status: AcquisitionStatus = "BLOCK"
        fetch_allowed = False
    elif existing_event is not None:
        status = "ALREADY_RETAINED"
        fetch_allowed = False
    elif reviewed_closed:
        status = "MARKET_CLOSED"
        fetch_allowed = False
    else:
        status = "READY"
        fetch_allowed = True
    return ProspectiveDailyAcquisition(
        artifact_type="prospective_daily_acquisition",
        schema_version=1,
        status=status,
        evaluated_at_utc=now.replace(microsecond=0).isoformat(),
        evaluated_market_date=market_now.date().isoformat(),
        market_timezone=MARKET_TIMEZONE,
        trial_id=trial_id,
        candidate=candidate,
        market_date=requested_date,
        test_start=test_start,
        test_end=test_end,
        development_cutoff=development_cutoff,
        development_cache_path=str(development_cache),
        quarantine_root=str(output_root),
        frozen_symbol_count=len(symbols),
        frozen_symbol_fingerprint=_symbol_fingerprint(symbols),
        price_adjustment=adjustment,
        minimum_success_ratio=minimum_success_ratio,
        requested_symbols=0,
        successful_symbols=0,
        failed_symbols=0,
        success_ratio=0.0,
        row_count=0,
        provider_routes={},
        failures=(),
        source_vendor="akshare",
        source_exported_at="",
        akshare_version=_akshare_version(),
        csv_sha256="",
        csv_bytes=b"",
        calendar_evidence_status=(
            "PASS"
            if calendar_pass
            else "BLOCK"
            if calendar_input_supplied
            else "MISSING"
        ),
        calendar_session_status=(
            "OPEN"
            if calendar_session_open is True
            else "CLOSED"
            if calendar_session_open is False
            else "UNREVIEWED"
        ),
        existing_event=existing_event,
        fetch_allowed=fetch_allowed,
        checks=tuple(checks),
        blockers=blockers,
        next_actions=_preflight_next_actions(status, requested_date),
        packet_verification=verification,
        calendar_preflight=calendar_report,
    )


def run_prospective_daily_acquisition(
    preflight: ProspectiveDailyAcquisition,
    *,
    output_dir: str | Path,
    fetch_symbol: FetchSymbol | None = None,
    max_attempts: int = 2,
    retry_delay_seconds: float = 1.0,
) -> ProspectiveDailyAcquisition:
    """Fetch the frozen universe into memory and produce deterministic CSV bytes."""
    if preflight.status != "READY" or not preflight.fetch_allowed:
        raise ValueError("prospective acquisition preflight is not READY")
    _require_quarantine_root(preflight, output_dir)
    calendar_error = _calendar_binding_error(preflight, require_open=True)
    if calendar_error:
        raise ValueError(calendar_error)
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if not math.isfinite(retry_delay_seconds) or retry_delay_seconds < 0:
        raise ValueError("retry_delay_seconds must be finite and non-negative")
    symbols, universe_error = _load_frozen_symbols(
        Path(preflight.development_cache_path),
        preflight.development_cutoff,
    )
    if universe_error or _symbol_fingerprint(symbols) != preflight.frozen_symbol_fingerprint:
        raise ValueError("frozen universe changed after preflight")

    if fetch_symbol is None:
        feed = AkshareFeed(
            None,
            adjust=preflight.price_adjustment,
            persist=False,
        )

        def default_fetch(symbol: str, start: str, end: str) -> tuple[pd.DataFrame, str]:
            frame = feed.fetch(symbol, start, end)
            return frame, str(feed.fetch_routes.get(symbol) or "unknown")

        fetch_symbol = default_fetch

    frames: list[pd.DataFrame] = []
    failures: list[SymbolAcquisitionFailure] = []
    route_counts: dict[str, int] = {}
    for symbol in symbols:
        failure_reason = ""
        for attempt in range(1, max_attempts + 1):
            try:
                frame, route = fetch_symbol(symbol, preflight.market_date, preflight.market_date)
                frame = _validated_symbol_frame(frame, symbol, preflight.market_date)
            except Exception as exc:  # noqa: BLE001 - every provider failure is retained
                failure_reason = f"{type(exc).__name__}: {exc}"
                if attempt < max_attempts and retry_delay_seconds:
                    time_module.sleep(retry_delay_seconds)
                continue
            frames.append(frame)
            route_name = str(route or "unknown")
            route_counts[route_name] = route_counts.get(route_name, 0) + 1
            break
        else:
            failures.append(
                SymbolAcquisitionFailure(symbol, max_attempts, failure_reason or "empty bars")
            )

    successful_symbols = len(symbols) - len(failures)
    success_ratio = successful_symbols / len(symbols) if symbols else 0.0
    merged = (
        pd.concat(frames, ignore_index=True).sort_values(["symbol", "date"])
        if frames
        else pd.DataFrame(columns=CANONICAL_COLUMNS)
    )
    csv_bytes = _deterministic_csv_bytes(merged) if not merged.empty else b""
    exported_at = _runtime_now().replace(microsecond=0).isoformat()
    acquisition_pass = bool(csv_bytes) and success_ratio >= preflight.minimum_success_ratio
    blockers = list(preflight.blockers)
    coverage_message = (
        "Frozen-universe provider coverage meets the required threshold: "
        f"actual={success_ratio:.2%}, required={preflight.minimum_success_ratio:.2%}."
    )
    if not acquisition_pass:
        coverage_message = (
            "Frozen-universe provider success ratio is below the required threshold: "
            f"actual={success_ratio:.2%}, required={preflight.minimum_success_ratio:.2%}."
        )
        blockers.append(coverage_message)
    status: AcquisitionStatus = "PASS" if not blockers else "BLOCK"
    return replace(
        preflight,
        status=status,
        evaluated_at_utc=exported_at,
        requested_symbols=len(symbols),
        successful_symbols=successful_symbols,
        failed_symbols=len(failures),
        success_ratio=success_ratio,
        row_count=len(merged),
        provider_routes=dict(sorted(route_counts.items())),
        failures=tuple(failures),
        source_exported_at=exported_at,
        csv_sha256=hashlib.sha256(csv_bytes).hexdigest() if csv_bytes else "",
        csv_bytes=csv_bytes,
        fetch_allowed=False,
        checks=(
            *preflight.checks,
            AcquisitionCheck(
                "PROVIDER_COVERAGE",
                "PASS" if acquisition_pass else "BLOCK",
                coverage_message,
            ),
        ),
        blockers=tuple(dict.fromkeys(blockers)),
        next_actions=_acquisition_next_actions(status),
    )


def handoff_prospective_daily_acquisition(
    acquisition: ProspectiveDailyAcquisition,
    *,
    packet_dir: str | Path,
    trial_registry_path: str | Path,
    output_dir: str | Path,
) -> SealedHoldoutIntakeReport:
    """Persist a PASS acquisition manifest/CSV and hand it to sealed intake."""
    if acquisition.status != "PASS" or not acquisition.csv_bytes:
        raise ValueError("only PASS acquisition evidence can enter sealed intake")
    _require_quarantine_root(acquisition, output_dir)
    calendar_error = _calendar_binding_error(acquisition, require_open=True)
    if calendar_error:
        raise ValueError(calendar_error)
    output_root = Path(output_dir).resolve()
    inputs = output_root / "acquisition_inputs"
    manifests = output_root / "acquisition_reports"
    inputs.mkdir(parents=True, exist_ok=True)
    manifests.mkdir(parents=True, exist_ok=True)
    stem = f"{acquisition.market_date}_{acquisition.csv_sha256[:16]}"
    csv_path = inputs / f"{stem}.csv"
    manifest_path = manifests / f"{stem}.json"
    _write_exact_file(csv_path, acquisition.csv_bytes, acquisition.csv_sha256)
    manifest_sha256 = _write_acquisition_manifest(acquisition, manifest_path)
    (manifests / f"{stem}.md").write_text(acquisition.to_markdown(), encoding="utf-8")
    intake = build_sealed_holdout_intake(
        packet_dir=packet_dir,
        trial_registry_path=trial_registry_path,
        daily_bars_csv=csv_path,
        output_dir=output_root,
        source_vendor="akshare",
        source_reference=f"{manifest_path}|sha256={manifest_sha256}",
        source_exported_at=acquisition.source_exported_at,
        price_adjustment=acquisition.price_adjustment,
    )
    return retain_sealed_holdout_intake(
        intake,
        daily_bars_csv=csv_path,
        output_dir=output_root,
    )


def write_prospective_daily_acquisition(
    report: ProspectiveDailyAcquisition,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "prospective_daily_acquisition.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, allow_nan=False, indent=2),
        encoding="utf-8",
    )
    (root / "prospective_daily_acquisition.md").write_text(
        report.to_markdown(),
        encoding="utf-8",
    )
    return root


def _validated_symbol_frame(frame: pd.DataFrame, symbol: str, market_date: str) -> pd.DataFrame:
    if frame.empty:
        raise ValueError("provider returned empty bars")
    missing = [column for column in CANONICAL_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError("provider frame is missing columns: " + ", ".join(missing))
    selected = frame[list(CANONICAL_COLUMNS)].copy()
    selected["symbol"] = selected["symbol"].astype(str).str.zfill(6)
    selected["date"] = selected["date"].astype(str)
    if set(selected["symbol"]) != {symbol} or set(selected["date"]) != {market_date}:
        raise ValueError("provider frame symbol/date does not match the frozen request")
    if selected.duplicated(["symbol", "date"]).any() or len(selected) != 1:
        raise ValueError("provider must return exactly one unique daily row per symbol")
    for column in CANONICAL_COLUMNS[2:]:
        selected[column] = pd.to_numeric(selected[column], errors="coerce")
    if selected[list(CANONICAL_COLUMNS[2:])].isna().any().any():
        raise ValueError("provider frame contains invalid numeric values")
    values = selected.iloc[0]
    numbers = [float(values[column]) for column in CANONICAL_COLUMNS[2:]]
    if not all(math.isfinite(value) for value in numbers):
        raise ValueError("provider frame contains non-finite values")
    open_, high, low, close, volume, amount = numbers
    if min(open_, high, low, close) <= 0 or high < max(open_, low, close) or low > min(
        open_, high, close
    ):
        raise ValueError("provider frame violates OHLC constraints")
    if volume < 0 or amount < 0:
        raise ValueError("provider frame volume/amount must be non-negative")
    return selected


def _deterministic_csv_bytes(frame: pd.DataFrame) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CANONICAL_COLUMNS)
    for row in frame[list(CANONICAL_COLUMNS)].itertuples(index=False, name=None):
        writer.writerow([str(row[0]), str(row[1]), *[_float_text(value) for value in row[2:]]])
    return buffer.getvalue().encode("utf-8")


def _float_text(value: Any) -> str:
    return format(float(value), ".17g")


def _load_frozen_symbols(cache: Path, cutoff: str) -> tuple[list[str], str]:
    if not cache.is_file():
        return [], f"Development cache does not exist: {cache}."
    try:
        uri = cache.resolve().as_posix()
        with sqlite3.connect(f"file:{uri}?mode=ro", uri=True) as conn:
            rows = conn.execute(
                "SELECT DISTINCT symbol FROM bars WHERE date <= ? ORDER BY symbol COLLATE BINARY",
                (cutoff,),
            ).fetchall()
    except sqlite3.Error as exc:
        return [], f"Frozen symbols cannot be read from SQLite: {exc}."
    symbols = [str(row[0]).strip().zfill(6) for row in rows]
    return symbols, ""


def _result_count(path: Path, trial_id: str) -> tuple[int, str]:
    try:
        events = verify_registry(path)
    except (OSError, TrialRegistryError) as exc:
        return 0, f"Registry cannot be verified: {type(exc).__name__}: {exc}."
    preregistrations = sum(
        isinstance(event, PreregistrationEvent) and event.trial_id == trial_id
        for event in events
    )
    if preregistrations != 1:
        return 0, f"Expected one preregistration, found {preregistrations}."
    return sum(
        isinstance(event, ResultEvent) and event.trial_id == trial_id for event in events
    ), ""


def _development_cache_path(packet: dict[str, Any], root: Path) -> Path:
    development = packet.get("development_data")
    raw = _text(development.get("cache_path")) if isinstance(development, dict) else ""
    return _resolve_path(raw or "__missing_development_cache__", root)


def _frozen_adjustment(packet: dict[str, Any]) -> str:
    execution = packet.get("execution_config")
    data = execution.get("data") if isinstance(execution, dict) else None
    return _text(data.get("adjust")).lower() if isinstance(data, dict) else ""


def _boundary_text(boundaries: dict[str, Any], section: str, field: str) -> str:
    value = boundaries.get(section)
    return _text(value.get(field)) if isinstance(value, dict) else ""


def _post_close(observed: date | None, market_now: datetime) -> bool:
    if observed is None or observed > market_now.date():
        return False
    return observed < market_now.date() or market_now.time().replace(tzinfo=None) >= time(15, 30)


def _symbol_fingerprint(symbols: list[str]) -> str:
    return hashlib.sha256(("\n".join(symbols) + "\n").encode("ascii")).hexdigest() if symbols else ""


def _write_exact_file(path: Path, payload: bytes, expected_sha256: str) -> None:
    if path.exists():
        if not path.is_file() or _file_sha256(path) != expected_sha256:
            raise OSError(f"Acquisition input path already exists with different bytes: {path}")
        return
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            if handle.write(payload) != len(payload):  # pragma: no cover - filesystem failure
                raise OSError("short acquisition-input write")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_acquisition_manifest(report: ProspectiveDailyAcquisition, path: Path) -> str:
    payload = json.dumps(report.to_dict(), ensure_ascii=False, allow_nan=False, indent=2)
    encoded = payload.encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    _write_exact_file(path, encoded, digest)
    return digest


def _require_quarantine_root(
    report: ProspectiveDailyAcquisition,
    output_dir: str | Path,
) -> None:
    expected = Path(report.quarantine_root).resolve()
    actual = Path(output_dir).resolve()
    if actual != expected:
        raise ValueError(
            f"output_dir changed after preflight: expected={expected}, actual={actual}"
        )


def _calendar_binding_error(
    report: ProspectiveDailyAcquisition,
    *,
    require_open: bool,
) -> str:
    if report.calendar_evidence_status == "MISSING":
        return ""
    retained = report.calendar_preflight
    if report.calendar_evidence_status != "PASS" or retained is None:
        return "reviewed calendar evidence is not PASS"
    fresh = build_exchange_calendar_preflight(
        retained.calendar_csv_path,
        retained.metadata_path,
        required_start_date=report.market_date,
        required_end_date=report.market_date,
    )
    if fresh.status != "PASS":
        return "reviewed calendar evidence changed or no longer passes strict preflight"
    if (
        fresh.csv_sha256 != retained.csv_sha256
        or fresh.metadata_sha256 != retained.metadata_sha256
    ):
        return "reviewed calendar evidence hashes changed after acquisition preflight"
    session = next(
        (item for item in fresh.sessions if str(item["date"]) == report.market_date),
        None,
    )
    if session is None or not isinstance(session.get("is_open"), bool):
        return "reviewed calendar no longer contains the requested market date"
    if require_open and session["is_open"] is not True:
        return "provider acquisition requires a reviewed open market session"
    return ""


def _preflight_next_actions(status: AcquisitionStatus, market_date: str) -> tuple[str, ...]:
    if status == "READY":
        return (f"Fetch the frozen universe for {market_date} into a scratch cache, then quarantine the deterministic CSV.",)
    if status == "ALREADY_RETAINED":
        return ("Do not refetch or replace this date; verify the existing quarantine event.",)
    if status == "MARKET_CLOSED":
        return (
            f"Retain the reviewed calendar evidence for {market_date}; do not call the provider or create synthetic bars.",
        )
    return (
        "Resolve the deterministic preflight blockers; do not call the provider while fetch_allowed is false.",
    )


def _acquisition_next_actions(status: AcquisitionStatus) -> tuple[str, ...]:
    if status == "PASS":
        return (
            "Write the immutable acquisition manifest and hand the exact CSV to sealed quarantine.",
            "Do not inspect candidate results or write the frozen execution cache.",
        )
    return (
        "Review provider failures and retry after fixing connectivity or route coverage.",
        "Do not quarantine an acquisition below the required frozen-universe success ratio.",
    )


def _check(
    checks: list[AcquisitionCheck],
    code: str,
    passed: bool,
    message: str,
) -> None:
    checks.append(AcquisitionCheck(code, "PASS" if passed else "BLOCK", message))


def _load_json_object(path: Path) -> tuple[dict[str, Any], str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {}, f"{type(exc).__name__}: {exc}"
    return (payload, "") if isinstance(payload, dict) else ({}, "packet root is not an object")


def _iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _akshare_version() -> str:
    try:
        return version("akshare")
    except PackageNotFoundError:
        return "unknown"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _workspace_root(value: str | Path | None) -> Path:
    return Path(value).resolve() if value is not None else Path(__file__).resolve().parents[3]


def _resolve_path(value: str | Path, root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _runtime_now() -> datetime:
    return datetime.now(UTC)
