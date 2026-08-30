"""Risk manager: converts SignalEvents into OrderEvents (or rejects them).

Responsibilities:
    1. Reject buys when max-drawdown circuit breaker is tripped.
    2. Reject buys that would breach max single-position pct.
    3. For EXIT signals, size = current holding (full close).
    4. For LONG signals, delegate to the configured Sizer.

The risk manager is the single chokepoint between strategy intent and broker
submission — every order flows through it.
"""
from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from quantify.core.event import Direction, OrderEvent, SignalEvent
from quantify.core.portfolio import Portfolio
from quantify.risk.sizer import Sizer


@dataclass(frozen=True, slots=True)
class RiskConfig:
    max_position_pct: float = 0.3   # 单标的最多占总净值的 30%
    max_drawdown_stop: float = 0.2  # 累计回撤超 20% 后停止开新仓


class RiskManager:
    def __init__(self, config: RiskConfig, sizer: Sizer) -> None:
        self.config = config
        self.sizer = sizer
        # 跟踪历史最高净值,用于回撤计算
        self._peak_equity: float = 0.0
        self._halted: bool = False

    def update_equity(self, equity: float) -> None:
        """Called after each bar by the engine; tracks peak & checks DD breaker."""
        if equity > self._peak_equity:
            self._peak_equity = equity
        if self._peak_equity > 0:
            dd = 1 - equity / self._peak_equity
            if dd >= self.config.max_drawdown_stop and not self._halted:
                self._halted = True
                logger.warning(
                    "Max drawdown breached: {:.2%} ≥ {:.2%}. Halting new long entries.",
                    dd, self.config.max_drawdown_stop,
                )

    def process(
        self,
        signal: SignalEvent,
        portfolio: Portfolio,
        ref_price: float,
        prices: dict[str, float] | None = None,
    ) -> OrderEvent | None:
        """Turn a signal into an order, or None if rejected."""
        pos = portfolio.positions.get(signal.symbol)

        # ===== EXIT: 平仓 =====
        if signal.direction in (Direction.EXIT, Direction.SHORT):
            if pos is None or pos.available_qty <= 0:
                logger.debug(
                    "EXIT signal for {} ignored: no available position (T+1 may block).",
                    signal.symbol,
                )
                return None
            return OrderEvent(
                timestamp=signal.timestamp,
                symbol=signal.symbol,
                direction=Direction.EXIT,
                quantity=pos.available_qty,
            )

        # ===== LONG: 开/加仓 =====
        if self._halted:
            logger.debug("LONG signal for {} rejected: DD breaker active.", signal.symbol)
            return None

        qty = self.sizer.size(signal.symbol, ref_price, portfolio)
        if qty <= 0:
            logger.warning(
                "LONG signal for {} sized to 0 shares (cash={:.0f}, ref_price={:.2f}). "
                "Increase initial_cash or sizer pct, or pick a lower-priced symbol.",
                signal.symbol, portfolio.cash, ref_price,
            )
            return None

        # 单标的上限:已有仓位 + 新增 ≤ 总净值 * max_position_pct
        marks = dict(prices or {})
        marks[signal.symbol] = ref_price
        equity = portfolio.total_equity(marks)
        existing_value = (pos.total_qty * ref_price) if pos else 0.0
        max_allowed_value = equity * self.config.max_position_pct
        new_value = qty * ref_price
        if existing_value + new_value > max_allowed_value:
            # 截到上限,避免完全拒绝(更友好)
            remaining = max_allowed_value - existing_value
            if remaining <= 0:
                logger.debug(
                    "LONG signal for {} rejected: position cap reached.", signal.symbol,
                )
                return None
            qty = int(remaining // ref_price)
            qty = (qty // self.sizer.lot_size) * self.sizer.lot_size  # type: ignore[attr-defined]
            if qty <= 0:
                return None

        return OrderEvent(
            timestamp=signal.timestamp,
            symbol=signal.symbol,
            direction=Direction.LONG,
            quantity=qty,
        )
