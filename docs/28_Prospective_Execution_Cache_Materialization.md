# Prospective Execution Cache Materialization

`prospective_execution_cache_materialization` is the only supported bridge
from sealed daily collection to the one permitted terminal research run when a
trial registered the same SQLite file as both its development and execution
cache. It never edits that frozen file.

For `guard-v1-20260716`, the holdout is sealed through `2026-10-16`. Before the
Shanghai market date is later than that date, the command returns `BLOCK`,
does not parse sealed bar rows, and writes no output or claim.

## Required Evidence

All inputs are recomputed from their source files:

- frozen packet, code bindings, development prefix, and unique preregistration;
- zero terminal result events;
- frozen development cache with no post-cutoff bars and the exact registered
  logical prefix; existing lineage must verify, while a registration-time
  legacy absence is recorded explicitly and rebuilt only in the new cache;
- independently retained source-QA checklist, answers, strict evidence manifest,
  and attachments covering the complete train-through-test interval;
- reviewed A-share exchange calendar with exact natural-day coverage;
- complete sealed ledger and immutable retained CSV bytes for every reviewed
  open session, with no rows on reviewed closed dates;
- provider-attempt journal with exactly one final `PASS` bound to each retained
  CSV; prior `BLOCK` attempts remain allowed and auditable;
- reviewed CSI 800 total-return benchmark and PIT membership through test end.

Source QA is attached to the newly built cache. It must not be backfilled into
the frozen development cache. Calendar and PIT membership are also imported
into the new cache so the frozen index-universe configuration has reviewed
inputs.

## One-Time Protocol

After every preflight passes, the tool exclusively creates
`prospective_execution_cache_materialization.claim.json` in the trial
quarantine. The claim is bound to the trial, replay-manifest hash, output path,
and timestamp. Its existence blocks every later materialization, even when a
different output directory is requested.

The claim is intentionally not auto-deleted after an interrupted build. An
interruption requires forensic review; automatic retry would weaken the
single-use contract.

The cache is rebuilt in a staging directory from:

1. canonical frozen development bars through `development_cutoff`;
2. ledger-ordered sealed inputs for each reviewed open session;
3. reviewed exchange-calendar sessions;
4. reviewed CSI 800 PIT membership snapshots.

Each bar batch receives deterministic lineage IDs and source hashes. The
source development cache SHA-256 is checked before and after replay. Publication
uses an absent output directory and never replaces an existing artifact.

The actual `guard-v1-20260716` development cache was registered without import
batch/row lineage. This is reported as
`LEGACY_FROZEN_PREFIX_WITHOUT_LINEAGE`, not silently upgraded. Its packet-bound
logical fingerprint and physical SHA-256 identify the source prefix; the new
cache then records a provenance batch for that exact prefix. A partially
populated, stale, or contradictory lineage state is `BLOCK`.

## Post-Holdout Command

Do not run this command before `2026-10-17` Shanghai time:

```powershell
.\.venv\Scripts\python.exe examples\run_prospective_execution_cache_materialization.py `
  --packet-dir evidence\trial_registry\guard-v1-20260716 `
  --registry evidence\trial_registry\research_trials.jsonl `
  --quarantine-root data_exports\prospective\guard-v1-20260716 `
  --source-qa-checklist data_exports\data_source_qa.json `
  --source-qa-answers data_exports\data_source_qa_answers.json `
  --source-qa-evidence-manifest data_exports\source_qa_evidence_manifest.json `
  --calendar-csv data_exports\calendars\cn_a_share_calendar.csv `
  --calendar-metadata data_exports\calendars\cn_a_share_calendar.metadata.json `
  --benchmark-csv data_exports\indices\csi800_total_return.csv `
  --benchmark-metadata data_exports\indices\csi800_total_return.metadata.json `
  --membership-csv data_exports\indices\csi800_pit_membership.csv `
  --membership-metadata data_exports\indices\csi800_pit_membership.metadata.json `
  --minimum-members-per-snapshot 700 `
  --output-dir results\prospective\guard_v1_20260716\terminal_materialization
```

On success, the output directory contains:

- `prospective_execution_cache.db`;
- `prospective_execution_cache_materialization.json`;
- `prospective_execution_cache_materialization.md`.

The JSON binds the registered prefix fingerprint, source cache SHA-256,
ordered collection and attempt event hashes, every input CSV hash, source-QA,
calendar and market-evidence hashes, replay batches, output cache SHA-256,
logical fingerprint, coverage, and the one-time claim.

## Verify And Admit

Reverify without writing the cache:

```powershell
.\.venv\Scripts\python.exe examples\verify_prospective_execution_cache_materialization.py `
  --artifact results\prospective\guard_v1_20260716\terminal_materialization\prospective_execution_cache_materialization.json `
  --packet-dir evidence\trial_registry\guard-v1-20260716 `
  --registry evidence\trial_registry\research_trials.jsonl `
  --output-dir results\prospective\guard_v1_20260716\operational_status\materialization_verification
```

Then pass the exact artifact to admission:

```powershell
.\.venv\Scripts\python.exe examples\run_prospective_trial_admission.py `
  --packet-dir evidence\trial_registry\guard-v1-20260716 `
  --registry evidence\trial_registry\research_trials.jsonl `
  --benchmark-csv data_exports\indices\csi800_total_return.csv `
  --benchmark-metadata data_exports\indices\csi800_total_return.metadata.json `
  --membership-csv data_exports\indices\csi800_pit_membership.csv `
  --membership-metadata data_exports\indices\csi800_pit_membership.metadata.json `
  --materialization-artifact results\prospective\guard_v1_20260716\terminal_materialization\prospective_execution_cache_materialization.json `
  --output-dir results\prospective\guard_v1_20260716\operational_status\admission
```

Materialization and admission remain research-only. They do not run the
candidate, append a terminal result, approve paper/micro-live use, or connect
to a broker.

After admission `PASS`, the only supported result workflow is the one-time
runner and post-result verifier in `docs/29_Prospective_Terminal_Analysis.md`.
