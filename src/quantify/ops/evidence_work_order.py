"""Batch-level work order for first-million evidence collection.

The work order rolls existing deterministic reports into an execution sequence.
It does not create evidence, mutate source QA answers, import data, approve
strategies, or produce broker instructions.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

WorkOrderDecision = Literal["PASS", "WATCH", "BLOCK"]

PROHIBITED_ACTIONS = [
    "Do not treat this work order as data evidence, source QA approval, strategy approval, or a profit claim.",
    "Do not close a batch without changing the underlying real evidence or data artifact.",
    "Do not fabricate source QA worksheet rows, evidence files, market CSVs, review notes, or approvals.",
    "Do not use this work order to bypass deterministic PASS/WATCH/BLOCK gates.",
    "Do not connect this workflow to real broker order submission.",
]


@dataclass(frozen=True, slots=True)
class EvidenceWorkBatch:
    sequence: int
    batch_id: str
    priority: str
    status: str
    title: str
    source_artifact: str
    target_artifact: str
    item_count: int
    sample_items: list[str]
    acceptance_criteria: str
    command_after_completion: str
    gate_note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "batch_id": self.batch_id,
            "priority": self.priority,
            "status": self.status,
            "title": self.title,
            "source_artifact": self.source_artifact,
            "target_artifact": self.target_artifact,
            "item_count": self.item_count,
            "sample_items": self.sample_items,
            "acceptance_criteria": self.acceptance_criteria,
            "command_after_completion": self.command_after_completion,
            "gate_note": self.gate_note,
        }


@dataclass(frozen=True, slots=True)
class EvidenceWorkOrder:
    decision: WorkOrderDecision
    as_of: str
    report_dir: str
    data_dir: str
    next_batch_id: str
    batch_count: int
    open_batch_count: int
    batches: list[EvidenceWorkBatch]
    command_sequence: list[str]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "as_of": self.as_of,
            "report_dir": self.report_dir,
            "data_dir": self.data_dir,
            "next_batch_id": self.next_batch_id,
            "batch_count": self.batch_count,
            "open_batch_count": self.open_batch_count,
            "batches": [batch.to_dict() for batch in self.batches],
            "command_sequence": self.command_sequence,
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# First Million Evidence Work Order: {self.decision}",
            "",
            f"- As of: `{self.as_of}`",
            f"- Report directory: `{self.report_dir}`",
            f"- Data directory: `{self.data_dir}`",
            f"- Next batch: `{self.next_batch_id or 'none'}`",
            f"- Open batches: {self.open_batch_count}",
            "",
            "This work order is a batch-level execution view over existing deterministic evidence reports. It cannot approve data, strategies, paper trading, or live trading.",
            "",
            "## Batches",
            "",
        ]
        if self.batches:
            lines.append("| seq | status | priority | batch | items | target | command |")
            lines.append("| ---: | --- | --- | --- | ---: | --- | --- |")
            for batch in self.batches:
                lines.append(
                    f"| {batch.sequence} | `{batch.status}` | `{batch.priority}` | `{batch.batch_id}` | {batch.item_count} | `{batch.target_artifact}` | `{batch.command_after_completion}` |"
                )
        else:
            lines.append("- None.")
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Command Sequence"])
        for index, command in enumerate(self.command_sequence, start=1):
            lines.extend(["", f"{index}.", "", "```powershell", command, "```"])
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_evidence_work_order(
    report_dir: str | Path = "results/first_million",
    *,
    data_dir: str | Path = "data_exports",
    as_of: str | None = None,
) -> EvidenceWorkOrder:
    report_root = Path(report_dir)
    data_root = Path(data_dir)
    resolved_as_of = str(as_of or _read_as_of(report_root) or "unspecified")
    handoff = _read_json(report_root / "operator_handoff_status.json")
    kit = _read_json(report_root / "evidence_intake_kit" / "first_million_evidence_intake_kit.json")
    batches = _batches(report_root=report_root, data_root=data_root, handoff=handoff, kit=kit, as_of=resolved_as_of)
    decision = _decision(batches)
    open_batches = [batch for batch in batches if batch.status in {"BLOCK", "WATCH"}]
    next_batch = open_batches[0].batch_id if open_batches else ""
    return EvidenceWorkOrder(
        decision=decision,
        as_of=resolved_as_of,
        report_dir=str(report_root),
        data_dir=str(data_root),
        next_batch_id=next_batch,
        batch_count=len(batches),
        open_batch_count=len(open_batches),
        batches=batches,
        command_sequence=_command_sequence(batches, report_root=report_root, data_root=data_root, as_of=resolved_as_of),
        next_actions=_next_actions(open_batches),
        prohibited_actions=PROHIBITED_ACTIONS,
    )


def write_evidence_work_order(order: EvidenceWorkOrder, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "first_million_evidence_work_order.json").write_text(
        json.dumps(order.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "first_million_evidence_work_order.md").write_text(order.to_markdown(), encoding="utf-8")
    with (root / "first_million_evidence_work_order.csv").open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        fieldnames = [
            "sequence",
            "batch_id",
            "priority",
            "status",
            "title",
            "source_artifact",
            "target_artifact",
            "item_count",
            "sample_items",
            "acceptance_criteria",
            "command_after_completion",
            "gate_note",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for batch in order.batches:
            row = batch.to_dict()
            row["sample_items"] = "; ".join(batch.sample_items)
            writer.writerow(row)
    return root


def _batches(
    *,
    report_root: Path,
    data_root: Path,
    handoff: dict[str, Any],
    kit: dict[str, Any],
    as_of: str,
) -> list[EvidenceWorkBatch]:
    files = [item for item in kit.get("files", []) or [] if isinstance(item, dict)]
    rows_by_type = _operator_rows_by_type(report_root / "operator_handoff.csv")
    return [
        _worksheet_batch(rows_by_type.get("source_qa_worksheet", []), data_root=data_root),
        _attachment_batch(files, rows_by_type.get("source_qa_attachment", []), data_root=data_root),
        _raw_bars_batch(files, report_root=report_root, data_root=data_root),
        _recommended_exports_batch(files, report_root=report_root, data_root=data_root),
        _market_index_batch(files, report_root=report_root, data_root=data_root, as_of=as_of),
        _final_verification_batch(report_root=report_root, data_root=data_root, as_of=as_of, handoff=handoff),
    ]


def _worksheet_batch(rows: list[dict[str, str]], *, data_root: Path) -> EvidenceWorkBatch:
    open_rows = [row for row in rows if _open(row)]
    command = str(open_rows[0].get("next_command") or "") if open_rows else _worksheet_command(data_root)
    return EvidenceWorkBatch(
        sequence=1,
        batch_id="source_qa_worksheet",
        priority="P0" if open_rows else "P2",
        status="BLOCK" if open_rows else "PASS",
        title="Fill source QA worksheet rows from retained evidence.",
        source_artifact="source_qa_worksheet_todo.csv",
        target_artifact=str(data_root / "data_source_qa_evidence_worksheet.csv"),
        item_count=len(open_rows),
        sample_items=[_row_item(row) for row in open_rows[:8]],
        acceptance_criteria="Worksheet preflight is not BLOCK, then data_source_qa_answers.json is regenerated from the filled worksheet.",
        command_after_completion=command,
        gate_note=(
            "Worksheet content must come from real export evidence. "
            "fill_data_source_qa_evidence_worksheet.py is only a typing aid; generated answers cannot clear source QA."
        ),
    )


def _attachment_batch(
    files: list[dict[str, Any]],
    rows: list[dict[str, str]],
    *,
    data_root: Path,
) -> EvidenceWorkBatch:
    attachment_files = [item for item in files if item.get("item_type") == "source_qa_attachment"]
    open_files = [item for item in attachment_files if str(item.get("current_state") or "").lower() not in {"present", "pass"}]
    command = _manifest_command(data_root)
    return EvidenceWorkBatch(
        sequence=2,
        batch_id="source_qa_attachments",
        priority="P0" if open_files else "P2",
        status="BLOCK" if open_files else "PASS",
        title="Attach retained source QA evidence files and regenerate manifest.",
        source_artifact="first_million_evidence_intake_manifest.csv",
        target_artifact=str(data_root / "source_qa_evidence_manifest.json"),
        item_count=len(open_files),
        sample_items=[str(item.get("item_id") or "") for item in open_files[:8]]
        or [_row_item(row) for row in rows[:8]],
        acceptance_criteria="source_qa_evidence_manifest.json includes retained non-placeholder files and strict source QA review accepts them.",
        command_after_completion=command,
        gate_note="Attachment presence is not approval; source QA readiness still decides validity.",
    )


def _raw_bars_batch(
    files: list[dict[str, Any]],
    *,
    report_root: Path,
    data_root: Path,
) -> EvidenceWorkBatch:
    bars = next((item for item in files if item.get("item_type") == "data_export_csv" and item.get("item_id") == "bars.csv"), {})
    open_item = bool(bars) and str(bars.get("current_state") or "").lower() not in {"present", "pass"}
    return EvidenceWorkBatch(
        sequence=3,
        batch_id="raw_bars_csv",
        priority="P0" if open_item else "P2",
        status="BLOCK" if open_item else "PASS",
        title="Replace template OHLCV with real recent A-share daily bars.",
        source_artifact="data_export_todo.csv",
        target_artifact=str(data_root / "raw" / "bars.csv"),
        item_count=1 if open_item else 0,
        sample_items=["bars.csv"] if open_item else [],
        acceptance_criteria="raw_bars_discovery.json lists a non-template, schema-valid daily bars candidate with enough configured coverage.",
        command_after_completion=_raw_bars_command(report_root, data_root),
        gate_note="A mapped CSV preview is insufficient if rows are template, stale, or not traceable.",
    )


def _recommended_exports_batch(
    files: list[dict[str, Any]],
    *,
    report_root: Path,
    data_root: Path,
) -> EvidenceWorkBatch:
    recommended = [
        item
        for item in files
        if item.get("item_type") == "data_export_csv"
        and item.get("item_id") != "bars.csv"
        and str(item.get("current_state") or "").lower() not in {"present", "pass"}
    ]
    return EvidenceWorkBatch(
        sequence=4,
        batch_id="recommended_audit_csvs",
        priority="P1" if recommended else "P2",
        status="WATCH" if recommended else "PASS",
        title="Attach recommended audit CSVs from the same export batch.",
        source_artifact="data_export_todo.csv",
        target_artifact=str(data_root),
        item_count=len(recommended),
        sample_items=[str(item.get("item_id") or "") for item in recommended[:8]],
        acceptance_criteria="Recommended audit files are present from the same batch, or their absence is explicitly documented in source QA limitations.",
        command_after_completion=_pipeline_command(report_root, data_root, "<YYYY-MM-DD>"),
        gate_note="Recommended files improve audit/execution checks but cannot override required OHLCV/source gates.",
    )


def _market_index_batch(
    files: list[dict[str, Any]],
    *,
    report_root: Path,
    data_root: Path,
    as_of: str,
) -> EvidenceWorkBatch:
    index_item = next((item for item in files if item.get("item_type") == "market_index_csv"), {})
    open_item = bool(index_item) and str(index_item.get("current_state") or "").lower() not in {"present", "pass"}
    return EvidenceWorkBatch(
        sequence=5,
        batch_id="market_index_csv",
        priority="P1" if open_item else "P2",
        status="WATCH" if open_item else "PASS",
        title="Attach reviewed broad A-share index CSV for market snapshot fallback.",
        source_artifact="market_index_discovery.json",
        target_artifact=str(data_root / "indices" / "indices.csv"),
        item_count=1 if open_item else 0,
        sample_items=["broad_a_share_index_daily"] if open_item else [],
        acceptance_criteria="market_index_discovery.json finds a reviewed broad-index CSV; snapshot-only context remains advisory WATCH.",
        command_after_completion=_market_index_command(report_root, data_root, as_of),
        gate_note="Index CSV discovery is not market evidence and cannot replace cache-derived market_regime.json.",
    )


def _final_verification_batch(
    *,
    report_root: Path,
    data_root: Path,
    as_of: str,
    handoff: dict[str, Any],
) -> EvidenceWorkBatch:
    status = str(handoff.get("status") or "BLOCK").upper()
    open_count = int(handoff.get("open_task_count") or 0)
    return EvidenceWorkBatch(
        sequence=6,
        batch_id="rerun_deterministic_gates",
        priority="P0" if status == "BLOCK" else "P1",
        status="BLOCK" if status == "BLOCK" else ("WATCH" if status == "WATCH" else "PASS"),
        title="Rerun deterministic source QA, discovery, intake, and first-million gates.",
        source_artifact="first_million_evidence_work_order.json",
        target_artifact=str(report_root / "first_million_pipeline.json"),
        item_count=open_count,
        sample_items=["first_million_pipeline", "source_qa_evidence_readiness", "candidate_experiment_readiness"],
        acceptance_criteria="first_million_pipeline.json records updated evidence; candidate research remains blocked unless all upstream gates allow it.",
        command_after_completion=_pipeline_command(report_root, data_root, as_of),
        gate_note="This verification batch cannot upgrade gates by itself; it only reruns the owners.",
    )


def _decision(batches: list[EvidenceWorkBatch]) -> WorkOrderDecision:
    if any(batch.status == "BLOCK" for batch in batches):
        return "BLOCK"
    if any(batch.status == "WATCH" for batch in batches):
        return "WATCH"
    return "PASS"


def _command_sequence(
    batches: list[EvidenceWorkBatch],
    *,
    report_root: Path,
    data_root: Path,
    as_of: str,
) -> list[str]:
    commands = [batch.command_after_completion for batch in batches if batch.command_after_completion]
    commands.extend(
        [
            _source_readiness_command(report_root, data_root),
            _pipeline_command(report_root, data_root, as_of),
        ]
    )
    return _dedupe([command for command in commands if command.strip()])


def _next_actions(open_batches: list[EvidenceWorkBatch]) -> list[str]:
    if not open_batches:
        return ["No open evidence batches remain; rerun first-million pipeline and review deterministic gates."]
    first = open_batches[0]
    return [
        f"Start with `{first.batch_id}`: {first.title}",
        f"Done when: {first.acceptance_criteria}",
        f"Then run: {first.command_after_completion}",
        "Keep downstream strategy research blocked until deterministic gates update from real evidence.",
    ]


def _operator_rows_by_type(path: Path) -> dict[str, list[dict[str, str]]]:
    rows: dict[str, list[dict[str, str]]] = {}
    for row in _read_csv_rows(path):
        rows.setdefault(str(row.get("task_type") or ""), []).append(row)
    return rows


def _open(row: dict[str, str]) -> bool:
    return str(row.get("status") or "").upper() in {"BLOCK", "WATCH"}


def _row_item(row: dict[str, str]) -> str:
    if row.get("row_number"):
        return f"row {row.get('row_number')}: {row.get('id')}"
    return str(row.get("id") or row.get("file_name") or row.get("target") or "")


def _worksheet_command(data_root: Path) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\run_data_source_qa_worksheet_preflight.py "
        f"--checklist {data_root / 'data_source_qa.json'} "
        f"--worksheet {data_root / 'data_source_qa_evidence_worksheet.csv'} "
        f"--output-dir {data_root}"
    )


def _manifest_command(data_root: Path) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\write_source_qa_evidence_manifest.py "
        f"--checklist {data_root / 'data_source_qa.json'} "
        f"--evidence-dir {data_root / 'source_qa_evidence'} --output-dir {data_root} --strict"
    )


def _raw_bars_command(report_root: Path, data_root: Path) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\run_raw_bars_discovery.py "
        f"--search-dir {data_root / 'raw'} --config config\\research_recent.yaml "
        f"--output-dir {report_root} --data-output-dir {data_root}"
    )


def _market_index_command(report_root: Path, data_root: Path, as_of: str) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\run_market_index_discovery.py "
        f"--search-dir {data_root / 'indices'} --output-dir {report_root} --as-of {as_of}"
    )


def _source_readiness_command(report_root: Path, data_root: Path) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_evidence_readiness.py "
        f"--checklist {data_root / 'data_source_qa.json'} "
        f"--worksheet {data_root / 'data_source_qa_evidence_worksheet.csv'} "
        f"--answers {data_root / 'data_source_qa_answers.json'} "
        f"--evidence-manifest {data_root / 'source_qa_evidence_manifest.json'} "
        f"--require-evidence-manifest --output-dir {report_root / 'source_qa'}"
    )


def _pipeline_command(report_root: Path, data_root: Path, as_of: str) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\run_first_million_pipeline.py "
        "--config config\\research_recent.yaml "
        f"--data-dir {data_root} --output-dir {report_root} "
        f"--source-qa-answers {data_root / 'data_source_qa_answers.json'} "
        f"--source-qa-evidence-manifest {data_root / 'source_qa_evidence_manifest.json'} "
        f"--require-source-qa-evidence-manifest --as-of {as_of} --min-symbols 300 --no-registry"
    )


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


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
