"""Persistent strategy candidate registry for long-horizon comparison."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quantify.data.provenance import (
    LATEST_IMPORT_BATCH_METADATA_KEY,
    LINEAGE_SCHEMA_VERSION,
    LINEAGE_SCHEMA_VERSION_METADATA_KEY,
    LOGICAL_BAR_FINGERPRINT_ALGORITHM,
    LOGICAL_BAR_FINGERPRINT_ALGORITHM_METADATA_KEY,
    LOGICAL_BAR_FINGERPRINT_METADATA_KEY,
)
from quantify.research.evidence_validation import (
    validate_benchmark_payload,
    validate_multiple_testing_payload,
    validate_trial_registry_review_payload,
)
from quantify.research.walk_forward_protocol import (
    CANDIDATE_WALK_FORWARD_ARTIFACT,
    WALK_FORWARD_ARTIFACT,
    validate_robustness_selection_safe_payload,
    validate_selection_safe_payload,
)

STRATEGY_REGISTRY_SCHEMA_VERSION = 3


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
            "| candidate | eligible | real_obs | unattested_obs | selection_unsafe_obs | statistical_unsafe_obs | demo_obs | latest_decision | latest_cwf | latest_regime | real_cwf_pass | avg_real_return | avg_real_drawdown | avg_real_sharpe | real_pass | total_obs |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for row in self.leaders:
            lines.append(
                "| {name} | `{eligible}` | {real_obs} | {unattested_obs} | {selection_unsafe_obs} | {statistical_unsafe_obs} | {demo_obs} | `{decision}` | `{cwf}` | `{regime}` | {cwf_pass:.2%} | {ret:.2%} | {dd:.2%} | {sharpe:.2f} | {real_pass} | {obs} |".format(
                    name=row["name"],
                    eligible=row["promotion_eligible"],
                    real_obs=row["real_observation_count"],
                    unattested_obs=row["unattested_observation_count"],
                    selection_unsafe_obs=row["selection_unsafe_observation_count"],
                    statistical_unsafe_obs=row["statistical_unsafe_observation_count"],
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
    manifest = _read_json(report_root / "run_manifest.json")
    walk_forward = _read_json(report_root / "walk_forward_report.json")
    candidate_walk_forward = _read_json(report_root / "candidate_walk_forward_report.json")
    candidate_walk_forward_summaries = _candidate_walk_forward_summaries(candidate_walk_forward)
    candidate_regime = _read_json(report_root / "candidate_regime_validation_report.json")
    candidate_regime_summaries = _candidate_regime_summaries(candidate_regime)
    run_id = report_root.name
    recorded_at = datetime.now(UTC).isoformat()
    summary_demo_data_used = bool(
        (summary.get("assumptions", {}) or {}).get("demo_data_used", False)
    )
    manifest_demo_data_used = bool(manifest.get("demo_data_used", False))
    demo_data_used = summary_demo_data_used or manifest_demo_data_used
    attestation = _data_attestation(manifest, demo_data_used=demo_data_used)
    selection_safety = _selection_safety(
        walk_forward,
        candidate_walk_forward,
        robustness,
    )
    statistical_safety = _statistical_evidence_safety(
        report_root,
        selection=selection,
        manifest=manifest,
    )
    promotion_eligible_real_observation = (
        attestation["attested_real_observation"] is True
        and selection_safety["selection_safe"] is True
        and statistical_safety["statistical_evidence_safe"] is True
    )

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
        "demo_data_used": demo_data_used,
        **attestation,
        **selection_safety,
        **statistical_safety,
        "promotion_eligible_real_observation": promotion_eligible_real_observation,
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
                "data_source": run_record["data_source"],
                "cache_logical_bar_fingerprint": run_record[
                    "cache_logical_bar_fingerprint"
                ],
                "cache_logical_bar_fingerprint_algorithm": run_record[
                    "cache_logical_bar_fingerprint_algorithm"
                ],
                "cache_latest_import_batch_id": run_record[
                    "cache_latest_import_batch_id"
                ],
                "cache_lineage_schema_version": run_record[
                    "cache_lineage_schema_version"
                ],
                "attestation_status": run_record["attestation_status"],
                "attestation_reason": run_record["attestation_reason"],
                "attested_real_observation": run_record["attested_real_observation"],
                "walk_forward_selection_safe": run_record[
                    "walk_forward_selection_safe"
                ],
                "candidate_walk_forward_selection_safe": run_record[
                    "candidate_walk_forward_selection_safe"
                ],
                "robustness_selection_safe": run_record["robustness_selection_safe"],
                "selection_safe": run_record["selection_safe"],
                "selection_safety_status": run_record["selection_safety_status"],
                "selection_safety_reason": run_record["selection_safety_reason"],
                "benchmark_evidence_pass": run_record["benchmark_evidence_pass"],
                "multiple_testing_evidence_pass": run_record[
                    "multiple_testing_evidence_pass"
                ],
                "trial_registry_evidence_pass": run_record[
                    "trial_registry_evidence_pass"
                ],
                "statistical_evidence_safe": run_record["statistical_evidence_safe"],
                "statistical_evidence_status": run_record["statistical_evidence_status"],
                "statistical_evidence_reason": run_record["statistical_evidence_reason"],
                "statistical_evidence_contract_version": STRATEGY_REGISTRY_SCHEMA_VERSION,
                "promotion_eligible_real_observation": run_record[
                    "promotion_eligible_real_observation"
                ],
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
        "schema_version": STRATEGY_REGISTRY_SCHEMA_VERSION,
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
    real_history = [row for row in history if _is_promotion_eligible_real_observation(row)]
    demo_history = [row for row in history if row.get("demo_data_used")]
    unattested_history = [
        row
        for row in history
        if not row.get("demo_data_used") and row.get("attested_real_observation") is not True
    ]
    selection_unsafe_history = [
        row
        for row in history
        if not row.get("demo_data_used")
        and row.get("attested_real_observation") is True
        and not _has_safe_walk_forward_selection(row)
    ]
    statistical_unsafe_history = [
        row
        for row in history
        if not row.get("demo_data_used")
        and row.get("attested_real_observation") is True
        and _has_safe_walk_forward_selection(row)
        and not _has_safe_statistical_evidence(row)
    ]
    real_decisions = [str(row.get("decision", "UNKNOWN")) for row in real_history]
    demo_decisions = [str(row.get("decision", "UNKNOWN")) for row in demo_history]
    promotion_eligible, promotion_reason = _promotion_state(real_history, real_decisions)
    if unattested_history:
        promotion_reason = (
            f"{promotion_reason} {len(unattested_history)} non-demo observation(s) were excluded "
            "because data attestation did not pass."
        )
    if selection_unsafe_history:
        promotion_reason = (
            f"{promotion_reason} {len(selection_unsafe_history)} attested non-demo "
            "observation(s) were excluded because walk-forward selection safety did not pass."
        )
    if statistical_unsafe_history:
        promotion_reason = (
            f"{promotion_reason} {len(statistical_unsafe_history)} attested selection-safe "
            "observation(s) were excluded because benchmark, multiple-testing, or prospective "
            "trial evidence did not pass."
        )
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
        "selection_contract_version": STRATEGY_REGISTRY_SCHEMA_VERSION,
        "statistical_evidence_contract_version": STRATEGY_REGISTRY_SCHEMA_VERSION,
        "selection_safe_real_observation_count": len(real_history),
        "statistical_safe_real_observation_count": len(real_history),
        "unattested_observation_count": len(unattested_history),
        "selection_unsafe_observation_count": len(selection_unsafe_history),
        "statistical_unsafe_observation_count": len(statistical_unsafe_history),
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
        return (
            False,
            "Needs at least 3 real-data observations with PASS data attestation and "
            "selection-safe walk-forward reports before promotion discussion.",
        )
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


def _data_attestation(
    manifest: dict[str, Any],
    *,
    demo_data_used: bool,
) -> dict[str, Any]:
    data_version = manifest.get("data_version", {}) or {}
    if not isinstance(data_version, dict):
        data_version = {}
    data_source = str(
        manifest.get("data_source") or data_version.get("data_source") or ""
    ).strip()
    logical_fingerprint = str(
        data_version.get(LOGICAL_BAR_FINGERPRINT_METADATA_KEY, "") or ""
    ).strip()
    algorithm = str(
        data_version.get(LOGICAL_BAR_FINGERPRINT_ALGORITHM_METADATA_KEY, "") or ""
    ).strip()
    batch_id = str(data_version.get(LATEST_IMPORT_BATCH_METADATA_KEY, "") or "").strip()
    lineage_schema_version = str(
        data_version.get(LINEAGE_SCHEMA_VERSION_METADATA_KEY, "") or ""
    ).strip()
    blockers: list[str] = []
    if not manifest:
        blockers.append("run_manifest.json is missing")
    if not logical_fingerprint:
        blockers.append("cache_logical_bar_fingerprint is missing")
    if algorithm != LOGICAL_BAR_FINGERPRINT_ALGORITHM:
        blockers.append(
            "cache_logical_bar_fingerprint_algorithm must be "
            f"{LOGICAL_BAR_FINGERPRINT_ALGORITHM}"
        )
    if not batch_id:
        blockers.append("cache_latest_import_batch_id is missing")
    if lineage_schema_version != LINEAGE_SCHEMA_VERSION:
        blockers.append(f"cache_lineage_schema_version must be {LINEAGE_SCHEMA_VERSION}")
    if str(data_version.get("data_source_qa_status", "") or "").upper() != "PASS":
        blockers.append("data_source_qa_status must be PASS")
    if _is_csv_route(manifest, data_version):
        if not str(data_version.get("csv_dataset_fingerprint", "") or "").strip():
            blockers.append("CSV route requires csv_dataset_fingerprint")
        if str(data_version.get("data_source_csv_qa_status", "") or "").upper() != "PASS":
            blockers.append("CSV route requires data_source_csv_qa_status=PASS")

    if demo_data_used:
        status = "DEMO_DATA"
        reason = "Demo data observations are never attested real observations."
    elif blockers:
        status = "UNATTESTED"
        reason = "; ".join(blockers) + "."
    else:
        status = "PASS"
        reason = "Run manifest contains the required cache provenance attestation."
    return {
        "data_source": data_source,
        "cache_logical_bar_fingerprint": logical_fingerprint,
        "cache_logical_bar_fingerprint_algorithm": algorithm,
        "cache_latest_import_batch_id": batch_id,
        "cache_lineage_schema_version": lineage_schema_version,
        "attestation_status": status,
        "attestation_reason": reason,
        "attested_real_observation": status == "PASS" and not demo_data_used,
    }


def _selection_safety(
    walk_forward: dict[str, Any],
    candidate_walk_forward: dict[str, Any],
    robustness: dict[str, Any],
) -> dict[str, Any]:
    walk_forward_validation = validate_selection_safe_payload(
        walk_forward,
        artifact_type=WALK_FORWARD_ARTIFACT,
    )
    candidate_validation = validate_selection_safe_payload(
        candidate_walk_forward,
        artifact_type=CANDIDATE_WALK_FORWARD_ARTIFACT,
    )
    robustness_validation = validate_robustness_selection_safe_payload(robustness)
    walk_forward_safe = walk_forward_validation.safe
    candidate_walk_forward_safe = candidate_validation.safe
    robustness_safe = robustness_validation.safe
    selection_safe = walk_forward_safe and candidate_walk_forward_safe and robustness_safe
    if selection_safe:
        reason = (
            "Walk-forward and robustness reports satisfy their complete selection-safe contracts."
        )
    else:
        unsafe_reports = []
        if not walk_forward_safe:
            unsafe_reports.append(
                "walk_forward_report.json (" + "; ".join(walk_forward_validation.reasons) + ")"
            )
        if not candidate_walk_forward_safe:
            unsafe_reports.append(
                "candidate_walk_forward_report.json ("
                + "; ".join(candidate_validation.reasons)
                + ")"
            )
        if not robustness_safe:
            unsafe_reports.append(
                "robustness_report.json (" + "; ".join(robustness_validation.reasons) + ")"
            )
        reason = (
            "Excluded from promotion-eligible real observations because selection_safe is not "
            f"exactly true in {', '.join(unsafe_reports)}."
        )
    return {
        "walk_forward_selection_safe": walk_forward_safe,
        "candidate_walk_forward_selection_safe": candidate_walk_forward_safe,
        "robustness_selection_safe": robustness_safe,
        "selection_safe": selection_safe,
        "selection_safety_status": "PASS" if selection_safe else "UNSAFE",
        "selection_safety_reason": reason,
    }


def _has_safe_walk_forward_selection(row: dict[str, Any]) -> bool:
    return (
        row.get("walk_forward_selection_safe") is True
        and row.get("candidate_walk_forward_selection_safe") is True
        and row.get("robustness_selection_safe") is True
    )


def _has_safe_statistical_evidence(row: dict[str, Any]) -> bool:
    return (
        row.get("statistical_evidence_contract_version") == STRATEGY_REGISTRY_SCHEMA_VERSION
        and row.get("benchmark_evidence_pass") is True
        and row.get("multiple_testing_evidence_pass") is True
        and row.get("trial_registry_evidence_pass") is True
        and row.get("statistical_evidence_safe") is True
    )


def _is_promotion_eligible_real_observation(row: dict[str, Any]) -> bool:
    return (
        not row.get("demo_data_used")
        and row.get("attested_real_observation") is True
        and _has_safe_walk_forward_selection(row)
        and _has_safe_statistical_evidence(row)
    )


def _statistical_evidence_safety(
    report_root: Path,
    *,
    selection: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    candidate = str(
        selection.get("selected_candidate") or selection.get("best_candidate") or ""
    )
    parameters = manifest.get("research_parameters", {})
    expected_symbol = (
        str(parameters.get("index_code") or "") if isinstance(parameters, dict) else ""
    )
    benchmark_payload = _read_json(report_root / "benchmark_report.json")
    multiple_payload = _read_json(report_root / "multiple_testing_report.json")
    trial_payload = _read_json(report_root / "trial_registry_review.json")
    benchmark = validate_benchmark_payload(
        benchmark_payload,
        expected_symbol=expected_symbol,
    )
    multiple = validate_multiple_testing_payload(
        multiple_payload,
        expected_candidate=candidate,
    )
    trial = validate_trial_registry_review_payload(
        trial_payload,
        expected_candidate=candidate,
        report_dir=report_root,
    )
    checks = (
        ("benchmark_report.json", benchmark),
        ("multiple_testing_report.json", multiple),
        ("trial_registry_review.json", trial),
    )
    passed = {
        filename: validation.valid and validation.status == "PASS"
        for filename, validation in checks
    }
    safe = all(passed.values())
    reasons = []
    for filename, validation in checks:
        if passed[filename]:
            continue
        detail = validation.reasons[0] if validation.reasons else f"status={validation.status}"
        reasons.append(f"{filename}: {detail}")
    return {
        "benchmark_evidence_pass": passed["benchmark_report.json"],
        "multiple_testing_evidence_pass": passed["multiple_testing_report.json"],
        "trial_registry_evidence_pass": passed["trial_registry_review.json"],
        "statistical_evidence_safe": safe,
        "statistical_evidence_status": "PASS" if safe else "UNSAFE",
        "statistical_evidence_reason": (
            "Benchmark, multiple-testing, and prospective trial evidence passed."
            if safe
            else "Excluded from promotion-eligible observations because " + "; ".join(reasons)
        ),
    }


def _is_csv_route(manifest: dict[str, Any], data_version: dict[str, Any]) -> bool:
    route_values = (
        manifest.get("data_source"),
        data_version.get("data_source"),
        data_version.get("last_import_source"),
    )
    return bool(str(data_version.get("csv_dataset_fingerprint", "") or "").strip()) or any(
        "csv" in str(value or "").strip().lower() for value in route_values
    )


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
