from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import yeuxq.analysis.engine as engine_module
import yeuxq.api.routes_analyze as analyze_routes
import yeuxq.services.backtest as backtest_module
from yeuxq.domain.models import Kline
from yeuxq.providers.composite import CompositeMarketData
from yeuxq.services.analyze import AnalyzeService
from yeuxq.services.backtest import BacktestService
from yeuxq.settings import Settings
from yeuxq.storage.cache import MemoryCache


def _klines(count: int = 150) -> list[Kline]:
    start = date(2024, 1, 1)
    price = 100.0
    rows: list[Kline] = []
    for offset in range(count):
        close = price * 1.004
        rows.append(
            Kline(
                date=(start + timedelta(days=offset)).isoformat(),
                open=price,
                close=close,
                high=close * 1.01,
                low=price * 0.99,
                volume=10_000 + offset,
                amount=1_000_000,
                turnover=1.5,
            )
        )
        price = close
    return rows


def _market(http: object) -> CompositeMarketData:
    market = object.__new__(CompositeMarketData)
    market.cfg = SimpleNamespace(
        tencent_kline="tencent://kline",
        his_hosts=["https://history.invalid"],
        quote_hosts=["https://quote.invalid"],
    )
    market.cache = MemoryCache()
    market.http = http
    return market


def test_index_fallback_uses_shanghai_index_secid() -> None:
    class FakeHttp:
        calls: list[dict] = []

        def get_json(self, url: str, params: dict, **kwargs: object) -> dict | None:
            self.calls.append(dict(params))
            if url == "tencent://kline":
                return None
            return {"data": {"klines": ["2024-01-02,3000,3010,3020,2990,100,100000,0,0,0,1.2"]}}

    http = FakeHttp()
    rows = _market(http).fetch_index_kline("SH.000001", count=60)

    assert rows[0].close == 3010
    assert http.calls[-1]["secid"] == "1.000001"
    assert all(call.get("secid") != "0.000001" for call in http.calls)


def test_market_breadth_pages_the_full_universe_by_symbol() -> None:
    class FakeHttp:
        calls: list[dict] = []

        def get_json(self, url: str, params: dict, **kwargs: object) -> dict:
            self.calls.append(dict(params))
            page = int(params["pn"])
            start = (page - 1) * 100
            end = min(205, start + 100)
            diff = []
            for index in range(start, end):
                pct = 1.0 if index < 100 else (-1.0 if index < 200 else 0.0)
                diff.append({"f12": f"{index:06d}", "f3": pct})
            return {"data": {"total": 205, "diff": diff}}

    http = FakeHttp()
    breadth = _market(http).fetch_market_breadth()

    assert breadth["available"] is True
    assert breadth["complete"] is True
    assert breadth["up"] == 100
    assert breadth["down"] == 100
    assert breadth["flat"] == 5
    assert breadth["observed_symbols"] == breadth["universe_total"] == 205
    assert len(http.calls) == 3
    assert all(call["fid"] == "f12" for call in http.calls)


def test_incomplete_market_breadth_is_explicitly_unavailable() -> None:
    class FakeHttp:
        def get_json(self, url: str, params: dict, **kwargs: object) -> dict | None:
            if params["pn"] == "1":
                rows = [{"f12": f"{index:06d}", "f3": 1.0} for index in range(100)]
                return {"data": {"total": 150, "diff": rows}}
            return None

    breadth = _market(FakeHttp()).fetch_market_breadth()

    assert breadth["available"] is False
    assert breadth["complete"] is False
    assert breadth["reason"] == "incomplete_universe"


def test_breadth_recomputes_the_canonical_python_decision_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("YEUXQ_ENGINE", raising=False)
    monkeypatch.setattr(engine_module, "rust_status", lambda: {"available": True})

    def unexpected_rust(payload: dict) -> dict:
        raise AssertionError("canonical mode must not invoke Rust")

    monkeypatch.setattr(engine_module, "analyze_rust", unexpected_rust)
    settings = Settings()
    settings.engine.weights.trend = 0.0
    settings.engine.weights.momentum = 1.0
    settings.engine.weights.breakout = 0.0
    settings.engine.weights.volume_price = 0.0
    settings.engine.weights.pattern = 0.0
    rows = _klines()

    initial = engine_module.run_analysis(rows, settings=settings)
    settings.engine.action.strong_buy_score = 101
    settings.engine.action.buy_score = 101
    settings.engine.action.cautious_score = initial.score + 1
    baseline = engine_module.run_analysis(rows, settings=settings)
    breadth = {
        "available": True,
        "complete": True,
        "valid_quotes": 200,
        "up": 180,
        "down": 20,
        "breadth_ratio": 0.9,
    }
    adjusted = engine_module.run_analysis(
        rows,
        settings=settings,
        market_breadth=breadth,
    )

    assert adjusted.momentum is not None
    expected_total = int(
        adjusted.momentum.c_score * 0.15
        + adjusted.momentum.a_score * 0.10
        + adjusted.momentum.n_score * 0.25
        + adjusted.momentum.s_score * 0.05
        + adjusted.momentum.l_score * 0.20
        + adjusted.momentum.i_score * 0.15
        + adjusted.momentum.m_score * 0.10
    )
    assert adjusted.momentum.total == expected_total
    assert adjusted.module_scores["动量质量"] == expected_total
    assert adjusted.score > baseline.score
    assert adjusted.action != baseline.action
    assert adjusted.trade_plan.action == adjusted.action
    assert adjusted.prediction is not None and baseline.prediction is not None
    assert adjusted.prediction.prob_up != baseline.prediction.prob_up


