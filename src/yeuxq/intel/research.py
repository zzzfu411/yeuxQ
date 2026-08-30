"""研报 / 新闻 / 财报分析编排：YeuX 检索 + Grok 生成。"""

from __future__ import annotations

import logging
import os
import re
import stat
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from yeuxq.settings import PACKAGE_ROOT, PROJECT_ROOT, get_settings
from yeuxq.intel.agent_tools import (
    ToolRunner,
    select_earnings_tools,
    select_report_tools,
    select_vision_tools,
)
from yeuxq.intel.fundamentals import fetch_finance_snapshot
from yeuxq.intel.llm_client import LlmClient
from yeuxq.intel.report_store import (
    ReportExpiredError,
    ReportNotFoundError,
    ReportStore,
    ReportStoreError,
)
from yeuxq.intel.secrets import load_intel_config
from yeuxq.intel.yeux_client import YeuxMcpClient
from yeuxq.security import RuntimeSecrets
from yeuxq.services.analyze import AnalyzeService

ROOT = PROJECT_ROOT or PACKAGE_ROOT
_INITIAL_ROOT = ROOT

log = logging.getLogger("yeuxq.research")

SYSTEM_ANALYST = """你是一名严谨的 A 股投研助手。你必须：
1. 区分「事实 / 推断 / 未知」；没有证据不要编造财报数字。
2. 引用检索材料中的信息时，尽量保留来源线索（标题/媒体/时间）。
3. 明确风险与不确定性；文末声明不构成投资建议。
4. 使用简体中文，结构清晰，适合个人投资者阅读。
5. 技术面结论若与基本面/新闻冲突，要明确指出冲突。"""

SYSTEM_VISION = """你是一名 A 股短线资金分析师，专注识别大资金（主力/机构）流入与出逃迹象。你必须：
1. 严格区分「图中可见证据 / 数据证据 / 推断」三类表述；没有证据禁止编造价格、资金数字或形态。
2. 先读图（若有），再与数字上下文交叉验证；互相冲突时明确指出，不要调和成单一叙事。
3. 结论只谈资金行为与技术结构，不给「必涨/必跌」承诺。
4. 资讯与快照若与图表/资金证据冲突，必须在「反证与风险」中点明。
5. 使用简体中文，结构清晰。
6. 文末声明不构成投资建议。"""

SYSTEM_VISION_AGENTIC = (
    SYSTEM_VISION
    + """
7. 你可以调用工具主动查证。出稿前至少要做到：调用一次资讯检索了解最新消息面（若资讯工具可用），并调用一次 get_fund_flow 用本地权威数据核对资金流。
8. 当资讯里的数字与本地数据冲突时，必须再查一次去判断哪个可信（例如换关键词重搜、或调 get_finance_snapshot 核对估值），而不是直接写「存在冲突」了事。
9. 工具调用要有目的性，不要为凑数而调；预算有限（最多 8 次）。
10. 报告里凡是来自工具的数字，标注来源（如「本地资金流数据」「检索：xxx」）。"""
)

SYSTEM_EARNINGS_AGENTIC = (
    SYSTEM_ANALYST
    + """
6. 你可以调用工具主动查证。必须先检索财报原始数据（营收/净利/毛利率等），再用 get_finance_snapshot 核对 PE/PB/市值等口径。
7. 不同来源的财报数字若不一致（很常见），必须再检索一次确认哪个是正式披露口径，并在报告里说明分歧与取舍依据，不要静默取其一。
8. 严禁编造未检索到的财务数字；材料没有就写「材料未披露/未检索到」。
9. 报告里每个关键数字都要标注来源（检索 / 本地快照）。
10. 工具调用要有目的性，不要为凑数而调；预算有限（最多 8 次）。深检索最多一次，优先普通检索，仅在普通检索不够或数字冲突时使用。"""
)

SYSTEM_REPORT_AGENTIC = (
    SYSTEM_ANALYST
    + """
6. 你可以调用工具主动查证。先检索最新消息面（公告/新闻/研报），再用本地行情与资金流工具核对现价、资金是否印证消息。
7. 资讯数字与本地数据冲突时必须再查一次核实，不要静默取其一。
8. 没有证据不要编造事实或数字；材料没有就写未知或未检索到。
9. 报告里关键数字都要标注来源（检索 / 本地数据）。
10. 工具调用要有目的性，不要为凑数而调；预算有限（最多 8 次）。"""
)


