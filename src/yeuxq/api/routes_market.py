from __future__ import annotations

from fastapi import APIRouter, Query

from yeuxq.api.deps import get_container
from yeuxq.services.serialize import kline_to_dict, quote_to_dict

router = APIRouter(tags=["market"])


@router.get("/api/health")
def health():
    from yeuxq.analysis.rust_bridge import rust_status

    c = get_container()
    return {
        "status": "ok",
        "app": c.settings.app.name,
        "version": c.settings.app.version,
        "engine": rust_status(),
    }


@router.get("/api/quote")
def quote(symbol: str = Query(...)):
    c = get_container()
    q = c.data.fetch_quote(symbol)
    if not q:
        return {"error": "无法获取行情"}
    return quote_to_dict(q)


@router.get("/api/kline")
def kline(
    symbol: str = Query(...),
    count: int = Query(250, ge=10, le=10000),
    period: str = Query("day"),
):
    c = get_container()
    ks = c.data.fetch_kline(symbol, count=count, period=period)
    return {"symbol": symbol, "period": period, "klines": [kline_to_dict(k) for k in ks]}


@router.get("/api/minute")
def minute(symbol: str = Query(...)):
    c = get_container()
    m = c.data.fetch_minute(symbol)
    if not m:
        return {"error": "无法获取分时"}
    return {
        "symbol": symbol,
        "times": m.times,
        "prices": m.prices,
        "avg": m.avg_prices,
        "volumes": m.volumes,
        "pre_close": m.pre_close,
        "name": m.name,
        "high": m.high,
        "low": m.low,
    }


@router.get("/api/search")
def search(keyword: str = Query(...)):
    c = get_container()
    return {"results": c.data.search_stock(keyword)}


@router.get("/api/realtime_flow")
def realtime_flow(symbol: str = Query(...)):
    return get_container().analyze.realtime_flow_payload(symbol)


@router.get("/api/config/public")
def public_config():
    s = get_container().settings
    return {
        "app": s.app.model_dump(),
        "weights": s.engine.weights.model_dump(),
        "prediction": {
            "horizon_days": s.prediction.horizon_days,
            "model": "rule_v1",
        },
        "scan": {
            "allow_full_market": s.scan.allow_full_market,
            "max_symbols": s.scan.max_symbols,
        },
        "research": get_container().research.status(),
        "capabilities": {
            "index_and_breadth": True,
            "large_order_aggregated_flow": True,
            "ticks_and_large_filter": True,
            "order_book_l1_5": True,
            "block_trades": True,
            "level2_full": False,
            "dark_pool": False,
            "dark_pool_alternative": "block_trades",
            "ai_report": True,
            "earnings_report": True,
            "watch_brief": True,
        },
    }


@router.get("/api/market/overview")
def market_overview():
    """大盘概览：上证指数近期 K 线 + 涨跌家数（非暗盘）。"""
    c = get_container()
    index = c.data.fetch_index_kline("000001", count=60)
    breadth = c.data.fetch_market_breadth()
    last = index[-1] if index else None
    prev = index[-2] if index and len(index) >= 2 else None
    change_pct = None
    if last and prev and prev.close:
        change_pct = round((last.close - prev.close) / prev.close * 100, 2)
    return {
        "index_code": "000001",
        "index_name": "上证指数",
        "last": kline_to_dict(last) if last else None,
        "change_pct": change_pct,
        "breadth": breadth,
        "klines": [kline_to_dict(k) for k in index[-60:]],
        "note": "公开行情聚合；不含暗盘/L2 逐笔",
    }
