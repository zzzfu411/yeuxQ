"""分析编排服务。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from yeuxq.analysis.chanlun_daily import analyze_chanlun_daily, daily_result_to_dict
from yeuxq.analysis.chanlun_minute import analyze_chanlun_minute
from yeuxq.analysis.engine import extract_features, run_analysis
from yeuxq.analysis.plugins.rule_predictor import (
    SUPPORTED_PREDICTION_HORIZONS,
    UnsupportedPredictionHorizon,
)
from yeuxq.analysis.rust_bridge import rust_status
from yeuxq.providers.composite import CompositeMarketData
from yeuxq.services.serialize import (
    flow_to_dict,
    kline_to_dict,
    minute_flow_to_dict,
    quote_to_dict,
    signal_to_dict,
)
from yeuxq.settings import Settings

log = logging.getLogger("yeuxq.analyze")


class AnalyzeService:
    def __init__(self, data: CompositeMarketData, settings: Settings) -> None:
        self.data = data
        self.settings = settings

    def _diagnostic_cursor(self) -> dict[str, int]:
        cursor = getattr(self.data, "diagnostic_cursor", None)
        return cursor() if callable(cursor) else {"provider": 0, "cache": 0}

    def _data_diagnostics(self, cursor: dict[str, int]) -> dict[str, list[dict]]:
        diagnostics = getattr(self.data, "diagnostics", None)
        if not callable(diagnostics):
            return {"providers": [], "cache": []}
        return diagnostics(since=cursor, limit=8)

    @staticmethod
    def _has_data(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, dict) and "available" in value:
            return value.get("available") is True
        if isinstance(value, (list, tuple, dict, str)):
            return bool(value)
        return True

    def _fetch(
        self,
        operation: str,
        call: Callable[[], Any],
        default: Any,
    ) -> tuple[Any, dict[str, Any]]:
        cursor = self._diagnostic_cursor()
        operation_error = False
        try:
            value = call()
        except Exception:
            log.warning("market data operation failed operation=%s", operation)
            value = default
            operation_error = True

        raw = self._data_diagnostics(cursor)
        providers = list(raw.get("providers") or [])[-4:]
        cache_events = list(raw.get("cache") or [])[-4:]
        has_data = self._has_data(value)
        provider_errors = [item for item in providers if item.get("status") == "error"]
        provider_success = any(item.get("status") == "ok" for item in providers)
        cache_hit = next(
            (item for item in reversed(cache_events) if item.get("state") == "HIT"),
            None,
        )
        cache_state = cache_hit or (cache_events[-1] if cache_events else None)

        if has_data:
            status = "degraded" if provider_errors else "available"
            source = (
                "memory_cache" if cache_hit else ("provider" if provider_success else "fallback")
            )
        else:
            status = "unavailable"
            source = "none"

        if cache_state:
            freshness = {
                "state": cache_state.get("state"),
                "age_seconds": cache_state.get("age_seconds"),
                "ttl_seconds": cache_state.get("ttl_seconds"),
            }
        elif provider_success:
            freshness = {"state": "FRESH", "age_seconds": 0.0, "ttl_seconds": None}
        else:
            freshness = {"state": "UNKNOWN", "age_seconds": None, "ttl_seconds": None}

        diagnostic: dict[str, Any] = {
            "status": status,
            "source": source,
            "freshness": freshness,
            "providers": providers,
        }
        if status == "unavailable":
            if operation_error:
                diagnostic["reason"] = "operation_error"
            elif isinstance(value, dict) and value.get("reason"):
                diagnostic["reason"] = str(value["reason"])[:64]
            elif provider_errors:
                diagnostic["reason"] = provider_errors[-1].get("error_code", "provider_error")
            else:
                diagnostic["reason"] = "no_data"
        return value, diagnostic

    def analyze(self, symbol: str, period: str = "day") -> dict[str, Any]:
        symbol = symbol.strip()
        if not symbol:
            return {"error": "缺少 symbol参数"}
        data_sources: dict[str, dict[str, Any]] = {}
        klines, data_sources["kline"] = self._fetch(
            "kline",
            lambda: self.data.fetch_kline(symbol, count=250, period=period),
            [],
        )
        if len(klines) < 30:
            return {
                "error": f"K线数据不足: {len(klines)}条",
                "meta": {"data_sources": data_sources},
            }

        quote, data_sources["quote"] = self._fetch(
            "quote", lambda: self.data.fetch_quote(symbol), None
        )
        flows, data_sources["fund_flow"] = self._fetch(
            "fund_flow", lambda: self.data.fetch_fund_flow(symbol, days=60), []
        )
        index_klines, data_sources["market_index"] = self._fetch(
            "market_index", lambda: self.data.fetch_index_kline("000001", count=60), None
        )
        breadth, data_sources["market_breadth"] = self._fetch(
            "market_breadth",
            self.data.fetch_market_breadth,
            {"available": False, "complete": False, "reason": "provider_error"},
        )

        weekly = None
        if period == "day":
            weekly, data_sources["weekly_kline"] = self._fetch(
                "weekly_kline",
                lambda: self.data.fetch_kline(symbol, count=80, period="week"),
                None,
            )

        result = run_analysis(
            klines,
            quote,
            flows,
            index_klines,
            weekly_klines=weekly,
            settings=self.settings,
            market_breadth=breadth,
        )

        signal = signal_to_dict(result)

        return {
            "symbol": symbol,
            "period": period,
            "quote": quote_to_dict(quote) if quote else None,
            "signal": signal,
            "prediction": signal.get("prediction"),
            "klines": [kline_to_dict(k) for k in klines[-120:]],
            "flows": [flow_to_dict(f) for f in flows],
            "breadth": breadth,
            "meta": {
                "engine_version": self.settings.app.version,
                "app": self.settings.app.name,
                "kline_count": len(klines),
                "engine": rust_status(),
                "data_sources": data_sources,
            },
            "disclaimer": "仅供技术分析学习，不构成投资建议",
        }

    def predict(self, symbol: str, horizon: int = 5) -> dict[str, Any]:
        if horizon not in SUPPORTED_PREDICTION_HORIZONS:
            raise UnsupportedPredictionHorizon(horizon)
        full = self.analyze(symbol, "day")
        if "error" in full:
            return full
        pred = full.get("prediction") or {}
        return {
            "symbol": symbol,
            "prediction": pred,
            "score": full.get("signal", {}).get("score"),
            "action": full.get("signal", {}).get("action"),
            "disclaimer": "概率为规则估计，不构成投资建议",
        }

    def features(self, symbol: str) -> dict[str, Any]:
        klines = self.data.fetch_kline(symbol, 250, "day")
        if len(klines) < 30:
            return {"error": "K线不足"}
        quote = self.data.fetch_quote(symbol)
        flows = self.data.fetch_fund_flow(symbol, 30)
        index_klines = self.data.fetch_index_kline("000001", 60)
        return {"symbol": symbol, "features": extract_features(klines, quote, flows, index_klines)}

    def chanlun_daily(self, symbol: str, count: int = 250, period: str = "day") -> dict[str, Any]:
        klines = self.data.fetch_kline(symbol, count=min(count, 500), period=period)
        if len(klines) < 30:
            return {"error": "K线不足"}
        r = analyze_chanlun_daily(klines)
        d = daily_result_to_dict(r)
        d["current_price"] = klines[-1].close
        return {"symbol": symbol, "period": period, **d}

    def chanlun_minute(self, symbol: str) -> dict[str, Any]:
        minute = self.data.fetch_minute(symbol)
        data = analyze_chanlun_minute(minute)
        return {"symbol": symbol, **data}

    def realtime_flow_payload(self, symbol: str) -> dict[str, Any]:
        flows, diagnostic = self._fetch(
            "realtime_flow", lambda: self.data.fetch_realtime_flow(symbol), []
        )
        summary = None
        if flows:
            last = flows[-1]
            summary = {
                "main_net": last.main_net,
                "super_large_net": last.super_large_net,
                "large_net": last.large_net,
                "medium_net": last.medium_net,
                "small_net": last.small_net,
            }
        return {
            "symbol": symbol,
            "flows": [minute_flow_to_dict(f) for f in flows],
            "summary": summary,
            "data_status": diagnostic["status"],
            "diagnostics": diagnostic,
        }
