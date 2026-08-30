from __future__ import annotations

from pathlib import Path

import pytest

from yeuxq.security.secrets import (
    RuntimeSecrets,
    SecretConfigurationError,
    reject_sensitive_public_config,
)


class TrackingEnvironment(dict[str, str]):
    def __init__(self, values: dict[str, str]) -> None:
        super().__init__(values)
        self.requested: list[str] = []

    def get(self, key: str, default: str | None = None) -> str | None:
        self.requested.append(key)
        return super().get(key, default)


def test_runtime_secrets_read_only_documented_environment_variables() -> None:
    environment = TrackingEnvironment(
        {
            "YEUXQ_ACCESS_TOKEN": "a" * 43,
            "YEUXQ_LLM_API_KEY": "synthetic-llm-key",
            "YEUXQ_YEUX_MCP_TOKEN": "synthetic-mcp-token",
            "UNRELATED_LLM_API_KEY": "must-be-ignored",
        }
    )

    loaded = RuntimeSecrets.from_env(environment)

    assert environment.requested == [
        "YEUXQ_ACCESS_TOKEN",
        "YEUXQ_LLM_API_KEY",
        "YEUXQ_YEUX_MCP_TOKEN",
    ]
    assert loaded.configured() == {
        "access_token": True,
        "llm": True,
        "yeux_mcp": True,
    }
    assert loaded.llm_api_key is not None
    assert loaded.llm_api_key.get_secret_value() == "synthetic-llm-key"


def test_runtime_secret_repr_and_status_do_not_reveal_values() -> None:
    raw = "private-value-not-for-output"
    loaded = RuntimeSecrets.from_env({"YEUXQ_LLM_API_KEY": raw})

    assert raw not in repr(loaded)
    assert raw not in str(loaded)
    assert raw not in repr(loaded.configured())


def test_runtime_secrets_do_not_touch_home_or_local_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def deny_file_access(*args: object, **kwargs: object) -> None:
        raise AssertionError("secret loader attempted filesystem access")

    monkeypatch.setattr(Path, "open", deny_file_access)
    monkeypatch.setattr(Path, "read_text", deny_file_access)

    assert RuntimeSecrets.from_env({}).configured() == {
        "access_token": False,
        "llm": False,
        "yeux_mcp": False,
    }


def test_runtime_secret_rejects_header_injection_whitespace_without_leaking() -> None:
    raw = "synthetic-secret\nInjected: value"
    with pytest.raises(SecretConfigurationError) as caught:
        RuntimeSecrets.from_env({"YEUXQ_LLM_API_KEY": raw})

    assert raw not in str(caught.value)


@pytest.mark.parametrize(
    "config",
    [
        {"llm_api_key": "value"},
        {"intel": {"clientSecret": "value"}},
        {"providers": [{"Authorization": "value"}]},
        {"broker": {"user-password": "value"}},
    ],
)
def test_public_config_rejects_secret_shaped_keys(config: dict[str, object]) -> None:
    with pytest.raises(SecretConfigurationError, match="forbidden"):
        reject_sensitive_public_config(config)


def test_public_config_allows_non_secret_token_and_budget_settings() -> None:
    reject_sensitive_public_config(
        {
            "prediction": {"max_tokens": 4096, "token_budget": 8},
            "security": {"allowed_hosts": ["localhost"]},
            "research": {"secretary_notes": False},
        }
    )


def test_public_config_cycles_fail_closed() -> None:
    config: dict[str, object] = {}
    config["nested"] = config

    with pytest.raises(SecretConfigurationError, match="cycles"):
        reject_sensitive_public_config(config)
