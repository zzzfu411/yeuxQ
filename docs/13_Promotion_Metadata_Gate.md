# Promotion Metadata Gate

This note defines the data-version evidence required before a cache can support
first-million, paper-promotion, or micro-live-readiness review. It is not a
profit claim and not live-trading permission.

## Required Cache Metadata

Promotion-facing caches must close the metadata chain, not only store OHLCV
bars. SQLite `research_metadata` must include:

- `csv_dataset_fingerprint`
- `data_source_qa_status=PASS`
- `data_source_csv_qa_status=PASS`
- `data_source_qa_checklist_path`
- `data_source_qa_checklist_sha256`
- `data_source_qa_answers_path`
- `data_source_qa_answers_sha256`

If strict source evidence manifest mode is enabled, it must also include:

- `data_source_qa_evidence_manifest_path`
- `data_source_qa_evidence_manifest_sha256`

The files referenced by metadata paths must still exist, and their current
sha256 must match the recorded digest.

## Guard Behavior

`current_data_cache`, `capital_goal_status`, and `run_manifest` treat missing
metadata as BLOCK evidence. A cache with recent bars but no CSV fingerprint or
source QA provenance is still not promotion-ready.

`micro_live_readiness` also requires `run_manifest.json` to be present, to use
non-demo data, to record both `in_sample_end` and `out_sample_start`, and to
carry the same CSV/source-QA provenance metadata. Human approval snapshots lock
`run_manifest.json` together with the other readiness artifacts, so changing the
data lineage after approval returns the gate to BLOCK until approval is renewed.
`capital_scaling_plan` applies the same run-manifest provenance check before
any capital increase can pass.

To inspect this layer without running the whole first-million pipeline:

```powershell
.\.venv\Scripts\python.exe examples\check_promotion_metadata.py --config config\research_recent.yaml --output-dir results\import\promotion_metadata
```

The command writes `promotion_metadata_check.json/md`. It is read-only: it does
not create tables, patch metadata, import bars, approve a strategy, or connect
to a broker. A `BLOCK` result exits with code `2`, matching the other gate and
preflight commands.

`examples/run_first_million_pipeline.py` also writes the same
`promotion_metadata_check.json/md` into its report directory after guarded
offline intake, so the daily brief and pipeline stage list show whether the
cache metadata is promotion-admissible.

`examples/import_research_csv.py --validate` can write
`csv_dataset_fingerprint`, but it does not by itself prove source QA. For
first-million or paper-promotion workflows, prefer guarded offline intake so
CSV validation, source QA, cache metadata, and run manifest describe the same
data batch.

## Expected Chain

For broker/vendor CSV:

```text
raw vendor CSV -> normalized bars.csv -> csv_validation dataset_fingerprint
-> guarded offline intake -> SQLite research_metadata -> run_manifest
```

For TongDaXin `.day` data:

```text
tdx_day_export.json -> CSV contract -> csv_validation dataset_fingerprint
-> guarded offline intake -> SQLite research_metadata -> run_manifest
```

TDX metadata must also preserve `tdx_day_export_report`,
`tdx_day_export_sha256`, source directory, symbol/row counts, and date bounds.

## Operator Rule

If readiness or goal status reports a cache metadata blocker, rerun guarded
offline intake with real source QA evidence instead of launching strategy
experiments. Do not patch metadata by hand to bypass source QA.
