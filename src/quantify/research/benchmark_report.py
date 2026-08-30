"""Operational, fail-closed review for a formally attested benchmark series."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Literal, cast

import pandas as pd

from quantify.research.benchmark import (
    AlignmentEvidence,
    BenchmarkConfiguration,
    BenchmarkIdentity,
    BenchmarkMetrics,
    BenchmarkStatus,
    BootstrapConfidenceInterval,
    SeriesKind,
    analyze_benchmark,
)

BenchmarkReviewStatus = Literal["PASS", "WATCH", "BLOCK"]

_METADATA_ARTIFACT_TYPE = "reviewed_benchmark_series"
_METADATA_SCHEMA_VERSION = 1
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_REQUIRED_METADATA_FIELDS = (
    "artifact_type",
    "schema_version",
    "symbol",
    "name",
    "total_return",
    "series_kind",
    "source_vendor",
    "source_exported_at",
    "reviewed_by",
    "reviewed_at",
    "file_sha256",
)


class BenchmarkReviewInputError(ValueError):
    """Raised when an existing JSON or CSV input cannot be parsed."""


@dataclass(frozen=True, slots=True)
class BenchmarkReviewEvidence:
    code: str
    status: BenchmarkReviewStatus
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "status": self.status, "message": self.message}


@dataclass(frozen=True, slots=True)
class ReviewedBenchmarkMetadata:
    artifact_type: str | None
    schema_version: int | None
    symbol: str | None
    name: str | None
    total_return: bool | None
    series_kind: str | None
    source_vendor: str | None
    source_exported_at: str | None
    reviewed_by: str | None
    reviewed_at: str | None
    file_sha256: str | None

    def to_dict(self) -> dict[str, str | int | bool | None]:
        return {
            "artifact_type": self.artifact_type,
            "schema_version": self.schema_version,
            "symbol": self.symbol,
            "name": self.name,
            "total_return": self.total_return,
            "series_kind": self.series_kind,
            "source_vendor": self.source_vendor,
            "source_exported_at": self.source_exported_at,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at,
            "file_sha256": self.file_sha256,
        }


@dataclass(frozen=True, slots=True)
class InputSeriesEvidence:
    path: str
    sha256: str | None
    expected_sha256: str | None
    sha256_matches_metadata: bool | None
    date_column: str
    value_column: str
    series_kind: str
    observations: int
    start_date: str | None
    end_date: str | None

    def to_dict(self) -> dict[str, str | int | bool | None]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "expected_sha256": self.expected_sha256,
            "sha256_matches_metadata": self.sha256_matches_metadata,
            "date_column": self.date_column,
            "value_column": self.value_column,
            "series_kind": self.series_kind,
            "observations": self.observations,
            "start_date": self.start_date,
            "end_date": self.end_date,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkReviewReport:
    status: BenchmarkReviewStatus
    sufficient: bool
    strategy_input: InputSeriesEvidence
    benchmark_input: InputSeriesEvidence
    metadata_path: str
    metadata_sha256: str | None
    metadata: ReviewedBenchmarkMetadata
    identity: BenchmarkIdentity | None
    configuration: BenchmarkConfiguration
    alignment: AlignmentEvidence | None
    metrics: BenchmarkMetrics | None
    annualized_excess_return_ci: BootstrapConfidenceInterval | None
    information_ratio_ci: BootstrapConfidenceInterval | None
    evidence: tuple[BenchmarkReviewEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": "benchmark_report",
            "schema_version": 1,
            "evidence_role": "benchmark_evidence_only",
            "can_upgrade_deterministic_gate": False,
            "status": self.status,
            "sufficient": self.sufficient,
            "inputs": {
                "strategy_equity_csv": self.strategy_input.to_dict(),
                "benchmark_csv": self.benchmark_input.to_dict(),
                "benchmark_metadata_json": {
                    "path": self.metadata_path,
                    "sha256": self.metadata_sha256,
                },
            },
            "benchmark_metadata": self.metadata.to_dict(),
            "identity": self.identity.to_dict() if self.identity else None,
            "configuration": self.configuration.to_dict(),
            "alignment": self.alignment.to_dict() if self.alignment else None,
            "metrics": self.metrics.to_dict() if self.metrics else _unavailable_metrics(),
            "confidence_intervals": {
                "annualized_excess_return_95": (
                    self.annualized_excess_return_ci.to_dict()
                    if self.annualized_excess_return_ci
                    else None
                ),
                "information_ratio_95": (
                    self.information_ratio_ci.to_dict() if self.information_ratio_ci else None
                ),
            },
            "evidence": [item.to_dict() for item in self.evidence],
        }

    def to_markdown(self) -> str:
        identity = self.identity
        lines = [
            f"# Benchmark Review: {self.status}",
            "",
            "- Evidence role: `benchmark_evidence_only`",
            "- Can upgrade deterministic gate: `false`",
            f"- Evidence sufficient: `{str(self.sufficient).lower()}`",
            "",
            "## Inputs",
            "",
            *_input_markdown("Strategy equity", self.strategy_input),
            *_input_markdown("Benchmark", self.benchmark_input),
            f"- Metadata JSON: `{self.metadata_path}`",
            f"- Metadata SHA-256: `{self.metadata_sha256 or 'unavailable'}`",
            "",
            "## Benchmark Identity",
            "",
            f"- Symbol: `{identity.symbol if identity else 'unavailable'}`",
            f"- Name: `{identity.name if identity else 'unavailable'}`",
            f"- Total return: `{_markdown_bool(identity.total_return if identity else None)}`",
            f"- Series kind: `{self.metadata.series_kind or 'unavailable'}`",
            f"- Source vendor: `{self.metadata.source_vendor or 'unavailable'}`",
            f"- Source exported at: `{self.metadata.source_exported_at or 'unavailable'}`",
            f"- Reviewed by: `{self.metadata.reviewed_by or 'unavailable'}`",
            f"- Reviewed at: `{self.metadata.reviewed_at or 'unavailable'}`",
            "",
            "## Alignment",
            "",
        ]
        if self.alignment is None:
            lines.append("- Unavailable because formal benchmark evidence is incomplete.")
        else:
            lines.extend(
                [
                    f"- Aligned return observations: {self.alignment.aligned_observations}",
                    f"- Aligned range: {_date_range(self.alignment.start_date, self.alignment.end_date)}",
                    "- Strategy unmatched returns: "
                    f"{self.alignment.strategy_unmatched_observations}",
                    "- Benchmark unmatched returns: "
                    f"{self.alignment.benchmark_unmatched_observations}",
                ]
            )
        lines.extend(["", "## Metrics", ""])
        metrics = self.metrics
        lines.extend(
            [
                f"- Strategy CAGR: {_markdown_number(metrics.strategy_cagr if metrics else None)}",
                f"- Benchmark CAGR: {_markdown_number(metrics.benchmark_cagr if metrics else None)}",
                f"- Excess CAGR: {_markdown_number(metrics.excess_cagr if metrics else None)}",
                "- Annualized tracking error: "
                f"{_markdown_number(metrics.annualized_tracking_error if metrics else None)}",
                f"- Information ratio: {_markdown_number(metrics.information_ratio if metrics else None)}",
                "- Annualized excess-return 95% CI: "
                f"{_interval_markdown(self.annualized_excess_return_ci)}",
                f"- Information-ratio 95% CI: {_interval_markdown(self.information_ratio_ci)}",
                "",
                "## Evidence",
                "",
            ]
        )
        lines.extend(
            f"- `{item.status}` `{item.code}`: {item.message}" for item in self.evidence
        )
        lines.extend(
            [
                "",
                "A PASS means only that the benchmark evidence contract and statistical review "
                "passed. It cannot upgrade, satisfy, or bypass any deterministic gate.",
                "",
            ]
        )
        return "\n".join(lines)


def build_benchmark_review_report(
    strategy_equity_csv: str | Path,
    benchmark_csv: str | Path,
    benchmark_metadata_json: str | Path,
    *,
    strategy_date_column: str = "timestamp",
    strategy_value_column: str = "equity",
    benchmark_date_column: str = "date",
    benchmark_value_column: str = "value",
    periods_per_year: int = 252,
    block_size: int = 5,
    n_bootstrap: int = 1_000,
    random_seed: int = 0,
) -> BenchmarkReviewReport:
    """Build a formal benchmark review without promoting incomplete evidence."""
    strategy_path = Path(strategy_equity_csv)
    benchmark_path = Path(benchmark_csv)
    metadata_path = Path(benchmark_metadata_json)
    configuration = BenchmarkConfiguration(
        periods_per_year=periods_per_year,
        block_size=block_size,
        n_bootstrap=n_bootstrap,
        random_seed=random_seed,
    )
    evidence: list[BenchmarkReviewEvidence] = []

    strategy_sha256 = _try_file_sha256(strategy_path, "STRATEGY_CSV", evidence)
    benchmark_sha256 = _try_file_sha256(benchmark_path, "BENCHMARK_CSV", evidence)
    metadata_sha256 = _try_file_sha256(metadata_path, "BENCHMARK_METADATA", evidence)
    metadata_payload = _read_metadata(metadata_path) if metadata_sha256 else {}
    metadata = _reviewed_metadata(metadata_payload)
    _validate_metadata(metadata_payload, metadata, evidence)

    expected_sha256 = metadata.file_sha256
    sha256_matches_metadata: bool | None = None
    if expected_sha256 and _SHA256_PATTERN.fullmatch(expected_sha256):
        sha256_matches_metadata = (
            benchmark_sha256 is not None
            and benchmark_sha256.lower() == expected_sha256.lower()
        )
        if benchmark_sha256 is not None:
            if sha256_matches_metadata:
                evidence.append(
                    BenchmarkReviewEvidence(
                        "BENCHMARK_SHA256_MATCH",
                        "PASS",
                        "Benchmark CSV SHA-256 matches the reviewed metadata.",
                    )
                )
            else:
                evidence.append(
                    BenchmarkReviewEvidence(
                        "BENCHMARK_SHA256_MISMATCH",
                        "BLOCK",
                        "Benchmark CSV SHA-256 does not match metadata file_sha256.",
                    )
                )

    strategy_series, strategy_input = _read_series_csv(
        strategy_path,
        sha256=strategy_sha256,
        expected_sha256=None,
        sha256_matches_metadata=None,
        date_column=strategy_date_column,
        value_column=strategy_value_column,
        series_kind="equity",
        label="strategy",
        evidence=evidence,
    )
    benchmark_series, benchmark_input = _read_series_csv(
        benchmark_path,
        sha256=benchmark_sha256,
        expected_sha256=expected_sha256,
        sha256_matches_metadata=sha256_matches_metadata,
        date_column=benchmark_date_column,
        value_column=benchmark_value_column,
        series_kind=metadata.series_kind or "unavailable",
        label="benchmark",
        evidence=evidence,
    )
    identity = _identity_from_metadata(metadata)

    if any(item.status == "BLOCK" for item in evidence):
        return _review_report(
            status="BLOCK",
            sufficient=False,
            strategy_input=strategy_input,
            benchmark_input=benchmark_input,
            metadata_path=metadata_path,
            metadata_sha256=metadata_sha256,
            metadata=metadata,
            identity=identity,
            configuration=configuration,
            evidence=evidence,
        )

    if strategy_series is None or benchmark_series is None or identity is None:
        evidence.append(
            BenchmarkReviewEvidence(
                "BENCHMARK_REVIEW_INPUT_INCOMPLETE",
                "BLOCK",
                "Formal benchmark analysis inputs are incomplete.",
            )
        )
        return _review_report(
            status="BLOCK",
            sufficient=False,
            strategy_input=strategy_input,
            benchmark_input=benchmark_input,
            metadata_path=metadata_path,
            metadata_sha256=metadata_sha256,
            metadata=metadata,
            identity=identity,
            configuration=configuration,
            evidence=evidence,
        )

    analysis = analyze_benchmark(
        strategy_series,
        benchmark_series,
        identity,
        strategy_series_kind="equity",
        benchmark_series_kind=cast(SeriesKind, metadata.series_kind),
        periods_per_year=periods_per_year,
        block_size=block_size,
        n_bootstrap=n_bootstrap,
        random_seed=random_seed,
    )
    evidence.extend(
        BenchmarkReviewEvidence(
            code=f"BENCHMARK_ANALYSIS_{analysis.status}",
            status=analysis.status,
            message=finding,
        )
        for finding in analysis.findings
    )
    if analysis.status == "BLOCK":
        return _review_report(
            status="BLOCK",
            sufficient=False,
            strategy_input=strategy_input,
            benchmark_input=benchmark_input,
            metadata_path=metadata_path,
            metadata_sha256=metadata_sha256,
            metadata=metadata,
            identity=identity,
            configuration=configuration,
            alignment=analysis.alignment,
            metrics=analysis.metrics,
            annualized_excess_return_ci=analysis.annualized_excess_return_ci,
            information_ratio_ci=analysis.information_ratio_ci,
            evidence=evidence,
        )

    if not _analysis_is_complete(analysis.metrics, analysis.annualized_excess_return_ci, analysis.information_ratio_ci):
        evidence.append(
            BenchmarkReviewEvidence(
                "BENCHMARK_STATISTICS_INCOMPLETE",
                "BLOCK",
                "Excess CAGR, tracking error, information ratio, and both 95% confidence "
                "intervals must all be available.",
            )
        )
        return _review_report(
            status="BLOCK",
            sufficient=False,
            strategy_input=strategy_input,
            benchmark_input=benchmark_input,
            metadata_path=metadata_path,
            metadata_sha256=metadata_sha256,
            metadata=metadata,
            identity=identity,
            configuration=configuration,
            alignment=analysis.alignment,
            metrics=analysis.metrics,
            annualized_excess_return_ci=analysis.annualized_excess_return_ci,
            information_ratio_ci=analysis.information_ratio_ci,
            evidence=evidence,
        )

    excess_interval_status, excess_interval_evidence = _excess_interval_decision(
        analysis.annualized_excess_return_ci
    )
    evidence.append(excess_interval_evidence)
    status = _worst_status(
        analysis.status,
        excess_interval_status,
        analysis.annualized_excess_return_ci.status,
        analysis.information_ratio_ci.status,
    )
    return _review_report(
        status=status,
        sufficient=True,
        strategy_input=strategy_input,
        benchmark_input=benchmark_input,
        metadata_path=metadata_path,
        metadata_sha256=metadata_sha256,
        metadata=metadata,
        identity=identity,
        configuration=configuration,
        alignment=analysis.alignment,
        metrics=analysis.metrics,
        annualized_excess_return_ci=analysis.annualized_excess_return_ci,
        information_ratio_ci=analysis.information_ratio_ci,
        evidence=evidence,
    )


def write_benchmark_review_report(
    report: BenchmarkReviewReport,
    output_dir: str | Path,
) -> Path:
    """Write benchmark_report.json and benchmark_report.md."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "benchmark_report.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    (root / "benchmark_report.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _read_metadata(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise BenchmarkReviewInputError(
            f"Benchmark metadata JSON cannot be parsed: {path}: {exc}"
        ) from exc
    return payload if isinstance(payload, dict) else {"__invalid_root__": type(payload).__name__}


