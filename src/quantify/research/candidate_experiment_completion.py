"""Completion gate for launched candidate research experiments."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal

CompletionDecision = Literal["PASS", "WATCH", "BLOCK"]
ArtifactStatus = Literal["PASS", "WATCH", "BLOCK", "MISSING", "UNKNOWN"]

PROHIBITED_ACTIONS = [
    "Do not promote a candidate while experiment completion is BLOCK.",
    "Do not ignore missing required outputs from the launch plan.",
    "Do not treat WATCH completion as paper or micro-live approval.",
    "Do not connect candidate completion artifacts to real broker order submission.",
    "Do not let LLM output upgrade deterministic completion status.",
]


@dataclass(frozen=True, slots=True)
class CandidateExperimentArtifactReview:
    name: str
    status: ArtifactStatus
    artifact: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status,
            "artifact": self.artifact,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class CandidateExperimentCompletionReview:
    decision: CompletionDecision
    as_of: str | None
    selected_candidate: str
    run_id: str
    experiment_dir: str
    launch_decision: str
    artifacts: list[CandidateExperimentArtifactReview]
    blockers: list[str]
    watch_items: list[str]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "as_of": self.as_of,
            "selected_candidate": self.selected_candidate,
            "run_id": self.run_id,
            "experiment_dir": self.experiment_dir,
            "launch_decision": self.launch_decision,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "blockers": self.blockers,
            "watch_items": self.watch_items,
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Candidate Experiment Completion: {self.decision}",
            "",
            f"- As of: `{self.as_of or 'unspecified'}`",
            f"- Candidate: `{self.selected_candidate or 'none'}`",
            f"- Run ID: `{self.run_id or 'none'}`",
            f"- Experiment directory: `{self.experiment_dir or 'none'}`",
            f"- Launch decision: `{self.launch_decision or 'unknown'}`",
            "",
            "This is a deterministic research-completion gate, not a profitability claim.",
            "",
            "## Required Artifacts",
            "",
            "| artifact | status | path | message |",
            "| --- | --- | --- | --- |",
        ]
        for artifact in self.artifacts:
            lines.append(
                f"| `{artifact.name}` | `{artifact.status}` | `{artifact.artifact}` | {artifact.message} |"
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


def build_candidate_experiment_completion(
    report_dir: str | Path,
    *,
    launch_path: str | Path | None = None,
    as_of: str | None = None,
) -> CandidateExperimentCompletionReview:
    root = Path(report_dir)
    launch_file = Path(launch_path) if launch_path else root / "candidate_experiment_launch.json"
    launch = _read_json(launch_file)
    if not launch:
        return _review(
            as_of=as_of,
            selected_candidate="",
            run_id="",
            experiment_dir="",
            launch_decision="MISSING",
            artifacts=[
                CandidateExperimentArtifactReview(
                    "candidate_experiment_launch",
                    "MISSING",
                    str(launch_file),
                    "candidate_experiment_launch.json is missing.",
                )
            ],
        )
    launch_decision = str(launch.get("decision", "UNKNOWN"))
    if launch_decision != "PASS":
        return _review(
            as_of=as_of or str(launch.get("as_of") or ""),
            selected_candidate=str(launch.get("selected_candidate") or ""),
            run_id=str(launch.get("run_id") or ""),
            experiment_dir=str(launch.get("experiment_dir") or ""),
            launch_decision=launch_decision,
            artifacts=[
                CandidateExperimentArtifactReview(
                    "candidate_experiment_launch",
                    _normalize_status(launch_decision),
                    str(launch_file),
                    "Launch plan is not PASS; experiment completion cannot be reviewed.",
                )
            ],
        )

    experiment_dir_text = str(launch.get("experiment_dir") or "").strip()
    experiment_dir = Path(experiment_dir_text)
    required_outputs = [str(item) for item in launch.get("required_outputs", []) or []]
    selected_candidate = str(launch.get("selected_candidate") or "")
    run_id = str(launch.get("run_id") or "")
    execution_artifact = root / "candidate_experiment_execution.json"
    artifacts = [
        _launch_contract_review(launch_file, launch),
        _execution_review(
            execution_artifact,
            selected_candidate=selected_candidate,
            run_id=run_id,
            experiment_dir=experiment_dir,
            experiment_dir_text=experiment_dir_text,
        )
    ]
    scope_artifacts = _required_output_scope_reviews(
        required_outputs,
        experiment_dir=experiment_dir,
        experiment_dir_text=experiment_dir_text,
    )
    if scope_artifacts:
        artifacts.extend(scope_artifacts)
        return _review(
            as_of=as_of or str(launch.get("as_of") or ""),
            selected_candidate=str(launch.get("selected_candidate") or ""),
            run_id=str(launch.get("run_id") or ""),
            experiment_dir=str(launch.get("experiment_dir") or ""),
            launch_decision=launch_decision,
            artifacts=artifacts,
        )
    artifacts.extend(
        _artifact_review(
            Path(path),
            name=Path(path).name,
            selected_candidate=selected_candidate,
        )
        for path in required_outputs
    )
    artifacts.append(
        _launch_contract_evidence_review(
            launch,
            experiment_dir=experiment_dir,
            selected_candidate=selected_candidate,
        )
    )
    if len(artifacts) == 1:
        artifacts = [
            artifacts[0],
            CandidateExperimentArtifactReview(
                "required_outputs",
                "BLOCK",
                str(launch_file),
                "Launch plan has no required_outputs.",
            )
        ]
    return _review(
        as_of=as_of or str(launch.get("as_of") or ""),
        selected_candidate=str(launch.get("selected_candidate") or ""),
        run_id=str(launch.get("run_id") or ""),
        experiment_dir=str(launch.get("experiment_dir") or ""),
        launch_decision=launch_decision,
        artifacts=artifacts,
    )


def _launch_contract_review(path: Path, payload: dict[str, Any]) -> CandidateExperimentArtifactReview:
    missing = _missing_launch_contract_fields(payload)
    if not missing:
        return CandidateExperimentArtifactReview(
            "launch_contract",
            "PASS",
            str(path),
            "Launch plan includes capital-goal, evidence-window, risk-budget, paper-entry, and anti-overfit controls.",
        )
    return CandidateExperimentArtifactReview(
        "launch_contract",
        "WATCH",
        str(path),
        "Launch plan is missing long-term experiment controls: " + ", ".join(missing) + ".",
    )


def _execution_review(
    path: Path,
    *,
    selected_candidate: str,
    run_id: str,
    experiment_dir: Path,
    experiment_dir_text: str,
) -> CandidateExperimentArtifactReview:
    if not path.exists():
        return CandidateExperimentArtifactReview(
            "candidate_experiment_execution",
            "MISSING",
            str(path),
            "candidate_experiment_execution.json is required before completion review.",
        )
    payload = _read_json(path)
    if not payload:
        return CandidateExperimentArtifactReview(
            "candidate_experiment_execution",
            "UNKNOWN",
            str(path),
            "candidate_experiment_execution.json is empty or cannot be parsed.",
        )
    identity_blocker = _execution_identity_blocker(
        payload,
        selected_candidate=selected_candidate,
        run_id=run_id,
        experiment_dir=experiment_dir,
        experiment_dir_text=experiment_dir_text,
    )
    if identity_blocker:
        return CandidateExperimentArtifactReview(
            "candidate_experiment_execution",
            "BLOCK",
            str(path),
            identity_blocker,
        )
    decision = str(payload.get("decision", "UNKNOWN")).upper()
    if decision == "PASS":
        status: ArtifactStatus = "PASS"
        message = f"Guarded executor ran all commands; steps={len(payload.get('steps', []) or [])}."
    elif decision == "DRY_RUN":
        status = "WATCH"
        message = f"Guarded executor only validated commands in dry-run; steps={len(payload.get('steps', []) or [])}."
    elif decision == "BLOCK":
        status = "BLOCK"
        blockers = payload.get("blockers", []) or []
        detail = str(blockers[0]) if blockers else "Guarded executor is BLOCK."
        message = detail
    else:
        status = "UNKNOWN"
        message = f"candidate_experiment_execution decision is {decision}."
    return CandidateExperimentArtifactReview(
        "candidate_experiment_execution",
        status,
        str(path),
        message,
    )


def write_candidate_experiment_completion(
    review: CandidateExperimentCompletionReview,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "candidate_experiment_completion.json").write_text(
        json.dumps(review.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "candidate_experiment_completion.md").write_text(review.to_markdown(), encoding="utf-8")
    return root


def _required_output_scope_reviews(
    required_outputs: list[str],
    *,
    experiment_dir: Path,
    experiment_dir_text: str,
) -> list[CandidateExperimentArtifactReview]:
    if not experiment_dir_text:
        return [
            CandidateExperimentArtifactReview(
                "experiment_dir",
                "BLOCK",
                str(experiment_dir),
                "Launch plan has empty experiment_dir.",
            )
        ]
    reviews = []
    for raw_path in required_outputs:
        path = Path(raw_path)
        if not _path_within(path, experiment_dir):
            reviews.append(
                CandidateExperimentArtifactReview(
                    Path(raw_path).name or "required_output",
                    "BLOCK",
                    raw_path,
                    "Required experiment output is outside launch experiment_dir.",
                )
            )
    return reviews


def _missing_launch_contract_fields(payload: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for key in [
        "capital_goal_fit_tests",
        "risk_budget_checks",
        "paper_entry_requirements",
        "anti_overfit_controls",
    ]:
        value = payload.get(key)
        if not isinstance(value, list) or not value:
            missing.append(key)
    window = payload.get("minimum_evidence_window")
    if not isinstance(window, dict) or not window:
        missing.append("minimum_evidence_window")
    else:
        for key in [
            "minimum_total_trading_days",
            "minimum_out_of_sample_trading_days",
            "minimum_walk_forward_windows",
            "sample_split_required",
        ]:
            if key not in window:
                missing.append(f"minimum_evidence_window.{key}")
    return missing


def _launch_contract_evidence_review(
    launch: dict[str, Any],
    *,
    experiment_dir: Path,
    selected_candidate: str,
) -> CandidateExperimentArtifactReview:
    blockers: list[str] = []
    watches: list[str] = []
    window = _dict_payload(launch.get("minimum_evidence_window"))
    evidence = _read_json(experiment_dir / "candidate_experiment_evidence.json")
    summary = _read_json(experiment_dir / "summary.json")
    run_manifest = _read_json(experiment_dir / "run_manifest.json")
    walk_forward = _read_json(experiment_dir / "candidate_walk_forward_report.json")
    regime = _read_json(experiment_dir / "candidate_regime_validation_report.json")
    selection = _read_json(experiment_dir / "candidate_selection.json")

    minimum_total_days = _int_value(window.get("minimum_total_trading_days"))
    if minimum_total_days:
        actual_total_days = _trading_day_count(run_manifest, summary, evidence)
        if actual_total_days <= 0:
            blockers.append(
                "run_manifest.json or summary.json is missing total trading-day evidence "
                f"for launch minimum {minimum_total_days}."
            )
        elif actual_total_days < minimum_total_days:
            blockers.append(
                "Total trading-day evidence="
                f"{actual_total_days} is below launch minimum {minimum_total_days}."
            )

    if window.get("sample_split_required") is True:
        split = _sample_split_evidence(run_manifest, summary, evidence)
        missing = [
            key
            for key, value in split.items()
            if key in {"in_sample_end", "out_sample_start"} and not value
        ]
        if missing:
            blockers.append(
                "Sample-split evidence is missing required fields: " + ", ".join(missing) + "."
            )
        minimum_out_days = _int_value(window.get("minimum_out_of_sample_trading_days"))
        if minimum_out_days:
            out_days = _out_of_sample_day_count(split, run_manifest, summary, walk_forward)
            if out_days <= 0:
                blockers.append(
                    "Out-of-sample trading-day evidence is missing for launch minimum "
                    f"{minimum_out_days}."
                )
            elif out_days < minimum_out_days:
                blockers.append(
                    "Out-of-sample trading-day evidence="
                    f"{out_days} is below launch minimum {minimum_out_days}."
                )

    minimum_windows = _int_value(window.get("minimum_walk_forward_windows"))
    if minimum_windows:
        actual_windows = _int_value(walk_forward.get("window_count"))
        if actual_windows < minimum_windows:
            blockers.append(
                "candidate_walk_forward_report.json window_count="
                f"{actual_windows} is below launch minimum {minimum_windows}."
            )
    if window.get("sample_split_required") is True:
        if not _has_selected_candidate_walk_forward(walk_forward, selected_candidate):
            blockers.append(
                "candidate_walk_forward_report.json does not expose selected-candidate "
                "walk-forward windows for sample-split review."
            )

    known_regimes = _int_value(regime.get("regime_count"))
    adverse_windows = _selected_adverse_regime_window_count(regime, selected_candidate)
    if known_regimes < 2:
        blockers.append(
            f"candidate_regime_validation_report.json regime_count={known_regimes} is below launch minimum 2."
        )
    if adverse_windows <= 0:
        watches.append(
            "candidate_regime_validation_report.json has no adverse-regime windows for the selected candidate."
        )

    capital_status = _selected_capital_goal_fit_status(selection, selected_candidate)
    if capital_status in {"", "UNKNOWN"}:
        blockers.append(
            "candidate_selection.json is missing selected-candidate capital_goal_fit_review evidence."
        )
    elif capital_status == "BLOCK":
        blockers.append(
            "candidate_selection.json selected candidate has BLOCK capital_goal_fit_review."
        )
    elif capital_status == "WATCH":
        watches.append(
            "candidate_selection.json selected candidate has WATCH capital_goal_fit_review."
        )

    tail_review = _selected_walk_forward_tail_review(
        walk_forward,
        selection,
        selected_candidate=selected_candidate,
    )
    blockers.extend(tail_review["blockers"])
    watches.extend(tail_review["watches"])

    if blockers:
        return CandidateExperimentArtifactReview(
            "launch_contract_evidence",
            "BLOCK",
            str(experiment_dir),
            " ".join(blockers),
        )
    if watches:
        return CandidateExperimentArtifactReview(
            "launch_contract_evidence",
            "WATCH",
            str(experiment_dir),
            " ".join(watches),
        )
    return CandidateExperimentArtifactReview(
        "launch_contract_evidence",
        "PASS",
        str(experiment_dir),
        "Experiment outputs satisfy launch minimum sample, walk-forward, regime, capital-goal, and tail-risk evidence.",
    )


def _artifact_review(
    path: Path,
    *,
    name: str,
    selected_candidate: str,
) -> CandidateExperimentArtifactReview:
    if not path.exists():
        return CandidateExperimentArtifactReview(
            name,
            "MISSING",
            str(path),
            "Required experiment output is missing.",
        )
    payload = _read_json(path)
    if not payload:
        return CandidateExperimentArtifactReview(
            name,
            "UNKNOWN",
            str(path),
            "Required experiment output is empty or cannot be parsed.",
        )
    status = _payload_status(path.name, payload)
    message = _message(path.name, payload, status)
    identity_blocker = _candidate_identity_blocker(
        path.name,
        payload,
        selected_candidate=selected_candidate,
    )
    if identity_blocker:
        message = f"{identity_blocker} Original artifact status was {status}."
        status = "BLOCK"
    return CandidateExperimentArtifactReview(name, status, str(path), message)


def _payload_status(filename: str, payload: dict[str, Any]) -> ArtifactStatus:
    if filename == "llm_review.json":
        return _normalize_status(payload.get("decision"))
    if filename == "candidate_stress_matrix.json":
        return _normalize_status(payload.get("stress_status", payload.get("status", "UNKNOWN")))
    return _normalize_status(payload.get("status", payload.get("decision", "UNKNOWN")))


def _message(filename: str, payload: dict[str, Any], status: ArtifactStatus) -> str:
    if filename == "candidate_experiment_evidence.json":
        blockers = len(payload.get("blockers", []) or [])
        watches = len(payload.get("watch_items", []) or [])
        return f"Candidate experiment evidence is {status}; blockers={blockers}, watch_items={watches}."
    if filename == "candidate_walk_forward_report.json":
        best = payload.get("best_candidate", "none")
        windows = payload.get("window_count", "unknown")
        return f"Candidate walk-forward is {status}; best={best or 'none'}, windows={windows}."
    if filename == "candidate_factor_diagnostics.json":
        candidates = payload.get("candidate_count", "unknown")
        warnings = len(payload.get("warnings", []) or [])
        return f"Candidate factor diagnostics is {status}; candidates={candidates}, warnings={warnings}."
    if filename == "candidate_regime_validation_report.json":
        best = payload.get("best_candidate", "none")
        regimes = payload.get("regime_count", "unknown")
        return f"Candidate regime validation is {status}; best={best or 'none'}, regimes={regimes}."
    if filename == "candidate_stress_matrix.json":
        scenarios = payload.get("scenario_count", "unknown")
        return f"Candidate stress matrix is {status}; scenarios={scenarios}."
    if filename == "candidate_selection.json":
        selected = payload.get("selected_candidate") or payload.get("best_candidate") or "none"
        top = payload.get("top_candidate") or selected
        return f"Candidate selection is {status}; selected={selected or 'none'}, top={top or 'none'}."
    if filename == "llm_review.json":
        missing = len(payload.get("missing_evidence", []) or [])
        return f"LLM deterministic review is {status}; missing_evidence={missing}."
    return f"{filename} status is {status}."


def _candidate_identity_blocker(
    filename: str,
    payload: dict[str, Any],
    *,
    selected_candidate: str,
) -> str:
    if filename not in _candidate_identity_files():
        return ""
    selected = selected_candidate.strip()
    if not selected:
        return "Launch selected_candidate is missing; candidate-specific artifact cannot be verified."

    refs = _candidate_identity_refs(filename, payload)
    count = _candidate_count(payload)
    if count > 1:
        return (
            "Candidate identity mismatch: launch selected_candidate="
            f"{selected}; artifact candidate_count={count}, expected 1 for a selected-only launch."
        )
    if not refs:
        return (
            f"Candidate identity missing: {filename} does not expose a candidate field "
            f"for launch selected_candidate={selected}."
        )
    mismatches = [(location, value) for location, value in refs if value != selected]
    if not mismatches:
        return ""
    details = "; ".join(
        f"{location}={value or 'none'}"
        for location, value in mismatches[:5]
    )
    if len(mismatches) > 5:
        details += f"; and {len(mismatches) - 5} more"
    return (
        f"Candidate identity mismatch: launch selected_candidate={selected}; "
        f"artifact has {details}."
    )


def _execution_identity_blocker(
    payload: dict[str, Any],
    *,
    selected_candidate: str,
    run_id: str,
    experiment_dir: Path,
    experiment_dir_text: str,
) -> str:
    checks = [
        ("selected_candidate", selected_candidate, _identity_value(payload.get("selected_candidate"))),
        ("run_id", run_id, _identity_value(payload.get("run_id"))),
    ]
    mismatches = []
    for field, expected, actual in checks:
        if not expected:
            mismatches.append(f"launch {field}=missing")
            continue
        if not actual:
            mismatches.append(f"{field}=missing, expected {expected}")
        elif actual != expected:
            mismatches.append(f"{field}={actual}, expected {expected}")

    actual_experiment_dir = _identity_value(payload.get("experiment_dir"))
    if experiment_dir_text:
        if not actual_experiment_dir:
            mismatches.append(f"experiment_dir=missing, expected {experiment_dir_text}")
        elif not _same_path(Path(actual_experiment_dir), experiment_dir):
            mismatches.append(f"experiment_dir={actual_experiment_dir}, expected {experiment_dir_text}")
    if not mismatches:
        return ""
    return "Execution identity mismatch: " + "; ".join(mismatches) + "."


def _candidate_identity_files() -> set[str]:
    return {
        "candidate_walk_forward_report.json",
        "candidate_factor_diagnostics.json",
        "candidate_regime_validation_report.json",
        "candidate_stress_matrix.json",
        "candidate_selection.json",
    }


def _candidate_identity_refs(filename: str, payload: dict[str, Any]) -> list[tuple[str, str]]:
    if filename == "candidate_selection.json":
        return [
            *_top_level_refs(payload, "selected_candidate", "best_candidate", "top_candidate"),
            *_list_refs(payload, "results", "name"),
        ]
    if filename == "candidate_walk_forward_report.json":
        return [
            *_top_level_refs(payload, "best_candidate"),
            *_list_refs(payload, "summaries", "candidate"),
            *_list_refs(payload, "windows", "candidate"),
        ]
    if filename == "candidate_factor_diagnostics.json":
        return _list_refs(payload, "diagnostics", "candidate")
    if filename == "candidate_regime_validation_report.json":
        return [
            *_top_level_refs(payload, "best_candidate"),
            *_list_refs(payload, "summaries", "candidate"),
            *_list_refs(payload, "buckets", "candidate"),
            *_list_refs(payload, "windows", "candidate"),
        ]
    if filename == "candidate_stress_matrix.json":
        return [
            *_list_refs(payload, "summaries", "candidate"),
            *_list_refs(payload, "results", "candidate"),
        ]
    return []


def _top_level_refs(payload: dict[str, Any], *keys: str) -> list[tuple[str, str]]:
    refs = []
    for key in keys:
        value = _identity_value(payload.get(key))
        if value:
            refs.append((key, value))
    return refs


def _list_refs(payload: dict[str, Any], list_key: str, field: str) -> list[tuple[str, str]]:
    rows = payload.get(list_key, []) or []
    if not isinstance(rows, list):
        return []
    refs = []
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            continue
        value = _identity_value(item.get(field))
        if value:
            refs.append((f"{list_key}[{index}].{field}", value))
    return refs


def _identity_value(value: object) -> str:
    return str(value or "").strip()


def _trading_day_count(
    run_manifest: dict[str, Any],
    summary: dict[str, Any],
    evidence: dict[str, Any],
) -> int:
    for payload in (run_manifest, summary):
        value = _int_value(payload.get("trading_day_count"))
        if value:
            return value
    value = _int_value(summary.get("n_bars"))
    if value:
        return value
    copied_summary = _copied_payload(evidence, "summary")
    if copied_summary:
        return _trading_day_count({}, copied_summary, {})
    copied_manifest = _copied_payload(evidence, "run_manifest")
    if copied_manifest:
        return _trading_day_count(copied_manifest, {}, {})
    return 0


def _sample_split_evidence(
    run_manifest: dict[str, Any],
    summary: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    assumptions = _dict_payload(summary.get("assumptions"))
    split: dict[str, Any] = {
        "in_sample_end": run_manifest.get("in_sample_end") or assumptions.get("in_sample_end") or "",
        "out_sample_start": (
            run_manifest.get("out_sample_start") or assumptions.get("out_sample_start") or ""
        ),
        "out_of_sample_trading_day_count": (
            run_manifest.get("out_of_sample_trading_day_count")
            or assumptions.get("out_of_sample_trading_day_count")
            or summary.get("out_of_sample_trading_day_count")
            or summary.get("out_sample_trading_day_count")
            or 0
        ),
    }
    copied_summary = _copied_payload(evidence, "summary")
    if copied_summary:
        copied = _sample_split_evidence({}, copied_summary, {})
        for key, value in copied.items():
            split[key] = split.get(key) or value
    copied_manifest = _copied_payload(evidence, "run_manifest")
    if copied_manifest:
        copied = _sample_split_evidence(copied_manifest, {}, {})
        for key, value in copied.items():
            split[key] = split.get(key) or value
    return split


def _out_of_sample_day_count(
    split: dict[str, Any],
    run_manifest: dict[str, Any],
    summary: dict[str, Any],
    walk_forward: dict[str, Any],
) -> int:
    explicit = _int_value(split.get("out_of_sample_trading_day_count"))
    if explicit:
        return explicit
    explicit = _int_value(summary.get("out_of_sample_trading_day_count"))
    if explicit:
        return explicit
    explicit = _int_value(run_manifest.get("out_of_sample_trading_day_count"))
    if explicit:
        return explicit
    window_days = _walk_forward_out_of_sample_days(walk_forward)
    if window_days:
        return window_days
    return 0


def _walk_forward_out_of_sample_days(payload: dict[str, Any]) -> int:
    windows = payload.get("windows", []) or []
    if not isinstance(windows, list):
        return 0
    total = 0
    for item in windows:
        if not isinstance(item, dict):
            continue
        explicit = _int_value(
            item.get("trading_day_count")
            or item.get("test_trading_days")
            or item.get("out_of_sample_trading_days")
        )
        if explicit:
            total += explicit
    return total


def _copied_payload(evidence: dict[str, Any], name: str) -> dict[str, Any]:
    copied = evidence.get("copied_artifacts", []) if isinstance(evidence, dict) else []
    if not isinstance(copied, list):
        return {}
    for item in copied:
        if not isinstance(item, dict) or item.get("name") != name:
            continue
        destination = str(item.get("destination") or "")
        if destination:
            return _read_json(Path(destination))
    return {}


def _selected_walk_forward_tail_review(
    walk_forward: dict[str, Any],
    selection: dict[str, Any],
    *,
    selected_candidate: str,
) -> dict[str, list[str]]:
    blockers: list[str] = []
    watches: list[str] = []
    summary = _selected_summary(walk_forward, selected_candidate)
    if not summary:
        blockers.append(
            "candidate_walk_forward_report.json is missing selected-candidate summary "
            "for tail-risk review."
        )
        return {"blockers": blockers, "watches": watches}
    capital = _selected_capital_goal_fit_review(selection, selected_candidate)
    missing_metrics = [
        key
        for key in ("positive_return_ratio", "worst_total_return", "worst_max_drawdown")
        if key not in summary
    ]
    if missing_metrics:
        blockers.append(
            "candidate_walk_forward_report.json selected-candidate summary is missing tail metrics: "
            + ", ".join(missing_metrics)
            + "."
        )
    drawdown_budget = _float_value(capital.get("drawdown_budget"))
    if not drawdown_budget:
        blockers.append(
            "candidate_selection.json selected-candidate capital_goal_fit_review is missing drawdown_budget."
        )
    worst_drawdown = _float_value(summary.get("worst_max_drawdown"))
    worst_return = _float_value(summary.get("worst_total_return"))
    positive_ratio = _float_value(summary.get("positive_return_ratio"))
    pass_ratio = _pass_ratio(summary)

    if drawdown_budget and worst_drawdown > drawdown_budget:
        blockers.append(
            "candidate_walk_forward_report.json worst_max_drawdown="
            f"{worst_drawdown:.2%} exceeds drawdown budget {drawdown_budget:.2%}."
        )
    elif drawdown_budget and worst_drawdown > drawdown_budget * 0.75:
        watches.append(
            "candidate_walk_forward_report.json worst_max_drawdown="
            f"{worst_drawdown:.2%} is close to drawdown budget {drawdown_budget:.2%}."
        )

    if worst_return <= -0.10:
        blockers.append(
            "candidate_walk_forward_report.json worst_total_return="
            f"{worst_return:.2%} breaches the -10% tail-loss block threshold."
        )
    elif worst_return <= -0.05:
        watches.append(
            "candidate_walk_forward_report.json worst_total_return="
            f"{worst_return:.2%} breaches the -5% tail-loss watch threshold."
        )

    if "positive_return_ratio" in summary and positive_ratio < 0.60:
        watches.append(
            "candidate_walk_forward_report.json positive_return_ratio="
            f"{positive_ratio:.2%} is below the 60% stability watch threshold."
        )
    if _int_value(summary.get("window_count")) > 0 and pass_ratio < 0.60:
        watches.append(
            "candidate_walk_forward_report.json PASS window ratio="
            f"{pass_ratio:.2%} is below the 60% stability watch threshold."
        )
    return {"blockers": blockers, "watches": watches}


def _selected_summary(payload: dict[str, Any], selected_candidate: str) -> dict[str, Any]:
    selected = selected_candidate.strip()
    summaries = payload.get("summaries", []) or []
    if isinstance(summaries, list):
        for item in summaries:
            if isinstance(item, dict) and str(item.get("candidate") or "").strip() == selected:
                return item
    if str(payload.get("best_candidate") or "").strip() == selected:
        return {
            "candidate": selected,
            "window_count": payload.get("window_count"),
            "pass_count": payload.get("pass_count"),
            "positive_return_ratio": payload.get("positive_return_ratio"),
            "worst_total_return": payload.get("worst_total_return"),
            "worst_max_drawdown": payload.get("worst_max_drawdown"),
        }
    return {}


def _selected_capital_goal_fit_review(
    payload: dict[str, Any],
    selected_candidate: str,
) -> dict[str, Any]:
    selected = selected_candidate.strip()
    results = payload.get("results", []) or []
    if isinstance(results, list):
        for item in results:
            if not isinstance(item, dict):
                continue
            if str(item.get("name") or "").strip() != selected:
                continue
            return _dict_payload(item.get("capital_goal_fit_review"))
    if str(payload.get("selected_candidate") or payload.get("best_candidate") or "").strip() == selected:
        return _dict_payload(payload.get("capital_goal_fit_review"))
    return {}


def _pass_ratio(summary: dict[str, Any]) -> float:
    window_count = _int_value(summary.get("window_count"))
    pass_count = _int_value(summary.get("pass_count"))
    if window_count <= 0:
        return 0.0
    return pass_count / window_count


def _float_value(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _candidate_count(payload: dict[str, Any]) -> int:
    try:
        return int(payload.get("candidate_count") or 0)
    except (TypeError, ValueError):
        return 0


def _has_selected_candidate_walk_forward(payload: dict[str, Any], selected_candidate: str) -> bool:
    selected = selected_candidate.strip()
    if not selected:
        return False
    if str(payload.get("best_candidate") or "").strip() == selected:
        return True
    return any(value == selected for _location, value in _candidate_identity_refs("candidate_walk_forward_report.json", payload))


def _selected_adverse_regime_window_count(payload: dict[str, Any], selected_candidate: str) -> int:
    selected = selected_candidate.strip()
    summaries = payload.get("summaries", []) or []
    if isinstance(summaries, list):
        for item in summaries:
            if not isinstance(item, dict):
                continue
            if str(item.get("candidate") or "").strip() == selected:
                return _int_value(item.get("adverse_regime_window_count"))
    return _int_value(payload.get("adverse_regime_window_count"))


def _selected_capital_goal_fit_status(payload: dict[str, Any], selected_candidate: str) -> str:
    selected = selected_candidate.strip()
    results = payload.get("results", []) or []
    if isinstance(results, list):
        for item in results:
            if not isinstance(item, dict):
                continue
            if str(item.get("name") or "").strip() != selected:
                continue
            return _capital_goal_fit_status(item)
    if str(payload.get("selected_candidate") or payload.get("best_candidate") or "").strip() == selected:
        return _capital_goal_fit_status(payload)
    return ""


def _capital_goal_fit_status(payload: dict[str, Any]) -> str:
    direct = str(payload.get("capital_goal_fit_status") or "").upper()
    if direct in {"PASS", "WATCH", "BLOCK"}:
        return direct
    review = _dict_payload(payload.get("capital_goal_fit_review"))
    nested = str(review.get("status") or "").upper()
    if nested in {"PASS", "WATCH", "BLOCK"}:
        return nested
    return "UNKNOWN"


def _int_value(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _review(
    *,
    as_of: str | None,
    selected_candidate: str,
    run_id: str,
    experiment_dir: str,
    launch_decision: str,
    artifacts: list[CandidateExperimentArtifactReview],
) -> CandidateExperimentCompletionReview:
    blockers = [
        f"{artifact.name}: {artifact.message}"
        for artifact in artifacts
        if artifact.status in {"BLOCK", "MISSING", "UNKNOWN"}
    ]
    watch_items = [
        f"{artifact.name}: {artifact.message}"
        for artifact in artifacts
        if artifact.status == "WATCH"
    ]
    decision = _decision(artifacts)
    return CandidateExperimentCompletionReview(
        decision=decision,
        as_of=as_of,
        selected_candidate=selected_candidate,
        run_id=run_id,
        experiment_dir=experiment_dir,
        launch_decision=launch_decision,
        artifacts=artifacts,
        blockers=blockers,
        watch_items=watch_items,
        next_actions=_next_actions(decision),
        prohibited_actions=PROHIBITED_ACTIONS,
    )


def _decision(artifacts: list[CandidateExperimentArtifactReview]) -> CompletionDecision:
    statuses = [artifact.status for artifact in artifacts]
    if any(status in {"BLOCK", "MISSING", "UNKNOWN"} for status in statuses):
        return "BLOCK"
    if any(status == "WATCH" for status in statuses):
        return "WATCH"
    return "PASS"


def _next_actions(decision: CompletionDecision) -> list[str]:
    if decision == "BLOCK":
        return [
            "Run or repair every missing/BLOCK experiment output from the launch plan.",
            "Do not generate paper orders or promotion evidence from an incomplete experiment.",
            "Rerun candidate experiment completion after the artifacts are present.",
        ]
    if decision == "WATCH":
        return [
            "Review WATCH artifacts manually before paper-stage planning.",
            "Keep the candidate in research-only mode until WATCH items are explained.",
        ]
    return [
        "Archive the experiment directory and use it as the evidence source for paper candidate planning.",
        "Continue to paper only through deterministic gates and human approval.",
    ]


def _normalize_status(value: object) -> ArtifactStatus:
    text = str(value or "").upper()
    if text in {"PASS", "WATCH", "BLOCK"}:
        return text  # type: ignore[return-value]
    return "UNKNOWN"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _dict_payload(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _path_within(path: Path, parent: Path) -> bool:
    resolved_path = _resolved(path)
    resolved_parent = _resolved(parent)
    return resolved_path == resolved_parent or resolved_parent in resolved_path.parents


def _same_path(left: Path, right: Path) -> bool:
    return _resolved(left) == _resolved(right)


def _resolved(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except OSError:
        return path.absolute()
