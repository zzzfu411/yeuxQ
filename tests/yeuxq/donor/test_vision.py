from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from yeuxq.domain.models import FundFlow, Kline, Quote
from yeuxq.intel import research as R
from yeuxq.intel.agent_tools import ToolRunner, select_vision_tools
from yeuxq.intel.llm_client import LlmClient
from yeuxq.intel.research import ResearchService

VALID_MD = """# 贵州茅台(600519) 看图 · 大资金研判

## 1. 一句话结论
拉锯，置信度中。结合本地资金流与图表，大资金近期并未单边流入。

## 2. 资金证据
近十日主力净流入累计偏弱，量价配合一般，未见持续大单承接。

## 3. 技术结构佐证
日线均线纠缠，MACD 走平，关键位附近震荡。

## 4. 最新资讯与催化
检索未见重大减持或业绩暴雷。

## 5. 反证与风险
若放量跌破支撑则证伪中性判断。

## 6. 观察触发点
站上前高或跌破近期低点。

不构成投资建议。
"""

CONTRACT_KEYS = {
    "ok",
    "symbol",
    "name",
    "report_markdown",
    "error",
    "model",
    "vision",
    "usage",
    "filename",
    "saved_path",
    "ttl_hours",
    "generated_at",
    "news_ok",
    "agentic",
    "tool_trace",
    "tool_calls_count",
    "rounds",
    "budget_hit",
}

NEWS_TEXT = "【资讯】茅台渠道反馈平稳，未见大额减持公告"
SNAP = {"symbol": "600519", "metrics": {"pe_ttm": 19.88}, "raw_notes": ["SNAP_VISION_TEST"]}


def _ok_agentic(*, vision: bool = True, content: str = VALID_MD) -> dict:
    return {
        "ok": True,
        "content": content,
        "model": "grok-4.6",
        "usage": {"total_tokens": 12},
        "vision": vision,
        "rounds": 2,
        "budget_hit": False,
        "tools_unsupported": False,
        "error": None,
    }


def _ok_llm(*, vision: bool = True, content: str = VALID_MD) -> dict:
    return {
        "ok": True,
        "content": content,
        "model": "grok-4.6",
        "usage": {"total_tokens": 12},
        "vision": vision,
        "raw": {},
    }


def _svc(llm_return: dict | None = None, *, news_ok: bool = True) -> ResearchService:
    svc = ResearchService.__new__(ResearchService)
    svc.cfg = {"llm_model": "grok-4.6"}
    svc.llm = MagicMock()
    agentic = llm_return or _ok_agentic()
    svc.llm.chat_agentic.return_value = agentic
    svc.llm.chat_vision.return_value = _ok_llm(
        vision=bool(agentic.get("vision")),
        content=str(agentic.get("content") or ""),
    )
    svc.yeux = MagicMock()
    svc.yeux.available.return_value = True
    if news_ok:
        svc.yeux.search.return_value = {
            "ok": True,
            "text": NEWS_TEXT,
            "tool": "yeux_search",
            "elapsed_sec": 0.12,
        }
    else:
        svc.yeux.search.return_value = {
            "ok": False,
            "error": "timeout",
            "text": "",
            "tool": "yeux_search",
            "elapsed_sec": 0.01,
        }
    return svc


def _patch_snapshot(monkeypatch):
    monkeypatch.setattr(R, "fetch_finance_snapshot", lambda symbol, timeout=12.0: SNAP)


def _agentic_runs(name: str, arguments: dict | None = None, content: str = VALID_MD):
    def _fn(system, prompt, images, tools, tool_runner, **kwargs):
        tool_runner.run(name, arguments or {})
        return _ok_agentic(vision=False, content=content)

    return _fn


class _Resp:
    def __init__(self, status_code: int, text: str = "", json_data: dict | None = None):
        self.status_code = status_code
        self.text = text
        self._json = json_data or {}

    def json(self):
        return self._json


def _patch_httpx(monkeypatch, responses: list[_Resp]):
    class CallLog(list):
        def __init__(self):
            super().__init__()
            self.timeouts: list = []

    calls: CallLog = CallLog()

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, headers=None, json=None, timeout=None, **kwargs):
            calls.append(deepcopy(json))
            calls.timeouts.append(timeout)
            idx = min(len(calls) - 1, len(responses) - 1)
            return responses[idx]

    monkeypatch.setattr("yeuxq.intel.llm_client.httpx.Client", FakeClient)
    return calls


def _patch_httpx_fn(monkeypatch, handler):
    class CallLog(list):
        def __init__(self):
            super().__init__()
            self.timeouts: list = []

    calls: CallLog = CallLog()

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, headers=None, json=None, timeout=None, **kwargs):
            calls.append(deepcopy(json))
            calls.timeouts.append(timeout)
            return handler(json, calls)

    monkeypatch.setattr("yeuxq.intel.llm_client.httpx.Client", FakeClient)
    return calls


