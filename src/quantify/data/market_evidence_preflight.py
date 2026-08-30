"""Read-only, fail-closed preflight for external CSI 800 market evidence."""

from __future__ import annotations

from collections import defaultdict
import csv
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Literal

PreflightStatus = Literal["PASS", "BLOCK"]

EXPECTED_CSI_800_INDEX_CODE = "000906"
BENCHMARK_METADATA_ARTIFACT_TYPE = "reviewed_benchmark_series"
MEMBERSHIP_METADATA_ARTIFACT_TYPE = "reviewed_pit_universe_membership"
MARKET_EVIDENCE_SCHEMA_VERSION = 1

_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PLACEHOLDER_VALUES = {
    "n/a",
    "na",
    "none",
    "not available",
    "tbd",
    "todo",
    "unknown",
}


@dataclass(frozen=True, slots=True)
class PreflightEvidence:
    """One deterministic contract decision."""

    code: str
    status: PreflightStatus
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "status": self.status, "message": self.message}


@dataclass(frozen=True, slots=True)
class FileEvidence:
    """Read evidence for an immutable external input."""

    path: str
    exists: bool
    readable: bool
    sha256: str | None

    def to_dict(self) -> dict[str, str | bool | None]:
        return {
            "path": self.path,
            "exists": self.exists,
            "readable": self.readable,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class CsvEvidence:
    """Observed CSV facts, including the reviewed hash binding."""

    file: FileEvidence
    expected_sha256: str | None
    sha256_matches_metadata: bool | None
    observations: int
    start_date: str | None
    end_date: str | None
    effective_dates: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = self.file.to_dict()
        payload.update(
            {
                "expected_sha256": self.expected_sha256,
                "sha256_matches_metadata": self.sha256_matches_metadata,
                "observations": self.observations,
                "start_date": self.start_date,
                "end_date": self.end_date,
            }
        )
        if self.effective_dates is not None:
            payload["effective_dates"] = self.effective_dates
        return payload


@dataclass(frozen=True, slots=True)
class MarketEvidencePreflightReport:
    """Serializable decision for benchmark and PIT membership evidence."""

    status: PreflightStatus
    expected_index_code: str
    required_start_date: str | None
    required_end_date: str | None
    minimum_members_per_snapshot: int
    benchmark_csv: CsvEvidence
    benchmark_metadata_file: FileEvidence
    benchmark_metadata: dict[str, Any]
    membership_csv: CsvEvidence
    membership_metadata_file: FileEvidence
    membership_metadata: dict[str, Any]
    evidence: tuple[PreflightEvidence, ...]

    @property
    def sufficient(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": "market_evidence_preflight",
            "schema_version": MARKET_EVIDENCE_SCHEMA_VERSION,
            "operation": "read_only_external_evidence_validation",
            "network_access": False,
            "broker_access": False,
            "status": self.status,
            "sufficient": self.sufficient,
            "expected_index_code": self.expected_index_code,
            "required_coverage": {
                "start_date": self.required_start_date,
                "end_date": self.required_end_date,
            },
            "minimum_members_per_snapshot": self.minimum_members_per_snapshot,
            "benchmark": {
                "csv": self.benchmark_csv.to_dict(),
                "metadata_json": self.benchmark_metadata_file.to_dict(),
                "metadata": dict(self.benchmark_metadata),
            },
            "membership": {
                "csv": self.membership_csv.to_dict(),
                "metadata_json": self.membership_metadata_file.to_dict(),
                "metadata": dict(self.membership_metadata),
            },
            "evidence": [item.to_dict() for item in self.evidence],
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Market Evidence Preflight: {self.status}",
            "",
            "- Operation: `read_only_external_evidence_validation`",
            "- Network access: `false`",
            "- Broker access: `false`",
            f"- Evidence sufficient: `{str(self.sufficient).lower()}`",
            f"- Expected index code: `{self.expected_index_code}`",
            f"- Required coverage: {_date_range(self.required_start_date, self.required_end_date)}",
            f"- Minimum members per PIT snapshot: {self.minimum_members_per_snapshot}",
            "",
            "## Benchmark",
            "",
            *_csv_markdown(self.benchmark_csv),
            f"- Metadata JSON: `{self.benchmark_metadata_file.path}`",
            f"- Metadata SHA-256: `{self.benchmark_metadata_file.sha256 or 'unavailable'}`",
            f"- Symbol: `{self.benchmark_metadata.get('symbol') or 'unavailable'}`",
            f"- Total return: `{_markdown_value(self.benchmark_metadata.get('total_return'))}`",
            "- Declared coverage: "
            f"{_date_range(_metadata_string(self.benchmark_metadata, 'coverage_start_date'), _metadata_string(self.benchmark_metadata, 'coverage_end_date'))}",
            f"- Source vendor: `{self.benchmark_metadata.get('source_vendor') or 'unavailable'}`",
            f"- Reviewed by: `{self.benchmark_metadata.get('reviewed_by') or 'unavailable'}`",
            "",
            "## PIT Membership",
            "",
            *_csv_markdown(self.membership_csv),
            f"- Metadata JSON: `{self.membership_metadata_file.path}`",
            f"- Metadata SHA-256: `{self.membership_metadata_file.sha256 or 'unavailable'}`",
            f"- Index code: `{self.membership_metadata.get('index_code') or 'unavailable'}`",
            f"- Point in time: `{_markdown_value(self.membership_metadata.get('point_in_time'))}`",
            f"- Snapshot mode: `{self.membership_metadata.get('snapshot_mode') or 'unavailable'}`",
            "- Declared coverage: "
            f"{_date_range(_metadata_string(self.membership_metadata, 'coverage_start_date'), _metadata_string(self.membership_metadata, 'coverage_end_date'))}",
            f"- Source vendor: `{self.membership_metadata.get('source_vendor') or 'unavailable'}`",
            f"- Source dataset: `{self.membership_metadata.get('source_dataset') or 'unavailable'}`",
            f"- Reviewed by: `{self.membership_metadata.get('reviewed_by') or 'unavailable'}`",
            "",
            "## Evidence",
            "",
        ]
        lines.extend(f"- `{item.status}` `{item.code}`: {item.message}" for item in self.evidence)
        lines.extend(
            [
                "",
                "A PASS attests only that the retained external files satisfy this preflight "
                "contract. It does not fetch data, contact a broker, or authorize trading.",
                "",
            ]
        )
        return "\n".join(lines)


def build_market_evidence_preflight(
    benchmark_csv: str | Path,
    benchmark_metadata_json: str | Path,
    membership_csv: str | Path,
    membership_metadata_json: str | Path,
    *,
    required_start_date: str | date | None = None,
    required_end_date: str | date | None = None,
    expected_index_code: str = EXPECTED_CSI_800_INDEX_CODE,
    benchmark_date_column: str = "date",
    benchmark_value_column: str = "value",
    membership_effective_date_column: str = "effective_date",
    membership_symbol_column: str = "symbol",
    membership_index_code_column: str = "index_code",
    minimum_members_per_snapshot: int = 700,
) -> MarketEvidencePreflightReport:
    """Validate retained external evidence without mutating inputs or using I/O services."""
    evidence: list[PreflightEvidence] = []
    if minimum_members_per_snapshot < 1:
        evidence.append(
            PreflightEvidence(
                "MEMBERSHIP_MINIMUM_COUNT_INVALID",
                "BLOCK",
                "minimum_members_per_snapshot must be at least 1.",
            )
        )
    expected_code = _normalize_index_code(expected_index_code)
    if expected_code != EXPECTED_CSI_800_INDEX_CODE:
        evidence.append(
            PreflightEvidence(
                "EXPECTED_INDEX_CODE_INVALID",
                "BLOCK",
                f"Expected index code must identify CSI 800 ({EXPECTED_CSI_800_INDEX_CODE}).",
            )
        )
    required_start = _coerce_requested_date(
        required_start_date, "REQUIRED_COVERAGE_START_INVALID", evidence
    )
    required_end = _coerce_requested_date(
        required_end_date, "REQUIRED_COVERAGE_END_INVALID", evidence
    )
    if required_start is not None and required_end is not None:
        if required_start > required_end:
            evidence.append(
                PreflightEvidence(
                    "REQUIRED_COVERAGE_RANGE_INVALID",
                    "BLOCK",
                    "Required coverage start_date must not be after end_date.",
                )
            )
        else:
            evidence.append(
                PreflightEvidence(
                    "REQUIRED_COVERAGE_VALID",
                    "PASS",
                    "Required market-evidence coverage is a valid closed date range.",
                )
            )

    benchmark_path = Path(benchmark_csv)
    benchmark_metadata_path = Path(benchmark_metadata_json)
    membership_path = Path(membership_csv)
    membership_metadata_path = Path(membership_metadata_json)

    benchmark_file = _fingerprint_file(benchmark_path, "BENCHMARK_CSV", evidence)
    benchmark_metadata_file = _fingerprint_file(
        benchmark_metadata_path, "BENCHMARK_METADATA", evidence
    )
    membership_file = _fingerprint_file(membership_path, "MEMBERSHIP_CSV", evidence)
    membership_metadata_file = _fingerprint_file(
        membership_metadata_path, "MEMBERSHIP_METADATA", evidence
    )

    benchmark_metadata_payload = _read_json_object(
        benchmark_metadata_path,
        benchmark_metadata_file,
        "BENCHMARK_METADATA",
        evidence,
    )
    membership_metadata_payload = _read_json_object(
        membership_metadata_path,
        membership_metadata_file,
        "MEMBERSHIP_METADATA",
        evidence,
    )
    benchmark_metadata = _contract_fields(benchmark_metadata_payload, _benchmark_metadata_fields())
    membership_metadata = _contract_fields(
        membership_metadata_payload, _membership_metadata_fields()
    )

    benchmark_coverage = _validate_benchmark_metadata(
        benchmark_metadata_payload,
        benchmark_metadata,
        expected_code,
        required_start,
        required_end,
        evidence,
    )
    membership_coverage = _validate_membership_metadata(
        membership_metadata_payload,
        membership_metadata,
        expected_code,
        required_start,
        required_end,
        membership_effective_date_column,
        membership_symbol_column,
        membership_index_code_column,
        evidence,
    )

    benchmark_expected_hash, benchmark_hash_match = _validate_hash_binding(
        "BENCHMARK",
        benchmark_file.sha256,
        benchmark_metadata.get("file_sha256"),
        evidence,
    )
    membership_expected_hash, membership_hash_match = _validate_hash_binding(
        "MEMBERSHIP",
        membership_file.sha256,
        membership_metadata.get("file_sha256"),
        evidence,
    )

    benchmark_rows = _read_csv_table(benchmark_path, benchmark_file, "BENCHMARK", evidence)
    benchmark_summary = _validate_benchmark_csv(
        benchmark_rows,
        benchmark_date_column,
        benchmark_value_column,
        benchmark_metadata.get("series_kind"),
        benchmark_coverage,
        required_start,
        required_end,
        evidence,
    )
    membership_rows = _read_csv_table(membership_path, membership_file, "MEMBERSHIP", evidence)
    membership_summary = _validate_membership_csv(
        membership_rows,
        membership_effective_date_column,
        membership_symbol_column,
        membership_index_code_column,
        expected_code,
        membership_coverage,
        required_start,
        minimum_members_per_snapshot,
        evidence,
    )
    _validate_observed_end_not_after_export(
        "BENCHMARK",
        benchmark_summary[2],
        _timezone_datetime(benchmark_metadata.get("source_exported_at")),
        evidence,
    )
    _validate_observed_end_not_after_export(
        "MEMBERSHIP",
        membership_summary[2],
        _timezone_datetime(membership_metadata.get("source_exported_at")),
        evidence,
    )
    for path, recorded, prefix in (
        (benchmark_path, benchmark_file.sha256, "BENCHMARK_CSV"),
        (benchmark_metadata_path, benchmark_metadata_file.sha256, "BENCHMARK_METADATA"),
        (membership_path, membership_file.sha256, "MEMBERSHIP_CSV"),
        (membership_metadata_path, membership_metadata_file.sha256, "MEMBERSHIP_METADATA"),
    ):
        _verify_file_unchanged(path, recorded, prefix, evidence)

    benchmark_csv_evidence = CsvEvidence(
        file=benchmark_file,
        expected_sha256=benchmark_expected_hash,
        sha256_matches_metadata=benchmark_hash_match,
        observations=benchmark_summary[0],
        start_date=_date_text(benchmark_summary[1]),
        end_date=_date_text(benchmark_summary[2]),
    )
    membership_csv_evidence = CsvEvidence(
        file=membership_file,
        expected_sha256=membership_expected_hash,
        sha256_matches_metadata=membership_hash_match,
        observations=membership_summary[0],
        start_date=_date_text(membership_summary[1]),
        end_date=_date_text(membership_summary[2]),
        effective_dates=membership_summary[3],
    )
    status: PreflightStatus = (
        "BLOCK" if any(item.status == "BLOCK" for item in evidence) else "PASS"
    )
    return MarketEvidencePreflightReport(
        status=status,
        expected_index_code=expected_code or str(expected_index_code).strip(),
        required_start_date=_date_text(required_start),
        required_end_date=_date_text(required_end),
        minimum_members_per_snapshot=minimum_members_per_snapshot,
        benchmark_csv=benchmark_csv_evidence,
        benchmark_metadata_file=benchmark_metadata_file,
        benchmark_metadata=benchmark_metadata,
        membership_csv=membership_csv_evidence,
        membership_metadata_file=membership_metadata_file,
        membership_metadata=membership_metadata,
        evidence=tuple(evidence),
    )


def write_market_evidence_preflight(
    report: MarketEvidencePreflightReport,
    output_dir: str | Path,
) -> Path:
    """Write market_evidence_preflight.json and market_evidence_preflight.md."""
    root = Path(output_dir)
    json_path = root / "market_evidence_preflight.json"
    markdown_path = root / "market_evidence_preflight.md"
    input_paths = {
        Path(value).resolve()
        for value in (
            report.benchmark_csv.file.path,
            report.benchmark_metadata_file.path,
            report.membership_csv.file.path,
            report.membership_metadata_file.path,
        )
    }
    if json_path.resolve() in input_paths or markdown_path.resolve() in input_paths:
        raise OSError("Preflight output paths must not overwrite external evidence inputs.")
    root.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    markdown_path.write_text(report.to_markdown(), encoding="utf-8")
    return root


# Report-suffixed aliases follow the naming used by older evidence builders.
build_market_evidence_preflight_report = build_market_evidence_preflight
write_market_evidence_preflight_report = write_market_evidence_preflight


def _fingerprint_file(
    path: Path,
    code_prefix: str,
    evidence: list[PreflightEvidence],
) -> FileEvidence:
    resolved = str(path.resolve())
    if not path.is_file():
        evidence.append(
            PreflightEvidence(
                f"{code_prefix}_MISSING",
                "BLOCK",
                f"Required input file is missing: {path}.",
            )
        )
        return FileEvidence(resolved, False, False, None)
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        evidence.append(
            PreflightEvidence(
                f"{code_prefix}_UNREADABLE",
                "BLOCK",
                f"Required input file cannot be read: {path}: {exc}.",
            )
        )
        return FileEvidence(resolved, True, False, None)
    evidence.append(
        PreflightEvidence(
            f"{code_prefix}_SHA256_RECORDED",
            "PASS",
            f"Recorded SHA-256 for retained input {path}.",
        )
    )
    return FileEvidence(resolved, True, True, digest.hexdigest())


def _read_json_object(
    path: Path,
    file_evidence: FileEvidence,
    code_prefix: str,
    evidence: list[PreflightEvidence],
) -> dict[str, Any] | None:
    if not file_evidence.readable:
        return None
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_json_object,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        evidence.append(
            PreflightEvidence(
                f"{code_prefix}_JSON_INVALID",
                "BLOCK",
                f"Metadata must be valid UTF-8 JSON without duplicate keys: {exc}.",
            )
        )
        return None
    if not isinstance(payload, dict):
        evidence.append(
            PreflightEvidence(
                f"{code_prefix}_ROOT_INVALID",
                "BLOCK",
                "Metadata JSON must contain an object at its root.",
            )
        )
        return None
    return payload


def _verify_file_unchanged(
    path: Path,
    recorded_sha256: str | None,
    code_prefix: str,
    evidence: list[PreflightEvidence],
) -> None:
    if recorded_sha256 is None:
        return
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        evidence.append(
            PreflightEvidence(
                f"{code_prefix}_CHANGED_DURING_PREFLIGHT",
                "BLOCK",
                f"Retained input became unreadable during preflight: {path}: {exc}.",
            )
        )
        return
    if digest.hexdigest() != recorded_sha256:
        evidence.append(
            PreflightEvidence(
                f"{code_prefix}_CHANGED_DURING_PREFLIGHT",
                "BLOCK",
                f"Retained input changed while it was being preflighted: {path}.",
            )
        )


def _validate_benchmark_metadata(
    payload: dict[str, Any] | None,
    metadata: dict[str, Any],
    expected_code: str,
    required_start: date | None,
    required_end: date | None,
    evidence: list[PreflightEvidence],
) -> tuple[date | None, date | None]:
    if payload is None:
        return None, None
    start_index = len(evidence)
    _validate_required_fields(payload, _benchmark_metadata_fields(), "BENCHMARK", evidence)
    _require_exact(
        metadata.get("artifact_type"),
        BENCHMARK_METADATA_ARTIFACT_TYPE,
        "BENCHMARK_METADATA_ARTIFACT_TYPE_INVALID",
        f"artifact_type must be {BENCHMARK_METADATA_ARTIFACT_TYPE!r}.",
        evidence,
    )
    _require_exact(
        metadata.get("schema_version"),
        MARKET_EVIDENCE_SCHEMA_VERSION,
        "BENCHMARK_METADATA_SCHEMA_VERSION_INVALID",
        "schema_version must be 1.",
        evidence,
    )
    for field in (
        "symbol",
        "name",
        "source_vendor",
        "source_exported_at",
        "reviewed_by",
        "reviewed_at",
    ):
        _require_provenance_string(metadata, field, "BENCHMARK", evidence)
    if metadata.get("total_return") is not True:
        evidence.append(
            PreflightEvidence(
                "BENCHMARK_TOTAL_RETURN_REQUIRED",
                "BLOCK",
                "Benchmark metadata total_return must be exactly true.",
            )
        )
    if metadata.get("series_kind") not in {"equity", "returns"}:
        evidence.append(
            PreflightEvidence(
                "BENCHMARK_SERIES_KIND_INVALID",
                "BLOCK",
                "Benchmark series_kind must be 'equity' or 'returns'.",
            )
        )
    symbol = _normalize_index_code(metadata.get("symbol"))
    if not expected_code or symbol != expected_code:
        evidence.append(
            PreflightEvidence(
                "BENCHMARK_INDEX_CODE_MISMATCH",
                "BLOCK",
                "Benchmark symbol does not identify the expected CSI 800 index code.",
            )
        )
    _validate_sha256_field(metadata.get("file_sha256"), "BENCHMARK", evidence)
    exported_at, _ = _validate_review_timestamps(metadata, "BENCHMARK", evidence)
    coverage = _validate_declared_coverage(
        metadata, "BENCHMARK", required_start, required_end, evidence
    )
    _validate_declared_end_not_after_export("BENCHMARK", coverage[1], exported_at, evidence)
    _append_contract_pass("BENCHMARK", start_index, evidence)
    return coverage


def _validate_membership_metadata(
    payload: dict[str, Any] | None,
    metadata: dict[str, Any],
    expected_code: str,
    required_start: date | None,
    required_end: date | None,
    effective_date_column: str,
    symbol_column: str,
    index_code_column: str,
    evidence: list[PreflightEvidence],
) -> tuple[date | None, date | None]:
    if payload is None:
        return None, None
    start_index = len(evidence)
    _validate_required_fields(payload, _membership_metadata_fields(), "MEMBERSHIP", evidence)
    _require_exact(
        metadata.get("artifact_type"),
        MEMBERSHIP_METADATA_ARTIFACT_TYPE,
        "MEMBERSHIP_METADATA_ARTIFACT_TYPE_INVALID",
        f"artifact_type must be {MEMBERSHIP_METADATA_ARTIFACT_TYPE!r}.",
        evidence,
    )
    _require_exact(
        metadata.get("schema_version"),
        MARKET_EVIDENCE_SCHEMA_VERSION,
        "MEMBERSHIP_METADATA_SCHEMA_VERSION_INVALID",
        "schema_version must be 1.",
        evidence,
    )
    for field in (
        "index_code",
        "source_vendor",
        "source_dataset",
        "source_exported_at",
        "reviewed_by",
        "reviewed_at",
        "effective_date_column",
        "symbol_column",
        "index_code_column",
    ):
        _require_provenance_string(metadata, field, "MEMBERSHIP", evidence)
    if metadata.get("point_in_time") is not True:
        evidence.append(
            PreflightEvidence(
                "MEMBERSHIP_NOT_POINT_IN_TIME",
                "BLOCK",
                "Membership metadata point_in_time must be exactly true.",
            )
        )
    if metadata.get("snapshot_mode") != "point_in_time_history":
        evidence.append(
            PreflightEvidence(
                "MEMBERSHIP_SNAPSHOT_MODE_INVALID",
                "BLOCK",
                "snapshot_mode must be 'point_in_time_history'; current snapshots are blocked.",
            )
        )
    if _normalize_index_code(metadata.get("index_code")) != expected_code or not expected_code:
        evidence.append(
            PreflightEvidence(
                "MEMBERSHIP_INDEX_CODE_MISMATCH",
                "BLOCK",
                "Membership metadata index_code does not identify the expected CSI 800 index.",
            )
        )
    declared_columns = {
        "effective_date_column": effective_date_column,
        "symbol_column": symbol_column,
        "index_code_column": index_code_column,
    }
    for field, configured in declared_columns.items():
        if metadata.get(field) != configured:
            evidence.append(
                PreflightEvidence(
                    f"MEMBERSHIP_METADATA_{field.upper()}_MISMATCH",
                    "BLOCK",
                    f"Membership metadata {field} must match configured column {configured!r}.",
                )
            )
    _validate_sha256_field(metadata.get("file_sha256"), "MEMBERSHIP", evidence)
    exported_at, _ = _validate_review_timestamps(metadata, "MEMBERSHIP", evidence)
    coverage = _validate_declared_coverage(
        metadata, "MEMBERSHIP", required_start, required_end, evidence
    )
    _validate_declared_end_not_after_export("MEMBERSHIP", coverage[1], exported_at, evidence)
    _append_contract_pass("MEMBERSHIP", start_index, evidence)
    return coverage


def _validate_declared_coverage(
    metadata: dict[str, Any],
    prefix: str,
    required_start: date | None,
    required_end: date | None,
    evidence: list[PreflightEvidence],
) -> tuple[date | None, date | None]:
    declared_start = _metadata_date(metadata.get("coverage_start_date"))
    declared_end = _metadata_date(metadata.get("coverage_end_date"))
    if declared_start is None:
        evidence.append(
            PreflightEvidence(
                f"{prefix}_COVERAGE_START_INVALID",
                "BLOCK",
                "coverage_start_date must be a valid YYYY-MM-DD date.",
            )
        )
    if declared_end is None:
        evidence.append(
            PreflightEvidence(
                f"{prefix}_COVERAGE_END_INVALID",
                "BLOCK",
                "coverage_end_date must be a valid YYYY-MM-DD date.",
            )
        )
    if declared_start is None or declared_end is None:
        return declared_start, declared_end
    if declared_start >= declared_end:
        evidence.append(
            PreflightEvidence(
                f"{prefix}_DECLARED_COVERAGE_INVALID",
                "BLOCK",
                "Declared coverage must span more than one calendar date.",
            )
        )
        return declared_start, declared_end
    if (
        required_start is not None
        and required_end is not None
        and (declared_start > required_start or declared_end < required_end)
    ):
        evidence.append(
            PreflightEvidence(
                f"{prefix}_DECLARED_COVERAGE_INADEQUATE",
                "BLOCK",
                "Declared metadata coverage does not span the required date range.",
            )
        )
    else:
        evidence.append(
            PreflightEvidence(
                f"{prefix}_DECLARED_COVERAGE_VALID",
                "PASS",
                "Declared metadata coverage spans the required date range.",
            )
        )
    return declared_start, declared_end


def _validate_hash_binding(
    prefix: str,
    actual_sha256: str | None,
    raw_expected_sha256: object,
    evidence: list[PreflightEvidence],
) -> tuple[str | None, bool | None]:
    expected = (
        str(raw_expected_sha256).lower()
        if isinstance(raw_expected_sha256, str) and _SHA256_PATTERN.fullmatch(raw_expected_sha256)
        else None
    )
    if expected is None or actual_sha256 is None:
        return expected, None
    matches = actual_sha256 == expected
    evidence.append(
        PreflightEvidence(
            f"{prefix}_SHA256_{'MATCH' if matches else 'MISMATCH'}",
            "PASS" if matches else "BLOCK",
            (
                f"{prefix.title()} CSV SHA-256 matches reviewed metadata."
                if matches
                else f"{prefix.title()} CSV SHA-256 does not match metadata file_sha256."
            ),
        )
    )
    return expected, matches


def _read_csv_table(
    path: Path,
    file_evidence: FileEvidence,
    prefix: str,
    evidence: list[PreflightEvidence],
) -> tuple[list[str], list[list[str]]] | None:
    if not file_evidence.readable:
        return None
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, strict=True)
            try:
                header = next(reader)
            except StopIteration:
                header = []
            rows = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        evidence.append(
            PreflightEvidence(
                f"{prefix}_CSV_INVALID",
                "BLOCK",
                f"CSV must be readable UTF-8 with valid quoting: {exc}.",
            )
        )
        return None
    if not header:
        evidence.append(PreflightEvidence(f"{prefix}_CSV_EMPTY", "BLOCK", "CSV has no header row."))
        return None
    if len(header) != len(set(header)):
        evidence.append(
            PreflightEvidence(
                f"{prefix}_CSV_HEADERS_DUPLICATE",
                "BLOCK",
                "CSV contains duplicate header names.",
            )
        )
    malformed = [index + 2 for index, row in enumerate(rows) if len(row) != len(header)]
    if malformed:
        evidence.append(
            PreflightEvidence(
                f"{prefix}_CSV_ROWS_MALFORMED",
                "BLOCK",
                "CSV rows do not match the header width: "
                + ", ".join(str(value) for value in malformed[:10])
                + ".",
            )
        )
    if not rows:
        evidence.append(
            PreflightEvidence(f"{prefix}_CSV_NO_ROWS", "BLOCK", "CSV has no data rows.")
        )
    return header, rows


