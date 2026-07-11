"""Operator-facing intake kit for first-million evidence collection.

The kit creates instructions and staging directories only. It never writes
source evidence files, market data rows, source QA answers, approvals, or
broker instructions.
"""
from __future__ import annotations

from dataclasses import dataclass
import csv
import json
from pathlib import Path
from typing import Any, Literal

IntakeKitDecision = Literal["PASS", "WATCH", "BLOCK"]

PROHIBITED_ACTIONS = [
    "Do not treat this kit as data evidence, source QA approval, strategy approval, or a profit claim.",
    "Do not put generated placeholder files into source_qa_evidence or real-data CSV paths.",
    "Do not fabricate screenshots, vendor receipts, CSV rows, review notes, or approvals to close gates.",
    "Do not use this kit to bypass deterministic source QA, data intake, market context, candidate, paper, or approval gates.",
    "Do not connect any intake artifact to real broker order submission.",
]


@dataclass(frozen=True, slots=True)
class EvidenceIntakeKitFile:
    item_type: str
    item_id: str
    required: str
    target_path: str
    staging_path: str
    current_state: str
    required_evidence: str
    acceptable_evidence: str
    unacceptable_evidence: str
    validation_command: str
    after_receipt_command: str

    def to_dict(self) -> dict[str, str]:
        return {
            "item_type": self.item_type,
            "item_id": self.item_id,
            "required": self.required,
            "target_path": self.target_path,
            "staging_path": self.staging_path,
            "current_state": self.current_state,
            "required_evidence": self.required_evidence,
            "acceptable_evidence": self.acceptable_evidence,
            "unacceptable_evidence": self.unacceptable_evidence,
            "validation_command": self.validation_command,
            "after_receipt_command": self.after_receipt_command,
        }


