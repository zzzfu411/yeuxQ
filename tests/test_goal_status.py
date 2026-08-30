from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pandas as pd

from quantify.data.storage import BarStorage
from quantify.goal import CapitalGoal, build_capital_goal_status, write_capital_goal_status
from quantify.goal.status import GoalEvidenceItem, _next_actions
from quantify.utils.config import Config
from tests.selection_safe_fixtures import (
    selection_safe_robustness_payload,
    selection_safe_walk_forward_payload,
)
from tests.statistical_evidence_fixtures import write_statistical_evidence_fixtures


def test_metadata_only_cache_block_suppresses_stale_acquisition_and_template_actions() -> None:
    evidence = [
        GoalEvidenceItem(
            "data_cache",
            "BLOCK",
            "current.db",
            "cache exists with 300 symbols. Cache metadata blocker: source QA is NOT_EVALUATED.",
        ),
        GoalEvidenceItem(
            "data_evidence_action_packet",
            "BLOCK",
            "data_evidence_action_packet.json",
            "source_qa_answers is missing.",
        ),
        GoalEvidenceItem(
            "recent_data_acquisition",
            "BLOCK",
            "recent_data_acquisition_plan.json",
            "An older provider attempt created no cache.",
        ),
        GoalEvidenceItem(
            "csv_validation",
            "BLOCK",
            "csv_validation.json",
            "Template CSV has only two symbols.",
        ),
        GoalEvidenceItem(
            "offline_source_qa_preflight",
            "BLOCK",
            "source_qa_preflight.json",
            "Real source QA answers are missing.",
        ),
    ]

    actions = _next_actions(evidence)

    assert actions[0].startswith("Follow data evidence action packet first")
    assert any("source QA preflight" in action for action in actions)
    assert any("guarded offline intake" in action for action in actions)
    assert not any("recent data acquisition" in action for action in actions)
    assert not any("CSV validation" in action for action in actions)


def test_capital_goal_status_blocks_missing_real_and_paper_evidence(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "run_manifest.json",
        {
            "demo_data_used": True,
            "latest_bar_date": "2021-12-31",
            "data_version": {},
        },
    )
    _write_json(tmp_path / "candidate_selection.json", {"status": "WATCH", "best_candidate": ""})

    status = build_capital_goal_status(tmp_path, goal=_goal())
    out = write_capital_goal_status(status, tmp_path)

    assert status.decision == "BLOCK"
    assert any("real_data_bootstrap" in blocker for blocker in status.blockers)
    assert any("human_approval" in blocker for blocker in status.blockers)
    assert (out / "capital_goal_status.json").exists()


def test_capital_goal_status_watches_goal_return_gap(tmp_path: Path) -> None:
    _write_core_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "candidate_selection.json",
        {
            "status": "PASS",
            "best_candidate": "core_multifactor",
            "results": [
                {
                    "name": "core_multifactor",
                    "metrics": {"annualized_return": 0.10},
                }
            ],
        },
    )
    write_statistical_evidence_fixtures(tmp_path)
    status = build_capital_goal_status(tmp_path, goal=_goal())

    assert status.decision == "WATCH"
    candidate = next(item for item in status.evidence if item.name == "candidate_selection")
    assert candidate.status == "WATCH"


def test_capital_goal_status_blocks_tampered_trial_candidate(tmp_path: Path) -> None:
    _write_core_pass_artifacts(tmp_path)
    _write_candidate_selection_pass(tmp_path)
    payload = json.loads((tmp_path / "trial_registry_review.json").read_text(encoding="utf-8"))
    payload["selected_candidate"] = "defensive_low_vol"
    _write_json(tmp_path / "trial_registry_review.json", payload)

    status = build_capital_goal_status(tmp_path, goal=_goal())

    trial_review = next(item for item in status.evidence if item.name == "trial_registry_review")
    assert status.decision == "BLOCK"
    assert trial_review.status == "BLOCK"
    assert "does not match deterministic candidate selection" in trial_review.message
    assert any("trial registry review" in action for action in status.next_actions)


def test_capital_goal_status_blocks_when_only_top_candidate_exists(tmp_path: Path) -> None:
    _write_core_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "candidate_selection.json",
        {
            "status": "BLOCK",
            "selected_candidate": "",
            "best_candidate": "",
            "top_candidate": "low_vol_test",
            "results": [{"name": "low_vol_test", "metrics": {"annualized_return": 0.40}}],
        },
    )

    status = build_capital_goal_status(tmp_path, goal=_goal())

    candidate = next(item for item in status.evidence if item.name == "candidate_selection")
    assert status.decision == "BLOCK"
    assert candidate.status == "BLOCK"
    assert "Selected=none, top=low_vol_test" in candidate.message


def test_capital_goal_status_blocks_missing_candidate_completion(tmp_path: Path) -> None:
    _write_core_pass_artifacts(tmp_path)
    (tmp_path / "candidate_experiment_completion.json").unlink()
    _write_json(
        tmp_path / "candidate_selection.json",
        {
            "status": "PASS",
            "best_candidate": "core_multifactor",
            "results": [{"name": "core_multifactor", "metrics": {"annualized_return": 0.40}}],
        },
    )

    status = build_capital_goal_status(tmp_path, goal=_goal())

    completion = next(
        item for item in status.evidence if item.name == "candidate_experiment_completion"
    )
    assert status.decision == "BLOCK"
    assert completion.status == "BLOCK"
    assert "Missing candidate experiment completion" in completion.message
    assert any(
        "Complete every required candidate experiment output" in action
        for action in status.next_actions
    )


def test_capital_goal_status_watches_candidate_completion_watch(tmp_path: Path) -> None:
    _write_core_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "candidate_experiment_completion.json",
        {
            "decision": "WATCH",
            "selected_candidate": "core_multifactor",
            "watch_items": ["llm_review.json: missing evidence"],
        },
    )
    _write_json(
        tmp_path / "candidate_selection.json",
        {
            "status": "PASS",
            "best_candidate": "core_multifactor",
            "results": [{"name": "core_multifactor", "metrics": {"annualized_return": 0.40}}],
        },
    )
    write_statistical_evidence_fixtures(tmp_path)

    status = build_capital_goal_status(tmp_path, goal=_goal())

    completion = next(
        item for item in status.evidence if item.name == "candidate_experiment_completion"
    )
    assert status.decision == "WATCH"
    assert completion.status == "WATCH"
    assert "llm_review.json" in completion.message


