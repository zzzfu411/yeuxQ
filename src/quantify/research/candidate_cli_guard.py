"""CLI guard for direct candidate research commands."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class CandidateCliGateError(RuntimeError):
    """Raised when a candidate CLI is run without the required launch gate."""


def enforce_candidate_cli_gate(
    gate_report_dir: str | Path | None,
    *,
    cfg,
    candidate: str | None = None,
    output_dir: str | Path | None = None,
) -> None:
    """Require launch evidence for real-data candidate research commands.

    Demo/tutorial configs may still run without a gate. Real-data configs with
    ``allow_demo_data=false`` must be tied to a PASS launch plan so direct CLI
    runs cannot bypass the first-million evidence gates.
    """
    requires_gate = not bool(getattr(cfg.research, "allow_demo_data", False))
    if gate_report_dir is None:
        if requires_gate:
            raise CandidateCliGateError(
                "Candidate research with allow_demo_data=false requires --gate-report-dir "
                "pointing to a PASS candidate_experiment_launch.json."
            )
        return

    root = Path(gate_report_dir)
    launch_path = root / "candidate_experiment_launch.json"
    launch = _read_json(launch_path)
    if not launch:
        raise CandidateCliGateError(f"{launch_path} is missing or unreadable.")
    decision = str(launch.get("decision", "UNKNOWN")).upper()
    if decision != "PASS":
        raise CandidateCliGateError(f"candidate_experiment_launch decision is {decision}; PASS is required.")

    selected = str(launch.get("selected_candidate") or "").strip()
    requested = (candidate or "").strip()
    if selected and not requested:
        raise CandidateCliGateError(
            f"Launch selected candidate {selected!r}; pass --candidate {selected} for this run."
        )
    if requested and selected and requested != selected:
        raise CandidateCliGateError(
            f"Requested candidate {requested!r} does not match launch candidate {selected!r}."
        )

    expected_output = str(launch.get("experiment_dir") or "").strip()
    if expected_output and output_dir is not None:
        requested_output = Path(output_dir)
        expected_path = Path(expected_output)
        if _resolved(requested_output) != _resolved(expected_path):
            raise CandidateCliGateError(
                "Candidate research output directory must match launch experiment_dir: "
                f"requested={requested_output}, expected={expected_path}."
            )

    goal_status = _read_json(root / "capital_goal_status.json") or _read_json(
        root / "goal" / "capital_goal_status.json"
    )
    strategy_gate = _evidence_status(goal_status, "strategy_search_gate")
    if strategy_gate == "BLOCK":
        raise CandidateCliGateError("strategy_search_gate is BLOCK; candidate research is closed.")


def _evidence_status(payload: dict[str, Any], name: str) -> str:
    for item in payload.get("evidence", []) or []:
        if isinstance(item, dict) and item.get("name") == name:
            return str(item.get("status", "UNKNOWN")).upper()
    return ""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _resolved(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except OSError:
        return path.absolute()
