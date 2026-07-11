"""Persistent strategy candidate registry for long-horizon comparison."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CandidateRegistry:
    registry_path: str
    run_count: int
    candidate_count: int
    leaders: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "registry_path": self.registry_path,
            "run_count": self.run_count,
            "candidate_count": self.candidate_count,
            "leaders": self.leaders,
        }

    def to_markdown(self) -> str:
        lines = [
            "# Strategy Candidate Registry",
            "",
            f"- Registry path: `{self.registry_path}`",
            f"- Runs: {self.run_count}",
            f"- Candidates: {self.candidate_count}",
            "",
            "| candidate | eligible | real_obs | demo_obs | latest_decision | latest_cwf | latest_regime | real_cwf_pass | avg_real_return | avg_real_drawdown | avg_real_sharpe | real_pass | total_obs |",
            "| --- | --- | ---: | ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for row in self.leaders:
            lines.append(
                "| {name} | `{eligible}` | {real_obs} | {demo_obs} | `{decision}` | `{cwf}` | `{regime}` | {cwf_pass:.2%} | {ret:.2%} | {dd:.2%} | {sharpe:.2f} | {real_pass} | {obs} |".format(
                    name=row["name"],
                    eligible=row["promotion_eligible"],
                    real_obs=row["real_observation_count"],
                    demo_obs=row["demo_observation_count"],
                    obs=row["observations"],
                    decision=row["latest_decision"],
                    cwf=row["latest_candidate_walk_forward_status"],
                    regime=row["latest_candidate_regime_validation_status"],
                    cwf_pass=row["real_avg_candidate_walk_forward_pass_ratio"],
                    ret=row["real_avg_annualized_return"],
                    dd=row["real_avg_max_drawdown"],
                    sharpe=row["real_avg_sharpe_ratio"],
                    real_pass=row["real_pass_count"],
                )
            )
        lines.extend(["", "## Promotion Notes"])
        for row in self.leaders:
            lines.append(f"- `{row['name']}`: {row['promotion_reason']}")
        lines.extend(
            [
                "",
                "This registry is a research memory, not a profit forecast or live trading instruction.",
            ]
        )
        return "\n".join(lines) + "\n"


def update_candidate_registry(
    report_dir: str | Path,
    *,
    registry_path: str | Path,
) -> CandidateRegistry:
    report_root = Path(report_dir)
    registry_file = Path(registry_path)
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    payload = _read_json(registry_file) or {"runs": [], "candidates": {}}
    runs = list(payload.get("runs", []) or [])
    candidates = dict(payload.get("candidates", {}) or {})

    selection = _read_json(report_root / "candidate_selection.json")
    if not selection:
        raise FileNotFoundError(f"Missing candidate_selection.json in {report_root}")
    market = selection.get("market_regime", {}) or {}
    weekly = _read_json(report_root / "weekly_review.json")
    pipeline = _read_json(report_root / "weekly_pipeline.json")
    data_audit = _read_json(report_root / "data_audit.json")
    robustness = _read_json(report_root / "robustness_report.json")
    llm_review = _read_json(report_root / "llm_review.json")
    summary = _read_json(report_root / "summary.json")
    candidate_walk_forward = _read_json(report_root / "candidate_walk_forward_report.json")
    candidate_walk_forward_summaries = _candidate_walk_forward_summaries(candidate_walk_forward)
    candidate_regime = _read_json(report_root / "candidate_regime_validation_report.json")
    candidate_regime_summaries = _candidate_regime_summaries(candidate_regime)
    run_id = report_root.name
    recorded_at = datetime.now(timezone.utc).isoformat()

    run_record = {
        "run_id": run_id,
        "recorded_at": recorded_at,
        "report_dir": str(report_root),
        "selection_status": selection.get("status", "UNKNOWN"),
        "selected_candidate": selection.get("selected_candidate", selection.get("best_candidate", "")),
        "best_candidate": selection.get("selected_candidate", selection.get("best_candidate", "")),
        "top_candidate": selection.get("top_candidate", selection.get("best_candidate", "")),
        "market_regime": market.get("label", "unknown"),
        "market_status": market.get("status", "UNKNOWN"),
        "weekly_decision": weekly.get("decision", pipeline.get("weekly_decision", "UNKNOWN")),
        "data_audit_status": data_audit.get("status", "UNKNOWN"),
        "robustness_status": robustness.get("status", "UNKNOWN"),
        "candidate_walk_forward_status": candidate_walk_forward.get("status", "UNKNOWN"),
        "candidate_walk_forward_best_candidate": candidate_walk_forward.get("best_candidate", ""),
        "candidate_regime_validation_status": candidate_regime.get("status", "UNKNOWN"),
        "candidate_regime_validation_best_candidate": candidate_regime.get("best_candidate", ""),
        "llm_review_decision": llm_review.get("decision", "UNKNOWN"),
        "demo_data_used": bool((summary.get("assumptions", {}) or {}).get("demo_data_used", False)),
    }
    runs.append(run_record)

    for result in selection.get("results", []) or []:
        name = str(result.get("name", ""))
        if not name:
            continue
        history = list((candidates.get(name, {}) or {}).get("history", []) or [])
        score = result.get("score", {}) or {}
        metrics = result.get("metrics", {}) or {}
        wf = candidate_walk_forward_summaries.get(name, {})
        wf_window_count = int(wf.get("window_count", 0) or 0)
        wf_pass_count = int(wf.get("pass_count", 0) or 0)
        regime = candidate_regime_summaries.get(name, {})
        history.append(
            {
                "run_id": run_id,
                "recorded_at": recorded_at,
                "decision": score.get("decision", "UNKNOWN"),
                "score": _float(score.get("score")),
                "annualized_return": _float(metrics.get("annualized_return")),
                "max_drawdown": _float(metrics.get("max_drawdown")),
                "sharpe_ratio": _float(metrics.get("sharpe_ratio")),
                "reject_rate": _float(result.get("reject_rate")),
                "avg_turnover_pct": _float(result.get("avg_turnover_pct")),
                "candidate_walk_forward_status": str(wf.get("status", "UNKNOWN")),
                "candidate_walk_forward_window_count": wf_window_count,
                "candidate_walk_forward_pass_count": wf_pass_count,
                "candidate_walk_forward_pass_ratio": wf_pass_count / wf_window_count if wf_window_count else 0.0,
                "candidate_walk_forward_avg_total_return": _float(wf.get("avg_total_return")),
                "candidate_walk_forward_avg_max_drawdown": _float(wf.get("avg_max_drawdown")),
                "candidate_walk_forward_avg_sharpe_ratio": _float(wf.get("avg_sharpe_ratio")),
                "candidate_walk_forward_avg_reject_rate": _float(wf.get("avg_reject_rate")),
                "candidate_walk_forward_positive_return_ratio": _float(
                    wf.get("positive_return_ratio")
                ),
                "candidate_walk_forward_worst_total_return": _float(wf.get("worst_total_return")),
                "candidate_walk_forward_worst_max_drawdown": _float(wf.get("worst_max_drawdown")),
                "candidate_regime_validation_status": str(regime.get("status", "UNKNOWN")),
                "candidate_regime_count": int(regime.get("regime_count", 0) or 0),
                "candidate_regime_known_count": int(regime.get("known_regime_count", 0) or 0),
                "candidate_regime_adverse_window_count": int(
                    regime.get("adverse_regime_window_count", 0) or 0
                ),
                "candidate_regime_pass_bucket_count": int(regime.get("pass_bucket_count", 0) or 0),
                "candidate_regime_watch_bucket_count": int(regime.get("watch_bucket_count", 0) or 0),
                "candidate_regime_block_bucket_count": int(regime.get("block_bucket_count", 0) or 0),
                "candidate_regime_avg_total_return": _float(regime.get("avg_total_return")),
                "candidate_regime_avg_max_drawdown": _float(regime.get("avg_max_drawdown")),
                "candidate_regime_avg_sharpe_ratio": _float(regime.get("avg_sharpe_ratio")),
                "market_regime": market.get("label", "unknown"),
                "weekly_decision": run_record["weekly_decision"],
                "demo_data_used": run_record["demo_data_used"],
            }
        )
        candidates[name] = {
            "name": name,
            "description": result.get("description", ""),
            "factors": result.get("factors", []),
            "history": history,
            "summary": _candidate_summary(name, history),
        }

    payload = {
        "updated_at": recorded_at,
        "runs": runs,
        "candidates": candidates,
    }
    registry_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report = _registry_report(registry_file, payload)
    (registry_file.parent / "strategy_registry.md").write_text(report.to_markdown(), encoding="utf-8")
    (report_root / "strategy_registry_snapshot.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (report_root / "strategy_registry_snapshot.md").write_text(report.to_markdown(), encoding="utf-8")
    return report


def _registry_report(registry_file: Path, payload: dict[str, Any]) -> CandidateRegistry:
    candidates = payload.get("candidates", {}) or {}
    summaries = [
        candidate.get("summary", {})
        for candidate in candidates.values()
        if candidate.get("summary")
    ]
    leaders = sorted(
        summaries,
        key=lambda row: (
            bool(row.get("promotion_eligible", False)),
            int(row.get("real_pass_count", 0)),
            int(row.get("real_observation_count", 0)),
            int(row.get("real_candidate_walk_forward_pass_count", 0)),
            float(row.get("real_avg_candidate_walk_forward_pass_ratio", 0.0)),
            int(row.get("real_candidate_regime_pass_count", 0)),
            float(row.get("real_avg_candidate_regime_adverse_window_count", 0.0)),
            -int(row.get("real_block_count", 0)),
            float(row.get("real_avg_score", 0.0)),
            float(row.get("real_avg_sharpe_ratio", 0.0)),
        ),
        reverse=True,
    )
    return CandidateRegistry(
        registry_path=str(registry_file),
        run_count=len(payload.get("runs", []) or []),
        candidate_count=len(candidates),
        leaders=leaders,
    )


def _candidate_summary(name: str, history: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = [str(row.get("decision", "UNKNOWN")) for row in history]
    real_history = [row for row in history if not row.get("demo_data_used")]
    demo_history = [row for row in history if row.get("demo_data_used")]
    real_decisions = [str(row.get("decision", "UNKNOWN")) for row in real_history]
    demo_decisions = [str(row.get("decision", "UNKNOWN")) for row in demo_history]
    promotion_eligible, promotion_reason = _promotion_state(real_history, real_decisions)
    return {
        "name": name,
        "observations": len(history),
        "latest_decision": decisions[-1] if decisions else "UNKNOWN",
        "latest_candidate_walk_forward_status": str(
            history[-1].get("candidate_walk_forward_status", "UNKNOWN")
        )
        if history
        else "UNKNOWN",
        "latest_candidate_regime_validation_status": str(
            history[-1].get("candidate_regime_validation_status", "UNKNOWN")
        )
        if history
        else "UNKNOWN",
        "latest_run_id": history[-1].get("run_id", "") if history else "",
        "pass_count": decisions.count("PASS"),
        "watch_count": decisions.count("WATCH"),
        "block_count": decisions.count("BLOCK"),
        "avg_score": _avg(history, "score"),
        "avg_annualized_return": _avg(history, "annualized_return"),
        "avg_max_drawdown": _avg(history, "max_drawdown"),
        "avg_sharpe_ratio": _avg(history, "sharpe_ratio"),
        "avg_reject_rate": _avg(history, "reject_rate"),
        "avg_turnover_pct": _avg(history, "avg_turnover_pct"),
        "real_observation_count": len(real_history),
        "demo_observation_count": len(demo_history),
        "real_pass_count": real_decisions.count("PASS"),
        "real_watch_count": real_decisions.count("WATCH"),
        "real_block_count": real_decisions.count("BLOCK"),
        "demo_pass_count": demo_decisions.count("PASS"),
        "demo_watch_count": demo_decisions.count("WATCH"),
        "demo_block_count": demo_decisions.count("BLOCK"),
        "real_avg_score": _avg(real_history, "score"),
        "real_avg_annualized_return": _avg(real_history, "annualized_return"),
        "real_avg_max_drawdown": _avg(real_history, "max_drawdown"),
        "real_avg_sharpe_ratio": _avg(real_history, "sharpe_ratio"),
        "real_avg_reject_rate": _avg(real_history, "reject_rate"),
        "real_avg_turnover_pct": _avg(real_history, "avg_turnover_pct"),
        "real_candidate_walk_forward_observation_count": _known_count(
            real_history, "candidate_walk_forward_status"
        ),
        "real_candidate_walk_forward_pass_count": _status_count(
            real_history, "candidate_walk_forward_status", "PASS"
        ),
        "real_candidate_walk_forward_watch_count": _status_count(
            real_history, "candidate_walk_forward_status", "WATCH"
        ),
        "real_candidate_walk_forward_block_count": _status_count(
            real_history, "candidate_walk_forward_status", "BLOCK"
        ),
        "real_avg_candidate_walk_forward_pass_ratio": _avg(
            real_history, "candidate_walk_forward_pass_ratio"
        ),
        "real_avg_candidate_walk_forward_return": _avg(
            real_history, "candidate_walk_forward_avg_total_return"
        ),
        "real_avg_candidate_walk_forward_drawdown": _avg(
            real_history, "candidate_walk_forward_avg_max_drawdown"
        ),
        "real_avg_candidate_walk_forward_sharpe": _avg(
            real_history, "candidate_walk_forward_avg_sharpe_ratio"
        ),
        "real_avg_candidate_walk_forward_reject_rate": _avg(
            real_history, "candidate_walk_forward_avg_reject_rate"
        ),
        "real_avg_candidate_walk_forward_positive_return_ratio": _avg(
            real_history, "candidate_walk_forward_positive_return_ratio"
        ),
        "real_worst_candidate_walk_forward_return": _min(
            real_history, "candidate_walk_forward_worst_total_return"
        ),
        "real_worst_candidate_walk_forward_drawdown": _max(
            real_history, "candidate_walk_forward_worst_max_drawdown"
        ),
        "real_candidate_regime_observation_count": _known_count(
            real_history, "candidate_regime_validation_status"
        ),
        "real_candidate_regime_pass_count": _status_count(
            real_history, "candidate_regime_validation_status", "PASS"
        ),
        "real_candidate_regime_watch_count": _status_count(
            real_history, "candidate_regime_validation_status", "WATCH"
        ),
        "real_candidate_regime_block_count": _status_count(
            real_history, "candidate_regime_validation_status", "BLOCK"
        ),
        "real_avg_candidate_regime_count": _avg(real_history, "candidate_regime_count"),
        "real_avg_candidate_regime_known_count": _avg(real_history, "candidate_regime_known_count"),
        "real_avg_candidate_regime_adverse_window_count": _avg(
            real_history, "candidate_regime_adverse_window_count"
        ),
        "real_avg_candidate_regime_return": _avg(real_history, "candidate_regime_avg_total_return"),
        "real_avg_candidate_regime_drawdown": _avg(real_history, "candidate_regime_avg_max_drawdown"),
        "real_avg_candidate_regime_sharpe": _avg(real_history, "candidate_regime_avg_sharpe_ratio"),
        "demo_avg_score": _avg(demo_history, "score"),
        "demo_avg_annualized_return": _avg(demo_history, "annualized_return"),
        "demo_avg_max_drawdown": _avg(demo_history, "max_drawdown"),
        "demo_avg_sharpe_ratio": _avg(demo_history, "sharpe_ratio"),
        "promotion_eligible": promotion_eligible,
        "promotion_reason": promotion_reason,
    }


def _promotion_state(
    real_history: list[dict[str, Any]],
    real_decisions: list[str],
) -> tuple[bool, str]:
    if len(real_history) < 3:
        return False, "Needs at least 3 real-data observations before promotion discussion."
    if real_decisions.count("BLOCK"):
        return False, "Real-data history contains BLOCK observations."
    if real_decisions.count("PASS") < 2:
        return False, "Needs at least 2 PASS observations on real data."
    known_wf = [
        row
        for row in real_history
        if str(row.get("candidate_walk_forward_status", "UNKNOWN")) != "UNKNOWN"
    ]
    wf_statuses = [str(row.get("candidate_walk_forward_status", "UNKNOWN")) for row in known_wf]
    if len(known_wf) < 3:
        return False, "Needs at least 3 real-data candidate walk-forward observations."
    if wf_statuses.count("BLOCK"):
        return False, "Real-data candidate walk-forward history contains BLOCK observations."
    if wf_statuses.count("PASS") < 2:
        return False, "Needs at least 2 PASS candidate walk-forward observations on real data."
    if _avg(known_wf, "candidate_walk_forward_pass_ratio") < 0.60:
        return False, "Real-data candidate walk-forward pass ratio is below 60%."
    if _avg(known_wf, "candidate_walk_forward_positive_return_ratio") < 0.60:
        return False, "Real-data candidate walk-forward positive-return ratio is below 60%."
    if _min(known_wf, "candidate_walk_forward_worst_total_return") <= -0.10:
        return False, "A real-data candidate walk-forward window lost more than 10%."
    known_regime = [
        row
        for row in real_history
        if str(row.get("candidate_regime_validation_status", "UNKNOWN")) != "UNKNOWN"
    ]
    regime_statuses = [
        str(row.get("candidate_regime_validation_status", "UNKNOWN")) for row in known_regime
    ]
    if len(known_regime) < 3:
        return False, "Needs at least 3 real-data candidate regime validation observations."
    if regime_statuses.count("BLOCK"):
        return False, "Real-data candidate regime validation history contains BLOCK observations."
    if regime_statuses.count("PASS") < 1:
        return False, "Needs at least 1 PASS candidate regime validation observation on real data."
    if _avg(known_regime, "candidate_regime_adverse_window_count") <= 0:
        return False, "Needs defensive or risk_off regime validation windows before promotion."
    if _avg(real_history, "max_drawdown") > 0.20:
        return False, "Real-data average drawdown exceeds the 20% research budget."
    if _avg(real_history, "reject_rate") >= 0.20:
        return False, "Real-data average reject rate is too high."
    return True, "Eligible for deeper paper-stage review; still not a live trading instruction."


def _avg(history: list[dict[str, Any]], key: str) -> float:
    values = [_float(row.get(key)) for row in history]
    return sum(values) / len(values) if values else 0.0


def _min(history: list[dict[str, Any]], key: str) -> float:
    values = [_float(row.get(key)) for row in history]
    return min(values) if values else 0.0


def _max(history: list[dict[str, Any]], key: str) -> float:
    values = [_float(row.get(key)) for row in history]
    return max(values) if values else 0.0


def _known_count(history: list[dict[str, Any]], key: str) -> int:
    return sum(1 for row in history if str(row.get(key, "UNKNOWN")) != "UNKNOWN")


def _status_count(history: list[dict[str, Any]], key: str, status: str) -> int:
    return sum(1 for row in history if str(row.get(key, "UNKNOWN")) == status)


def _candidate_walk_forward_summaries(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("candidate", "")): row
        for row in report.get("summaries", []) or []
        if row.get("candidate")
    }


def _candidate_regime_summaries(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("candidate", "")): row
        for row in report.get("summaries", []) or []
        if row.get("candidate")
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
