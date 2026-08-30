"""动量质量七维（原 CANSLIM 的价量近似实现，避免名实不符）。"""

from __future__ import annotations

from dataclasses import replace
from typing import List, Optional, Tuple

from yeuxq.analysis.indicators import pct_change, sma_series
from yeuxq.domain.models import FundFlow, Kline, MomentumResult


def _c_score(klines: List[Kline]) -> Tuple[int, str]:
    if len(klines) < 10:
        return 50, ""
    closes = [k.close for k in klines]
    g20 = pct_change(closes[-21], closes[-1]) if len(closes) >= 21 else 0.0
    g5 = pct_change(closes[-6], closes[-1])

    def bucket20(g: float) -> int:
        if g > 20:
            return 90
        if g > 15:
            return 80
        if g > 10:
            return 70
        if g > 5:
            return 60
        if g > 0:
            return 50
        if g > -5:
            return 35
        return 20

    def bucket5(g: float) -> int:
        if g > 5:
            return 80
        if g > 2:
            return 70
        if g > 0:
            return 60
        if g > -5:
            return 50
        return 35

    score = max(bucket20(g20), bucket5(g5))
    return score, f"C(近期动量){score}分"


def _a_score(klines: List[Kline]) -> Tuple[int, str]:
    if len(klines) < 60:
        return 50, ""
    n = min(121, len(klines))
    gain = pct_change(klines[-n].close, klines[-1].close)
    if gain > 150:
        score = 90
    elif gain > 30:
        score = 75
    elif gain > 15:
        score = 70
    elif gain > 12:
        score = 60
    elif gain > 5:
        score = 50
    elif gain > -15:
        score = 35
    else:
        score = 20
    return score, f"A(中期趋势){score}分"


def _n_score(klines: List[Kline]) -> Tuple[int, str, Optional[dict]]:
    if len(klines) < 60:
        return 50, "", None
    window = klines[-250:] if len(klines) >= 100 else klines
    high_250 = max(k.high for k in window)
    price = klines[-1].close
    dist = (high_250 - price) / high_250 * 100 if high_250 else 100
    if dist <= 2:
        score = 90
    elif dist <= 5:
        score = 80
    elif dist <= 10:
        score = 70
    elif dist <= 15:
        score = 55
    else:
        score = 40
    cup = _detect_cup_handle(klines)
    if cup and cup.get("breakout"):
        score = min(100, score + 10)
    return score, f"N(新高形态){score}分", cup


