"""Multiple-testing diagnostics for strategy research.

The routines in this module are deliberately self-contained. They require the
inputs needed by the statistical formulas and never substitute sample moments,
trial counts, or an annualization frequency.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
from itertools import combinations
import json
from math import comb, erf, exp, isfinite, log, sqrt
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

DiagnosticStatus = Literal["PASS", "WATCH", "BLOCK"]

_EULER_MASCHERONI = 0.5772156649015329
_SQRT_TWO = sqrt(2.0)


@dataclass(frozen=True, slots=True)
class MultipleTestingEvidence:
    """One auditable reason contributing to a diagnostic decision."""

    code: str
    status: DiagnosticStatus
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "status": self.status, "message": self.message}


@dataclass(frozen=True, slots=True)
class DeflatedSharpeRatioResult:
    """Structured result of a Deflated Sharpe Ratio calculation."""

    status: DiagnosticStatus
    sufficient: bool
    observed_annualized_sharpe: float
    effective_trials: float
    observations: int
    periods_per_year: float
    skewness: float
    excess_kurtosis: float
    expected_maximum_sharpe: float | None
    standard_error: float | None
    dsr_probability: float | None
    pass_probability: float
    watch_probability: float
    minimum_observations: int
    insufficiency_reasons: tuple[str, ...]
    evidence: tuple[MultipleTestingEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": "deflated_sharpe_ratio",
            "status": self.status,
            "sufficient": self.sufficient,
            "observed_annualized_sharpe": self.observed_annualized_sharpe,
            "effective_trials": self.effective_trials,
            "observations": self.observations,
            "periods_per_year": self.periods_per_year,
            "skewness": self.skewness,
            "excess_kurtosis": self.excess_kurtosis,
            "expected_maximum_sharpe": self.expected_maximum_sharpe,
            "standard_error": self.standard_error,
            "dsr_probability": self.dsr_probability,
            "pass_probability": self.pass_probability,
            "watch_probability": self.watch_probability,
            "minimum_observations": self.minimum_observations,
            "insufficiency_reasons": list(self.insufficiency_reasons),
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class CSCVSplitResult:
    """One complementary in-sample/out-of-sample CSCV split."""

    in_sample_partitions: tuple[int, ...]
    out_of_sample_partitions: tuple[int, ...]
    in_sample_winner: str
    in_sample_sharpe: float
    out_of_sample_sharpe: float
    out_of_sample_rank: float
    out_of_sample_relative_rank: float
    out_of_sample_rank_logit: float
    degraded: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "in_sample_partitions": list(self.in_sample_partitions),
            "out_of_sample_partitions": list(self.out_of_sample_partitions),
            "in_sample_winner": self.in_sample_winner,
            "in_sample_sharpe": self.in_sample_sharpe,
            "out_of_sample_sharpe": self.out_of_sample_sharpe,
            "out_of_sample_rank": self.out_of_sample_rank,
            "out_of_sample_relative_rank": self.out_of_sample_relative_rank,
            "out_of_sample_rank_logit": self.out_of_sample_rank_logit,
            "degraded": self.degraded,
        }


@dataclass(frozen=True, slots=True)
class CSCVProbabilityOfBacktestOverfittingResult:
    """Structured CSCV estimate of selection overfitting risk."""

    status: DiagnosticStatus
    sufficient: bool
    observations: int
    trial_count: int
    trial_names: tuple[str, ...]
    partition_count: int
    partition_sizes: tuple[int, ...]
    total_combinations: int
    evaluated_combinations: int
    max_combinations: int | None
    pbo: float | None
    degradation_probability: float | None
    pass_probability: float
    watch_probability: float
    degradation_pass_probability: float
    degradation_watch_probability: float
    minimum_observations_per_partition: int
    rank_logits: tuple[float, ...]
    splits: tuple[CSCVSplitResult, ...]
    insufficiency_reasons: tuple[str, ...]
    evidence: tuple[MultipleTestingEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": "cscv_probability_of_backtest_overfitting",
            "status": self.status,
            "sufficient": self.sufficient,
            "observations": self.observations,
            "trial_count": self.trial_count,
            "trial_names": list(self.trial_names),
            "partition_count": self.partition_count,
            "partition_sizes": list(self.partition_sizes),
            "total_combinations": self.total_combinations,
            "evaluated_combinations": self.evaluated_combinations,
            "max_combinations": self.max_combinations,
            "pbo": self.pbo,
            "degradation_probability": self.degradation_probability,
            "pass_probability": self.pass_probability,
            "watch_probability": self.watch_probability,
            "degradation_pass_probability": self.degradation_pass_probability,
            "degradation_watch_probability": self.degradation_watch_probability,
            "minimum_observations_per_partition": self.minimum_observations_per_partition,
            "rank_logits": list(self.rank_logits),
            "splits": [split.to_dict() for split in self.splits],
            "insufficiency_reasons": list(self.insufficiency_reasons),
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True, slots=True)
class MultipleTestingReport:
    """CSV-backed review combining DSR and CSCV/PBO evidence."""

    status: DiagnosticStatus
    sufficient: bool
    input_csv: str
    input_sha256: str | None
    candidate_columns: tuple[str, ...]
    selected_candidate: str
    observations: int
    observation_start: str | None
    observation_end: str | None
    periods_per_year: float | None
    partition_count: int | None
    max_combinations: int | None
    effective_trials_override: float | None
    effective_trials: float | None
    effective_trials_source: str | None
    selected_annualized_sharpe: float | None
    selected_skewness: float | None
    selected_excess_kurtosis: float | None
    dsr: DeflatedSharpeRatioResult | None
    cscv_pbo: CSCVProbabilityOfBacktestOverfittingResult | None
    insufficiency_reasons: tuple[str, ...]
    evidence: tuple[MultipleTestingEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": "multiple_testing_report",
            "schema_version": 1,
            "evidence_role": "diagnostic_only",
            "can_upgrade_deterministic_gate": False,
            "status": self.status,
            "sufficient": self.sufficient,
            "input": {
                "csv_path": self.input_csv,
                "sha256": self.input_sha256,
                "date_column": "date",
                "candidate_columns": list(self.candidate_columns),
                "observations": self.observations,
                "observation_start": self.observation_start,
                "observation_end": self.observation_end,
            },
            "parameters": {
                "selected_candidate": self.selected_candidate,
                "periods_per_year": self.periods_per_year,
                "partition_count": self.partition_count,
                "max_combinations": self.max_combinations,
                "effective_trials_override": self.effective_trials_override,
                "effective_trials": self.effective_trials,
                "effective_trials_source": self.effective_trials_source,
            },
            "selected_statistics": {
                "annualized_sharpe": self.selected_annualized_sharpe,
                "sample_skewness": self.selected_skewness,
                "sample_excess_kurtosis": self.selected_excess_kurtosis,
            },
            "diagnostics": {
                "deflated_sharpe_ratio": self.dsr.to_dict() if self.dsr else None,
                "cscv_pbo": self.cscv_pbo.to_dict() if self.cscv_pbo else None,
            },
            "insufficiency_reasons": list(self.insufficiency_reasons),
            "evidence": [item.to_dict() for item in self.evidence],
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Multiple-Testing Diagnostics: {self.status}",
            "",
            "- Evidence role: `diagnostic_only`",
            "- Can upgrade deterministic gate: `false`",
            f"- Statistically sufficient: `{str(self.sufficient).lower()}`",
            "",
            "## Input",
            "",
            f"- CSV: `{self.input_csv}`",
            f"- SHA-256: `{self.input_sha256 or 'unavailable'}`",
            f"- Candidate columns: {_markdown_names(self.candidate_columns)}",
            f"- Selected candidate: `{self.selected_candidate or 'missing'}`",
            f"- Observations: {self.observations}",
            f"- Observation range: {_range_label(self.observation_start, self.observation_end)}",
            "",
            "## Parameters",
            "",
            f"- Periods per year: {_markdown_value(self.periods_per_year)}",
            f"- Partition count: {_markdown_value(self.partition_count)}",
            f"- Maximum combinations: {_markdown_value(self.max_combinations)}",
            f"- Effective trials override: {_markdown_value(self.effective_trials_override)}",
            f"- Effective trials used: {_markdown_value(self.effective_trials)}",
            f"- Effective trials source: `{self.effective_trials_source or 'unavailable'}`",
            "",
            "## Selected Statistics",
            "",
            f"- Annualized Sharpe: {_markdown_value(self.selected_annualized_sharpe)}",
            f"- Sample skewness: {_markdown_value(self.selected_skewness)}",
            f"- Sample excess kurtosis: {_markdown_value(self.selected_excess_kurtosis)}",
            "",
            "## Diagnostics",
            "",
        ]
        if self.dsr is None:
            lines.append("- DSR: unavailable")
        else:
            lines.append(
                f"- DSR: `{self.dsr.status}`; probability="
                f"{_markdown_value(self.dsr.dsr_probability)}; expected null maximum Sharpe="
                f"{_markdown_value(self.dsr.expected_maximum_sharpe)}"
            )
        if self.cscv_pbo is None:
            lines.append("- CSCV/PBO: unavailable")
        else:
            lines.append(
                f"- CSCV/PBO: `{self.cscv_pbo.status}`; PBO="
                f"{_markdown_value(self.cscv_pbo.pbo)}; degradation probability="
                f"{_markdown_value(self.cscv_pbo.degradation_probability)}; combinations="
                f"{self.cscv_pbo.evaluated_combinations}/{self.cscv_pbo.total_combinations}"
            )
        lines.extend(["", "## Insufficiency Reasons", ""])
        if self.insufficiency_reasons:
            lines.extend(f"- {reason}" for reason in self.insufficiency_reasons)
        else:
            lines.append("- None.")
        lines.extend(["", "## Evidence", ""])
        lines.extend(f"- `{item.status}` `{item.code}`: {item.message}" for item in self.evidence)
        lines.extend(
            [
                "",
                "This report is a multiple-testing diagnostic. It cannot by itself upgrade, "
                "satisfy, or bypass any deterministic promotion gate.",
                "",
            ]
        )
        return "\n".join(lines)


def build_multiple_testing_report(
    input_csv: str | Path,
    *,
    selected_candidate: str,
    periods_per_year: float,
    partition_count: int,
    max_combinations: int | None = None,
    effective_trials: float | None = None,
) -> MultipleTestingReport:
    """Build a fail-closed multiple-testing report from frozen trial returns."""
    path = Path(input_csv)
    path_label = str(path.resolve())
    reasons: list[str] = []
    input_sha256 = _try_file_sha256(path, reasons)
    annualization = _report_positive_float("periods_per_year", periods_per_year, reasons)
    partitions = _report_partition_count(partition_count, reasons)
    combination_cap = _report_optional_positive_int("max_combinations", max_combinations, reasons)
    override = _report_optional_finite_float("effective_trials", effective_trials, reasons)
    selected_name = str(selected_candidate).strip()
    if not selected_name:
        reasons.append("selected_candidate must be a non-empty trial column name.")

    frame, candidate_columns, observations, observation_start, observation_end = _read_returns_csv(
        path, reasons
    )
    trial_count = len(candidate_columns)
    if trial_count < 2:
        reasons.append(
            f"At least two frozen trial columns are required; found trial_count={trial_count}."
        )
    if selected_name and selected_name not in candidate_columns:
        reasons.append(f"selected_candidate={selected_name!r} is not a trial column.")

    effective_trials_used: float | None = None
    effective_trials_source: str | None = None
    if trial_count:
        if override is None and effective_trials is None:
            effective_trials_used = float(trial_count)
            effective_trials_source = "trial_column_count"
        elif override is not None:
            if override < trial_count:
                reasons.append(
                    f"effective_trials override={override} cannot be below trial_count={trial_count}."
                )
            else:
                effective_trials_used = override
                effective_trials_source = "explicit_conservative_override"

    if partitions is not None:
        minimum_observations = max(30, partitions * 2)
        if observations < minimum_observations:
            reasons.append(
                f"observations={observations} is below the report minimum={minimum_observations} "
                f"for partition_count={partitions}."
            )

    if reasons or frame is None or annualization is None or partitions is None:
        return _blocked_multiple_testing_report(
            input_csv=path_label,
            input_sha256=input_sha256,
            candidate_columns=candidate_columns,
            selected_candidate=selected_name,
            observations=observations,
            observation_start=observation_start,
            observation_end=observation_end,
            periods_per_year=annualization,
            partition_count=partitions,
            max_combinations=combination_cap,
            effective_trials_override=override,
            effective_trials=effective_trials_used,
            effective_trials_source=effective_trials_source,
            reasons=reasons,
        )

    selected_returns = frame[selected_name]
    period_standard_deviation = float(selected_returns.std(ddof=1))
    if not isfinite(period_standard_deviation) or period_standard_deviation <= 0.0:
        reasons.append(
            "Selected-candidate Sharpe, sample skewness, and sample excess kurtosis require "
            "finite returns with positive sample variance."
        )
        return _blocked_multiple_testing_report(
            input_csv=path_label,
            input_sha256=input_sha256,
            candidate_columns=candidate_columns,
            selected_candidate=selected_name,
            observations=observations,
            observation_start=observation_start,
            observation_end=observation_end,
            periods_per_year=annualization,
            partition_count=partitions,
            max_combinations=combination_cap,
            effective_trials_override=override,
            effective_trials=effective_trials_used,
            effective_trials_source=effective_trials_source,
            reasons=reasons,
        )
    selected_statistics = (
        float(selected_returns.mean() / period_standard_deviation * sqrt(annualization)),
        float(selected_returns.skew()),
        float(selected_returns.kurt()),
    )
    if not all(isfinite(value) for value in selected_statistics):
        reasons.append(
            "Selected-candidate Sharpe, sample skewness, and sample excess kurtosis require "
            "finite returns with positive sample variance."
        )
        return _blocked_multiple_testing_report(
            input_csv=path_label,
            input_sha256=input_sha256,
            candidate_columns=candidate_columns,
            selected_candidate=selected_name,
            observations=observations,
            observation_start=observation_start,
            observation_end=observation_end,
            periods_per_year=annualization,
            partition_count=partitions,
            max_combinations=combination_cap,
            effective_trials_override=override,
            effective_trials=effective_trials_used,
            effective_trials_source=effective_trials_source,
            reasons=reasons,
        )

    annualized_sharpe, sample_skewness, sample_excess_kurtosis = selected_statistics
    try:
        dsr = deflated_sharpe_ratio(
            observed_annualized_sharpe=annualized_sharpe,
            effective_trials=effective_trials_used or 0.0,
            observations=observations,
            periods_per_year=annualization,
            skewness=sample_skewness,
            excess_kurtosis=sample_excess_kurtosis,
        )
        cscv_pbo = cscv_probability_of_backtest_overfitting(
            frame,
            partition_count=partitions,
            max_combinations=combination_cap,
        )
    except (ArithmeticError, TypeError, ValueError) as exc:
        reasons.append(f"Multiple-testing calculation failed closed: {exc}")
        return _blocked_multiple_testing_report(
            input_csv=path_label,
            input_sha256=input_sha256,
            candidate_columns=candidate_columns,
            selected_candidate=selected_name,
            observations=observations,
            observation_start=observation_start,
            observation_end=observation_end,
            periods_per_year=annualization,
            partition_count=partitions,
            max_combinations=combination_cap,
            effective_trials_override=override,
            effective_trials=effective_trials_used,
            effective_trials_source=effective_trials_source,
            reasons=reasons,
        )

    reasons.extend(dsr.insufficiency_reasons)
    reasons.extend(cscv_pbo.insufficiency_reasons)
    status = _worst_status(dsr.status, cscv_pbo.status)
    evidence = (
        MultipleTestingEvidence(
            code="MULTIPLE_TESTING_INPUT_VALID",
            status="PASS",
            message=(
                f"Validated {observations} observations across {trial_count} frozen trial columns."
            ),
        ),
        MultipleTestingEvidence(
            code="MULTIPLE_TESTING_EFFECTIVE_TRIALS",
            status="PASS",
            message=(
                f"effective_trials={effective_trials_used} from {effective_trials_source}; "
                f"trial_count={trial_count}."
            ),
        ),
        *dsr.evidence,
        *cscv_pbo.evidence,
    )
    return MultipleTestingReport(
        status=status,
        sufficient=dsr.sufficient and cscv_pbo.sufficient,
        input_csv=path_label,
        input_sha256=input_sha256,
        candidate_columns=candidate_columns,
        selected_candidate=selected_name,
        observations=observations,
        observation_start=observation_start,
        observation_end=observation_end,
        periods_per_year=annualization,
        partition_count=partitions,
        max_combinations=combination_cap,
        effective_trials_override=override,
        effective_trials=effective_trials_used,
        effective_trials_source=effective_trials_source,
        selected_annualized_sharpe=annualized_sharpe,
        selected_skewness=sample_skewness,
        selected_excess_kurtosis=sample_excess_kurtosis,
        dsr=dsr,
        cscv_pbo=cscv_pbo,
        insufficiency_reasons=tuple(reasons),
        evidence=evidence,
    )


def write_multiple_testing_report(
    report: MultipleTestingReport,
    output_dir: str | Path,
) -> Path:
    """Write strict JSON and Markdown multiple-testing report artifacts."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "multiple_testing_report.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    (root / "multiple_testing_report.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _blocked_multiple_testing_report(
    *,
    input_csv: str,
    input_sha256: str | None,
    candidate_columns: tuple[str, ...],
    selected_candidate: str,
    observations: int,
    observation_start: str | None,
    observation_end: str | None,
    periods_per_year: float | None,
    partition_count: int | None,
    max_combinations: int | None,
    effective_trials_override: float | None,
    effective_trials: float | None,
    effective_trials_source: str | None,
    reasons: list[str],
) -> MultipleTestingReport:
    unique_reasons = tuple(dict.fromkeys(reasons))
    evidence = tuple(
        MultipleTestingEvidence(
            code="MULTIPLE_TESTING_INSUFFICIENT",
            status="BLOCK",
            message=reason,
        )
        for reason in unique_reasons
    )
    return MultipleTestingReport(
        status="BLOCK",
        sufficient=False,
        input_csv=input_csv,
        input_sha256=input_sha256,
        candidate_columns=candidate_columns,
        selected_candidate=selected_candidate,
        observations=observations,
        observation_start=observation_start,
        observation_end=observation_end,
        periods_per_year=periods_per_year,
        partition_count=partition_count,
        max_combinations=max_combinations,
        effective_trials_override=effective_trials_override,
        effective_trials=effective_trials,
        effective_trials_source=effective_trials_source,
        selected_annualized_sharpe=None,
        selected_skewness=None,
        selected_excess_kurtosis=None,
        dsr=None,
        cscv_pbo=None,
        insufficiency_reasons=unique_reasons,
        evidence=evidence,
    )


