"""YeuX MCP Streamable HTTP 客户端（yeux_search / yeux_deep_search）。"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any, Optional

import httpx

log = logging.getLogger("yeuxq.yeux")


def _parse_sse_jsonrpc(text: str) -> list[dict[str, Any]]:
    """从 SSE 文本中提取 JSON-RPC 消息。"""
    messages: list[dict[str, Any]] = []
    # 按 data: 行拼接
    data_buf: list[str] = []
    for line in text.splitlines():
        if line.startswith("data:"):
            payload = line[5:].lstrip()
            if payload == "":
                continue
            data_buf.append(payload)
        elif line.strip() == "" and data_buf:
            raw = "\n".join(data_buf)
            data_buf = []
            try:
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    messages.append(obj)
            except json.JSONDecodeError:
                # 有时一行一个完整 JSON
                for part in raw.split("\n"):
                    part = part.strip()
                    if not part:
                        continue
                    try:
                        obj = json.loads(part)
                        if isinstance(obj, dict):
                            messages.append(obj)
                    except json.JSONDecodeError:
                        continue
    if data_buf:
        raw = "\n".join(data_buf)
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                messages.append(obj)
        except json.JSONDecodeError:
            # 兜底：全文找 JSON 对象
            for m in re.finditer(r"\{.*\}", text, re.S):
                try:
                    obj = json.loads(m.group(0))
                    if isinstance(obj, dict) and ("result" in obj or "error" in obj or "id" in obj):
                        messages.append(obj)
                        break
                except json.JSONDecodeError:
                    continue
    if not messages:
        # 非 SSE 纯 JSON
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                messages.append(obj)
        except json.JSONDecodeError:
            pass
    return messages


def _extract_tool_text(result: Any) -> str:
    """从 tools/call result 抽出可读文本。"""
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        if "content" in result:
            parts = []
            content = result["content"]
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            parts.append(str(item.get("text", "")))
                        else:
                            parts.append(json.dumps(item, ensure_ascii=False))
                    else:
                        parts.append(str(item))
            else:
                parts.append(str(content))
            return "\n".join(parts)
        if "structuredContent" in result:
            return json.dumps(result["structuredContent"], ensure_ascii=False, indent=2)
        return json.dumps(result, ensure_ascii=False, indent=2)
    return str(result)


class YeuxMcpClient:
    """短会话 MCP 客户端：每次搜索 initialize → call → 结束。"""

    def __init__(
        self,
        url: str,
        token: str,
        timeout: float = 180.0,
    ) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._id = 0
        self._lock = threading.Lock()

    def available(self) -> bool:
        return bool(self.url and self.token)

    def _next_id(self) -> int:
        with self._lock:
            self._id += 1
            return self._id

    def _headers(self, session_id: Optional[str] = None) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if session_id:
            h["Mcp-Session-Id"] = session_id
        return h

    def _post(
        self, client: httpx.Client, body: dict, session_id: Optional[str] = None
    ) -> tuple[httpx.Response, list[dict]]:
        r = client.post(self.url, headers=self._headers(session_id), json=body)
        msgs = _parse_sse_jsonrpc(r.text)
        return r, msgs

    def search(self, query: str, deep: bool = False) -> dict[str, Any]:
        """调用 yeux_search 或 yeux_deep_search。"""
        if not self.available():
            return {
                "ok": False,
                "error": "YeuX 未配置：请设置 YEUXQ_YEUX_MCP_TOKEN",
                "text": "",
                "tool": None,
            }
        tool = "yeux_deep_search" if deep else "yeux_search"
        t0 = time.time()
        try:
            with httpx.Client(timeout=self.timeout, trust_env=False) as client:
                # 1) initialize
                init_body = {
                    "jsonrpc": "2.0",
                    "id": self._next_id(),
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "yeuxQ", "version": "2.0.0"},
                    },
                }
                r, msgs = self._post(client, init_body)
                sid = r.headers.get("mcp-session-id") or r.headers.get("Mcp-Session-Id")
                if not sid:
                    return {
                        "ok": False,
                        "error": "MCP 未返回 session id",
                        "text": r.text[:500],
                        "tool": tool,
                    }

                # 2) notifications/initialized
                client.post(
                    self.url,
                    headers=self._headers(sid),
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                )

                # 3) tools/call
                call_body = {
                    "jsonrpc": "2.0",
                    "id": self._next_id(),
                    "method": "tools/call",
                    "params": {"name": tool, "arguments": {"query": query}},
                }
                r2, msgs2 = self._post(client, call_body, sid)
                elapsed = round(time.time() - t0, 2)

                # 找带 result 的消息
                result_msg = None
                for m in msgs2:
                    if m.get("result") is not None or m.get("error") is not None:
                        result_msg = m
                        break
                if result_msg is None and msgs2:
                    result_msg = msgs2[-1]

                if result_msg is None:
                    return {
                        "ok": False,
                        "error": f"空响应 status={r2.status_code}",
                        "text": r2.text[:1000],
                        "tool": tool,
                        "elapsed_sec": elapsed,
                    }
                if result_msg.get("error"):
                    return {
                        "ok": False,
                        "error": str(result_msg["error"]),
                        "text": "",
                        "tool": tool,
                        "elapsed_sec": elapsed,
                    }
                text = _extract_tool_text(result_msg.get("result"))
                return {
                    "ok": True,
                    "tool": tool,
                    "query": query,
                    "text": text,
                    "elapsed_sec": elapsed,
                    "raw_result": result_msg.get("result"),
                }
        except Exception as e:
            log.exception("yeux search failed")
            return {
                "ok": False,
                "error": str(e),
                "text": "",
                "tool": tool,
                "elapsed_sec": round(time.time() - t0, 2),
            }
