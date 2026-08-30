# Prospective Terminal Analysis

`prospective_terminal_analysis` is the single-use terminal research runner for
a frozen prospective trial. It can run only after dynamic admission accepts an
exact post-holdout materialization. It does not select a candidate, modify a
parameter, contact a provider, submit an order, approve paper trading, or
authorize live use.

For `guard-v1-20260716`, the command remains prohibited through `2026-10-16`.

## Frozen Execution

The runner recomputes admission and verifies that:

- the packet, preregistration, code bindings, candidate snapshot, dates, costs,
  risk limits, and materialized cache still match;
- exactly zero terminal results exist before execution;
- the only derived-config change is `data.cache_path`, replacing the packet's
  development-cache path with the artifact-authorized materialized cache;
- the terminal output directory and global terminal claim are unused.

It then exclusively creates
`prospective_terminal_analysis.claim.json` in the trial quarantine. This claim
is never automatically deleted, including after an interrupted run. A second
analysis is prohibited.

The candidate runs only over the frozen `test.start..test.end` interval. The
same frozen signals/costs are also evaluated at CNY 100,000 because small-capital
lot and minimum-commission feasibility was preregistered. The runner produces:

- the full primary research report and run manifest;
- terminal-window data audit;
- CNY 100,000 execution stress summary;
- CSI 800 total-return analysis with fixed 5-day moving blocks, 1,000 bootstrap
  samples, and random seed 0;
- a deterministic `PASS/WATCH/BLOCK` conclusion;
- one terminal artifact and one registry result event.

A completed run has artifact `status=PASS`, meaning execution and evidence
publication completed. Strategy efficacy is the separate `decision` field. A
completed trial may therefore correctly be `status=PASS, decision=BLOCK`.

## Decision Contract

`BLOCK` is retained when any of these conditions holds:

- terminal data audit is not `PASS`;
- primary or CNY 100,000 drawdown exceeds the frozen risk limit;
- CNY 100,000 reject rate is at least 50%;
- fresh-holdout total return is non-positive;
- formal benchmark analysis is `BLOCK`;
- benchmark excess CAGR is non-positive.

`WATCH` means point estimates are positive but the benchmark-relative interval
is not decisive, benchmark evidence is `WATCH`, or primary reject rate is at
least 20%. `PASS` requires all frozen efficacy, risk, execution, benchmark, and
data-audit checks to pass.

This decision is research evidence only. It cannot upgrade paper, micro-live,
live-trading, approval, or broker gates.

## Run Once

Run only after materialization verification and admission both pass:

```powershell
.\.venv\Scripts\python.exe examples\run_prospective_terminal_analysis.py `
  --packet-dir evidence\trial_registry\guard-v1-20260716 `
  --registry evidence\trial_registry\research_trials.jsonl `
  --materialization-artifact results\prospective\guard_v1_20260716\terminal_materialization\prospective_execution_cache_materialization.json `
  --benchmark-csv data_exports\indices\csi800_total_return.csv `
  --benchmark-metadata data_exports\indices\csi800_total_return.metadata.json `
  --membership-csv data_exports\indices\csi800_pit_membership.csv `
  --membership-metadata data_exports\indices\csi800_pit_membership.metadata.json `
  --minimum-members-per-snapshot 700 `
  --output-dir results\prospective\guard_v1_20260716\terminal_result
```

The result event binds terminal/materialization/cache/report hashes and the
frozen test boundaries. The runner writes
`prospective_terminal_result_receipt.json` only after the registry append
succeeds.

## Verify Without Rerun

```powershell
.\.venv\Scripts\python.exe examples\verify_prospective_terminal_analysis.py `
  --artifact results\prospective\guard_v1_20260716\terminal_result\prospective_terminal_analysis.json `
  --packet-dir evidence\trial_registry\guard-v1-20260716 `
  --registry evidence\trial_registry\research_trials.jsonl `
  --materialization-artifact results\prospective\guard_v1_20260716\terminal_materialization\prospective_execution_cache_materialization.json `
  --output-dir results\prospective\guard_v1_20260716\operational_status\terminal_verification
```

The verifier never recalculates candidate performance. It verifies evidence
file hashes, recomputes the deterministic decision, and requires exactly one
matching result event and receipt. Missing, changed, duplicated, or replaced
evidence is `BLOCK`.

## Current Missing Evidence

The real trial still lacks reviewed source QA, reviewed exchange calendar, CSI
800 total-return/PIT files, and completed sealed observations. In addition,
terminal data-audit `PASS` requires reviewed A-share execution context such as
ST/delist and suspension coverage. These inputs must be real and retained; the
system must not manufacture them to make the terminal decision pass.