def _try_file_sha256(path: Path, reasons: list[str]) -> str | None:
    if not path.exists():
        reasons.append(f"Input CSV does not exist: {path}.")
        return None
    if not path.is_file():
        reasons.append(f"Input CSV path is not a file: {path}.")
        return None
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        reasons.append(f"Input CSV could not be hashed: {exc}")
        return None
    return digest.hexdigest()


def _read_returns_csv(
    path: Path,
    reasons: list[str],
) -> tuple[pd.DataFrame | None, tuple[str, ...], int, str | None, str | None]:
    if not path.is_file():
        return None, (), 0, None, None
    local_reasons: list[str] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            header = next(csv.reader(handle), None)
        raw = pd.read_csv(path)
    except (OSError, UnicodeError, csv.Error, pd.errors.ParserError) as exc:
        reasons.append(f"Input CSV could not be parsed: {exc}")
        return None, (), 0, None, None

    if not header:
        reasons.append("Input CSV must contain a header row.")
        return None, (), 0, None, None
    candidate_columns = tuple(str(value) for value in header[1:])
    observations = len(raw)
    if header[0] != "date":
        local_reasons.append("The first CSV column must be named exactly 'date'.")
    if len(header) != len(set(header)):
        local_reasons.append("CSV column names must be unique.")
    if any(not name.strip() for name in candidate_columns):
        local_reasons.append("Trial column names must be non-empty.")
    if observations == 0:
        local_reasons.append("Input CSV contains no return observations.")
    if len(raw.columns) != len(header):
        local_reasons.append("CSV header and parsed column counts do not match.")

    parsed_dates: pd.Series | None = None
    observation_start: str | None = None
    observation_end: str | None = None
    if observations and len(raw.columns):
        parsed_dates = pd.to_datetime(raw.iloc[:, 0], errors="coerce")
        if parsed_dates.isna().any():
            local_reasons.append("The date column contains missing or invalid dates.")
        elif parsed_dates.duplicated().any():
            local_reasons.append("The date column must contain unique observations.")
        else:
            observation_start = pd.Timestamp(parsed_dates.min()).date().isoformat()
            observation_end = pd.Timestamp(parsed_dates.max()).date().isoformat()

    numeric_returns: pd.DataFrame | None = None
    if observations and candidate_columns and len(raw.columns) == len(header):
        numeric_returns = raw.iloc[:, 1:].apply(pd.to_numeric, errors="coerce")
        numeric_returns.columns = list(candidate_columns)
        values = numeric_returns.to_numpy(dtype=float)
        if not np.isfinite(values).all():
            local_reasons.append(
                "Trial returns contain missing, non-numeric, or non-finite values."
            )

    reasons.extend(local_reasons)
    if local_reasons or parsed_dates is None or numeric_returns is None:
        return None, candidate_columns, observations, observation_start, observation_end
    numeric_returns.index = pd.DatetimeIndex(parsed_dates)
    return (
        numeric_returns.sort_index(kind="stable"),
        candidate_columns,
        observations,
        observation_start,
        observation_end,
    )


