"""Read-only inbox for retained source QA evidence files.

The inbox helps a human operator map local evidence files to required source QA
attachment ids. It never creates evidence, never writes answers, and never
approves source QA by itself.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from quantify.data.source_qa import validate_source_qa_attachment

EvidenceInboxStatus = Literal["PASS", "WATCH", "BLOCK"]

PROHIBITED_ACTIONS = [
    "Do not treat inbox file discovery as source QA approval.",
    "Do not fabricate screenshots, PDFs, notes, hashes, or human review records.",
    "Do not use generated todo files, attachment plans, templates, or this inbox report as source evidence.",
    "Do not generate data_source_qa_answers.json from guessed file matches.",
    "Do not connect this workflow to real broker order submission.",
]

_SOURCE_EVIDENCE_ARGS = {
    "source_identity": "--source-identity-evidence",
    "license_scope": "--license-evidence",
    "price_adjustment": "--price-adjustment-evidence",
    "point_in_time": "--point-in-time-evidence",
    "manual_signoff": "--manual-signoff-evidence",
}


@dataclass(frozen=True, slots=True)
class SourceQAEvidenceInboxFile:
    path: str
    exists: bool
    size_bytes: int
    modified_at_utc: str
    sha256: str
    inferred_id: str
    matched_required_id: str
    status: EvidenceInboxStatus
    message: str
    validation_error: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "exists": self.exists,
            "size_bytes": self.size_bytes,
            "modified_at_utc": self.modified_at_utc,
            "sha256": self.sha256,
            "inferred_id": self.inferred_id,
            "matched_required_id": self.matched_required_id,
            "status": self.status,
            "message": self.message,
            "validation_error": self.validation_error,
        }


@dataclass(frozen=True, slots=True)
class SourceQAEvidenceInboxItem:
    item_id: str
    target_path: str
    current_state: str
    required_evidence: str
    acceptable_evidence: str
    unacceptable_evidence: str
    matched_files: list[SourceQAEvidenceInboxFile]
    suggested_files: list[SourceQAEvidenceInboxFile]
    status: EvidenceInboxStatus
    message: str
    next_command: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "target_path": self.target_path,
            "current_state": self.current_state,
            "required_evidence": self.required_evidence,
            "acceptable_evidence": self.acceptable_evidence,
            "unacceptable_evidence": self.unacceptable_evidence,
            "matched_files": [item.to_dict() for item in self.matched_files],
            "suggested_files": [item.to_dict() for item in self.suggested_files],
            "status": self.status,
            "message": self.message,
            "next_command": self.next_command,
        }


@dataclass(frozen=True, slots=True)
class SourceQAWorksheetFillArgument:
    item_id: str
    cli_argument: str
    value: str
    source: str
    exists: bool
    ready: bool
    status: EvidenceInboxStatus
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "cli_argument": self.cli_argument,
            "value": self.value,
            "source": self.source,
            "exists": self.exists,
            "ready": self.ready,
            "status": self.status,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class SourceQAEvidenceInboxReport:
    status: EvidenceInboxStatus
    as_of: str
    data_dir: str
    report_dir: str
    checklist_path: str
    evidence_dir: str
    manifest_path: str
    scanned_file_count: int
    required_item_count: int
    matched_item_count: int
    missing_item_count: int
    invalid_file_count: int
    unmatched_file_count: int
    worksheet_fill_command: str
    worksheet_fill_command_ready: bool
    worksheet_fill_command_status: EvidenceInboxStatus
    worksheet_fill_command_blockers: list[str]
    worksheet_fill_command_warnings: list[str]
    worksheet_fill_args: list[SourceQAWorksheetFillArgument]
    items: list[SourceQAEvidenceInboxItem]
    unmatched_files: list[SourceQAEvidenceInboxFile]
    next_commands: list[str]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "as_of": self.as_of,
            "data_dir": self.data_dir,
            "report_dir": self.report_dir,
            "checklist_path": self.checklist_path,
            "evidence_dir": self.evidence_dir,
            "manifest_path": self.manifest_path,
            "scanned_file_count": self.scanned_file_count,
            "required_item_count": self.required_item_count,
            "matched_item_count": self.matched_item_count,
            "missing_item_count": self.missing_item_count,
            "invalid_file_count": self.invalid_file_count,
            "unmatched_file_count": self.unmatched_file_count,
            "worksheet_fill_command": self.worksheet_fill_command,
            "worksheet_fill_command_ready": self.worksheet_fill_command_ready,
            "worksheet_fill_command_status": self.worksheet_fill_command_status,
            "worksheet_fill_command_blockers": self.worksheet_fill_command_blockers,
            "worksheet_fill_command_warnings": self.worksheet_fill_command_warnings,
            "worksheet_fill_args": [item.to_dict() for item in self.worksheet_fill_args],
            "items": [item.to_dict() for item in self.items],
            "unmatched_files": [item.to_dict() for item in self.unmatched_files],
            "next_commands": self.next_commands,
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Source QA Evidence Inbox: {self.status}",
            "",
            f"- As of: `{self.as_of}`",
            f"- Data directory: `{self.data_dir}`",
            f"- Report directory: `{self.report_dir}`",
            f"- Checklist: `{self.checklist_path}`",
            f"- Evidence directory: `{self.evidence_dir}`",
            f"- Manifest: `{self.manifest_path}`",
            f"- Scanned files: {self.scanned_file_count}",
            f"- Required items: {self.required_item_count}",
            f"- Matched items: {self.matched_item_count}",
            f"- Missing items: {self.missing_item_count}",
            f"- Invalid files: {self.invalid_file_count}",
            f"- Unmatched files: {self.unmatched_file_count}",
            f"- Worksheet fill command ready: `{str(self.worksheet_fill_command_ready).lower()}`",
            f"- Worksheet fill command status: `{self.worksheet_fill_command_status}`",
            "",
            "This inbox only maps local files to source QA evidence requirements. It does not create evidence, answer source QA, approve data, or permit broker activity.",
            "",
            "## Worksheet Fill Command",
            "",
            "Replace the metadata placeholders before running this command. Evidence arguments are populated from matched or suggested local files when available; target paths and placeholders are not ready evidence. The command is only ready when each source evidence argument points to an existing matched or suggested file.",
            "",
            "```powershell",
            self.worksheet_fill_command,
            "```",
            "",
            "| status | id | argument | source | exists | ready | value |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for item in self.worksheet_fill_args:
            lines.append(
                f"| `{item.status}` | `{item.item_id}` | `{item.cli_argument}` | "
                f"`{item.source}` | `{item.exists}` | `{item.ready}` | `{_cell(item.value)}` |"
            )
        if self.worksheet_fill_command_blockers:
            lines.extend(["", "Worksheet fill blockers:"])
            lines.extend(f"- {item}" for item in self.worksheet_fill_command_blockers)
        if self.worksheet_fill_command_warnings:
            lines.extend(["", "Worksheet fill warnings:"])
            lines.extend(f"- {item}" for item in self.worksheet_fill_command_warnings)
        lines.extend(
            [
            "",
            "## Required Items",
            "",
            ]
        )
        if self.items:
            lines.append("| status | id | target | state | matched | suggestions | message |")
            lines.append("| --- | --- | --- | --- | ---: | ---: | --- |")
            for item in self.items:
                lines.append(
                    f"| `{item.status}` | `{item.item_id}` | `{item.target_path}` | "
                    f"`{item.current_state}` | {len(item.matched_files)} | "
                    f"{len(item.suggested_files)} | {_cell(item.message)} |"
                )
        else:
            lines.append("- None.")
        lines.extend(["", "## Unmatched Files", ""])
        if self.unmatched_files:
            lines.append("| status | inferred id | path | size | message |")
            lines.append("| --- | --- | --- | ---: | --- |")
            for item in self.unmatched_files:
                lines.append(
                    f"| `{item.status}` | `{item.inferred_id or '-'}` | `{item.path}` | "
                    f"{item.size_bytes} | {_cell(item.message)} |"
                )
        else:
            lines.append("- None.")
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Next Commands"])
        for command in self.next_commands:
            lines.extend(["", "```powershell", command, "```"])
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_source_qa_evidence_inbox(
    *,
    data_dir: str | Path = "data_exports",
    report_dir: str | Path = "results/first_million",
    checklist_path: str | Path | None = None,
    evidence_dir: str | Path | None = None,
    manifest_path: str | Path | None = None,
    as_of: str | None = None,
    max_suggestions_per_item: int = 3,
) -> SourceQAEvidenceInboxReport:
    data_root = Path(data_dir)
    report_root = Path(report_dir)
    checklist_file = Path(checklist_path) if checklist_path else data_root / "data_source_qa.json"
    evidence_root = Path(evidence_dir) if evidence_dir else data_root / "source_qa_evidence"
    manifest_file = Path(manifest_path) if manifest_path else data_root / "source_qa_evidence_manifest.json"
    required_items = _required_items(checklist_file, report_root)
    source_ids = [item["id"] for item in required_items]
    files = [_file_candidate(path, source_ids) for path in _scan_files(evidence_root)]
    manifest_by_id = _manifest_items(manifest_file)
    rows = _attachment_plan_rows(report_root / "source_qa_evidence_attachment_plan.csv")
    items = [
        _inbox_item(
            item,
            files=files,
            manifest_by_id=manifest_by_id,
            plan_rows=rows,
            max_suggestions=max_suggestions_per_item,
            data_root=data_root,
            checklist_file=checklist_file,
            evidence_root=evidence_root,
            manifest_file=manifest_file,
        )
        for item in required_items
    ]
    matched_paths = {
        file.path
        for item in items
        for file in [*item.matched_files, *item.suggested_files]
    }
    unmatched_files = [file for file in files if file.path not in matched_paths]
    invalid_file_count = sum(
        1
        for file in files
        if file.status == "BLOCK" or (file.validation_error and file.validation_error.get("code"))
    )
    missing_item_count = sum(1 for item in items if item.status == "BLOCK")
    status = _report_status(items, invalid_file_count)
    fill_args = _worksheet_fill_args(items)
    fill_review = _worksheet_fill_command_review(fill_args)
    fill_command = _worksheet_fill_command(
        checklist_file=checklist_file,
        worksheet_file=data_root / "data_source_qa_evidence_worksheet.csv",
        data_root=data_root,
        fill_args=fill_args,
    )
    return SourceQAEvidenceInboxReport(
        status=status,
        as_of=str(as_of or _read_as_of(report_root) or "unspecified"),
        data_dir=str(data_root),
        report_dir=str(report_root),
        checklist_path=str(checklist_file),
        evidence_dir=str(evidence_root),
        manifest_path=str(manifest_file),
        scanned_file_count=len(files),
        required_item_count=len(items),
        matched_item_count=sum(1 for item in items if item.matched_files),
        missing_item_count=missing_item_count,
        invalid_file_count=invalid_file_count,
        unmatched_file_count=len(unmatched_files),
        worksheet_fill_command=fill_command,
        worksheet_fill_command_ready=fill_review["ready"],
        worksheet_fill_command_status=fill_review["status"],
        worksheet_fill_command_blockers=fill_review["blockers"],
        worksheet_fill_command_warnings=fill_review["warnings"],
        worksheet_fill_args=fill_args,
        items=items,
        unmatched_files=unmatched_files,
        next_commands=_next_commands(
            status=status,
            checklist_file=checklist_file,
            evidence_root=evidence_root,
            manifest_file=manifest_file,
            report_root=report_root,
            fill_command=fill_command,
        ),
        next_actions=_next_actions(
            status,
            items,
            unmatched_files,
            fill_blockers=fill_review["blockers"],
            fill_warnings=fill_review["warnings"],
        ),
        prohibited_actions=PROHIBITED_ACTIONS,
    )


def write_source_qa_evidence_inbox(
    report: SourceQAEvidenceInboxReport,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "source_qa_evidence_inbox.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "source_qa_evidence_inbox.md").write_text(report.to_markdown(), encoding="utf-8")
    with (root / "source_qa_evidence_inbox.csv").open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        fieldnames = [
            "item_id",
            "status",
            "target_path",
            "current_state",
            "matched_files",
            "suggested_files",
            "message",
            "required_evidence",
            "next_command",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in report.items:
            writer.writerow(
                {
                    "item_id": item.item_id,
                    "status": item.status,
                    "target_path": item.target_path,
                    "current_state": item.current_state,
                    "matched_files": "; ".join(file.path for file in item.matched_files),
                    "suggested_files": "; ".join(file.path for file in item.suggested_files),
                    "message": item.message,
                    "required_evidence": item.required_evidence,
                    "next_command": item.next_command,
                }
            )
    return root


def _required_items(checklist_file: Path, report_root: Path) -> list[dict[str, str]]:
    checklist = _read_json(checklist_file)
    items = [
        {
            "id": str(item.get("id", "")).strip(),
            "required_evidence": str(item.get("required_evidence", "")).strip(),
            "acceptable_evidence": _acceptable_evidence(str(item.get("id", "")).strip()),
            "unacceptable_evidence": _unacceptable_evidence(str(item.get("id", "")).strip()),
            "target_path": str(_default_target(checklist_file, str(item.get("id", "")).strip())),
            "current_state": "required",
            "next_command": "",
        }
        for item in checklist.get("checklist", []) or []
        if isinstance(item, dict)
        and str(item.get("review_stage", "")) == "source"
        and str(item.get("severity", "")).upper() == "BLOCK_IF_NO"
        and str(item.get("id", "")).strip()
    ]
    if items:
        plan_rows = _attachment_plan_rows(report_root / "source_qa_evidence_attachment_plan.csv")
        return [_merge_plan_row(item, plan_rows.get(item["id"], {})) for item in items]
    return _items_from_operator_packet(report_root) or _items_from_attachment_plan(report_root)


def _items_from_operator_packet(report_root: Path) -> list[dict[str, str]]:
    packet = _read_json(report_root / "source_qa_operator_packet.json")
    rows = []
    for item in packet.get("items", []) or []:
        if not isinstance(item, dict) or str(item.get("item_type")) != "attachment":
            continue
        item_id = str(item.get("item_id") or "").strip()
        if not item_id:
            continue
        rows.append(
            {
                "id": item_id,
                "required_evidence": str(item.get("evidence_required") or ""),
                "acceptable_evidence": str(item.get("acceptable_evidence") or _acceptable_evidence(item_id)),
                "unacceptable_evidence": str(item.get("unacceptable_evidence") or _unacceptable_evidence(item_id)),
                "target_path": str(item.get("target") or ""),
                "current_state": str(item.get("current_state") or "missing"),
                "next_command": str(item.get("command_after_completion") or ""),
            }
        )
    return rows


def _items_from_attachment_plan(report_root: Path) -> list[dict[str, str]]:
    rows = []
    for item_id, row in _attachment_plan_rows(report_root / "source_qa_evidence_attachment_plan.csv").items():
        rows.append(
            {
                "id": item_id,
                "required_evidence": str(row.get("required_evidence") or ""),
                "acceptable_evidence": _acceptable_evidence(item_id),
                "unacceptable_evidence": str(row.get("do_not_use") or _unacceptable_evidence(item_id)),
                "target_path": str(row.get("suggested_file") or ""),
                "current_state": str(row.get("current_state") or "missing"),
                "next_command": str(row.get("next_command") or ""),
            }
        )
    return rows


def _merge_plan_row(item: dict[str, str], row: dict[str, str]) -> dict[str, str]:
    if not row:
        return item
    merged = dict(item)
    merged["target_path"] = str(row.get("suggested_file") or row.get("target") or item["target_path"])
    merged["current_state"] = str(row.get("current_state") or item["current_state"])
    merged["unacceptable_evidence"] = str(row.get("do_not_use") or item["unacceptable_evidence"])
    merged["next_command"] = str(row.get("next_command") or item["next_command"])
    if row.get("required_evidence"):
        merged["required_evidence"] = str(row.get("required_evidence"))
    return merged


def _inbox_item(
    item: dict[str, str],
    *,
    files: list[SourceQAEvidenceInboxFile],
    manifest_by_id: dict[str, list[dict[str, Any]]],
    plan_rows: dict[str, dict[str, str]],
    max_suggestions: int,
    data_root: Path,
    checklist_file: Path,
    evidence_root: Path,
    manifest_file: Path,
) -> SourceQAEvidenceInboxItem:
    item_id = item["id"]
    manifest_matches = [
        _manifest_file_candidate(raw, item_id, files)
        for raw in manifest_by_id.get(item_id, [])
        if isinstance(raw, dict)
    ]
    matched = [file for file in manifest_matches if file is not None]
    if not matched:
        matched = [file for file in files if file.matched_required_id == item_id]
    suggested = [
        file
        for file in _rank_suggestions(item_id, files)
        if file.path not in {match.path for match in matched}
    ][:max_suggestions]
    invalid = [file for file in matched if file.status == "BLOCK"]
    if matched and not invalid:
        status: EvidenceInboxStatus = "PASS"
        message = "Local evidence file is present; rerun strict source QA review to decide validity."
    elif matched and invalid:
        status = "WATCH"
        message = "A local file is mapped, but basic validation flagged it; replace or fix before strict review."
    elif suggested:
        status = "WATCH"
        message = "No manifest match yet; possible local file suggestions need human review."
    else:
        status = "BLOCK"
        message = "Required source QA evidence attachment is missing from the inbox."
    plan_row = plan_rows.get(item_id, {})
    target = str(item.get("target_path") or plan_row.get("suggested_file") or _default_target_from_root(data_root, item_id))
    next_command = str(
        item.get("next_command")
        or plan_row.get("next_command")
        or _manifest_command(checklist_file=checklist_file, evidence_root=evidence_root, manifest_file=manifest_file)
    )
    return SourceQAEvidenceInboxItem(
        item_id=item_id,
        target_path=target,
        current_state=str(item.get("current_state") or "missing"),
        required_evidence=str(item.get("required_evidence") or ""),
        acceptable_evidence=str(item.get("acceptable_evidence") or _acceptable_evidence(item_id)),
        unacceptable_evidence=str(item.get("unacceptable_evidence") or _unacceptable_evidence(item_id)),
        matched_files=matched,
        suggested_files=suggested,
        status=status,
        message=message,
        next_command=next_command,
    )


def _file_candidate(path: Path, source_ids: list[str]) -> SourceQAEvidenceInboxFile:
    exists = path.exists()
    stat = path.stat() if exists else None
    sha = _file_sha256(path) if exists and path.is_file() else ""
    if _looks_like_instruction_or_generated_file(path):
        return SourceQAEvidenceInboxFile(
            path=str(path),
            exists=exists,
            size_bytes=int(stat.st_size) if stat else 0,
            modified_at_utc=(
                datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat() if stat else ""
            ),
            sha256=sha,
            inferred_id="",
            matched_required_id="",
            status="BLOCK",
            message="Instruction, template, generated, or planning files cannot be used as source QA evidence.",
            validation_error={
                "code": "instruction_or_generated_file",
                "message": "Use retained vendor/broker/export evidence, not README, template, generated, or planning files.",
            },
        )
    inferred_id = _infer_id(path, source_ids)
    matched_id = inferred_id if inferred_id in set(source_ids) else ""
    validation_error = (
        validate_source_qa_attachment(item_id=matched_id, path_text=str(path), sha256=sha)
        if matched_id
        else {}
    )
    status: EvidenceInboxStatus = "PASS"
    message = "File is available for human evidence review."
    if not matched_id:
        status = "WATCH"
        message = "File does not clearly match a required source QA id."
    elif validation_error:
        status = "BLOCK"
        message = str(validation_error.get("message") or "File failed basic attachment validation.")
    return SourceQAEvidenceInboxFile(
        path=str(path),
        exists=exists,
        size_bytes=int(stat.st_size) if stat else 0,
        modified_at_utc=(
            datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat() if stat else ""
        ),
        sha256=sha,
        inferred_id=inferred_id,
        matched_required_id=matched_id,
        status=status,
        message=message,
        validation_error=validation_error or {},
    )


def _manifest_file_candidate(
    raw: dict[str, Any],
    item_id: str,
    files: list[SourceQAEvidenceInboxFile],
) -> SourceQAEvidenceInboxFile | None:
    path_text = str(raw.get("path") or "").strip()
    if not path_text:
        return SourceQAEvidenceInboxFile(
            path="",
            exists=False,
            size_bytes=0,
            modified_at_utc="",
            sha256=str(raw.get("sha256") or ""),
            inferred_id=item_id,
            matched_required_id=item_id,
            status="BLOCK",
            message="Manifest item has no path.",
            validation_error={"code": "path_missing", "message": "Manifest attachment is missing its local file path."},
        )
    existing = next((file for file in files if Path(file.path) == Path(path_text)), None)
    if existing is not None:
        return existing
    sha = str(raw.get("sha256") or "").strip()
    error = validate_source_qa_attachment(item_id=item_id, path_text=path_text, sha256=sha)
    return SourceQAEvidenceInboxFile(
        path=path_text,
        exists=Path(path_text).exists(),
        size_bytes=0,
        modified_at_utc="",
        sha256=sha,
        inferred_id=item_id,
        matched_required_id=item_id,
        status="BLOCK" if error else "PASS",
        message=str(error.get("message") if error else "Manifest file exists outside scanned inbox."),
        validation_error=error or {},
    )


def _scan_files(evidence_root: Path) -> list[Path]:
    if not evidence_root.exists():
        return []
    return sorted(path for path in evidence_root.rglob("*") if path.is_file())


def _manifest_items(path: Path) -> dict[str, list[dict[str, Any]]]:
    payload = _read_json(path)
    by_id: dict[str, list[dict[str, Any]]] = {}
    for item in payload.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        if item_id:
            by_id.setdefault(item_id, []).append(item)
    return by_id


def _attachment_plan_rows(path: Path) -> dict[str, dict[str, str]]:
    rows = _read_csv_rows(path)
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        item_id = str(row.get("id") or "").strip()
        if item_id:
            result[item_id] = row
    return result


def _rank_suggestions(
    item_id: str,
    files: list[SourceQAEvidenceInboxFile],
) -> list[SourceQAEvidenceInboxFile]:
    scored = [(file, _match_score(item_id, file)) for file in files]
    return [
        file
        for file, score in sorted(
            scored,
            key=lambda item: (
                -item[1],
                item[0].status == "BLOCK",
                item[0].path.lower(),
            ),
        )
        if score > 0 and file.status != "BLOCK"
    ]


def _match_score(item_id: str, file: SourceQAEvidenceInboxFile) -> int:
    if file.matched_required_id == item_id:
        return 100
    tokens = set(_tokens(Path(file.path).name))
    item_tokens = set(_tokens(item_id))
    score = 0
    if item_id.lower() in Path(file.path).stem.lower():
        score += 50
    score += 10 * len(tokens.intersection(item_tokens))
    score += _semantic_score(item_id, tokens)
    return score


def _semantic_score(item_id: str, tokens: set[str]) -> int:
    groups = {
        "source_identity": {"source", "identity", "vendor", "broker", "terminal", "receipt", "export"},
        "license_scope": {"license", "scope", "permission", "terms", "usage", "account"},
        "price_adjustment": {"price", "adjustment", "qfq", "hfq", "raw", "adjust"},
        "point_in_time": {"pit", "point", "time", "survivorship", "fundamental", "limitation"},
        "manual_signoff": {"manual", "signoff", "review", "reviewed", "approval", "human"},
    }
    return 5 * len(tokens.intersection(groups.get(item_id, set())))


def _infer_id(path: Path, source_ids: list[str]) -> str:
    lowered_name = path.name.lower()
    lowered_stem = path.stem.lower()
    for item_id in sorted(source_ids, key=len, reverse=True):
        lowered = item_id.lower()
        if lowered_stem == lowered or lowered_stem.startswith(f"{lowered}_") or lowered_stem.startswith(
            f"{lowered}-"
        ):
            return item_id
        if f"_{lowered}_" in lowered_name or f"-{lowered}-" in lowered_name:
            return item_id
    best = ""
    best_score = 0
    for item_id in source_ids:
        score = _semantic_score(item_id, set(_tokens(path.name)))
        if score > best_score:
            best = item_id
            best_score = score
    return best if best_score >= 10 else ""


def _looks_like_instruction_or_generated_file(path: Path) -> bool:
    lowered = path.name.lower()
    if lowered.startswith("readme"):
        return True
    tokens = set(_tokens(path.name))
    blocked = {
        "generated",
        "instruction",
        "kit",
        "mock",
        "placeholder",
        "plan",
        "sample",
        "template",
        "todo",
        "worksheet",
    }
    return bool(tokens & blocked)


def _report_status(items: list[SourceQAEvidenceInboxItem], invalid_file_count: int) -> EvidenceInboxStatus:
    if not items or any(item.status == "BLOCK" for item in items):
        return "BLOCK"
    if invalid_file_count or any(item.status == "WATCH" for item in items):
        return "WATCH"
    return "PASS"


def _next_actions(
    status: EvidenceInboxStatus,
    items: list[SourceQAEvidenceInboxItem],
    unmatched_files: list[SourceQAEvidenceInboxFile],
    *,
    fill_blockers: list[str],
    fill_warnings: list[str],
) -> list[str]:
    if status == "PASS":
        actions = [
            "Regenerate source_qa_evidence_manifest.json from retained evidence files.",
            "Run strict source QA readiness and first-million pipeline; deterministic gates still decide readiness.",
        ]
        if fill_warnings:
            actions.insert(0, f"Review worksheet fill warnings before filling the worksheet: {fill_warnings[0]}")
        return actions
    missing = [item.item_id for item in items if item.status == "BLOCK"][:6]
    watch = [item.item_id for item in items if item.status == "WATCH"][:6]
    actions = []
    if fill_blockers:
        actions.append(f"Do not run the worksheet fill command yet: {fill_blockers[0]}")
    elif fill_warnings:
        actions.append(f"Review worksheet fill warnings before running the command: {fill_warnings[0]}")
    if missing:
        actions.append(f"Add retained local evidence files for missing source QA ids: {', '.join(missing)}.")
    if watch:
        actions.append(f"Review suggested or invalid evidence files for ids: {', '.join(watch)}.")
    if unmatched_files:
        actions.append("Review unmatched files; rename or relocate only if they are retained real evidence.")
    actions.append("After fixing files, regenerate the manifest and rerun source QA readiness.")
    return actions


def _next_commands(
    *,
    status: EvidenceInboxStatus,
    checklist_file: Path,
    evidence_root: Path,
    manifest_file: Path,
    report_root: Path,
    fill_command: str,
) -> list[str]:
    commands = [
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_evidence_inbox.py "
            f"--data-dir {checklist_file.parent} --report-dir {report_root}"
        ),
        fill_command,
        _manifest_command(
            checklist_file=checklist_file,
            evidence_root=evidence_root,
            manifest_file=manifest_file,
        ),
    ]
    if status != "BLOCK":
        commands.append(
            ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_evidence_readiness.py "
            f"--checklist {checklist_file} "
            f"--worksheet {checklist_file.parent / 'data_source_qa_evidence_worksheet.csv'} "
            f"--answers {checklist_file.parent / 'data_source_qa_answers.json'} "
            f"--evidence-manifest {manifest_file} --require-evidence-manifest "
            f"--output-dir {report_root / 'source_qa'}"
        )
    return commands


def _manifest_command(*, checklist_file: Path, evidence_root: Path, manifest_file: Path) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\write_source_qa_evidence_manifest.py "
        f"--checklist {checklist_file} --evidence-dir {evidence_root} "
        f"--output-dir {manifest_file.parent} --strict"
    )


def _worksheet_fill_args(items: list[SourceQAEvidenceInboxItem]) -> list[SourceQAWorksheetFillArgument]:
    result: list[SourceQAWorksheetFillArgument] = []
    for item in items:
        cli_arg = _SOURCE_EVIDENCE_ARGS.get(item.item_id)
        if cli_arg is None:
            continue
        result.append(_worksheet_fill_arg(item, cli_arg=cli_arg))
    return result


def _worksheet_fill_command_review(
    fill_args: list[SourceQAWorksheetFillArgument],
) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    if not fill_args:
        blockers.append("No source QA evidence arguments are available; generate the source QA checklist first.")
    for item in fill_args:
        if not item.ready:
            blockers.append(
                f"{item.item_id}: {item.source} value is not ready evidence for {item.cli_argument}: {item.message}"
            )
            continue
        if item.status == "WATCH" or item.source == "suggested_file":
            warnings.append(
                f"{item.item_id}: {item.source} requires human confirmation before worksheet fill."
            )
    if blockers:
        status: EvidenceInboxStatus = "BLOCK"
    elif warnings:
        status = "WATCH"
    else:
        status = "PASS"
    return {
        "ready": not blockers,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
    }


def _worksheet_fill_arg(
    item: SourceQAEvidenceInboxItem,
    *,
    cli_arg: str,
) -> SourceQAWorksheetFillArgument:
    if item.matched_files:
        file = item.matched_files[0]
        status: EvidenceInboxStatus = "BLOCK" if file.status == "BLOCK" else "PASS"
        return SourceQAWorksheetFillArgument(
            item_id=item.item_id,
            cli_argument=cli_arg,
            value=file.path,
            source="matched_file",
            exists=file.exists,
            ready=file.exists and status != "BLOCK",
            status=status,
            message=file.message,
        )
    if item.suggested_files:
        file = item.suggested_files[0]
        ready = file.exists and file.status != "BLOCK"
        return SourceQAWorksheetFillArgument(
            item_id=item.item_id,
            cli_argument=cli_arg,
            value=file.path,
            source="suggested_file",
            exists=file.exists,
            ready=ready,
            status="WATCH",
            message="Suggested local file requires human confirmation before use.",
        )
    value = item.target_path or f"<retained-{item.item_id}-evidence>"
    exists = bool(value and Path(value).exists())
    return SourceQAWorksheetFillArgument(
        item_id=item.item_id,
        cli_argument=cli_arg,
        value=value,
        source="target_path" if item.target_path else "placeholder",
        exists=exists,
        ready=False,
        status="BLOCK",
        message=(
            "No matching local evidence file is available yet; this target path is a human placeholder "
            "until retained evidence is placed and rescanned."
        ),
    )


def _worksheet_fill_command(
    *,
    checklist_file: Path,
    worksheet_file: Path,
    data_root: Path,
    fill_args: list[SourceQAWorksheetFillArgument],
) -> str:
    parts = [
        ".\\.venv\\Scripts\\python.exe",
        "examples\\fill_data_source_qa_evidence_worksheet.py",
        "--checklist",
        str(checklist_file),
        "--worksheet",
        str(worksheet_file),
        "--output-dir",
        str(data_root),
        "--vendor",
        "<real-vendor-or-broker>",
        "--terminal",
        "<terminal-product-and-version>",
        "--operator",
        "<export-operator>",
        "--exported-at",
        "<local-export-time>",
        "--price-adjustment",
        "<raw-qfq-or-hfq>",
        "--license-scope",
        "<retained-license-scope>",
        "--reviewed-by",
        "<human-reviewer>",
        "--reviewed-at",
        "<review-date>",
    ]
    for item in fill_args:
        parts.extend([item.cli_argument, item.value])
    return " ".join(_quote_command_part(part) for part in parts)


def _quote_command_part(value: str) -> str:
    text = str(value)
    if not text:
        return '""'
    if any(char.isspace() for char in text) or "<" in text or ">" in text:
        return f'"{text.replace(chr(34), chr(92) + chr(34))}"'
    return text


def _default_target(checklist_file: Path, item_id: str) -> Path:
    return checklist_file.parent / "source_qa_evidence" / _default_file_name(item_id)


def _default_target_from_root(data_root: Path, item_id: str) -> Path:
    return data_root / "source_qa_evidence" / _default_file_name(item_id)


def _default_file_name(item_id: str) -> str:
    names = {
        "source_identity": "source_identity_receipt.png",
        "license_scope": "license_scope_note.pdf",
        "price_adjustment": "price_adjustment_qfq.png",
        "point_in_time": "point_in_time_note.md",
        "manual_signoff": "manual_signoff.md",
    }
    return names.get(item_id, f"{item_id or 'source_qa'}_evidence.txt")


def _acceptable_evidence(item_id: str) -> str:
    values = {
        "source_identity": "Retained receipt, screenshot, PDF, or metadata identifying vendor, terminal/product, operator, and export time.",
        "license_scope": "Retained vendor terms, account permission, invoice, or license note tied to the export account.",
        "price_adjustment": "Retained export setting screenshot or metadata showing raw/qfq/hfq adjustment.",
        "point_in_time": "Vendor PIT documentation or an explicit retained note limiting non-PIT data to OHLCV research only.",
        "manual_signoff": "Attributable human review note with reviewed_by and reviewed_at.",
    }
    return values.get(item_id, "Retained local source evidence tied to the export batch.")


def _unacceptable_evidence(item_id: str) -> str:
    values = {
        "source_identity": "Unlabeled screenshots, generated receipts, or copied vendor names without export timestamp.",
        "license_scope": "Assumed public marketing text, generic terms, or notes without account/vendor context.",
        "price_adjustment": "Unverified qfq labels, mixed adjustment files, or screenshots without the setting visible.",
        "point_in_time": "Vague PIT claims, survivorship-only notes, or after-the-fact fundamentals assertions.",
        "manual_signoff": "Unsigned notes, LLM-generated approvals, or signoff without reviewer/date.",
    }
    return values.get(item_id, "Generated placeholders, weak notes, or unverifiable files.")


def _read_as_of(report_root: Path) -> str:
    for name in ("first_million_daily_brief.json", "source_qa_operator_packet.json", "first_million_pipeline.json"):
        payload = _read_json(report_root / name)
        text = str(payload.get("as_of") or "")
        if text:
            return text
    return ""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except UnicodeDecodeError:
        with path.open("r", newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except OSError:
        return []


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(value or "").lower())


def _cell(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")