def test_capital_goal_status_blocks_empty_recent_cache_from_config(tmp_path: Path) -> None:
    cache = tmp_path / "recent.db"
    BarStorage(cache)
    _write_core_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "candidate_selection.json",
        {
            "status": "PASS",
            "best_candidate": "core_multifactor",
            "results": [{"name": "core_multifactor", "metrics": {"annualized_return": 0.40}}],
        },
    )

    status = build_capital_goal_status(
        tmp_path,
        goal=_goal(),
        cfg=_cfg(cache),
        as_of="2026-06-08",
        min_symbols=300,
        min_trading_days=240,
    )

    data_cache = next(item for item in status.evidence if item.name == "data_cache")
    assert status.decision == "BLOCK"
    assert data_cache.status == "BLOCK"
    assert "symbols=0" in data_cache.message
    assert status.next_actions[0].startswith("Import recent real A-share data")


def test_capital_goal_status_includes_recent_acquisition_and_csv_validation_blockers(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "recent.db"
    BarStorage(cache)
    _write_core_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "recent_data_acquisition_plan.json",
        {
            "status": "BLOCK",
            "current_symbol_count": 0,
            "current_latest_bar_date": "",
            "latest_import_attempt": {
                "network_blocked": True,
                "actual_bar_end": "",
            },
            "blockers": ["Current cache is not ready for recent A-share research evidence."],
        },
    )
    _write_json(
        tmp_path / "csv_validation.json",
        {
            "status": "BLOCK",
            "metrics": {
                "bars_end": "2024-01-03",
                "bars_end_lag_days": 884,
                "bars_symbol_count": 2,
            },
            "findings": [
                {
                    "severity": "BLOCK",
                    "code": "BARS_END_BEFORE_EXPECTED",
                    "message": "bars.csv ends before the requested research end date.",
                }
            ],
        },
    )
    _write_json(
        tmp_path / "candidate_selection.json",
        {
            "status": "PASS",
            "best_candidate": "core_multifactor",
            "results": [{"name": "core_multifactor", "metrics": {"annualized_return": 0.40}}],
        },
    )

    status = build_capital_goal_status(
        tmp_path,
        goal=_goal(),
        cfg=_cfg(cache),
        as_of="2026-06-09",
        min_symbols=300,
        min_trading_days=240,
    )

    acquisition = next(item for item in status.evidence if item.name == "recent_data_acquisition")
    csv_validation = next(item for item in status.evidence if item.name == "csv_validation")
    assert status.decision == "BLOCK"
    assert acquisition.status == "BLOCK"
    assert "network/proxy blocked" in acquisition.message
    assert csv_validation.status == "BLOCK"
    assert "BARS_END_BEFORE_EXPECTED" in csv_validation.message
    assert any("Fix CSV validation blocker" in action for action in status.next_actions)


def test_capital_goal_status_closes_strategy_search_when_data_gates_block(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "recent.db"
    BarStorage(cache)
    _write_core_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "recent_data_acquisition_plan.json",
        {
            "status": "BLOCK",
            "current_symbol_count": 0,
            "current_latest_bar_date": "",
            "latest_import_attempt": {"network_blocked": True, "actual_bar_end": ""},
            "blockers": ["Current cache is not ready for recent A-share research evidence."],
        },
    )
    _write_json(
        tmp_path / "candidate_selection.json",
        {
            "status": "PASS",
            "best_candidate": "core_multifactor",
            "results": [{"name": "core_multifactor", "metrics": {"annualized_return": 0.40}}],
        },
    )

    status = build_capital_goal_status(
        tmp_path,
        goal=_goal(),
        cfg=_cfg(cache),
        as_of="2026-06-09",
        min_symbols=300,
        min_trading_days=240,
    )
    out = write_capital_goal_status(status, tmp_path)
    payload = json.loads((out / "capital_goal_status.json").read_text(encoding="utf-8"))
    markdown = (out / "capital_goal_status.md").read_text(encoding="utf-8")

    gate = next(item for item in status.evidence if item.name == "strategy_search_gate")
    assert status.decision == "BLOCK"
    assert gate.status == "BLOCK"
    assert "Do not enter strategy search" in gate.message
    assert "strategy_search_gate" in payload["blockers"][-1]
    assert any("Do not start strategy search" in action for action in payload["prohibited_actions"])
    assert "profit-claim wording" in markdown


