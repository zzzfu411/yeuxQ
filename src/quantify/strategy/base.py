"""Strategy: the user-facing extension point.

A strategy is a stateful object that receives one MarketEvent at a time and emits
zero or more SignalEvents. The engine isolates strategies from order sizing and
broker details — strategies declare *intent* (buy/sell this symbol), risk/sizer
decides *how much*.

Subclasses must implement `on_bar`. Override `on_init`/`on_finish` for setup/teardown.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from quantify.core.bar import Bar
from quantify.core.event import SignalEvent


class Strategy(ABC):
    """Abstract base class for trading strategies.

    Lifecycle:
        on_init()           — called once at engine start, before any bars
        on_bar(bar)         — called for each new bar, returns list of SignalEvent
        on_finish()         — called once after the last bar (for cleanup/logging)
    """

    #: Human-readable name, defaults to class name
    name: str = ""

    def __init__(self, **params) -> None:
        self.name = self.name or self.__class__.__name__
        self.params = params

    def on_init(self) -> None:
        """Hook for initialization. Override if needed."""

    def on_finish(self) -> None:
        """Hook for cleanup. Override if needed."""

    @abstractmethod
    def on_bar(self, bar: Bar) -> list[SignalEvent]:
        """Called once per new bar. Return 0..N signals.

        Implementations should be deterministic and only use information up to
        and including `bar` — never look at future bars (a.k.a. look-ahead bias).
        """
