"""Roll up recent candidate research into a single research-only focus report."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import csv
import json
from pathlib import Path
from typing import Any

from quantify.research.candidate_next_experiments import (
    build_candidate_next_experiments_report,
    load_candidate_report_bundle,
)

REPORT_STATUS = "RESEARCH_ONLY"
DEFAULT_ALLOWED_ACTIONS = [
    "Use the top-ranked candidate as the next research-only experiment focus.",
    "Refresh this rollup after each new recent candidate research run before changing candidate priority.",
    "Compare this rollup with candidate_next_experiments.json before adding factor complexity or paper-scope claims.",
]
DEFAULT_PROHIBITED_ACTIONS = [
    "Do not treat the best research candidate as paper approval, micro-live readiness, or a buy/sell signal.",
    "Do not let this rollup change deterministic gates, human approval requirements, or broker boundaries.",
    "Do not connect any command or output here to real broker order submission.",
]
SOURCE_FILES = (
    "candidate_selection.json",
    "candidate_research_precheck.json",
    "candidate_walk_forward_report.json",
    "candidate_factor_diagnostics.json",
    "candidate_regime_validation_report.json",
    "candidate_stress_matrix.json",
)


@dataclass(frozen=True, slots=True)
class RecentResearchCandidate:
    rank: int
    candidate: str
    report_dir: str
    selection_decision: str
    capital_goal_fit_status: str
    walk_forward_status: str
    factor_status: str
    regime_status: str
    stress_status: str
    annualized_return: float | None
    return_margin: float | None
    max_drawdown: float | None
    sharpe_ratio: float | None
    avg_turnover_pct: float | None
    reject_rate: float | None
    positive_return_ratio: float | None
    next_command: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "candidate": self.candidate,
            "report_dir": self.report_dir,
            "selection_decision": self.selection_decision,
            "capital_goal_fit_status": self.capital_goal_fit_status,
            "walk_forward_status": self.walk_forward_status,
            "factor_status": self.factor_status,
            "regime_status": self.regime_status,
            "stress_status": self.stress_status,
            "annualized_return": self.annualized_return,
            "return_margin": self.return_margin,
            "max_drawdown": self.max_drawdown,
            "sharpe_ratio": self.sharpe_ratio,
            "avg_turnover_pct": self.avg_turnover_pct,
            "reject_rate": self.reject_rate,
            "positive_return_ratio": self.positive_return_ratio,
            "next_command": self.next_command,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class RecentCandidateResearchReport:
    as_of: str
    search_dir: str
    status: str
    report_count: int
    candidate_count: int
    best_research_candidate: str
    best_research_reason: str
    best_research_command: str
    candidate_summaries: list[RecentResearchCandidate]
    missing_evidence: list[str]
    next_actions: list[str]
    allowed_actions: list[str]
    prohibited_actions: list[str]
    can_enter_paper: bool = False
    can_enter_micro_live_ready: bool = False
    can_generate_broker_orders: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": "recent_candidate_research",
            "as_of": self.as_of,
            "search_dir": self.search_dir,
            "status": self.status,
            "report_count": self.report_count,
            "candidate_count": self.candidate_count,
            "best_research_candidate": self.best_research_candidate,
            "best_research_reason": self.best_research_reason,
            "best_research_command": self.best_research_command,
            "candidate_summaries": [item.to_dict() for item in self.candidate_summaries],
            "missing_evidence": self.missing_evidence,
            "next_actions": self.next_actions,
            "allowed_actions": self.allowed_actions,
            "prohibited_actions": self.prohibited_actions,
            "can_enter_paper": self.can_enter_paper,
            "can_enter_micro_live_ready": self.can_enter_micro_live_ready,
            "can_generate_broker_orders": self.can_generate_broker_orders,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Recent Candidate Research: {self.status}",
            "",
            f"- As of: `{self.as_of}`",
            f"- Search directory: `{self.search_dir}`",
            f"- Report count: {self.report_count}",
            f"- Candidate count: {self.candidate_count}",
            f"- Best research candidate: `{self.best_research_candidate or 'none'}`",
            f"- Best research reason: {self.best_research_reason or 'No current research candidate is available.'}",
            "",
            "This rollup is research-only. It cannot approve paper trading, micro-live readiness, or real broker execution.",
            "",
            "## Candidate Rankings",
            "",
            "| rank | candidate | selection | goal fit | walk-forward | factor | regime | stress | ann. return | max DD | sharpe | turnover | reject | report dir |",
            "| ---: | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
        if self.candidate_summaries:
            for item in self.candidate_summaries:
                lines.append(
                    "| {rank} | `{candidate}` | `{selection}` | `{goal}` | `{wf}` | `{factor}` | `{regime}` | `{stress}` | `{ret}` | `{dd}` | `{sharpe}` | `{turnover}` | `{reject}` | `{report_dir}` |".format(
                        rank=item.rank,
                        candidate=item.candidate,
                        selection=item.selection_decision,
                        goal=item.capital_goal_fit_status,
                        wf=item.walk_forward_status,
                        factor=item.factor_status,
                        regime=item.regime_status,
                        stress=item.stress_status,
                        ret=_fmt_pct(item.annualized_return),
                        dd=_fmt_pct(item.max_drawdown),
                        sharpe=_fmt_float(item.sharpe_ratio),
                        turnover=_fmt_pct(item.avg_turnover_pct),
                        reject=_fmt_pct(item.reject_rate),
                        report_dir=_cell(item.report_dir),
                    )
                )
                lines.append(f"  - Reason: {item.reason}")
                lines.append(f"  - Next command: `{item.next_command}`")
        else:
            lines.append("| 0 | `none` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | `n/a` | `n/a` | `n/a` | `n/a` | `n/a` | `n/a` |")

        lines.extend(["", "## Missing Evidence"])
        lines.extend(f"- {item}" for item in self.missing_evidence) if self.missing_evidence else lines.append("- None.")
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Allowed Actions"])
        lines.extend(f"- {item}" for item in self.allowed_actions)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"

    def to_csv_rows(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.candidate_summaries]


@dataclass(slots=True)
class _CandidateSnapshot:
    candidate: str
    report_dirs: list[str] = field(default_factory=list)
    selection_result: dict[str, Any] = field(default_factory=dict)
    walk_forward: dict[str, Any] = field(default_factory=dict)
    factor_diagnostic: dict[str, Any] = field(default_factory=dict)
    regime_summary: dict[str, Any] = field(default_factory=dict)
    stress_summary: dict[str, Any] = field(default_factory=dict)


def build_recent_candidate_research_report(
    search_dir: str | Path = "results/research_recent",
    *,
    as_of: str | None = None,
    max_report_dirs: int = 24,
) -> RecentCandidateResearchReport:
    root = Path(search_dir)
    report_dirs = discover_recent_candidate_report_dirs(root, max_report_dirs=max_report_dirs)
    bundles = [load_candidate_report_bundle(path) for path in report_dirs]
    next_experiments = build_candidate_next_experiments_report(bundles)
    summaries = _candidate_summaries(bundles, next_experiments)
    best = summaries[0] if summaries else None
    return RecentCandidateResearchReport(
        as_of=as_of or date.today().isoformat(),
        search_dir=str(root),
        status=REPORT_STATUS,
        report_count=len(report_dirs),
        candidate_count=len(summaries),
        best_research_candidate=best.candidate if best else "",
        best_research_reason=best.reason if best else "No recent candidate research evidence is available.",
        best_research_command=best.next_command if best else "",
        candidate_summaries=summaries,
        missing_evidence=next_experiments.missing_evidence[:12],
        next_actions=_next_actions(best, next_experiments.missing_evidence),
        allowed_actions=list(DEFAULT_ALLOWED_ACTIONS),
        prohibited_actions=list(DEFAULT_PROHIBITED_ACTIONS),
    )


def write_recent_candidate_research_report(
    report: RecentCandidateResearchReport,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "recent_candidate_research.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "recent_candidate_research.md").write_text(report.to_markdown(), encoding="utf-8")
    _write_csv(root / "recent_candidate_research.csv", report.to_csv_rows())
    return root


def discover_recent_candidate_report_dirs(
    search_dir: str | Path,
    *,
    max_report_dirs: int = 24,
) -> list[Path]:
    root = Path(search_dir)
    if not root.exists():
        return []
    dirs = [
        path
        for path in root.iterdir()
        if path.is_dir() and any((path / filename).exists() for filename in SOURCE_FILES)
    ]
    ordered = sorted(dirs, key=lambda path: path.stat().st_mtime)
    if max_report_dirs > 0:
        return ordered[-max_report_dirs:]
    return ordered


def resolve_recent_candidate_research_dir(
    report_dir: str | Path,
    override: str | Path | None = None,
) -> Path:
    root = Path(report_dir)
    if override is not None:
        return Path(override)
    candidates = [
        root / "research_recent_real_candidates",
        root.parent / "research_recent_real_candidates",
        root / "research_recent_real_cache",
        root.parent / "research_recent_real_cache",
        root / "research_recent",
        root.parent / "research_recent",
    ]
    ranked: list[tuple[int, float, Path]] = []
    for candidate in candidates:
        report_dirs = discover_recent_candidate_report_dirs(candidate, max_report_dirs=1)
        if not report_dirs:
            continue
        latest_mtime = max(path.stat().st_mtime for path in report_dirs)
        ranked.append((_recent_research_dir_priority(candidate), -latest_mtime, candidate))
    if ranked:
        ranked.sort(key=lambda item: (item[0], item[1], str(item[2])))
        return ranked[0][2]
    return root.parent / "research_recent"


def _candidate_summaries(
    bundles: list[Any],
    next_experiments: Any,
) -> list[RecentResearchCandidate]:
    snapshots = _candidate_snapshots(bundles)
    command_map = _candidate_command_map(next_experiments)
    scored_rows = []
    for candidate, snapshot in snapshots.items():
        selection = snapshot.selection_result
        walk_forward = snapshot.walk_forward
        factor = snapshot.factor_diagnostic
        regime = snapshot.regime_summary
        stress = snapshot.stress_summary
        selection_decision = _selection_decision(selection)
        capital_goal_fit_status = _dict_status(selection.get("capital_goal_fit_review"))
        row = {
            "candidate": candidate,
            "report_dir": snapshot.report_dirs[-1] if snapshot.report_dirs else "",
            "selection_decision": selection_decision,
            "capital_goal_fit_status": capital_goal_fit_status,
            "walk_forward_status": _dict_status(walk_forward),
            "factor_status": _dict_status(factor, missing="MISSING"),
            "regime_status": _dict_status(regime, missing="MISSING"),
            "stress_status": _dict_status(stress, missing="MISSING"),
            "annualized_return": _metric(selection, "annualized_return"),
            "return_margin": _capital_goal_metric(selection, "return_margin"),
            "max_drawdown": _metric(selection, "max_drawdown"),
            "sharpe_ratio": _metric(selection, "sharpe_ratio"),
            "avg_turnover_pct": _metric(selection, "avg_turnover_pct"),
            "reject_rate": _metric(selection, "reject_rate"),
            "positive_return_ratio": _optional_float(walk_forward.get("positive_return_ratio")),
            "next_command": command_map.get(candidate, _default_command(candidate)),
        }
        row["reason"] = _candidate_reason(row)
        scored_rows.append(row)

    ranked = sorted(scored_rows, key=_candidate_sort_key)
    summaries = []
    for index, row in enumerate(ranked, start=1):
        summaries.append(
            RecentResearchCandidate(
                rank=index,
                candidate=str(row["candidate"]),
                report_dir=str(row["report_dir"]),
                selection_decision=str(row["selection_decision"]),
                capital_goal_fit_status=str(row["capital_goal_fit_status"]),
                walk_forward_status=str(row["walk_forward_status"]),
                factor_status=str(row["factor_status"]),
                regime_status=str(row["regime_status"]),
                stress_status=str(row["stress_status"]),
                annualized_return=_optional_float(row["annualized_return"]),
                return_margin=_optional_float(row["return_margin"]),
                max_drawdown=_optional_float(row["max_drawdown"]),
                sharpe_ratio=_optional_float(row["sharpe_ratio"]),
                avg_turnover_pct=_optional_float(row["avg_turnover_pct"]),
                reject_rate=_optional_float(row["reject_rate"]),
                positive_return_ratio=_optional_float(row["positive_return_ratio"]),
                next_command=str(row["next_command"]),
                reason=str(row["reason"]),
            )
        )
    return summaries


def _candidate_snapshots(bundles: list[Any]) -> dict[str, _CandidateSnapshot]:
    snapshots: dict[str, _CandidateSnapshot] = {}
    for bundle in bundles:
        precheck = bundle.candidate_research_precheck if hasattr(bundle, "candidate_research_precheck") else {}
        for candidate in precheck.get("candidates", []) or []:
            _snapshot(snapshots, str(candidate), bundle.report_dir)

        selection = bundle.candidate_selection if hasattr(bundle, "candidate_selection") else {}
        for result in selection.get("results", []) or []:
            if not isinstance(result, dict):
                continue
            candidate = str(result.get("name") or "")
            if not candidate:
                continue
            snapshot = _snapshot(snapshots, candidate, bundle.report_dir)
            snapshot.selection_result = result

        walk_forward = bundle.candidate_walk_forward if hasattr(bundle, "candidate_walk_forward") else {}
        for summary in walk_forward.get("summaries", []) or []:
            if not isinstance(summary, dict):
                continue
            candidate = str(summary.get("candidate") or "")
            if not candidate:
                continue
            snapshot = _snapshot(snapshots, candidate, bundle.report_dir)
            snapshot.walk_forward = summary

        factor = bundle.factor_diagnostics if hasattr(bundle, "factor_diagnostics") else {}
        for diagnostic in factor.get("diagnostics", []) or []:
            if not isinstance(diagnostic, dict):
                continue
            candidate = str(diagnostic.get("candidate") or "")
            if not candidate:
                continue
            snapshot = _snapshot(snapshots, candidate, bundle.report_dir)
            snapshot.factor_diagnostic = diagnostic

        regime = bundle.regime_validation if hasattr(bundle, "regime_validation") else {}
        for summary in regime.get("summaries", []) or []:
            if not isinstance(summary, dict):
                continue
            candidate = str(summary.get("candidate") or "")
            if not candidate:
                continue
            snapshot = _snapshot(snapshots, candidate, bundle.report_dir)
            snapshot.regime_summary = summary

        stress = bundle.stress_matrix if hasattr(bundle, "stress_matrix") else {}
        for summary in stress.get("summaries", []) or []:
            if not isinstance(summary, dict):
                continue
            candidate = str(summary.get("candidate") or "")
            if not candidate:
                continue
            snapshot = _snapshot(snapshots, candidate, bundle.report_dir)
            snapshot.stress_summary = summary
    return snapshots


def _snapshot(
    snapshots: dict[str, _CandidateSnapshot],
    candidate: str,
    report_dir: str,
) -> _CandidateSnapshot:
    if candidate not in snapshots:
        snapshots[candidate] = _CandidateSnapshot(candidate=candidate)
    snapshot = snapshots[candidate]
    if report_dir and report_dir not in snapshot.report_dirs:
        snapshot.report_dirs.append(report_dir)
    return snapshot


def _candidate_command_map(next_experiments: Any) -> dict[str, str]:
    ranked: dict[str, tuple[int, str]] = {}
    commands: dict[str, str] = {}
    for experiment in next_experiments.experiments:
        candidate = str(experiment.candidate or "")
        if not candidate or candidate == "ALL":
            continue
        rank = _command_priority(str(experiment.category or ""))
        current = ranked.get(candidate)
        if current is None or rank < current[0]:
            ranked[candidate] = (rank, str(experiment.command_hint or ""))
    for candidate, (_, command) in ranked.items():
        commands[candidate] = command
    return commands


def _command_priority(category: str) -> int:
    order = {
        "liquidity_neutral_guard_lineage_review": 0,
        "low_concentration_vs_baseline": 0,
        "quarterly_trend_vs_baseline": 0,
        "trend_filter_ablation": 1,
        "stress_matrix_failure": 1,
        "walk_forward_failure_analysis": 2,
        "positive_window_ratio": 2,
        "factor_dependency": 3,
        "regime_failure": 3,
        "turnover_control": 4,
        "drawdown_budget": 4,
        "weak_risk_adjusted_return": 4,
        "capital_goal_fit": 4,
        "adverse_window_review": 5,
        "execution_rejects": 5,
        "blocked_candidate_review": 9,
        "missing_factor_diagnostics": 9,
        "missing_regime_validation": 9,
    }
    return order.get(category, 6)


def _candidate_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _severity(row["selection_decision"]),
        _severity(row["capital_goal_fit_status"]),
        0 if row["annualized_return"] is not None else 1,
        -_sortable_number(row["annualized_return"], default=-9.0),
        0 if row["return_margin"] is not None else 1,
        -_sortable_number(row["return_margin"], default=-9.0),
        0 if row["max_drawdown"] is not None else 1,
        _sortable_number(row["max_drawdown"], default=9.0),
        0 if row["sharpe_ratio"] is not None else 1,
        -_sortable_number(row["sharpe_ratio"], default=-99.0),
        0 if row["avg_turnover_pct"] is not None else 1,
        _sortable_number(row["avg_turnover_pct"], default=9.0),
        0 if row["reject_rate"] is not None else 1,
        _sortable_number(row["reject_rate"], default=9.0),
        _severity(row["walk_forward_status"]),
        _severity(row["factor_status"]),
        _severity(row["regime_status"]),
        _severity(row["stress_status"]),
        str(row["candidate"]),
    )


def _candidate_reason(row: dict[str, Any]) -> str:
    parts = [
        f"selection={row['selection_decision']}/{row['capital_goal_fit_status']}",
        f"annualized_return={_fmt_pct(_optional_float(row['annualized_return']))}",
        f"return_margin={_fmt_pct(_optional_float(row['return_margin']))}",
        f"max_drawdown={_fmt_pct(_optional_float(row['max_drawdown']))}",
        f"sharpe={_fmt_float(_optional_float(row['sharpe_ratio']))}",
        f"turnover={_fmt_pct(_optional_float(row['avg_turnover_pct']))}",
        f"reject_rate={_fmt_pct(_optional_float(row['reject_rate']))}",
    ]
    open_statuses = [
        f"walk_forward={row['walk_forward_status']}",
        f"factor={row['factor_status']}",
        f"regime={row['regime_status']}",
        f"stress={row['stress_status']}",
    ]
    comparison = _candidate_focus_reason(str(row["candidate"]))
    return "; ".join(parts + [comparison, "open issues: " + ", ".join(open_statuses)]) + "."


def _next_actions(best: RecentResearchCandidate | None, missing_evidence: list[str]) -> list[str]:
    actions: list[str] = []
    if best:
        actions.append(
            f"Keep `{best.candidate}` as the current research-only focus and rerun `{best.next_command}`."
        )
        actions.extend(_candidate_specific_next_actions(best.candidate))
    else:
        actions.append("Generate recent candidate research evidence before ranking the next A-share daily candidate.")
    actions.append("Reject any compounding or deployment claim until return margin is positive after costs and paper evidence exists.")
    if missing_evidence:
        actions.append(f"Resolve the leading evidence gap first: {missing_evidence[0]}")
    actions.append("Refresh this rollup after each new recent candidate research run.")
    return actions


def _recent_research_dir_priority(path: Path) -> int:
    value = str(path).lower().replace("/", "\\")
    if "research_recent_real_candidates" in value:
        return 0
    if "research_recent_real_cache" in value:
        return 1
    if "research_recent" in value:
        return 2
    return 3


def _selection_decision(selection: dict[str, Any]) -> str:
    score = selection.get("score") if isinstance(selection.get("score"), dict) else {}
    return str(score.get("decision") or selection.get("decision") or "UNKNOWN").upper()


def _dict_status(payload: Any, *, missing: str = "UNKNOWN") -> str:
    if not isinstance(payload, dict) or not payload:
        return missing
    return str(payload.get("status") or payload.get("decision") or missing).upper()


def _capital_goal_metric(selection: dict[str, Any], key: str) -> float | None:
    review = selection.get("capital_goal_fit_review")
    if not isinstance(review, dict):
        return None
    return _optional_float(review.get(key))


def _metric(selection: dict[str, Any], key: str) -> float | None:
    if key in selection:
        return _optional_float(selection.get(key))
    metrics = selection.get("metrics")
    if isinstance(metrics, dict):
        return _optional_float(metrics.get(key))
    return None


def _severity(value: object) -> int:
    status = str(value or "").strip().upper()
    mapping = {
        "PASS": 0,
        "READY": 0,
        "WATCH": 1,
        "RESEARCH_ONLY": 1,
        "OPEN": 1,
        "BLOCK": 2,
        "BLOCKED": 2,
        "MISSING": 3,
        "UNKNOWN": 4,
        "SKIPPED": 4,
    }
    return mapping.get(status, 5)


def _default_command(candidate: str) -> str:
    return (
        "python examples/run_candidate_research_precheck.py --config config/research_recent.yaml "
        f"--output-dir results/research_recent/<timestamp> --candidate {candidate}"
    )


def _candidate_focus_reason(candidate: str) -> str:
    mapping = {
        "low_turnover_low_concentration_price_volume": (
            "focus=prove lower concentration is better than the baseline low-turnover variant"
        ),
        "trend_filtered_quarterly_price_volume": (
            "focus=prove quarterly cadence is better than the monthly trend-filtered baseline"
        ),
        "liquidity_neutral_momentum_guard_price_volume": (
            "focus=close the slow-signal to liquidity-neutral guarded lineage before adding factors"
        ),
    }
    return mapping.get(candidate, "focus=keep the candidate in research-only comparison mode")


def _candidate_specific_next_actions(candidate: str) -> list[str]:
    mapping = {
        "low_turnover_low_concentration_price_volume": [
            "Run a direct baseline comparison against `low_turnover_price_volume` before tuning any other parameter.",
            "Keep the lower-concentration variant only if drawdown or Sharpe improves without a worse return margin.",
        ],
        "trend_filtered_quarterly_price_volume": [
            "Run a direct cadence comparison against `trend_filtered_price_volume` before changing filter strength.",
            "Keep the quarterly trend-filtered variant only if the better path is not mostly cash drag avoidance by luck.",
        ],
        "liquidity_neutral_momentum_guard_price_volume": [
            "Run the three-candidate lineage review against `stable_universe_slow_signal_price_volume` and `long_momentum_liquidity_monthly_price_volume` before adding any new factor.",
            "Attribute whether drawdown, turnover, or return decay came from liquidity neutralization, the defensive guard, or the slow-signal base.",
        ],
    }
    return mapping.get(candidate, [])


def _sortable_number(value: object, *, default: float) -> float:
    parsed = _optional_float(value)
    return parsed if parsed is not None else default


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2%}"


def _fmt_float(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


def _cell(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "rank",
        "candidate",
        "report_dir",
        "selection_decision",
        "capital_goal_fit_status",
        "walk_forward_status",
        "factor_status",
        "regime_status",
        "stress_status",
        "annualized_return",
        "return_margin",
        "max_drawdown",
        "sharpe_ratio",
        "avg_turnover_pct",
        "reject_rate",
        "positive_return_ratio",
        "next_command",
        "reason",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
