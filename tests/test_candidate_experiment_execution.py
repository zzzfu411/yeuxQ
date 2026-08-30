from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from quantify.research.candidate_experiment_execution import (
    run_candidate_experiment_execution,
    write_candidate_experiment_execution,
)
from tests.selection_safe_fixtures import selection_safe_robustness_payload


def test_candidate_experiment_execution_blocks_missing_launch(tmp_path: Path) -> None:
    report = run_candidate_experiment_execution(tmp_path)
    out = write_candidate_experiment_execution(report, tmp_path)

    payload = json.loads((out / "candidate_experiment_execution.json").read_text(encoding="utf-8"))
    markdown = (out / "candidate_experiment_execution.md").read_text(encoding="utf-8")

    assert payload["decision"] == "BLOCK"
    assert "missing or unreadable" in payload["blockers"][0]
    assert "not a trading instruction" in markdown


def test_candidate_experiment_execution_dry_run_validates_whitelisted_commands(
    tmp_path: Path,
) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(
        tmp_path,
        experiment_dir,
        [
            f"python examples/run_candidate_experiment_evidence.py --source-report-dir {tmp_path} --output-dir {experiment_dir}",
            f"python examples/run_candidate_walk_forward.py --config {tmp_path / 'research.yaml'} --output-dir {experiment_dir} --gate-report-dir {tmp_path}",
            f"python examples/run_candidate_stress_matrix.py --config {tmp_path / 'research.yaml'} --output-dir {experiment_dir} --candidate price_volume_defensive --gate-report-dir {tmp_path}",
            f"python examples/run_llm_review.py --report-dir {experiment_dir} --stage paper",
        ],
    )

    report = run_candidate_experiment_execution(tmp_path, dry_run=True)

    assert report.decision == "DRY_RUN"
    assert len(report.steps) == 4
    assert all(step.status == "SKIPPED" for step in report.steps)
    assert all(step.returncode is None for step in report.steps)


def test_candidate_experiment_execution_blocks_candidate_command_without_gate(
    tmp_path: Path,
) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(
        tmp_path,
        experiment_dir,
        [
            f"python examples/run_candidate_walk_forward.py --config {tmp_path / 'research.yaml'} --output-dir {experiment_dir}"
        ],
    )

    report = run_candidate_experiment_execution(tmp_path, dry_run=True)

    assert report.decision == "BLOCK"
    assert report.steps[0].status == "BLOCK"
    assert "--gate-report-dir" in report.steps[0].message


def test_candidate_experiment_execution_blocks_output_outside_launch_dir(tmp_path: Path) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    outside_dir = tmp_path / "wrong_output"
    _write_launch(
        tmp_path,
        experiment_dir,
        [
            (
                "python examples/run_candidate_walk_forward.py "
                f"--config {tmp_path / 'research.yaml'} --output-dir {outside_dir} "
                f"--candidate price_volume_defensive --gate-report-dir {tmp_path}"
            )
        ],
    )

    report = run_candidate_experiment_execution(tmp_path, dry_run=True)

    assert report.decision == "BLOCK"
    assert report.steps[0].status == "BLOCK"
    assert "must stay under launch experiment_dir" in report.steps[0].message


def test_candidate_experiment_execution_blocks_wrong_gate_report_dir(tmp_path: Path) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    wrong_gate = tmp_path / "wrong_gate"
    _write_launch(
        tmp_path,
        experiment_dir,
        [
            (
                "python examples/run_candidate_walk_forward.py "
                f"--config {tmp_path / 'research.yaml'} --output-dir {experiment_dir} "
                f"--candidate price_volume_defensive --gate-report-dir {wrong_gate}"
            )
        ],
    )

    report = run_candidate_experiment_execution(tmp_path, dry_run=True)

    assert report.decision == "BLOCK"
    assert report.steps[0].status == "BLOCK"
    assert "must use the launch report_dir as --gate-report-dir" in report.steps[0].message


def test_candidate_experiment_execution_blocks_non_whitelisted_command(tmp_path: Path) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(
        tmp_path,
        experiment_dir,
        ["python examples/download_data.py --symbol 600519"],
    )

    report = run_candidate_experiment_execution(tmp_path, dry_run=True)

    assert report.decision == "BLOCK"
    assert report.steps[0].status == "BLOCK"
    assert "whitelist" in report.steps[0].message