def _report_positive_float(
    name: str,
    value: float,
    reasons: list[str],
) -> float | None:
    try:
        result = _finite_float(name, value)
    except (TypeError, ValueError) as exc:
        reasons.append(str(exc))
        return None
    if result <= 0.0:
        reasons.append(f"{name} must be positive.")
        return None
    return result


def _report_partition_count(value: int, reasons: list[str]) -> int | None:
    try:
        result = _strict_int("partition_count", value)
    except TypeError as exc:
        reasons.append(str(exc))
        return None
    if result < 4 or result % 2:
        reasons.append("partition_count must be an even integer of at least 4.")
        return None
    return result


def _report_optional_positive_int(
    name: str,
    value: int | None,
    reasons: list[str],
) -> int | None:
    if value is None:
        return None
    try:
        result = _strict_int(name, value)
    except TypeError as exc:
        reasons.append(str(exc))
        return None
    if result < 1:
        reasons.append(f"{name} must be positive when provided.")
        return None
    return result


def _report_optional_finite_float(
    name: str,
    value: float | None,
    reasons: list[str],
) -> float | None:
    if value is None:
        return None
    try:
        return _finite_float(name, value)
    except (TypeError, ValueError) as exc:
        reasons.append(str(exc))
        return None


def _markdown_names(names: tuple[str, ...]) -> str:
    return ", ".join(f"`{name}`" for name in names) if names else "None."


