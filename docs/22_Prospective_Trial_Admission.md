# Prospective Trial Admission

`prospective_trial_admission` is the dynamic, read-only gate between a frozen
trial registration and its one permitted terminal holdout analysis. It does
not change the frozen packet. Evidence that legitimately arrives later is
recomputed from its source files every time.

## Why This Is Separate From the Frozen Packet

The packet records the evidence available when the protocol is registered.
Its `execution_allowed` field is therefore an immutable historical snapshot.
For `guard-v1-20260716` that snapshot is `false` because source provenance and
external market evidence were incomplete at registration. Editing the packet
afterward would invalidate the registration.

The admission report instead recomputes:

- frozen packet, code, config, development-prefix, and registry integrity;
- exactly one preregistration and zero terminal result events;
- current cache source QA, retained evidence hashes, logical identity, import
  batches, and row lineage;
- terminal-cache isolation: either a genuinely distinct future cache registered
  before the holdout, or an exact post-holdout materialization artifact;
- frozen data-source route versus current cache provenance;
- the raw CSI 800 total-return and PIT membership files and their metadata;
- complete cache coverage through the registered test end;
- the A-share market date in `Asia/Shanghai`.

All checks must pass. The holdout remains sealed through the registered test
end date, so terminal analysis is considered only on a later Shanghai date.

## Two Different Permissions

`collection_ready=true` means only that the frozen protocol, registry, source
QA, route identity, and lineage are valid enough for append-only daily data
collection. It does not permit candidate-result inspection.

`terminal_analysis_allowed=true` additionally requires reviewed market
evidence, complete frozen-window cache coverage, a date after the registered
test end, and no prior result event. It permits one frozen research analysis.
It never permits paper, micro-live, live trading, or broker access.

Use that permission only through
`docs/29_Prospective_Terminal_Analysis.md`. The terminal runner claims the trial
before calculation and appends one hash-bound result after publication.

## Run For guard_v1

```powershell
.\.venv\Scripts\python.exe examples\run_prospective_trial_admission.py `
  --packet-dir evidence\trial_registry\guard-v1-20260716 `
  --registry evidence\trial_registry\research_trials.jsonl `
  --benchmark-csv data_exports\indices\csi800_total_return.csv `
  --benchmark-metadata data_exports\indices\csi800_total_return.metadata.json `
  --membership-csv data_exports\indices\csi800_pit_membership.csv `
  --membership-metadata data_exports\indices\csi800_pit_membership.metadata.json `
  --materialization-artifact results\prospective\guard_v1_20260716\terminal_materialization\prospective_execution_cache_materialization.json `
  --minimum-members-per-snapshot 700 `
  --output-dir results\prospective\guard_v1_20260716\operational_status\admission
```

The command writes:

- `prospective_trial_admission.json/md`
- `prospective_trial_packet_verification.json/md`
- `promotion_metadata_check.json/md`
- `market_evidence_preflight.json/md`

For the actual `guard-v1-20260716` packet, `--materialization-artifact` is
required after the holdout because its immutable execution config points to
the same file as the frozen development cache. See
`docs/28_Prospective_Execution_Cache_Materialization.md`. Appending holdout rows
to that original cache is always `BLOCK`, even when coverage and source QA look
complete.

It exits nonzero on `BLOCK`. There is deliberately no `--as-of` override: a
caller cannot future-date the clock to open the holdout early.

## Current guard_v1 State

On `2026-07-17` Shanghai time the report is `BLOCK/HOLDOUT_SEALED`:

- packet integrity and registry binding: `PASS`;
- one preregistration and zero results: `PASS`;
- configured `akshare` route versus cache provenance: `PASS`;
- source QA and complete import lineage: `BLOCK`;
- reviewed CSI 800 total-return and PIT membership evidence: `BLOCK`;
- verified isolated execution cache and coverage through `2026-10-16`: `BLOCK`;
- terminal holdout analysis: prohibited through `2026-10-16`.

The next legitimate operation is evidence acquisition and append-only,
provenance-aware data collection. It is not strategy execution.

While source QA remains incomplete, exact finalized daily exports may be
retained only in the unreviewed sealed quarantine described in
`docs/23_Sealed_Holdout_Intake.md`. Quarantine retention is deliberately not
the same as `collection_ready=true` and cannot write the execution cache.
