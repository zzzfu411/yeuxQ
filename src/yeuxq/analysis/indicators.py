"""共享技术指标。"""

from __future__ import annotations

from typing import List, Optional, Sequence


def sma_series(values: Sequence[float], period: int) -> List[Optional[float]]:
    if period <= 0 or not values:
        return []
    result: List[Optional[float]] = [None] * len(values)
    running = 0.0
    for i, v in enumerate(values):
        running += v
        if i >= period:
            running -= values[i - period]
        if i >= period - 1:
            result[i] = running / period
    return result


def ema_series(values: Sequence[float], period: int) -> List[Optional[float]]:
    if period <= 0 or not values:
        return []
    result: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return result
    alpha = 2.0 / (period + 1)
    prev = sum(values[:period]) / period
    result[period - 1] = prev
    for i in range(period, len(values)):
        prev = alpha * values[i] + (1 - alpha) * prev
        result[i] = prev
    return result


def last_sma(values: Sequence[float], period: int) -> float:
    if len(values) < period or period <= 0:
        return 0.0
    return sum(values[-period:]) / period


def ma_direction(ma_values: Sequence[Optional[float]], lookback: int = 5) -> str:
    valid = [v for v in ma_values if v is not None]
    if len(valid) < lookback + 1:
        return "未知"
    recent = valid[-(lookback + 1) :]
    slope = recent[-1] - recent[0]
    base = abs(recent[0]) or 1e-9
    thr = base * 0.002
    if slope > thr:
        return "向上"
    if slope < -thr:
        return "向下"
    return "走平"


def pct_change(old: float, new: float) -> float:
    if not old:
        return 0.0
    return (new - old) / old * 100.0


def find_peaks(values: Sequence[float], window: int = 3) -> List[int]:
    peaks = []
    n = len(values)
    for i in range(window, n - window):
        lo, hi = i - window, i + window
        if all(values[i] >= values[j] for j in range(lo, hi + 1) if j != i):
            if not all(values[j] == values[i] for j in range(lo, hi + 1)):
                peaks.append(i)
    return peaks


def find_troughs(values: Sequence[float], window: int = 3) -> List[int]:
    troughs = []
    n = len(values)
    for i in range(window, n - window):
        lo, hi = i - window, i + window
        if all(values[i] <= values[j] for j in range(lo, hi + 1) if j != i):
            if not all(values[j] == values[i] for j in range(lo, hi + 1)):
                troughs.append(i)
    return troughs


def true_range(high: float, low: float, pre_close: float) -> float:
    return max(high - low, abs(high - pre_close), abs(low - pre_close))


def atr(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 20
) -> float:
    if len(closes) < period + 1:
        return 0.0
    trs = []
    for i in range(len(closes) - period, len(closes)):
        trs.append(true_range(highs[i], lows[i], closes[i - 1]))
    return sum(trs) / len(trs) if trs else 0.0


def macd(
    closes: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[List[Optional[float]], List[Optional[float]], List[Optional[float]]]:
    ema_fast = ema_series(closes, fast)
    ema_slow = ema_series(closes, slow)
    dif: List[Optional[float]] = [None] * len(closes)
    for i in range(len(closes)):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            dif[i] = ema_fast[i] - ema_slow[i]  # type: ignore[operator]
    # DEA on valid dif
    dif_vals = [d if d is not None else 0.0 for d in dif]
    dea = ema_series(dif_vals, signal)
    hist: List[Optional[float]] = [None] * len(closes)
    for i in range(len(closes)):
        if dif[i] is not None and dea[i] is not None:
            hist[i] = dif[i] - dea[i]  # type: ignore[operator]
    return dif, dea, hist


def adx_approx(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14
) -> float:
    """简化 ADX：用平均波幅方向强度近似 0-100。"""
    if len(closes) < period + 1:
        return 0.0
    up_moves = 0.0
    down_moves = 0.0
    for i in range(len(closes) - period, len(closes)):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        if up > down and up > 0:
            up_moves += up
        elif down > up and down > 0:
            down_moves += down
    tot = up_moves + down_moves
    if tot <= 0:
        return 0.0
    dx = abs(up_moves - down_moves) / tot * 100
    return round(min(100.0, dx), 2)