def test_candidate_experiment_execution_runs_injected_runner_and_writes_logs(
    tmp_path: Path,
) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(
        tmp_path,
        experiment_dir,
        [
            f"python examples/run_candidate_experiment_evidence.py --source-report-dir {tmp_path} --output-dir {experiment_dir}",
            f"python examples/run_candidate_walk_forward.py --config {tmp_path / 'research.yaml'} --output-dir {experiment_dir} --gate-report-dir {tmp_path}",
            f"python examples/run_candidate_stress_matrix.py --config {tmp_path / 'research.yaml'} --output-dir {experiment_dir} --candidate price_volume_defensive --gate-report-dir {tmp_path}",
            f"python examples/run_candidate_factor_diagnostics.py --config {tmp_path / 'research.yaml'} --output-dir {experiment_dir} --candidate price_volume_defensive --gate-report-dir {tmp_path}",
        ],
    )
    _write_foundational_evidence(tmp_path)
    calls: list[list[str]] = []

    def runner(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="ok", stderr="")

    report = run_candidate_experiment_execution(tmp_path, runner=runner)
    write_candidate_experiment_execution(report, tmp_path)

    payload = json.loads(
        (tmp_path / "candidate_experiment_execution.json").read_text(encoding="utf-8")
    )
    assert report.decision == "PASS"
    assert len(calls) == 4
    assert calls[0][0] == sys.executable
    assert payload["steps"][0]["status"] == "PASS"
    assert (experiment_dir / "execution_logs" / "01_stdout.log").read_text(encoding="utf-8") == "ok"


def test_candidate_experiment_execution_blocks_before_runner_when_foundational_evidence_missing(
    tmp_path: Path,
) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(
        tmp_path,
        experiment_dir,
        [
            f"python examples/run_candidate_experiment_evidence.py --source-report-dir {tmp_path} --output-dir {experiment_dir}",
            f"python examples/run_candidate_walk_forward.py --config {tmp_path / 'research.yaml'} --output-dir {experiment_dir} --gate-report-dir {tmp_path}",
        ],
    )
    calls: list[list[str]] = []

    def runner(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="ok", stderr="")

    report = run_candidate_experiment_execution(tmp_path, runner=runner)

    assert report.decision == "BLOCK"
    assert calls == []
    assert len(report.steps) == 1
    assert report.steps[0].status == "BLOCK"
    assert "Foundational evidence preflight failed" in report.steps[0].message
    assert "summary missing" in report.steps[0].message


