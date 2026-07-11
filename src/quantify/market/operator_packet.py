"""Operator packet for market-context evidence collection.

The packet is an execution aid for humans. It does not generate market evidence,
replace cache-derived market_regime.json, approve strategy research, or create
broker instructions.
"""
from __future__ import annotations

from dataclasses import dataclass
import csv
import json
from pathlib import Path
from typing import Any, Literal

from .readiness import (
    MarketContextReadiness,
    build_market_context_readiness_from_report,
)

MarketContextOperatorDecision = Literal["PASS", "WATCH", "BLOCK"]

PROHIBITED_ACTIONS = [
    "Do not fabricate index metrics, screenshots, CSV rows, review notes, or market evidence.",
    "Do not use this packet as market evidence; it is only an operator checklist.",
    "Do not treat market_context_snapshot.json as a replacement for cache-derived market_regime.json.",
    "Do not use market context to approve strategies, promote stages, or relax deterministic gates.",
    "Do not turn market context into a buy/sell signal or LLM trading decision.",
    "Do not connect market context evidence to real broker order submission.",
]

REQUIRED_SNAPSHOT_FIELDS = [
    "as_of",
    "source",
    "reviewed_by",
    "reviewed_at",
]

REQUIRED_INDEX_FIELDS = [
    "name",
    "return_20d",
    "return_60d",
    "return_120d",
    "max_drawdown",
    "annualized_volatility",
    "breadth_above_ma20",
    "breadth_above_ma60",
    "note",
]


@dataclass(frozen=True, slots=True)
class MarketContextOperatorItem:
    item_type: str
    item_id: str
    target: str
    current_state: str
    required_value: str
    acceptable_evidence: str
    unacceptable_evidence: str
    command_after_completion: str

    def to_dict(self) -> dict[str, str]:
        return {
            "item_type": self.item_type,
            "item_id": self.item_id,
            "target": self.target,
            "current_state": self.current_state,
            "required_value": self.required_value,
            "acceptable_evidence": self.acceptable_evidence,
            "unacceptable_evidence": self.unacceptable_evidence,
            "command_after_completion": self.command_after_completion,
        }


