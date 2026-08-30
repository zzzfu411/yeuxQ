"""Bounded, secret-safe status objects for external market-data calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Generic, TypeVar


class ProviderErrorCode(StrEnum):
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    HTTP_ERROR = "http_error"
    INVALID_JSON = "invalid_json"
    INVALID_SCHEMA = "invalid_schema"
    NETWORK_ERROR = "network_error"
    ALL_HOSTS_UNAVAILABLE = "all_hosts_unavailable"


T = TypeVar("T")


@dataclass(frozen=True)
class ProviderAttempt:
    """One host attempt. ``provider`` is a hostname label, never a URL."""

    provider: str
    ok: bool
    error_code: ProviderErrorCode | None = None
    status_code: int | None = None
    retry_after_seconds: float | None = None
    elapsed_ms: int = 0

    def diagnostic(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "provider": self.provider,
            "status": "ok" if self.ok else "error",
            "elapsed_ms": max(0, self.elapsed_ms),
        }
        if self.error_code is not None:
            result["error_code"] = self.error_code.value
        if self.status_code is not None:
            result["status_code"] = self.status_code
        if self.retry_after_seconds is not None:
            result["retry_after_seconds"] = self.retry_after_seconds
        return result


@dataclass(frozen=True)
class ProviderOutcome(Generic[T]):
    """Typed provider result while preserving a simple value-or-None adapter."""

    value: T | None
    ok: bool
    provider: str
    error_code: ProviderErrorCode | None = None
    status_code: int | None = None
    rate_limit_wait_seconds: float = 0.0
    attempts: tuple[ProviderAttempt, ...] = field(default_factory=tuple)

    def diagnostic(self, *, max_attempts: int = 4) -> dict[str, Any]:
        result: dict[str, Any] = {
            "provider": self.provider,
            "status": "ok" if self.ok else "error",
            "rate_limit_wait_seconds": round(max(0.0, self.rate_limit_wait_seconds), 6),
        }
        if self.error_code is not None:
            result["error_code"] = self.error_code.value
        if self.status_code is not None:
            result["status_code"] = self.status_code
        if self.attempts:
            bounded = self.attempts[-max(1, min(max_attempts, 8)) :]
            result["attempts"] = [attempt.diagnostic() for attempt in bounded]
            result["attempt_count"] = len(self.attempts)
        return result
