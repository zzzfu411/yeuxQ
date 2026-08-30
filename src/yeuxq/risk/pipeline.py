"""统一风控：硬/软否决、分级、仓位、盈亏比。"""

from __future__ import annotations

from typing import List

from yeuxq.domain.models import SignalResult, TradePlan
from yeuxq.settings import EngineCfg, RiskCfg


def apply_risk_pipeline(
    result: SignalResult,
    engine_cfg: EngineCfg,
    risk_cfg: RiskCfg,
) -> SignalResult:
    action = result.action
    original = action
    score = result.score
    confidence = result.confidence
    module_scores = result.module_scores
    m_score = result.momentum.m_score if result.momentum else 50

    stock_signals: List[str] = []
    if result.trend:
        stock_signals.extend(result.trend.signals)
    if result.volume_price:
        stock_signals.extend(result.volume_price.signals)
    for s in result.buy_signals + result.sell_signals:
        if any(kw in s for kw in ("大盘", "空头环境", "今日", "上证")):
            continue
        stock_signals.append(s)
    text = " ".join(stock_signals)
    if result.volume_price:
        text += " " + result.volume_price.pattern

    hard_reason = None
    for kw in risk_cfg.hard_veto:
        if kw in text:
            hard_reason = kw
            break
    soft_reason = None
    for kw in risk_cfg.soft_veto:
        if kw in text:
            soft_reason = kw
            break

    scores_list = [
        module_scores.get("趋势", 50),
        module_scores.get("动量质量", 50),
        module_scores.get("突破", 50),
        module_scores.get("量价", 50),
        module_scores.get("形态", 50),
    ]
    modules_above = sum(1 for s in scores_list if s >= 55)
    thr = engine_cfg.action
    veto_reason = ""

    is_sell = action in ("卖出", "强烈卖出")
    is_buy = action in ("买入", "强烈买入", "谨慎买入")

    if is_sell:
        pass
    elif is_buy or action == "观望":
        if hard_reason and (is_buy or score >= thr.cautious_score):
            action = "观望"
            veto_reason = f"硬否决：{hard_reason}"
        else:
            if (
                score >= thr.strong_buy_score
                and confidence >= thr.strong_buy_confidence
                and modules_above >= thr.strong_buy_modules
            ):
                action = "强烈买入"
            elif (
                score >= thr.buy_score
                and confidence >= thr.buy_confidence
                and modules_above >= thr.buy_modules
            ):
                action = "买入"
            elif score >= thr.cautious_score:
                action = "谨慎买入"
            else:
                action = "观望"
            if soft_reason and action == "强烈买入":
                action = "买入"
                veto_reason = f"软否决：{soft_reason}"
            elif soft_reason and action == "买入":
                action = "谨慎买入"
                veto_reason = f"软否决：{soft_reason}"

    # M 分仓位
    if action in ("买入", "强烈买入", "谨慎买入"):
        if m_score < 40:
            position = "轻仓(1/4) — 大盘偏空"
            if action == "强烈买入":
                action = "买入"
                veto_reason = (veto_reason + "；" if veto_reason else "") + f"M分{m_score}偏低降级"
            elif action == "买入":
                action = "谨慎买入"
                veto_reason = (veto_reason + "；" if veto_reason else "") + f"M分{m_score}偏低降级"
        elif m_score < 55:
            position = "半仓(1/2) — 大盘中性偏弱"
        elif m_score < 65:
            position = "半仓(1/2)"
        else:
            position = "正常仓位"
    else:
        position = "空仓等待"

    plan = result.trade_plan
    risk_notes: List[str] = []
    rr = plan.risk_reward_ratio
    entry, stop, target = plan.entry_price, plan.stop_loss, plan.target_price
    if entry and stop and target and entry > stop:
        if not rr:
            rr = round((target - entry) / (entry - stop), 1)
        if rr < 1.0:
            risk_notes.append(f"盈亏比{rr}倒挂，不建议入场")
            if action in ("买入", "强烈买入", "谨慎买入"):
                action = "观望"
                veto_reason = (veto_reason + "；" if veto_reason else "") + f"盈亏比{rr}倒挂"
        elif rr < 1.5:
            risk_notes.append(f"盈亏比{rr}偏低，谨慎操作")
        elif rr < 2.0:
            risk_notes.append(f"盈亏比{rr}，勉强达标")
        else:
            risk_notes.append(f"盈亏比{rr}，风险收益比良好")

    plan = TradePlan(
        action=action,
        entry_price=plan.entry_price,
        stop_loss=plan.stop_loss,
        target_price=plan.target_price,
        position_size=position,
        holding_period=plan.holding_period,
        risk_reward_ratio=rr,
        max_loss_pct=plan.max_loss_pct,
        notes=plan.notes,
        stop_method=plan.stop_method,
    )

    warnings = list(result.risk_warnings)
    if veto_reason:
        warnings.insert(0, veto_reason)

    summary = result.plain_summary
    if veto_reason and action != original:
        summary = f"[优化：{original}→{action}] {veto_reason}。{summary}"

    result.action = action
    result.original_action = original
    result.veto_reason = veto_reason
    result.position_advice = position
    result.risk_notes = risk_notes
    result.risk_reward = rr
    result.trade_plan = plan
    result.risk_warnings = warnings
    result.plain_summary = summary
    return result
