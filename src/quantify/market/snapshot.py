"""Auditable external market context snapshot.

The snapshot is for research context only. It can describe recent index-level
conditions when a full A-share cache is not ready, but it cannot replace the
cache-derived market_regime report or relax deterministic strategy gates.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from math import isfinite, sqrt
from pathlib import Path
from typing import Any, Literal

import pandas as pd

MarketContextStatus = Literal["PASS", "WATCH", "BLOCK"]
MarketContextLabel = Literal["risk_on", "neutral", "defensive", "risk_off", "unknown"]

PLACEHOLDER_TOKENS = ("<", ">", "todo", "tbd", "placeholder", "demo", "sample", "fake")
TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True, slots=True)
class MarketContextIndexMetric:
    name: str
    return_20d: float | None = None
    return_60d: float | None = None
    return_120d: float | None = None
    max_drawdown: float | None = None
    annualized_volatility: float | None = None
    breadth_above_ma20: float | None = None
    breadth_above_ma60: float | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "return_20d": self.return_20d,
            "return_60d": self.return_60d,
            "return_120d": self.return_120d,
            "max_drawdown": self.max_drawdown,
            "annualized_volatility": self.annualized_volatility,
            "breadth_above_ma20": self.breadth_above_ma20,
            "breadth_above_ma60": self.breadth_above_ma60,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class MarketContextSnapshot:
    status: MarketContextStatus
    label: MarketContextLabel
    as_of: str
    source: str
    reviewed_by: str
    reviewed_at: str
    index_metrics: list[MarketContextIndexMetric]
    metrics: dict[str, float | int | None]
    breadth_note: str
    findings: list[str]
    recommendations: list[str]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": "market_context_snapshot",
            "context_source": "market_context_snapshot",
            "status": self.status,
            "label": self.label,
            "as_of": self.as_of,
            "source": self.source,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at,
            "index_metrics": [item.to_dict() for item in self.index_metrics],
            "metrics": self.metrics,
            "breadth_note": self.breadth_note,
            "findings": self.findings,
            "recommendations": self.recommendations,
            "warnings": self.warnings,
            "can_replace_market_regime": False,
            "can_approve_strategy": False,
            "can_generate_broker_orders": False,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Market Context Snapshot: {self.label} ({self.status})",
            "",
            f"- As of: `{self.as_of or 'missing'}`",
            f"- Source: `{self.source or 'missing'}`",
            f"- Reviewed by: `{self.reviewed_by or 'missing'}`",
            f"- Reviewed at: `{self.reviewed_at or 'missing'}`",
            "",
            "This snapshot is descriptive context only. It cannot replace `market_regime.json`, "
            "approve strategy experiments, upgrade deterministic gates, or generate broker orders.",
            "",
            "## Aggregate Metrics",
        ]
        lines.extend(f"- {key}: `{_format_metric(value)}`" for key, value in self.metrics.items())
        lines.extend(
            [
                "",
                "## Index Metrics",
                "",
                "| index | return_20d | return_60d | return_120d | max_drawdown | volatility | breadth20 | breadth60 | note |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        if self.index_metrics:
            for item in self.index_metrics:
                lines.append(
                    "| {name} | `{r20}` | `{r60}` | `{r120}` | `{dd}` | `{vol}` | `{b20}` | `{b60}` | {note} |".format(
                        name=_cell(item.name),
                        r20=_format_metric(item.return_20d),
                        r60=_format_metric(item.return_60d),
                        r120=_format_metric(item.return_120d),
                        dd=_format_metric(item.max_drawdown),
                        vol=_format_metric(item.annualized_volatility),
                        b20=_format_metric(item.breadth_above_ma20),
                        b60=_format_metric(item.breadth_above_ma60),
                        note=_cell(item.note or ""),
                    )
                )
        else:
            lines.append("| none | `n/a` | `n/a` | `n/a` | `n/a` | `n/a` | `n/a` | `n/a` | no metrics |")
        lines.extend(["", "## Breadth Note", self.breadth_note or "No breadth note supplied."])
        lines.extend(["", "## Findings"])
        lines.extend(f"- {item}" for item in self.findings) if self.findings else lines.append("- None.")
        lines.extend(["", "## Recommendations"])
        lines.extend(f"- {item}" for item in self.recommendations)
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {item}" for item in self.warnings)
        return "\n".join(lines) + "\n"


def build_market_context_snapshot(
    *,
    as_of: str,
    source: str,
    reviewed_by: str,
    reviewed_at: str,
    index_metrics: list[MarketContextIndexMetric | dict[str, Any]],
    breadth_note: str = "",
    extra_findings: list[str] | None = None,
) -> MarketContextSnapshot:
    metrics = [_coerce_index_metric(item) for item in index_metrics]
    aggregate = _aggregate_metrics(metrics)
    findings = _metadata_findings(
        as_of=as_of,
        source=source,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
    )
    findings.extend(_metric_findings(metrics))
    findings.extend(_risk_findings(aggregate))
    findings.extend(str(item) for item in (extra_findings or []) if str(item or "").strip())
    label = _classify(aggregate, findings)
    status = _status(label, findings)
    return MarketContextSnapshot(
        status=status,
        label=label,
        as_of=str(as_of or ""),
        source=str(source or ""),
        reviewed_by=str(reviewed_by or ""),
        reviewed_at=str(reviewed_at or ""),
        index_metrics=metrics,
        metrics=aggregate,
        breadth_note=str(breadth_note or ""),
        findings=findings,
        recommendations=_recommendations(label),
        warnings=_warnings(),
    )


def write_market_context_snapshot(snapshot: MarketContextSnapshot, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "market_context_snapshot.json").write_text(
        json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "market_context_snapshot.md").write_text(snapshot.to_markdown(), encoding="utf-8")
    return root


def build_market_context_snapshot_from_csvs(
    *,
    csv_paths: list[str | Path],
    as_of: str,
    source: str,
    reviewed_by: str,
    reviewed_at: str,
    breadth_note: str = "",
    encoding: str = "utf-8-sig",
) -> MarketContextSnapshot:
    """Build a market context snapshot from local index-level daily CSV files.

    CSV input can be one file per index, or a long-form file with an index/name
    column. Required columns are date and close. Optional latest breadth columns
    are used when present: breadth_above_ma20 and breadth_above_ma60.
    """
    metrics, findings = read_market_context_index_metrics_from_csvs(
        csv_paths=csv_paths,
        as_of=as_of,
        encoding=encoding,
    )
    return build_market_context_snapshot(
        as_of=as_of,
        source=source,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        index_metrics=metrics,
        breadth_note=breadth_note,
        extra_findings=findings,
    )


def read_market_context_index_metrics_from_csvs(
    *,
    csv_paths: list[str | Path],
    as_of: str,
    encoding: str = "utf-8-sig",
) -> tuple[list[MarketContextIndexMetric], list[str]]:
    metrics: list[MarketContextIndexMetric] = []
    findings: list[str] = []
    if not csv_paths:
        return [], ["BLOCK: at least one index CSV path is required."]
    for raw_path in csv_paths:
        path = Path(raw_path)
        if not path.exists():
            findings.append(f"BLOCK: index CSV is missing: {path}.")
            continue
        try:
            frame = _read_csv(path, encoding)
        except (OSError, UnicodeDecodeError, pd.errors.ParserError) as exc:
            findings.append(f"BLOCK: failed to read index CSV `{path}`: {type(exc).__name__}: {exc}.")
            continue
        file_metrics, file_findings = _index_metrics_from_frame(frame, path=path, as_of=as_of)
        metrics.extend(file_metrics)
        findings.extend(file_findings)
    return metrics, findings


def _coerce_index_metric(value: MarketContextIndexMetric | dict[str, Any]) -> MarketContextIndexMetric:
    if isinstance(value, MarketContextIndexMetric):
        return value
    return MarketContextIndexMetric(
        name=str(value.get("name", "") or ""),
        return_20d=_finite_or_none(value.get("return_20d")),
        return_60d=_finite_or_none(value.get("return_60d")),
        return_120d=_finite_or_none(value.get("return_120d")),
        max_drawdown=_finite_or_none(value.get("max_drawdown")),
        annualized_volatility=_finite_or_none(value.get("annualized_volatility")),
        breadth_above_ma20=_finite_or_none(value.get("breadth_above_ma20")),
        breadth_above_ma60=_finite_or_none(value.get("breadth_above_ma60")),
        note=str(value.get("note", "") or ""),
    )


def _index_metrics_from_frame(
    frame: pd.DataFrame,
    *,
    path: Path,
    as_of: str,
) -> tuple[list[MarketContextIndexMetric], list[str]]:
    findings: list[str] = []
    if frame.empty:
        return [], [f"BLOCK: index CSV `{path}` is empty."]
    normalized = _normalize_columns(frame)
    date_col = _first_column(normalized, ("date", "trade_date", "trading_date", "datetime"))
    close_col = _first_column(normalized, ("close", "close_price", "index_close", "收盘", "收盘价"))
    if date_col is None:
        return [], [f"BLOCK: index CSV `{path}` is missing a date column."]
    if close_col is None:
        return [], [f"BLOCK: index CSV `{path}` is missing a close column."]
    name_col = _first_column(
        normalized,
        ("index", "index_name", "name", "symbol", "code", "index_code", "指数", "代码", "名称"),
    )
    groups = (
        [(str(name), group) for name, group in normalized.groupby(name_col, dropna=False)]
        if name_col
        else [(path.stem, normalized)]
    )
    metrics = []
    for raw_name, group in groups:
        name = str(raw_name or path.stem).strip() or path.stem
        metric, metric_findings = _index_metric_from_group(
            group,
            path=path,
            name=name,
            date_col=date_col,
            close_col=close_col,
            as_of=as_of,
        )
        if metric is not None:
            metrics.append(metric)
        findings.extend(metric_findings)
    return metrics, findings


def _index_metric_from_group(
    group: pd.DataFrame,
    *,
    path: Path,
    name: str,
    date_col: str,
    close_col: str,
    as_of: str,
) -> tuple[MarketContextIndexMetric | None, list[str]]:
    findings: list[str] = []
    dates = pd.to_datetime(group[date_col], errors="coerce")
    close = pd.to_numeric(group[close_col], errors="coerce")
    data = pd.DataFrame({"date": dates, "close": close})
    for column in ("breadth_above_ma20", "breadth20", "above_ma20_ratio"):
        if column in group.columns:
            data["breadth_above_ma20"] = pd.to_numeric(group[column], errors="coerce")
            break
    for column in ("breadth_above_ma60", "breadth60", "above_ma60_ratio"):
        if column in group.columns:
            data["breadth_above_ma60"] = pd.to_numeric(group[column], errors="coerce")
            break
    cutoff = pd.to_datetime(as_of, errors="coerce")
    if pd.notna(cutoff):
        data = data[data["date"] <= cutoff]
    data = data.dropna(subset=["date", "close"]).sort_values("date")
    data = data[data["close"] > 0]
    data = data.drop_duplicates(subset=["date"], keep="last")
    if len(data) < 2:
        return None, [f"BLOCK: index `{name}` in `{path}` has fewer than 2 valid close rows."]

    close_series = pd.Series(data["close"].to_numpy(dtype=float), index=data["date"])
    returns = close_series.pct_change().dropna()
    metric = MarketContextIndexMetric(
        name=name,
        return_20d=_horizon_return(close_series, 20),
        return_60d=_horizon_return(close_series, 60),
        return_120d=_horizon_return(close_series, 120),
        max_drawdown=_max_drawdown(close_series),
        annualized_volatility=_annualized_volatility(returns),
        breadth_above_ma20=_last_optional_ratio(data, "breadth_above_ma20"),
        breadth_above_ma60=_last_optional_ratio(data, "breadth_above_ma60"),
        note=f"rows={len(data)}, first={data['date'].iloc[0].date()}, last={data['date'].iloc[-1].date()}",
    )
    if len(data) < 60:
        findings.append(f"WATCH: index `{name}` has only {len(data)} valid rows; regime context is short.")
    if data["date"].iloc[-1].date().isoformat() != str(as_of):
        findings.append(
            f"WATCH: index `{name}` latest date {data['date'].iloc[-1].date()} does not match as_of {as_of}."
        )
    return metric, findings


def _metadata_findings(
    *,
    as_of: str,
    source: str,
    reviewed_by: str,
    reviewed_at: str,
) -> list[str]:
    findings: list[str] = []
    required = {
        "as_of": as_of,
        "source": source,
        "reviewed_by": reviewed_by,
        "reviewed_at": reviewed_at,
    }
    for field, value in required.items():
        if not str(value or "").strip():
            findings.append(f"BLOCK: {field} is required for an auditable market context snapshot.")
        elif _looks_placeholder(value):
            findings.append(f"BLOCK: {field} looks like placeholder evidence.")
    return findings


def _metric_findings(metrics: list[MarketContextIndexMetric]) -> list[str]:
    if not metrics:
        return ["BLOCK: At least one index metric is required."]
    findings: list[str] = []
    for item in metrics:
        if not item.name.strip():
            findings.append("BLOCK: index metric name is required.")
        elif _looks_placeholder(item.name):
            findings.append(f"BLOCK: index metric name `{item.name}` looks like placeholder evidence.")
        if not _has_any_metric(item):
            findings.append(f"BLOCK: index `{item.name or 'unknown'}` has no numeric metrics.")
        missing = [
            key
            for key in ("return_20d", "return_60d", "return_120d", "max_drawdown", "annualized_volatility")
            if getattr(item, key) is None
        ]
        if missing and _has_any_metric(item):
            findings.append(f"WATCH: index `{item.name}` is missing metrics: {', '.join(missing)}.")
    return findings


def _read_csv(path: Path, encoding: str) -> pd.DataFrame:
    if encoding != "auto":
        return pd.read_csv(path, encoding=encoding)
    last_error: Exception | None = None
    for candidate in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            return pd.read_csv(path, encoding=candidate)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return pd.read_csv(path)


def _normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    renamed = {column: str(column).strip().lower() for column in frame.columns}
    return frame.rename(columns=renamed)


def _first_column(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    columns = set(frame.columns)
    return next((column for column in candidates if column in columns), None)


def _risk_findings(metrics: dict[str, float | int | None]) -> list[str]:
    findings: list[str] = []
    if _value(metrics, "index_count") <= 0:
        return findings
    if _value(metrics, "max_drawdown") >= 0.18:
        findings.append("WATCH: broad index drawdown is risk-off level.")
    elif _value(metrics, "max_drawdown") >= 0.12:
        findings.append("WATCH: broad index drawdown is elevated.")
    if _value(metrics, "annualized_volatility") >= 0.30:
        findings.append("WATCH: index volatility is high for a stable compounding workflow.")
    if _value(metrics, "breadth_above_ma60", default=1.0) < 0.35:
        findings.append("WATCH: breadth_above_ma60 is weak where supplied.")
    return findings


def _horizon_return(close: pd.Series, horizon: int) -> float | None:
    if len(close) <= horizon:
        return None
    return _finite_or_none(float(close.iloc[-1] / close.iloc[-(horizon + 1)] - 1))


def _max_drawdown(close: pd.Series) -> float | None:
    if close.empty:
        return None
    drawdown = 1 - close / close.cummax()
    return _finite_or_none(float(drawdown.max()))


def _annualized_volatility(returns: pd.Series) -> float | None:
    if len(returns) <= 1:
        return 0.0
    return _finite_or_none(float(returns.std(ddof=1) * sqrt(TRADING_DAYS_PER_YEAR)))


def _last_optional_ratio(frame: pd.DataFrame, column: str) -> float | None:
    if column not in frame.columns:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    if values.empty:
        return None
    return _finite_or_none(float(values.iloc[-1]))


def _aggregate_metrics(metrics: list[MarketContextIndexMetric]) -> dict[str, float | int | None]:
    return {
        "index_count": len(metrics),
        "return_20d": _average([item.return_20d for item in metrics]),
        "return_60d": _average([item.return_60d for item in metrics]),
        "return_120d": _average([item.return_120d for item in metrics]),
        "max_drawdown": _maximum([item.max_drawdown for item in metrics]),
        "annualized_volatility": _maximum([item.annualized_volatility for item in metrics]),
        "breadth_above_ma20": _average([item.breadth_above_ma20 for item in metrics]),
        "breadth_above_ma60": _average([item.breadth_above_ma60 for item in metrics]),
    }


def _classify(
    metrics: dict[str, float | int | None],
    findings: list[str],
) -> MarketContextLabel:
    if any(item.startswith("BLOCK:") for item in findings):
        return "unknown" if _value(metrics, "index_count") <= 0 else _metric_label(metrics)
    if any("missing metrics" in item for item in findings):
        return _metric_label(metrics)
    return _metric_label(metrics)


def _metric_label(metrics: dict[str, float | int | None]) -> MarketContextLabel:
    if _value(metrics, "index_count") <= 0:
        return "unknown"
    ret20 = _value(metrics, "return_20d")
    ret60 = _value(metrics, "return_60d")
    breadth20 = _value(metrics, "breadth_above_ma20", default=0.5)
    breadth60 = _value(metrics, "breadth_above_ma60", default=0.5)
    max_drawdown = _value(metrics, "max_drawdown")
    volatility = _value(metrics, "annualized_volatility")
    if max_drawdown >= 0.18 or ret60 <= -0.10 or (breadth60 < 0.25 and ret20 <= 0):
        return "risk_off"
    if max_drawdown >= 0.12 or ret60 < 0 or breadth60 < 0.45 or volatility >= 0.30:
        return "defensive"
    if ret60 >= 0.05 and ret20 > 0 and breadth20 >= 0.60 and breadth60 >= 0.55 and max_drawdown < 0.10:
        return "risk_on"
    return "neutral"


def _status(label: MarketContextLabel, findings: list[str]) -> MarketContextStatus:
    if any(item.startswith("BLOCK:") for item in findings):
        return "BLOCK"
    if label in {"unknown", "defensive", "risk_off"}:
        return "WATCH"
    if any(item.startswith("WATCH:") for item in findings):
        return "WATCH"
    return "PASS"


def _recommendations(label: MarketContextLabel) -> list[str]:
    base = [
        "Use this snapshot only as research context until a cache-derived market_regime.json exists.",
        "Keep source QA, offline intake, data audit, robustness, paper stability, and human approval as separate gates.",
    ]
    if label == "risk_on":
        return ["Do not let a risk-on snapshot relax data or execution evidence requirements.", *base]
    if label == "neutral":
        return ["Continue normal research preparation, but require full market_regime before promotion.", *base]
    if label == "defensive":
        return ["Favor lower exposure assumptions and add drawdown stress before any paper discussion.", *base]
    if label == "risk_off":
        return ["Pause promotion discussions and use the context only for adverse-market research questions.", *base]
    return ["Complete source metadata and index metrics before using this context in reviews.", *base]


def _warnings() -> list[str]:
    return [
        "External or manual index context can be stale, incomplete, or inconsistent with the tradable universe.",
        "This snapshot cannot approve strategy experiments or substitute for market_regime.json.",
        "This snapshot cannot justify live trading, leverage, broker integration, or LLM buy/sell decisions.",
    ]


def _has_any_metric(item: MarketContextIndexMetric) -> bool:
    return any(
        getattr(item, key) is not None
        for key in (
            "return_20d",
            "return_60d",
            "return_120d",
            "max_drawdown",
            "annualized_volatility",
            "breadth_above_ma20",
            "breadth_above_ma60",
        )
    )


def _looks_placeholder(value: object) -> bool:
    text = str(value or "").strip().lower()
    return any(token in text for token in PLACEHOLDER_TOKENS)


def _average(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None and isfinite(value)]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _maximum(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None and isfinite(value)]
    if not clean:
        return None
    return max(clean)


def _finite_or_none(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if isfinite(numeric) else None


def _value(
    metrics: dict[str, float | int | None],
    key: str,
    *,
    default: float = 0.0,
) -> float:
    value = metrics.get(key)
    if value is None:
        return default
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return numeric if isfinite(numeric) else default


def _format_metric(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")
