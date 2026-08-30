"""智能研报 / 新闻 / 财报 API（用户点击触发）。"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from yeuxq.api.deps import get_container
from yeuxq.intel.research import list_saved_reports, read_saved_report, store_policy

router = APIRouter(tags=["research"])


def _public_research_payload(payload: dict) -> dict:
    result = dict(payload)
    report_id = str(result.get("report_id") or result.get("filename") or "")
    result["report_id"] = report_id
    # Keep the donor response shape without exposing any server filesystem path.
    result["filename"] = report_id
    result["saved_path"] = ""
    return result


class ReportRequest(BaseModel):
    symbol: str
    deep: bool = False
    include_technical: bool = True
    focus: str = Field("综合", description="综合/技术/事件/风险 等")


class EarningsRequest(BaseModel):
    symbol: str
    deep: bool = True
    period_hint: str = "最近一期财报/业绩预告"


class NewsRequest(BaseModel):
    symbol: str
    name: str = ""
    deep: bool = False
    extra_query: str = ""


class BriefRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    deep: bool = False
    with_news: bool = True
    with_llm: bool = True


class VisionRequest(BaseModel):
    symbol: str
    name: str = ""
    view: str = "day"
    range: int = 250
    ind: str = "macd"
    image: str = ""
    context: Optional[dict] = None
    deep: bool = False
    with_news: bool = True


@router.get("/api/research/status")
def research_status():
    return get_container().research.status()


@router.get("/api/research/reports")
def research_reports(
    symbol: str = Query(""),
    limit: int = Query(30, ge=1, le=80),
):
    container = get_container()
    items = list_saved_reports(
        symbol=symbol.strip(),
        limit=limit,
        store=container.report_store,
    )
    items = [_public_research_payload(item) for item in items]
    return {"ok": True, "symbol": symbol.strip(), "items": items, **store_policy()}


@router.get("/api/research/reports/{report_id}")
def research_report_file(report_id: str):
    payload = read_saved_report(report_id, store=get_container().report_store)
    return _public_research_payload(payload)


@router.post("/api/research/news")
def research_news(req: NewsRequest):
    symbol = req.symbol.strip()
    if _bad_symbol(symbol):
        return _public_research_payload({"ok": False, "symbol": symbol, "error": "无效股票代码"})
    payload = get_container().research.search_news(
        symbol=symbol,
        name=req.name,
        deep=req.deep,
        extra_query=req.extra_query,
    )
    return _public_research_payload(payload)


@router.get("/api/research/news")
def research_news_get(
    symbol: str = Query(...),
    deep: bool = Query(False),
    q: str = Query(""),
):
    normalized = symbol.strip()
    if _bad_symbol(normalized):
        return _public_research_payload(
            {"ok": False, "symbol": normalized, "error": "无效股票代码"}
        )
    payload = get_container().research.search_news(
        symbol=normalized,
        deep=deep,
        extra_query=q,
    )
    return _public_research_payload(payload)


def _invalid_research_payload(symbol: str, error: str, *, kind: str) -> dict:
    pol = store_policy()
    now = datetime.now(timezone.utc).isoformat()
    base = {
        "ok": False,
        "symbol": symbol,
        "name": "",
        "report_markdown": "",
        "error": error,
        "model": "grok-4.6",
        "usage": None,
        "report_id": "",
        "ttl_hours": pol.get("ttl_hours", 24),
        "agentic": False,
        "tool_trace": [],
        "tool_calls_count": 0,
        "rounds": 0,
        "budget_hit": False,
        "generated_at": now,
    }
    if kind == "earnings":
        base.update(
            searches=[],
            news_excerpt="",
            fundamentals=None,
            disclaimer="AI 生成内容可能有误，财报数字请以交易所披露为准。",
        )
    else:
        base.update(
            focus="",
            deep=False,
            news_excerpt="",
            inputs={},
            disclaimer="AI 生成内容可能有误，不构成投资建议。",
        )
    return base


def _bad_symbol(symbol: str) -> bool:
    s = (symbol or "").strip()
    return re.fullmatch(r"[0-9]{6}", s, re.ASCII) is None


@router.post("/api/research/report")
def research_report(req: ReportRequest):
    """生成综合投研速报（YeuX + 技术面 + Grok）。可能需 30–120 秒。"""
    symbol = req.symbol.strip()
    if _bad_symbol(symbol):
        return _invalid_research_payload(symbol, "无效股票代码", kind="report")
    payload = get_container().research.generate_report(
        symbol=symbol,
        deep=req.deep,
        include_technical=req.include_technical,
        focus=req.focus,
    )
    return _public_research_payload(payload)


@router.post("/api/research/earnings")
def research_earnings(req: EarningsRequest):
    """财报/业绩专题（默认 deep search）。可能需 1–3 分钟。"""
    symbol = req.symbol.strip()
    if _bad_symbol(symbol):
        return _invalid_research_payload(symbol, "无效股票代码", kind="earnings")
    payload = get_container().research.generate_earnings_report(
        symbol=symbol,
        deep=req.deep,
        period_hint=req.period_hint,
    )
    return _public_research_payload(payload)


@router.post("/api/research/brief")
def research_brief(req: BriefRequest):
    """自选晨报：本地技术面一览 + 可选资讯/Grok。默认保存 24 小时。"""
    payload = get_container().research.generate_watch_brief(
        symbols=req.symbols,
        deep=req.deep,
        with_news=req.with_news,
        with_llm=req.with_llm,
    )
    return _public_research_payload(payload)


@router.post("/api/research/vision")
def research_vision(req: VisionRequest):
    """图表截图 + 数字上下文的大资金研判，可能需 30–120 秒。"""
    symbol = req.symbol.strip()
    if _bad_symbol(symbol):
        pol = store_policy()
        return {
            "ok": False,
            "symbol": symbol,
            "name": req.name or "",
            "report_markdown": "",
            "error": "无效股票代码",
            "model": "grok-4.6",
            "vision": False,
            "usage": None,
            "report_id": "",
            "ttl_hours": pol.get("ttl_hours", 24),
            "news_ok": None,
            "agentic": False,
            "tool_trace": [],
            "tool_calls_count": 0,
            "rounds": 0,
            "budget_hit": False,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    payload = get_container().research.generate_vision_report(
        symbol=symbol,
        name=req.name,
        view=req.view,
        range_=req.range,
        ind=req.ind,
        image=req.image,
        context=req.context,
        deep=req.deep,
        with_news=req.with_news,
    )
    return _public_research_payload(payload)