def test_capital_goal_status_includes_data_evidence_packet_blocker(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "recent.db"
    storage = BarStorage(cache)
    _seed_real_like_cache(storage, symbols=2, start="2024-01-02", periods=2)
    _write_core_pass_artifacts(tmp_path)
    _write_candidate_selection_pass(tmp_path)
    _write_json(
        tmp_path / "data_gap_action_plan.json",
        {"decision": "BLOCK", "items": []},
    )
    _write_json(
        tmp_path / "data_evidence_action_packet.json",
        {
            "decision": "BLOCK",
            "current_blockers": [
                {
                    "name": "source_qa_answers",
                    "status": "BLOCK",
                    "message": "data_source_qa_answers.json is missing or empty.",
                    "next_action": "Fill source QA answers from real vendor evidence.",
                }
            ],
            "watch_items": [],
            "immediate_commands": ["run source qa"],
            "source_qa_evidence_to_fill": [
                {"id": "license_scope"},
                {"id": "price_adjustment"},
            ],
        },
    )

    status = build_capital_goal_status(
        tmp_path,
        goal=_goal(),
        cfg=_cfg_window(cache, start="2024-01-02", end="2024-01-03"),
        as_of="2024-01-03",
        min_symbols=2,
        min_trading_days=2,
    )

    packet = next(item for item in status.evidence if item.name == "data_evidence_action_packet")
    strategy_gate = next(item for item in status.evidence if item.name == "strategy_search_gate")
    assert status.decision == "BLOCK"
    assert packet.status == "BLOCK"
    assert "source_qa_answers" in packet.message
    assert strategy_gate.status == "BLOCK"
    assert "data_evidence_action_packet" in strategy_gate.message
    assert status.next_actions[0].startswith("Follow data evidence action packet first")


def test_capital_goal_status_includes_operator_handoff_status_blocker(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "recent.db"
    storage = BarStorage(cache)
    _seed_real_like_cache(storage, symbols=2, start="2024-01-02", periods=2)
    _write_core_pass_artifacts(tmp_path)
    _write_candidate_selection_pass(tmp_path)
    _write_json(
        tmp_path / "operator_handoff_status.json",
        {
            "status": "BLOCK",
            "open_task_count": 17,
            "p0_open_task_count": 17,
            "source_qa_open_task_count": 11,
            "data_export_open_task_count": 6,
        },
    )

    status = build_capital_goal_status(
        tmp_path,
        goal=_goal(),
        cfg=_cfg_window(cache, start="2024-01-02", end="2024-01-03"),
        as_of="2024-01-03",
        min_symbols=2,
        min_trading_days=2,
    )

    handoff = next(item for item in status.evidence if item.name == "operator_handoff_status")
    strategy_gate = next(item for item in status.evidence if item.name == "strategy_search_gate")
    assert status.decision == "BLOCK"
    assert handoff.status == "BLOCK"
    assert "17 open tasks" in handoff.message
    assert "source_qa=11" in handoff.message
    assert strategy_gate.status == "BLOCK"
    assert "operator_handoff_status" in strategy_gate.message
    assert status.next_actions[0].startswith("Close operator handoff P0 tasks first")


def test_capital_goal_status_includes_csv_intake_preview_blocker(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "recent.db"
    storage = BarStorage(cache)
    _seed_real_like_cache(storage, symbols=2, start="2024-01-02", periods=2)
    _write_core_pass_artifacts(tmp_path)
    _write_candidate_selection_pass(tmp_path)
    _write_json(
        tmp_path / "csv_intake_preview.json",
        {
            "status": "BLOCK",
            "items": [
                {
                    "role": "bars",
                    "file_name": "bars.csv",
                    "status": "BLOCK",
                    "message": "Required columns could not be mapped into the research schema.",
                    "missing_columns": ["close"],
                }
            ],
        },
    )

    status = build_capital_goal_status(
        tmp_path,
        goal=_goal(),
        cfg=_cfg_window(cache, start="2024-01-02", end="2024-01-03"),
        as_of="2024-01-03",
        min_symbols=2,
        min_trading_days=2,
    )

    preview = next(item for item in status.evidence if item.name == "csv_intake_preview")
    strategy_gate = next(item for item in status.evidence if item.name == "strategy_search_gate")
    assert status.decision == "BLOCK"
    assert preview.status == "BLOCK"
    assert "bars.csv" in preview.message
    assert "close" in preview.message
    assert strategy_gate.status == "BLOCK"
    assert "csv_intake_preview" in strategy_gate.message
    assert status.next_actions[0].startswith("Fix csv_intake_preview.md")


def test_capital_goal_status_blocks_run_manifest_without_csv_fingerprint(
    tmp_path: Path,
) -> None:
    _write_core_pass_artifacts(tmp_path)
    _write_candidate_selection_pass(tmp_path)
    _write_json(
        tmp_path / "run_manifest.json",
        {
            "demo_data_used": False,
            "latest_bar_date": "2026-06-05",
            "data_version": {},
        },
    )

    status = build_capital_goal_status(tmp_path, goal=_goal())

    manifest = next(item for item in status.evidence if item.name == "run_manifest")
    strategy_gate = next(item for item in status.evidence if item.name == "strategy_search_gate")
    assert status.decision == "BLOCK"
    assert manifest.status == "BLOCK"
    assert "no CSV dataset fingerprint" in manifest.message
    assert strategy_gate.status == "BLOCK"


def test_capital_goal_status_blocks_current_cache_without_csv_fingerprint(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "recent.db"
    storage = BarStorage(cache)
    _seed_real_like_cache(storage, symbols=2, start="2024-01-02", periods=2, with_metadata=False)
    _write_core_pass_artifacts(tmp_path)
    _write_candidate_selection_pass(tmp_path)

    status = build_capital_goal_status(
        tmp_path,
        goal=_goal(),
        cfg=_cfg_window(cache, start="2024-01-02", end="2024-01-03"),
        as_of="2024-01-03",
        min_symbols=2,
        min_trading_days=2,
    )

    data_cache = next(item for item in status.evidence if item.name == "data_cache")
    strategy_gate = next(item for item in status.evidence if item.name == "strategy_search_gate")
    assert status.decision == "BLOCK"
    assert data_cache.status == "BLOCK"
    assert "Missing csv_dataset_fingerprint" in data_cache.message
    assert strategy_gate.status == "BLOCK"
    assert status.next_actions[0].startswith("Rerun guarded offline intake")


def test_capital_goal_status_does_not_require_packet_for_generic_report(
    tmp_path: Path,
) -> None:
    _write_core_pass_artifacts(tmp_path)
    _write_candidate_selection_pass(tmp_path)

    status = build_capital_goal_status(tmp_path, goal=_goal())

    packet = next(item for item in status.evidence if item.name == "data_evidence_action_packet")
    ramp = next(item for item in status.evidence if item.name == "provider_acquisition_ramp")
    assert status.decision == "PASS"
    assert packet.status == "PASS"
    assert packet.artifact == "not_applicable"
    assert ramp.status == "PASS"
    assert ramp.artifact == "not_applicable"
    assert "optional route diagnostics are not a data gate" in ramp.message


def test_capital_goal_status_provider_ramp_block_is_route_diagnostic(
    tmp_path: Path,
) -> None:
    _write_core_pass_artifacts(tmp_path)
    _write_candidate_selection_pass(tmp_path)
    _write_provider_ramp_report(tmp_path / "provider_acquisition_ramp.json", status="BLOCK")

    status = build_capital_goal_status(tmp_path, goal=_goal())

    ramp = next(item for item in status.evidence if item.name == "provider_acquisition_ramp")
    strategy_gate = next(item for item in status.evidence if item.name == "strategy_search_gate")
    assert status.decision == "WATCH"
    assert ramp.status == "WATCH"
    assert "route diagnostics only" in ramp.message
    assert "cannot approve source QA" in ramp.message
    assert "promotion gates" in ramp.message
    assert strategy_gate.status == "PASS"
    assert "Data/source gates are PASS" in strategy_gate.message
    assert any(
        action.startswith("Review provider acquisition ramp route diagnostics")
        for action in status.next_actions
    )


def test_capital_goal_status_includes_import_doctor_blocker(tmp_path: Path) -> None:
    cache = tmp_path / "recent.db"
    doctor_dir = tmp_path / "doctor"
    BarStorage(cache)
    _write_core_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "candidate_selection.json",
        {
            "status": "PASS",
            "best_candidate": "core_multifactor",
            "results": [{"name": "core_multifactor", "metrics": {"annualized_return": 0.40}}],
        },
    )
    doctor_dir.mkdir()
    _write_json(
        doctor_dir / "data_import_doctor.json",
        {
            "status": "BLOCK",
            "findings": [
                {
                    "severity": "BLOCK",
                    "code": "TEMPLATE_EXPORT_UNREPLACED",
                    "message": "One or more CSV files still contain the generated template sample rows.",
                }
            ],
        },
    )

    status = build_capital_goal_status(
        tmp_path,
        goal=_goal(),
        cfg=_cfg(cache),
        import_doctor_dir=doctor_dir,
        as_of="2026-06-08",
        min_symbols=300,
        min_trading_days=240,
    )

    doctor = next(item for item in status.evidence if item.name == "offline_import_doctor")
    assert status.decision == "BLOCK"
    assert doctor.status == "BLOCK"
    assert "TEMPLATE_EXPORT_UNREPLACED" in doctor.message
    assert status.next_actions[0].startswith("Fix offline import doctor blocker")


def test_capital_goal_status_includes_source_qa_blocker(tmp_path: Path) -> None:
    cache = tmp_path / "recent.db"
    source_qa_dir = tmp_path / "source_qa"
    BarStorage(cache)
    _write_core_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "candidate_selection.json",
        {
            "status": "PASS",
            "best_candidate": "core_multifactor",
            "results": [{"name": "core_multifactor", "metrics": {"annualized_return": 0.40}}],
        },
    )
    source_qa_dir.mkdir()
    _write_json(
        source_qa_dir / "data_source_qa_review.json",
        {
            "status": "BLOCK",
            "findings": [
                {
                    "severity": "BLOCK",
                    "code": "SOURCE_QA_ANSWERS_MISSING",
                    "message": "data_source_qa_answers.json is missing or empty.",
                }
            ],
        },
    )

    status = build_capital_goal_status(
        tmp_path,
        goal=_goal(),
        cfg=_cfg(cache),
        source_qa_dir=source_qa_dir,
        as_of="2026-06-08",
        min_symbols=300,
        min_trading_days=240,
    )

    source_qa = next(item for item in status.evidence if item.name == "offline_source_qa")
    assert status.decision == "BLOCK"
    assert source_qa.status == "BLOCK"
    assert "SOURCE_QA_ANSWERS_MISSING" in source_qa.message
    assert status.next_actions[0].startswith("Fix data source QA blocker")


def test_capital_goal_status_includes_source_qa_preflight_blocker(tmp_path: Path) -> None:
    cache = tmp_path / "recent.db"
    source_qa_dir = tmp_path / "source_qa"
    BarStorage(cache)
    _write_core_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "candidate_selection.json",
        {
            "status": "PASS",
            "best_candidate": "core_multifactor",
            "results": [{"name": "core_multifactor", "metrics": {"annualized_return": 0.40}}],
        },
    )
    source_qa_dir.mkdir()
    _write_json(
        source_qa_dir / "source_qa_preflight.json",
        {
            "status": "BLOCK",
            "items": [
                {
                    "kind": "artifact",
                    "status": "BLOCK",
                    "field": "data_source_qa_answers.json",
                    "message": "Source QA answers are missing or empty.",
                }
            ],
        },
    )
    _write_json(
        source_qa_dir / "data_source_qa_review.json",
        {
            "status": "PASS",
            "findings": [],
        },
    )

    status = build_capital_goal_status(
        tmp_path,
        goal=_goal(),
        cfg=_cfg(cache),
        source_qa_dir=source_qa_dir,
        as_of="2026-06-08",
        min_symbols=300,
        min_trading_days=240,
    )

    preflight = next(item for item in status.evidence if item.name == "offline_source_qa_preflight")
    strategy_gate = next(item for item in status.evidence if item.name == "strategy_search_gate")
    assert status.decision == "BLOCK"
    assert preflight.status == "BLOCK"
    assert "data_source_qa_answers.json" in preflight.message
    assert strategy_gate.status == "BLOCK"
    assert any("source QA preflight" in action for action in status.next_actions)


def test_capital_goal_status_includes_offline_intake_blocker(tmp_path: Path) -> None:
    cache = tmp_path / "recent.db"
    intake_dir = tmp_path / "offline_intake"
    BarStorage(cache)
    _write_core_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "candidate_selection.json",
        {
            "status": "PASS",
            "best_candidate": "core_multifactor",
            "results": [{"name": "core_multifactor", "metrics": {"annualized_return": 0.40}}],
        },
    )
    intake_dir.mkdir()
    _write_json(
        intake_dir / "offline_data_intake.json",
        {
            "status": "BLOCK",
            "steps": [
                {
                    "name": "doctor",
                    "status": "BLOCK",
                    "artifact": "data_import_doctor.json",
                    "message": "TEMPLATE_EXPORT_UNREPLACED: generated template sample rows remain.",
                }
            ],
        },
    )

    status = build_capital_goal_status(
        tmp_path,
        goal=_goal(),
        cfg=_cfg(cache),
        offline_intake_dir=intake_dir,
        as_of="2026-06-08",
        min_symbols=300,
        min_trading_days=240,
    )

    intake = next(item for item in status.evidence if item.name == "offline_data_intake")
    assert status.decision == "BLOCK"
    assert intake.status == "BLOCK"
    assert "Stopped at doctor" in intake.message
    assert status.next_actions[0].startswith("Fix offline data intake blocker")


