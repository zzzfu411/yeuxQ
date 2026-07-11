"""Combined first-million data/source-QA intake status.

This report is an operator map over existing deterministic artifacts. It does
not create evidence, import data, approve strategies, or authorize broker use.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

DataIntakeDecision = Literal["PASS", "WATCH", "BLOCK"]

PROHIBITED_ACTIONS = [
    "Do not treat this status report as source QA approval, data approval, strategy evidence, or a profit claim.",
    "Do not close intake items without changing the underlying retained evidence or real data files.",
    "Do not fabricate source QA worksheet rows, evidence files, market CSVs, raw bars, review notes, or approvals.",
    "Do not use this report to bypass deterministic PASS/WATCH/BLOCK gates.",
    "Do not connect this workflow to real broker order submission.",
]


@dataclass(frozen=True, slots=True)
class DataIntakeStatusItem:
    sequence: int
    area: str
    status: DataIntakeDecision
    current_state: str
    target: str
    next_action: str
    next_command: str
    source_artifact: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "area": self.area,
            "status": self.status,
            "current_state": self.current_state,
            "target": self.target,
            "next_action": self.next_action,
            "next_command": self.next_command,
            "source_artifact": self.source_artifact,
        }


@dataclass(frozen=True, slots=True)
class DataIntakeStatusReport:
    decision: DataIntakeDecision
    as_of: str
    report_dir: str
    data_dir: str
    next_area: str
    next_action: str
    next_command: str
    summary: dict[str, Any]
    items: list[DataIntakeStatusItem]
    command_sequence: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "as_of": self.as_of,
            "report_dir": self.report_dir,
            "data_dir": self.data_dir,
            "next_area": self.next_area,
            "next_action": self.next_action,
            "next_command": self.next_command,
            "summary": self.summary,
            "items": [item.to_dict() for item in self.items],
            "command_sequence": self.command_sequence,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Data Intake Status: {self.decision}",
            "",
            f"- As of: `{self.as_of}`",
            f"- Report directory: `{self.report_dir}`",
            f"- Data directory: `{self.data_dir}`",
            f"- Next area: `{self.next_area or 'none'}`",
            f"- Next action: {self.next_action or 'None.'}",
            "",
            "This report is a combined operator view over existing deterministic artifacts. It cannot approve data, strategies, paper trading, live trading, or broker orders.",
            "",
            "## Summary",
            "",
            "| key | value |",
            "| --- | --- |",
        ]
        for key, value in self.summary.items():
            lines.append(f"| `{key}` | `{_cell(value)}` |")
        lines.extend(["", "## Intake Items", ""])
        if self.items:
            lines.append("| seq | status | area | state | target | next action |")
            lines.append("| ---: | --- | --- | --- | --- | --- |")
            for item in self.items:
                lines.append(
                    f"| {item.sequence} | `{item.status}` | `{item.area}` | `{_cell(item.current_state)}` | `{_cell(item.target)}` | {_cell(item.next_action)} |"
                )
        else:
            lines.append("- None.")
        if self.next_command:
            lines.extend(["", "## Next Command", "", "```powershell", self.next_command, "```"])
        lines.extend(["", "## Command Sequence"])
        for command in self.command_sequence:
            lines.extend(["", "```powershell", command, "```"])
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_data_intake_status(
    report_dir: str | Path = "results/first_million",
    *,
    data_dir: str | Path = "data_exports",
    as_of: str | None = None,
) -> DataIntakeStatusReport:
    report_root = Path(report_dir)
    data_root = Path(data_dir)
    raw_discovery = _read_json(report_root / "raw_bars_discovery.json")
    evidence_inbox = _read_json(report_root / "source_qa_evidence_inbox.json")
    source_readiness = _read_json(report_root / "source_qa" / "source_qa_evidence_readiness.json")
    source_closeout = _read_json(report_root / "source_qa_closeout.json")
    ohlcv_closeout = _read_json(report_root / "ohlcv_intake_closeout.json")
    work_order = _read_json(report_root / "first_million_evidence_work_order.json")
    operator = _read_json(report_root / "operator_handoff_status.json")
    answers_path = data_root / "data_source_qa_answers.json"
    manifest_path = data_root / "source_qa_evidence_manifest.json"
    worksheet_path = data_root / "data_source_qa_evidence_worksheet.csv"

    items = [
        _work_order_item(work_order, operator, report_root=report_root),
        _source_evidence_item(evidence_inbox, data_root=data_root, report_root=report_root),
        _worksheet_fill_item(evidence_inbox, worksheet_path=worksheet_path, report_root=report_root),
        _answers_item(source_readiness, answers_path=answers_path, report_root=report_root),
        _manifest_item(source_readiness, manifest_path=manifest_path, report_root=report_root),
        _raw_bars_item(raw_discovery, data_root=data_root, report_root=report_root),
        _source_closeout_item(source_closeout, report_root=report_root),
        _ohlcv_closeout_item(ohlcv_closeout, report_root=report_root),
    ]
    items = [item for item in items if item.area]
    decision = _decision(items)
    open_items = [item for item in items if item.status in {"BLOCK", "WATCH"}]
    next_item = open_items[0] if open_items else None
    resolved_as_of = str(as_of or _read_as_of(report_root) or "unspecified")
    command_sequence = _command_sequence(items, report_root=report_root, data_root=data_root, as_of=resolved_as_of)
    return DataIntakeStatusReport(
        decision=decision,
        as_of=resolved_as_of,
        report_dir=str(report_root),
        data_dir=str(data_root),
        next_area=next_item.area if next_item else "",
        next_action=next_item.next_action if next_item else "All intake status items are PASS; rerun deterministic gates before research promotion.",
        next_command=next_item.next_command if next_item else "",
        summary=_summary(
            raw_discovery=raw_discovery,
            evidence_inbox=evidence_inbox,
            source_readiness=source_readiness,
            source_closeout=source_closeout,
            ohlcv_closeout=ohlcv_closeout,
            work_order=work_order,
            worksheet_path=worksheet_path,
            answers_path=answers_path,
            manifest_path=manifest_path,
        ),
        items=items,
        command_sequence=command_sequence,
        prohibited_actions=PROHIBITED_ACTIONS,
    )


def write_data_intake_status(report: DataIntakeStatusReport, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "data_intake_status.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "data_intake_status.md").write_text(report.to_markdown(), encoding="utf-8")
    with (root / "data_intake_status.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        fieldnames = [
            "sequence",
            "area",
            "status",
            "current_state",
            "target",
            "next_action",
            "next_command",
            "source_artifact",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(item.to_dict() for item in report.items)
    return root


def _work_order_item(
    payload: dict[str, Any],
    operator: dict[str, Any],
    *,
    report_root: Path,
) -> DataIntakeStatusItem:
    status = _status(payload.get("decision"), missing=_status(operator.get("status"), missing="BLOCK"))
    next_batch = str(payload.get("next_batch_id") or "")
    batches = [item for item in payload.get("batches", []) or [] if isinstance(item, dict)]
    batch = next((item for item in batches if str(item.get("batch_id") or "") == next_batch), batches[0] if batches else {})
    command = str(batch.get("command_after_completion") or "")
    action = str(batch.get("title") or "")
    if not action:
        batch_payload = operator.get("next_batch") if isinstance(operator.get("next_batch"), dict) else {}
        action = str(batch_payload.get("acceptance_criteria") or "Refresh evidence work order after changing files.")
        command = command or str(batch_payload.get("next_command") or "")
        next_batch = next_batch or str(batch_payload.get("task_type") or "")
    return DataIntakeStatusItem(
        sequence=1,
        area="operator_next_batch",
        status=_normalize(status),
        current_state=f"next_batch={next_batch or 'none'}, open_batches={_int(payload.get('open_batch_count'))}",
        target=str(batch.get("target_artifact") or "first_million evidence queue"),
        next_action=action or "Review first_million_evidence_work_order.json.",
        next_command=command,
        source_artifact=str(report_root / "first_million_evidence_work_order.json"),
    )


def _source_evidence_item(
    payload: dict[str, Any],
    *,
    data_root: Path,
    report_root: Path,
) -> DataIntakeStatusItem:
    missing = _int(payload.get("missing_item_count"))
    invalid = _int(payload.get("invalid_file_count"))
    matched = _int(payload.get("matched_item_count"))
    status = _normalize(_status(payload.get("status"), missing="BLOCK"))
    if missing or invalid:
        action = (
            f"Place retained source QA evidence files; missing={missing}, invalid={invalid}. "
            "Do not use README, template, or generated files as evidence."
        )
    else:
        action = "Regenerate strict source QA evidence manifest from retained local files."
    return DataIntakeStatusItem(
        sequence=2,
        area="source_qa_evidence_files",
        status=status,
        current_state=f"matched={matched}, missing={missing}, invalid={invalid}",
        target=str(data_root / "source_qa_evidence"),
        next_action=action,
        next_command=_first_command(payload, default=_inbox_command(data_root, report_root)),
        source_artifact=str(report_root / "source_qa_evidence_inbox.json"),
    )


def _worksheet_fill_item(
    payload: dict[str, Any],
    *,
    worksheet_path: Path,
    report_root: Path,
) -> DataIntakeStatusItem:
    ready = bool(payload.get("worksheet_fill_command_ready"))
    status = _normalize(_status(payload.get("worksheet_fill_command_status"), missing="BLOCK"))
    blockers = [str(item) for item in payload.get("worksheet_fill_command_blockers", []) or [] if str(item).strip()]
    command = str(payload.get("worksheet_fill_command") or "")
    if ready:
        action = "Run the worksheet fill command after replacing metadata placeholders from retained records."
        next_command = command
    else:
        action = blockers[0] if blockers else "Worksheet fill command is not ready; retained evidence args are missing."
        next_command = _inbox_command(worksheet_path.parent, report_root)
    return DataIntakeStatusItem(
        sequence=3,
        area="source_qa_worksheet_fill_command",
        status=status,
        current_state=f"ready={str(ready).lower()}, blockers={len(blockers)}",
        target=str(worksheet_path),
        next_action=action,
        next_command=next_command,
        source_artifact=str(report_root / "source_qa_evidence_inbox.json"),
    )


def _answers_item(
    source_readiness: dict[str, Any],
    *,
    answers_path: Path,
    report_root: Path,
) -> DataIntakeStatusItem:
    section = _section(source_readiness, "answers_preflight")
    status = _normalize(_status(section.get("status"), missing=("PASS" if _json_has_content(answers_path) else "BLOCK")))
    blockers = [str(item) for item in section.get("blockers", []) or [] if str(item).strip()]
    if status == "PASS":
        action = "Source QA answers are present; strict review still decides validity."
    else:
        action = blockers[0] if blockers else "Generate data_source_qa_answers.json only from a filled, reviewed worksheet."
    return DataIntakeStatusItem(
        sequence=4,
        area="source_qa_answers",
        status=status,
        current_state=f"exists={str(answers_path.exists()).lower()}, nonempty={str(_json_has_content(answers_path)).lower()}",
        target=str(answers_path),
        next_action=action,
        next_command=(
            ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa_answers.py "
            f"--checklist {answers_path.parent / 'data_source_qa.json'} "
            f"--worksheet {answers_path.parent / 'data_source_qa_evidence_worksheet.csv'} "
            f"--output {answers_path} "
            f"--evidence-manifest {answers_path.parent / 'source_qa_evidence_manifest.json'} "
            "--require-evidence-manifest"
        ),
        source_artifact=str(report_root / "source_qa" / "source_qa_evidence_readiness.json"),
    )


def _manifest_item(
    source_readiness: dict[str, Any],
    *,
    manifest_path: Path,
    report_root: Path,
) -> DataIntakeStatusItem:
    section = _section(source_readiness, "manifest_preflight")
    status = _normalize(_status(section.get("status"), missing=("PASS" if _json_has_content(manifest_path) else "BLOCK")))
    blockers = [str(item) for item in section.get("blockers", []) or [] if str(item).strip()]
    action = "Strict source QA evidence manifest is present; rerun readiness." if status == "PASS" else (
        blockers[0] if blockers else "Generate source_qa_evidence_manifest.json from retained local evidence files."
    )
    return DataIntakeStatusItem(
        sequence=5,
        area="source_qa_evidence_manifest",
        status=status,
        current_state=f"exists={str(manifest_path.exists()).lower()}, nonempty={str(_json_has_content(manifest_path)).lower()}",
        target=str(manifest_path),
        next_action=action,
        next_command=(
            ".\\.venv\\Scripts\\python.exe examples\\write_source_qa_evidence_manifest.py "
            f"--checklist {manifest_path.parent / 'data_source_qa.json'} "
            f"--evidence-dir {manifest_path.parent / 'source_qa_evidence'} "
            f"--output-dir {manifest_path.parent} --strict"
        ),
        source_artifact=str(report_root / "source_qa" / "source_qa_evidence_readiness.json"),
    )


def _raw_bars_item(
    payload: dict[str, Any],
    *,
    data_root: Path,
    report_root: Path,
) -> DataIntakeStatusItem:
    status = _normalize(_status(payload.get("status"), missing="BLOCK"))
    best = str(payload.get("best_candidate") or "")
    candidates = payload.get("candidates", []) if isinstance(payload, dict) else []
    kit = payload.get("dropzone_kit") if isinstance(payload.get("dropzone_kit"), dict) else {}
    dropzone = str(kit.get("dropzone_dir") or data_root / "raw")
    if best:
        action = f"Review and normalize best raw bars candidate: {best}."
    else:
        action = "Place a retained broker/vendor daily bars CSV in the raw dropzone, then rerun discovery."
    return DataIntakeStatusItem(
        sequence=6,
        area="raw_bars_csv",
        status=status,
        current_state=f"best={best or 'none'}, candidates={len(candidates or [])}",
        target=dropzone,
        next_action=action,
        next_command=_first_command(payload, default=_raw_discovery_command(dropzone, report_root, data_root)),
        source_artifact=str(report_root / "raw_bars_discovery.json"),
    )


def _source_closeout_item(payload: dict[str, Any], *, report_root: Path) -> DataIntakeStatusItem:
    status = _normalize(_status(payload.get("decision"), missing="BLOCK"))
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    action = str(payload.get("next_action") or "")
    if not action:
        action = "Run source QA closeout after changing worksheet, answers, or evidence files."
    return DataIntakeStatusItem(
        sequence=7,
        area="source_qa_closeout",
        status=status,
        current_state=(
            f"open_actions={_int(counts.get('open_action_count'))}, "
            f"missing_worksheet={_int(counts.get('missing_worksheet_count'))}, "
            f"missing_attachments={_int(counts.get('missing_attachment_count'))}"
        ),
        target=str(report_root / "source_qa_closeout.json"),
        next_action=action,
        next_command=_first_command(payload, key="command_sequence", default=_source_closeout_command(report_root)),
        source_artifact=str(report_root / "source_qa_closeout.json"),
    )


def _ohlcv_closeout_item(payload: dict[str, Any], *, report_root: Path) -> DataIntakeStatusItem:
    status = _normalize(_status(payload.get("decision"), missing="BLOCK"))
    blockers = [str(item) for item in payload.get("blockers", []) or [] if str(item).strip()]
    action = blockers[0] if blockers else "Run guarded OHLCV closeout after source QA and raw bars are ready."
    return DataIntakeStatusItem(
        sequence=8,
        area="ohlcv_intake_closeout",
        status=status,
        current_state=(
            f"source_qa={payload.get('source_qa_status') or 'MISSING'}, "
            f"raw={payload.get('raw_discovery_status') or 'MISSING'}, "
            f"offline={payload.get('offline_intake_status') or 'MISSING'}"
        ),
        target=str(report_root / "ohlcv_intake_closeout.json"),
        next_action=action,
        next_command=_first_command(payload, key="command_sequence", default=_ohlcv_closeout_command(report_root)),
        source_artifact=str(report_root / "ohlcv_intake_closeout.json"),
    )


def _summary(
    *,
    raw_discovery: dict[str, Any],
    evidence_inbox: dict[str, Any],
    source_readiness: dict[str, Any],
    source_closeout: dict[str, Any],
    ohlcv_closeout: dict[str, Any],
    work_order: dict[str, Any],
    worksheet_path: Path,
    answers_path: Path,
    manifest_path: Path,
) -> dict[str, Any]:
    return {
        "operator_next_batch": str(work_order.get("next_batch_id") or ""),
        "raw_bars_status": _status(raw_discovery.get("status"), missing="MISSING"),
        "raw_bars_best_candidate": str(raw_discovery.get("best_candidate") or ""),
        "source_evidence_status": _status(evidence_inbox.get("status"), missing="MISSING"),
        "source_evidence_missing": _int(evidence_inbox.get("missing_item_count")),
        "source_evidence_invalid": _int(evidence_inbox.get("invalid_file_count")),
        "worksheet_exists": worksheet_path.exists(),
        "worksheet_fill_ready": bool(evidence_inbox.get("worksheet_fill_command_ready")),
        "answers_exists": answers_path.exists(),
        "answers_nonempty": _json_has_content(answers_path),
        "manifest_exists": manifest_path.exists(),
        "manifest_nonempty": _json_has_content(manifest_path),
        "source_readiness_status": _status(source_readiness.get("status"), missing="MISSING"),
        "source_closeout_decision": _status(source_closeout.get("decision"), missing="MISSING"),
        "ohlcv_closeout_decision": _status(ohlcv_closeout.get("decision"), missing="MISSING"),
    }


def _command_sequence(
    items: list[DataIntakeStatusItem],
    *,
    report_root: Path,
    data_root: Path,
    as_of: str,
) -> list[str]:
    commands = [item.next_command for item in items if item.status in {"BLOCK", "WATCH"} and item.next_command]
    commands.extend(
        [
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_data_intake_status.py "
                f"--report-dir {report_root} --data-dir {data_root} --as-of {as_of}"
            ),
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_first_million_pipeline.py "
                "--config config\\research_recent.yaml --data-dir data_exports "
                f"--output-dir {report_root} "
                "--source-qa-answers data_exports\\data_source_qa_answers.json "
                "--source-qa-evidence-manifest data_exports\\source_qa_evidence_manifest.json "
                "--require-source-qa-evidence-manifest "
                f"--as-of {as_of} --min-symbols 300 --min-trading-days 240 --no-registry"
            ),
        ]
    )
    return _dedupe(commands)[:18]


def _decision(items: list[DataIntakeStatusItem]) -> DataIntakeDecision:
    if not items or any(item.status == "BLOCK" for item in items):
        return "BLOCK"
    if any(item.status == "WATCH" for item in items):
        return "WATCH"
    return "PASS"


def _section(payload: dict[str, Any], name: str) -> dict[str, Any]:
    for section in payload.get("sections", []) or []:
        if isinstance(section, dict) and str(section.get("name") or "") == name:
            return section
    return {}


def _first_command(payload: dict[str, Any], *, key: str = "next_commands", default: str = "") -> str:
    values = payload.get(key)
    if isinstance(values, list):
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
    return default


def _inbox_command(data_root: Path, report_root: Path) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_evidence_inbox.py "
        f"--data-dir {data_root} --report-dir {report_root}"
    )


def _raw_discovery_command(dropzone: str, report_root: Path, data_root: Path) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\run_raw_bars_discovery.py "
        f"--search-dir {dropzone} --config config\\research_recent.yaml "
        f"--output-dir {report_root} --data-output-dir {data_root} --write-dropzone-kit --min-symbols 300"
    )


def _source_closeout_command(report_root: Path) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_closeout.py "
        f"--data-dir data_exports --report-dir {report_root} --output-dir {report_root}"
    )


def _ohlcv_closeout_command(report_root: Path) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\run_ohlcv_intake_closeout.py "
        f"--data-dir data_exports --report-dir {report_root} --config config\\research_recent.yaml "
        "--source-qa-answers data_exports\\data_source_qa_answers.json "
        "--source-qa-evidence-manifest data_exports\\source_qa_evidence_manifest.json "
        "--require-source-qa-evidence-manifest --min-symbols 300 --min-trading-days 240"
    )


def _read_as_of(report_root: Path) -> str:
    for name in ("first_million_daily_brief.json", "first_million_pipeline.json", "source_qa_closeout.json"):
        payload = _read_json(report_root / name)
        text = str(payload.get("as_of") or "")
        if text:
            return text
    return ""


def _json_has_content(path: Path) -> bool:
    payload = _read_json(path)
    if not payload:
        return False
    if isinstance(payload.get("answers"), list):
        return bool(payload.get("answers"))
    if isinstance(payload.get("items"), list):
        return bool(payload.get("items"))
    if isinstance(payload.get("checklist"), list):
        return bool(payload.get("checklist"))
    return bool(payload)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize(value: object) -> DataIntakeDecision:
    text = str(value or "").strip().upper()
    if text == "PASS":
        return "PASS"
    if text == "WATCH":
        return "WATCH"
    return "BLOCK"


def _status(value: object, *, missing: str = "UNKNOWN") -> str:
    text = str(value or "").strip().upper()
    return text or missing


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value.strip()))


def _cell(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")