def _validate_benchmark_csv(
    table: tuple[list[str], list[list[str]]] | None,
    date_column: str,
    value_column: str,
    series_kind: object,
    declared_coverage: tuple[date | None, date | None],
    required_start: date | None,
    required_end: date | None,
    evidence: list[PreflightEvidence],
) -> tuple[int, date | None, date | None]:
    if table is None:
        return 0, None, None
    validation_start = len(evidence)
    header, raw_rows = table
    if len(header) != len(set(header)):
        return len(raw_rows), None, None
    missing = [name for name in (date_column, value_column) if name not in header]
    if missing:
        evidence.append(
            PreflightEvidence(
                "BENCHMARK_CSV_COLUMNS_MISSING",
                "BLOCK",
                "Benchmark CSV is missing required columns: " + ", ".join(missing) + ".",
            )
        )
        return len(raw_rows), None, None
    if any(len(row) != len(header) for row in raw_rows):
        return len(raw_rows), None, None
    date_index = header.index(date_column)
    value_index = header.index(value_column)
    dates: list[date] = []
    invalid_date_rows: list[int] = []
    invalid_value_rows: list[int] = []
    for row_number, row in enumerate(raw_rows, start=2):
        observed_date = _metadata_date(row[date_index])
        if observed_date is None:
            invalid_date_rows.append(row_number)
        else:
            dates.append(observed_date)
        try:
            value = float(row[value_index])
        except ValueError:
            invalid_value_rows.append(row_number)
            continue
        if not math.isfinite(value):
            invalid_value_rows.append(row_number)
        elif series_kind == "equity" and value <= 0.0:
            invalid_value_rows.append(row_number)
        elif series_kind == "returns" and value < -1.0:
            invalid_value_rows.append(row_number)
    if invalid_date_rows:
        evidence.append(
            PreflightEvidence(
                "BENCHMARK_DATES_INVALID",
                "BLOCK",
                _row_message("Benchmark CSV contains invalid YYYY-MM-DD dates", invalid_date_rows),
            )
        )
    if len(dates) != len(set(dates)):
        evidence.append(
            PreflightEvidence(
                "BENCHMARK_DATES_DUPLICATE",
                "BLOCK",
                "Benchmark CSV contains duplicate calendar dates.",
            )
        )
    if invalid_value_rows:
        evidence.append(
            PreflightEvidence(
                "BENCHMARK_VALUES_INVALID",
                "BLOCK",
                _row_message(
                    "Benchmark values violate the finite series_kind contract",
                    invalid_value_rows,
                ),
            )
        )
    start = min(dates) if dates else None
    end = max(dates) if dates else None
    declared_start, declared_end = declared_coverage
    if (
        start is not None
        and end is not None
        and declared_start is not None
        and declared_end is not None
    ):
        if start > declared_start or end < declared_end:
            evidence.append(
                PreflightEvidence(
                    "BENCHMARK_OBSERVED_COVERAGE_INADEQUATE",
                    "BLOCK",
                    "Benchmark CSV observations do not span their declared metadata coverage.",
                )
            )
        elif (
            required_start is not None
            and required_end is not None
            and (start > required_start or end < required_end)
        ):
            evidence.append(
                PreflightEvidence(
                    "BENCHMARK_REQUIRED_COVERAGE_INADEQUATE",
                    "BLOCK",
                    "Benchmark CSV observations do not span the required date range.",
                )
            )
        elif not any(item.status == "BLOCK" for item in evidence[validation_start:]):
            evidence.append(
                PreflightEvidence(
                    "BENCHMARK_CSV_VALID",
                    "PASS",
                    "Benchmark CSV dates, values, and observed coverage are valid.",
                )
            )
    return len(raw_rows), start, end


