"""Discover local TongDaXin .day files before offline OHLCV intake."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal

from quantify.data.tdx_day import _file_identity, _is_a_share_stock, _read_day_file
from quantify.utils.config import load_config

TdxDiscoveryStatus = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class TdxDiscoveryRoot:
    path: str
    exists: bool
    day_file_count: int
    stock_file_count: int
    symbol_count: int
    start: str
    end: str
    status: TdxDiscoveryStatus
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "exists": self.exists,
            "day_file_count": self.day_file_count,
            "stock_file_count": self.stock_file_count,
            "symbol_count": self.symbol_count,
            "start": self.start,
            "end": self.end,
            "status": self.status,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class TdxDayDiscoveryReport:
    status: TdxDiscoveryStatus
    config_path: str
    output_dir: str
    start: str
    end: str
    min_symbols: int
    roots: list[TdxDiscoveryRoot]
    best_root: str
    next_commands: list[str]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "config_path": self.config_path,
            "output_dir": self.output_dir,
            "start": self.start,
            "end": self.end,
            "min_symbols": self.min_symbols,
            "roots": [root.to_dict() for root in self.roots],
            "best_root": self.best_root,
            "next_commands": self.next_commands,
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# TongDaXin Day Discovery: {self.status}",
            "",
            f"- Config: `{self.config_path}`",
            f"- Output directory: `{self.output_dir}`",
            f"- Required period: `{self.start}` to `{self.end}`",
            f"- Minimum symbols: {self.min_symbols}",
            f"- Best root: `{self.best_root or 'none'}`",
            "",
            "This report only discovers local .day files. It is not a data license review, "
            "strategy recommendation, or trading instruction.",
            "",
            "## Roots",
            "",
            "| status | path | exists | .day files | stock files | symbols | period | message |",
            "| --- | --- | --- | ---: | ---: | ---: | --- | --- |",
        ]
        for root in self.roots:
            period = f"{root.start or '-'} to {root.end or '-'}"
            lines.append(
                f"| `{root.status}` | `{root.path}` | `{root.exists}` | {root.day_file_count} | "
                f"{root.stock_file_count} | {root.symbol_count} | `{period}` | {root.message} |"
            )
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Next Commands"])
        for command in self.next_commands:
            lines.append("")
            lines.append("```powershell")
            lines.append(command)
            lines.append("```")
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_tdx_day_discovery_report(
    *,
    search_dirs: list[str | Path] | None = None,
    config_path: str | Path = "config/research_recent.yaml",
    output_dir: str | Path = "results/first_million",
    data_output_dir: str | Path = "data_exports",
    min_symbols: int | None = None,
    start: str | None = None,
    end: str | None = None,
    as_of: str | None = None,
    max_files_to_probe: int = 2000,
) -> TdxDayDiscoveryReport:
    cfg = load_config(config_path)
    resolved_start = start or str(cfg.research.start)
    resolved_end = end or str(cfg.research.end)
    resolved_min_symbols = int(min_symbols if min_symbols is not None else 300)
    roots = [
        _scan_root(
            Path(path),
            start=resolved_start,
            end=resolved_end,
            min_symbols=resolved_min_symbols,
            max_files_to_probe=max_files_to_probe,
        )
        for path in _candidate_roots(search_dirs)
    ]
    best = _best_root(roots)
    status = _report_status(best, roots)
    usable_best_root = best.path if best and best.status != "BLOCK" else ""
    return TdxDayDiscoveryReport(
        status=status,
        config_path=str(config_path),
        output_dir=str(output_dir),
        start=resolved_start,
        end=resolved_end,
        min_symbols=resolved_min_symbols,
        roots=roots,
        best_root=usable_best_root,
        next_commands=_next_commands(
            best_root=usable_best_root,
            config_path=config_path,
            data_output_dir=data_output_dir,
            output_dir=output_dir,
            start=resolved_start,
            end=resolved_end,
            as_of=as_of,
            min_symbols=resolved_min_symbols,
        ),
        next_actions=_next_actions(status, best),
        prohibited_actions=[
            "Do not treat local .day discovery as proof that data is licensed, adjusted, or complete.",
            "Do not run candidate experiments until source QA and offline intake gates pass.",
            "Do not use TDX OHLCV files to validate valuation or accounting-quality factors.",
            "Do not connect this workflow to real broker order submission.",
        ],
    )


def write_tdx_day_discovery_report(
    report: TdxDayDiscoveryReport,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "tdx_day_discovery.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "tdx_day_discovery.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _candidate_roots(search_dirs: list[str | Path] | None) -> list[Path]:
    if search_dirs:
        return _dedupe_paths([Path(path) for path in search_dirs])
    return _dedupe_paths(
        [
            Path("C:/new_tdx/vipdoc"),
            Path("C:/tdx/vipdoc"),
            Path("C:/TdxW/vipdoc"),
            Path("D:/new_tdx/vipdoc"),
            Path("D:/tdx/vipdoc"),
            Path("D:/TdxW/vipdoc"),
        ]
    )


def _scan_root(
    root: Path,
    *,
    start: str,
    end: str,
    min_symbols: int,
    max_files_to_probe: int,
) -> TdxDiscoveryRoot:
    if not root.exists():
        return TdxDiscoveryRoot(
            path=str(root),
            exists=False,
            day_file_count=0,
            stock_file_count=0,
            symbol_count=0,
            start="",
            end="",
            status="BLOCK",
            message="Directory does not exist.",
        )
    day_files = _discover_day_files(root)
    stock_files = [path for path in day_files if _stock_identity(path)]
    summaries = [_file_period(path, start=start, end=end) for path in stock_files[:max_files_to_probe]]
    covered = [item for item in summaries if item["rows"] > 0]
    symbols = {str(item["symbol"]) for item in covered if item.get("symbol")}
    first = min((str(item["start"]) for item in covered if item.get("start")), default="")
    last = max((str(item["end"]) for item in covered if item.get("end")), default="")
    status = _root_status(
        stock_file_count=len(stock_files),
        symbol_count=len(symbols),
        first=first,
        last=last,
        start=start,
        end=end,
        min_symbols=min_symbols,
    )
    return TdxDiscoveryRoot(
        path=str(root),
        exists=True,
        day_file_count=len(day_files),
        stock_file_count=len(stock_files),
        symbol_count=len(symbols),
        start=first,
        end=last,
        status=status,
        message=_root_message(
            status=status,
            stock_file_count=len(stock_files),
            symbol_count=len(symbols),
            first=first,
            last=last,
            start=start,
            end=end,
            min_symbols=min_symbols,
            probed=min(len(stock_files), max_files_to_probe),
        ),
    )


def _discover_day_files(root: Path) -> list[Path]:
    if root.is_file() and root.suffix.lower() == ".day":
        return [root]
    return sorted(path for path in root.rglob("*.day") if path.is_file())


def _stock_identity(path: Path) -> dict[str, str]:
    identity = _file_identity(path)
    if not identity:
        return {}
    return identity if _is_a_share_stock(identity["symbol"], identity["exchange"]) else {}


def _file_period(path: Path, *, start: str, end: str) -> dict[str, Any]:
    identity = _stock_identity(path)
    if not identity:
        return {"symbol": "", "rows": 0, "start": "", "end": ""}
    try:
        rows, _rows_read = _read_day_file(path, start=start, end=end)
    except ValueError:
        return {"symbol": identity["symbol"], "rows": 0, "start": "", "end": ""}
    return {
        "symbol": identity["symbol"],
        "rows": len(rows),
        "start": str(rows[0]["date"]) if rows else "",
        "end": str(rows[-1]["date"]) if rows else "",
    }


def _root_status(
    *,
    stock_file_count: int,
    symbol_count: int,
    first: str,
    last: str,
    start: str,
    end: str,
    min_symbols: int,
) -> TdxDiscoveryStatus:
    if stock_file_count == 0 or symbol_count == 0:
        return "BLOCK"
    if symbol_count < min_symbols or not first or not last:
        return "WATCH"
    if first > start or last < end:
        return "WATCH"
    return "PASS"


def _root_message(
    *,
    status: TdxDiscoveryStatus,
    stock_file_count: int,
    symbol_count: int,
    first: str,
    last: str,
    start: str,
    end: str,
    min_symbols: int,
    probed: int,
) -> str:
    if status == "BLOCK":
        return "No usable A-share stock .day files were found."
    messages = []
    if symbol_count < min_symbols:
        messages.append(f"symbols={symbol_count} below min_symbols={min_symbols}")
    if first and first > start:
        messages.append(f"first covered date {first} is after required start {start}")
    if last and last < end:
        messages.append(f"latest covered date {last} is before required end {end}")
    if probed < stock_file_count:
        messages.append(f"period checked on first {probed} of {stock_file_count} stock files")
    if messages:
        return "; ".join(messages) + "."
    return "Usable stock .day coverage found."


def _best_root(roots: list[TdxDiscoveryRoot]) -> TdxDiscoveryRoot | None:
    if not roots:
        return None
    return max(
        roots,
        key=lambda root: (
            _status_rank(root.status),
            root.symbol_count,
            root.stock_file_count,
            root.day_file_count,
        ),
    )


def _status_rank(status: str) -> int:
    return {"PASS": 2, "WATCH": 1, "BLOCK": 0}.get(status, 0)


def _report_status(
    best: TdxDiscoveryRoot | None,
    roots: list[TdxDiscoveryRoot],
) -> TdxDiscoveryStatus:
    if best is None or not roots or best.status == "BLOCK":
        return "BLOCK"
    return best.status


def _next_actions(status: TdxDiscoveryStatus, best: TdxDiscoveryRoot | None) -> list[str]:
    if best is None or status == "BLOCK":
        return [
            "Install or locate TongDaXin vipdoc .day files, then rerun discovery with --search-dir.",
            "If TDX data is unavailable, use broker/vendor CSV export instead.",
        ]
    if status == "WATCH":
        return [
            "Review symbol breadth and date coverage before conversion.",
            "Convert the best root only if WATCH gaps are acceptable for research.",
            "Fill source QA answers after conversion; TDX discovery is not license or adjustment evidence.",
        ]
    return [
        "Convert the best root into data_exports, then fill source QA answers.",
        "Run real-data handoff, offline package, and guarded intake before candidate experiments.",
    ]


def _next_commands(
    *,
    best_root: str,
    config_path: str | Path,
    data_output_dir: str | Path,
    output_dir: str | Path,
    start: str,
    end: str,
    as_of: str | None,
    min_symbols: int,
) -> list[str]:
    if not best_root:
        return [
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_tdx_day_discovery.py "
                f"--config {config_path} --output-dir {output_dir} "
                "--search-dir <tdx-vipdoc-or-lday-dir>"
            )
        ]
    as_of_arg = f" --as-of {as_of}" if as_of else ""
    return [
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_tdx_ohlcv_intake.py "
            f"--input-dir {best_root} --data-dir {data_output_dir} --output-dir {output_dir} "
            f"--config {config_path} --min-symbols {min_symbols} --start {start} --end {end}{as_of_arg}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\convert_tdx_day.py "
            f"--input-dir {best_root} --output-dir {data_output_dir} --start {start} --end {end}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_real_data_handoff.py "
            f"--data-dir {data_output_dir} --config {config_path} --output-dir {output_dir} "
            f"--min-symbols {min_symbols}{as_of_arg}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_offline_data_package.py "
            f"--data-dir {data_output_dir} --config {config_path} --output-dir {output_dir} "
            f"--source-qa-answers {Path(data_output_dir) / 'data_source_qa_answers.json'} "
            f"--min-symbols {min_symbols}{as_of_arg}"
        ),
    ]


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result = []
    for path in paths:
        key = str(path)
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result