class ResearchService:
    def __init__(
        self,
        analyze: AnalyzeService,
        *,
        public_config: object | None = None,
        runtime_secrets: RuntimeSecrets | None = None,
        report_store: ReportStore | None = None,
    ) -> None:
        self.analyze = analyze
        cfg = load_intel_config(public_config, runtime_secrets)
        self.cfg = cfg
        self.report_store = report_store
        self.yeux = YeuxMcpClient(
            url=cfg["yeux_mcp_url"],
            token=cfg["yeux_mcp_token"],
            timeout=cfg["yeux_timeout"],
        )
        self.llm = LlmClient(
            base_url=cfg["llm_base_url"],
            api_key=cfg["llm_api_key"],
            model=cfg["llm_model"],
            timeout=cfg["llm_timeout"],
            reasoning_effort=str(cfg.get("llm_reasoning_effort") or "xhigh"),
        )

    def status(self) -> dict[str, Any]:
        return {
            "yeux_configured": self.yeux.available(),
            "llm_configured": self.llm.available(),
            "llm_model": self.cfg.get("llm_model"),
            "llm_reasoning_effort": self.cfg.get("llm_reasoning_effort"),
            "llm_base_url": self.cfg.get("llm_base_url"),
            "yeux_mcp_url": self.cfg.get("yeux_mcp_url"),
            "credentials": {
                "llm": bool(self.cfg.get("llm_api_key")),
                "yeux_mcp": bool(self.cfg.get("yeux_mcp_token")),
            },
            **store_policy(),
        }

    def _store_report(self, symbol: str, kind: str, markdown: str) -> dict[str, Any]:
        return _save_report(
            symbol,
            kind,
            markdown,
            store=getattr(self, "report_store", None),
        )

    def search_news(
        self,
        symbol: str,
        name: str = "",
        deep: bool = False,
        extra_query: str = "",
    ) -> dict[str, Any]:
        label = f"{name}({symbol})" if name else symbol
        q = extra_query.strip() or f"{label} 最新 新闻 公告 业绩 研报 风险 2025 2026"
        result = self.yeux.search(q, deep=deep)
        md = ""
        if result.get("ok") and (result.get("text") or "").strip():
            md = f"# {label} 资讯\n\n{result.get('text')}\n"
            saved = self._store_report(symbol, "news", md)
        else:
            saved = _empty_save()
        return {
            "symbol": symbol,
            "name": name,
            "query": q,
            "deep": deep,
            **result,
            **saved,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def generate_report(
        self,
        symbol: str,
        deep: bool = False,
        include_technical: bool = True,
        focus: str = "综合",
    ) -> dict[str, Any]:
        """综合投研速报：Grok 自主调工具调查，网关不支持则回落预检索。"""
        symbol = symbol.strip()
        tech: dict[str, Any] = {}
        name = ""
        if include_technical:
            tech = self.analyze.analyze(symbol, "day")
            if tech.get("error"):
                return {
                    "ok": False,
                    "error": tech["error"],
                    "symbol": symbol,
                    "name": "",
                    "focus": focus,
                    "deep": deep,
                    "report_markdown": "",
                    "model": self.cfg.get("llm_model"),
                    "usage": None,
                    "news_excerpt": "",
                    "inputs": {},
                    "disclaimer": "AI 生成内容可能有误，不构成投资建议。",
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    **_empty_save(),
                    **_agentic_fields(),
                }
            name = ((tech.get("quote") or {}).get("name")) or ""
        try:
            fund = fetch_finance_snapshot(symbol)
        except Exception as e:
            log.warning("finance snapshot failed: %s", e)
            fund = None
        tools = select_report_tools(deep=deep)
        runner = ToolRunner(
            self,
            max_tool_calls=8,
            total_budget_sec=180.0,
            max_deep_search=2 if deep else 0,
        )
        user_prompt = _compose_report_agentic_prompt(
            symbol=symbol,
            name=name,
            focus=focus,
            tech_brief=_format_tech_brief(tech),
            fund=fund,
            deep=deep,
        )
        llm = self.llm.chat_agentic(
            SYSTEM_REPORT_AGENTIC,
            user_prompt,
            [],
            tools,
            runner,
            temperature=0.25,
            max_tokens=5000,
            max_rounds=6,
            total_budget_sec=180.0,
        )
        md = llm.get("content") or ""
        if not llm.get("ok"):
            md = ""
        if not _is_valid_report(md):
            if runner.trace:
                first_yeux = _first_yeux_trace(runner.trace)
                args = first_yeux.get("args") if isinstance(first_yeux.get("args"), dict) else {}
                return self._finish_from_tools(
                    kind="report",
                    symbol=symbol,
                    name=name,
                    system=SYSTEM_ANALYST,
                    user_prompt=user_prompt,
                    runner=runner,
                    llm=llm,
                    temperature=0.25,
                    max_tokens=5000,
                    extra={
                        "focus": focus,
                        "deep": deep,
                        "inputs": {
                            "technical_score": (
                                (tech.get("signal") or {}).get("score") if tech else None
                            ),
                            "technical_action": (
                                (tech.get("signal") or {}).get("action") if tech else None
                            ),
                            "news_ok": runner.yeux_ok,
                            "news_tool": first_yeux.get("name"),
                            "news_elapsed_sec": first_yeux.get("elapsed_sec"),
                            "news_query": args.get("query") if first_yeux else None,
                            "fundamentals": fund,
                        },
                        "news_excerpt": _news_excerpt_from_trace(runner.trace, 4000),
                        "disclaimer": "AI 生成内容可能有误，不构成投资建议。",
                    },
                )
            legacy = self._generate_report_legacy(
                symbol=symbol,
                deep=deep,
                include_technical=include_technical,
                focus=focus,
            )
            return _with_agentic_trace(legacy, runner, llm)
        first_yeux = _first_yeux_trace(runner.trace)
        args = first_yeux.get("args") if isinstance(first_yeux.get("args"), dict) else {}
        saved = self._store_report(symbol, "report", md)
        return {
            "ok": bool(llm.get("ok")),
            "symbol": symbol,
            "name": name,
            "focus": focus,
            "deep": deep,
            "report_markdown": md,
            "error": None if llm.get("ok") else (llm.get("error") or "生成失败"),
            "model": llm.get("model") or self.cfg.get("llm_model"),
            "usage": llm.get("usage"),
            **saved,
            "inputs": {
                "technical_score": ((tech.get("signal") or {}).get("score") if tech else None),
                "technical_action": ((tech.get("signal") or {}).get("action") if tech else None),
                "news_ok": runner.yeux_ok,
                "news_tool": first_yeux.get("name"),
                "news_elapsed_sec": first_yeux.get("elapsed_sec"),
                "news_query": args.get("query") if first_yeux else None,
                "fundamentals": fund,
            },
            "news_excerpt": _news_excerpt_from_trace(runner.trace, 4000),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "disclaimer": "AI 生成内容可能有误，不构成投资建议。",
            **_agentic_fields(
                agentic=True,
                trace=runner.trace,
                rounds=llm.get("rounds"),
                budget_hit=llm.get("budget_hit"),
            ),
        }

    def _generate_report_legacy(
        self,
        symbol: str,
        deep: bool = False,
        include_technical: bool = True,
        focus: str = "综合",
    ) -> dict[str, Any]:
        """预检索 + 单轮 chat 回落路径。"""
        symbol = symbol.strip()
        tech: dict[str, Any] = {}
        name = ""
        if include_technical:
            tech = self.analyze.analyze(symbol, "day")
            if tech.get("error"):
                return {
                    "ok": False,
                    "error": tech["error"],
                    "symbol": symbol,
                    "name": "",
                    "focus": focus,
                    "deep": deep,
                    "report_markdown": "",
                    "model": self.cfg.get("llm_model"),
                    "usage": None,
                    "news_excerpt": "",
                    "inputs": {},
                    "disclaimer": "AI 生成内容可能有误，不构成投资建议。",
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    **_empty_save(),
                    **_agentic_fields(),
                }
            name = ((tech.get("quote") or {}).get("name")) or ""

        news = self.search_news(symbol, name=name, deep=deep)
        fund = fetch_finance_snapshot(symbol)
        tech_brief = _format_tech_brief(tech)
        user_prompt = f"""请为 A 股标的生成《投研速报》。

【标的】{name or ""} {symbol}
【关注重点】{focus}
【生成时间(UTC)】{datetime.now(timezone.utc).isoformat()}

【技术面引擎输出】
{tech_brief or "（未提供）"}

【公开行情/估值快照】
{fund}

【YeuX 检索结果】tool={news.get("tool")} ok={news.get("ok")} elapsed={news.get("elapsed_sec")}
query={news.get("query")}
-----
{news.get("text") or news.get("error") or "无检索内容"}
-----

请输出 Markdown，章节固定为：
# 标题
## 1. 一句话结论
## 2. 技术面解读
## 3. 新闻与事件催化
## 4. 基本面/财报线索（无数据则写「公开接口未取到，需人工核实」）
## 5. 多空逻辑与关键价位
## 6. 风险清单
## 7. 信息来源与局限
文末加：不构成投资建议。
"""
        llm = self.llm.chat(
            [
                {"role": "system", "content": SYSTEM_ANALYST},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.25,
            max_tokens=5000,
        )
        md = llm.get("content") or ""
        if not llm.get("ok"):
            md = ""
        if not _is_valid_report(md):
            return {
                "ok": False,
                "symbol": symbol,
                "name": name,
                "focus": focus,
                "deep": deep,
                "report_markdown": "",
                "error": llm.get("error") or "模型返回了无效内容",
                "model": llm.get("model") or self.cfg.get("llm_model"),
                "usage": llm.get("usage"),
                "inputs": {
                    "technical_score": ((tech.get("signal") or {}).get("score") if tech else None),
                    "technical_action": (
                        (tech.get("signal") or {}).get("action") if tech else None
                    ),
                    "news_ok": news.get("ok"),
                    "news_tool": news.get("tool"),
                    "news_elapsed_sec": news.get("elapsed_sec"),
                    "news_query": news.get("query"),
                    "fundamentals": fund,
                },
                "news_excerpt": (news.get("text") or "")[:4000],
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "disclaimer": "AI 生成内容可能有误，不构成投资建议。",
                **_empty_save(),
                **_agentic_fields(rounds=1 if llm.get("ok") else 0),
            }
        saved = self._store_report(symbol, "report", md)
        return {
            "ok": bool(llm.get("ok")),
            "symbol": symbol,
            "name": name,
            "focus": focus,
            "deep": deep,
            "report_markdown": md,
            "error": None if llm.get("ok") else (llm.get("error") or "生成失败"),
            "model": llm.get("model") or self.cfg.get("llm_model"),
            "usage": llm.get("usage"),
            **saved,
            "inputs": {
                "technical_score": ((tech.get("signal") or {}).get("score") if tech else None),
                "technical_action": ((tech.get("signal") or {}).get("action") if tech else None),
                "news_ok": news.get("ok"),
                "news_tool": news.get("tool"),
                "news_elapsed_sec": news.get("elapsed_sec"),
                "news_query": news.get("query"),
                "fundamentals": fund,
            },
            "news_excerpt": (news.get("text") or "")[:4000],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "disclaimer": "AI 生成内容可能有误，不构成投资建议。",
            **_agentic_fields(rounds=1 if llm.get("ok") else 0),
        }

    def generate_earnings_report(
        self,
        symbol: str,
        deep: bool = True,
        period_hint: str = "最近一期财报/业绩预告",
    ) -> dict[str, Any]:
        """财报/业绩专题：Grok 自主调工具交叉核对，网关不支持则回落预检索。"""
        symbol = symbol.strip()
        quote = self.analyze.data.fetch_quote(symbol)
        name = quote.name if quote else ""
        try:
            fund = fetch_finance_snapshot(symbol)
        except Exception as e:
            log.warning("finance snapshot failed: %s", e)
            fund = None
        tools = select_earnings_tools(deep=deep)
        runner = ToolRunner(
            self,
            max_tool_calls=8,
            total_budget_sec=180.0,
            max_deep_search=1 if deep else 0,
        )
        label = f"{name}({symbol})" if name else symbol
        user_prompt = _compose_earnings_agentic_prompt(
            label=label,
            period_hint=period_hint,
            fund=fund,
            deep=deep,
        )
        llm = self.llm.chat_agentic(
            SYSTEM_EARNINGS_AGENTIC,
            user_prompt,
            [],
            tools,
            runner,
            temperature=0.2,
            max_tokens=5000,
            max_rounds=6,
            total_budget_sec=180.0,
        )
        md = llm.get("content") or ""
        if not llm.get("ok"):
            md = ""
        if not _is_valid_report(md):
            if runner.trace:
                return self._finish_from_tools(
                    kind="earnings",
                    symbol=symbol,
                    name=name,
                    system=SYSTEM_ANALYST,
                    user_prompt=user_prompt,
                    runner=runner,
                    llm=llm,
                    temperature=0.2,
                    max_tokens=5000,
                    extra={
                        "searches": _searches_from_trace(runner.trace),
                        "news_excerpt": _news_excerpt_from_trace(runner.trace, 5000),
                        "fundamentals": fund,
                        "disclaimer": "AI 生成内容可能有误，财报数字请以交易所披露为准。",
                    },
                )
            legacy = self._generate_earnings_legacy(
                symbol=symbol,
                deep=deep,
                period_hint=period_hint,
            )
            return _with_agentic_trace(legacy, runner, llm)
        saved = self._store_report(symbol, "earnings", md)
        return {
            "ok": bool(llm.get("ok")),
            "symbol": symbol,
            "name": name,
            "report_markdown": md,
            "error": None if llm.get("ok") else (llm.get("error") or "生成失败"),
            "model": llm.get("model") or self.cfg.get("llm_model"),
            "usage": llm.get("usage"),
            **saved,
            "searches": _searches_from_trace(runner.trace),
            "news_excerpt": _news_excerpt_from_trace(runner.trace, 5000),
            "fundamentals": fund,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "disclaimer": "AI 生成内容可能有误，财报数字请以交易所披露为准。",
            **_agentic_fields(
                agentic=True,
                trace=runner.trace,
                rounds=llm.get("rounds"),
                budget_hit=llm.get("budget_hit"),
            ),
        }

    def _generate_earnings_legacy(
        self,
        symbol: str,
        deep: bool = True,
        period_hint: str = "最近一期财报/业绩预告",
    ) -> dict[str, Any]:
        """预检索 q1/q2 + 单轮 chat 回落路径。"""
        symbol = symbol.strip()
        quote = self.analyze.data.fetch_quote(symbol)
        name = quote.name if quote else ""
        label = f"{name}({symbol})" if name else symbol

        q1 = f"{label} {period_hint} 营收 净利润 毛利率 同比 环比 原文"
        q2 = f"{label} 业绩会 机构点评 一致预期 风险 最新"
        s1 = self.yeux.search(q1, deep=deep)
        s2 = self.yeux.search(q2, deep=False)
        fund = fetch_finance_snapshot(symbol)

        user_prompt = f"""请撰写《{label} 财报/业绩专题分析》。

【估值与行情快照】
{fund}

【检索1 财报数据线索】ok={s1.get("ok")} tool={s1.get("tool")}
{s1.get("text") or s1.get("error")}

【检索2 机构/市场反应】ok={s2.get("ok")} tool={s2.get("tool")}
{s2.get("text") or s2.get("error")}

要求：
- 用 Markdown
- 尽量表格化列出：营收、净利、增速、毛利率/净利率、指引（若材料有）
- 若材料没有确切数字，明确写「材料未披露/未检索到」，禁止编造
- 分析质量、超/低于预期的可能原因、对股价含义
- 风险与后续观察点
- 不构成投资建议
"""
        llm = self.llm.chat(
            [
                {"role": "system", "content": SYSTEM_ANALYST},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=5000,
        )
        md = llm.get("content") or ""
        if not llm.get("ok"):
            md = ""
        if not _is_valid_report(md):
            return {
                "ok": False,
                "symbol": symbol,
                "name": name,
                "report_markdown": "",
                "error": llm.get("error") or "模型返回了无效内容",
                "model": llm.get("model") or self.cfg.get("llm_model"),
                "usage": llm.get("usage"),
                "searches": [
                    {
                        "query": q1,
                        "ok": s1.get("ok"),
                        "tool": s1.get("tool"),
                        "elapsed_sec": s1.get("elapsed_sec"),
                    },
                    {
                        "query": q2,
                        "ok": s2.get("ok"),
                        "tool": s2.get("tool"),
                        "elapsed_sec": s2.get("elapsed_sec"),
                    },
                ],
                "news_excerpt": ((s1.get("text") or "") + "\n\n" + (s2.get("text") or ""))[:5000],
                "fundamentals": fund,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "disclaimer": "AI 生成内容可能有误，财报数字请以交易所披露为准。",
                **_empty_save(),
                **_agentic_fields(rounds=1 if llm.get("ok") else 0),
            }
        saved = self._store_report(symbol, "earnings", md)
        return {
            "ok": bool(llm.get("ok")),
            "symbol": symbol,
            "name": name,
            "report_markdown": md,
            "error": None if llm.get("ok") else (llm.get("error") or "生成失败"),
            "model": llm.get("model") or self.cfg.get("llm_model"),
            "usage": llm.get("usage"),
            **saved,
            "searches": [
                {
                    "query": q1,
                    "ok": s1.get("ok"),
                    "tool": s1.get("tool"),
                    "elapsed_sec": s1.get("elapsed_sec"),
                },
                {
                    "query": q2,
                    "ok": s2.get("ok"),
                    "tool": s2.get("tool"),
                    "elapsed_sec": s2.get("elapsed_sec"),
                },
            ],
            "news_excerpt": ((s1.get("text") or "") + "\n\n" + (s2.get("text") or ""))[:5000],
            "fundamentals": fund,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "disclaimer": "AI 生成内容可能有误，财报数字请以交易所披露为准。",
            **_agentic_fields(rounds=1 if llm.get("ok") else 0),
        }

    def generate_watch_brief(
        self,
        symbols: list[str],
        deep: bool = False,
        with_news: bool = True,
        with_llm: bool = True,
    ) -> dict[str, Any]:
        """自选晨报：本地技术面一览 + 可选大盘资讯 + 可选 Grok 点评。"""
        cleaned = _normalize_symbols(symbols)
        try:
            from yeuxq.settings import get_settings

            cap = int(get_settings().research.max_brief_symbols)
        except Exception:
            cap = 8
        cleaned = cleaned[: max(1, min(cap, 12))]
        if not cleaned:
            return {"ok": False, "error": "没有有效的股票代码", "rows": []}

        rows: list[dict[str, Any]] = []
        for code in cleaned:
            payload = self.analyze.analyze(code, "day")
            rows.append(row_from_analyze(code, payload))

        news: dict[str, Any] = {}
        if with_news and self.yeux.available():
            news = self.yeux.search("A股 今日 要闻 板块 北向 风险 政策 2026", deep=deep)

        llm: dict[str, Any] = {}
        llm_text = ""
        if with_llm and self.llm.available():
            table = format_watch_brief_markdown(rows)
            user_prompt = f"""请为个人投资者写一段《自选晨报》组合点评（不要重复贴完整表格）。

【技术面一览】
{table}

【市场检索】ok={news.get("ok")}
{(news.get("text") or news.get("error") or "无检索")[:6000]}

要求：
- 简体中文 Markdown
- 先写 3～6 条组合观察（哪些偏强/偏弱/互相冲突）
- 再写今日共同风险
- 禁止编造未出现的财报数字
- 文末：不构成投资建议
"""
            llm = self.llm.chat(
                [
                    {"role": "system", "content": SYSTEM_ANALYST},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.25,
                max_tokens=2500,
            )
            llm_text = llm.get("content") or ""

        md = format_watch_brief_markdown(
            rows,
            news_text=(news.get("text") or "") if news.get("ok") else "",
            llm_text=llm_text,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        saved = self._store_report("WATCH", "brief", md)
        return {
            "ok": True,
            "symbol": "WATCH",
            "kind": "brief",
            "rows": rows,
            "report_markdown": md,
            "model": llm.get("model") or self.cfg.get("llm_model"),
            "error": llm.get("error") if llm and not llm.get("ok") else None,
            "news_ok": news.get("ok"),
            "news_elapsed_sec": news.get("elapsed_sec"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "disclaimer": "本地规则 + 公开检索生成，不构成投资建议。",
            **saved,
        }

    def generate_vision_report(
        self,
        symbol: str,
        name: str = "",
        view: str = "day",
        range_: int = 250,
        ind: str = "macd",
        image: str = "",
        context: dict | None = None,
        deep: bool = False,
        with_news: bool = True,
    ) -> dict[str, Any]:
        """图表截图 + 数字上下文的大资金研判；默认 Grok 自主调工具调查，网关不支持则回落预检索。"""
        symbol = (symbol or "").strip()
        ctx = context if isinstance(context, dict) else {}
        quote = ctx.get("quote") if isinstance(ctx.get("quote"), dict) else {}
        name = name or (quote.get("name") or "")
        tools = select_vision_tools(with_news=with_news, deep=deep)
        runner = ToolRunner(
            self,
            max_tool_calls=8,
            total_budget_sec=180.0,
            max_deep_search=2 if deep else 0,
        )
        user_prompt = _compose_vision_prompt(
            symbol=symbol,
            name=name,
            view=view,
            range_=range_,
            ind=ind,
            image=image,
            context=ctx,
            agentic=True,
            deep=deep,
            with_news=with_news,
        )
        llm = self.llm.chat_agentic(
            SYSTEM_VISION_AGENTIC,
            user_prompt,
            [image] if image else [],
            tools,
            runner,
            temperature=0.25,
            max_tokens=4000,
            max_rounds=6,
            total_budget_sec=180.0,
        )
        md = llm.get("content") or ""
        if not llm.get("ok"):
            md = ""
        if not _is_valid_report(md):
            if runner.trace:
                return self._finish_from_tools(
                    kind="vision",
                    symbol=symbol,
                    name=name,
                    system=SYSTEM_VISION,
                    user_prompt=user_prompt,
                    runner=runner,
                    llm=llm,
                    temperature=0.25,
                    max_tokens=4000,
                    extra={
                        "vision": False,
                        "news_ok": runner.yeux_ok if with_news else None,
                    },
                )
            legacy = self._generate_vision_legacy(
                symbol=symbol,
                name=name,
                view=view,
                range_=range_,
                ind=ind,
                image=image,
                context=ctx,
                deep=deep,
                with_news=with_news,
            )
            legacy["tool_trace"] = runner.trace
            legacy["tool_calls_count"] = len(runner.trace)
            if legacy.get("ok"):
                legacy["error"] = llm.get("error") or "模型返回了无效内容"
            return legacy
        saved = self._store_report(symbol, "vision", md) if md.strip() else _empty_save()
        return {
            "ok": bool(llm.get("ok")),
            "symbol": symbol,
            "name": name,
            "report_markdown": md,
            "error": None if llm.get("ok") else (llm.get("error") or "生成失败"),
            "model": llm.get("model") or self.cfg.get("llm_model") or "grok-4.6",
            "vision": bool(llm.get("vision")) if llm.get("ok") else False,
            "usage": llm.get("usage"),
            "news_ok": runner.yeux_ok if with_news else None,
            "agentic": True,
            "tool_trace": runner.trace,
            "tool_calls_count": len(runner.trace),
            "rounds": int(llm.get("rounds") or 0),
            "budget_hit": bool(llm.get("budget_hit")),
            **saved,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _compose_from_tools(
        self,
        system: str,
        user_prompt: str,
        runner: Any,
        *,
        temperature: float = 0.25,
        max_tokens: int = 5000,
    ) -> dict[str, Any]:
        """用已有工具结果单轮出稿，不再检索、不注册 tools。"""
        blob = _join_full_results(getattr(runner, "full_results", None) or [])
        user = (
            f"{user_prompt}\n\n"
            "以下是已经调查到的工具结果，请直接据此写完整报告，不要再要求工具。\n\n"
            f"{blob}"
        )
        llm = self.llm.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        md = llm.get("content") or ""
        if not llm.get("ok"):
            md = ""
        if not _is_valid_report(md):
            return {
                "ok": False,
                "content": "",
                "error": llm.get("error") or "模型返回了无效内容",
                "model": llm.get("model") or self.cfg.get("llm_model"),
                "usage": llm.get("usage"),
            }
        return {
            "ok": True,
            "content": md,
            "error": None,
            "model": llm.get("model") or self.cfg.get("llm_model"),
            "usage": llm.get("usage"),
        }

    def _finish_from_tools(
        self,
        *,
        kind: str,
        symbol: str,
        name: str,
        system: str,
        user_prompt: str,
        runner: Any,
        llm: dict[str, Any],
        temperature: float,
        max_tokens: int,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        composed = self._compose_from_tools(
            system,
            user_prompt,
            runner,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        md = composed.get("content") or ""
        saved = self._store_report(symbol, kind, md) if composed.get("ok") else _empty_save()
        out = {
            "ok": bool(composed.get("ok")),
            "symbol": symbol,
            "name": name,
            "report_markdown": md if composed.get("ok") else "",
            "error": None
            if composed.get("ok")
            else (composed.get("error") or "模型返回了无效内容"),
            "model": composed.get("model") or self.cfg.get("llm_model") or "grok-4.6",
            "usage": composed.get("usage"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            **extra,
            **_agentic_fields(
                agentic=False,
                trace=runner.trace,
                rounds=llm.get("rounds"),
                budget_hit=llm.get("budget_hit"),
            ),
            **saved,
        }
        return out

    def _generate_vision_legacy(
        self,
        symbol: str,
        name: str = "",
        view: str = "day",
        range_: int = 250,
        ind: str = "macd",
        image: str = "",
        context: dict | None = None,
        deep: bool = False,
        with_news: bool = True,
    ) -> dict[str, Any]:
        """预检索 + 单轮 chat_vision 回落路径。"""
        ctx = context if isinstance(context, dict) else {}
        quote = ctx.get("quote") if isinstance(ctx.get("quote"), dict) else {}
        name = name or (quote.get("name") or "")
        label = f"{name}({symbol})" if name else symbol
        news: dict[str, Any] = {}
        if with_news:
            if self.yeux.available():
                q = f"{label} 最新 新闻 公告 业绩 资金流 主力 2026"
                news = self.yeux.search(q, deep=deep)
            else:
                news = {"ok": False, "error": "YeuX 未配置", "text": "", "tool": None}
        news_block = _format_vision_news(news, with_news=with_news)
        try:
            fund = fetch_finance_snapshot(symbol)
            fund_block = fund if fund else "快照未取到"
        except Exception as e:
            log.warning("finance snapshot failed: %s", e)
            fund_block = "快照未取到"
        user_prompt = _compose_vision_prompt(
            symbol=symbol,
            name=name,
            view=view,
            range_=range_,
            ind=ind,
            image=image,
            context=ctx,
            agentic=False,
            deep=deep,
            with_news=with_news,
            news=news,
            news_block=news_block,
            fund_block=fund_block,
        )
        llm = self.llm.chat_vision(
            SYSTEM_VISION,
            user_prompt,
            [image] if image else [],
            temperature=0.25,
            max_tokens=4000,
        )
        md = llm.get("content") or ""
        if not llm.get("ok"):
            md = ""
        if not _is_valid_report(md):
            return {
                "ok": False,
                "symbol": symbol,
                "name": name,
                "report_markdown": "",
                "error": llm.get("error") or "模型返回了无效内容",
                "model": llm.get("model") or self.cfg.get("llm_model") or "grok-4.6",
                "vision": False,
                "usage": llm.get("usage"),
                "news_ok": bool(news.get("ok")) if with_news else None,
                "agentic": False,
                "tool_trace": [],
                "tool_calls_count": 0,
                "rounds": 1 if llm.get("ok") else 0,
                "budget_hit": False,
                **_empty_save(),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        saved = self._store_report(symbol, "vision", md)
        return {
            "ok": bool(llm.get("ok")),
            "symbol": symbol,
            "name": name,
            "report_markdown": md,
            "error": None if llm.get("ok") else (llm.get("error") or "生成失败"),
            "model": llm.get("model") or self.cfg.get("llm_model") or "grok-4.6",
            "vision": bool(llm.get("vision")) if llm.get("ok") else False,
            "usage": llm.get("usage"),
            "news_ok": bool(news.get("ok")) if with_news else None,
            "agentic": False,
            "tool_trace": [],
            "tool_calls_count": 0,
            "rounds": 1 if llm.get("ok") else 0,
            "budget_hit": False,
            **saved,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


WATCH_SYMBOL = "WATCH"
_KINDS = ("report", "earnings", "news", "brief", "vision")

_VIEW_LABELS = {"day": "日K", "week": "周K", "minute": "分时", "min": "分时"}


def format_chart_view(view: str = "day", range_: int = 250, ind: str = "macd") -> str:
    """人类可读的图表视角，如「日K · 近1年 · MACD」。"""
    key = (view or "day").strip().lower()
    v = _VIEW_LABELS.get(key, view or "日K")
    try:
        n = int(range_)
    except (TypeError, ValueError):
        n = 250
    if n <= 0:
        r = "全部"
    elif key == "day" and n == 250:
        r = "近1年"
    elif key == "day" and n == 120:
        r = "近半年"
    elif key == "day" and n == 60:
        r = "近3月"
    elif key == "week" and n in (50, 52):
        r = "近1年"
    else:
        r = f"近{n}根"
    i = (ind or "macd").strip().upper() or "MACD"
    return f"{v} · {r} · {i}"


def _dash(v: Any, suffix: str = "") -> str:
    if v is None or v == "":
        return "—"
    return f"{v}{suffix}"


def _yi_yi(v: Any) -> str:
    """主力净流入（元）→ 亿元，保留 2 位。"""
    try:
        if v is None or v == "":
            return "—"
        return f"{float(v) / 1e8:.2f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_list(xs: Any) -> str:
    if not xs:
        return "—"
    if isinstance(xs, (list, tuple)):
        parts = [str(x) for x in xs if x not in (None, "")]
        return "、".join(parts) if parts else "—"
    return str(xs)


def _fmt_map(obj: Any) -> str:
    if not obj:
        return "—"
    if isinstance(obj, dict):
        parts = [f"{k}={v}" for k, v in obj.items() if v not in (None, "")]
        return "，".join(parts) if parts else "—"
    return str(obj)


def _is_valid_report(md: str) -> bool:
    """拒绝工具调用残留和过短正文，避免把垃圾稿落盘给用户。"""
    text = (md or "").strip()
    if len(text) < 200:
        return False
    lowered = text.lower()
    if "<tool_call>" in lowered:
        return False
    if '"arguments":' in text:
        return False
    return True


_YEUX_TOOL_NAMES = frozenset({"yeux_search", "yeux_deep_search"})
_FULL_RESULTS_CAP = 24000


def _join_full_results(blocks: list[str] | None, cap: int = _FULL_RESULTS_CAP) -> str:
    items = [str(b) for b in (blocks or []) if str(b).strip()]
    if not items:
        return "（无工具结果）"
    text = "\n\n".join(items)
    while len(items) > 1 and len(text) > cap:
        items.pop(0)
        text = "\n\n".join(items)
    if len(text) > cap:
        text = text[-cap:]
    return text


def _agentic_fields(
    *,
    agentic: bool = False,
    trace: list | None = None,
    rounds: Any = 0,
    budget_hit: Any = False,
) -> dict[str, Any]:
    items = list(trace or [])
    return {
        "agentic": bool(agentic),
        "tool_trace": items,
        "tool_calls_count": len(items),
        "rounds": int(rounds or 0),
        "budget_hit": bool(budget_hit),
    }


def _with_agentic_trace(legacy: dict[str, Any], runner: Any, llm: dict[str, Any]) -> dict[str, Any]:
    legacy["tool_trace"] = runner.trace
    legacy["tool_calls_count"] = len(runner.trace)
    if legacy.get("ok"):
        legacy["error"] = llm.get("error") or "模型返回了无效内容"
    return legacy


def _first_yeux_trace(trace: list[dict[str, Any]] | None) -> dict[str, Any]:
    items = [t for t in (trace or []) if str(t.get("name") or "") in _YEUX_TOOL_NAMES]
    for item in items:
        if item.get("ok"):
            return item
    return items[0] if items else {}


def _searches_from_trace(trace: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in trace or []:
        name = str(item.get("name") or "")
        if name not in _YEUX_TOOL_NAMES:
            continue
        args = item.get("args") if isinstance(item.get("args"), dict) else {}
        out.append(
            {
                "query": str(args.get("query") or ""),
                "ok": bool(item.get("ok")),
                "tool": name,
                "elapsed_sec": item.get("elapsed_sec"),
            }
        )
    return out


def _news_excerpt_from_trace(trace: list[dict[str, Any]] | None, limit: int = 4000) -> str:
    item = _first_yeux_trace(trace)
    if not item.get("ok"):
        return ""
    return str(item.get("summary") or "").strip()[:limit]


def _format_tech_brief(tech: dict[str, Any]) -> str:
    if not tech or tech.get("error"):
        return ""
    sig = tech.get("signal") or {}
    pred = tech.get("prediction") or sig.get("prediction") or {}
    return (
        f"动作={sig.get('action')} 综合分={sig.get('score')} 置信={sig.get('confidence')}\n"
        f"摘要={sig.get('plain_summary')}\n"
        f"模块={sig.get('module_scores')}\n"
        f"预测={pred}\n"
        f"交易计划={sig.get('trade_plan')}\n"
        f"风险={sig.get('risk_warnings')}\n"
    )


def _compose_report_agentic_prompt(
    *,
    symbol: str,
    name: str,
    focus: str,
    tech_brief: str,
    fund: Any,
    deep: bool,
) -> str:
    extra = "【工具】你可以调用工具检索消息面，并用本地行情/资金流/估值核对。本地数据比网络资讯更权威；冲突时必须再查一次核实。本次未预检索资讯。\n"
    if deep:
        extra += "本次允许深度检索，冲突核验时可使用 yeux_deep_search。\n"
    return f"""请为 A 股标的生成《投研速报》。

【标的】{name or ""} {symbol}
【关注重点】{focus}
【生成时间(UTC)】{datetime.now(timezone.utc).isoformat()}

【技术面引擎输出】
{tech_brief or "（未提供）"}

【公开行情/估值快照】（本地预取，仍可用 get_finance_snapshot / get_quote 复核）
{fund}

{extra}
请输出 Markdown，章节固定为：
# 标题
## 1. 一句话结论
## 2. 技术面解读
## 3. 新闻与事件催化
## 4. 基本面/财报线索（无数据则写「公开接口未取到，需人工核实」）
## 5. 多空逻辑与关键价位
## 6. 风险清单
## 7. 信息来源与局限
## 8. 调查过程（列出你调用了哪些工具、为什么、得到什么关键结论）
文末加：不构成投资建议。
"""


def _compose_earnings_agentic_prompt(
    *,
    label: str,
    period_hint: str,
    fund: Any,
    deep: bool,
) -> str:
    extra = (
        "【工具】你可以调用工具调查。必须先检索财报原始数据，再用 get_finance_snapshot 核对 PE/PB/市值口径。"
        "不同来源数字不一致时必须再检索确认正式披露口径，并在报告里说明分歧与取舍。\n"
    )
    if deep:
        extra += "本次允许深度检索，但最多一次；优先普通检索，仅在普通检索不够或数字冲突时使用 yeux_deep_search。\n"
    return f"""请撰写《{label} 财报/业绩专题分析》。

【期间提示】{period_hint}

【估值与行情快照】（本地预取，出稿前仍须用 get_finance_snapshot 核对）
{fund}

{extra}
请输出 Markdown，章节固定为：
# 标题
## 1. 一句话结论
## 2. 财报要点（表格：营收、净利、增速、毛利率/净利率、指引；无数据写「材料未披露/未检索到」）
## 3. 与预期/机构点评
## 4. 估值核对（对照本地快照，标注来源）
## 5. 数字分歧与取舍（若有）
## 6. 对股价含义与资金反应
## 7. 风险与后续观察点
## 8. 调查过程（列出你调用了哪些工具、为什么、得到什么关键结论）
文末加：不构成投资建议。
"""


def _format_vision_news(news: dict[str, Any], with_news: bool) -> str:
    """资讯检索正文：失败写明原因，无内容写「未检索到有效资讯」，正文截到 4000 字。"""
    if not with_news:
        return "本次未开启资讯检索"
    if not news.get("ok"):
        return f"检索失败：{news.get('error') or '未知错误'}"
    text = (news.get("text") or "").strip()
    if not text:
        return "未检索到有效资讯"
    return text[:4000]


def _compose_vision_prompt(
    *,
    symbol: str,
    name: str,
    view: str,
    range_: int,
    ind: str,
    image: str,
    context: dict | None,
    agentic: bool,
    deep: bool,
    with_news: bool,
    news: dict[str, Any] | None = None,
    news_block: str = "",
    fund_block: Any = "",
) -> str:
    label = f"{name}({symbol})" if name else symbol
    view_desc = format_chart_view(view, range_, ind)
    numbers = format_vision_context(context, name=name)
    if image:
        read_hint = "本次附有图表截图。请先阅读图中的 K 线、均线/指标与资金流，再结合下方数字上下文；图中看不清的内容标为未知，禁止脑补。"
    else:
        read_hint = "本次无图表，仅基于数字上下文。"
    extra = ""
    if agentic:
        extra = (
            "\n【工具】你可以调用工具调查。本地数据（get_fund_flow / get_quote / get_klines 等）"
            "比网络资讯更权威；资讯数字与本地冲突时必须再查一次核实。\n"
        )
        if deep:
            extra += "本次允许深度检索，冲突核验时可使用 yeux_deep_search。\n"
        if not with_news:
            extra += (
                "本次未开启资讯检索，资讯工具不可用，请仅基于图表、数字上下文与本地数据工具作答。\n"
            )
    else:
        news = news or {}
        extra = (
            f"\n【最新资讯检索】tool={news.get('tool') if with_news else None} "
            f"ok={news.get('ok') if with_news else None} elapsed={news.get('elapsed_sec') if with_news else None}\n"
            f"{news_block}\n\n"
            f"【基本面/估值快照】\n{fund_block}\n"
        )
    chapters = f"""请输出 Markdown，章节固定为：
# {name or symbol}({symbol}) 看图 · 大资金研判
## 1. 一句话结论（流入/出逃/拉锯，含置信度 高/中/低）
## 2. 资金证据（主力净流入、量价配合、大单迹象）
## 3. 技术结构佐证（趋势/均线/中枢/关键位）
## 4. 最新资讯与催化（标注来源线索；未检索到则写明，禁止编造）
## 5. 反证与风险
## 6. 观察触发点（什么走势确认或证伪上述判断）"""
    if agentic:
        chapters += "\n## 7. 调查过程（列出你调用了哪些工具、为什么、得到什么关键结论）"
    return f"""请对以下 A 股标的做「看图 · 大资金研判」。

【标的】{label}
【图表视角】{view_desc}
【读图说明】{read_hint}

【数字上下文】
{numbers}
{extra}
{chapters}
文末加：不构成投资建议。
"""


def format_vision_context(context: dict | None, name: str = "") -> str:
    """把 quote/signal/prediction/flows 拼成紧凑【数字上下文】，缺字段容错。"""
    ctx = context if isinstance(context, dict) else {}
    quote = ctx.get("quote") if isinstance(ctx.get("quote"), dict) else {}
    signal = ctx.get("signal") if isinstance(ctx.get("signal"), dict) else {}
    pred = ctx.get("prediction")
    if not isinstance(pred, dict):
        pred = signal.get("prediction") if isinstance(signal.get("prediction"), dict) else {}
    flows = ctx.get("flows") if isinstance(ctx.get("flows"), list) else []

    q_name = quote.get("name") or name or "—"
    lines = [
        f"行情：名称={q_name} 现价={_dash(quote.get('price'))} "
        f"涨跌幅={_dash(quote.get('pct'), '%')} 换手={_dash(quote.get('turnover'), '%')}",
        f"信号：动作={_dash(signal.get('action'))} 综合分={_dash(signal.get('score'))}",
        f"买入信号={_fmt_list(signal.get('buy_signals'))}",
        f"卖出信号={_fmt_list(signal.get('sell_signals'))}",
        f"关键价位={_fmt_map(signal.get('key_levels'))}",
        f"交易计划={_fmt_map(signal.get('trade_plan'))}",
        f"预测：方向={_dash(pred.get('direction'))} 倾向={_dash(pred.get('tilt') if pred.get('tilt') is not None else pred.get('prob_up'))}",
        f"驱动={_fmt_list(pred.get('drivers'))}",
    ]
    recent = [f for f in flows[-10:] if isinstance(f, dict)]
    if recent:
        flow_bits = []
        for f in recent:
            flow_bits.append(f"{f.get('date') or '?'} {_yi_yi(f.get('main_net'))}亿")
        lines.append("主力净流入(近10日, 亿元)：" + "，".join(flow_bits))
    else:
        lines.append("主力净流入(近10日, 亿元)：—")
    return "\n".join(lines)


def _normalize_symbols(symbols: list[str]) -> list[str]:
    out: list[str] = []
    for raw in symbols or []:
        code = "".join(ch for ch in str(raw) if ch.isdigit())[:6]
        if len(code) == 6 and code not in out:
            out.append(code)
    return out


def row_from_analyze(symbol: str, payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("error"):
        return {
            "symbol": symbol,
            "name": "",
            "action": "失败",
            "score": None,
            "confidence": None,
            "pct": None,
            "summary": str(payload.get("error") or "分析失败"),
            "ok": False,
        }
    quote = payload.get("quote") or {}
    sig = payload.get("signal") or {}
    return {
        "symbol": symbol,
        "name": quote.get("name") or "",
        "action": sig.get("action") or "观望",
        "score": sig.get("score"),
        "confidence": sig.get("confidence"),
        "pct": quote.get("pct"),
        "summary": (sig.get("plain_summary") or "")[:120],
        "ok": True,
    }


def format_watch_brief_markdown(
    rows: list[dict[str, Any]],
    *,
    news_text: str = "",
    llm_text: str = "",
    generated_at: str = "",
) -> str:
    lines = ["# 自选晨报", ""]
    if generated_at:
        lines.append(f"生成时间（UTC）{generated_at}")
        lines.append("")
    lines.extend(
        [
            "| 代码 | 名称 | 动作 | 综合分 | 涨跌% | 一句话 |",
            "|------|------|------|--------|-------|--------|",
        ]
    )
    for row in rows:
        pct = row.get("pct")
        pct_s = "—" if pct is None else f"{pct}"
        score = row.get("score")
        score_s = "—" if score is None else str(score)
        summary = str(row.get("summary") or "").replace("|", "/")
        lines.append(
            f"| {row.get('symbol', '')} | {row.get('name', '')} | {row.get('action', '')} | "
            f"{score_s} | {pct_s} | {summary} |"
        )
    lines.append("")
    lines.append("> 技术面来自本地规则引擎；资讯与点评可能滞后或有误。不构成投资建议。")
    lines.append("")
    if (news_text or "").strip():
        lines.extend(["## 市场检索", "", news_text.strip(), ""])
    if (llm_text or "").strip():
        lines.extend(["## 组合点评", "", llm_text.strip(), ""])
    return "\n".join(lines).rstrip() + "\n"


def store_policy() -> dict[str, Any]:
    ttl, replace = _store_settings()
    return {"ttl_hours": ttl, "replace_same_kind": replace}


def _store_settings() -> tuple[float, bool]:
    try:
        cfg = get_settings().research
        ttl = float(cfg.ttl_hours)
        replace = bool(cfg.replace_same_kind)
        if ttl <= 0:
            ttl = 24.0
        return ttl, replace
    except Exception:
        return 24.0, True


def _reports_dir(folder: Path | None = None) -> Path:
    if folder is not None:
        return Path(folder)
    # Retain the donor tests' explicit ROOT monkeypatch without using the
    # package/source directory as the installed application's data location.
    if ROOT != _INITIAL_ROOT:
        return ROOT / "data" / "reports"
    settings = get_settings()
    return settings.resolve_data_path(settings.research.report_dir)


def _parse_report_name(name: str) -> Optional[dict[str, str]]:
    stem = name[:-3] if name.endswith(".md") else name
    parts = stem.split("_")
    if len(parts) < 3:
        return None
    kind = parts[1]
    if kind not in _KINDS:
        return None
    return {"symbol": parts[0], "kind": kind, "stamp": "_".join(parts[2:])}


def _empty_save() -> dict[str, Any]:
    ttl, replace = _store_settings()
    return {
        "report_id": "",
        "saved_path": "",
        "filename": "",
        "ttl_hours": ttl,
        "replace_same_kind": replace,
        "purged_expired": 0,
        "purged_replaced": 0,
    }


def _report_store(
    folder: Path | None = None,
    *,
    ttl_hours: float | None = None,
) -> ReportStore:
    ttl, replace = _store_settings()
    try:
        max_bytes = int(get_settings().research.max_report_bytes)
    except Exception:
        max_bytes = 2 * 1024 * 1024
    return ReportStore(
        _reports_dir(folder),
        ttl_hours=ttl if ttl_hours is None else ttl_hours,
        replace_same_kind=replace,
        max_bytes=max_bytes,
    )


_LEGACY_REPORT_PATTERN = re.compile(
    r"^(?:[0-9]{6}|WATCH)_(?:report|earnings|news|brief|vision)_"
    r"[0-9]{8}_[0-9]{6}\.md$",
    re.ASCII,
)


def _purge_expired_legacy(root: Path, cutoff: float) -> int:
    """Remove only strictly recognized pre-integration reports."""

    if not root.is_dir():
        return 0
    removed = 0
    for candidate in root.iterdir():
        if _LEGACY_REPORT_PATTERN.fullmatch(candidate.name) is None:
            continue
        try:
            details = os.lstat(candidate)
            if not stat.S_ISREG(details.st_mode) or details.st_mtime >= cutoff:
                continue
            candidate.unlink()
            removed += 1
        except OSError:
            log.warning("无法删除过期的旧格式研报 %s", candidate.name)
    return removed


def purge_expired_reports(
    folder: Path | None = None,
    ttl_hours: float | None = None,
    now: float | None = None,
) -> int:
    """删除超过 TTL 的研报文件，返回删除数量。"""
    ttl = float(ttl_hours) if ttl_hours is not None else _store_settings()[0]
    if ttl <= 0:
        return 0
    timestamp = time.time() if now is None else now
    reference = datetime.fromtimestamp(timestamp, timezone.utc)
    store = _report_store(folder, ttl_hours=ttl)
    removed = store.purge_expired(now=reference)
    return removed + _purge_expired_legacy(store.root, timestamp - ttl * 3600)


def _save_report(
    symbol: str,
    kind: str,
    markdown: str,
    folder: Path | None = None,
    *,
    store: ReportStore | None = None,
) -> dict[str, Any]:
    meta = _empty_save()
    if not isinstance(markdown, str) or not markdown.strip() or kind not in _KINDS:
        return meta
    ttl, replace = _store_settings()
    selected = store or _report_store(folder)
    stored = selected.save(symbol, kind, markdown)
    path = selected.root / stored.report_id.value
    meta.update(
        {
            "report_id": stored.report_id.value,
            "saved_path": str(path),
            "filename": stored.report_id.value,
            "ttl_hours": ttl,
            "replace_same_kind": replace,
            "purged_expired": stored.purged_expired,
            "purged_replaced": stored.purged_replaced,
        }
    )
    return meta


def _item_from_stored(stored: Any, *, now: datetime | None = None) -> dict[str, Any]:
    reference = datetime.now(timezone.utc) if now is None else now.astimezone(timezone.utc)
    report_id = stored.report_id.value
    created_at = stored.created_at
    remain = max(0, int((stored.expires_at - reference).total_seconds()))
    return {
        "report_id": report_id,
        "filename": report_id,
        "symbol": stored.subject,
        "kind": stored.kind.value,
        "stamp": created_at.astimezone().strftime("%Y%m%d_%H%M%S"),
        "bytes": stored.size_bytes,
        "mtime": created_at.astimezone().isoformat(timespec="seconds"),
        "expires_at": stored.expires_at.isoformat(timespec="seconds"),
        "ttl_remain_sec": remain,
    }


def list_saved_reports(
    symbol: str = "",
    limit: int = 40,
    folder: Path | None = None,
    *,
    store: ReportStore | None = None,
) -> list[dict[str, Any]]:
    ttl, _ = _store_settings()
    selected = store or _report_store(folder)
    selected.purge_expired()
    _purge_expired_legacy(selected.root, time.time() - ttl * 3600)
    try:
        rows = selected.list(
            subject=symbol.strip() or None,
            limit=max(1, min(limit, 80)),
        )
    except ReportStoreError:
        return []
    return [_item_from_stored(row) for row in rows]


def read_saved_report(
    report_id: str,
    folder: Path | None = None,
    *,
    store: ReportStore | None = None,
) -> dict[str, Any]:
    ttl, _ = _store_settings()
    selected = store or _report_store(folder)
    try:
        document = selected.read(report_id)
    except (ReportExpiredError, ReportNotFoundError):
        return {"ok": False, "error": "文件不存在或已过期"}
    except (ReportStoreError, ValueError):
        return {"ok": False, "error": "非法研报标识"}
    item = _item_from_stored(document.metadata)
    return {
        "ok": True,
        "report_id": document.metadata.report_id.value,
        "filename": document.metadata.report_id.value,
        "markdown": document.markdown,
        **item,
        "saved_path": str(selected.root / document.metadata.report_id.value),
        "ttl_hours": ttl,
    }
