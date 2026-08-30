"""突破模块：海龟交易法则（20日/55日唐奇安）。"""

from __future__ import annotations

from typing import List, Optional, Tuple

from yeuxq.analysis.indicators import true_range
from yeuxq.domain.models import BreakoutResult, Kline


def calc_n(klines: List[Kline], period: int = 20) -> float:
    if len(klines) < period + 1:
        return 0.0
    trs = []
    for i in range(len(klines) - period, len(klines)):
        trs.append(true_range(klines[i].high, klines[i].low, klines[i - 1].close))
    return round(sum(trs) / len(trs), 4)


def donchian(klines: List[Kline], period: int) -> Tuple[float, float]:
    if len(klines) <= period:
        window = klines[:-1] if len(klines) > 1 else klines
    else:
        window = klines[-period - 1 : -1]
    return max(k.high for k in window), min(k.low for k in window)


def _find_last_entry(klines: List[Kline], period: int) -> Optional[Tuple[str, float, int]]:
    """回溯最近一次上破/下破入场。"""
    if len(klines) < period + 5:
        return None
    for i in range(len(klines) - 1, period, -1):
        window = klines[i - period : i]
        ch = max(k.high for k in window)
        cl = min(k.low for k in window)
        if klines[i].high >= ch:
            return ("long", ch, i)
        if klines[i].low <= cl:
            return ("short", cl, i)
    return None


def _analyze_system(
    klines: List[Kline], period: int, name: str, exit_period: int
) -> BreakoutResult:
    n = calc_n(klines, 20)
    ch, cl = donchian(klines, period)
    price = klines[-1].close
    entry = _find_last_entry(klines, period)
    signal = "观望"
    entry_price = None
    stop = 0.0
    units = 0
    next_add = None
    exit_price = None
    signals: List[str] = []
    breakout_price = ch

    if entry and entry[0] == "long":
        entry_price = entry[1]
        idx = entry[2]
        days = len(klines) - 1 - idx
        stop = round(entry_price - 2 * n, 2) if n else round(entry_price * 0.95, 2)
        # 是否仍持仓：未跌破 2N 且未触发 exit_period 低点离场的简化
        exit_low = min(k.low for k in klines[-exit_period:]) if len(klines) >= exit_period else cl
        if price < stop or klines[-1].low <= exit_low and days > 0 and price < entry_price:
            signal = "多头止损" if price < stop else "观望"
            if signal == "多头止损":
                signals.append(f"触发止损{stop}")
        else:
            signal = "持仓"
            units = 1
            # 0.5N 加仓
            add_level = entry_price + 0.5 * n
            if n and price >= add_level:
                units = min(4, 1 + int((price - entry_price) / (0.5 * n)))
            next_add = round(entry_price + units * 0.5 * n, 2) if n else None
            signals.append(f"持有多头{days}日，止损{stop}")
            if next_add:
                signals.append(f"加仓参考{next_add}")
    elif price >= ch:
        signal = "突破买入"
        entry_price = ch
        stop = round(ch - 2 * n, 2) if n else round(ch * 0.95, 2)
        units = 1
        next_add = round(ch + 0.5 * n, 2) if n else None
        signals.append(f"上破{period}日通道{ch}")
    elif price <= cl:
        signal = "向下突破"
        breakout_price = cl
        entry_price = cl
        stop = round(cl + 2 * n, 2) if n else round(cl * 1.05, 2)
        signals.append(f"下破{period}日通道{cl}")

    # 评分细分用 description
    dist = 0.0
    if ch and price:
        dist = (price - ch) / ch * 100
    desc = f"{name} signal={signal} N={n} 距上轨{dist:.2f}%"
    return BreakoutResult(
        system=name,
        signal=signal,
        breakout_price=breakout_price,
        current_n=n,
        stop_loss=stop,
        entry_price=entry_price,
        position_units=units,
        exit_price=exit_price,
        channel_high=ch,
        channel_low=cl,
        next_add_price=next_add,
        signals=signals,
        description=desc,
    )


def analyze_breakout(klines: List[Kline]) -> List[BreakoutResult]:
    if len(klines) < 60:
        return []
    return [
        _analyze_system(klines, 20, "系统一(20日)", exit_period=10),
        _analyze_system(klines, 55, "系统二(55日)", exit_period=20),
    ]


def breakout_score(breakouts: List[BreakoutResult]) -> int:
    if not breakouts:
        return 50
    score = 50
    for b in breakouts:
        if b.signal in ("持仓", "突破买入"):
            base = 62
            # 持仓天数/单位加分
            base += min(8, b.position_units * 2)
            if b.current_n and b.entry_price and b.channel_high:
                # 站稳通道上沿
                if breakouts and breakouts[0]:
                    pass
            score = max(score, base)
        elif b.signal == "空头平仓":
            score = max(score, 63)
        elif b.signal in ("向下突破", "多头止损"):
            score = min(score, 35)
    return max(20, min(100, score))