def _markdown_value(value: float | int | None) -> str:
    if value is None:
        return "`unavailable`"
    if isinstance(value, int):
        return f"`{value}`"
    return f"`{value:.6g}`"


def _range_label(start: str | None, end: str | None) -> str:
    if start is None or end is None:
        return "`unavailable`"
    return f"`{start}` to `{end}`"


def deflated_sharpe_ratio(
    *,
    observed_annualized_sharpe: float,
    effective_trials: float,
    observations: int,
    periods_per_year: float,
    skewness: float,
    excess_kurtosis: float,
    pass_probability: float = 0.95,
    watch_probability: float = 0.80,
    minimum_observations: int = 30,
) -> DeflatedSharpeRatioResult:
    """Estimate the probability that Sharpe exceeds the multiple-test hurdle.

    ``periods_per_year`` is required because the observed Sharpe is annualized,
    while skewness, excess kurtosis, and ``observations`` describe period
    returns. The expected null maximum uses the Bailey-Lopez de Prado
    approximation, and the Sharpe standard error includes the supplied third
    and fourth moments.
    """
    observed = _finite_float("observed_annualized_sharpe", observed_annualized_sharpe)
    trials = _finite_float("effective_trials", effective_trials)
    annualization = _finite_float("periods_per_year", periods_per_year)
    sample_skewness = _finite_float("skewness", skewness)
    sample_excess_kurtosis = _finite_float("excess_kurtosis", excess_kurtosis)
    sample_size = _strict_int("observations", observations)
    minimum_sample = _strict_int("minimum_observations", minimum_observations)
    _validate_probability_thresholds(pass_probability, watch_probability)

    if trials < 1.0:
        raise ValueError("effective_trials must be at least 1.")
    if annualization <= 0.0:
        raise ValueError("periods_per_year must be positive.")
    if sample_size < 0:
        raise ValueError("observations must be non-negative.")
    if minimum_sample < 2:
        raise ValueError("minimum_observations must be at least 2.")
    if sample_excess_kurtosis < -2.0:
        raise ValueError("excess_kurtosis cannot be less than -2.")

    reasons: list[str] = []
    if sample_size < minimum_sample:
        reasons.append(
            f"observations={sample_size} is below minimum_observations={minimum_sample}."
        )
    if reasons:
        return _insufficient_dsr_result(
            observed=observed,
            trials=trials,
            observations=sample_size,
            periods_per_year=annualization,
            skewness=sample_skewness,
            excess_kurtosis=sample_excess_kurtosis,
            pass_probability=pass_probability,
            watch_probability=watch_probability,
            minimum_observations=minimum_sample,
            reasons=reasons,
        )

    period_sharpe = observed / sqrt(annualization)
    variance_numerator = (
        1.0
        - sample_skewness * period_sharpe
        + ((sample_excess_kurtosis + 2.0) / 4.0) * period_sharpe**2
    )
    if not isfinite(variance_numerator) or variance_numerator <= 0.0:
        reasons.append(
            "The supplied Sharpe, skewness, and excess kurtosis imply a non-positive "
            "Sharpe sampling variance."
        )
        return _insufficient_dsr_result(
            observed=observed,
            trials=trials,
            observations=sample_size,
            periods_per_year=annualization,
            skewness=sample_skewness,
            excess_kurtosis=sample_excess_kurtosis,
            pass_probability=pass_probability,
            watch_probability=watch_probability,
            minimum_observations=minimum_sample,
            reasons=reasons,
        )

    standard_error = sqrt(annualization * variance_numerator / (sample_size - 1))
    expected_maximum = _expected_null_maximum(trials, standard_error)
    dsr_probability = _normal_cdf((observed - expected_maximum) / standard_error)
    status = _higher_probability_status(
        dsr_probability,
        pass_probability=pass_probability,
        watch_probability=watch_probability,
    )
    evidence = (
        MultipleTestingEvidence(
            code="DSR_SAMPLE_SUFFICIENT",
            status="PASS",
            message=(f"observations={sample_size} meets minimum_observations={minimum_sample}."),
        ),
        MultipleTestingEvidence(
            code=f"DSR_PROBABILITY_{status}",
            status=status,
            message=(
                f"DSR probability={dsr_probability:.6f}; PASS requires "
                f">={pass_probability:.6f} and WATCH requires >={watch_probability:.6f}."
            ),
        ),
    )
    return DeflatedSharpeRatioResult(
        status=status,
        sufficient=True,
        observed_annualized_sharpe=observed,
        effective_trials=trials,
        observations=sample_size,
        periods_per_year=annualization,
        skewness=sample_skewness,
        excess_kurtosis=sample_excess_kurtosis,
        expected_maximum_sharpe=expected_maximum,
        standard_error=standard_error,
        dsr_probability=dsr_probability,
        pass_probability=pass_probability,
        watch_probability=watch_probability,
        minimum_observations=minimum_sample,
        insufficiency_reasons=(),
        evidence=evidence,
    )


