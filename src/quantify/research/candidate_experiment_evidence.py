"""Evidence handoff for a launched candidate experiment.

The handoff copies foundational research evidence into the candidate
experiment directory so the later deterministic gates review one complete
artifact bundle. It does not generate trading orders or relax any gate.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

EvidenceStatus = Literal["PASS", "WATCH", "BLOCK", "MISSING"]
ReportStatus = Literal["PASS", "WATCH", "BLOCK"]

REQUIRED_JSON_ARTIFACTS: tuple[tuple[str, str, str | None], ...] = (
    ("summary", "summary.json", None),
    ("run_manifest", "run_manifest.json", None),
    ("real_data_bootstrap", "real_data_bootstrap.json", "decision"),
    ("real_data_gate", "real_data_gate.json", "decision"),
    ("data_audit", "data_audit.json", "status"),
    ("robustness", "robustness_report.json", "status"),
    ("walk_forward", "walk_forward_report.json", "status"),
)
OPTIONAL_ARTIFACTS: tuple[tuple[str, str, str | None], ...] = (
    ("market_regime", "market_regime.json", "status"),
    ("orders", "orders.csv", None),
    ("turnover", "turnover.csv", None),
    ("factor_ic", "factor_ic.csv", None),
)
PROHIBITED_ACTIONS = [
    "Do not treat copied evidence as newly generated research.",
    "Do not copy candidate-specific outputs from another experiment as proof for this run.",
    "Do not connect this evidence handoff to real broker order submission.",
    "Do not let LLM output upgrade deterministic evidence status.",
]


@dataclass(frozen=True, slots=True)
class CandidateExperimentEvidenceItem:
    name: str
    status: EvidenceStatus
    source: str
    destination: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "source": self.source,
            "destination": self.destination,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class CandidateExperimentEvidenceReport:
    status: ReportStatus
    source_report_dir: str
    output_dir: str
    source_dirs_checked: list[str]
    copied_artifacts: list[CandidateExperimentEvidenceItem]
    blockers: list[str]
    watch_items: list[str]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source_report_dir": self.source_report_dir,
            "output_dir": self.output_dir,
            "source_dirs_checked": self.source_dirs_checked,
            "copied_artifacts": [item.to_dict() for item in self.copied_artifacts],
            "blockers": self.blockers,
            "watch_items": self.watch_items,
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Candidate Experiment Evidence: {self.status}",
            "",
            f"- Source report directory: `{self.source_report_dir}`",
            f"- Output directory: `{self.output_dir}`",
            "",
            "This handoff copies already-produced research evidence into a candidate experiment bundle.",
            "",
            "## Source Directories Checked",
        ]
        lines.extend(f"- `{item}`" for item in self.source_dirs_checked)
        lines.extend(
            [
                "",
                "## Copied Artifacts",
                "",
                "| artifact | status | source | destination | message |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for item in self.copied_artifacts:
            lines.append(
                f"| `{item.name}` | `{item.status}` | `{item.source or '-'}` | "
                f"`{item.destination or '-'}` | {item.message} |"
            )
        lines.extend(["", "## Blockers"])
        lines.extend(f"- {item}" for item in self.blockers) if self.blockers else lines.append("- None.")
        lines.extend(["", "## Watch Items"])
        lines.extend(f"- {item}" for item in self.watch_items) if self.watch_items else lines.append("- None.")
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def sync_candidate_experiment_evidence(
    source_report_dir: str | Path,
    output_dir: str | Path,
) -> CandidateExperimentEvidenceReport:
    source_root = Path(source_report_dir)
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    source_dirs = _source_dirs(source_root)
    items: list[CandidateExperimentEvidenceItem] = []
    for name, filename, status_key in REQUIRED_JSON_ARTIFACTS:
        items.append(_copy_artifact(name, filename, source_dirs, target, required=True, status_key=status_key))
    for name, filename, status_key in OPTIONAL_ARTIFACTS:
        items.append(_copy_artifact(name, filename, source_dirs, target, required=False, status_key=status_key))

    blockers = [
        f"{item.name}: {item.message}"
        for item in items
        if item.status in {"BLOCK", "MISSING"} and _is_required(item.name)
    ]
    watch_items = [
        f"{item.name}: {item.message}"
        for item in items
        if item.status == "WATCH" or (item.status in {"BLOCK", "MISSING"} and not _is_required(item.name))
    ]
    status = _status(blockers, watch_items)
    return CandidateExperimentEvidenceReport(
        status=status,
        source_report_dir=str(source_root),
        output_dir=str(target),
        source_dirs_checked=[str(item) for item in source_dirs],
        copied_artifacts=items,
        blockers=blockers,
        watch_items=watch_items,
        next_actions=_next_actions(status),
        prohibited_actions=PROHIBITED_ACTIONS,
    )


def write_candidate_experiment_evidence(
    report: CandidateExperimentEvidenceReport,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "candidate_experiment_evidence.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "candidate_experiment_evidence.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _copy_artifact(
    name: str,
    filename: str,
    source_dirs: list[Path],
    target: Path,
    *,
    required: bool,
    status_key: str | None,
) -> CandidateExperimentEvidenceItem:
    source = _find_source(filename, source_dirs)
    destination = target / filename
    if source is None:
        status: EvidenceStatus = "MISSING" if required else "WATCH"
        return CandidateExperimentEvidenceItem(
            name,
            status,
            "",
            str(destination),
            "Required source artifact is missing." if required else "Optional source artifact is missing.",
        )

    payload = _read_json(source) if source.suffix.lower() == ".json" else {}
    status = _artifact_status(name, source, payload, status_key=status_key, required=required)
    shutil.copy2(source, destination)
    _copy_markdown_sibling(source, destination)
    return CandidateExperimentEvidenceItem(
        name,
        status,
        str(source),
        str(destination),
        _message(name, status, source, payload),
    )


def _artifact_status(
    name: str,
    source: Path,
    payload: dict[str, Any],
    *,
    status_key: str | None,
    required: bool,
) -> EvidenceStatus:
    if source.suffix.lower() == ".json" and not payload:
        return "BLOCK" if required else "WATCH"
    if name == "summary":
        assumptions = payload.get("assumptions", {}) if isinstance(payload, dict) else {}
        if isinstance(assumptions, dict) and assumptions.get("demo_data_used") is True:
            return "BLOCK"
        return "PASS"
    if name == "run_manifest":
        if payload.get("demo_data_used") is True:
            return "BLOCK"
        return "PASS"
    if status_key:
        return _normalize_status(payload.get(status_key), required=required)
    return "PASS"


def _normalize_status(value: object, *, required: bool) -> EvidenceStatus:
    text = str(value or "").upper()
    if text == "PASS":
        return "PASS"
    if text == "WATCH":
        return "WATCH"
    if text == "BLOCK":
        return "BLOCK"
    return "BLOCK" if required else "WATCH"


def _message(
    name: str,
    status: EvidenceStatus,
    source: Path,
    payload: dict[str, Any],
) -> str:
    if name == "summary":
        assumptions = payload.get("assumptions", {}) if isinstance(payload, dict) else {}
        demo = assumptions.get("demo_data_used", "unknown") if isinstance(assumptions, dict) else "unknown"
        return f"Copied research summary from {source.name}; demo_data_used={demo}."
    if name == "run_manifest":
        return f"Copied run manifest; demo_data_used={payload.get('demo_data_used', 'unknown')}."
    if status == "PASS":
        return f"Copied {source.name}; source status is PASS."
    if status == "WATCH":
        return f"Copied {source.name}; source status requires manual review."
    return f"Copied {source.name}; source status blocks promotion."


def _copy_markdown_sibling(source: Path, destination: Path) -> None:
    md_source = source.with_suffix(".md")
    if not md_source.exists():
        return
    shutil.copy2(md_source, destination.with_suffix(".md"))


def _source_dirs(source_root: Path) -> list[Path]:
    candidates = [source_root, source_root / "weekly"]
    return [item for item in candidates if item.exists()]


def _find_source(filename: str, source_dirs: list[Path]) -> Path | None:
    return next((root / filename for root in source_dirs if (root / filename).exists()), None)


def _is_required(name: str) -> bool:
    return any(item_name == name for item_name, _, _ in REQUIRED_JSON_ARTIFACTS)


def _status(blockers: list[str], watch_items: list[str]) -> ReportStatus:
    if blockers:
        return "BLOCK"
    if watch_items:
        return "WATCH"
    return "PASS"


def _next_actions(status: ReportStatus) -> list[str]:
    if status == "BLOCK":
        return [
            "Generate missing foundational research artifacts before running candidate experiments.",
            "Use a weekly pipeline output or first-million report with completed weekly evidence as the source.",
            "Do not continue candidate execution while foundational evidence is BLOCK.",
        ]
    if status == "WATCH":
        return [
            "Review WATCH foundational evidence before interpreting candidate results.",
            "Keep the experiment research-only until every downstream deterministic gate is reviewed.",
        ]
    return [
        "Run candidate-specific validation commands against this evidence bundle.",
        "Keep copied evidence tied to the same config, cache, and sample window.",
    ]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
