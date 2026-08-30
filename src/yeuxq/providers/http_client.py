"""Shared HTTP client with structured, secret-safe provider outcomes."""

from __future__ import annotations

import itertools
import logging
import time
from collections import deque
from collections.abc import Callable
from typing import Any, Optional, cast
from urllib.parse import urlsplit

import httpx

from yeuxq.providers.base import UA_POOL, RateLimiter
from yeuxq.providers.status import ProviderAttempt, ProviderErrorCode, ProviderOutcome
from yeuxq.settings import DataCfg

log = logging.getLogger("yeuxq.http")


def _provider_label(target: str) -> str:
    """Return only a bounded hostname label, excluding path, query and credentials."""
    try:
        hostname = urlsplit(target).hostname
    except (TypeError, ValueError):
        hostname = None
    return (hostname or "unknown")[:128].lower()


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, min(float(raw), 3600.0))
    except (TypeError, ValueError):
        return None


class HttpClient:
    def __init__(self, cfg: DataCfg) -> None:
        self.cfg = cfg
        self.limiter = RateLimiter(cfg.rate_limit_per_second)
        self._ua = itertools.cycle(UA_POOL)
        self._client = httpx.Client(
            timeout=cfg.request_timeout,
            trust_env=False,
            headers={
                "User-Agent": next(self._ua),
                "Accept": "*/*",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": "https://quote.eastmoney.com/",
                "Connection": "keep-alive",
            },
        )
        self._outcomes: deque[tuple[int, dict[str, Any]]] = deque(maxlen=128)
        self._sequence = 0
        self.last_outcome: ProviderOutcome[Any] | None = None

    def close(self) -> None:
        self._client.close()

    def _rotate_ua(self) -> None:
        self._client.headers["User-Agent"] = next(self._ua)

    def _record(self, outcome: ProviderOutcome[Any]) -> ProviderOutcome[Any]:
        self._sequence += 1
        self.last_outcome = outcome
        self._outcomes.append((self._sequence, outcome.diagnostic()))
        return outcome

    def diagnostic_cursor(self) -> int:
        return self._sequence

    def diagnostics(self, *, since: int = 0, limit: int = 16) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 32))
        return [dict(item) for seq, item in self._outcomes if seq > since][-bounded:]

    @staticmethod
    def _error_outcome(
        provider: str,
        error_code: ProviderErrorCode,
        *,
        elapsed_ms: int,
        rate_limit_wait_seconds: float,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> ProviderOutcome[Any]:
        attempt = ProviderAttempt(
            provider=provider,
            ok=False,
            error_code=error_code,
            status_code=status_code,
            retry_after_seconds=retry_after_seconds,
            elapsed_ms=elapsed_ms,
        )
        return ProviderOutcome(
            value=None,
            ok=False,
            provider=provider,
            error_code=error_code,
            status_code=status_code,
            rate_limit_wait_seconds=rate_limit_wait_seconds,
            attempts=(attempt,),
        )

    def _request_json(
        self,
        target: str,
        params: Optional[dict],
        *,
        validator: Callable[[Any], bool] | None,
        rate_limit_wait_seconds: float,
    ) -> ProviderOutcome[Any]:
        provider = _provider_label(target)
        started = time.monotonic()
        try:
            response = self._client.get(target, params=params)
        except httpx.TimeoutException:
            elapsed = int((time.monotonic() - started) * 1000)
            return self._error_outcome(
                provider,
                ProviderErrorCode.TIMEOUT,
                elapsed_ms=elapsed,
                rate_limit_wait_seconds=rate_limit_wait_seconds,
            )
        except (httpx.RequestError, OSError):
            elapsed = int((time.monotonic() - started) * 1000)
            return self._error_outcome(
                provider,
                ProviderErrorCode.NETWORK_ERROR,
                elapsed_ms=elapsed,
                rate_limit_wait_seconds=rate_limit_wait_seconds,
            )
        except Exception:
            elapsed = int((time.monotonic() - started) * 1000)
            return self._error_outcome(
                provider,
                ProviderErrorCode.NETWORK_ERROR,
                elapsed_ms=elapsed,
                rate_limit_wait_seconds=rate_limit_wait_seconds,
            )

        elapsed = int((time.monotonic() - started) * 1000)
        if response.status_code == 429:
            return self._error_outcome(
                provider,
                ProviderErrorCode.RATE_LIMITED,
                elapsed_ms=elapsed,
                rate_limit_wait_seconds=rate_limit_wait_seconds,
                status_code=429,
                retry_after_seconds=_retry_after_seconds(response),
            )
        if response.status_code != 200:
            return self._error_outcome(
                provider,
                ProviderErrorCode.HTTP_ERROR,
                elapsed_ms=elapsed,
                rate_limit_wait_seconds=rate_limit_wait_seconds,
                status_code=response.status_code,
            )
        try:
            value = response.json()
        except (ValueError, TypeError):
            return self._error_outcome(
                provider,
                ProviderErrorCode.INVALID_JSON,
                elapsed_ms=elapsed,
                rate_limit_wait_seconds=rate_limit_wait_seconds,
                status_code=response.status_code,
            )

        schema_valid = isinstance(value, (dict, list))
        if schema_valid and validator is not None:
            try:
                schema_valid = bool(validator(value))
            except Exception:
                schema_valid = False
        if not schema_valid:
            return self._error_outcome(
                provider,
                ProviderErrorCode.INVALID_SCHEMA,
                elapsed_ms=elapsed,
                rate_limit_wait_seconds=rate_limit_wait_seconds,
                status_code=response.status_code,
            )

        attempt = ProviderAttempt(provider=provider, ok=True, status_code=200, elapsed_ms=elapsed)
        return ProviderOutcome(
            value=value,
            ok=True,
            provider=provider,
            status_code=200,
            rate_limit_wait_seconds=rate_limit_wait_seconds,
            attempts=(attempt,),
        )

    def get_json_outcome(
        self,
        url: str,
        params: Optional[dict] = None,
        host_pool: Optional[list[str]] = None,
        path: Optional[str] = None,
        validator: Callable[[Any], bool] | None = None,
    ) -> ProviderOutcome[Any]:
        """GET JSON and retain why a request or complete host pool failed."""
        waited = self.limiter.acquire()
        self._rotate_ua()
        if host_pool is not None and path is not None:
            attempts: list[ProviderAttempt] = []
            last: ProviderOutcome[Any] | None = None
            for host in host_pool:
                outcome = self._request_json(
                    host + path,
                    params,
                    validator=validator,
                    rate_limit_wait_seconds=waited,
                )
                attempts.extend(outcome.attempts)
                last = outcome
                if outcome.ok:
                    aggregate = ProviderOutcome(
                        value=outcome.value,
                        ok=True,
                        provider=outcome.provider,
                        status_code=outcome.status_code,
                        rate_limit_wait_seconds=waited,
                        attempts=tuple(attempts),
                    )
                    return self._record(aggregate)

            aggregate = ProviderOutcome(
                value=None,
                ok=False,
                provider="host_pool",
                error_code=ProviderErrorCode.ALL_HOSTS_UNAVAILABLE,
                status_code=last.status_code if last else None,
                rate_limit_wait_seconds=waited,
                attempts=tuple(attempts),
            )
            log.warning(
                "provider request failed provider=%s code=%s attempts=%d",
                aggregate.provider,
                aggregate.error_code.value,
                len(attempts),
            )
            return self._record(aggregate)

        outcome = self._request_json(
            url,
            params,
            validator=validator,
            rate_limit_wait_seconds=waited,
        )
        if not outcome.ok:
            log.warning(
                "provider request failed provider=%s code=%s",
                outcome.provider,
                outcome.error_code.value if outcome.error_code else "unknown",
            )
        return self._record(outcome)

    def get_json(
        self,
        url: str,
        params: Optional[dict] = None,
        host_pool: Optional[list[str]] = None,
        path: Optional[str] = None,
        validator: Callable[[Any], bool] | None = None,
    ) -> Any | None:
        """Compatibility adapter returning only the parsed value or ``None``."""
        return self.get_json_outcome(
            url,
            params=params,
            host_pool=host_pool,
            path=path,
            validator=validator,
        ).value

    def get_text_outcome(
        self,
        url: str,
        params: Optional[dict] = None,
    ) -> ProviderOutcome[str]:
        waited = self.limiter.acquire()
        self._rotate_ua()
        provider = _provider_label(url)
        started = time.monotonic()
        try:
            response = self._client.get(url, params=params)
        except httpx.TimeoutException:
            outcome = self._error_outcome(
                provider,
                ProviderErrorCode.TIMEOUT,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                rate_limit_wait_seconds=waited,
            )
            return cast(ProviderOutcome[str], self._record(outcome))
        except Exception:
            outcome = self._error_outcome(
                provider,
                ProviderErrorCode.NETWORK_ERROR,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                rate_limit_wait_seconds=waited,
            )
            return cast(ProviderOutcome[str], self._record(outcome))

        elapsed = int((time.monotonic() - started) * 1000)
        if response.status_code == 429:
            outcome = self._error_outcome(
                provider,
                ProviderErrorCode.RATE_LIMITED,
                elapsed_ms=elapsed,
                rate_limit_wait_seconds=waited,
                status_code=429,
                retry_after_seconds=_retry_after_seconds(response),
            )
            return cast(ProviderOutcome[str], self._record(outcome))
        if response.status_code != 200:
            outcome = self._error_outcome(
                provider,
                ProviderErrorCode.HTTP_ERROR,
                elapsed_ms=elapsed,
                rate_limit_wait_seconds=waited,
                status_code=response.status_code,
            )
            return cast(ProviderOutcome[str], self._record(outcome))
        attempt = ProviderAttempt(provider=provider, ok=True, status_code=200, elapsed_ms=elapsed)
        outcome = ProviderOutcome(
            value=response.text,
            ok=True,
            provider=provider,
            status_code=200,
            rate_limit_wait_seconds=waited,
            attempts=(attempt,),
        )
        return cast(ProviderOutcome[str], self._record(outcome))

    def get_text(self, url: str, params: Optional[dict] = None) -> Optional[str]:
        return self.get_text_outcome(url, params=params).value
