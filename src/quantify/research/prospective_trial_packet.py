"""Freeze a prospective research protocol before its holdout begins.

The packet binds the candidate implementation, parameters, exact execution
configuration, development-data prefix, boundaries, and stop rules.  It may
preregister a research-only trial, but it never authorizes execution or live
trading.  Future run manifests recompute the prefix fingerprint so appending
new holdout bars does not erase the pre-holdout identity.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import yaml

from quantify.data.cache_metadata import build_promotion_metadata_check
from quantify.data.provenance import LOGICAL_BAR_FINGERPRINT_ALGORITHM
from quantify.data.storage import BarStorage
from quantify.research.candidates import CandidateSpec, candidate_spec_by_name
from quantify.research.trial_registry import PreregistrationEvent, append_preregistration
from quantify.research.trial_registry import TrialRegistryError, verify_registry
from quantify.utils.config import Config, load_config

PROSPECTIVE_TRIAL_PACKET_SCHEMA_VERSION = 1
PROSPECTIVE_TRIAL_PACKET_ARTIFACT_TYPE = "prospective_trial_packet"
PacketStatus = Literal["FROZEN_RESEARCH_ONLY", "BLOCK"]

DEFAULT_CODE_PATHS = (
    "src/quantify/research/candidates.py",
    "src/quantify/research/factors.py",
    "src/quantify/research/strategy.py",
    "src/quantify/research/walk_forward_protocol.py",
    "src/quantify/research/robustness.py",
    "src/quantify/engine/backtest.py",
    "src/quantify/engine/paper_broker.py",
    "src/quantify/risk/manager.py",
)

PROHIBITED_ACTIONS = (
    "Do not use observations dated before test_start as prospective holdout evidence.",
    "Do not change candidate code, parameters, boundaries, metrics, or stop rules after registration.",
    "Do not treat this packet or registry append as data provenance, benchmark, strategy, or promotion PASS.",
    "Do not enter paper or micro-live readiness while any deterministic evidence gate is BLOCK.",
    "Do not generate or submit real broker orders from this workflow.",
)


@dataclass(frozen=True, slots=True)
class ProspectiveTrialPacket:
    artifact_type: str
    schema_version: int
    status: PacketStatus
    packet_id: str
    trial_id: str
    created_at_utc: str
    candidate: str
    hypothesis: str
    development_cutoff: str
    boundaries: dict[str, dict[str, str]]
    candidate_snapshot: dict[str, Any]
    execution_config: dict[str, Any]
    execution_config_filename: str
    fingerprints: dict[str, Any]
    development_data: dict[str, Any]
    external_evidence: dict[str, Any]
    required_data: list[str]
    required_tests: list[str]
    stop_conditions: list[str]
    prohibited_actions: list[str]
    missing_evidence: list[str]
    blockers: list[str]
    registry_append_allowed: bool
    execution_allowed: bool
    registration_payload: dict[str, Any] | None
    packet_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "schema_version": self.schema_version,
            "status": self.status,
            "packet_id": self.packet_id,
            "trial_id": self.trial_id,
            "created_at_utc": self.created_at_utc,
            "candidate": self.candidate,
            "hypothesis": self.hypothesis,
            "development_cutoff": self.development_cutoff,
            "boundaries": self.boundaries,
            "candidate_snapshot": self.candidate_snapshot,
            "execution_config": self.execution_config,
            "execution_config_filename": self.execution_config_filename,
            "fingerprints": self.fingerprints,
            "development_data": self.development_data,
            "external_evidence": self.external_evidence,
            "required_data": self.required_data,
            "required_tests": self.required_tests,
            "stop_conditions": self.stop_conditions,
            "prohibited_actions": self.prohibited_actions,
            "missing_evidence": self.missing_evidence,
            "blockers": self.blockers,
            "registry_append_allowed": self.registry_append_allowed,
            "execution_allowed": self.execution_allowed,
            "registration_payload": self.registration_payload,
            "packet_sha256": self.packet_sha256,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Prospective Trial Packet: {self.status}",
            "",
            f"- Packet: `{self.packet_id}`",
            f"- Trial: `{self.trial_id}`",
            f"- Candidate: `{self.candidate}`",
            f"- Created at UTC: `{self.created_at_utc}`",
            f"- Development cutoff: `{self.development_cutoff}`",
            f"- Packet SHA-256: `{self.packet_sha256}`",
            f"- Parameter fingerprint: `{self.fingerprints.get('parameter_fingerprint', '')}`",
            f"- Protocol fingerprint: `{self.fingerprints.get('protocol_fingerprint', '')}`",
            f"- Config fingerprint: `{self.fingerprints.get('config_fingerprint', '')}`",
            f"- Development prefix fingerprint: `{self.fingerprints.get('data_fingerprint', '')}`",
            f"- Registry append allowed: `{self.registry_append_allowed}`",
            f"- Experiment execution allowed: `{self.execution_allowed}`",
            "",
            "## Frozen Boundaries",
            "",
        ]
        for name in ("train", "selection", "test"):
            boundary = self.boundaries.get(name, {})
            lines.append(f"- {name}: `{boundary.get('start', '')}` to `{boundary.get('end', '')}`")
        lines.extend(["", "## Missing Evidence", ""])
        lines.extend(f"- {item}" for item in self.missing_evidence or ["None."])
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- {item}" for item in self.blockers or ["None."])
        lines.extend(["", "## Stop Conditions", ""])
        lines.extend(f"- {item}" for item in self.stop_conditions)
        lines.extend(["", "## Prohibited Actions", ""])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        lines.extend(
            [
                "",
                "This artifact freezes a falsification protocol only. It is not a profit claim, "
                "data approval, paper approval, or live-trading authorization.",
                "",
            ]
        )
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class ProspectiveTrialPacketVerification:
    artifact_type: str
    schema_version: int
    status: Literal["PASS", "BLOCK"]
    packet_path: str
    registry_path: str
    trial_id: str
    packet_sha256: str
    registry_tail_hash: str
    checks: list[dict[str, Any]]
    blockers: list[str]
    execution_allowed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "schema_version": self.schema_version,
            "status": self.status,
            "packet_path": self.packet_path,
            "registry_path": self.registry_path,
            "trial_id": self.trial_id,
            "packet_sha256": self.packet_sha256,
            "registry_tail_hash": self.registry_tail_hash,
            "checks": self.checks,
            "blockers": self.blockers,
            "execution_allowed": self.execution_allowed,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Prospective Trial Packet Verification: {self.status}",
            "",
            f"- Trial: `{self.trial_id or 'unavailable'}`",
            f"- Packet: `{self.packet_path}`",
            f"- Packet SHA-256: `{self.packet_sha256 or 'unavailable'}`",
            f"- Registry: `{self.registry_path}`",
            f"- Registry tail: `{self.registry_tail_hash or 'unavailable'}`",
            f"- Execution allowed: `{self.execution_allowed}`",
            "",
            "## Checks",
            "",
        ]
        lines.extend(
            f"- `{item['status']}` `{item['name']}`: {item['message']}" for item in self.checks
        )
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- {item}" for item in self.blockers or ["None."])
        lines.extend(
            [
                "",
                "Integrity PASS cannot upgrade source QA, market evidence, strategy, paper, "
                "or live-trading gates.",
                "",
            ]
        )
        return "\n".join(lines)


def build_prospective_trial_packet(
    *,
    plan_path: str | Path,
    base_config_path: str | Path,
    development_cache_path: str | Path,
    execution_cache_path: str | Path,
    trial_id: str,
    candidate: str,
    train_start: str,
    train_end: str,
    selection_start: str,
    selection_end: str,
    test_start: str,
    test_end: str,
    created_at: str | None = None,
    execution_results_dir: str = "results/prospective/guard_v1",
    market_evidence_preflight: str | Path | None = None,
    code_paths: list[str | Path] | None = None,
) -> ProspectiveTrialPacket:
    """Build an immutable protocol packet without running the strategy."""
    plan_file = Path(plan_path)
    config_file = Path(base_config_path)
    cache_file = Path(development_cache_path)
    created_at_utc = _timestamp(created_at)
    boundaries = {
        "train": {"start": train_start, "end": train_end},
        "selection": {"start": selection_start, "end": selection_end},
        "test": {"start": test_start, "end": test_end},
    }
    blockers = _boundary_blockers(boundaries, selection_end)
    if created_at is not None:
        blockers.append(
            "caller-supplied created_at cannot authorize a prospective registry append; "
            "use the runtime UTC clock"
        )
    if candidate.strip() == "":
        blockers.append("candidate must be non-empty")
    if trial_id.strip() == "":
        blockers.append("trial_id must be non-empty")

    plan, plan_error = _load_json_object(plan_file)
    if plan_error:
        blockers.append(plan_error)
    else:
        if str(plan.get("candidate") or "") != candidate:
            blockers.append("plan candidate does not match the requested candidate")
        plan_cutoff = str((plan.get("development_data") or {}).get("end") or "")
        if plan_cutoff != selection_end:
            blockers.append("plan development-data cutoff does not match selection_end")
    hypothesis = str(plan.get("hypothesis") or "").strip()
    if not hypothesis:
        blockers.append("plan hypothesis is missing")

    config: Config | None = None
    if not config_file.is_file():
        blockers.append(f"base config does not exist: {config_file}")
    else:
        try:
            config = load_config(config_file)
        except (OSError, TypeError, yaml.YAMLError) as exc:
            blockers.append(f"base config cannot be loaded: {type(exc).__name__}: {exc}")

    candidate_snapshot: dict[str, Any] = {}
    if config is not None:
        try:
            spec = candidate_spec_by_name(config, candidate)
        except (AttributeError, TypeError, ValueError) as exc:
            blockers.append(f"candidate cannot be resolved from config: {exc}")
        else:
            candidate_snapshot = _candidate_snapshot(spec)

    resolved_code_paths = _resolve_code_paths(code_paths)
    code_bindings, code_errors = _file_bindings(resolved_code_paths)
    blockers.extend(code_errors)
    plan_sha256 = _file_sha256(plan_file)
    if not plan_sha256:
        blockers.append("plan SHA-256 is unavailable")

    parameter_fingerprint = _canonical_sha256(
        {
            "candidate_snapshot": candidate_snapshot,
            "code_bindings": code_bindings,
        }
    )
    protocol_fingerprint = _canonical_sha256(
        {
            "plan_sha256": plan_sha256,
            "candidate": candidate,
            "hypothesis": hypothesis,
            "parameter_fingerprint": parameter_fingerprint,
            "boundaries": boundaries,
            "required_data": list(plan.get("required_data") or []),
            "required_tests": list(plan.get("required_tests") or []),
            "stop_conditions": list(plan.get("stop_conditions") or []),
            "prohibited_actions": list(PROHIBITED_ACTIONS),
        }
    )
    execution_config = _execution_config(
        config.to_dict() if config is not None else {},
        trial_id=trial_id,
        candidate=candidate,
        parameter_fingerprint=parameter_fingerprint,
        protocol_fingerprint=protocol_fingerprint,
        boundaries=boundaries,
        cache_path=execution_cache_path,
        results_dir=execution_results_dir,
    )
    config_bytes = _yaml_bytes(execution_config)
    config_fingerprint = hashlib.sha256(config_bytes).hexdigest()

    development_data, data_errors = _development_data(cache_file, selection_end)
    blockers.extend(data_errors)
    data_fingerprint = str(development_data.get("prefix_logical_bar_fingerprint") or "")
    external_evidence, missing_evidence = _external_evidence(
        market_evidence_preflight,
        promotion_status=str(development_data.get("promotion_status") or "BLOCK"),
        promotion_blockers=list(development_data.get("promotion_blockers") or []),
    )

    try:
        created_date = datetime.fromisoformat(created_at_utc).date()
        holdout_start = date.fromisoformat(test_start)
    except ValueError:
        blockers.append("created_at and test_start must be valid ISO-8601 values")
        before_holdout = False
    else:
        before_holdout = created_date < holdout_start
        if not before_holdout:
            blockers.append("protocol must be frozen before test_start; retroactive registration is blocked")

    blockers = list(dict.fromkeys(blockers))
    registry_append_allowed = not blockers and bool(data_fingerprint) and before_holdout
    execution_allowed = (
        registry_append_allowed
        and str(development_data.get("promotion_status")) == "PASS"
        and str(external_evidence.get("status")) == "PASS"
        and not missing_evidence
    )
    registration_payload = None
    if registry_append_allowed:
        registration_payload = {
            "trial_id": trial_id,
            "candidate": candidate,
            "hypothesis": hypothesis,
            "parameter_fingerprint": parameter_fingerprint,
            "data_fingerprint": data_fingerprint,
            "config_fingerprint": config_fingerprint,
            "train_boundary": boundaries["train"],
            "selection_boundary": boundaries["selection"],
            "test_boundary": boundaries["test"],
            "created_at": created_at_utc,
            "prohibited_live_use": True,
        }

    status: PacketStatus = "FROZEN_RESEARCH_ONLY" if registry_append_allowed else "BLOCK"
    fingerprints = {
        "plan_sha256": plan_sha256,
        "parameter_fingerprint": parameter_fingerprint,
        "protocol_fingerprint": protocol_fingerprint,
        "config_fingerprint": config_fingerprint,
        "data_fingerprint": data_fingerprint,
        "data_fingerprint_kind": "logical_bar_prefix_through_selection_end",
        "data_fingerprint_algorithm": LOGICAL_BAR_FINGERPRINT_ALGORITHM,
        "code_bindings": code_bindings,
    }
    payload_without_hash = {
        "artifact_type": PROSPECTIVE_TRIAL_PACKET_ARTIFACT_TYPE,
        "schema_version": PROSPECTIVE_TRIAL_PACKET_SCHEMA_VERSION,
        "status": status,
        "packet_id": str(plan.get("plan_id") or trial_id),
        "trial_id": trial_id,
        "created_at_utc": created_at_utc,
        "candidate": candidate,
        "hypothesis": hypothesis,
        "development_cutoff": selection_end,
        "boundaries": boundaries,
        "candidate_snapshot": candidate_snapshot,
        "execution_config": execution_config,
        "execution_config_filename": "guard_v1_execution.yaml",
        "fingerprints": fingerprints,
        "development_data": development_data,
        "external_evidence": external_evidence,
        "required_data": list(plan.get("required_data") or []),
        "required_tests": list(plan.get("required_tests") or []),
        "stop_conditions": list(plan.get("stop_conditions") or []),
        "prohibited_actions": list(PROHIBITED_ACTIONS),
        "missing_evidence": missing_evidence,
        "blockers": blockers,
        "registry_append_allowed": registry_append_allowed,
        "execution_allowed": execution_allowed,
        "registration_payload": registration_payload,
    }
    return ProspectiveTrialPacket(
        **payload_without_hash,
        packet_sha256=_canonical_sha256(payload_without_hash),
    )


def write_prospective_trial_packet(
    packet: ProspectiveTrialPacket,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    config_path = root / packet.execution_config_filename
    config_path.write_bytes(_yaml_bytes(packet.execution_config))
    (root / "prospective_trial_packet.json").write_text(
        json.dumps(packet.to_dict(), ensure_ascii=False, allow_nan=False, indent=2),
        encoding="utf-8",
    )
    (root / "prospective_trial_packet.md").write_text(packet.to_markdown(), encoding="utf-8")
    if packet.registration_payload is not None:
        (root / "trial_preregistration_payload.json").write_text(
            json.dumps(
                packet.registration_payload,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    return root


def append_packet_preregistration(
    packet: ProspectiveTrialPacket,
    registry_path: str | Path,
) -> PreregistrationEvent:
    if not packet.registry_append_allowed or packet.registration_payload is None:
        raise ValueError("packet is not eligible for registry append")
    expected_hash = _canonical_sha256({
        key: value for key, value in packet.to_dict().items() if key != "packet_sha256"
    })
    if expected_hash != packet.packet_sha256:
        raise ValueError("packet SHA-256 does not verify")
    payload = packet.registration_payload
    return append_preregistration(
        registry_path,
        trial_id=str(payload["trial_id"]),
        candidate=str(payload["candidate"]),
        hypothesis=str(payload["hypothesis"]),
        parameter_fingerprint=str(payload["parameter_fingerprint"]),
        data_fingerprint=str(payload["data_fingerprint"]),
        config_fingerprint=str(payload["config_fingerprint"]),
        train_boundary=payload["train_boundary"],
        selection_boundary=payload["selection_boundary"],
        test_boundary=payload["test_boundary"],
        created_at=str(payload["created_at"]),
        prohibited_live_use=True,
    )


def build_prospective_trial_packet_verification(
    packet_dir: str | Path,
    registry_path: str | Path,
    *,
    workspace_root: str | Path | None = None,
) -> ProspectiveTrialPacketVerification:
    """Recompute every local binding needed to trust a frozen packet."""
    packet_root = Path(packet_dir)
    packet_path = packet_root / "prospective_trial_packet.json"
    registry = Path(registry_path)
    root = (
        Path(workspace_root).resolve()
        if workspace_root is not None
        else Path(__file__).resolve().parents[3]
    )
    checks: list[dict[str, Any]] = []
    blockers: list[str] = []
    packet, packet_error = _load_json_object(packet_path)
    if packet_error:
        _verification_check(checks, blockers, "packet_json", False, packet_error)
        packet = {}
    else:
        valid_contract = (
            packet.get("artifact_type") == PROSPECTIVE_TRIAL_PACKET_ARTIFACT_TYPE
            and packet.get("schema_version") == PROSPECTIVE_TRIAL_PACKET_SCHEMA_VERSION
        )
        _verification_check(
            checks,
            blockers,
            "packet_contract",
            valid_contract,
            "Packet artifact type and schema version match." if valid_contract else "Packet contract is invalid.",
        )

    expected_packet_sha = str(packet.get("packet_sha256") or "")
    packet_body = {key: value for key, value in packet.items() if key != "packet_sha256"}
    actual_packet_sha = _canonical_sha256(packet_body) if packet else ""
    _verification_check(
        checks,
        blockers,
        "packet_sha256",
        bool(expected_packet_sha) and expected_packet_sha == actual_packet_sha,
        "Packet canonical SHA-256 matches." if expected_packet_sha == actual_packet_sha else "Packet canonical SHA-256 mismatch.",
    )

    fingerprints = packet.get("fingerprints") if isinstance(packet.get("fingerprints"), dict) else {}
    config_name = str(packet.get("execution_config_filename") or "guard_v1_execution.yaml")
    config_path = packet_root / config_name
    expected_config_sha = str(fingerprints.get("config_fingerprint") or "")
    actual_config_sha = _file_sha256(config_path)
    _verification_check(
        checks,
        blockers,
        "execution_config",
        bool(expected_config_sha) and expected_config_sha == actual_config_sha,
        "Frozen execution config SHA-256 matches." if expected_config_sha == actual_config_sha else "Frozen execution config SHA-256 mismatch.",
    )

    plan_path = packet_root / "protocol_plan.json"
    expected_plan_sha = str(fingerprints.get("plan_sha256") or "")
    actual_plan_sha = _file_sha256(plan_path)
    _verification_check(
        checks,
        blockers,
        "protocol_plan",
        bool(expected_plan_sha) and expected_plan_sha == actual_plan_sha,
        "Retained protocol plan SHA-256 matches." if expected_plan_sha == actual_plan_sha else "Retained protocol plan SHA-256 mismatch.",
    )

    for binding in fingerprints.get("code_bindings") or []:
        if not isinstance(binding, dict):
            _verification_check(checks, blockers, "code_binding", False, "Code binding is not an object.")
            continue
        raw_path = Path(str(binding.get("path") or ""))
        code_path = raw_path if raw_path.is_absolute() else root / raw_path
        expected = str(binding.get("sha256") or "")
        actual = _file_sha256(code_path)
        _verification_check(
            checks,
            blockers,
            f"code:{binding.get('path')}",
            bool(expected) and expected == actual,
            "Code SHA-256 matches." if expected == actual else "Code SHA-256 mismatch or file missing.",
        )

    development = packet.get("development_data") if isinstance(packet.get("development_data"), dict) else {}
    raw_cache = Path(str(development.get("cache_path") or ""))
    cache_path = raw_cache if raw_cache.is_absolute() else root / raw_cache
    cutoff = str(packet.get("development_cutoff") or "")
    expected_prefix = str(fingerprints.get("data_fingerprint") or "")
    try:
        actual_prefix = BarStorage(cache_path).logical_bar_fingerprint(end=cutoff)
    except Exception as exc:  # noqa: BLE001 - verification reports malformed evidence
        actual_prefix = ""
        prefix_message = f"Development prefix cannot be recomputed: {type(exc).__name__}: {exc}"
    else:
        prefix_message = (
            "Development prefix SHA-256 matches."
            if expected_prefix == actual_prefix
            else "Development prefix SHA-256 mismatch."
        )
    _verification_check(
        checks,
        blockers,
        "development_prefix",
        bool(expected_prefix) and expected_prefix == actual_prefix,
        prefix_message,
    )

    trial_id = str(packet.get("trial_id") or "")
    registry_tail_hash = ""
    registry_event: PreregistrationEvent | None = None
    try:
        events = verify_registry(registry)
    except (OSError, TrialRegistryError) as exc:
        _verification_check(
            checks,
            blockers,
            "registry_chain",
            False,
            f"Registry verification failed: {type(exc).__name__}: {exc}",
        )
    else:
        registry_tail_hash = events[-1].event_hash if events else ""
        matches = [
            event
            for event in events
            if isinstance(event, PreregistrationEvent) and event.trial_id == trial_id
        ]
        registry_event = matches[0] if len(matches) == 1 else None
        _verification_check(
            checks,
            blockers,
            "registry_chain",
            registry_event is not None,
            "Registry chain and unique trial preregistration verify."
            if registry_event is not None
            else "Registry does not contain exactly one matching preregistration.",
        )

    registration = packet.get("registration_payload")
    if registry_event is None or not isinstance(registration, dict):
        registration_matches = False
    else:
        event_payload = registry_event.to_dict()
        registration_matches = all(event_payload.get(key) == value for key, value in registration.items())
    _verification_check(
        checks,
        blockers,
        "registry_packet_binding",
        registration_matches,
        "Registry event matches the packet preregistration payload."
        if registration_matches
        else "Registry event does not match the packet preregistration payload.",
    )

    blockers = list(dict.fromkeys(blockers))
    status: Literal["PASS", "BLOCK"] = "BLOCK" if blockers else "PASS"
    packet_execution_allowed = packet.get("execution_allowed") is True
    return ProspectiveTrialPacketVerification(
        artifact_type="prospective_trial_packet_verification",
        schema_version=1,
        status=status,
        packet_path=str(packet_path),
        registry_path=str(registry),
        trial_id=trial_id,
        packet_sha256=actual_packet_sha,
        registry_tail_hash=registry_tail_hash,
        checks=checks,
        blockers=blockers,
        execution_allowed=status == "PASS" and packet_execution_allowed,
    )


def write_prospective_trial_packet_verification(
    verification: ProspectiveTrialPacketVerification,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "prospective_trial_packet_verification.json").write_text(
        json.dumps(verification.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "prospective_trial_packet_verification.md").write_text(
        verification.to_markdown(),
        encoding="utf-8",
    )
    return root


def _candidate_snapshot(spec: CandidateSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "description": spec.description,
        "factors": [
            {
                "class": f"{factor.__class__.__module__}.{factor.__class__.__qualname__}",
                "name": str(factor.name),
                "higher_is_better": bool(factor.higher_is_better),
            }
            for factor in spec.factors
        ],
        "n_holdings": spec.n_holdings,
        "max_weight": spec.max_weight,
        "rebalance": spec.rebalance,
        "trend_filter": spec.trend_filter,
        "trend_scale": spec.trend_scale,
        "trend_gate": spec.trend_gate,
        "data_dependency": spec.data_dependency,
        "hold_rank_buffer": spec.hold_rank_buffer,
        "min_trade_weight": spec.min_trade_weight,
        "max_new_positions": spec.max_new_positions,
        "score_smoothing_observations": spec.score_smoothing_observations,
        "score_smoothing_step_days": spec.score_smoothing_step_days,
    }


def _execution_config(
    base: dict[str, Any],
    *,
    trial_id: str,
    candidate: str,
    parameter_fingerprint: str,
    protocol_fingerprint: str,
    boundaries: dict[str, dict[str, str]],
    cache_path: str | Path,
    results_dir: str,
) -> dict[str, Any]:
    config = deepcopy(base)
    config.setdefault("research", {})
    config["research"].update(
        {
            "start": boundaries["train"]["start"],
            "end": boundaries["test"]["end"],
            "in_sample_end": boundaries["selection"]["end"],
            "out_sample_start": boundaries["test"]["start"],
            "allow_demo_data": False,
        }
    )
    config.setdefault("data", {})
    config["data"]["cache_path"] = str(cache_path)
    config.setdefault("universe", {})
    config["universe"].update({"mode": "index", "index_code": "000906", "include_st": False})
    config.setdefault("output", {})
    config["output"]["results_dir"] = results_dir
    config["prospective_trial"] = {
        "trial_id": trial_id,
        "candidate": candidate,
        "parameter_fingerprint": parameter_fingerprint,
        "protocol_fingerprint": protocol_fingerprint,
        "prohibited_live_use": True,
    }
    return config


def _development_data(cache: Path, cutoff: str) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    check = build_promotion_metadata_check(cache)
    stats = check.cache_stats
    bar_end = str(stats.get("bar_end") or "")
    if not cache.is_file():
        errors.append(f"development cache does not exist: {cache}")
        prefix = ""
    else:
        try:
            prefix = BarStorage(cache).logical_bar_fingerprint(end=cutoff)
        except Exception as exc:  # noqa: BLE001 - packet must fail closed on malformed SQLite
            errors.append(f"development prefix fingerprint failed: {type(exc).__name__}: {exc}")
            prefix = ""
    if bar_end and bar_end > cutoff:
        errors.append("development cache contains post-cutoff bars; retroactive holdout use is blocked")
    if bar_end and bar_end != cutoff:
        errors.append(f"development cache bar_end must equal cutoff {cutoff}; actual={bar_end}")
    return (
        {
            "cache_path": str(cache),
            "bar_start": str(stats.get("bar_start") or ""),
            "bar_end": bar_end,
            "bar_count": int(stats.get("bar_count") or 0),
            "symbol_count": int(stats.get("symbol_count") or 0),
            "prefix_logical_bar_fingerprint": prefix,
            "prefix_end": cutoff,
            "fingerprint_algorithm": LOGICAL_BAR_FINGERPRINT_ALGORITHM,
            "promotion_status": check.status,
            "promotion_blockers": check.blockers,
            "promotion_eligible": check.status == "PASS",
            "role": "contaminated_development_prefix_not_independent_holdout",
        },
        errors,
    )


def _external_evidence(
    path: str | Path | None,
    *,
    promotion_status: str,
    promotion_blockers: list[str],
) -> tuple[dict[str, Any], list[str]]:
    missing: list[str] = []
    if promotion_status != "PASS":
        missing.append(
            "Promotion-safe source QA and import lineage are not PASS: "
            + (promotion_blockers[0] if promotion_blockers else "unknown blocker")
        )
    if path is None:
        missing.append("PASS market_evidence_preflight.json for CSI 800 total return and PIT membership.")
        return {"status": "MISSING", "path": "", "sha256": ""}, missing
    evidence_path = Path(path)
    payload, error = _load_json_object(evidence_path)
    digest = _file_sha256(evidence_path)
    status = str(payload.get("status") or payload.get("decision") or "BLOCK") if not error else "BLOCK"
    if error:
        missing.append(error)
    elif status != "PASS":
        missing.append(f"Market evidence preflight is {status}, expected PASS.")
    return {
        "status": status,
        "path": str(evidence_path),
        "sha256": digest,
        "artifact_type": str(payload.get("artifact_type") or ""),
    }, missing


def _boundary_blockers(
    boundaries: dict[str, dict[str, str]],
    development_cutoff: str,
) -> list[str]:
    values: list[date] = []
    blockers: list[str] = []
    for name in ("train", "selection", "test"):
        for edge in ("start", "end"):
            raw = boundaries[name][edge]
            try:
                values.append(date.fromisoformat(raw))
            except ValueError:
                blockers.append(f"{name}.{edge} must be an ISO date")
    if len(values) == 6 and not (
        values[0] <= values[1] < values[2] <= values[3] < values[4] <= values[5]
    ):
        blockers.append("train, selection, and test boundaries must be strictly ordered")
    if boundaries["selection"]["end"] != development_cutoff:
        blockers.append("selection.end must equal the development cutoff")
    return blockers


def _resolve_code_paths(paths: list[str | Path] | None) -> list[Path]:
    root = Path(__file__).resolve().parents[3]
    requested = paths if paths is not None else list(DEFAULT_CODE_PATHS)
    return [path if (path := Path(item)).is_absolute() else root / path for item in requested]


def _file_bindings(paths: list[Path]) -> tuple[list[dict[str, Any]], list[str]]:
    root = Path(__file__).resolve().parents[3]
    bindings: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in paths:
        digest = _file_sha256(path)
        if not digest:
            errors.append(f"code binding file is missing or unreadable: {path}")
        try:
            display = path.resolve().relative_to(root).as_posix()
        except ValueError:
            display = str(path.resolve())
        bindings.append({"path": display, "sha256": digest})
    return bindings, errors


def _load_json_object(path: Path) -> tuple[dict[str, Any], str]:
    if not path.is_file():
        return {}, f"JSON evidence does not exist: {path}"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {}, f"JSON evidence cannot be parsed: {path}: {type(exc).__name__}: {exc}"
    if not isinstance(payload, dict):
        return {}, f"JSON evidence root must be an object: {path}"
    return payload, ""


def _timestamp(value: str | None) -> str:
    if value is None:
        return _runtime_now().astimezone(UTC).replace(microsecond=0).isoformat()
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware ISO-8601")
    return parsed.astimezone(UTC).replace(microsecond=0).isoformat()


def _runtime_now() -> datetime:
    return datetime.now(tz=UTC)


def _yaml_bytes(payload: dict[str, Any]) -> bytes:
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=False).encode("utf-8")


def _file_sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _verification_check(
    checks: list[dict[str, Any]],
    blockers: list[str],
    name: str,
    passed: bool,
    message: str,
) -> None:
    status = "PASS" if passed else "BLOCK"
    checks.append({"name": name, "status": status, "message": message})
    if not passed:
        blockers.append(f"{name}: {message}")
