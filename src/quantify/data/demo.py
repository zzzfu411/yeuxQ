"""Shared demo-data classification helpers."""
from __future__ import annotations

from collections.abc import Iterable

DEMO_SYMBOL_PREFIX = "DEMO"


def is_demo_contaminated(symbols: Iterable[str]) -> bool:
    """Return whether any symbol identifies deterministic demo data."""
    return any(symbol.startswith(DEMO_SYMBOL_PREFIX) for symbol in symbols)


def is_mixed_demo_contaminated(symbols: Iterable[str]) -> bool:
    """Return whether demo and non-demo symbols coexist in one universe."""
    values = list(symbols)
    demo_count = sum(symbol.startswith(DEMO_SYMBOL_PREFIX) for symbol in values)
    return 0 < demo_count < len(values)
