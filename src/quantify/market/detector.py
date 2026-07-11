"""Market regime detector built from cached A-share daily bars."""
from __future__ import annotations

from dataclasses import dataclass
import json
from math import isfinite, sqrt
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from quantify.data.provider import DataProvider

MarketRegimeStatus = Literal["PASS", "WATCH", "BLOCK"]
MarketRegimeLabel = Literal["risk_on", "neutral", "defensive", "risk_off", "unknown"]

TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True, slots=True)
class MarketRegimeReport:
    status: MarketRegimeStatus
    label: MarketRegimeLabel
    as_of: str
    start: str
    end: str
    symbol_count: int
    usable_symbol_count: int
    trading_day_count: int
    metrics: dict[str, float | int | None]
    findings: list[str]
    recommendations: list[str]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "label": self.label,
            "as_of": self.as_of,
            "start": self.start,
            "end": self.end,
            "symbol_count": self.symbol_count,
            "usable_symbol_count": self.usable_symbol_count,
            "trading_day_count": self.trading_day_count,
            "metrics": self.metrics,
            "findings": self.findings,
            "recommendations": self.recommendations,
            "warnings": self.warnings,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Market Regime: {self.label} ({self.status})",
            "",
            f"- As of: `{self.as_of}`",
            f"- Period: `{self.start}` to `{self.end}`",
            f"- Symbols: {self.symbol_count}",
            f"- Usable symbols: {self.usable_symbol_count}",
            f"- Trading days: {self.trading_day_count}",
            "",
            "## Metrics",
        ]
        lines.extend(f"- {key}: `{_format_metric(value)}`" for key, value in self.metrics.items())
        lines.extend(["", "## Findings"])
        if self.findings:
            lines.extend(f"- {finding}" for finding in self.findings)
        else:
            lines.append("- No regime findings.")
        lines.extend(["", "## Recommendations"])
        lines.extend(f"- {item}" for item in self.recommendations)
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {item}" for item in self.warnings)
        return "\n".join(lines) + "\n"


def detect_market_regime(
    data: DataProvider,
    start: str,
    end: str,
    *,
    symbols: list[str] | None = None,
    min_history_days: int = 60,
) -> MarketRegimeReport:
    """Summarize broad market trend, volatility, breadth, and drawdown.

    The detector is descriptive only. It does not generate buy/sell signals and
    cannot promote a strategy past deterministic risk gates or human approval.
    """
    requested_symbols = symbols or data.all_symbols()
    days = data.trading_days(start, end)
    if not requested_symbols:
        return _empty_report(
            start,
            end,
            trading_day_count=len(days),
            finding="No symbols are available for market regime detection.",
        )

    close = data.close_matrix(requested_symbols, start, end)
    close = _clean_close_matrix(close)
    if close.empty:
        return _empty_report(
            start,
            end,
            symbol_count=len(requested_symbols),
            trading_day_count=len(days),
            finding="No cached close prices are available for market regime detection.",
        )

    usable_close = close.loc[:, close.notna().sum() >= 2]
    if usable_close.empty:
        return _empty_report(
            start,
            end,
            symbol_count=len(requested_symbols),
            trading_day_count=len(days),
            finding="No symbol has enough close prices to compute market returns.",
        )

    market_index, market_returns = _equal_weight_market_index(usable_close)
    metrics = _metrics(usable_close, market_index, market_returns)
    findings = _findings(metrics, len(market_index), len(usable_close.columns), min_history_days)
    label = _classify(metrics, findings)
    status = _status(label, findings)
    return MarketRegimeReport(
        status=status,
        label=label,
        as_of=str(usable_close.index[-1]),
        start=start,
        end=end,
        symbol_count=len(requested_symbols),
        usable_symbol_count=len(usable_close.columns),
        trading_day_count=len(days) if days else len(usable_close),
        metrics=metrics,
        findings=findings,
        recommendations=_recommendations(label),
        warnings=_warnings(),
    )


