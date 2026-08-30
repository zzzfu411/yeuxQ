"""大单 / 分笔 / 五档 / 大宗交易（公开源 best-effort）。

说明：
- 大单：由分笔成交按金额阈值过滤（非券商 L2 逐笔原始流）
- 五档：新浪公开行情（有延迟，非 Level-2 十档）
- 大宗交易：东财数据中心（A 股场外大额成交，常被误称为「暗盘」）
- 真·暗盘（港股 IPO 暗盘 / 海外 dark pool）：公开源通常不可用，接口返回明确说明
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from yeuxq.providers.base import is_etf, sina_symbol, symbol_to_secid, symbol_to_tencent, to_float
from yeuxq.providers.http_client import HttpClient
from yeuxq.settings import DataCfg
from yeuxq.storage.cache import MemoryCache

log = logging.getLogger("yeuxq.orderflow")

EM_UT = "fa5fd1943c7b386f172d6893dbfba10b"

# 默认金额阈值（元）——可按市值股调整
DEFAULT_LARGE = 200_000  # 大单下限（低价股）
DEFAULT_SUPER = 1_000_000  # 超大单下限


def adaptive_thresholds(price: float, etf: bool = False) -> tuple[float, float]:
    """按股价自适应：高价股用手数门槛，低价股用金额下限。

    大单 ≈ max(20万, 15手金额)；超大单 ≈ max(100万, 50手金额)。
    茅台 ~1343 → 大单约 201 万 / 超大单约 671 万，避免全日几乎都是「大单」。
    """
    if price <= 0:
        return float(DEFAULT_LARGE), float(DEFAULT_SUPER)
    lot_amt = price * (1.0 if etf else 100.0)
    large = max(float(DEFAULT_LARGE), lot_amt * 15.0)
    super_amt = max(float(DEFAULT_SUPER), lot_amt * 50.0)
    if super_amt < large * 1.5:
        super_amt = large * 2.5
    return round(large, 2), round(super_amt, 2)


def _lot_multiplier(symbol: str) -> int:
    """成交量单位：A 股 details 多为「手」→ *100 股；ETF 多为份。"""
    return 1 if is_etf(symbol) else 100


class OrderFlowProvider:
    def __init__(self, cfg: DataCfg, cache: MemoryCache, http: Optional[HttpClient] = None) -> None:
        self.cfg = cfg
        self.cache = cache
        self.http = http or HttpClient(cfg)
        self._owns_http = http is None

    def close(self) -> None:
        if self._owns_http:
            self.http.close()

    # ---------------- 分笔成交 ----------------
    def fetch_ticks(self, symbol: str, limit: int = 5000) -> Dict[str, Any]:
        """获取分笔。缓存全日完整列表，limit 仅影响返回切片。"""
        symbol = symbol.strip()
        cache_key = f"ticks:full:{symbol}"
        cached = self.cache.get(cache_key, self.cfg.quote_ttl_seconds)
        if cached is None:
            secid = symbol_to_secid(symbol)
            params = {
                "secid": secid,
                "fields1": "f1,f2,f3,f4",
                "fields2": "f51,f52,f53,f54,f55",
                "pos": "0",
                "ut": EM_UT,
            }
            data = self.http.get_json(
                "",
                params=params,
                host_pool=self.cfg.quote_hosts,
                path="/api/qt/stock/details/get",
            )
            raw_details = []
            pre_price = 0.0
            name_code = symbol
            if data and data.get("data"):
                d = data["data"]
                raw_details = d.get("details") or []
                pre_price = to_float(d.get("prePrice")) or 0.0
                name_code = d.get("code") or symbol

            mult = _lot_multiplier(symbol)
            ticks: List[Dict[str, Any]] = []
            for line in raw_details:
                # time,price,vol,?,bs
                parts = str(line).split(",")
                if len(parts) < 3:
                    continue
                t = parts[0]
                price = to_float(parts[1]) or 0.0
                vol_hand = to_float(parts[2]) or 0.0  # 手 or 份
                bs_code = int(to_float(parts[4]) or 0) if len(parts) >= 5 else 0
                shares = vol_hand * mult
                amount = price * shares
                side = self._map_bs(bs_code)
                ticks.append(
                    {
                        "time": t,
                        "price": price,
                        "volume_hand": vol_hand,
                        "shares": shares,
                        "amount": round(amount, 2),
                        "side": side,
                        "bs_code": bs_code,
                    }
                )
            cached = {
                "symbol": symbol,
                "code": name_code,
                "pre_price": pre_price,
                "count": len(ticks),
                "ticks": ticks,
                "source": "eastmoney_details",
                "note": "分笔成交公开接口，有延迟；非交易所 Level-2 原始逐笔",
            }
            self.cache.set(cache_key, cached)

        # 返回副本并按 limit 截最新
        full_ticks = cached.get("ticks") or []
        out_ticks = full_ticks[-limit:] if limit and len(full_ticks) > limit else full_ticks
        return {
            **cached,
            "count": len(out_ticks),
            "total_count": len(full_ticks),
            "ticks": out_ticks,
        }

    @staticmethod
    def _map_bs(code: int) -> str:
        # 东财常见：1 卖盘/外盘主动买方向混用，以经验映射
        # 实际：1=下跌方向成交偏卖，2=上涨方向成交偏买，4=竞价/平
        # 不同文档不一致；结合涨跌更稳，这里按 code 给出标签
        if code == 2:
            return "买盘"
        if code == 1:
            return "卖盘"
        if code == 4:
            return "中性"
        return "未知"

    def fetch_large_orders(
        self,
        symbol: str,
        large_amount: float = DEFAULT_LARGE,
        super_amount: float = DEFAULT_SUPER,
        limit: int = 200,
    ) -> Dict[str, Any]:
        """从分笔中过滤大单/超大单。"""
        tick_data = self.fetch_ticks(symbol, limit=8000)
        ticks = tick_data.get("ticks") or []
        last_px = 0.0
        if ticks:
            last_px = float(ticks[-1].get("price") or 0)
        auto_l, auto_s = adaptive_thresholds(last_px, is_etf(symbol))
        # 调用方仍传默认 20万/100万时，改用自适应
        if abs(large_amount - DEFAULT_LARGE) < 1 and abs(super_amount - DEFAULT_SUPER) < 1:
            large_amount, super_amount = auto_l, auto_s
        large: List[dict] = []
        super_large: List[dict] = []
        buy_amt = sell_amt = mid_amt = 0.0
        buy_n = sell_n = 0

        for t in ticks:
            amt = t.get("amount") or 0
            side = t.get("side")
            row = {**t, "tier": "超大单" if amt >= super_amount else "大单"}
            if amt >= super_amount:
                super_large.append(row)
                large.append(row)
            elif amt >= large_amount:
                large.append(row)
            if side == "买盘":
                buy_amt += amt
                buy_n += 1
            elif side == "卖盘":
                sell_amt += amt
                sell_n += 1
            else:
                mid_amt += amt

        # 最新在前
        large_sorted = list(reversed(large))[:limit]
        super_sorted = list(reversed(super_large))[:limit]

        net_large = sum(
            (x["amount"] if x["side"] == "买盘" else -x["amount"] if x["side"] == "卖盘" else 0)
            for x in large
        )

        return {
            "symbol": symbol,
            "thresholds": {
                "large": large_amount,
                "super": super_amount,
                "adaptive": True,
                "ref_price": last_px,
            },
            "summary": {
                "tick_count": len(ticks),
                "large_count": len(large),
                "super_count": len(super_large),
                "buy_ticks": buy_n,
                "sell_ticks": sell_n,
                "buy_amount": round(buy_amt, 2),
                "sell_amount": round(sell_amt, 2),
                "neutral_amount": round(mid_amt, 2),
                "large_net_amount": round(net_large, 2),
                "large_buy_amount": round(
                    sum(x["amount"] for x in large if x["side"] == "买盘"), 2
                ),
                "large_sell_amount": round(
                    sum(x["amount"] for x in large if x["side"] == "卖盘"), 2
                ),
            },
            "large_orders": large_sorted,
            "super_orders": super_sorted,
            "source": tick_data.get("source"),
            "note": (
                f"按成交额过滤：大单≥{large_amount / 1e4:.0f}万，超大单≥{super_amount / 1e4:.0f}万。"
                "由公开分笔推算，非券商 L2 委托队列。"
            ),
        }

    # ---------------- 五档盘口 ----------------
    def fetch_order_book(self, symbol: str) -> Dict[str, Any]:
        """新浪五档买卖盘。"""
        symbol = symbol.strip()
        cache_key = f"ob:{symbol}"
        cached = self.cache.get(cache_key, self.cfg.quote_ttl_seconds)
        if cached is not None:
            return cached

        sy = sina_symbol(symbol)
        url = f"https://hq.sinajs.cn/list={sy}"
        text = None
        try:
            with httpx.Client(timeout=self.cfg.request_timeout, trust_env=False) as client:
                r = client.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Referer": "https://finance.sina.com.cn",
                    },
                )
                text = r.text
        except Exception as e:
            log.warning("sina order book fail: %s", e)
            # tencent fallback
            return self._order_book_tencent(symbol)

        m = re.search(r'="([^"]*)"', text or "")
        if not m or not m.group(1):
            return self._order_book_tencent(symbol)
        parts = m.group(1).split(",")
        if len(parts) < 32:
            return {"symbol": symbol, "error": "五档数据不完整", "bids": [], "asks": []}

        name = parts[0]
        price = to_float(parts[3]) or 0
        bids = []
        asks = []
        # 10..19 bid vol/price pairs; 20..29 ask
        for i in range(5):
            bv = to_float(parts[10 + i * 2]) or 0
            bp = to_float(parts[11 + i * 2]) or 0
            av = to_float(parts[20 + i * 2]) or 0
            ap = to_float(parts[21 + i * 2]) or 0
            # 新浪量单位：股
            bids.append(
                {
                    "level": i + 1,
                    "price": bp,
                    "volume": bv,
                    "volume_hand": round(bv / 100, 2) if not is_etf(symbol) else bv,
                }
            )
            asks.append(
                {
                    "level": i + 1,
                    "price": ap,
                    "volume": av,
                    "volume_hand": round(av / 100, 2) if not is_etf(symbol) else av,
                }
            )

        result = {
            "symbol": symbol,
            "name": name,
            "price": price,
            "pre_close": to_float(parts[2]),
            "open": to_float(parts[1]),
            "high": to_float(parts[4]),
            "low": to_float(parts[5]),
            "bids": bids,
            "asks": asks,
            "datetime": f"{parts[30]} {parts[31]}" if len(parts) > 31 else "",
            "source": "sina_l1_5",
            "note": "公开五档（L1），有延迟；非 Level-2 十档/逐笔委托",
        }
        self.cache.set(cache_key, result)
        return result

    def _order_book_tencent(self, symbol: str) -> Dict[str, Any]:
        tc = symbol_to_tencent(symbol)
        try:
            with httpx.Client(timeout=self.cfg.request_timeout, trust_env=False) as client:
                r = client.get(
                    f"https://qt.gtimg.cn/q={tc}",
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                text = r.text
        except Exception as e:
            return {"symbol": symbol, "error": f"五档获取失败: {e}", "bids": [], "asks": []}
        # v_sh600519="1~name~code~price~..."
        m = re.search(r'="([^"]*)"', text or "")
        if not m:
            return {"symbol": symbol, "error": "腾讯五档为空", "bids": [], "asks": []}
        p = m.group(1).split("~")
        # tencent: 9-18 roughly bid/ask pairs in some versions — fragile
        # Documented: 9 price, 10 bid vol total?, ... use fields carefully
        # Common: 9=current, 19-28 = five档 mixed — skip if uncertain
        return {
            "symbol": symbol,
            "name": p[1] if len(p) > 1 else "",
            "price": to_float(p[3]) if len(p) > 3 else None,
            "bids": [],
            "asks": [],
            "source": "tencent_partial",
            "note": "新浪五档失败，腾讯回退仅有最新价（字段不稳）",
            "raw_hint": p[3:10] if len(p) > 10 else p,
        }

    # ---------------- 大宗交易（A股「类暗盘」公开数据） ----------------
    def fetch_block_trades(self, symbol: str, page_size: int = 50) -> Dict[str, Any]:
        """东财大宗交易明细。"""
        symbol = symbol.strip()
        cache_key = f"block:{symbol}:{page_size}"
        cached = self.cache.get(cache_key, 60.0)
        if cached is not None:
            return cached

        params = {
            "sortColumns": "TRADE_DATE,DEAL_AMT",
            "sortTypes": "-1,-1",
            "pageSize": str(page_size),
            "pageNumber": "1",
            "reportName": "RPT_DATA_BLOCKTRADE",
            "columns": "ALL",
            "filter": f'(SECURITY_CODE="{symbol}")',
            "source": "WEB",
            "client": "WEB",
        }
        rows: List[dict] = []
        try:
            with httpx.Client(timeout=self.cfg.request_timeout, trust_env=False) as client:
                r = client.get(
                    "https://datacenter-web.eastmoney.com/api/data/v1/get",
                    params=params,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Referer": "https://data.eastmoney.com/dzjy/",
                    },
                )
                body = r.json()
                data = ((body or {}).get("result") or {}).get("data") or []
                for item in data:
                    rows.append(
                        {
                            "date": str(item.get("TRADE_DATE") or "")[:10],
                            "price": to_float(item.get("DEAL_PRICE")),
                            "volume": to_float(item.get("DEAL_VOLUME")),  # 股?
                            "amount": to_float(item.get("DEAL_AMT")),
                            "premium_ratio": to_float(item.get("PREMIUM_RATIO")),
                            "buyer": item.get("BUYER_NAME") or "",
                            "seller": item.get("SELLER_NAME") or "",
                            "close_price": to_float(item.get("CLOSE_PRICE")),
                            "change_rate": to_float(item.get("CHANGE_RATE")),
                            "name": item.get("SECURITY_NAME_ABBR") or "",
                        }
                    )
        except Exception as e:
            log.warning("block trade fail: %s", e)
            return {
                "symbol": symbol,
                "error": str(e),
                "trades": [],
                "note": "大宗交易拉取失败",
            }

        total_amt = sum((x.get("amount") or 0) for x in rows)
        result = {
            "symbol": symbol,
            "count": len(rows),
            "total_amount": total_amt,
            "trades": rows,
            "source": "eastmoney_blocktrade",
            "note": (
                "大宗交易 = A 股盘后/协议大额成交（公开披露）。"
                "这是零售语境里最接近「场外大单/类暗盘」的公开数据；"
                "**不是**港股 IPO 暗盘，也不是海外 Dark Pool。"
            ),
            "dark_pool_available": False,
            "dark_pool_reason": "A 股无公开 dark pool 数据馈送；港股暗盘需独立行情源且仅覆盖未上市新股。",
        }
        self.cache.set(cache_key, result)
        return result

    def fetch_dark_pool_status(self, symbol: str) -> Dict[str, Any]:
        """明确返回暗盘不可用 + 给出大宗替代。"""
        block = self.fetch_block_trades(symbol, page_size=20)
        return {
            "symbol": symbol,
            "dark_pool_supported": False,
            "message": (
                "无法提供真·暗盘（Dark Pool / 港股 IPO 暗盘）实时数据："
                "免费公开源与当前 A 股接口均不包含。"
            ),
            "alternatives": {
                "block_trades": "大宗交易（已实现）——机构协议大额成交",
                "large_orders": "分笔大单过滤（已实现）——竞价市场大额成交",
                "aggregated_flow": "东财超大单/大单净流入汇总（已有）",
            },
            "block_trades_preview": block.get("trades", [])[:5],
            "block_trades_count": block.get("count", 0),
        }

    # ---------------- 聚合总览 ----------------
    def fetch_overview(
        self,
        symbol: str,
        large_amount: float = DEFAULT_LARGE,
        super_amount: float = DEFAULT_SUPER,
    ) -> Dict[str, Any]:
        large = self.fetch_large_orders(symbol, large_amount, super_amount, limit=50)
        book = self.fetch_order_book(symbol)
        block = self.fetch_block_trades(symbol, page_size=30)
        dark = self.fetch_dark_pool_status(symbol)
        return {
            "symbol": symbol,
            "order_book": book,
            "large_orders": large,
            "block_trades": block,
            "dark_pool": dark,
            "capabilities": {
                "ticks": True,
                "large_order_filter": True,
                "order_book_l1_5": True,
                "block_trades": True,
                "dark_pool": False,
                "level2_10": False,
            },
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
