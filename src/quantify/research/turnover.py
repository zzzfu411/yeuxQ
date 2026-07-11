"""Turnover evidence helpers for research reports."""
from __future__ import annotations

from typing import Any


def summarize_turnover(turnover_rows: list[dict[str, Any]]) -> dict[str, float | int]:
    """Split initial deployment turnover from recurring maintenance turnover."""
    values = [
        _float(row.get("turnover_pct"))
        for row in turnover_rows
        if isinstance(row, dict) and row.get("turnover_pct") is not None
    ]
    maintenance = values[1:] if len(values) > 1 else []
    return {
        "turnover_observation_count": len(values),
        "initial_turnover_pct": values[0] if values else 0.0,
        "avg_turnover_pct": sum(values) / len(values) if values else 0.0,
        "maintenance_turnover_observation_count": len(maintenance),
        "avg_maintenance_turnover_pct": sum(maintenance) / len(maintenance) if maintenance else 0.0,
        "max_maintenance_turnover_pct": max(maintenance) if maintenance else 0.0,
    }


def _float(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
