"""First-million evidence-to-ranking dashboard.

This report links existing deterministic artifacts from data/source QA through
candidate readiness and formal strategy ranking. It is a read-only operator
view: it does not create evidence, rank strategies, approve paper trading, or
authorize broker orders.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

FirstMillionEvidenceRankingDecision = Literal["PASS", "WATCH", "BLOCK"]

PROHIBITED_ACTIONS = [
    "Do not treat this map as a buy/sell signal, strategy recommendation, or profit claim.",
    "Do not use this map to upgrade deterministic PASS/WATCH/BLOCK gates.",
    "Do not mark any chain item complete without changing the underlying evidence artifact.",
    "Do not fabricate source QA evidence, raw bars, market context, candidate results, or approvals.",
    "Do not connect this workflow to real broker order submission.",
]


@dataclass(frozen=True, slots=True)
class FirstMillionEvidenceRankingDashboardItem:
    sequence: int
    area: str
    status: FirstMillionEvidenceRankingDecision
    current_state: str
    required_evidence: str
    next_action: str
    next_command: str
    source_artifacts: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "area": self.area,
            "status": self.status,
            "current_state": self.current_state,
            "required_evidence": self.required_evidence,
            "next_action": self.next_action,
            "next_command": self.next_command,
            "source_artifacts": self.source_artifacts,
        }


@dataclass(frozen=True, slots=True)
class FirstMillionEvidenceRankingDashboard:
    decision: FirstMillionEvidenceRankingDecision
    as_of: str
    report_dir: str
    data_dir: str
    next_area: str
    next_action: str
    top_candidate: str
    top_candidate_basis: str
    can_rank_candidates: bool
    summary: dict[str, Any]
    items: list[FirstMillionEvidenceRankingDashboardItem]
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
            "top_candidate": self.top_candidate,
            "top_candidate_basis": self.top_candidate_basis,
            "can_rank_candidates": self.can_rank_candidates,
            "summary": self.summary,
            "items": [item.to_dict() for item in self.items],
            "command_sequence": self.command_sequence,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# First Million Evidence Ranking Dashboard: {self.decision}",
            "",
            f"- As of: `{self.as_of}`",
            f"- Report directory: `{self.report_dir}`",
            f"- Data directory: `{self.data_dir}`",
            f"- Top candidate: `{self.top_candidate or 'none'}`",
            f"- Top candidate basis: `{self.top_candidate_basis or 'none'}`",
            f"- Can rank candidates: `{self.can_rank_candidates}`",
            f"- Next area: `{self.next_area or 'none'}`",
            f"- Next action: {self.next_action or 'None.'}",
            "",
            "This map is a read-only chain over deterministic evidence. It cannot rank candidates, approve strategies, enter paper trading, or generate broker orders.",
            "",
            "## Summary",
            "",
            "| key | value |",
            "| --- | --- |",
        ]
        for key, value in self.summary.items():
            lines.append(f"| `{key}` | `{_cell(value)}` |")
        lines.extend(["", "## Evidence Chain", ""])
        if self.items:
            lines.append("| seq | status | area | state | required evidence | next action |")
            lines.append("| ---: | --- | --- | --- | --- | --- |")
            for item in self.items:
                lines.append(
                    f"| {item.sequence} | `{item.status}` | `{item.area}` | `{_cell(item.current_state)}` | {_cell(item.required_evidence)} | {_cell(item.next_action)} |"
                )
        else:
            lines.append("- None.")
        lines.extend(["", "## Command Sequence"])
        for index, command in enumerate(self.command_sequence, start=1):
            lines.extend(["", f"{index}.", "", "```powershell", command, "```"])
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_first_million_evidence_ranking_dashboard(
    report_dir: str | Path = "results/first_million",
    *,
    data_dir: str | Path = "data_exports",
    as_of: str | None = None,
) -> FirstMillionEvidenceRankingDashboard:
    root = Path(report_dir)
    data_root = Path(data_dir)
    data_intake = _read_json(root / "data_intake_status.json")
    source_closeout = _read_json(root / "source_qa_closeout.json")
    evidence_inbox = _read_json(root / "source_qa_evidence_inbox.json")
    raw_bars = _read_json(root / "raw_bars_discovery.json")
    ohlcv_closeout = _read_json(root / "ohlcv_intake_closeout.json")
    market_index = _read_json(root / "market_index_discovery.json")
    market_packet = _read_json(root / "market_context_operator_packet.json")
    ohlcv_package = _read_json(root / "ohlcv_experiment_package.json")
    candidate_readiness = _read_json(root / "candidate_experiment_readiness.json")
    candidate_completion = _read_json(root / "candidate_experiment_completion.json")
    strategy_discovery = _read_json(root / "strategy_discovery_plan.json")
    ranking_gate = _ranking_gate(strategy_discovery)
    resolved_as_of = str(as_of or _read_as_of(root) or "unspecified")

    items = [
        _source_qa_worksheet_item(root, data_root, data_intake, source_closeout, evidence_inbox),
        _source_qa_attachment_item(root, data_root, evidence_inbox),
        _raw_bars_item(root, data_root, raw_bars, ohlcv_closeout),
        _market_context_item(root, market_index, market_packet),
        _ohlcv_package_item(root, ohlcv_package),
        _candidate_readiness_item(root, candidate_readiness, resolved_as_of),
        _candidate_completion_item(root, candidate_completion),
        _ranking_gate_item(root, strategy_discovery, ranking_gate, resolved_as_of),
    ]
    decision = _decision(items)
    open_items = [item for item in items if item.status in {"BLOCK", "WATCH"}]
    next_item = open_items[0] if open_items else None
    can_rank = bool(strategy_discovery.get("can_rank_candidates") or ranking_gate.get("can_rank_candidates"))
    top_candidate = str(strategy_discovery.get("top_candidate") or "")
    top_candidate_basis = str(strategy_discovery.get("top_candidate_basis") or "none")
    return FirstMillionEvidenceRankingDashboard(
        decision=decision,
        as_of=resolved_as_of,
        report_dir=str(root),
        data_dir=str(data_root),
        next_area=next_item.area if next_item else "",
        next_action=next_item.next_action if next_item else "All chain items are PASS; rerun deterministic review before any paper-stage action.",
        top_candidate=top_candidate,
        top_candidate_basis=top_candidate_basis,
        can_rank_candidates=can_rank,
        summary=_summary(
            data_intake=data_intake,
            evidence_inbox=evidence_inbox,
            raw_bars=raw_bars,
            market_packet=market_packet,
            candidate_readiness=candidate_readiness,
            candidate_completion=candidate_completion,
            strategy_discovery=strategy_discovery,
            ranking_gate=ranking_gate,
        ),
        items=items,
        command_sequence=_command_sequence(items, root=root, data_root=data_root, as_of=resolved_as_of),
        prohibited_actions=PROHIBITED_ACTIONS,
    )


def write_first_million_evidence_ranking_dashboard(
    dashboard: FirstMillionEvidenceRankingDashboard,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "first_million_evidence_ranking_dashboard.json").write_text(
        json.dumps(dashboard.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "first_million_evidence_ranking_dashboard.md").write_text(
        dashboard.to_markdown(),
        encoding="utf-8",
    )
    with (root / "first_million_evidence_ranking_dashboard.csv").open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        fieldnames = [
            "sequence",
            "area",
            "status",
            "current_state",
            "required_evidence",
            "next_action",
            "next_command",
            "source_artifacts",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in dashboard.items:
            row = item.to_dict()
            row["source_artifacts"] = "; ".join(item.source_artifacts)
            writer.writerow(row)
    return root


def _source_qa_worksheet_item(
    root: Path,
    data_root: Path,
    data_intake: dict[str, Any],
    source_closeout: dict[str, Any],
    evidence_inbox: dict[str, Any],
) -> FirstMillionEvidenceRankingDashboardItem:
    summary = data_intake.get("summary") if isinstance(data_intake.get("summary"), dict) else {}
    worksheet_ready = bool(summary.get("worksheet_fill_ready") or evidence_inbox.get("worksheet_fill_command_ready"))
    source_status = _status(source_closeout.get("decision"), missing="BLOCK")
    status = "PASS" if source_status == "PASS" and worksheet_ready else "BLOCK"
    counts = source_closeout.get("counts") if isinstance(source_closeout.get("counts"), dict) else {}
    next_action = str(source_closeout.get("next_action") or data_intake.get("next_action") or "")
    if not next_action:
        next_action = "Fill source QA worksheet rows from retained evidence and rerun source QA closeout."
    return FirstMillionEvidenceRankingDashboardItem(
        sequence=1,
        area="source_qa_worksheet",
        status=_normalize(status),
        current_state=(
            f"worksheet_ready={str(worksheet_ready).lower()}, "
            f"missing_rows={_int(counts.get('missing_worksheet_count'))}"
        ),
        required_evidence="Filled source QA worksheet rows from retained vendor/export evidence.",
        next_action=next_action,
        next_command=_first_command(data_intake, key="command_sequence", default=_data_intake_command(root, data_root)),
        source_artifacts=[
            str(root / "data_intake_status.json"),
            str(root / "source_qa_closeout.json"),
            str(data_root / "data_source_qa_evidence_worksheet.csv"),
        ],
    )


def _source_qa_attachment_item(
    root: Path,
    data_root: Path,
    evidence_inbox: dict[str, Any],
) -> FirstMillionEvidenceRankingDashboardItem:
    status = _normalize(_status(evidence_inbox.get("status"), missing="BLOCK"))
    missing = _int(evidence_inbox.get("missing_item_count"))
    invalid = _int(evidence_inbox.get("invalid_file_count"))
    next_action = _first_issue(evidence_inbox)
    if not next_action:
        next_action = "Collect retained source QA evidence attachments and regenerate the strict manifest."
    return FirstMillionEvidenceRankingDashboardItem(
        sequence=2,
        area="source_qa_attachments",
        status=status,
        current_state=f"missing={missing}, invalid={invalid}",
        required_evidence="Retained local source QA evidence files and strict source_qa_evidence_manifest.json.",
        next_action=next_action,
        next_command=_first_command(evidence_inbox, default=_inbox_command(root, data_root)),
        source_artifacts=[
            str(root / "source_qa_evidence_inbox.json"),
            str(data_root / "source_qa_evidence_manifest.json"),
        ],
    )


def _raw_bars_item(
    root: Path,
    data_root: Path,
    raw_bars: dict[str, Any],
    ohlcv_closeout: dict[str, Any],
) -> FirstMillionEvidenceRankingDashboardItem:
    raw_status = _status(raw_bars.get("status"), missing="BLOCK")
    closeout_status = _status(ohlcv_closeout.get("decision"), missing="BLOCK")
    status = "PASS" if raw_status == "PASS" and closeout_status == "PASS" else "BLOCK"
    best = str(raw_bars.get("best_candidate") or "")
    next_action = _first_issue(raw_bars) or _first_issue(ohlcv_closeout)
    if not next_action:
        next_action = "Place retained A-share daily bars CSV in the raw dropzone, then run guarded OHLCV closeout."
    return FirstMillionEvidenceRankingDashboardItem(
        sequence=3,
        area="raw_bars_to_guarded_ohlcv",
        status=_normalize(status),
        current_state=f"raw={raw_status}, ohlcv_closeout={closeout_status}, best={best or 'none'}",
        required_evidence="Non-template A-share daily OHLCV export, normalized cache, and guarded closeout PASS.",
        next_action=next_action,
        next_command=_first_command(raw_bars, default=_raw_discovery_command(root, data_root)),
        source_artifacts=[
            str(root / "raw_bars_discovery.json"),
            str(root / "ohlcv_intake_closeout.json"),
        ],
    )


def _market_context_item(
    root: Path,
    market_index: dict[str, Any],
    market_packet: dict[str, Any],
) -> FirstMillionEvidenceRankingDashboardItem:
    index_status = _status(market_index.get("status"), missing="BLOCK")
    packet_status = _status(market_packet.get("decision"), missing="BLOCK")
    status = "PASS" if index_status == "PASS" and packet_status == "PASS" else "BLOCK"
    next_action = _first_issue(market_packet) or _first_issue(market_index)
    if not next_action:
        next_action = "Provide reviewed market index/context evidence before comparing candidates."
    return FirstMillionEvidenceRankingDashboardItem(
        sequence=4,
        area="market_context",
        status=_normalize(status),
        current_state=f"index={index_status}, packet={packet_status}",
        required_evidence="Reviewed market index CSV or market context packet for the same evidence date.",
        next_action=next_action,
        next_command=_first_command(market_packet, key="command_sequence", default=_market_packet_command(root)),
        source_artifacts=[
            str(root / "market_index_discovery.json"),
            str(root / "market_context_operator_packet.json"),
        ],
    )


def _ohlcv_package_item(root: Path, payload: dict[str, Any]) -> FirstMillionEvidenceRankingDashboardItem:
    status = _normalize(_status(payload.get("decision"), missing="BLOCK"))
    bars = payload.get("bars") if isinstance(payload.get("bars"), dict) else {}
    next_action = _first_issue(payload)
    if not next_action:
        next_action = "Prepare an OHLCV experiment package from audited real daily data."
    return FirstMillionEvidenceRankingDashboardItem(
        sequence=5,
        area="ohlcv_experiment_package",
        status=status,
        current_state=(
            f"launch_allowed={str(bool(payload.get('launch_research_allowed'))).lower()}, "
            f"symbols={_int(bars.get('symbol_count'))}, trading_days={_int(bars.get('trading_day_count'))}"
        ),
        required_evidence="OHLCV package PASS with sufficient symbols, trading days, and source QA evidence.",
        next_action=next_action,
        next_command=_ohlcv_package_command(root),
        source_artifacts=[str(root / "ohlcv_experiment_package.json")],
    )


def _candidate_readiness_item(
    root: Path,
    payload: dict[str, Any],
    as_of: str,
) -> FirstMillionEvidenceRankingDashboardItem:
    status = _normalize(_status(payload.get("decision"), missing="BLOCK"))
    runnable = _int(payload.get("runnable_count"))
    blocked = _int(payload.get("blocked_count"))
    next_action = _first_issue(payload)
    if not next_action:
        next_action = "Reach at least one READY candidate before launching research experiments."
    return FirstMillionEvidenceRankingDashboardItem(
        sequence=6,
        area="candidate_experiment_readiness",
        status=status,
        current_state=f"runnable={runnable}, blocked={blocked}",
        required_evidence="At least one pre-registered candidate is READY under deterministic readiness review.",
        next_action=next_action,
        next_command=_strategy_discovery_command(root, as_of),
        source_artifacts=[str(root / "candidate_experiment_readiness.json")],
    )


def _candidate_completion_item(root: Path, payload: dict[str, Any]) -> FirstMillionEvidenceRankingDashboardItem:
    status = _normalize(_status(payload.get("decision"), missing="BLOCK"))
    candidate = str(payload.get("selected_candidate") or "")
    next_action = _first_issue(payload)
    if not next_action:
        next_action = "Run and complete a guarded candidate research packet before formal ranking."
    return FirstMillionEvidenceRankingDashboardItem(
        sequence=7,
        area="candidate_experiment_completion",
        status=status,
        current_state=f"selected_candidate={candidate or 'none'}",
        required_evidence="Completed research run, stress matrix, diagnostics, and completion review PASS.",
        next_action=next_action,
        next_command=(
            ".\\.venv\\Scripts\\python.exe examples\\run_candidate_experiment_completion.py "
            f"--report-dir {root}"
        ),
        source_artifacts=[str(root / "candidate_experiment_completion.json")],
    )


def _ranking_gate_item(
    root: Path,
    strategy_discovery: dict[str, Any],
    ranking_gate: dict[str, Any],
    as_of: str,
) -> FirstMillionEvidenceRankingDashboardItem:
    status = _normalize(_status(ranking_gate.get("status"), missing="BLOCK"))
    can_rank = bool(strategy_discovery.get("can_rank_candidates") or ranking_gate.get("can_rank_candidates"))
    first_blocker = _first_list_item(ranking_gate, "blocked_by")
    next_action = first_blocker or "Review candidate_selection.json and completed research evidence."
    return FirstMillionEvidenceRankingDashboardItem(
        sequence=8,
        area="strategy_ranking_gate",
        status=status,
        current_state=(
            f"can_rank={str(can_rank).lower()}, "
            f"candidate_selection={_status(ranking_gate.get('candidate_selection_status'), missing='MISSING')}, "
            f"ranked={_int(ranking_gate.get('ranked_candidate_count'))}"
        ),
        required_evidence="PASS candidate_selection.json after completed deterministic research evidence.",
        next_action=next_action,
        next_command=_strategy_discovery_command(root, as_of),
        source_artifacts=[str(root / "strategy_discovery_plan.json")],
    )


def _summary(
    *,
    data_intake: dict[str, Any],
    evidence_inbox: dict[str, Any],
    raw_bars: dict[str, Any],
    market_packet: dict[str, Any],
    candidate_readiness: dict[str, Any],
    candidate_completion: dict[str, Any],
    strategy_discovery: dict[str, Any],
    ranking_gate: dict[str, Any],
) -> dict[str, Any]:
    data_summary = data_intake.get("summary") if isinstance(data_intake.get("summary"), dict) else {}
    return {
        "data_intake_decision": _status(data_intake.get("decision"), missing="MISSING"),
        "source_evidence_status": _status(evidence_inbox.get("status"), missing="MISSING"),
        "source_evidence_missing": _int(evidence_inbox.get("missing_item_count")),
        "raw_bars_status": _status(raw_bars.get("status"), missing="MISSING"),
        "raw_bars_best_candidate": str(raw_bars.get("best_candidate") or ""),
        "market_context_status": _status(market_packet.get("decision"), missing="MISSING"),
        "candidate_readiness_decision": _status(candidate_readiness.get("decision"), missing="MISSING"),
        "candidate_runnable_count": _int(candidate_readiness.get("runnable_count")),
        "candidate_completion_decision": _status(candidate_completion.get("decision"), missing="MISSING"),
        "ranking_gate_status": _status(ranking_gate.get("status"), missing="MISSING"),
        "can_rank_candidates": bool(strategy_discovery.get("can_rank_candidates") or ranking_gate.get("can_rank_candidates")),
        "top_candidate": str(strategy_discovery.get("top_candidate") or ""),
        "top_candidate_basis": str(strategy_discovery.get("top_candidate_basis") or "none"),
        "first_ranking_blocker": _first_list_item(ranking_gate, "blocked_by"),
        "worksheet_fill_ready": bool(data_summary.get("worksheet_fill_ready")),
    }


def _command_sequence(
    items: list[FirstMillionEvidenceRankingDashboardItem],
    *,
    root: Path,
    data_root: Path,
    as_of: str,
) -> list[str]:
    commands = [item.next_command for item in items if item.status in {"BLOCK", "WATCH"} and item.next_command]
    commands.extend(
        [
            _strategy_discovery_command(root, as_of),
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_first_million_daily_brief.py "
                f"--report-dir {root} --as-of {as_of}"
            ),
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_first_million_evidence_ranking_dashboard.py "
                f"--report-dir {root} --data-dir {data_root} --as-of {as_of}"
            ),
        ]
    )
    return _dedupe(commands)[:16]


def _decision(
    items: list[FirstMillionEvidenceRankingDashboardItem],
) -> FirstMillionEvidenceRankingDecision:
    if not items or any(item.status == "BLOCK" for item in items):
        return "BLOCK"
    if any(item.status == "WATCH" for item in items):
        return "WATCH"
    return "PASS"


def _ranking_gate(strategy_discovery: dict[str, Any]) -> dict[str, Any]:
    gate = strategy_discovery.get("ranking_gate")
    return gate if isinstance(gate, dict) else {}


def _data_intake_command(root: Path, data_root: Path) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\run_data_intake_status.py "
        f"--report-dir {root} --data-dir {data_root}"
    )


def _inbox_command(root: Path, data_root: Path) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_evidence_inbox.py "
        f"--data-dir {data_root} --report-dir {root}"
    )


def _raw_discovery_command(root: Path, data_root: Path) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\run_raw_bars_discovery.py "
        f"--search-dir {data_root / 'raw'} --config config\\research_recent.yaml "
        f"--output-dir {root} --data-output-dir {data_root} --write-dropzone-kit --min-symbols 300"
    )


def _market_packet_command(root: Path) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\run_market_context_operator_packet.py "
        f"--report-dir {root}"
    )


def _ohlcv_package_command(root: Path) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\run_ohlcv_experiment_package.py "
        "--data-dir data_exports "
        f"--report-dir {root} --config config\\research_recent.yaml "
        "--source-qa-answers data_exports\\data_source_qa_answers.json "
        "--source-qa-evidence-manifest data_exports\\source_qa_evidence_manifest.json "
        "--require-source-qa-evidence-manifest --min-symbols 300 --min-trading-days 240"
    )


def _strategy_discovery_command(root: Path, as_of: str) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\run_strategy_discovery_plan.py "
        f"--report-dir {root} --config config\\research_recent.yaml --as-of {as_of}"
    )


def _first_command(payload: dict[str, Any], *, key: str = "next_commands", default: str = "") -> str:
    values = payload.get(key)
    if isinstance(values, list):
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
    text = str(payload.get("next_command") or "").strip()
    return text or default


def _first_issue(payload: dict[str, Any]) -> str:
    text = str(payload.get("next_action") or "").strip()
    if text:
        return text
    for key in ("blockers", "watch_items", "next_actions"):
        value = _first_list_item(payload, key)
        if value:
            return value
    for item in payload.get("items", []) or []:
        if isinstance(item, dict):
            item_type = str(item.get("item_type") or item.get("area") or "item")
            item_id = str(item.get("item_id") or item.get("item") or "unknown")
            required = str(item.get("required_value") or item.get("next_action") or item.get("current_state") or "")
            return f"{item_type}/{item_id}: {required}".strip()
    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if isinstance(candidate, dict):
                text = str(candidate.get("message") or "").strip()
                if text:
                    return text
                finding = _first_list_item(candidate, "findings")
                if finding:
                    return finding
    return ""


def _first_list_item(payload: dict[str, Any], key: str) -> str:
    values = payload.get(key)
    if isinstance(values, list):
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
    return ""


def _read_as_of(root: Path) -> str:
    for name in (
        "first_million_daily_brief.json",
        "strategy_discovery_plan.json",
        "first_million_pipeline.json",
    ):
        payload = _read_json(root / name)
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


def _normalize(value: object) -> FirstMillionEvidenceRankingDecision:
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