@dataclass(frozen=True, slots=True)
class EvidenceIntakeKit:
    decision: IntakeKitDecision
    as_of: str
    report_dir: str
    data_dir: str
    kit_dir: str
    source_qa_evidence_dir: str
    raw_bars_dir: str
    index_dir: str
    file_count: int
    files: list[EvidenceIntakeKitFile]
    command_sequence: list[str]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "as_of": self.as_of,
            "report_dir": self.report_dir,
            "data_dir": self.data_dir,
            "kit_dir": self.kit_dir,
            "source_qa_evidence_dir": self.source_qa_evidence_dir,
            "raw_bars_dir": self.raw_bars_dir,
            "index_dir": self.index_dir,
            "file_count": self.file_count,
            "files": [item.to_dict() for item in self.files],
            "command_sequence": self.command_sequence,
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# First Million Evidence Intake Kit: {self.decision}",
            "",
            f"- As of: `{self.as_of}`",
            f"- Report directory: `{self.report_dir}`",
            f"- Data directory: `{self.data_dir}`",
            f"- Kit directory: `{self.kit_dir}`",
            f"- Source QA evidence inbox: `{self.source_qa_evidence_dir}`",
            f"- Raw bars inbox: `{self.raw_bars_dir}`",
            f"- Index CSV inbox: `{self.index_dir}`",
            f"- Requested files: {self.file_count}",
            "",
            "This kit is a staging checklist. It creates no market data, no source evidence, no approvals, and no broker instructions.",
            "",
            "## File Requests",
            "",
        ]
        if self.files:
            lines.append("| type | id | required | target | staging | state |")
            lines.append("| --- | --- | --- | --- | --- | --- |")
            for item in self.files:
                lines.append(
                    "| `{type}` | `{item}` | `{required}` | `{target}` | `{staging}` | `{state}` |".format(
                        type=item.item_type,
                        item=item.item_id,
                        required=item.required,
                        target=item.target_path,
                        staging=item.staging_path,
                        state=item.current_state,
                    )
                )
        else:
            lines.append("- None.")
        lines.extend(["", "## How To Use"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Command Sequence"])
        for index, command in enumerate(self.command_sequence, start=1):
            lines.extend(["", f"{index}.", "", "```powershell", command, "```"])
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_evidence_intake_kit(
    report_dir: str | Path = "results/first_million",
    *,
    data_dir: str | Path = "data_exports",
    kit_dir: str | Path | None = None,
    as_of: str | None = None,
) -> EvidenceIntakeKit:
    report_root = Path(report_dir)
    data_root = Path(data_dir)
    kit_root = Path(kit_dir) if kit_dir else report_root / "evidence_intake_kit"
    resolved_as_of = str(as_of or _read_as_of(report_root) or "unspecified")
    source_qa_dir = data_root / "source_qa_evidence"
    raw_dir = data_root / "raw"
    index_dir = data_root / "indices"
    files = [
        *_source_qa_requests(report_root=report_root, data_root=data_root, kit_root=kit_root),
        *_data_export_requests(report_root=report_root, data_root=data_root, kit_root=kit_root),
        *_market_index_requests(report_root=report_root, data_root=data_root, kit_root=kit_root),
    ]
    decision = _decision(files)
    return EvidenceIntakeKit(
        decision=decision,
        as_of=resolved_as_of,
        report_dir=str(report_root),
        data_dir=str(data_root),
        kit_dir=str(kit_root),
        source_qa_evidence_dir=str(source_qa_dir),
        raw_bars_dir=str(raw_dir),
        index_dir=str(index_dir),
        file_count=len(files),
        files=files,
        command_sequence=_command_sequence(
            report_root=report_root,
            data_root=data_root,
            as_of=resolved_as_of,
        ),
        next_actions=_next_actions(decision, files),
        prohibited_actions=PROHIBITED_ACTIONS,
    )


def write_evidence_intake_kit(kit: EvidenceIntakeKit, output_dir: str | Path | None = None) -> Path:
    root = Path(output_dir) if output_dir else Path(kit.kit_dir)
    root.mkdir(parents=True, exist_ok=True)
    _write_staging_readmes(kit, root)
    (root / "first_million_evidence_intake_kit.json").write_text(
        json.dumps(kit.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "first_million_evidence_intake_kit.md").write_text(
        kit.to_markdown(),
        encoding="utf-8",
    )
    with (root / "first_million_evidence_intake_manifest.csv").open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        fieldnames = [
            "item_type",
            "item_id",
            "required",
            "target_path",
            "staging_path",
            "current_state",
            "required_evidence",
            "acceptable_evidence",
            "unacceptable_evidence",
            "validation_command",
            "after_receipt_command",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(item.to_dict() for item in kit.files)
    return root


def _source_qa_requests(
    *,
    report_root: Path,
    data_root: Path,
    kit_root: Path,
) -> list[EvidenceIntakeKitFile]:
    rows = _read_csv_rows(report_root / "source_qa_evidence_attachment_plan.csv")
    requests = []
    for row in rows:
        item_id = str(row.get("id") or "").strip()
        if not item_id:
            continue
        target = Path(str(row.get("suggested_file") or ""))
        if not str(target):
            target = data_root / "source_qa_evidence" / f"{item_id}_evidence.txt"
        requests.append(
            EvidenceIntakeKitFile(
                item_type="source_qa_attachment",
                item_id=item_id,
                required="yes",
                target_path=str(target),
                staging_path=str(kit_root / "incoming_source_qa_evidence" / target.name),
                current_state=str(row.get("current_state") or "missing"),
                required_evidence=str(row.get("required_evidence") or ""),
                acceptable_evidence=str(row.get("acceptance_criteria") or ""),
                unacceptable_evidence=str(row.get("do_not_use") or ""),
                validation_command=str(row.get("next_command") or _manifest_command(data_root)),
                after_receipt_command=_source_qa_inbox_command(report_root, data_root),
            )
        )
    return requests


def _data_export_requests(
    *,
    report_root: Path,
    data_root: Path,
    kit_root: Path,
) -> list[EvidenceIntakeKitFile]:
    rows = _read_csv_rows(report_root / "data_export_todo.csv")
    requests = []
    for row in rows:
        file_name = str(row.get("file_name") or "").strip()
        if not file_name:
            continue
        required = "yes" if str(row.get("required") or "").lower() == "yes" else "recommended"
        target_dir = data_root / "raw" if file_name == "bars.csv" else data_root
        target = target_dir / file_name if file_name == "bars.csv" else data_root / file_name
        requests.append(
            EvidenceIntakeKitFile(
                item_type="data_export_csv",
                item_id=file_name,
                required=required,
                target_path=str(target),
                staging_path=str(kit_root / "incoming_data_exports" / file_name),
                current_state=str(row.get("current_state") or ""),
                required_evidence=str(row.get("columns") or ""),
                acceptable_evidence=str(row.get("acceptance_criteria") or ""),
                unacceptable_evidence="Generated template rows, toy examples, stale exports, or mixed adjustment methods.",
                validation_command=_raw_bars_discovery_command(report_root, data_root)
                if file_name == "bars.csv"
                else _pipeline_command(report_root, data_root),
                after_receipt_command=_pipeline_command(report_root, data_root),
            )
        )
    return requests


def _market_index_requests(
    *,
    report_root: Path,
    data_root: Path,
    kit_root: Path,
) -> list[EvidenceIntakeKitFile]:
    discovery = _read_json(report_root / "market_index_discovery.json")
    if str(discovery.get("status") or "").upper() == "PASS":
        return []
    return [
        EvidenceIntakeKitFile(
            item_type="market_index_csv",
            item_id="broad_a_share_index_daily",
            required="recommended",
            target_path=str(data_root / "indices" / "indices.csv"),
            staging_path=str(kit_root / "incoming_market_indices" / "indices.csv"),
            current_state="missing" if not discovery.get("best_candidate") else "needs_review",
            required_evidence="Reviewed broad A-share index daily CSV with date and close columns.",
            acceptable_evidence=(
                "CSI300, CSI500, CSI1000, All-A proxy, or another documented broad A-share index; "
                "long-form index/name/symbol/code columns and breadth fields are allowed."
            ),
            unacceptable_evidence="Single-stock CSVs, index_constituents.csv, generated examples, or unsourced screenshots.",
            validation_command=_market_index_discovery_command(report_root, data_root),
            after_receipt_command=_market_index_discovery_command(report_root, data_root),
        )
    ]


def _decision(files: list[EvidenceIntakeKitFile]) -> IntakeKitDecision:
    if any(item.required == "yes" and item.current_state not in {"present", "pass"} for item in files):
        return "BLOCK"
    if files:
        return "WATCH"
    return "PASS"


def _next_actions(decision: IntakeKitDecision, files: list[EvidenceIntakeKitFile]) -> list[str]:
    if decision == "PASS":
        return [
            "No intake file requests are open; rerun deterministic source QA, data intake, and first-million gates.",
        ]
    required = [item for item in files if item.required == "yes"]
    optional = [item for item in files if item.required != "yes"]
    actions = []
    if required:
        actions.append(
            f"Collect {len(required)} required real evidence/export files; place them in the target paths, not as generated placeholders."
        )
    if optional:
        actions.append(
            f"Collect or explicitly document {len(optional)} recommended audit/context files after required files are handled."
        )
    actions.append(
        "After copying real files, rerun the command sequence; deterministic gates remain the only source of PASS/WATCH/BLOCK."
    )
    return actions


def _command_sequence(*, report_root: Path, data_root: Path, as_of: str) -> list[str]:
    return [
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_first_million_evidence_intake_receiver.py "
            f"--manifest {report_root / 'evidence_intake_kit' / 'first_million_evidence_intake_manifest.csv'} "
            f"--data-dir {data_root} --report-dir {report_root} --as-of {as_of}"
        ),
        _source_qa_inbox_command(report_root, data_root),
        _manifest_command(data_root),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_evidence_readiness.py "
            f"--checklist {data_root / 'data_source_qa.json'} "
            f"--worksheet {data_root / 'data_source_qa_evidence_worksheet.csv'} "
            f"--answers {data_root / 'data_source_qa_answers.json'} "
            f"--evidence-manifest {data_root / 'source_qa_evidence_manifest.json'} "
            f"--require-evidence-manifest --output-dir {report_root / 'source_qa'}"
        ),
        _raw_bars_discovery_command(report_root, data_root),
        _market_index_discovery_command(report_root, data_root).replace("<YYYY-MM-DD>", as_of),
        _pipeline_command(report_root, data_root).replace("<YYYY-MM-DD>", as_of),
    ]


def _source_qa_inbox_command(report_root: Path, data_root: Path) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_evidence_inbox.py "
        f"--data-dir {data_root} --report-dir {report_root}"
    )


def _manifest_command(data_root: Path) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\write_source_qa_evidence_manifest.py "
        f"--checklist {data_root / 'data_source_qa.json'} "
        f"--evidence-dir {data_root / 'source_qa_evidence'} "
        f"--output-dir {data_root} --strict"
    )