def _validate_membership_csv(
    table: tuple[list[str], list[list[str]]] | None,
    effective_date_column: str,
    symbol_column: str,
    index_code_column: str,
    expected_code: str,
    declared_coverage: tuple[date | None, date | None],
    required_start: date | None,
    minimum_members_per_snapshot: int,
    evidence: list[PreflightEvidence],
) -> tuple[int, date | None, date | None, int]:
    if table is None:
        return 0, None, None, 0
    validation_start = len(evidence)
    header, raw_rows = table
    if len(header) != len(set(header)):
        return len(raw_rows), None, None, 0
    required_columns = (index_code_column, effective_date_column, symbol_column)
    missing = [name for name in required_columns if name not in header]
    if missing:
        evidence.append(
            PreflightEvidence(
                "MEMBERSHIP_CSV_COLUMNS_MISSING",
                "BLOCK",
                "Membership CSV is missing required columns: " + ", ".join(missing) + ".",
            )
        )
        return len(raw_rows), None, None, 0
    if any(len(row) != len(header) for row in raw_rows):
        return len(raw_rows), None, None, 0
    code_index = header.index(index_code_column)
    date_index = header.index(effective_date_column)
    symbol_index = header.index(symbol_column)
    dates: list[date] = []
    keys: list[tuple[str, date, str]] = []
    invalid_date_rows: list[int] = []
    invalid_key_rows: list[int] = []
    wrong_code_rows: list[int] = []
    for row_number, row in enumerate(raw_rows, start=2):
        observed_date = _metadata_date(row[date_index])
        symbol = row[symbol_index].strip().upper()
        code = _normalize_index_code(row[code_index])
        if observed_date is None:
            invalid_date_rows.append(row_number)
        else:
            dates.append(observed_date)
        if not symbol or _is_placeholder(symbol):
            invalid_key_rows.append(row_number)
        if not code or code != expected_code:
            wrong_code_rows.append(row_number)
        if observed_date is not None and symbol and code:
            keys.append((code, observed_date, symbol))
    if invalid_date_rows:
        evidence.append(
            PreflightEvidence(
                "MEMBERSHIP_DATES_INVALID",
                "BLOCK",
                _row_message(
                    "Membership CSV contains invalid YYYY-MM-DD effective dates",
                    invalid_date_rows,
                ),
            )
        )
    if invalid_key_rows:
        evidence.append(
            PreflightEvidence(
                "MEMBERSHIP_KEYS_INVALID",
                "BLOCK",
                _row_message("Membership CSV contains empty symbol keys", invalid_key_rows),
            )
        )
    if wrong_code_rows:
        evidence.append(
            PreflightEvidence(
                "MEMBERSHIP_CSV_INDEX_CODE_MISMATCH",
                "BLOCK",
                _row_message(
                    "Membership CSV rows do not identify the expected CSI 800 index",
                    wrong_code_rows,
                ),
            )
        )
    if len(keys) != len(set(keys)):
        evidence.append(
            PreflightEvidence(
                "MEMBERSHIP_KEYS_DUPLICATE",
                "BLOCK",
                "Membership CSV contains duplicate (index_code, effective_date, symbol) keys.",
            )
        )
    unique_dates = set(dates)
    if len(unique_dates) < 2:
        evidence.append(
            PreflightEvidence(
                "MEMBERSHIP_CURRENT_SNAPSHOT_ONLY",
                "BLOCK",
                "Membership CSV must contain at least two distinct effective dates.",
            )
        )
    members_by_date: dict[date, set[str]] = defaultdict(set)
    for code, effective_date, symbol in keys:
        if code == expected_code:
            members_by_date[effective_date].add(symbol)
    undersized = {
        effective_date.isoformat(): len(symbols)
        for effective_date, symbols in sorted(members_by_date.items())
        if len(symbols) < minimum_members_per_snapshot
    }
    if undersized:
        examples = ", ".join(
            f"{effective_date}={count}" for effective_date, count in list(undersized.items())[:5]
        )
        evidence.append(
            PreflightEvidence(
                "MEMBERSHIP_SNAPSHOT_MEMBER_COUNT_TOO_LOW",
                "BLOCK",
                "CSI 800 PIT snapshots must contain at least "
                f"{minimum_members_per_snapshot} distinct members; undersized snapshots: {examples}.",
            )
        )
    start = min(dates) if dates else None
    end = max(dates) if dates else None
    declared_start, declared_end = declared_coverage
    if (
        start is not None
        and end is not None
        and declared_start is not None
        and declared_end is not None
    ):
        if start > declared_start or end > declared_end:
            evidence.append(
                PreflightEvidence(
                    "MEMBERSHIP_EFFECTIVE_DATES_OUTSIDE_COVERAGE",
                    "BLOCK",
                    "Membership effective dates are inconsistent with declared coverage.",
                )
            )
        elif required_start is not None and not any(value <= required_start for value in dates):
            evidence.append(
                PreflightEvidence(
                    "MEMBERSHIP_INITIAL_SNAPSHOT_MISSING",
                    "BLOCK",
                    "No membership snapshot is effective on or before required_start_date.",
                )
            )
        elif not any(declared_start <= value <= declared_end for value in dates):
            evidence.append(
                PreflightEvidence(
                    "MEMBERSHIP_DECLARED_COVERAGE_UNSUPPORTED",
                    "BLOCK",
                    "No membership effective date falls within declared coverage.",
                )
            )
        elif len(unique_dates) >= 2 and not any(
            item.status == "BLOCK" for item in evidence[validation_start:]
        ):
            evidence.append(
                PreflightEvidence(
                    "MEMBERSHIP_CSV_VALID",
                    "PASS",
                    "Membership keys and effective-dated PIT history are valid.",
                )
            )
    return len(raw_rows), start, end, len(unique_dates)


