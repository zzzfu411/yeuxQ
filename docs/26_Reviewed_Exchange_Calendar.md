# Reviewed Exchange Calendar

`exchange_calendar_preflight` validates local A-share open/closed evidence. It
does not download a calendar, infer closures, contact a broker, alter the input
files, or authorize holdout analysis or trading.

The evidence is one real CSV plus one real metadata JSON document. Both belong
under `data_exports/calendars/`, are intentionally ignored by Git, and must be
retained outside Git according to the evidence-retention policy. Never create a
placeholder, sample, empty, copied, or guessed pair to make this gate pass.

## CSV Contract

The CSV must be UTF-8, optionally with a BOM. Its header must be exactly
`date,is_open` in that order, with no extra columns, and every row must have
exactly two fields. Each row must also satisfy:

- `date` is a unique `YYYY-MM-DD` natural date;
- `is_open` is exactly `1` for an open A-share session or `0` for a reviewed
  market-closed date;
- every natural day from `coverage_start_date` through `coverage_end_date`
  appears exactly once, including weekends and exchange holidays;
- Saturday and Sunday are never marked open;
- the covered interval contains at least one open session.

Input row order is not evidence: the preflight sorts parsed sessions by date.
Missing dates are never inferred as closures. Do not add dummy bars for closed
dates, and do not edit the CSV after its final bytes have been reviewed and
hashed.

## Metadata Contract

Metadata must be a UTF-8 JSON object with no duplicate keys or non-finite
numbers. These identity fields must match exactly:

| Field | Required value |
| --- | --- |
| `artifact_type` | `reviewed_exchange_calendar` |
| `schema_version` | JSON number `1` |
| `exchange_scope` | `CN_A_SHARE` |
| `timezone` | `Asia/Shanghai` |
| `date_column` | `date` |
| `is_open_column` | `is_open` |

The object must also contain:

- `coverage_start_date` and `coverage_end_date`: valid ascending dates that
  equal the CSV's complete natural-day interval and span the requested range;
- `source_vendor` and `source_dataset`: concrete source identities;
- `source_exported_at`: a real timezone-aware export timestamp;
- `reviewed_by` and `reviewed_at`: the accountable reviewer and a real
  timezone-aware review timestamp;
- `file_sha256`: the 64-hex SHA-256 of the exact CSV bytes.

Empty values, recognized placeholder values such as `TBD`, `unknown`, or
`missing`, and values beginning with an angle bracket block. Timestamps must satisfy
`source_exported_at <= reviewed_at <= preflight evaluation time`, and the
declared coverage end cannot be later than the source export date. The metadata
file itself is also hashed into the report, but its digest does not replace the
required CSV hash binding.

## Standalone Preflight

After the real pair has been placed in the dropzone, validate it locally:

```powershell
.\.venv\Scripts\python.exe examples\run_exchange_calendar_preflight.py `
  --calendar-csv data_exports\calendars\cn_a_share_exchange_calendar.csv `
  --metadata data_exports\calendars\cn_a_share_exchange_calendar.metadata.json `
  --required-start-date 2026-07-17 `
  --required-end-date 2026-07-20 `
  --output-dir results\prospective\guard_v1_20260716\operational_status\calendar
```

Set the required range to the dates the downstream decision actually needs.
The command writes `exchange_calendar_preflight.json` and
`exchange_calendar_preflight.md` with the input hashes and row counts, and exits
`0` only for `PASS`. A validation BLOCK or report-write failure exits `2`. The
output directory must not overwrite either evidence input.

Missing/unreadable files, malformed JSON/CSV, duplicate dates or keys, an
invalid `is_open` value, a missing natural day, weekend-open data, inadequate
coverage, placeholder provenance, bad/future timestamps, or a SHA-256 mismatch
all produce `BLOCK`. Do not repair a BLOCK by inventing closure rows or review
metadata; obtain corrected source evidence and repeat the review.

## Continuity Use

Pass the same reviewed pair to the read-only continuity report:

```powershell
.\.venv\Scripts\python.exe examples\run_prospective_collection_status.py `
  --packet-dir evidence\trial_registry\guard-v1-20260716 `
  --registry evidence\trial_registry\research_trials.jsonl `
  --quarantine-root data_exports\prospective\guard-v1-20260716 `
  --calendar-csv data_exports\calendars\cn_a_share_exchange_calendar.csv `
  --calendar-metadata data_exports\calendars\cn_a_share_exchange_calendar.metadata.json `
  --output-dir results\prospective\guard_v1_20260716\operational_status\collection
```

The continuity check requires coverage from the trial start through its latest
finalized date within the test interval. A reviewed open date (`is_open=1`) is
due after the 15:30 `Asia/Shanghai` close buffer and requires retained
quarantine evidence. A reviewed closed date (`is_open=0`) appears as
`REVIEWED_MARKET_CLOSED` and is not due. This distinction comes only from a
strict calendar PASS.

If both calendar options are omitted, continuity remains on conservative
Monday-Friday candidates and can be at most `WATCH` when current. If only one
option is supplied, the input pair check is `BLOCK`. Once a test date is
finalized and calendar coverage is due, either file being missing or the pair
failing preflight makes continuity `BLOCK`. Before the first test date reaches
the close buffer, continuity is `NOT_DUE` and does not yet preflight a complete
pair. A calendar PASS covers continuity only through the latest finalized test
date; future dates beyond declared coverage remain unreviewed candidates until
real reviewed evidence is extended.

Calendar PASS is not source QA, benchmark or PIT-membership approval, strategy
evidence, permission to open the sealed holdout, or paper/live authorization.

## Daily Acquisition Use

The post-close collector accepts the same evidence pair:

```powershell
.\.venv\Scripts\python.exe examples\run_prospective_daily_acquisition.py `
  --packet-dir evidence\trial_registry\guard-v1-20260716 `
  --registry evidence\trial_registry\research_trials.jsonl `
  --market-date 2026-07-17 `
  --calendar-csv data_exports\calendars\cn_a_share_exchange_calendar.csv `
  --calendar-metadata data_exports\calendars\cn_a_share_exchange_calendar.metadata.json `
  --minimum-success-ratio 0.95 `
  --output-dir data_exports\prospective\guard-v1-20260716
```

An open row can become `READY` only after all existing packet, registry,
close-time, frozen-universe, and ledger gates pass. A closed row becomes the
zero-network, zero-quarantine-write `MARKET_CLOSED` no-op. Supplied calendar
evidence is hash-bound to preflight and checked again before acquisition and
handoff; the quarantine root is bound in the same way. Omitting both calendar
options retains conservative weekday behavior, while supplying only one or an
invalid pair is `BLOCK`.
