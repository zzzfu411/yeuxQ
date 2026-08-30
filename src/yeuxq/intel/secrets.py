"""Build advisory-client configuration without reading secrets from files."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yeuxq.security import RuntimeSecrets


_DEFAULTS: dict[str, object] = {
    "llm_base_url": "https://grok.yeuxark.com/v1",
    "llm_model": "grok-4.6",
    "llm_reasoning_effort": "xhigh",
    "llm_timeout": 240.0,
    "yeux_mcp_url": "https://search.yeuxark.com/mcp",
    "yeux_timeout": 360.0,
}


def _public_value(config: object | None, name: str) -> object:
    if config is None:
        return _DEFAULTS[name]
    if isinstance(config, Mapping):
        return config.get(name, _DEFAULTS[name])
    return getattr(config, name, _DEFAULTS[name])


def _norm_base(url: str) -> str:
    candidate = (url or "").strip().rstrip("/")
    if candidate.endswith("/chat/completions"):
        candidate = candidate[: -len("/chat/completions")]
    if candidate and not candidate.endswith("/v1"):
        candidate += "/v1"
    return candidate


def _secret_value(secret: object | None) -> str:
    if secret is None:
        return ""
    getter = getattr(secret, "get_secret_value", None)
    return str(getter()) if callable(getter) else ""


def load_intel_config(
    public_config: object | None = None,
    runtime_secrets: RuntimeSecrets | None = None,
) -> dict[str, Any]:
    """Return public endpoints plus secrets from the documented environment only."""

    secrets = runtime_secrets or RuntimeSecrets.from_env()
    return {
        "llm_base_url": _norm_base(str(_public_value(public_config, "llm_base_url"))),
        "llm_api_key": _secret_value(secrets.llm_api_key),
        "llm_model": str(_public_value(public_config, "llm_model") or "grok-4.6"),
        "llm_reasoning_effort": str(
            _public_value(public_config, "llm_reasoning_effort") or "xhigh"
        ),
        "llm_timeout": float(_public_value(public_config, "llm_timeout")),
        "yeux_mcp_url": str(_public_value(public_config, "yeux_mcp_url") or "").rstrip("/"),
        "yeux_mcp_token": _secret_value(secrets.yeux_mcp_token),
        "yeux_timeout": float(_public_value(public_config, "yeux_timeout")),
    }


def mask_secret(value: str) -> str:
    """Retained for internal compatibility; API status must expose booleans instead."""

    if not value:
        return ""
    return "****"


__all__ = ["load_intel_config", "mask_secret"]
