# Multiple-Testing Diagnostics

## Purpose and boundary

`multiple_testing_report.json` and `multiple_testing_report.md` quantify selection risk after
several frozen strategy trials have been compared. The review combines:

- Deflated Sharpe Ratio (DSR) for the frozen selected candidate.
- CSCV-style Probability of Backtest Overfitting (PBO) across every trial column.
- The probability that the in-sample winner's Sharpe degrades out of sample.

This artifact has `evidence_role=diagnostic_only` and
`can_upgrade_deterministic_gate=false`. It cannot, by itself, upgrade, satisfy, or bypass a
deterministic promotion gate. It supplements provenance, selection-safe walk-forward, independent
holdout, robustness, execution, and readiness evidence; it does not replace any of them.

## Frozen CSV contract

The input is one UTF-8 CSV whose columns are:

```text
date,trial_a,trial_b,...
2025-01-02,0.0012,-0.0004,...
```

- The first column must be named exactly `date` and contain unique valid dates.
- Every remaining column is one frozen trial's daily return series.
- At least two uniquely named trial columns are required.
- Every trial must use the same dates, with no missing, non-numeric, `NaN`, or infinite values.
- The selected candidate must already be frozen and must match one trial column exactly.

The report records the resolved input path, byte-level SHA-256, candidate columns, observation
count and date range. These fields tie the diagnostics to one immutable CSV payload.

## Parameters

- `selected-candidate`: frozen trial column used for annualized Sharpe and return moments.
- `periods-per-year`: explicit annualization frequency; there is no fabricated daily default.
- `partition-count`: even CSCV partition count of at least four.
- `max-combinations`: optional deterministic cap. Omit it to evaluate all half partitions.
- `effective-trials`: optional conservative DSR override. It must be at least the CSV trial count.

Without an override, DSR uses the number of trial columns as `effective_trials`. An override may
increase the multiple-testing penalty but may never reduce it below the observed trial count.

## Calculations

For the selected daily return column, the review computes sample standard deviation, annualized
Sharpe, pandas sample skewness, and unbiased sample excess kurtosis. It passes those measured values
to DSR together with the observation count, explicit annualization frequency, and effective trial
count.

CSCV sorts observations by date, divides them into contiguous partitions, selects the highest
in-sample non-annualized Sharpe for each deterministic half-partition combination, and measures its
out-of-sample relative-rank logit. PBO is the share of logits at or below zero. Degradation
probability is the share of selected winners whose out-of-sample Sharpe is below in-sample Sharpe.

The report status is the worst of the DSR and CSCV/PBO statuses. A deterministic combination cap is
also visible in CSCV evidence and prevents the CSCV result from receiving `PASS`.

## Fail-closed behavior

No diagnostic number is invented when the input cannot support it. The report is `BLOCK`, keeps
affected statistics and diagnostics as `null`, and records explicit `insufficiency_reasons` for:

- fewer than two trial columns;
- fewer than `max(30, 2 * partition_count)` observations;
- missing, non-numeric, `NaN`, or infinite returns;
- invalid or duplicate dates and malformed CSV structure;
- a missing selected candidate or an optimistic effective-trial override;
- zero variance that makes a selected-candidate or CSCV half-sample Sharpe undefined;
- invalid annualization, partition, or combination parameters.

The CLI still writes both reports for these data failures so the blocked decision remains auditable.

## Command

```powershell
.\.venv\Scripts\python.exe examples\run_multiple_testing_review.py `
  --input-csv results\frozen_trial_returns.csv `
  --output-dir results\multiple_testing_review `
  --selected-candidate stable_best `
  --periods-per-year 252 `
  --partition-count 8 `
  --max-combinations 35 `
  --effective-trials 12
```

Omit `--max-combinations` to evaluate all combinations. Omit `--effective-trials` to use the trial
column count. Neither omission fabricates sample data or return moments.