def _validate_required_fields(
    payload: dict[str, Any],
    fields: tuple[str, ...],
    prefix: str,
    evidence: list[PreflightEvidence],
) -> None:
    missing = [field for field in fields if field not in payload]
    if missing:
        evidence.append(
            PreflightEvidence(
                f"{prefix}_METADATA_FIELDS_MISSING",
                "BLOCK",
                f"{prefix.title()} metadata is missing required fields: "
                + ", ".join(missing)
                + ".",
            )
        )


def _require_provenance_string(
    metadata: dict[str, Any],
    field: str,
    prefix: str,
    evidence: list[PreflightEvidence],
) -> None:
    value = metadata.get(field)
    if not isinstance(value, str) or not value.strip() or _is_placeholder(value):
        evidence.append(
            PreflightEvidence(
                f"{prefix}_METADATA_{field.upper()}_INVALID",
                "BLOCK",
                f"{field} must be a non-placeholder string.",
            )
        )


def _validate_review_timestamps(
    metadata: dict[str, Any],
    prefix: str,
    evidence: list[PreflightEvidence],
) -> tuple[datetime | None, datetime | None]:
    exported = _timezone_datetime(metadata.get("source_exported_at"))
    reviewed = _timezone_datetime(metadata.get("reviewed_at"))
    if exported is None:
        evidence.append(
            PreflightEvidence(
                f"{prefix}_SOURCE_EXPORTED_AT_INVALID",
                "BLOCK",
                "source_exported_at must be an ISO-8601 timestamp with a UTC offset.",
            )
        )
    if reviewed is None:
        evidence.append(
            PreflightEvidence(
                f"{prefix}_REVIEWED_AT_INVALID",
                "BLOCK",
                "reviewed_at must be an ISO-8601 timestamp with a UTC offset.",
            )
        )
    if exported is not None and reviewed is not None and reviewed < exported:
        evidence.append(
            PreflightEvidence(
                f"{prefix}_REVIEW_PRECEDES_EXPORT",
                "BLOCK",
                "reviewed_at must not precede source_exported_at.",
            )
        )
    return exported, reviewed


