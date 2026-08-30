"""趋势模块：均线方向、排列、强度、阶段。"""

from __future__ import annotations

from typing import List, Optional

from yeuxq.analysis.indicators import adx_approx, ma_direction, pct_change, sma_series
from yeuxq.domain.models import Kline, TrendResult


def analyze_trend(klines: List[Kline]) -> TrendResult:
    if len(klines) < 30:
        return TrendResult(
            direction="未知",
            strength=50,
            stage="数据不足",
            ma_arrangement="未知",
            signals=["K线不足"],
        )
    closes = [k.close for k in klines]
    highs = [k.high for k in klines]
    lows = [k.low for k in klines]
    ma5 = sma_series(closes, 5)
    ma10 = sma_series(closes, 10)
    ma20 = sma_series(closes, 20)
    ma60 = sma_series(closes, 60)

    d20 = ma_direction(ma20, 5)
    d60 = ma_direction(ma60, 5) if len(closes) >= 65 else "未知"
    price = closes[-1]
    ma20_v = ma20[-1] or price
    ma60_v = ma60[-1] or price
    ma5_v = ma5[-1] or price
    ma10_v = ma10[-1] or price

    scores = {
        "ma20_dir": 30 if d20 == "向上" else (10 if d20 == "走平" else 0),
        "ma60_dir": 25
        if d60 == "向上"
        else (10 if d60 == "走平" else (0 if d60 != "未知" else 12)),
        "price_vs_ma20": 15 if price >= ma20_v else 0,
        "price_vs_ma60": 10 if price >= ma60_v else 0,
        "resonance": 0,
    }
    # 多周期共振：短中长期同向
    short_up = price >= ma5_v >= ma10_v
    mid_up = ma20_v and d20 == "向上"
    long_up = ma60_v and (d60 in ("向上", "走平", "未知")) and price >= ma60_v * 0.98
    if short_up and mid_up and long_up:
        scores["resonance"] = 20
    elif mid_up and price >= ma20_v:
        scores["resonance"] = 12
    elif d20 == "向下" and price < ma20_v:
        scores["resonance"] = 0
    else:
        scores["resonance"] = 8

    strength = int(sum(scores.values()))
    strength = max(0, min(100, strength))

    # 真实均线排列
    vals = [ma5_v, ma10_v, ma20_v, ma60_v]
    if all(vals[i] >= vals[i + 1] for i in range(3)):
        arrangement = "多头排列"
    elif all(vals[i] <= vals[i + 1] for i in range(3)):
        arrangement = "空头排列"
    else:
        arrangement = "纠缠"

    gain20 = pct_change(closes[-21], closes[-1]) if len(closes) >= 21 else 0.0
    adx = adx_approx(highs, lows, closes, 14)

    if arrangement == "多头排列" and d20 == "向上" and gain20 > 5:
        direction, stage = "上升", "强势上升阶段"
    elif d20 == "向上" and price >= ma20_v:
        direction, stage = "上升", "上升阶段"
    elif d20 == "向下" and price < ma20_v:
        direction, stage = "下降", "下降阶段"
    elif arrangement == "空头排列":
        direction, stage = "下降", "弱势下降阶段"
    else:
        direction, stage = "震荡", "震荡整理阶段"

    # ADX 微调强度
    if adx > 40 and direction == "上升":
        strength = min(100, strength + 5)
    if adx > 40 and direction == "下降":
        strength = max(0, strength - 5)

    signals: List[str] = []
    if d20 == "向上":
        signals.append("MA20向上")
    elif d20 == "向下":
        signals.append("MA20向下")
    if price >= ma60_v:
        signals.append("站上60日决策线")
    else:
        signals.append("受压60日决策线")
    if price < ma20_v and d20 != "向上":
        signals.append("跌破MA20")
    if arrangement == "多头排列":
        signals.append("均线多头排列")
    elif arrangement == "空头排列":
        signals.append("均线空头排列")
    if adx >= 25:
        signals.append(f"趋势强度ADX约{adx:.0f}")

    trendline = _find_trendline(klines, direction)

    return TrendResult(
        direction=direction,
        strength=strength,
        stage=stage,
        ma_arrangement=arrangement,
        ma_scores=scores,
        trendline=trendline,
        signals=signals,
    )


def _find_trendline(klines: List[Kline], direction: str) -> Optional[dict]:
    if direction != "上升" or len(klines) < 21:
        return None
    lows = [k.low for k in klines]
    ws = len(klines) - 20
    we = len(klines) - 1
    troughs = []
    for i in range(ws, we + 1):
        lo = max(ws, i - 5)
        hi = min(we, i + 5)
        neighbors = lows[lo:i] + lows[i + 1 : hi + 1]
        if neighbors and lows[i] <= min(neighbors):
            troughs.append(i)
    t0 = troughs[0] if troughs else ws
    after = lows[t0 + 1 : we + 1]
    if not after:
        return None
    t1 = t0 + 1 + after.index(min(after))
    if lows[t1] <= lows[t0]:
        return None
    return {
        "start_date": klines[t0].date,
        "end_date": klines[t1].date,
        "start_price": lows[t0],
        "end_price": lows[t1],
    }