@dataclass(frozen=True, slots=True)
class MarketContextOperatorPacket:
    decision: MarketContextOperatorDecision
    as_of: str
    report_dir: str
    readiness_decision: str
    readiness_source: str
    readiness_label: str
    readiness_artifact: str
    snapshot_path: str
    market_regime_path: str
    missing_item_count: int
    items: list[MarketContextOperatorItem]
    command_sequence: list[str]
    acceptance_criteria: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "as_of": self.as_of,
            "report_dir": self.report_dir,
            "readiness_decision": self.readiness_decision,
            "readiness_source": self.readiness_source,
            "readiness_label": self.readiness_label,
            "readiness_artifact": self.readiness_artifact,
            "snapshot_path": self.snapshot_path,
            "market_regime_path": self.market_regime_path,
            "missing_item_count": self.missing_item_count,
            "items": [item.to_dict() for item in self.items],
            "command_sequence": self.command_sequence,
            "acceptance_criteria": self.acceptance_criteria,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Market Context Operator Packet: {self.decision}",
            "",
            f"- As of: `{self.as_of}`",
            f"- Report directory: `{self.report_dir}`",
            f"- Readiness: `{self.readiness_source}` / `{self.readiness_decision}` / `{self.readiness_label}`",
            f"- Readiness artifact: `{self.readiness_artifact or 'missing'}`",
            f"- Snapshot path: `{self.snapshot_path}`",
            f"- Market regime path: `{self.market_regime_path}`",
            f"- Missing items: {self.missing_item_count}",
            "",
            "This packet tells a human operator how to attach market-context evidence. It cannot replace `market_regime.json`, approve strategies, upgrade deterministic gates, or create broker orders.",
            "",
            "## Required Snapshot Fields",
        ]
        lines.extend(f"- `{field}`" for field in REQUIRED_SNAPSHOT_FIELDS)
        lines.extend(["", "## Required Index Metric Fields"])
        lines.extend(f"- `{field}`" for field in REQUIRED_INDEX_FIELDS)
        lines.extend(["", "## Fill Items", ""])
        if self.items:
            lines.append("| type | id | target | state | required | acceptable evidence | do not use |")
            lines.append("| --- | --- | --- | --- | --- | --- | --- |")
            for item in self.items:
                lines.append(
                    f"| `{item.item_type}` | `{item.item_id}` | `{item.target}` | "
                    f"`{item.current_state}` | {_cell(item.required_value)} | "
                    f"{_cell(item.acceptable_evidence)} | {_cell(item.unacceptable_evidence)} |"
                )
        else:
            lines.append("- None.")
        lines.extend(["", "## Command Sequence"])
        for index, command in enumerate(self.command_sequence, start=1):
            lines.extend(["", f"{index}.", "", "```powershell", command, "```"])
        lines.extend(["", "## Acceptance Criteria"])
        lines.extend(f"- {item}" for item in self.acceptance_criteria)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_market_context_operator_packet(
    report_dir: str | Path = "results/first_million",
    *,
    as_of: str | None = None,
    max_staleness_days: int = 7,
    readiness: MarketContextReadiness | None = None,
) -> MarketContextOperatorPacket:
    root = Path(report_dir)
    resolved_readiness = readiness or build_market_context_readiness_from_report(
        root,
        as_of=as_of,
        max_staleness_days=max_staleness_days,
    )
    snapshot_path = root / "market_context_snapshot.json"
    market_regime_path = _market_regime_path(root)
    snapshot_payload = _read_json(snapshot_path)
    items = _items(
        root=root,
        snapshot_payload=snapshot_payload,
        readiness=resolved_readiness,
        as_of=str(as_of or resolved_readiness.target_as_of or _read_as_of(root) or "unspecified"),
    )
    decision = _decision(resolved_readiness, items)
    return MarketContextOperatorPacket(
        decision=decision,
        as_of=str(as_of or resolved_readiness.target_as_of or _read_as_of(root) or "unspecified"),
        report_dir=str(root),
        readiness_decision=resolved_readiness.decision,
        readiness_source=resolved_readiness.source,
        readiness_label=resolved_readiness.label,
        readiness_artifact=resolved_readiness.artifact,
        snapshot_path=str(snapshot_path),
        market_regime_path=str(market_regime_path),
        missing_item_count=len(items),
        items=items,
        command_sequence=_command_sequence(decision),
        acceptance_criteria=[
            "Prefer cache-derived market_regime.json from audited A-share daily data when local cache data is available.",
            "If market_regime.json is not available yet, market_context_snapshot.json must include reviewed metadata and at least one complete index metric.",
            "After writing or refreshing market evidence, run market_context_readiness and keep snapshot-only context at WATCH.",
            "Candidate experiments may proceed only when their separate source QA, data, OHLCV, robustness, paper, and approval gates allow it.",
            "The packet remains research/paper-only and never creates broker instructions.",
        ],
        prohibited_actions=PROHIBITED_ACTIONS,
    )


