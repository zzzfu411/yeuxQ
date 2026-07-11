"""Stability review for continuous paper-trading runs."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd

PaperStabilityStatus = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class PaperStabilityFinding:
    severity: PaperStabilityStatus
    code: str
    message: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class PaperStabilityReport:
    status: PaperStabilityStatus
    paper_dir: str
    observed_days: int
    rebalanced_days: int
    total_return: float
    max_drawdown: float
    worst_daily_return: float
    reject_rate: float
    broker_connection: str
    latest_date: str
    findings: list[PaperStabilityFinding]
    metrics: dict[str, Any]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "paper_dir": self.paper_dir,
            "observed_days": self.observed_days,
            "rebalanced_days": self.rebalanced_days,
            "total_return": self.total_return,
            "max_drawdown": self.max_drawdown,
            "worst_daily_return": self.worst_daily_return,
            "reject_rate": self.reject_rate,
            "broker_connection": self.broker_connection,
            "latest_date": self.latest_date,
            "findings": [finding.to_dict() for finding in self.findings],
            "metrics": self.metrics,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Paper Stability Review: {self.status}",
            "",
            f"- Paper directory: `{self.paper_dir}`",
            f"- Latest date: `{self.latest_date or 'missing'}`",
            f"- Observed days: {self.observed_days}",
            f"- Rebalanced days: {self.rebalanced_days}",
            f"- Total return: {self.total_return:.2%}",
            f"- Max drawdown: {self.max_drawdown:.2%}",
            f"- Worst daily return: {self.worst_daily_return:.2%}",
            f"- Reject rate: {self.reject_rate:.2%}",
            f"- Broker connection: `{self.broker_connection}`",
            "",
            "## Findings",
        ]
        if self.findings:
            for finding in self.findings:
                evidence = ", ".join(f"{key}={value}" for key, value in finding.evidence.items())
                lines.append(f"- `{finding.severity}` `{finding.code}`: {finding.message} ({evidence or 'n/a'})")
        else:
            lines.append("- No paper-stability findings.")
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {action}" for action in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def evaluate_paper_stability(
    paper_dir: str | Path,
    *,
    min_observed_days: int = 20,
    target_observed_days: int = 40,
    max_drawdown_watch: float = 0.10,
    max_drawdown_block: float = 0.15,
    max_reject_rate_watch: float = 0.10,
    max_reject_rate_block: float = 0.20,
    max_single_day_loss: float = 0.05,
) -> PaperStabilityReport:
    root = Path(paper_dir)
    state = _read_json(root / "paper_state.json")
    daily = _read_csv(root / "paper_daily.csv")
    orders = _read_csv(root / "paper_orders.csv")
    findings: list[PaperStabilityFinding] = []

    if not state:
        findings.append(PaperStabilityFinding("BLOCK", "MISSING_PAPER_STATE", "paper_state.json is missing.", {}))
    if daily.empty:
        findings.append(PaperStabilityFinding("BLOCK", "MISSING_PAPER_DAILY", "paper_daily.csv is missing.", {}))

    broker_connection = str(state.get("broker_connection", "none") if state else "missing")
    if broker_connection not in {"", "none"}:
        findings.append(
            PaperStabilityFinding(
                "BLOCK",
                "BROKER_CONNECTED",
                "Paper run reports a broker connection.",
                {"broker_connection": broker_connection},
            )
        )

    metrics = _metrics(daily, orders)
    observed_days = int(metrics["observed_days"])
    rebalanced_days = int(metrics["rebalanced_days"])
    state_observed_days = int(state.get("observed_days", 0) or 0) if state else 0
    if state and state_observed_days != observed_days:
        findings.append(
            PaperStabilityFinding(
                "BLOCK",
                "PAPER_STATE_DAILY_MISMATCH",
                "paper_state observed_days does not match paper_daily.csv rows.",
                {"state_observed_days": state_observed_days, "daily_observed_days": observed_days},
            )
        )
    state_as_of = str(state.get("as_of", "") or "") if state else ""
    latest_date = str(metrics.get("latest_date", "") or "")
    if state_as_of and latest_date and state_as_of[:10] != latest_date[:10]:
        findings.append(
            PaperStabilityFinding(
                "BLOCK",
                "PAPER_STATE_DATE_MISMATCH",
                "paper_state as_of does not match the latest paper_daily.csv date.",
                {"state_as_of": state_as_of[:10], "latest_daily_date": latest_date[:10]},
            )
        )
    state_order_count = int(state.get("order_count", 0) or 0) if state else 0
    state_rejected_count = int(state.get("rejected_order_count", 0) or 0) if state else 0
    if state and (
        state_order_count != int(metrics.get("order_count", 0) or 0)
        or state_rejected_count != int(metrics.get("rejected_order_count", 0) or 0)
    ):
        findings.append(
            PaperStabilityFinding(
                "BLOCK",
                "PAPER_STATE_ORDER_MISMATCH",
                "paper_state order counts do not match paper_orders.csv.",
                {
                    "state_order_count": state_order_count,
                    "orders_file_count": metrics.get("order_count", 0),
                    "state_rejected_order_count": state_rejected_count,
                    "orders_file_rejected_count": metrics.get("rejected_order_count", 0),
                },
            )
        )
    candidate_count = int(metrics.get("candidate_count", 0) or 0)
    if candidate_count > 1:
        findings.append(
            PaperStabilityFinding(
                "BLOCK",
                "MIXED_PAPER_DAILY_CANDIDATES",
                "paper_daily.csv contains multiple candidate strategies.",
                {
                    "candidate_count": candidate_count,
                    "candidate_examples": metrics.get("candidate_examples", []),
                },
            )
        )
    state_candidate = str(state.get("candidate", "") or "") if state else ""
    daily_candidate = str((metrics.get("candidate_examples") or [""])[0] or "")
    if state_candidate and daily_candidate and candidate_count == 1 and state_candidate != daily_candidate:
        findings.append(
            PaperStabilityFinding(
                "BLOCK",
                "PAPER_STATE_CANDIDATE_MISMATCH",
                "paper_state candidate does not match paper_daily.csv candidate.",
                {"state_candidate": state_candidate, "daily_candidate": daily_candidate},
            )
        )
    if int(metrics.get("duplicate_date_count", 0) or 0):
        findings.append(
            PaperStabilityFinding(
                "BLOCK",
                "DUPLICATE_PAPER_DAILY_DATES",
                "paper_daily.csv contains duplicate dates.",
                {
                    "duplicate_date_count": metrics["duplicate_date_count"],
                    "examples": metrics.get("duplicate_date_examples", []),
                },
            )
        )
    if int(metrics.get("large_calendar_gap_count", 0) or 0):
        findings.append(
            PaperStabilityFinding(
                "WATCH",
                "PAPER_DAILY_GAPS",
                "paper_daily.csv has large calendar gaps; confirm holidays or missing paper runs.",
                {
                    "large_calendar_gap_count": metrics["large_calendar_gap_count"],
                    "examples": metrics.get("large_calendar_gap_examples", []),
                },
            )
        )
    if observed_days < min_observed_days:
        findings.append(
            PaperStabilityFinding(
                "BLOCK",
                "TOO_FEW_OBSERVED_DAYS",
                f"Paper run needs at least {min_observed_days} observed days.",
                {"observed_days": observed_days, "min_observed_days": min_observed_days},
            )
        )
    elif observed_days < target_observed_days:
        findings.append(
            PaperStabilityFinding(
                "WATCH",
                "SHORT_OBSERVATION_WINDOW",
                f"Paper run is shorter than the {target_observed_days}-day target.",
                {"observed_days": observed_days, "target_observed_days": target_observed_days},
            )
        )
    if rebalanced_days <= 0 and observed_days:
        findings.append(
            PaperStabilityFinding(
                "WATCH",
                "NO_REBALANCE_OBSERVED",
                "No rebalance day has been observed in the paper run.",
                {"rebalanced_days": rebalanced_days},
            )
        )
    if float(metrics["max_drawdown"]) >= max_drawdown_block:
        findings.append(
            PaperStabilityFinding(
                "BLOCK",
                "PAPER_DRAWDOWN_BLOCK",
                "Paper max drawdown exceeds the block threshold.",
                {"max_drawdown": metrics["max_drawdown"], "threshold": max_drawdown_block},
            )
        )
    elif float(metrics["max_drawdown"]) >= max_drawdown_watch:
        findings.append(
            PaperStabilityFinding(
                "WATCH",
                "PAPER_DRAWDOWN_WATCH",
                "Paper max drawdown is elevated.",
                {"max_drawdown": metrics["max_drawdown"], "threshold": max_drawdown_watch},
            )
        )
    if float(metrics["reject_rate"]) >= max_reject_rate_block:
        findings.append(
            PaperStabilityFinding(
                "BLOCK",
                "PAPER_REJECT_RATE_BLOCK",
                "Paper reject rate exceeds the block threshold.",
                {"reject_rate": metrics["reject_rate"], "threshold": max_reject_rate_block},
            )
        )
    elif float(metrics["reject_rate"]) >= max_reject_rate_watch:
        findings.append(
            PaperStabilityFinding(
                "WATCH",
                "PAPER_REJECT_RATE_WATCH",
                "Paper reject rate is elevated.",
                {"reject_rate": metrics["reject_rate"], "threshold": max_reject_rate_watch},
            )
        )
    if float(metrics["worst_daily_return"]) <= -max_single_day_loss:
        findings.append(
            PaperStabilityFinding(
                "WATCH",
                "LARGE_SINGLE_DAY_LOSS",
                "Paper run has a large single-day loss.",
                {"worst_daily_return": metrics["worst_daily_return"], "threshold": -max_single_day_loss},
            )
        )

    return PaperStabilityReport(
        status=_combine([finding.severity for finding in findings]),
        paper_dir=str(root),
        observed_days=observed_days,
        rebalanced_days=rebalanced_days,
        total_return=float(metrics["total_return"]),
        max_drawdown=float(metrics["max_drawdown"]),
        worst_daily_return=float(metrics["worst_daily_return"]),
        reject_rate=float(metrics["reject_rate"]),
        broker_connection=broker_connection,
        latest_date=str(metrics["latest_date"]),
        findings=findings,
        metrics=metrics,
        prohibited_actions=[
            "Do not treat paper stability PASS as permission for live trading.",
            "Do not connect a real broker from paper artifacts.",
            "Do not increase capital without a new review and approval record.",
            "Do not ignore data audit, robustness, LLM review, or human approval gates.",
        ],
    )


def write_paper_stability_report(report: PaperStabilityReport, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "paper_stability.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "paper_stability.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def missing_paper_stability_report(paper_dir: str | Path = "") -> PaperStabilityReport:
    finding = PaperStabilityFinding(
        "BLOCK",
        "MISSING_CONTINUOUS_PAPER_RUN",
        "No continuous paper state directory was provided for stability review.",
        {"paper_dir": str(paper_dir)},
    )
    return PaperStabilityReport(
        status="BLOCK",
        paper_dir=str(paper_dir),
        observed_days=0,
        rebalanced_days=0,
        total_return=0.0,
        max_drawdown=0.0,
        worst_daily_return=0.0,
        reject_rate=0.0,
        broker_connection="missing",
        latest_date="",
        findings=[finding],
        metrics={
            "observed_days": 0,
            "rebalanced_days": 0,
            "total_return": 0.0,
            "max_drawdown": 0.0,
            "worst_daily_return": 0.0,
            "reject_rate": 0.0,
            "latest_date": "",
            "order_count": 0,
            "rejected_order_count": 0,
        },
        prohibited_actions=[
            "Do not treat a missing paper run as micro-live readiness evidence.",
            "Run a continuous paper loop for 4-8 weeks before promotion discussion.",
            "Do not connect a real broker from paper artifacts.",
        ],
    )


def _metrics(daily: pd.DataFrame, orders: pd.DataFrame) -> dict[str, Any]:
    if daily.empty or "equity" not in daily:
        return {
            "observed_days": 0,
            "rebalanced_days": 0,
            "total_return": 0.0,
            "max_drawdown": 0.0,
            "worst_daily_return": 0.0,
            "reject_rate": 0.0,
            "latest_date": "",
            "order_count": len(orders),
            "rejected_order_count": _rejected_orders(orders),
            "duplicate_date_count": 0,
            "duplicate_date_examples": [],
            "large_calendar_gap_count": 0,
            "large_calendar_gap_examples": [],
            "candidate_count": 0,
            "candidate_examples": [],
        }
    frame = daily.copy()
    frame["equity"] = pd.to_numeric(frame["equity"], errors="coerce")
    frame = frame.dropna(subset=["equity"]).sort_values("date" if "date" in frame else frame.index.name)
    equity = frame["equity"].astype(float)
    returns = equity.pct_change().dropna()
    drawdown = 1 - equity / equity.cummax()
    order_count = len(orders)
    rejected = _rejected_orders(orders)
    duplicate_count, duplicate_examples = _duplicate_date_metrics(frame)
    gap_count, gap_examples = _large_gap_metrics(frame)
    candidate_count, candidate_examples = _candidate_metrics(frame)
    return {
        "observed_days": len(frame),
        "rebalanced_days": int(frame.get("rebalanced", pd.Series(dtype=bool)).astype(bool).sum()),
        "total_return": float(equity.iloc[-1] / equity.iloc[0] - 1) if len(equity) >= 2 else 0.0,
        "max_drawdown": float(drawdown.max()) if not drawdown.empty else 0.0,
        "worst_daily_return": float(returns.min()) if not returns.empty else 0.0,
        "reject_rate": rejected / order_count if order_count else 0.0,
        "latest_date": str(frame["date"].iloc[-1])[:10] if "date" in frame and not frame.empty else "",
        "order_count": order_count,
        "rejected_order_count": rejected,
        "duplicate_date_count": duplicate_count,
        "duplicate_date_examples": duplicate_examples,
        "large_calendar_gap_count": gap_count,
        "large_calendar_gap_examples": gap_examples,
        "candidate_count": candidate_count,
        "candidate_examples": candidate_examples,
    }


def _rejected_orders(orders: pd.DataFrame) -> int:
    if orders.empty or "status" not in orders:
        return 0
    return int((orders["status"].astype(str).str.lower() == "rejected").sum())


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _duplicate_date_metrics(frame: pd.DataFrame) -> tuple[int, list[str]]:
    if frame.empty or "date" not in frame:
        return 0, []
    dates = frame["date"].astype(str).str[:10]
    duplicated = dates[dates.duplicated()].drop_duplicates().tolist()
    return len(duplicated), duplicated[:10]


def _large_gap_metrics(frame: pd.DataFrame, *, max_calendar_gap_days: int = 10) -> tuple[int, list[dict[str, Any]]]:
    if frame.empty or "date" not in frame:
        return 0, []
    dates = pd.to_datetime(frame["date"], errors="coerce").dropna().sort_values()
    if len(dates) < 2:
        return 0, []
    gaps = dates.diff().dt.days.fillna(0).astype(int)
    examples = []
    for idx, gap in enumerate(gaps):
        if gap <= max_calendar_gap_days:
            continue
        examples.append(
            {
                "previous_date": dates.iloc[idx - 1].date().isoformat(),
                "next_date": dates.iloc[idx].date().isoformat(),
                "gap_days": int(gap),
            }
        )
    return len(examples), examples[:10]


def _candidate_metrics(frame: pd.DataFrame) -> tuple[int, list[str]]:
    if frame.empty or "candidate" not in frame:
        return 0, []
    candidates = sorted(
        {
            str(item)
            for item in frame["candidate"].dropna().astype(str).tolist()
            if str(item)
        }
    )
    return len(candidates), candidates[:10]


def _combine(statuses: list[PaperStabilityStatus]) -> PaperStabilityStatus:
    if any(status == "BLOCK" for status in statuses):
        return "BLOCK"
    if any(status == "WATCH" for status in statuses):
        return "WATCH"
    return "PASS"