def cscv_probability_of_backtest_overfitting(
    returns: pd.DataFrame,
    *,
    partition_count: int,
    max_combinations: int | None = None,
    pass_probability: float = 0.20,
    watch_probability: float = 0.50,
    degradation_pass_probability: float = 0.50,
    degradation_watch_probability: float = 0.75,
    minimum_observations_per_partition: int = 2,
) -> CSCVProbabilityOfBacktestOverfittingResult:
    """Estimate CSCV Probability of Backtest Overfitting from trial returns.

    Rows are sorted by date and split into contiguous partitions. For every
    selected half-partition combination, the highest in-sample Sharpe trial is
    evaluated out of sample. PBO is the fraction of selected winners whose
    out-of-sample relative-rank logit is non-positive. Degradation probability
    is the fraction whose out-of-sample Sharpe is below its in-sample Sharpe.
    """
    frame = _validate_returns_frame(returns)
    partitions = _strict_int("partition_count", partition_count)
    minimum_partition_size = _strict_int(
        "minimum_observations_per_partition", minimum_observations_per_partition
    )
    _validate_probability_thresholds(watch_probability, pass_probability)
    _validate_probability_thresholds(
        degradation_watch_probability,
        degradation_pass_probability,
    )
    if partitions < 4 or partitions % 2:
        raise ValueError("partition_count must be an even integer of at least 4.")
    if minimum_partition_size < 2:
        raise ValueError("minimum_observations_per_partition must be at least 2.")
    if max_combinations is not None:
        max_combinations = _strict_int("max_combinations", max_combinations)
        if max_combinations < 1:
            raise ValueError("max_combinations must be positive when provided.")

    observation_count = len(frame)
    trial_names = tuple(str(column) for column in frame.columns)
    half = partitions // 2
    total_combinations = comb(partitions, half)
    partition_positions = tuple(
        np.asarray(chunk, dtype=np.int64)
        for chunk in np.array_split(np.arange(observation_count, dtype=np.int64), partitions)
    )
    partition_sizes = tuple(int(len(chunk)) for chunk in partition_positions)
    reasons: list[str] = []
    if min(partition_sizes, default=0) < minimum_partition_size:
        reasons.append(
            f"Each of {partitions} partitions requires at least "
            f"{minimum_partition_size} observations; partition sizes are {partition_sizes}."
        )
    if reasons:
        return _insufficient_cscv_result(
            observations=observation_count,
            trial_names=trial_names,
            partition_count=partitions,
            partition_sizes=partition_sizes,
            total_combinations=total_combinations,
            max_combinations=max_combinations,
            pass_probability=pass_probability,
            watch_probability=watch_probability,
            degradation_pass_probability=degradation_pass_probability,
            degradation_watch_probability=degradation_watch_probability,
            minimum_observations_per_partition=minimum_partition_size,
            reasons=reasons,
        )

    split_combinations = _selected_half_combinations(
        partitions,
        half,
        total_combinations=total_combinations,
        max_combinations=max_combinations,
    )
    values = frame.to_numpy(dtype=float, copy=True)
    all_partition_ids = set(range(partitions))
    split_results: list[CSCVSplitResult] = []
    for in_sample_partitions in split_combinations:
        out_of_sample_partitions = tuple(sorted(all_partition_ids.difference(in_sample_partitions)))
        in_sample_positions = np.concatenate(
            [partition_positions[index] for index in in_sample_partitions]
        )
        out_of_sample_positions = np.concatenate(
            [partition_positions[index] for index in out_of_sample_partitions]
        )
        in_sample_scores = _sharpe_scores(values[in_sample_positions])
        out_of_sample_scores = _sharpe_scores(values[out_of_sample_positions])
        if not np.isfinite(in_sample_scores).all() or not np.isfinite(out_of_sample_scores).all():
            reasons.append(
                "At least one CSCV half-sample has zero return variance, so Sharpe ranking "
                "is undefined."
            )
            return _insufficient_cscv_result(
                observations=observation_count,
                trial_names=trial_names,
                partition_count=partitions,
                partition_sizes=partition_sizes,
                total_combinations=total_combinations,
                max_combinations=max_combinations,
                pass_probability=pass_probability,
                watch_probability=watch_probability,
                degradation_pass_probability=degradation_pass_probability,
                degradation_watch_probability=degradation_watch_probability,
                minimum_observations_per_partition=minimum_partition_size,
                reasons=reasons,
            )
        winner_index = int(np.argmax(in_sample_scores))
        out_of_sample_rank = _average_rank(out_of_sample_scores, winner_index)
        relative_rank = out_of_sample_rank / (len(trial_names) + 1.0)
        rank_logit = log(relative_rank / (1.0 - relative_rank))
        in_sample_score = float(in_sample_scores[winner_index])
        out_of_sample_score = float(out_of_sample_scores[winner_index])
        split_results.append(
            CSCVSplitResult(
                in_sample_partitions=in_sample_partitions,
                out_of_sample_partitions=out_of_sample_partitions,
                in_sample_winner=trial_names[winner_index],
                in_sample_sharpe=in_sample_score,
                out_of_sample_sharpe=out_of_sample_score,
                out_of_sample_rank=out_of_sample_rank,
                out_of_sample_relative_rank=relative_rank,
                out_of_sample_rank_logit=rank_logit,
                degraded=out_of_sample_score < in_sample_score,
            )
        )

    rank_logits = tuple(split.out_of_sample_rank_logit for split in split_results)
    pbo = sum(value <= 0.0 for value in rank_logits) / len(rank_logits)
    degradation_probability = sum(split.degraded for split in split_results) / len(split_results)
    pbo_status = _lower_probability_status(
        pbo,
        pass_probability=pass_probability,
        watch_probability=watch_probability,
    )
    degradation_status = _lower_probability_status(
        degradation_probability,
        pass_probability=degradation_pass_probability,
        watch_probability=degradation_watch_probability,
    )
    cap_status: DiagnosticStatus = (
        "WATCH"
        if max_combinations is not None and max_combinations < total_combinations
        else "PASS"
    )
    status = _worst_status(pbo_status, degradation_status, cap_status)
    evidence = (
        MultipleTestingEvidence(
            code=f"CSCV_PBO_{pbo_status}",
            status=pbo_status,
            message=(
                f"PBO={pbo:.6f}; PASS requires <={pass_probability:.6f} and WATCH "
                f"requires <={watch_probability:.6f}."
            ),
        ),
        MultipleTestingEvidence(
            code=f"CSCV_DEGRADATION_{degradation_status}",
            status=degradation_status,
            message=(
                f"degradation_probability={degradation_probability:.6f}; PASS requires "
                f"<={degradation_pass_probability:.6f} and WATCH requires "
                f"<={degradation_watch_probability:.6f}."
            ),
        ),
        MultipleTestingEvidence(
            code="CSCV_COMBINATIONS_CAPPED" if cap_status == "WATCH" else "CSCV_COMBINATIONS_ALL",
            status=cap_status,
            message=(
                f"Evaluated {len(split_results)} of {total_combinations} deterministic "
                "half-partition combinations."
            ),
        ),
    )
    return CSCVProbabilityOfBacktestOverfittingResult(
        status=status,
        sufficient=True,
        observations=observation_count,
        trial_count=len(trial_names),
        trial_names=trial_names,
        partition_count=partitions,
        partition_sizes=partition_sizes,
        total_combinations=total_combinations,
        evaluated_combinations=len(split_results),
        max_combinations=max_combinations,
        pbo=float(pbo),
        degradation_probability=float(degradation_probability),
        pass_probability=pass_probability,
        watch_probability=watch_probability,
        degradation_pass_probability=degradation_pass_probability,
        degradation_watch_probability=degradation_watch_probability,
        minimum_observations_per_partition=minimum_partition_size,
        rank_logits=rank_logits,
        splits=tuple(split_results),
        insufficiency_reasons=(),
        evidence=evidence,
    )


