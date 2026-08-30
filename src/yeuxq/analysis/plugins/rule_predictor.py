"""规则版趋势预测：线性打分 → sigmoid 概率。"""

from __future__ import annotations

import math
from typing import Any

from yeuxq.domain.models import Prediction
from yeuxq.settings import PredictionCfg

SUPPORTED_PREDICTION_HORIZONS = (5,)


class UnsupportedPredictionHorizon(ValueError):
    def __init__(self, requested: int) -> None:
        self.requested = requested
        self.supported = SUPPORTED_PREDICTION_HORIZONS
        super().__init__(f"unsupported prediction horizon: {requested}")


def _sigmoid(x: float) -> float:
    if x >= 30:
        return 1.0
    if x <= -30:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


class RulePredictor:
    name = "rule_v1"

    def __init__(self, cfg: PredictionCfg | None = None) -> None:
        self.cfg = cfg or PredictionCfg()

    def predict(self, features: dict[str, Any]) -> Prediction:
        horizon = int(features.get("horizon_days", self.cfg.horizon_days))
        if horizon not in SUPPORTED_PREDICTION_HORIZONS:
            raise UnsupportedPredictionHorizon(horizon)
        coeffs = self.cfg.coeffs
        z = self.cfg.bias
        drivers: list[str] = []
        for key, coef in coeffs.items():
            val = float(features.get(key, 0) or 0)
            # 标准化：分数类中心化到 50
            if key in (
                "score",
                "trend",
                "momentum",
                "volume_price",
                "breakout",
                "m_score",
                "pattern",
            ):
                centered = val - 50.0
                z += coef * centered
                if centered > 10:
                    drivers.append(f"{key}+")
                elif centered < -10:
                    drivers.append(f"{key}-")
            else:
                z += coef * val
                if key == "main_flow_streak" and val >= 3:
                    drivers.append("主力连续流入")
                if key == "weekly_align" and val > 0:
                    drivers.append("周线共振")

        prob = round(_sigmoid(z), 4)
        if prob >= 0.58:
            direction = "看多"
        elif prob <= 0.42:
            direction = "看空"
        else:
            direction = "中性"

        # 置信度：远离 0.5 且驱动多
        conf = round(min(0.95, abs(prob - 0.5) * 2 * 0.7 + min(0.3, len(drivers) * 0.05)), 3)
        # 友好驱动名
        name_map = {
            "score+": "综合分偏强",
            "score-": "综合分偏弱",
            "trend+": "趋势多头",
            "trend-": "趋势偏空",
            "momentum+": "动量质量较好",
            "momentum-": "动量质量偏弱",
            "volume_price+": "量价配合",
            "volume_price-": "量价不佳",
            "breakout+": "突破/持仓偏多",
            "breakout-": "突破偏空",
            "m_score+": "大盘环境偏多",
            "m_score-": "大盘环境偏空",
        }
        nice = [name_map.get(d, d) for d in drivers]
        # 去重保序
        seen = set()
        nice_u = []
        for d in nice:
            if d not in seen:
                seen.add(d)
                nice_u.append(d)

        return Prediction(
            direction=direction,
            horizon_days=horizon,
            prob_up=prob,
            confidence=conf,
            drivers=nice_u[:6],
            model=self.name,
            tilt=prob,
        )
