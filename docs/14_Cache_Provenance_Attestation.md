# Cache Provenance Attestation v1

## Purpose

Cache Provenance Attestation v1 makes normalized A-share daily bars auditable
without claiming knowledge that the system does not have. It answers:

- Which committed import batch last wrote each current bar?
- Did the logical bar content change after import?
- Is the current SQLite cache still the content that the run manifest recorded?

It does not prove data licensing, point-in-time universe membership, source
accuracy, or strategy profitability. Those remain separate deterministic gates.

## Three Separate Identities

| Identity | Meaning | Stability |
| --- | --- | --- |
| `cache_sha256` | Exact SQLite file bytes | Changes after `VACUUM`, indexes, or metadata writes |
| `cache_logical_bar_fingerprint` | Canonical normalized `bars` content | Stable across insertion order and `VACUUM` |
| `csv_dataset_fingerprint` | Retained and validated CSV input package | Only valid for a real CSV intake route |

Never copy one identity into another field. In particular, an AKShare/Sina API
cache must not invent `csv_dataset_fingerprint`.

## SQLite Evidence

`data_import_batches` records one atomic import commit, including:

- batch ID and source type;
- optional typed source fingerprint;
- import time, row/symbol/date coverage;
- logical fingerprints before and after the write;
- canonical fingerprint algorithm version.

`bar_import_lineage` is append-only import history. Each record binds one
`(symbol, date)` row fingerprint to its import batch. Current lineage is the
latest lineage record for each bar key.

The official import path writes the batch row, bar upserts, row lineage, logical
fingerprint, and compact `research_metadata` attestation in one SQLite
transaction. A lineage failure rolls back all of those writes.

## Canonical Fingerprint

The v1 algorithm is `sha256:quantify.logical-bars.v1`:

1. Read fixed columns in binary `(symbol, date)` order.
2. Encode text unambiguously as UTF-8 JSON fields.
3. Encode every finite numeric value with exact `float.hex()` representation.
4. Prefix each row payload with its byte length and include the total row count.
5. Hash the versioned stream with SHA-256.

This excludes SQLite page layout, row IDs, indexes, and file metadata. Any bar
insert, delete, key change, or OHLCVA value change changes the digest with
cryptographic probability.

## Promotion Rules

All promotion-facing routes require:

- matching claimed and read-only recomputed logical fingerprints;
- a stored, committed latest import batch;
- complete current-bar lineage with matching row fingerprints;
- source QA and retained evidence hashes;
- a run manifest tied to the same cache, logical fingerprint, and batch.

CSV routes additionally require a matching `csv_dataset_fingerprint` and CSV
source-QA PASS. API/provider routes do not require a CSV fingerprint, but still
require provider/source QA and a compatible batch source type.

The weekly pipeline writes `promotion_metadata_check.json/md`. Micro-live
readiness and human approval snapshots include this artifact. LLM review may
describe missing attestation, but cannot upgrade its deterministic result.

## Legacy Cache Policy

Opening an old cache may add empty v1 schema tables, but it never fabricates
historical lineage. Existing bars remain legacy/unattested until they are
re-imported from retained source evidence through a v1 importer.

The current AKShare/Sina research cache is retained as legacy evidence. Do not
patch its metadata or synthesize CSV/source claims. Build a new cache path for a
future attested import, then regenerate all run manifests and review artifacts.

## Verification

```powershell
.\.venv\Scripts\python.exe examples\check_promotion_metadata.py `
  --config config\research_recent.yaml `
  --output-dir results\import\promotion_metadata

.\.venv\Scripts\python.exe -m pytest tests\test_cache_provenance.py `
  tests\test_promotion_metadata_check.py -q `
  --basetemp .\tmp\pytest-provenance -p no:cacheprovider
```

This workflow remains research/paper only. It does not connect to a broker or
authorize live orders.
