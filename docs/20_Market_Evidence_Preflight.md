# Market Evidence Preflight

`market_evidence_preflight` is a strict, local-only admission check for two retained external
market-data artifacts:

1. A reviewed CSI 800 total-return benchmark CSV.
2. A reviewed, effective-dated CSI 800 point-in-time universe membership CSV.

The preflight reads the supplied files and writes its own JSON and Markdown report. It never
modifies an input, downloads data, calls a vendor, contacts a broker, or authorizes trading.
Every missing, malformed, contradictory, or inadequately reviewed input produces `BLOCK`.
Each input is hashed again after parsing; a file that changes during the preflight is blocked.

## Required coverage

The caller must provide `required_start_date` and `required_end_date` as `YYYY-MM-DD`. Both
metadata contracts must declare a `coverage_start_date` and `coverage_end_date` that span that
closed range.

The benchmark's observed dates must also span its entire declared range. Membership is modeled
as effective-dated snapshots: it must contain at least two distinct effective dates, an effective
snapshot on or before the required start, and no effective date after the declared end. The
reviewed membership metadata attests how long the final effective snapshot remains applicable.
A one-date export is treated as a current snapshot and cannot pass, even if its metadata claims
that it is PIT history.

Each snapshot must contain at least 700 distinct members by default. This catches truncated or
sample exports that carry the CSI 800 label but cannot represent the index. The threshold can be
changed with `--minimum-members-per-snapshot` only when the caller has a documented reason; a
smaller threshold weakens the evidence contract and must not be used for formal CSI 800 review.

## Benchmark CSV and metadata

The default benchmark columns are `date,value`. Dates must be unique, valid `YYYY-MM-DD` values.
Values must be finite. For `series_kind: "equity"`, values must be positive; for
`series_kind: "returns"`, values must be at least `-1.0`.

The metadata is UTF-8 JSON with no duplicate keys. It extends the existing reviewed benchmark
contract with explicit coverage:

```json
{
  "artifact_type": "reviewed_benchmark_series",
  "schema_version": 1,
  "symbol": "000906.SH",
  "name": "CSI 800 Total Return",
  "total_return": true,
  "series_kind": "equity",
  "coverage_start_date": "2020-01-01",
  "coverage_end_date": "2025-12-31",
  "source_vendor": "licensed-vendor",
  "source_exported_at": "2026-07-15T09:30:00+08:00",
  "reviewed_by": "reviewer-name",
  "reviewed_at": "2026-07-15T10:00:00+08:00",
  "file_sha256": "<sha256-of-exact-benchmark-csv-bytes>"
}
```

`total_return` must be the boolean `true`. The normalized `symbol` must be `000906`; common
forms such as `000906.SH` are accepted. `file_sha256` must be the exact 64-character SHA-256 of
the retained CSV. Source and reviewer fields must be non-placeholder values. Both timestamps
must be ISO-8601 timestamps with UTC offsets, and review cannot precede export.
Neither the declared coverage end nor any observed CSV date may be later than
the source export date.

## Membership CSV and metadata

The default membership columns are:

```csv
index_code,effective_date,symbol
000906,2020-01-02,000001
000906,2020-01-02,600001
000906,2020-06-15,000001
000906,2020-06-15,600002
```

Every `effective_date` must be a valid `YYYY-MM-DD` date. Every row must identify CSI 800 and
have a non-empty symbol. The normalized primary key is
`(index_code, effective_date, symbol)`; duplicate keys are blocked. Repeated effective dates for
different symbols are expected because each date represents a membership snapshot.

Membership metadata is a separate structured, reviewed, hash-bound contract:

```json
{
  "artifact_type": "reviewed_pit_universe_membership",
  "schema_version": 1,
  "index_code": "000906",
  "point_in_time": true,
  "snapshot_mode": "point_in_time_history",
  "effective_date_column": "effective_date",
  "symbol_column": "symbol",
  "index_code_column": "index_code",
  "coverage_start_date": "2020-01-01",
  "coverage_end_date": "2025-12-31",
  "source_vendor": "licensed-vendor",
  "source_dataset": "CSI 800 historical constituents",
  "source_exported_at": "2026-07-15T09:30:00+08:00",
  "reviewed_by": "reviewer-name",
  "reviewed_at": "2026-07-15T10:00:00+08:00",
  "file_sha256": "<sha256-of-exact-membership-csv-bytes>"
}
```

`point_in_time` must be the boolean `true`, and `snapshot_mode` must be exactly
`point_in_time_history`. Labels such as `current_snapshot`, a false PIT flag, missing source
dataset identity, missing reviewer provenance, and a hash mismatch all block admission. Declared
column names must match the columns selected for the run.

## Run the CLI

```powershell
python examples/run_market_evidence_preflight.py `
  --benchmark-csv evidence/csi800_total_return.csv `
  --benchmark-metadata evidence/csi800_total_return.metadata.json `
  --membership-csv evidence/csi800_pit_membership.csv `
  --membership-metadata evidence/csi800_pit_membership.metadata.json `
  --required-start-date 2020-01-01 `
  --required-end-date 2025-12-31 `
  --minimum-members-per-snapshot 700 `
  --output-dir artifacts/market_evidence_preflight
```

Optional column overrides are available as `--benchmark-date-column`,
`--benchmark-value-column`, `--membership-effective-date-column`,
`--membership-symbol-column`, and `--membership-index-code-column`. Membership metadata must
declare the same selected names.

For both evidence types, a future coverage claim is fail-closed: the declared
coverage end and every observed/effective CSV date must be no later than the
recorded source export date. This prevents a metadata file from claiming
observations that could not yet have existed when the retained export was made.

The CLI always attempts to write:

- `market_evidence_preflight.json`
- `market_evidence_preflight.md`

It exits `0` only on `PASS`. It exits `2` on `BLOCK`, including missing files, malformed JSON or
CSV, hash mismatch, wrong index identity, non-total-return benchmark, non-PIT/current-only
membership, invalid or duplicate dates/keys, insufficient coverage, and missing source/reviewer
provenance. An output filesystem error also exits `2` and is reported on stderr.
The writer refuses an output path that would overwrite any of the four external inputs.

`PASS` means only that these retained external inputs satisfy this admission contract. It is not
a data-quality guarantee beyond the checks listed here and is not a trading or promotion gate.
