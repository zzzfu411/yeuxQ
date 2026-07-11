"""OpenAI-compatible advisory LLM client.

The client is deliberately read-only from the trading system's point of view:
it consumes a prompt pack and returns narrative review text. It never modifies
the deterministic gate decision and never talks to broker code.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from quantify.llm.reviewer import PromptPack

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


@dataclass(frozen=True, slots=True)
class LLMClientConfig:
    base_url: str = DEFAULT_OPENAI_BASE_URL
    api_key: str | None = None
    model: str = DEFAULT_OPENAI_MODEL
    timeout_seconds: float = 60.0

    @classmethod
    def from_env(
        cls,
        *,
        model: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> LLMClientConfig:
        return cls(
            base_url=os.getenv("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
            api_key=os.getenv("OPENAI_API_KEY"),
            model=model or os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
            timeout_seconds=timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class LLMNarrativeReview:
    provider: str
    model: str
    content: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "provider": self.provider,
            "model": self.model,
            "ok": self.ok,
            "content": self.content,
            "error": self.error,
        }

    def to_markdown(self) -> str:
        lines = [
            "# Advisory LLM Narrative Review",
            "",
            f"- Provider: `{self.provider}`",
            f"- Model: `{self.model}`",
            f"- Status: `{'ok' if self.ok else 'error'}`",
            "",
        ]
        if self.error:
            lines.extend(
                [
                    "## Error",
                    "",
                    self.error,
                    "",
                    "The deterministic review files were still produced. This advisory error does not "
                    "change the PASS/WATCH/BLOCK decision.",
                ]
            )
        else:
            lines.extend(["## Narrative", "", self.content])
        return "\n".join(lines).rstrip() + "\n"


class LLMClient:
    """Minimal OpenAI-compatible chat completions client."""

    provider = "openai_compatible"

    def __init__(self, config: LLMClientConfig) -> None:
        self.config = config

    def review(self, prompt: PromptPack) -> LLMNarrativeReview:
        if not self.config.api_key:
            return LLMNarrativeReview(
                provider=self.provider,
                model=self.config.model,
                error="OPENAI_API_KEY is not configured; skipped advisory LLM call.",
            )

        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
            ],
            "temperature": 0.2,
        }
        try:
            response = self._post_chat_completions(payload)
            content = _extract_message_content(response)
            return LLMNarrativeReview(
                provider=self.provider,
                model=self.config.model,
                content=content,
            )
        except Exception as exc:  # noqa: BLE001 - advisory errors must not abort the gate.
            return LLMNarrativeReview(
                provider=self.provider,
                model=self.config.model,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _post_chat_completions(self, payload: dict[str, object]) -> dict[str, object]:
        base_url = self.config.base_url.rstrip("/")
        url = f"{base_url}/chat/completions"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url=url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM provider returned HTTP {exc.code}: {detail}") from exc
        return json.loads(raw)


def _extract_message_content(response: dict[str, object]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("LLM response has no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise ValueError("LLM response choice is malformed")
    message = first.get("message")
    if not isinstance(message, dict):
        raise ValueError("LLM response choice has no message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("LLM response message has empty content")
    return content.strip()
