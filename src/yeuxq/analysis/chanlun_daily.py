"""缠论日/周线：合并 → 分型 → 笔 → 中枢 → 简化背驰/买卖点。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from yeuxq.analysis.indicators import macd
from yeuxq.domain.models import Kline


@dataclass
class Fractal:
    index: int
    type: str  # top/bottom
    price: float
    date: str


@dataclass
class Stroke:
    direction: str
    start_price: float
    end_price: float
    start_date: str
    end_date: str
    start_idx: int
    end_idx: int
    macd_area: float = 0.0
    has_divergence: bool = False


@dataclass
class Zhongshu:
    start_date: str
    end_date: str
    zg: float
    zd: float
    zz: float
    is_broken: bool = False
    break_direction: str = ""


@dataclass
class ChanSignal:
    type: str
    type_name: str
    price: float
    date: str
    description: str
    confidence: int


@dataclass
class ChanDailyResult:
    kline_count: int
    fractal_count: int
    stroke_count: int
    zhongshu_count: int
    current_state: str
    summary: str
    signals: List[ChanSignal] = field(default_factory=list)
    fractals: List[Fractal] = field(default_factory=list)
    strokes: List[Stroke] = field(default_factory=list)
    zhongshus: List[Zhongshu] = field(default_factory=list)
    chart_signals: list = field(default_factory=list)
    chart_fractals: list = field(default_factory=list)
    chart_strokes: list = field(default_factory=list)
    chart_zhongshus: list = field(default_factory=list)


def _merge_klines(klines: List[Kline]) -> List[dict]:
    """简化包含处理：同向合并高低。"""
    if not klines:
        return []
    merged = [
        {
            "high": klines[0].high,
            "low": klines[0].low,
            "date": klines[0].date,
            "idx": 0,
            "dir": 0,
        }
    ]
    for i, k in enumerate(klines[1:], 1):
        last = merged[-1]
        # 包含
        if k.high <= last["high"] and k.low >= last["low"]:
            continue
        if k.high >= last["high"] and k.low <= last["low"]:
            # 新K包含旧：按前方向扩展
            if last["dir"] >= 0:
                last["high"] = max(last["high"], k.high)
                last["date"] = k.date
                last["idx"] = i
            else:
                last["low"] = min(last["low"], k.low)
                last["date"] = k.date
                last["idx"] = i
            continue
        direction = 1 if k.high > last["high"] else -1
        merged.append(
            {
                "high": k.high,
                "low": k.low,
                "date": k.date,
                "idx": i,
                "dir": direction,
            }
        )
    return merged


def _fractals(merged: List[dict]) -> List[Fractal]:
    out: List[Fractal] = []
    for i in range(1, len(merged) - 1):
        a, b, c = merged[i - 1], merged[i], merged[i + 1]
        if b["high"] > a["high"] and b["high"] > c["high"]:
            out.append(Fractal(index=b["idx"], type="top", price=b["high"], date=b["date"]))
        if b["low"] < a["low"] and b["low"] < c["low"]:
            out.append(Fractal(index=b["idx"], type="bottom", price=b["low"], date=b["date"]))
    return out


def _strokes(fractals: List[Fractal], klines: List[Kline]) -> List[Stroke]:
    if len(fractals) < 2:
        return []
    # 交替分型
    alt: List[Fractal] = [fractals[0]]
    for f in fractals[1:]:
        if f.type == alt[-1].type:
            # 同型取更极端
            if f.type == "top" and f.price >= alt[-1].price:
                alt[-1] = f
            elif f.type == "bottom" and f.price <= alt[-1].price:
                alt[-1] = f
        else:
            alt.append(f)

    closes = [k.close for k in klines]
    _, _, hist = macd(closes)
    strokes: List[Stroke] = []
    for i in range(len(alt) - 1):
        a, b = alt[i], alt[i + 1]
        if abs(b.index - a.index) < 4:
            continue
        direction = "up" if b.price > a.price else "down"
        # MACD 面积
        lo, hi = min(a.index, b.index), max(a.index, b.index)
        area = 0.0
        for j in range(lo, min(hi + 1, len(hist))):
            if hist[j] is not None:
                area += abs(hist[j])  # type: ignore[arg-type]
        strokes.append(
            Stroke(
                direction=direction,
                start_price=a.price,
                end_price=b.price,
                start_date=a.date,
                end_date=b.date,
                start_idx=a.index,
                end_idx=b.index,
                macd_area=round(area, 2),
            )
        )
    # 背驰：同向相邻笔 MACD 面积衰减
    for i in range(1, len(strokes)):
        if strokes[i].direction == strokes[i - 1].direction:
            continue
        # 与上一段同向比较：找上一个同向
        for j in range(i - 1, -1, -1):
            if strokes[j].direction == strokes[i].direction:
                if strokes[j].macd_area > 0 and strokes[i].macd_area < strokes[j].macd_area * 0.8:
                    # 价格创新极
                    if (
                        strokes[i].direction == "down"
                        and strokes[i].end_price < strokes[j].end_price
                    ):
                        strokes[i].has_divergence = True
                    if strokes[i].direction == "up" and strokes[i].end_price > strokes[j].end_price:
                        strokes[i].has_divergence = True
                break
    return strokes


def _zhongshus(strokes: List[Stroke]) -> List[Zhongshu]:
    zs: List[Zhongshu] = []
    i = 0
    while i + 2 < len(strokes):
        s1, s2, s3 = strokes[i], strokes[i + 1], strokes[i + 2]
        # 三笔重叠
        highs = [max(s.start_price, s.end_price) for s in (s1, s2, s3)]
        lows = [min(s.start_price, s.end_price) for s in (s1, s2, s3)]
        zg = min(highs)
        zd = max(lows)
        if zg > zd:
            zz = (zg + zd) / 2
            zs.append(
                Zhongshu(
                    start_date=s1.start_date,
                    end_date=s3.end_date,
                    zg=round(zg, 2),
                    zd=round(zd, 2),
                    zz=round(zz, 2),
                )
            )
            i += 3
        else:
            i += 1
    # 是否被后续笔破坏
    if zs and strokes:
        last_price = strokes[-1].end_price
        for z in zs:
            if last_price > z.zg:
                z.is_broken = True
                z.break_direction = "up"
            elif last_price < z.zd:
                z.is_broken = True
                z.break_direction = "down"
    return zs


def _signals(strokes: List[Stroke], zhongshus: List[Zhongshu]) -> List[ChanSignal]:
    sigs: List[ChanSignal] = []
    for s in strokes:
        if s.has_divergence and s.direction == "down":
            sigs.append(
                ChanSignal(
                    type="buy1",
                    type_name="一买点",
                    price=s.end_price,
                    date=s.end_date,
                    description=f"一买点：下跌笔背驰，MACD面积{s.macd_area}",
                    confidence=min(90, 60 + int(10 if s.macd_area else 0)),
                )
            )
        if s.has_divergence and s.direction == "up":
            sigs.append(
                ChanSignal(
                    type="sell1",
                    type_name="一卖点",
                    price=s.end_price,
                    date=s.end_date,
                    description=f"一卖点：上涨笔背驰，MACD面积{s.macd_area}",
                    confidence=75,
                )
            )
    # 简化二买：一买后一笔回调不破前低
    buy1_idx = [i for i, g in enumerate(sigs) if g.type == "buy1"]
    if buy1_idx and len(strokes) >= 3:
        last_buy = sigs[buy1_idx[-1]]
        for s in strokes:
            if (
                s.end_date > last_buy.date
                and s.direction == "down"
                and s.end_price >= last_buy.price
            ):
                sigs.append(
                    ChanSignal(
                        type="buy2",
                        type_name="二买点",
                        price=s.end_price,
                        date=s.end_date,
                        description=f"二买点：一买后回调未破前低{last_buy.price}",
                        confidence=70,
                    )
                )
                break
    return sigs[-6:]


def analyze_chanlun_daily(klines: List[Kline]) -> ChanDailyResult:
    if len(klines) < 30:
        return ChanDailyResult(
            kline_count=len(klines),
            fractal_count=0,
            stroke_count=0,
            zhongshu_count=0,
            current_state="数据不足",
            summary="K线不足，无法缠论分析",
        )
    merged = _merge_klines(klines)
    fr = _fractals(merged)
    strokes = _strokes(fr, klines)
    zs = _zhongshus(strokes)
    sigs = _signals(strokes, zs)

    price = klines[-1].close
    state = "中枢外"
    if zs:
        z = zs[-1]
        if z.zd <= price <= z.zg:
            state = f"中枢内[{z.zd}-{z.zg}]震荡"
        elif price > z.zg:
            state = f"中枢上破[{z.zd}-{z.zg}]"
        else:
            state = f"中枢下破[{z.zd}-{z.zg}]"

    summary = f"缠论：{len(fr)}分型 {len(strokes)}笔 {len(zs)}中枢；{state}"
    if sigs:
        summary += f"；最新{sigs[-1].type_name}@{sigs[-1].price}"

    chart_signals = [
        {
            "type": s.type,
            "type_name": s.type_name,
            "price": s.price,
            "date": s.date,
            "confidence": s.confidence,
        }
        for s in sigs
    ]
    chart_fractals = [{"type": f.type, "price": f.price, "date": f.date} for f in fr[-40:]]
    chart_strokes = [
        {
            "direction": s.direction,
            "start_price": s.start_price,
            "end_price": s.end_price,
            "start_date": s.start_date,
            "end_date": s.end_date,
            "has_divergence": s.has_divergence,
        }
        for s in strokes
    ]
    chart_zs = [
        {
            "start_date": z.start_date,
            "end_date": z.end_date,
            "zg": z.zg,
            "zd": z.zd,
            "zz": z.zz,
            "is_broken": z.is_broken,
            "break_direction": z.break_direction,
        }
        for z in zs
    ]

    return ChanDailyResult(
        kline_count=len(klines),
        fractal_count=len(fr),
        stroke_count=len(strokes),
        zhongshu_count=len(zs),
        current_state=state,
        summary=summary,
        signals=sigs,
        fractals=fr,
        strokes=strokes,
        zhongshus=zs,
        chart_signals=chart_signals,
        chart_fractals=chart_fractals,
        chart_strokes=chart_strokes,
        chart_zhongshus=chart_zs,
    )


def daily_result_to_dict(r: ChanDailyResult) -> dict:
    return {
        "kline_count": r.kline_count,
        "merged_count": getattr(r, "merged_count", r.kline_count),
        "fractal_count": r.fractal_count,
        "stroke_count": r.stroke_count,
        "zhongshu_count": r.zhongshu_count,
        "current_state": r.current_state,
        "summary": r.summary,
        "description": r.summary,
        "zhongshus": [
            {
                "start_date": z.start_date,
                "end_date": z.end_date,
                "zg": z.zg,
                "zd": z.zd,
                "zz": z.zz,
                "is_broken": z.is_broken,
                "break_direction": z.break_direction,
            }
            for z in r.zhongshus
        ],
        "signals": [
            {
                "type": s.type,
                "type_name": s.type_name,
                "price": s.price,
                "date": s.date,
                "description": s.description,
                "confidence": s.confidence,
            }
            for s in r.signals
        ],
        "chart_signals": r.chart_signals,
        "chart_fractals": r.chart_fractals,
        "chart_strokes": r.chart_strokes,
        "chart_zhongshus": r.chart_zhongshus,
    }
