"""缠论分时：1分钟 → 5分钟K → 简化买卖点。"""

from __future__ import annotations

from typing import List, Optional

from yeuxq.analysis.chanlun_daily import analyze_chanlun_daily, daily_result_to_dict
from yeuxq.domain.models import Kline, MinuteData


def construct_5min_klines(minute: MinuteData) -> List[Kline]:
    """将分时点聚合为5分钟 OHLC。"""
    if not minute.times or not minute.prices:
        return []
    bars: List[Kline] = []
    bucket_t: List[str] = []
    bucket_p: List[float] = []
    bucket_v: List[float] = []

    def flush() -> None:
        nonlocal bucket_t, bucket_p, bucket_v
        if not bucket_p:
            return
        bars.append(
            Kline(
                date=bucket_t[-1],
                open=bucket_p[0],
                close=bucket_p[-1],
                high=max(bucket_p),
                low=min(bucket_p),
                volume=sum(bucket_v),
            )
        )
        bucket_t, bucket_p, bucket_v = [], [], []

    for i, t in enumerate(minute.times):
        # 午休分割
        if bucket_t and bucket_t[0].startswith("11:") and t.startswith("13:"):
            flush()
        bucket_t.append(t)
        bucket_p.append(minute.prices[i])
        bucket_v.append(minute.volumes[i] if i < len(minute.volumes) else 0.0)
        if len(bucket_p) >= 5:
            flush()
    flush()
    return bars


def analyze_chanlun_minute(minute: Optional[MinuteData]) -> dict:
    if not minute or len(minute.prices) < 20:
        return {"summary": "分时数据不足", "signals": [], "kline_count": 0}
    k5 = construct_5min_klines(minute)
    if len(k5) < 10:
        return {"summary": "5分钟K不足", "signals": [], "kline_count": len(k5)}
    result = analyze_chanlun_daily(k5)
    d = daily_result_to_dict(result)
    d["summary"] = "分时缠论(5分钟)：" + result.summary
    return d


def signals_to_dict(data: dict) -> dict:
    return data
