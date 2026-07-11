"""Factor-component diagnostics for strategy candidates."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal

from quantify.data.provider import DataProvider
from quantify.research.candidate_walk_forward import (
    CandidateWalkForwardSummary,
    run_candidate_walk_forward,
)
from quantify.research.candidates import CandidateSpec, default_candidate_specs

FactorDiagnosticStatus = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class CandidateFactorDiagnostic:
    candidate: str
    status: FactorDiagnosticStatus
    component_count: int
    total_component_count: int
    component_limit: int | None
    component_pass_count: int
    best_component: str
    best_component_return: float
    composite_return: float
    dependency_ratio: float
    components: list[dict[str, Any]]
    findings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "status": self.status,
            "component_count": self.component_count,
            "total_component_count": self.total_component_count,
            "component_limit": self.component_limit,
            "component_pass_count": self.component_pass_count,
            "best_component": self.best_component,
            "best_component_return": self.best_component_return,
            "composite_return": self.composite_return,
            "dependency_ratio": self.dependency_ratio,
            "components": self.components,
            "findings": self.findings,
        }


@dataclass(frozen=True, slots=True)
class CandidateFactorDiagnosticsReport:
    status: FactorDiagnosticStatus
    candidate_count: int
    diagnostics: list[CandidateFactorDiagnostic]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "candidate_count": self.candidate_count,
            "warnings": self.warnings,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Candidate Factor Diagnostics: {self.status}",
            "",
            "| candidate | status | components | pass | best_component | dependency | composite_return |",
            "| --- | --- | ---: | ---: | --- | ---: | ---: |",
        ]
        for diagnostic in self.diagnostics:
            component_label = str(diagnostic.component_count)
            if diagnostic.component_count != diagnostic.total_component_count:
                component_label = f"{diagnostic.component_count}/{diagnostic.total_component_count}"
            lines.append(
                "| {candidate} | `{status}` | {count} | {passes} | `{best}` | {dependency:.2f} | {ret:.2%} |".format(
                    candidate=diagnostic.candidate,
                    status=diagnostic.status,
                    count=component_label,
                    passes=diagnostic.component_pass_count,
                    best=diagnostic.best_component or "none",
                    dependency=diagnostic.dependency_ratio,
                    ret=diagnostic.composite_return,
                )
            )
        lines.extend(["", "## Findings"])
        for diagnostic in self.diagnostics:
            lines.append(f"- `{diagnostic.candidate}`")
            lines.extend(f"  - {finding}" for finding in diagnostic.findings)
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in self.warnings) if self.warnings else lines.append("- None.")
        lines.append("")
        lines.append(
            "This report checks factor-component robustness; it is not a promise of profit or a live trading instruction."
        )
        return "\n".join(lines) + "\n"


def run_candidate_factor_diagnostics(
    data: DataProvider,
    cfg,
    *,
    train_days: int = 120,
    test_days: int = 60,
    step_days: int = 60,
    max_windows: int | None = None,
    specs: list[CandidateSpec] | None = None,
    candidate: str | None = None,
    min_component_pass_ratio: float = 0.40,
    max_dependency_ratio: float = 1.50,
    max_components: int | None = None,
    market_regime_by_window: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> CandidateFactorDiagnosticsReport:
    if max_components is not None and max_components < 1:
        raise ValueError("max_components must be >= 1 when provided.")
    candidates = _select_specs(specs or default_candidate_specs(cfg), candidate)
    diagnostics = [
        _diagnose_candidate(
            data,
            cfg,
            spec,
            train_days=train_days,
            test_days=test_days,
            step_days=step_days,
            max_windows=max_windows,
            min_component_pass_ratio=min_component_pass_ratio,
            max_dependency_ratio=max_dependency_ratio,
            max_components=max_components,
            market_regime_by_window=market_regime_by_window,
        )
        for spec in candidates
    ]
    warnings = []
    if not diagnostics:
        warnings.append("No candidate factor diagnostics could be computed.")
    if all(diagnostic.status == "BLOCK" for diagnostic in diagnostics):
        warnings.append("All candidates have blocked factor-component diagnostics.")
    limited = [
        diagnostic
        for diagnostic in diagnostics
        if diagnostic.component_count < diagnostic.total_component_count
    ]
    if limited:
        warnings.append(
            "Component diagnostics were limited for "
            + ", ".join(diagnostic.candidate for diagnostic in limited)
            + "; treat the report as research triage, not full evidence."
        )
    return CandidateFactorDiagnosticsReport(
        status=_overall_status(diagnostics, warnings),
        candidate_count=len(diagnostics),
        diagnostics=diagnostics,
        warnings=warnings,
    )


def write_candidate_factor_diagnostics_report(
    report: CandidateFactorDiagnosticsReport,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "candidate_factor_diagnostics.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "candidate_factor_diagnostics.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _select_specs(specs: list[CandidateSpec], candidate: str | None) -> list[CandidateSpec]:
    if not candidate:
        return specs
    selected = [spec for spec in specs if spec.name == candidate]
    if not selected:
        available = ", ".join(spec.name for spec in specs)
        raise ValueError(f"Unknown candidate {candidate!r}; available candidates: {available}")
    return selected


def _diagnose_candidate(
    data: DataProvider,
    cfg,
    spec: CandidateSpec,
    *,
    train_days: int,
    test_days: int,
    step_days: int,
    max_windows: int | None,
    min_component_pass_ratio: float,
    max_dependency_ratio: float,
    max_components: int | None,
    market_regime_by_window: dict[tuple[str, str], dict[str, Any]] | None,
) -> CandidateFactorDiagnostic:
    composite = run_candidate_walk_forward(
        data,
        cfg,
        train_days=train_days,
        test_days=test_days,
        step_days=step_days,
        max_windows=max_windows,
        specs=[spec],
        market_regime_by_window=market_regime_by_window,
    )
    composite_summary = composite.summaries[0] if composite.summaries else None
    factor_items = list(enumerate(spec.factors))
    selected_factor_items = factor_items[:max_components] if max_components is not None else factor_items
    components = [
        _component_summary(
            data,
            cfg,
            spec,
            factor_idx=idx,
            train_days=train_days,
            test_days=test_days,
            step_days=step_days,
            max_windows=max_windows,
            market_regime_by_window=market_regime_by_window,
        )
        for idx, _factor in selected_factor_items
    ]
    components = [component for component in components if component]
    composite_return = composite_summary.avg_total_return if composite_summary else 0.0
    best = max(components, key=lambda row: float(row["avg_total_return"]), default={})
    best_return = float(best.get("avg_total_return", 0.0) or 0.0)
    dependency_ratio = best_return / composite_return if composite_return > 0 else 0.0
    pass_count = sum(1 for component in components if component["status"] == "PASS")
    pass_ratio = pass_count / len(components) if components else 0.0
    findings = _findings(
        composite_summary,
        components,
        pass_ratio=pass_ratio,
        dependency_ratio=dependency_ratio,
        min_component_pass_ratio=min_component_pass_ratio,
        max_dependency_ratio=max_dependency_ratio,
        component_count=len(components),
        total_component_count=len(factor_items),
    )
    return CandidateFactorDiagnostic(
        candidate=spec.name,
        status=_candidate_status(findings),
        component_count=len(components),
        total_component_count=len(factor_items),
        component_limit=max_components,
        component_pass_count=pass_count,
        best_component=str(best.get("factor", "")),
        best_component_return=best_return,
        composite_return=composite_return,
        dependency_ratio=dependency_ratio,
        components=components,
        findings=findings,
    )


def _component_summary(
    data: DataProvider,
    cfg,
    spec: CandidateSpec,
    *,
    factor_idx: int,
    train_days: int,
    test_days: int,
    step_days: int,
    max_windows: int | None,
    market_regime_by_window: dict[tuple[str, str], dict[str, Any]] | None,
) -> dict[str, Any]:
    factor = spec.factors[factor_idx]
    component_spec = CandidateSpec(
        name=f"{spec.name}__{factor.name}",
        description=f"Single-factor component: {factor.name}",
        factors=[factor],
        n_holdings=spec.n_holdings,
        max_weight=spec.max_weight,
        rebalance=spec.rebalance,
        trend_filter=spec.trend_filter,
        trend_scale=spec.trend_scale,
        trend_gate=spec.trend_gate,
        hold_rank_buffer=spec.hold_rank_buffer,
        min_trade_weight=spec.min_trade_weight,
        max_new_positions=spec.max_new_positions,
        score_smoothing_observations=spec.score_smoothing_observations,
        score_smoothing_step_days=spec.score_smoothing_step_days,
    )
    report = run_candidate_walk_forward(
        data,
        cfg,
        train_days=train_days,
        test_days=test_days,
        step_days=step_days,
        max_windows=max_windows,
        specs=[component_spec],
        market_regime_by_window=market_regime_by_window,
    )
    summary = report.summaries[0] if report.summaries else None
    return _summary_dict(factor.name, summary)


def _summary_dict(factor_name: str, summary: CandidateWalkForwardSummary | None) -> dict[str, Any]:
    if summary is None:
        return {
            "factor": factor_name,
            "status": "BLOCK",
            "window_count": 0,
            "pass_count": 0,
            "avg_total_return": 0.0,
            "avg_max_drawdown": 0.0,
            "avg_sharpe_ratio": 0.0,
        }
    return {
        "factor": factor_name,
        "status": summary.status,
        "window_count": summary.window_count,
        "pass_count": summary.pass_count,
        "avg_total_return": summary.avg_total_return,
        "avg_max_drawdown": summary.avg_max_drawdown,
        "avg_sharpe_ratio": summary.avg_sharpe_ratio,
    }


def _findings(
    composite: CandidateWalkForwardSummary | None,
    components: list[dict[str, Any]],
    *,
    pass_ratio: float,
    dependency_ratio: float,
    min_component_pass_ratio: float,
    max_dependency_ratio: float,
    component_count: int,
    total_component_count: int,
) -> list[str]:
    findings = []
    if composite is None or composite.status == "BLOCK":
        findings.append("BLOCK: composite candidate walk-forward is missing or BLOCK.")
    if not components:
        findings.append("BLOCK: no factor components could be diagnosed.")
    if component_count < total_component_count:
        findings.append(
            f"WATCH: diagnostics limited to {component_count} of {total_component_count} factor components."
        )
    if pass_ratio < min_component_pass_ratio:
        findings.append(
            f"WATCH: component PASS ratio {pass_ratio:.0%} is below {min_component_pass_ratio:.0%}."
        )
    if dependency_ratio > max_dependency_ratio:
        findings.append(
            f"WATCH: best single factor return is {dependency_ratio:.2f}x composite return; check single-factor dependency."
        )
    if not findings:
        findings.append("PASS: component diagnostics do not show obvious single-factor dependency.")
    return findings


def _candidate_status(findings: list[str]) -> FactorDiagnosticStatus:
    if any(finding.startswith("BLOCK") for finding in findings):
        return "BLOCK"
    if any(finding.startswith("WATCH") for finding in findings):
        return "WATCH"
    return "PASS"


def _overall_status(
    diagnostics: list[CandidateFactorDiagnostic],
    warnings: list[str],
) -> FactorDiagnosticStatus:
    if any(diagnostic.status == "PASS" for diagnostic in diagnostics) and not warnings:
        return "PASS"
    if any(diagnostic.status in {"PASS", "WATCH"} for diagnostic in diagnostics):
        return "WATCH"
    return "BLOCK"