def test_capital_goal_status_includes_offline_data_package_blocker(tmp_path: Path) -> None:
    cache = tmp_path / "recent.db"
    BarStorage(cache)
    _write_core_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "candidate_selection.json",
        {
            "status": "PASS",
            "best_candidate": "core_multifactor",
            "results": [{"name": "core_multifactor", "metrics": {"annualized_return": 0.40}}],
        },
    )
    _write_json(
        tmp_path / "offline_data_package.json",
        {
            "status": "BLOCK",
            "items": [
                {
                    "name": "csv_template_rows",
                    "status": "BLOCK",
                    "message": "One or more CSV files still contain generated template sample rows.",
                }
            ],
        },
    )

    status = build_capital_goal_status(
        tmp_path,
        goal=_goal(),
        cfg=_cfg(cache),
        as_of="2026-06-08",
        min_symbols=300,
        min_trading_days=240,
    )

    package = next(item for item in status.evidence if item.name == "offline_data_package")
    assert status.decision == "BLOCK"
    assert package.status == "BLOCK"
    assert "csv_template_rows" in package.message


def test_capital_goal_status_surfaces_offline_package_source_provenance(
    tmp_path: Path,
) -> None:
    _write_core_pass_artifacts(tmp_path)
    _write_candidate_selection_pass(tmp_path)
    _write_json(
        tmp_path / "offline_data_package.json",
        {
            "status": "PASS",
            "items": [],
            "source_metadata_summary": {
                "data_vendor_or_broker": "unit-test vendor",
                "terminal_or_product_name": "unit-test terminal",
                "exported_at_local_time": "2026-06-08 18:00:00",
                "price_adjustment": "qfq",
                "reviewed_by": "tester",
                "reviewed_at": "2026-06-08",
            },
        },
    )

    status = build_capital_goal_status(tmp_path, goal=_goal())

    package = next(item for item in status.evidence if item.name == "offline_data_package")
    assert status.decision == "PASS"
    assert package.status == "PASS"
    assert "source=unit-test vendor / unit-test terminal" in package.message
    assert "exported_at=2026-06-08 18:00:00" in package.message


