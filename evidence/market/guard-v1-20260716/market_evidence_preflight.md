# Market Evidence Preflight: BLOCK

- Operation: `read_only_external_evidence_validation`
- Network access: `false`
- Broker access: `false`
- Evidence sufficient: `false`
- Expected index code: `000906`
- Required coverage: `2024-06-03` to `2026-10-16`
- Minimum members per PIT snapshot: 700

## Benchmark

- CSV: `D:\Develop\claude\quantify\data_exports\indices\csi800_total_return.csv`
- SHA-256: `unavailable`
- Hash matches metadata: `unavailable`
- Observed coverage: unavailable
- Observations: 0
- Metadata JSON: `D:\Develop\claude\quantify\data_exports\indices\csi800_total_return.metadata.json`
- Metadata SHA-256: `unavailable`
- Symbol: `unavailable`
- Total return: `unavailable`
- Declared coverage: unavailable
- Source vendor: `unavailable`
- Reviewed by: `unavailable`

## PIT Membership

- CSV: `D:\Develop\claude\quantify\data_exports\indices\csi800_pit_membership.csv`
- SHA-256: `unavailable`
- Hash matches metadata: `unavailable`
- Observed coverage: unavailable
- Observations: 0
- Distinct effective dates: 0
- Metadata JSON: `D:\Develop\claude\quantify\data_exports\indices\csi800_pit_membership.metadata.json`
- Metadata SHA-256: `unavailable`
- Index code: `unavailable`
- Point in time: `unavailable`
- Snapshot mode: `unavailable`
- Declared coverage: unavailable
- Source vendor: `unavailable`
- Source dataset: `unavailable`
- Reviewed by: `unavailable`

## Evidence

- `PASS` `REQUIRED_COVERAGE_VALID`: Required market-evidence coverage is a valid closed date range.
- `BLOCK` `BENCHMARK_CSV_MISSING`: Required input file is missing: data_exports\indices\csi800_total_return.csv.
- `BLOCK` `BENCHMARK_METADATA_MISSING`: Required input file is missing: data_exports\indices\csi800_total_return.metadata.json.
- `BLOCK` `MEMBERSHIP_CSV_MISSING`: Required input file is missing: data_exports\indices\csi800_pit_membership.csv.
- `BLOCK` `MEMBERSHIP_METADATA_MISSING`: Required input file is missing: data_exports\indices\csi800_pit_membership.metadata.json.

A PASS attests only that the retained external files satisfy this preflight contract. It does not fetch data, contact a broker, or authorize trading.
