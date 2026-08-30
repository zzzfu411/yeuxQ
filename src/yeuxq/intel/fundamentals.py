"""公开源基本面/财报摘要（东财，非官方）。"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from yeuxq.providers.base import symbol_to_secid, to_float

log = logging.getLogger("yeuxq.fundamentals")

EM_UT = "fa5fd1943c7b386f172d6893dbfba10b"
HOSTS = [
    "https://push2delay.eastmoney.com",
    "https://push2.eastmoney.com",
    "https://emweb.securities.eastmoney.com",
    "https://f10.eastmoney.com",
]


def fetch_finance_snapshot(symbol: str, timeout: float = 12.0) -> dict[str, Any]:
    """尽量拉取个股关键财务指标快照（多接口 fallback，失败则空）。"""
    symbol = symbol.strip()
    secid = symbol_to_secid(symbol)
    out: dict[str, Any] = {"symbol": symbol, "source": "eastmoney", "metrics": {}, "raw_notes": []}

    # 1) 核心报价扩展字段里常有市盈率/市净率等
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            params = {
                "secid": secid,
                "fields": "f57,f58,f43,f162,f163,f164,f167,f168,f169,f170,f116,f117,f46,f44,f45,f47,f48,f60",
                "fltt": "2",
                "invt": "2",
                "ut": EM_UT,
            }
            for host in ("https://push2delay.eastmoney.com", "https://push2.eastmoney.com"):
                r = client.get(host + "/api/qt/stock/get", params=params)
                if r.status_code != 200:
                    continue
                data = r.json().get("data") or {}
                if not data:
                    continue
                out["name"] = data.get("f58") or ""
                out["metrics"] = {
                    "price": to_float(data.get("f43")),
                    "pe_ttm": to_float(data.get("f162")),  # 常见映射，接口变更时可能为空
                    "pb": to_float(data.get("f167")),
                    "total_mv": to_float(data.get("f116")),
                    "float_mv": to_float(data.get("f117")),
                    "turnover": to_float(data.get("f168")),
                    "pct": to_float(data.get("f170")),
                }
                out["raw_notes"].append("quote_extended_fields")
                break
    except Exception as e:
        out["raw_notes"].append(f"quote_fail:{e}")

    # 2) F10 主要指标页（HTML/JSON 不稳定，做 best-effort）
    try:
        market = "SH" if symbol.startswith(("6", "5", "9")) else "SZ"
        code = f"{market}{symbol}"
        url = f"https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/Index?type=web&code={code}"
        out["f10_url"] = url
        out["raw_notes"].append("f10_url_attached")
    except Exception as e:
        out["raw_notes"].append(f"f10_fail:{e}")

    return out