def test_capital_goal_status_passes_complete_raw_vendor_traceability(tmp_path: Path) -> None:
    cache = tmp_path / "recent.db"
    storage = BarStorage(cache)
    _seed_real_like_cache(storage, symbols=2, start="2024-01-02", periods=2)
    storage.save_metadata(
        {
            "csv_dataset_fingerprint": "csv-fingerprint-1",
            "raw_vendor_bars_sha256": "raw-hash-1",
        }
    )
    intake_dir = tmp_path / "offline_intake"
    intake_dir.mkdir()
    _write_core_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "run_manifest.json",
        {
            "demo_data_used": False,
            "latest_bar_date": "2024-01-03",
            "data_version": {
                "csv_dataset_fingerprint": "csv-fingerprint-1",
                "raw_vendor_bars_sha256": "raw-hash-1",
            },
        },
    )
    _write_raw_vendor_trace(intake_dir, raw_hash="raw-hash-1")
    _write_candidate_selection_pass(tmp_path)

    status = build_capital_goal_status(
        tmp_path,
        goal=_goal(),
        cfg=_cfg_window(cache, start="2024-01-02", end="2024-01-03"),
        offline_intake_dir=intake_dir,
        as_of="2024-01-03",
        min_symbols=2,
        min_trading_days=2,
    )

    raw_trace = next(item for item in status.evidence if item.name == "raw_vendor_traceability")
    assert status.decision == "PASS"
    assert raw_trace.status == "PASS"
    assert "raw-hash-1" in raw_trace.message


def test_capital_goal_status_blocks_raw_vendor_hash_mismatch(tmp_path: Path) -> None:
    cache = tmp_path / "recent.db"
    storage = BarStorage(cache)
    _seed_real_like_cache(storage, symbols=2, start="2024-01-02", periods=2)
    storage.save_metadata(
        {
            "csv_dataset_fingerprint": "csv-fingerprint-1",
            "raw_vendor_bars_sha256": "raw-hash-1",
        }
    )
    intake_dir = tmp_path / "offline_intake"
    intake_dir.mkdir()
    _write_core_pass_artifacts(tmp_path)
    _write_candidate_selection_pass(tmp_path)
    _write_json(
        tmp_path / "run_manifest.json",
        {
            "demo_data_used": False,
            "latest_bar_date": "2024-01-03",
            "data_version": {
                "csv_dataset_fingerprint": "csv-fingerprint-1",
                "raw_vendor_bars_sha256": "raw-hash-1",
            },
        },
    )
    _write_raw_vendor_trace(intake_dir, raw_hash="raw-hash-1", import_hash="different-hash")

    status = build_capital_goal_status(
        tmp_path,
        goal=_goal(),
        cfg=_cfg_window(cache, start="2024-01-02", end="2024-01-03"),
        offline_intake_dir=intake_dir,
        as_of="2024-01-03",
        min_symbols=2,
        min_trading_days=2,
    )

    raw_trace = next(item for item in status.evidence if item.name == "raw_vendor_traceability")
    strategy_gate = next(item for item in status.evidence if item.name == "strategy_search_gate")
    assert status.decision == "BLOCK"
    assert raw_trace.status == "BLOCK"
    assert "does not match" in raw_trace.message
    assert strategy_gate.status == "BLOCK"
    assert any("raw vendor traceability" in action for action in status.next_actions)


def test_capital_goal_status_passes_complete_tdx_day_traceability(tmp_path: Path) -> None:
    cache = tmp_path / "recent.db"
    storage = BarStorage(cache)
    _seed_real_like_cache(storage, symbols=2, start="2024-01-02", periods=2)
    intake_dir = tmp_path / "offline_intake"
    intake_dir.mkdir()
    _write_core_pass_artifacts(tmp_path)
    metadata = _write_tdx_day_trace(tmp_path, intake_dir)
    storage.save_metadata({"csv_dataset_fingerprint": "csv-fingerprint-1", **metadata})
    _write_candidate_selection_pass(tmp_path)

    status = build_capital_goal_status(
        tmp_path,
        goal=_goal(),
        cfg=_cfg_window(cache, start="2024-01-02", end="2024-01-03"),
        offline_intake_dir=intake_dir,
        as_of="2024-01-03",
        min_symbols=2,
        min_trading_days=2,
    )

    tdx_trace = next(item for item in status.evidence if item.name == "tdx_day_traceability")
    manifest = next(item for item in status.evidence if item.name == "run_manifest")
    assert status.decision == "PASS"
    assert tdx_trace.status == "PASS"
    assert metadata["tdx_day_export_sha256"][:12] in tdx_trace.message
    assert "TDX day export sha256" in manifest.message


def test_capital_goal_status_blocks_tdx_day_hash_mismatch(tmp_path: Path) -> None:
    cache = tmp_path / "recent.db"
    storage = BarStorage(cache)
    _seed_real_like_cache(storage, symbols=2, start="2024-01-02", periods=2)
    intake_dir = tmp_path / "offline_intake"
    intake_dir.mkdir()
    _write_core_pass_artifacts(tmp_path)
    _write_candidate_selection_pass(tmp_path)
    metadata = _write_tdx_day_trace(tmp_path, intake_dir, import_hash="different-hash")
    storage.save_metadata({"csv_dataset_fingerprint": "csv-fingerprint-1", **metadata})

    status = build_capital_goal_status(
        tmp_path,
        goal=_goal(),
        cfg=_cfg_window(cache, start="2024-01-02", end="2024-01-03"),
        offline_intake_dir=intake_dir,
        as_of="2024-01-03",
        min_symbols=2,
        min_trading_days=2,
    )

    tdx_trace = next(item for item in status.evidence if item.name == "tdx_day_traceability")
    strategy_gate = next(item for item in status.evidence if item.name == "strategy_search_gate")
    assert status.decision == "BLOCK"
    assert tdx_trace.status == "BLOCK"
    assert "does not match" in tdx_trace.message
    assert strategy_gate.status == "BLOCK"
    assert any("TDX day" in action for action in status.next_actions)


