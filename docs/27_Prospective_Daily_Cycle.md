# Prospective Daily Cycle

`prospective_daily_cycle` is the operator control plane for one sealed holdout
collection day. It combines continuity, acquisition preflight, explicit
provider execution, attempt journaling, sealed handoff, and post-handoff
continuity without running the candidate or writing an execution cache.

The command is offline by default. It never contacts the provider unless the
operator adds `--execute-acquisition`.

## Default Daily Check

```powershell
.\.venv\Scripts\python.exe examples\run_prospective_daily_cycle.py `
  --packet-dir evidence\trial_registry\guard-v1-20260716 `
  --registry evidence\trial_registry\research_trials.jsonl `
  --quarantine-root data_exports\prospective\guard-v1-20260716 `
  --output-dir results\prospective\guard_v1_20260716\operational_status\daily_cycle
```

This verifies the frozen packet, registry, retained quarantine, provider-attempt
journal, and earliest continuity gap. Before the close it returns `NOT_DUE`.
After the close, a new unresolved date normally returns `ACTION_REQUIRED` with
a READY acquisition preflight and exact next command. Neither state accesses
the network.

When real reviewed calendar evidence exists, pass the pair to every cycle:

```powershell
  --calendar-csv data_exports\calendars\cn_a_share_exchange_calendar.csv `
  --calendar-metadata data_exports\calendars\cn_a_share_exchange_calendar.metadata.json
```

Supplying only one path or invalid evidence is `BLOCK`; it never silently falls
back to weekday mode.

## Explicit Collection

After reviewing the offline action packet, enable exactly the earliest due
date:

```powershell
.\.venv\Scripts\python.exe examples\run_prospective_daily_cycle.py `
  --packet-dir evidence\trial_registry\guard-v1-20260716 `
  --registry evidence\trial_registry\research_trials.jsonl `
  --quarantine-root data_exports\prospective\guard-v1-20260716 `
  --output-dir results\prospective\guard_v1_20260716\operational_status\daily_cycle `
  --execute-acquisition `
  --minimum-success-ratio 0.95 `
  --max-attempts 2 `
  --retry-delay-seconds 1
```

The cycle cannot select a later date while an earlier date is unresolved. A
provider attempt is journaled before any PASS handoff. Only provider coverage
PASS can enter sealed intake, after which continuity is rerun. A successful
end-to-end input returns `COLLECTED`; this is collection success only, never
strategy or promotion PASS.

## Retry Boundary

If the latest provider attempt is `BLOCK`, the next cycle returns
`REVIEW_REQUIRED`, even if `--execute-acquisition` was supplied. Inspect the
immutable attempt report and fix the provider/route issue first. A deliberate
retry requires both flags:

```powershell
  --execute-acquisition --retry-blocked-attempt
```

If provider coverage previously passed but no sealed event exists, automatic
refetch remains prohibited even with retry authorization. Investigate the
handoff artifacts; otherwise a successful provider call could be repeated while
its original data identity is unresolved.

## Statuses

- `NOT_DUE`: no finalized date is due.
- `CURRENT`: all finalized dates are current; no provider call is needed.
- `ACTION_REQUIRED`: earliest due date has a READY preflight, but execution was
  not explicitly requested.
- `REVIEW_REQUIRED`: a prior attempt needs operator investigation or explicit
  retry authorization.
- `COLLECTED`: provider PASS was journaled, sealed handoff succeeded, and the
  target date is no longer unresolved.
- `MARKET_CLOSED`: reviewed calendar proves no collection is due.
- `BLOCK`: packet, calendar, journal, interval, provider coverage, handoff, or
  post-handoff continuity failed.

## Outputs And Safety

The cycle output directory is required to be disjoint from the quarantine root.
It contains:

- `prospective_daily_cycle.json/md`;
- `collection_before/`;
- optional `acquisition/`;
- optional `collection_after/`.

Actual provider attempts and sealed inputs remain under the trial quarantine
root. Cycle reports contain structured checks and hashes but no raw CSV bytes,
candidate returns, positions, or orders. Every status keeps broker access,
execution-cache writes, holdout analysis, paper promotion, and live trading
disabled.
