"""One-command weekly workflow for research-to-paper evidence generation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from quantify.audit import audit_data, write_data_audit
from quantify.core.portfolio import Portfolio
from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.engine.paper_broker import PaperBroker, PaperBrokerConfig
from quantify.goal import CapitalGoal, build_capital_goal_status, write_capital_goal_status
from quantify.llm import LLMReviewPromptBuilder, review_report
from quantify.market import detect_market_regime, write_market_regime_report
from quantify.ops.bootstrap import build_real_data_bootstrap_report, write_real_data_bootstrap_report
from quantify.ops.data_coverage import analyze_data_coverage, write_data_coverage_report
from quantify.ops.promotion import write_strategy_promotion_review
from quantify.ops.recent_candidate_research import (
    build_recent_candidate_research_report,
    write_recent_candidate_research_report,
)
from quantify.ops.registry import update_candidate_registry
from quantify.ops.real_data_gate import evaluate_real_data_gate, write_real_data_gate
from quantify.ops.run_manifest import build_run_manifest, write_run_manifest
from quantify.ops.weekly import WeeklyReview, build_weekly_review, write_weekly_review
from quantify.paper import (
    build_paper_candidate_plan,
    evaluate_paper_stability,
    missing_paper_stability_report,
    write_paper_candidate_plan,
    write_paper_daily_review,
    write_paper_stability_report,
)
from quantify.readiness import (
    build_manual_target_plan,
    write_manual_target_plan,
    write_readiness_outputs,
)
from quantify.research.candidate_walk_forward import (
    run_candidate_walk_forward,
    write_candidate_walk_forward_report,
)
from quantify.research.candidate_factor_diagnostics import (
    run_candidate_factor_diagnostics,
    write_candidate_factor_diagnostics_report,
)
from quantify.research.candidates import run_candidate_selection, write_candidate_selection_report
from quantify.research.demo_data import seed_demo_data
from quantify.research.engine import ResearchEngine
from quantify.research.factors import FactorPipeline
from quantify.research.regime_validation import (
    run_candidate_regime_validation,
    write_candidate_regime_validation_report,
)
from quantify.research.report import research_evidence_digest, write_research_report
from quantify.research.robustness import run_robustness, write_robustness_report
from quantify.research.strategy import MultiFactorStrategyConfig, MultiFactorTargetStrategy
from quantify.research.universe import UniverseConfig, UniverseFilter
from quantify.research.walk_forward import run_walk_forward, write_walk_forward_report

PipelineReviewStage = Literal["research", "paper", "micro_live_ready"]


@dataclass(frozen=True, slots=True)
class WeeklyPipelineResult:
    output_dir: str
    demo_data_used: bool
    stages: list[dict[str, str]]
    weekly_decision: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": self.output_dir,
            "demo_data_used": self.demo_data_used,
            "stages": self.stages,
            "weekly_decision": self.weekly_decision,
        }


def run_weekly_pipeline(
    cfg,
    *,
    config_path: str | Path = "",
    output_dir: str | Path | None = None,
    starting_capital: float = 100_000.0,
    target_capital: float = 1_000_000.0,
    years: float = 8.0,
    max_drawdown_budget: float = 0.20,
    review_stage: PipelineReviewStage = "paper",
    registry_path: str | Path | None = "results/strategy_registry/strategy_registry.json",
    paper_state_dir: str | Path | None = None,
    as_of: str | None = None,
    walk_forward_train_days: int = 120,
    walk_forward_test_days: int = 60,
    walk_forward_step_days: int = 60,
    prepare_micro_live_readiness: bool = False,
    micro_live_candidate: str | None = None,
    micro_live_capital: float | None = None,
    micro_live_cash_buffer_pct: float = 0.05,
    current_positions_path: str | Path | None = None,
) -> WeeklyPipelineResult:
    """Run the offline weekly evidence workflow.

    The pipeline writes research and paper-review artifacts only. It never
    creates broker credentials, writes approval records, or submits live orders.
    """
    storage = BarStorage(cfg.data.cache_path)
    provider = DataProvider(storage)
    demo_used = _ensure_data(provider, storage, cfg)
    run_dir = Path(output_dir) if output_dir else Path(cfg.output.results_dir) / _timestamp()
    run_dir.mkdir(parents=True, exist_ok=True)

    stages: list[dict[str, str]] = []
    manifest = build_run_manifest(
        provider,
        cfg,
        storage=storage,
        config_path=config_path,
        purpose="weekly_pipeline",
        demo_data_used=demo_used or _looks_like_demo_data(provider.all_symbols()),
    )
    audit = audit_data(
        provider,
        cfg.research.start,
        cfg.research.end,
        data_source=cfg.data.source,
        cache_path=cfg.data.cache_path,
        demo_data_used=manifest.demo_data_used,
    )
    research_dir, demo_like = _run_research(
        provider,
        cfg,
        run_dir,
        demo_used,
        audit=audit,
        manifest=manifest,
    )
    stages.append({"name": "research", "status": "PASS", "artifact": str(research_dir)})

    write_run_manifest(manifest, run_dir)
    stages.append({"name": "run_manifest", "status": "PASS", "artifact": "run_manifest.json"})

    bootstrap = build_real_data_bootstrap_report(
        provider,
        cfg,
        config_path="",
        cache_path=cfg.data.cache_path,
        as_of=as_of,
    )
    write_real_data_bootstrap_report(bootstrap, run_dir)
    stages.append({"name": "real_data_bootstrap", "status": bootstrap.decision, "artifact": "real_data_bootstrap.json"})

    real_data = evaluate_real_data_gate(provider, cfg.research.start, cfg.research.end, as_of=as_of)
    write_real_data_gate(real_data, run_dir)
    stages.append({"name": "real_data_gate", "status": real_data.decision, "artifact": "real_data_gate.json"})

    coverage = analyze_data_coverage(provider, cfg.research.start, cfg.research.end)
    write_data_coverage_report(coverage, run_dir)
    stages.append({"name": "data_coverage", "status": coverage.status, "artifact": "data_coverage.json"})

    write_data_audit(audit, run_dir)
    stages.append({"name": "data_audit", "status": audit.status, "artifact": "data_audit.json"})

    market = detect_market_regime(provider, cfg.research.start, cfg.research.end)
    write_market_regime_report(market, run_dir)
    stages.append({"name": "market_regime", "status": market.status, "artifact": "market_regime.json"})

    robustness = run_robustness(provider, cfg)
    write_robustness_report(robustness, run_dir)
    stages.append({"name": "robustness", "status": robustness.status, "artifact": "robustness_report.json"})

    walk_forward = run_walk_forward(
        provider,
        cfg,
        train_days=walk_forward_train_days,
        test_days=walk_forward_test_days,
        step_days=walk_forward_step_days,
    )
    write_walk_forward_report(walk_forward, run_dir)
    stages.append({"name": "walk_forward", "status": walk_forward.status, "artifact": "walk_forward_report.json"})

    candidate_walk_forward = run_candidate_walk_forward(
        provider,
        cfg,
        train_days=walk_forward_train_days,
        test_days=walk_forward_test_days,
        step_days=walk_forward_step_days,
    )
    write_candidate_walk_forward_report(candidate_walk_forward, run_dir)
    stages.append(
        {
            "name": "candidate_walk_forward",
            "status": candidate_walk_forward.status,
            "artifact": "candidate_walk_forward_report.json",
        }
    )

    candidate_factor_diagnostics = run_candidate_factor_diagnostics(
        provider,
        cfg,
        train_days=walk_forward_train_days,
        test_days=walk_forward_test_days,
        step_days=walk_forward_step_days,
        candidate=candidate_walk_forward.best_candidate or None,
    )
    write_candidate_factor_diagnostics_report(candidate_factor_diagnostics, run_dir)
    stages.append(
        {
            "name": "candidate_factor_diagnostics",
            "status": candidate_factor_diagnostics.status,
            "artifact": "candidate_factor_diagnostics.json",
        }
    )

    candidate_regime_validation = run_candidate_regime_validation(
        provider,
        cfg,
        train_days=walk_forward_train_days,
        test_days=walk_forward_test_days,
        step_days=walk_forward_step_days,
        candidate_walk_forward=candidate_walk_forward,
    )
    write_candidate_regime_validation_report(candidate_regime_validation, run_dir)
    stages.append(
        {
            "name": "candidate_regime_validation",
            "status": candidate_regime_validation.status,
            "artifact": "candidate_regime_validation_report.json",
        }
    )

    goal = CapitalGoal(
        starting_capital=starting_capital,
        target_capital=target_capital,
        years=years,
        max_drawdown_budget=max_drawdown_budget,
    )
    candidates = run_candidate_selection(
        provider,
        cfg,
        goal=goal,
        data_audit_status=audit.status,
        robustness_status=robustness.status,
        market_regime=market.to_dict(),
        candidate_walk_forward=candidate_walk_forward.to_dict(),
        candidate_regime_validation=candidate_regime_validation.to_dict(),
    )
    write_candidate_selection_report(candidates, run_dir)
    stages.append({"name": "candidate_selection", "status": candidates.status, "artifact": "candidate_selection.json"})

    paper_dir = write_paper_daily_review(paper_state_dir or run_dir, run_dir)
    paper_daily_status = str(_read_json(paper_dir / "paper_daily_review.json").get("status", "UNKNOWN"))
    stages.append({"name": "paper_daily", "status": paper_daily_status, "artifact": "paper_daily_review.json"})

    if paper_state_dir is not None:
        paper_stability = evaluate_paper_stability(paper_state_dir)
    else:
        paper_stability = missing_paper_stability_report()
    write_paper_stability_report(paper_stability, run_dir)
    stages.append(
        {
            "name": "paper_stability",
            "status": paper_stability.status,
            "artifact": "paper_stability.json",
        }
    )

    effective_review_stage: PipelineReviewStage = "micro_live_ready" if prepare_micro_live_readiness else review_stage
    llm_review = review_report(run_dir, intended_stage=effective_review_stage)
    (run_dir / "llm_review.json").write_text(
        json.dumps(llm_review.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "llm_review.md").write_text(llm_review.to_markdown(), encoding="utf-8")
    prompt = LLMReviewPromptBuilder().build(llm_review)
    (run_dir / "llm_prompt.md").write_text(prompt.to_markdown(), encoding="utf-8")
    stages.append({"name": "llm_review", "status": llm_review.decision, "artifact": "llm_review.json"})

    recent_research = build_recent_candidate_research_report(run_dir, as_of=as_of)
    write_recent_candidate_research_report(recent_research, run_dir)
    stages.append(
        {
            "name": "recent_candidate_research",
            "status": recent_research.status,
            "artifact": "recent_candidate_research.json",
        }
    )

    paper_candidate_plan = build_paper_candidate_plan(
        run_dir,
        config_path=config_path or "config/research.yaml",
        paper_state_dir=paper_state_dir or "results/paper/core",
    )
    write_paper_candidate_plan(paper_candidate_plan, run_dir)
    stages.append(
        {
            "name": "paper_candidate_plan",
            "status": paper_candidate_plan.decision,
            "artifact": "paper_candidate_plan.json",
        }
    )

    if prepare_micro_live_readiness:
        target_status = "PASS"
        try:
            target_plan = build_manual_target_plan(
                provider,
                cfg,
                as_of=as_of,
                candidate=micro_live_candidate or candidates.selected_candidate or candidates.best_candidate or None,
                capital=micro_live_capital,
                cash_buffer_pct=micro_live_cash_buffer_pct,
                current_positions=_read_positions(
                    Path(current_positions_path) if current_positions_path else run_dir / "paper_positions.csv"
                ),
            )
            write_manual_target_plan(target_plan, run_dir)
        except Exception as exc:
            target_status = "BLOCK"
            _write_micro_live_prepare_error(run_dir, exc)
        stages.append(
            {
                "name": "manual_target_plan",
                "status": target_status,
                "artifact": "target_portfolio.json",
            }
        )
        write_readiness_outputs(run_dir)
        readiness = _read_json(run_dir / "micro_live_readiness.json")
        stages.append(
            {
                "name": "micro_live_readiness",
                "status": str(readiness.get("decision", "UNKNOWN")),
                "artifact": "micro_live_readiness.json",
                "message": _payload_issue(readiness) or "Micro-live readiness completed without findings.",
            }
        )

    write_weekly_review(run_dir)
    weekly = build_weekly_review(run_dir)
    stages.append({"name": "weekly_review", "status": weekly.decision, "artifact": "weekly_review.json"})

    if registry_path is not None:
        registry = update_candidate_registry(run_dir, registry_path=registry_path)
        stages.append(
            {
                "name": "strategy_registry",
                "status": "PASS",
                "artifact": registry.registry_path,
            }
        )
        write_strategy_promotion_review(registry.registry_path, run_dir, goal=goal)
        promotion = _read_json(run_dir / "strategy_promotion_review.json")
        stages.append(
            {
                "name": "strategy_promotion_review",
                "status": str(promotion.get("decision", "UNKNOWN")),
                "artifact": "strategy_promotion_review.json",
            }
        )

    goal_status = build_capital_goal_status(run_dir, goal=goal)
    write_capital_goal_status(goal_status, run_dir)
    stages.append(
        {
            "name": "capital_goal_status",
            "status": goal_status.decision,
            "artifact": "capital_goal_status.json",
            "message": _payload_issue(goal_status.to_dict()) or "Capital goal status completed.",
        }
    )

    result = WeeklyPipelineResult(
        output_dir=str(run_dir),
        demo_data_used=demo_like,
        stages=stages,
        weekly_decision=weekly.decision,
    )
    (run_dir / "weekly_pipeline.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "weekly_pipeline.md").write_text(_pipeline_markdown(result, weekly), encoding="utf-8")
    return result


def _run_research(
    provider: DataProvider,
    cfg,
    run_dir: Path,
    demo_used: bool,
    *,
    audit,
    manifest,
) -> tuple[Path, bool]:
    factor_pipeline = FactorPipeline()
    strategy = MultiFactorTargetStrategy(
        UniverseFilter(
            UniverseConfig(
                mode=cfg.universe.mode,
                index_code=cfg.universe.index_code,
                include_st=cfg.universe.include_st,
                min_history_days=cfg.universe.min_history_days,
            )
        ),
        factor_pipeline,
        MultiFactorStrategyConfig(
            n_holdings=cfg.strategy.n_holdings,
            max_weight=cfg.strategy.max_weight,
        ),
    )
    broker = PaperBroker(
        PaperBrokerConfig(
            commission_rate=cfg.broker.commission_rate,
            min_commission=cfg.broker.min_commission,
            stamp_tax=cfg.broker.stamp_tax,
            slippage_bps=cfg.broker.slippage_bps,
            price_limit_pct=cfg.broker.price_limit_pct,
            lot_size=cfg.broker.lot_size,
        )
    )
    engine = ResearchEngine(
        provider,
        strategy,
        broker,
        Portfolio(initial_cash=cfg.research.initial_cash),
        factor_pipeline,
        max_drawdown_stop=cfg.risk.max_drawdown_stop,
    )
    result = engine.run(cfg.research.start, cfg.research.end, rebalance=cfg.research.rebalance)
    trading_days = provider.trading_days(cfg.research.start, cfg.research.end)
    all_symbols = provider.all_symbols()
    demo_like = demo_used or _looks_like_demo_data(all_symbols)
    assumptions = {
        "data_source": cfg.data.source,
        "cache_path": cfg.data.cache_path,
        "demo_data_used": demo_like,
        "start": cfg.research.start,
        "end": cfg.research.end,
        "universe": cfg.universe.mode,
        "rebalance": cfg.research.rebalance,
        "in_sample_end": cfg.research.in_sample_end,
        "out_sample_start": cfg.research.out_sample_start,
        "n_holdings": cfg.strategy.n_holdings,
        "max_weight": cfg.strategy.max_weight,
        "symbol_count": len(all_symbols),
        "trading_day_count": len(trading_days),
        "notice": "Research simulation only; no broker or live trading connection.",
    }
    return (
        write_research_report(
            result,
            run_dir,
            title="A-share multi-factor weekly pipeline research",
            assumptions=assumptions,
            evidence=research_evidence_digest(audit=audit, manifest=manifest),
        ),
        demo_like,
    )


def _ensure_data(provider: DataProvider, storage: BarStorage, cfg) -> bool:
    symbols = provider.all_symbols()
    days = provider.trading_days(cfg.research.start, cfg.research.end)
    if symbols and days:
        if _looks_like_demo_data(symbols) and not cfg.research.allow_demo_data:
            raise RuntimeError(
                "Cached data appears to be deterministic demo data. "
                "Import real research data or set allow_demo_data=true for tutorials."
            )
        return False
    if not cfg.research.allow_demo_data:
        raise RuntimeError("No cached research data found and allow_demo_data=false.")
    seed_demo_data(storage, cfg.research.start, cfg.research.end)
    return True


def _read_positions(path: Path) -> pd.DataFrame | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    return pd.read_csv(path)


def _write_micro_live_prepare_error(root: Path, exc: Exception) -> None:
    payload = {
        "status": "BLOCK",
        "message": str(exc),
        "prohibited_actions": [
            "Do not treat a failed target-plan preparation as approval for micro-live readiness.",
            "Do not submit broker orders from partial or missing manual target artifacts.",
        ],
    }
    (root / "micro_live_readiness_prepare_error.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _pipeline_markdown(result: WeeklyPipelineResult, weekly: WeeklyReview) -> str:
    lines = [
        f"# Weekly Pipeline: {result.weekly_decision}",
        "",
        f"- Output directory: `{result.output_dir}`",
        f"- Demo data used: `{result.demo_data_used}`",
        "",
        "## Stages",
        "",
        "| stage | status | artifact | message |",
        "| --- | --- | --- | --- |",
    ]
    for stage in result.stages:
        lines.append(
            f"| {stage['name']} | `{stage['status']}` | `{stage['artifact']}` | "
            f"{_markdown_cell(stage.get('message', ''))} |"
        )
    lines.extend(["", "## Weekly Required Actions"])
    lines.extend(f"- {item}" for item in weekly.required_actions)
    lines.extend(["", "## Safety Boundary"])
    lines.extend(
        [
            "- This pipeline is offline research and paper review only.",
            "- It does not call an external LLM by default.",
            "- It does not write approval records or submit broker orders.",
        ]
    )
    return "\n".join(lines) + "\n"


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _looks_like_demo_data(symbols: list[str]) -> bool:
    return bool(symbols) and all(symbol.startswith("DEMO") for symbol in symbols)


def _payload_issue(payload: dict[str, Any]) -> str:
    for key in ("blockers", "watch_items", "next_actions"):
        values = payload.get(key)
        if isinstance(values, list):
            for value in values:
                text = str(value or "").strip()
                if text:
                    return text
    findings = payload.get("findings")
    if isinstance(findings, list):
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            code = str(finding.get("code") or "").strip()
            message = str(finding.get("message") or "").strip()
            if code and message:
                return f"{code}: {message}"
            if message:
                return message
    return ""


def _markdown_cell(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
