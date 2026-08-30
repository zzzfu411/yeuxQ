"""Explicit environment-only secret injection for yeuxQ."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os
import re
from typing import Any

from pydantic import SecretStr


class SecretConfigurationError(ValueError):
    """Raised when runtime or public configuration violates secret policy."""


_ENV_NAMES = {
    "access_token": "YEUXQ_ACCESS_TOKEN",
    "llm_api_key": "YEUXQ_LLM_API_KEY",
    "yeux_mcp_token": "YEUXQ_YEUX_MCP_TOKEN",
}
_SENSITIVE_PARTS = frozenset(
    {
        "access_key",
        "access_token",
        "api_key",
        "apikey",
        "auth_token",
        "authorization",
        "bearer_token",
        "client_secret",
        "credential",
        "credentials",
        "passwd",
        "password",
        "private_key",
        "secret",
        "token",
    }
)


def _read_secret(environ: Mapping[str, str], name: str) -> SecretStr | None:
    value = environ.get(name)
    if value is None or value == "":
        return None
    if value != value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise SecretConfigurationError(f"{name} contains unsupported whitespace")
    return SecretStr(value)


@dataclass(frozen=True, slots=True)
class RuntimeSecrets:
    """Secrets loaded from exactly three documented environment variables."""

    access_token: SecretStr | None = None
    llm_api_key: SecretStr | None = None
    yeux_mcp_token: SecretStr | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> RuntimeSecrets:
        source = os.environ if environ is None else environ
        return cls(
            access_token=_read_secret(source, _ENV_NAMES["access_token"]),
            llm_api_key=_read_secret(source, _ENV_NAMES["llm_api_key"]),
            yeux_mcp_token=_read_secret(source, _ENV_NAMES["yeux_mcp_token"]),
        )

    def configured(self) -> dict[str, bool]:
        return {
            "access_token": self.access_token is not None,
            "llm": self.llm_api_key is not None,
            "yeux_mcp": self.yeux_mcp_token is not None,
        }


def _normalized_key(key: str) -> str:
    with_word_breaks = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    return re.sub(r"[^a-z0-9]+", "_", with_word_breaks.lower()).strip("_")


def _is_sensitive_key(key: str) -> bool:
    normalized = _normalized_key(key)
    return any(normalized == part or normalized.endswith(f"_{part}") for part in _SENSITIVE_PARTS)


def reject_sensitive_public_config(config: Mapping[str, Any]) -> None:
    """Reject secret-shaped keys from YAML/JSON intended for public config."""

    if not isinstance(config, Mapping):
        raise SecretConfigurationError("public configuration must be an object")
    active: set[int] = set()

    def walk(value: Any, path: tuple[str, ...]) -> None:
        if isinstance(value, Mapping):
            identity = id(value)
            if identity in active:
                raise SecretConfigurationError("public configuration must not contain cycles")
            active.add(identity)
            try:
                for key, item in value.items():
                    if not isinstance(key, str):
                        raise SecretConfigurationError("public configuration keys must be strings")
                    next_path = (*path, key)
                    if _is_sensitive_key(key):
                        raise SecretConfigurationError(
                            "secret-shaped key is forbidden in public configuration: "
                            + ".".join(next_path)
                        )
                    walk(item, next_path)
            finally:
                active.remove(identity)
        elif isinstance(value, (list, tuple)):
            identity = id(value)
            if identity in active:
                raise SecretConfigurationError("public configuration must not contain cycles")
            active.add(identity)
            try:
                for index, item in enumerate(value):
                    walk(item, (*path, f"[{index}]"))
            finally:
                active.remove(identity)

    walk(config, ())


__all__ = [
    "RuntimeSecrets",
    "SecretConfigurationError",
    "reject_sensitive_public_config",
]
