"""Read-only continuity status for sealed prospective daily collection."""

from __future__ import annotations

from collections.abc import Sequence
import csv
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
import json
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from quantify.data.exchange_calendar_preflight import (
    ExchangeCalendarPreflight,
    build_exchange_calendar_preflight,
)
from quantify.data.prospective_acquisition_journal import (
    ProspectiveAcquisitionJournalError,
    verify_prospective_acquisition_attempts,
)
from quantify.research.prospective_trial_packet import (
    ProspectiveTrialPacketVerification,
    build_prospective_trial_packet_verification,
)
from quantify.research.sealed_holdout_intake import (
    SealedHoldoutIntakeError,
    verify_collection_ledger,
)
from quantify.research.trial_registry import (
    PreregistrationEvent,
    ResultEvent,
    TrialRegistryError,
    verify_registry,
)

CollectionStatus = Literal["PASS", "WATCH", "BLOCK", "NOT_DUE"]
MARKET_TIMEZONE = "Asia/Shanghai"

PROHIBITED_ACTIONS = (
    "Do not interpret candidate weekdays as reviewed exchange-calendar evidence.",
    "Do not skip an unresolved candidate weekday silently; collect it or retain reviewed closure evidence.",
    "Do not inspect candidate results, write the execution cache, or open the holdout from this status report.",
    "Do not interpret provider-attempt counts or coverage as candidate-performance evidence.",
    "Do not use collection continuity as source-QA, strategy, paper, or live-trading approval.",
    "Do not connect this workflow to a broker or generate orders.",
)


@dataclass(frozen=True, slots=True)
class CollectionStatusCheck:
    code: str
    status: Literal["PASS", "WATCH", "BLOCK"]
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "status": self.status, "message": self.message}


