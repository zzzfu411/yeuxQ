"""Cache metadata guardrails shared by readiness and goal audits."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from quantify.data.provenance import (
    LATEST_IMPORT_BATCH_METADATA_KEY,
    LINEAGE_SCHEMA_VERSION,
    LINEAGE_SCHEMA_VERSION_METADATA_KEY,
    LOGICAL_BAR_FINGERPRINT_ALGORITHM,
    LOGICAL_BAR_FINGERPRINT_ALGORITHM_METADATA_KEY,
    LOGICAL_BAR_FINGERPRINT_METADATA_KEY,
    bar_row_fingerprint,
    logical_bar_fingerprint_from_connection,
)

PromotionMetadataStatus = Literal["PASS", "BLOCK"]

PROMOTION_METADATA_PROHIBITED_ACTIONS = [
    "Do not patch cache metadata by hand to bypass source QA.",
    "Do not treat promotion metadata PASS as strategy approval or a profit claim.",
    "Do not enter paper or micro-live readiness while deterministic gates are BLOCK.",
    "Do not connect this workflow to real broker order submission.",
]


@dataclass(frozen=True, slots=True)
class PromotionMetadataCheck:
    status: PromotionMetadataStatus
    cache_path: str
    require_evidence_manifest: bool
    metadata: dict[str, str]
    cache_stats: dict[str, Any]
    blockers: list[str]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "cache_path": self.cache_path,
            "require_evidence_manifest": self.require_evidence_manifest,
            "metadata": self.metadata,
            "cache_stats": self.cache_stats,
            "blockers": self.blockers,
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Promotion Metadata Check: {self.status}",
            "",
            f"- Cache: `{self.cache_path}`",
            f"- Require evidence manifest: `{self.require_evidence_manifest}`",
            "",
            (
                "This check reads SQLite metadata and bar-table identity without changing the cache. "
                "It is not a trading signal or broker instruction."
            ),
            "",
            "## Blockers",
        ]
        lines.extend(f"- {item}" for item in self.blockers) if self.blockers else lines.append("- None.")
        lines.extend(["", "## Metadata"])
        if self.metadata:
            lines.extend(["", "| key | value |", "| --- | --- |"])
            for key in sorted(self.metadata):
                lines.append(f"| `{key}` | `{self.metadata[key]}` |")
        else:
            lines.append("- None.")
        lines.extend(["", "## Cache Stats"])
        if self.cache_stats:
            lines.extend(["", "| key | value |", "| --- | --- |"])
            for key in sorted(self.cache_stats):
                lines.append(f"| `{key}` | `{self.cache_stats[key]}` |")
        else:
            lines.append("- None.")
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_promotion_metadata_check(
    cache_path: str | Path,
    *,
    require_evidence_manifest: bool = False,
) -> PromotionMetadataCheck:
    """Build a read-only promotion metadata check for an existing research cache."""
    cache = Path(cache_path)
    metadata: dict[str, str] = {}
    cache_stats: dict[str, Any] = {}
    blockers: list[str] = []
    if not cache.exists():
        blockers.append(f"Cache file does not exist: {cache}.")
    elif not cache.is_file():
        blockers.append(f"Cache path is not a file: {cache}.")
    else:
        try:
            metadata, has_table = load_cache_metadata_readonly(cache)
            cache_stats, has_bars_table = load_cache_bar_stats_readonly(cache)
            provenance_stats = load_cache_provenance_readonly(cache, metadata)
            cache_stats.update(provenance_stats)
        except sqlite3.Error as exc:
            blockers.append(f"Could not read SQLite promotion evidence from {cache}: {exc}.")
        else:
            if not has_table:
                blockers.append("Cache has no research_metadata table.")
            if not has_bars_table:
                blockers.append("Cache has no bars table.")
            else:
                blockers.extend(cache_data_identity_blockers(cache_stats, metadata))
                blockers.extend(cache_provenance_blockers(cache_stats, metadata))
            effective_metadata = dict(metadata)
            if require_evidence_manifest:
                effective_metadata["data_source_qa_require_evidence_manifest"] = "true"
            blockers.extend(cache_metadata_blockers(effective_metadata))

    blockers = list(dict.fromkeys(blockers))
    status: PromotionMetadataStatus = "BLOCK" if blockers else "PASS"
    return PromotionMetadataCheck(
        status=status,
        cache_path=str(cache),
        require_evidence_manifest=require_evidence_manifest,
        metadata=metadata,
        cache_stats=cache_stats,
        blockers=blockers,
        next_actions=promotion_metadata_next_actions(status, blockers),
        prohibited_actions=PROMOTION_METADATA_PROHIBITED_ACTIONS,
    )


def write_promotion_metadata_check(
    check: PromotionMetadataCheck,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "promotion_metadata_check.json").write_text(
        json.dumps(check.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "promotion_metadata_check.md").write_text(check.to_markdown(), encoding="utf-8")
    return root


def load_cache_metadata_readonly(cache_path: str | Path) -> tuple[dict[str, str], bool]:
    """Load `research_metadata` without creating or migrating the SQLite cache."""
    cache = Path(cache_path)
    uri = cache.resolve().as_posix()
    metadata: dict[str, str] = {}
    with sqlite3.connect(f"file:{uri}?mode=ro", uri=True) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'research_metadata'"
        ).fetchone()
        if row is None:
            return metadata, False
        rows = conn.execute("SELECT key, value FROM research_metadata ORDER BY key").fetchall()
    return {str(row[0]): str(row[1]) for row in rows}, True


def load_cache_bar_stats_readonly(cache_path: str | Path) -> tuple[dict[str, Any], bool]:
    """Read canonical bar-table identity without creating or changing the cache."""
    cache = Path(cache_path)
    uri = cache.resolve().as_posix()
    with sqlite3.connect(f"file:{uri}?mode=ro", uri=True) as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'bars'"
        ).fetchone()
        if row is None:
            return {}, False
        values = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(date), MAX(date) FROM bars"
        ).fetchone()
    values = values or (0, 0, None, None)
    return {
        "bar_count": int(values[0] or 0),
        "symbol_count": int(values[1] or 0),
        "bar_start": str(values[2] or ""),
        "bar_end": str(values[3] or ""),
    }, True


def load_cache_provenance_readonly(
    cache_path: str | Path,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Recompute logical cache identity and verify current-row lineage read-only."""
    cache = Path(cache_path)
    uri = cache.resolve().as_posix()
    stats: dict[str, Any] = {
        "provenance_batches_table": False,
        "provenance_lineage_table": False,
        "provenance_batch_count": 0,
        "provenance_lineage_record_count": 0,
        "provenance_current_lineage_count": 0,
        "provenance_missing_current_lineage_count": 0,
        "provenance_mismatched_current_lineage_count": 0,
        "logical_bar_fingerprint_actual": "",
        "latest_import_batch_id": str(metadata.get(LATEST_IMPORT_BATCH_METADATA_KEY, "") or ""),
        "latest_import_batch_exists": False,
        "latest_import_batch_status": "",
        "latest_import_batch_post_fingerprint": "",
        "latest_import_source_type": "",
        "latest_import_source_fingerprint_kind": "",
        "latest_import_source_fingerprint": "",
    }
    with sqlite3.connect(f"file:{uri}?mode=ro", uri=True) as conn:
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        if "bars" not in tables:
            return stats
        stats["logical_bar_fingerprint_actual"] = logical_bar_fingerprint_from_connection(conn)

        has_batches = "data_import_batches" in tables
        has_lineage = "bar_import_lineage" in tables
        stats["provenance_batches_table"] = has_batches
        stats["provenance_lineage_table"] = has_lineage
        if has_batches:
            stats["provenance_batch_count"] = int(
                conn.execute("SELECT COUNT(*) FROM data_import_batches").fetchone()[0]
            )
            latest_batch_id = str(stats["latest_import_batch_id"])
            if latest_batch_id:
                row = conn.execute(
                    """
                    SELECT status, post_import_logical_fingerprint, source_type,
                           source_fingerprint_kind, source_fingerprint
                    FROM data_import_batches WHERE batch_id = ?
                    """,
                    (latest_batch_id,),
                ).fetchone()
                if row is not None:
                    stats["latest_import_batch_exists"] = True
                    stats["latest_import_batch_status"] = str(row[0])
                    stats["latest_import_batch_post_fingerprint"] = str(row[1])
                    stats["latest_import_source_type"] = str(row[2])
                    stats["latest_import_source_fingerprint_kind"] = str(row[3])
                    stats["latest_import_source_fingerprint"] = str(row[4])

        if has_lineage:
            stats["provenance_lineage_record_count"] = int(
                conn.execute("SELECT COUNT(*) FROM bar_import_lineage").fetchone()[0]
            )
            query = """
                WITH latest AS (
                    SELECT symbol, date, MAX(lineage_id) AS lineage_id
                    FROM bar_import_lineage
                    GROUP BY symbol, date
                )
                SELECT b.symbol, b.date, b.open, b.high, b.low, b.close, b.volume, b.amount,
                       l.row_fingerprint
                FROM bars b
                LEFT JOIN latest x ON x.symbol = b.symbol AND x.date = b.date
                LEFT JOIN bar_import_lineage l ON l.lineage_id = x.lineage_id
                ORDER BY b.symbol COLLATE BINARY, b.date COLLATE BINARY
            """
            current_count = 0
            missing_count = 0
            mismatch_count = 0
            for row in conn.execute(query):
                current_count += 1
                recorded = row[8]
                if recorded is None:
                    missing_count += 1
                elif str(recorded) != bar_row_fingerprint(row[:8]):
                    mismatch_count += 1
            stats["provenance_current_lineage_count"] = current_count - missing_count
            stats["provenance_missing_current_lineage_count"] = missing_count
            stats["provenance_mismatched_current_lineage_count"] = mismatch_count
    return stats