def test_save_vision_kind_and_parse(tmp_path: Path):
    folder = tmp_path / "reports"
    saved = R._save_report("600519", "vision", "# 看图", folder=folder)
    assert saved["filename"].startswith("600519_vision_")
    assert saved["filename"].endswith(".md")
    parsed = R._parse_report_name(saved["filename"])
    assert parsed is not None
    assert parsed["symbol"] == "600519"
    assert parsed["kind"] == "vision"
    listed = R.list_saved_reports(symbol="600519", folder=folder)
    assert listed[0]["kind"] == "vision"
    assert Path(saved["saved_path"]).is_file()


def test_generate_vision_report_saves_and_contract(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(R, "ROOT", tmp_path)
    svc = _svc(_ok_agentic(vision=True, content=VALID_MD))
    out = svc.generate_vision_report(
        "600519",
        name="贵州茅台",
        view="day",
        range_=250,
        ind="macd",
        image="data:image/jpeg;base64,abc",
        context={
            "quote": {"name": "贵州茅台", "price": 1400.5, "pct": 1.2, "turnover": 0.31},
            "signal": {
                "action": "买入",
                "score": 72,
                "buy_signals": ["趋势上升"],
                "sell_signals": [],
                "key_levels": {"入场": 1390},
                "trade_plan": {"action": "买入", "entry_price": 1390},
            },
            "prediction": {"direction": "看多", "tilt": 0.62, "drivers": ["主力连续流入"]},
            "flows": [{"date": "2026-08-12", "main_net": 2.5e8}],
        },
    )
    assert CONTRACT_KEYS <= set(out)
    assert out["ok"] is True
    assert out["vision"] is True
    assert out["agentic"] is True
    assert out["symbol"] == "600519"
    assert out["name"] == "贵州茅台"
    assert "看图" in out["report_markdown"]
    assert out["model"] == "grok-4.6"
    assert out["usage"] == {"total_tokens": 12}
    assert out["error"] is None
    assert out["news_ok"] is None
    assert out["filename"].startswith("600519_vision_")
    assert Path(out["saved_path"]).is_file()
    assert out["ttl_hours"] == 24
    assert out["tool_trace"] == []
    assert out["tool_calls_count"] == 0

    args, kwargs = svc.llm.chat_agentic.call_args
    assert args[0] == R.SYSTEM_VISION_AGENTIC
    assert args[2] == ["data:image/jpeg;base64,abc"]
    assert kwargs["temperature"] == 0.25
    assert kwargs["max_tokens"] == 4000
    assert kwargs["total_budget_sec"] == 180
    prompt = args[1]
    assert "日K · 近1年 · MACD" in prompt
    assert "请先阅读图中" in prompt
    assert "2.50亿" in prompt
    assert "主力连续流入" in prompt
    assert NEWS_TEXT not in prompt
    assert "SNAP_VISION_TEST" not in prompt
    assert "## 4. 最新资讯与催化" in prompt
    assert "## 6. 观察触发点" in prompt
    assert "## 7. 调查过程" in prompt
    assert "本地数据" in prompt
    svc.yeux.search.assert_not_called()


def test_generate_vision_report_no_image(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(R, "ROOT", tmp_path)
    svc = _svc(_ok_agentic(vision=False, content=VALID_MD))
    out = svc.generate_vision_report("600519", name="贵州茅台", image="")
    assert CONTRACT_KEYS <= set(out)
    assert out["ok"] is True
    assert out["vision"] is False
    assert out["agentic"] is True
    assert out["news_ok"] is None
    assert "看图" in out["report_markdown"]
    args, _kwargs = svc.llm.chat_agentic.call_args
    assert args[2] == []
    assert "本次无图表，仅基于数字上下文" in args[1]


def test_generate_vision_report_skips_news(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(R, "ROOT", tmp_path)
    svc = _svc(_ok_agentic(vision=False, content=VALID_MD))
    out = svc.generate_vision_report("600519", name="贵州茅台", image="", with_news=False)
    assert out["news_ok"] is None
    svc.yeux.search.assert_not_called()
    args, _kwargs = svc.llm.chat_agentic.call_args
    names = [t["function"]["name"] for t in args[3]]
    assert "yeux_search" not in names
    assert "yeux_deep_search" not in names
    assert "本次未开启资讯检索" in args[1]


def test_generate_vision_report_news_fail(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(R, "ROOT", tmp_path)
    svc = _svc(news_ok=False)
    svc.llm.chat_agentic.side_effect = _agentic_runs(
        "yeux_search", {"query": "x"}, content=VALID_MD
    )
    out = svc.generate_vision_report("600519", name="贵州茅台", image="")
    assert out["news_ok"] is False
    assert out["agentic"] is True
    assert "看图" in out["report_markdown"]


def test_chat_vision_image_degrade(monkeypatch):
    ok = {
        "choices": [{"message": {"content": "降级文本"}}],
        "model": "grok-4.6",
        "usage": {"total_tokens": 3},
    }
    calls = _patch_httpx(
        monkeypatch,
        [
            _Resp(400, text="this gateway does not support image input"),
            _Resp(200, json_data=ok),
        ],
    )
    client = LlmClient(base_url="https://example.invalid/v1", api_key="sk-test", model="grok-4.6")
    out = client.chat_vision(
        "sys",
        "请看图",
        ["data:image/jpeg;base64,xx"],
        temperature=0.3,
        max_tokens=100,
    )
    assert out["ok"] is True
    assert out["vision"] is False
    assert out["content"] == "降级文本"
    assert len(calls) == 2
    first_user = calls[0]["messages"][1]["content"]
    assert isinstance(first_user, list)
    assert first_user[1]["type"] == "image_url"
    second_user = calls[1]["messages"][1]["content"]
    assert second_user == "请看图"


def test_chat_vision_empty_images_text_only(monkeypatch):
    calls = _patch_httpx(
        monkeypatch,
        [
            _Resp(
                200,
                json_data={
                    "choices": [{"message": {"content": "纯文本"}}],
                    "model": "grok-4.6",
                    "usage": {},
                },
            )
        ],
    )
    client = LlmClient(base_url="https://example.invalid/v1", api_key="sk-test")
    out = client.chat_vision("sys", "hello", [])
    assert out["ok"] is True
    assert out["vision"] is False
    assert calls[0]["messages"][1]["content"] == "hello"


def _vision_client(monkeypatch, payload: dict) -> TestClient:
    class FakeResearch:
        def generate_vision_report(self, **kwargs):
            return payload

    class FakeContainer:
        research = FakeResearch()

    monkeypatch.setattr("yeuxq.api.routes_research.get_container", lambda: FakeContainer())
    app = FastAPI()
    from yeuxq.api.routes_research import router

    app.include_router(router)
    return TestClient(app)


def test_vision_route_ok(monkeypatch):
    payload = {
        "ok": True,
        "symbol": "600519",
        "name": "贵州茅台",
        "report_markdown": "# md",
        "error": None,
        "model": "grok-4.6",
        "vision": True,
        "usage": {"total_tokens": 10},
        "filename": "600519_vision_20260813_163000.md",
        "saved_path": "data/reports/600519_vision_20260813_163000.md",
        "ttl_hours": 24,
        "news_ok": True,
        "agentic": True,
        "tool_trace": [],
        "tool_calls_count": 0,
        "rounds": 2,
        "budget_hit": False,
        "generated_at": "2026-08-13T08:30:00+00:00",
    }
    client = _vision_client(monkeypatch, payload)
    r = client.post(
        "/api/research/vision",
        json={
            "symbol": "600519",
            "name": "贵州茅台",
            "view": "day",
            "range": 250,
            "ind": "macd",
            "image": "data:image/jpeg;base64,xx",
            "context": {"quote": {"price": 1}},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert CONTRACT_KEYS <= set(body)
    assert body["ok"] is True
    assert body["vision"] is True
    assert body["report_markdown"] == "# md"


def test_vision_route_invalid_symbol():
    app = FastAPI()
    from yeuxq.api.routes_research import router

    app.include_router(router)
    client = TestClient(app)
    r = client.post("/api/research/vision", json={"symbol": "abc"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "无效股票代码"
    assert body["report_markdown"] == ""
    assert body["vision"] is False
    assert body["agentic"] is False
    assert body["tool_trace"] == []
    assert body["tool_calls_count"] == 0
    assert body["rounds"] == 0
    assert body["budget_hit"] is False


def _mock_container(monkeypatch, *, flows=None, klines=None, quote=None, realtime=None):
    container = MagicMock()
    container.data.fetch_fund_flow.return_value = flows or []
    container.data.fetch_kline.return_value = klines or []
    container.data.fetch_quote.return_value = quote
    container.analyze.realtime_flow_payload.return_value = realtime or {
        "symbol": "600519",
        "summary": {},
        "flows": [],
    }
    monkeypatch.setattr("yeuxq.api.deps.get_container", lambda: container)
    return container


def test_tool_runner_compresses_flow_and_klines(monkeypatch):
    flows = [
        FundFlow(
            date=f"d{i:03d}",
            main_net=1e8 if i % 2 == 0 else -2e8,
            super_large_net=5e7,
            large_net=5e7,
            medium_net=0,
            small_net=0,
            main_pct=10,
        )
        for i in range(80)
    ]
    klines = [
        Kline(
            date=f"2026-01-{(i % 28) + 1:02d}",
            open=100 + i,
            close=101 + i,
            high=102 + i,
            low=99 + i,
            volume=1000 + i,
            pct=0.5,
        )
        for i in range(120)
    ]
    _mock_container(monkeypatch, flows=flows, klines=klines)
    research = MagicMock()
    runner = ToolRunner(research, max_tool_calls=8)
    flow_text = runner.run("get_fund_flow", {"symbol": "600519", "days": 80})
    assert "亿" in flow_text
    assert len(flow_text) <= 4000
    k_text = runner.run("get_klines", {"symbol": "600519", "period": "day", "count": 120})
    assert "MA5" in k_text
    data_lines = [ln for ln in k_text.splitlines() if ln[:4].isdigit() or ln.startswith("2026-")]
    assert len(data_lines) <= 22


def test_tool_runner_swallows_errors(monkeypatch):
    container = _mock_container(monkeypatch)
    container.data.fetch_quote.side_effect = RuntimeError("boom")
    runner = ToolRunner(MagicMock())
    text = runner.run("get_quote", {"symbol": "600519"})
    assert text.startswith("工具执行失败：")
    assert "boom" in text
    assert runner.trace[-1]["ok"] is False


def test_tool_runner_budget_exhausted():
    research = MagicMock()
    research.yeux.search.return_value = {"ok": True, "text": "ok"}
    runner = ToolRunner(research, max_tool_calls=1, total_budget_sec=180)
    first = runner.run("yeux_search", {"query": "贵州茅台"})
    assert "ok" in first or "未检索" in first or "渠道" in first or first
    assert runner.exhausted is True
    second = runner.run("yeux_search", {"query": "再查"})
    assert "调查预算已用尽" in second
    assert runner.exhausted is True
    assert len(runner.trace) == 1
    research.yeux.search.assert_called_once()


def test_tool_runner_max_deep_search():
    research = MagicMock()
    research.yeux.search.return_value = {"ok": True, "text": "deep-hit"}
    runner = ToolRunner(research, max_deep_search=1, max_tool_calls=8)
    a = runner.run("yeux_deep_search", {"query": "一次"})
    assert "deep-hit" in a
    b = runner.run("yeux_deep_search", {"query": "二次"})
    assert "深检索次数已用尽" in b
    assert runner.trace[-1]["ok"] is False
    research.yeux.search.assert_called_once()


def test_chat_agentic_multi_round(monkeypatch):
    tool_msg = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "yeux_search",
                                "arguments": '{"query": "贵州茅台 最新新闻"}',
                            },
                        }
                    ],
                }
            }
        ],
        "model": "grok-4.6",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    final_msg = {
        "choices": [{"message": {"role": "assistant", "content": "终稿"}}],
        "model": "grok-4.6",
        "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
    }
    calls = _patch_httpx(
        monkeypatch, [_Resp(200, json_data=tool_msg), _Resp(200, json_data=final_msg)]
    )
    runner = MagicMock()
    runner.exhausted = False
    runner.run.return_value = "检索命中：渠道平稳"
    client = LlmClient(base_url="https://example.invalid/v1", api_key="sk-test")
    out = client.chat_agentic(
        "sys", "请调查", [], [{"type": "function", "function": {"name": "yeux_search"}}], runner
    )
    assert out["ok"] is True
    assert out["rounds"] == 2
    assert out["content"] == "终稿"
    assert out["budget_hit"] is False
    runner.run.assert_called_once_with("yeux_search", {"query": "贵州茅台 最新新闻"})
    roles = [m.get("role") for m in calls[1]["messages"]]
    assert "tool" in roles
    tool_msgs = [m for m in calls[1]["messages"] if m.get("role") == "tool"]
    assert tool_msgs[0]["tool_call_id"] == "call_1"
    assert tool_msgs[0]["content"] == "检索命中：渠道平稳"
    assert "tools" in calls[0]
    assert "tools" in calls[1]


def test_chat_agentic_wrap_up_without_tools(monkeypatch):
    tool_msg = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_x",
                            "type": "function",
                            "function": {"name": "get_quote", "arguments": '{"symbol":"600519"}'},
                        }
                    ],
                }
            }
        ],
        "model": "grok-4.6",
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    final_msg = {
        "choices": [{"message": {"content": "收尾终稿"}}],
        "model": "grok-4.6",
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    }

    def handler(payload, _calls):
        if payload and payload.get("tools"):
            return _Resp(200, json_data=tool_msg)
        return _Resp(200, json_data=final_msg)

    calls = _patch_httpx_fn(monkeypatch, handler)
    runner = MagicMock()
    runner.exhausted = False
    runner.run.return_value = "行情ok"
    client = LlmClient(base_url="https://example.invalid/v1", api_key="sk-test")
    out = client.chat_agentic(
        "sys",
        "请调查",
        [],
        [{"type": "function", "function": {"name": "get_quote"}}],
        runner,
        max_rounds=2,
        total_budget_sec=180,
    )
    assert out["ok"] is True
    assert out["budget_hit"] is True
    assert out["content"] == "收尾终稿"
    assert any("tools" not in c for c in calls)
    last = calls[-1]
    assert "tools" not in last
    assert last["messages"][-1]["content"].startswith("调查预算已用尽")


