"""Paper daily review artifacts derived from a research report directory."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import pandas as pd


@dataclass(frozen=True, slots=True)
class PaperDailyState:
    as_of: str
    observed_days: int
    last_equity: float
    cash_estimate: float
    position_count: int
    order_count: int
    rejected_order_count: int
    broker_connection: str = "none"

    def to_dict(self) -> dict[str, str | int | float]:
        return {
            "as_of": self.as_of,
            "observed_days": self.observed_days,
            "last_equity": self.last_equity,
            "cash_estimate": self.cash_estimate,
            "position_count": self.position_count,
            "order_count": self.order_count,
            "rejected_order_count": self.rejected_order_count,
            "broker_connection": self.broker_connection,
        }

    @property
    def status(self) -> str:
        if self.broker_connection not in {"", "none"}:
            return "BLOCK"
        if self.rejected_order_count > 0:
            return "WATCH"
        return "PASS"

    def to_markdown(self) -> str:
        payload = self.review_payload()
        return _review_markdown(payload)

    def review_payload(self) -> dict[str, object]:
        reject_rate = self.rejected_order_count / self.order_count if self.order_count else 0.0
        return {
            "status": self.status,
            "as_of": self.as_of,
            "state": self.to_dict(),
            "execution_quality": {
                "order_count": self.order_count,
                "rejected_order_count": self.rejected_order_count,
                "reject_rate": reject_rate,
            },
            "target_deviation": {
                "max_abs_target_deviation": 0.0,
                "max_deviation_symbol": "",
            },
            "manual_review_questions": [
                "Confirm this paper daily artifact came from local research or paper simulation only.",
                "Confirm rejected orders are understood before any paper promotion.",
            ],
            "prohibited_actions": [
                "Do not submit unattended live broker orders from paper artifacts.",
                "Do not treat a clean paper day as permission to increase capital.",
            ],
        }


def _review_markdown(payload: dict[str, object]) -> str:
    state = payload["state"]
    assert isinstance(state, dict)
    execution = payload["execution_quality"]
    assert isinstance(execution, dict)
    return (
        f"# Paper Daily Review: {payload['status']}\n\n"
        f"- As of: `{state.get('as_of', '')}`\n"
        f"- Observed days: {state.get('observed_days', 0)}\n"
        f"- Last equity: {float(state.get('last_equity', 0.0) or 0.0):.2f}\n"
        f"- Cash estimate: {float(state.get('cash_estimate', 0.0) or 0.0):.2f}\n"
        f"- Position count: {state.get('position_count', 0)}\n"
        f"- Orders: {state.get('order_count', 0)}\n"
        f"- Rejected orders: {state.get('rejected_order_count', 0)}\n"
        f"- Broker connection: `{state.get('broker_connection', '')}`\n\n"
        "## Execution Quality\n"
        f"- Reject rate: {float(execution.get('reject_rate', 0.0) or 0.0):.2%}\n\n"
        "## Manual Review Questions\n"
        + "".join(f"- {item}\n" for item in payload.get("manual_review_questions", []))
        + "\n## Prohibited Actions\n"
        + "".join(f"- {item}\n" for item in payload.get("prohibited_actions", []))
        + "\n"
        "This is a paper-trading review artifact only. It does not connect to a real broker.\n"
    )


def write_paper_daily_review(report_dir: str | Path, output_dir: str | Path | None = None) -> Path:
    root = Path(report_dir)
    out = Path(output_dir) if output_dir else root
    out.mkdir(parents=True, exist_ok=True)
    if (root / "paper_state.json").exists() and (root / "paper_daily.csv").exists():
        return _write_loop_daily_review(root, out)

    equity = _read_csv(root / "equity.csv")
    positions = _read_csv(root / "positions.csv")
    orders = _read_csv(root / "orders.csv")

    as_of = _last_value(equity, "timestamp") or _last_value(positions, "date") or ""
    latest_positions = _latest_positions(positions, as_of)
    last_equity = _last_float(equity, "equity")
    market_value = (
        float(pd.to_numeric(latest_positions.get("market_value", pd.Series(dtype=float))).sum())
        if not latest_positions.empty
        else 0.0
    )
    rejected_count = _rejected_order_count(orders)
    state = PaperDailyState(
        as_of=as_of,
        observed_days=len(equity),
        last_equity=last_equity,
        cash_estimate=last_equity - market_value,
        position_count=len(latest_positions),
        order_count=len(orders),
        rejected_order_count=rejected_count,
    )

    (out / "paper_state.json").write_text(
        json.dumps(state.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    latest_positions.to_csv(out / "paper_positions.csv", index=False)
    orders.to_csv(out / "paper_orders.csv", index=False)
    (out / "paper_daily_review.json").write_text(
        json.dumps(state.review_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out / "paper_daily_review.md").write_text(state.to_markdown(), encoding="utf-8")
    return out


def _write_loop_daily_review(root: Path, out: Path) -> Path:
    state_payload = _read_json(root / "paper_state.json")
    daily = _read_csv(root / "paper_daily.csv")
    orders = _read_csv(root / "paper_orders.csv")
    positions = _read_csv(root / "paper_positions.csv")
    latest = daily.iloc[-1].to_dict() if not daily.empty else {}
    as_of = str(state_payload.get("as_of") or latest.get("date") or "")
    latest_positions = _latest_positions(positions, as_of)
    latest_orders = _orders_on_date(orders, as_of)
    latest_rejected = _rejected_order_count(latest_orders)
    total_orders = len(orders)
    total_rejected = _rejected_order_count(orders)
    reject_rate = total_rejected / total_orders if total_orders else 0.0
    broker_connection = str(state_payload.get("broker_connection", "none"))
    max_deviation = float(latest.get("max_abs_target_deviation", 0.0) or 0.0)
    status = _loop_review_status(
        broker_connection=broker_connection,
        latest_rejected_count=latest_rejected,
        cumulative_reject_rate=reject_rate,
        max_target_deviation=max_deviation,
    )
    payload = {
        "status": status,
        "as_of": as_of,
        "candidate": state_payload.get("candidate", ""),
        "state": state_payload,
        "latest_day": latest,
        "execution_quality": {
            "order_count": total_orders,
            "rejected_order_count": total_rejected,
            "reject_rate": reject_rate,
            "latest_order_count": len(latest_orders),
            "latest_rejected_order_count": latest_rejected,
            "latest_rejected_reasons": _rejected_reason_counts(latest_orders),
            "cumulative_rejected_reasons": _rejected_reason_counts(orders),
        },
        "target_deviation": {
            "target_count": int(latest.get("target_count", 0) or 0),
            "target_weight_sum": float(latest.get("target_weight_sum", 0.0) or 0.0),
            "max_abs_target_deviation": max_deviation,
            "max_deviation_symbol": str(latest.get("max_deviation_symbol", "") or ""),
            "actual_weight": float(latest.get("max_deviation_actual_weight", 0.0) or 0.0),
            "target_weight": float(latest.get("max_deviation_target_weight", 0.0) or 0.0),
        },
        "top_positions": _top_positions(latest_positions),
        "manual_review_questions": _loop_review_questions(
            latest=latest,
            latest_rejected_count=latest_rejected,
            cumulative_reject_rate=reject_rate,
            max_target_deviation=max_deviation,
        ),
        "prohibited_actions": [
            "Do not submit unattended live broker orders from paper artifacts.",
            "Do not treat a clean paper day as permission to increase capital.",
            "Do not let LLM advisory text change deterministic paper/readiness gates.",
        ],
    }

    _copy_if_exists(root / "paper_state.json", out / "paper_state.json")
    _copy_frame(daily, out / "paper_daily.csv")
    _copy_frame(orders, out / "paper_orders.csv")
    _copy_frame(latest_positions, out / "paper_positions.csv")
    (out / "paper_daily_review.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out / "paper_daily_review.md").write_text(_loop_review_markdown(payload), encoding="utf-8")
    return out


def _loop_review_status(
    *,
    broker_connection: str,
    latest_rejected_count: int,
    cumulative_reject_rate: float,
    max_target_deviation: float,
) -> str:
    if broker_connection not in {"", "none"}:
        return "BLOCK"
    if latest_rejected_count > 0 or cumulative_reject_rate >= 0.10 or max_target_deviation >= 0.02:
        return "WATCH"
    return "PASS"


def _loop_review_questions(
    *,
    latest: dict,
    latest_rejected_count: int,
    cumulative_reject_rate: float,
    max_target_deviation: float,
) -> list[str]:
    questions = ["Confirm the paper loop did not connect to a real broker."]
    if not bool(latest.get("rebalanced", False)):
        questions.append("No rebalance was scheduled today; confirm positions and cash still reconciled.")
    if latest_rejected_count:
        questions.append("Explain each latest rejected order before the next rebalance.")
    if cumulative_reject_rate >= 0.10:
        questions.append("Reduce target weights or add cash buffers before treating execution as stable.")
    if max_target_deviation >= 0.02:
        questions.append("Explain the largest target-vs-actual weight deviation.")
    return questions


def _loop_review_markdown(payload: dict) -> str:
    state = payload["state"]
    latest = payload.get("latest_day", {})
    execution = payload.get("execution_quality", {})
    deviation = payload.get("target_deviation", {})
    lines = [
        f"# Paper Loop Daily Review: {payload['status']}",
        "",
        f"- As of: `{payload['as_of']}`",
        f"- Candidate: `{payload.get('candidate', '') or 'unknown'}`",
        f"- Observed days: {state.get('observed_days', 0)}",
        f"- Cash: {float(state.get('cash', 0.0) or 0.0):.2f}",
        f"- Last equity: {float(state.get('last_equity', 0.0) or 0.0):.2f}",
        f"- Position count: {state.get('position_count', 0)}",
        f"- Broker connection: `{state.get('broker_connection', '')}`",
        "",
        "## Latest Day",
        f"- Rebalanced: `{bool(latest.get('rebalanced', False))}`",
        f"- Orders: {int(latest.get('order_count', 0) or 0)}",
        f"- Rejected orders: {int(latest.get('rejected_order_count', 0) or 0)}",
        f"- Turnover rate: {float(latest.get('turnover_rate', 0.0) or 0.0):.2%}",
        "",
        "## Execution Quality",
        f"- Cumulative orders: {execution.get('order_count', 0)}",
        f"- Cumulative rejected orders: {execution.get('rejected_order_count', 0)}",
        f"- Cumulative reject rate: {float(execution.get('reject_rate', 0.0) or 0.0):.2%}",
        f"- Latest rejected reasons: {_format_counts(execution.get('latest_rejected_reasons', {}))}",
        f"- Cumulative rejected reasons: {_format_counts(execution.get('cumulative_rejected_reasons', {}))}",
        "",
        "## Target Deviation",
        f"- Target count: {deviation.get('target_count', 0)}",
        f"- Target weight sum: {float(deviation.get('target_weight_sum', 0.0) or 0.0):.2%}",
        f"- Max absolute deviation: {float(deviation.get('max_abs_target_deviation', 0.0) or 0.0):.2%}",
        f"- Max deviation symbol: `{deviation.get('max_deviation_symbol', '') or 'none'}`",
        "",
        "## Top Positions",
    ]
    positions = payload.get("top_positions", [])
    if positions:
        for row in positions:
            lines.append(
                "- "
                f"`{row.get('symbol', '')}` qty={int(row.get('quantity', 0) or 0)} "
                f"weight={float(row.get('weight', 0.0) or 0.0):.2%}"
            )
    else:
        lines.append("- None.")
    lines.extend(["", "## Manual Review Questions"])
    lines.extend(f"- {item}" for item in payload.get("manual_review_questions", []))
    lines.extend(["", "## Prohibited Actions"])
    lines.extend(f"- {item}" for item in payload.get("prohibited_actions", []))
    return "\n".join(lines) + "\n"


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _copy_if_exists(src: Path, dst: Path) -> None:
    if src.exists():
        dst.write_bytes(src.read_bytes())


def _copy_frame(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False)


def _last_value(frame: pd.DataFrame, column: str) -> str:
    if frame.empty or column not in frame:
        return ""
    return str(frame[column].iloc[-1])[:10]


def _last_float(frame: pd.DataFrame, column: str) -> float:
    if frame.empty or column not in frame:
        return 0.0
    return float(pd.to_numeric(frame[column], errors="coerce").iloc[-1])


def _latest_positions(positions: pd.DataFrame, as_of: str) -> pd.DataFrame:
    if positions.empty:
        return positions
    date_col = "date" if "date" in positions else None
    if date_col is None:
        return positions
    latest_date = as_of or str(positions[date_col].iloc[-1])
    return positions[positions[date_col].astype(str).str[:10] == latest_date].copy()


def _orders_on_date(orders: pd.DataFrame, as_of: str) -> pd.DataFrame:
    if orders.empty or not as_of:
        return pd.DataFrame(columns=orders.columns)
    date_col = "timestamp" if "timestamp" in orders else "date" if "date" in orders else None
    if date_col is None:
        return pd.DataFrame(columns=orders.columns)
    return orders[orders[date_col].astype(str).str[:10] == as_of].copy()


def _rejected_order_count(orders: pd.DataFrame) -> int:
    if orders.empty or "status" not in orders:
        return 0
    return int((orders["status"].astype(str).str.lower() == "rejected").sum())


def _rejected_reason_counts(orders: pd.DataFrame) -> dict[str, int]:
    if orders.empty or "status" not in orders:
        return {}
    rejected = orders[orders["status"].astype(str).str.lower() == "rejected"]
    if rejected.empty:
        return {}
    if "reason" not in rejected:
        return {"unknown": len(rejected)}
    counts = rejected["reason"].fillna("").astype(str).replace("", "unknown").value_counts()
    return {str(key): int(value) for key, value in counts.sort_index().items()}


def _top_positions(positions: pd.DataFrame) -> list[dict[str, object]]:
    if positions.empty:
        return []
    frame = positions.copy()
    if "weight" in frame:
        frame["weight"] = pd.to_numeric(frame["weight"], errors="coerce").fillna(0.0)
        frame = frame.sort_values("weight", ascending=False)
    return frame.head(10).to_dict("records")


def _format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in counts.items())