def write_market_context_operator_packet(
    packet: MarketContextOperatorPacket,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "market_context_operator_packet.json").write_text(
        json.dumps(packet.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "market_context_operator_packet.md").write_text(packet.to_markdown(), encoding="utf-8")
    with (root / "market_context_operator_packet.csv").open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        fieldnames = [
            "item_type",
            "item_id",
            "target",
            "current_state",
            "required_value",
            "acceptable_evidence",
            "unacceptable_evidence",
            "command_after_completion",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(item.to_dict() for item in packet.items)
    return root


def _items(
    *,
    root: Path,
    snapshot_payload: dict[str, Any],
    readiness: MarketContextReadiness,
    as_of: str,
) -> list[MarketContextOperatorItem]:
    if readiness.source == "market_regime" and readiness.decision == "PASS":
        return []

    items: list[MarketContextOperatorItem] = []
    market_regime = _market_regime_path(root)
    snapshot = root / "market_context_snapshot.json"

    if readiness.source != "market_regime":
        items.append(
            MarketContextOperatorItem(
                item_type="preferred_artifact",
                item_id="market_regime",
                target=str(market_regime),
                current_state="missing" if not market_regime.exists() else readiness.decision,
                required_value="Generate cache-derived market_regime.json from audited A-share daily data.",
                acceptable_evidence="Local cache-derived market_regime.json produced by run_market_regime.py using the same reviewed data window.",
                unacceptable_evidence="Manual labels, LLM-written regime notes, screenshots without underlying data, or broker/order instructions.",
                command_after_completion=_run_market_regime_command(),
            )
        )

    if readiness.source == "market_regime":
        if readiness.decision != "PASS":
            items.append(
                MarketContextOperatorItem(
                    item_type="refresh",
                    item_id="market_regime_readiness",
                    target=str(market_regime),
                    current_state=readiness.decision,
                    required_value="Refresh or repair market_regime.json until market_context_readiness is PASS/WATCH with explicit findings.",
                    acceptable_evidence="A regenerated market_regime.json with status, label, as_of/end, and same-window cache metadata.",
                    unacceptable_evidence="Editing JSON status by hand, stale reports, or unreviewed copied artifacts.",
                    command_after_completion=_run_readiness_command(as_of),
                )
            )
        return items

    if readiness.source == "market_context_snapshot" and readiness.decision == "WATCH":
        return items

    for field in REQUIRED_SNAPSHOT_FIELDS:
        if not str(snapshot_payload.get(field) or "").strip():
            items.append(
                MarketContextOperatorItem(
                    item_type="snapshot_metadata",
                    item_id=field,
                    target=str(snapshot),
                    current_state="missing",
                    required_value=_snapshot_field_requirement(field),
                    acceptable_evidence=_snapshot_field_evidence(field),
                    unacceptable_evidence="Placeholders, inferred values, generated notes, or evidence not tied to the reviewed market snapshot.",
                    command_after_completion=_write_snapshot_manual_command(as_of),
                )
            )
    index_metrics = snapshot_payload.get("index_metrics")
    first_metric = index_metrics[0] if isinstance(index_metrics, list) and index_metrics else {}
    if not isinstance(first_metric, dict):
        first_metric = {}
    if not index_metrics:
        items.append(
            MarketContextOperatorItem(
                item_type="snapshot_index_metric",
                item_id="index_metrics",
                target=str(snapshot),
                current_state="missing",
                required_value="Provide at least one reviewed broad A-share index metric row.",
                acceptable_evidence="Reviewed local index CSV/export covering CSI300, CSI500, CSI1000, All-A proxy, or another documented broad A-share index.",
                unacceptable_evidence="Single-stock returns, unsourced web snippets, hand-waved market labels, or LLM-generated figures.",
                command_after_completion=_write_snapshot_manual_command(as_of),
            )
        )
    else:
        for field in REQUIRED_INDEX_FIELDS:
            value = first_metric.get(field)
            if value is None or str(value).strip() == "":
                items.append(
                    MarketContextOperatorItem(
                        item_type="snapshot_index_metric",
                        item_id=field,
                        target=str(snapshot),
                        current_state="missing",
                        required_value=_index_field_requirement(field),
                        acceptable_evidence=_index_field_evidence(field),
                        unacceptable_evidence="Synthetic metrics, approximations without source rows, or values copied from unrelated dates.",
                        command_after_completion=_write_snapshot_manual_command(as_of),
                    )
                )
    return items


def _decision(
    readiness: MarketContextReadiness,
    items: list[MarketContextOperatorItem],
) -> MarketContextOperatorDecision:
    if readiness.decision == "BLOCK":
        return "BLOCK"
    if any(item.item_type.startswith("snapshot_") for item in items):
        return "BLOCK"
    if readiness.decision == "WATCH" or items:
        return "WATCH"
    return "PASS"


def _command_sequence(decision: MarketContextOperatorDecision) -> list[str]:
    if decision == "PASS":
        return [_run_readiness_command("<YYYY-MM-DD>")]
    return [
        _run_market_regime_command(),
        _run_market_index_discovery_command("<YYYY-MM-DD>"),
        _write_snapshot_manual_command("<YYYY-MM-DD>"),
        _write_snapshot_csv_command("<YYYY-MM-DD>"),
        _run_readiness_command("<YYYY-MM-DD>"),
    ]


def _run_market_regime_command() -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\run_market_regime.py "
        "--config config\\research_recent.yaml --output-dir results\\first_million"
    )


def _run_market_index_discovery_command(as_of: str) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\run_market_index_discovery.py "
        "--search-dir data_exports\\indices --output-dir results\\first_million "
        f"--as-of {as_of}"
    )


