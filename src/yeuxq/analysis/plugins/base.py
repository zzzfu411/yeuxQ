"""ML / 预测插件协议。"""

from __future__ import annotations

from typing import Any, Protocol

from yeuxq.domain.models import Prediction


class PredictorProtocol(Protocol):
    name: str

    def predict(self, features: dict[str, Any]) -> Prediction:
        """根据特征字典输出预测。"""
        ...
