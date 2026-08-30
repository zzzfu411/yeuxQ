"""Fail-closed validators for externally generated research evidence."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any, Literal

from quantify.research.trial_registry import TrialRegistryError, verify_registry

EvidenceStatus = Literal["PASS", "WATCH", "BLOCK"]
_VALID_STATUSES = {"PASS", "WATCH", "BLOCK"}


@dataclass(frozen=True, slots=True)
class EvidenceContractValidation:
    valid: bool
    status: EvidenceStatus
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "status": self.status,
            "reasons": list(self.reasons),
        }


def validate_multiple_testing_payload(
    payload: dict[str, Any],
    *,
    expected_candidate: str = "",
    verify_input_file: bool = True,
) -> EvidenceContractValidation:
    """Validate a complete multiple-testing report without trusting bare status."""
    reasons: list[str] = []
    if payload.get("artifact_type") != "multiple_testing_report":
        reasons.append("artifact_type must be multiple_testing_report.")
    if payload.get("schema_version") != 1:
        reasons.append("schema_version must be 1.")
    if payload.get("evidence_role") != "diagnostic_only":
        reasons.append("evidence_role must be diagnostic_only.")
    if payload.get("can_upgrade_deterministic_gate") is not False:
        reasons.append("can_upgrade_deterministic_gate must be exactly false.")

    status = _status(payload.get("status"), reasons, "status")
    sufficient = payload.get("sufficient")
    if not isinstance(sufficient, bool):
        reasons.append("sufficient must be a boolean.")
    if sufficient is False and status != "BLOCK":
        reasons.append("statistically insufficient evidence must be BLOCK.")

    input_payload = payload.get("input")
    if not isinstance(input_payload, dict):
        reasons.append("input must be an object.")
        input_payload = {}
    input_path = str(input_payload.get("csv_path") or "").strip()
    input_sha256 = str(input_payload.get("sha256") or "").strip()
    if not input_path:
        reasons.append("input.csv_path is required.")
    if not _is_sha256(input_sha256):
        reasons.append("input.sha256 must be a lowercase SHA-256 digest.")
    candidates = input_payload.get("candidate_columns")
    if not isinstance(candidates, list) or len(candidates) < 2:
        reasons.append("input.candidate_columns must contain at least two trials.")
        candidate_names: list[str] = []
    else:
        candidate_names = [str(item) for item in candidates]
        if any(not name for name in candidate_names) or len(candidate_names) != len(
            set(candidate_names)
        ):
            reasons.append("input.candidate_columns must contain unique non-empty names.")
    observations = input_payload.get("observations")
    if isinstance(observations, bool) or not isinstance(observations, int) or observations <= 0:
        reasons.append("input.observations must be a positive integer.")

    parameters = payload.get("parameters")
    if not isinstance(parameters, dict):
        reasons.append("parameters must be an object.")
        parameters = {}
    selected = str(parameters.get("selected_candidate") or "").strip()
    if not selected or selected not in candidate_names:
        reasons.append("parameters.selected_candidate must identify a frozen trial column.")
    if expected_candidate and selected != expected_candidate:
        reasons.append(
            "parameters.selected_candidate does not match the deterministic selected candidate."
        )
    effective_trials = _finite_number(parameters.get("effective_trials"))
    if effective_trials is None or effective_trials < len(candidate_names):
        reasons.append("parameters.effective_trials cannot be below the frozen trial count.")

    diagnostics = payload.get("diagnostics")
    if not isinstance(diagnostics, dict):
        reasons.append("diagnostics must be an object.")
        diagnostics = {}
    diagnostic_statuses: list[EvidenceStatus] = []
    for key in ("deflated_sharpe_ratio", "cscv_pbo"):
        item = diagnostics.get(key)
        if not isinstance(item, dict):
            reasons.append(f"diagnostics.{key} must be an object.")
            continue
        item_status = _status(item.get("status"), reasons, f"diagnostics.{key}.status")
        diagnostic_statuses.append(item_status)
        if item.get("sufficient") is not True and sufficient is True:
            reasons.append(f"diagnostics.{key}.sufficient must be true when report is sufficient.")
    if diagnostic_statuses and status != _worst_status(diagnostic_statuses):
        reasons.append("status must equal the worst DSR and CSCV/PBO status.")

    insufficiency_reasons = payload.get("insufficiency_reasons")
    if not isinstance(insufficiency_reasons, list):
        reasons.append("insufficiency_reasons must be a list.")
    elif sufficient is False and not insufficiency_reasons:
        reasons.append("insufficient evidence must explain its insufficiency_reasons.")

    if verify_input_file and input_path and _is_sha256(input_sha256):
        path = Path(input_path)
        if not path.is_file():
            reasons.append("The frozen multiple-testing input CSV no longer exists.")
        elif _file_sha256(path) != input_sha256:
            reasons.append("The frozen multiple-testing input CSV SHA-256 no longer matches.")

    return EvidenceContractValidation(valid=not reasons, status=status, reasons=reasons)


def validate_benchmark_payload(
    payload: dict[str, Any],
    *,
    expected_symbol: str = "",
    verify_input_files: bool = True,
) -> EvidenceContractValidation:
    """Validate formal total-return benchmark evidence and retained inputs."""
    reasons: list[str] = []
    if payload.get("artifact_type") != "benchmark_report":
        reasons.append("artifact_type must be benchmark_report.")
    if payload.get("schema_version") != 1:
        reasons.append("schema_version must be 1.")
    if payload.get("evidence_role") != "benchmark_evidence_only":
        reasons.append("evidence_role must be benchmark_evidence_only.")
    if payload.get("can_upgrade_deterministic_gate") is not False:
        reasons.append("can_upgrade_deterministic_gate must be exactly false.")
    status = _status(payload.get("status"), reasons, "status")
    sufficient = payload.get("sufficient")
    if not isinstance(sufficient, bool):
        reasons.append("sufficient must be a boolean.")
    if sufficient is False and status != "BLOCK":
        reasons.append("insufficient benchmark evidence must be BLOCK.")

    metadata = payload.get("benchmark_metadata")
    if not isinstance(metadata, dict):
        reasons.append("benchmark_metadata must be an object.")
        metadata = {}
    if metadata.get("artifact_type") != "reviewed_benchmark_series":
        reasons.append("benchmark metadata artifact_type must be reviewed_benchmark_series.")
    if metadata.get("schema_version") != 1:
        reasons.append("benchmark metadata schema_version must be 1.")
    if metadata.get("total_return") is not True:
        reasons.append("benchmark metadata total_return must be exactly true.")
    for field in ("symbol", "name", "source_vendor", "source_exported_at", "reviewed_by", "reviewed_at"):
        if not isinstance(metadata.get(field), str) or not str(metadata.get(field)).strip():
            reasons.append(f"benchmark metadata {field} must be a non-empty string.")
    metadata_file_sha = str(metadata.get("file_sha256") or "").lower()
    if not _is_sha256(metadata_file_sha):
        reasons.append("benchmark metadata file_sha256 must be a SHA-256 digest.")

    identity = payload.get("identity")
    if not isinstance(identity, dict):
        reasons.append("identity must be an object.")
        identity = {}
    if identity.get("total_return") is not True:
        reasons.append("identity.total_return must be exactly true.")
    if identity.get("symbol") != metadata.get("symbol") or identity.get("name") != metadata.get(
        "name"
    ):
        reasons.append("identity must match the reviewed benchmark metadata.")
    if expected_symbol and _symbol_root(identity.get("symbol")) != _symbol_root(expected_symbol):
        reasons.append("benchmark symbol does not match the run manifest index_code.")

    inputs = payload.get("inputs")
    if not isinstance(inputs, dict):
        reasons.append("inputs must be an object.")
        inputs = {}
    input_rows = {
        "strategy_equity_csv": inputs.get("strategy_equity_csv"),
        "benchmark_csv": inputs.get("benchmark_csv"),
        "benchmark_metadata_json": inputs.get("benchmark_metadata_json"),
    }
    for name, raw in input_rows.items():
        if not isinstance(raw, dict):
            reasons.append(f"inputs.{name} must be an object.")
            continue
        path_label = str(raw.get("path") or "").strip()
        sha256 = str(raw.get("sha256") or "").lower()
        if not path_label:
            reasons.append(f"inputs.{name}.path is required.")
        if not _is_sha256(sha256):
            reasons.append(f"inputs.{name}.sha256 must be a SHA-256 digest.")
        if verify_input_files and path_label and _is_sha256(sha256):
            path = Path(path_label)
            if not path.is_file():
                reasons.append(f"The retained {name} input no longer exists.")
            elif _file_sha256(path) != sha256:
                reasons.append(f"The retained {name} input SHA-256 no longer matches.")
    benchmark_input = input_rows.get("benchmark_csv")
    if isinstance(benchmark_input, dict):
        if benchmark_input.get("sha256_matches_metadata") is not True:
            reasons.append("benchmark CSV SHA-256 must match reviewed metadata.")
        if str(benchmark_input.get("sha256") or "").lower() != metadata_file_sha:
            reasons.append("benchmark CSV digest must equal benchmark metadata file_sha256.")

    if sufficient is True:
        alignment = payload.get("alignment")
        if not isinstance(alignment, dict) or not isinstance(
            alignment.get("aligned_observations"), int
        ):
            reasons.append("sufficient benchmark evidence requires alignment observations.")
        metrics = payload.get("metrics")
        if not isinstance(metrics, dict) or metrics.get("excess_cagr") is None:
            reasons.append("sufficient benchmark evidence requires computed metrics.")
        intervals = payload.get("confidence_intervals")
        if not isinstance(intervals, dict):
            reasons.append("confidence_intervals must be an object.")
        else:
            excess_interval = intervals.get("annualized_excess_return_95")
            if not isinstance(excess_interval, dict):
                reasons.append("annualized excess-return 95% interval is required.")
            elif status == "PASS":
                lower = _finite_number(excess_interval.get("lower"))
                if lower is None or lower <= 0.0:
                    reasons.append(
                        "PASS benchmark evidence requires a strictly positive CI lower bound."
                    )

    evidence = payload.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        reasons.append("evidence must contain structured benchmark findings.")
    else:
        evidence_statuses = [
            _status(item.get("status"), reasons, f"evidence[{index}].status")
            for index, item in enumerate(evidence)
            if isinstance(item, dict)
        ]
        if evidence_statuses and status != _worst_status(evidence_statuses):
            reasons.append("status must equal the worst benchmark evidence status.")
    return EvidenceContractValidation(valid=not reasons, status=status, reasons=reasons)


def validate_trial_registry_review_payload(
    payload: dict[str, Any],
    *,
    expected_candidate: str = "",
    report_dir: str | Path | None = None,
    verify_registry_file: bool = True,
) -> EvidenceContractValidation:
    """Validate the current trial-registry review and all bound artifact hashes."""
    reasons: list[str] = []
    if payload.get("artifact_type") != "trial_registry_review":
        reasons.append("artifact_type must be trial_registry_review.")
    if payload.get("schema_version") != 1:
        reasons.append("schema_version must be 1.")
    if payload.get("can_upgrade_deterministic_gate") is not False:
        reasons.append("can_upgrade_deterministic_gate must be exactly false.")
    status = _status(payload.get("status"), reasons, "status")
    if status == "WATCH":
        reasons.append("trial registry review status can only be PASS or BLOCK.")
    candidate = str(payload.get("selected_candidate") or "").strip()
    if not candidate:
        reasons.append("selected_candidate is required.")
    if expected_candidate and candidate != expected_candidate:
        reasons.append("trial review candidate does not match deterministic candidate selection.")
    registry_sha256 = str(payload.get("registry_sha256") or "").lower()
    tail_hash = str(payload.get("registry_tail_hash") or "").lower()
    if not _is_sha256(registry_sha256):
        reasons.append("registry_sha256 must be a SHA-256 digest.")
    if not _is_sha256(tail_hash):
        reasons.append("registry_tail_hash must be a SHA-256 digest.")
    event_count = payload.get("verified_event_count")
    if isinstance(event_count, bool) or not isinstance(event_count, int) or event_count < 2:
        reasons.append("verified_event_count must include preregistration and result events.")
    preregistration_sequence = payload.get("preregistration_sequence")
    result_sequence = payload.get("result_sequence")
    if (
        isinstance(preregistration_sequence, bool)
        or not isinstance(preregistration_sequence, int)
        or isinstance(result_sequence, bool)
        or not isinstance(result_sequence, int)
        or preregistration_sequence >= result_sequence
    ):
        reasons.append("result_sequence must follow preregistration_sequence.")
    if not str(payload.get("matched_trial_id") or "").strip():
        reasons.append("matched_trial_id is required.")
    if not str(payload.get("matched_result_id") or "").strip():
        reasons.append("matched_result_id is required.")

    root = Path(report_dir) if report_dir is not None else Path(str(payload.get("report_dir") or ""))
    required_names = {
        "run_manifest.json",
        "robustness_report.json",
        "walk_forward_report.json",
        "candidate_walk_forward_report.json",
        "candidate_selection.json",
        "selection_evidence_manifest.json",
    }
    for optional in ("multiple_testing_report.json", "benchmark_report.json"):
        if root and (root / optional).exists():
            required_names.add(optional)
    bindings = payload.get("bound_evidence")
    if not isinstance(bindings, list):
        reasons.append("bound_evidence must be a list.")
        bindings = []
    binding_names: set[str] = set()
    for index, binding in enumerate(bindings):
        if not isinstance(binding, dict):
            reasons.append(f"bound_evidence[{index}] must be an object.")
            continue
        filename = str(binding.get("filename") or "")
        binding_names.add(filename)
        expected_sha = str(binding.get("expected_sha256") or "").lower()
        actual_sha = str(binding.get("actual_sha256") or "").lower()
        if (
            binding.get("status") != "PASS"
            or binding.get("matches") is not True
            or not _is_sha256(expected_sha)
            or expected_sha != actual_sha
        ):
            reasons.append(f"bound_evidence[{index}] does not prove an exact PASS hash binding.")
        path = root / filename
        if not path.is_file():
            reasons.append(f"Bound evidence file is missing: {filename}.")
        elif _is_sha256(actual_sha) and _file_sha256(path) != actual_sha:
            reasons.append(f"Bound evidence file changed after review: {filename}.")
    missing_bindings = sorted(required_names - binding_names)
    if missing_bindings:
        reasons.append("bound_evidence is missing: " + ", ".join(missing_bindings) + ".")

    blockers = payload.get("blockers")
    if not isinstance(blockers, list):
        reasons.append("blockers must be a list.")
    elif status == "PASS" and blockers:
        reasons.append("PASS trial registry review cannot contain blockers.")
    elif status == "BLOCK" and not blockers:
        reasons.append("BLOCK trial registry review must explain its blockers.")

    registry_path = Path(str(payload.get("registry_path") or ""))
    if verify_registry_file:
        if not registry_path.is_file():
            reasons.append("The reviewed trial registry no longer exists.")
        elif _is_sha256(registry_sha256) and _file_sha256(registry_path) != registry_sha256:
            reasons.append("The reviewed trial registry SHA-256 no longer matches.")
        else:
            try:
                events = verify_registry(registry_path)
            except (OSError, TrialRegistryError) as exc:
                reasons.append(f"Trial registry verification failed: {exc}")
            else:
                current_tail = events[-1].event_hash if events else ""
                if current_tail != tail_hash or len(events) != event_count:
                    reasons.append("Trial registry event count or tail hash changed after review.")
    return EvidenceContractValidation(valid=not reasons, status=status, reasons=reasons)


def _status(value: Any, reasons: list[str], field: str) -> EvidenceStatus:
    if value not in _VALID_STATUSES:
        reasons.append(f"{field} must be PASS, WATCH, or BLOCK.")
        return "BLOCK"
    return value


def _worst_status(statuses: list[EvidenceStatus]) -> EvidenceStatus:
    severity = {"PASS": 0, "WATCH": 1, "BLOCK": 2}
    return max(statuses, key=severity.__getitem__)


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    result = float(value)
    if result != result or result in {float("inf"), float("-inf")}:
        return None
    return result


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _symbol_root(value: Any) -> str:
    return str(value or "").strip().upper().split(".", maxsplit=1)[0]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
