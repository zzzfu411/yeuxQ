from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from yeuxq.intel import research as R
from yeuxq.intel.agent_tools import select_earnings_tools, select_report_tools
from yeuxq.intel.research import ResearchService

VALID_MD = """# 贵州茅台(600519) 财报 / 投研速报

## 1. 一句话结论
业绩稳健，估值与本地快照口径一致，消息面未见重大减持。结合检索与本地资金流，大资金没有单边出逃。

## 2. 要点
营收与净利均有披露，数字来自检索与本地快照交叉核对。材料未披露的口径明确写未知，不编造。

## 3. 核对
本地 PE/PB 与检索口径一致，资金流未出现单边出逃。现价与换手可用于印证消息面。

## 4. 风险
若后续正式披露与快报口径分歧，需要再核验。宏观与消费需求仍是主要不确定性。

## 5. 来源
检索材料与本地估值快照均已对照。文末声明不构成投资建议。

不构成投资建议。
"""

NEWS_TEXT = "【资讯】茅台年报营收约1500亿，净利约750亿，渠道反馈平稳"
SNAP = {"symbol": "600519", "metrics": {"pe_ttm": 19.88}, "raw_notes": ["SNAP_EARNINGS_TEST"]}

AGENTIC_KEYS = {"agentic", "tool_trace", "tool_calls_count", "rounds", "budget_hit"}


def _ok_agentic(*, content: str = VALID_MD) -> dict:
    return {
        "ok": True,
        "content": content,
        "model": "grok-4.6",
        "usage": {"total_tokens": 12},
        "vision": False,
        "rounds": 3,
        "budget_hit": False,
        "tools_unsupported": False,
        "error": None,
    }


def _ok_chat(*, content: str = VALID_MD) -> dict:
    return {
        "ok": True,
        "content": content,
        "model": "grok-4.6",
        "usage": {"total_tokens": 12},
    }


def _svc() -> ResearchService:
    svc = ResearchService.__new__(ResearchService)
    svc.cfg = {"llm_model": "grok-4.6"}
    svc.llm = MagicMock()
    svc.llm.chat_agentic.return_value = _ok_agentic()
    svc.llm.chat.return_value = _ok_chat()
    svc.yeux = MagicMock()
    svc.yeux.available.return_value = True
    svc.yeux.search.return_value = {
        "ok": True,
        "text": NEWS_TEXT,
        "tool": "yeux_search",
        "elapsed_sec": 0.12,
    }
    svc.analyze = MagicMock()
    quote = MagicMock()
    quote.name = "贵州茅台"
    svc.analyze.data.fetch_quote.return_value = quote
    svc.analyze.analyze.return_value = {
        "quote": {"name": "贵州茅台"},
        "signal": {
            "action": "买入",
            "score": 72,
            "confidence": 55,
            "plain_summary": "多头",
            "module_scores": {},
            "trade_plan": {},
            "risk_warnings": [],
        },
        "prediction": {},
    }
    return svc


def _patch_snapshot(monkeypatch):
    monkeypatch.setattr(R, "fetch_finance_snapshot", lambda symbol, timeout=12.0: SNAP)


def _agentic_runs(name: str, arguments: dict | None = None, content: str = VALID_MD):
    def _fn(system, prompt, images, tools, tool_runner, **kwargs):
        tool_runner.run(name, arguments or {})
        return _ok_agentic(content=content)

    return _fn


def test_select_earnings_and_report_tools():
    earn = [t["function"]["name"] for t in select_earnings_tools(deep=True)]
    assert earn == [
        "yeux_search",
        "yeux_deep_search",
        "get_fund_flow",
        "get_quote",
        "get_finance_snapshot",
        "get_klines",
    ]
    assert "get_realtime_flow" not in earn
    earn_shallow = [t["function"]["name"] for t in select_earnings_tools(deep=False)]
    assert "yeux_deep_search" not in earn_shallow
    assert "yeux_search" in earn_shallow

    report = [t["function"]["name"] for t in select_report_tools(deep=False)]
    assert report == [
        "yeux_search",
        "get_fund_flow",
        "get_quote",
        "get_finance_snapshot",
        "get_klines",
    ]
    assert "get_realtime_flow" not in report
    assert "yeux_deep_search" not in report
    report_deep = [t["function"]["name"] for t in select_report_tools(deep=True)]
    assert "yeux_deep_search" in report_deep
    assert "yeux_search" in report_deep