def _read_series_csv(
    path: Path,
    *,
    sha256: str | None,
    expected_sha256: str | None,
    sha256_matches_metadata: bool | None,
    date_column: str,
    value_column: str,
    series_kind: str,
    label: str,
    evidence: list[BenchmarkReviewEvidence],
) -> tuple[pd.Series | None, InputSeriesEvidence]:
    if sha256 is None:
        return None, _input_evidence(
            path,
            sha256,
            expected_sha256,
            sha256_matches_metadata,
            date_column,
            value_column,
            series_kind,
        )
    try:
        frame = pd.read_csv(path)
    except (OSError, UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise BenchmarkReviewInputError(f"{label} CSV cannot be parsed: {path}: {exc}") from exc

    missing_columns = [name for name in (date_column, value_column) if name not in frame.columns]
    if missing_columns:
        evidence.append(
            BenchmarkReviewEvidence(
                f"{label.upper()}_CSV_COLUMNS_MISSING",
                "BLOCK",
                f"{label} CSV is missing required columns: {', '.join(missing_columns)}.",
            )
        )
        return None, _input_evidence(
            path,
            sha256,
            expected_sha256,
            sha256_matches_metadata,
            date_column,
            value_column,
            series_kind,
            observations=len(frame),
        )

    dates = pd.to_datetime(frame[date_column], errors="coerce")
    valid_dates = not dates.isna().any()
    duplicate_dates = bool(dates.duplicated().any()) if valid_dates else False
    if not valid_dates:
        evidence.append(
            BenchmarkReviewEvidence(
                f"{label.upper()}_CSV_DATES_INVALID",
                "BLOCK",
                f"{label} CSV contains invalid dates in column {date_column!r}.",
            )
        )
    if duplicate_dates:
        evidence.append(
            BenchmarkReviewEvidence(
                f"{label.upper()}_CSV_DATES_DUPLICATE",
                "BLOCK",
                f"{label} CSV contains duplicate calendar dates.",
            )
        )
    start_date = dates.min().date().isoformat() if valid_dates and len(dates) else None
    end_date = dates.max().date().isoformat() if valid_dates and len(dates) else None
    input_evidence = _input_evidence(
        path,
        sha256,
        expected_sha256,
        sha256_matches_metadata,
        date_column,
        value_column,
        series_kind,
        observations=len(frame),
        start_date=start_date,
        end_date=end_date,
    )
    series = pd.Series(frame[value_column].to_numpy(), index=frame[date_column].to_numpy())
    return series, input_evidence


def _input_evidence(
    path: Path,
    sha256: str | None,
    expected_sha256: str | None,
    sha256_matches_metadata: bool | None,
    date_column: str,
    value_column: str,
    series_kind: str,
    *,
    observations: int = 0,
    start_date: str | None = None,
    end_date: str | None = None,
) -> InputSeriesEvidence:
    return InputSeriesEvidence(
        path=str(path.resolve()),
        sha256=sha256,
        expected_sha256=expected_sha256,
        sha256_matches_metadata=sha256_matches_metadata,
        date_column=date_column,
        value_column=value_column,
        series_kind=series_kind,
        observations=observations,
        start_date=start_date,
        end_date=end_date,
    )


def _reviewed_metadata(payload: dict[str, Any]) -> ReviewedBenchmarkMetadata:
    schema_version = payload.get("schema_version")
    return ReviewedBenchmarkMetadata(
        artifact_type=_non_empty_string(payload.get("artifact_type")),
        schema_version=(
            schema_version
            if isinstance(schema_version, int) and not isinstance(schema_version, bool)
            else None
        ),
        symbol=_non_empty_string(payload.get("symbol")),
        name=_non_empty_string(payload.get("name")),
        total_return=(
            payload.get("total_return") if isinstance(payload.get("total_return"), bool) else None
        ),
        series_kind=_non_empty_string(payload.get("series_kind")),
        source_vendor=_non_empty_string(payload.get("source_vendor")),
        source_exported_at=_non_empty_string(payload.get("source_exported_at")),
        reviewed_by=_non_empty_string(payload.get("reviewed_by")),
        reviewed_at=_non_empty_string(payload.get("reviewed_at")),
        file_sha256=_non_empty_string(payload.get("file_sha256")),
    )


def _validate_metadata(
    payload: dict[str, Any],
    metadata: ReviewedBenchmarkMetadata,
    evidence: list[BenchmarkReviewEvidence],
) -> None:
    if "__invalid_root__" in payload:
        evidence.append(
            BenchmarkReviewEvidence(
                "BENCHMARK_METADATA_ROOT_INVALID",
                "BLOCK",
                "Benchmark metadata JSON must contain an object at its root.",
            )
        )
        return
    missing = [field for field in _REQUIRED_METADATA_FIELDS if field not in payload]
    if missing:
        evidence.append(
            BenchmarkReviewEvidence(
                "BENCHMARK_METADATA_FIELDS_MISSING",
                "BLOCK",
                f"Benchmark metadata is missing required fields: {', '.join(missing)}.",
            )
        )
    checks = (
        (
            metadata.artifact_type == _METADATA_ARTIFACT_TYPE,
            "BENCHMARK_METADATA_ARTIFACT_TYPE_INVALID",
            f"artifact_type must be {_METADATA_ARTIFACT_TYPE!r}.",
        ),
        (
            metadata.schema_version == _METADATA_SCHEMA_VERSION,
            "BENCHMARK_METADATA_SCHEMA_VERSION_INVALID",
            f"schema_version must be {_METADATA_SCHEMA_VERSION}.",
        ),
        (metadata.symbol is not None, "BENCHMARK_METADATA_SYMBOL_INVALID", "symbol is required."),
        (metadata.name is not None, "BENCHMARK_METADATA_NAME_INVALID", "name is required."),
        (
            metadata.total_return is True,
            "BENCHMARK_METADATA_TOTAL_RETURN_REQUIRED",
            "total_return must be the boolean true for a formal benchmark review.",
        ),
        (
            metadata.series_kind in {"equity", "returns"},
            "BENCHMARK_METADATA_SERIES_KIND_INVALID",
            "series_kind must be 'equity' or 'returns'.",
        ),
        (
            metadata.source_vendor is not None,
            "BENCHMARK_METADATA_SOURCE_VENDOR_INVALID",
            "source_vendor is required.",
        ),
        (
            metadata.source_exported_at is not None,
            "BENCHMARK_METADATA_SOURCE_EXPORTED_AT_INVALID",
            "source_exported_at is required.",
        ),
        (
            metadata.reviewed_by is not None,
            "BENCHMARK_METADATA_REVIEWED_BY_INVALID",
            "reviewed_by is required.",
        ),
        (
            metadata.reviewed_at is not None,
            "BENCHMARK_METADATA_REVIEWED_AT_INVALID",
            "reviewed_at is required.",
        ),
        (
            metadata.file_sha256 is not None
            and bool(_SHA256_PATTERN.fullmatch(metadata.file_sha256)),
            "BENCHMARK_METADATA_FILE_SHA256_INVALID",
            "file_sha256 must be a 64-character hexadecimal SHA-256 digest.",
        ),
    )
    for valid, code, message in checks:
        if not valid:
            evidence.append(BenchmarkReviewEvidence(code, "BLOCK", message))
    if not any(item.status == "BLOCK" for item in evidence):
        evidence.append(
            BenchmarkReviewEvidence(
                "BENCHMARK_METADATA_VALID",
                "PASS",
                "Reviewed benchmark metadata contract is complete and valid.",
            )
        )


def _identity_from_metadata(metadata: ReviewedBenchmarkMetadata) -> BenchmarkIdentity | None:
    if metadata.symbol is None or metadata.name is None or metadata.total_return is None:
        return None
    return BenchmarkIdentity(
        symbol=metadata.symbol,
        name=metadata.name,
        total_return=metadata.total_return,
    )


def _analysis_is_complete(
    metrics: BenchmarkMetrics,
    excess_interval: BootstrapConfidenceInterval,
    information_ratio_interval: BootstrapConfidenceInterval,
) -> bool:
    return (
        metrics.strategy_cagr is not None
        and metrics.benchmark_cagr is not None
        and metrics.excess_cagr is not None
        and metrics.annualized_tracking_error is not None
        and metrics.information_ratio is not None
        and excess_interval.lower is not None
        and excess_interval.upper is not None
        and information_ratio_interval.lower is not None
        and information_ratio_interval.upper is not None
    )


def _excess_interval_decision(
    interval: BootstrapConfidenceInterval,
) -> tuple[BenchmarkReviewStatus, BenchmarkReviewEvidence]:
    lower = cast(float, interval.lower)
    upper = cast(float, interval.upper)
    if upper <= 0.0:
        status: BenchmarkReviewStatus = "BLOCK"
        code = "EXCESS_RETURN_CI_NON_POSITIVE"
        message = f"Annualized excess-return 95% CI [{lower:.8f}, {upper:.8f}] has upper <= 0."
    elif lower > 0.0:
        status = "PASS"
        code = "EXCESS_RETURN_CI_POSITIVE"
        message = f"Annualized excess-return 95% CI [{lower:.8f}, {upper:.8f}] is above 0."
    else:
        status = "WATCH"
        code = "EXCESS_RETURN_CI_CROSSES_ZERO"
        message = f"Annualized excess-return 95% CI [{lower:.8f}, {upper:.8f}] crosses or touches 0."
    return status, BenchmarkReviewEvidence(code, status, message)


def _review_report(
    *,
    status: BenchmarkReviewStatus,
    sufficient: bool,
    strategy_input: InputSeriesEvidence,
    benchmark_input: InputSeriesEvidence,
    metadata_path: Path,
    metadata_sha256: str | None,
    metadata: ReviewedBenchmarkMetadata,
    identity: BenchmarkIdentity | None,
    configuration: BenchmarkConfiguration,
    evidence: list[BenchmarkReviewEvidence],
    alignment: AlignmentEvidence | None = None,
    metrics: BenchmarkMetrics | None = None,
    annualized_excess_return_ci: BootstrapConfidenceInterval | None = None,
    information_ratio_ci: BootstrapConfidenceInterval | None = None,
) -> BenchmarkReviewReport:
    return BenchmarkReviewReport(
        status=status,
        sufficient=sufficient,
        strategy_input=strategy_input,
        benchmark_input=benchmark_input,
        metadata_path=str(metadata_path.resolve()),
        metadata_sha256=metadata_sha256,
        metadata=metadata,
        identity=identity,
        configuration=configuration,
        alignment=alignment,
        metrics=metrics,
        annualized_excess_return_ci=annualized_excess_return_ci,
        information_ratio_ci=information_ratio_ci,
        evidence=tuple(evidence),
    )


def _try_file_sha256(
    path: Path,
    code_prefix: str,
    evidence: list[BenchmarkReviewEvidence],
) -> str | None:
    if not path.is_file():
        evidence.append(
            BenchmarkReviewEvidence(
                f"{code_prefix}_MISSING",
                "BLOCK",
                f"Required input file is missing: {path}.",
            )
        )
        return None
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise BenchmarkReviewInputError(f"Cannot read input file {path}: {exc}") from exc
    value = digest.hexdigest()
    evidence.append(
        BenchmarkReviewEvidence(
            f"{code_prefix}_SHA256_RECORDED",
            "PASS",
            f"Recorded SHA-256 for {path}.",
        )
    )
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def _non_empty_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    result = value.strip()
    return result or None


def _worst_status(*statuses: BenchmarkStatus) -> BenchmarkReviewStatus:
    severity = {"PASS": 0, "WATCH": 1, "BLOCK": 2}
    return cast(BenchmarkReviewStatus, max(statuses, key=severity.__getitem__))


def _unavailable_metrics() -> dict[str, None]:
    return {
        "strategy_cagr": None,
        "benchmark_cagr": None,
        "excess_cagr": None,
        "annualized_excess_return": None,
        "annualized_tracking_error": None,
        "information_ratio": None,
    }


def _input_markdown(label: str, value: InputSeriesEvidence) -> list[str]:
    return [
        f"- {label} CSV: `{value.path}`",
        f"- {label} SHA-256: `{value.sha256 or 'unavailable'}`",
        f"- {label} coverage: {_date_range(value.start_date, value.end_date)} "
        f"({value.observations} observations)",
    ]


def _date_range(start: str | None, end: str | None) -> str:
    return f"`{start}` to `{end}`" if start and end else "unavailable"


def _markdown_number(value: float | None) -> str:
    return "unavailable" if value is None else f"`{value:.8f}`"


def _markdown_bool(value: bool | None) -> str:
    return "unavailable" if value is None else str(value).lower()


def _interval_markdown(interval: BootstrapConfidenceInterval | None) -> str:
    if interval is None or interval.lower is None or interval.upper is None:
        return "unavailable"
    return f"`[{interval.lower:.8f}, {interval.upper:.8f}]` ({interval.status})"
