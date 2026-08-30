"""结果序列化。"""

from __future__ import annotations

from yeuxq.domain.models import (
    FundFlow,
    Kline,
    MinuteFlow,
    Quote,
    SignalResult,
)


def kline_to_dict(k: Kline) -> dict:
    return {
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


def quote_to_dict(q: Quote) -> dict:
    return {
        "symbol": q.symbol,
        "name": q.name,
        "price": q.price,
        "pct": q.pct,
        "change": q.change,
        "high": q.high,
        "low": q.low,
        "open": q.open,
        "pre_close": q.pre_close,
        "volume": q.volume,
        "amount": q.amount,
        "turnover": q.turnover,
    }


def flow_to_dict(f: FundFlow) -> dict:
    return {
        "date": f.date,
        "main_net": f.main_net,
        "super_large_net": f.super_large_net,
        "large_net": f.large_net,
        "medium_net": f.medium_net,
        "small_net": f.small_net,
        "main_pct": f.main_pct,
    }


def minute_flow_to_dict(f: MinuteFlow) -> dict:
    return {
        "time": f.time,
        "main_net": f.main_net,
        "small_net": f.small_net,
        "medium_net": f.medium_net,
        "large_net": f.large_net,
        "super_large_net": f.super_large_net,
    }


def signal_to_dict(r: SignalResult) -> dict:
    data = {
        "action": r.action,
        "score": r.score,
        "confidence": r.confidence,
        "risk_level": r.risk_level,
        "signal_strength": r.signal_strength,
        "plain_summary": r.plain_summary,
        "trade_plan": {
            "action": r.trade_plan.action,
            "entry_price": r.trade_plan.entry_price,
            "stop_loss": r.trade_plan.stop_loss,
            "target_price": r.trade_plan.target_price,
            "position_size": r.trade_plan.position_size,
            "holding_period": r.trade_plan.holding_period,
            "risk_reward_ratio": r.trade_plan.risk_reward_ratio,
            "max_loss_pct": r.trade_plan.max_loss_pct,
            "notes": r.trade_plan.notes,
            "stop_method": r.trade_plan.stop_method,
        },
        "module_scores": r.module_scores,
        "buy_signals": r.buy_signals,
        "sell_signals": r.sell_signals,
        "risk_warnings": r.risk_warnings,
        "key_levels": r.key_levels,
        "description": r.description,
        "original_action": r.original_action,
        "veto_reason": r.veto_reason,
        "position_advice": r.position_advice,
        "risk_notes": r.risk_notes,
        "risk_reward": r.risk_reward,
        "trend": None,
        "patterns": [],
        "volume_price": None,
        "breakouts": [],
        "momentum": None,
        "canslim": None,  # 兼容旧前端字段名
        "prediction": None,
    }
    if r.trend:
        data["trend"] = {
            "direction": r.trend.direction,
            "strength": r.trend.strength,
            "stage": r.trend.stage,
            "ma_arrangement": r.trend.ma_arrangement,
            "ma_scores": r.trend.ma_scores,
            "trendline": r.trend.trendline,
            "signals": r.trend.signals,
        }
    for p in r.patterns:
        data["patterns"].append(
            {
                "name": p.name,
                "direction": p.direction,
                "confidence": p.confidence,
                "status": p.status,
                "target_price": p.target_price,
                "key_levels": p.key_levels,
                "description": p.description,
            }
        )
    if r.volume_price:
        data["volume_price"] = {
            "pattern": r.volume_price.pattern,
            "direction": r.volume_price.direction,
            "confidence": r.volume_price.confidence,
            "volume_ratio": r.volume_price.volume_ratio,
            "turnover": r.volume_price.turnover,
            "obv_trend": r.volume_price.obv_trend,
            "signals": r.volume_price.signals,
            "description": r.volume_price.description,
            "flow_features": r.volume_price.flow_features,
        }
    for b in r.breakouts:
        data["breakouts"].append(
            {
                "system": b.system,
                "signal": b.signal,
                "breakout_price": b.breakout_price,
                "current_n": b.current_n,
                "stop_loss": b.stop_loss,
                "entry_price": b.entry_price,
                "position_units": b.position_units,
                "exit_price": b.exit_price,
                "channel_high": b.channel_high,
                "channel_low": b.channel_low,
                "next_add_price": b.next_add_price,
                "signals": b.signals,
                "description": b.description,
            }
        )
    if r.momentum:
        mom = {
            "c_score": r.momentum.c_score,
            "a_score": r.momentum.a_score,
            "n_score": r.momentum.n_score,
            "s_score": r.momentum.s_score,
            "l_score": r.momentum.l_score,
            "i_score": r.momentum.i_score,
            "m_score": r.momentum.m_score,
            "total": r.momentum.total,
            "grade": r.momentum.grade,
            "signals": r.momentum.signals,
            "cup_handle": r.momentum.cup_handle,
            "description": r.momentum.description,
        }
        data["momentum"] = mom
        data["canslim"] = mom  # 兼容
    if r.prediction:
        data["prediction"] = {
            "direction": r.prediction.direction,
            "horizon_days": r.prediction.horizon_days,
            "prob_up": r.prediction.prob_up,
            "tilt": getattr(r.prediction, "tilt", r.prediction.prob_up),
            "confidence": r.prediction.confidence,
            "drivers": r.prediction.drivers,
            "model": r.prediction.model,
            "disclaimer": r.prediction.disclaimer,
        }
    return data
