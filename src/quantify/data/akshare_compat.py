"""Compatibility shim for the optional AKShare dependency."""
from __future__ import annotations

import sys
from types import ModuleType
from typing import Any


def _missing_akshare(*args: Any, **kwargs: Any) -> Any:
    raise ModuleNotFoundError(
        "akshare is not installed; install akshare to use live A-share data providers."
    )


class _AkshareShim(ModuleType):
    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        return _missing_akshare


try:
    import akshare as ak  # type: ignore[import-not-found]
except ModuleNotFoundError:
    ak = _AkshareShim("akshare")
    ak.stock_zh_a_hist = _missing_akshare  # type: ignore[attr-defined]
    ak.stock_zh_a_daily = _missing_akshare  # type: ignore[attr-defined]
    ak.stock_zh_a_spot_em = _missing_akshare  # type: ignore[attr-defined]
    ak.index_stock_cons_csindex = _missing_akshare  # type: ignore[attr-defined]
    sys.modules.setdefault("akshare", ak)
