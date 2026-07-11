"""Lightweight CSV intake preview before guarded offline import."""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from quantify.data.csv_contract import RESEARCH_CSV_SCHEMAS
from quantify.data.csv_research_importer import (
    _ALIASES,
    AUTO_ENCODINGS,
    _normalize_bars,
    _normalize_fundamentals,
    _normalize_stock_info,
    _normalize_suspensions,
    _read_calendar,
    _read_csv,
    _read_index_constituents,
    _rename_columns,
)

PreviewStatus = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class CSVPreviewItem:
    role: str
    file_name: str
    path: str
    required: bool
    status: PreviewStatus
    raw_columns: list[str]
    mapped_columns: list[str]
    missing_columns: list[str]
    raw_rows: int
    normalized_rows: int
    symbol_count: int
    start: str
    end: str
    sample_rows: list[dict[str, Any]]
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "file_name": self.file_name,
            "path": self.path,
            "required": self.required,
            "status": self.status,
            "raw_columns": self.raw_columns,
            "mapped_columns": self.mapped_columns,
            "missing_columns": self.missing_columns,
            "raw_rows": self.raw_rows,
            "normalized_rows": self.normalized_rows,
            "symbol_count": self.symbol_count,
            "start": self.start,
            "end": self.end,
            "sample_rows": self.sample_rows,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class CSVIntakePreview:
    status: PreviewStatus
    data_dir: str
    encoding: str
    items: list[CSVPreviewItem]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "data_dir": self.data_dir,
            "encoding": self.encoding,
            "items": [item.to_dict() for item in self.items],
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# CSV Intake Preview: {self.status}",
            "",
            f"- Data directory: `{self.data_dir}`",
            f"- Encoding: `{self.encoding}`",
            "",
            "## Files",
            "",
            "| role | status | path | rows | normalized | symbols | period | missing | message |",
            "| --- | --- | --- | ---: | ---: | ---: | --- | --- | --- |",
        ]
        for item in self.items:
            period = f"{item.start or '-'} to {item.end or '-'}"
            missing = ", ".join(item.missing_columns) if item.missing_columns else "none"
            lines.append(
                f"| `{item.role}` | `{item.status}` | `{item.path}` | {item.raw_rows} | "
                f"{item.normalized_rows} | {item.symbol_count} | `{period}` | "
                f"{missing} | {item.message} |"
            )
        lines.extend(["", "## Column Mapping"])
        for item in self.items:
            if not item.raw_columns:
                continue
            lines.append("")
            lines.append(f"### `{item.role}`")
            lines.append(f"- Raw: `{', '.join(item.raw_columns)}`")
            lines.append(f"- Mapped: `{', '.join(item.mapped_columns)}`")
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {action}" for action in self.next_actions)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {action}" for action in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_csv_intake_preview(
    *,
    data_dir: str | Path = "data_exports",
    encoding: str = "utf-8-sig",
    sample_rows: int = 3,
) -> CSVIntakePreview:
    root = Path(data_dir)
    items = [
        _preview_item(root / schema.file_name, schema.required, schema.role, schema.file_name, encoding, sample_rows)
        for schema in RESEARCH_CSV_SCHEMAS
    ]
    return CSVIntakePreview(
        status=_combine([item.status for item in items]),
        data_dir=str(root),
        encoding=encoding,
        items=items,
        next_actions=_next_actions(items),
        prohibited_actions=[
            "Do not import CSV files into the research cache while preview is BLOCK.",
            "Do not treat preview PASS as strategy profitability evidence.",
            "Do not connect previewed files to real broker order submission.",
        ],
    )