def _raw_bars_discovery_command(report_root: Path, data_root: Path) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\run_raw_bars_discovery.py "
        f"--search-dir {data_root / 'raw'} --config config\\research_recent.yaml "
        f"--output-dir {report_root} --data-output-dir {data_root}"
    )


def _market_index_discovery_command(report_root: Path, data_root: Path) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\run_market_index_discovery.py "
        f"--search-dir {data_root / 'indices'} --output-dir {report_root} --as-of <YYYY-MM-DD>"
    )


def _pipeline_command(report_root: Path, data_root: Path) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\run_first_million_pipeline.py "
        "--config config\\research_recent.yaml "
        f"--data-dir {data_root} --output-dir {report_root} "
        f"--source-qa-answers {data_root / 'data_source_qa_answers.json'} "
        f"--source-qa-evidence-manifest {data_root / 'source_qa_evidence_manifest.json'} "
        "--require-source-qa-evidence-manifest --as-of <YYYY-MM-DD> --min-symbols 300 --no-registry"
    )


def _write_staging_readmes(kit: EvidenceIntakeKit, root: Path) -> None:
    sections = {
        "incoming_source_qa_evidence": (
            "Place real retained source QA evidence files here first if you do not want to copy them directly into data_exports/source_qa_evidence. "
            "After review, copy the real files to their target_path values and regenerate source_qa_evidence_manifest.json."
        ),
        "incoming_data_exports": (
            "Place real broker/vendor CSV exports here first. Required bars.csv must eventually be copied to data_exports/raw/bars.csv or passed as --raw-bars-csv."
            " If the vendor provides a zip archive, keep it as retained evidence but extract the raw daily-bars CSV before guarded intake."
        ),
        "incoming_market_indices": (
            "Place reviewed broad A-share index daily CSVs here first. A usable file needs at least date and close columns."
        ),
    }
    for dirname, text in sections.items():
        directory = root / dirname
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "README.md").write_text(
            "# Intake Staging Directory\n\n"
            f"{text}\n\n"
            "Do not create placeholder evidence files in this directory to satisfy gates.\n",
            encoding="utf-8",
        )
    (root / "README.md").write_text(kit.to_markdown(), encoding="utf-8")


def _read_as_of(report_root: Path) -> str:
    for name in ("first_million_daily_brief.json", "first_million_pipeline.json"):
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
