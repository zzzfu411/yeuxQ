"""Cache metadata guardrails shared by readiness and goal audits."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Literal

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
    blockers: list[str]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "cache_path": self.cache_path,
            "require_evidence_manifest": self.require_evidence_manifest,
            "metadata": self.metadata,
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
            "This check reads SQLite `research_metadata` only. It is not a trading signal or broker instruction.",
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
    blockers: list[str] = []
    if not cache.exists():
        blockers.append(f"Cache file does not exist: {cache}.")
    elif not cache.is_file():
        blockers.append(f"Cache path is not a file: {cache}.")
    else:
        try:
            metadata, has_table = load_cache_metadata_readonly(cache)
        except sqlite3.Error as exc:
            blockers.append(f"Could not read SQLite research_metadata from {cache}: {exc}.")
        else:
            if not has_table:
                blockers.append("Cache has no research_metadata table.")
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
    if not str(metadata.get("csv_dataset_fingerprint", "") or "").strip():
        blockers.append("Missing csv_dataset_fingerprint in cache metadata.")

    source_status = str(metadata.get("data_source_qa_status", "") or "").upper()
    if source_status != "PASS":
        blockers.append(
            "Cache metadata data_source_qa_status is "
            f"{source_status or 'missing'}; expected PASS."
        )

    csv_source_status = str(metadata.get("data_source_csv_qa_status", "") or "").upper()
    if csv_source_status != "PASS":
        blockers.append(
            "Cache metadata data_source_csv_qa_status is "
            f"{csv_source_status or 'missing'}; expected PASS."
        )

    blockers.extend(source_qa_provenance_blockers(metadata))
    return blockers


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
