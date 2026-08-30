# Sealed Holdout Intake

`sealed_holdout_intake` preserves finalized daily-bar exports during a frozen
prospective test without revealing candidate results. It exists because the
current `guard_v1` execution cache lacks promotion-safe source QA and historical
lineage, while prospective raw observations still need to be retained from day
one.

## Safety Model

A successful intake performs only two durable actions:

1. Copy the exact UTF-8 CSV bytes into an ignored quarantine directory.
2. Append one canonical JSON event to a SHA-256-linked collection ledger.

It does not:

- write or patch the execution SQLite cache;
- calculate returns, factors, holdings, rankings, or candidate metrics;
- claim that a vendor, license, adjustment, or reviewer has been approved;
- upgrade source QA, market evidence, promotion, paper, or live gates;
- contact a broker or create orders.

Every retained event has `evidence_role=unreviewed_quarantine`. Source QA and a
guarded replay are separate future operations.

## Input Contract

The input must be an actual finalized UTF-8 CSV containing exactly one market
date and these columns:

```csv
symbol,date,open,high,low,close,volume,amount
```

The validator requires:

- six-digit symbols and unique `(symbol, date)` keys;
- one valid weekday inside the frozen test interval;
- finite, positive OHLC prices with consistent high/low ordering;
- non-negative volume and amount;
- `raw`, `qfq`, or `hfq` matching the frozen configuration;
- a timezone-aware source export timestamp no later than the intake runtime;
- same-day retention only after `15:30 Asia/Shanghai`;
- a verified frozen packet, trial registry, and zero terminal result events.

The command has no caller-supplied clock override.

## Run After Market Close

Use only real source values and a real exported file:

```powershell
.\.venv\Scripts\python.exe examples\run_sealed_holdout_intake.py `
  --packet-dir evidence\trial_registry\guard-v1-20260716 `
  --registry evidence\trial_registry\research_trials.jsonl `
  --daily-bars-csv "<real-finalized-daily-bars.csv>" `
  --source-vendor "<actual-vendor-or-terminal>" `
  --source-reference "<retained-export-id-or-path>" `
  --source-exported-at "2026-07-17T15:30:00+08:00" `
  --price-adjustment qfq `
  --output-dir data_exports\prospective\guard-v1-20260716
```

On success the directory contains:

- `sealed_inputs/<date>_<raw-hash-prefix>.csv`: exact retained bytes;
- `sealed_holdout_collection.jsonl`: append-only collection chain;
- `sealed_holdout_intake.json/md`: latest intake report;
- `intake_reports/<date>_<event-hash-prefix>.json/md`: immutable report copies.

The same date and identical bytes are idempotent. The same date with different
bytes is `BLOCK`; evidence is never silently replaced. A malformed, truncated,
noncanonical, or hash-mismatched ledger also blocks every further append.

## Later Guarded Replay

Quarantine retention is intentionally weaker than admissible data provenance.
Before replaying any row into an execution cache:

1. Complete real source QA and retain its reviewed attachments and hashes.
2. Verify usage rights and the declared price adjustment.
3. Replay exact quarantined bytes through a provenance-aware importer.
4. Recompute the registered prefix through `2026-07-14`; any change is BLOCK.
5. Re-run dynamic prospective admission.

The production replay protocol is now specified in
`docs/28_Prospective_Execution_Cache_Materialization.md`. It rebuilds a new
cache, imports reviewed calendar/PIT membership, creates a one-time claim, and
binds every replay input. Direct append to the packet's frozen development
cache is prohibited.

Even after replay, candidate-result inspection stays prohibited through
`2026-10-16`. Terminal analysis is a separate, one-time post-holdout action.

For the guarded AKShare post-close collector that produces this canonical CSV
without persisting into the frozen cache, see
`docs/24_Prospective_Daily_Acquisition.md`.
