from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr
import pytest

from yeuxq.security.network import (
    ServeMode,
    ServeSecurityError,
    is_loopback_bind,
    validate_serve_security,
)


@pytest.mark.parametrize(
    "host",
    ["localhost", "LOCALHOST", "127.0.0.1", "127.25.4.3", "::1", "[::1]"],
)
def test_unambiguous_loopback_hosts_are_accepted(host: str) -> None:
    assert is_loopback_bind(host) is True


@pytest.mark.parametrize(
    "host",
    ["", "0.0.0.0", "::", "192.168.1.10", "example.test", "127.0.0.1.evil"],
)
def test_wildcard_network_and_ambiguous_hosts_are_not_loopback(host: str) -> None:
    assert is_loopback_bind(host) is False


def test_loopback_bind_uses_safe_host_defaults_without_requiring_tls() -> None:
    decision = validate_serve_security(host="127.0.0.1")

    assert decision.mode is ServeMode.LOOPBACK
    assert decision.requires_api_auth is False
    assert decision.tls_enabled is False
    assert {"127.0.0.1", "localhost", "[::1]"} == set(decision.allowed_hosts)


def test_non_loopback_bind_requires_token_allowed_hosts_and_tls(tmp_path: Path) -> None:
    token = SecretStr("a" * 43)
    cert = tmp_path / "server.crt"
    key = tmp_path / "server.key"
    cert.write_text("synthetic certificate", encoding="utf-8")
    key.write_text("synthetic private key", encoding="utf-8")

    with pytest.raises(ServeSecurityError, match="ACCESS_TOKEN"):
        validate_serve_security(host="0.0.0.0")
    with pytest.raises(ServeSecurityError, match="allowed-host"):
        validate_serve_security(host="0.0.0.0", access_token=token)
    with pytest.raises(ServeSecurityError, match="requires TLS"):
        validate_serve_security(
            host="0.0.0.0", access_token=token, allowed_hosts=["workstation.local"]
        )

    decision = validate_serve_security(
        host="0.0.0.0",
        access_token=token,
        allowed_hosts=["Workstation.Local"],
        tls_certfile=cert,
        tls_keyfile=key,
    )
    assert decision.mode is ServeMode.NETWORK
    assert decision.requires_api_auth is True
    assert decision.allowed_hosts == ("workstation.local",)
    assert decision.tls_enabled is True


def test_non_loopback_validation_rejects_weak_token_and_wildcard_without_leaking() -> None:
    weak = "secret-value-that-must-not-appear"
    with pytest.raises(ServeSecurityError) as caught:
        validate_serve_security(
            host="192.168.1.20",
            access_token=SecretStr(weak),
            allowed_hosts=["*"],
        )

    assert weak not in str(caught.value)
    assert weak not in repr(caught.value)


def test_tls_pair_must_be_complete_and_reference_separate_files(tmp_path: Path) -> None:
    cert = tmp_path / "server.pem"
    cert.write_text("synthetic", encoding="utf-8")

    with pytest.raises(ServeSecurityError, match="configured together"):
        validate_serve_security(host="127.0.0.1", tls_certfile=cert)
    with pytest.raises(ServeSecurityError, match="separate"):
        validate_serve_security(host="127.0.0.1", tls_certfile=cert, tls_keyfile=cert)
