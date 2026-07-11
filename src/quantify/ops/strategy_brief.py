"""First-million strategy brief assembled from current evidence."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal

from quantify.research.candidate_experiment_readiness import CandidateExperimentReadiness
from quantify.research.candidate_hypotheses import CandidateHypothesisCatalog

BriefDecision = Literal["RUN_RESEARCH", "PREPARE_DATA", "PAPER_ONLY", "PAUSE"]


@dataclass(frozen=True, slots=True)
class StrategyBriefCandidate:
    priority: int
    candidate: str
    status: str
    evidence_scope: str
    data_dependency: str
    reason: str
    next_command: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "priority": self.priority,
            "candidate": self.candidate,
            "status": self.status,
            "evidence_scope": self.evidence_scope,
            "data_dependency": self.data_dependency,
            "reason": self.reason,
            "next_command": self.next_command,
        }


@dataclass(frozen=True, slots=True)
class FirstMillionStrategyBrief:
    decision: BriefDecision
    as_of: str | None
    market_context_status: str
    market_context_label: str
    market_context_source: str
    readiness_decision: str
    data_gap_decision: str
    data_evidence_decision: str
    data_evidence_next_action: str
    offline_package_status: str
    top_research_candidate: str
    compounding_goal: dict[str, Any]
    candidate_actions: list[StrategyBriefCandidate]
    missing_evidence: list[str]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "as_of": self.as_of,
            "market_context_status": self.market_context_status,
            "market_context_label": self.market_context_label,
            "market_context_source": self.market_context_source,
            "readiness_decision": self.readiness_decision,
            "data_gap_decision": self.data_gap_decision,
            "data_evidence_decision": self.data_evidence_decision,
            "data_evidence_next_action": self.data_evidence_next_action,
            "offline_package_status": self.offline_package_status,
            "top_research_candidate": self.top_research_candidate,
            "compounding_goal": self.compounding_goal,
            "candidate_actions": [item.to_dict() for item in self.candidate_actions],
            "missing_evidence": self.missing_evidence,
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# First Million Strategy Brief: {self.decision}",
            "",
            f"- As of: `{self.as_of or 'unspecified'}`",
            f"- Market context: `{self.market_context_label}` "
            f"(`{self.market_context_status}`, source `{self.market_context_source}`)",
            f"- Experiment readiness: `{self.readiness_decision}`",
            f"- Data gap plan: `{self.data_gap_decision}`",
            f"- Data evidence packet: `{self.data_evidence_decision}`",
            f"- Offline package: `{self.offline_package_status}`",
            f"- Top research candidate: `{self.top_research_candidate or 'none'}`",
            f"- Compounding goal: `{self.compounding_goal.get('status', 'MISSING')}`",
            "",
            "This brief is a research work order. It is not a profit claim, strategy approval, or broker instruction.",
            "",
            "## Compounding Goal Gap",
            "",
            f"- Selected candidate: `{self.compounding_goal.get('selected_candidate', 'none') or 'none'}`",
            f"- Candidate selection: `{self.compounding_goal.get('candidate_selection_status', 'MISSING')}`",
            f"- Capital goal status: `{self.compounding_goal.get('capital_goal_status', 'MISSING')}`",
            f"- Compounding path: `{self.compounding_goal.get('compounding_path_decision', 'MISSING')}`",
            f"- Required annual return: {_pct(self.compounding_goal.get('required_annual_return', 0.0))}",
            f"- Projected capital: {_money(self.compounding_goal.get('projected_capital_at_horizon', 0.0))}",
            f"- Capital shortfall: {_money(self.compounding_goal.get('capital_shortfall', 0.0))}",
            "",
            "### Goal Gap Items",
            *_goal_gap_lines(self.compounding_goal),
            "",
            "## Candidate Actions",
            "",
            "| priority | candidate | status | scope | reason | next command |",
            "| ---: | --- | --- | --- | --- | --- |",
        ]
        if self.candidate_actions:
            for item in self.candidate_actions:
                command = item.next_command or "none"
                lines.append(
                    f"| {item.priority} | `{item.candidate}` | `{item.status}` | "
                    f"`{item.evidence_scope}` | {_cell(item.reason)} | `{command}` |"
                )
        else:
            lines.append("| 0 | `none` | `BLOCKED` | `n/a` | No candidate actions are available. | `none` |")
        lines.extend(["", "## Missing Evidence"])
        lines.extend(f"- {item}" for item in self.missing_evidence) if self.missing_evidence else lines.append("- None.")
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_first_million_strategy_brief(
    *,
    readiness: CandidateExperimentReadiness,
    hypothesis_catalog: CandidateHypothesisCatalog,
    data_gap_plan: dict[str, Any],
    offline_package: dict[str, Any],
    data_evidence_packet: dict[str, Any] | None = None,
    market_regime: dict[str, Any] | None = None,
    market_context_snapshot: dict[str, Any] | None = None,
    capital_goal_status: dict[str, Any] | None = None,
    compounding_path_review: dict[str, Any] | None = None,
    candidate_selection: dict[str, Any] | None = None,
    as_of: str | None = None,
) -> FirstMillionStrategyBrief:
    candidate_actions = _candidate_actions(readiness)
    market_context = _market_context(market_regime, market_context_snapshot)
    data_evidence = _data_evidence_context(data_evidence_packet)
    compounding_goal = _compounding_goal_summary(
        capital_goal_status=capital_goal_status,
        compounding_path_review=compounding_path_review,
        candidate_selection=candidate_selection,
    )
    missing_evidence = _missing_evidence(data_gap_plan, offline_package, readiness)
    missing_evidence.extend(_data_evidence_missing_evidence(data_evidence_packet))
    missing_evidence.extend(_market_context_missing_evidence(market_context))
    missing_evidence.extend(_compounding_missing_evidence(compounding_goal))
    missing_evidence = _dedupe(missing_evidence)
    top = next((item.candidate for item in candidate_actions if item.status == "READY"), "")
    decision = _decision(
        readiness_decision=readiness.decision,
        data_gap_decision=str(data_gap_plan.get("decision", data_gap_plan.get("status", "UNKNOWN"))),
        data_evidence_decision=str(data_evidence.get("decision", "MISSING")),
        offline_package_status=str(offline_package.get("status", "UNKNOWN")),
        market_status=str(market_context.get("status", "UNKNOWN")),
        has_ready_candidate=bool(top),
    )
    return FirstMillionStrategyBrief(
        decision=decision,
        as_of=as_of,
        market_context_status=str(market_context.get("status", "MISSING") or "MISSING"),
        market_context_label=str(market_context.get("label", "unknown") or "unknown"),
        market_context_source=str(market_context.get("source", "missing") or "missing"),
        readiness_decision=readiness.decision,
        data_gap_decision=str(data_gap_plan.get("decision", data_gap_plan.get("status", "UNKNOWN"))),
        data_evidence_decision=str(data_evidence.get("decision", "MISSING")),
        data_evidence_next_action=str(data_evidence.get("next_action", "")),
        offline_package_status=str(offline_package.get("status", "UNKNOWN")),
        top_research_candidate=top or _first_catalog_candidate(hypothesis_catalog),
        compounding_goal=compounding_goal,
        candidate_actions=candidate_actions,
        missing_evidence=missing_evidence,
        next_actions=_next_actions(
            decision,
            readiness,
            missing_evidence,
            candidate_actions,
            str(data_evidence.get("next_action", "")),
            market_context,
            compounding_goal,
        ),
        prohibited_actions=[
            "Do not treat this brief as a guarantee of stable profits or one-million success.",
            "Do not run candidate experiments while their readiness item is BLOCKED.",
            "Do not promote a strategy from template, demo, stale, or unaudited data.",
            "Do not connect any output from this brief to real broker order submission.",
            "Do not let LLM narrative upgrade deterministic gates or human approval requirements.",
            "Do not treat market_context_snapshot as a substitute for cache-derived market_regime.json.",
        ],
    )


def write_first_million_strategy_brief(
    brief: FirstMillionStrategyBrief,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "first_million_strategy_brief.json").write_text(
        json.dumps(brief.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "first_million_strategy_brief.md").write_text(brief.to_markdown(), encoding="utf-8")
    return root


def _candidate_actions(readiness: CandidateExperimentReadiness) -> list[StrategyBriefCandidate]:
    actions: list[StrategyBriefCandidate] = []
    ranked = sorted(
        readiness.items,
        key=lambda value: (
            _candidate_rank_bucket(value),
            value.priority,
            value.candidate,
        ),
    )
    for item in ranked:
        actions.append(
            StrategyBriefCandidate(
                priority=item.priority,
                candidate=item.candidate,
                status=item.status,
                evidence_scope=item.evidence_scope,
                data_dependency=item.data_dependency,
                reason=_candidate_reason(item),
                next_command=_candidate_next_command(item),
            )
        )
    return actions


def _candidate_rank_bucket(item) -> tuple[int, int, int]:
    ready_rank = 0 if item.status == "READY" else 1
    fit_rank = _fit_priority(item.market_regime_fit_status, item.market_regime_fit)
    source_rank = 0 if item.market_context_source == "market_regime" else 1
    return ready_rank, fit_rank, source_rank


def _fit_priority(status: str, fit: str) -> int:
    normalized_status = str(status or "").upper()
    normalized_fit = str(fit or "").strip().lower()
    if normalized_status == "PASS" and normalized_fit in {"intended_regime", "neutral_research_baseline"}:
        return 0
    if normalized_status == "PASS":
        return 1
    if normalized_fit == "defensive_fit":
        return 2
    if normalized_fit == "intended_regime":
        return 3
    if normalized_fit == "neutral_research_baseline":
        return 4
    if normalized_fit == "opportunistic_only":
        return 5
    if normalized_fit in {"defensive_mismatch", "out_of_intended_regime", "insufficient_context"}:
        return 6
    if normalized_fit == "risk_off_pause" or normalized_status == "BLOCK":
        return 7
    if normalized_status == "NOT_REVIEWED":
        return 8
    return 9


def _candidate_reason(item) -> str:
    market_clause = (
        f"Market context={item.market_context_source}:{item.market_context_label}:{item.market_context_status}; "
        f"market_regime_fit={item.market_regime_fit_status}/{item.market_regime_fit}."
    )
    if item.status == "READY":
        return " ".join(
            [
                "Candidate is READY under the current deterministic readiness review.",
                market_clause,
                str(item.market_regime_fit_note or "").strip(),
            ]
        ).strip()
    blocked = "; ".join(item.blocked_by[:3]) or "Candidate is blocked by unresolved evidence."
    return " ".join(
        [
            blocked,
            market_clause,
            str(item.market_regime_fit_note or "").strip(),
        ]
    ).strip()


def _candidate_next_command(item) -> str:
    if item.status != "READY":
        return item.next_command
    fit = str(item.market_regime_fit or "").strip().lower()
    source = str(item.market_context_source or "").strip().lower()
    if fit == "risk_off_pause":
        return "none"
    if fit == "opportunistic_only" and source == "market_context_snapshot":
        return "Refresh cache-derived market_regime.json before launching this risk-on-only research path."
    if fit in {"defensive_fit", "defensive_mismatch"}:
        return item.next_command or "Focus on defensive and drawdown-stress candidate research first."
    if fit == "neutral_research_baseline":
        return item.next_command or "Run the diversified neutral-regime candidate research path first."
    return item.next_command


def _missing_evidence(
    data_gap_plan: dict[str, Any],
    offline_package: dict[str, Any],
    readiness: CandidateExperimentReadiness,
) -> list[str]:
    values: list[str] = []
    for item in data_gap_plan.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("status", "")).upper() == "BLOCK":
            values.append(f"data_gap.{item.get('name')}: {item.get('message')}")
    for item in offline_package.get("items", []) or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("status", "")).upper() == "BLOCK":
            values.append(f"offline_package.{item.get('name')}: {item.get('message')}")
    values.extend(readiness.blockers)
    return _dedupe(values)


def _market_context(
    market_regime: dict[str, Any] | None,
    market_context_snapshot: dict[str, Any] | None,
) -> dict[str, str]:
    if market_regime:
        return {
            "status": str(market_regime.get("status", "MISSING") or "MISSING"),
            "label": str(market_regime.get("label", "unknown") or "unknown"),
            "source": str(market_regime.get("context_source", "market_regime") or "market_regime"),
        }
    if market_context_snapshot:
        snapshot_status = str(market_context_snapshot.get("status", "UNKNOWN") or "UNKNOWN").upper()
        return {
            "status": "BLOCK" if snapshot_status == "BLOCK" else "WATCH",
            "label": str(market_context_snapshot.get("label", "unknown") or "unknown"),
            "source": "market_context_snapshot",
        }
    return {"status": "MISSING", "label": "unknown", "source": "missing"}


def _data_evidence_context(data_evidence_packet: dict[str, Any] | None) -> dict[str, str]:
    if not data_evidence_packet:
        return {
            "decision": "MISSING",
            "next_action": "Build data_evidence_action_packet.json from the current data gap plan.",
        }
    blockers = data_evidence_packet.get("current_blockers", []) or []
    watches = data_evidence_packet.get("watch_items", []) or []
    for items in (blockers, watches):
        for item in items:
            if isinstance(item, dict):
                action = str(item.get("next_action", "") or "").strip()
                if action:
                    return {
                        "decision": str(data_evidence_packet.get("decision", "UNKNOWN")),
                        "next_action": action,
                    }
    commands = data_evidence_packet.get("immediate_commands", []) or []
    return {
        "decision": str(data_evidence_packet.get("decision", "UNKNOWN")),
        "next_action": _first(commands, "Continue through source QA and guarded offline intake."),
    }


def _data_evidence_missing_evidence(data_evidence_packet: dict[str, Any] | None) -> list[str]:
    if not data_evidence_packet:
        return ["data_evidence_action_packet.json: missing current real-data work order."]
    values: list[str] = []
    for key in ("current_blockers", "watch_items"):
        for item in data_evidence_packet.get(key, []) or []:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", "")).upper()
            if status in {"BLOCK", "WATCH"}:
                values.append(f"data_evidence.{item.get('name')}: {item.get('message')}")
    return values


def _compounding_goal_summary(
    *,
    capital_goal_status: dict[str, Any] | None,
    compounding_path_review: dict[str, Any] | None,
    candidate_selection: dict[str, Any] | None,
) -> dict[str, Any]:
    capital = capital_goal_status or {}
    compounding = compounding_path_review or {}
    selection = candidate_selection or {}
    selected = str(
        compounding.get("selected_candidate")
        or selection.get("selected_candidate")
        or capital.get("best_candidate")
        or selection.get("best_candidate")
        or ""
    )
    top = str(selection.get("top_candidate") or selection.get("best_candidate") or "")
    goal = _dict_value(compounding.get("goal")) or _dict_value(capital.get("goal"))
    required_return = _float(goal.get("required_annual_return"))
    projected = _float(compounding.get("projected_capital_at_horizon"))
    shortfall = _float(compounding.get("capital_shortfall"))
    capital_status = str(capital.get("decision", "MISSING") or "MISSING").upper()
    compounding_status = str(compounding.get("decision", "MISSING") or "MISSING").upper()
    selection_status = str(selection.get("status", "MISSING") or "MISSING").upper()
    status = _goal_summary_status(capital_status, compounding_status, selection_status)
    gap_items = _goal_gap_items(
        capital_goal_status=capital,
        compounding_path_review=compounding,
        candidate_selection=selection,
        status=status,
    )
    return {
        "status": status,
        "selected_candidate": selected,
        "top_candidate": top,
        "candidate_selection_status": selection_status,
        "capital_goal_status": capital_status,
        "compounding_path_decision": compounding_status,
        "required_annual_return": required_return,
        "projected_capital_at_horizon": projected,
        "capital_shortfall": shortfall,
        "gap_items": gap_items,
        "can_claim_compounding_path": status == "PASS" and not gap_items,
    }


def _goal_summary_status(
    capital_status: str,
    compounding_status: str,
    selection_status: str,
) -> str:
    statuses = [capital_status, compounding_status, selection_status]
    if any(status in {"BLOCK", "MISSING", "UNKNOWN", ""} for status in statuses):
        return "BLOCK"
    if any(status == "WATCH" for status in statuses):
        return "WATCH"
    return "PASS"


def _goal_gap_items(
    *,
    capital_goal_status: dict[str, Any],
    compounding_path_review: dict[str, Any],
    candidate_selection: dict[str, Any],
    status: str,
) -> list[str]:
    items: list[str] = []
    if not candidate_selection:
        items.append("candidate_selection.json is missing; no strategy can be tied to the one-million path.")
    elif not str(candidate_selection.get("selected_candidate") or ""):
        items.append("candidate_selection.json has no selected_candidate; top_candidate is not enough for compounding evidence.")
    if not capital_goal_status:
        items.append("goal/capital_goal_status.json is missing; capital-goal gates have not been audited.")
    if not compounding_path_review:
        items.append("goal/compounding_path_review.json is missing; projected capital and shortfall are unaudited.")
    for blocker in capital_goal_status.get("blockers", []) or []:
        items.append(f"capital_goal_status blocker: {blocker}")
    for finding in compounding_path_review.get("findings", []) or []:
        if not isinstance(finding, dict):
            continue
        severity = str(finding.get("severity", "") or "").upper()
        code = str(finding.get("code", "") or "")
        message = str(finding.get("message", "") or "")
        if severity in {"BLOCK", "WATCH"}:
            items.append(f"compounding_path {severity} {code}: {message}")
    if status == "PASS" and not items:
        items.append("No deterministic goal-gap items remain, but manual review is still required before capital deployment.")
    return _dedupe(items)


def _compounding_missing_evidence(compounding_goal: dict[str, Any]) -> list[str]:
    if str(compounding_goal.get("status", "")).upper() == "PASS":
        return []
    return [f"compounding_goal: {item}" for item in compounding_goal.get("gap_items", []) or []]


def _market_context_missing_evidence(market_context: dict[str, str]) -> list[str]:
    source = market_context.get("source", "missing")
    if source == "market_context_snapshot":
        return [
            "market_regime.json: only market_context_snapshot is available; "
            "cache-derived market regime evidence is still missing."
        ]
    if source == "missing":
        return ["market_regime.json: cache-derived market context is missing."]
    return []


def _decision(
    *,
    readiness_decision: str,
    data_gap_decision: str,
    data_evidence_decision: str,
    offline_package_status: str,
    market_status: str,
    has_ready_candidate: bool,
) -> BriefDecision:
    if (
        data_gap_decision.upper() == "BLOCK"
        or data_evidence_decision.upper() in {"BLOCK", "MISSING"}
        or offline_package_status.upper() == "BLOCK"
    ):
        return "PREPARE_DATA"
    if readiness_decision.upper() == "BLOCK":
        return "PAUSE"
    if market_status.upper() in {"WATCH", "BLOCK", "MISSING", "UNKNOWN"}:
        return "PAPER_ONLY" if has_ready_candidate else "PAUSE"
    return "RUN_RESEARCH" if has_ready_candidate else "PAUSE"


def _next_actions(
    decision: BriefDecision,
    readiness: CandidateExperimentReadiness,
    missing_evidence: list[str],
    candidate_actions: list[StrategyBriefCandidate],
    data_evidence_next_action: str,
    market_context: dict[str, str],
    compounding_goal: dict[str, Any],
) -> list[str]:
    if decision == "PREPARE_DATA":
        actions = [
            "Fill the source QA evidence worksheet and data_source_qa_answers.json with real vendor/export evidence.",
            "Replace template CSV rows with recent real A-share daily exports, then rerun data gap and offline package checks.",
            "Rerun first-million pipeline before launching any strategy experiment.",
        ]
        if data_evidence_next_action:
            actions.insert(0, f"Follow data_evidence_action_packet.md first: {data_evidence_next_action}")
        return _dedupe([*actions, *_compounding_next_actions(compounding_goal)])
    if decision == "RUN_RESEARCH":
        first_ready = next((item for item in candidate_actions if item.status == "READY"), None)
        actions = [
            f"Run the first READY candidate experiment: {first_ready.candidate}."
            if first_ready
            else "No READY candidate is available; rerun readiness after evidence is complete.",
            "Keep all outputs under the fixed experiment directory and run completion review before paper planning.",
        ]
        actions.extend(_market_next_actions(market_context, candidate_actions))
        actions.extend(_compounding_next_actions(compounding_goal))
        return _dedupe(actions)
    if decision == "PAPER_ONLY":
        actions = [
            "Use READY candidates only for offline research or paper observation; do not increase capital.",
            "Refresh market_regime.json from the same audited cache and require completion review before paper planning.",
        ]
        actions.extend(_market_next_actions(market_context, candidate_actions))
        actions.extend(_compounding_next_actions(compounding_goal))
        return _dedupe(actions)
    market_actions = _market_next_actions(market_context, candidate_actions)
    compounding_actions = _compounding_next_actions(compounding_goal)
    if market_actions:
        return _dedupe([*(readiness.next_actions or missing_evidence), *market_actions, *compounding_actions])
    return _dedupe(
        [
            *(readiness.next_actions or missing_evidence or ["Resolve deterministic blockers before continuing."]),
            *compounding_actions,
        ]
    )


def _compounding_next_actions(compounding_goal: dict[str, Any]) -> list[str]:
    status = str(compounding_goal.get("status", "MISSING") or "MISSING").upper()
    if status == "PASS":
        return ["Keep the compounding path under manual review; PASS is not a profit guarantee."]
    selected = str(compounding_goal.get("selected_candidate") or "none")
    return [
        f"Resolve compounding goal gaps before treating `{selected}` as a capital-scaling candidate.",
    ]


def _market_next_actions(
    market_context: dict[str, str],
    candidate_actions: list[StrategyBriefCandidate],
) -> list[str]:
    source = str(market_context.get("source", "missing") or "missing")
    label = str(market_context.get("label", "unknown") or "unknown").strip().lower()
    top_ready = next((item for item in candidate_actions if item.status == "READY"), None)
    if label == "risk_off":
        return [
            "Keep the workflow research-only and prefer defensive low-vol / cash-guard ideas before any capital discussion.",
        ]
    if label == "defensive":
        target = top_ready.candidate if top_ready else "defensive_low_vol"
        return [
            f"Prioritize {target} and other defensive candidates; verify drawdown and cash-drag behavior first.",
        ]
    if label == "risk_on":
        target = top_ready.candidate if top_ready else "momentum_quality"
        return [
            f"Use {target} as the next comparison candidate, but keep paper evidence and cost stress ahead of capital scaling.",
        ]
    if label == "neutral":
        target = top_ready.candidate if top_ready else "core_multifactor"
        return [
            f"Compare {target} against the diversified baseline under cost stress and walk-forward evidence.",
        ]
    if source == "market_context_snapshot":
        return [
            "Refresh cache-derived market_regime.json before treating the snapshot as anything beyond advisory context.",
        ]
    return []


def _first_catalog_candidate(catalog: CandidateHypothesisCatalog) -> str:
    if not catalog.candidates:
        return ""
    return catalog.candidates[0].name


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _first(values: object, default: str) -> str:
    if isinstance(values, list) and values:
        return str(values[0])
    return default


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _goal_gap_lines(compounding_goal: dict[str, Any]) -> list[str]:
    items = compounding_goal.get("gap_items", [])
    if not isinstance(items, list) or not items:
        return ["- None."]
    return [f"- {item}" for item in items]


def _dict_value(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _pct(value: object) -> str:
    return f"{_float(value):.2%}"


def _money(value: object) -> str:
    return f"{_float(value):.2f}"
