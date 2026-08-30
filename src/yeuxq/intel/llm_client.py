"""OpenAI 兼容 Chat Completions（Grok-4.6 + reasoning_effort）。"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

log = logging.getLogger("yeuxq.llm")

# data URI 字符数上限（约 8MB），超限则调用前丢弃，避免网关拒收大包
MAX_VISION_IMAGE_CHARS = 8 * 1024 * 1024
_VISION_FAIL_HINTS = ("image", "vision", "multimodal", "modal")
_TOOL_FAIL_HINTS = ("tool", "function")
_WRAP_UP_USER = "调查预算已用尽。请立即基于已获得的全部信息输出最终报告，不要再请求任何工具。"
# 工具轮 180s + 收尾独立 150s。剩余不足 45s 不再开新工具轮。整体硬上限约 330 秒。
AGENTIC_TOOL_BUDGET_SEC = 180.0
AGENTIC_WRAP_UP_SEC = 150.0
AGENTIC_MIN_ROUND_SEC = 45.0
AGENTIC_WALL_CLOCK_CAP_SEC = 330.0
_GATEWAY_TIMEOUT_STATUSES = frozenset({502, 503, 504, 524})
_WRAP_UP_COMPRESS_CHARS = 30000
_WRAP_UP_TOOL_CLIP = 1500


def _filter_vision_images(images: list[str] | None) -> list[str]:
    kept: list[str] = []
    for img in images or []:
        if not str(img).strip():
            continue
        if len(img) > MAX_VISION_IMAGE_CHARS:
            log.warning(
                "drop oversized vision image (%s chars > %s)",
                len(img),
                MAX_VISION_IMAGE_CHARS,
            )
            continue
        kept.append(img)
    return kept


def _vision_user_content(prompt: str, images: list[str]) -> tuple[Any, bool]:
    kept = _filter_vision_images(images)
    if kept:
        user_content: Any = [{"type": "text", "text": prompt}]
        for url in kept:
            user_content.append({"type": "image_url", "image_url": {"url": url}})
        return user_content, True
    return prompt, False


def _add_usage(acc: dict[str, int], usage: Any) -> None:
    if not isinstance(usage, dict):
        return
    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        try:
            acc[k] += int(usage.get(k) or 0)
        except (TypeError, ValueError):
            pass


def _message_content(data: dict) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    content = msg.get("content") or ""
    if isinstance(content, list):
        parts: list[str] = []
        for p in content:
            if isinstance(p, dict):
                parts.append(str(p.get("text") or ""))
            elif p:
                parts.append(str(p))
        return "".join(parts)
    return content if isinstance(content, str) else str(content)


def _approx_messages_chars(messages: list[dict[str, Any]]) -> int:
    try:
        return len(json.dumps(messages, ensure_ascii=False, default=str))
    except Exception:
        return sum(len(str(m)) for m in messages)


def _clip_message_text(content: Any, clip: int) -> Any:
    if isinstance(content, str) and len(content) > clip:
        return content[:clip] + "…（已截断）"
    return content


def _compress_messages_for_wrap_up(
    messages: list[dict[str, Any]],
    *,
    limit: int = _WRAP_UP_COMPRESS_CHARS,
    clip: int = _WRAP_UP_TOOL_CLIP,
) -> None:
    """收尾前压缩：保留 system + 首条 user，tool 结果各截到 clip 字。"""
    if _approx_messages_chars(messages) <= limit:
        return
    for i, msg in enumerate(messages):
        if i < 2:
            continue
        if msg.get("role") == "tool":
            msg["content"] = _clip_message_text(msg.get("content"), clip)
        elif msg.get("role") == "assistant" and msg.get("tool_calls"):
            continue
        elif msg.get("role") in {"user", "assistant"}:
            msg["content"] = _clip_message_text(msg.get("content"), clip)


class LlmClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = "grok-4.6",
        timeout: float = 240.0,
        reasoning_effort: str = "xhigh",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.reasoning_effort = reasoning_effort

    def available(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        if not self.available():
            return {
                "ok": False,
                "error": "LLM 未配置：请设置 YEUXQ_LLM_API_KEY",
                "content": "",
            }
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        try:
            with httpx.Client(timeout=self.timeout, trust_env=False) as client:
                r = client.post(url, headers=headers, json=payload)
                if r.status_code >= 400:
                    # 个别网关不认 reasoning_effort，降级再试一次
                    if self.reasoning_effort and "reasoning" in (r.text or "").lower():
                        payload.pop("reasoning_effort", None)
                        r = client.post(url, headers=headers, json=payload)
                if r.status_code >= 400:
                    return {
                        "ok": False,
                        "error": f"HTTP {r.status_code}: {r.text[:500]}",
                        "content": "",
                    }
                data = r.json()
                return {
                    "ok": True,
                    "content": _message_content(data),
                    "model": data.get("model", self.model),
                    "usage": data.get("usage"),
                    "raw": data,
                }
        except Exception as e:
            log.exception("llm chat failed")
            return {"ok": False, "error": str(e), "content": ""}

    def chat_vision(
        self,
        system: str,
        prompt: str,
        images: list[str],
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """OpenAI vision 数组格式；网关拒图时降级为纯文本（vision=False）。"""
        if not self.available():
            return {
                "ok": False,
                "error": "LLM 未配置：请设置 YEUXQ_LLM_API_KEY",
                "content": "",
                "vision": False,
            }
        user_content, use_vision = _vision_user_content(prompt, images)

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort

        def _fail(err: str) -> dict[str, Any]:
            return {"ok": False, "error": err, "content": "", "vision": False}

        try:
            with httpx.Client(timeout=self.timeout, trust_env=False) as client:
                r = client.post(url, headers=headers, json=payload)
                # 图片降级须在 reasoning 降级之前
                if r.status_code >= 400 and use_vision:
                    body = (r.text or "").lower()
                    if any(k in body for k in _VISION_FAIL_HINTS):
                        use_vision = False
                        payload["messages"] = [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ]
                        r = client.post(url, headers=headers, json=payload)
                if r.status_code >= 400:
                    if self.reasoning_effort and "reasoning" in (r.text or "").lower():
                        payload.pop("reasoning_effort", None)
                        r = client.post(url, headers=headers, json=payload)
                if r.status_code >= 400:
                    return _fail(f"HTTP {r.status_code}: {r.text[:500]}")
                data = r.json()
                return {
                    "ok": True,
                    "content": _message_content(data),
                    "model": data.get("model", self.model),
                    "usage": data.get("usage"),
                    "raw": data,
                    "vision": use_vision,
                }
        except Exception as e:
            log.exception("llm chat_vision failed")
            return _fail(str(e))

    def chat_agentic(
        self,
        system: str,
        prompt: str,
        images: list[str],
        tools: list[dict],
        tool_runner: Any,
        temperature: float = 0.25,
        max_tokens: int = 4000,
        max_rounds: int = 6,
        total_budget_sec: float = AGENTIC_TOOL_BUDGET_SEC,
        tool_round_reasoning_effort: str | None = "low",
    ) -> dict[str, Any]:
        """带 tools 的多轮 function calling；预算耗尽时强制不带 tools 收尾出稿。

        工具选择轮使用 tool_round_reasoning_effort（默认 low；空则不传该字段）。
        收尾合成轮仍用 self.reasoning_effort（通常 xhigh）。
        挂钟：工具轮预算 total_budget_sec（默认 180s）；剩余不足 45s 不再开新工具轮，
        改为收尾。收尾不占用工具轮预算，单独 min(self.timeout, 150)s。
        整体硬上限约 330 秒，前端超时应对齐 360s 余量。
        """

        def _out(
            *,
            ok: bool,
            content: str = "",
            error: str | None = None,
            vision: bool = False,
            rounds: int = 0,
            budget_hit: bool = False,
            tools_unsupported: bool = False,
            usage: dict[str, int] | None = None,
            model: str | None = None,
        ) -> dict[str, Any]:
            return {
                "ok": ok,
                "content": content,
                "model": model or self.model,
                "usage": usage,
                "rounds": rounds,
                "vision": vision,
                "budget_hit": budget_hit,
                "tools_unsupported": tools_unsupported,
                "error": error,
            }

        if not self.available():
            return _out(
                ok=False,
                error="LLM 未配置：请设置 YEUXQ_LLM_API_KEY",
            )

        user_content, use_vision = _vision_user_content(prompt, images)
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]
        usage_acc = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        has_usage = False
        rounds = 0
        t0 = time.time()
        model_name = self.model

        def _payload(with_tools: bool) -> dict[str, Any]:
            body: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            effort = tool_round_reasoning_effort if with_tools else self.reasoning_effort
            if effort:
                body["reasoning_effort"] = effort
            if with_tools and tools:
                body["tools"] = tools
                body["tool_choice"] = "auto"
            return body

        def _post(
            client: httpx.Client,
            body: dict[str, Any],
            *,
            has_tools: bool,
            timeout: float,
        ) -> Any:
            try:
                r = client.post(url, headers=headers, json=body, timeout=timeout)
                if r.status_code in _GATEWAY_TIMEOUT_STATUSES:
                    return ("timeout", r)
                if r.status_code >= 400:
                    text = (r.text or "").lower()
                    # 先 reasoning 降级，再判断是否真的不支持 tools
                    if "reasoning_effort" in body and "reasoning" in text:
                        body.pop("reasoning_effort", None)
                        r = client.post(url, headers=headers, json=body, timeout=timeout)
                if r.status_code in _GATEWAY_TIMEOUT_STATUSES:
                    return ("timeout", r)
                if r.status_code >= 400:
                    text = (r.text or "").lower()
                    if has_tools and any(k in text for k in _TOOL_FAIL_HINTS):
                        return ("unsupported", r)
                    return ("error", r)
                return ("ok", r)
            except httpx.TimeoutException as e:
                return ("timeout", e)

        try:
            with httpx.Client(timeout=self.timeout, trust_env=False) as client:
                while rounds < max_rounds:
                    elapsed = time.time() - t0
                    remaining = total_budget_sec - elapsed
                    if (
                        getattr(tool_runner, "exhausted", False)
                        or remaining < AGENTIC_MIN_ROUND_SEC
                    ):
                        break
                    post_timeout = min(float(self.timeout), remaining)
                    body = _payload(True)
                    tag, r = _post(client, body, has_tools=True, timeout=post_timeout)
                    rounds += 1
                    if tag == "timeout":
                        log.warning(
                            "agentic tool-round timeout, wrap up with collected tool results"
                        )
                        break
                    if tag == "unsupported":
                        return _out(
                            ok=False,
                            error=f"HTTP {r.status_code}: {r.text[:500]}",
                            vision=use_vision,
                            rounds=rounds,
                            tools_unsupported=True,
                            usage=usage_acc if has_usage else None,
                        )
                    if tag != "ok":
                        return _out(
                            ok=False,
                            error=f"HTTP {r.status_code}: {r.text[:500]}",
                            vision=use_vision,
                            rounds=rounds,
                            usage=usage_acc if has_usage else None,
                        )
                    data = r.json()
                    model_name = data.get("model", model_name)
                    if data.get("usage"):
                        _add_usage(usage_acc, data.get("usage"))
                        has_usage = True
                    choices = data.get("choices") or []
                    msg = (choices[0].get("message") or {}) if choices else {}
                    tool_calls = msg.get("tool_calls") or []
                    if tool_calls:
                        messages.append(msg)
                        for tc in tool_calls:
                            fn = tc.get("function") or {}
                            name = str(fn.get("name") or "")
                            raw_args = fn.get("arguments") if "arguments" in fn else "{}"
                            parse_note = ""
                            try:
                                if isinstance(raw_args, str):
                                    parsed = json.loads(raw_args) if raw_args.strip() else {}
                                elif isinstance(raw_args, dict):
                                    parsed = raw_args
                                else:
                                    parsed = {}
                                    parse_note = "工具参数解析失败，已按空参数执行。"
                            except Exception:
                                parsed = {}
                                parse_note = "工具参数解析失败，已按空参数执行。"
                            if not isinstance(parsed, dict):
                                parsed = {}
                                parse_note = "工具参数解析失败，已按空参数执行。"
                            result = tool_runner.run(name, parsed)
                            if parse_note:
                                result = parse_note + "\n" + result
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tc.get("id") or "",
                                    "content": result,
                                }
                            )
                        continue
                    content = _message_content(data)
                    if content:
                        return _out(
                            ok=True,
                            content=content,
                            vision=use_vision,
                            rounds=rounds,
                            usage=usage_acc if has_usage else None,
                            model=model_name,
                        )
                    break

                _compress_messages_for_wrap_up(messages)
                messages.append({"role": "user", "content": _WRAP_UP_USER})
                body = _payload(False)
                wrap_timeout = min(float(self.timeout), AGENTIC_WRAP_UP_SEC)
                tag, r = _post(client, body, has_tools=False, timeout=wrap_timeout)
                rounds += 1
                if tag == "timeout":
                    code = getattr(r, "status_code", None)
                    err = f"收尾请求超时: HTTP {code}" if code else f"收尾请求超时: {r}"
                    return _out(
                        ok=False,
                        error=err,
                        vision=use_vision,
                        rounds=rounds,
                        budget_hit=True,
                        usage=usage_acc if has_usage else None,
                    )
                if tag != "ok":
                    return _out(
                        ok=False,
                        error=f"HTTP {r.status_code}: {r.text[:500]}",
                        vision=use_vision,
                        rounds=rounds,
                        budget_hit=True,
                        usage=usage_acc if has_usage else None,
                    )
                data = r.json()
                model_name = data.get("model", model_name)
                if data.get("usage"):
                    _add_usage(usage_acc, data.get("usage"))
                    has_usage = True
                return _out(
                    ok=True,
                    content=_message_content(data),
                    vision=use_vision,
                    rounds=rounds,
                    budget_hit=True,
                    usage=usage_acc if has_usage else None,
                    model=model_name,
                )
        except Exception as e:
            log.exception("llm chat_agentic failed")
            return _out(ok=False, error=str(e), vision=use_vision, rounds=rounds)
