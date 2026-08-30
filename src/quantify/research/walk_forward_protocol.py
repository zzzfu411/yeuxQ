"""Selection-safe rolling-origin schedules for time-series validation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

WalkForwardMode = Literal["expanding", "rolling"]

SELECTION_PROTOCOL = "quantify.walk-forward-selection.v2"
SELECTION_SCHEMA_VERSION = 2
WALK_FORWARD_ARTIFACT = "walk_forward_report"
CANDIDATE_WALK_FORWARD_ARTIFACT = "candidate_walk_forward_report"
ROBUSTNESS_ARTIFACT = "robustness_report"
ROBUSTNESS_SELECTION_PROTOCOL = "quantify.robustness-selection.v2"
ROBUSTNESS_REQUIRED_SCENARIOS = (
    "baseline",
    "holdings_low",
    "holdings_high",
    "max_weight_low",
    "rebalance_alt",
    "high_cost",
)


@dataclass(frozen=True, slots=True)
class SelectionSafetyValidation:
    safe: bool
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"safe": self.safe, "reasons": self.reasons}


@dataclass(frozen=True, slots=True)
class WalkForwardPhase:
    """Inclusive trading-day boundaries for one protocol phase."""

    start: str
    end: str
    trading_day_count: int

    def to_dict(self) -> dict[str, str | int]:
        return {
            "start": self.start,
            "end": self.end,
            "trading_day_count": self.trading_day_count,
        }


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    """One ordered train/purge/selection/embargo/test fold."""

    name: str
    mode: WalkForwardMode
    train: WalkForwardPhase
    purge: WalkForwardPhase
    selection: WalkForwardPhase
    embargo: WalkForwardPhase
    test: WalkForwardPhase

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "mode": self.mode,
            "train": self.train.to_dict(),
            "purge": self.purge.to_dict(),
            "selection": self.selection.to_dict(),
            "embargo": self.embargo.to_dict(),
            "test": self.test.to_dict(),
        }


def build_walk_forward_folds(
    days: list[str],
    *,
    train_days: int,
    purge_days: int,
    selection_days: int,
    embargo_days: int,
    test_days: int,
    step_days: int,
    mode: WalkForwardMode,
) -> list[WalkForwardFold]:
    """Build non-overlapping test folds without consulting any observations."""
    validate_walk_forward_parameters(
        train_days=train_days,
        purge_days=purge_days,
        selection_days=selection_days,
        embargo_days=embargo_days,
        test_days=test_days,
        step_days=step_days,
        mode=mode,
    )
    ordered_days = [str(day) for day in days]
    if len(ordered_days) != len(set(ordered_days)) or ordered_days != sorted(ordered_days):
        raise ValueError("trading days must be strictly increasing.")
    folds: list[WalkForwardFold] = []
    offset = 0
    while True:
        train_start = 0 if mode == "expanding" else offset
        train_stop = train_days + offset
        purge_start = train_stop
        purge_stop = purge_start + purge_days
        selection_start = purge_stop
        selection_stop = selection_start + selection_days
        embargo_start = selection_stop
        embargo_stop = embargo_start + embargo_days
        test_start = embargo_stop
        test_stop = test_start + test_days
        if test_stop > len(ordered_days):
            break
        folds.append(
            WalkForwardFold(
                name=f"wf_{len(folds) + 1:02d}",
                mode=mode,
                train=_phase(ordered_days, train_start, train_stop),
                purge=_phase(ordered_days, purge_start, purge_stop),
                selection=_phase(ordered_days, selection_start, selection_stop),
                embargo=_phase(ordered_days, embargo_start, embargo_stop),
                test=_phase(ordered_days, test_start, test_stop),
            )
        )
        offset += step_days
    return folds


def protocol_configuration(
    *,
    train_days: int,
    purge_days: int,
    selection_days: int,
    embargo_days: int,
    test_days: int,
    step_days: int,
    mode: WalkForwardMode,
) -> dict[str, str | int]:
    return {
        "mode": mode,
        "train_days": train_days,
        "purge_days": purge_days,
        "selection_days": selection_days,
        "embargo_days": embargo_days,
        "test_days": test_days,
        "step_days": step_days,
    }


def validate_walk_forward_parameters(
    *,
    train_days: int,
    purge_days: int,
    selection_days: int,
    embargo_days: int,
    test_days: int,
    step_days: int,
    mode: str,
) -> None:
    if mode not in {"expanding", "rolling"}:
        raise ValueError("mode must be 'expanding' or 'rolling'.")
    for name, value in (
        ("train_days", train_days),
        ("selection_days", selection_days),
        ("test_days", test_days),
        ("step_days", step_days),
    ):
        if value <= 0:
            raise ValueError(f"{name} must be positive.")
    for name, value in (("purge_days", purge_days), ("embargo_days", embargo_days)):
        if value < 0:
            raise ValueError(f"{name} must be non-negative.")
    if step_days < test_days:
        raise ValueError("step_days must be greater than or equal to test_days.")


def validate_selection_safe_payload(
    payload: dict[str, Any],
    *,
    artifact_type: str,
) -> SelectionSafetyValidation:
    """Verify the complete v2 envelope instead of trusting a bare boolean."""
    reasons: list[str] = []
    if payload.get("artifact_type") != artifact_type:
        reasons.append(f"artifact_type must be {artifact_type}.")
    if payload.get("schema_version") != SELECTION_SCHEMA_VERSION:
        reasons.append(f"schema_version must be {SELECTION_SCHEMA_VERSION}.")
    if payload.get("selection_protocol") != SELECTION_PROTOCOL:
        reasons.append(f"selection_protocol must be {SELECTION_PROTOCOL}.")
    if payload.get("selection_safe") is not True:
        reasons.append("selection_safe must be exactly true.")
    if payload.get("test_used_for_selection") is not False:
        reasons.append("test_used_for_selection must be exactly false.")
    configuration = payload.get("configuration")
    if not isinstance(configuration, dict):
        reasons.append("configuration must be an object.")
        configuration = {}
    _validate_configuration(configuration, reasons)
    windows = payload.get("windows")
    if not isinstance(windows, list):
        reasons.append("windows must be a list.")
        windows = []
    window_count = _strict_int(payload.get("window_count"))
    if window_count is None or window_count != len(windows):
        reasons.append("window_count must equal the number of windows.")
    _validate_windows(windows, configuration, reasons)
    if artifact_type == CANDIDATE_WALK_FORWARD_ARTIFACT:
        _validate_candidate_lock(payload, windows, reasons)
    return SelectionSafetyValidation(safe=not reasons, reasons=reasons)


def validate_robustness_selection_safe_payload(
    payload: dict[str, Any],
) -> SelectionSafetyValidation:
    """Verify the complete frozen robustness matrix and its test folds."""
    reasons: list[str] = []
    if payload.get("artifact_type") != ROBUSTNESS_ARTIFACT:
        reasons.append(f"artifact_type must be {ROBUSTNESS_ARTIFACT}.")
    if payload.get("schema_version") != SELECTION_SCHEMA_VERSION:
        reasons.append(f"schema_version must be {SELECTION_SCHEMA_VERSION}.")
    if payload.get("selection_protocol") != ROBUSTNESS_SELECTION_PROTOCOL:
        reasons.append(f"selection_protocol must be {ROBUSTNESS_SELECTION_PROTOCOL}.")
    if payload.get("selection_safe") is not True:
        reasons.append("selection_safe must be exactly true.")
    if payload.get("test_used_for_selection") is not False:
        reasons.append("test_used_for_selection must be exactly false.")
    if payload.get("scenario_matrix_frozen") is not True:
        reasons.append("scenario_matrix_frozen must be exactly true.")
    configuration = payload.get("configuration")
    if not isinstance(configuration, dict):
        reasons.append("configuration must be an object.")
        configuration = {}
    _validate_configuration(configuration, reasons)

    scenario_matrix = payload.get("scenario_matrix")
    if not isinstance(scenario_matrix, list):
        reasons.append("scenario_matrix must be a list.")
        scenario_matrix = []
    scenario_names = _validate_robustness_scenario_matrix(scenario_matrix, reasons)
    scenario_count = _strict_int(payload.get("scenario_count"))
    if scenario_count is None or scenario_count != len(scenario_matrix):
        reasons.append("scenario_count must equal the number of frozen scenarios.")
    missing_required = [
        name for name in ROBUSTNESS_REQUIRED_SCENARIOS if name not in scenario_names
    ]
    if missing_required:
        reasons.append(
            "scenario_matrix is missing required scenarios: "
            + ", ".join(missing_required)
            + "."
        )
    if payload.get("baseline_scenario") != "baseline":
        reasons.append("baseline_scenario must be baseline.")

    folds = payload.get("folds")
    if not isinstance(folds, list) or not folds:
        reasons.append("folds must contain locked robustness test evidence.")
        folds = []
    fold_count = _strict_int(payload.get("fold_count"))
    if fold_count is None or fold_count != len(folds):
        reasons.append("fold_count must equal the number of robustness folds.")
    _validate_windows(folds, configuration, reasons)
    _validate_robustness_folds(folds, scenario_names, reasons)

    aggregate_scenarios = payload.get("scenarios")
    if not isinstance(aggregate_scenarios, list):
        reasons.append("scenarios must contain aggregate scenario evidence.")
    else:
        aggregate_names = [
            str(item.get("name", "")) if isinstance(item, dict) else ""
            for item in aggregate_scenarios
        ]
        if aggregate_names != scenario_names:
            reasons.append("aggregate scenarios must match the frozen scenario matrix in order.")
    return SelectionSafetyValidation(safe=not reasons, reasons=reasons)


def _validate_robustness_scenario_matrix(
    scenario_matrix: list[Any],
    reasons: list[str],
) -> list[str]:
    names: list[str] = []
    for index, item in enumerate(scenario_matrix):
        label = f"scenario_matrix[{index}]"
        if not isinstance(item, dict):
            reasons.append(f"{label} must be an object.")
            names.append("")
            continue
        name = item.get("name")
        if not isinstance(name, str) or not name:
            reasons.append(f"{label}.name must be a non-empty string.")
            names.append("")
            continue
        names.append(name)
    if len(names) != len(set(names)):
        reasons.append("scenario_matrix names must be unique.")
    return names


def _validate_robustness_folds(
    folds: list[Any],
    scenario_names: list[str],
    reasons: list[str],
) -> None:
    valid_statuses = {"PASS", "WATCH", "BLOCK"}
    for index, fold in enumerate(folds):
        label = f"folds[{index}]"
        if not isinstance(fold, dict):
            continue
        if fold.get("evaluation_phase") != "test":
            reasons.append(f"{label}.evaluation_phase must be test.")
        if fold.get("status") not in valid_statuses:
            reasons.append(f"{label}.status is invalid.")
        scenarios = fold.get("scenarios")
        if not isinstance(scenarios, list):
            reasons.append(f"{label}.scenarios must be a list.")
            scenarios = []
        count = _strict_int(fold.get("scenario_count"))
        if count is None or count != len(scenarios):
            reasons.append(f"{label}.scenario_count must equal its scenario rows.")
        fold_names = [
            str(item.get("name", "")) if isinstance(item, dict) else ""
            for item in scenarios
        ]
        if fold_names != scenario_names:
            reasons.append(f"{label}.scenarios must match the frozen matrix in order.")
        for scenario_index, scenario in enumerate(scenarios):
            if not isinstance(scenario, dict):
                reasons.append(f"{label}.scenarios[{scenario_index}] must be an object.")
            elif scenario.get("status") not in valid_statuses:
                reasons.append(f"{label}.scenarios[{scenario_index}].status is invalid.")


def _validate_configuration(configuration: dict[str, Any], reasons: list[str]) -> None:
    required = (
        "mode",
        "train_days",
        "purge_days",
        "selection_days",
        "embargo_days",
        "test_days",
        "step_days",
    )
    missing = [key for key in required if key not in configuration]
    if missing:
        reasons.append("configuration is missing: " + ", ".join(missing) + ".")
        return
    values = {key: _strict_int(configuration.get(key)) for key in required if key != "mode"}
    if any(value is None for value in values.values()):
        reasons.append("configuration day counts must be integers.")
        return
    try:
        validate_walk_forward_parameters(
            train_days=values["train_days"] or 0,
            purge_days=values["purge_days"] or 0,
            selection_days=values["selection_days"] or 0,
            embargo_days=values["embargo_days"] or 0,
            test_days=values["test_days"] or 0,
            step_days=values["step_days"] or 0,
            mode=str(configuration.get("mode", "")),
        )
    except ValueError as exc:
        reasons.append(f"invalid configuration: {exc}")


def _validate_windows(
    windows: list[Any],
    configuration: dict[str, Any],
    reasons: list[str],
) -> None:
    previous_test_end = ""
    names: set[str] = set()
    for index, item in enumerate(windows, start=1):
        label = f"windows[{index - 1}]"
        if not isinstance(item, dict):
            reasons.append(f"{label} must be an object.")
            continue
        name = str(item.get("window") or item.get("name") or "")
        if not name or name in names:
            reasons.append(f"{label} must have a unique window name.")
        names.add(name)
        phases = item.get("phases")
        if not isinstance(phases, dict):
            reasons.append(f"{label}.phases must be an object.")
            continue
        if phases.get("name") != name:
            reasons.append(f"{label}.phases.name must match the window name.")
        if phases.get("mode") != configuration.get("mode"):
            reasons.append(f"{label}.phases.mode must match configuration.mode.")
        phase_rows = []
        for phase_name in ("train", "purge", "selection", "embargo", "test"):
            phase = phases.get(phase_name)
            if not isinstance(phase, dict):
                reasons.append(f"{label}.phases.{phase_name} must be an object.")
                phase = {}
            phase_rows.append((phase_name, phase))
            _validate_phase_count(label, phase_name, phase, configuration, reasons)
        nonempty = [
            (phase_name, str(phase.get("start", "")), str(phase.get("end", "")))
            for phase_name, phase in phase_rows
            if _strict_int(phase.get("trading_day_count")) not in {None, 0}
        ]
        for (left_name, _left_start, left_end), (right_name, right_start, _right_end) in zip(
            nonempty,
            nonempty[1:],
            strict=False,
        ):
            if not left_end or not right_start or left_end >= right_start:
                reasons.append(f"{label} phases {left_name} and {right_name} overlap or are unordered.")
        test = phases.get("test", {}) if isinstance(phases.get("test"), dict) else {}
        test_start = str(test.get("start", ""))
        test_end = str(test.get("end", ""))
        if item.get("start") != test_start or item.get("end") != test_end:
            reasons.append(f"{label} legacy start/end must match phases.test.")
        if previous_test_end and (not test_start or previous_test_end >= test_start):
            reasons.append(f"{label} test window overlaps or precedes the prior test window.")
        previous_test_end = test_end


def _validate_phase_count(
    label: str,
    phase_name: str,
    phase: dict[str, Any],
    configuration: dict[str, Any],
    reasons: list[str],
) -> None:
    count = _strict_int(phase.get("trading_day_count"))
    expected = _strict_int(configuration.get(f"{phase_name}_days"))
    if count is None or count < 0:
        reasons.append(f"{label}.phases.{phase_name}.trading_day_count is invalid.")
        return
    if phase_name == "train" and configuration.get("mode") == "expanding":
        if expected is not None and count < expected:
            reasons.append(f"{label}.phases.train is shorter than train_days.")
    elif expected is not None and count != expected:
        reasons.append(f"{label}.phases.{phase_name} count does not match configuration.")
    start = str(phase.get("start", ""))
    end = str(phase.get("end", ""))
    if count == 0 and (start or end):
        reasons.append(f"{label}.phases.{phase_name} must have empty boundaries when count is zero.")
    if count > 0 and (not start or not end or start > end):
        reasons.append(f"{label}.phases.{phase_name} boundaries are invalid.")


def _validate_candidate_lock(
    payload: dict[str, Any],
    windows: list[Any],
    reasons: list[str],
) -> None:
    selections = payload.get("selections")
    if not isinstance(selections, list):
        reasons.append("selections must be a list for candidate walk-forward reports.")
        return
    candidate_count = _strict_int(payload.get("candidate_count"))
    if candidate_count is None or candidate_count <= 0:
        reasons.append("candidate_count must be a positive integer.")
        return
    if len(selections) != candidate_count * len(windows):
        reasons.append("selections must contain one ranked candidate set per test fold.")
    for item in windows:
        if not isinstance(item, dict):
            continue
        window_name = str(item.get("window", ""))
        rows = [
            row
            for row in selections
            if isinstance(row, dict) and str(row.get("window", "")) == window_name
        ]
        raw_ranks = [_strict_int(row.get("rank")) for row in rows]
        if any(rank is None for rank in raw_ranks):
            reasons.append(f"{window_name} selection ranks must be integers.")
            continue
        ranks = sorted(rank for rank in raw_ranks if rank is not None)
        if ranks != list(range(1, candidate_count + 1)):
            reasons.append(f"{window_name} selection ranks must cover 1..candidate_count.")
            continue
        locked = next((row for row in rows if row.get("rank") == 1), None)
        if not locked or locked.get("candidate") != item.get("candidate"):
            reasons.append(f"{window_name} test candidate must match the pretest rank-1 candidate.")
        if item.get("selection_rank") != 1:
            reasons.append(f"{window_name} selection_rank must be 1.")
    if windows:
        latest = windows[-1] if isinstance(windows[-1], dict) else {}
        selected = payload.get("selected_candidate")
        if not selected or selected != latest.get("candidate"):
            reasons.append("selected_candidate must match the latest pretest-locked candidate.")
        if payload.get("best_candidate") != selected:
            reasons.append("best_candidate must be the locked selected_candidate compatibility alias.")


def _strict_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _phase(days: list[str], start: int, stop: int) -> WalkForwardPhase:
    values = days[start:stop]
    if not values:
        return WalkForwardPhase(start="", end="", trading_day_count=0)
    return WalkForwardPhase(
        start=values[0],
        end=values[-1],
        trading_day_count=len(values),
    )
