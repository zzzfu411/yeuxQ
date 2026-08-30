"""Narrow read-only service used by the versioned advisory workbench API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yeuxq.providers.composite import CompositeMarketData
from yeuxq.services.analyze import AnalyzeService
from yeuxq.services.report_read_facade import ReportReadFacade
from yeuxq.services.serialize import kline_to_dict, quote_to_dict


@dataclass(frozen=True)
class AdvisoryWorkbenchService:
    data: CompositeMarketData
    analyze: AnalyzeService
    reports: ReportReadFacade

    def search_instruments(self, keyword: str, limit: int) -> dict[str, object]:
        rows = self.data.search_stock(keyword, count=limit)
        items: list[dict[str, str]] = []
        for row in rows[:limit]:
            code = str(row.get("code") or "").strip()
            if len(code) != 6 or not code.isascii() or not code.isdigit():
                continue
            market = str(row.get("market") or "").upper()
            if market not in {"SH", "SZ", "BJ"}:
                market = (
                    "SH"
                    if code.startswith(("5", "6"))
                    else "BJ"
                    if code.startswith("920")
                    else "SZ"
                )
            name = str(row.get("name") or "").replace("\x00", " ").strip()[:80]
            items.append({"code": code, "name": name, "market": market})
        return {"results": items}

    def watchlist_quotes(self, symbols: list[str]) -> dict[str, object]:
        items: list[dict[str, Any]] = []
        unavailable: list[str] = []
        for symbol in symbols:
            quote = self.data.fetch_quote(symbol)
            if quote is None:
                unavailable.append(symbol)
                continue
            items.append(quote_to_dict(quote))
        return {"items": items, "unavailable_symbols": unavailable}

    def market_overview(self) -> dict[str, object]:
        index = self.data.fetch_index_kline("000001", count=60)
        breadth = self.data.fetch_market_breadth()
        last = index[-1] if index else None
        previous = index[-2] if len(index) >= 2 else None
        change_pct = None
        if last is not None and previous is not None and previous.close:
            change_pct = round((last.close - previous.close) / previous.close * 100, 2)
        return {
            "index_code": "000001",
            "index_name": "上证指数",
            "last": kline_to_dict(last) if last else None,
            "change_pct": change_pct,
            "breadth": breadth,
            "klines": [kline_to_dict(item) for item in index[-60:]],
            "note": "公开行情聚合；不含暗盘/L2 逐笔",
        }

    def symbol_analysis(self, symbol: str, period: str) -> dict[str, object]:
        return self.analyze.analyze(symbol, period)

    def symbol_minute(self, symbol: str) -> dict[str, object]:
        return self.analyze.minute_snapshot(symbol)

    def list_reports(self, subject: str | None, limit: int) -> dict[str, object]:
        return {"items": self.reports.list(subject=subject, limit=limit)}

    def get_report(self, report_id: str) -> dict[str, object]:
        return self.reports.read(report_id)


__all__ = ["AdvisoryWorkbenchService"]