def _validate_declared_end_not_after_export(
    prefix: str,
    declared_end: date | None,
    exported_at: datetime | None,
    evidence: list[PreflightEvidence],
) -> None:
    if declared_end is not None and exported_at is not None and declared_end > exported_at.date():
        evidence.append(
            PreflightEvidence(
                f"{prefix}_DECLARED_COVERAGE_AFTER_EXPORT",
                "BLOCK",
                "coverage_end_date cannot be later than the source export date.",
            )
        )


def _validate_observed_end_not_after_export(
    prefix: str,
    observed_end: date | None,
    exported_at: datetime | None,
    evidence: list[PreflightEvidence],
) -> None:
    if observed_end is not None and exported_at is not None and observed_end > exported_at.date():
        evidence.append(
            PreflightEvidence(
                f"{prefix}_OBSERVATION_AFTER_EXPORT",
                "BLOCK",
                "CSV dates cannot be later than the source export date.",
            )
        )


def _validate_sha256_field(
    value: object,
    prefix: str,
    evidence: list[PreflightEvidence],
) -> None:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        evidence.append(
            PreflightEvidence(
                f"{prefix}_METADATA_FILE_SHA256_INVALID",
                "BLOCK",
                "file_sha256 must be a 64-character hexadecimal SHA-256 digest.",
            )
        )


