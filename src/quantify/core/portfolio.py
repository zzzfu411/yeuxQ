"""Portfolio: tracks cash, positions, and net equity over time.

Key A-share invariant: T+1 means stock bought today cannot be sold today.
We model this with two counters per position:
    - total_qty:     all shares held
    - available_qty: shares eligible to sell now (= total_qty - bought_today)

`on_new_day` is called at the start of each trading day; it moves all bought_today
shares into available_qty, implementing the T+1 release.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from quantify.core.event import Direction, FillEvent


@dataclass(slots=True)
class Position:
    symbol: str
    total_qty: int = 0          # 总持仓
    available_qty: int = 0      # 可卖数量(T+1 之后才进入此池)
    avg_cost: float = 0.0       # 加权平均成本(用于浮盈亏与会计)
    bought_today: int = 0       # 今日买入量,日终结算前不计入 available_qty

    def market_value(self, price: float) -> float:
        return self.total_qty * price

    def unrealized_pnl(self, price: float) -> float:
        return (price - self.avg_cost) * self.total_qty


@dataclass
class Portfolio:
    initial_cash: float
    cash: float = field(init=False)
    positions: dict[str, Position] = field(default_factory=dict)
    # 每日净值历史:[(date, equity), ...] —— 由 backtest 引擎在每个 bar 后追加
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)
    # 每笔成交日志,用于分析与回报输出
    trade_log: list[FillEvent] = field(default_factory=list)
    # 跟踪当前日期,用于检测跨日做 T+1 释放
    _current_day: date | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.cash = self.initial_cash

    # ----- T+1 日终结算 -----
    def on_new_day(self, day: date) -> None:
        """新交易日开始时调用:将昨日及之前买入的股票全部释放为可卖。

        A 股 T+1:今日买入次日可卖,所以新一天到来时把 bought_today 清零并入 available。
        """
        if self._current_day is not None and day != self._current_day:
            for pos in self.positions.values():
                pos.available_qty = pos.total_qty
                pos.bought_today = 0
        self._current_day = day

    # ----- 应用成交 -----
    def apply_fill(self, fill: FillEvent) -> None:
        """根据成交回报更新持仓与现金。

        买入:cash 减少 (gross + 佣金),持仓增加,加权平均成本上移
        卖出:cash 增加 (gross - 佣金 - 印花税),持仓减少
        """
        pos = self.positions.setdefault(fill.symbol, Position(symbol=fill.symbol))

        if fill.direction == Direction.LONG:
            new_total = pos.total_qty + fill.quantity
            # 新加权平均成本 = (旧持仓×旧成本 + 新买入金额) / 新总量
            # 用 gross_value 而非 total_cost,佣金已从 cash 扣减,不计入成本
            pos.avg_cost = (
                (pos.total_qty * pos.avg_cost + fill.gross_value) / new_total
                if new_total > 0
                else 0.0
            )
            pos.total_qty = new_total
            pos.bought_today += fill.quantity  # T+1:今日买入不入 available
            self.cash -= fill.total_cost

        elif fill.direction in (Direction.SHORT, Direction.EXIT):
            if fill.quantity > pos.available_qty:
                raise ValueError(
                    f"Sell {fill.quantity} > available {pos.available_qty} for {fill.symbol} "
                    f"(T+1 may be blocking)"
                )
            pos.total_qty -= fill.quantity
            pos.available_qty -= fill.quantity
            if pos.total_qty == 0:
                pos.avg_cost = 0.0
            # 卖出:收回现金 - 佣金 - 印花税
            self.cash += fill.gross_value - fill.commission - fill.tax

        self.trade_log.append(fill)

    # ----- 净值计算 -----
    def total_equity(self, prices: dict[str, float]) -> float:
        """总净值 = 现金 + 所有持仓按最新价的市值。

        prices 是 {symbol: latest_close};若某持仓在 prices 中缺失,按成本价估值(防 KeyError)。
        """
        mv = 0.0
        for sym, pos in self.positions.items():
            px = prices.get(sym, pos.avg_cost)
            mv += pos.market_value(px)
        return self.cash + mv

    def record_equity(self, timestamp: datetime, prices: dict[str, float]) -> None:
        self.equity_curve.append((timestamp, self.total_equity(prices)))