def cache_provenance_blockers(
    cache_stats: dict[str, Any],
    metadata: dict[str, Any],
) -> list[str]:
    """Return blockers when the logical cache attestation is absent or stale."""
    blockers: list[str] = []
    if not bool(cache_stats.get("provenance_batches_table")):
        blockers.append("Cache has no data_import_batches provenance table.")
    if not bool(cache_stats.get("provenance_lineage_table")):
        blockers.append("Cache has no bar_import_lineage provenance table.")

    claimed = str(metadata.get(LOGICAL_BAR_FINGERPRINT_METADATA_KEY, "") or "")
    actual = str(cache_stats.get("logical_bar_fingerprint_actual", "") or "")
    algorithm = str(metadata.get(LOGICAL_BAR_FINGERPRINT_ALGORITHM_METADATA_KEY, "") or "")
    if not claimed:
        blockers.append(f"Missing {LOGICAL_BAR_FINGERPRINT_METADATA_KEY} in cache metadata.")
    elif claimed != actual:
        blockers.append("Cache logical bar fingerprint does not match current canonical bars.")
    if algorithm != LOGICAL_BAR_FINGERPRINT_ALGORITHM:
        blockers.append(
            "Cache logical bar fingerprint algorithm is missing or unsupported: "
            f"expected={LOGICAL_BAR_FINGERPRINT_ALGORITHM}, actual={algorithm or 'missing'}."
        )
    schema_version = str(metadata.get(LINEAGE_SCHEMA_VERSION_METADATA_KEY, "") or "")
    if schema_version != LINEAGE_SCHEMA_VERSION:
        blockers.append(
            f"Cache lineage schema version must be {LINEAGE_SCHEMA_VERSION}; "
            f"actual={schema_version or 'missing'}."
        )

    latest_batch_id = str(metadata.get(LATEST_IMPORT_BATCH_METADATA_KEY, "") or "")
    if not latest_batch_id:
        blockers.append(f"Missing {LATEST_IMPORT_BATCH_METADATA_KEY} in cache metadata.")
    elif not bool(cache_stats.get("latest_import_batch_exists")):
        blockers.append("Cache latest import batch metadata does not reference a stored batch.")
    else:
        if str(cache_stats.get("latest_import_batch_status", "")) != "COMMITTED":
            blockers.append("Cache latest import batch is not COMMITTED.")
        if claimed and str(cache_stats.get("latest_import_batch_post_fingerprint", "")) != claimed:
            blockers.append("Cache latest import batch fingerprint does not match cache metadata.")

    bar_count = int(cache_stats.get("bar_count", 0) or 0)
    current_lineage_count = int(cache_stats.get("provenance_current_lineage_count", 0) or 0)
    reported_missing_lineage = int(
        cache_stats.get("provenance_missing_current_lineage_count", 0) or 0
    )
    missing_lineage = max(reported_missing_lineage, bar_count - current_lineage_count)
    mismatched_lineage = int(cache_stats.get("provenance_mismatched_current_lineage_count", 0) or 0)
    if bar_count > 0 and current_lineage_count != bar_count:
        blockers.append(
            "Current bars are not fully covered by import lineage: "
            f"bars={bar_count}, covered={current_lineage_count}, missing={missing_lineage}."
        )
    if mismatched_lineage:
        blockers.append(
            f"Current bars have {mismatched_lineage} row fingerprint(s) that do not match lineage."
        )

    csv_fingerprint = str(metadata.get("csv_dataset_fingerprint", "") or "")
    if csv_fingerprint and bool(cache_stats.get("latest_import_batch_exists")):
        source_kind = str(cache_stats.get("latest_import_source_fingerprint_kind", "") or "")
        source_fingerprint = str(cache_stats.get("latest_import_source_fingerprint", "") or "")
        if source_kind != "csv_dataset_fingerprint" or source_fingerprint != csv_fingerprint:
            blockers.append(
                "Latest import batch is not bound to the cache csv_dataset_fingerprint."
            )
    declared_source = str(metadata.get("data_source", "") or "").strip().lower()
    latest_source = str(cache_stats.get("latest_import_source_type", "") or "").strip().lower()
    if declared_source and latest_source:
        declared_csv = declared_source in {
            "csv",
            "local_csv",
            "guarded_local_csv",
            "offline_csv",
            "tdx_csv",
        }
        latest_csv = latest_source in {"local_csv", "guarded_local_csv", "offline_csv", "tdx_csv"}
        declared_akshare = declared_source in {"akshare", "sina", "eastmoney"}
        latest_akshare = latest_source.startswith("akshare")
        if (declared_csv and not latest_csv) or (declared_akshare and not latest_akshare):
            blockers.append(
                "Latest import batch source type does not match cache data_source metadata."
            )
    return blockers