def test_capital_goal_status_blocks_missing_tdx_day_export_report(tmp_path: Path) -> None:
    cache = tmp_path / "recent.db"
    storage = BarStorage(cache)
    _seed_real_like_cache(storage, symbols=2, start="2024-01-02", periods=2)
    intake_dir = tmp_path / "offline_intake"
    intake_dir.mkdir()
    _write_core_pass_artifacts(tmp_path)
    _write_candidate_selection_pass(tmp_path)
    metadata = _tdx_metadata(
        report_path=tmp_path / "missing_tdx_day_export.json",
        report_hash="tdx-hash-1",
    )
    _write_json(
        intake_dir / "data_import.json",
        {
            "status": "PASS",
            "metadata": {"csv_dataset_fingerprint": "csv-fingerprint-1", **metadata},
        },
    )
    storage.save_metadata({"csv_dataset_fingerprint": "csv-fingerprint-1", **metadata})
    _write_json(
        tmp_path / "run_manifest.json",
        {
            "demo_data_used": False,
            "latest_bar_date": "2024-01-03",
            "data_version": {"csv_dataset_fingerprint": "csv-fingerprint-1", **metadata},
        },
    )

    status = build_capital_goal_status(
        tmp_path,
        goal=_goal(),
        cfg=_cfg_window(cache, start="2024-01-02", end="2024-01-03"),
        offline_intake_dir=intake_dir,
        as_of="2024-01-03",
        min_symbols=2,
        min_trading_days=2,
    )

    tdx_trace = next(item for item in status.evidence if item.name == "tdx_day_traceability")
    assert status.decision == "BLOCK"
    assert tdx_trace.status == "BLOCK"
    assert "does not exist" in tdx_trace.message


def test_capital_goal_status_does_not_require_raw_trace_for_standard_csv(
    tmp_path: Path,
) -> None:
    _write_core_pass_artifacts(tmp_path)
    _write_candidate_selection_pass(tmp_path)

    status = build_capital_goal_status(tmp_path, goal=_goal())

    raw_trace = next(item for item in status.evidence if item.name == "raw_vendor_traceability")
    tdx_trace = next(item for item in status.evidence if item.name == "tdx_day_traceability")
    assert status.decision == "PASS"
    assert raw_trace.status == "PASS"
    assert raw_trace.artifact == "not_applicable"
    assert tdx_trace.status == "PASS"
    assert tdx_trace.artifact == "not_applicable"


def test_capital_goal_status_passes_when_config_cache_is_broad_and_recent(tmp_path: Path) -> None:
    cache = tmp_path / "recent.db"
    storage = BarStorage(cache)
    _seed_real_like_cache(storage, symbols=300, start="2025-06-23", periods=250)
    _write_core_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "candidate_selection.json",
        {
            "status": "PASS",
            "best_candidate": "core_multifactor",
            "results": [{"name": "core_multifactor", "metrics": {"annualized_return": 0.40}}],
        },
    )
    write_statistical_evidence_fixtures(tmp_path)

    status = build_capital_goal_status(
        tmp_path,
        goal=_goal(),
        cfg=_cfg(cache),
        as_of="2026-06-08",
        min_symbols=300,
        min_trading_days=240,
    )

    data_cache = next(item for item in status.evidence if item.name == "data_cache")
    assert status.decision == "PASS"
    assert data_cache.status == "PASS"
    assert "symbols=300" in data_cache.message


