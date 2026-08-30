"""Downstream integrity review for preregistered research trial evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import hmac
import json
from pathlib import Path
import re
from typing import Any, Literal

from quantify.research.trial_registry import (
    GENESIS_HASH,
    PreregistrationEvent,
    RegistryEvent,
    ResultEvent,
    TrialRegistryError,
    verify_registry,
)

ARTIFACT_TYPE = "trial_registry_review"
TRIAL_REGISTRY_REVIEW_SCHEMA_VERSION = 1
ReviewStatus = Literal["PASS", "BLOCK"]

REQUIRED_EVIDENCE_FILES = (
    "run_manifest.json",
    "robustness_report.json",
    "walk_forward_report.json",
    "candidate_walk_forward_report.json",
    "candidate_selection.json",
    "selection_evidence_manifest.json",
)
OPTIONAL_EVIDENCE_FILES = (
    "multiple_testing_report.json",
    "benchmark_report.json",
)
DATA_VERSION_FINGERPRINT_KEYS = (
    "cache_logical_bar_fingerprint",
    "prospective_prefix_logical_bar_fingerprint",
    "csv_dataset_fingerprint",
    "raw_vendor_bars_sha256",
)

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class TrialRegistryEvidenceBinding:
    filename: str
    path: str
    required: bool
    exists: bool
    readable_json_object: bool
    expected_sha256: str
    actual_sha256: str
    matches: bool
    status: ReviewStatus
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "path": self.path,
            "required": self.required,
            "exists": self.exists,
            "readable_json_object": self.readable_json_object,
            "expected_sha256": self.expected_sha256,
            "actual_sha256": self.actual_sha256,
            "matches": self.matches,
            "status": self.status,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class TrialRegistryReview:
    artifact_type: str
    schema_version: int
    status: ReviewStatus
    registry_path: str
    report_dir: str
    selected_candidate: str
    registry_sha256: str
    registry_tail_hash: str
    verified_event_count: int
    matched_trial_id: str
    matched_result_id: str
    preregistration_sequence: int | None
    result_sequence: int | None
    bound_evidence: list[TrialRegistryEvidenceBinding]
    blockers: list[str]
    can_upgrade_deterministic_gate: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "schema_version": self.schema_version,
            "status": self.status,
            "registry_path": self.registry_path,
            "report_dir": self.report_dir,
            "selected_candidate": self.selected_candidate,
            "registry_sha256": self.registry_sha256,
            "registry_tail_hash": self.registry_tail_hash,
            "verified_event_count": self.verified_event_count,
            "matched_trial_id": self.matched_trial_id,
            "matched_result_id": self.matched_result_id,
            "preregistration_sequence": self.preregistration_sequence,
            "result_sequence": self.result_sequence,
            "bound_evidence": [item.to_dict() for item in self.bound_evidence],
            "blockers": self.blockers,
            "can_upgrade_deterministic_gate": self.can_upgrade_deterministic_gate,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Trial Registry Review: {self.status}",
            "",
            f"- Artifact type: `{self.artifact_type}`",
            f"- Schema version: `{self.schema_version}`",
            f"- Registry: `{self.registry_path}`",
            f"- Report directory: `{self.report_dir}`",
            f"- Selected candidate: `{self.selected_candidate or 'missing'}`",
            f"- Registry SHA-256: `{self.registry_sha256 or 'unavailable'}`",
            f"- Registry tail hash: `{self.registry_tail_hash or 'unverified'}`",
            f"- Verified events: `{self.verified_event_count}`",
            f"- Matched trial: `{self.matched_trial_id or 'none'}`",
            f"- Matched result: `{self.matched_result_id or 'none'}`",
            f"- Can upgrade deterministic gate: `{self.can_upgrade_deterministic_gate}`",
            "",
            "This review binds research evidence only and never upgrades a deterministic gate.",
            "",
            "## Evidence Bindings",
            "",
            "| file | required | status | expected SHA-256 | actual SHA-256 | message |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for item in self.bound_evidence:
            lines.append(
                f"| `{item.filename}` | `{item.required}` | `{item.status}` | "
                f"`{item.expected_sha256 or 'missing'}` | "
                f"`{item.actual_sha256 or 'missing'}` | {_markdown_cell(item.message)} |"
            )
        lines.extend(["", "## Blockers"])
        if self.blockers:
            lines.extend(f"- {item}" for item in self.blockers)
        else:
            lines.append("- None.")
        lines.extend(
            [
                "",
                "A BLOCK report must be resolved by producing new valid evidence or a new "
                "preregistered trial. Historical registry events must not be edited or backfilled.",
            ]
        )
        return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class _ArtifactState:
    filename: str
    path: Path
    required: bool
    exists: bool
    payload: dict[str, Any] | None
    sha256: str
    error: str


@dataclass(frozen=True, slots=True)
class _PairEvaluation:
    preregistration: PreregistrationEvent
    result: ResultEvent
    blockers: list[str]
    bindings: list[TrialRegistryEvidenceBinding]


def build_trial_registry_review(
    registry_path: str | Path,
    report_dir: str | Path,
    selected_candidate: str | None = None,
    trial_id: str | None = None,
) -> TrialRegistryReview:
    """Verify a trial/result pair against the current immutable report artifacts."""
    registry = Path(registry_path)
    root = Path(report_dir)
    blockers: list[str] = []

    registry_sha256, registry_hash_error = _file_sha256(registry)
    if registry_hash_error:
        _add_blocker(blockers, f"registry: {registry_hash_error}")

    events: list[RegistryEvent] = []
    registry_tail_hash = ""
    if not registry_hash_error:
        try:
            events = verify_registry(registry)
            registry_tail_hash = events[-1].event_hash if events else GENESIS_HASH
        except (OSError, TrialRegistryError) as exc:
            _add_blocker(
                blockers,
                f"registry hash-chain verification failed: {type(exc).__name__}: {exc}",
            )

    states = _artifact_states(root)
    for state in states:
        if state.error:
            _add_blocker(blockers, f"{state.filename}: {state.error}")

    state_by_name = {state.filename: state for state in states}
    run_manifest = _payload(state_by_name, "run_manifest.json")
    selection = _payload(state_by_name, "candidate_selection.json")

    requested_candidate = str(selected_candidate or "").strip()
    requested_trial_id = str(trial_id or "").strip()
    recorded_candidate = _nonempty_text(selection.get("selected_candidate"))
    requested_preregistration = next(
        (
            event
            for event in events
            if isinstance(event, PreregistrationEvent) and event.trial_id == requested_trial_id
        ),
        None,
    )
    if requested_trial_id:
        if requested_preregistration is None:
            candidate = requested_candidate
            _add_blocker(blockers, f"requested trial_id {requested_trial_id!r} is not registered")
        else:
            candidate = requested_candidate or requested_preregistration.candidate
            if candidate != requested_preregistration.candidate:
                _add_blocker(
                    blockers,
                    "requested trial_id candidate does not match selected_candidate",
                )
    else:
        candidate = requested_candidate or recorded_candidate
        if not candidate:
            _add_blocker(
                blockers,
                "selected candidate is missing from both the argument and candidate_selection.json",
            )
        if requested_candidate and recorded_candidate != requested_candidate:
            _add_blocker(
                blockers,
                "candidate_selection.json selected_candidate does not match the requested candidate",
            )

    evaluations = _pair_evaluations(
        events,
        candidate=candidate,
        trial_id=requested_trial_id,
        run_manifest=run_manifest,
        states=states,
    )
    selected_evaluation = evaluations[0] if evaluations else None

    candidate_preregistrations = [
        event
        for event in events
        if isinstance(event, PreregistrationEvent) and event.candidate == candidate
    ]
    if not requested_trial_id and len(candidate_preregistrations) > 1:
        _add_blocker(
            blockers,
            "multiple preregistered trials exist for the candidate; review must specify trial_id",
        )
    reviewed_trial_ids = (
        [requested_trial_id]
        if requested_trial_id
        else [event.trial_id for event in candidate_preregistrations]
    )
    for reviewed_trial_id in reviewed_trial_ids:
        result_count = sum(
            isinstance(event, ResultEvent) and event.trial_id == reviewed_trial_id
            for event in events
        )
        if result_count > 1:
            _add_blocker(
                blockers,
                f"trial {reviewed_trial_id!r} has multiple result events; "
                "cherry-pick-safe review requires one terminal result",
            )

    if candidate and not any(
        isinstance(event, PreregistrationEvent) and event.candidate == candidate for event in events
    ):
        _add_blocker(
            blockers,
            f"selected candidate {candidate!r} has no preregistration",
        )
    elif candidate and not evaluations:
        _add_blocker(
            blockers,
            f"selected candidate {candidate!r} has no subsequent result event",
        )

    if selected_evaluation is not None:
        for blocker in selected_evaluation.blockers:
            _add_blocker(blockers, blocker)
        bindings = selected_evaluation.bindings
        matched_trial_id = selected_evaluation.preregistration.trial_id
        matched_result_id = selected_evaluation.result.result_id
        preregistration_sequence: int | None = selected_evaluation.preregistration.sequence
        result_sequence: int | None = selected_evaluation.result.sequence
    else:
        bindings = _evidence_bindings(states, {})
        matched_trial_id = ""
        matched_result_id = ""
        preregistration_sequence = None
        result_sequence = None

    for binding in bindings:
        if binding.status == "BLOCK":
            _add_blocker(blockers, f"{binding.filename}: {binding.message}")

    return TrialRegistryReview(
        artifact_type=ARTIFACT_TYPE,
        schema_version=TRIAL_REGISTRY_REVIEW_SCHEMA_VERSION,
        status="BLOCK" if blockers else "PASS",
        registry_path=str(registry),
        report_dir=str(root),
        selected_candidate=candidate,
        registry_sha256=registry_sha256,
        registry_tail_hash=registry_tail_hash,
        verified_event_count=len(events),
        matched_trial_id=matched_trial_id,
        matched_result_id=matched_result_id,
        preregistration_sequence=preregistration_sequence,
        result_sequence=result_sequence,
        bound_evidence=bindings,
        blockers=blockers,
        can_upgrade_deterministic_gate=False,
    )


def write_trial_registry_review(
    review: TrialRegistryReview,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "trial_registry_review.json").write_text(
        json.dumps(review.to_dict(), ensure_ascii=False, allow_nan=False, indent=2),
        encoding="utf-8",
    )
    (root / "trial_registry_review.md").write_text(
        review.to_markdown(),
        encoding="utf-8",
    )
    return root


def _pair_evaluations(
    events: list[RegistryEvent],
    *,
    candidate: str,
    trial_id: str = "",
    run_manifest: dict[str, Any],
    states: list[_ArtifactState],
) -> list[_PairEvaluation]:
    if not candidate:
        return []
    preregistrations = [
        event
        for event in events
        if isinstance(event, PreregistrationEvent) and event.candidate == candidate
        and (not trial_id or event.trial_id == trial_id)
    ]
    pairs = [
        (preregistration, result)
        for preregistration in preregistrations
        for result in events
        if isinstance(result, ResultEvent)
        and result.trial_id == preregistration.trial_id
        and result.sequence > preregistration.sequence
    ]
    pairs.sort(key=lambda pair: pair[1].sequence)
    return [
        _evaluate_pair(
            preregistration,
            result,
            candidate=candidate,
            run_manifest=run_manifest,
            states=states,
        )
        for preregistration, result in pairs
    ]


def _evaluate_pair(
    preregistration: PreregistrationEvent,
    result: ResultEvent,
    *,
    candidate: str,
    run_manifest: dict[str, Any],
    states: list[_ArtifactState],
) -> _PairEvaluation:
    blockers: list[str] = []
    _validate_manifest_fingerprints(preregistration, run_manifest, blockers)
    _validate_boundaries(preregistration, run_manifest, blockers)
    _validate_event_timing(preregistration, result, run_manifest, blockers)

    result_payload = result.result
    if not isinstance(result_payload, dict) or not result_payload:
        _add_blocker(blockers, "result.result must be a non-empty structured object")
        artifact_fingerprints: dict[str, Any] = {}
    else:
        if result_payload.get("candidate") != candidate:
            _add_blocker(
                blockers,
                "result.result candidate does not match the selected candidate",
            )
        raw_fingerprints = result_payload.get("artifact_fingerprints")
        if not isinstance(raw_fingerprints, dict):
            _add_blocker(blockers, "result.result artifact_fingerprints must be an object")
            artifact_fingerprints = {}
        else:
            artifact_fingerprints = raw_fingerprints

    bindings = _evidence_bindings(states, artifact_fingerprints)
    for binding in bindings:
        if binding.status == "BLOCK":
            _add_blocker(blockers, f"{binding.filename}: {binding.message}")
    return _PairEvaluation(preregistration, result, blockers, bindings)


def _validate_manifest_fingerprints(
    preregistration: PreregistrationEvent,
    manifest: dict[str, Any],
    blockers: list[str],
) -> None:
    config_sha256 = _nonempty_text(manifest.get("config_sha256"))
    if not config_sha256:
        _add_blocker(blockers, "run_manifest.json config_sha256 is missing")
    elif preregistration.config_fingerprint != config_sha256:
        _add_blocker(
            blockers,
            "preregistration config_fingerprint does not match run_manifest.json config_sha256",
        )

    accepted_data_fingerprints: set[str] = set()
    cache_sha256 = _nonempty_text(manifest.get("cache_sha256"))
    if cache_sha256:
        accepted_data_fingerprints.add(cache_sha256)
    data_version = manifest.get("data_version")
    if isinstance(data_version, dict):
        for key in DATA_VERSION_FINGERPRINT_KEYS:
            value = _nonempty_text(data_version.get(key))
            if value:
                accepted_data_fingerprints.add(value)
    if not accepted_data_fingerprints:
        _add_blocker(
            blockers,
            "run_manifest.json records no accepted cache/logical/csv/raw data fingerprint",
        )
    elif preregistration.data_fingerprint not in accepted_data_fingerprints:
        _add_blocker(
            blockers,
            "preregistration data_fingerprint does not match any accepted run manifest fingerprint",
        )

    prefix_fingerprint = ""
    prefix_end = ""
    prefix_algorithm = ""
    if isinstance(data_version, dict):
        prefix_fingerprint = _nonempty_text(
            data_version.get("prospective_prefix_logical_bar_fingerprint")
        )
        prefix_end = _nonempty_text(
            data_version.get("prospective_prefix_logical_bar_fingerprint_end")
        )
        prefix_algorithm = _nonempty_text(
            data_version.get("prospective_prefix_logical_bar_fingerprint_algorithm")
        )
    if prefix_fingerprint and preregistration.data_fingerprint == prefix_fingerprint:
        selection = _boundary(preregistration.selection_boundary)
        if prefix_algorithm != "sha256:quantify.logical-bars.v1":
            _add_blocker(blockers, "prospective prefix fingerprint algorithm is invalid")
        if selection is None or prefix_end != selection[1]:
            _add_blocker(
                blockers,
                "prospective prefix fingerprint cutoff does not match selection boundary end",
            )

    research_parameters = manifest.get("research_parameters")
    if isinstance(research_parameters, dict):
        parameter_fingerprint = _nonempty_text(
            research_parameters.get("prospective_parameter_fingerprint")
        )
        if parameter_fingerprint and parameter_fingerprint != preregistration.parameter_fingerprint:
            _add_blocker(
                blockers,
                "preregistration parameter_fingerprint does not match run manifest prospective parameters",
            )


def _validate_boundaries(
    preregistration: PreregistrationEvent,
    manifest: dict[str, Any],
    blockers: list[str],
) -> None:
    manifest_values: dict[str, str] = {}
    for key in ("start", "end", "in_sample_end", "out_sample_start"):
        value = _nonempty_text(manifest.get(key))
        if not value or _parse_date(value) is None:
            _add_blocker(blockers, f"run_manifest.json {key} must be an ISO date")
        else:
            manifest_values[key] = value
    if len(manifest_values) != 4:
        return

    manifest_order = [
        _parse_date(manifest_values[key])
        for key in (
            "start",
            "in_sample_end",
            "out_sample_start",
            "end",
        )
    ]
    if not (manifest_order[0] <= manifest_order[1] < manifest_order[2] <= manifest_order[3]):
        _add_blocker(blockers, "run_manifest.json sample range and split are not ordered")
        return

    boundaries: dict[str, tuple[str, str]] = {}
    for name, raw in (
        ("train", preregistration.train_boundary),
        ("selection", preregistration.selection_boundary),
        ("test", preregistration.test_boundary),
    ):
        parsed = _boundary(raw)
        if parsed is None:
            _add_blocker(
                blockers,
                f"preregistration {name}_boundary must contain ISO-date start and end",
            )
        else:
            boundaries[name] = parsed
    if len(boundaries) != 3:
        return

    train = boundaries["train"]
    selection = boundaries["selection"]
    test = boundaries["test"]
    ordered_dates = [
        _parse_date(train[0]),
        _parse_date(train[1]),
        _parse_date(selection[0]),
        _parse_date(selection[1]),
        _parse_date(test[0]),
        _parse_date(test[1]),
    ]
    if not (
        ordered_dates[0]
        <= ordered_dates[1]
        < ordered_dates[2]
        <= ordered_dates[3]
        < ordered_dates[4]
        <= ordered_dates[5]
    ):
        _add_blocker(blockers, "preregistration train/selection/test boundaries are not ordered")

    expected = {
        "train.start": manifest_values["start"],
        "selection.end": manifest_values["in_sample_end"],
        "test.start": manifest_values["out_sample_start"],
        "test.end": manifest_values["end"],
    }
    actual = {
        "train.start": train[0],
        "selection.end": selection[1],
        "test.start": test[0],
        "test.end": test[1],
    }
    for key, expected_value in expected.items():
        if actual[key] != expected_value:
            _add_blocker(
                blockers,
                f"preregistration {key} does not match run_manifest.json ({expected_value})",
            )


def _validate_event_timing(
    preregistration: PreregistrationEvent,
    result: ResultEvent,
    manifest: dict[str, Any],
    blockers: list[str],
) -> None:
    if preregistration.sequence >= result.sequence:
        _add_blocker(blockers, "result does not follow its preregistration in the registry")
    manifest_time = _parse_datetime(manifest.get("created_at_utc"))
    preregistration_time = _parse_datetime(preregistration.created_at)
    result_time = _parse_datetime(result.created_at)
    if manifest_time is None:
        _add_blocker(blockers, "run_manifest.json created_at_utc must be timezone-aware ISO-8601")
        return
    if preregistration_time is None or preregistration_time > manifest_time:
        _add_blocker(
            blockers,
            "preregistration was not recorded before the run manifest; post-hoc backfill is blocked",
        )
    if result_time is None or result_time < manifest_time:
        _add_blocker(
            blockers,
            "result created_at precedes the run manifest and cannot bind this run",
        )


def _artifact_states(root: Path) -> list[_ArtifactState]:
    specs = [(filename, True) for filename in REQUIRED_EVIDENCE_FILES]
    specs.extend(
        (filename, False) for filename in OPTIONAL_EVIDENCE_FILES if (root / filename).exists()
    )
    return [_read_artifact(root / filename, required=required) for filename, required in specs]


def _read_artifact(path: Path, *, required: bool) -> _ArtifactState:
    if not path.exists():
        return _ArtifactState(path.name, path, required, False, None, "", "file is missing")
    if not path.is_file():
        return _ArtifactState(
            path.name,
            path,
            required,
            True,
            None,
            "",
            "path is not a regular file",
        )
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return _ArtifactState(
            path.name,
            path,
            required,
            True,
            None,
            "",
            f"cannot be read: {exc}",
        )
    digest = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
        payload = json.loads(
            text,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return _ArtifactState(
            path.name,
            path,
            required,
            True,
            None,
            digest,
            f"file is not valid strict JSON: {exc}",
        )
    if not isinstance(payload, dict) or not payload:
        return _ArtifactState(
            path.name,
            path,
            required,
            True,
            None,
            digest,
            "file must contain a non-empty JSON object",
        )
    return _ArtifactState(path.name, path, required, True, payload, digest, "")


def _evidence_bindings(
    states: list[_ArtifactState],
    artifact_fingerprints: dict[str, Any],
) -> list[TrialRegistryEvidenceBinding]:
    bindings: list[TrialRegistryEvidenceBinding] = []
    for state in states:
        raw_expected = artifact_fingerprints.get(state.filename)
        expected = raw_expected if isinstance(raw_expected, str) else ""
        if state.error:
            message = state.error
        elif not expected:
            message = "result artifact_fingerprints does not bind this file"
        elif _SHA256_PATTERN.fullmatch(expected) is None:
            message = "recorded artifact fingerprint is not a lowercase SHA-256 digest"
        elif not hmac.compare_digest(expected, state.sha256):
            message = "recorded artifact fingerprint does not match current file SHA-256"
        else:
            message = "Current file is bound by the matched result event."
        matches = not state.error and bool(expected) and hmac.compare_digest(expected, state.sha256)
        status: ReviewStatus = "PASS" if matches else "BLOCK"
        bindings.append(
            TrialRegistryEvidenceBinding(
                filename=state.filename,
                path=str(state.path),
                required=state.required,
                exists=state.exists,
                readable_json_object=state.payload is not None,
                expected_sha256=expected,
                actual_sha256=state.sha256,
                matches=matches,
                status=status,
                message=message,
            )
        )
    return bindings


def _payload(states: dict[str, _ArtifactState], filename: str) -> dict[str, Any]:
    state = states.get(filename)
    return state.payload if state is not None and state.payload is not None else {}


def _boundary(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, dict):
        return None
    start = _nonempty_text(value.get("start"))
    end = _nonempty_text(value.get("end"))
    if not start or not end or _parse_date(start) is None or _parse_date(end) is None:
        return None
    return start, end


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _nonempty_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _file_sha256(path: Path) -> tuple[str, str]:
    if not path.exists():
        return "", "file is missing"
    if not path.is_file():
        return "", "path is not a regular file"
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        return "", f"cannot be read: {exc}"
    return digest.hexdigest(), ""


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate JSON key {key!r}")
        payload[key] = value
    return payload


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value!r}")


def _add_blocker(blockers: list[str], message: str) -> None:
    if message not in blockers:
        blockers.append(message)


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
