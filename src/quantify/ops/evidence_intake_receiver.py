"""Receive staged first-million evidence files without weakening gates."""
from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from quantify.data.raw_bars_discovery import build_raw_bars_discovery_report
from quantify.data.source_qa import validate_source_qa_attachment
from quantify.market.index_discovery import build_market_index_discovery_report

ReceiveDecision = Literal["PASS", "WATCH", "BLOCK"]

PROHIBITED_ACTIONS = [
    "Do not treat file receipt as source QA approval, data QA approval, strategy approval, or a profit claim.",
    "Do not fabricate source evidence, CSV rows, market rows, review notes, or approvals to close gates.",
    "Do not copy README, worksheet, template, plan, sample, generated, or placeholder files as evidence.",
    "Do not overwrite target files unless --overwrite is explicitly supplied.",
    "Do not connect received files to real broker order submission.",
]


@dataclass(frozen=True, slots=True)
class EvidenceReceiptItem:
    item_type: str
    item_id: str
    required: str
    status: ReceiveDecision
    action: str
    staging_path: str
    target_path: str
    size_bytes: int
    sha256: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_type": self.item_type,
            "item_id": self.item_id,
            "required": self.required,
            "status": self.status,
            "action": self.action,
            "staging_path": self.staging_path,
            "target_path": self.target_path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class EvidenceIntakeReceipt:
    decision: ReceiveDecision
    mode: str
    manifest_path: str
    kit_dir: str
    data_dir: str
    report_dir: str
    as_of: str
    received_count: int
    pending_count: int
    rejected_count: int
    skipped_count: int
    items: list[EvidenceReceiptItem]
    next_commands: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "mode": self.mode,
            "manifest_path": self.manifest_path,
            "kit_dir": self.kit_dir,
            "data_dir": self.data_dir,
            "report_dir": self.report_dir,
            "as_of": self.as_of,
            "received_count": self.received_count,
            "pending_count": self.pending_count,
            "rejected_count": self.rejected_count,
            "skipped_count": self.skipped_count,
            "items": [item.to_dict() for item in self.items],
            "next_commands": self.next_commands,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# First Million Evidence Intake Receipt: {self.decision}",
            "",
            f"- Mode: `{self.mode}`",
            f"- Manifest: `{self.manifest_path}`",
            f"- Kit directory: `{self.kit_dir}`",
            f"- Data directory: `{self.data_dir}`",
            f"- Report directory: `{self.report_dir}`",
            f"- As of: `{self.as_of or 'unspecified'}`",
            f"- Received: {self.received_count}",
            f"- Pending: {self.pending_count}",
            f"- Rejected: {self.rejected_count}",
            f"- Skipped: {self.skipped_count}",
            "",
            "This receipt only records staged-file validation and optional copy actions. Deterministic source QA, raw bars discovery, market context, and first-million gates still own PASS/WATCH/BLOCK.",
            "",
            "## Items",
            "",
        ]
        if self.items:
            lines.append("| status | action | type | id | staging | target | message |")
            lines.append("| --- | --- | --- | --- | --- | --- | --- |")
            for item in self.items:
                lines.append(
                    f"| `{item.status}` | `{item.action}` | `{item.item_type}` | `{item.item_id}` | `{item.staging_path}` | `{item.target_path}` | {_cell(item.message)} |"
                )
        else:
            lines.append("- No intake manifest rows were found.")
        lines.extend(["", "## Next Commands"])
        for command in self.next_commands:
            lines.extend(["", "```powershell", command, "```"])
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def receive_evidence_intake(
    *,
    manifest_path: str | Path = "results/first_million/evidence_intake_kit/first_million_evidence_intake_manifest.csv",
    kit_dir: str | Path | None = None,
    data_dir: str | Path = "data_exports",
    report_dir: str | Path = "results/first_million",
    as_of: str | None = None,
    apply: bool = False,
    overwrite: bool = False,
    encoding: str = "utf-8-sig",
    config_path: str | Path = "config/research_recent.yaml",
    min_symbols: int = 300,
) -> EvidenceIntakeReceipt:
    manifest_file = Path(manifest_path)
    resolved_kit_dir = Path(kit_dir) if kit_dir is not None else manifest_file.parent
    data_root = Path(data_dir)
    report_root = Path(report_dir)
    mode = "apply" if apply else "review"
    rows = _read_manifest_rows(manifest_file, encoding=encoding)
    items: list[EvidenceReceiptItem] = []
    for row in rows:
        items.append(
            _receive_row(
                row,
                apply=apply,
                overwrite=overwrite,
                config_path=config_path,
                data_dir=data_root,
                report_dir=report_root,
                as_of=as_of or "",
                min_symbols=min_symbols,
            )
        )
    decision = _decision(items)
    return EvidenceIntakeReceipt(
        decision=decision,
        mode=mode,
        manifest_path=str(manifest_file),
        kit_dir=str(resolved_kit_dir),
        data_dir=str(data_root),
        report_dir=str(report_root),
        as_of=str(as_of or ""),
        received_count=sum(1 for item in items if item.action == "copied"),
        pending_count=sum(1 for item in items if item.action == "pending"),
        rejected_count=sum(1 for item in items if item.action == "rejected"),
        skipped_count=sum(1 for item in items if item.action in {"would_copy", "exists"}),
        items=items,
        next_commands=_next_commands(report_root=report_root, data_root=data_root, as_of=str(as_of or "")),
        prohibited_actions=PROHIBITED_ACTIONS,
    )


