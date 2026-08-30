"""大单 / 五档 / 大宗 / 暗盘状态 API。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from yeuxq.api.deps import get_container

router = APIRouter(tags=["orderflow"])


@router.get("/api/orderflow/overview")
def orderflow_overview(
    symbol: str = Query(...),
    large: float = Query(200000, description="大单金额阈值(元)"),
    super_amt: float = Query(1000000, description="超大单金额阈值(元)", alias="super"),
):
    return get_container().orderflow.fetch_overview(symbol, large, super_amt)


@router.get("/api/orderflow/ticks")
def orderflow_ticks(
    symbol: str = Query(...),
    limit: int = Query(500, ge=10, le=8000),
):
    data = get_container().orderflow.fetch_ticks(symbol, limit=limit)
    # 默认只返回最新 limit 条，减小 payload
    ticks = data.get("ticks") or []
    data = dict(data)
    data["ticks"] = ticks[-limit:]
    return data


@router.get("/api/orderflow/large")
def orderflow_large(
    symbol: str = Query(...),
    large: float = Query(200000),
    super_amt: float = Query(1000000, alias="super"),
    limit: int = Query(100, ge=10, le=500),
):
    return get_container().orderflow.fetch_large_orders(symbol, large, super_amt, limit)


@router.get("/api/orderflow/book")
def orderflow_book(symbol: str = Query(...)):
    return get_container().orderflow.fetch_order_book(symbol)


@router.get("/api/orderflow/block")
def orderflow_block(
    symbol: str = Query(...),
    page_size: int = Query(50, ge=5, le=200),
):
    return get_container().orderflow.fetch_block_trades(symbol, page_size)


@router.get("/api/orderflow/darkpool")
def orderflow_darkpool(symbol: str = Query(...)):
    """真·暗盘不可用说明 + 大宗交易替代预览。"""
    return get_container().orderflow.fetch_dark_pool_status(symbol)
