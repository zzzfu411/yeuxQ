"""Fail-closed network exposure policy for the yeuxQ service."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
import ipaddress
from os import PathLike
from pathlib import Path
import re

from pydantic import SecretStr


class ServeSecurityError(ValueError):
    """Raised when a requested bind would expose an unsafe service."""


class ServeMode(str, Enum):
    LOOPBACK = "loopback"
    NETWORK = "network"


@dataclass(frozen=True, slots=True)
class ServeSecurityDecision:
    mode: ServeMode
    requires_api_auth: bool
    allowed_hosts: tuple[str, ...]
    tls_enabled: bool


_PLACEHOLDER_TOKEN = re.compile(
    r"^(?:change[-_ ]?me|example|placeholder|replace[-_ ]?me|your[-_ ]?token)$",
    re.IGNORECASE,
)


def _host_text(host: str) -> str:
    if not isinstance(host, str) or not host.strip():
        return ""
    candidate = host.strip().lower()
    if candidate.startswith("[") and candidate.endswith("]"):
        candidate = candidate[1:-1]
    return candidate


def is_loopback_bind(host: str) -> bool:
    """Return whether *host* is unambiguously confined to loopback."""

    candidate = _host_text(host)
    if candidate == "localhost":
        return True
    if not candidate or "%" in candidate:
        return False
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def _normalize_allowed_hosts(hosts: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for host in hosts:
        if not isinstance(host, str) or not host.strip():
            raise ServeSecurityError("allowed hosts must contain non-empty host names")
        candidate = host.strip().lower()
        if "*" in candidate:
            raise ServeSecurityError("wildcard allowed hosts are forbidden")
        if any(char in candidate for char in ("/", "\\", "@", "?", "#")):
            raise ServeSecurityError("allowed hosts must not contain URL or path syntax")
        if candidate not in normalized:
            normalized.append(candidate)
    return tuple(normalized)


def _validate_access_token(access_token: SecretStr | None) -> None:
    if access_token is None:
        raise ServeSecurityError("non-loopback bind requires YEUXQ_ACCESS_TOKEN")
    raw = access_token.get_secret_value()
    if raw != raw.strip() or any(ord(char) < 33 or ord(char) == 127 for char in raw):
        raise ServeSecurityError("YEUXQ_ACCESS_TOKEN contains unsupported whitespace")
    if len(raw) < 32 or _PLACEHOLDER_TOKEN.fullmatch(raw):
        raise ServeSecurityError(
            "YEUXQ_ACCESS_TOKEN must be a non-placeholder value of 32+ characters"
        )


def _validate_tls_pair(
    certfile: str | PathLike[str] | None,
    keyfile: str | PathLike[str] | None,
) -> bool:
    if certfile is None and keyfile is None:
        return False
    if certfile is None or keyfile is None:
        raise ServeSecurityError("TLS certificate and key must be configured together")
    cert_path = Path(certfile)
    key_path = Path(keyfile)
    if not cert_path.is_file() or not key_path.is_file():
        raise ServeSecurityError("TLS certificate and key must reference existing files")
    if cert_path.resolve() == key_path.resolve():
        raise ServeSecurityError("TLS certificate and key must be separate files")
    return True


def validate_serve_security(
    *,
    host: str,
    access_token: SecretStr | None = None,
    allowed_hosts: Iterable[str] = (),
    tls_certfile: str | PathLike[str] | None = None,
    tls_keyfile: str | PathLike[str] | None = None,
) -> ServeSecurityDecision:
    """Validate a bind before Uvicorn starts and return its security mode.

    Direct network exposure requires a dedicated API token, explicit Host
    allowlist and TLS. A reverse proxy should keep yeuxQ itself on loopback.
    """

    if not isinstance(host, str) or not host.strip():
        raise ServeSecurityError("bind host must be a non-empty string")
    normalized_hosts = _normalize_allowed_hosts(allowed_hosts)
    tls_enabled = _validate_tls_pair(tls_certfile, tls_keyfile)
    if is_loopback_bind(host):
        return ServeSecurityDecision(
            mode=ServeMode.LOOPBACK,
            requires_api_auth=False,
            allowed_hosts=normalized_hosts or ("127.0.0.1", "localhost", "[::1]"),
            tls_enabled=tls_enabled,
        )

    _validate_access_token(access_token)
    if not normalized_hosts:
        raise ServeSecurityError("non-loopback bind requires an explicit allowed-host list")
    if not tls_enabled:
        raise ServeSecurityError("direct non-loopback bind requires TLS")
    return ServeSecurityDecision(
        mode=ServeMode.NETWORK,
        requires_api_auth=True,
        allowed_hosts=normalized_hosts,
        tls_enabled=True,
    )


__all__ = [
    "ServeMode",
    "ServeSecurityDecision",
    "ServeSecurityError",
    "is_loopback_bind",
    "validate_serve_security",
]
