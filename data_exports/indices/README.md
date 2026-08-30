# Reviewed Market Evidence Dropzone

Place licensed, retained external market evidence here. All files except this
README are ignored by Git so vendor data and reviewer metadata are not committed
accidentally.

Required files for `guard-v1-20260716`:

- `csi800_total_return.csv`
- `csi800_total_return.metadata.json`
- `csi800_pit_membership.csv`
- `csi800_pit_membership.metadata.json`

Do not create placeholder evidence or copy current constituent snapshots into
the PIT file. The benchmark must be CSI 800 total return, and membership must be
reviewed effective-dated history with at least 700 distinct members per snapshot.
Each metadata file must bind the exact CSV SHA-256 and record source, export
time, reviewer, review time, and declared coverage through `2026-10-16`.

Run the fail-closed preflight with:

```powershell
.\.venv\Scripts\python.exe examples\run_market_evidence_preflight.py `
  --benchmark-csv data_exports\indices\csi800_total_return.csv `
  --benchmark-metadata data_exports\indices\csi800_total_return.metadata.json `
  --membership-csv data_exports\indices\csi800_pit_membership.csv `
  --membership-metadata data_exports\indices\csi800_pit_membership.metadata.json `
  --required-start-date 2024-06-03 `
  --required-end-date 2026-10-16 `
  --minimum-members-per-snapshot 700 `
  --output-dir evidence\market\guard-v1-reviewed
```

Only `status=PASS` makes the external evidence package structurally admissible.
It does not override source QA, strategy, paper, approval, or live-trading gates.