def test_candidate_experiment_execution_blocks_demo_foundational_evidence_before_runner(
    tmp_path: Path,
) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(
        tmp_path,
        experiment_dir,
        [
            f"python examples/run_candidate_experiment_evidence.py --source-report-dir {tmp_path} --output-dir {experiment_dir}",
        ],
    )
    _write_foundational_evidence(tmp_path, demo_data_used=True)

    def runner(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        raise AssertionError("runner must not be called when foundational evidence is demo data")

    report = run_candidate_experiment_execution(tmp_path, runner=runner)

    assert report.decision == "BLOCK"
    assert "summary is BLOCK" in report.steps[0].message
    assert "run_manifest is BLOCK" in report.steps[0].message


def test_candidate_experiment_execution_preflight_blocks_unsafe_walk_forward_envelopes(
    tmp_path: Path,
) -> None:
    malformed_folds = _walk_forward_payload()
    windows = malformed_folds["windows"]
    assert isinstance(windows, list)
    first_window = windows[0]
    assert isinstance(first_window, dict)
    phases = first_window["phases"]
    assert isinstance(phases, dict)
    test_phase = phases["test"]
    assert isinstance(test_phase, dict)
    test_phase["trading_day_count"] = 2
    unsafe_cases = [
        ({"status": "PASS"}, "artifact_type must be walk_forward_report."),
        (
            {"status": "PASS", "selection_safe": True},
            "schema_version must be 2.",
        ),
        (
            {**_walk_forward_payload(), "schema_version": 1},
            "schema_version must be 2.",
        ),
        (
            {**_walk_forward_payload(), "selection_protocol": "legacy"},
            "selection_protocol must be quantify.walk-forward-selection.v2.",
        ),
        (
            malformed_folds,
            "windows[0].phases.test count does not match configuration.",
        ),
    ]

    for index, (payload, expected_reason) in enumerate(unsafe_cases):
        root = tmp_path / str(index)
        experiment_dir = root / "candidate_experiments" / "run"
        _write_launch(
            root,
            experiment_dir,
            [
                "python examples/run_candidate_experiment_evidence.py "
                f"--source-report-dir {root} --output-dir {experiment_dir}"
            ],
        )
        _write_foundational_evidence(root, walk_forward_payload=payload)

        def runner(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
            raise AssertionError("runner must not be called for unsafe walk-forward evidence")

        report = run_candidate_experiment_execution(root, runner=runner)

        assert report.decision == "BLOCK"
        assert expected_reason in report.steps[0].message


def test_candidate_experiment_execution_stops_on_runner_failure(tmp_path: Path) -> None:
    experiment_dir = tmp_path / "candidate_experiments" / "run"
    _write_launch(
        tmp_path,
        experiment_dir,
        [
            f"python examples/run_candidate_walk_forward.py --config {tmp_path / 'research.yaml'} --output-dir {experiment_dir} --gate-report-dir {tmp_path}",
            f"python examples/run_candidate_factor_diagnostics.py --config {tmp_path / 'research.yaml'} --output-dir {experiment_dir} --candidate price_volume_defensive --gate-report-dir {tmp_path}",
        ],
    )

    def runner(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=args, returncode=7, stdout="", stderr="failed")

    report = run_candidate_experiment_execution(tmp_path, runner=runner)

    assert report.decision == "BLOCK"
    assert len(report.steps) == 1
    assert report.steps[0].returncode == 7
    assert "execution stopped" in report.steps[0].message


def test_candidate_experiment_execution_cli_returns_nonzero_on_block(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_candidate_experiment_execution.py",
            "--report-dir",
            str(tmp_path),
            "--dry-run",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads(
        (tmp_path / "candidate_experiment_execution.json").read_text(encoding="utf-8")
    )
    assert completed.returncode == 2
    assert payload["decision"] == "BLOCK"


def _write_launch(root: Path, experiment_dir: Path, commands: list[str]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "candidate_experiment_launch.json").write_text(
        json.dumps(
            {
                "decision": "PASS",
                "selected_candidate": "price_volume_defensive",
                "run_id": "run",
                "experiment_dir": str(experiment_dir),
                "command_sequence": commands,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_foundational_evidence(
    root: Path,
    *,
    demo_data_used: bool = False,
    walk_forward_payload: dict | None = None,
) -> None:
    _write_json(
        root / "summary.json",
        {"assumptions": {"demo_data_used": demo_data_used}},
    )
    _write_json(root / "run_manifest.json", {"demo_data_used": demo_data_used})
    _write_json(root / "real_data_bootstrap.json", {"decision": "PASS"})
    _write_json(root / "real_data_gate.json", {"decision": "PASS"})
    _write_json(root / "data_audit.json", {"status": "PASS"})
    _write_json(root / "robustness_report.json", selection_safe_robustness_payload())
    _write_json(
        root / "walk_forward_report.json",
        walk_forward_payload if walk_forward_payload is not None else _walk_forward_payload(),
    )


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _walk_forward_payload() -> dict:
    return {
        "artifact_type": "walk_forward_report",
        "schema_version": 2,
        "selection_protocol": "quantify.walk-forward-selection.v2",
        "selection_safe": True,
        "test_used_for_selection": False,
        "configuration": {
            "mode": "expanding",
            "train_days": 2,
            "purge_days": 0,
            "selection_days": 1,
            "embargo_days": 0,
            "test_days": 1,
            "step_days": 1,
        },
        "status": "PASS",
        "window_count": 1,
        "windows": [
            {
                "name": "wf_01",
                "start": "d04",
                "end": "d04",
                "phases": {
                    "name": "wf_01",
                    "mode": "expanding",
                    "train": {"start": "d01", "end": "d02", "trading_day_count": 2},
                    "purge": {"start": "", "end": "", "trading_day_count": 0},
                    "selection": {"start": "d03", "end": "d03", "trading_day_count": 1},
                    "embargo": {"start": "", "end": "", "trading_day_count": 0},
                    "test": {"start": "d04", "end": "d04", "trading_day_count": 1},
                },
            }
        ],
    }