def test_earnings_agentic_main_path_and_searches(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(R, "ROOT", tmp_path)
    _patch_snapshot(monkeypatch)
    svc = _svc()
    svc.llm.chat_agentic.side_effect = _agentic_runs(
        "yeux_search",
        {"query": "贵州茅台 600519 年报 营收 净利"},
    )
    out = svc.generate_earnings_report("600519", deep=True)
    assert AGENTIC_KEYS <= set(out)
    assert out["ok"] is True
    assert out["agentic"] is True
    assert out["name"] == "贵州茅台"
    assert out["rounds"] == 3
    assert out["budget_hit"] is False
    assert out["tool_calls_count"] >= 1
    assert out["tool_trace"][0]["name"] == "yeux_search"
    assert out["searches"]
    assert out["searches"][0]["query"] == "贵州茅台 600519 年报 营收 净利"
    assert out["searches"][0]["ok"] is True
    assert out["searches"][0]["tool"] == "yeux_search"
    assert "elapsed_sec" in out["searches"][0]
    assert NEWS_TEXT[:20] in (out["news_excerpt"] or "")
    assert out["filename"].startswith("600519_earnings_")
    assert Path(out["saved_path"]).is_file()

    args, kwargs = svc.llm.chat_agentic.call_args
    assert args[0] == R.SYSTEM_EARNINGS_AGENTIC
    assert args[2] == []
    assert kwargs["total_budget_sec"] == 180
    assert kwargs["max_rounds"] == 6
    names = [t["function"]["name"] for t in args[3]]
    assert "yeux_deep_search" in names
    assert "get_finance_snapshot" in names
    assert "get_fund_flow" in names
    assert "get_realtime_flow" not in names
    prompt = args[1]
    assert "## 8. 调查过程" in prompt
    assert (
        "SNAP_EARNINGS_TEST" in str(prompt)
        or "pe_ttm" in str(prompt).lower()
        or "19.88" in str(prompt)
    )
    assert "【检索1 财报数据线索】" not in prompt
    svc.yeux.search.assert_called_once()
    svc.llm.chat.assert_not_called()


def test_earnings_legacy_uses_system_analyst(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(R, "ROOT", tmp_path)
    _patch_snapshot(monkeypatch)
    assert "你可以调用工具" not in R.SYSTEM_ANALYST
    assert "get_finance_snapshot" not in R.SYSTEM_ANALYST
    assert "你可以调用工具" in R.SYSTEM_EARNINGS_AGENTIC
    assert "get_finance_snapshot" in R.SYSTEM_EARNINGS_AGENTIC

    svc = _svc()
    svc.llm.chat_agentic.return_value = {
        "ok": False,
        "content": "",
        "model": "grok-4.6",
        "usage": None,
        "rounds": 1,
        "vision": False,
        "budget_hit": False,
        "tools_unsupported": True,
        "error": "function calling not supported",
    }
    out = svc.generate_earnings_report("600519")
    assert out["ok"] is True
    assert out["agentic"] is False
    assert out["report_markdown"] == VALID_MD
    messages = svc.llm.chat.call_args[0][0]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == R.SYSTEM_ANALYST
    assert "你可以调用工具" not in messages[0]["content"]
    assert svc.yeux.search.call_count == 2
    assert len(out["searches"]) == 2
    assert "营收" in out["searches"][0]["query"]


def test_earnings_invalid_draft_falls_back_without_saving_garbage(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(R, "ROOT", tmp_path)
    _patch_snapshot(monkeypatch)
    garbage = (
        "先检索财报再核对估值。\n"
        "<tool_call>\n"
        '{"name": "get_finance_snapshot", "arguments": {"symbol": "600519"}}\n'
        "</tool_call>\n"
    )
    svc = _svc()

    def _fn(system, prompt, images, tools, tool_runner, **kwargs):
        tool_runner.run("yeux_search", {"query": "贵州茅台 财报"})
        return _ok_agentic(content=garbage)

    svc.llm.chat_agentic.side_effect = _fn
    svc.llm.chat.return_value = _ok_chat(content=VALID_MD)
    out = svc.generate_earnings_report("600519")
    assert out["ok"] is True
    assert out["agentic"] is False
    assert out["report_markdown"] == VALID_MD
    assert out["tool_calls_count"] >= 1
    assert out["tool_trace"][0]["name"] == "yeux_search"
    assert svc.yeux.search.call_count == 1
    messages = svc.llm.chat.call_args[0][0]
    assert messages[0]["content"] == R.SYSTEM_ANALYST
    assert "不要再要求工具" in messages[1]["content"]
    assert "### yeux_search" in messages[1]["content"]
    folder = tmp_path / "data" / "reports"
    for p in folder.glob("*.md"):
        text = p.read_text(encoding="utf-8")
        assert "<tool_call>" not in text
        assert '"arguments":' not in text

    svc.llm.chat.return_value = _ok_chat(content=garbage)
    out2 = svc.generate_earnings_report("600519")
    assert out2["ok"] is False
    assert out2["error"] == "模型返回了无效内容"
    assert svc.yeux.search.call_count == 2
    for p in folder.glob("*.md"):
        assert "<tool_call>" not in p.read_text(encoding="utf-8")


def test_report_agentic_main_path_and_news_excerpt(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(R, "ROOT", tmp_path)
    _patch_snapshot(monkeypatch)
    svc = _svc()
    svc.llm.chat_agentic.side_effect = _agentic_runs(
        "yeux_search",
        {"query": "贵州茅台 最新新闻 公告"},
    )
    out = svc.generate_report("600519", include_technical=True, focus="事件")
    assert AGENTIC_KEYS <= set(out)
    assert out["ok"] is True
    assert out["agentic"] is True
    assert out["focus"] == "事件"
    assert out["name"] == "贵州茅台"
    assert out["news_excerpt"]
    assert NEWS_TEXT[:20] in out["news_excerpt"]
    assert out["inputs"]["news_ok"] is True
    assert out["inputs"]["news_query"] == "贵州茅台 最新新闻 公告"
    assert out["inputs"]["technical_score"] == 72
    assert out["filename"].startswith("600519_report_")

    args, kwargs = svc.llm.chat_agentic.call_args
    assert args[0] == R.SYSTEM_REPORT_AGENTIC
    assert args[2] == []
    assert kwargs["total_budget_sec"] == 180
    names = [t["function"]["name"] for t in args[3]]
    assert "yeux_search" in names
    assert "get_quote" in names
    assert "get_fund_flow" in names
    assert "get_realtime_flow" not in names
    assert "yeux_deep_search" not in names
    assert "## 8. 调查过程" in args[1]
    assert "【YeuX 检索结果】" not in args[1]
    svc.yeux.search.assert_called_once()
    svc.llm.chat.assert_not_called()


def test_report_legacy_uses_system_analyst(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(R, "ROOT", tmp_path)
    _patch_snapshot(monkeypatch)
    assert "你可以调用工具" in R.SYSTEM_REPORT_AGENTIC
    assert "你可以调用工具" not in R.SYSTEM_ANALYST
    svc = _svc()
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
    out = svc.generate_report("600519")
    assert out["ok"] is True
    assert out["agentic"] is False
    messages = svc.llm.chat.call_args[0][0]
    assert messages[0]["content"] == R.SYSTEM_ANALYST
    assert out["news_excerpt"]
    assert NEWS_TEXT in out["news_excerpt"]


def test_earnings_and_report_routes_invalid_symbol():
    app = FastAPI()
    from yeuxq.api.routes_research import router

    app.include_router(router)
    client = TestClient(app)
    for path in ("/api/research/earnings", "/api/research/report"):
        r = client.post(path, json={"symbol": "abc"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert body["error"] == "无效股票代码"
        assert body["agentic"] is False
        assert body["tool_trace"] == []
        assert body["tool_calls_count"] == 0
        assert body["rounds"] == 0
        assert body["budget_hit"] is False
        assert body["report_markdown"] == ""


def test_earnings_max_deep_search_is_one(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(R, "ROOT", tmp_path)
    _patch_snapshot(monkeypatch)
    captured: dict = {}
    Real = R.ToolRunner

    class Spy(Real):
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(R, "ToolRunner", Spy)
    svc = _svc()
    svc.generate_earnings_report("600519", deep=True)
    assert captured.get("max_deep_search") == 1
    assert "深检索最多一次" in R.SYSTEM_EARNINGS_AGENTIC
    prompt = svc.llm.chat_agentic.call_args[0][1]
    assert "最多一次" in prompt


def test_join_full_results_drops_oldest():
    blocks = ["### a\n" + ("A" * 10000), "### b\n" + ("B" * 10000), "### c\n" + ("C" * 10000)]
    text = R._join_full_results(blocks, cap=12000)
    assert len(text) <= 12000
    assert "### c" in text
    assert "### a" not in text
