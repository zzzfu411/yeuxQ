from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

import yeuxq.storage.cache as cache_module
from yeuxq.providers.base import RateLimiter
from yeuxq.providers.composite import CompositeMarketData
from yeuxq.providers.http_client import HttpClient
from yeuxq.providers.status import ProviderErrorCode
from yeuxq.services.analyze import AnalyzeService
from yeuxq.settings import DataCfg, Settings
from yeuxq.storage.cache import CacheState, MemoryCache


def _http(handler) -> HttpClient:
    client = HttpClient(DataCfg(rate_limit_per_second=1000, request_timeout=0.1))
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def test_timeout_outcome_is_structured_and_secret_safe() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("contains-secret", request=request)

    client = _http(timeout)
    try:
        outcome = client.get_json_outcome(
            "https://user:password@quotes.example/api?token=top-secret",
            params={"api_key": "also-secret"},
        )
    finally:
        client.close()

    diagnostic = outcome.diagnostic()
    assert outcome.error_code is ProviderErrorCode.TIMEOUT
    assert diagnostic["provider"] == "quotes.example"
    assert "secret" not in str(diagnostic)
    assert "password" not in str(diagnostic)
    assert "token" not in str(diagnostic)


def test_rate_limit_http_error_and_retry_after_are_explicit() -> None:
    client = _http(
        lambda request: httpx.Response(
            429,
            headers={"Retry-After": "12"},
            request=request,
        )
    )
    try:
        outcome = client.get_json_outcome("https://quotes.example/api")
    finally:
        client.close()

    assert outcome.error_code is ProviderErrorCode.RATE_LIMITED
    assert outcome.status_code == 429
    assert outcome.attempts[0].retry_after_seconds == 12.0


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(200, content=b"<html>bad</html>"), ProviderErrorCode.INVALID_JSON),
        (httpx.Response(200, json="wrong-shape"), ProviderErrorCode.INVALID_SCHEMA),
        (httpx.Response(503, json={"error": "down"}), ProviderErrorCode.HTTP_ERROR),
    ],
)
def test_invalid_responses_have_distinct_error_codes(
    response: httpx.Response,
    expected: ProviderErrorCode,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        response.request = request
        return response

    client = _http(handler)
    try:
        outcome = client.get_json_outcome("https://quotes.example/api")
    finally:
        client.close()

    assert outcome.error_code is expected


def test_host_fallback_keeps_attempts_and_all_host_failure_is_explicit() -> None:
    def fallback(request: httpx.Request) -> httpx.Response:
        if request.url.host == "first.example":
            raise httpx.ConnectTimeout("down", request=request)
        return httpx.Response(200, json={"data": {"price": 1}}, request=request)

    client = _http(fallback)
    try:
        outcome = client.get_json_outcome(
            "",
            params={"token": "never-exported"},
            host_pool=["https://first.example", "https://second.example"],
            path="/quote",
        )
    finally:
        client.close()

    assert outcome.ok is True
    assert outcome.provider == "second.example"
    assert [attempt.error_code for attempt in outcome.attempts] == [
        ProviderErrorCode.TIMEOUT,
        None,
    ]
    assert "never-exported" not in str(outcome.diagnostic())

    unavailable = _http(
        lambda request: (_ for _ in ()).throw(httpx.ConnectError("offline", request=request))
    )
    try:
        failed = unavailable.get_json_outcome(
            "",
            host_pool=["https://first.example", "https://second.example"],
            path="/quote",
        )
    finally:
        unavailable.close()
    assert failed.error_code is ProviderErrorCode.ALL_HOSTS_UNAVAILABLE
    assert all(attempt.error_code is ProviderErrorCode.NETWORK_ERROR for attempt in failed.attempts)


def test_rate_limiter_returns_the_wait_it_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    limiter = RateLimiter(2.0)
    limiter._tokens = 0.0
    waits: list[float] = []
    monkeypatch.setattr("yeuxq.providers.base.time.sleep", waits.append)

    waited = limiter.acquire()

    assert waits == [waited]
    assert 0.49 <= waited <= 0.5
    assert limiter.last_wait_seconds == waited


def test_cache_lookup_distinguishes_hit_stale_and_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    monkeypatch.setattr(cache_module.time, "time", lambda: now[0])
    cache = MemoryCache()
    cache.set("quote:600519:private", {"price": 1})

    now[0] = 105.0
    hit = cache.lookup("quote:600519:private", ttl=10)
    now[0] = 111.0
    stale = cache.lookup("quote:600519:private", ttl=10)
    miss = cache.lookup("quote:600519:private", ttl=10)

    assert hit.state is CacheState.HIT and hit.age_seconds == 5
    assert stale.state is CacheState.STALE and stale.value == {"price": 1}
    assert miss.state is CacheState.MISS
    assert cache.get("quote:600519:private", ttl=10) is None
    diagnostics = cache.diagnostics(limit=10)
    assert [item["state"] for item in diagnostics[:3]] == ["HIT", "STALE", "MISS"]
    assert all("600519" not in str(item) for item in diagnostics)


def test_realtime_flow_reports_unavailable_when_every_host_is_offline() -> None:
    offline = _http(
        lambda request: (_ for _ in ()).throw(httpx.ConnectError("offline", request=request))
    )
    market = object.__new__(CompositeMarketData)
    market.cfg = SimpleNamespace(
        quote_ttl_seconds=2.0,
        rt_flow_hosts=["https://first.example", "https://second.example"],
    )
    market.cache = MemoryCache()
    market.http = offline

    try:
        payload = AnalyzeService(market, Settings()).realtime_flow_payload("600519")
    finally:
        offline.close()

    assert payload["flows"] == []
    assert payload["summary"] is None
    assert payload["data_status"] == "unavailable"
    assert payload["diagnostics"]["reason"] == "all_hosts_unavailable"
    assert len(payload["diagnostics"]["providers"]) <= 4