def test_tools_unsupported_falls_back_legacy(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(R, "ROOT", tmp_path)
    _patch_snapshot(monkeypatch)

    def handler(payload, _calls):
        if payload and payload.get("tools"):
            return _Resp(400, text="function calling not supported")
        return _Resp(
            200,
            json_data={
                "choices": [{"message": {"content": VALID_MD}}],
                "model": "grok-4.6",
                "usage": {"total_tokens": 4},
            },
        )

    _patch_httpx_fn(monkeypatch, handler)
    svc = ResearchService.__new__(ResearchService)
    svc.cfg = {"llm_model": "grok-4.6"}
    svc.llm = LlmClient(base_url="https://example.invalid/v1", api_key="sk-test")
    svc.yeux = MagicMock()
    svc.yeux.available.return_value = True
    svc.yeux.search.return_value = {
        "ok": True,
        "text": NEWS_TEXT,
        "tool": "yeux_search",
        "elapsed_sec": 0.1,
    }
    out = svc.generate_vision_report("600519", name="贵州茅台", image="")
    assert out["ok"] is True
    assert out["agentic"] is False
    assert out["report_markdown"] == VALID_MD
    svc.yeux.search.assert_called()


def test_with_news_false_excludes_yeux_tools(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(R, "ROOT", tmp_path)
    svc = _svc()
    svc.generate_vision_report("600519", name="贵州茅台", with_news=False)
    tools = svc.llm.chat_agentic.call_args[0][3]
    names = [t["function"]["name"] for t in tools]
    assert "yeux_search" not in names
    assert "yeux_deep_search" not in names
    assert "get_fund_flow" in names
    names_all = [t["function"]["name"] for t in select_vision_tools(with_news=False, deep=False)]
    assert names_all == names


def test_news_ok_true_when_yeux_succeeds(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(R, "ROOT", tmp_path)
    svc = _svc(news_ok=True)
    svc.llm.chat_agentic.side_effect = _agentic_runs("yeux_search", {"query": "贵州茅台 最新新闻"})
    out = svc.generate_vision_report("600519", name="贵州茅台")
    assert out["news_ok"] is True


def test_news_ok_false_when_yeux_fails(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(R, "ROOT", tmp_path)
    svc = _svc(news_ok=False)
    svc.llm.chat_agentic.side_effect = _agentic_runs("yeux_search", {"query": "贵州茅台"})
    out = svc.generate_vision_report("600519", name="贵州茅台")
    assert out["news_ok"] is False


def test_news_ok_none_when_never_called(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(R, "ROOT", tmp_path)
    svc = _svc()
    out = svc.generate_vision_report("600519", name="贵州茅台", with_news=True)
    assert out["news_ok"] is None
    svc.yeux.search.assert_not_called()


def test_reasoning_effort_unsupported_retries_not_legacy(monkeypatch):
    def handler(payload, _calls):
        if payload and payload.get("reasoning_effort"):
            return _Resp(400, text="reasoning_effort unsupported")
        return _Resp(
            200,
            json_data={
                "choices": [{"message": {"content": "降级成功"}}],
                "model": "grok-4.6",
                "usage": {"total_tokens": 2},
            },
        )

    calls = _patch_httpx_fn(monkeypatch, handler)
    runner = MagicMock()
    runner.exhausted = False
    client = LlmClient(
        base_url="https://example.invalid/v1", api_key="sk-test", reasoning_effort="xhigh"
    )
    out = client.chat_agentic(
        "sys",
        "请调查",
        [],
        [{"type": "function", "function": {"name": "yeux_search"}}],
        runner,
    )
    assert out["ok"] is True
    assert out["tools_unsupported"] is False
    assert out["content"] == "降级成功"
    assert any(c.get("reasoning_effort") for c in calls)
    assert any("reasoning_effort" not in c for c in calls)


def test_wrap_up_400_with_function_not_tools_unsupported(monkeypatch):
    tool_msg = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_w",
                            "type": "function",
                            "function": {"name": "get_quote", "arguments": '{"symbol":"600519"}'},
                        }
                    ],
                }
            }
        ],
        "model": "grok-4.6",
        "usage": {"total_tokens": 1},
    }

    def handler(payload, _calls):
        if payload and payload.get("tools"):
            return _Resp(200, json_data=tool_msg)
        return _Resp(400, text="invalid function schema in request")

    _patch_httpx_fn(monkeypatch, handler)
    runner = MagicMock()
    runner.exhausted = False
    runner.run.return_value = "ok"
    client = LlmClient(base_url="https://example.invalid/v1", api_key="sk-test")
    out = client.chat_agentic(
        "sys",
        "请调查",
        [],
        [{"type": "function", "function": {"name": "get_quote"}}],
        runner,
        max_rounds=1,
        total_budget_sec=150,
    )
    assert out["tools_unsupported"] is False
    assert out["budget_hit"] is True
    assert out["ok"] is False