def test_predict_api_rejects_unsupported_horizon(monkeypatch: pytest.MonkeyPatch) -> None:
    service = AnalyzeService(SimpleNamespace(), Settings())
    monkeypatch.setattr(
        analyze_routes,
        "get_container",
        lambda: SimpleNamespace(analyze=service),
    )

    with pytest.raises(HTTPException) as exc_info:
        analyze_routes.predict(symbol="600519", horizon=10)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == {
        "code": "unsupported_horizon",
        "requested": 10,
        "supported": [5],
    }


def test_single_backtest_keeps_python_canonical_when_rust_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _klines(140)

    class FakeData:
        def fetch_kline(self, *args: object, **kwargs: object) -> list[Kline]:
            return rows

        def fetch_fund_flow(self, *args: object, **kwargs: object) -> list:
            return []

        def fetch_index_kline(self, *args: object, **kwargs: object) -> list[Kline]:
            return rows

    monkeypatch.delenv("YEUXQ_ENGINE", raising=False)
    monkeypatch.setattr(backtest_module, "rust_status", lambda: {"available": True})
    monkeypatch.setattr(
        backtest_module,
        "backtest_rust",
        lambda payload: pytest.fail("Rust must not be selected implicitly"),
    )
    service = BacktestService(FakeData(), Settings())
    monkeypatch.setattr(service, "_legacy", lambda *args, **kwargs: {"engine": "python"})

    assert service.run("600519", lookback=120) == {"engine": "python"}


def test_explicit_rust_failure_falls_back_without_leaking_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _klines(140)

    class FakeData:
        def fetch_kline(self, *args: object, **kwargs: object) -> list[Kline]:
            return rows

        def fetch_fund_flow(self, *args: object, **kwargs: object) -> list:
            return []

        def fetch_index_kline(self, *args: object, **kwargs: object) -> list[Kline]:
            return rows

    monkeypatch.setenv("YEUXQ_ENGINE", "rust")
    monkeypatch.setattr(backtest_module, "rust_status", lambda: {"available": True})

    def fail_rust(payload: dict) -> dict:
        raise RuntimeError("sensitive implementation detail")

    monkeypatch.setattr(backtest_module, "backtest_rust", fail_rust)
    service = BacktestService(FakeData(), Settings())
    monkeypatch.setattr(service, "_legacy", lambda *args, **kwargs: {"engine": "python"})

    result = service.run("600519", lookback=120)

    assert result == {
        "engine": "python",
        "fallback": "python",
        "fallback_reason": "rust_error",
    }
    assert "sensitive" not in str(result)


def test_compare_uses_disjoint_decision_and_outcome_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _klines(140)

    class FakeData:
        def fetch_kline(self, *args: object, **kwargs: object) -> list[Kline]:
            return rows

        def fetch_fund_flow(self, *args: object, **kwargs: object) -> list:
            return []

        def fetch_index_kline(self, *args: object, **kwargs: object) -> list[Kline]:
            return rows

    calls: list[dict] = []
    monkeypatch.setattr(backtest_module, "rust_status", lambda: {"available": True})

    def capture(payload: dict) -> dict:
        calls.append(payload)
        return {"trades": 0, "win_rate": 0, "expectancy": 0}

    monkeypatch.setattr(backtest_module, "backtest_rust", capture)
    report = BacktestService(FakeData(), Settings()).compare(
        ["600519"],
        lookback=120,
        train_ratio=0.7,
    )

    row = report["per_symbol"][0]
    train_calls = [call for call in calls if "outcome_end" in call]
    valid_calls = [call for call in calls if "eval_start" in call]
    assert row["train_end"] < row["validation_start"]
    assert len(train_calls) == len(valid_calls) == 3
    assert all(call["eval_end"] == row["train_end"] for call in train_calls)
    assert all(call["outcome_end"] == row["train_end"] for call in train_calls)
    assert all(call["eval_start"] == row["validation_start"] for call in valid_calls)