@dataclass(frozen=True, slots=True)
class ProspectiveCollectionStatus:
    artifact_type: str
    schema_version: int
    status: CollectionStatus
    evaluated_at_utc: str
    evaluated_market_date: str
    market_timezone: str
    trial_id: str
    candidate: str
    test_start: str
    test_end: str
    finalized_through: str
    calendar_evidence_status: str
    calendar_model: str
    due_candidate_weekdays: tuple[str, ...]
    retained_dates: tuple[str, ...]
    unresolved_dates: tuple[str, ...]
    unexpected_dates: tuple[str, ...]
    coverage_complete_through: str
    earliest_unresolved_date: str
    next_candidate_date: str
    retained_event_count: int
    attempt_journal_status: str
    attempt_event_count: int
    attempt_journal_tail_hash: str
    latest_attempt: dict[str, Any] | None
    quarantine_root: str
    ledger_path: str
    quarantine_coverage_current: bool
    execution_cache_write_allowed: bool
    holdout_analysis_allowed: bool
    promotion_eligible: bool
    paper_trading_allowed: bool
    live_trading_allowed: bool
    checks: tuple[CollectionStatusCheck, ...]
    blockers: tuple[str, ...]
    next_actions: tuple[str, ...]
    next_command: str
    timeline: tuple[dict[str, Any], ...]
    prohibited_actions: tuple[str, ...]
    packet_verification: ProspectiveTrialPacketVerification
    calendar_preflight: ExchangeCalendarPreflight | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "schema_version": self.schema_version,
            "operation": "read_only_prospective_collection_continuity",
            "network_access": False,
            "broker_access": False,
            "status": self.status,
            "evaluated_at_utc": self.evaluated_at_utc,
            "evaluated_market_date": self.evaluated_market_date,
            "market_timezone": self.market_timezone,
            "trial_id": self.trial_id,
            "candidate": self.candidate,
            "test_interval": {"start": self.test_start, "end": self.test_end},
            "finalized_through": self.finalized_through,
            "calendar_evidence_status": self.calendar_evidence_status,
            "calendar_model": self.calendar_model,
            "due_candidate_weekdays": list(self.due_candidate_weekdays),
            "retained_dates": list(self.retained_dates),
            "unresolved_dates": list(self.unresolved_dates),
            "unexpected_dates": list(self.unexpected_dates),
            "coverage_complete_through": self.coverage_complete_through,
            "earliest_unresolved_date": self.earliest_unresolved_date,
            "next_candidate_date": self.next_candidate_date,
            "retained_event_count": self.retained_event_count,
            "attempt_journal_status": self.attempt_journal_status,
            "attempt_event_count": self.attempt_event_count,
            "attempt_journal_tail_hash": self.attempt_journal_tail_hash,
            "latest_attempt": self.latest_attempt,
            "quarantine_root": self.quarantine_root,
            "ledger_path": self.ledger_path,
            "quarantine_coverage_current": self.quarantine_coverage_current,
            "execution_cache_write_allowed": self.execution_cache_write_allowed,
            "holdout_analysis_allowed": self.holdout_analysis_allowed,
            "promotion_eligible": self.promotion_eligible,
            "paper_trading_allowed": self.paper_trading_allowed,
            "live_trading_allowed": self.live_trading_allowed,
            "checks": [item.to_dict() for item in self.checks],
            "blockers": list(self.blockers),
            "next_actions": list(self.next_actions),
            "next_command": self.next_command,
            "timeline": list(self.timeline),
            "prohibited_actions": list(self.prohibited_actions),
            "packet_verification": self.packet_verification.to_dict(),
            "calendar_preflight": (
                self.calendar_preflight.to_dict() if self.calendar_preflight else None
            ),
        }

    def to_markdown(self) -> str:
        continuity_label = (
            "reviewed open sessions"
            if self.calendar_evidence_status == "PASS"
            else "candidate weekdays"
        )
        evidence_note = (
            "Reviewed exchange-calendar evidence determines open sessions and explicit "
            "market closures; PASS remains a collection-continuity result only."
            if self.calendar_evidence_status == "PASS"
            else "Candidate weekdays are a conservative continuity model, not proof of an "
            "open exchange session. Formal PASS requires reviewed calendar evidence."
        )
        lines = [
            f"# Prospective Collection Status: {self.status}",
            "",
            f"- Trial: `{self.trial_id or 'unavailable'}`",
            f"- Candidate: `{self.candidate or 'unavailable'}`",
            f"- Market date: `{self.evaluated_market_date}` ({self.market_timezone})",
            f"- Finalized through: `{self.finalized_through or 'none'}`",
            f"- Calendar evidence: `{self.calendar_evidence_status}`",
            f"- Retained dates: `{len(self.retained_dates)}`",
            f"- Provider attempt journal: `{self.attempt_journal_status}`",
            f"- Provider attempt events: `{self.attempt_event_count}`",
            f"- Provider attempt tail: `{self.attempt_journal_tail_hash or 'none'}`",
            f"- Unresolved {continuity_label}: `{len(self.unresolved_dates)}`",
            f"- Coverage complete through: `{self.coverage_complete_through or 'none'}`",
            f"- Earliest unresolved: `{self.earliest_unresolved_date or 'none'}`",
            f"- Next candidate date: `{self.next_candidate_date or 'none'}`",
            f"- Execution-cache write allowed: `{self.execution_cache_write_allowed}`",
            f"- Holdout analysis allowed: `{self.holdout_analysis_allowed}`",
            "",
            evidence_note,
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
        lines.extend(["", "## Next Command", "", "```powershell"])
        lines.append(self.next_command or "# No collection command is currently due.")
        lines.extend(["```", "", "## Timeline", ""])
        lines.append(
            "| date | state | retained | attempts | latest attempt | coverage | "
            "calendar confirmation required |"
        )
        lines.append("| --- | --- | --- | ---: | --- | --- | --- |")
        for row in self.timeline:
            lines.append(
                f"| {row['date']} | {row['state']} | {row['retained']} | "
                f"{row['attempt_count']} | {row['latest_attempt_status'] or '-'} | "
                f"{row['latest_attempt_coverage'] or '-'} | "
                f"{row['calendar_confirmation_required']} |"
            )
        lines.extend(["", "## Prohibited Actions", ""])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        lines.append("")
        return "\n".join(lines)


def build_prospective_collection_status(
    *,
    packet_dir: str | Path,
    trial_registry_path: str | Path,
    quarantine_root: str | Path,
    calendar_csv: str | Path | None = None,
    calendar_metadata: str | Path | None = None,
    workspace_root: str | Path | None = None,
) -> ProspectiveCollectionStatus:
    """Verify continuity without reading bar values or contacting a provider."""
    root = _workspace_root(workspace_root)
    packet_root = _resolve_path(packet_dir, root)
    registry_path = _resolve_path(trial_registry_path, root)
    quarantine = _resolve_path(quarantine_root, root)
    ledger_path = quarantine / "sealed_holdout_collection.jsonl"
    now = _runtime_now()
    market_now = now.astimezone(ZoneInfo(MARKET_TIMEZONE))
    finalized_date = (
        market_now.date()
        if market_now.time().replace(tzinfo=None) >= time(15, 30)
        else market_now.date() - timedelta(days=1)
    )

    packet, packet_error = _load_json_object(packet_root / "prospective_trial_packet.json")
    verification = build_prospective_trial_packet_verification(
        packet_root,
        registry_path,
        workspace_root=root,
    )
    trial_id = _text(packet.get("trial_id"))
    candidate = _text(packet.get("candidate"))
    boundaries = packet.get("boundaries") if isinstance(packet.get("boundaries"), dict) else {}
    test_start = _boundary_text(boundaries, "test", "start")
    test_end = _boundary_text(boundaries, "test", "end")
    start_date = _iso_date(test_start)
    end_date = _iso_date(test_end)

    checks: list[CollectionStatusCheck] = []
    _check(
        checks,
        "PACKET_INTEGRITY",
        "PASS" if not packet_error and verification.status == "PASS" else "BLOCK",
        "Frozen packet, code, config, prefix, and registry binding verify."
        if not packet_error and verification.status == "PASS"
        else "Frozen packet integrity or registry binding does not verify.",
    )
    result_count, registry_error = _result_count(registry_path, trial_id)
    _check(
        checks,
        "TERMINAL_RESULT_ABSENT",
        "PASS" if not registry_error and result_count == 0 else "BLOCK",
        "Registry contains one preregistration and no terminal result."
        if not registry_error and result_count == 0
        else registry_error or f"Trial already has {result_count} terminal result event(s).",
    )

    ledger_error = ""
    try:
        events = verify_collection_ledger(ledger_path, quarantine_root=quarantine)
    except (OSError, SealedHoldoutIntakeError) as exc:
        events = []
        ledger_error = f"{type(exc).__name__}: {exc}"
    retained_dates = tuple(
        sorted(
            {
                str(event["market_date"])
                for event in events
                if event["trial_id"] == trial_id
            }
        )
    )
    _check(
        checks,
        "QUARANTINE_LEDGER",
        "PASS" if not ledger_error else "BLOCK",
        f"Verified {len(retained_dates)} retained date event(s) and their referenced files."
        if not ledger_error
        else f"Quarantine ledger cannot be verified: {ledger_error}",
    )

    attempt_error = ""
    try:
        all_attempt_events = verify_prospective_acquisition_attempts(quarantine)
    except ProspectiveAcquisitionJournalError as exc:
        all_attempt_events = []
        attempt_error = f"{type(exc).__name__}: {exc}"
    attempt_events = tuple(
        event for event in all_attempt_events if event["trial_id"] == trial_id
    )
    attempts_by_date: dict[str, list[dict[str, Any]]] = {}
    for event in attempt_events:
        attempts_by_date.setdefault(str(event["market_date"]), []).append(event)
    _check(
        checks,
        "ACQUISITION_ATTEMPT_JOURNAL",
        "PASS" if not attempt_error else "BLOCK",
        f"Verified {len(attempt_events)} provider-attempt event(s) and immutable reports."
        if not attempt_error
        else f"Provider-attempt journal cannot be verified: {attempt_error}",
    )

    calendar_report: ExchangeCalendarPreflight | None = None
    calendar_input_supplied = calendar_csv is not None or calendar_metadata is not None
    calendar_pair_ready = (calendar_csv is None) == (calendar_metadata is None)
    if not calendar_pair_ready:
        _check(
            checks,
            "REVIEWED_CALENDAR_INPUT_PAIR",
            "BLOCK",
            "Calendar CSV and metadata must be supplied together.",
        )
    elif calendar_csv is not None and calendar_metadata is not None:
        required_end = min(end_date, finalized_date) if end_date is not None else finalized_date
        if start_date is not None and required_end >= start_date:
            calendar_report = build_exchange_calendar_preflight(
                _resolve_path(calendar_csv, root),
                _resolve_path(calendar_metadata, root),
                required_start_date=start_date.isoformat(),
                required_end_date=required_end.isoformat(),
            )
            _check(
                checks,
                "REVIEWED_CALENDAR_EVIDENCE",
                "PASS" if calendar_report.status == "PASS" else "BLOCK",
                "Reviewed exchange calendar passes strict preflight."
                if calendar_report.status == "PASS"
                else "Reviewed exchange calendar preflight is BLOCK.",
            )
    if calendar_report is None and calendar_pair_ready:
        _check(
            checks,
            "REVIEWED_CALENDAR_EVIDENCE",
            "WATCH",
            "Reviewed exchange-calendar evidence is not yet attached; weekdays remain candidates only.",
        )

    calendar_pass = calendar_report is not None and calendar_report.status == "PASS"
    if calendar_pass:
        reviewed_sessions = [
            item
            for item in calendar_report.sessions
            if start_date is not None
            and end_date is not None
            and start_date <= date.fromisoformat(str(item["date"])) <= end_date
        ]
        reviewed_open_dates = [
            str(item["date"]) for item in reviewed_sessions if item["is_open"] is True
        ]
        due_dates = [item for item in reviewed_open_dates if item <= finalized_date.isoformat()]
        all_candidate_dates = list(reviewed_open_dates)
        declared_end = _iso_date(calendar_report.declared_end_date)
        fallback_start = declared_end + timedelta(days=1) if declared_end is not None else start_date
        if fallback_start is not None and end_date is not None and fallback_start <= end_date:
            all_candidate_dates.extend(_candidate_weekdays(fallback_start, end_date))
        all_candidate_dates = list(dict.fromkeys(all_candidate_dates))
    else:
        reviewed_sessions = []
        due_dates = _candidate_weekdays(
            start_date,
            min(end_date, finalized_date) if end_date is not None else None,
        )
        all_candidate_dates = _candidate_weekdays(start_date, end_date)
    invalid_attempt_dates = tuple(
        sorted(
            date_text
            for date_text in attempts_by_date
            if start_date is None
            or end_date is None
            or not start_date <= date.fromisoformat(date_text) <= end_date
            or date_text > finalized_date.isoformat()
        )
    )
    reviewed_closed_dates = {
        str(item["date"])
        for item in reviewed_sessions
        if item["is_open"] is not True
    }
    reviewed_closed_attempt_dates = tuple(
        sorted(date_text for date_text in attempts_by_date if date_text in reviewed_closed_dates)
    )
    _check(
        checks,
        "ATTEMPT_DATES_FINALIZED_AND_INSIDE_FROZEN_INTERVAL",
        "PASS" if not invalid_attempt_dates else "BLOCK",
        "All provider attempts are finalized and inside the frozen prospective test interval."
        if not invalid_attempt_dates
        else "Provider attempts outside the frozen/finalized interval: "
        + ", ".join(invalid_attempt_dates[:10])
        + ".",
    )
    if calendar_pass:
        _check(
            checks,
            "REVIEWED_CLOSED_DATES_HAVE_NO_ATTEMPTS",
            "PASS" if not reviewed_closed_attempt_dates else "BLOCK",
            "Reviewed market-closed dates have no provider attempts."
            if not reviewed_closed_attempt_dates
            else "Provider attempts exist on reviewed market-closed dates: "
            + ", ".join(reviewed_closed_attempt_dates[:10])
            + ".",
        )
    retained = set(retained_dates)
    unresolved = tuple(item for item in due_dates if item not in retained)
    unexpected = tuple(
        sorted(item for item in retained if item not in set(all_candidate_dates) or item > finalized_date.isoformat())
    )
    continuity_status: Literal["PASS", "BLOCK"] = "PASS" if not unresolved else "BLOCK"
    continuity_subject = (
        "finalized reviewed open session(s)"
        if calendar_pass
        else "finalized candidate weekday(s)"
    )
    _check(
        checks,
        "DUE_WEEKDAY_CONTINUITY",
        continuity_status,
        f"All {len(due_dates)} {continuity_subject} are retained."
        if not unresolved
        else f"Missing {len(unresolved)} {continuity_subject}; earliest={unresolved[0]}.",
    )
    _check(
        checks,
        "UNEXPECTED_RETAINED_DATES",
        "PASS" if not unexpected else "BLOCK",
        "No retained event is outside the frozen/finalized candidate weekday range."
        if not unexpected
        else "Unexpected retained dates: " + ", ".join(unexpected[:10]) + ".",
    )
    coverage_complete_through = ""
    for item in due_dates:
        if item not in retained:
            break
        coverage_complete_through = item
    next_candidate = next(
        (item for item in all_candidate_dates if item > finalized_date.isoformat()),
        "",
    )
    if calendar_pass:
        timeline_rows = [
            _reviewed_timeline_row(
                item,
                retained=str(item["date"]) in retained,
                finalized=str(item["date"]) <= finalized_date.isoformat(),
                current_market_date=market_now.date().isoformat(),
                attempts=attempts_by_date.get(str(item["date"]), ()),
            )
            for item in reviewed_sessions
        ]
        reviewed_dates = {str(item["date"]) for item in reviewed_sessions}
        timeline_rows.extend(
            _timeline_row(
                item,
                retained=item in retained,
                finalized=item <= finalized_date.isoformat(),
                current_market_date=market_now.date().isoformat(),
                attempts=attempts_by_date.get(item, ()),
            )
            for item in all_candidate_dates
            if item not in reviewed_dates
        )
        timeline = tuple(sorted(timeline_rows, key=lambda item: str(item["date"])))
    else:
        timeline = tuple(
            _timeline_row(
                item,
                retained=item in retained,
                finalized=item <= finalized_date.isoformat(),
                current_market_date=market_now.date().isoformat(),
                attempts=attempts_by_date.get(item, ()),
            )
            for item in all_candidate_dates
        )
    hard_blockers = tuple(
        dict.fromkeys(item.message for item in checks if item.status == "BLOCK")
    )
    pre_holdout_not_due = start_date is not None and finalized_date < start_date
    if hard_blockers:
        status: CollectionStatus = "BLOCK"
    elif pre_holdout_not_due:
        status = "NOT_DUE"
    elif calendar_pass:
        status = "PASS"
    else:
        status = "WATCH"
    earliest = unresolved[0] if unresolved else ""
    next_command_date = earliest or next_candidate
    command_has_reviewed_session = calendar_pass and any(
        str(item["date"]) == next_command_date for item in reviewed_sessions
    )
    next_command = _next_command(
        packet_root,
        registry_path,
        quarantine,
        next_command_date,
        calendar_csv=(
            _resolve_path(calendar_csv, root)
            if command_has_reviewed_session and calendar_csv is not None
            else None
        ),
        calendar_metadata=(
            _resolve_path(calendar_metadata, root)
            if command_has_reviewed_session and calendar_metadata is not None
            else None
        ),
    ) if next_command_date else ""
    return ProspectiveCollectionStatus(
        artifact_type="prospective_collection_status",
        schema_version=2,
        status=status,
        evaluated_at_utc=now.replace(microsecond=0).isoformat(),
        evaluated_market_date=market_now.date().isoformat(),
        market_timezone=MARKET_TIMEZONE,
        trial_id=trial_id,
        candidate=candidate,
        test_start=test_start,
        test_end=test_end,
        finalized_through=finalized_date.isoformat(),
        calendar_evidence_status=(
            "PASS"
            if calendar_pass
            else "BLOCK"
            if calendar_input_supplied
            else "MISSING"
        ),
        calendar_model=(
            "reviewed_exchange_calendar"
            if calendar_pass
            else "weekday_candidates_not_reviewed_exchange_sessions"
        ),
        due_candidate_weekdays=tuple(due_dates),
        retained_dates=retained_dates,
        unresolved_dates=unresolved,
        unexpected_dates=unexpected,
        coverage_complete_through=coverage_complete_through,
        earliest_unresolved_date=earliest,
        next_candidate_date=next_candidate,
        retained_event_count=len(retained_dates),
        attempt_journal_status="PASS" if not attempt_error else "BLOCK",
        attempt_event_count=len(attempt_events),
        attempt_journal_tail_hash=(
            str(all_attempt_events[-1]["event_hash"]) if all_attempt_events else ""
        ),
        latest_attempt=attempt_events[-1] if attempt_events else None,
        quarantine_root=str(quarantine),
        ledger_path=str(ledger_path),
        quarantine_coverage_current=not unresolved and not hard_blockers,
        execution_cache_write_allowed=False,
        holdout_analysis_allowed=False,
        promotion_eligible=False,
        paper_trading_allowed=False,
        live_trading_allowed=False,
        checks=tuple(checks),
        blockers=hard_blockers,
        next_actions=_next_actions(
            status,
            earliest,
            next_candidate,
            calendar_pass=calendar_pass,
            earliest_attempt=(
                attempts_by_date[earliest][-1]
                if earliest and attempts_by_date.get(earliest)
                else None
            ),
        ),
        next_command=next_command,
        timeline=timeline,
        prohibited_actions=PROHIBITED_ACTIONS,
        packet_verification=verification,
        calendar_preflight=calendar_report,
    )


def write_prospective_collection_status(
    report: ProspectiveCollectionStatus,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "prospective_collection_status.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, allow_nan=False, indent=2),
        encoding="utf-8",
    )
    (root / "prospective_collection_status.md").write_text(
        report.to_markdown(),
        encoding="utf-8",
    )
    with (root / "prospective_collection_timeline.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "date",
                "state",
                "retained",
                "attempt_count",
                "latest_attempt_status",
                "latest_attempt_at_utc",
                "latest_attempt_coverage",
                "calendar_confirmation_required",
            ),
        )
        writer.writeheader()
        writer.writerows(report.timeline)
    return root


