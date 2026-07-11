"""Discover local raw broker/vendor bars CSV files before normalization.

This module is read-only: it scans candidate CSV files and reports whether they
look normalizable into the bars.csv contract. It never writes bars.csv and does
not approve source QA, strategy research, or broker activity.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Literal
import zipfile

from quantify.data.vendor_bars_normalizer import normalize_vendor_bars
from quantify.utils.config import load_config

RawBarsDiscoveryStatus = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class RawBarsCandidate:
    path: str
    exists: bool
    size_bytes: int
    status: RawBarsDiscoveryStatus
    encoding: str
    raw_row_count: int
    normalized_row_count: int
    symbol_count: int
    start: str
    end: str
    raw_sha256: str
    raw_columns: list[str]
    findings: list[dict[str, Any]]
    message: str
    normalize_command: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "exists": self.exists,
            "size_bytes": self.size_bytes,
            "status": self.status,
            "encoding": self.encoding,
            "raw_row_count": self.raw_row_count,
            "normalized_row_count": self.normalized_row_count,
            "symbol_count": self.symbol_count,
            "start": self.start,
            "end": self.end,
            "raw_sha256": self.raw_sha256,
            "raw_columns": self.raw_columns,
            "findings": self.findings,
            "message": self.message,
            "normalize_command": self.normalize_command,
        }


@dataclass(frozen=True, slots=True)
class RawBarsDropzoneKit:
    dropzone_dir: str
    readme_path: str
    source_qa_evidence_dir: str
    accepted_extensions: list[str]
    required_columns: list[str]
    optional_columns: list[str]
    source_qa_files: list[str]
    checklist: list[str]
    command_sequence: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dropzone_dir": self.dropzone_dir,
            "readme_path": self.readme_path,
            "source_qa_evidence_dir": self.source_qa_evidence_dir,
            "accepted_extensions": self.accepted_extensions,
            "required_columns": self.required_columns,
            "optional_columns": self.optional_columns,
            "source_qa_files": self.source_qa_files,
            "checklist": self.checklist,
            "command_sequence": self.command_sequence,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            "# Raw Bars Dropzone Kit",
            "",
            f"- Dropzone directory: `{self.dropzone_dir}`",
            f"- Source-QA evidence directory: `{self.source_qa_evidence_dir}`",
            "",
            "Place retained broker/vendor A-share daily-bars exports here before running discovery. "
            "This kit is an operator instruction sheet only; it does not create market data, source evidence, "
            "strategy approval, or broker connectivity.",
            "",
            "## Accepted Files",
            "",
            f"- Extensions: `{', '.join(self.accepted_extensions)}`",
            "- Prefer one retained raw CSV exported directly from the broker/vendor terminal.",
            "- Zip archives may be retained as evidence, but discovery will stay BLOCK until the daily-bars CSV is extracted.",
            "- Do not edit the retained raw CSV after export; normalization reports its sha256.",
            "",
            "## Columns",
            "",
            f"- Required: `{', '.join(self.required_columns)}`",
            f"- Optional: `{', '.join(self.optional_columns)}`",
            "- Common Chinese broker headers are accepted by the normalizer; use `--encoding auto` for GBK/GB18030 exports.",
            "",
            "## Source QA Files",
        ]
        lines.extend(f"- `{item}`" for item in self.source_qa_files)
        lines.extend(["", "## Checklist"])
        lines.extend(f"- {item}" for item in self.checklist)
        lines.extend(["", "## Command Sequence"])
        for index, command in enumerate(self.command_sequence, start=1):
            lines.extend(["", f"{index}.", "", "```powershell", command, "```"])
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class RawBarsDiscoveryReport:
    status: RawBarsDiscoveryStatus
    config_path: str
    output_dir: str
    data_output_dir: str
    search_dirs: list[str]
    pattern: str
    start: str
    end: str
    min_symbols: int
    max_files: int
    dropzone_kit: RawBarsDropzoneKit
    candidates: list[RawBarsCandidate]
    best_candidate: str
    next_commands: list[str]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "config_path": self.config_path,
            "output_dir": self.output_dir,
            "data_output_dir": self.data_output_dir,
            "search_dirs": self.search_dirs,
            "pattern": self.pattern,
            "start": self.start,
            "end": self.end,
            "min_symbols": self.min_symbols,
            "max_files": self.max_files,
            "dropzone_kit": self.dropzone_kit.to_dict(),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "best_candidate": self.best_candidate,
            "next_commands": self.next_commands,
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Raw Bars CSV Discovery: {self.status}",
            "",
            f"- Config: `{self.config_path}`",
            f"- Output directory: `{self.output_dir}`",
            f"- Data output directory: `{self.data_output_dir}`",
            f"- Search directories: `{', '.join(self.search_dirs) or 'none'}`",
            f"- Pattern: `{self.pattern}`",
            f"- Required period: `{self.start}` to `{self.end}`",
            f"- Minimum symbols: {self.min_symbols}",
            f"- Best candidate: `{self.best_candidate or 'none'}`",
            f"- Dropzone: `{self.dropzone_kit.dropzone_dir}`",
            f"- Dropzone README: `{self.dropzone_kit.readme_path}`",
            "",
            "This report only discovers and preflights local raw bars CSV files. It does not normalize data, create source evidence, approve strategy research, or submit orders.",
            "",
            "## Candidates",
            "",
            "| status | path | rows | normalized | symbols | period | message |",
            "| --- | --- | ---: | ---: | ---: | --- | --- |",
        ]
        for candidate in self.candidates:
            period = f"{candidate.start or '-'} to {candidate.end or '-'}"
            lines.append(
                f"| `{candidate.status}` | `{candidate.path}` | {candidate.raw_row_count} | "
                f"{candidate.normalized_row_count} | {candidate.symbol_count} | `{period}` | "
                f"{_cell(candidate.message)} |"
            )
        lines.extend(
            [
                "",
                "## Dropzone Kit",
                "",
                "Write the local operator instructions with:",
                "",
                "```powershell",
                (
                    ".\\.venv\\Scripts\\python.exe examples\\run_raw_bars_discovery.py "
                    f"--config {self.config_path} --output-dir {self.output_dir} "
                    f"--data-output-dir {self.data_output_dir} "
                    f"--dropzone-dir {self.dropzone_kit.dropzone_dir} --write-dropzone-kit"
                ),
                "```",
                "",
                "The kit creates the dropzone README only; it does not create `bars.csv`, source QA answers, approvals, or broker instructions.",
            ]
        )
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Next Commands"])
        for command in self.next_commands:
            lines.extend(["", "```powershell", command, "```"])
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_raw_bars_discovery_report(
    *,
    search_dirs: list[str | Path] | None = None,
    config_path: str | Path = "config/research_recent.yaml",
    output_dir: str | Path = "results/first_million",
    data_output_dir: str | Path = "data_exports",
    pattern: str = "*.csv",
    min_symbols: int | None = None,
    start: str | None = None,
    end: str | None = None,
    encoding: str = "auto",
    max_files: int = 50,
    dropzone_dir: str | Path | None = None,
) -> RawBarsDiscoveryReport:
    cfg = load_config(config_path)
    resolved_start = start or str(cfg.research.start)
    resolved_end = end or str(cfg.research.end)
    resolved_min_symbols = int(min_symbols if min_symbols is not None else 300)
    resolved_dropzone_dir = Path(dropzone_dir) if dropzone_dir is not None else Path(data_output_dir) / "raw"
    dropzone_kit = _dropzone_kit(
        dropzone_dir=resolved_dropzone_dir,
        data_output_dir=data_output_dir,
        config_path=config_path,
        output_dir=output_dir,
        start=resolved_start,
        end=resolved_end,
        min_symbols=resolved_min_symbols,
        encoding=encoding,
    )
    roots = _candidate_roots(search_dirs)
    paths = _candidate_files(roots, pattern=pattern, max_files=max_files)
    candidates = [
        _candidate(
            path,
            config_path=config_path,
            output_dir=output_dir,
            data_output_dir=data_output_dir,
            start=resolved_start,
            end=resolved_end,
            min_symbols=resolved_min_symbols,
            encoding=encoding,
        )
        for path in paths
    ]
    if not candidates:
        candidates = [_missing_candidate(root) for root in roots]
    best = _best_candidate(candidates)
    status = _report_status(best)
    best_path = best.path if best and best.status != "BLOCK" else ""
    return RawBarsDiscoveryReport(
        status=status,
        config_path=str(config_path),
        output_dir=str(output_dir),
        data_output_dir=str(data_output_dir),
        search_dirs=[str(root) for root in roots],
        pattern=pattern,
        start=resolved_start,
        end=resolved_end,
        min_symbols=resolved_min_symbols,
        max_files=max_files,
        dropzone_kit=dropzone_kit,
        candidates=candidates,
        best_candidate=best_path,
        next_commands=_next_commands(
            best=best if best and best.status != "BLOCK" else None,
            config_path=config_path,
            output_dir=output_dir,
            data_output_dir=data_output_dir,
            start=resolved_start,
            end=resolved_end,
            min_symbols=resolved_min_symbols,
            encoding=encoding,
            dropzone_dir=resolved_dropzone_dir,
        ),
        next_actions=_next_actions(status, best, dropzone_kit),
        prohibited_actions=[
            "Do not treat raw CSV discovery as source QA, license evidence, or strategy approval.",
            "Do not normalize or import a candidate while discovery is BLOCK.",
            "Do not use discovered OHLCV data for PIT fundamentals, valuation, or quality claims.",
            "Do not connect this workflow to real broker order submission.",
        ],
    )


def write_raw_bars_discovery_report(
    report: RawBarsDiscoveryReport,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "raw_bars_discovery.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "raw_bars_discovery.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def write_raw_bars_dropzone_kit(report: RawBarsDiscoveryReport) -> Path:
    kit = report.dropzone_kit
    dropzone = Path(kit.dropzone_dir)
    dropzone.mkdir(parents=True, exist_ok=True)
    Path(kit.source_qa_evidence_dir).mkdir(parents=True, exist_ok=True)
    readme = Path(kit.readme_path)
    readme.write_text(kit.to_markdown(), encoding="utf-8")
    return readme


def _candidate(
    path: Path,
    *,
    config_path: str | Path,
    output_dir: str | Path,
    data_output_dir: str | Path,
    start: str,
    end: str,
    min_symbols: int,
    encoding: str,
) -> RawBarsCandidate:
    if path.suffix.lower() == ".zip":
        return _archive_candidate(path)
    report = normalize_vendor_bars(
        input_path=path,
        output_dir=data_output_dir,
        encoding=encoding,
        start=start,
        end=end,
        min_symbols=min_symbols,
        write_output=False,
    )
    return RawBarsCandidate(
        path=str(path),
        exists=True,
        size_bytes=report.raw_size_bytes,
        status=report.status,
        encoding=report.encoding,
        raw_row_count=report.raw_row_count,
        normalized_row_count=report.normalized_row_count,
        symbol_count=report.symbol_count,
        start=report.normalized_start,
        end=report.normalized_end,
        raw_sha256=report.raw_sha256,
        raw_columns=report.raw_columns,
        findings=[finding.to_dict() for finding in report.findings],
        message=_candidate_message(report.to_dict()),
        normalize_command=_normalize_command(
            path=path,
            data_output_dir=data_output_dir,
            output_dir=output_dir,
            start=start,
            end=end,
            min_symbols=min_symbols,
            encoding=encoding,
        ),
    )


def _archive_candidate(path: Path) -> RawBarsCandidate:
    try:
        with zipfile.ZipFile(path) as archive:
            csv_names = [
                name
                for name in archive.namelist()
                if not name.endswith("/") and Path(name).suffix.lower() == ".csv"
            ]
    except zipfile.BadZipFile:
        csv_names = []
        message = "Zip archive is unreadable; keep the original export, then provide an extracted CSV."
    else:
        message = (
            "Zip archive contains CSV files; extract the retained raw daily-bars CSV into data_exports/raw and rerun discovery."
            if csv_names
            else "Zip archive contains no CSV files; provide a retained raw daily-bars CSV export."
        )
    return RawBarsCandidate(
        path=str(path),
        exists=True,
        size_bytes=path.stat().st_size if path.exists() else 0,
        status="BLOCK",
        encoding="zip",
        raw_row_count=0,
        normalized_row_count=0,
        symbol_count=0,
        start="",
        end="",
        raw_sha256=_sha256(path),
        raw_columns=csv_names[:20],
        findings=[
            {
                "severity": "BLOCK",
                "code": "ARCHIVE_REQUIRES_EXTRACTED_CSV",
                "message": message,
            }
        ],
        message=message,
        normalize_command="",
    )


def _missing_candidate(root: Path) -> RawBarsCandidate:
    return RawBarsCandidate(
        path=str(root),
        exists=root.exists(),
        size_bytes=0,
        status="BLOCK",
        encoding="",
        raw_row_count=0,
        normalized_row_count=0,
        symbol_count=0,
        start="",
        end="",
        raw_sha256="",
        raw_columns=[],
        findings=[],
        message="No candidate raw bars CSV files were found.",
        normalize_command="",
    )


def _candidate_roots(search_dirs: list[str | Path] | None) -> list[Path]:
    if search_dirs:
        return _dedupe_paths([Path(path) for path in search_dirs])
    return _dedupe_paths([Path("data_exports"), Path("raw_data"), Path("data/raw"), Path("data_exports/raw")])


def _candidate_files(roots: list[Path], *, pattern: str, max_files: int) -> list[Path]:
    explicit_files: list[Path] = []
    discovered_files: list[Path] = []
    for root in roots:
        if root.is_file():
            if root.suffix.lower() in {".csv", ".zip"}:
                explicit_files.append(root)
            continue
        if not root.exists():
            continue
        discovered_files.extend(
            path
            for path in root.rglob(pattern)
            if path.is_file() and path.suffix.lower() == ".csv"
        )
        discovered_files.extend(
            path
            for path in root.rglob("*.zip")
            if path.is_file()
        )
    filtered = [
        path
        for path in _dedupe_paths([*explicit_files, *discovered_files])
        if path in explicit_files or not _looks_like_contract_template_file(path)
    ]
    return sorted(filtered, key=lambda path: path.stat().st_size if path.exists() else 0, reverse=True)[:max_files]


def _looks_like_contract_template_file(path: Path) -> bool:
    contract_names = {
        "bars.csv",
        "stock_info.csv",
        "fundamentals.csv",
        "calendar.csv",
        "suspensions.csv",
        "index_constituents.csv",
        "data_source_qa_evidence_worksheet.csv",
        "source_qa_evidence_manifest.csv",
    }
    if path.name not in contract_names:
        return False
    parent = path.parent.as_posix().lower().replace("\\", "/")
    return parent.endswith("data_exports") or parent.endswith("/data_exports")


def _best_candidate(candidates: list[RawBarsCandidate]) -> RawBarsCandidate | None:
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            _status_rank(item.status),
            item.symbol_count,
            item.normalized_row_count,
            item.size_bytes,
        ),
    )


def _status_rank(status: str) -> int:
    return {"PASS": 2, "WATCH": 1, "BLOCK": 0}.get(status, 0)


def _report_status(best: RawBarsCandidate | None) -> RawBarsDiscoveryStatus:
    if best is None:
        return "BLOCK"
    return best.status


def _candidate_message(payload: dict[str, Any]) -> str:
    findings = payload.get("findings", []) or []
    for severity in ("BLOCK", "WATCH"):
        for finding in findings:
            if isinstance(finding, dict) and finding.get("severity") == severity:
                return f"{finding.get('code')}: {finding.get('message')}"
    return (
        f"Normalizable raw bars CSV; symbols={payload.get('symbol_count', 0)}, "
        f"rows={payload.get('normalized_row_count', 0)}."
    )


def _dropzone_kit(
    *,
    dropzone_dir: Path,
    data_output_dir: str | Path,
    config_path: str | Path,
    output_dir: str | Path,
    start: str,
    end: str,
    min_symbols: int,
    encoding: str,
) -> RawBarsDropzoneKit:
    data_root = Path(data_output_dir)
    evidence_dir = data_root / "source_qa_evidence"
    readme_path = dropzone_dir / "README_raw_bars_dropzone.md"
    raw_placeholder = f'"{dropzone_dir / "<broker_vendor_daily_bars.csv>"}"'
    source_qa_files = [
        str(data_root / "data_source_qa.json"),
        str(data_root / "data_source_qa_evidence_worksheet.csv"),
        str(evidence_dir),
        str(data_root / "source_qa_evidence_manifest.json"),
        str(data_root / "data_source_qa_answers.json"),
    ]
    command_sequence = [
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_raw_bars_discovery.py "
            f"--search-dir {dropzone_dir} --config {config_path} --output-dir {output_dir} "
            f"--data-output-dir {data_root} --encoding {encoding} --min-symbols {min_symbols}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\normalize_vendor_bars.py "
            f"--input {raw_placeholder} --output-dir {data_root} --report-dir {output_dir} "
            f"--encoding {encoding} --start {start} --end {end} --min-symbols {min_symbols}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa.py "
            f"--config {config_path} --output-dir {data_root} --min-symbols {min_symbols}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa_evidence_worksheet.py "
            f"--checklist {data_root / 'data_source_qa.json'} --output-dir {data_root}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_source_qa_evidence_manifest.py "
            f"--checklist {data_root / 'data_source_qa.json'} "
            f"--evidence-dir {evidence_dir} --output-dir {data_root} --strict"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa_answers.py "
            f"--checklist {data_root / 'data_source_qa.json'} "
            f"--worksheet {data_root / 'data_source_qa_evidence_worksheet.csv'} "
            f"--output {data_root / 'data_source_qa_answers.json'} "
            f"--evidence-manifest {data_root / 'source_qa_evidence_manifest.json'} "
            "--require-evidence-manifest"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_ohlcv_intake_closeout.py "
            f"--data-dir {data_root} --report-dir {output_dir} --config {config_path} "
            f"--source-qa-answers {data_root / 'data_source_qa_answers.json'} "
            f"--source-qa-evidence-manifest {data_root / 'source_qa_evidence_manifest.json'} "
            f"--require-source-qa-evidence-manifest --min-symbols {min_symbols} --min-trading-days 240"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_first_million_pipeline.py "
            f"--config {config_path} --data-dir {data_root} --output-dir {output_dir} "
            f"--source-qa-answers {data_root / 'data_source_qa_answers.json'} "
            f"--source-qa-evidence-manifest {data_root / 'source_qa_evidence_manifest.json'} "
            f"--require-source-qa-evidence-manifest --min-symbols {min_symbols} --min-trading-days 240"
        ),
    ]
    return RawBarsDropzoneKit(
        dropzone_dir=str(dropzone_dir),
        readme_path=str(readme_path),
        source_qa_evidence_dir=str(evidence_dir),
        accepted_extensions=[".csv", ".zip"],
        required_columns=["symbol", "date", "open", "high", "low", "close", "volume"],
        optional_columns=["amount"],
        source_qa_files=source_qa_files,
        checklist=[
            "Copy the retained raw broker/vendor daily-bars CSV into the dropzone.",
            "Keep the original export and any zip/archive receipt as retained evidence.",
            "Confirm the export covers the configured research window and the latest completed trading day.",
            "Confirm the price adjustment matches the config, for example qfq/hfq/raw.",
            "Attach source identity, license, export timestamp, price-adjustment, and human-review evidence under the source-QA evidence directory.",
            "Run discovery before normalization; only normalize PASS/WATCH candidates after source QA evidence is prepared.",
            "Rerun the first-million pipeline after guarded intake writes a traceable research cache.",
        ],
        command_sequence=command_sequence,
        prohibited_actions=[
            "Do not fabricate, edit, or backfill raw bars to satisfy coverage checks.",
            "Do not treat this dropzone README as source QA, license evidence, strategy approval, or profit evidence.",
            "Do not use OHLCV-only data for point-in-time fundamentals, valuation, or quality claims.",
            "Do not connect this workflow to real broker order submission.",
        ],
    )


def _next_actions(
    status: RawBarsDiscoveryStatus,
    best: RawBarsCandidate | None,
    dropzone_kit: RawBarsDropzoneKit,
) -> list[str]:
    if best is None or status == "BLOCK":
        archive_action = []
        if best and best.encoding == "zip":
            archive_action.append(
                "Extract the retained raw daily-bars CSV from the zip archive into data_exports/raw; keep the original zip as source evidence."
            )
        return [
            *archive_action,
            f"Place a retained broker/vendor daily bars CSV under {dropzone_kit.dropzone_dir} or pass --search-dir <directory>.",
            f"Use --write-dropzone-kit to write operator instructions to {dropzone_kit.readme_path}.",
            "Rerun raw bars discovery before normalization.",
        ]
    if status == "WATCH":
        return [
            "Review WATCH findings before normalization; the candidate may be useful for smoke research only.",
            "Normalize the best candidate only after confirming source QA evidence for the export.",
        ]
    return [
        "Normalize the best candidate into data_exports/bars.csv.",
        "Fill source QA evidence and rerun first-million pipeline before any candidate research.",
    ]


def _next_commands(
    *,
    best: RawBarsCandidate | None,
    config_path: str | Path,
    output_dir: str | Path,
    data_output_dir: str | Path,
    start: str,
    end: str,
    min_symbols: int,
    encoding: str,
    dropzone_dir: Path,
) -> list[str]:
    answers_path = Path(data_output_dir) / "data_source_qa_answers.json"
    manifest_path = Path(data_output_dir) / "source_qa_evidence_manifest.json"
    strict_source_args = (
        f"--source-qa-answers {answers_path} "
        f"--source-qa-evidence-manifest {manifest_path} "
        "--require-source-qa-evidence-manifest"
    )
    if best is None:
        return [
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_raw_bars_discovery.py "
                f"--config {config_path} --output-dir {output_dir} --data-output-dir {data_output_dir} "
                f"--dropzone-dir {dropzone_dir} --write-dropzone-kit"
            ),
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_raw_bars_discovery.py "
                f"--config {config_path} --output-dir {output_dir} --data-output-dir {data_output_dir} "
                f"--search-dir {dropzone_dir} --encoding {encoding} --min-symbols {min_symbols}"
            )
        ]
    return [
        best.normalize_command,
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_real_data_batch_onboarding.py "
            f"--data-dir {data_output_dir} --report-dir {output_dir} --config {config_path} "
            f"--raw-bars-csv {best.path} {strict_source_args} --min-symbols {min_symbols}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_first_million_pipeline.py "
            f"--config {config_path} --data-dir {data_output_dir} --output-dir {output_dir} "
            f"--raw-bars-csv {best.path} {strict_source_args} --min-symbols {min_symbols}"
        ),
    ]


def _normalize_command(
    *,
    path: Path,
    data_output_dir: str | Path,
    output_dir: str | Path,
    start: str,
    end: str,
    min_symbols: int,
    encoding: str,
) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\normalize_vendor_bars.py "
        f"--input {path} --output-dir {data_output_dir} --report-dir {output_dir} "
        f"--encoding {encoding} --start {start} --end {end} --min-symbols {min_symbols}"
    )


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result = []
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


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
