"""研报 / 看图 / 财报的 OpenAI function calling 工具集与执行器。"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any, Optional

from yeuxq.analysis.indicators import last_sma
from yeuxq.intel.fundamentals import fetch_finance_snapshot

log = logging.getLogger("yeuxq.agent_tools")

_YEUX_TOOLS = frozenset({"yeux_search", "yeux_deep_search"})
_KLINE_PERIODS = frozenset({"day", "week", "month"})
_BUDGET_MSG = "调查预算已用尽，请基于已获得的信息直接给出结论"
_DEEP_EXHAUSTED_MSG = "深检索次数已用尽，请改用 yeux_search"


def _fn(name: str, description: str, params: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": params,
                "required": required,
            },
        },
    }


VISION_TOOLS: list[dict[str, Any]] = [
    _fn(
        "yeux_search",
        "用网络检索最新新闻、公告、业绩或资金流报道。需要了解消息面、核实某日资金数字或查找催化事件时调用。"
        "query 应包含公司名或代码以及要核实的具体问题。适合快速检索。",
        {"query": {"type": "string", "description": "检索词，含标的名称/代码与要核实的问题"}},
        ["query"],
    ),
    _fn(
        "yeux_deep_search",
        "深度网络检索，更慢但更全面。仅在普通检索结果不够、或资讯数字与本地数据冲突需要交叉核验时使用。不要作为第一次检索。",
        {"query": {"type": "string", "description": "深度检索词"}},
        ["query"],
    ),
    _fn(
        "get_fund_flow",
        "获取本地权威的历史主力资金流（按日，单位亿元）。出稿前应至少调用一次，用本地数据核对资讯里的流入/流出数字。本地数据优先于网络报道。",
        {
            "symbol": {"type": "string", "description": "6 位股票代码"},
            "days": {"type": "integer", "description": "回溯天数，默认 30，最大 120"},
        },
        ["symbol"],
    ),
    _fn(
        "get_realtime_flow",
        "获取今日分时主力资金流汇总与关键时点。需要看盘中资金进出节奏（而非历史日频）时调用。",
        {"symbol": {"type": "string", "description": "6 位股票代码"}},
        ["symbol"],
    ),
    _fn(
        "get_quote",
        "获取最新行情（现价、涨跌幅、换手、成交额）。数字上下文缺失或需要确认现价时调用。",
        {"symbol": {"type": "string", "description": "6 位股票代码"}},
        ["symbol"],
    ),
    _fn(
        "get_finance_snapshot",
        "获取估值快照（PE/PB/市值等）。资讯中的估值与上下文冲突、需要判断哪边可信时调用。",
        {"symbol": {"type": "string", "description": "6 位股票代码"}},
        ["symbol"],
    ),
    _fn(
        "get_klines",
        "获取 K 线结构化摘要（区间高低、涨跌幅、均线、最近 20 根），不是原始 OHLC 全量。图中看不清趋势/均线/关键价时调用。",
        {
            "symbol": {"type": "string", "description": "6 位股票代码"},
            "period": {"type": "string", "description": "day / week / month，非法值回落 day"},
            "count": {"type": "integer", "description": "根数，默认 60，最大 120"},
        },
        ["symbol"],
    ),
]


def select_vision_tools(*, with_news: bool = True, deep: bool = False) -> list[dict[str, Any]]:
    skip: set[str] = set()
    if not with_news:
        skip |= _YEUX_TOOLS
    if not deep:
        skip.add("yeux_deep_search")
    return [t for t in VISION_TOOLS if t["function"]["name"] not in skip]


def select_earnings_tools(*, deep: bool = True) -> list[dict[str, Any]]:
    """财报专题：资讯 + 深检索 + 估值/行情/K 线/资金流；不含分时。"""
    skip = {"get_realtime_flow"}
    if not deep:
        skip.add("yeux_deep_search")
    return [t for t in VISION_TOOLS if t["function"]["name"] not in skip]


def select_report_tools(*, deep: bool = False) -> list[dict[str, Any]]:
    """资讯/研报：偏重检索，辅以现价、资金流、估值、K 线核对；不含分时。"""
    skip = {"get_realtime_flow"}
    if not deep:
        skip.add("yeux_deep_search")
    return [t for t in VISION_TOOLS if t["function"]["name"] not in skip]


def _yi(v: Any) -> str:
    try:
        if v is None or v == "":
            return "—"
        return f"{float(v) / 1e8:.2f}"
    except (TypeError, ValueError):
        return "—"


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "…（已截断）"


def _as_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "__dict__"):
        return {k: getattr(obj, k) for k in vars(obj)}
    return {}


def _summary_head(text: str) -> str:
    return " ".join((text or "").split())[:200]


def _fail(reason: str) -> str:
    return f"工具执行失败：{reason}"


def _full_result_block(name: str, args: dict[str, Any], text: str) -> str:
    extra = ""
    if name in _YEUX_TOOLS:
        extra = f" query={args.get('query') or ''}"
    elif args.get("symbol"):
        extra = f" symbol={args.get('symbol')}"
    return f"### {name}{extra}\n{text or ''}"


def format_fund_flow(flows: list[Any], *, days: int) -> str:
    rows: list[dict[str, Any]] = [_as_dict(f) for f in (flows or [])]
    if not rows:
        return "未取到资金流数据"
    lines = [f"资金流明细（最近{len(rows)}日，单位亿元）："]
    inflow_n = outflow_n = 0
    total = 0.0
    max_in: tuple[float, str] | None = None
    max_out: tuple[float, str] | None = None
    detail: list[str] = []
    for f in rows:
        main = float(f.get("main_net") or 0)
        total += main
        date = str(f.get("date") or "?")
        if main > 0:
            inflow_n += 1
            if max_in is None or main > max_in[0]:
                max_in = (main, date)
        elif main < 0:
            outflow_n += 1
            if max_out is None or main < max_out[0]:
                max_out = (main, date)
        detail.append(
            f"{date} 主力净流入(亿)={_yi(f.get('main_net'))} "
            f"超大单(亿)={_yi(f.get('super_large_net'))} "
            f"大单(亿)={_yi(f.get('large_net'))} "
            f"主力占比%={f.get('main_pct') if f.get('main_pct') is not None else '—'}"
        )
    summary = [
        f"汇总：区间累计主力净流入={_yi(total)}亿；流入{inflow_n}日 / 流出{outflow_n}日",
    ]
    if max_in:
        summary.append(f"最大单日流入={_yi(max_in[0])}亿（{max_in[1]}）")
    if max_out:
        summary.append(f"最大单日流出={_yi(max_out[0])}亿（{max_out[1]}）")
    body = "\n".join(lines + detail + summary)
    if len(body) > 4000:
        kept = detail[-30:] if len(detail) > 30 else detail
        body = "\n".join(
            [f"资金流明细（超长，仅保留最近{len(kept)}日 + 全区间汇总，单位亿元）："]
            + kept
            + summary
        )
    return _clip(body, 4000)


def format_klines(klines: list[Any], *, period: str) -> str:
    rows = [_as_dict(k) for k in (klines or [])]
    if not rows:
        return "未取到K线数据"
    closes = [float(k.get("close") or 0) for k in rows]
    highs = [float(k.get("high") or 0) for k in rows]
    lows = [float(k.get("low") or 0) for k in rows]
    first, last = rows[0], rows[-1]
    start_d = first.get("date") or "?"
    end_d = last.get("date") or "?"
    last_close = float(last.get("close") or 0)
    first_close = float(first.get("close") or 0) or last_close
    pct = (last_close / first_close - 1.0) * 100.0 if first_close else 0.0
    hi = max(highs) if highs else 0.0
    lo = min(lows) if lows else 0.0

    def _ma(n: int) -> str:
        if len(closes) < n:
            return "—"
        return f"{last_sma(closes, n):.2f}"

    lines = [
        f"K线摘要 period={period} 根数={len(rows)}",
        f"区间={start_d} ~ {end_d} 最高={hi:.2f} 最低={lo:.2f} 最新收盘={last_close:.2f} 期间涨跌幅={pct:.2f}%",
        f"MA5={_ma(5)} MA10={_ma(10)} MA20={_ma(20)} MA60={_ma(60)}",
        "最近20根（日期 收盘 涨跌幅% 成交量）：",
    ]
    for k in rows[-20:]:
        p = k.get("pct")
        p_s = f"{float(p):.2f}" if p is not None and p != "" else "—"
        lines.append(f"{k.get('date') or '?'} {k.get('close')} {p_s}% {k.get('volume')}")
    return _clip("\n".join(lines), 3000)


def format_realtime_flow(payload: dict[str, Any] | None) -> str:
    data = payload if isinstance(payload, dict) else {}
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    flows = data.get("flows") if isinstance(data.get("flows"), list) else []
    lines = [f"分时资金流 symbol={data.get('symbol') or ''}（单位亿元）"]
    if summary:
        lines.append(
            "汇总："
            f"主力={_yi(summary.get('main_net'))} "
            f"超大单={_yi(summary.get('super_large_net'))} "
            f"大单={_yi(summary.get('large_net'))} "
            f"中单={_yi(summary.get('medium_net'))} "
            f"小单={_yi(summary.get('small_net'))}"
        )
    else:
        lines.append("汇总：无")
    parsed = [_as_dict(f) for f in flows]
    if parsed:
        keyed = []
        keyed.append(parsed[0])
        keyed.append(parsed[-1])
        by_main = sorted(parsed, key=lambda x: float(x.get("main_net") or 0))
        keyed.append(by_main[0])
        keyed.append(by_main[-1])
        step = max(1, len(parsed) // 4)
        keyed.extend(parsed[::step][:4])
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for f in keyed:
            t = str(f.get("time") or "?")
            if t in seen:
                continue
            seen.add(t)
            unique.append(f)
        unique.sort(key=lambda x: str(x.get("time") or ""))
        lines.append("关键时点（时间 主力净流入亿）：")
        for f in unique:
            lines.append(f"{f.get('time') or '?'} {_yi(f.get('main_net'))}")
    return _clip("\n".join(lines), 2000)


def format_quote(quote: Any) -> str:
    q = _as_dict(quote)
    if not q:
        return "未取到行情"
    return (
        f"行情 {q.get('symbol') or ''} {q.get('name') or ''} "
        f"现价={q.get('price')} 涨跌幅={q.get('pct')}% 换手={q.get('turnover')}% "
        f"成交额={_yi(q.get('amount'))}亿 成交量={q.get('volume')}"
    )


def format_snapshot(snap: dict[str, Any] | None) -> str:
    data = snap if isinstance(snap, dict) else {}
    m = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
    lines = [
        f"估值快照 symbol={data.get('symbol') or ''} name={data.get('name') or ''} source={data.get('source') or ''}",
        f"现价={m.get('price')} PE_TTM={m.get('pe_ttm')} PB={m.get('pb')} "
        f"总市值={_yi(m.get('total_mv'))}亿 流通市值={_yi(m.get('float_mv'))}亿 换手={m.get('turnover')}",
    ]
    if data.get("f10_url"):
        lines.append(f"F10={data.get('f10_url')}")
    return _clip("\n".join(lines), 2000)


def format_yeux_result(result: dict[str, Any] | None) -> str:
    data = result if isinstance(result, dict) else {}
    if not data.get("ok"):
        return _fail(str(data.get("error") or "检索失败"))
    text = (data.get("text") or "").strip()
    if not text:
        return "未检索到有效资讯"
    return _clip(text, 6000)


class ToolRunner:
    def __init__(
        self,
        research: Any,
        *,
        max_tool_calls: int = 8,
        total_budget_sec: float = 180.0,
        max_deep_search: int = 2,
        local_timeout: float = 20.0,
    ) -> None:
        self.research = research
        self.max_tool_calls = int(max_tool_calls)
        self.total_budget_sec = float(total_budget_sec)
        self.max_deep_search = int(max_deep_search)
        self.local_timeout = float(local_timeout)
        self._t0 = time.time()
        self._calls = 0
        self._deep_used = 0
        self._trace: list[dict[str, Any]] = []
        self._full_results: list[str] = []
        self._yeux_attempted = False
        self._yeux_any_ok = False

    @property
    def trace(self) -> list[dict[str, Any]]:
        return list(self._trace)

    @property
    def full_results(self) -> list[str]:
        return list(self._full_results)

    @property
    def exhausted(self) -> bool:
        if self._calls >= self.max_tool_calls:
            return True
        return (time.time() - self._t0) >= self.total_budget_sec

    @property
    def yeux_ok(self) -> Optional[bool]:
        if not self._yeux_attempted:
            return None
        return self._yeux_any_ok

    def run(self, name: str, arguments: dict) -> str:
        args = arguments if isinstance(arguments, dict) else {}
        t0 = time.time()
        if self.exhausted:
            return _BUDGET_MSG
        try:
            text, ok, count_call, mark_yeux = self._dispatch(name, args)
        except Exception as e:
            log.exception("tool %s failed", name)
            text, ok, count_call, mark_yeux = _fail(str(e)), False, True, name in _YEUX_TOOLS
        if count_call:
            self._calls += 1
        if mark_yeux:
            self._yeux_attempted = True
            if ok:
                self._yeux_any_ok = True
        self._record(name, args, ok=ok, elapsed=time.time() - t0, text=text)
        self._full_results.append(_full_result_block(name, args, text))
        return text

    def _record(self, name: str, args: dict, *, ok: bool, elapsed: float, text: str) -> None:
        self._trace.append(
            {
                "name": name,
                "args": args,
                "ok": ok,
                "elapsed_sec": round(elapsed, 3),
                "result_chars": len(text or ""),
                "summary": _summary_head(text),
            }
        )

    def _container(self) -> Any:
        from yeuxq.api.deps import get_container

        return get_container()

    def _local(self, fn, *a, **k):
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(fn, *a, **k).result(timeout=self.local_timeout)
        except FuturesTimeout as e:
            raise TimeoutError(f"本地调用超时({self.local_timeout}s)") from e

    def _dispatch(self, name: str, args: dict) -> tuple[str, bool, bool, bool]:
        """返回 (文本, ok, 是否计入次数, 是否记为 yeux 尝试)。"""
        if name == "yeux_deep_search" and self._deep_used >= self.max_deep_search:
            return _DEEP_EXHAUSTED_MSG, False, True, False
        if name not in {t["function"]["name"] for t in VISION_TOOLS}:
            return f"未知工具：{name}", False, True, False

        if name in _YEUX_TOOLS:
            query = str(args.get("query") or "").strip()
            if not query:
                return _fail("缺少 query"), False, True, True
            deep = name == "yeux_deep_search"
            if deep:
                self._deep_used += 1
            result = self.research.yeux.search(query, deep=deep)
            text = format_yeux_result(result)
            ok = bool(result.get("ok")) if isinstance(result, dict) else False
            return text, ok, True, True

        symbol = str(args.get("symbol") or "").strip()
        if name in {
            "get_fund_flow",
            "get_realtime_flow",
            "get_quote",
            "get_finance_snapshot",
            "get_klines",
        }:
            if not symbol:
                return _fail("缺少 symbol"), False, True, False

        c = self._container()
        if name == "get_fund_flow":
            try:
                days = int(args.get("days") if args.get("days") is not None else 30)
            except (TypeError, ValueError):
                days = 30
            days = max(1, min(120, days))
            flows = self._local(c.data.fetch_fund_flow, symbol, days)
            return format_fund_flow(flows, days=days), True, True, False
        if name == "get_realtime_flow":
            payload = self._local(c.analyze.realtime_flow_payload, symbol)
            return format_realtime_flow(payload), True, True, False
        if name == "get_quote":
            quote = self._local(c.data.fetch_quote, symbol)
            return format_quote(quote), True, True, False
        if name == "get_finance_snapshot":
            snap = self._local(fetch_finance_snapshot, symbol, self.local_timeout)
            return format_snapshot(snap), True, True, False
        if name == "get_klines":
            period = str(args.get("period") or "day").strip().lower()
            if period not in _KLINE_PERIODS:
                period = "day"
            try:
                count = int(args.get("count") if args.get("count") is not None else 60)
            except (TypeError, ValueError):
                count = 60
            count = max(1, min(120, count))
            klines = self._local(c.data.fetch_kline, symbol, count, period)
            return format_klines(klines, period=period), True, True, False
        return f"未知工具：{name}", False, True, False