def write_csv_intake_preview(preview: CSVIntakePreview, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "csv_intake_preview.json").write_text(
        json.dumps(preview.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "csv_intake_preview.md").write_text(preview.to_markdown(), encoding="utf-8")
    return root


def _preview_item(
    path: Path,
    required: bool,
    role: str,
    file_name: str,
    encoding: str,
    sample_rows: int,
) -> CSVPreviewItem:
    if not path.exists():
        status: PreviewStatus = "BLOCK" if required else "WATCH"
        return CSVPreviewItem(
            role=role,
            file_name=file_name,
            path=str(path),
            required=required,
            status=status,
            raw_columns=[],
            mapped_columns=[],
            missing_columns=_required_columns(role),
            raw_rows=0,
            normalized_rows=0,
            symbol_count=0,
            start="",
            end="",
            sample_rows=[],
            message=f"{file_name} is missing.",
        )
    try:
        raw = _read_csv(path, encoding)
    except UnicodeDecodeError as exc:
        return _failed_item(path, required, role, file_name, f"Could not read with encoding={encoding}: {exc}")
    raw_sample = _sample_frame(path, encoding, raw, sample_rows)
    mapped = _rename_columns(raw, _ALIASES)
    missing = [column for column in _required_columns(role) if column not in mapped.columns]
    if missing:
        return CSVPreviewItem(
            role=role,
            file_name=file_name,
            path=str(path),
            required=required,
            status="BLOCK" if required else "WATCH",
            raw_columns=[str(column) for column in raw.columns],
            mapped_columns=[str(column) for column in mapped.columns],
            missing_columns=missing,
            raw_rows=len(raw),
            normalized_rows=0,
            symbol_count=0,
            start="",
            end="",
            sample_rows=_sample(raw_sample, sample_rows),
            message="Required columns could not be mapped into the research schema.",
        )
    try:
        normalized = _normalize(role, raw)
    except Exception as exc:  # noqa: BLE001 - user-facing preview catches data problems.
        return CSVPreviewItem(
            role=role,
            file_name=file_name,
            path=str(path),
            required=required,
            status="BLOCK" if required else "WATCH",
            raw_columns=[str(column) for column in raw.columns],
            mapped_columns=[str(column) for column in mapped.columns],
            missing_columns=[],
            raw_rows=len(raw),
            normalized_rows=0,
            symbol_count=0,
            start="",
            end="",
            sample_rows=_sample(raw_sample, sample_rows),
            message=f"{type(exc).__name__}: {exc}",
        )
    return CSVPreviewItem(
        role=role,
        file_name=file_name,
        path=str(path),
        required=required,
        status="PASS",
        raw_columns=[str(column) for column in raw.columns],
        mapped_columns=[str(column) for column in mapped.columns],
        missing_columns=[],
        raw_rows=len(raw),
        normalized_rows=len(normalized),
        symbol_count=_symbol_count(normalized),
        start=_start(normalized),
        end=_end(normalized),
        sample_rows=_sample(raw_sample, sample_rows),
        message="Columns mapped and normalized successfully.",
    )


def _failed_item(
    path: Path,
    required: bool,
    role: str,
    file_name: str,
    message: str,
) -> CSVPreviewItem:
    return CSVPreviewItem(
        role=role,
        file_name=file_name,
        path=str(path),
        required=required,
        status="BLOCK" if required else "WATCH",
        raw_columns=[],
        mapped_columns=[],
        missing_columns=_required_columns(role),
        raw_rows=0,
        normalized_rows=0,
        symbol_count=0,
        start="",
        end="",
        sample_rows=[],
        message=message,
    )


def _normalize(role: str, raw: pd.DataFrame) -> pd.DataFrame:
    normalizers: dict[str, Callable[[pd.DataFrame], pd.DataFrame]] = {
        "bars": _normalize_bars,
        "stock_info": _normalize_stock_info,
        "fundamentals": _normalize_fundamentals,
        "suspensions": _normalize_suspensions,
        "index_constituents": lambda frame: pd.DataFrame(
            [
                {"index_code": row["index_code"], "date": row["date"], "symbol": symbol}
                for row in _read_index_constituents(frame, default_index_code="000906")
                for symbol in row["symbols"]
            ]
        ),
    }
    if role == "calendar":
        return pd.DataFrame({"date": _read_calendar(raw)})
    return normalizers[role](raw)


def _required_columns(role: str) -> list[str]:
    requirements = {
        "bars": ["symbol", "date", "open", "high", "low", "close", "volume"],
        "stock_info": ["symbol"],
        "fundamentals": ["symbol", "date"],
        "calendar": ["date"],
        "suspensions": ["symbol", "date"],
        "index_constituents": ["date", "symbol"],
    }
    return requirements[role]


def _sample(frame: pd.DataFrame, sample_rows: int) -> list[dict[str, Any]]:
    if sample_rows <= 0:
        return []
    return json.loads(frame.head(sample_rows).to_json(orient="records", force_ascii=False))


def _sample_frame(path: Path, encoding: str, fallback: pd.DataFrame, sample_rows: int) -> pd.DataFrame:
    if sample_rows <= 0:
        return fallback.head(0)
    encodings = AUTO_ENCODINGS if encoding.lower() == "auto" else (encoding,)
    for candidate in encodings:
        try:
            return pd.read_csv(
                path,
                encoding=candidate,
                dtype=str,
                keep_default_na=False,
                nrows=sample_rows,
            )
        except UnicodeDecodeError:
            continue
        except Exception:
            return fallback.head(sample_rows)
    return fallback.head(sample_rows)


def _symbol_count(frame: pd.DataFrame) -> int:
    return int(frame["symbol"].nunique()) if "symbol" in frame else 0


def _start(frame: pd.DataFrame) -> str:
    return str(frame["date"].min()) if "date" in frame and not frame.empty else ""


def _end(frame: pd.DataFrame) -> str:
    return str(frame["date"].max()) if "date" in frame and not frame.empty else ""


def _combine(statuses: list[PreviewStatus]) -> PreviewStatus:
    if any(status == "BLOCK" for status in statuses):
        return "BLOCK"
    if any(status == "WATCH" for status in statuses):
        return "WATCH"
    return "PASS"


def _next_actions(items: list[CSVPreviewItem]) -> list[str]:
    blockers = [item for item in items if item.status == "BLOCK"]
    watchers = [item for item in items if item.status == "WATCH"]
    if blockers:
        first = blockers[0]
        return [
            f"Fix {first.file_name} before import: {first.message}",
            "Rerun csv_intake_preview after replacing or remapping the export files.",
        ]
    if watchers:
        first = watchers[0]
        return [
            f"Review optional file warning for {first.file_name}: {first.message}",
            "Run validate_research_csv.py before guarded offline intake.",
        ]
    return ["Run validate_research_csv.py, then guarded offline data intake."]
