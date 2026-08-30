"""Operate the append-only research trial registry with strict JSON inputs."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys
from typing import Any, TextIO

from quantify.research.trial_registry import (
    GENESIS_HASH,
    HASH_ALGORITHM,
    TRIAL_REGISTRY_SCHEMA_VERSION,
    PreregistrationEvent,
    ResultEvent,
    TrialRegistryError,
    UnknownTrialError,
    append_preregistration,
    append_result,
    verify_registry,
)

_PREREGISTRATION_FIELDS = frozenset(
    {
        "trial_id",
        "candidate",
        "hypothesis",
        "parameter_fingerprint",
        "data_fingerprint",
        "config_fingerprint",
        "train_boundary",
        "selection_boundary",
        "test_boundary",
        "created_at",
        "prohibited_live_use",
    }
)
_RESULT_REQUIRED_FIELDS = frozenset({"trial_id", "result", "created_at"})
_RESULT_OPTIONAL_FIELDS = frozenset({"result_id"})


class PayloadError(ValueError):
    """Raised when a command payload is not a strict JSON object."""


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "preregister":
            output = _preregister(args.registry, args.payload)
        elif args.command == "record-result":
            output = _record_result(args.registry, args.payload)
        else:
            output = _verify(args.registry)
    except (OSError, PayloadError, TrialRegistryError) as exc:
        failure = {
            "status": "FAIL",
            "command": args.command,
            "registry_path": str(args.registry),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        if args.command == "verify":
            failure["valid"] = False
        _write_json(failure, sys.stdout if args.command == "verify" else sys.stderr)
        return 1

    _write_json(output, sys.stdout)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Append or verify research-only trial registry events."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    preregister = subparsers.add_parser(
        "preregister", help="Append one immutable trial preregistration."
    )
    _add_registry_argument(preregister)
    preregister.add_argument(
        "--payload",
        required=True,
        type=Path,
        help="UTF-8 JSON object containing the complete preregistration payload.",
    )

    record_result = subparsers.add_parser(
        "record-result", help="Append a result to an already preregistered trial."
    )
    _add_registry_argument(record_result)
    record_result.add_argument(
        "--payload",
        required=True,
        type=Path,
        help="UTF-8 JSON object containing the complete result payload.",
    )

    verify = subparsers.add_parser(
        "verify", help="Verify canonical JSONL, event order, and the complete hash chain."
    )
    _add_registry_argument(verify)
    return parser


def _add_registry_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--registry", required=True, type=Path, help="Canonical JSONL path")


def _preregister(registry: Path, payload_path: Path) -> dict[str, Any]:
    payload = _load_json_object(payload_path)
    _require_exact_fields(payload, _PREREGISTRATION_FIELDS)
    if payload["prohibited_live_use"] is not True:
        raise PayloadError("preregister requires explicit prohibited_live_use=true")

    event = append_preregistration(
        registry,
        trial_id=payload["trial_id"],
        candidate=payload["candidate"],
        hypothesis=payload["hypothesis"],
        parameter_fingerprint=payload["parameter_fingerprint"],
        data_fingerprint=payload["data_fingerprint"],
        config_fingerprint=payload["config_fingerprint"],
        train_boundary=payload["train_boundary"],
        selection_boundary=payload["selection_boundary"],
        test_boundary=payload["test_boundary"],
        created_at=payload["created_at"],
        prohibited_live_use=True,
    )
    return _append_summary("preregister", registry, event)


def _record_result(registry: Path, payload_path: Path) -> dict[str, Any]:
    payload = _load_json_object(payload_path)
    _require_exact_fields(
        payload,
        _RESULT_REQUIRED_FIELDS,
        optional=_RESULT_OPTIONAL_FIELDS,
    )
    if not registry.is_file():
        raise UnknownTrialError(f"registry does not contain a preregistered trial: {registry}")

    events = verify_registry(registry)
    trial_id = payload["trial_id"]
    if not any(
        isinstance(event, PreregistrationEvent) and event.trial_id == trial_id for event in events
    ):
        raise UnknownTrialError(f"result references unknown trial_id: {trial_id}")

    event = append_result(
        registry,
        trial_id=trial_id,
        result=payload["result"],
        created_at=payload["created_at"],
        result_id=payload.get("result_id"),
    )
    return _append_summary("record-result", registry, event)


def _verify(registry: Path) -> dict[str, Any]:
    if not registry.is_file():
        raise FileNotFoundError(f"registry does not exist: {registry}")
    events = verify_registry(registry)
    preregistrations = [event for event in events if isinstance(event, PreregistrationEvent)]
    results = [event for event in events if isinstance(event, ResultEvent)]
    return {
        "status": "PASS",
        "valid": True,
        "command": "verify",
        "registry_path": str(registry),
        "schema_version": TRIAL_REGISTRY_SCHEMA_VERSION,
        "hash_algorithm": HASH_ALGORITHM,
        "event_count": len(events),
        "preregistration_count": len(preregistrations),
        "result_count": len(results),
        "trial_count": len(preregistrations),
        "trial_ids": sorted(event.trial_id for event in preregistrations),
        "last_event_hash": events[-1].event_hash if events else GENESIS_HASH,
    }


def _append_summary(
    command: str,
    registry: Path,
    event: PreregistrationEvent | ResultEvent,
) -> dict[str, Any]:
    return {
        "status": "APPENDED",
        "command": command,
        "registry_path": str(registry),
        "event": event.to_dict(),
    }


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise PayloadError(f"payload is not valid UTF-8: {path}") from exc
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except json.JSONDecodeError as exc:
        raise PayloadError(f"payload is malformed JSON: {path}: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise PayloadError(f"payload must be a JSON object: {path}")
    return payload


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise PayloadError(f"payload contains duplicate JSON key: {key}")
        payload[key] = value
    return payload


def _reject_json_constant(value: str) -> None:
    raise PayloadError(f"payload contains prohibited non-finite number: {value}")


def _require_exact_fields(
    payload: dict[str, Any],
    required: frozenset[str],
    *,
    optional: frozenset[str] = frozenset(),
) -> None:
    fields = set(payload)
    missing = sorted(required - fields)
    unexpected = sorted(fields - required - optional)
    if missing or unexpected:
        raise PayloadError(
            f"payload fields differ from command schema; missing={missing}, unexpected={unexpected}"
        )


def _write_json(payload: dict[str, Any], stream: TextIO) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        file=stream,
    )


if __name__ == "__main__":
    raise SystemExit(main())
