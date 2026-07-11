from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys

from quantify.ops.first_million_resolution import (
    build_first_million_resolution_plan,
    write_first_million_resolution_plan,
)


def test_first_million_resolution_plan_prioritizes_operator_tasks(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "first_million_pipeline.json",
        {
            "decision": "BLOCK",
            "stages": [
                {
                    "name": "source_qa_preflight",
                    "status": "BLOCK",
                    "artifact": str(tmp_path / "source_qa" / "source_qa_preflight.json"),
                    "message": "Source QA answers are missing.",
                },
                {
                    "name": "candidate_experiment_readiness",
                    "status": "BLOCK",
                    "artifact": str(tmp_path / "candidate_experiment_readiness.json"),
                    "message": "Runnable=0, blocked=6.",
                },
            ],
        },
    )
    _write_json(
        tmp_path / "source_qa" / "source_qa_preflight.json",
        {"status": "BLOCK", "next_commands": ["run source preflight again"]},
    )
    _write_json(
        tmp_path / "candidate_experiment_readiness.json",
        {
            "decision": "BLOCK",
            "blockers": ["source_qa_preflight=BLOCK"],
            "next_actions": ["Resolve source QA preflight before candidate experiments."],
        },
    )
    _write_operator_handoff(tmp_path)

    plan = build_first_million_resolution_plan(tmp_path, as_of="2026-06-10")
    out = write_first_million_resolution_plan(plan, tmp_path)

    payload = json.loads((out / "first_million_resolution_plan.json").read_text(encoding="utf-8"))
    markdown = (out / "first_million_resolution_plan.md").read_text(encoding="utf-8")
    rows = list(
        csv.DictReader(
            (out / "first_million_resolution_plan.csv").open(encoding="utf-8-sig")
        )
    )

    assert plan.decision == "BLOCK"
    assert payload["task_counts"]["P0"] == 2
    assert rows[0]["category"] == "source_qa_worksheet"
    assert rows[0]["item"] == "row 1: data_vendor_or_broker"
    assert rows[0]["command"] == "generate answers"
    assert rows[1]["category"] == "source_qa_attachment"
    assert any(row["priority"] == "P2" for row in rows)
    assert "deterministic blockers" in markdown
    assert "acceptance" in markdown
    assert "Top Commands" in markdown
    assert "generate answers" in markdown
    assert any("Fill vendor row" in action for action in payload["next_actions"])
    assert any("Run: generate answers" in action for action in payload["next_actions"])
    assert any("Done when: Evidence is real" in action for action in payload["next_actions"])
    assert any("Do not fabricate" in item for item in payload["prohibited_actions"])