def _candidate_weekdays(start: date | None, end: date | None) -> list[str]:
    if start is None or end is None or end < start:
        return []
    output: list[str] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            output.append(current.isoformat())
        current += timedelta(days=1)
    return output


def _timeline_row(
    date_text: str,
    *,
    retained: bool,
    finalized: bool,
    current_market_date: str,
    attempts: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    if retained:
        state = "RETAINED_QUARANTINE"
    elif not finalized:
        state = "FUTURE_CANDIDATE"
    elif date_text == current_market_date:
        state = "DUE_UNRESOLVED"
    else:
        state = "OVERDUE_UNRESOLVED"
    return {
        "date": date_text,
        "state": state,
        "retained": retained,
        **_attempt_timeline_fields(attempts),
        "calendar_confirmation_required": True,
    }


def _reviewed_timeline_row(
    session: dict[str, Any],
    *,
    retained: bool,
    finalized: bool,
    current_market_date: str,
    attempts: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    date_text = str(session["date"])
    if session["is_open"] is not True:
        state = "REVIEWED_MARKET_CLOSED"
    elif retained:
        state = "RETAINED_QUARANTINE"
    elif not finalized:
        state = "FUTURE_REVIEWED_SESSION"
    elif date_text == current_market_date:
        state = "DUE_UNRESOLVED"
    else:
        state = "OVERDUE_UNRESOLVED"
    return {
        "date": date_text,
        "state": state,
        "retained": retained,
        **_attempt_timeline_fields(attempts),
        "calendar_confirmation_required": False,
    }


def _attempt_timeline_fields(
    attempts: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    latest = attempts[-1] if attempts else None
    return {
        "attempt_count": len(attempts),
        "latest_attempt_status": str(latest["status"]) if latest else "",
        "latest_attempt_at_utc": str(latest["attempted_at_utc"]) if latest else "",
        "latest_attempt_coverage": (
            f"{latest['successful_symbols']}/{latest['requested_symbols']}"
            if latest
            else ""
        ),
    }


def _next_actions(
    status: CollectionStatus,
    earliest_unresolved: str,
    next_candidate: str,
    *,
    calendar_pass: bool,
    earliest_attempt: dict[str, Any] | None,
) -> tuple[str, ...]:
    if status == "BLOCK" and earliest_unresolved:
        if earliest_attempt is not None and earliest_attempt["status"] == "BLOCK":
            return (
                f"Latest provider attempt for {earliest_unresolved} is BLOCK at "
                f"{earliest_attempt['successful_symbols']}/{earliest_attempt['requested_symbols']} symbols; inspect its immutable attempt report before retrying.",
                "Do not skip to a later date while this continuity gap remains unresolved.",
            )
        if earliest_attempt is not None and earliest_attempt["status"] == "PASS":
            return (
                f"Provider coverage for {earliest_unresolved} passed but no sealed collection event exists; investigate the handoff before refetching.",
                "Do not skip to a later date while this continuity gap remains unresolved.",
            )
        return (
            f"Resolve candidate weekday {earliest_unresolved}: retain finalized bars or reviewed market-closure evidence.",
            "Do not skip to a later date while this continuity gap remains unresolved.",
        )
    if status == "NOT_DUE":
        return (
            f"Wait until after 15:30 Asia/Shanghai on {next_candidate or 'the first test date'} before collection.",
        )
    if calendar_pass:
        return (
            "Reviewed exchange-calendar continuity is current; wait for the next reviewed open session's post-close collection window.",
            "Keep the calendar evidence hash-bound and extend reviewed coverage before its declared end is exhausted.",
        )
    return (
        "Candidate weekday continuity is current; wait for the next post-close collection window.",
        "Acquire reviewed exchange-calendar evidence before claiming formal coverage PASS.",
    )


def _next_command(
    packet_dir: Path,
    registry_path: Path,
    quarantine_root: Path,
    market_date: str,
    *,
    calendar_csv: Path | None,
    calendar_metadata: Path | None,
) -> str:
    command = (
        ".\\.venv\\Scripts\\python.exe examples\\run_prospective_daily_acquisition.py "
        f'--packet-dir "{packet_dir}" --registry "{registry_path}" '
        f"--market-date {market_date} "
    )
    if calendar_csv is not None and calendar_metadata is not None:
        command += (
            f'--calendar-csv "{calendar_csv}" '
            f'--calendar-metadata "{calendar_metadata}" '
        )
    return command + (
        "--minimum-success-ratio 0.95 "
        f'--output-dir "{quarantine_root}"'
    )


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


def _check(
    checks: list[CollectionStatusCheck],
    code: str,
    status: Literal["PASS", "WATCH", "BLOCK"],
    message: str,
) -> None:
    checks.append(CollectionStatusCheck(code, status, message))


def _load_json_object(path: Path) -> tuple[dict[str, Any], str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {}, f"{type(exc).__name__}: {exc}"
    return (payload, "") if isinstance(payload, dict) else ({}, "packet root is not an object")


def _boundary_text(boundaries: dict[str, Any], section: str, field: str) -> str:
    value = boundaries.get(section)
    return _text(value.get(field)) if isinstance(value, dict) else ""


def _iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _workspace_root(value: str | Path | None) -> Path:
    return Path(value).resolve() if value is not None else Path(__file__).resolve().parents[3]


def _resolve_path(value: str | Path, root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _runtime_now() -> datetime:
    return datetime.now(UTC)