def write_market_regime_report(report: MarketRegimeReport, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "market_regime.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "market_regime.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _empty_report(
    start: str,
    end: str,
    *,
    symbol_count: int = 0,
    trading_day_count: int = 0,
    finding: str,
) -> MarketRegimeReport:
    return MarketRegimeReport(
        status="BLOCK",
        label="unknown",
        as_of=end,
        start=start,
        end=end,
        symbol_count=symbol_count,
        usable_symbol_count=0,
        trading_day_count=trading_day_count,
        metrics={
            "return_20d": None,
            "return_60d": None,
            "return_120d": None,
            "breadth_above_ma20": None,
            "breadth_above_ma60": None,
            "annualized_volatility": None,
            "max_drawdown": None,
            "current_drawdown": None,
        },
        findings=[finding],
        recommendations=_recommendations("unknown"),
        warnings=_warnings(),
    )


def _clean_close_matrix(close: pd.DataFrame) -> pd.DataFrame:
    if close.empty:
        return close
    numeric = close.apply(pd.to_numeric, errors="coerce").sort_index()
    return numeric.where(numeric > 0).dropna(how="all")


def _equal_weight_market_index(close: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    filled = close.ffill()
    returns = filled / filled.shift(1) - 1
    market_returns = returns.mean(axis=1, skipna=True).dropna()
    if market_returns.empty:
        first_date = close.index[0]
        return pd.Series([1.0], index=pd.Index([first_date])), pd.Series(dtype=float)
    base = pd.Series([1.0], index=pd.Index([filled.index[0]]))
    index = pd.concat([base, (1 + market_returns).cumprod()])
    index = index[~index.index.duplicated(keep="last")]
    return index.astype(float), market_returns.astype(float)


def _metrics(
    close: pd.DataFrame,
    market_index: pd.Series,
    market_returns: pd.Series,
) -> dict[str, float | int | None]:
    max_drawdown, current_drawdown = _drawdowns(market_index)
    volatility = (
        _finite_or_none(float(market_returns.std(ddof=1) * sqrt(TRADING_DAYS_PER_YEAR)))
        if len(market_returns) > 1
        else 0.0
    )
    return {
        "return_20d": _horizon_return(market_index, 20),
        "return_60d": _horizon_return(market_index, 60),
        "return_120d": _horizon_return(market_index, 120),
        "breadth_above_ma20": _breadth_above_ma(close, 20),
        "breadth_above_ma60": _breadth_above_ma(close, 60),
        "annualized_volatility": volatility,
        "max_drawdown": max_drawdown,
        "current_drawdown": current_drawdown,
    }


def _horizon_return(market_index: pd.Series, horizon: int) -> float | None:
    if len(market_index) <= horizon:
        return None
    return _finite_or_none(float(market_index.iloc[-1] / market_index.iloc[-(horizon + 1)] - 1))


def _breadth_above_ma(close: pd.DataFrame, window: int) -> float | None:
    if len(close) < window:
        return None
    ma = close.rolling(window=window, min_periods=window).mean().iloc[-1]
    latest = close.iloc[-1]
    valid = latest.notna() & ma.notna()
    if int(valid.sum()) == 0:
        return None
    return _finite_or_none(float((latest[valid] > ma[valid]).mean()))


def _drawdowns(market_index: pd.Series) -> tuple[float | None, float | None]:
    if market_index.empty:
        return None, None
    drawdown = 1 - market_index / market_index.cummax()
    return _finite_or_none(float(drawdown.max())), _finite_or_none(float(drawdown.iloc[-1]))


def _findings(
    metrics: dict[str, float | int | None],
    index_points: int,
    usable_symbol_count: int,
    min_history_days: int,
) -> list[str]:
    findings = []
    if index_points < min_history_days:
        findings.append(
            f"Only {index_points} market index points are available; at least {min_history_days} are preferred."
        )
    if usable_symbol_count < 5:
        findings.append("Fewer than 5 usable symbols; breadth and equal-weight trend are fragile.")
    if _value(metrics, "max_drawdown") >= 0.15:
        findings.append("Broad equal-weight market drawdown is elevated.")
    if _value(metrics, "breadth_above_ma60", default=1.0) < 0.35:
        findings.append("Less than 35% of usable symbols are above their 60-day moving average.")
    if _value(metrics, "annualized_volatility") >= 0.30:
        findings.append("Annualized market volatility is high for a stable compounding workflow.")
    return findings


def _classify(
    metrics: dict[str, float | int | None],
    findings: list[str],
) -> MarketRegimeLabel:
    if any("Only" in finding or "Fewer than 5" in finding for finding in findings):
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


def _status(label: MarketRegimeLabel, findings: list[str]) -> MarketRegimeStatus:
    if label == "unknown":
        return "WATCH"
    if label in {"defensive", "risk_off"}:
        return "WATCH"
    if any("Only" in finding or "Fewer than 5" in finding for finding in findings):
        return "WATCH"
    return "PASS"


def _recommendations(label: MarketRegimeLabel) -> list[str]:
    base = [
        "Use this regime as research context only; it is not a buy/sell signal.",
        "Keep data audit, robustness, LLM advisory review, and human approval as separate gates.",
    ]
    if label == "risk_on":
        return [
            "Core multi-factor and momentum-quality candidates can stay in the research queue.",
            "Do not raise capital unless out-of-sample and paper-trading evidence also pass.",
            *base,
        ]
    if label == "neutral":
        return [
            "Prefer diversified core candidates and avoid single-theme concentration.",
            "Require cost stress and parameter perturbation before promotion.",
            *base,
        ]
    if label == "defensive":
        return [
            "Favor defensive low-volatility candidates and reduce exposure assumptions in paper review.",
            "Add drawdown and liquidity stress tests before any readiness discussion.",
            *base,
        ]
    if label == "risk_off":
        return [
            "Do not promote strategies toward micro_live_ready from this regime alone.",
            "Use paper-only observation, lower exposure assumptions, and stricter drawdown review.",
            *base,
        ]
    return [
        "Collect more real A-share daily data before relying on market context.",
        "Treat candidate selection as incomplete until the regime report has enough breadth and history.",
        *base,
    ]


def _warnings() -> list[str]:
    return [
        "Market regime detection is descriptive and can be wrong after regime shifts.",
        "This report cannot justify live trading, leverage, or bypassing deterministic gates.",
        "LLM advisory output must not modify the deterministic market or strategy decision.",
    ]


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


def _finite_or_none(value: float) -> float | None:
    return value if isfinite(value) else None


def _format_metric(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)
