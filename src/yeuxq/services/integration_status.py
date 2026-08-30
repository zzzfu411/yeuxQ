"""Strict, fail-closed reader for the integration status projection."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import json
import os
from pathlib import Path
import stat
from typing import Any


SUPPORTED_SCHEMA_VERSION = "1.0.0"
MAX_STATUS_BYTES = 1_048_576

_ROOT_FIELDS = {
    "schema_version",
    "updated_at",
    "project",
    "overall",
    "frontend_sync",
    "verification",
    "boundaries",
    "phases",
    "risks",
    "excluded_scope",
    "next_actions",
}
_OVERALL_FIELDS = {
    "status",
    "active_phase",
    "completed_phases",
    "total_phases",
    "progress_percent",
    "release_readiness",
    "release_block_reason",
    "operating_boundary",
}
_PHASE_FIELDS = {
    "id",
    "order",
    "name",
    "status",
    "progress_percent",
    "started_at",
    "completed_at",
    "owner",
    "evidence",
    "acceptance",
}
_PHASE_OPTIONAL_FIELDS = {"notes", "release_blockers_outside_phase"}
_RISK_FIELDS = {
    "id",
    "priority",
    "title",
    "status",
    "owner",
    "release_blocking",
    "closure",
}
_PHASE_STATES = {"not_started", "in_progress", "completed", "blocked"}
_READINESS_STATES = {"PASS", "WATCH", "BLOCK"}
_RISK_STATES = {"open", "mitigated", "closed"}
_VERIFICATION_STATES = {"PASS", "WATCH", "BLOCK", "NOT_RUN"}


class _StatusInvalid(ValueError):
    pass


def _is_record(value: object) -> bool:
    return isinstance(value, Mapping) and all(isinstance(key, str) for key in value)


def _record(value: object, name: str) -> Mapping[str, Any]:
    if not _is_record(value):
        raise _StatusInvalid(f"{name} must be an object")
    return value  # type: ignore[return-value]


def _exact_fields(value: Mapping[str, Any], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise _StatusInvalid(f"{name} has an unsupported schema")


def _string(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise _StatusInvalid(f"{name} must be a string")
    return value


def _boolean(value: object, name: str, expected: bool | None = None) -> bool:
    if not isinstance(value, bool) or (expected is not None and value is not expected):
        raise _StatusInvalid(f"{name} has an invalid boolean value")
    return value


def _integer(value: object, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise _StatusInvalid(f"{name} is outside its integer boundary")
    return value


def _enum(value: object, allowed: set[str], name: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise _StatusInvalid(f"{name} contains an unknown state")
    return value


def _string_list(value: object, name: str, *, maximum: int = 1_000) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise _StatusInvalid(f"{name} must be a bounded array")
    for index, item in enumerate(value):
        _string(item, f"{name}[{index}]")
    return value


def _iso_datetime(value: object, name: str) -> str:
    text = _string(value, name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _StatusInvalid(f"{name} must use ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _StatusInvalid(f"{name} must include a timezone")
    return text


def _validate_project(value: object) -> None:
    project = _record(value, "project")
    for key in (
        "name",
        "canonical_repo_id",
        "canonical_local_path",
        "canonical_remote",
        "canonical_python_core",
        "integration_namespace",
    ):
        _string(project.get(key), f"project.{key}")
    donor = _record(project.get("donor"), "project.donor")
    reference = _record(project.get("reference_only"), "project.reference_only")
    if donor.get("role") != "donor" or reference.get("role") != "reference_only":
        raise _StatusInvalid("project source roles are invalid")
    for name, item in (("donor", donor), ("reference_only", reference)):
        for key in ("id", "local_path", "copy_policy"):
            _string(item.get(key), f"project.{name}.{key}")


def _validate_frontend(value: object) -> None:
    frontend = _record(value, "frontend_sync")
    _boolean(frontend.get("required"), "frontend_sync.required", True)
    if frontend.get("source_of_truth") != "integration/integration_status.json":
        raise _StatusInvalid("frontend_sync source_of_truth is invalid")
    if frontend.get("unknown_or_invalid_state") != "BLOCK":
        raise _StatusInvalid("frontend_sync must fail closed")
    _boolean(frontend.get("ui_mutation_allowed"), "frontend_sync.ui_mutation_allowed", False)
    if frontend.get("target_http_method") != "GET":
        raise _StatusInvalid("frontend_sync must remain read-only")


def _validate_verification(value: object) -> None:
    verification = _record(value, "verification")
    _iso_datetime(verification.get("verified_at"), "verification.verified_at")
    for key in ("status_contract", "json_parser", "diff_check"):
        _enum(verification.get(key), _VERIFICATION_STATES, f"verification.{key}")
    for key in ("targeted_tests", "full_tests"):
        tests = _record(verification.get(key), f"verification.{key}")
        _enum(tests.get("status"), _VERIFICATION_STATES, f"verification.{key}.status")
        _integer(tests.get("passed"), f"verification.{key}.passed", 0, 10_000_000)
        _integer(tests.get("failed"), f"verification.{key}.failed", 0, 10_000_000)
    scan = _record(verification.get("secret_scan"), "verification.secret_scan")
    _enum(scan.get("status"), _VERIFICATION_STATES, "verification.secret_scan.status")
    _integer(scan.get("candidate_files"), "verification.secret_scan.candidate_files", 0, 10_000_000)
    build = _record(verification.get("distribution_build"), "verification.distribution_build")
    _enum(build.get("status"), _VERIFICATION_STATES, "verification.distribution_build.status")
    _boolean(build.get("contains_quantify"), "distribution_build.contains_quantify", True)
    _boolean(build.get("contains_yeuxq"), "distribution_build.contains_yeuxq", True)


def _validate_boundaries(value: object) -> None:
    boundaries = _record(value, "boundaries")
    observation = _record(boundaries.get("live_observation"), "boundaries.live_observation")
    _boolean(
        observation.get("research_eligible_by_default"),
        "boundaries.live_observation.research_eligible_by_default",
        False,
    )
    safety = _record(
        observation.get("fixed_safety_fields"),
        "boundaries.live_observation.fixed_safety_fields",
    )
    _boolean(safety.get("prohibited_live_use"), "fixed_safety_fields.prohibited_live_use", True)
    _boolean(safety.get("broker_access"), "fixed_safety_fields.broker_access", False)
    _boolean(
        safety.get("live_trading_allowed"),
        "fixed_safety_fields.live_trading_allowed",
        False,
    )
    research = _record(boundaries.get("research"), "boundaries.research")
    if research.get("mode") != "research_only":
        raise _StatusInvalid("research boundary mode is invalid")
    _boolean(
        research.get("implicit_observation_promotion"),
        "boundaries.research.implicit_observation_promotion",
        False,
    )
    execution = _record(boundaries.get("execution"), "boundaries.execution")
    for key in ("broker_integration", "account_access", "live_orders", "automatic_trading"):
        _boolean(execution.get(key), f"boundaries.execution.{key}", False)
    _boolean(execution.get("paper_simulation_only"), "execution.paper_simulation_only", True)


def _validate_phases(value: object) -> tuple[list[Mapping[str, Any]], set[str]]:
    if not isinstance(value, list) or not value or len(value) > 100:
        raise _StatusInvalid("phases must be a bounded non-empty array")
    phases: list[Mapping[str, Any]] = []
    identifiers: set[str] = set()
    orders: set[int] = set()
    for index, raw in enumerate(value):
        phase = _record(raw, f"phases[{index}]")
        if not _PHASE_FIELDS <= set(phase) or set(phase) - _PHASE_FIELDS - _PHASE_OPTIONAL_FIELDS:
            raise _StatusInvalid(f"phases[{index}] has an unsupported schema")
        identifier = _string(phase.get("id"), f"phases[{index}].id")
        if not identifier.replace("_", "a").isalnum() or not identifier[0].islower():
            raise _StatusInvalid("phase id must be lower snake_case")
        order = _integer(phase.get("order"), f"phases[{index}].order", 0, 99)
        if identifier in identifiers or order in orders:
            raise _StatusInvalid("phase ids and orders must be unique")
        identifiers.add(identifier)
        orders.add(order)
        _string(phase.get("name"), f"phases[{index}].name")
        state = _enum(phase.get("status"), _PHASE_STATES, f"phases[{index}].status")
        progress = _integer(
            phase.get("progress_percent"), f"phases[{index}].progress_percent", 0, 100
        )
        if (state == "completed" and progress != 100) or (state == "not_started" and progress != 0):
            raise _StatusInvalid("phase status conflicts with progress")
        _string(phase.get("owner"), f"phases[{index}].owner")
        _string_list(phase.get("evidence"), f"phases[{index}].evidence")
        _string_list(phase.get("acceptance"), f"phases[{index}].acceptance")
        phases.append(phase)
    return phases, identifiers


def _validate_risks(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or len(value) > 1_000:
        raise _StatusInvalid("risks must be a bounded array")
    risks: list[Mapping[str, Any]] = []
    identifiers: set[str] = set()
    for index, raw in enumerate(value):
        risk = _record(raw, f"risks[{index}]")
        _exact_fields(risk, _RISK_FIELDS, f"risks[{index}]")
        identifier = _string(risk.get("id"), f"risks[{index}].id")
        if identifier in identifiers:
            raise _StatusInvalid("risk ids must be unique")
        identifiers.add(identifier)
        _enum(risk.get("priority"), {"P0", "P1"}, f"risks[{index}].priority")
        _enum(risk.get("status"), _RISK_STATES, f"risks[{index}].status")
        _string(risk.get("title"), f"risks[{index}].title")
        _string(risk.get("owner"), f"risks[{index}].owner")
        _boolean(risk.get("release_blocking"), f"risks[{index}].release_blocking")
        _string(risk.get("closure"), f"risks[{index}].closure")
        risks.append(risk)
    return risks


def validate_integration_status(payload: object) -> tuple[str, ...]:
    """Return validation errors; an empty tuple means the payload is trusted."""

    try:
        root = _record(payload, "root")
        _exact_fields(root, _ROOT_FIELDS, "root")
        if root.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
            raise _StatusInvalid("schema_version is unsupported")
        _iso_datetime(root.get("updated_at"), "updated_at")
        _validate_project(root.get("project"))

        overall = _record(root.get("overall"), "overall")
        _exact_fields(overall, _OVERALL_FIELDS, "overall")
        _enum(overall.get("status"), _PHASE_STATES, "overall.status")
        active_phase = _string(overall.get("active_phase"), "overall.active_phase")
        completed = _integer(overall.get("completed_phases"), "overall.completed_phases", 0, 100)
        total = _integer(overall.get("total_phases"), "overall.total_phases", 1, 100)
        _integer(overall.get("progress_percent"), "overall.progress_percent", 0, 100)
        readiness = _enum(
            overall.get("release_readiness"), _READINESS_STATES, "overall.release_readiness"
        )
        _string(
            overall.get("release_block_reason"), "overall.release_block_reason", allow_empty=True
        )
        if overall.get("operating_boundary") != "research_only_advisory_only":
            raise _StatusInvalid("overall operating boundary is invalid")

        _validate_frontend(root.get("frontend_sync"))
        _validate_verification(root.get("verification"))
        _validate_boundaries(root.get("boundaries"))
        phases, phase_ids = _validate_phases(root.get("phases"))
        risks = _validate_risks(root.get("risks"))
        if total != len(phases) or completed != sum(
            phase.get("status") == "completed" for phase in phases
        ):
            raise _StatusInvalid("overall phase counts are inconsistent")
        if active_phase not in phase_ids:
            raise _StatusInvalid("overall active_phase is unknown")
        if readiness != "BLOCK" and any(
            risk.get("release_blocking") is True and risk.get("status") != "closed"
            for risk in risks
        ):
            raise _StatusInvalid("open release risks require BLOCK")
        _string_list(root.get("excluded_scope"), "excluded_scope")
        actions = root.get("next_actions")
        if not isinstance(actions, list) or len(actions) > 1_000:
            raise _StatusInvalid("next_actions must be a bounded array")
        for index, raw_action in enumerate(actions):
            action = _record(raw_action, f"next_actions[{index}]")
            _exact_fields(action, {"order", "phase", "action", "blocking"}, "next_action")
            _integer(action.get("order"), "next_action.order", 0, 10_000)
            _string(action.get("phase"), "next_action.phase")
            _string(action.get("action"), "next_action.action")
            _boolean(action.get("blocking"), "next_action.blocking")
    except _StatusInvalid as exc:
        return (str(exc),)
    return ()


def blocked_integration_status(reason: str) -> dict[str, Any]:
    return {
        "valid": False,
        "release_readiness": "BLOCK",
        "reason": reason,
        "status": None,
    }


def project_integration_status(payload: object) -> dict[str, Any]:
    """Validate a parsed payload and return a bounded public projection."""

    if isinstance(payload, Mapping) and payload.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        return blocked_integration_status("STATUS_SCHEMA_UNSUPPORTED")
    if validate_integration_status(payload):
        return blocked_integration_status("STATUS_INVALID")
    try:
        normalized = json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError):
        return blocked_integration_status("STATUS_INVALID")
    return {
        "valid": True,
        "release_readiness": normalized["overall"]["release_readiness"],
        "reason": None,
        "status": normalized,
    }


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _StatusInvalid("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise _StatusInvalid(f"unsupported JSON constant: {value}")


def _read_bounded(path: Path) -> bytes:
    if path.is_symlink():
        raise _StatusInvalid("status source must not be a symlink")
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_STATUS_BYTES:
            raise _StatusInvalid("status source is not a bounded regular file")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(65_536, MAX_STATUS_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_STATUS_BYTES:
                raise _StatusInvalid("status source exceeds its size boundary")
        after = os.fstat(descriptor)
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
        ):
            raise _StatusInvalid("status source changed while being read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


class IntegrationStatusService:
    """Read one configured status file without accepting a request path or URL."""

    def __init__(self, status_file: str | os.PathLike[str]) -> None:
        if not isinstance(status_file, (str, os.PathLike)) or not str(status_file).strip():
            raise ValueError("status_file must be an explicit local path")
        self._status_file = Path(status_file)

    @property
    def status_file(self) -> Path:
        return self._status_file

    def read(self) -> dict[str, Any]:
        try:
            raw = _read_bounded(self._status_file)
            payload = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_json_constant,
            )
        except FileNotFoundError:
            return blocked_integration_status("STATUS_UNAVAILABLE")
        except (OSError, UnicodeDecodeError):
            return blocked_integration_status("STATUS_UNAVAILABLE")
        except (json.JSONDecodeError, _StatusInvalid):
            return blocked_integration_status("STATUS_INVALID")
        return project_integration_status(payload)

    def get_integration_status(self) -> dict[str, Any]:
        return self.read()


__all__ = [
    "IntegrationStatusService",
    "MAX_STATUS_BYTES",
    "SUPPORTED_SCHEMA_VERSION",
    "blocked_integration_status",
    "project_integration_status",
    "validate_integration_status",
]
