"""Advisory point-in-time backtests with an explicit optional Rust path."""

from __future__ import annotations

import logging
import os
from typing import Any, List

from yeuxq.analysis.engine import run_analysis
from yeuxq.analysis.rust_bridge import backtest_rust, rust_status
from yeuxq.domain.models import FundFlow, Kline
from yeuxq.providers.composite import CompositeMarketData
from yeuxq.settings import Settings

log = logging.getLogger("yeuxq.backtest")


def _rust_requested() -> bool:
    """Rust must never replace the canonical Python path implicitly."""

    return os.environ.get("YEUXQ_ENGINE", "python").strip().lower() == "rust"


class BacktestService:
    def __init__(self, data: CompositeMarketData, settings: Settings) -> None:
        self.data = data
        self.settings = settings

    def run(
        self,
        symbol: str,
        horizon: int = 5,
        min_score: int = 65,
        lookback: int = 250,
        point_in_time: bool = True,
        commission: float = 0.00025,
        stamp_duty: float = 0.0005,
        slippage: float = 0.001,
        entry_mode: str = "next_open",
    ) -> dict[str, Any]:
        symbol = symbol.strip()
        count = min(500, lookback + horizon + 80)
        klines = self.data.fetch_kline(symbol, count=count, period="day")
        if len(klines) < lookback // 2:
            return {"error": f"K线不足: {len(klines)}"}

        flows = self.data.fetch_fund_flow(symbol, days=min(120, lookback))
        index_klines = self.data.fetch_index_kline("000001", count=min(300, lookback + 20))

        rust_fallback_reason: str | None = None
        if point_in_time and _rust_requested():
            if not rust_status().get("available"):
                rust_fallback_reason = "rust_unavailable"
            else:
                try:
                    payload = {
                        "klines": [_k(k) for k in klines],
                        "flows": [_f(f) for f in flows],
                        "index": [_k(k) for k in index_klines],
                        "config": {
                            "chanlun_bonus": self.settings.engine.chanlun_bonus,
                            "sell_symmetric": getattr(self.settings.engine, "sell_symmetric", True),
                            "atr_position": getattr(self.settings.engine, "atr_position", True),
                            "w_trend": self.settings.engine.weights.trend,
                            "w_momentum": self.settings.engine.weights.momentum,
                            "w_breakout": self.settings.engine.weights.breakout,
                            "w_volume": self.settings.engine.weights.volume_price,
                            "w_pattern": self.settings.engine.weights.pattern,
                        },
                        "cost": {
                            "commission": commission,
                            "stamp_duty": stamp_duty,
                            "slippage": slippage,
                        },
                        "min_score": min_score,
                        "min_bars": 80,
                        "horizon": horizon,
                        "entry_mode": entry_mode,
                    }
                    report = backtest_rust(payload)
                    report["symbol"] = symbol
                    report["engine"] = "rust"
                    report["point_in_time"] = True
                    return report
                except Exception:
                    log.exception("optional Rust backtest failed; using canonical Python")
                    rust_fallback_reason = "rust_error"

        report = self._legacy(
            symbol,
            klines,
            flows,
            index_klines,
            horizon,
            min_score,
            lookback,
        )
        if rust_fallback_reason:
            report["fallback"] = "python"
            report["fallback_reason"] = rust_fallback_reason
        return report

    def compare(
        self,
        symbols: List[str],
        horizon: int = 5,
        min_score: int = 60,
        lookback: int = 250,
        train_ratio: float = 0.7,
    ) -> dict[str, Any]:
        """同一数据上对比 baseline / sell_symmetric / full 三套规则，并切训练/验证段。"""
        if not rust_status().get("available"):
            return {
                "error": "需要 Rust 计算核（cargo build -p trendlab-core --release --bin trendlab）"
            }
        symbols = [s.strip() for s in symbols if s and s.strip()][:12]
        if not symbols:
            return {"error": "symbols 为空"}

        variants = [
            {
                "name": "baseline",
                "sell_symmetric": False,
                "chanlun_bonus": False,
                "atr_position": False,
            },
            {
                "name": "sell_symmetric",
                "sell_symmetric": True,
                "chanlun_bonus": False,
                "atr_position": False,
            },
            {"name": "full", "sell_symmetric": True, "chanlun_bonus": True, "atr_position": True},
        ]
        per_symbol: list[dict] = []
        agg: dict[str, dict] = {
            v["name"]: {
                "trades": 0,
                "pnl": 0.0,
                "wins": 0,
                "valid_trades": 0,
                "valid_pnl": 0.0,
                "valid_wins": 0,
            }
            for v in variants
        }

        for sym in symbols:
            klines = self.data.fetch_kline(
                sym, count=min(500, lookback + horizon + 80), period="day"
            )
            if len(klines) < 100:
                per_symbol.append({"symbol": sym, "error": f"K线不足 {len(klines)}"})
                continue
            flows = self.data.fetch_fund_flow(sym, days=min(120, lookback))
            index_klines = self.data.fetch_index_kline("000001", count=min(300, lookback + 20))
            split_idx = max(90, int(len(klines) * train_ratio))
            split_idx = min(split_idx, len(klines) - 1)
            validation_start = klines[split_idx].date
            train_end = klines[split_idx - 1].date
            row: dict[str, Any] = {
                "symbol": sym,
                "bars": len(klines),
                "split_date": validation_start,
                "train_end": train_end,
                "validation_start": validation_start,
                "variants": {},
            }
            for v in variants:
                cfg = {
                    "chanlun_bonus": v["chanlun_bonus"],
                    "sell_symmetric": v["sell_symmetric"],
                    "atr_position": v["atr_position"],
                    "w_trend": self.settings.engine.weights.trend,
                    "w_momentum": self.settings.engine.weights.momentum,
                    "w_breakout": self.settings.engine.weights.breakout,
                    "w_volume": self.settings.engine.weights.volume_price,
                    "w_pattern": self.settings.engine.weights.pattern,
                }
                base = {
                    "klines": [_k(k) for k in klines],
                    "flows": [_f(f) for f in flows],
                    "index": [_k(k) for k in index_klines],
                    "config": cfg,
                    "cost": {"commission": 0.00025, "stamp_duty": 0.0005, "slippage": 0.001},
                    "min_score": min_score,
                    "min_bars": 80,
                    "horizon": horizon,
                    "entry_mode": "next_open",
                }
                try:
                    full = backtest_rust(base)
                    train = backtest_rust(
                        {
                            **base,
                            "eval_end": train_end,
                            "outcome_end": train_end,
                        }
                    )
                    valid = backtest_rust({**base, "eval_start": validation_start})
                except Exception as e:
                    row["variants"][v["name"]] = {"error": str(e)[:200]}
                    continue
                row["variants"][v["name"]] = {
                    "full": _brief(full),
                    "train": _brief(train),
                    "valid": _brief(valid),
                }
                a = agg[v["name"]]
                a["trades"] += int(full.get("trades") or 0)
                a["pnl"] += float(full.get("expectancy") or 0) * max(
                    int(full.get("trades") or 0), 0
                )
                a["wins"] += int(
                    round((full.get("win_rate") or 0) / 100.0 * (full.get("trades") or 0))
                )
                a["valid_trades"] += int(valid.get("trades") or 0)
                a["valid_pnl"] += float(valid.get("expectancy") or 0) * max(
                    int(valid.get("trades") or 0), 0
                )
                a["valid_wins"] += int(
                    round((valid.get("win_rate") or 0) / 100.0 * (valid.get("trades") or 0))
                )
            per_symbol.append(row)

        summary = {}
        for name, a in agg.items():
            t = a["trades"]
            vt = a["valid_trades"]
            summary[name] = {
                "trades": t,
                "win_rate": round(a["wins"] / t * 100, 1) if t else 0,
                "expectancy": round(a["pnl"] / t, 2) if t else 0,
                "valid_trades": vt,
                "valid_win_rate": round(a["valid_wins"] / vt * 100, 1) if vt else 0,
                "valid_expectancy": round(a["valid_pnl"] / vt, 2) if vt else 0,
            }
        winner = None
        if any(summary[n]["valid_trades"] for n in summary):
            winner = max(
                summary,
                key=lambda n: (
                    summary[n]["valid_expectancy"],
                    -abs(summary[n]["valid_expectancy"]),
                ),
            )
        return {
            "symbols": symbols,
            "horizon": horizon,
            "min_score": min_score,
            "train_ratio": train_ratio,
            "summary": summary,
            "suggested_variant": winner,
            "per_symbol": per_symbol,
            "engine": "rust",
            "point_in_time": True,
            "note": "验证段期望优先选规则；样本仍偏少时只作对照，禁止当实盘依据。",
            "disclaimer": "点时回测含成本；未计涨跌停/停牌/冲击。",
        }

    def _legacy(
        self,
        symbol: str,
        klines: List[Kline],
        flows: List[FundFlow],
        index_klines: List[Kline],
        horizon: int,
        min_score: int,
        lookback: int,
    ) -> dict[str, Any]:
        trades: List[dict] = []
        start = max(60, len(klines) - lookback)
        for i in range(start, len(klines) - horizon, 5):
            window = klines[: i + 1]
            asof = klines[i].date
            fl = [f for f in flows if f.date <= asof]
            idx = [k for k in index_klines if k.date <= asof]
            try:
                sig = run_analysis(window, None, fl, idx, settings=self.settings)
            except Exception:
                continue
            if sig.score < min_score or sig.action not in ("买入", "强烈买入", "谨慎买入"):
                continue
            entry = klines[i].close
            future = klines[i + horizon].close
            ret = (future - entry) / entry * 100 if entry else 0.0
            trades.append(
                {
                    "date": klines[i].date,
                    "action": sig.action,
                    "score": sig.score,
                    "entry": entry,
                    "exit": future,
                    "return_pct": round(ret, 2),
                    "reason": "到期(legacy)",
                }
            )
        if not trades:
            return {
                "symbol": symbol,
                "trades": 0,
                "win_rate": 0,
                "avg_return": 0,
                "engine": "python_legacy",
                "note": "无信号或 Rust 不可用",
            }
        wins = sum(1 for t in trades if t["return_pct"] > 0)
        avg = sum(t["return_pct"] for t in trades) / len(trades)
        return {
            "symbol": symbol,
            "horizon": horizon,
            "min_score": min_score,
            "trades": len(trades),
            "win_rate": round(wins / len(trades) * 100, 1),
            "avg_return": round(avg, 2),
            "expectancy": round(avg, 2),
            "samples": trades[-20:],
            "engine": "python_legacy",
            "point_in_time": True,
            "disclaimer": "Python 回退：隔 5 日抽样；已按日期截断资金流。建议编译 Rust CLI。",
        }


def _k(k: Kline) -> dict:
    return {
        "date": k.date,
        "open": k.open,
        "close": k.close,
        "high": k.high,
        "low": k.low,
        "volume": k.volume,
        "amount": k.amount,
        "pct": k.pct,
        "turnover": k.turnover,
    }


def _brief(r: dict) -> dict:
    return {
        "trades": r.get("trades", 0),
        "win_rate": r.get("win_rate", 0),
        "expectancy": r.get("expectancy", r.get("avg_return", 0)),
        "profit_factor": r.get("profit_factor", 0),
        "max_drawdown": r.get("max_drawdown", 0),
        "by_year": r.get("by_year") or [],
    }


def _f(f: FundFlow) -> dict:
    return {
        "date": f.date,
        "main_net": f.main_net,
        "super_large_net": f.super_large_net,
        "large_net": f.large_net,
        "medium_net": f.medium_net,
        "small_net": f.small_net,
        "main_pct": f.main_pct,
    }
