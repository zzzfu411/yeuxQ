# Prospective Daily Acquisition

`prospective_daily_acquisition` automates the post-close input to the sealed
holdout quarantine. It fetches only the symbols present in the frozen
development prefix, generates one deterministic canonical CSV, and delegates
retention to `sealed_holdout_intake`.

It is a collection tool, not a strategy runner.

## Deterministic Boundaries

Before any network call, preflight verifies:

- the prospective packet, frozen code/config, development prefix, and trial
  registry;
- exactly one preregistration and zero terminal result events;
- a reviewed calendar date inside the registered test interval when a calendar
  pair is supplied, otherwise a conservative weekday;
- an atomic calendar CSV/metadata pair, strict preflight, target-date row, and
  exact evidence hashes;
- the `15:30 Asia/Shanghai` close buffer;
- the symbol set read through SQLite `mode=ro` from the development cache at
  the frozen cutoff;
- the symbol count recorded in the packet and a deterministic symbol-list
  fingerprint;
- the frozen price-adjustment setting;
- the existing quarantine ledger and retained bytes.
- every prior provider-attempt event, hash-chain link, and referenced immutable
  attempt report.

If any check blocks, `fetch_allowed=false` and AKShare is not called. There is
no caller-controlled clock override.

The daily-acquisition CLI accepts the same reviewed calendar CSV and metadata
used by the continuity report. Both arguments must be supplied together. A
missing, unreadable, malformed, incomplete, or hash-mismatched supplied pair is
`BLOCK`; it never falls back to weekday mode. Omitting both arguments preserves
the conservative weekday behavior, which is not proof that the exchange opened.

A reviewed `is_open=0` date returns `MARKET_CLOSED` with
`fetch_allowed=false` and `network_access=false`. The CLI prints the in-memory
decision and writes no report, bar file, manifest, or ledger entry into the
quarantine root. A retained event on a reviewed closed date is an inconsistency
and becomes `BLOCK`, not `ALREADY_RETAINED`.

For `READY` sessions, the run and handoff stages revalidate the calendar CSV
and metadata hashes and require the exact quarantine root bound by preflight
before creating a directory or calling the provider. Editing either evidence
file or changing `output_dir` after preflight fails closed.

## Network Collection

The default fetch path creates an `AkshareFeed` with `persist=False` and no
storage handle. It requests one symbol and one date at a time. No SQLite file
is created by collection, and the frozen development/execution cache is never
passed to the feed or written.

Each symbol is retried up to the configured attempt count. Returned frames must
contain exactly one row for the requested symbol/date and satisfy the canonical
OHLCVA contract. The default minimum successful-symbol ratio is `95%`.
Acquisition below that threshold is `BLOCK` and cannot enter quarantine.
It is still a real provider attempt and is recorded in the append-only attempt
journal before the CLI exits.

The deterministic CSV is sorted by `(symbol, date)`, uses a fixed header and
stable float formatting, and is SHA-256 bound to an immutable acquisition
manifest. Provider routes and per-symbol failures are retained in the report.

AKShare identity, routes, and timestamps remain `NOT_EVALUATED` source
declarations. Acquisition PASS cannot substitute for reviewed source QA,
licensed benchmark data, PIT membership, or human approval.

## Premarket Preflight

This command performs no network requests:

```powershell
.\.venv\Scripts\python.exe examples\run_prospective_daily_acquisition.py `
  --packet-dir evidence\trial_registry\guard-v1-20260716 `
  --registry evidence\trial_registry\research_trials.jsonl `
  --market-date 2026-07-17 `
  --calendar-csv data_exports\calendars\cn_a_share_exchange_calendar.csv `
  --calendar-metadata data_exports\calendars\cn_a_share_exchange_calendar.metadata.json `
  --minimum-success-ratio 0.95 `
  --output-dir data_exports\prospective\guard-v1-20260716 `
  --preflight-only
```

Before `15:30 Asia/Shanghai`, a reviewed open session is `BLOCK` with
`POST_CLOSE_TIME=BLOCK` and `fetch_allowed=false`. A valid reviewed closed date
is the zero-write `MARKET_CLOSED` no-op even when no close wait is required.

## Post-Close Collection

After the requested date is finalized and continuity identifies it as an open,
unresolved session:

```powershell
.\.venv\Scripts\python.exe examples\run_prospective_daily_acquisition.py `
  --packet-dir evidence\trial_registry\guard-v1-20260716 `
  --registry evidence\trial_registry\research_trials.jsonl `
  --market-date 2026-07-17 `
  --calendar-csv data_exports\calendars\cn_a_share_exchange_calendar.csv `
  --calendar-metadata data_exports\calendars\cn_a_share_exchange_calendar.metadata.json `
  --minimum-success-ratio 0.95 `
  --max-attempts 2 `
  --retry-delay-seconds 1 `
  --output-dir data_exports\prospective\guard-v1-20260716
```

On a full successful handoff, the output includes:

- `prospective_daily_acquisition.json/md`;
- `acquisition_inputs/<date>_<hash>.csv`;
- `acquisition_reports/<date>_<hash>.json/md`;
- `prospective_acquisition_attempts.jsonl`;
- `acquisition_attempts/<date>_<report-hash>.json`;
- the sealed input, collection ledger, and intake reports described in
  `docs/23_Sealed_Holdout_Intake.md`.

## Provider Attempt Journal

Every completed provider call is journaled whether its frozen-universe coverage
is `PASS` or `BLOCK`. The JSONL event stores counts, routes, failure count,
calendar hashes, frozen-universe fingerprint, report hash, and safety flags. It
does not store CSV bytes, OHLCVA rows, candidate returns, positions, or orders.
The referenced immutable report contains the structured acquisition review and
per-symbol failure reasons, but still excludes raw bar values.

The event chain uses canonical JSON, monotonically increasing sequence numbers,
`previous_hash`, `event_hash`, file locking, flush, and `fsync`. Before a new
provider request, preflight verifies the complete chain and every referenced
report. Tampering therefore blocks before network access rather than after a
new attempt has already occurred.

Verify the journal independently with:

```powershell
.\.venv\Scripts\python.exe examples\verify_prospective_acquisition_attempts.py `
  --output-dir data_exports\prospective\guard-v1-20260716
```

`READY` preflight, pre-close `BLOCK`, `ALREADY_RETAINED`, and
`MARKET_CLOSED` do not create attempt events because no provider attempt
occurred. A valid `MARKET_CLOSED` remains a complete zero-write no-op.

For normal daily operation, use the default-offline orchestrator in
`docs/27_Prospective_Daily_Cycle.md`. It always selects the earliest continuity
gap and requires explicit execution and retry authorization before provider
access.

Re-running a retained date returns `ALREADY_RETAINED` and does not call the
provider or replace evidence. Candidate analysis remains prohibited through
`2026-10-16` regardless of collection status.

The reviewed calendar contract intentionally requires a complete natural-day
interval containing at least one open session. A one-row, closed-only file is
not sufficient evidence; provide the surrounding reviewed interval instead of
creating a synthetic open row.

Run the cross-day continuity report in
`docs/25_Prospective_Collection_Status.md` before each collection. It exposes
the earliest unresolved reviewed open session, or a conservative candidate
weekday where reviewed coverage is not yet available, so a later date cannot
hide a gap. Missing or invalid calendar files never justify skipping a date.