def _insufficient_dsr_result(
    *,
    observed: float,
    trials: float,
    observations: int,
    periods_per_year: float,
    skewness: float,
    excess_kurtosis: float,
    pass_probability: float,
    watch_probability: float,
    minimum_observations: int,
    reasons: list[str],
) -> DeflatedSharpeRatioResult:
    evidence = tuple(
        MultipleTestingEvidence(code="DSR_INSUFFICIENT", status="BLOCK", message=reason)
        for reason in reasons
    )
    return DeflatedSharpeRatioResult(
        status="BLOCK",
        sufficient=False,
        observed_annualized_sharpe=observed,
        effective_trials=trials,
        observations=observations,
        periods_per_year=periods_per_year,
        skewness=skewness,
        excess_kurtosis=excess_kurtosis,
        expected_maximum_sharpe=None,
        standard_error=None,
        dsr_probability=None,
        pass_probability=pass_probability,
        watch_probability=watch_probability,
        minimum_observations=minimum_observations,
        insufficiency_reasons=tuple(reasons),
        evidence=evidence,
    )


def _insufficient_cscv_result(
    *,
    observations: int,
    trial_names: tuple[str, ...],
    partition_count: int,
    partition_sizes: tuple[int, ...],
    total_combinations: int,
    max_combinations: int | None,
    pass_probability: float,
    watch_probability: float,
    degradation_pass_probability: float,
    degradation_watch_probability: float,
    minimum_observations_per_partition: int,
    reasons: list[str],
) -> CSCVProbabilityOfBacktestOverfittingResult:
    evidence = tuple(
        MultipleTestingEvidence(code="CSCV_INSUFFICIENT", status="BLOCK", message=reason)
        for reason in reasons
    )
    return CSCVProbabilityOfBacktestOverfittingResult(
        status="BLOCK",
        sufficient=False,
        observations=observations,
        trial_count=len(trial_names),
        trial_names=trial_names,
        partition_count=partition_count,
        partition_sizes=partition_sizes,
        total_combinations=total_combinations,
        evaluated_combinations=0,
        max_combinations=max_combinations,
        pbo=None,
        degradation_probability=None,
        pass_probability=pass_probability,
        watch_probability=watch_probability,
        degradation_pass_probability=degradation_pass_probability,
        degradation_watch_probability=degradation_watch_probability,
        minimum_observations_per_partition=minimum_observations_per_partition,
        rank_logits=(),
        splits=(),
        insufficiency_reasons=tuple(reasons),
        evidence=evidence,
    )


