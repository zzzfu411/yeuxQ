"""Discover local index CSV files for market-context snapshots.

This module is read-only. It helps an operator find reviewed broad A-share
index CSV exports that can feed market_context_snapshot.json. It does not
download data, infer truth from screenshots, approve strategies, or trade.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from quantify.market.snapshot import read_market_context_index_metrics_from_csvs

MarketIndexDiscoveryStatus = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class MarketIndexCandidate:
    path: str
    exists: bool
    size_bytes: int
    status: MarketIndexDiscoveryStatus
    index_count: int
    index_names: list[str]
    findings: list[str]
    snapshot_command: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "exists": self.exists,
            "size_bytes": self.size_bytes,
            "status": self.status,
            "index_count": self.index_count,
            "index_names": self.index_names,
            "findings": self.findings,
            "snapshot_command": self.snapshot_command,
        }


@dataclass(frozen=True, slots=True)
class MarketIndexDiscoveryReport:
    status: MarketIndexDiscoveryStatus
    as_of: str
    output_dir: str
    search_dirs: list[str]
    pattern: str
    candidates: list[MarketIndexCandidate]
    best_candidate: str
    next_commands: list[str]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "as_of": self.as_of,
            "output_dir": self.output_dir,
            "search_dirs": self.search_dirs,
            "pattern": self.pattern,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "best_candidate": self.best_candidate,
            "next_commands": self.next_commands,
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Market Index CSV Discovery: {self.status}",
            "",
            f"- As of: `{self.as_of}`",
            f"- Output directory: `{self.output_dir}`",
            f"- Search directories: `{', '.join(self.search_dirs) or 'none'}`",
            f"- Pattern: `{self.pattern}`",
            f"- Best candidate: `{self.best_candidate or 'none'}`",
            "",
            "This report only discovers local index CSV files for market-context snapshots. It is not market evidence by itself, not a strategy approval, and not a broker workflow.",
            "",
            "## Candidates",
            "",
            "| status | path | indices | names | findings |",
            "| --- | --- | ---: | --- | --- |",
        ]
        for candidate in self.candidates:
            lines.append(
                "| `{status}` | `{path}` | {count} | {names} | {findings} |".format(
                    status=candidate.status,
                    path=candidate.path,
                    count=candidate.index_count,
                    names=_cell(", ".join(candidate.index_names) or "none"),
                    findings=_cell("; ".join(candidate.findings) or "none"),
                )
            )
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Next Commands"])
        for command in self.next_commands:
            lines.extend(["", "```powershell", command, "```"])
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_market_index_discovery_report(
    *,
    search_dirs: list[str | Path] | None = None,
    output_dir: str | Path = "results/first_million",
    as_of: str,
    pattern: str = "*.csv",
    encoding: str = "auto",
    max_files: int = 50,
) -> MarketIndexDiscoveryReport:
    roots = _candidate_roots(search_dirs)
    paths = _candidate_files(roots, pattern=pattern, max_files=max_files)
    candidates = [
        _candidate(
            path,
            as_of=as_of,
            output_dir=output_dir,
            encoding=encoding,
        )
        for path in paths
    ]
    if not candidates:
        candidates = [_missing_candidate(root, as_of=as_of, output_dir=output_dir) for root in roots]
    best = _best_candidate(candidates)
    status = _report_status(best)
    best_path = best.path if best and best.status != "BLOCK" else ""
    return MarketIndexDiscoveryReport(
        status=status,
        as_of=as_of,
        output_dir=str(output_dir),
        search_dirs=[str(root) for root in roots],
        pattern=pattern,
        candidates=candidates,
        best_candidate=best_path,
        next_commands=_next_commands(best if best and best.status != "BLOCK" else None),
        next_actions=_next_actions(status, best),
        prohibited_actions=[
            "Do not treat index CSV discovery as market_regime.json or strategy evidence.",
            "Do not use single-stock files, generated examples, or template CSVs as market context.",
            "Do not let market_context_snapshot replace cache-derived market_regime.json.",
            "Do not connect market context output to real broker order submission.",
        ],
    )


def write_market_index_discovery_report(
    report: MarketIndexDiscoveryReport,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "market_index_discovery.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "market_index_discovery.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _candidate(
    path: Path,
    *,
    as_of: str,
    output_dir: str | Path,
    encoding: str,
) -> MarketIndexCandidate:
    metrics, findings = read_market_context_index_metrics_from_csvs(
        csv_paths=[path],
        as_of=as_of,
        encoding=encoding,
    )
    status = _candidate_status(metrics, findings)
    return MarketIndexCandidate(
        path=str(path),
        exists=True,
        size_bytes=path.stat().st_size,
        status=status,
        index_count=len(metrics),
        index_names=[item.name for item in metrics],
        findings=findings,
        snapshot_command=_snapshot_command(path=path, as_of=as_of, output_dir=output_dir, encoding=encoding),
    )


def _missing_candidate(
    root: Path,
    *,
    as_of: str,
    output_dir: str | Path,
) -> MarketIndexCandidate:
    return MarketIndexCandidate(
        path=str(root),
        exists=root.exists(),
        size_bytes=0,
        status="BLOCK",
        index_count=0,
        index_names=[],
        findings=["No candidate index CSV files were found."],
        snapshot_command=_snapshot_command(
            path=root / "indices.csv",
            as_of=as_of,
            output_dir=output_dir,
            encoding="auto",
        ),
    )


def _candidate_roots(search_dirs: list[str | Path] | None) -> list[Path]:
    if search_dirs:
        return _dedupe_paths([Path(path) for path in search_dirs])
    return _dedupe_paths(
        [
            Path("data_exports/indices"),
            Path("data_exports/index"),
            Path("data_exports/raw"),
            Path("data_exports"),
            Path("raw_data/indices"),
        ]
    )


def _candidate_files(roots: list[Path], *, pattern: str, max_files: int) -> list[Path]:
    explicit_files: list[Path] = []
    discovered_files: list[Path] = []
    for root in roots:
        if root.is_file():
            if root.suffix.lower() == ".csv":
                explicit_files.append(root)
            continue
        if not root.exists():
            continue
        discovered_files.extend(
            path
            for path in root.rglob(pattern)
            if path.is_file() and path.suffix.lower() == ".csv"
        )
    filtered = [
        path
        for path in _dedupe_paths([*explicit_files, *discovered_files])
        if path in explicit_files or (_looks_like_index_file(path) and path.name not in _excluded_file_names())
    ]
    return sorted(filtered, key=lambda path: path.stat().st_size if path.exists() else 0, reverse=True)[:max_files]


def _looks_like_index_file(path: Path) -> bool:
    text = path.stem.lower()
    tokens = (
        "index",
        "indices",
        "csi",
        "hs300",
        "zz500",
        "zz1000",
        "000300",
        "000905",
        "000852",
        "000906",
        "399300",
        "399905",
    )
    return any(token in text for token in tokens)


def _excluded_file_names() -> set[str]:
    return {
        "index_constituents.csv",
        "data_source_qa_evidence_worksheet.csv",
        "source_qa_evidence_manifest.csv",
    }


def _candidate_status(
    metrics,
    findings: list[str],
) -> MarketIndexDiscoveryStatus:
    if not metrics or any(str(item).startswith("BLOCK:") for item in findings):
        return "BLOCK"
    if any(str(item).startswith("WATCH:") for item in findings):
        return "WATCH"
    return "PASS"


def _best_candidate(candidates: list[MarketIndexCandidate]) -> MarketIndexCandidate | None:
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            _status_rank(item.status),
            item.index_count,
            item.size_bytes,
        ),
    )


def _report_status(candidate: MarketIndexCandidate | None) -> MarketIndexDiscoveryStatus:
    if candidate is None:
        return "BLOCK"
    return candidate.status


def _next_commands(candidate: MarketIndexCandidate | None) -> list[str]:
    if candidate is None:
        return [
            ".\\.venv\\Scripts\\python.exe examples\\run_market_index_discovery.py --search-dir data_exports\\indices --output-dir results\\first_million --as-of <YYYY-MM-DD>",
        ]
    return [
        candidate.snapshot_command,
        ".\\.venv\\Scripts\\python.exe examples\\run_market_context_readiness.py --report-dir results\\first_million --as-of <YYYY-MM-DD>",
        ".\\.venv\\Scripts\\python.exe examples\\run_first_million_pipeline.py --config config\\research_recent.yaml --data-dir data_exports --output-dir results\\first_million --source-qa-answers data_exports\\data_source_qa_answers.json --source-qa-evidence-manifest data_exports\\source_qa_evidence_manifest.json --require-source-qa-evidence-manifest --no-registry",
    ]


def _next_actions(
    status: MarketIndexDiscoveryStatus,
    candidate: MarketIndexCandidate | None,
) -> list[str]:
    if candidate is None or status == "BLOCK":
        return [
            "Place a reviewed broad A-share index daily CSV under data_exports\\indices, then rerun market index discovery.",
            "Use columns date and close; optional long-form columns include index/name/symbol/code and breadth_above_ma20/breadth_above_ma60.",
            "Keep candidate experiments blocked until market_context_readiness and the separate source/data gates allow them.",
        ]
    if status == "WATCH":
        return [
            f"Review WATCH findings for {candidate.path}, then create market_context_snapshot.json if the evidence is acceptable.",
            "Snapshot-only market context remains advisory and cannot replace cache-derived market_regime.json.",
        ]
    return [
        f"Create market_context_snapshot.json from {candidate.path}, then rerun market_context_readiness.",
        "Continue to prefer cache-derived market_regime.json once audited A-share daily data is available.",
    ]


def _snapshot_command(
    *,
    path: Path,
    as_of: str,
    output_dir: str | Path,
    encoding: str,
) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\write_market_context_snapshot.py "
        f"--output-dir {output_dir} --as-of {as_of} "
        '--source "<reviewed-index-csv-export>" --reviewed-by "<name>" '
        f"--reviewed-at <YYYY-MM-DD> --index-csv {path} --encoding {encoding}"
    )


def _status_rank(status: str) -> int:
    return {"PASS": 2, "WATCH": 1, "BLOCK": 0}.get(status, 0)


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