def test_goal_status_cli_writes_outputs(tmp_path: Path) -> None:
    _write_core_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "candidate_selection.json",
        {
            "status": "PASS",
            "best_candidate": "core_multifactor",
            "results": [
                {
                    "name": "core_multifactor",
                    "metrics": {"annualized_return": 0.40},
                }
            ],
        },
    )
    write_statistical_evidence_fixtures(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_goal_status.py",
            "--report-dir",
            str(tmp_path),
            "--years",
            "8",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((tmp_path / "capital_goal_status.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["decision"] == "PASS"


def test_goal_status_cli_accepts_import_doctor_dir(tmp_path: Path) -> None:
    cache = tmp_path / "recent.db"
    doctor_dir = tmp_path / "doctor"
    BarStorage(cache)
    _write_core_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "candidate_selection.json",
        {
            "status": "PASS",
            "best_candidate": "core_multifactor",
            "results": [{"name": "core_multifactor", "metrics": {"annualized_return": 0.40}}],
        },
    )
    _write_config(tmp_path / "config.yaml", cache)
    doctor_dir.mkdir()
    _write_json(
        doctor_dir / "data_import_doctor.json",
        {
            "status": "BLOCK",
            "findings": [
                {"severity": "BLOCK", "code": "DATA_EXPORT_DIR_MISSING", "message": "missing"}
            ],
        },
    )

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_goal_status.py",
            "--report-dir",
            str(tmp_path),
            "--config",
            str(tmp_path / "config.yaml"),
            "--import-doctor-dir",
            str(doctor_dir),
            "--as-of",
            "2026-06-08",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((tmp_path / "capital_goal_status.json").read_text(encoding="utf-8"))
    evidence_names = {item["name"] for item in payload["evidence"]}
    assert completed.returncode == 0
    assert payload["decision"] == "BLOCK"
    assert "offline_import_doctor" in evidence_names


def test_goal_status_cli_accepts_source_qa_dir(tmp_path: Path) -> None:
    cache = tmp_path / "recent.db"
    source_qa_dir = tmp_path / "source_qa"
    BarStorage(cache)
    _write_core_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "candidate_selection.json",
        {
            "status": "PASS",
            "best_candidate": "core_multifactor",
            "results": [{"name": "core_multifactor", "metrics": {"annualized_return": 0.40}}],
        },
    )
    _write_config(tmp_path / "config.yaml", cache)
    source_qa_dir.mkdir()
    _write_json(
        source_qa_dir / "source_qa_preflight.json",
        {
            "status": "BLOCK",
            "items": [
                {
                    "kind": "metadata",
                    "status": "BLOCK",
                    "field": "data_vendor_or_broker",
                    "message": "Required source metadata is missing.",
                }
            ],
        },
    )
    _write_json(
        source_qa_dir / "data_source_qa_review.json",
        {
            "status": "BLOCK",
            "findings": [
                {
                    "severity": "BLOCK",
                    "code": "SOURCE_METADATA_MISSING",
                    "message": "Required source metadata fields are missing.",
                }
            ],
        },
    )

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_goal_status.py",
            "--report-dir",
            str(tmp_path),
            "--config",
            str(tmp_path / "config.yaml"),
            "--source-qa-dir",
            str(source_qa_dir),
            "--as-of",
            "2026-06-08",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((tmp_path / "capital_goal_status.json").read_text(encoding="utf-8"))
    evidence_names = {item["name"] for item in payload["evidence"]}
    assert completed.returncode == 0
    assert payload["decision"] == "BLOCK"
    assert "offline_source_qa_preflight" in evidence_names
    assert "offline_source_qa" in evidence_names


def test_goal_status_cli_accepts_offline_intake_dir(tmp_path: Path) -> None:
    cache = tmp_path / "recent.db"
    intake_dir = tmp_path / "offline_intake"
    BarStorage(cache)
    _write_core_pass_artifacts(tmp_path)
    _write_json(
        tmp_path / "candidate_selection.json",
        {
            "status": "PASS",
            "best_candidate": "core_multifactor",
            "results": [{"name": "core_multifactor", "metrics": {"annualized_return": 0.40}}],
        },
    )
    _write_config(tmp_path / "config.yaml", cache)
    intake_dir.mkdir()
    _write_json(
        intake_dir / "offline_data_intake.json",
        {
            "status": "BLOCK",
            "steps": [
                {
                    "name": "csv_validation",
                    "status": "BLOCK",
                    "artifact": "csv_validation.json",
                    "message": "bars.csv is missing required columns.",
                }
            ],
        },
    )

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_goal_status.py",
            "--report-dir",
            str(tmp_path),
            "--config",
            str(tmp_path / "config.yaml"),
            "--offline-intake-dir",
            str(intake_dir),
            "--as-of",
            "2026-06-08",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((tmp_path / "capital_goal_status.json").read_text(encoding="utf-8"))
    evidence_names = {item["name"] for item in payload["evidence"]}
    assert completed.returncode == 0
    assert payload["decision"] == "BLOCK"
    assert "offline_data_package" in evidence_names
    assert "offline_data_intake" in evidence_names


def _goal() -> CapitalGoal:
    return CapitalGoal(starting_capital=100_000, target_capital=1_000_000, years=8)


def _cfg(cache_path: Path) -> Config:
    return Config(
        {
            "research": {
                "start": "2025-06-23",
                "end": "2026-06-05",
                "initial_cash": 1_000_000.0,
                "rebalance": "monthly",
            },
            "data": {"cache_path": str(cache_path), "source": "csv"},
        }
    )


def _cfg_window(cache_path: Path, *, start: str, end: str) -> Config:
    return Config(
        {
            "research": {
                "start": start,
                "end": end,
                "initial_cash": 1_000_000.0,
                "rebalance": "monthly",
            },
            "data": {"cache_path": str(cache_path), "source": "csv"},
        }
    )


def _seed_real_like_cache(
    storage: BarStorage,
    *,
    symbols: int,
    start: str,
    periods: int,
    with_metadata: bool = True,
) -> None:
    dates = pd.bdate_range(start, periods=periods)
    symbol_list = [f"{idx:06d}" for idx in range(1, symbols + 1)]
    storage.save_calendar(pd.DatetimeIndex(dates))
    storage.save_stock_info(
        pd.DataFrame(
            {
                "symbol": symbol_list,
                "name": [f"Stock{idx:03d}" for idx in range(1, symbols + 1)],
                "industry": ["industry"] * symbols,
                "is_st": [0] * symbols,
            }
        )
    )
    rows = []
    for idx, symbol in enumerate(symbol_list, start=1):
        base = 10 + idx * 0.01
        for offset, date in enumerate(dates):
            close = base + offset * 0.001
            rows.append(
                {
                    "symbol": symbol,
                    "date": date.date().isoformat(),
                    "open": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": 1_000_000,
                    "amount": close * 1_000_000,
                }
            )
    if with_metadata:
        metadata = {
            "data_source": "local_csv",
            "csv_dataset_fingerprint": "csv-fingerprint-1",
            "data_source_qa_status": "PASS",
            "data_source_csv_qa_status": "PASS",
            **_cache_source_qa_metadata(storage.db_path.parent),
        }
        storage.save_bars_with_lineage(
            pd.DataFrame(rows),
            source_type="guarded_local_csv",
            source_reference="unit-test-bars.csv",
            source_fingerprint_kind="csv_dataset_fingerprint",
            source_fingerprint="csv-fingerprint-1",
            cache_metadata=metadata,
        )
    else:
        storage.save_bars(pd.DataFrame(rows))
        storage.save_metadata({"data_source": "local_csv"})


def _cache_source_qa_metadata(root: Path) -> dict[str, str]:
    qa_dir = root / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    checklist = qa_dir / "data_source_qa.json"
    answers = qa_dir / "data_source_qa_answers.json"
    if not checklist.exists():
        checklist.write_text('{"checklist": [{"id": "source_identity"}]}', encoding="utf-8")
    if not answers.exists():
        answers.write_text('{"answers": {"source_identity": "yes"}}', encoding="utf-8")
    return {
        "data_source_qa_checklist_path": str(checklist),
        "data_source_qa_checklist_sha256": _sha256(checklist),
        "data_source_qa_answers_path": str(answers),
        "data_source_qa_answers_sha256": _sha256(answers),
    }


def _write_candidate_selection_pass(root: Path) -> None:
    _write_json(
        root / "candidate_selection.json",
        {
            "status": "PASS",
            "best_candidate": "core_multifactor",
            "results": [{"name": "core_multifactor", "metrics": {"annualized_return": 0.40}}],
        },
    )
    write_statistical_evidence_fixtures(root)


def _write_raw_vendor_trace(
    root: Path,
    *,
    raw_hash: str,
    import_hash: str | None = None,
) -> None:
    _write_json(
        root / "offline_data_intake.json",
        {
            "status": "PASS",
            "steps": [
                {
                    "name": "vendor_bars_normalization",
                    "status": "PASS",
                    "artifact": str(root / "vendor_bars_normalization.json"),
                    "message": "rows=4, symbols=2",
                }
            ],
        },
    )
    _write_json(
        root / "vendor_bars_normalization.json",
        {
            "status": "PASS",
            "input_path": "raw_vendor_bars.csv",
            "raw_sha256": raw_hash,
            "raw_size_bytes": 123,
            "raw_modified_at_utc": "2024-01-03T10:00:00+00:00",
        },
    )
    _write_json(
        root / "data_import.json",
        {
            "status": "PASS",
            "metadata": {
                "csv_dataset_fingerprint": "csv-fingerprint-1",
                "raw_vendor_bars_sha256": import_hash or raw_hash,
            },
        },
    )


def _write_tdx_day_trace(
    root: Path,
    intake_dir: Path,
    *,
    import_hash: str | None = None,
) -> dict[str, str]:
    report_path = root / "tdx_day_export.json"
    _write_json(
        report_path,
        {
            "status": "PASS",
            "input_dir": "C:\\new_tdx\\vipdoc",
            "output_dir": "data_exports",
            "start": "2024-01-02",
            "end": "2024-01-03",
            "bars_csv": "data_exports\\bars.csv",
            "stock_info_csv": "data_exports\\stock_info.csv",
            "calendar_csv": "data_exports\\calendar.csv",
            "discovered_files": 2,
            "converted_files": 2,
            "symbol_count": 2,
            "row_count": 4,
            "files": [],
            "failures": [],
            "notes": [],
        },
    )
    report_hash = _sha256(report_path)
    metadata = _tdx_metadata(report_path=report_path, report_hash=report_hash)
    import_metadata = {**metadata, "tdx_day_export_sha256": import_hash or report_hash}
    _write_json(
        intake_dir / "offline_data_intake.json",
        {
            "status": "PASS",
            "steps": [
                {
                    "name": "doctor",
                    "status": "PASS",
                    "artifact": str(intake_dir / "data_import_doctor.json"),
                    "message": "Data import doctor completed.",
                },
                {
                    "name": "csv_validation",
                    "status": "PASS",
                    "artifact": str(intake_dir / "csv_validation.json"),
                    "message": "symbols=2, bars_start=2024-01-02, bars_end=2024-01-03",
                },
                {
                    "name": "import",
                    "status": "PASS",
                    "artifact": str(intake_dir / "data_import.json"),
                    "message": "imported_symbols=2, bar_rows=4",
                },
            ],
        },
    )
    _write_json(
        intake_dir / "data_import.json",
        {
            "status": "PASS",
            "metadata": {"csv_dataset_fingerprint": "csv-fingerprint-1", **import_metadata},
        },
    )
    _write_json(
        root / "run_manifest.json",
        {
            "demo_data_used": False,
            "latest_bar_date": "2024-01-03",
            "data_version": {"csv_dataset_fingerprint": "csv-fingerprint-1", **metadata},
        },
    )
    return metadata


def _tdx_metadata(*, report_path: Path, report_hash: str) -> dict[str, str]:
    return {
        "tdx_day_export_report": str(report_path),
        "tdx_day_export_sha256": report_hash,
        "tdx_day_export_status": "PASS",
        "tdx_day_input_dir": "C:\\new_tdx\\vipdoc",
        "tdx_day_symbol_count": "2",
        "tdx_day_row_count": "4",
        "tdx_day_start": "2024-01-02",
        "tdx_day_end": "2024-01-03",
    }


def _write_core_pass_artifacts(root: Path) -> None:
    _write_json(
        root / "run_manifest.json",
        {
            "demo_data_used": False,
            "latest_bar_date": "2026-06-05",
            "data_version": {"csv_dataset_fingerprint": "abc"},
        },
    )
    _write_json(
        root / "recent_data_acquisition_plan.json",
        {
            "status": "PASS",
            "current_symbol_count": 300,
            "current_latest_bar_date": "2026-06-05",
            "latest_import_attempt": {
                "network_blocked": False,
                "actual_bar_end": "2026-06-05",
            },
            "blockers": [],
        },
    )
    _write_json(
        root / "csv_validation.json",
        {
            "status": "PASS",
            "metrics": {
                "bars_end": "2026-06-05",
                "bars_symbol_count": 300,
            },
            "findings": [],
        },
    )
    _write_json(
        root / "operator_handoff_status.json",
        {
            "status": "PASS",
            "open_task_count": 0,
            "p0_open_task_count": 0,
            "source_qa_open_task_count": 0,
            "data_export_open_task_count": 0,
        },
    )
    _write_json(
        root / "csv_intake_preview.json",
        {
            "status": "PASS",
            "items": [
                {
                    "role": "bars",
                    "file_name": "bars.csv",
                    "status": "PASS",
                    "normalized_rows": 60000,
                    "symbol_count": 300,
                    "message": "Columns mapped and normalized successfully.",
                }
            ],
        },
    )
    for name, key in [
        ("real_data_bootstrap.json", "decision"),
        ("real_data_gate.json", "decision"),
        ("data_coverage.json", "status"),
        ("data_audit.json", "status"),
        ("offline_data_package.json", "status"),
        ("robustness_report.json", "status"),
        ("walk_forward_report.json", "status"),
        ("candidate_walk_forward_report.json", "status"),
        ("candidate_factor_diagnostics.json", "status"),
        ("candidate_regime_validation_report.json", "status"),
        ("candidate_experiment_launch.json", "decision"),
        ("candidate_experiment_execution.json", "decision"),
        ("candidate_experiment_completion.json", "decision"),
        ("llm_review.json", "decision"),
        ("paper_stability.json", "status"),
        ("strategy_promotion_review.json", "decision"),
        ("capital_scaling_plan.json", "decision"),
    ]:
        _write_json(root / name, {key: "PASS"})
    _write_json(
        root / "approval_record.json",
        {
            "approved_by": "tester",
            "approved_at": "2026-06-08T00:00:00",
            "allowed_stage": "paper",
            "approval_notes": "unit test",
        },
    )


def _write_json(path: Path, payload: dict) -> None:
    if path.name == "robustness_report.json":
        payload = selection_safe_robustness_payload(status=str(payload.get("status", "PASS")))
    elif path.name == "walk_forward_report.json":
        payload = selection_safe_walk_forward_payload(status=str(payload.get("status", "PASS")))
    elif path.name == "candidate_walk_forward_report.json":
        candidate = str(payload.get("best_candidate") or "core_multifactor")
        payload = selection_safe_walk_forward_payload(
            status=str(payload.get("status", "PASS")),
            candidate=candidate,
        )
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_provider_ramp_report(path: Path, *, status: str) -> None:
    _write_json(
        path,
        {
            "status": status,
            "provider": "akshare",
            "configured_stage_sizes": [2, 20],
            "executed_stage_count": 2,
            "stages": [
                {
                    "index": 1,
                    "size": 2,
                    "status": "PASS",
                    "imported_symbols": 2,
                    "requested_symbols": 2,
                    "bar_rows": 4,
                },
                {
                    "index": 2,
                    "size": 20,
                    "status": status,
                    "imported_symbols": 0 if status == "BLOCK" else 19,
                    "requested_symbols": 20,
                    "bar_rows": 0 if status == "BLOCK" else 38,
                },
            ],
            "research_only": True,
            "source_qa_provenance_status": "NOT_EVALUATED",
            "promotion_gate_effect": "NONE",
            "next_actions": ["Review provider ramp before broad provider imports."],
            "prohibited_actions": [
                "Do not treat AKShare/provider ramp PASS as source QA/provenance PASS."
            ],
        },
    )


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_config(path: Path, cache_path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "research:",
                '  start: "2025-06-23"',
                '  end: "2026-06-05"',
                "data:",
                f"  cache_path: '{cache_path}'",
            ]
        ),
        encoding="utf-8",
    )
