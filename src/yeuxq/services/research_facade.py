"""Read-only projection of canonical quantify readiness artifacts.

This module intentionally does not import the readiness evaluator or any write
helper.  It projects an already-produced ``micro_live_readiness.json`` file and
never lets application, observation, or LLM fields recompute its decision.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any


AUTHORITY = "src/quantify/readiness"
READINESS_FILENAME = "micro_live_readiness.json"
MAX_ARTIFACT_BYTES = 1_048_576
MAX_FINDINGS = 256
MAX_LIST_LIMIT = 200
MAX_DIRECTORY_SCAN = 10_000

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_FINDING_CODE = re.compile(r"^[A-Z][A-Z0-9_:-]{0,63}$")
_DECISIONS = {"PASS", "WATCH", "BLOCK"}
_RISK_KEYS = {
    "manual_reference_only",
    "auto_order_submission",
    "max_position_pct",
    "max_strategy_drawdown_stop",
    "single_day_loss_stop",
    "max_capital_increase_without_new_review",
}
_FAIL_CLOSED_RISK_BUDGET: dict[str, Any] = {
    "manual_reference_only": True,
    "auto_order_submission": False,
    "max_position_pct": 0.0,
    "max_strategy_drawdown_stop": 0.0,
    "single_day_loss_stop": 0.0,
    "max_capital_increase_without_new_review": 0.0,
}
_FAILURE_MESSAGES = {
    "RUN_NOT_FOUND": "The requested canonical research run is unavailable.",
    "READINESS_MISSING": "The canonical readiness artifact is missing.",
    "READINESS_UNREADABLE": "The canonical readiness artifact cannot be read safely.",
    "READINESS_INVALID": "The canonical readiness artifact failed strict validation.",
}


class ResearchFacadeError(RuntimeError):
    """Base class for facade configuration and boundary failures."""


class ResearchFacadeConfigurationError(ResearchFacadeError):
    """Raised when the explicitly allowed results root is invalid."""


class InvalidRunIdError(ResearchFacadeError, ValueError):
    """Raised before filesystem access for an unsafe run identifier."""


class UnsafeResearchPathError(ResearchFacadeError):
    """Raised when a run or artifact resolves outside its allowed boundary."""


class _InvalidArtifact(ValueError):
    pass


def _is_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_run_id(value: object) -> str:
    if not isinstance(value, str) or _RUN_ID.fullmatch(value) is None:
        raise InvalidRunIdError("run_id must be a safe ASCII identifier")
    if value in {".", ".."}:
        raise InvalidRunIdError("run_id must not contain path traversal")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _InvalidArtifact("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise _InvalidArtifact(f"unsupported JSON constant: {value}")


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _validate_risk_budget(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _RISK_KEYS:
        raise _InvalidArtifact("risk_budget has an invalid schema")
    if value["manual_reference_only"] is not True:
        raise _InvalidArtifact("risk_budget must remain manual-reference-only")
    if value["auto_order_submission"] is not False:
        raise _InvalidArtifact("risk_budget must prohibit automatic order submission")

    max_position = _finite_number(value["max_position_pct"])
    drawdown_stop = _finite_number(value["max_strategy_drawdown_stop"])
    daily_stop = _finite_number(value["single_day_loss_stop"])
    capital_increase = _finite_number(value["max_capital_increase_without_new_review"])
    if max_position is None or not 0 < max_position <= 0.05:
        raise _InvalidArtifact("max_position_pct is outside the canonical boundary")
    if drawdown_stop is None or not 0 < drawdown_stop <= 0.15:
        raise _InvalidArtifact("max_strategy_drawdown_stop is outside the canonical boundary")
    if daily_stop is None or not 0 < daily_stop <= 0.02:
        raise _InvalidArtifact("single_day_loss_stop is outside the canonical boundary")
    if capital_increase is None or capital_increase != 0.0:
        raise _InvalidArtifact("capital increase requires a new canonical review")
    return {key: value[key] for key in sorted(_RISK_KEYS)}


def _validate_findings(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > MAX_FINDINGS:
        raise _InvalidArtifact("findings must be a bounded array")
    findings: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"severity", "code", "message"}:
            raise _InvalidArtifact("finding has an invalid schema")
        severity = item["severity"]
        code = item["code"]
        message = item["message"]
        if severity not in _DECISIONS:
            raise _InvalidArtifact("finding severity is unknown")
        if not isinstance(code, str) or _FINDING_CODE.fullmatch(code) is None:
            raise _InvalidArtifact("finding code is invalid")
        if not isinstance(message, str) or not message.strip() or len(message) > 2_048:
            raise _InvalidArtifact("finding message is invalid")
        findings.append({"severity": severity, "code": code, "message": message})
    return findings


def _validate_payload(payload: object) -> tuple[str, list[dict[str, str]], dict[str, Any]]:
    if not isinstance(payload, Mapping):
        raise _InvalidArtifact("readiness payload must be an object")
    if any(key not in payload for key in ("decision", "findings", "risk_budget")):
        raise _InvalidArtifact("readiness payload is missing canonical fields")
    decision = payload["decision"]
    if not isinstance(decision, str) or decision not in _DECISIONS:
        raise _InvalidArtifact("readiness decision is unknown")
    findings = _validate_findings(payload["findings"])
    risk_budget = _validate_risk_budget(payload["risk_budget"])

    severities = {item["severity"] for item in findings}
    derived = "BLOCK" if "BLOCK" in severities else "WATCH" if "WATCH" in severities else "PASS"
    if decision != derived:
        raise _InvalidArtifact("decision conflicts with canonical findings")
    return decision, findings, risk_budget


def _artifact_metadata(data: bytes, details: os.stat_result) -> tuple[str, str, int]:
    digest = hashlib.sha256(data).hexdigest()
    mtime = datetime.fromtimestamp(details.st_mtime, tz=UTC).isoformat()
    return digest, mtime, len(data)


def _read_bounded(path: Path) -> tuple[bytes, os.stat_result]:
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_ARTIFACT_BYTES:
            raise _InvalidArtifact("readiness artifact is not a bounded regular file")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(65_536, MAX_ARTIFACT_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_ARTIFACT_BYTES:
                raise _InvalidArtifact("readiness artifact exceeds its size boundary")
        after = os.fstat(descriptor)
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
        ):
            raise _InvalidArtifact("readiness artifact changed while being read")
        return b"".join(chunks), after
    finally:
        os.close(descriptor)


def _base_projection(
    run_id: str,
    *,
    decision: str,
    findings: list[dict[str, str]],
    risk_budget: dict[str, Any],
    reason: str | None,
    artifact_sha256: str | None,
    artifact_mtime: str | None,
    artifact_size_bytes: int | None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "decision": decision,
        "findings": findings,
        "risk_budget": risk_budget,
        "reason": reason,
        "authority": AUTHORITY,
        "read_only": True,
        "broker_access": False,
        "live_trading_allowed": False,
        "artifact_sha256": artifact_sha256,
        "artifact_mtime": artifact_mtime,
        "artifact_size_bytes": artifact_size_bytes,
    }


def _blocked_projection(
    run_id: str,
    reason: str,
    *,
    artifact_sha256: str | None = None,
    artifact_mtime: str | None = None,
    artifact_size_bytes: int | None = None,
) -> dict[str, Any]:
    return _base_projection(
        run_id,
        decision="BLOCK",
        findings=[
            {
                "severity": "BLOCK",
                "code": reason,
                "message": _FAILURE_MESSAGES[reason],
            }
        ],
        risk_budget=dict(_FAIL_CLOSED_RISK_BUDGET),
        reason=reason,
        artifact_sha256=artifact_sha256,
        artifact_mtime=artifact_mtime,
        artifact_size_bytes=artifact_size_bytes,
    )


class ResearchReadinessFacade:
    """Safely read canonical readiness outputs beneath one explicit root."""

    def __init__(self, allowed_results_root: str | os.PathLike[str]) -> None:
        try:
            root = Path(allowed_results_root).resolve(strict=True)
        except (OSError, TypeError, ValueError) as exc:
            raise ResearchFacadeConfigurationError(
                "allowed_results_root must be an existing directory"
            ) from exc
        if not root.is_dir():
            raise ResearchFacadeConfigurationError("allowed_results_root must be a directory")
        self._root = root

    @property
    def allowed_results_root(self) -> Path:
        return self._root

    def _resolve_run(self, run_id: str) -> Path | None:
        candidate = self._root / run_id
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError:
            return None
        except OSError:
            return None
        if not _is_within(self._root, resolved):
            raise UnsafeResearchPathError("run directory escapes allowed_results_root")
        return resolved if resolved.is_dir() else None

    def read(self, run_id: str) -> dict[str, Any]:
        """Return a validated projection or a fail-closed BLOCK projection."""

        safe_run_id = _validate_run_id(run_id)
        run_root = self._resolve_run(safe_run_id)
        if run_root is None:
            return _blocked_projection(safe_run_id, "RUN_NOT_FOUND")

        artifact = run_root / READINESS_FILENAME
        try:
            resolved_artifact = artifact.resolve(strict=True)
        except FileNotFoundError:
            return _blocked_projection(safe_run_id, "READINESS_MISSING")
        except OSError:
            return _blocked_projection(safe_run_id, "READINESS_UNREADABLE")
        if not _is_within(run_root, resolved_artifact):
            raise UnsafeResearchPathError("readiness artifact escapes its run directory")

        try:
            data, details = _read_bounded(resolved_artifact)
        except _InvalidArtifact:
            return _blocked_projection(safe_run_id, "READINESS_INVALID")
        except OSError:
            return _blocked_projection(safe_run_id, "READINESS_UNREADABLE")
        artifact_sha256, artifact_mtime, artifact_size = _artifact_metadata(data, details)

        try:
            text = data.decode("utf-8")
            payload = json.loads(
                text,
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_json_constant,
            )
            decision, findings, risk_budget = _validate_payload(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, _InvalidArtifact):
            return _blocked_projection(
                safe_run_id,
                "READINESS_INVALID",
                artifact_sha256=artifact_sha256,
                artifact_mtime=artifact_mtime,
                artifact_size_bytes=artifact_size,
            )
        return _base_projection(
            safe_run_id,
            decision=decision,
            findings=findings,
            risk_budget=risk_budget,
            reason=None,
            artifact_sha256=artifact_sha256,
            artifact_mtime=artifact_mtime,
            artifact_size_bytes=artifact_size,
        )

    def get_readiness(self, run_id: str) -> dict[str, Any]:
        """Named alias used by API adapters."""

        return self.read(run_id)

    def list_run_ids(self, *, limit: int = 100) -> list[str]:
        """List only bounded, safe run identifiers without reading artifacts."""

        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_LIST_LIMIT
        ):
            raise ValueError(f"limit must be between 1 and {MAX_LIST_LIMIT}")
        run_ids: list[str] = []
        try:
            entries = self._root.iterdir()
            for index, entry in enumerate(entries):
                if index >= MAX_DIRECTORY_SCAN:
                    break
                try:
                    name = _validate_run_id(entry.name)
                    resolved = entry.resolve(strict=True)
                except (InvalidRunIdError, FileNotFoundError, OSError):
                    continue
                if not _is_within(self._root, resolved) or not resolved.is_dir():
                    continue
                run_ids.append(name)
        except OSError as exc:
            raise ResearchFacadeError("allowed results root cannot be listed") from exc
        return sorted(set(run_ids), reverse=True)[:limit]


__all__ = [
    "AUTHORITY",
    "InvalidRunIdError",
    "MAX_LIST_LIMIT",
    "READINESS_FILENAME",
    "ResearchFacadeConfigurationError",
    "ResearchFacadeError",
    "ResearchReadinessFacade",
    "UnsafeResearchPathError",
]
