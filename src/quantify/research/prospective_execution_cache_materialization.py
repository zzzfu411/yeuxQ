"""Guarded post-holdout replay into a new prospective execution cache.

The frozen development cache is never changed.  During the registered holdout
this module is read-only and fails closed before reading sealed bar values.
After the holdout, it verifies every retained input and rebuilds provenance in
a fresh SQLite cache that is bound by a canonical materialization artifact.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
import csv
import gc
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time
from typing import Any, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd

from quantify.data.cache_metadata import (
    PromotionMetadataCheck,
    build_promotion_metadata_check,
    cache_data_identity_blockers,
    cache_provenance_blockers,
    load_cache_bar_stats_readonly,
    load_cache_metadata_readonly,
    load_cache_provenance_readonly,
)
from quantify.data.exchange_calendar_preflight import (
    ExchangeCalendarPreflight,
    build_exchange_calendar_preflight,
)
from quantify.data.market_evidence_preflight import (
    MarketEvidencePreflightReport,
    build_market_evidence_preflight,
)
from quantify.data.prospective_acquisition_journal import (
    ATTEMPT_LEDGER_FILENAME,
    ProspectiveAcquisitionJournalError,
    verify_prospective_acquisition_attempts,
)
from quantify.data.provenance import (
    LOGICAL_BAR_FINGERPRINT_ALGORITHM,
    logical_bar_fingerprint_from_connection,
)
from quantify.data.source_qa import DataSourceQAReview, build_data_source_qa_review
from quantify.data.storage import BarStorage
from quantify.research.prospective_trial_packet import (
    ProspectiveTrialPacketVerification,
    build_prospective_trial_packet_verification,
)
from quantify.research.sealed_holdout_intake import (
    LEDGER_FILENAME,
    SealedHoldoutIntakeError,
    load_verified_sealed_daily_bars,
    verify_collection_ledger,
)
from quantify.research.trial_registry import (
    PreregistrationEvent,
    ResultEvent,
    TrialRegistryError,
    verify_registry,
)

MaterializationStatus = Literal["PASS", "BLOCK"]

ARTIFACT_TYPE = "prospective_execution_cache_materialization"
SCHEMA_VERSION = 1
ARTIFACT_FILENAME = "prospective_execution_cache_materialization.json"
MARKDOWN_FILENAME = "prospective_execution_cache_materialization.md"
CACHE_FILENAME = "prospective_execution_cache.db"
CLAIM_FILENAME = "prospective_execution_cache_materialization.claim.json"
MARKET_TIMEZONE = "Asia/Shanghai"
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z")

PROHIBITED_ACTIONS = (
    "Do not materialize, inspect, or analyze sealed observations through the registered holdout end date.",
    "Do not edit, append to, replace, or backfill metadata in the frozen development cache.",
    "Do not bypass a missing open session, provider-attempt record, retained input, source-QA item, or market-evidence file.",
    "Do not replace a completed materialization directory or create a second terminal result.",
    "Do not treat materialization PASS as paper, micro-live, live-trading, profit, or broker authorization.",
    "Do not generate or submit real broker orders from this workflow.",
)


class ProspectiveExecutionCacheMaterializationError(ValueError):
    """Raised when guarded materialization or its artifact cannot be trusted."""


@dataclass(frozen=True, slots=True)
class MaterializationCheck:
    code: str
    status: MaterializationStatus
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "status": self.status, "message": self.message}


@dataclass(frozen=True, slots=True)
class ProspectiveExecutionCacheMaterialization:
    artifact_type: str
    schema_version: int
    status: MaterializationStatus
    materialized: bool
    evaluated_at_utc: str
    evaluated_market_date: str
    market_timezone: str
    trial_id: str
    candidate: str
    boundaries: dict[str, dict[str, str]]
    inputs: dict[str, Any]
    source_development: dict[str, Any]
    collection: dict[str, Any]
    replay_manifest: dict[str, Any]
    replay_manifest_sha256: str
    output_cache: dict[str, Any]
    source_qa: dict[str, Any]
    calendar: dict[str, Any]
    market_evidence: dict[str, Any]
    checks: tuple[MaterializationCheck, ...]
    blockers: tuple[str, ...]
    next_actions: tuple[str, ...]
    prohibited_actions: tuple[str, ...]
    artifact_sha256: str

    @property
    def sufficient(self) -> bool:
        return self.status == "PASS" and self.materialized

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "schema_version": self.schema_version,
            "operation": "post_holdout_guarded_execution_cache_materialization",
            "network_access": False,
            "broker_access": False,
            "holdout_analysis_performed": False,
            "paper_trading_allowed": False,
            "live_trading_allowed": False,
            "status": self.status,
            "sufficient": self.sufficient,
            "materialized": self.materialized,
            "evaluated_at_utc": self.evaluated_at_utc,
            "evaluated_market_date": self.evaluated_market_date,
            "market_timezone": self.market_timezone,
            "trial_id": self.trial_id,
            "candidate": self.candidate,
            "boundaries": self.boundaries,
            "inputs": self.inputs,
            "source_development": self.source_development,
            "collection": self.collection,
            "replay_manifest": self.replay_manifest,
            "replay_manifest_sha256": self.replay_manifest_sha256,
            "output_cache": self.output_cache,
            "source_qa": self.source_qa,
            "calendar": self.calendar,
            "market_evidence": self.market_evidence,
            "checks": [item.to_dict() for item in self.checks],
            "blockers": list(self.blockers),
            "next_actions": list(self.next_actions),
            "prohibited_actions": list(self.prohibited_actions),
            "artifact_sha256": self.artifact_sha256,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Prospective Execution Cache Materialization: {self.status}",
            "",
            f"- Trial: `{self.trial_id or 'unavailable'}`",
            f"- Candidate: `{self.candidate or 'unavailable'}`",
            f"- Materialized: `{self.materialized}`",
            f"- Evaluated at UTC: `{self.evaluated_at_utc}`",
            f"- Source development cache: `{self.source_development.get('path') or 'unavailable'}`",
            f"- Output cache: `{self.output_cache.get('path') or 'not written'}`",
            f"- Output cache SHA-256: `{self.output_cache.get('sha256') or 'unavailable'}`",
            f"- Output logical fingerprint: `{self.output_cache.get('logical_bar_fingerprint') or 'unavailable'}`",
            f"- Replay manifest SHA-256: `{self.replay_manifest_sha256 or 'unavailable'}`",
            f"- Artifact SHA-256: `{self.artifact_sha256 or 'unavailable'}`",
            "",
            "This protocol replays evidence into a new research cache only. It does not run "
            "the candidate, inspect holdout performance, authorize trading, or contact a broker.",
            "",
            "## Checks",
            "",
        ]
        lines.extend(f"- `{item.status}` `{item.code}`: {item.message}" for item in self.checks)
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- {item}" for item in self.blockers or ("None.",))
        lines.extend(["", "## Next Actions", ""])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Prohibited Actions", ""])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        lines.append("")
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class ProspectiveExecutionCacheMaterializationVerification:
    artifact_type: str
    schema_version: int
    status: MaterializationStatus
    artifact_path: str
    artifact_sha256: str
    trial_id: str
    output_cache_path: str
    market_evidence_files: dict[str, dict[str, str]]
    checks: tuple[MaterializationCheck, ...]
    blockers: tuple[str, ...]
    promotion_metadata: PromotionMetadataCheck

    @property
    def sufficient(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "schema_version": self.schema_version,
            "operation": "read_only_materialization_verification",
            "network_access": False,
            "broker_access": False,
            "status": self.status,
            "sufficient": self.sufficient,
            "artifact_path": self.artifact_path,
            "artifact_sha256": self.artifact_sha256,
            "trial_id": self.trial_id,
            "output_cache_path": self.output_cache_path,
            "market_evidence_files": self.market_evidence_files,
            "checks": [item.to_dict() for item in self.checks],
            "blockers": list(self.blockers),
            "promotion_metadata": self.promotion_metadata.to_dict(),
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Prospective Execution Cache Materialization Verification: {self.status}",
            "",
            f"- Artifact: `{self.artifact_path}`",
            f"- Artifact canonical SHA-256: `{self.artifact_sha256 or 'unavailable'}`",
            f"- Trial: `{self.trial_id or 'unavailable'}`",
            f"- Output cache: `{self.output_cache_path or 'unavailable'}`",
            "- Network access: `False`",
            "- Broker access: `False`",
            "",
            "## Checks",
            "",
        ]
        lines.extend(f"- `{item.status}` `{item.code}`: {item.message}" for item in self.checks)
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- {item}" for item in self.blockers or ("None.",))
        lines.append("")
        return "\n".join(lines)


@dataclass(slots=True)
class _EvidenceContext:
    now: datetime
    root: Path
    packet_root: Path
    registry_path: Path
    quarantine_root: Path
    output_dir: Path
    packet: dict[str, Any]
    packet_verification: ProspectiveTrialPacketVerification
    trial_id: str
    candidate: str
    boundaries: dict[str, dict[str, str]]
    source_cache: Path
    source_cache_sha256: str
    source_cache_stats: dict[str, Any]
    source_cache_metadata: dict[str, str]
    source_qa_review: DataSourceQAReview
    source_qa_files: dict[str, dict[str, str]]
    calendar_report: ExchangeCalendarPreflight
    market_report: MarketEvidencePreflightReport
    ledger_events: list[dict[str, Any]]
    attempt_events: list[dict[str, Any]]
    replay_entries: list[dict[str, Any]]
    preregistration_event_hash: str
    checks: list[MaterializationCheck]


def materialize_prospective_execution_cache(
    *,
    packet_dir: str | Path,
    registry_path: str | Path,
    quarantine_root: str | Path,
    source_qa_checklist: str | Path,
    source_qa_answers: str | Path,
    source_qa_evidence_manifest: str | Path,
    calendar_csv: str | Path,
    calendar_metadata: str | Path,
    benchmark_csv: str | Path,
    benchmark_metadata: str | Path,
    membership_csv: str | Path,
    membership_metadata: str | Path,
    output_dir: str | Path,
    workspace_root: str | Path | None = None,
    minimum_members_per_snapshot: int = 700,
) -> ProspectiveExecutionCacheMaterialization:
    """Validate and, only after the holdout, atomically publish a new cache."""
    inputs = _input_paths(
        packet_dir=packet_dir,
        registry_path=registry_path,
        quarantine_root=quarantine_root,
        source_qa_checklist=source_qa_checklist,
        source_qa_answers=source_qa_answers,
        source_qa_evidence_manifest=source_qa_evidence_manifest,
        calendar_csv=calendar_csv,
        calendar_metadata=calendar_metadata,
        benchmark_csv=benchmark_csv,
        benchmark_metadata=benchmark_metadata,
        membership_csv=membership_csv,
        membership_metadata=membership_metadata,
        output_dir=output_dir,
        workspace_root=workspace_root,
        minimum_members_per_snapshot=minimum_members_per_snapshot,
    )
    context = _collect_evidence(
        inputs,
        require_unused_output=True,
        allow_terminal_result=False,
    )
    blockers = _blockers(context.checks)
    if blockers:
        return _report_from_context(context, inputs, blockers=blockers)

    source_hash_before = context.source_cache_sha256
    output = context.output_dir
    replay_manifest = _replay_manifest(context)
    replay_manifest_sha256 = _canonical_sha256(replay_manifest)
    claim_path = context.quarantine_root / CLAIM_FILENAME
    claim_payload = {
        "artifact_type": "prospective_execution_cache_materialization_claim",
        "schema_version": 1,
        "trial_id": context.trial_id,
        "candidate": context.candidate,
        "output_dir": str(output),
        "replay_manifest_sha256": replay_manifest_sha256,
        "claimed_at_utc": context.now.replace(microsecond=0).isoformat(),
        "one_time": True,
    }
    claim_bytes = _canonical_json(claim_payload)
    try:
        with claim_path.open("xb") as handle:
            if handle.write(claim_bytes) != len(claim_bytes):  # pragma: no cover
                raise OSError("short materialization-claim write")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ProspectiveExecutionCacheMaterializationError(
            "a one-time materialization claim already exists; repeat replay is prohibited"
        ) from exc
    claim_sha256 = hashlib.sha256(claim_bytes).hexdigest()
    staging = output.with_name(f".{output.name}.{uuid4().hex}.tmp")
    output.parent.mkdir(parents=True, exist_ok=True)
    if staging.exists():  # pragma: no cover - UUID collision
        raise ProspectiveExecutionCacheMaterializationError(
            f"materialization staging path unexpectedly exists: {staging}"
        )
    staging.mkdir()
    try:
        staged_cache = staging / CACHE_FILENAME
        _rebuild_cache(context, staged_cache, inputs)
        source_hash_after = _file_sha256(context.source_cache)
        if not hmac.compare_digest(source_hash_before, source_hash_after):
            raise ProspectiveExecutionCacheMaterializationError(
                "frozen development cache changed during materialization"
            )
        promotion = build_promotion_metadata_check(
            staged_cache,
            require_evidence_manifest=True,
        )
        if promotion.status != "PASS":
            raise ProspectiveExecutionCacheMaterializationError(
                "materialized cache promotion metadata failed: " + "; ".join(promotion.blockers)
            )
        expected_last = context.replay_entries[-1]["market_date"]
        if str(promotion.cache_stats.get("bar_end") or "") != expected_last:
            raise ProspectiveExecutionCacheMaterializationError(
                "materialized cache does not end on the final reviewed open session"
            )
        final_cache_path = output / CACHE_FILENAME
        output_cache = {
            "path": str(final_cache_path),
            "sha256": _file_sha256(staged_cache),
            "logical_bar_fingerprint": str(
                promotion.cache_stats.get("logical_bar_fingerprint_actual") or ""
            ),
            "logical_bar_fingerprint_algorithm": LOGICAL_BAR_FINGERPRINT_ALGORITHM,
            "bar_count": int(promotion.cache_stats.get("bar_count") or 0),
            "symbol_count": int(promotion.cache_stats.get("symbol_count") or 0),
            "bar_start": str(promotion.cache_stats.get("bar_start") or ""),
            "bar_end": str(promotion.cache_stats.get("bar_end") or ""),
            "promotion_status": promotion.status,
            "claim_path": str(claim_path),
            "claim_sha256": claim_sha256,
        }
        report = _report_from_context(
            context,
            inputs,
            blockers=(),
            materialized=True,
            output_cache=output_cache,
            replay_manifest=replay_manifest,
            source_hash_after=source_hash_after,
        )
        artifact_path = staging / ARTIFACT_FILENAME
        artifact_path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, allow_nan=False, indent=2),
            encoding="utf-8",
        )
        (staging / MARKDOWN_FILENAME).write_text(report.to_markdown(), encoding="utf-8")
        if output.exists():
            raise ProspectiveExecutionCacheMaterializationError(
                "materialization output appeared after preflight; replacement is prohibited"
            )
        _publish_directory(staging, output)
        return report
    except Exception:
        if staging.exists():
            _remove_tree(staging)
        raise


def build_prospective_execution_cache_materialization_verification(
    artifact_path: str | Path,
    *,
    packet_dir: str | Path,
    registry_path: str | Path,
    workspace_root: str | Path | None = None,
) -> ProspectiveExecutionCacheMaterializationVerification:
    """Recompute every materialization binding without changing any input."""
    root = _workspace_root(workspace_root)
    artifact_file = _resolve_path(artifact_path, root)
    payload, payload_error = _load_json_object(artifact_file)
    checks: list[MaterializationCheck] = []
    contract_ready = (
        not payload_error
        and payload.get("artifact_type") == ARTIFACT_TYPE
        and payload.get("schema_version") == SCHEMA_VERSION
        and payload.get("status") == "PASS"
        and payload.get("materialized") is True
        and payload.get("sufficient") is True
        and payload.get("network_access") is False
        and payload.get("broker_access") is False
        and payload.get("holdout_analysis_performed") is False
        and payload.get("paper_trading_allowed") is False
        and payload.get("live_trading_allowed") is False
    )
    _check(
        checks,
        "MATERIALIZATION_ARTIFACT_CONTRACT",
        contract_ready,
        "Materialization artifact contract and safety flags verify."
        if contract_ready
        else payload_error or "Materialization artifact contract or safety flags are invalid.",
    )
    claimed_hash = _text(payload.get("artifact_sha256"))
    actual_hash = (
        _canonical_sha256(
            {key: value for key, value in payload.items() if key != "artifact_sha256"}
        )
        if payload
        else ""
    )
    hash_ready = bool(claimed_hash) and hmac.compare_digest(claimed_hash, actual_hash)
    _check(
        checks,
        "MATERIALIZATION_ARTIFACT_SHA256",
        hash_ready,
        "Materialization artifact canonical SHA-256 matches."
        if hash_ready
        else "Materialization artifact canonical SHA-256 mismatch.",
    )

    inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
    expected_packet = _resolve_path(packet_dir, root)
    expected_registry = _resolve_path(registry_path, root)
    path_binding_ready = _same_path(inputs.get("packet_dir"), expected_packet) and _same_path(
        inputs.get("registry_path"), expected_registry
    )
    _check(
        checks,
        "MATERIALIZATION_PACKET_REGISTRY_PATHS",
        path_binding_ready,
        "Artifact is bound to the requested packet directory and registry."
        if path_binding_ready
        else "Artifact packet/registry paths do not match admission inputs.",
    )

    context: _EvidenceContext | None = None
    context_error = ""
    if contract_ready and path_binding_ready:
        try:
            context = _collect_evidence(
                inputs,
                require_unused_output=False,
                allow_terminal_result=True,
            )
        except (OSError, ValueError) as exc:
            context_error = f"{type(exc).__name__}: {exc}"
    evidence_ready = context is not None and not _blockers(context.checks)
    _check(
        checks,
        "MATERIALIZATION_INPUT_REVERIFICATION",
        evidence_ready,
        "Packet, registry, source QA, calendar, market evidence, ledgers, and sealed inputs reverify."
        if evidence_ready
        else context_error or "One or more materialization inputs no longer verify.",
    )

    replay_ready = False
    if context is not None:
        replay = _replay_manifest(context)
        replay_hash = _canonical_sha256(replay)
        replay_ready = (
            payload.get("replay_manifest") == replay
            and payload.get("replay_manifest_sha256") == replay_hash
        )
    _check(
        checks,
        "REPLAY_MANIFEST_BINDING",
        replay_ready,
        "Ordered replay manifest and its SHA-256 recompute exactly."
        if replay_ready
        else "Ordered replay manifest or its SHA-256 does not match current evidence.",
    )

    output = payload.get("output_cache") if isinstance(payload.get("output_cache"), dict) else {}
    output_cache = _resolve_path(_text(output.get("path")) or "__missing__", root)
    promotion = build_promotion_metadata_check(
        output_cache,
        require_evidence_manifest=True,
    )
    output_hash = _file_sha256(output_cache) if output_cache.is_file() else ""
    expected_output_cache = (
        context.output_dir / CACHE_FILENAME
        if context is not None
        else _resolve_path("__missing_expected_output__", root)
    )
    output_ready = (
        promotion.status == "PASS"
        and output_cache == expected_output_cache
        and _valid_hash(output_hash)
        and hmac.compare_digest(output_hash, _text(output.get("sha256")))
        and output.get("logical_bar_fingerprint")
        == promotion.cache_stats.get("logical_bar_fingerprint_actual")
        and output.get("bar_count") == promotion.cache_stats.get("bar_count")
        and output.get("symbol_count") == promotion.cache_stats.get("symbol_count")
        and output.get("bar_start") == promotion.cache_stats.get("bar_start")
        and output.get("bar_end") == promotion.cache_stats.get("bar_end")
    )
    _check(
        checks,
        "MATERIALIZED_CACHE_BINDING",
        output_ready,
        "Materialized cache bytes, logical identity, coverage, source QA, and lineage verify."
        if output_ready
        else "Materialized cache is missing, changed, incomplete, or no longer promotion-safe.",
    )

    claim_path = _resolve_path(_text(output.get("claim_path")) or "__missing_claim__", root)
    claim, claim_error = _load_json_object(claim_path)
    expected_claim = {
        "artifact_type": "prospective_execution_cache_materialization_claim",
        "schema_version": 1,
        "trial_id": _text(payload.get("trial_id")),
        "candidate": _text(payload.get("candidate")),
        "output_dir": str(output_cache.parent),
        "replay_manifest_sha256": _text(payload.get("replay_manifest_sha256")),
        "claimed_at_utc": _text(payload.get("evaluated_at_utc")),
        "one_time": True,
    }
    claim_hash = _optional_file_sha256(claim_path)
    claim_ready = (
        not claim_error
        and claim == expected_claim
        and claim_path == _resolve_path(inputs.get("quarantine_root", ""), root) / CLAIM_FILENAME
        and claim_hash == _text(output.get("claim_sha256"))
    )
    _check(
        checks,
        "ONE_TIME_MATERIALIZATION_CLAIM",
        claim_ready,
        "One-time quarantine claim is canonical and bound to this exact replay/output."
        if claim_ready
        else claim_error or "One-time materialization claim is missing, changed, or inconsistent.",
    )

    if context is not None:
        expected_source = {
            **_source_development(context),
            "sha256_after": context.source_cache_sha256,
            "unchanged": True,
        }
        source_ready = payload.get("source_development") == expected_source
        expected_collection = _collection_summary(context)
        collection_ready = payload.get("collection") == expected_collection
        evidence_payload_ready = (
            payload.get("source_qa") == _source_qa_summary(context)
            and payload.get("calendar") == _calendar_summary(context)
            and payload.get("market_evidence") == _market_summary(context)
        )
    else:
        source_ready = collection_ready = evidence_payload_ready = False
    _check(
        checks,
        "FROZEN_SOURCE_CACHE_UNCHANGED",
        source_ready,
        "Frozen development cache physical and logical identities remain unchanged."
        if source_ready
        else "Frozen development cache binding changed after materialization.",
    )
    _check(
        checks,
        "SEALED_COLLECTION_BINDING",
        collection_ready,
        "Ledger, attempt journal, ordered event hashes, and retained input hashes match."
        if collection_ready
        else "Sealed collection summary does not match current ledgers or inputs.",
    )
    _check(
        checks,
        "EXTERNAL_EVIDENCE_BINDING",
        evidence_payload_ready,
        "Source QA, reviewed calendar, benchmark, and PIT evidence hashes match."
        if evidence_payload_ready
        else "Source QA, calendar, or market-evidence bindings changed.",
    )

    blockers = _blockers(checks)
    return ProspectiveExecutionCacheMaterializationVerification(
        artifact_type="prospective_execution_cache_materialization_verification",
        schema_version=1,
        status="BLOCK" if blockers else "PASS",
        artifact_path=str(artifact_file),
        artifact_sha256=actual_hash,
        trial_id=_text(payload.get("trial_id")),
        output_cache_path=str(output_cache),
        market_evidence_files=(
            dict(payload.get("market_evidence", {}).get("files", {}))
            if isinstance(payload.get("market_evidence"), dict)
            and isinstance(payload.get("market_evidence", {}).get("files"), dict)
            else {}
        ),
        checks=tuple(checks),
        blockers=blockers,
        promotion_metadata=promotion,
    )


def write_prospective_execution_cache_materialization_verification(
    verification: ProspectiveExecutionCacheMaterializationVerification,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "prospective_execution_cache_materialization_verification.json").write_text(
        json.dumps(
            verification.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (root / "prospective_execution_cache_materialization_verification.md").write_text(
        verification.to_markdown(),
        encoding="utf-8",
    )
    return root


def _collect_evidence(
    inputs: dict[str, Any],
    *,
    require_unused_output: bool,
    allow_terminal_result: bool,
) -> _EvidenceContext:
    root = _workspace_root(inputs.get("workspace_root") or None)
    now = _runtime_now()
    packet_root = _resolve_path(inputs.get("packet_dir", ""), root)
    registry_path = _resolve_path(inputs.get("registry_path", ""), root)
    quarantine = _resolve_path(inputs.get("quarantine_root", ""), root)
    output = _resolve_path(inputs.get("output_dir", ""), root)
    packet, packet_error = _load_json_object(packet_root / "prospective_trial_packet.json")
    packet_verification = build_prospective_trial_packet_verification(
        packet_root,
        registry_path,
        workspace_root=root,
    )
    trial_id = _text(packet.get("trial_id"))
    candidate = _text(packet.get("candidate"))
    boundaries = _boundaries(packet)
    train_start = _boundary_date(boundaries, "train", "start")
    test_start = _boundary_date(boundaries, "test", "start")
    test_end = _boundary_date(boundaries, "test", "end")
    cutoff = _iso_date(packet.get("development_cutoff"))
    checks: list[MaterializationCheck] = []
    _check(
        checks,
        "PACKET_INTEGRITY",
        not packet_error and packet_verification.status == "PASS",
        "Frozen packet, code, config, development prefix, and registry binding verify."
        if not packet_error and packet_verification.status == "PASS"
        else packet_error or "Frozen packet or registry binding does not verify.",
    )

    preregistration_hash = ""
    result_count = 0
    registry_error = ""
    try:
        registry_events = verify_registry(registry_path)
    except (OSError, TrialRegistryError) as exc:
        registry_events = []
        registry_error = f"{type(exc).__name__}: {exc}"
    else:
        preregistrations = [
            event
            for event in registry_events
            if isinstance(event, PreregistrationEvent) and event.trial_id == trial_id
        ]
        results = [
            event
            for event in registry_events
            if isinstance(event, ResultEvent) and event.trial_id == trial_id
        ]
        result_count = len(results)
        if len(preregistrations) == 1:
            preregistration_hash = preregistrations[0].event_hash
    result_count_ready = result_count <= 1 if allow_terminal_result else result_count == 0
    registry_ready = not registry_error and bool(preregistration_hash) and result_count_ready
    _check(
        checks,
        "TERMINAL_RESULT_ABSENT",
        registry_ready,
        (
            "Registry has exactly one preregistration and at most one terminal result for post-result verification."
            if allow_terminal_result
            else "Registry has exactly one preregistration and no terminal result for this trial."
        )
        if registry_ready
        else registry_error
        or (f"Registry preregistration/result state is invalid; terminal_results={result_count}."),
    )

    market_date = now.astimezone(ZoneInfo(MARKET_TIMEZONE)).date()
    timing_ready = test_end is not None and market_date > test_end
    _check(
        checks,
        "POST_HOLDOUT_TIME_SEAL",
        timing_ready,
        f"Registered holdout ended on {test_end}; guarded replay may be considered."
        if timing_ready
        else (
            f"Holdout remains sealed through {test_end or 'an invalid end date'}; "
            "materialization is prohibited."
        ),
    )

    source_cache = _development_cache_path(packet, root)
    source_stats, source_metadata, source_hash, source_errors = _development_cache_evidence(
        source_cache,
        cutoff=cutoff,
        expected_prefix=_text((packet.get("fingerprints") or {}).get("data_fingerprint"))
        if isinstance(packet.get("fingerprints"), dict)
        else "",
    )
    source_ready = not source_errors
    _check(
        checks,
        "FROZEN_DEVELOPMENT_CACHE",
        source_ready,
        "Frozen development cache has the exact registered prefix and no post-cutoff bars; existing lineage verifies or its registration-time legacy absence is explicit."
        if source_ready
        else "; ".join(source_errors),
    )
    configured_source = _configured_source(packet)
    cached_source = _text(source_metadata.get("data_source"))
    source_route_ready = (
        bool(configured_source)
        and bool(cached_source)
        and _source_route_family(configured_source) == _source_route_family(cached_source)
    )
    _check(
        checks,
        "FROZEN_SOURCE_ROUTE",
        source_route_ready,
        f"Frozen configured source {configured_source!r} matches development provenance {cached_source!r}."
        if source_route_ready
        else "Frozen configured source and development-cache provenance route do not match.",
    )

    checklist = _resolve_path(inputs.get("source_qa_checklist", ""), root)
    answers = _resolve_path(inputs.get("source_qa_answers", ""), root)
    manifest = _resolve_path(inputs.get("source_qa_evidence_manifest", ""), root)
    source_qa_review = build_data_source_qa_review(
        checklist_path=checklist,
        answers_path=answers,
        evidence_manifest_path=manifest,
        require_evidence_manifest=True,
    )
    source_qa_files = _source_qa_file_bindings(checklist, answers, manifest)
    qa_coverage_ready = _source_qa_coverage(checklist, train_start, test_end)
    qa_adjustment = _text(source_qa_review.source_metadata.get("price_adjustment")).lower()
    frozen_adjustment = _frozen_adjustment(packet)
    qa_source_route_ready = _source_qa_route_matches(
        configured_source,
        source_qa_review.source_metadata,
    )
    qa_timestamps_ready = _source_qa_timestamps_not_future(
        source_qa_review,
        now.astimezone(ZoneInfo(MARKET_TIMEZONE)).date(),
    )
    source_qa_ready = (
        source_qa_review.status == "PASS"
        and qa_coverage_ready
        and qa_timestamps_ready
        and qa_source_route_ready
        and bool(frozen_adjustment)
        and qa_adjustment == frozen_adjustment
        and all(_valid_hash(item.get("sha256")) for item in source_qa_files.values())
    )
    _check(
        checks,
        "REVIEWED_SOURCE_QA",
        source_qa_ready,
        "Independent source QA, attachments, full frozen coverage, and price adjustment verify."
        if source_qa_ready
        else (
            "Source QA must PASS with retained attachments, non-future timestamps, complete "
            "train-through-test coverage, the frozen source route, and price adjustment."
        ),
    )

    calendar_report = build_exchange_calendar_preflight(
        _resolve_path(inputs.get("calendar_csv", ""), root),
        _resolve_path(inputs.get("calendar_metadata", ""), root),
        required_start_date=test_start.isoformat() if test_start else "",
        required_end_date=test_end.isoformat() if test_end else "",
    )
    _check(
        checks,
        "REVIEWED_EXCHANGE_CALENDAR",
        calendar_report.status == "PASS",
        "Reviewed A-share exchange calendar covers every natural day in the test interval."
        if calendar_report.status == "PASS"
        else "Reviewed A-share exchange calendar is incomplete or invalid.",
    )

    market_report = build_market_evidence_preflight(
        _resolve_path(inputs.get("benchmark_csv", ""), root),
        _resolve_path(inputs.get("benchmark_metadata", ""), root),
        _resolve_path(inputs.get("membership_csv", ""), root),
        _resolve_path(inputs.get("membership_metadata", ""), root),
        required_start_date=train_start,
        required_end_date=test_end,
        minimum_members_per_snapshot=int(inputs.get("minimum_members_per_snapshot") or 700),
    )
    market_not_future = _market_evidence_not_future(market_report, now)
    _check(
        checks,
        "REVIEWED_MARKET_EVIDENCE",
        market_report.status == "PASS" and market_not_future,
        "Reviewed CSI 800 total-return benchmark and PIT membership evidence verify."
        if market_report.status == "PASS" and market_not_future
        else "Reviewed benchmark or PIT membership evidence is incomplete, invalid, or future-dated.",
    )

    ledger_error = ""
    try:
        ledger_events = verify_collection_ledger(
            quarantine / LEDGER_FILENAME,
            quarantine_root=quarantine,
        )
    except (OSError, SealedHoldoutIntakeError) as exc:
        ledger_events = []
        ledger_error = f"{type(exc).__name__}: {exc}"
    _check(
        checks,
        "SEALED_COLLECTION_LEDGER",
        not ledger_error,
        f"Verified {len(ledger_events)} sealed collection event(s) and retained files."
        if not ledger_error
        else f"Sealed collection ledger cannot be verified: {ledger_error}",
    )

    attempt_error = ""
    try:
        attempt_events = verify_prospective_acquisition_attempts(quarantine)
    except (OSError, ProspectiveAcquisitionJournalError) as exc:
        attempt_events = []
        attempt_error = f"{type(exc).__name__}: {exc}"
    _check(
        checks,
        "PROVIDER_ATTEMPT_JOURNAL",
        not attempt_error,
        f"Verified {len(attempt_events)} provider-attempt event(s) and immutable reports."
        if not attempt_error
        else f"Provider-attempt journal cannot be verified: {attempt_error}",
    )

    if timing_ready:
        replay_entries, continuity_errors = _replay_entries(
            trial_id=trial_id,
            candidate=candidate,
            calendar=calendar_report,
            ledger_events=ledger_events,
            attempt_events=attempt_events,
            quarantine=quarantine,
            expected_symbol_count=int(
                (packet.get("development_data") or {}).get("symbol_count") or 0
            )
            if isinstance(packet.get("development_data"), dict)
            else 0,
        )
    else:
        replay_entries = []
        continuity_errors = [
            "Sealed CSV row identity is not evaluated before the post-holdout time seal passes."
        ]
    _check(
        checks,
        "COMPLETE_REVIEWED_SESSION_CONTINUITY",
        not continuity_errors,
        f"Every reviewed open session has one ledger-bound sealed input and one matching PASS provider attempt ({len(replay_entries)} sessions)."
        if not continuity_errors
        else "; ".join(continuity_errors),
    )

    claim_exists = (quarantine / CLAIM_FILENAME).exists()
    output_ready = (
        not output.exists() and not claim_exists
        if require_unused_output
        else output.is_dir() and claim_exists
    )
    _check(
        checks,
        "SINGLE_USE_OUTPUT_DIRECTORY",
        output_ready,
        "Materialization output path and one-time claim are unused; atomic publication is available."
        if require_unused_output and output_ready
        else "Completed materialization output directory exists for read-only verification."
        if not require_unused_output and output_ready
        else (
            "Materialization output or one-time claim already exists; replacement/repeat replay is prohibited."
            if require_unused_output
            else "Materialization output directory is missing or not a directory."
        ),
    )
    disjoint_ready = _paths_disjoint(
        output,
        source_cache,
        packet_root,
        registry_path,
        quarantine,
        *(
            _resolve_path(inputs.get(name, ""), root)
            for name in (
                "source_qa_checklist",
                "source_qa_answers",
                "source_qa_evidence_manifest",
                "calendar_csv",
                "calendar_metadata",
                "benchmark_csv",
                "benchmark_metadata",
                "membership_csv",
                "membership_metadata",
            )
        ),
    )
    _check(
        checks,
        "OUTPUT_PATH_ISOLATION",
        disjoint_ready,
        "Output is disjoint from frozen inputs, evidence, registry, and quarantine."
        if disjoint_ready
        else "Output path overlaps a frozen input, evidence file, registry, or quarantine.",
    )

    return _EvidenceContext(
        now=now,
        root=root,
        packet_root=packet_root,
        registry_path=registry_path,
        quarantine_root=quarantine,
        output_dir=output,
        packet=packet,
        packet_verification=packet_verification,
        trial_id=trial_id,
        candidate=candidate,
        boundaries=boundaries,
        source_cache=source_cache,
        source_cache_sha256=source_hash,
        source_cache_stats=source_stats,
        source_cache_metadata=source_metadata,
        source_qa_review=source_qa_review,
        source_qa_files=source_qa_files,
        calendar_report=calendar_report,
        market_report=market_report,
        ledger_events=ledger_events,
        attempt_events=attempt_events,
        replay_entries=replay_entries,
        preregistration_event_hash=preregistration_hash,
        checks=checks,
    )


def _rebuild_cache(
    context: _EvidenceContext,
    target: Path,
    inputs: dict[str, Any],
) -> None:
    cutoff = _text(context.packet.get("development_cutoff"))
    source_uri = context.source_cache.resolve().as_posix()
    with sqlite3.connect(f"file:{source_uri}?mode=ro", uri=True) as conn:
        development = pd.read_sql_query(
            """
            SELECT symbol, date, open, high, low, close, volume, amount
            FROM bars WHERE date <= ? ORDER BY symbol COLLATE BINARY, date COLLATE BINARY
            """,
            conn,
            params=[cutoff],
        )
    if development.empty:
        raise ProspectiveExecutionCacheMaterializationError(
            "frozen development prefix unexpectedly contains no bars"
        )
    replay_frames = [
        load_verified_sealed_daily_bars(entry["retained_path"], entry["ledger_event"])
        for entry in context.replay_entries
    ]
    all_symbols = set(development["symbol"].astype(str))
    for frame in replay_frames:
        all_symbols.update(frame["symbol"].astype(str))
    final_start = min(str(development["date"].min()), context.replay_entries[0]["market_date"])
    final_end = context.replay_entries[-1]["market_date"]
    source_type = _materialized_source_type(_configured_source(context.packet))
    qa_metadata = {
        "data_source": _configured_source(context.packet),
        "data_source_qa_status": "PASS",
        "data_source_qa_checklist_path": context.source_qa_files["checklist"]["path"],
        "data_source_qa_checklist_sha256": context.source_qa_files["checklist"]["sha256"],
        "data_source_qa_answers_path": context.source_qa_files["answers"]["path"],
        "data_source_qa_answers_sha256": context.source_qa_files["answers"]["sha256"],
        "data_source_qa_evidence_manifest_path": context.source_qa_files["evidence_manifest"][
            "path"
        ],
        "data_source_qa_evidence_manifest_sha256": context.source_qa_files["evidence_manifest"][
            "sha256"
        ],
        "data_source_qa_require_evidence_manifest": "true",
        "data_import_symbol_count": len(all_symbols),
        "data_import_actual_bar_start": final_start,
        "data_import_actual_bar_end": final_end,
        "prospective_materialization_trial_id": context.trial_id,
        "prospective_development_cache_sha256": context.source_cache_sha256,
        "prospective_development_prefix_fingerprint": _text(
            (context.packet.get("fingerprints") or {}).get("data_fingerprint")
        ),
    }
    storage = BarStorage(target)
    storage.save_bars_with_lineage(
        development,
        source_type=source_type,
        source_reference=f"{context.source_cache}|sha256={context.source_cache_sha256}",
        source_fingerprint_kind="logical_bar_prefix",
        source_fingerprint=_text(
            (context.packet.get("fingerprints") or {}).get("data_fingerprint")
        ),
        source_metadata={
            "role": "frozen_development_prefix",
            "packet_sha256": context.packet_verification.packet_sha256,
            "cutoff": cutoff,
        },
        cache_metadata=qa_metadata,
        batch_id=_batch_id(context.trial_id, "development", context.source_cache_sha256),
        imported_at_utc=_text(context.packet.get("created_at_utc")),
    )
    for index, (entry, frame) in enumerate(zip(context.replay_entries, replay_frames, strict=True)):
        final = index == len(context.replay_entries) - 1
        storage.save_bars_with_lineage(
            frame,
            source_type=source_type,
            source_reference=(f"{entry['retained_path']}|sha256={entry['raw_sha256']}"),
            source_fingerprint_kind="sealed_input_sha256",
            source_fingerprint=entry["raw_sha256"],
            source_metadata={
                "role": "prospective_sealed_replay",
                "ledger_event_hash": entry["ledger_event_hash"],
                "attempt_event_hash": entry["attempt_event_hash"],
                "calendar_csv_sha256": context.calendar_report.csv_sha256,
                "calendar_metadata_sha256": context.calendar_report.metadata_sha256,
            },
            cache_metadata=qa_metadata if final else None,
            batch_id=entry["batch_id"],
            imported_at_utc=_text(entry["ledger_event"].get("received_at_utc")),
        )
    storage.save_calendar(
        [
            str(item["date"])
            for item in context.calendar_report.sessions
            if item.get("is_open") is True
        ]
    )
    membership_path = _resolve_path(inputs.get("membership_csv", ""), context.root)
    for effective_date, symbols in _membership_snapshots(membership_path).items():
        storage.save_index_constituents("000906", effective_date, symbols)


def _replay_entries(
    *,
    trial_id: str,
    candidate: str,
    calendar: ExchangeCalendarPreflight,
    ledger_events: list[dict[str, Any]],
    attempt_events: list[dict[str, Any]],
    quarantine: Path,
    expected_symbol_count: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    if calendar.status != "PASS":
        return [], ["Reviewed calendar must PASS before continuity can be evaluated."]
    start = _iso_date(calendar.required_start_date)
    end = _iso_date(calendar.required_end_date)
    open_dates = [
        str(item["date"])
        for item in calendar.sessions
        if item.get("is_open") is True
        and start is not None
        and end is not None
        and start <= date.fromisoformat(str(item["date"])) <= end
    ]
    if not open_dates:
        errors.append("Reviewed test interval contains no open sessions.")
    foreign_ledger = [event for event in ledger_events if event.get("trial_id") != trial_id]
    foreign_attempts = [event for event in attempt_events if event.get("trial_id") != trial_id]
    if foreign_ledger or foreign_attempts:
        errors.append("Quarantine contains events for a different trial.")
    trial_ledger = [event for event in ledger_events if event.get("trial_id") == trial_id]
    trial_attempts = [event for event in attempt_events if event.get("trial_id") == trial_id]
    ledger_dates = [str(event.get("market_date") or "") for event in trial_ledger]
    if ledger_dates != open_dates:
        missing = sorted(set(open_dates) - set(ledger_dates))
        unexpected = sorted(set(ledger_dates) - set(open_dates))
        errors.append(
            "Ledger dates must exactly equal reviewed open sessions in chronological order"
            f"; missing={missing[:5]}, unexpected={unexpected[:5]}."
        )
    attempts_by_date: dict[str, list[dict[str, Any]]] = {}
    for attempt in trial_attempts:
        attempts_by_date.setdefault(str(attempt.get("market_date") or ""), []).append(attempt)
    if sorted(attempts_by_date) != open_dates:
        errors.append("Provider-attempt dates must exactly equal reviewed open sessions.")
    replay: list[dict[str, Any]] = []
    frozen_fingerprints: set[str] = set()
    for event in trial_ledger:
        market_date = str(event.get("market_date") or "")
        retained = quarantine / str(event.get("retained_relative_path") or "")
        try:
            load_verified_sealed_daily_bars(retained, event)
        except (OSError, SealedHoldoutIntakeError) as exc:
            errors.append(f"{market_date}: sealed CSV failed canonical verification: {exc}.")
            continue
        if event.get("candidate") != candidate:
            errors.append(f"{market_date}: ledger candidate does not match frozen candidate.")
        attempts = attempts_by_date.get(market_date, [])
        matching = [
            item
            for item in attempts
            if item.get("status") == "PASS"
            and item.get("csv_sha256") == event.get("raw_sha256")
            and item.get("candidate") == candidate
            and item.get("source_vendor") == event.get("source_vendor")
        ]
        if len(matching) != 1:
            errors.append(
                f"{market_date}: expected exactly one PASS attempt bound to retained CSV; found {len(matching)}."
            )
            continue
        if attempts[-1] is not matching[0]:
            errors.append(f"{market_date}: matching PASS must be the final provider attempt.")
        pass_attempts = [item for item in attempts if item.get("status") == "PASS"]
        if len(pass_attempts) != 1:
            errors.append(f"{market_date}: expected exactly one PASS provider attempt.")
        attempt = matching[0]
        frozen_fingerprints.add(_text(attempt.get("frozen_symbol_fingerprint")))
        if expected_symbol_count and attempt.get("requested_symbols") != expected_symbol_count:
            errors.append(
                f"{market_date}: requested symbol count differs from frozen development universe."
            )
        if attempt.get("calendar_evidence_status") == "PASS" and (
            attempt.get("calendar_csv_sha256") != calendar.csv_sha256
            or attempt.get("calendar_metadata_sha256") != calendar.metadata_sha256
        ):
            errors.append(
                f"{market_date}: attempt calendar binding differs from final reviewed calendar."
            )
        replay.append(
            {
                "market_date": market_date,
                "ledger_sequence": event.get("sequence"),
                "ledger_event_hash": _text(event.get("event_hash")),
                "attempt_sequence": attempt.get("sequence"),
                "attempt_event_hash": _text(attempt.get("event_hash")),
                "raw_sha256": _text(event.get("raw_sha256")),
                "canonical_bar_fingerprint": _text(event.get("canonical_bar_fingerprint")),
                "row_count": event.get("row_count"),
                "symbol_count": event.get("symbol_count"),
                "retained_path": str(retained.resolve()),
                "batch_id": _batch_id(trial_id, market_date, _text(event.get("event_hash"))),
                "ledger_event": event,
            }
        )
    if len(frozen_fingerprints) != 1 or not all(_valid_hash(item) for item in frozen_fingerprints):
        errors.append("All PASS attempts must share one valid frozen-symbol fingerprint.")
    return replay, list(dict.fromkeys(errors))


def _development_cache_evidence(
    cache: Path,
    *,
    cutoff: date | None,
    expected_prefix: str,
) -> tuple[dict[str, Any], dict[str, str], str, list[str]]:
    errors: list[str] = []
    metadata: dict[str, str] = {}
    stats: dict[str, Any] = {}
    digest = ""
    if not cache.is_file():
        return stats, metadata, digest, [f"Frozen development cache is missing: {cache}."]
    try:
        digest = _file_sha256(cache)
        metadata, has_metadata = load_cache_metadata_readonly(cache)
        stats, has_bars = load_cache_bar_stats_readonly(cache)
        provenance = load_cache_provenance_readonly(cache, metadata)
        stats.update(provenance)
    except (OSError, sqlite3.Error, ValueError) as exc:
        return stats, metadata, digest, [f"Development cache cannot be verified: {exc}."]
    if not has_metadata:
        errors.append("Development cache has no research_metadata table.")
    if not has_bars:
        errors.append("Development cache has no bars table.")
    else:
        errors.extend(cache_data_identity_blockers(stats, metadata))
        lineage_metadata_present = any(
            str(metadata.get(key, "") or "").strip()
            for key in (
                "cache_logical_bar_fingerprint",
                "cache_logical_bar_fingerprint_algorithm",
                "cache_latest_import_batch_id",
                "cache_lineage_schema_version",
            )
        )
        lineage_rows = int(stats.get("provenance_lineage_record_count") or 0)
        lineage_batches = int(stats.get("provenance_batch_count") or 0)
        legacy_unlineaged = (
            not lineage_metadata_present and lineage_rows == 0 and lineage_batches == 0
        )
        if legacy_unlineaged:
            stats["source_lineage_status"] = "LEGACY_FROZEN_PREFIX_WITHOUT_LINEAGE"
        else:
            provenance_errors = cache_provenance_blockers(stats, metadata)
            errors.extend(provenance_errors)
            stats["source_lineage_status"] = (
                "VERIFIED" if not provenance_errors else "INVALID_OR_PARTIAL"
            )
    cutoff_text = cutoff.isoformat() if cutoff else ""
    if str(stats.get("bar_end") or "") != cutoff_text:
        errors.append(
            f"Development cache bar_end must equal frozen cutoff {cutoff_text or 'invalid'}."
        )
    if has_bars:
        uri = cache.resolve().as_posix()
        try:
            with sqlite3.connect(f"file:{uri}?mode=ro", uri=True) as conn:
                prefix = logical_bar_fingerprint_from_connection(conn, end=cutoff_text)
                full = logical_bar_fingerprint_from_connection(conn)
        except sqlite3.Error as exc:
            errors.append(f"Development logical fingerprint cannot be recomputed: {exc}.")
        else:
            if not expected_prefix or prefix != expected_prefix or full != expected_prefix:
                errors.append("Development cache logical bars differ from the exact frozen prefix.")
    return stats, metadata, digest, list(dict.fromkeys(errors))


def _report_from_context(
    context: _EvidenceContext,
    inputs: dict[str, Any],
    *,
    blockers: tuple[str, ...],
    materialized: bool = False,
    output_cache: dict[str, Any] | None = None,
    replay_manifest: dict[str, Any] | None = None,
    source_hash_after: str = "",
) -> ProspectiveExecutionCacheMaterialization:
    replay = replay_manifest or _replay_manifest(context)
    replay_hash = _canonical_sha256(replay) if replay else ""
    source = _source_development(context)
    if materialized:
        source.update(
            {
                "sha256_after": source_hash_after,
                "unchanged": hmac.compare_digest(
                    context.source_cache_sha256,
                    source_hash_after,
                ),
            }
        )
    body = {
        "artifact_type": ARTIFACT_TYPE,
        "schema_version": SCHEMA_VERSION,
        "operation": "post_holdout_guarded_execution_cache_materialization",
        "network_access": False,
        "broker_access": False,
        "holdout_analysis_performed": False,
        "paper_trading_allowed": False,
        "live_trading_allowed": False,
        "status": "PASS" if materialized else "BLOCK",
        "sufficient": materialized,
        "materialized": materialized,
        "evaluated_at_utc": context.now.replace(microsecond=0).isoformat(),
        "evaluated_market_date": context.now.astimezone(ZoneInfo(MARKET_TIMEZONE))
        .date()
        .isoformat(),
        "market_timezone": MARKET_TIMEZONE,
        "trial_id": context.trial_id,
        "candidate": context.candidate,
        "boundaries": context.boundaries,
        "inputs": inputs,
        "source_development": source,
        "collection": _collection_summary(context),
        "replay_manifest": replay,
        "replay_manifest_sha256": replay_hash,
        "output_cache": output_cache or {},
        "source_qa": _source_qa_summary(context),
        "calendar": _calendar_summary(context),
        "market_evidence": _market_summary(context),
        "checks": [item.to_dict() for item in context.checks],
        "blockers": list(blockers),
        "next_actions": list(_next_actions(context.checks, materialized=materialized)),
        "prohibited_actions": list(PROHIBITED_ACTIONS),
    }
    artifact_hash = _canonical_sha256(body) if materialized else ""
    return ProspectiveExecutionCacheMaterialization(
        artifact_type=ARTIFACT_TYPE,
        schema_version=SCHEMA_VERSION,
        status="PASS" if materialized else "BLOCK",
        materialized=materialized,
        evaluated_at_utc=body["evaluated_at_utc"],
        evaluated_market_date=body["evaluated_market_date"],
        market_timezone=MARKET_TIMEZONE,
        trial_id=context.trial_id,
        candidate=context.candidate,
        boundaries=context.boundaries,
        inputs=inputs,
        source_development=source,
        collection=body["collection"],
        replay_manifest=replay,
        replay_manifest_sha256=replay_hash,
        output_cache=output_cache or {},
        source_qa=body["source_qa"],
        calendar=body["calendar"],
        market_evidence=body["market_evidence"],
        checks=tuple(context.checks),
        blockers=blockers,
        next_actions=tuple(body["next_actions"]),
        prohibited_actions=PROHIBITED_ACTIONS,
        artifact_sha256=artifact_hash,
    )


def _replay_manifest(context: _EvidenceContext) -> dict[str, Any]:
    output_cache_path = context.output_dir / CACHE_FILENAME
    return {
        "schema_version": 1,
        "trial_id": context.trial_id,
        "candidate": context.candidate,
        "packet_sha256": context.packet_verification.packet_sha256,
        "frozen_execution_config_fingerprint": _text(
            (context.packet.get("fingerprints") or {}).get("config_fingerprint")
        ),
        "terminal_execution_cache_override": str(output_cache_path),
        "preregistration_event_hash": context.preregistration_event_hash,
        "development_cache_sha256": context.source_cache_sha256,
        "development_prefix_logical_fingerprint": _text(
            (context.packet.get("fingerprints") or {}).get("data_fingerprint")
        ),
        "calendar_csv_sha256": context.calendar_report.csv_sha256,
        "calendar_metadata_sha256": context.calendar_report.metadata_sha256,
        "source_qa_files": context.source_qa_files,
        "market_evidence_files": _market_file_bindings(context.market_report),
        "collection_ledger_sha256": _optional_file_sha256(
            context.quarantine_root / LEDGER_FILENAME
        ),
        "collection_event_hashes": [
            _text(event.get("event_hash")) for event in context.ledger_events
        ],
        "attempt_journal_sha256": _optional_file_sha256(
            context.quarantine_root / ATTEMPT_LEDGER_FILENAME
        ),
        "attempt_event_hashes": [
            _text(event.get("event_hash")) for event in context.attempt_events
        ],
        "replay_batches": [
            {key: value for key, value in entry.items() if key != "ledger_event"}
            for entry in context.replay_entries
        ],
    }


def _source_development(context: _EvidenceContext) -> dict[str, Any]:
    return {
        "path": str(context.source_cache),
        "sha256_before": context.source_cache_sha256,
        "bar_count": int(context.source_cache_stats.get("bar_count") or 0),
        "symbol_count": int(context.source_cache_stats.get("symbol_count") or 0),
        "bar_start": str(context.source_cache_stats.get("bar_start") or ""),
        "bar_end": str(context.source_cache_stats.get("bar_end") or ""),
        "logical_bar_fingerprint": str(
            context.source_cache_stats.get("logical_bar_fingerprint_actual") or ""
        ),
        "logical_bar_fingerprint_algorithm": LOGICAL_BAR_FINGERPRINT_ALGORITHM,
        "source_lineage_status": str(
            context.source_cache_stats.get("source_lineage_status") or "INVALID_OR_UNKNOWN"
        ),
    }


def _collection_summary(context: _EvidenceContext) -> dict[str, Any]:
    return {
        "quarantine_root": str(context.quarantine_root),
        "ledger_path": str(context.quarantine_root / LEDGER_FILENAME),
        "ledger_sha256": _optional_file_sha256(context.quarantine_root / LEDGER_FILENAME),
        "ledger_event_count": len(context.ledger_events),
        "ledger_event_hashes": [_text(item.get("event_hash")) for item in context.ledger_events],
        "ledger_tail_hash": _text(context.ledger_events[-1].get("event_hash"))
        if context.ledger_events
        else "",
        "attempt_journal_path": str(context.quarantine_root / ATTEMPT_LEDGER_FILENAME),
        "attempt_journal_sha256": _optional_file_sha256(
            context.quarantine_root / ATTEMPT_LEDGER_FILENAME
        ),
        "attempt_event_count": len(context.attempt_events),
        "attempt_event_hashes": [_text(item.get("event_hash")) for item in context.attempt_events],
        "attempt_tail_hash": _text(context.attempt_events[-1].get("event_hash"))
        if context.attempt_events
        else "",
        "reviewed_open_dates": [entry["market_date"] for entry in context.replay_entries],
        "input_sha256": [entry["raw_sha256"] for entry in context.replay_entries],
    }


def _source_qa_summary(context: _EvidenceContext) -> dict[str, Any]:
    return {
        "status": context.source_qa_review.status,
        "review_stage": context.source_qa_review.review_stage,
        "files": context.source_qa_files,
        "reviewed_by": _text(context.source_qa_review.source_metadata.get("reviewed_by")),
        "reviewed_at": _text(context.source_qa_review.source_metadata.get("reviewed_at")),
        "price_adjustment": _text(context.source_qa_review.source_metadata.get("price_adjustment")),
    }


def _calendar_summary(context: _EvidenceContext) -> dict[str, Any]:
    return {
        "status": context.calendar_report.status,
        "csv_path": context.calendar_report.calendar_csv_path,
        "csv_sha256": context.calendar_report.csv_sha256,
        "metadata_path": context.calendar_report.metadata_path,
        "metadata_sha256": context.calendar_report.metadata_sha256,
        "required_start_date": context.calendar_report.required_start_date,
        "required_end_date": context.calendar_report.required_end_date,
        "open_session_count": len(context.replay_entries),
    }


def _market_summary(context: _EvidenceContext) -> dict[str, Any]:
    return {
        "status": context.market_report.status,
        "files": _market_file_bindings(context.market_report),
        "required_start_date": context.market_report.required_start_date,
        "required_end_date": context.market_report.required_end_date,
        "minimum_members_per_snapshot": context.market_report.minimum_members_per_snapshot,
    }


def _market_file_bindings(report: MarketEvidencePreflightReport) -> dict[str, dict[str, str]]:
    return {
        "benchmark_csv": {
            "path": report.benchmark_csv.file.path,
            "sha256": report.benchmark_csv.file.sha256 or "",
        },
        "benchmark_metadata": {
            "path": report.benchmark_metadata_file.path,
            "sha256": report.benchmark_metadata_file.sha256 or "",
        },
        "membership_csv": {
            "path": report.membership_csv.file.path,
            "sha256": report.membership_csv.file.sha256 or "",
        },
        "membership_metadata": {
            "path": report.membership_metadata_file.path,
            "sha256": report.membership_metadata_file.sha256 or "",
        },
    }


def _market_evidence_not_future(
    report: MarketEvidencePreflightReport,
    evaluated_at: datetime,
) -> bool:
    values = (
        report.benchmark_metadata.get("source_exported_at"),
        report.benchmark_metadata.get("reviewed_at"),
        report.membership_metadata.get("source_exported_at"),
        report.membership_metadata.get("reviewed_at"),
    )
    timestamps: list[datetime] = []
    for value in values:
        if not isinstance(value, str):
            return False
        try:
            timestamp = datetime.fromisoformat(value)
        except ValueError:
            return False
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            return False
        timestamps.append(timestamp)
    return all(timestamp <= evaluated_at for timestamp in timestamps)


def _source_qa_file_bindings(
    checklist: Path,
    answers: Path,
    manifest: Path,
) -> dict[str, dict[str, str]]:
    return {
        "checklist": {"path": str(checklist), "sha256": _optional_file_sha256(checklist)},
        "answers": {"path": str(answers), "sha256": _optional_file_sha256(answers)},
        "evidence_manifest": {
            "path": str(manifest),
            "sha256": _optional_file_sha256(manifest),
        },
    }


def _source_qa_coverage(
    checklist: Path,
    required_start: date | None,
    required_end: date | None,
) -> bool:
    payload, error = _load_json_object(checklist)
    start = _iso_date(payload.get("start"))
    end = _iso_date(payload.get("end"))
    return (
        not error
        and start is not None
        and end is not None
        and required_start is not None
        and required_end is not None
        and start <= required_start
        and end >= required_end
    )


def _source_qa_timestamps_not_future(
    review: DataSourceQAReview,
    evaluated_market_date: date,
) -> bool:
    exported = _metadata_date(review.source_metadata.get("exported_at_local_time"))
    reviewed = _metadata_date(review.source_metadata.get("reviewed_at"))
    return (
        exported is not None
        and reviewed is not None
        and exported <= reviewed <= evaluated_market_date
    )


def _metadata_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def _membership_snapshots(path: Path) -> dict[str, list[str]]:
    snapshots: dict[str, list[str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if str(row.get("index_code") or "").strip().split(".")[0] != "000906":
                continue
            effective = str(row.get("effective_date") or "").strip()
            symbol = str(row.get("symbol") or "").strip().split(".")[0].zfill(6)
            snapshots.setdefault(effective, []).append(symbol)
    return {effective: sorted(set(symbols)) for effective, symbols in sorted(snapshots.items())}


def _input_paths(**values: Any) -> dict[str, Any]:
    root = _workspace_root(values.pop("workspace_root", None))
    minimum = int(values.pop("minimum_members_per_snapshot"))
    resolved = {key: str(_resolve_path(value, root)) for key, value in values.items()}
    resolved["workspace_root"] = str(root)
    resolved["minimum_members_per_snapshot"] = minimum
    return resolved


def _paths_disjoint(output: Path, *inputs: Path) -> bool:
    output_resolved = output.resolve()
    for item in inputs:
        resolved = item.resolve()
        if output_resolved == resolved:
            return False
        try:
            output_resolved.relative_to(resolved)
        except ValueError:
            pass
        else:
            return False
        try:
            resolved.relative_to(output_resolved)
        except ValueError:
            pass
        else:
            return False
    return True


def _publish_directory(staging: Path, output: Path) -> None:
    gc.collect()
    for attempt in range(10):
        try:
            os.replace(staging, output)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.05 * (attempt + 1))


def _remove_tree(path: Path) -> None:
    gc.collect()
    for attempt in range(10):
        try:
            shutil.rmtree(path)
            return
        except PermissionError:
            if attempt == 9:
                return
            time.sleep(0.05 * (attempt + 1))


def _same_path(raw: Any, expected: Path) -> bool:
    if not isinstance(raw, str) or not raw:
        return False
    try:
        return Path(raw).resolve() == expected.resolve()
    except OSError:
        return False


def _materialized_source_type(source: str) -> str:
    family = _source_route_family(source)
    if family == "akshare":
        return "akshare_prospective_materialization"
    if family == "csv":
        return "guarded_local_csv"
    return f"{family or 'unknown'}_prospective_materialization"


def _source_route_family(value: str) -> str:
    source = value.strip().lower()
    if source in {"csv", "local_csv", "guarded_local_csv", "offline_csv", "tdx_csv"}:
        return "csv"
    if source in {"akshare", "sina", "eastmoney", "akshare_api", "akshare_research_import"}:
        return "akshare"
    return source


def _source_qa_route_matches(source: str, metadata: dict[str, Any]) -> bool:
    family = _source_route_family(source)
    declared = " ".join(
        (
            _text(metadata.get("data_vendor_or_broker")),
            _text(metadata.get("terminal_or_product_name")),
        )
    ).lower()
    if not declared:
        return False
    if family == "akshare":
        return any(marker in declared for marker in ("akshare", "eastmoney", "sina"))
    if family == "csv":
        return True
    return bool(family) and family in declared


def _batch_id(trial_id: str, label: str, digest: str) -> str:
    safe_trial = re.sub(r"[^A-Za-z0-9_.-]+", "-", trial_id).strip("-") or "trial"
    safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-") or "batch"
    return f"prospective-{safe_trial}-{safe_label}-{digest[:16]}"


def _development_cache_path(packet: dict[str, Any], root: Path) -> Path:
    development = packet.get("development_data")
    raw = _text(development.get("cache_path")) if isinstance(development, dict) else ""
    return _resolve_path(raw or "__missing_development_cache__", root)


def _configured_source(packet: dict[str, Any]) -> str:
    execution = packet.get("execution_config")
    data = execution.get("data") if isinstance(execution, dict) else None
    return _text(data.get("source")) if isinstance(data, dict) else ""


def _frozen_adjustment(packet: dict[str, Any]) -> str:
    execution = packet.get("execution_config")
    data = execution.get("data") if isinstance(execution, dict) else None
    return _text(data.get("adjust")).lower() if isinstance(data, dict) else ""


def _boundaries(packet: dict[str, Any]) -> dict[str, dict[str, str]]:
    raw = packet.get("boundaries")
    if not isinstance(raw, dict):
        return {}
    output: dict[str, dict[str, str]] = {}
    for name in ("train", "selection", "test"):
        value = raw.get(name)
        if isinstance(value, dict):
            output[name] = {
                "start": _text(value.get("start")),
                "end": _text(value.get("end")),
            }
    return output


def _boundary_date(
    boundaries: dict[str, dict[str, str]],
    section: str,
    field: str,
) -> date | None:
    return _iso_date(boundaries.get(section, {}).get(field))


def _next_actions(
    checks: list[MaterializationCheck],
    *,
    materialized: bool,
) -> tuple[str, ...]:
    if materialized:
        return (
            "Run read-only materialization verification, then pass its exact artifact to prospective trial admission.",
            "If admission passes, run the frozen terminal research analysis exactly once; do not authorize trading.",
        )
    blocked = {item.code for item in checks if item.status == "BLOCK"}
    actions: list[str] = []
    if "POST_HOLDOUT_TIME_SEAL" in blocked:
        actions.append(
            "Keep the holdout sealed and continue append-only daily collection; do not inspect retained rows."
        )
    if "FROZEN_DEVELOPMENT_CACHE" in blocked:
        actions.append(
            "Restore the exact lineage-aware frozen development cache; never patch it in place."
        )
    if "REVIEWED_SOURCE_QA" in blocked:
        actions.append(
            "Complete genuine source QA and retained evidence attachments for the full train-through-test interval."
        )
    if "REVIEWED_EXCHANGE_CALENDAR" in blocked:
        actions.append(
            "Provide a hash-bound, human-reviewed A-share exchange calendar covering the entire holdout."
        )
    if "REVIEWED_MARKET_EVIDENCE" in blocked:
        actions.append(
            "Provide reviewed CSI 800 total-return and PIT membership evidence through the test end."
        )
    if "COMPLETE_REVIEWED_SESSION_CONTINUITY" in blocked:
        actions.append(
            "Resolve missing/tampered ledger, attempt-journal, or sealed-input evidence without refetching a prior PASS date."
        )
    if "SINGLE_USE_OUTPUT_DIRECTORY" in blocked:
        actions.append(
            "Choose a new, absent output directory; completed materializations cannot be replaced."
        )
    return tuple(dict.fromkeys(actions))


def _check(
    checks: list[MaterializationCheck],
    code: str,
    passed: bool,
    message: str,
) -> None:
    checks.append(MaterializationCheck(code, "PASS" if passed else "BLOCK", message))


def _blockers(checks: list[MaterializationCheck]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.message for item in checks if item.status == "BLOCK"))


def _load_json_object(path: Path) -> tuple[dict[str, Any], str]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return {}, f"{type(exc).__name__}: {exc}"
    if not isinstance(payload, dict):
        return {}, "JSON root is not an object"
    return payload, ""


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError(f"duplicate JSON key {key!r}")
        output[key] = value
    return output


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value!r}")


def _canonical_sha256(payload: Any) -> str:
    encoded = _canonical_json(payload)
    return hashlib.sha256(encoded).hexdigest()


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
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


def _optional_file_sha256(path: Path) -> str:
    try:
        return _file_sha256(path)
    except OSError:
        return ""


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and _HASH_PATTERN.fullmatch(value) is not None


def _iso_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _workspace_root(value: str | Path | None) -> Path:
    if value is not None and str(value):
        return Path(value).resolve()
    return Path(__file__).resolve().parents[3]


def _resolve_path(value: str | Path, root: Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _runtime_now() -> datetime:
    return datetime.now(UTC)