def test_first_million_resolution_plan_cli_returns_nonzero_on_block(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "first_million_pipeline.json",
        {
            "decision": "BLOCK",
            "stages": [
                {
                    "name": "offline_data_package",
                    "status": "BLOCK",
                    "artifact": str(tmp_path / "offline_data_package.json"),
                    "message": "source_qa_answers missing",
                }
            ],
        },
    )
    _write_json(
        tmp_path / "offline_data_package.json",
        {"status": "BLOCK", "next_actions": ["Fill data_source_qa_answers.json."]},
    )

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_first_million_resolution_plan.py",
            "--report-dir",
            str(tmp_path),
            "--as-of",
            "2026-06-10",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((tmp_path / "first_million_resolution_plan.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["decision"] == "BLOCK"
    assert payload["tasks"][0]["source_stage"] == "offline_data_package"


def test_first_million_resolution_plan_prioritizes_placeholder_attachment(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "first_million_pipeline.json",
        {
            "decision": "BLOCK",
            "stages": [
                {
                    "name": "candidate_experiment_readiness",
                    "status": "BLOCK",
                    "artifact": str(tmp_path / "candidate_experiment_readiness.json"),
                    "message": "Runnable=0, blocked=6.",
                },
            ],
        },
    )
    _write_json(
        tmp_path / "candidate_experiment_readiness.json",
        {
            "decision": "BLOCK",
            "blockers": ["source_qa_preflight=BLOCK"],
            "next_actions": ["Resolve source QA preflight before candidate experiments."],
        },
    )
    _write_operator_handoff(tmp_path, attachment_state="placeholder_content")

    plan = build_first_million_resolution_plan(tmp_path, as_of="2026-06-10")
    out = write_first_million_resolution_plan(plan, tmp_path)

    rows = list(
        csv.DictReader(
            (out / "first_million_resolution_plan.csv").open(encoding="utf-8-sig")
        )
    )
    first_attachment = next(row for row in rows if row["category"] == "source_qa_attachment")

    assert plan.decision == "BLOCK"
    assert first_attachment["priority"] == "P0"
    assert first_attachment["item"] == "source_identity"
    assert "placeholder" in first_attachment["action"]
    assert rows.index(first_attachment) < next(
        index for index, row in enumerate(rows) if row["category"] == "candidate_experiment"
    )


def test_first_million_resolution_plan_prioritizes_generated_path_attachment(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "first_million_pipeline.json",
        {
            "decision": "BLOCK",
            "stages": [
                {
                    "name": "candidate_experiment_readiness",
                    "status": "BLOCK",
                    "artifact": str(tmp_path / "candidate_experiment_readiness.json"),
                    "message": "Runnable=0, blocked=6.",
                },
            ],
        },
    )
    _write_json(
        tmp_path / "candidate_experiment_readiness.json",
        {
            "decision": "BLOCK",
            "blockers": ["source_qa_preflight=BLOCK"],
            "next_actions": ["Resolve source QA preflight before candidate experiments."],
        },
    )
    _write_operator_handoff(tmp_path, attachment_state="generated_artifact_path")

    plan = build_first_million_resolution_plan(tmp_path, as_of="2026-06-10")
    out = write_first_million_resolution_plan(plan, tmp_path)

    rows = list(
        csv.DictReader(
            (out / "first_million_resolution_plan.csv").open(encoding="utf-8-sig")
        )
    )
    first_attachment = next(row for row in rows if row["category"] == "source_qa_attachment")

    assert plan.decision == "BLOCK"
    assert first_attachment["priority"] == "P0"
    assert first_attachment["item"] == "source_identity"
    assert "workflow artifact" in first_attachment["action"]
    assert rows.index(first_attachment) < next(
        index for index, row in enumerate(rows) if row["category"] == "candidate_experiment"
    )


def test_first_million_resolution_plan_surfaces_stage_blocker_before_next_action(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "first_million_pipeline.json",
        {
            "decision": "BLOCK",
            "stages": [
                {
                    "name": "capital_goal_status",
                    "status": "BLOCK",
                    "artifact": str(tmp_path / "goal" / "capital_goal_status.json"),
                    "message": "Capital goal evidence is BLOCK.",
                },
            ],
        },
    )
    _write_json(
        tmp_path / "goal" / "capital_goal_status.json",
        {
            "decision": "BLOCK",
            "blockers": ["RUN_MANIFEST: missing source QA evidence manifest."],
            "next_actions": ["Resolve capital goal status."],
        },
    )

    plan = build_first_million_resolution_plan(tmp_path, as_of="2026-06-10")
    task = next(item for item in plan.tasks if item.source_stage == "capital_goal_status")

    assert plan.decision == "BLOCK"
    assert "RUN_MANIFEST" in task.action


def test_first_million_resolution_plan_passes_when_pipeline_pass_has_no_tasks(
    tmp_path: Path,
) -> None:
    _write_json(tmp_path / "first_million_pipeline.json", {"decision": "PASS", "stages": []})

    plan = build_first_million_resolution_plan(tmp_path, as_of="2026-06-10")

    assert plan.decision == "PASS"
    assert plan.task_counts["total"] == 0
    assert "No open resolution tasks" in plan.next_actions[0]


def test_first_million_resolution_plan_surfaces_missing_market_context_task(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "first_million_pipeline.json",
        {
            "decision": "BLOCK",
            "stages": [
                {
                    "name": "candidate_experiment_readiness",
                    "status": "BLOCK",
                    "artifact": str(tmp_path / "candidate_experiment_readiness.json"),
                    "message": "Runnable=0, blocked=6.",
                },
            ],
        },
    )
    _write_json(
        tmp_path / "candidate_experiment_readiness.json",
        {
            "decision": "BLOCK",
            "blockers": ["market_context=MISSING"],
            "next_actions": ["Generate market_regime.json."],
        },
    )
    _write_candidate_readiness_matrix(tmp_path)

    plan = build_first_million_resolution_plan(tmp_path, as_of="2026-06-10")
    out = write_first_million_resolution_plan(plan, tmp_path)
    rows = list(
        csv.DictReader(
            (out / "first_million_resolution_plan.csv").open(encoding="utf-8-sig")
        )
    )
    market_task = next(row for row in rows if row["category"] == "market_context")

    assert plan.decision == "BLOCK"
    assert market_task["priority"] == "P1"
    assert market_task["status"] == "OPEN"
    assert market_task["item"] == "market_regime_or_reviewed_snapshot"
    assert "market_regime.json" in market_task["action"]
    assert "market_context_snapshot.json" in market_task["action"]
    assert any("run_market_regime.py" in action for action in plan.next_actions)


def _write_operator_handoff(root: Path, *, attachment_state: str = "") -> None:
    with (root / "operator_handoff.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        fieldnames = [
            "task_type",
            "priority",
            "status",
            "target",
            "source_artifact",
            "row_number",
            "file_name",
            "id",
            "action",
            "acceptance_criteria",
            "current_state",
            "next_command",
            "gate_note",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(
            {
                "task_type": "source_qa_worksheet",
                "priority": "P0",
                "status": "BLOCK",
                "target": "data_exports/data_source_qa_evidence_worksheet.csv",
                "source_artifact": "source_qa_worksheet_todo.csv",
                "row_number": "1",
                "id": "data_vendor_or_broker",
                "action": "Fill vendor row from real export evidence.",
                "acceptance_criteria": "Evidence is real and answers are regenerated.",
                "next_command": "generate answers",
                "gate_note": "Deterministic gates still decide.",
            }
        )
        writer.writerow(
            {
                "task_type": "source_qa_attachment",
                "priority": "P0",
                "status": "BLOCK",
                "target": "data_exports/source_qa_evidence/source_identity.txt",
                "source_artifact": "source_qa_attachment_todo.csv",
                "id": "source_identity",
                "action": (
                    "Replace placeholder source identity attachment with retained source evidence."
                    if attachment_state == "placeholder_content"
                    else (
                        "Replace generated workflow artifact path with retained source evidence."
                        if attachment_state == "generated_artifact_path"
                        else "Attach retained source identity evidence."
                    )
                ),
                "acceptance_criteria": (
                    "Manifest includes a non-placeholder retained attachment."
                    if attachment_state == "placeholder_content"
                    else (
                        "Manifest attachment path points to retained source evidence, not worksheet or plan files."
                        if attachment_state == "generated_artifact_path"
                        else "Manifest includes this attachment."
                    )
                ),
                "current_state": attachment_state,
                "next_command": "regenerate manifest",
                "gate_note": "Deterministic gates still decide.",
            }
        )


def _write_candidate_readiness_matrix(root: Path) -> None:
    with (root / "candidate_experiment_readiness_matrix.csv").open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        fieldnames = [
            "priority",
            "candidate",
            "data_dependency",
            "evidence_scope",
            "evidence_path",
            "evidence_path_status",
            "status",
            "first_blocker",
            "blocker_count",
            "warning_count",
            "next_command",
            "source_provenance",
            "market_context_source",
            "market_context_status",
            "market_context_label",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(
            {
                "priority": "1",
                "candidate": "price_volume_defensive",
                "data_dependency": "ohlcv_only",
                "evidence_scope": "OHLCV_ONLY",
                "evidence_path": "ohlcv_minimum_path",
                "evidence_path_status": "PASS",
                "status": "BLOCKED",
                "first_blocker": "market_context=MISSING: provide cache-derived market_regime.json",
                "blocker_count": "1",
                "warning_count": "0",
                "next_command": "",
                "source_provenance": "vendor",
                "market_context_source": "missing",
                "market_context_status": "BLOCK",
                "market_context_label": "unknown",
            }
        )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
