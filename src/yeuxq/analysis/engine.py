"""统一信号引擎：五模块 + 风控 + 预测。"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

from yeuxq.analysis.breakout import analyze_breakout, breakout_score
from yeuxq.analysis.momentum_quality import analyze_momentum, apply_market_breadth
from yeuxq.analysis.pattern import analyze_patterns, pattern_score
from yeuxq.analysis.plugins.rule_predictor import RulePredictor
from yeuxq.analysis.trend import analyze_trend
from yeuxq.analysis.volume_price import analyze_volume_price
from yeuxq.domain.models import (
    BreakoutResult,
    FundFlow,
    Kline,
    MomentumResult,
    PatternResult,
    Quote,
    SignalResult,
    TradePlan,
    TrendResult,
    VolumePriceResult,
)
from yeuxq.analysis.rust_bridge import analyze_rust, rust_status
from yeuxq.risk.pipeline import apply_risk_pipeline
from yeuxq.settings import Settings, get_settings

log = logging.getLogger("yeuxq.engine")


def _klines_payload(klines: List[Kline]) -> list:
    return [
        {
            "date": k.date,
            "open": k.open,
            "close": k.close,
            "high": k.high,
            "low": k.low,
            "volume": k.volume,
            "amount": k.amount,
            "pct": k.pct,
            "turnover": k.turnover,
        }
        for k in klines
    ]


def _flows_payload(flows: Optional[List[FundFlow]]) -> list:
    if not flows:
        return []
    return [
        {
            "date": f.date,
            "main_net": f.main_net,
            "super_large_net": f.super_large_net,
            "large_net": f.large_net,
            "medium_net": f.medium_net,
            "small_net": f.small_net,
            "main_pct": f.main_pct,
        }
        for f in flows
    ]


def _cfg_payload(settings: Settings) -> dict:
    e = settings.engine
    return {
        "w_trend": e.weights.trend,
        "w_momentum": e.weights.momentum,
        "w_breakout": e.weights.breakout,
        "w_volume": e.weights.volume_price,
        "w_pattern": e.weights.pattern,
        "strong_buy_score": e.action.strong_buy_score,
        "strong_buy_confidence": e.action.strong_buy_confidence,
        "strong_buy_modules": e.action.strong_buy_modules,
        "buy_score": e.action.buy_score,
        "buy_confidence": e.action.buy_confidence,
        "buy_modules": e.action.buy_modules,
        "cautious_score": e.action.cautious_score,
        "stop_loss": e.stop_loss,
        "fixed_stop_pct": e.fixed_stop_pct,
        "chanlun_bonus": e.chanlun_bonus,
        "sell_symmetric": getattr(e, "sell_symmetric", True),
        "atr_position": getattr(e, "atr_position", True),
    }


def _result_from_rust(d: dict) -> SignalResult:
    from yeuxq.domain.models import Prediction

    tp = d.get("trade_plan") or {}
    pred = d.get("prediction") or {}
    tilt = float(pred.get("tilt") or pred.get("prob_up") or 0)
    tr = d.get("trend") or {}
    vp = d.get("volume_price") or {}
    mom = d.get("momentum") or {}
    trend = None
    if tr:
        trend = TrendResult(
            direction=tr.get("direction", ""),
            strength=int(tr.get("strength") or 0),
            stage=tr.get("stage", ""),
            ma_arrangement=tr.get("ma_arrangement", ""),
            ma_scores=tr.get("ma_scores") or {},
            signals=list(tr.get("signals") or []),
        )
    volume = None
    if vp:
        volume = VolumePriceResult(
            pattern=vp.get("pattern", ""),
            direction=vp.get("direction", ""),
            confidence=int(vp.get("confidence") or 0),
            volume_ratio=float(vp.get("volume_ratio") or 0),
            turnover=float(vp.get("turnover") or 0),
            obv_trend=vp.get("obv_trend", ""),
            signals=list(vp.get("signals") or []),
            flow_features=vp.get("flow_features") or {},
        )
    patterns = [
        PatternResult(
            name=p.get("name", ""),
            direction=p.get("direction", ""),
            confidence=int(p.get("confidence") or 0),
            status=p.get("status", ""),
            target_price=p.get("target_price"),
            key_levels=p.get("key_levels") or {},
        )
        for p in (d.get("patterns") or [])
    ]
    breakouts = [
        BreakoutResult(
            system=b.get("system", ""),
            signal=b.get("signal", ""),
            breakout_price=float(b.get("breakout_price") or 0),
            current_n=float(b.get("current_n") or 0),
            stop_loss=float(b.get("stop_loss") or 0),
            entry_price=b.get("entry_price"),
            position_units=int(b.get("position_units") or 0),
            channel_high=float(b.get("channel_high") or 0),
            channel_low=float(b.get("channel_low") or 0),
            next_add_price=b.get("next_add_price"),
            signals=list(b.get("signals") or []),
        )
        for b in (d.get("breakouts") or [])
    ]
    momentum = None
    if mom:
        momentum = MomentumResult(
            c_score=int(mom.get("c_score") or 0),
            a_score=int(mom.get("a_score") or 0),
            n_score=int(mom.get("n_score") or 0),
            s_score=int(mom.get("s_score") or 0),
            l_score=int(mom.get("l_score") or 0),
            i_score=int(mom.get("i_score") or 0),
            m_score=int(mom.get("m_score") or 0),
            total=int(mom.get("total") or 0),
            grade=mom.get("grade", ""),
            signals=list(mom.get("signals") or []),
            description=mom.get("description", ""),
        )
    plan = TradePlan(
        action=tp.get("action", ""),
        entry_price=float(tp.get("entry_price") or 0),
        stop_loss=float(tp.get("stop_loss") or 0),
        target_price=float(tp.get("target_price") or 0),
        position_size=tp.get("position_size", ""),
        holding_period=tp.get("holding_period", "中线(1-3月)"),
        risk_reward_ratio=float(tp.get("risk_reward_ratio") or 0),
        max_loss_pct=float(tp.get("max_loss_pct") or 0),
        notes=tp.get("notes", ""),
        stop_method=tp.get("stop_method", ""),
    )
    return SignalResult(
        action=d.get("action", "观望"),
        score=int(d.get("score") or 0),
        confidence=int(d.get("confidence") or 0),
        risk_level=d.get("risk_level", ""),
        signal_strength=d.get("signal_strength", ""),
        plain_summary=d.get("plain_summary", ""),
        trade_plan=plan,
        module_scores=d.get("module_scores") or {},
        buy_signals=list(d.get("buy_signals") or []),
        sell_signals=list(d.get("sell_signals") or []),
        risk_warnings=list(d.get("risk_warnings") or []),
        key_levels=d.get("key_levels") or {},
        description=d.get("description", ""),
        trend=trend,
        patterns=patterns,
        volume_price=volume,
        breakouts=breakouts,
        momentum=momentum,
        prediction=Prediction(
            direction=pred.get("direction", ""),
            horizon_days=int(pred.get("horizon_days") or 5),
            prob_up=tilt,
            confidence=float(pred.get("confidence") or 0),
            drivers=list(pred.get("drivers") or []),
            model=pred.get("model", "rule_v2_rust"),
            disclaimer=pred.get("disclaimer", ""),
            tilt=tilt,
        ),
        original_action=d.get("original_action", ""),
        veto_reason=d.get("veto_reason", ""),
        position_advice=d.get("position_advice", ""),
        risk_notes=list(d.get("risk_notes") or []),
        risk_reward=float(d.get("risk_reward") or 0),
    )


def _volume_score(vp: VolumePriceResult) -> int:
    if vp.direction == "看涨":
        return vp.confidence
    if vp.direction == "看跌":
        return max(20, 100 - vp.confidence)
    return 50


def _build_trade_plan(
    action: str,
    score: int,
    trend: TrendResult,
    patterns: List[PatternResult],
    breakouts: List[BreakoutResult],
    klines: List[Kline],
    settings: Settings,
) -> TradePlan:
    entry = klines[-1].close if klines else 0.0
    method = settings.engine.stop_loss
    fixed = round(entry * (1 - settings.engine.fixed_stop_pct), 2)

    atr_stop = fixed
    for b in breakouts:
        if b.signal in ("持仓", "突破买入") and b.stop_loss:
            atr_stop = b.stop_loss
            break

    structure_stop = fixed
    if trend.trendline and trend.trendline.get("end_price"):
        structure_stop = min(fixed, float(trend.trendline["end_price"]) * 0.99)

    if method == "fixed_pct":
        stop, stop_method = fixed, "fixed_pct"
    elif method == "atr_2n":
        stop, stop_method = atr_stop, "atr_2n"
    elif method == "structure":
        stop, stop_method = structure_stop, "structure"
    else:
        # hybrid: 取更高的止损（更紧）但仍低于入场
        candidates = [s for s in (fixed, atr_stop, structure_stop) if s and s < entry]
        stop = max(candidates) if candidates else fixed
        stop_method = "hybrid"

    target = entry * 1.1
    for name in ("头肩底", "双底", "箱体"):
        for p in patterns:
            if (
                p.name == name
                and p.direction == "看涨"
                and p.target_price
                and p.target_price > entry
            ):
                target = p.target_price
                break
        else:
            continue
        break
    # 杯柄目标在 momentum 里，引擎外也可；这里用形态优先

    risk = entry - stop
    reward = target - entry
    rr = round(reward / risk, 1) if risk > 0 else 0.0
    max_loss = round((entry - stop) / entry * 100, 2) if entry else 5.0

    notes_parts = []
    for b in breakouts:
        if b.signal == "持仓" and b.entry_price:
            notes_parts.append(
                f"{b.system}持仓中(突破价{b.entry_price})，止损{b.stop_loss}"
                + (f"，加仓价{b.next_add_price}" if b.next_add_price else "")
            )
            break
    notes = "；".join(notes_parts)

    pos = "半仓(1/2)" if action in ("买入", "强烈买入", "谨慎买入") else "空仓等待"
    return TradePlan(
        action=action,
        entry_price=round(entry, 2),
        stop_loss=round(stop, 2),
        target_price=round(target, 2),
        position_size=pos,
        risk_reward_ratio=rr,
        max_loss_pct=max_loss,
        notes=notes,
        stop_method=stop_method,
    )


def run_analysis(
    klines: List[Kline],
    quote: Optional[Quote] = None,
    flows: Optional[List[FundFlow]] = None,
    index_klines: Optional[List[Kline]] = None,
    weekly_klines: Optional[List[Kline]] = None,
    settings: Optional[Settings] = None,
    market_breadth: Optional[dict] = None,
) -> SignalResult:
    settings = settings or get_settings()
    engine_choice = os.environ.get("YEUXQ_ENGINE", "python")
    use_rust = engine_choice.strip().lower() == "rust"
    if use_rust and market_breadth and market_breadth.get("available") is True:
        log.warning(
            "rust engine does not satisfy the breadth parity contract; using canonical python"
        )
        use_rust = False
    if use_rust and rust_status().get("available"):
        try:
            payload = {
                "klines": _klines_payload(klines),
                "flows": _flows_payload(flows),
                "index": _klines_payload(index_klines or []),
                "weekly": _klines_payload(weekly_klines or []),
                "config": _cfg_payload(settings),
            }
            return _result_from_rust(analyze_rust(payload))
        except Exception:
            log.exception("rust engine failed, fallback python")

    w = settings.engine.weights

    trend = analyze_trend(klines)
    vp = analyze_volume_price(klines, quote, flows)
    patterns = analyze_patterns(klines)
    breakouts = analyze_breakout(klines)
    momentum = apply_market_breadth(
        analyze_momentum(klines, flows, index_klines),
        market_breadth,
    )

    t_score = trend.strength
    m_score = momentum.total
    b_score = breakout_score(breakouts)
    v_score = _volume_score(vp)
    p_score = pattern_score(patterns)

    # 周线共振微调
    weekly_align = 0
    if weekly_klines and len(weekly_klines) >= 30:
        wt = analyze_trend(weekly_klines)
        if wt.direction == "上升" and trend.direction == "上升":
            t_score = min(100, t_score + 5)
            weekly_align = 1
        elif wt.direction == "下降" and trend.direction == "上升":
            t_score = max(0, t_score - 5)
            weekly_align = -1

    score = int(
        t_score * w.trend
        + m_score * w.momentum
        + b_score * w.breakout
        + v_score * w.volume_price
        + p_score * w.pattern
    )
    score = max(0, min(100, score))

    module_scores = {
        "趋势": t_score,
        "动量质量": m_score,
        "突破": b_score,
        "量价": v_score,
        "形态": p_score,
    }
    modules_ok = sum(1 for s in module_scores.values() if s >= 55)
    confidence = max(10, min(95, int(score * 0.8) + 12 * modules_ok - 40))

    # 初步 action
    thr = settings.engine.action
    if score >= thr.strong_buy_score:
        action = "强烈买入"
    elif score >= thr.buy_score:
        action = "买入"
    elif score >= thr.cautious_score:
        action = "谨慎买入"
    else:
        action = "观望"

    # 卖出启发
    sell_signals: List[str] = []
    buy_signals: List[str] = []
    if trend.direction == "下降":
        sell_signals.append("处于下降趋势")
    if vp.direction == "看跌":
        sell_signals.append(f"量价{vp.pattern}")
    for b in breakouts:
        if b.signal in ("向下突破", "多头止损"):
            sell_signals.append(f"{b.system}{b.signal}")
        if b.signal in ("持仓", "突破买入"):
            buy_signals.append(f"{b.system}{b.signal}")
    if trend.direction == "上升":
        buy_signals.append(f"趋势{trend.stage}")
    if vp.direction == "看涨":
        buy_signals.append(vp.pattern)
    for p in patterns:
        if p.direction == "看涨" and p.status == "已突破":
            buy_signals.append(f"{p.name}已突破")
        if p.direction == "看跌" and p.status in ("已跌破", "已突破"):
            sell_signals.append(p.name)

    if len(sell_signals) >= 3 and score < 55:
        action = "卖出"

    # 风险等级
    risk_points = 0
    if trend.direction == "下降":
        risk_points += 2
    if vp.direction == "看跌":
        risk_points += 2
    if momentum.m_score < 30:
        risk_points += 1
    if any("止损" in s for b in breakouts for s in b.signals):
        risk_points += 1
    risk_level = "高" if risk_points >= 5 else ("中" if risk_points >= 3 else "低")
    strength = "强" if score >= 75 else ("中" if score >= 60 else "弱")

    plan = _build_trade_plan(action, score, trend, patterns, breakouts, klines, settings)

    key_levels = {}
    if plan.stop_loss:
        key_levels["止损"] = plan.stop_loss
    if plan.entry_price:
        key_levels["入场"] = plan.entry_price
    if plan.target_price:
        key_levels["目标"] = plan.target_price
    for b in breakouts:
        if b.channel_high:
            key_levels[f"{b.system}上轨"] = b.channel_high
        if b.channel_low:
            key_levels[f"{b.system}下轨"] = b.channel_low
    for p in patterns:
        key_levels.update({f"{p.name}-{k}": v for k, v in p.key_levels.items()})

    warnings: List[str] = []
    if momentum.m_score < 40:
        warnings.append("大盘环境偏弱，注意控制仓位")
    if vp.pattern == "价跌量增":
        warnings.append("价跌量增，抛压加重")
    if quote and quote.turnover and quote.turnover > 15:
        warnings.append(f"换手率{quote.turnover:.1f}%过高(可能有分歧)")

    plain = (
        f"综合{score}分({strength})，趋势{trend.direction}，建议{action}。"
        f"量价{vp.pattern}，动量评级{momentum.grade}。"
    )
    desc = (
        f"综合{score}分 | 趋势={trend.direction}({t_score}) | 量价={vp.pattern}({v_score}) "
        f"| 突破={b_score} | 动量={momentum.grade}({m_score}) | 形态={p_score}"
    )

    result = SignalResult(
        action=action,
        score=score,
        confidence=confidence,
        risk_level=risk_level,
        signal_strength=strength,
        plain_summary=plain,
        trade_plan=plan,
        module_scores=module_scores,
        buy_signals=buy_signals,
        sell_signals=sell_signals,
        risk_warnings=warnings,
        key_levels=key_levels,
        description=desc,
        trend=trend,
        patterns=patterns,
        volume_price=vp,
        breakouts=breakouts,
        momentum=momentum,
    )

    result = apply_risk_pipeline(result, settings.engine, settings.risk)

    # 预测
    feats = {
        "score": result.score,
        "trend": t_score,
        "momentum": m_score,
        "volume_price": v_score,
        "breakout": b_score,
        "pattern": p_score,
        "m_score": momentum.m_score,
        "main_flow_streak": (vp.flow_features or {}).get("main_flow_streak", 0),
        "weekly_align": weekly_align,
        "horizon_days": settings.prediction.horizon_days,
    }
    predictor = RulePredictor(settings.prediction)
    result.prediction = predictor.predict(feats)
    return result


def extract_features(
    klines: List[Kline],
    quote: Optional[Quote] = None,
    flows: Optional[List[FundFlow]] = None,
    index_klines: Optional[List[Kline]] = None,
) -> dict:
    """导出特征供 ML 插件使用。"""
    result = run_analysis(klines, quote, flows, index_klines)
    vp = result.volume_price
    return {
        "score": result.score,
        "module_scores": result.module_scores,
        "action": result.action,
        "m_score": result.momentum.m_score if result.momentum else None,
        "flow_features": vp.flow_features if vp else {},
        "prediction": {
            "prob_up": result.prediction.prob_up if result.prediction else None,
            "direction": result.prediction.direction if result.prediction else None,
        },
    }