def _detect_cup_handle(klines: List[Kline]) -> Optional[dict]:
    if len(klines) < 80:
        return None
    w = klines[-120:] if len(klines) >= 120 else klines
    highs = [k.high for k in w]
    lows = [k.low for k in w]
    cup_high = max(highs[: len(w) // 2])
    cup_low = min(lows)
    depth = (cup_high - cup_low) / cup_high * 100 if cup_high else 0
    if depth < 8 or depth > 40:
        return None
    handle = w[len(w) // 2 :]
    handle_high = max(k.high for k in handle)
    handle_low = min(k.low for k in handle)
    h_depth = (handle_high - handle_low) / handle_high * 100 if handle_high else 0
    price = w[-1].close
    breakout = price >= cup_high * 0.99
    buy = round(cup_high, 2)
    target = round(buy + (cup_high - cup_low), 2)
    return {
        "pattern": "杯柄形态",
        "cup_high": round(cup_high, 2),
        "cup_low": round(cup_low, 2),
        "handle_high": round(handle_high, 2),
        "handle_low": round(handle_low, 2),
        "cup_depth": round(depth, 1),
        "handle_depth": round(h_depth, 1),
        "breakout": breakout,
        "buy_point": buy,
        "target": target,
    }


def _s_score(klines: List[Kline]) -> Tuple[int, str]:
    turns = [k.turnover for k in klines[-10:] if k.turnover]
    if not turns:
        # 用量比近似
        vols = [k.volume for k in klines]
        if len(vols) < 10:
            return 50, ""
        ratio = vols[-1] / (sum(vols[-10:-1]) / 9 + 1e-9)
        score = 70 if 1.2 <= ratio <= 3 else (55 if ratio < 1.2 else 40)
        return score, f"S(供需/量能){score}分"
    avg = sum(turns) / len(turns)
    last = turns[-1]
    if 1.5 <= last <= 8:
        score = 70
    elif last < 1.5:
        score = 55
    elif last <= 15:
        score = 45
    else:
        score = 30
    if avg > 0 and last > avg * 2:
        score = max(30, score - 10)
    return score, f"S(供需/换手){score}分"


def _l_score(klines: List[Kline], index_klines: Optional[List[Kline]]) -> Tuple[int, str]:
    if len(klines) < 60:
        return 50, ""
    g60 = pct_change(klines[-61].close, klines[-1].close)
    g250 = pct_change(klines[-min(250, len(klines))].close, klines[-1].close)
    if g60 >= 20:
        base = 75
    elif g60 >= 10:
        base = 65
    elif g60 >= 1:
        base = 50
    elif g60 >= -9:
        base = 35
    else:
        base = 20
    # 相对大盘
    if index_klines and len(index_klines) >= 61:
        ig = pct_change(index_klines[-61].close, index_klines[-1].close)
        rel = g60 - ig
        if rel > 10:
            base = min(100, base + 15)
        elif rel > 0:
            base = min(100, base + 8)
        elif rel < -10:
            base = max(0, base - 15)
    if g250 > 2.5:
        base = min(100, base + 10)
    return base, f"L(相对强度){base}分"


def _i_score(flows: Optional[List[FundFlow]]) -> Tuple[int, str]:
    if not flows:
        return 50, ""
    mains = [f.main_net for f in flows]
    streak = 0
    for v in reversed(mains[-5:]):
        if v > 0:
            streak += 1
        else:
            break
    sum5 = sum(mains[-5:])
    last = mains[-1]
    super5 = sum(f.super_large_net for f in flows[-5:])
    if streak >= 3:
        score = 85
    elif sum5 < 0 and last < 0:
        score = 20 if last < -5e8 else 35
    elif sum5 > 0 and last > 0:
        score = 75
    elif sum5 > 0:
        score = 65
    else:
        score = 45
    if super5 > 0 and sum5 > 0:
        score = min(100, score + 5)
    return score, f"I(资金流代理){score}分"


def _m_score(index_klines: Optional[List[Kline]], stock: List[Kline]) -> Tuple[int, str]:
    src = index_klines if index_klines and len(index_klines) >= 30 else stock
    name = "大盘指数" if index_klines and len(index_klines) >= 30 else "个股均线(近似)"
    if len(src) < 30:
        return 50, ""
    closes = [k.close for k in src]
    ma20 = sma_series(closes, 20)
    ma60 = sma_series(closes, 60)
    if ma20[-1] is None or (len(closes) >= 60 and ma60[-1] is None):
        return 50, ""
    ma20_v = ma20[-1]
    ma60_v = ma60[-1] if ma60[-1] is not None else ma20_v
    up_days = sum(1 for i in range(len(closes) - 20, len(closes)) if closes[i] > closes[i - 1])
    rising = (
        len(ma20) >= 6 and ma20[-1] is not None and ma20[-6] is not None and ma20[-1] >= ma20[-6]
    )
    if ma20_v > ma60_v and up_days >= 13:
        score = 80
    elif ma20_v > ma60_v and up_days >= 7:
        score = 70
    elif ma20_v > ma60_v:
        score = 60
    elif name == "大盘指数":
        score = 15
    else:
        score = 35
    if not rising and score > 40:
        score -= 5
    return score, f"M(市场环境/{name}){score}分"


def _grade(score: int) -> str:
    if score >= 85:
        return "A+"
    if score >= 70:
        return "A"
    if score >= 60:
        return "B+"
    if score >= 50:
        return "B"
    if score >= 40:
        return "C+"
    if score >= 30:
        return "C"
    return "D"


def _momentum_total(c: int, a: int, n: int, s: int, leader: int, i: int, m: int) -> int:
    total = int(c * 0.15 + a * 0.10 + n * 0.25 + s * 0.05 + leader * 0.20 + i * 0.15 + m * 0.10)
    return max(0, min(100, total))


def apply_market_breadth(momentum: MomentumResult, breadth: Optional[dict]) -> MomentumResult:
    """Apply only a complete, full-universe breadth observation before aggregation."""
    if not breadth or breadth.get("available") is not True or breadth.get("complete") is not True:
        return momentum
    try:
        valid_quotes = int(breadth.get("valid_quotes", breadth.get("total", 0)) or 0)
        ratio = float(breadth["breadth_ratio"])
    except (KeyError, TypeError, ValueError):
        return momentum
    if valid_quotes < 50 or not 0.0 <= ratio <= 1.0:
        return momentum

    if ratio >= 0.7:
        bonus, label = 15, "广度强"
    elif ratio >= 0.6:
        bonus, label = 10, "偏多"
    elif ratio >= 0.5:
        bonus, label = 5, "中性"
    elif ratio >= 0.4:
        bonus, label = -5, "偏空"
    elif ratio >= 0.3:
        bonus, label = -10, "广度弱"
    else:
        bonus, label = -15, "普跌"

    adjusted_m = max(0, min(100, momentum.m_score + bonus))
    total = _momentum_total(
        momentum.c_score,
        momentum.a_score,
        momentum.n_score,
        momentum.s_score,
        momentum.l_score,
        momentum.i_score,
        adjusted_m,
    )
    up_n = int(breadth.get("up", 0) or 0)
    down_n = int(breadth.get("down", 0) or 0)
    breadth_signal = (
        f"全市场宽度修正M分{momentum.m_score}->{adjusted_m}："
        f"{up_n}涨/{down_n}跌，{ratio * 100:.0f}%上涨({label})"
    )
    description = (
        f"动量质量{total}分 评级{_grade(total)} | "
        f"C{momentum.c_score} A{momentum.a_score} N{momentum.n_score} "
        f"S{momentum.s_score} L{momentum.l_score} I{momentum.i_score} M{adjusted_m}"
    )
    return replace(
        momentum,
        m_score=adjusted_m,
        total=total,
        grade=_grade(total),
        signals=[*momentum.signals, breadth_signal],
        description=description,
    )


def analyze_momentum(
    klines: List[Kline],
    flows: Optional[List[FundFlow]] = None,
    index_klines: Optional[List[Kline]] = None,
) -> MomentumResult:
    c, cs = _c_score(klines)
    a, as_ = _a_score(klines)
    n, ns, cup = _n_score(klines)
    s, ss = _s_score(klines)
    relative_strength, relative_signal = _l_score(klines, index_klines)
    i, is_ = _i_score(flows)
    m, ms = _m_score(index_klines, klines)
    # 加权：C15 A10 N25 S5 L20 I15 M10
    total = _momentum_total(c, a, n, s, relative_strength, i, m)
    grade = _grade(total)
    signals = [x for x in (cs, as_, ns, ss, relative_signal, is_, ms) if x]
    desc = f"动量质量{total}分 评级{grade} | C{c} A{a} N{n} S{s} L{relative_strength} I{i} M{m}"
    return MomentumResult(
        c_score=c,
        a_score=a,
        n_score=n,
        s_score=s,
        l_score=relative_strength,
        i_score=i,
        m_score=m,
        total=total,
        grade=grade,
        signals=signals,
        cup_handle=cup,
        description=desc,
    )