def _validate_returns_frame(returns: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(returns, pd.DataFrame):
        raise TypeError("returns must be a pandas DataFrame.")
    if not isinstance(returns.index, pd.DatetimeIndex):
        raise ValueError("returns must have a DatetimeIndex.")
    if returns.index.has_duplicates:
        raise ValueError("returns index must contain unique dates.")
    if returns.columns.has_duplicates:
        raise ValueError("returns columns must be unique trial names.")
    if returns.shape[1] < 2:
        raise ValueError("CSCV requires returns for at least two trials.")
    if returns.shape[0] == 0:
        raise ValueError("returns must contain at least one observation.")
    if any(not pd.api.types.is_numeric_dtype(dtype) for dtype in returns.dtypes):
        raise ValueError("returns must contain only numeric trial columns.")
    frame = returns.sort_index(kind="stable").astype(float)
    if not np.isfinite(frame.to_numpy()).all():
        raise ValueError("returns must contain only finite values and no missing data.")
    return frame


def _selected_half_combinations(
    partition_count: int,
    half: int,
    *,
    total_combinations: int,
    max_combinations: int | None,
) -> tuple[tuple[int, ...], ...]:
    if max_combinations is None or max_combinations >= total_combinations:
        return tuple(combinations(range(partition_count), half))
    if max_combinations == 1:
        selected_ranks = (total_combinations // 2,)
    else:
        selected_ranks = tuple(
            index * (total_combinations - 1) // (max_combinations - 1)
            for index in range(max_combinations)
        )
    return tuple(_combination_at_rank(partition_count, half, rank) for rank in selected_ranks)


def _combination_at_rank(item_count: int, selection_count: int, rank: int) -> tuple[int, ...]:
    """Return a zero-based lexicographic combination without enumerating predecessors."""
    selected: list[int] = []
    candidate = 0
    remaining_rank = rank
    for slot in range(selection_count):
        slots_after = selection_count - slot - 1
        maximum_candidate = item_count - slots_after
        while candidate < maximum_candidate:
            following_count = comb(item_count - candidate - 1, slots_after)
            if remaining_rank < following_count:
                selected.append(candidate)
                candidate += 1
                break
            remaining_rank -= following_count
            candidate += 1
    return tuple(selected)


def _sharpe_scores(values: np.ndarray) -> np.ndarray:
    means = np.mean(values, axis=0)
    standard_deviations = np.std(values, axis=0, ddof=1)
    scores = np.full_like(means, np.nan, dtype=float)
    varying = np.ptp(values, axis=0) > 0.0
    scores[varying] = means[varying] / standard_deviations[varying]
    return scores


def _average_rank(values: np.ndarray, selected_index: int) -> float:
    """Return an average ascending rank, where one is the worst performance."""
    selected_value = values[selected_index]
    below = int(np.count_nonzero(values < selected_value))
    equal = int(np.count_nonzero(values == selected_value))
    return 1.0 + below + (equal - 1.0) / 2.0


def _expected_null_maximum(effective_trials: float, standard_error: float) -> float:
    if effective_trials == 1.0:
        return 0.0
    first_quantile = _normal_ppf(1.0 - 1.0 / effective_trials)
    second_quantile = _normal_ppf(1.0 - 1.0 / (effective_trials * exp(1.0)))
    return standard_error * (
        (1.0 - _EULER_MASCHERONI) * first_quantile + _EULER_MASCHERONI * second_quantile
    )


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + erf(value / _SQRT_TWO))


def _normal_ppf(probability: float) -> float:
    """Acklam's inverse-normal approximation, accurate to about 1e-9."""
    if not 0.0 < probability < 1.0:
        raise ValueError("normal quantile probability must be strictly between 0 and 1.")
    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    )
    lower = 0.02425
    upper = 1.0 - lower
    if probability < lower:
        q = sqrt(-2.0 * log(probability))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    if probability <= upper:
        q = probability - 0.5
        r = q * q
        return (
            (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
            * q
            / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
        )
    q = sqrt(-2.0 * log(1.0 - probability))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
        (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
    )


def _higher_probability_status(
    probability: float,
    *,
    pass_probability: float,
    watch_probability: float,
) -> DiagnosticStatus:
    if probability >= pass_probability:
        return "PASS"
    if probability >= watch_probability:
        return "WATCH"
    return "BLOCK"


def _lower_probability_status(
    probability: float,
    *,
    pass_probability: float,
    watch_probability: float,
) -> DiagnosticStatus:
    if probability <= pass_probability:
        return "PASS"
    if probability <= watch_probability:
        return "WATCH"
    return "BLOCK"


def _worst_status(*statuses: DiagnosticStatus) -> DiagnosticStatus:
    severity = {"PASS": 0, "WATCH": 1, "BLOCK": 2}
    return max(statuses, key=severity.__getitem__)


def _validate_probability_thresholds(
    pass_probability: float,
    watch_probability: float,
) -> None:
    if not isfinite(pass_probability) or not isfinite(watch_probability):
        raise ValueError("probability thresholds must be finite.")
    if not 0.0 <= watch_probability <= pass_probability <= 1.0:
        raise ValueError("probability thresholds must satisfy 0 <= WATCH <= PASS <= 1.")


def _finite_float(name: str, value: float) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{name} must be a finite number.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be a finite number.") from exc
    if not isfinite(result):
        raise ValueError(f"{name} must be finite.")
    return result


def _strict_int(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise TypeError(f"{name} must be an integer.")
    return int(value)
