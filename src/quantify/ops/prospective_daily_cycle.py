"""One-command, explicit-execution cycle for sealed prospective collection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Literal

from quantify.data.prospective_daily_acquisition import (
    FetchSymbol,
    ProspectiveDailyAcquisition,
    build_prospective_daily_acquisition_preflight,
    handoff_prospective_daily_acquisition,
    run_prospective_daily_acquisition,
    write_prospective_daily_acquisition,
)
from quantify.data.prospective_acquisition_journal import (
    record_prospective_acquisition_attempt,
)
from quantify.research.prospective_collection_status import (
    ProspectiveCollectionStatus,
    build_prospective_collection_status,
    write_prospective_collection_status,
)
from quantify.research.sealed_holdout_intake import (
    SealedHoldoutIntakeError,
    SealedHoldoutIntakeReport,
)

DailyCycleStatus = Literal[
    "NOT_DUE",
    "CURRENT",
    "ACTION_REQUIRED",
    "REVIEW_REQUIRED",
    "COLLECTED",
    "MARKET_CLOSED",
    "BLOCK",
]

PROHIBITED_ACTIONS = (
    "Do not enable acquisition without an explicit --execute-acquisition operator action.",
    "Do not retry a prior BLOCK provider attempt without explicit retry authorization.",
    "Do not refetch after provider PASS when sealed handoff is missing; investigate first.",
    "Do not inspect candidate results or replay sealed rows into an execution cache during the holdout.",
    "Do not treat collection, provider coverage, or cycle status as strategy or promotion evidence.",
    "Do not connect this cycle to a broker or generate orders.",
)


@dataclass(frozen=True, slots=True)
class ProspectiveDailyCycle:
    artifact_type: str
    schema_version: int
    status: DailyCycleStatus
    evaluated_at_utc: str
    trial_id: str
    candidate: str
    target_date: str
    execution_requested: bool
    retry_blocked_attempt_authorized: bool
    execution_performed: bool
    network_access: bool
    quarantine_root: str
    cycle_output_dir: str
    before_collection: ProspectiveCollectionStatus
    acquisition: ProspectiveDailyAcquisition | None
    attempt_event: dict[str, Any] | None
    intake: SealedHoldoutIntakeReport | None
    after_collection: ProspectiveCollectionStatus | None
    blockers: tuple[str, ...]
    next_actions: tuple[str, ...]
    next_command: str
    prohibited_actions: tuple[str, ...] = PROHIBITED_ACTIONS

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "schema_version": self.schema_version,
            "operation": "prospective_daily_collection_cycle",
            "status": self.status,
            "evaluated_at_utc": self.evaluated_at_utc,
            "trial_id": self.trial_id,
            "candidate": self.candidate,
            "target_date": self.target_date,
            "execution_requested": self.execution_requested,
            "retry_blocked_attempt_authorized": self.retry_blocked_attempt_authorized,
            "execution_performed": self.execution_performed,
            "network_access": self.network_access,
            "broker_access": False,
            "execution_cache_write_allowed": False,
            "holdout_analysis_allowed": False,
            "promotion_eligible": False,
            "paper_trading_allowed": False,
            "live_trading_allowed": False,
            "quarantine_root": self.quarantine_root,
            "cycle_output_dir": self.cycle_output_dir,
            "before_collection": self.before_collection.to_dict(),
            "acquisition": self.acquisition.to_dict() if self.acquisition else None,
            "attempt_event": self.attempt_event,
            "intake": self.intake.to_dict() if self.intake else None,
            "after_collection": (
                self.after_collection.to_dict() if self.after_collection else None
            ),
            "blockers": list(self.blockers),
            "next_actions": list(self.next_actions),
            "next_command": self.next_command,
            "prohibited_actions": list(self.prohibited_actions),
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Prospective Daily Cycle: {self.status}",
            "",
            f"- Trial: `{self.trial_id or 'unavailable'}`",
            f"- Candidate: `{self.candidate or 'unavailable'}`",
            f"- Target date: `{self.target_date or 'none'}`",
            f"- Execution requested: `{self.execution_requested}`",
            f"- Retry authorized: `{self.retry_blocked_attempt_authorized}`",
            f"- Execution performed: `{self.execution_performed}`",
            f"- Network access: `{self.network_access}`",
            f"- Before continuity: `{self.before_collection.status}`",
            f"- Acquisition: `{self.acquisition.status if self.acquisition else 'not built'}`",
            f"- After continuity: `{self.after_collection.status if self.after_collection else 'not run'}`",
            "",
            "This cycle manages sealed input collection only. It cannot inspect candidate "
            "performance, approve paper/live stages, or submit orders.",
            "",
            "## Blockers",
            "",
        ]
        lines.extend(f"- {item}" for item in self.blockers or ("None.",))
        lines.extend(["", "## Next Actions", ""])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Next Command", "", "```powershell"])
        lines.append(self.next_command or "# No acquisition command is currently due.")
        lines.extend(["```", "", "## Prohibited Actions", ""])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        lines.append("")
        return "\n".join(lines)


def run_prospective_daily_cycle(
    *,
    packet_dir: str | Path,
    trial_registry_path: str | Path,
    quarantine_root: str | Path,
    cycle_output_dir: str | Path,
    calendar_csv: str | Path | None = None,
    calendar_metadata: str | Path | None = None,
    execute_acquisition: bool = False,
    retry_blocked_attempt: bool = False,
    minimum_success_ratio: float = 0.95,
    max_attempts: int = 2,
    retry_delay_seconds: float = 1.0,
    fetch_symbol: FetchSymbol | None = None,
    workspace_root: str | Path | None = None,
) -> ProspectiveDailyCycle:
    """Evaluate one cycle and optionally collect only its earliest due date."""
    root = _workspace_root(workspace_root)
    quarantine = _resolve_path(quarantine_root, root).resolve()
    cycle_output = _resolve_path(cycle_output_dir, root).resolve()
    if (
        quarantine == cycle_output
        or quarantine in cycle_output.parents
        or cycle_output in quarantine.parents
    ):
        raise ValueError("cycle output and quarantine roots must be disjoint")
    before = build_prospective_collection_status(
        packet_dir=packet_dir,
        trial_registry_path=trial_registry_path,
        quarantine_root=quarantine,
        calendar_csv=calendar_csv,
        calendar_metadata=calendar_metadata,
        workspace_root=root,
    )
    target_date = before.earliest_unresolved_date
    acquisition: ProspectiveDailyAcquisition | None = None
    attempt_event: dict[str, Any] | None = None
    intake: SealedHoldoutIntakeReport | None = None
    after: ProspectiveCollectionStatus | None = None
    execution_performed = False
    network_access = False
    blockers: tuple[str, ...] = ()
    next_actions: tuple[str, ...] = before.next_actions
    next_command = before.next_command

    non_gap_blockers = tuple(
        item.message
        for item in before.checks
        if item.status == "BLOCK" and item.code != "DUE_WEEKDAY_CONTINUITY"
    )
    if non_gap_blockers:
        status: DailyCycleStatus = "BLOCK"
        blockers = tuple(dict.fromkeys(non_gap_blockers))
    elif not target_date:
        if before.status == "NOT_DUE":
            status = "NOT_DUE"
        elif before.status in {"PASS", "WATCH"}:
            status = "CURRENT"
        else:
            status = "BLOCK"
            blockers = before.blockers or ("Collection continuity is BLOCK without a due target.",)
    else:
        timeline_row = next(
            (item for item in before.timeline if item["date"] == target_date),
            {},
        )
        latest_attempt_status = str(timeline_row.get("latest_attempt_status") or "")
        if latest_attempt_status == "PASS":
            status = "REVIEW_REQUIRED"
            blockers = (
                "Provider coverage passed but no sealed collection event exists; investigate handoff before refetching.",
            )
        elif latest_attempt_status == "BLOCK" and not retry_blocked_attempt:
            status = "REVIEW_REQUIRED"
            blockers = (
                "The latest provider attempt is BLOCK; inspect its immutable report and explicitly authorize retry.",
            )
        else:
            acquisition = build_prospective_daily_acquisition_preflight(
                packet_dir=packet_dir,
                trial_registry_path=trial_registry_path,
                output_dir=quarantine,
                market_date=target_date,
                minimum_success_ratio=minimum_success_ratio,
                calendar_csv=calendar_csv,
                calendar_metadata=calendar_metadata,
                workspace_root=root,
            )
            if acquisition.status == "BLOCK":
                status = "BLOCK"
                blockers = acquisition.blockers
                next_actions = acquisition.next_actions
            elif acquisition.status == "MARKET_CLOSED":
                status = "MARKET_CLOSED"
                next_actions = acquisition.next_actions
                next_command = ""
            elif acquisition.status == "ALREADY_RETAINED":
                status = "BLOCK"
                blockers = (
                    "Acquisition reports ALREADY_RETAINED while continuity still marks the date unresolved.",
                )
            elif not execute_acquisition:
                status = "ACTION_REQUIRED"
                next_actions = (
                    f"Review the preflight and explicitly execute acquisition for {target_date}.",
                    *before.next_actions,
                )
            else:
                execution_performed = True
                try:
                    acquisition = run_prospective_daily_acquisition(
                        acquisition,
                        output_dir=quarantine,
                        fetch_symbol=fetch_symbol,
                        max_attempts=max_attempts,
                        retry_delay_seconds=retry_delay_seconds,
                    )
                    network_access = acquisition.to_dict()["network_access"] is True
                    attempt_event = record_prospective_acquisition_attempt(
                        acquisition,
                        quarantine,
                    )
                    write_prospective_daily_acquisition(acquisition, quarantine)
                    if acquisition.status != "PASS":
                        status = "BLOCK"
                        blockers = acquisition.blockers
                        next_actions = acquisition.next_actions
                    else:
                        intake = handoff_prospective_daily_acquisition(
                            acquisition,
                            packet_dir=packet_dir,
                            trial_registry_path=trial_registry_path,
                            output_dir=quarantine,
                        )
                        after = build_prospective_collection_status(
                            packet_dir=packet_dir,
                            trial_registry_path=trial_registry_path,
                            quarantine_root=quarantine,
                            calendar_csv=calendar_csv,
                            calendar_metadata=calendar_metadata,
                            workspace_root=root,
                        )
                        if target_date in after.unresolved_dates or after.status == "BLOCK":
                            status = "BLOCK"
                            blockers = after.blockers or (
                                "The collected date remains unresolved after sealed handoff.",
                            )
                            next_actions = after.next_actions
                            next_command = after.next_command
                        else:
                            status = "COLLECTED"
                            next_actions = after.next_actions
                            next_command = after.next_command
                except (OSError, RuntimeError, SealedHoldoutIntakeError, ValueError) as exc:
                    status = "BLOCK"
                    blockers = (f"Daily cycle execution failed: {type(exc).__name__}: {exc}",)
                    next_actions = (
                        "Inspect the provider-attempt journal and sealed intake artifacts before retrying.",
                    )

    return ProspectiveDailyCycle(
        artifact_type="prospective_daily_cycle",
        schema_version=1,
        status=status,
        evaluated_at_utc=_runtime_now().replace(microsecond=0).isoformat(),
        trial_id=before.trial_id,
        candidate=before.candidate,
        target_date=target_date,
        execution_requested=execute_acquisition,
        retry_blocked_attempt_authorized=retry_blocked_attempt,
        execution_performed=execution_performed,
        network_access=network_access,
        quarantine_root=str(quarantine),
        cycle_output_dir=str(cycle_output),
        before_collection=before,
        acquisition=acquisition,
        attempt_event=attempt_event,
        intake=intake,
        after_collection=after,
        blockers=tuple(dict.fromkeys(blockers)),
        next_actions=next_actions,
        next_command=next_command,
    )


def write_prospective_daily_cycle(
    report: ProspectiveDailyCycle,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir).resolve()
    if root != Path(report.cycle_output_dir).resolve():
        raise ValueError("cycle output directory changed after evaluation")
    root.mkdir(parents=True, exist_ok=True)
    (root / "prospective_daily_cycle.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, allow_nan=False, indent=2),
        encoding="utf-8",
    )
    (root / "prospective_daily_cycle.md").write_text(
        report.to_markdown(),
        encoding="utf-8",
    )
    write_prospective_collection_status(report.before_collection, root / "collection_before")
    if report.acquisition is not None:
        write_prospective_daily_acquisition(report.acquisition, root / "acquisition")
    if report.after_collection is not None:
        write_prospective_collection_status(report.after_collection, root / "collection_after")
    return root


def _workspace_root(value: str | Path | None) -> Path:
    return Path(value).resolve() if value is not None else Path(__file__).resolve().parents[3]


def _resolve_path(value: str | Path, root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _runtime_now() -> datetime:
    return datetime.now(UTC)
