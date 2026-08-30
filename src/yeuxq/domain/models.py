"""领域模型：行情与分析结果。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Kline:
    date: str
    open: float
    close: float
    high: float
    low: float
    volume: float = 0.0
    amount: float = 0.0
    pct: float = 0.0
    turnover: float = 0.0


@dataclass
class Quote:
    symbol: str
    name: str
    price: float
    pct: float
    change: float
    high: float
    low: float
    open: float
    pre_close: float
    volume: float
    amount: float
    turnover: float = 0.0


@dataclass
class FundFlow:
    date: str
    main_net: float
    super_large_net: float
    large_net: float
    medium_net: float
    small_net: float
    main_pct: float = 0.0


@dataclass
class MinuteFlow:
    time: str
    main_net: float
    small_net: float
    medium_net: float
    large_net: float
    super_large_net: float


@dataclass
class MinuteData:
    times: list[str]
    prices: list[float]
    avg_prices: list[float]
    volumes: list[float]
    pre_close: float = 0.0
    name: str = ""
    high: float = 0.0
    low: float = 0.0


@dataclass
class TrendResult:
    direction: str
    strength: int
    stage: str
    ma_arrangement: str
    ma_scores: dict[str, int] = field(default_factory=dict)
    trendline: Optional[dict[str, Any]] = None
    signals: list[str] = field(default_factory=list)


@dataclass
class VolumePriceResult:
    pattern: str
    direction: str
    confidence: int
    volume_ratio: float
    turnover: float
    obv_trend: str
    signals: list[str] = field(default_factory=list)
    description: str = ""
    flow_features: dict[str, Any] = field(default_factory=dict)


@dataclass
class PatternResult:
    name: str
    direction: str
    confidence: int
    status: str
    target_price: Optional[float] = None
    key_levels: dict[str, float] = field(default_factory=dict)
    description: str = ""


@dataclass
class BreakoutResult:
    system: str
    signal: str
    breakout_price: float
    current_n: float
    stop_loss: float
    entry_price: Optional[float] = None
    position_units: int = 0
    exit_price: Optional[float] = None
    channel_high: float = 0.0
    channel_low: float = 0.0
    next_add_price: Optional[float] = None
    signals: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class MomentumResult:
    """动量质量七维（原 CANSLIM 简化版，避免名实不符）。"""

    c_score: int
    a_score: int
    n_score: int
    s_score: int
    l_score: int
    i_score: int
    m_score: int
    total: int
    grade: str
    signals: list[str] = field(default_factory=list)
    cup_handle: Optional[dict[str, Any]] = None
    description: str = ""


@dataclass
class TradePlan:
    action: str
    entry_price: float
    stop_loss: float
    target_price: float
    position_size: str
    holding_period: str = "中线(1-3月)"
    risk_reward_ratio: float = 0.0
    max_loss_pct: float = 5.0
    notes: str = ""
    stop_method: str = ""


@dataclass
class Prediction:
    direction: str
    horizon_days: int
    prob_up: float
    confidence: float
    drivers: list[str] = field(default_factory=list)
    model: str = "rule_v1"
    disclaimer: str = "规则倾向（未校准），不是历史胜率，不构成投资建议"
    tilt: float = 0.0


@dataclass
class SignalResult:
    action: str
    score: int
    confidence: int
    risk_level: str
    signal_strength: str
    plain_summary: str
    trade_plan: TradePlan
    module_scores: dict[str, int] = field(default_factory=dict)
    buy_signals: list[str] = field(default_factory=list)
    sell_signals: list[str] = field(default_factory=list)
    risk_warnings: list[str] = field(default_factory=list)
    key_levels: dict[str, float] = field(default_factory=dict)
    description: str = ""
    trend: Optional[TrendResult] = None
    patterns: list[PatternResult] = field(default_factory=list)
    volume_price: Optional[VolumePriceResult] = None
    breakouts: list[BreakoutResult] = field(default_factory=list)
    momentum: Optional[MomentumResult] = None
    prediction: Optional[Prediction] = None
    original_action: str = ""
    veto_reason: str = ""
    position_advice: str = ""
    risk_notes: list[str] = field(default_factory=list)
    risk_reward: float = 0.0