def write_evidence_intake_receipt(
    receipt: EvidenceIntakeReceipt,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "first_million_evidence_intake_receipt.json").write_text(
        json.dumps(receipt.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "first_million_evidence_intake_receipt.md").write_text(receipt.to_markdown(), encoding="utf-8")
    with (root / "first_million_evidence_intake_receipt.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        fieldnames = [
            "item_type",
            "item_id",
            "required",
            "status",
            "action",
            "staging_path",
            "target_path",
            "size_bytes",
            "sha256",
            "message",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(item.to_dict() for item in receipt.items)
    return root


def _receive_row(
    row: dict[str, str],
    *,
    apply: bool,
    overwrite: bool,
    config_path: str | Path,
    data_dir: Path,
    report_dir: Path,
    as_of: str,
    min_symbols: int,
) -> EvidenceReceiptItem:
    item_type = str(row.get("item_type") or "").strip()
    item_id = str(row.get("item_id") or "").strip()
    required = str(row.get("required") or "").strip()
    staging = Path(str(row.get("staging_path") or "").strip())
    target = Path(str(row.get("target_path") or "").strip())

    if not staging.exists():
        alternate, alternate_error = _alternate_bars_staging_candidate(
            item_type=item_type,
            item_id=item_id,
            staging=staging,
        )
        if alternate_error:
            base = _item_base(row, staging=staging, target=target)
            return _item(**base, status="BLOCK", action="rejected", message=alternate_error)
        if alternate is not None:
            staging = alternate

    base = _item_base(row, staging=staging, target=target)

    if not staging.exists():
        return _item(**base, status=_pending_status(required), action="pending", message="Staging file is missing.")
    if not staging.is_file():
        return _item(**base, status="BLOCK", action="rejected", message="Staging path is not a file.")
    if target.exists() and not overwrite:
        return _item(
            **base,
            status="WATCH",
            action="exists",
            message="Target already exists; rerun with --overwrite only after confirming replacement.",
        )

    validation_error = _validate_staged_file(
        item_type=item_type,
        item_id=item_id,
        staging=staging,
        config_path=config_path,
        data_dir=data_dir,
        report_dir=report_dir,
        as_of=as_of,
        min_symbols=min_symbols,
    )
    if validation_error:
        return _item(**base, status="BLOCK", action="rejected", message=validation_error)
    if not apply:
        return _item(**base, status="WATCH", action="would_copy", message="Staging file passed receipt checks; rerun with --apply to copy.")

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(staging, target)
    return _item(**base, status="PASS", action="copied", message="Staging file copied to target path.")


def _validate_staged_file(
    *,
    item_type: str,
    item_id: str,
    staging: Path,
    config_path: str | Path,
    data_dir: Path,
    report_dir: Path,
    as_of: str,
    min_symbols: int,
) -> str:
    if staging.stat().st_size <= 0:
        return "Staging file is empty."
    path_error = _generated_or_staging_path_error(staging)
    if path_error:
        return path_error
    content_error = _text_placeholder_error(staging)
    if content_error:
        return content_error
    if item_type == "source_qa_attachment":
        return _validate_source_attachment_candidate(item_id=item_id, staging=staging)
    if item_type == "data_export_csv" and item_id == "bars.csv":
        return _validate_raw_bars_candidate(
            staging=staging,
            config_path=config_path,
            data_dir=data_dir,
            report_dir=report_dir,
            min_symbols=min_symbols,
        )
    if item_type == "data_export_csv":
        if staging.suffix.lower() != ".csv":
            return "Data export item must be a CSV file."
        return _validate_csv_not_toy(staging)
    if item_type == "market_index_csv":
        return _validate_market_index_candidate(staging=staging, report_dir=report_dir, as_of=as_of)
    return "Unknown intake item type."


def _validate_source_attachment_candidate(*, item_id: str, staging: Path) -> str:
    attachment_error = validate_source_qa_attachment(
        item_id=item_id,
        path_text=str(staging),
        sha256=_sha256(staging),
    )
    return str(attachment_error.get("message") or attachment_error.get("code") or "") if attachment_error else ""


def _validate_raw_bars_candidate(
    *,
    staging: Path,
    config_path: str | Path,
    data_dir: Path,
    report_dir: Path,
    min_symbols: int,
) -> str:
    if staging.suffix.lower() not in {".csv", ".zip"}:
        return "Raw bars item must be a CSV file, or a zip archive that contains an extractable CSV."
    report = build_raw_bars_discovery_report(
        search_dirs=[staging],
        config_path=config_path,
        output_dir=report_dir,
        data_output_dir=data_dir,
        min_symbols=min_symbols,
        encoding="auto",
    )
    if report.status == "BLOCK":
        candidate = report.candidates[0] if report.candidates else None
        return f"Raw bars discovery rejects staging file: {candidate.message if candidate else 'no candidate'}"
    return ""


def _alternate_bars_staging_candidate(
    *,
    item_type: str,
    item_id: str,
    staging: Path,
) -> tuple[Path | None, str]:
    if item_type != "data_export_csv" or item_id != "bars.csv":
        return None, ""
    parent = staging.parent
    if not parent.exists():
        return None, ""
    candidates = sorted(
        [
            path
            for path in parent.iterdir()
            if path.is_file() and path.suffix.lower() in {".csv", ".zip"}
        ],
        key=lambda path: path.name.lower(),
    )
    if not candidates:
        return None, ""
    if len(candidates) > 1:
        names = ", ".join(path.name for path in candidates[:5])
        suffix = "" if len(candidates) <= 5 else ", ..."
        return (
            None,
            "bars.csv staging file is missing and multiple CSV/ZIP candidates were found "
            f"in the staging directory: {names}{suffix}. Keep one file or update the manifest staging_path.",
        )
    return candidates[0], ""


def _validate_market_index_candidate(*, staging: Path, report_dir: Path, as_of: str) -> str:
    if staging.suffix.lower() != ".csv":
        return "Market index item must be a CSV file."
    if not as_of:
        return "Market index receipt requires --as-of for discovery preflight."
    report = build_market_index_discovery_report(
        search_dirs=[staging],
        output_dir=report_dir,
        as_of=as_of,
        encoding="auto",
    )
    if report.status == "BLOCK":
        candidate = report.candidates[0] if report.candidates else None
        findings = "; ".join(candidate.findings) if candidate else "no candidate"
        return f"Market index discovery rejects staging file: {findings}"
    return ""


def _validate_csv_not_toy(staging: Path) -> str:
    text = _read_text_sample(staging)
    if not text:
        return ""
    lowered = text.lower()
    if "sample" in lowered or "template" in lowered or "placeholder" in lowered:
        return "CSV content looks like sample, template, or placeholder material."
    line_count = max(0, len([line for line in text.splitlines() if line.strip()]) - 1)
    if line_count <= 1:
        return "CSV has too few data rows to be retained as an audit export."
    return ""


def _generated_or_staging_path_error(path: Path) -> str:
    name_key = "-".join(re.findall(r"[a-z0-9]+", path.stem.lower()))
    if name_key in {"readme", "data-source-qa-evidence-worksheet", "source-qa-evidence-attachment-plan"}:
        return "Staging file path looks like a generated workflow aid."
    tokens = set(re.findall(r"[a-z0-9]+", path.name.lower()))
    if tokens & {"sample", "template", "placeholder", "generated", "mock", "fake", "todo"}:
        return "Staging file name looks like sample/template/placeholder material."
    return ""


def _text_placeholder_error(path: Path) -> str:
    if path.suffix.lower() not in {".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".log"}:
        return ""
    text = _read_text_sample(path)
    if not text:
        return "Text staging file is empty or unreadable."
    normalized = " ".join(text.strip().lower().replace("_", "-").split())
    if not normalized:
        return "Text staging file is empty."
    bad_phrases = {
        "placeholder evidence",
        "sample evidence",
        "generated placeholder",
        "generated receipt",
        "generated sample",
        "fake evidence",
        "mock evidence",
        "todo evidence",
    }
    if normalized in {"todo", "tbd", "placeholder", "sample", "template", "evidence"}:
        return "Text staging file looks like placeholder material."
    for phrase in bad_phrases:
        if phrase in normalized:
            return "Text staging file looks like generated or placeholder evidence."
    return ""


def _read_text_sample(path: Path, sample_bytes: int = 8192) -> str:
    try:
        raw = path.read_bytes()[:sample_bytes]
    except OSError:
        return ""
    if b"\x00" in raw:
        return ""
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return ""


def _item_base(row: dict[str, str], *, staging: Path, target: Path) -> dict[str, Any]:
    return {
        "item_type": str(row.get("item_type") or "").strip(),
        "item_id": str(row.get("item_id") or "").strip(),
        "required": str(row.get("required") or "").strip(),
        "staging_path": str(staging),
        "target_path": str(target),
        "size_bytes": staging.stat().st_size if staging.exists() and staging.is_file() else 0,
        "sha256": _sha256(staging) if staging.exists() and staging.is_file() else "",
    }


def _item(
    *,
    item_type: str,
    item_id: str,
    required: str,
    staging_path: str,
    target_path: str,
    size_bytes: int,
    sha256: str,
    status: ReceiveDecision,
    action: str,
    message: str,
) -> EvidenceReceiptItem:
    return EvidenceReceiptItem(
        item_type=item_type,
        item_id=item_id,
        required=required,
        status=status,
        action=action,
        staging_path=staging_path,
        target_path=target_path,
        size_bytes=size_bytes,
        sha256=sha256,
        message=message,
    )


def _read_manifest_rows(path: Path, *, encoding: str) -> list[dict[str, str]]:
    try:
        with path.open("r", newline="", encoding=encoding) as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except UnicodeDecodeError:
        with path.open("r", newline="", encoding="utf-8") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except OSError:
        return []


def _decision(items: list[EvidenceReceiptItem]) -> ReceiveDecision:
    if any(item.status == "BLOCK" for item in items):
        return "BLOCK"
    if any(item.status == "WATCH" for item in items):
        return "WATCH"
    return "PASS"


def _pending_status(required: str) -> ReceiveDecision:
    return "BLOCK" if str(required).lower() == "yes" else "WATCH"


def _next_commands(*, report_root: Path, data_root: Path, as_of: str) -> list[str]:
    date_arg = as_of or "<YYYY-MM-DD>"
    return [
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_evidence_inbox.py "
            f"--data-dir {data_root} --report-dir {report_root}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_source_qa_evidence_manifest.py "
            f"--checklist {data_root / 'data_source_qa.json'} "
            f"--evidence-dir {data_root / 'source_qa_evidence'} --output-dir {data_root} --strict"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_raw_bars_discovery.py "
            f"--search-dir {data_root / 'raw'} --config config\\research_recent.yaml "
            f"--output-dir {report_root} --data-output-dir {data_root}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_market_index_discovery.py "
            f"--search-dir {data_root / 'indices'} --output-dir {report_root} --as-of {date_arg}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_first_million_pipeline.py "
            "--config config\\research_recent.yaml "
            f"--data-dir {data_root} --output-dir {report_root} "
            f"--source-qa-answers {data_root / 'data_source_qa_answers.json'} "
            f"--source-qa-evidence-manifest {data_root / 'source_qa_evidence_manifest.json'} "
            f"--require-source-qa-evidence-manifest --as-of {date_arg} --min-symbols 300 --no-registry"
        ),
    ]


def _sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cell(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")
