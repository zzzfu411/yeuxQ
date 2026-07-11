"""Single-screen readiness card for the first-million research workflow."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from typing import Any, Literal

from quantify.data.cache_metadata import build_promotion_metadata_check, cache_metadata_blockers
from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.data.offline_package import format_source_provenance
from quantify.goal.status import _evaluate_cache_gate

ReadinessStatus = Literal["PASS", "WATCH", "BLOCK", "MISSING", "UNKNOWN"]
ReadinessDecision = Literal["PASS", "WATCH", "BLOCK"]

PROHIBITED_ACTIONS = [
    "Do not start strategy search or make profit-claim wording while this readiness card is BLOCK.",
    "Do not run candidate experiments while this readiness card is BLOCK.",
    "Do not treat readiness PASS as a promise of profit.",
    "Do not enter paper or micro-live readiness from a partial evidence set.",
    "Do not connect this workflow to real broker order submission.",
    "Do not let LLM output upgrade deterministic readiness status.",
]


@dataclass(frozen=True, slots=True)
class FirstMillionReadinessGate:
    name: str
    status: ReadinessStatus
    artifact: str
    message: str
    next_action: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "artifact": self.artifact,
            "message": self.message,
            "next_action": self.next_action,
        }


@dataclass(frozen=True, slots=True)
class FirstMillionReadinessCard:
    decision: ReadinessDecision
    as_of: str
    report_dir: str
    gates: list[FirstMillionReadinessGate]
    blockers: list[str]
    watch_items: list[str]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "as_of": self.as_of,
            "report_dir": self.report_dir,
            "gates": [gate.to_dict() for gate in self.gates],
            "blockers": self.blockers,
            "watch_items": self.watch_items,
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# First Million Readiness: {self.decision}",
            "",
            f"- As of: `{self.as_of}`",
            f"- Report directory: `{self.report_dir}`",
            "",
            "This card summarizes evidence readiness only. It is not a strategy recommendation or a live trading instruction.",
            "",
            "## Gate Summary",
            "",
            "| gate | status | artifact | message | next action |",
            "| --- | --- | --- | --- | --- |",
        ]
        for gate in self.gates:
            lines.append(
                f"| `{gate.name}` | `{gate.status}` | `{gate.artifact}` | "
                f"{gate.message} | {gate.next_action} |"
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


def build_first_million_readiness_card(
    report_dir: str | Path,
    *,
    as_of: str | None = None,
    cfg=None,
    min_symbols: int = 300,
    min_trading_days: int = 240,
) -> FirstMillionReadinessCard:
    root = Path(report_dir)
    config_gates = []
    if cfg is not None:
        config_gates.extend(
            [
                _research_cache_admissibility_gate(
                    cfg,
                    as_of=as_of,
                    min_symbols=min_symbols,
                    min_trading_days=min_trading_days,
                ),
                _current_data_cache_gate(
                    cfg,
                    as_of=as_of,
                    min_symbols=min_symbols,
                    min_trading_days=min_trading_days,
                ),
            ]
        )
    if cfg is not None or (root / "promotion_metadata_check.json").exists():
        config_gates.append(_promotion_metadata_gate(root, cfg))
    gates = [
        *config_gates,
        _recent_data_acquisition_gate(root),
        _provider_smoke_readiness_gate(root),
        _provider_acquisition_ramp_gate(root),
        _data_gap_gate(root),
        _data_evidence_packet_gate(root),
        _operator_handoff_status_gate(root),
        _csv_intake_preview_gate(root),
        _offline_package_gate(root),
        _real_data_handoff_gate(root),
        _source_qa_preflight_gate(root),
        _source_qa_gate(root),
        _offline_intake_gate(root),
        _market_context_readiness_gate(root),
        _candidate_readiness_gate(root),
        _candidate_launch_gate(root),
        _candidate_execution_gate(root),
        _candidate_completion_gate(root),
        _run_manifest_gate(root),
        _micro_live_readiness_gate(root),
        _capital_scaling_plan_gate(root),
        _capital_goal_gate(root),
        _compounding_path_gate(root),
    ]
    decision = _decision(gates)
    return FirstMillionReadinessCard(
        decision=decision,
        as_of=as_of or date.today().isoformat(),
        report_dir=str(root),
        gates=gates,
        blockers=[f"{gate.name}: {gate.message}" for gate in gates if gate.status in {"BLOCK", "MISSING", "UNKNOWN"}],
        watch_items=[f"{gate.name}: {gate.message}" for gate in gates if gate.status == "WATCH"],
        next_actions=_next_actions(gates),
        prohibited_actions=PROHIBITED_ACTIONS,
    )


def write_first_million_readiness_card(
    card: FirstMillionReadinessCard,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "first_million_readiness.json").write_text(
        json.dumps(card.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "first_million_readiness.md").write_text(card.to_markdown(), encoding="utf-8")
    return root


def _recent_data_acquisition_gate(root: Path) -> FirstMillionReadinessGate:
    path = root / "recent_data_acquisition_plan.json"
    payload = _read_json(path)
    if not payload:
        return _missing_gate("recent_data_acquisition_plan", path, "Run recent data acquisition plan.")
    status = _normalize(payload.get("status"))
    latest_import = payload.get("latest_import_attempt", {})
    latest_import = latest_import if isinstance(latest_import, dict) else {}
    if status == "PASS":
        message = (
            f"Current symbols={payload.get('current_symbol_count', 0)}, "
            f"latest_bar={payload.get('current_latest_bar_date', '') or 'missing'}."
        )
    elif bool(latest_import.get("network_blocked")):
        message = _latest_import_failure_message(latest_import)
    else:
        message = _first(payload.get("blockers", []), "Recent data acquisition plan requires review.")
    next_action = str(latest_import.get("next_action") or "") if latest_import else ""
    return FirstMillionReadinessGate(
        "recent_data_acquisition_plan",
        status,
        str(path),
        message,
        next_action or _first_step_command(payload.get("steps", []), "Acquire or import recent A-share data."),
    )


def _provider_smoke_readiness_gate(root: Path) -> FirstMillionReadinessGate:
    path = root / "provider_smoke_readiness.json"
    payload = _read_json(path)
    if not payload:
        return FirstMillionReadinessGate(
            "provider_smoke_readiness",
            "WATCH",
            str(path),
            "Provider smoke readiness has not been generated; this is route diagnostics only.",
            "Run run_provider_smoke_readiness.py or rerun first-million pipeline with --latest-import-report.",
        )
    raw_status = _normalize(payload.get("status"))
    status: ReadinessStatus = "PASS" if raw_status == "PASS" else "WATCH"
    endpoint = str(payload.get("endpoint_viability") or "UNKNOWN")
    data_sufficiency = str(payload.get("data_sufficiency_status") or "UNKNOWN")
    if bool(payload.get("network_blocked")):
        message = (
            "Provider smoke is network/proxy blocked "
            f"(endpoint={endpoint}, route={payload.get('recommended_route', 'offline_csv_or_tdx')})."
        )
    else:
        imported = int(payload.get("imported_symbols") or 0)
        requested = int(payload.get("requested_symbols") or 0)
        message = (
            f"Provider smoke={payload.get('status', 'UNKNOWN')}, endpoint={endpoint}, "
            f"data={data_sufficiency}, imported={imported}/{requested}."
        )
    return FirstMillionReadinessGate(
        "provider_smoke_readiness",
        status,
        str(path),
        message,
        _first(
            payload.get("next_actions", []),
            "Continue through deterministic data/source-QA gates; provider smoke cannot approve readiness.",
        ),
    )


def _provider_acquisition_ramp_gate(root: Path) -> FirstMillionReadinessGate:
    path = root / "provider_acquisition_ramp.json"
    payload = _read_json(path)
    if not payload:
        return FirstMillionReadinessGate(
            "provider_acquisition_ramp",
            "PASS",
            "not_applicable",
            "Provider acquisition ramp was not supplied; this optional route diagnostic is not a data gate.",
            "Run run_provider_acquisition_ramp.py into an isolated cache before scaling provider imports.",
        )
    raw_status = _normalize(payload.get("status"))
    status: ReadinessStatus = "PASS" if raw_status == "PASS" else "WATCH"
    provider = str(payload.get("provider") or "unknown")
    executed = int(payload.get("executed_stage_count") or len(payload.get("stages", []) or []))
    stages = [item for item in payload.get("stages", []) or [] if isinstance(item, dict)]
    last = stages[-1] if stages else {}
    imported = int(last.get("imported_symbols") or 0)
    requested = int(last.get("requested_symbols") or 0)
    if raw_status == "PASS":
        message = (
            f"Provider ramp passed for {provider}; executed_stages={executed}, "
            f"last_stage_imported={imported}/{requested}. Acquisition evidence only."
        )
    else:
        message = (
            f"Provider ramp is {raw_status}; route diagnostics only, "
            f"last_stage_imported={imported}/{requested}. It cannot approve source QA or promotion gates."
        )
    return FirstMillionReadinessGate(
        "provider_acquisition_ramp",
        status,
        str(path),
        message,
        _first(
            payload.get("next_actions", []),
            "Review provider ramp report, then continue through deterministic source-QA and data gates.",
        ),
    )


def _current_data_cache_gate(
    cfg,
    *,
    as_of: str | None,
    min_symbols: int,
    min_trading_days: int,
) -> FirstMillionReadinessGate:
    cache = Path(str(cfg.data.cache_path))
    if not cache.exists():
        return FirstMillionReadinessGate(
            "current_data_cache",
            "BLOCK",
            str(cache),
            "Configured recent research cache does not exist.",
            "Import or ingest recent real A-share data into the configured cache.",
        )
    storage = BarStorage(cache)
    provider = DataProvider(storage)
    gate = _evaluate_cache_gate(
        provider,
        str(cfg.research.start),
        str(cfg.research.end),
        as_of=as_of,
        min_symbols=min_symbols,
        min_trading_days=min_trading_days,
    )
    metadata = storage.load_metadata()
    metadata_blockers = cache_metadata_blockers(metadata)
    message = (
        f"Current cache latest_bar={gate['latest_bar_date'] or 'missing'}, "
        f"symbols={gate['symbol_count']}, trading_days={gate['trading_day_count']}, "
        f"bars={gate['bar_count']}, demo={gate['demo_data_used']}."
    )
    if gate["decision"] == "PASS" and metadata_blockers:
        decision = "BLOCK"
        message += f" Cache metadata blocker: {metadata_blockers[0]}"
        next_action = (
            "Rerun guarded offline intake so the cache records CSV fingerprint, "
            "PASS source QA metadata, and provenance hashes."
        )
    elif gate["decision"] == "PASS":
        decision = "PASS"
        next_action = "Continue through source QA, offline intake, and candidate experiment gates."
    else:
        decision = gate["decision"]
        next_action = "Refresh/import recent real A-share data, then rerun first-million readiness."
    return FirstMillionReadinessGate(
        "current_data_cache",
        decision,
        str(cache),
        message,
        next_action,
    )


def _promotion_metadata_gate(root: Path, cfg) -> FirstMillionReadinessGate:
    path = root / "promotion_metadata_check.json"
    payload = _read_json(path)
    artifact = path
    if not payload:
        if cfg is None:
            return _missing_gate(
                "promotion_metadata_check",
                path,
                "Run check_promotion_metadata.py or rerun first-million pipeline with --config.",
            )
        cache = Path(str(cfg.data.cache_path))
        check = build_promotion_metadata_check(cache)
        payload = check.to_dict()
        artifact = cache
    status = _normalize(payload.get("status"))
    blockers = payload.get("blockers", []) or []
    next_actions = payload.get("next_actions", []) or []
    if status == "PASS":
        metadata = _dict_payload(payload.get("metadata"))
        fingerprint = str(metadata.get("csv_dataset_fingerprint", "") or "")
        message = f"Promotion metadata passed; csv_dataset_fingerprint={fingerprint[:12] or 'missing'}."
    else:
        message = _first(blockers, "Promotion metadata is not admissible.")
    return FirstMillionReadinessGate(
        "promotion_metadata_check",
        "PASS" if status == "PASS" else "BLOCK",
        str(artifact),
        message,
        _first(
            next_actions,
            "Rerun guarded offline intake so the cache records CSV fingerprint, PASS source QA metadata, and provenance hashes.",
        ),
    )


def _research_cache_admissibility_gate(
    cfg,
    *,
    as_of: str | None,
    min_symbols: int,
    min_trading_days: int,
) -> FirstMillionReadinessGate:
    cache = Path(str(cfg.data.cache_path))
    if not cache.exists():
        return FirstMillionReadinessGate(
            "research_cache_admissibility",
            "BLOCK",
            str(cache),
            "Configured recent research cache does not exist.",
            "Import or ingest recent real A-share data before expecting research-only weekly evidence.",
        )
    storage = BarStorage(cache)
    provider = DataProvider(storage)
    gate = _evaluate_cache_gate(
        provider,
        str(cfg.research.start),
        str(cfg.research.end),
        as_of=as_of,
        min_symbols=min_symbols,
        min_trading_days=min_trading_days,
    )
    decision = gate["decision"]
    if bool(gate["demo_data_used"]):
        decision = "BLOCK"
    if decision == "PASS":
        message = (
            f"Research cache is admissible: latest_bar={gate['latest_bar_date'] or 'missing'}, "
            f"symbols={gate['symbol_count']}, trading_days={gate['trading_day_count']}, "
            f"bars={gate['bar_count']}."
        )
        next_action = (
            "Research-only weekly review may run on this cache, but promotion still requires offline intake "
            "and PASS source-QA provenance."
        )
    elif decision == "WATCH":
        message = (
            f"Research cache is marginal: latest_bar={gate['latest_bar_date'] or 'missing'}, "
            f"symbols={gate['symbol_count']}, trading_days={gate['trading_day_count']}, "
            f"bars={gate['bar_count']}; use for guarded research-only review only."
        )
        next_action = (
            "Refresh or broaden the recent real cache before treating this as a stable research baseline."
        )
    else:
        message = (
            f"Research cache is not admissible: latest_bar={gate['latest_bar_date'] or 'missing'}, "
            f"symbols={gate['symbol_count']}, trading_days={gate['trading_day_count']}, "
            f"bars={gate['bar_count']}, demo={gate['demo_data_used']}."
        )
        next_action = "Refresh/import recent real A-share data, then rerun first-million readiness."
    return FirstMillionReadinessGate(
        "research_cache_admissibility",
        decision,
        str(cache),
        message,
        next_action,
    )


def _data_gap_gate(root: Path) -> FirstMillionReadinessGate:
    path = root / "data_gap_action_plan.json"
    payload = _read_json(path)
    if not payload:
        return _missing_gate("data_gap_action_plan", path, "Run first-million pipeline or data gap action plan.")
    status = _normalize(payload.get("decision"))
    items = payload.get("items", []) or []
    first_bad = _first_named_item(items, {"BLOCK", "WATCH"})
    message = _item_message(first_bad) if first_bad else "Data gap action plan has no unresolved items."
    return FirstMillionReadinessGate(
        "data_gap_action_plan",
        status,
        str(path),
        message,
        _first(payload.get("next_actions", []), "Continue to source QA and offline intake."),
    )


def _data_evidence_packet_gate(root: Path) -> FirstMillionReadinessGate:
    path = root / "data_evidence_action_packet.json"
    payload = _read_json(path)
    if not payload:
        return _missing_gate(
            "data_evidence_action_packet",
            path,
            "Build data_evidence_action_packet.json from the current data gap plan.",
        )
    status = _normalize(payload.get("decision"))
    blockers = payload.get("current_blockers", []) or []
    watches = payload.get("watch_items", []) or []
    first_bad = _first_named_item(blockers, {"BLOCK"}) or _first_named_item(watches, {"WATCH"})
    if first_bad:
        name = str(first_bad.get("name", "data_evidence"))
        message = str(first_bad.get("message", "Data evidence packet requires action."))
        next_action = str(first_bad.get("next_action", "Follow data_evidence_action_packet.md."))
        gate_message = f"{name}: {message}"
    else:
        commands = len(payload.get("immediate_commands", []) or [])
        next_action = _first(
            payload.get("immediate_commands", []),
            "Continue through source QA and guarded offline intake.",
        )
        gate_message = f"Data evidence action packet is ready; immediate_commands={commands}."
    return FirstMillionReadinessGate(
        "data_evidence_action_packet",
        status,
        str(path),
        gate_message,
        next_action,
    )


def _operator_handoff_status_gate(root: Path) -> FirstMillionReadinessGate:
    path = root / "operator_handoff_status.json"
    payload = _read_json(path)
    if not payload:
        return _missing_gate(
            "operator_handoff_status",
            path,
            "Build operator_handoff_status.json from the current operator handoff queue.",
        )
    status = _normalize(payload.get("status"))
    open_count = int(payload.get("open_task_count", 0) or 0)
    p0_count = int(payload.get("p0_open_task_count", 0) or 0)
    source_count = int(payload.get("source_qa_open_task_count", 0) or 0)
    attachment_count = int(payload.get("source_qa_attachment_open_task_count", 0) or 0)
    export_count = int(payload.get("data_export_open_task_count", 0) or 0)
    if open_count:
        message = (
            f"Operator handoff open_tasks={open_count}, P0={p0_count}, "
            f"source_qa={source_count}, source_qa_attachment={attachment_count}, "
            f"data_export={export_count}."
        )
    else:
        message = "Operator handoff queue has no open tasks."
    return FirstMillionReadinessGate(
        "operator_handoff_status",
        status,
        str(path),
        message,
        _first(payload.get("next_actions", []), "Refresh operator handoff status."),
    )


def _csv_intake_preview_gate(root: Path) -> FirstMillionReadinessGate:
    path = root / "csv_intake_preview.json"
    payload = _read_json(path)
    if not payload:
        return _missing_gate(
            "csv_intake_preview",
            path,
            "Run CSV intake preview before guarded offline data intake.",
        )
    status = _normalize(payload.get("status"))
    items = payload.get("items", []) or []
    first_bad = _first_named_item(items, {"BLOCK", "WATCH"})
    if first_bad:
        message = f"{first_bad.get('file_name', 'csv')}: {first_bad.get('message', 'CSV preview requires review.')}"
    else:
        bars = next((item for item in items if isinstance(item, dict) and item.get("role") == "bars"), {})
        message = (
            "CSV preview mapped import columns; "
            f"bars_rows={bars.get('normalized_rows', 0)}, symbols={bars.get('symbol_count', 0)}."
        )
    return FirstMillionReadinessGate(
        "csv_intake_preview",
        status,
        str(path),
        message,
        _first(payload.get("next_actions", []), "Run CSV validation before guarded offline intake."),
    )


def _offline_package_gate(root: Path) -> FirstMillionReadinessGate:
    path = root / "offline_data_package.json"
    payload = _read_json(path)
    if not payload:
        return _missing_gate("offline_data_package", path, "Build offline data package report.")
    status = _normalize(payload.get("status"))
    items = payload.get("items", []) or []
    first_bad = _first_named_item(items, {"BLOCK", "WATCH"})
    provenance = format_source_provenance(_dict_payload(payload.get("source_metadata_summary")))
    if first_bad:
        message = _item_message(first_bad)
    elif provenance:
        message = f"Offline data package passed; {provenance}."
    else:
        message = "Offline data package has no unresolved items."
    return FirstMillionReadinessGate(
        "offline_data_package",
        status,
        str(path),
        message,
        _first(payload.get("next_actions", []), "Run guarded offline data intake."),
    )


def _real_data_handoff_gate(root: Path) -> FirstMillionReadinessGate:
    path = root / "real_data_handoff_checklist.json"
    payload = _read_json(path)
    if not payload:
        return _missing_gate("real_data_handoff_checklist", path, "Build real-data handoff checklist.")
    status = _normalize(payload.get("status"))
    evidence_paths = payload.get("evidence_paths", []) or []
    first_bad = _first_named_item(evidence_paths, {"BLOCK", "WATCH"})
    if first_bad:
        blocked_by = first_bad.get("blocked_by", []) or []
        if blocked_by:
            message = f"{first_bad.get('name')}: {blocked_by[0]}"
        else:
            message = f"{first_bad.get('name')}: {first_bad.get('next_action', 'requires review')}"
    else:
        message = "Real-data handoff checklist has no unresolved paths."
    return FirstMillionReadinessGate(
        "real_data_handoff_checklist",
        status,
        str(path),
        message,
        _first(payload.get("next_actions", []), "Run guarded offline data intake."),
    )


def _source_qa_gate(root: Path) -> FirstMillionReadinessGate:
    path = root / "source_qa" / "data_source_qa_review.json"
    payload = _read_json(path)
    if not payload:
        return _missing_gate("data_source_qa_review", path, "Run data source QA review.")
    status = _normalize(payload.get("status"))
    findings = payload.get("findings", []) or []
    first_bad = _first_finding(findings, {"BLOCK", "WATCH"})
    provenance = format_source_provenance(_dict_payload(payload.get("source_metadata")))
    if first_bad:
        message = _finding_message(first_bad)
    elif provenance:
        message = f"Data source QA review passed; {provenance}."
    else:
        message = "Data source QA review passed."
    return FirstMillionReadinessGate(
        "data_source_qa_review",
        status,
        str(path),
        message,
        _first(payload.get("next_actions", []), "Keep source evidence with the export batch."),
    )


def _source_qa_preflight_gate(root: Path) -> FirstMillionReadinessGate:
    path = root / "source_qa" / "source_qa_preflight.json"
    payload = _read_json(path)
    if not payload:
        return _missing_gate("source_qa_preflight", path, "Run source QA preflight.")
    status = _normalize(payload.get("status"))
    items = payload.get("items", []) or []
    first_bad = _first_named_item(items, {"BLOCK", "WATCH"})
    if first_bad:
        field = str(first_bad.get("field", "source_qa"))
        message = str(first_bad.get("message", "source QA preflight requires review."))
        gate_message = f"{field}: {message}"
    else:
        gate_message = "Source QA preflight has no unresolved source-stage gaps."
    return FirstMillionReadinessGate(
        "source_qa_preflight",
        status,
        str(path),
        gate_message,
        _first(payload.get("next_commands", []), "Run data source QA review."),
    )


def _offline_intake_gate(root: Path) -> FirstMillionReadinessGate:
    path = root / "offline_intake" / "offline_data_intake.json"
    payload = _read_json(path)
    if not payload:
        return _missing_gate("offline_data_intake", path, "Run guarded offline data intake.")
    status = _normalize(payload.get("status"))
    steps = payload.get("steps", []) or []
    first_bad = _first_named_item(steps, {"BLOCK", "WATCH"})
    message = _item_message(first_bad) if first_bad else "Guarded offline intake passed."
    return FirstMillionReadinessGate(
        "offline_data_intake",
        status,
        str(path),
        message,
        _first(payload.get("next_actions", []), "Continue to candidate experiment readiness."),
    )


def _candidate_readiness_gate(root: Path) -> FirstMillionReadinessGate:
    path = root / "candidate_experiment_readiness.json"
    payload = _read_json(path)
    if not payload:
        return _missing_gate("candidate_experiment_readiness", path, "Run candidate experiment readiness.")
    status = _normalize(payload.get("decision"))
    if status == "PASS":
        message = f"Runnable experiments={payload.get('runnable_count', 0)}."
    else:
        message = _first(payload.get("blockers", []), "Candidate experiments are not ready.")
    return FirstMillionReadinessGate(
        "candidate_experiment_readiness",
        status,
        str(path),
        message,
        _first(payload.get("next_actions", []), "Run candidate experiment launch."),
    )


def _market_context_readiness_gate(root: Path) -> FirstMillionReadinessGate:
    path = root / "market_context_readiness.json"
    payload = _read_json(path)
    if not payload:
        return _missing_gate(
            "market_context_readiness",
            path,
            "Run market context readiness before candidate experiment readiness.",
        )
    status = _normalize(payload.get("decision"))
    if status == "PASS":
        message = (
            f"Market context source={payload.get('source', 'unknown')}, "
            f"label={payload.get('label', 'unknown')}."
        )
    elif status == "WATCH":
        message = _first(payload.get("watch_items", []), "Market context requires WATCH review.")
    else:
        message = _first(payload.get("blockers", []), "Market context readiness is BLOCK.")
    return FirstMillionReadinessGate(
        "market_context_readiness",
        status,
        str(path),
        message,
        _first(payload.get("next_actions", []), "Generate market_regime.json from audited A-share data."),
    )


def _candidate_launch_gate(root: Path) -> FirstMillionReadinessGate:
    path = root / "candidate_experiment_launch.json"
    payload = _read_json(path)
    if not payload:
        return _missing_gate("candidate_experiment_launch", path, "Run candidate experiment launch.")
    status = _normalize(payload.get("decision"))
    if status == "PASS":
        message = (
            f"Selected candidate={payload.get('selected_candidate', 'none') or 'none'}, "
            f"run_id={payload.get('run_id', 'none') or 'none'}."
        )
    else:
        message = _first(payload.get("blocked_by", []), "Candidate experiment launch is BLOCK.")
    return FirstMillionReadinessGate(
        "candidate_experiment_launch",
        status,
        str(path),
        message,
        _first(payload.get("next_actions", []), "Run launch commands only if decision is PASS."),
    )


def _candidate_execution_gate(root: Path) -> FirstMillionReadinessGate:
    path = root / "candidate_experiment_execution.json"
    payload = _read_json(path)
    if not payload:
        return _missing_gate("candidate_experiment_execution", path, "Run candidate experiment execution.")
    decision = str(payload.get("decision", "")).upper()
    status: ReadinessStatus
    if decision == "PASS":
        status = "PASS"
    elif decision == "DRY_RUN":
        status = "WATCH"
    elif decision == "BLOCK":
        status = "BLOCK"
    else:
        status = "UNKNOWN"
    blockers = payload.get("blockers", []) or []
    if blockers:
        message = str(blockers[0])
    else:
        steps = payload.get("steps", []) or []
        message = f"Execution decision={decision or 'UNKNOWN'}, steps={len(steps)}."
    return FirstMillionReadinessGate(
        "candidate_experiment_execution",
        status,
        str(path),
        message,
        _first(payload.get("next_actions", []), "Run candidate experiment completion after execution."),
    )


def _candidate_completion_gate(root: Path) -> FirstMillionReadinessGate:
    path = root / "candidate_experiment_completion.json"
    payload = _read_json(path)
    if not payload:
        return _missing_gate("candidate_experiment_completion", path, "Run candidate experiment completion.")
    status = _normalize(payload.get("decision"))
    if status == "PASS":
        message = (
            f"Completed candidate={payload.get('selected_candidate', 'none') or 'none'}, "
            f"run_id={payload.get('run_id', 'none') or 'none'}."
        )
    elif status == "WATCH":
        message = _first(payload.get("watch_items", []), "Candidate experiment completion has WATCH items.")
    else:
        message = _first(payload.get("blockers", []), "Candidate experiment completion is BLOCK.")
    return FirstMillionReadinessGate(
        "candidate_experiment_completion",
        status,
        str(path),
        message,
        _first(payload.get("next_actions", []), "Complete required experiment outputs."),
    )


def _capital_goal_gate(root: Path) -> FirstMillionReadinessGate:
    path = root / "goal" / "capital_goal_status.json"
    payload = _read_json(path)
    if not payload:
        return _missing_gate("capital_goal_status", path, "Run capital goal status after experiment gates.")
    status = _normalize(payload.get("decision"))
    if status == "PASS":
        message = "Capital goal evidence matrix is PASS."
    elif status == "WATCH":
        message = _first(payload.get("next_actions", []), "Capital goal evidence has WATCH items.")
    else:
        message = _first(payload.get("blockers", []), "Capital goal evidence is BLOCK.")
    return FirstMillionReadinessGate(
        "capital_goal_status",
        status,
        str(path),
        message,
        _first(payload.get("next_actions", []), "Continue weekly evidence accumulation."),
    )


def _run_manifest_gate(root: Path) -> FirstMillionReadinessGate:
    path = _first_existing([root / "run_manifest.json", root / "weekly" / "run_manifest.json"])
    if path is None:
        return _missing_gate(
            "run_manifest",
            root / "run_manifest.json",
            "Rerun first-million pipeline or weekly pipeline to generate run_manifest.json.",
        )
    payload = _read_json(path)
    if not payload:
        return FirstMillionReadinessGate(
            "run_manifest",
            "BLOCK",
            str(path),
            "run_manifest.json could not be read as a valid evidence manifest.",
            "Rerun the pipeline and keep the generated run_manifest.json with the report.",
        )
    blocker = _run_manifest_blocker(payload)
    if blocker:
        return FirstMillionReadinessGate(
            "run_manifest",
            "BLOCK",
            str(path),
            blocker,
            "Rerun guarded offline intake and the pipeline so run_manifest.json records real-data provenance and sample split.",
        )
    data_version = _dict_payload(payload.get("data_version"))
    fingerprint = str(data_version.get("csv_dataset_fingerprint", "") or "")
    message = (
        f"Run manifest passed; latest_bar={payload.get('latest_bar_date', '') or 'missing'}, "
        f"symbols={payload.get('symbol_count', 0)}, "
        f"trading_days={payload.get('trading_day_count', 0)}, "
        f"csv_dataset_fingerprint={fingerprint[:12] or 'missing'}."
    )
    return FirstMillionReadinessGate(
        "run_manifest",
        "PASS",
        str(path),
        message,
        "Keep run_manifest.json with every research, paper, and readiness artifact.",
    )


def _micro_live_readiness_gate(root: Path) -> FirstMillionReadinessGate:
    path = _first_existing(
        [root / "micro_live_readiness.json", root / "weekly" / "micro_live_readiness.json"]
    )
    if path is None:
        return FirstMillionReadinessGate(
            "micro_live_readiness",
            "PASS",
            "not_applicable",
            "Micro-live readiness has not been prepared; this optional downstream gate is not evaluated.",
            "Prepare micro-live readiness only after research, paper, source QA, and approval evidence are complete.",
        )
    payload = _read_json(path)
    status = _normalize(payload.get("decision"))
    findings = payload.get("findings", []) or []
    first_bad = _first_finding(findings, {"BLOCK", "WATCH"})
    if first_bad:
        message = _finding_message(first_bad)
    else:
        message = f"Micro-live readiness decision={status}, findings={len(findings)}."
    return FirstMillionReadinessGate(
        "micro_live_readiness",
        status,
        str(path),
        message,
        "Resolve micro-live readiness findings; this workflow remains manual-reference-only.",
    )


def _capital_scaling_plan_gate(root: Path) -> FirstMillionReadinessGate:
    path = _first_existing(
        [root / "capital_scaling_plan.json", root / "weekly" / "capital_scaling_plan.json"]
    )
    if path is None:
        return FirstMillionReadinessGate(
            "capital_scaling_plan",
            "PASS",
            "not_applicable",
            "Capital scaling plan has not been generated; this optional downstream gate is not evaluated.",
            "Generate a capital scaling plan only after micro-live readiness and fresh human approval are complete.",
        )
    payload = _read_json(path)
    status = _normalize(payload.get("decision"))
    blockers = payload.get("blockers", []) or []
    if status == "PASS":
        message = (
            f"Capital scaling passed; current={payload.get('current_capital', 0)}, "
            f"proposed={payload.get('proposed_capital', 0)}, "
            f"max_allowed={payload.get('max_allowed_capital', 0)}."
        )
    else:
        message = _first(blockers, "Capital scaling plan is not PASS.")
    return FirstMillionReadinessGate(
        "capital_scaling_plan",
        status,
        str(path),
        message,
        "Resolve capital scaling blockers before any manual capital increase.",
    )


def _compounding_path_gate(root: Path) -> FirstMillionReadinessGate:
    path = root / "goal" / "compounding_path_review.json"
    payload = _read_json(path)
    if not payload:
        return _missing_gate("compounding_path_review", path, "Run compounding path review.")
    status = _normalize(payload.get("decision"))
    if status == "PASS":
        message = "Compounding path review is PASS for deeper manual review."
    elif status == "WATCH":
        message = _first_finding_message(payload, "WATCH")
    else:
        message = _first_finding_message(payload, "BLOCK")
    return FirstMillionReadinessGate(
        "compounding_path_review",
        status,
        str(path),
        message,
        _first(payload.get("next_actions", []), "Resolve compounding path blockers."),
    )


def _missing_gate(name: str, path: Path, next_action: str) -> FirstMillionReadinessGate:
    return FirstMillionReadinessGate(
        name,
        "MISSING",
        str(path),
        f"{path.name} is missing.",
        next_action,
    )


def _decision(gates: list[FirstMillionReadinessGate]) -> ReadinessDecision:
    statuses = [gate.status for gate in gates]
    if any(status in {"BLOCK", "MISSING", "UNKNOWN"} for status in statuses):
        return "BLOCK"
    if any(status == "WATCH" for status in statuses):
        return "WATCH"
    return "PASS"


def _latest_import_failure_message(latest_import: dict[str, Any]) -> str:
    message = str(
        latest_import.get("message")
        or "AKShare import was blocked by network/proxy access."
    )
    evidence = []
    failure_stage = str(latest_import.get("failure_stage") or "").strip()
    if failure_stage:
        evidence.append(f"failure_stage={failure_stage}")
    recommended_route = str(latest_import.get("recommended_route") or "").strip()
    if recommended_route:
        evidence.append(f"recommended_route={recommended_route}")
    path = str(latest_import.get("path") or "").strip()
    if path:
        evidence.append(f"report={path}")
    if not evidence:
        return message
    return f"{message} ({', '.join(evidence)})"


def _next_actions(gates: list[FirstMillionReadinessGate]) -> list[str]:
    actions = []
    for gate in gates:
        if gate.status in {"BLOCK", "MISSING", "UNKNOWN"}:
            actions.append(gate.next_action)
            break
    if not actions:
        for gate in gates:
            if gate.status == "WATCH":
                actions.append(gate.next_action)
                break
    if not actions:
        actions.append("Evidence gates are ready; continue only through deterministic review and human approval.")
    return actions


def _first_named_item(items: list[Any], statuses: set[str]) -> dict[str, Any]:
    for item in items:
        if isinstance(item, dict) and str(item.get("status", "")).upper() in statuses:
            return item
    return {}


def _first_finding(findings: list[Any], severities: set[str]) -> dict[str, Any]:
    for item in findings:
        if isinstance(item, dict) and str(item.get("severity", "")).upper() in severities:
            return item
    return {}


def _item_message(item: dict[str, Any]) -> str:
    if not item:
        return ""
    name = str(item.get("name", "item"))
    message = str(item.get("message", "status requires review."))
    return f"{name}: {message}"


def _finding_message(item: dict[str, Any]) -> str:
    if not item:
        return ""
    code = str(item.get("code", "FINDING"))
    message = str(item.get("message", "finding requires review."))
    return f"{code}: {message}"


def _first_finding_message(payload: dict[str, Any], severity: str) -> str:
    findings = payload.get("findings", []) or []
    first = next(
        (
            item
            for item in findings
            if isinstance(item, dict) and str(item.get("severity", "")).upper() == severity
        ),
        {},
    )
    return _finding_message(first) if first else "Compounding path review requires attention."


def _run_manifest_blocker(payload: dict[str, Any]) -> str:
    if payload.get("demo_data_used") is True:
        return "run_manifest.json says demo data was used."
    if not str(payload.get("in_sample_end", "") or "").strip():
        return "run_manifest.json must record in_sample_end."
    if not str(payload.get("out_sample_start", "") or "").strip():
        return "run_manifest.json must record out_sample_start."
    data_version = payload.get("data_version", {})
    if not isinstance(data_version, dict):
        return "run_manifest.json data_version must be an object with source QA provenance."
    metadata = dict(data_version)
    metadata["data_source_qa_require_evidence_manifest"] = "true"
    blockers = cache_metadata_blockers(metadata)
    return f"run_manifest provenance blocker: {blockers[0]}" if blockers else ""


def _dict_payload(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_existing(paths: list[Path]) -> Path | None:
    return next((path for path in paths if path.exists()), None)


def _first(values: object, default: str) -> str:
    if isinstance(values, list) and values:
        return str(values[0])
    return default


def _first_step_command(steps: object, default: str) -> str:
    if isinstance(steps, list) and steps:
        first = steps[0]
        if isinstance(first, dict):
            return str(first.get("command") or first.get("purpose") or default)
    return default


def _normalize(value: object) -> ReadinessStatus:
    text = str(value or "").upper()
    if text in {"PASS", "WATCH", "BLOCK"}:
        return text  # type: ignore[return-value]
    return "UNKNOWN"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