def _write_snapshot_manual_command(as_of: str) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\write_market_context_snapshot.py "
        f"--output-dir results\\first_million --as-of {as_of} "
        '--source "<reviewed-index-source>" --reviewed-by "<name>" --reviewed-at <YYYY-MM-DD> '
        '--index "CSI300,0.01,0.03,0.04,0.08,0.22,0.55,0.50,reviewed note"'
    )


def _write_snapshot_csv_command(as_of: str) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\write_market_context_snapshot.py "
        f"--output-dir results\\first_million --as-of {as_of} "
        '--source "<reviewed-index-csv-export>" --reviewed-by "<name>" '
        "--reviewed-at <YYYY-MM-DD> --index-csv data_exports\\indices\\indices.csv --encoding auto"
    )


def _run_readiness_command(as_of: str) -> str:
    return (
        ".\\.venv\\Scripts\\python.exe examples\\run_market_context_readiness.py "
        f"--report-dir results\\first_million --as-of {as_of}"
    )


def _snapshot_field_requirement(field: str) -> str:
    values = {
        "as_of": "Record the market snapshot date as YYYY-MM-DD.",
        "source": "Name the reviewed external index source or retained local CSV export.",
        "reviewed_by": "Record the human reviewer name or operator identifier.",
        "reviewed_at": "Record the human review date as YYYY-MM-DD.",
    }
    return values[field]


def _snapshot_field_evidence(field: str) -> str:
    values = {
        "as_of": "Index export date, retained data file timestamp, or review note tied to the date.",
        "source": "Vendor/export metadata, terminal screenshot, or retained local CSV path and hash note.",
        "reviewed_by": "Attributable human review note; LLM text cannot sign off evidence.",
        "reviewed_at": "Review log, ticket, or local note with reviewer/date.",
    }
    return values[field]


def _index_field_requirement(field: str) -> str:
    values = {
        "name": "Index name or symbol, e.g. CSI300 or CSI500.",
        "return_20d": "20-trading-day index return as a decimal.",
        "return_60d": "60-trading-day index return as a decimal.",
        "return_120d": "120-trading-day index return as a decimal.",
        "max_drawdown": "Recent window max drawdown as a positive decimal.",
        "annualized_volatility": "Annualized index volatility as a decimal.",
        "breadth_above_ma20": "Share of reviewed universe/index constituents above MA20, if supplied.",
        "breadth_above_ma60": "Share of reviewed universe/index constituents above MA60, if supplied.",
        "note": "Short note explaining rows, source window, or limitation.",
    }
    return values[field]


def _index_field_evidence(field: str) -> str:
    if field == "note":
        return "Reviewer note tied to retained index rows, source window, or known limitations."
    if field == "name":
        return "Index CSV/export column or terminal label identifying the index series."
    return "Retained index daily close CSV/export or reviewed metric calculation record."


def _market_regime_path(root: Path) -> Path:
    local = root / "market_regime.json"
    if local.exists():
        return local
    weekly = root / "weekly" / "market_regime.json"
    return weekly if weekly.exists() else local


def _read_as_of(root: Path) -> str:
    for name in ("market_context_readiness.json", "first_million_daily_brief.json", "first_million_pipeline.json"):
        payload = _read_json(root / name)
        text = str(payload.get("target_as_of") or payload.get("as_of") or "")
        if text:
            return text
    return ""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _cell(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")