def _append_contract_pass(
    prefix: str,
    start_index: int,
    evidence: list[PreflightEvidence],
) -> None:
    if not any(item.status == "BLOCK" for item in evidence[start_index:]):
        evidence.append(
            PreflightEvidence(
                f"{prefix}_METADATA_VALID",
                "PASS",
                f"{prefix.title()} reviewed metadata contract is complete and valid.",
            )
        )


def _require_exact(
    value: object,
    expected: object,
    code: str,
    message: str,
    evidence: list[PreflightEvidence],
) -> None:
    if value != expected or type(value) is not type(expected):
        evidence.append(PreflightEvidence(code, "BLOCK", message))


def _coerce_requested_date(
    value: str | date | None,
    code: str,
    evidence: list[PreflightEvidence],
) -> date | None:
    if isinstance(value, datetime):
        parsed = None
    elif isinstance(value, date):
        parsed = value
    else:
        parsed = _metadata_date(value)
    if parsed is None:
        evidence.append(PreflightEvidence(code, "BLOCK", "A valid YYYY-MM-DD date is required."))
    return parsed


def _metadata_date(value: object) -> date | None:
    if not isinstance(value, str) or not _ISO_DATE_PATTERN.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _timezone_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _normalize_index_code(value: object) -> str:
    if not isinstance(value, str):
        return ""
    candidate = value.strip().upper()
    if not candidate:
        return ""
    pieces = [piece for piece in candidate.split(".") if piece]
    numeric = next((piece for piece in pieces if piece.isdigit()), "")
    if not numeric and len(candidate) == 8 and candidate[:2] in {"SH", "SZ"}:
        numeric = candidate[2:]
    return numeric if len(numeric) == 6 and numeric.isdigit() else candidate