def test_post_timeout_shrinks_with_remaining_budget(monkeypatch):
    clock = {"now": 0.0}
    monkeypatch.setattr("yeuxq.intel.llm_client.time.time", lambda: clock["now"])
    tool_msg = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_t",
                            "type": "function",
                            "function": {"name": "get_quote", "arguments": '{"symbol":"600519"}'},
                        }
                    ],
                }
            }
        ],
        "model": "grok-4.6",
        "usage": {"total_tokens": 1},
    }
    final_msg = {
        "choices": [{"message": {"content": "收尾"}}],
        "model": "grok-4.6",
        "usage": {"total_tokens": 1},
    }

    def handler(payload, _calls):
        clock["now"] += 80.0
        if payload and payload.get("tools"):
            return _Resp(200, json_data=tool_msg)
        return _Resp(200, json_data=final_msg)

    calls = _patch_httpx_fn(monkeypatch, handler)
    runner = MagicMock()
    runner.exhausted = False
    runner.run.return_value = "ok"
    client = LlmClient(base_url="https://example.invalid/v1", api_key="sk-test", timeout=240.0)
    out = client.chat_agentic(
        "sys",
        "请调查",
        [],
        [{"type": "function", "function": {"name": "get_quote"}}],
        runner,
        max_rounds=2,
        total_budget_sec=150,
    )
    assert out["ok"] is True
    timeouts = calls.timeouts
    assert timeouts[0] == 150.0
    assert timeouts[1] == 70.0
    assert timeouts[-1] == 150.0


