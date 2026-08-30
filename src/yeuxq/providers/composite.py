"""多源行情 composite：腾讯/新浪/东财 fallback + 缓存 + SQLite。"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

from yeuxq.domain.models import FundFlow, Kline, MinuteData, MinuteFlow, Quote
from yeuxq.providers.base import (
    is_etf,
    sina_symbol,
    symbol_to_secid,
    symbol_to_tencent,
    to_float,
)
from yeuxq.providers.http_client import HttpClient
from yeuxq.settings import Settings
from yeuxq.storage.cache import MemoryCache
from yeuxq.storage.kline_store import KlineStore

log = logging.getLogger("yeuxq.composite")

EM_UT = "fa5fd1943c7b386f172d6893dbfba10b"

_INDEX_IDS: dict[str, tuple[str, str]] = {
    "000001": ("sh000001", "1.000001"),
    "SH.000001": ("sh000001", "1.000001"),
    "SH000001": ("sh000001", "1.000001"),
    "000300": ("sh000300", "1.000300"),
    "SH.000300": ("sh000300", "1.000300"),
    "SH000300": ("sh000300", "1.000300"),
    "399001": ("sz399001", "0.399001"),
    "SZ.399001": ("sz399001", "0.399001"),
    "SZ399001": ("sz399001", "0.399001"),
    "399006": ("sz399006", "0.399006"),
    "SZ.399006": ("sz399006", "0.399006"),
    "SZ399006": ("sz399006", "0.399006"),
}


def _index_provider_ids(index_code: str) -> tuple[str, str]:
    code = index_code.strip().upper()
    try:
        return _INDEX_IDS[code]
    except KeyError as exc:
        raise ValueError(f"unsupported index code: {index_code}") from exc


class CompositeMarketData:
    def __init__(self, settings: Settings, cache: MemoryCache, store: KlineStore) -> None:
        self.settings = settings
        self.cfg = settings.data
        self.cache = cache
        self.store = store
        self.http = HttpClient(self.cfg)

    def close(self) -> None:
        self.http.close()

    def diagnostic_cursor(self) -> dict[str, int]:
        """Snapshot bounded provider/cache ledgers for request-scoped diagnostics."""
        http_cursor = getattr(self.http, "diagnostic_cursor", None)
        cache_cursor = getattr(self.cache, "diagnostic_cursor", None)
        return {
            "provider": int(http_cursor()) if callable(http_cursor) else 0,
            "cache": int(cache_cursor()) if callable(cache_cursor) else 0,
        }

    def diagnostics(
        self,
        *,
        since: Optional[dict[str, int]] = None,
        limit: int = 8,
    ) -> dict[str, list[dict]]:
        """Return secret-safe diagnostics without payloads, URLs or cache keys."""
        cursor = since or {}
        bounded = max(1, min(int(limit), 16))
        http_diagnostics = getattr(self.http, "diagnostics", None)
        cache_diagnostics = getattr(self.cache, "diagnostics", None)
        providers = (
            http_diagnostics(since=int(cursor.get("provider", 0)), limit=bounded)
            if callable(http_diagnostics)
            else []
        )
        caches = (
            cache_diagnostics(since=int(cursor.get("cache", 0)), limit=bounded)
            if callable(cache_diagnostics)
            else []
        )
        return {"providers": providers, "cache": caches}

    # ---------------- K 线 ----------------
    def fetch_kline(self, symbol: str, count: int = 250, period: str = "day") -> List[Kline]:
        symbol = symbol.strip()
        period = period if period in ("day", "week", "month") else "day"
        cache_key = f"kline:{symbol}:{count}:{period}"
        cached = self.cache.get(cache_key, self.cfg.memory_ttl_seconds)
        if cached is not None:
            return cached

        # 本地库命中且足够长：仍可返回（盘中会与网络结果合并刷新）
        local = self.store.load(symbol, period, count)
        klines = self._fetch_kline_tencent(symbol, count, period)
        if not klines:
            klines = self._fetch_kline_sina(symbol, count, period)
        if not klines:
            klines = self._fetch_kline_eastmoney(symbol, count, period)
        if not klines and local:
            log.info("network kline failed, use local cache %s", symbol)
            klines = local

        if klines:
            klines = self._sanitize(klines)
            if period == "day":
                self._enrich_amount_turnover(symbol, count, klines)
            self.store.save_many(symbol, period, klines)
            self.cache.set(cache_key, klines)
        return klines or []

    def _sanitize(self, klines: List[Kline]) -> List[Kline]:
        out: List[Kline] = []
        for k in klines:
            if k.close > 0 and k.high > 0 and k.low > 0 and k.open > 0:
                if k.high >= k.low and k.high >= k.close and k.high >= k.open:
                    if k.low <= k.close and k.low <= k.open and k.close < 100000:
                        out.append(k)
        return out

    def _fetch_kline_tencent(self, symbol: str, count: int, period: str) -> List[Kline]:
        tc = symbol_to_tencent(symbol)
        params = {"param": f"{tc},{period},,,{count},qfq"}
        data = self.http.get_json(self.cfg.tencent_kline, params=params)
        if not data or data.get("code") != 0:
            return []
        stock = data.get("data", {}).get(tc, {})
        key = f"qfq{period}" if period in ("day", "week", "month") else "qfqday"
        rows = stock.get(key) or stock.get(period) or stock.get("day") or []
        klines: List[Kline] = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                continue
            vol = to_float(row[5]) or 0.0
            k = Kline(
                date=str(row[0]),
                open=float(row[1]),
                close=float(row[2]),
                high=float(row[3]),
                low=float(row[4]),
                volume=vol,
            )
            if klines and klines[-1].close:
                k.pct = round((k.close - klines[-1].close) / klines[-1].close * 100, 2)
            klines.append(k)
        return klines

    def _fetch_kline_sina(self, symbol: str, count: int, period: str) -> List[Kline]:
        scale_map = {"day": "240", "week": "1200", "month": "7200"}
        params = {
            "symbol": sina_symbol(symbol),
            "scale": scale_map.get(period, "240"),
            "ma": "no",
            "datalen": str(count),
        }
        data = self.http.get_json(self.cfg.sina_kline, params=params)
        if not isinstance(data, list):
            return []
        klines: List[Kline] = []
        for item in data:
            o = to_float(item.get("open"))
            c = to_float(item.get("close"))
            h = to_float(item.get("high"))
            lo = to_float(item.get("low"))
            v = to_float(item.get("volume"))
            d = item.get("day", "")
            if None in (o, c, h, lo) or not d:
                continue
            vol = (v or 0.0) if is_etf(symbol) else ((v or 0.0) / 100.0)
            k = Kline(date=d, open=o, close=c, high=h, low=lo, volume=vol)
            if klines and klines[-1].close:
                k.pct = round((k.close - klines[-1].close) / klines[-1].close * 100, 2)
            klines.append(k)
        return klines

    def _fetch_kline_eastmoney(self, symbol: str, count: int, period: str) -> List[Kline]:
        return self._fetch_kline_eastmoney_secid(symbol_to_secid(symbol), count, period)

    def _fetch_kline_eastmoney_secid(self, secid: str, count: int, period: str) -> List[Kline]:
        klt = {"day": "101", "week": "102", "month": "103"}.get(period, "101")
        params = {
            "secid": secid,
            "ut": EM_UT,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": klt,
            "fqt": "1",
            "lmt": str(count),
            "end": "20500101",
        }
        data = self.http.get_json(
            "", params=params, host_pool=self.cfg.his_hosts, path="/api/qt/stock/kline/get"
        )
        if not data or not data.get("data") or not data["data"].get("klines"):
            return []
        klines: List[Kline] = []
        for line in data["data"]["klines"]:
            parts = line.split(",")
            if len(parts) < 7:
                continue
            k = Kline(
                date=parts[0],
                open=float(parts[1]),
                close=float(parts[2]),
                high=float(parts[3]),
                low=float(parts[4]),
                volume=float(parts[5]),
                amount=to_float(parts[6]) or 0.0,
            )
            if len(parts) >= 11:
                k.turnover = to_float(parts[10]) or 0.0
            if klines and klines[-1].close:
                k.pct = round((k.close - klines[-1].close) / klines[-1].close * 100, 2)
            klines.append(k)
        return klines

    def _enrich_amount_turnover(self, symbol: str, count: int, klines: List[Kline]) -> None:
        params = {
            "secid": symbol_to_secid(symbol),
            "ut": EM_UT,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101",
            "fqt": "0",
            "lmt": str(min(count + 60, 500)),
            "end": "20500101",
        }
        data = self.http.get_json(
            "", params=params, host_pool=self.cfg.his_hosts, path="/api/qt/stock/kline/get"
        )
        if not data or not data.get("data") or not data["data"].get("klines"):
            return
        em_map: dict[str, tuple[float, float]] = {}
        for line in data["data"]["klines"]:
            parts = line.split(",")
            if len(parts) >= 11:
                em_map[parts[0]] = (to_float(parts[6]) or 0.0, to_float(parts[10]) or 0.0)
        for k in klines:
            if k.date in em_map:
                amt, turn = em_map[k.date]
                if amt:
                    k.amount = amt
                if turn:
                    k.turnover = turn

    # ---------------- 行情 ----------------
    def fetch_quote(self, symbol: str) -> Optional[Quote]:
        symbol = symbol.strip()
        cache_key = f"quote:{symbol}"
        cached = self.cache.get(cache_key, self.cfg.quote_ttl_seconds)
        if cached is not None:
            return cached
        params = {
            "secid": symbol_to_secid(symbol),
            "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f169,f170,f168",
            "fltt": "2",
            "invt": "2",
            "ut": EM_UT,
        }
        data = self.http.get_json(
            "", params=params, host_pool=self.cfg.quote_hosts, path="/api/qt/stock/get"
        )
        if not data or not data.get("data"):
            return None
        d = data["data"]
        q = Quote(
            symbol=symbol,
            name=d.get("f58", ""),
            price=to_float(d.get("f43")) or 0,
            pct=to_float(d.get("f170")) or 0,
            change=to_float(d.get("f169")) or 0,
            high=to_float(d.get("f44")) or 0,
            low=to_float(d.get("f45")) or 0,
            open=to_float(d.get("f46")) or 0,
            pre_close=to_float(d.get("f60")) or 0,
            volume=to_float(d.get("f47")) or 0,
            amount=to_float(d.get("f48")) or 0,
            turnover=to_float(d.get("f168")) or 0,
        )
        self.cache.set(cache_key, q)
        return q

    # ---------------- 资金流 ----------------
    @staticmethod
    def _parse_day_flows(data: object) -> List[FundFlow]:
        flows: List[FundFlow] = []
        if not isinstance(data, dict):
            return flows
        raw = ((data.get("data") or {}) if data.get("data") else {}) or {}
        klines = raw.get("klines") if isinstance(raw, dict) else None
        if not klines:
            return flows
        for line in klines:
            parts = str(line).split(",")
            if len(parts) < 6:
                continue
            try:
                flows.append(
                    FundFlow(
                        date=parts[0],
                        main_net=float(parts[1]),
                        small_net=float(parts[2]),
                        medium_net=float(parts[3]),
                        large_net=float(parts[4]),
                        super_large_net=float(parts[5]),
                        main_pct=float(parts[6]) if len(parts) > 6 and parts[6] else 0.0,
                    )
                )
            except (TypeError, ValueError):
                continue
        return flows

    def fetch_fund_flow(self, symbol: str, days: int = 30) -> List[FundFlow]:
        symbol = symbol.strip()
        days = max(int(days or 30), 5)
        cache_key = f"flow:{symbol}:{days}"
        cached = self.cache.get(cache_key, self.cfg.memory_ttl_seconds)
        if cached is not None and len(cached) >= 3:
            return cached
        params = {
            "lmt": str(days),
            "klt": "101",
            "secid": symbol_to_secid(symbol),
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
            "ut": EM_UT,
        }
        # push2delay 历史资金流经常只给当天；push2his 直连常被掐。
        # 按「能出序列的源」优先，单日结果不当成功。
        hosts = list(self.cfg.his_hosts)
        preferred = [h for h in hosts if "push2test" in h or "push2his" in h]
        rest = [h for h in hosts if h not in preferred]
        ordered = preferred + rest
        best: List[FundFlow] = []
        path = "/api/qt/stock/fflow/daykline/get"
        for host in ordered:
            data = self.http.get_json("", params=params, host_pool=[host], path=path)
            flows = self._parse_day_flows(data)
            if len(flows) > len(best):
                best = flows
            if len(best) >= min(days, 10):
                break
        if len(best) >= 3:
            self.cache.set(cache_key, best)
        return best

    def fetch_realtime_flow(self, symbol: str) -> List[MinuteFlow]:
        symbol = symbol.strip()
        cache_key = f"rtflow:{symbol}"
        cached = self.cache.get(cache_key, self.cfg.quote_ttl_seconds)
        if cached is not None:
            return cached
        params = {
            "klt": "1",
            "secid": symbol_to_secid(symbol),
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
            "ut": EM_UT,
            "lmt": "300",
        }
        data = self.http.get_json(
            "",
            params=params,
            host_pool=self.cfg.rt_flow_hosts,
            path="/api/qt/stock/fflow/kline/get",
        )
        flows: List[MinuteFlow] = []
        if data and data.get("data") and data["data"].get("klines"):
            for line in data["data"]["klines"]:
                parts = line.split(",")
                if len(parts) >= 6:
                    t = parts[0].split(" ")[-1] if " " in parts[0] else parts[0]
                    flows.append(
                        MinuteFlow(
                            time=t,
                            main_net=to_float(parts[1]) or 0.0,
                            small_net=to_float(parts[2]) or 0.0,
                            medium_net=to_float(parts[3]) or 0.0,
                            large_net=to_float(parts[4]) or 0.0,
                            super_large_net=to_float(parts[5]) or 0.0,
                        )
                    )
        self.cache.set(cache_key, flows)
        return flows

    # ---------------- 分时 ----------------
    def fetch_minute(self, symbol: str) -> Optional[MinuteData]:
        symbol = symbol.strip()
        cache_key = f"minute:{symbol}"
        cached = self.cache.get(cache_key, self.cfg.quote_ttl_seconds)
        if cached is not None:
            return cached
        params = {
            "secid": symbol_to_secid(symbol),
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            "ut": EM_UT,
            "ndays": "1",
            "iscr": "0",
            "iscca": "0",
        }
        data = self.http.get_json(
            "", params=params, host_pool=self.cfg.quote_hosts, path="/api/qt/stock/trends2/get"
        )
        if not data or not data.get("data"):
            return None
        d = data["data"]
        trends = d.get("trends") or []
        times, prices, avgs, vols = [], [], [], []
        for line in trends:
            parts = line.split(",")
            if len(parts) < 6:
                continue
            t = parts[0].split(" ")[-1] if " " in parts[0] else parts[0]
            times.append(t)
            prices.append(to_float(parts[2]) or 0.0)
            avgs.append(to_float(parts[7]) if len(parts) > 7 else (to_float(parts[2]) or 0.0))
            vols.append(to_float(parts[5]) or 0.0)
        md = MinuteData(
            times=times,
            prices=prices,
            avg_prices=avgs,
            volumes=vols,
            pre_close=to_float(d.get("preClose")) or to_float(d.get("preSettlementPrice")) or 0.0,
            name=d.get("name", ""),
            high=to_float(d.get("high")) or (max(prices) if prices else 0.0),
            low=to_float(d.get("low")) or (min(prices) if prices else 0.0),
        )
        self.cache.set(cache_key, md)
        return md

    # ---------------- 搜索 ----------------
    def search_stock(self, keyword: str, count: int = 10) -> List[Dict[str, str]]:
        keyword = (keyword or "").strip()
        if not keyword:
            return []
        cache_key = f"search:{keyword}:{count}"
        cached = self.cache.get(cache_key, self.cfg.memory_ttl_seconds)
        if cached is not None:
            return cached
        if keyword.isdigit() and len(keyword) == 6:
            mkt = (
                "SH"
                if keyword.startswith(("6", "5"))
                else ("BJ" if keyword.startswith("920") else "SZ")
            )
            result = [{"code": keyword, "name": "", "market": mkt}]
            self.cache.set(cache_key, result)
            return result
        params = {"input": keyword, "type": "14", "count": str(count), "ut": EM_UT}
        query = urllib.parse.urlencode(params)
        url = f"{self.cfg.search_host}/api/suggest/get?{query}"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            log.debug("search fail: %s", e)
            return []
        items = body.get("QuotationCodeTable", {}).get("Data") or []
        results: List[Dict[str, str]] = []
        for item in items:
            code = item.get("Code", "")
            name = item.get("Name", "")
            classify = item.get("Classify", "")
            valid = (
                classify in ("AStock", "Fund")
                or (len(code) == 6 and code[0] in "036")
                or code.startswith("920")
                or (len(code) == 6 and code.startswith("5"))
            )
            if valid and len(code) == 6:
                mkt = (
                    "SH"
                    if code.startswith(("6", "5"))
                    else ("BJ" if code.startswith("920") else "SZ")
                )
                results.append({"code": code, "name": name, "market": mkt})
        results = results[:count]
        self.cache.set(cache_key, results)
        return results

    # ---------------- 指数 / 宽度 / 列表 ----------------
    def fetch_index_kline(self, index_code: str = "000001", count: int = 60) -> List[Kline]:
        tc, eastmoney_secid = _index_provider_ids(index_code)
        params = {"param": f"{tc},day,,,{count},"}
        data = self.http.get_json(self.cfg.tencent_kline, params=params)
        klines: List[Kline] = []
        if data and data.get("code") == 0:
            stock = data.get("data", {}).get(tc, {})
            rows = stock.get("day") or stock.get("qfqday") or []
            for row in rows:
                if len(row) >= 6:
                    k = Kline(
                        date=str(row[0]),
                        open=float(row[1]),
                        close=float(row[2]),
                        high=float(row[3]),
                        low=float(row[4]),
                        volume=to_float(row[5]) or 0,
                    )
                    if klines and klines[-1].close:
                        k.pct = round((k.close - klines[-1].close) / klines[-1].close * 100, 2)
                    klines.append(k)
        if klines:
            return klines
        return self._fetch_kline_eastmoney_secid(eastmoney_secid, count, "day")

    @staticmethod
    def _breadth_unavailable(reason: str, **details: object) -> dict:
        return {
            "available": False,
            "complete": False,
            "reason": reason,
            "source": "eastmoney_clist",
            **details,
        }

    def fetch_market_breadth(self) -> dict:
        cache_key = "breadth"
        cached = self.cache.get(cache_key, 60.0)
        if cached is not None:
            return cached

        page_size = 100
        expected_total: Optional[int] = None
        rows_by_symbol: dict[str, dict] = {}
        page = 1
        while True:
            params = {
                "pn": str(page),
                "pz": str(page_size),
                "po": "1",
                "np": "1",
                "fltt": "2",
                "invt": "2",
                # Stable symbol ordering avoids sampling only the top gainers.
                "fid": "f12",
                "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
                "fields": "f12,f14,f3",
                "ut": EM_UT,
            }
            data = self.http.get_json(
                "", params=params, host_pool=self.cfg.quote_hosts, path="/api/qt/clist/get"
            )
            payload = (data or {}).get("data") or {}
            rows = payload.get("diff") or []
            if isinstance(rows, dict):
                rows = list(rows.values())
            if expected_total is None:
                try:
                    expected_total = int(payload.get("total") or 0)
                except (TypeError, ValueError):
                    expected_total = 0
                if expected_total <= 0:
                    return self._breadth_unavailable("missing_universe_total")
            if not rows:
                return self._breadth_unavailable(
                    "incomplete_universe",
                    universe_total=expected_total,
                    observed_symbols=len(rows_by_symbol),
                    failed_page=page,
                )
            before = len(rows_by_symbol)
            for row in rows:
                code = str(row.get("f12") or "").strip()
                if code:
                    rows_by_symbol[code] = row

            if len(rows_by_symbol) >= expected_total:
                break
            expected_pages = (expected_total + page_size - 1) // page_size
            if page >= expected_pages or len(rows_by_symbol) == before:
                return self._breadth_unavailable(
                    "incomplete_universe",
                    universe_total=expected_total,
                    observed_symbols=len(rows_by_symbol),
                    failed_page=page,
                )
            page += 1

        up = down = flat = 0
        for row in rows_by_symbol.values():
            pct = to_float(row.get("f3"))
            if pct is None:
                continue
            if pct > 0:
                up += 1
            elif pct < 0:
                down += 1
            else:
                flat += 1
        valid_quotes = up + down + flat
        if valid_quotes < 50:
            return self._breadth_unavailable(
                "insufficient_valid_quotes",
                universe_total=expected_total,
                observed_symbols=len(rows_by_symbol),
                valid_quotes=valid_quotes,
            )
        result = {
            "available": True,
            "complete": True,
            "source": "eastmoney_clist",
            "universe": "cn_a_sh_sz_bj",
            "up": up,
            "down": down,
            "flat": flat,
            "total": valid_quotes,
            "valid_quotes": valid_quotes,
            "observed_symbols": len(rows_by_symbol),
            "universe_total": expected_total,
            "coverage_ratio": round(len(rows_by_symbol) / expected_total, 4),
            "breadth_ratio": round(up / valid_quotes, 4),
        }
        self.cache.set(cache_key, result)
        return result

    def fetch_symbols(self, limit: int = 200) -> List[Dict[str, str]]:
        """获取股票池（非全 A；分页截断）。"""
        out: List[Dict[str, str]] = []
        page = 1
        while len(out) < limit:
            params = {
                "pn": str(page),
                "pz": "100",
                "po": "1",
                "np": "1",
                "fltt": "2",
                "invt": "2",
                "fid": "f3",
                "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
                "fields": "f12,f14,f2,f3",
                "ut": EM_UT,
            }
            data = self.http.get_json(
                "", params=params, host_pool=self.cfg.quote_hosts, path="/api/qt/clist/get"
            )
            rows = ((data or {}).get("data") or {}).get("diff") or []
            if not rows:
                break
            for r in rows:
                code = str(r.get("f12", ""))
                name = str(r.get("f14", ""))
                if len(code) == 6 and "ST" not in name.upper():
                    out.append({"code": code, "name": name})
                if len(out) >= limit:
                    break
            page += 1
            if page > 20:
                break
        return out[:limit]