def _contract_fields(
    payload: dict[str, Any] | None,
    fields: tuple[str, ...],
) -> dict[str, Any]:
    if payload is None:
        return {}
    return {field: payload.get(field) for field in fields if field in payload}


def _benchmark_metadata_fields() -> tuple[str, ...]:
    return (
        "artifact_type",
        "schema_version",
        "symbol",
        "name",
        "total_return",
        "series_kind",
        "coverage_start_date",
        "coverage_end_date",
        "source_vendor",
        "source_exported_at",
        "reviewed_by",
        "reviewed_at",
        "file_sha256",
    )


def _membership_metadata_fields() -> tuple[str, ...]:
    return (
        "artifact_type",
        "schema_version",
        "index_code",
        "point_in_time",
        "snapshot_mode",
        "effective_date_column",
        "symbol_column",
        "index_code_column",
        "coverage_start_date",
        "coverage_end_date",
        "source_vendor",
        "source_dataset",
        "source_exported_at",
        "reviewed_by",
        "reviewed_at",
        "file_sha256",
    )


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return normalized in _PLACEHOLDER_VALUES or "<" in value or ">" in value


def _row_message(prefix: str, rows: list[int]) -> str:
    return f"{prefix}; rows: {', '.join(str(value) for value in rows[:10])}."


def _date_text(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _metadata_string(metadata: dict[str, Any], field: str) -> str | None:
    value = metadata.get(field)
    return value if isinstance(value, str) else None


def _date_range(start: str | None, end: str | None) -> str:
    return f"`{start}` to `{end}`" if start and end else "unavailable"


def _markdown_value(value: object) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return str(value) if value is not None else "unavailable"


def _csv_markdown(value: CsvEvidence) -> list[str]:
    lines = [
        f"- CSV: `{value.file.path}`",
        f"- SHA-256: `{value.file.sha256 or 'unavailable'}`",
        f"- Hash matches metadata: `{_markdown_value(value.sha256_matches_metadata)}`",
        f"- Observed coverage: {_date_range(value.start_date, value.end_date)}",
        f"- Observations: {value.observations}",
    ]
    if value.effective_dates is not None:
        lines.append(f"- Distinct effective dates: {value.effective_dates}")
    return lines