def test_agentic_empty_falls_back_legacy_keeps_trace(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(R, "ROOT", tmp_path)
    _patch_snapshot(monkeypatch)
    svc = _svc(news_ok=True)

    def _fn(system, prompt, images, tools, tool_runner, **kwargs):
        tool_runner.run("yeux_search", {"query": "贵州茅台"})
        return {
            "ok": False,
            "content": "",
            "model": "grok-4.6",
            "usage": None,
            "rounds": 1,
            "vision": False,
            "budget_hit": False,
            "tools_unsupported": False,
            "error": "HTTP 500: boom",
        }

    svc.llm.chat_agentic.side_effect = _fn
    svc.llm.chat.return_value = _ok_llm(vision=False, content=VALID_MD)
    out = svc.generate_vision_report("600519", name="贵州茅台", image="")
    assert out["ok"] is True
    assert out["agentic"] is False
    assert out["report_markdown"] == VALID_MD
    assert out["error"] is None
    assert out["tool_calls_count"] >= 1
    assert out["tool_trace"]
    assert out["tool_trace"][0]["name"] == "yeux_search"
    assert svc.yeux.search.call_count == 1
    svc.llm.chat_vision.assert_not_called()
    user = svc.llm.chat.call_args[0][0][1]["content"]
    assert "不要再要求工具" in user
    assert "### yeux_search" in user


_TOOL_CALL_MSG = {
    "choices": [
        {
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_q",
                        "type": "function",
                        "function": {"name": "get_quote", "arguments": '{"symbol":"600519"}'},
                    }
                ],
            }
        }
    ],
    "model": "grok-4.6",
    "usage": {"total_tokens": 1},
}


