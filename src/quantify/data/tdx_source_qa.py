"""TongDaXin-specific source QA answers for local .day OHLCV intake."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quantify.data.source_qa import (
    build_data_source_qa_answers,
    build_source_qa_evidence_manifest,
    write_data_source_qa_answers,
    write_source_qa_evidence_manifest,
)
from quantify.data.source_qa_worksheet_fill import fill_source_qa_evidence_worksheet

DEFAULT_TDX_VENDOR = "TongDaXin local .day files"
DEFAULT_TDX_TERMINAL = "TongDaXin"
TDX_OHLCV_ONLY_PIT_NOTE = (
    "TDX OHLCV-only .day files do not supply PIT fundamentals or PIT index constituents; "
    "use only price_volume_defensive research until separate PIT evidence is supplied, and keep "
    "fundamental-dependent candidates blocked."
)
TDX_DEFAULT_LIMITATIONS = (
    "TDX .day OHLCV intake does not prove ST flags, suspensions, limit-up/down tradability, "
    "PIT fundamentals, or PIT index constituents. Price adjustment depends on the source "
    "terminal/export setting and must be evidenced separately."
)


def build_tdx_source_qa_answers(
    *,
    checklist_path: str | Path = "data_exports/data_source_qa.json",
    tdx_export_report: str | Path | None = "data_exports/tdx_day_export.json",
    input_dir: str | Path | None = None,
    data_vendor_or_broker: str = DEFAULT_TDX_VENDOR,
    terminal_or_product_name: str = DEFAULT_TDX_TERMINAL,
    export_operator: str,
    exported_at_local_time: str,
    price_adjustment: str | None = None,
    price_adjustment_evidence: str,
    license_or_usage_scope: str = "research and paper trading only",
    license_evidence: str,
    pit_fundamental_evidence: str | None = None,
    reviewed_by: str,
    reviewed_at: str,
    encoding: str = "utf-8-sig",
    known_limitations: str = "",
) -> dict[str, Any]:
    """Build source-stage QA answers for converted local TDX OHLCV data.

    The helper narrows TDX `.day` evidence to the OHLCV-only path unless the
    operator supplies separate PIT fundamental evidence. It still requires real
    license, adjustment, export-time, and human-review evidence from the user.
    """
    checklist_file = Path(checklist_path)
    checklist = _read_json(checklist_file)
    report_file = Path(tdx_export_report) if tdx_export_report else None
    report = _read_json(report_file) if report_file else {}
    resolved_input_dir = str(input_dir or report.get("input_dir", "") or "").strip()
    if not resolved_input_dir and not report:
        raise ValueError("TDX source QA requires --input-dir or an existing tdx_day_export.json.")

    resolved_price_adjustment = (
        str(price_adjustment or "").strip()
        or str((checklist.get("source_metadata_template", {}) or {}).get("price_adjustment", "")).strip()
        or "qfq"
    )
    resolved_limitations = _combine_notes(TDX_DEFAULT_LIMITATIONS, known_limitations)
    pit_evidence = str(pit_fundamental_evidence or "").strip() or TDX_OHLCV_ONLY_PIT_NOTE
    source_identity = _source_identity_evidence(
        vendor=data_vendor_or_broker,
        terminal=terminal_or_product_name,
        operator=export_operator,
        exported_at=exported_at_local_time,
        input_dir=resolved_input_dir,
        report=report,
        report_file=report_file,
    )

    answers = build_data_source_qa_answers(
        checklist_path=checklist_file,
        data_vendor_or_broker=data_vendor_or_broker,
        terminal_or_product_name=terminal_or_product_name,
        export_operator=export_operator,
        exported_at_local_time=exported_at_local_time,
        price_adjustment=resolved_price_adjustment,
        price_adjustment_evidence=_combine_notes(
            price_adjustment_evidence,
            f"tdx_price_adjustment_recorded_as={resolved_price_adjustment}",
        ),
        license_or_usage_scope=license_or_usage_scope,
        license_evidence=license_evidence,
        point_in_time_evidence=pit_evidence,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        encoding=encoding,
        known_limitations=resolved_limitations,
    )
    answer_map = answers.get("answers", {})
    if isinstance(answer_map, dict):
        _replace_evidence(answer_map, "source_identity", source_identity)
        _append_evidence(answer_map, "point_in_time", TDX_OHLCV_ONLY_PIT_NOTE)

    metadata = answers.get("source_metadata", {})
    if isinstance(metadata, dict):
        metadata.update(
            {
                "tdx_input_dir": resolved_input_dir,
                "tdx_export_report_path": str(report_file or ""),
                "tdx_symbol_count": report.get("symbol_count", ""),
                "tdx_row_count": report.get("row_count", ""),
                "tdx_start": report.get("start", ""),
                "tdx_end": report.get("end", ""),
                "candidate_scope": "OHLCV-only unless PIT evidence is supplied separately",
            }
        )
    return answers


def write_tdx_source_qa_answers(answers: dict[str, Any], output_path: str | Path) -> Path:
    """Write TDX source QA answers using the shared source QA JSON contract."""
    return write_data_source_qa_answers(answers, output_path)


def write_tdx_source_qa_support_artifacts(
    answers: dict[str, Any],
    *,
    checklist_path: str | Path = "data_exports/data_source_qa.json",
    worksheet_path: str | Path = "data_exports/data_source_qa_evidence_worksheet.csv",
    evidence_dir: str | Path = "data_exports/source_qa_evidence",
    manifest_path: str | Path = "data_exports/source_qa_evidence_manifest.json",
    encoding: str = "utf-8-sig",
) -> dict[str, Any]:
    """Write worksheet and attachment artifacts derived from explicit TDX evidence fields.

    This helper does not invent new evidence. It records the already supplied
    TDX source QA answers into the worksheet/attachment artifacts that the
    deterministic source-QA readiness gates expect.
    """
    checklist_file = Path(checklist_path)
    worksheet_file = Path(worksheet_path)
    evidence_root = Path(evidence_dir)
    manifest_file = Path(manifest_path)
    source_metadata = answers.get("source_metadata", {}) if isinstance(answers, dict) else {}
    answer_map = answers.get("answers", {}) if isinstance(answers, dict) else {}

    fill_report, preflight = fill_source_qa_evidence_worksheet(
        checklist_path=checklist_file,
        worksheet_path=worksheet_file,
        output_dir=worksheet_file.parent,
        encoding=encoding,
        vendor=str(source_metadata.get("data_vendor_or_broker") or ""),
        terminal=str(source_metadata.get("terminal_or_product_name") or ""),
        operator=str(source_metadata.get("export_operator") or ""),
        exported_at=str(source_metadata.get("exported_at_local_time") or ""),
        price_adjustment=str(source_metadata.get("price_adjustment") or ""),
        license_scope=str(source_metadata.get("license_or_usage_scope") or ""),
        reviewed_by=str(source_metadata.get("reviewed_by") or ""),
        reviewed_at=str(source_metadata.get("reviewed_at") or ""),
        source_identity_evidence=_answer_evidence(answer_map, "source_identity"),
        license_evidence=_answer_evidence(answer_map, "license_scope"),
        price_adjustment_evidence=_answer_evidence(answer_map, "price_adjustment"),
        point_in_time_evidence=_answer_evidence(answer_map, "point_in_time"),
        manual_signoff_evidence=_manual_signoff_evidence(answer_map, source_metadata),
        notes="Derived from explicit TDX source QA evidence fields.",
    )

    _write_tdx_support_evidence_files(
        evidence_root,
        source_metadata=source_metadata,
        answer_map=answer_map,
    )
    manifest = build_source_qa_evidence_manifest(
        checklist_path=checklist_file,
        evidence_dir=evidence_root,
    )
    write_source_qa_evidence_manifest(manifest, manifest_file.parent)
    if manifest_file.name != "source_qa_evidence_manifest.json":
        manifest_file.parent.mkdir(parents=True, exist_ok=True)
        manifest_file.write_text(
            json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return {
        "worksheet_path": str(worksheet_file),
        "evidence_dir": str(evidence_root),
        "manifest_path": str(manifest_file),
        "worksheet_fill_status": fill_report.status,
        "worksheet_preflight_status": preflight.status,
        "manifest_item_count": len(manifest.items),
    }


def _source_identity_evidence(
    *,
    vendor: str,
    terminal: str,
    operator: str,
    exported_at: str,
    input_dir: str,
    report: dict[str, Any],
    report_file: Path | None,
) -> str:
    pieces = [
        f"vendor={vendor}",
        f"terminal={terminal}",
        f"operator={operator}",
        f"exported_at={exported_at}",
    ]
    if input_dir:
        pieces.append(f"tdx_input_dir={input_dir}")
    if report:
        pieces.extend(
            [
                f"tdx_export_report={report_file}",
                f"symbols={report.get('symbol_count', '')}",
                f"rows={report.get('row_count', '')}",
                f"period={report.get('start', '')} to {report.get('end', '')}",
            ]
        )
    return "; ".join(str(piece) for piece in pieces if str(piece).strip())


def _replace_evidence(answers: dict[str, Any], item_id: str, evidence: str) -> None:
    item = answers.get(item_id)
    if isinstance(item, dict):
        item["answer"] = "yes"
        item["evidence"] = evidence


def _append_evidence(answers: dict[str, Any], item_id: str, evidence: str) -> None:
    item = answers.get(item_id)
    if not isinstance(item, dict):
        return
    existing = str(item.get("evidence", "") or "").strip()
    item["answer"] = "yes"
    item["evidence"] = _combine_notes(existing, evidence)


def _combine_notes(*notes: str) -> str:
    return "; ".join(note.strip() for note in notes if str(note or "").strip())


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _answer_evidence(answer_map: dict[str, Any], item_id: str) -> str:
    item = answer_map.get(item_id)
    if not isinstance(item, dict):
        return ""
    return str(item.get("evidence") or "").strip()


def _manual_signoff_evidence(answer_map: dict[str, Any], source_metadata: dict[str, Any]) -> str:
    evidence = _answer_evidence(answer_map, "manual_signoff")
    if evidence:
        return evidence
    reviewed_by = str(source_metadata.get("reviewed_by") or "").strip()
    reviewed_at = str(source_metadata.get("reviewed_at") or "").strip()
    return _combine_notes(
        f"reviewed_by={reviewed_by}" if reviewed_by else "",
        f"reviewed_at={reviewed_at}" if reviewed_at else "",
    )


def _write_tdx_support_evidence_files(
    evidence_root: Path,
    *,
    source_metadata: dict[str, Any],
    answer_map: dict[str, Any],
) -> None:
    evidence_root.mkdir(parents=True, exist_ok=True)
    price_adjustment = str(source_metadata.get("price_adjustment") or "qfq").strip().lower() or "qfq"
    note_specs = [
        (
            "source_identity",
            evidence_root / "source_identity_receipt.md",
            _source_identity_note(source_metadata, answer_map),
        ),
        (
            "license_scope",
            evidence_root / "license_scope_note.md",
            _license_scope_note(source_metadata, answer_map),
        ),
        (
            "price_adjustment",
            evidence_root / f"price_adjustment_{_safe_token(price_adjustment)}.md",
            _price_adjustment_note(source_metadata, answer_map),
        ),
        (
            "point_in_time",
            evidence_root / "point_in_time_note.md",
            _point_in_time_note(source_metadata, answer_map),
        ),
        (
            "manual_signoff",
            evidence_root / "manual_signoff.md",
            _manual_signoff_note(source_metadata, answer_map),
        ),
    ]
    for item_id, path, content in note_specs:
        if _has_existing_attachment(evidence_root, item_id) or not content.strip():
            continue
        path.write_text(content.strip() + "\n", encoding="utf-8")


def _source_identity_note(source_metadata: dict[str, Any], answer_map: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Source Identity Evidence",
            "",
            f"vendor: {source_metadata.get('data_vendor_or_broker', '')}",
            f"terminal: {source_metadata.get('terminal_or_product_name', '')}",
            f"operator: {source_metadata.get('export_operator', '')}",
            f"exported_at_local_time: {source_metadata.get('exported_at_local_time', '')}",
            f"tdx_input_dir: {source_metadata.get('tdx_input_dir', '')}",
            f"tdx_export_report_path: {source_metadata.get('tdx_export_report_path', '')}",
            f"tdx_symbol_count: {source_metadata.get('tdx_symbol_count', '')}",
            f"tdx_row_count: {source_metadata.get('tdx_row_count', '')}",
            f"tdx_period: {source_metadata.get('tdx_start', '')} to {source_metadata.get('tdx_end', '')}",
            "",
            f"evidence_summary: {_answer_evidence(answer_map, 'source_identity')}",
        ]
    )


def _license_scope_note(source_metadata: dict[str, Any], answer_map: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# License Scope Evidence",
            "",
            f"license_or_usage_scope: {source_metadata.get('license_or_usage_scope', '')}",
            f"reviewed_by: {source_metadata.get('reviewed_by', '')}",
            f"reviewed_at: {source_metadata.get('reviewed_at', '')}",
            "",
            f"evidence_summary: {_answer_evidence(answer_map, 'license_scope')}",
        ]
    )


def _price_adjustment_note(source_metadata: dict[str, Any], answer_map: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Price Adjustment Evidence",
            "",
            f"price_adjustment: {source_metadata.get('price_adjustment', '')}",
            f"tdx_input_dir: {source_metadata.get('tdx_input_dir', '')}",
            "",
            f"evidence_summary: {_answer_evidence(answer_map, 'price_adjustment')}",
        ]
    )


def _point_in_time_note(source_metadata: dict[str, Any], answer_map: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Point-In-Time Boundary Evidence",
            "",
            f"candidate_scope: {source_metadata.get('candidate_scope', '')}",
            f"known_limitations: {source_metadata.get('known_limitations', '')}",
            "",
            f"evidence_summary: {_answer_evidence(answer_map, 'point_in_time')}",
        ]
    )


def _manual_signoff_note(source_metadata: dict[str, Any], answer_map: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Manual Signoff",
            "",
            f"reviewed_by: {source_metadata.get('reviewed_by', '')}",
            f"reviewed_at: {source_metadata.get('reviewed_at', '')}",
            f"export_operator: {source_metadata.get('export_operator', '')}",
            f"exported_at_local_time: {source_metadata.get('exported_at_local_time', '')}",
            "",
            f"evidence_summary: {_manual_signoff_evidence(answer_map, source_metadata)}",
        ]
    )


def _has_existing_attachment(evidence_root: Path, item_id: str) -> bool:
    if not evidence_root.exists():
        return False
    for path in evidence_root.rglob("*"):
        if path.is_file() and _matches_item_id(path, item_id):
            return True
    return False


def _matches_item_id(path: Path, item_id: str) -> bool:
    lowered = item_id.lower()
    stem = path.stem.lower()
    name = path.name.lower()
    return (
        stem == lowered
        or stem.startswith(f"{lowered}_")
        or stem.startswith(f"{lowered}-")
        or f"_{lowered}_" in name
        or f"-{lowered}-" in name
    )


def _safe_token(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in value.strip().lower())
    return cleaned.strip("_") or "note"
