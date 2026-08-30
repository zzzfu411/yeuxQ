"""形态模块：箱体/双底/头肩等启发式识别。"""

from __future__ import annotations

from typing import List, Optional

from yeuxq.analysis.indicators import find_peaks, find_troughs
from yeuxq.domain.models import Kline, PatternResult


def _detect_box(klines: List[Kline], price: float) -> Optional[PatternResult]:
    if len(klines) < 20:
        return None
    window = klines[-20:]
    upper = max(k.high for k in window)
    lower = min(k.low for k in window)
    if upper <= lower:
        return None
    amp = (upper - lower) / lower * 100
    if not (5.0 <= amp <= 25.0):
        return None
    if price >= upper * 0.98:
        status, direction, conf = "已突破", "看涨", 70
        target = round(upper + (upper - lower), 2)
    elif price <= lower * 1.02:
        status, direction, conf = "跌破", "看跌", 65
        target = round(lower - (upper - lower), 2)
    else:
        status, direction, conf = "震荡中", "中性", 50
        target = upper
    return PatternResult(
        name="箱体",
        direction=direction,
        confidence=conf,
        status=status,
        target_price=target,
        key_levels={"上沿": round(upper, 2), "下沿": round(lower, 2)},
        description=f"近20日箱体振幅{amp:.1f}%",
    )


def _detect_double_bottom(klines: List[Kline], price: float) -> Optional[PatternResult]:
    if len(klines) < 40:
        return None
    lows = [k.low for k in klines]
    highs = [k.high for k in klines]
    troughs = find_troughs(lows, 3)
    if len(troughs) < 2:
        return None
    t1, t2 = troughs[-2], troughs[-1]
    if t2 - t1 < 5:
        return None
    p1, p2 = lows[t1], lows[t2]
    if abs(p1 - p2) / max(p1, p2) > 0.03:
        return None
    neck = max(highs[t1 : t2 + 1])
    bottom = min(p1, p2)
    if price >= neck * 0.995:
        status, conf = "已突破", 62
        direction = "看涨"
    elif price > bottom * 1.02:
        status, conf = "形成中", 48
        direction = "看涨"
    else:
        return None
    target = round(neck + (neck - bottom), 2)
    return PatternResult(
        name="双底",
        direction=direction,
        confidence=conf,
        status=status,
        target_price=target,
        key_levels={"颈线": round(neck, 2), "底部": round(bottom, 2)},
        description="双底形态，突破颈线后目标=颈线+底到颈线高度",
    )


def _detect_head_shoulders_bottom(klines: List[Kline], price: float) -> Optional[PatternResult]:
    if len(klines) < 50:
        return None
    lows = [k.low for k in klines]
    highs = [k.high for k in klines]
    troughs = find_troughs(lows, 4)
    if len(troughs) < 3:
        return None
    left_idx, head_idx, right_idx = troughs[-3], troughs[-2], troughs[-1]
    if not (lows[head_idx] < lows[left_idx] and lows[head_idx] < lows[right_idx]):
        return None
    if abs(lows[left_idx] - lows[right_idx]) / max(lows[left_idx], lows[right_idx]) > 0.05:
        return None
    neck = max(highs[left_idx : right_idx + 1])
    bottom = lows[head_idx]
    status = "已突破" if price >= neck * 0.995 else "形成中"
    conf = 68 if status == "已突破" else 50
    target = round(neck + (neck - bottom), 2)
    return PatternResult(
        name="头肩底",
        direction="看涨",
        confidence=conf,
        status=status,
        target_price=target,
        key_levels={"颈线": round(neck, 2), "头部": round(bottom, 2)},
        description="头肩底，突破颈线看涨",
    )


def _detect_double_top(klines: List[Kline], price: float) -> Optional[PatternResult]:
    if len(klines) < 40:
        return None
    highs = [k.high for k in klines]
    lows = [k.low for k in klines]
    peaks = find_peaks(highs, 3)
    if len(peaks) < 2:
        return None
    p1, p2 = peaks[-2], peaks[-1]
    if p2 - p1 < 5:
        return None
    h1, h2 = highs[p1], highs[p2]
    if abs(h1 - h2) / max(h1, h2) > 0.03:
        return None
    neck = min(lows[p1 : p2 + 1])
    top = max(h1, h2)
    if price <= neck * 1.005:
        status, conf, direction = "已跌破", 62, "看跌"
    else:
        status, conf, direction = "形成中", 48, "看跌"
    target = round(neck - (top - neck), 2)
    return PatternResult(
        name="双顶",
        direction=direction,
        confidence=conf,
        status=status,
        target_price=target,
        key_levels={"颈线": round(neck, 2), "顶部": round(top, 2)},
        description="双顶形态",
    )


def analyze_patterns(klines: List[Kline]) -> List[PatternResult]:
    if len(klines) < 20:
        return []
    price = klines[-1].close
    found: List[PatternResult] = []
    for fn in (
        _detect_box,
        _detect_double_bottom,
        _detect_head_shoulders_bottom,
        _detect_double_top,
    ):
        p = fn(klines, price)
        if p:
            found.append(p)
    # 限制数量，优先高置信
    found.sort(key=lambda x: x.confidence, reverse=True)
    return found[:5]


def pattern_score(patterns: List[PatternResult]) -> int:
    total = 50.0
    for p in patterns:
        sign = 1 if p.direction == "看涨" else (-1 if p.direction == "看跌" else 0)
        total += sign * p.confidence * 0.2
    return max(20, min(100, int(total)))