def test_legacy_system_prompt_has_no_tool_discipline(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(R, "ROOT", tmp_path)
    _patch_snapshot(monkeypatch)
    assert "你可以调用工具" not in R.SYSTEM_VISION
    assert "get_fund_flow" not in R.SYSTEM_VISION
    assert "你可以调用工具" in R.SYSTEM_VISION_AGENTIC
    assert "get_fund_flow" in R.SYSTEM_VISION_AGENTIC

    svc = _svc()
    svc.generate_vision_report("600519", name="贵州茅台", image="")
    assert svc.llm.chat_agentic.call_args[0][0] == R.SYSTEM_VISION_AGENTIC

    svc.llm.chat_agentic.return_value = {
        "ok": False,
        "content": "",
        "model": "grok-4.6",
        "usage": None,
        "rounds": 1,
        "vision": False,
        "budget_hit": False,
        "tools_unsupported": False,
        "error": "生成失败",
    }
    svc.llm.chat_vision.return_value = _ok_llm(vision=False, content=VALID_MD)
    svc.generate_vision_report("600519", name="贵州茅台", image="")
    assert svc.llm.chat_vision.call_args[0][0] == R.SYSTEM_VISION


def test_tool_round_readtimeout_wraps_up_keeps_trace(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(R, "ROOT", tmp_path)
    _patch_snapshot(monkeypatch)
    _mock_container(
        monkeypatch,
        quote=Quote(
            symbol="600519",
            name="贵州茅台",
            price=1400.0,
            pct=0.5,
            change=7.0,
            high=1410.0,
            low=1390.0,
            open=1395.0,
            pre_close=1393.0,
            volume=1e6,
            amount=1e9,
            turnover=0.3,
        ),
    )
    n = {"i": 0}

    def handler(payload, _calls):
        if payload and payload.get("tools"):
            n["i"] += 1
            if n["i"] >= 2:
                raise httpx.ReadTimeout("read timeout")
            return _Resp(200, json_data=_TOOL_CALL_MSG)
        return _Resp(
            200,
            json_data={
                "choices": [{"message": {"content": VALID_MD}}],
                "model": "grok-4.6",
                "usage": {"total_tokens": 3},
            },
        )

    _patch_httpx_fn(monkeypatch, handler)
    svc = ResearchService.__new__(ResearchService)
    svc.cfg = {"llm_model": "grok-4.6"}
    svc.llm = LlmClient(base_url="https://example.invalid/v1", api_key="sk-test")
    svc.yeux = MagicMock()
    svc.yeux.available.return_value = True
    out = svc.generate_vision_report("600519", name="贵州茅台", image="")
    assert out["ok"] is True
    assert out["agentic"] is True
    assert out["budget_hit"] is True
    assert out["tool_trace"]
    assert out["tool_trace"][0]["name"] == "get_quote"
    assert "<tool_call>" not in out["report_markdown"]
    assert Path(out["saved_path"]).is_file()


def test_remaining_under_45s_skips_new_tool_round(monkeypatch):
    clock = {"now": 0.0}
    monkeypatch.setattr("yeuxq.intel.llm_client.time.time", lambda: clock["now"])

    def handler(payload, _calls):
        if payload and payload.get("tools"):
            clock["now"] += 140.0
            return _Resp(200, json_data=_TOOL_CALL_MSG)
        return _Resp(
            200,
            json_data={
                "choices": [{"message": {"content": "直接收尾"}}],
                "model": "grok-4.6",
                "usage": {"total_tokens": 1},
            },
        )

    calls = _patch_httpx_fn(monkeypatch, handler)
    runner = MagicMock()
    runner.exhausted = False
    runner.run.return_value = "行情ok"
    client = LlmClient(base_url="https://example.invalid/v1", api_key="sk-test", timeout=240.0)
    out = client.chat_agentic(
        "sys",
        "请调查",
        [],
        [{"type": "function", "function": {"name": "get_quote"}}],
        runner,
        max_rounds=6,
        total_budget_sec=180,
    )
    assert out["ok"] is True
    assert out["budget_hit"] is True
    assert out["content"] == "直接收尾"
    tool_payloads = [c for c in calls if c.get("tools")]
    assert len(tool_payloads) == 1
    assert "tools" not in calls[-1]
    runner.run.assert_called_once()


def test_tool_round_reasoning_low_wrap_up_xhigh(monkeypatch):
    def handler(payload, _calls):
        if payload and payload.get("tools"):
            return _Resp(200, json_data=_TOOL_CALL_MSG)
        return _Resp(
            200,
            json_data={
                "choices": [{"message": {"content": "合成终稿"}}],
                "model": "grok-4.6",
                "usage": {"total_tokens": 2},
            },
        )

    calls = _patch_httpx_fn(monkeypatch, handler)
    runner = MagicMock()
    runner.exhausted = False
    runner.run.return_value = "行情ok"
    client = LlmClient(
        base_url="https://example.invalid/v1",
        api_key="sk-test",
        reasoning_effort="xhigh",
    )
    out = client.chat_agentic(
        "sys",
        "请调查",
        [],
        [{"type": "function", "function": {"name": "get_quote"}}],
        runner,
        max_rounds=1,
    )
    assert out["ok"] is True
    tool_payloads = [c for c in calls if c.get("tools")]
    wrap_payloads = [c for c in calls if not c.get("tools")]
    assert tool_payloads
    assert wrap_payloads
    assert all(c.get("reasoning_effort") == "low" for c in tool_payloads)
    assert all(c.get("reasoning_effort") == "xhigh" for c in wrap_payloads)


def test_is_valid_report_and_tool_call_garbage_falls_back(tmp_path: Path, monkeypatch):
    assert R._is_valid_report('<tool_call>\n{"name": "get_fund_flow"}\n</tool_call>') is False
    assert R._is_valid_report("# 茅台看图") is False
    assert R._is_valid_report(VALID_MD) is True
    padded = "正文" * 80 + '\n"arguments": {"symbol": "600519"}'
    assert R._is_valid_report(padded) is False

    monkeypatch.setattr(R, "ROOT", tmp_path)
    _patch_snapshot(monkeypatch)
    garbage = (
        "先核对本地资金流、估值快照与近期K线/MACD。\n"
        "<tool_call>\n"
        '{"name": "get_fund_flow", "arguments": {"symbol": "600519"}}\n'
        "</tool_call>\n"
    )
    svc = _svc(_ok_agentic(content=garbage))
    svc.llm.chat_vision.return_value = _ok_llm(vision=False, content=VALID_MD)
    out = svc.generate_vision_report("600519", name="贵州茅台", image="")
    assert out["ok"] is True
    assert out["agentic"] is False
    assert out["report_markdown"] == VALID_MD
    assert "<tool_call>" not in out["report_markdown"]
    folder = tmp_path / "data" / "reports"
    saved = list(folder.glob("*.md")) if folder.exists() else []
    assert saved
    for p in saved:
        text = p.read_text(encoding="utf-8")
        assert "<tool_call>" not in text
        assert '"arguments":' not in text

    svc.llm.chat_agentic.return_value = {
        "ok": False,
        "content": "",
        "model": "grok-4.6",
        "usage": None,
        "rounds": 1,
        "vision": False,
        "budget_hit": False,
        "tools_unsupported": False,
        "error": "生成失败",
    }
    svc.llm.chat_vision.return_value = _ok_llm(content=garbage)
    out2 = svc.generate_vision_report("600519", name="贵州茅台", image="")
    assert out2["ok"] is False
    assert out2["error"] == "模型返回了无效内容"
    for p in folder.glob("*.md"):
        assert "<tool_call>" not in p.read_text(encoding="utf-8")


def test_tool_round_http_524_wraps_up(monkeypatch):
    n = {"i": 0}

    def handler(payload, _calls):
        if payload and payload.get("tools"):
            n["i"] += 1
            if n["i"] >= 2:
                return _Resp(524, text="error code: 524")
            return _Resp(200, json_data=_TOOL_CALL_MSG)
        return _Resp(
            200,
            json_data={
                "choices": [{"message": {"content": "收尾合成稿"}}],
                "model": "grok-4.6",
                "usage": {"total_tokens": 3},
            },
        )

    _patch_httpx_fn(monkeypatch, handler)
    runner = MagicMock()
    runner.exhausted = False
    runner.trace = []
    runner.run.side_effect = lambda name, args: (
        runner.trace.append({"name": name, "ok": True}) or "行情ok"
    )
    client = LlmClient(base_url="https://example.invalid/v1", api_key="sk-test")
    out = client.chat_agentic(
        "sys",
        "请调查",
        [],
        [{"type": "function", "function": {"name": "get_quote"}}],
        runner,
        max_rounds=6,
        total_budget_sec=180,
    )
    assert out["ok"] is True
    assert out["budget_hit"] is True
    assert out["content"] == "收尾合成稿"
    assert runner.trace
    runner.run.assert_called()


def test_compress_messages_for_wrap_up_clips_tools():
    from yeuxq.intel.llm_client import _compress_messages_for_wrap_up

    messages = [
        {"role": "system", "content": "sys-keep"},
        {"role": "user", "content": "first-user-keep"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "c1", "function": {"name": "yeux_search", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "T" * 8000},
    ]
    _compress_messages_for_wrap_up(messages, limit=100, clip=40)
    assert messages[0]["content"] == "sys-keep"
    assert messages[1]["content"] == "first-user-keep"
    assert messages[2]["tool_calls"][0]["id"] == "c1"
    assert messages[3]["content"].startswith("T" * 40)
    assert "已截断" in messages[3]["content"]


def test_tool_runner_keeps_full_results():
    research = MagicMock()
    research.yeux.search.return_value = {
        "ok": True,
        "text": "完整检索正文应保留下来供回落写财报使用",
    }
    runner = ToolRunner(research)
    runner.run("yeux_search", {"query": "贵州茅台 年报"})
    assert runner.full_results
    assert runner.full_results[0].startswith("### yeux_search query=贵州茅台 年报")
    assert "完整检索正文" in runner.full_results[0]
    assert runner.trace[0]["name"] == "yeux_search"
    assert len(runner.trace[0]["summary"]) <= 200
