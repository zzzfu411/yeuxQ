# Prospective Collection Status

`prospective_collection_status` is the read-only continuity control plane for
the sealed holdout. It prevents a missing earlier date from being silently
ignored while later dates are collected.

## Evidence Boundary

The status report verifies:

- the frozen packet, code/config bindings, development prefix, and trial
  registry;
- exactly one preregistration and zero terminal result events;
- the quarantine JSONL hash chain;
- the provider-attempt JSONL hash chain and every referenced immutable attempt
  report;
- every retained daily CSV and hash-bound acquisition manifest referenced by
  that chain;
- the dates already finalized under the `15:30 Asia/Shanghai` close buffer.

The current development cache's trading calendar ends at `2026-07-14` and does
not cover the prospective test. Until reviewed exchange-calendar evidence is
attached, the report uses Monday-Friday dates only as conservative **candidate
weekdays**. It never labels them verified trading sessions.

Reviewed evidence is supplied as a pair with `--calendar-csv` and
`--calendar-metadata`. The pair is checked by the strict, read-only preflight in
`docs/26_Reviewed_Exchange_Calendar.md` for complete natural-day coverage,
concrete provenance, review timestamps, and exact CSV SHA-256 binding. Supplying
only one path, an unreadable file, invalid content, insufficient coverage, or a
hash mismatch is `BLOCK`.

## Status Semantics

- `NOT_DUE`: the first or next candidate weekday has not reached its close
  buffer.
- `BLOCK`: a finalized candidate weekday is unresolved, retained evidence is
  missing/changed, supplied calendar evidence is invalid, the ledger is
  invalid, or packet/registry integrity fails.
- `WATCH`: all finalized candidate weekdays are retained, but reviewed exchange
  calendar evidence is still missing.
- `PASS`: the reviewed calendar passes through the latest finalized date and
  every finalized reviewed open session has retained quarantine evidence.

A weekday exchange holiday may therefore appear as unresolved. That is
intentional fail-closed behavior: it must eventually be resolved by reviewed
market-closure evidence rather than silently skipped.

With a calendar PASS, continuity treats rows differently:

- `is_open=1`: a finalized session requires retained quarantine evidence. If
  absent, it is `DUE_UNRESOLVED` or `OVERDUE_UNRESOLVED` and the report blocks.
- `is_open=0`: the timeline records `REVIEWED_MARKET_CLOSED`; no daily bar is
  due and no empty or synthetic acquisition file may be created.

Closed dates are accepted only from the reviewed, hash-bound pair. They are not
inferred from missing bars, provider errors, weekends, or operator judgment. A
retained bar event on a date the reviewed calendar marks closed is unexpected
evidence and blocks continuity.

The current report schema is v2. Each timeline row also contains provider
`attempt_count`, latest attempt status/time, and successful/requested symbol
coverage. These fields distinguish:

- no provider call yet;
- a provider attempt that was `BLOCK` below required coverage;
- provider coverage `PASS` followed by a missing sealed collection event;
- a fully retained quarantine date.

The first case points to the normal collection command. A coverage `BLOCK`
points to its immutable attempt report before retry. A provider `PASS` without
sealed retention points to handoff investigation before refetching. Attempt
counts and coverage are execution evidence only; they are never candidate
returns, factor quality, or promotion evidence.

Any attempt-chain/report tampering, attempt outside the frozen test interval,
or provider attempt on a date later proven `REVIEWED_MARKET_CLOSED` is a
deterministic `BLOCK`.

## Run

```powershell
.\.venv\Scripts\python.exe examples\run_prospective_collection_status.py `
  --packet-dir evidence\trial_registry\guard-v1-20260716 `
  --registry evidence\trial_registry\research_trials.jsonl `
  --quarantine-root data_exports\prospective\guard-v1-20260716 `
  --calendar-csv data_exports\calendars\cn_a_share_exchange_calendar.csv `
  --calendar-metadata data_exports\calendars\cn_a_share_exchange_calendar.metadata.json `
  --output-dir results\prospective\guard_v1_20260716\operational_status\collection
```

Use those calendar paths only after the actual reviewed files exist. Omitting
both options keeps the conservative weekday model and cannot produce formal
`PASS`; supplying only one option or pointing either option at a missing file
is `BLOCK` once calendar coverage is due for a finalized test date. Before the
first test date reaches the close buffer, the report is `NOT_DUE` and does not
preflight a complete pair. The required range is the trial start through the
latest finalized date within the test interval, so evidence that passed
yesterday may block after a newly finalized date until reviewed coverage is
extended.

Outputs:

- `prospective_collection_status.json`
- `prospective_collection_status.md`
- `prospective_collection_timeline.csv`

The report includes the earliest unresolved date and a ready-to-run
`run_prospective_daily_acquisition.py` command. It has no network or broker
access and never writes an execution cache.

It also exposes `attempt_journal_status`, `attempt_event_count`,
`attempt_journal_tail_hash`, and `latest_attempt`. The timeline CSV adds the
same date-level attempt summary without raw bars or candidate results.

`docs/27_Prospective_Daily_Cycle.md` wraps this read-only status into the normal
operator workflow. It does not weaken continuity: only the earliest unresolved
date can become an acquisition target.

## Current Sequence

For `guard-v1-20260716`, the first candidate date is `2026-07-17`:

- before 15:30 Shanghai time: `NOT_DUE`, no missing-date failure;
- after 15:30 with no retained CSV: `BLOCK`, earliest unresolved is
  `2026-07-17`;
- after successful quarantine retention: `WATCH` until reviewed calendar
  evidence is available;
- on Monday morning: Friday remains current and Monday is still future;
- after Monday close with reviewed `is_open=1` and no bars: Monday becomes the
  earliest unresolved date and later collection must not silently hide it;
- after Monday close with reviewed `is_open=0`: Monday is
  `REVIEWED_MARKET_CLOSED`, requires no bar file, and continuity can `PASS` if
  every other finalized open session is retained.

None of these statuses permits holdout analysis, promotion, paper, micro-live,
live trading, or broker orders.
