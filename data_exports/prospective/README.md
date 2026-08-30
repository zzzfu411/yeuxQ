# Prospective Daily-Bar Quarantine

Real prospective daily CSV files and the resulting quarantine ledger belong
under a trial-specific directory here, for example:

```text
data_exports/prospective/guard-v1-20260716/
```

Everything below this directory except this README is ignored by Git. Do not
commit licensed vendor rows, source references, or retained evidence.

The intake command accepts exactly one finalized market date per CSV. Required
columns are:

```csv
symbol,date,open,high,low,close,volume,amount
```

Do not place templates or invented rows here. The intake retains exact bytes
as `unreviewed_quarantine`; it does not write the execution cache, pass source
QA, open the holdout, or authorize trading. See
`docs/23_Sealed_Holdout_Intake.md`.

The post-close AKShare collector can produce and quarantine the canonical CSV
without writing the frozen execution cache. Run its no-network preflight first;
see `docs/24_Prospective_Daily_Acquisition.md`.

Use `docs/25_Prospective_Collection_Status.md` to audit retained dates and the
earliest unresolved candidate weekday before collecting a later date.
Attach a real hash-bound exchange calendar as described in
`docs/26_Reviewed_Exchange_Calendar.md` before treating weekdays as confirmed
open sessions or reviewed market closures. Missing calendar evidence remains a
real evidence gap; never infer a holiday from absent bars.

Pass that pair directly to `run_prospective_daily_acquisition.py`. A reviewed
closed date is a zero-write `MARKET_CLOSED` no-op; do not create an empty daily
CSV. The collector rechecks both calendar hashes and the preflight-bound
quarantine root before any provider call or retained evidence write.

Actual provider calls are audited separately in
`prospective_acquisition_attempts.jsonl`, including coverage failures that never
enter sealed intake. Each event hash-binds an immutable structured report under
`acquisition_attempts/`; neither artifact contains raw bar values or candidate
results. Run `examples/verify_prospective_acquisition_attempts.py` before
investigating or retrying a failed collection.

Use `examples/run_prospective_daily_cycle.py` as the normal daily entry point.
It is offline by default, chooses only the earliest unresolved date, and
requires explicit execution plus separate authorization for a retry after a
BLOCK attempt. Store its control-plane reports under `results/`, not inside this
quarantine directory.