def cache_data_identity_blockers(
    cache_stats: dict[str, Any],
    metadata: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    bar_count = int(cache_stats.get("bar_count", 0) or 0)
    symbol_count = int(cache_stats.get("symbol_count", 0) or 0)
    bar_start = str(cache_stats.get("bar_start", "") or "")
    bar_end = str(cache_stats.get("bar_end", "") or "")
    if bar_count <= 0:
        blockers.append("Cache bars table has no market-data rows.")
    if symbol_count <= 0:
        blockers.append("Cache bars table has no symbols.")
    if not bar_start or not bar_end:
        blockers.append("Cache bars table has no valid date range.")

    blockers.extend(
        _metadata_stat_mismatch(
            metadata,
            metadata_key="data_import_symbol_count",
            actual=symbol_count,
            label="symbol count",
            integer=True,
        )
    )
    blockers.extend(
        _metadata_stat_mismatch(
            metadata,
            metadata_key="data_import_actual_bar_start",
            actual=bar_start,
            label="bar start",
        )
    )
    blockers.extend(
        _metadata_stat_mismatch(
            metadata,
            metadata_key="data_import_actual_bar_end",
            actual=bar_end,
            label="bar end",
        )
    )
    return blockers


def _metadata_stat_mismatch(
    metadata: dict[str, Any],
    *,
    metadata_key: str,
    actual: object,
    label: str,
    integer: bool = False,
) -> list[str]:
    claimed_text = str(metadata.get(metadata_key, "") or "").strip()
    if not claimed_text:
        return []
    if integer:
        try:
            claimed: object = int(claimed_text)
        except ValueError:
            return [f"Cache metadata {metadata_key} is not a valid integer."]
    else:
        claimed = claimed_text
    if claimed == actual:
        return []
    return [
        f"Cache metadata {metadata_key} does not match actual {label}: "
        f"claimed={claimed}, actual={actual}."
    ]


def promotion_metadata_next_actions(
    status: PromotionMetadataStatus,
    blockers: list[str],
) -> list[str]:
    if status == "PASS":
        return [
            "Promotion metadata is intact; continue through deterministic readiness, goal, and human approval gates."
        ]
    if any("does not exist" in item or "not a file" in item for item in blockers):
        return [
            "Import recent real A-share data through guarded offline intake before checking promotion metadata."
        ]
    if any("bars table" in item.lower() or "market-data rows" in item.lower() for item in blockers):
        return [
            "Rebuild the cache through guarded intake; promotion requires non-empty canonical bars."
        ]
    if any(
        marker in item.lower()
        for item in blockers
        for marker in ("lineage", "logical bar fingerprint", "import batch")
    ):
        return [
            "Re-import the dataset through a provenance-aware provider or guarded CSV intake; do not backfill attestation metadata by hand."
        ]
    if any("sha256" in item.lower() or "hash" in item.lower() for item in blockers):
        return [
            "Restore the retained source QA evidence files or rerun guarded offline intake to record fresh provenance hashes."
        ]
    return [
        "Rerun guarded offline intake so the cache records CSV fingerprint, PASS source QA metadata, and provenance hashes."
    ]


def cache_metadata_blockers(metadata: dict[str, Any]) -> list[str]:
    """Return blocking metadata gaps for a research cache used in promotion gates."""
    blockers: list[str] = []
    if _requires_csv_dataset_fingerprint(metadata) and not str(
        metadata.get("csv_dataset_fingerprint", "") or ""
    ).strip():
        blockers.append("Missing csv_dataset_fingerprint in cache metadata.")

    source_status = str(metadata.get("data_source_qa_status", "") or "").upper()
    if source_status != "PASS":
        blockers.append(
            "Cache metadata data_source_qa_status is "
            f"{source_status or 'missing'}; expected PASS."
        )

    csv_source_status = str(metadata.get("data_source_csv_qa_status", "") or "").upper()
    if _requires_csv_dataset_fingerprint(metadata) and csv_source_status != "PASS":
        blockers.append(
            "Cache metadata data_source_csv_qa_status is "
            f"{csv_source_status or 'missing'}; expected PASS."
        )

    blockers.extend(source_qa_provenance_blockers(metadata))
    return blockers


def _requires_csv_dataset_fingerprint(metadata: dict[str, Any]) -> bool:
    """Require a CSV fingerprint only when the cache actually claims a CSV route."""
    routes = {
        str(metadata.get("data_source", "") or "").strip().lower(),
        str(metadata.get("last_import_source", "") or "").strip().lower(),
    }
    csv_routes = {"csv", "local_csv", "guarded_local_csv", "offline_csv", "tdx_csv"}
    if routes & csv_routes:
        return True
    return any(
        str(metadata.get(key, "") or "").strip()
        for key in ("csv_validation_status", "csv_validation_report")
    )


def source_qa_provenance_blockers(metadata: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    for label, path_key, sha_key in [
        ("source QA checklist", "data_source_qa_checklist_path", "data_source_qa_checklist_sha256"),
        ("source QA answers", "data_source_qa_answers_path", "data_source_qa_answers_sha256"),
    ]:
        blockers.extend(metadata_file_hash_blockers(metadata, label=label, path_key=path_key, sha_key=sha_key))

    require_manifest = str(metadata.get("data_source_qa_require_evidence_manifest", "") or "").lower()
    if require_manifest in {"true", "1", "yes"}:
        blockers.extend(
            metadata_file_hash_blockers(
                metadata,
                label="source QA evidence manifest",
                path_key="data_source_qa_evidence_manifest_path",
                sha_key="data_source_qa_evidence_manifest_sha256",
            )
        )
    return blockers


def metadata_file_hash_blockers(
    metadata: dict[str, Any],
    *,
    label: str,
    path_key: str,
    sha_key: str,
) -> list[str]:
    blockers: list[str] = []
    path_text = str(metadata.get(path_key, "") or "").strip()
    sha_text = str(metadata.get(sha_key, "") or "").strip()
    if not path_text:
        blockers.append(f"Missing {path_key} in cache metadata.")
        return blockers
    if not sha_text:
        blockers.append(f"Missing {sha_key} in cache metadata.")
        return blockers
    if not looks_like_sha256(sha_text):
        blockers.append(f"Cache metadata {sha_key} is not a valid sha256 hex digest.")
        return blockers
    path = Path(path_text)
    if not path.exists():
        blockers.append(f"Cache metadata {path_key} points to a missing {label} file: {path_text}.")
        return blockers
    actual = file_sha256(path)
    if actual != sha_text.lower():
        blockers.append(f"Cache metadata {sha_key} does not match current {label} file hash.")
    return blockers


def looks_like_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdefABCDEF" for char in value)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
