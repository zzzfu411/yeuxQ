from __future__ import annotations


def selection_safe_walk_forward_payload(
    *,
    status: str = "PASS",
    candidate: str | None = None,
    window_count: int = 1,
) -> dict[str, object]:
    windows: list[dict[str, object]] = []
    for index in range(window_count):
        train_end = 2 + index * 3
        selection_day = train_end + 1
        test_day = selection_day + 1
        name = f"wf_{index + 1:02d}"
        phases = {
            "name": name,
            "mode": "expanding",
            "train": {
                "start": "d01",
                "end": f"d{train_end:02d}",
                "trading_day_count": train_end,
            },
            "purge": {"start": "", "end": "", "trading_day_count": 0},
            "selection": {
                "start": f"d{selection_day:02d}",
                "end": f"d{selection_day:02d}",
                "trading_day_count": 1,
            },
            "embargo": {"start": "", "end": "", "trading_day_count": 0},
            "test": {
                "start": f"d{test_day:02d}",
                "end": f"d{test_day:02d}",
                "trading_day_count": 1,
            },
        }
        window: dict[str, object] = {
            "name": name,
            "start": f"d{test_day:02d}",
            "end": f"d{test_day:02d}",
            "status": status,
            "phases": phases,
        }
        if candidate:
            window.update({"candidate": candidate, "window": name, "selection_rank": 1})
        windows.append(window)
    payload: dict[str, object] = {
        "artifact_type": (
            "candidate_walk_forward_report" if candidate else "walk_forward_report"
        ),
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
        "status": status,
        "window_count": window_count,
        "windows": windows,
    }
    if candidate:
        payload.update(
            {
                "candidate_count": 1,
                "selected_candidate": candidate,
                "best_candidate": candidate,
                "selections": [
                    {"candidate": candidate, "window": str(window["window"]), "rank": 1}
                    for window in windows
                ],
                "summaries": [
                    {
                        "candidate": candidate,
                        "status": status,
                        "window_count": window_count,
                        "pass_count": window_count if status == "PASS" else 0,
                        "watch_count": window_count if status == "WATCH" else 0,
                        "block_count": window_count if status == "BLOCK" else 0,
                        "positive_return_ratio": 1.0,
                        "worst_total_return": 0.01,
                        "worst_max_drawdown": 0.02,
                    }
                ],
            }
        )
    return payload


def selection_safe_robustness_payload(*, status: str = "PASS") -> dict[str, object]:
    scenario_names = (
        "baseline",
        "holdings_low",
        "holdings_high",
        "max_weight_low",
        "rebalance_alt",
        "high_cost",
    )
    folds: list[dict[str, object]] = []
    for index in range(3):
        train_end = 2 + index * 3
        selection_day = train_end + 1
        test_day = selection_day + 1
        name = f"wf_{index + 1:02d}"
        phases = {
            "name": name,
            "mode": "expanding",
            "train": {
                "start": "d01",
                "end": f"d{train_end:02d}",
                "trading_day_count": train_end,
            },
            "purge": {"start": "", "end": "", "trading_day_count": 0},
            "selection": {
                "start": f"d{selection_day:02d}",
                "end": f"d{selection_day:02d}",
                "trading_day_count": 1,
            },
            "embargo": {"start": "", "end": "", "trading_day_count": 0},
            "test": {
                "start": f"d{test_day:02d}",
                "end": f"d{test_day:02d}",
                "trading_day_count": 1,
            },
        }
        folds.append(
            {
                "name": name,
                "start": f"d{test_day:02d}",
                "end": f"d{test_day:02d}",
                "status": status,
                "evaluation_phase": "test",
                "scenario_count": len(scenario_names),
                "phases": phases,
                "scenarios": [
                    {"name": scenario_name, "status": status}
                    for scenario_name in scenario_names
                ],
            }
        )
    return {
        "artifact_type": "robustness_report",
        "schema_version": 2,
        "selection_protocol": "quantify.robustness-selection.v2",
        "selection_safe": True,
        "test_used_for_selection": False,
        "scenario_matrix_frozen": True,
        "configuration": {
            "mode": "expanding",
            "train_days": 2,
            "purge_days": 0,
            "selection_days": 1,
            "embargo_days": 0,
            "test_days": 1,
            "step_days": 1,
        },
        "fold_count": len(folds),
        "folds": folds,
        "scenario_count": len(scenario_names),
        "scenario_matrix": [{"name": name} for name in scenario_names],
        "baseline_scenario": "baseline",
        "baseline": {},
        "status": status,
        "scenarios": [
            {"name": name, "status": status, "fold_count": len(folds)}
            for name in scenario_names
        ],
    }
