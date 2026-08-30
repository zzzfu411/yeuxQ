"""量价模块：量价模式 + OBV + 资金流衍生特征。"""

from __future__ import annotations

from typing import List, Optional, Tuple

from yeuxq.analysis.indicators import last_sma, ma_direction, sma_series
from yeuxq.domain.models import FundFlow, Kline, Quote, VolumePriceResult


def _calc_obv(klines: List[Kline]) -> List[float]:
    obv: List[float] = []
    running = 0.0
    prev = None
    for k in klines:
        if prev is not None and k.close != prev:
            running += k.volume if k.close > prev else -k.volume
        obv.append(running)
        prev = k.close
    return obv


def _classify(klines: List[Kline]) -> Tuple[str, str, int]:
    if len(klines) < 10:
        return "数据不足", "中性", 50
    closes = [k.close for k in klines]
    g8 = (closes[-1] - closes[-8]) / closes[-8] * 100 if closes[-8] else 0.0
    vols = [k.volume for k in klines]
    if g8 > 2:
        price_dir = "涨"
    elif g8 < -2:
        price_dir = "跌"
    else:
        price_dir = "平"
    if len(vols) >= 8:
        ma3 = sum(vols[-3:]) / 3
        ma5p = sum(vols[-8:-3]) / 5
        vc = (ma3 - ma5p) / ma5p * 100 if ma5p else 0.0
    else:
        vc = 0.0
    if vc > 30:
        vol_dir = "增"
    elif vc < -30:
        vol_dir = "缩"
    else:
        vol_dir = "平"

    mapping = {
        ("涨", "增"): ("量价齐升", "看涨", 82),
        ("涨", "缩"): ("价涨量缩", "中性", 45),
        ("涨", "平"): ("价涨量平", "看涨", 60),
        ("跌", "增"): ("价跌量增", "看跌", 75),
        ("跌", "缩"): ("缩量回调", "中性", 55),
        ("跌", "平"): ("价跌量平", "看跌", 58),
        ("平", "增"): ("放量滞涨", "中性", 48),
        ("平", "缩"): ("缩量整理", "中性", 52),
        ("平", "平"): ("量价平衡", "中性", 50),
    }
    return mapping.get((price_dir, vol_dir), ("量价平衡", "中性", 50))


def _flow_features(flows: Optional[List[FundFlow]]) -> dict:
    if not flows:
        return {
            "main_flow_streak": 0,
            "sum5_main": 0.0,
            "super_large_ratio": 0.0,
            "main_pct_last": 0.0,
            "label": "无资金流",
            "bonus": 0,
        }
    mains = [f.main_net for f in flows]
    streak = 0
    for v in reversed(mains):
        if v > 0:
            streak += 1
        else:
            break
    sum5 = sum(mains[-5:])
    last = mains[-1]
    super5 = sum(f.super_large_net for f in flows[-5:])
    abs_main5 = sum(abs(f.main_net) for f in flows[-5:]) or 1.0
    super_ratio = super5 / abs_main5
    bonus = 0
    label = "主力资金温和"
    if streak >= 3:
        bonus, label = 15, f"连续{streak}日主力净流入"
    elif sum5 < 0 and last < -5e8:
        bonus, label = -15, "今日主力大幅流出"
    elif sum5 > 0 and last > 0:
        bonus, label = 10, "5日主力净流入"
    elif sum5 < 0:
        bonus, label = -8, "5日主力净流出"
    if super_ratio > 0.5 and last > 0:
        bonus += 5
        label += "·超大单占优"
    return {
        "main_flow_streak": streak,
        "sum5_main": sum5,
        "super_large_ratio": round(super_ratio, 3),
        "main_pct_last": flows[-1].main_pct,
        "label": label,
        "bonus": bonus,
    }


def analyze_volume_price(
    klines: List[Kline],
    quote: Optional[Quote] = None,
    flows: Optional[List[FundFlow]] = None,
) -> VolumePriceResult:
    pattern, direction, conf = _classify(klines)
    vols = [k.volume for k in klines]
    vol_ma = last_sma(vols, 5) or 1.0
    volume_ratio = round((vols[-1] / vol_ma) if vol_ma else 1.0, 2)
    turnover = quote.turnover if quote else (klines[-1].turnover if klines else 0.0)

    obv = _calc_obv(klines)
    obv_ma = sma_series(obv, 5)
    obv_dir = ma_direction(obv_ma, 3)
    if obv_dir == "向上":
        obv_trend = "上升"
    elif obv_dir == "向下":
        obv_trend = "下降"
    else:
        obv_trend = "走平"

    feats = _flow_features(flows)
    conf = max(20, min(100, conf + int(feats["bonus"])))

    signals: List[str] = []
    if direction == "看涨":
        signals.append("量价配合良好")
    if pattern == "价跌量增":
        signals.append("价跌量增")
    if obv_trend == "上升":
        signals.append("OBV向上")
    elif obv_trend == "下降":
        signals.append("OBV下降")
    if feats["label"]:
        signals.append(feats["label"])
    if "净流入" in feats["label"]:
        signals.append("主力净流入")
    if "流出" in feats["label"]:
        signals.append("主力净流出")

    desc = f"{pattern} | 量比{volume_ratio} | OBV{obv_trend} | {feats['label']}"
    return VolumePriceResult(
        pattern=pattern,
        direction=direction,
        confidence=conf,
        volume_ratio=volume_ratio,
        turnover=turnover or 0.0,
        obv_trend=obv_trend,
        signals=signals,
        description=desc,
        flow_features=feats,
    )
