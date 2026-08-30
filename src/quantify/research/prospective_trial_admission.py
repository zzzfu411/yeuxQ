"""Dynamic, fail-closed admission for a frozen prospective trial.

The frozen packet records what was known at registration time.  This module
does not mutate that packet.  It recomputes the evidence that can legitimately
arrive later and keeps the holdout sealed through its registered end date.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
import json
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from quantify.data.cache_metadata import (
    PromotionMetadataCheck,
    build_promotion_metadata_check,
    write_promotion_metadata_check,
)
from quantify.data.market_evidence_preflight import (
    MarketEvidencePreflightReport,
    build_market_evidence_preflight,
    write_market_evidence_preflight,
)
from quantify.research.prospective_execution_cache_materialization import (
    ProspectiveExecutionCacheMaterializationVerification,
    build_prospective_execution_cache_materialization_verification,
)
from quantify.research.prospective_trial_packet import (
    ProspectiveTrialPacketVerification,
    build_prospective_trial_packet_verification,
    write_prospective_trial_packet_verification,
)
from quantify.research.trial_registry import (
    PreregistrationEvent,
    ResultEvent,
    TrialRegistryError,
    verify_registry,
)

AdmissionStatus = Literal["PASS", "BLOCK"]
MARKET_TIMEZONE = "Asia/Shanghai"

PROHIBITED_ACTIONS = (
    "Do not inspect, backtest, tune, or report the prospective holdout through its registered end date.",
    "Do not edit the frozen packet, config, code bindings, registry, or pre-holdout data to obtain PASS.",
    "Do not patch cache metadata or fabricate source, reviewer, benchmark, membership, or lineage evidence.",
    "Do not run the terminal analysis more than once or append a replacement result event.",
    "Do not treat admission PASS as paper, micro-live, profit, or broker authorization.",
    "Do not generate or submit real broker orders from this workflow.",
)


@dataclass(frozen=True, slots=True)
class AdmissionCheck:
    code: str
    status: AdmissionStatus
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "status": self.status, "message": self.message}


@dataclass(frozen=True, slots=True)
class ProspectiveTrialAdmission:
    artifact_type: str
    schema_version: int
    status: AdmissionStatus
    evaluated_at_utc: str
    evaluated_market_date: str
    market_timezone: str
    trial_id: str
    candidate: str
    phase: str
    boundaries: dict[str, dict[str, str]]
    execution_cache_path: str
    execution_cache_source: str
    collection_ready: bool
    terminal_analysis_allowed: bool
    paper_trading_allowed: bool
    live_trading_allowed: bool
    registry_state: dict[str, Any]
    checks: tuple[AdmissionCheck, ...]
    blockers: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    next_actions: tuple[str, ...]
    prohibited_actions: tuple[str, ...]
    packet_verification: ProspectiveTrialPacketVerification
    promotion_metadata: PromotionMetadataCheck
    market_evidence: MarketEvidencePreflightReport
    materialization_verification: ProspectiveExecutionCacheMaterializationVerification | None

    @property
    def sufficient(self) -> bool:
        return self.status == "PASS" and self.terminal_analysis_allowed

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "schema_version": self.schema_version,
            "operation": "read_only_prospective_trial_admission",
            "network_access": False,
            "broker_access": False,
            "status": self.status,
            "sufficient": self.sufficient,
            "evaluated_at_utc": self.evaluated_at_utc,
            "evaluated_market_date": self.evaluated_market_date,
            "market_timezone": self.market_timezone,
            "trial_id": self.trial_id,
            "candidate": self.candidate,
            "phase": self.phase,
            "boundaries": self.boundaries,
            "execution_cache_path": self.execution_cache_path,
            "execution_cache_source": self.execution_cache_source,
            "collection_ready": self.collection_ready,
            "terminal_analysis_allowed": self.terminal_analysis_allowed,
            "paper_trading_allowed": self.paper_trading_allowed,
            "live_trading_allowed": self.live_trading_allowed,
            "registry_state": self.registry_state,
            "checks": [item.to_dict() for item in self.checks],
            "blockers": list(self.blockers),
            "missing_evidence": list(self.missing_evidence),
            "next_actions": list(self.next_actions),
            "prohibited_actions": list(self.prohibited_actions),
            "packet_verification": self.packet_verification.to_dict(),
            "promotion_metadata": self.promotion_metadata.to_dict(),
            "market_evidence": self.market_evidence.to_dict(),
            "materialization_verification": (
                self.materialization_verification.to_dict()
                if self.materialization_verification is not None
                else None
            ),
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Prospective Trial Admission: {self.status}",
            "",
            f"- Trial: `{self.trial_id or 'unavailable'}`",
            f"- Candidate: `{self.candidate or 'unavailable'}`",
            f"- Phase: `{self.phase}`",
            f"- Evaluated at UTC: `{self.evaluated_at_utc}`",
            f"- A-share market date: `{self.evaluated_market_date}` ({self.market_timezone})",
            f"- Execution cache: `{self.execution_cache_path or 'unavailable'}`",
            f"- Execution cache source: `{self.execution_cache_source}`",
            f"- Append-only collection ready: `{self.collection_ready}`",
            f"- Terminal holdout analysis allowed: `{self.terminal_analysis_allowed}`",
            f"- Paper trading allowed: `{self.paper_trading_allowed}`",
            f"- Live trading allowed: `{self.live_trading_allowed}`",
            "",
            "This is a read-only evidence admission report. It does not run the strategy, "
            "open the holdout, append a result, or authorize trading.",
            "",
            "## Checks",
            "",
        ]
        lines.extend(f"- `{item.status}` `{item.code}`: {item.message}" for item in self.checks)
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- {item}" for item in self.blockers or ("None.",))
        lines.extend(["", "## Missing Evidence", ""])
        lines.extend(f"- {item}" for item in self.missing_evidence or ("None.",))
        lines.extend(["", "## Next Actions", ""])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Prohibited Actions", ""])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        lines.append("")
        return "\n".join(lines)


def build_prospective_trial_admission(
    *,
    packet_dir: str | Path,
    registry_path: str | Path,
    benchmark_csv: str | Path,
    benchmark_metadata: str | Path,
    membership_csv: str | Path,
    membership_metadata: str | Path,
    workspace_root: str | Path | None = None,
    minimum_members_per_snapshot: int = 700,
    require_source_qa_evidence_manifest: bool = True,
    materialization_artifact: str | Path | None = None,
) -> ProspectiveTrialAdmission:
    """Recompute every dynamic gate before a terminal holdout analysis."""
    root = _workspace_root(workspace_root)
    evaluated_at = _runtime_now()
    evaluated_date = evaluated_at.astimezone(ZoneInfo(MARKET_TIMEZONE)).date()
    packet_root = _resolve_path(packet_dir, root)
    registry = _resolve_path(registry_path, root)
    packet, packet_error = _load_json_object(packet_root / "prospective_trial_packet.json")

    packet_verification = build_prospective_trial_packet_verification(
        packet_root,
        registry,
        workspace_root=root,
    )
    boundaries = _boundaries(packet)
    trial_id = _text(packet.get("trial_id"))
    candidate = _text(packet.get("candidate"))
    train_start = _boundary_date(boundaries, "train", "start")
    test_start = _boundary_date(boundaries, "test", "start")
    test_end = _boundary_date(boundaries, "test", "end")

    registered_execution_cache = _execution_cache_path(packet, root)
    development_cache = _development_cache_path(packet, root)
    registered_cache_is_distinct = (
        registered_execution_cache.resolve() != development_cache.resolve()
    )
    materialization_verification: ProspectiveExecutionCacheMaterializationVerification | None = None
    if materialization_artifact is not None:
        materialization_verification = (
            build_prospective_execution_cache_materialization_verification(
                _resolve_path(materialization_artifact, root),
                packet_dir=packet_root,
                registry_path=registry,
                workspace_root=root,
            )
        )
        execution_cache = Path(materialization_verification.output_cache_path)
        execution_cache_source = "post_holdout_materialization"
        execution_cache_boundary_ready = (
            materialization_verification.status == "PASS"
            and materialization_verification.trial_id == trial_id
            and execution_cache.resolve() != development_cache.resolve()
        )
    else:
        execution_cache = registered_execution_cache
        execution_cache_source = (
            "registered_distinct_future_cache"
            if registered_cache_is_distinct
            else "invalid_frozen_development_cache"
        )
        execution_cache_boundary_ready = registered_cache_is_distinct
    promotion_metadata_report = build_promotion_metadata_check(
        execution_cache,
        require_evidence_manifest=require_source_qa_evidence_manifest,
    )
    market_report = build_market_evidence_preflight(
        _resolve_path(benchmark_csv, root),
        _resolve_path(benchmark_metadata, root),
        _resolve_path(membership_csv, root),
        _resolve_path(membership_metadata, root),
        required_start_date=train_start,
        required_end_date=test_end,
        minimum_members_per_snapshot=minimum_members_per_snapshot,
    )

    checks: list[AdmissionCheck] = []
    _check(
        checks,
        "TERMINAL_EXECUTION_CACHE_BOUNDARY",
        execution_cache_boundary_ready,
        (
            "Verified post-holdout materialization supplies a new cache without changing the frozen development prefix."
            if materialization_verification is not None and execution_cache_boundary_ready
            else "Frozen packet registered a genuinely distinct future execution cache."
            if registered_cache_is_distinct and materialization_artifact is None
            else "Terminal execution requires a verified materialization artifact because the registered execution cache is the frozen development cache."
        ),
    )
    _check(
        checks,
        "PACKET_INTEGRITY",
        packet_verification.status == "PASS" and not packet_error,
        "Frozen packet, code, config, development prefix, and registry binding verify."
        if packet_verification.status == "PASS" and not packet_error
        else "Frozen packet integrity or registry binding does not verify.",
    )

    preregistrations = 0
    results = 0
    registry_error = ""
    try:
        events = verify_registry(registry)
    except (OSError, TrialRegistryError) as exc:
        events = []
        registry_error = f"{type(exc).__name__}: {exc}"
    else:
        preregistrations = sum(
            isinstance(event, PreregistrationEvent) and event.trial_id == trial_id
            for event in events
        )
        results = sum(
            isinstance(event, ResultEvent) and event.trial_id == trial_id for event in events
        )
    registry_clean = not registry_error and preregistrations == 1 and results == 0
    _check(
        checks,
        "TERMINAL_RESULT_ABSENT",
        registry_clean,
        "Registry contains one preregistration and no terminal result for this trial."
        if registry_clean
        else _registry_message(registry_error, preregistrations, results),
    )
    _check(
        checks,
        "SOURCE_QA_AND_LINEAGE",
        promotion_metadata_report.status == "PASS",
        "Execution cache source QA, retained hashes, canonical identity, and row lineage verify."
        if promotion_metadata_report.status == "PASS"
        else "Execution cache is not promotion-safe; source QA or import lineage is incomplete.",
    )
    configured_source = _configured_source(packet)
    cached_source = _text(promotion_metadata_report.metadata.get("data_source"))
    source_identity_ready = (
        bool(configured_source)
        and bool(cached_source)
        and _source_route_family(configured_source) == _source_route_family(cached_source)
    )
    _check(
        checks,
        "CONFIGURED_SOURCE_IDENTITY",
        source_identity_ready,
        f"Frozen source route {configured_source!r} matches cache provenance {cached_source!r}."
        if source_identity_ready
        else (
            "Frozen execution source and cache provenance must both be present and use the "
            f"same route family; configured={configured_source or 'missing'!r}, "
            f"cached={cached_source or 'missing'!r}."
        ),
    )
    _check(
        checks,
        "MARKET_EVIDENCE",
        market_report.status == "PASS",
        "Reviewed CSI 800 total-return and PIT membership evidence verify."
        if market_report.status == "PASS"
        else "Reviewed CSI 800 total-return or PIT membership evidence is incomplete or invalid.",
    )
    materialization_market_ready = (
        materialization_verification is None
        or _materialization_market_evidence_matches(
            materialization_verification,
            market_report,
        )
    )
    _check(
        checks,
        "MATERIALIZATION_MARKET_EVIDENCE_BINDING",
        materialization_market_ready,
        "Admission benchmark and PIT membership files match the materialization hashes."
        if materialization_verification is not None and materialization_market_ready
        else "Registered distinct-cache admission has no materialization evidence substitution."
        if materialization_verification is None
        else "Admission benchmark or PIT membership file differs from materialization evidence.",
    )
    market_timestamps_ready = _market_timestamps_not_future(market_report, evaluated_at)
    _check(
        checks,
        "MARKET_EVIDENCE_NOT_FUTURE_DATED",
        market_timestamps_ready,
        "Market evidence export and review timestamps are not later than this admission run."
        if market_timestamps_ready
        else "Market evidence timestamps are missing, invalid, or later than this admission run.",
    )

    timing_ready = test_end is not None and evaluated_date > test_end
    _check(
        checks,
        "HOLDOUT_TIME_SEAL",
        timing_ready,
        f"Registered holdout ended on {test_end.isoformat()}; terminal analysis may be considered."
        if timing_ready and test_end is not None
        else _time_seal_message(evaluated_date, test_start, test_end),
    )

    cache_stats = promotion_metadata_report.cache_stats
    cache_start = _iso_date(cache_stats.get("bar_start"))
    cache_end = _iso_date(cache_stats.get("bar_end"))
    coverage_ready = (
        train_start is not None
        and test_end is not None
        and cache_start is not None
        and cache_end is not None
        and cache_start <= train_start
        and cache_end >= test_end
    )
    _check(
        checks,
        "EXECUTION_CACHE_COVERAGE",
        coverage_ready,
        "Execution cache covers the complete frozen train-through-test interval."
        if coverage_ready
        else _coverage_message(cache_start, cache_end, train_start, test_end),
    )

    collection_ready = (
        packet_verification.status == "PASS"
        and not packet_error
        and registry_clean
        and execution_cache_boundary_ready
        and promotion_metadata_report.status == "PASS"
        and source_identity_ready
    )
    terminal_analysis_allowed = all(item.status == "PASS" for item in checks)
    blockers = tuple(dict.fromkeys(item.message for item in checks if item.status == "BLOCK"))
    missing_evidence = _missing_evidence(
        packet_verification,
        promotion_metadata_report,
        market_report,
        coverage_ready=coverage_ready,
        execution_cache_boundary_ready=execution_cache_boundary_ready,
    )
    phase = _phase(evaluated_date, test_start, test_end, results)
    registry_state = {
        "path": str(registry),
        "chain_error": registry_error,
        "matching_preregistrations": preregistrations,
        "matching_results": results,
        "terminal_result_recorded": results > 0,
    }
    return ProspectiveTrialAdmission(
        artifact_type="prospective_trial_admission",
        schema_version=2,
        status="PASS" if terminal_analysis_allowed else "BLOCK",
        evaluated_at_utc=evaluated_at.replace(microsecond=0).isoformat(),
        evaluated_market_date=evaluated_date.isoformat(),
        market_timezone=MARKET_TIMEZONE,
        trial_id=trial_id,
        candidate=candidate,
        phase=phase,
        boundaries=boundaries,
        execution_cache_path=str(execution_cache),
        execution_cache_source=execution_cache_source,
        collection_ready=collection_ready,
        terminal_analysis_allowed=terminal_analysis_allowed,
        paper_trading_allowed=False,
        live_trading_allowed=False,
        registry_state=registry_state,
        checks=tuple(checks),
        blockers=blockers,
        missing_evidence=missing_evidence,
        next_actions=_next_actions(
            checks,
            test_end=test_end,
            results=results,
            collection_ready=collection_ready,
        ),
        prohibited_actions=PROHIBITED_ACTIONS,
        packet_verification=packet_verification,
        promotion_metadata=promotion_metadata_report,
        market_evidence=market_report,
        materialization_verification=materialization_verification,
    )


def write_prospective_trial_admission(
    report: ProspectiveTrialAdmission,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "prospective_trial_admission.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, allow_nan=False, indent=2),
        encoding="utf-8",
    )
    (root / "prospective_trial_admission.md").write_text(
        report.to_markdown(),
        encoding="utf-8",
    )
    write_prospective_trial_packet_verification(report.packet_verification, root)
    write_promotion_metadata_check(report.promotion_metadata, root)
    write_market_evidence_preflight(report.market_evidence, root)
    return root


def _check(
    checks: list[AdmissionCheck],
    code: str,
    passed: bool,
    message: str,
) -> None:
    checks.append(AdmissionCheck(code, "PASS" if passed else "BLOCK", message))


def _workspace_root(value: str | Path | None) -> Path:
    if value is not None:
        return Path(value).resolve()
    return Path(__file__).resolve().parents[3]


def _resolve_path(value: str | Path, root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _execution_cache_path(packet: dict[str, Any], root: Path) -> Path:
    execution = packet.get("execution_config")
    if not isinstance(execution, dict):
        return root / "__missing_execution_cache__"
    data = execution.get("data")
    if not isinstance(data, dict):
        return root / "__missing_execution_cache__"
    raw = _text(data.get("cache_path"))
    return _resolve_path(raw or "__missing_execution_cache__", root)


def _development_cache_path(packet: dict[str, Any], root: Path) -> Path:
    development = packet.get("development_data")
    if not isinstance(development, dict):
        return root / "__missing_development_cache__"
    raw = _text(development.get("cache_path"))
    return _resolve_path(raw or "__missing_development_cache__", root)


def _configured_source(packet: dict[str, Any]) -> str:
    execution = packet.get("execution_config")
    if not isinstance(execution, dict):
        return ""
    data = execution.get("data")
    return _text(data.get("source")) if isinstance(data, dict) else ""


def _source_route_family(value: str) -> str:
    source = value.strip().lower()
    if source in {"csv", "local_csv", "guarded_local_csv", "offline_csv", "tdx_csv"}:
        return "csv"
    if source in {"akshare", "sina", "eastmoney", "akshare_api", "akshare_research_import"}:
        return "akshare"
    return source


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


def _iso_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


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
        return {}, "packet JSON root is not an object"
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


def _runtime_now() -> datetime:
    return datetime.now(UTC)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _market_timestamps_not_future(
    market: MarketEvidencePreflightReport,
    evaluated_at: datetime,
) -> bool:
    values = [
        market.benchmark_metadata.get("source_exported_at"),
        market.benchmark_metadata.get("reviewed_at"),
        market.membership_metadata.get("source_exported_at"),
        market.membership_metadata.get("reviewed_at"),
    ]
    parsed: list[datetime] = []
    for value in values:
        if not isinstance(value, str):
            return False
        try:
            timestamp = datetime.fromisoformat(value)
        except ValueError:
            return False
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            return False
        parsed.append(timestamp)
    return all(timestamp <= evaluated_at for timestamp in parsed)


def _materialization_market_evidence_matches(
    verification: ProspectiveExecutionCacheMaterializationVerification,
    market: MarketEvidencePreflightReport,
) -> bool:
    expected = verification.market_evidence_files
    observed = {
        "benchmark_csv": market.benchmark_csv.file.sha256 or "",
        "benchmark_metadata": market.benchmark_metadata_file.sha256 or "",
        "membership_csv": market.membership_csv.file.sha256 or "",
        "membership_metadata": market.membership_metadata_file.sha256 or "",
    }
    return bool(expected) and all(
        isinstance(expected.get(name), dict)
        and expected[name].get("sha256") == digest
        and bool(digest)
        for name, digest in observed.items()
    )


def _registry_message(error: str, preregistrations: int, results: int) -> str:
    if error:
        return f"Trial registry cannot be verified: {error}."
    if preregistrations != 1:
        return f"Expected exactly one preregistration; found {preregistrations}."
    return (
        f"Trial already has {results} terminal result event(s); repeat analysis and "
        "result replacement are prohibited."
    )


def _time_seal_message(
    evaluated: date,
    test_start: date | None,
    test_end: date | None,
) -> str:
    if test_start is None or test_end is None:
        return "Registered test boundaries are missing or invalid."
    if evaluated < test_start:
        return f"Prospective holdout has not started; it opens on {test_start.isoformat()}."
    return (
        f"Prospective holdout is sealed through {test_end.isoformat()}; do not inspect or "
        "analyze its observations before the next UTC date."
    )


def _coverage_message(
    actual_start: date | None,
    actual_end: date | None,
    required_start: date | None,
    required_end: date | None,
) -> str:
    actual = f"{actual_start or 'missing'} to {actual_end or 'missing'}"
    required = f"{required_start or 'invalid'} to {required_end or 'invalid'}"
    return f"Execution cache coverage is {actual}; required frozen coverage is {required}."


def _phase(
    evaluated: date,
    test_start: date | None,
    test_end: date | None,
    results: int,
) -> str:
    if results:
        return "TERMINAL_RESULT_RECORDED"
    if test_start is None or test_end is None:
        return "INVALID_BOUNDARIES"
    if evaluated < test_start:
        return "PRE_HOLDOUT"
    if evaluated <= test_end:
        return "HOLDOUT_SEALED"
    return "POST_HOLDOUT_ADMISSION"


def _missing_evidence(
    verification: ProspectiveTrialPacketVerification,
    promotion: PromotionMetadataCheck,
    market: MarketEvidencePreflightReport,
    *,
    coverage_ready: bool,
    execution_cache_boundary_ready: bool,
) -> tuple[str, ...]:
    items: list[str] = []
    if verification.status != "PASS":
        items.append("A fully verified frozen packet and registry binding.")
    if promotion.status != "PASS":
        items.append(
            "Promotion-safe source QA, retained evidence hashes, and complete import lineage."
        )
    if market.status != "PASS":
        items.append("Reviewed CSI 800 total-return and effective-dated PIT membership evidence.")
    if not execution_cache_boundary_ready:
        items.append("A verified post-holdout materialization artifact for a new execution cache.")
    if not coverage_ready:
        items.append(
            "A provenance-aware execution cache covering the complete frozen test end date."
        )
    return tuple(items)


def _next_actions(
    checks: list[AdmissionCheck],
    *,
    test_end: date | None,
    results: int,
    collection_ready: bool,
) -> tuple[str, ...]:
    blocked = {item.code for item in checks if item.status == "BLOCK"}
    actions: list[str] = []
    if "PACKET_INTEGRITY" in blocked:
        actions.append(
            "Restore the exact retained packet, config, code bindings, registry, and pre-holdout prefix; do not rewrite them."
        )
    if "TERMINAL_EXECUTION_CACHE_BOUNDARY" in blocked:
        actions.append(
            "After the holdout, materialize exact sealed inputs into a new cache and pass its verified artifact; never append to the frozen development cache."
        )
    if "SOURCE_QA_AND_LINEAGE" in blocked:
        actions.append(
            "Complete reviewed source QA, then re-import through guarded provenance-aware intake; do not patch the cache in place."
        )
    if "CONFIGURED_SOURCE_IDENTITY" in blocked:
        actions.append(
            "Use a provenance-aware cache whose recorded source route matches the frozen execution configuration."
        )
    if "MARKET_EVIDENCE" in blocked:
        actions.append(
            "Acquire and retain reviewed CSI 800 total-return and historical PIT membership files, then rerun strict preflight."
        )
    if "MARKET_EVIDENCE_NOT_FUTURE_DATED" in blocked and "MARKET_EVIDENCE" not in blocked:
        actions.append(
            "Reject future-dated metadata; rerun admission only after the retained export and human review actually occur."
        )
    if "MATERIALIZATION_MARKET_EVIDENCE_BINDING" in blocked:
        actions.append(
            "Use the exact benchmark and PIT membership files hash-bound by the materialization artifact."
        )
    if "EXECUTION_CACHE_COVERAGE" in blocked:
        actions.append(
            "Complete sealed collection and guarded post-holdout materialization until the new cache covers the frozen test end."
        )
    if "HOLDOUT_TIME_SEAL" in blocked and test_end is not None:
        actions.append(
            f"Keep the holdout sealed through {test_end.isoformat()}; collect append-only data without inspecting candidate results."
        )
    if results:
        actions.append(
            "Do not rerun the trial; review the single retained terminal result and its bound artifacts."
        )
    elif not blocked:
        actions.append(
            "Run the frozen terminal analysis exactly once and append one hash-bound result event for deterministic review."
        )
    elif collection_ready:
        actions.append(
            "Collection prerequisites pass; continue append-only daily ingestion without opening the holdout."
        )
    return tuple(dict.fromkeys(actions))
