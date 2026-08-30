from __future__ import annotations

import json
from pathlib import Path
import socket
from typing import Any

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
import pytest

from yeuxq.api.advisory_app import ADVISORY_BOUNDARY, create_advisory_app
from yeuxq.intel.report_store import ReportNotFoundError
from yeuxq.security import RuntimeSecrets
from yeuxq.settings import Settings


EXPECTED_PATHS = {
    "/instruments/search",
    "/watchlist/quotes",
    "/market/overview",
    "/symbols/{symbol}/analysis",
    "/symbols/{symbol}/minute",
    "/reports",
    "/reports/{report_id}",
}
DANGEROUS_ROUTE_SEGMENTS = {
    "account",
    "accounts",
    "broker",
    "brokers",
    "cancel",
    "execute",
    "execution",
    "order",
    "orders",
    "position",
    "positions",
    "trade",
    "trades",
}
VALID_REPORT_ID = "600519_report_20260830T010203123456Z_012345abcdef.md"


def _evidence_payload(kind: str, **extra: object) -> dict[str, Any]:
    return {
        "kind": kind,
        "availability": "AVAILABLE",
        "event_time": "2026-08-30T09:30:00+08:00",
        "received_at": "2026-08-30T09:30:01+08:00",
        "stale_after": "2026-08-30T09:45:01+08:00",
        "freshness": "FRESH",
        "provenance": {"source": "contract-fixture"},
        **extra,
    }


class FakeProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def search_instruments(self, keyword: str, limit: int) -> dict[str, Any]:
        self.calls.append(("search_instruments", keyword, limit))
        return _evidence_payload(
            "instrument_search",
            items=[{"symbol": "600519.SH", "name": "贵州茅台"}],
            limit=limit,
        )

    def watchlist_quotes(self, symbols: list[str]) -> dict[str, Any]:
        self.calls.append(("watchlist_quotes", tuple(symbols)))
        return _evidence_payload(
            "watchlist_quotes",
            items=[{"symbol": symbol, "price": 1.0} for symbol in symbols],
        )

    def market_overview(self) -> dict[str, Any]:
        self.calls.append(("market_overview",))
        return _evidence_payload("market_overview", index_code="000001.SH")

    def symbol_analysis(self, symbol: str, period: str) -> dict[str, Any]:
        self.calls.append(("symbol_analysis", symbol, period))
        return _evidence_payload(
            "symbol_analysis",
            symbol=symbol,
            period=period,
            action="HOLD",
        )

    def symbol_minute(self, symbol: str) -> dict[str, Any]:
        self.calls.append(("symbol_minute", symbol))
        return _evidence_payload("symbol_minute", symbol=symbol)

    def list_reports(self, subject: str, limit: int) -> dict[str, Any]:
        self.calls.append(("list_reports", subject, limit))
        return _evidence_payload(
            "advisory_report_list",
            subject=subject,
            limit=limit,
            items=[
                {
                    "report_id": VALID_REPORT_ID,
                    "subject": subject,
                    "canonical": False,
                    "can_upgrade_gate": False,
                }
            ],
        )

    def get_report(self, report_id: str) -> dict[str, Any]:
        self.calls.append(("get_report", report_id))
        if report_id != VALID_REPORT_ID:
            raise ReportNotFoundError("report does not exist")
        return _evidence_payload(
            "advisory_report",
            report_id=report_id,
            markdown="# Advisory fixture",
            canonical=False,
            can_upgrade_gate=False,
        )


def _client(provider: FakeProvider) -> TestClient:
    return TestClient(create_advisory_app(provider))


def _assert_envelope(response: Any, request_id: str) -> dict[str, Any]:
    assert response.headers["X-Request-ID"] == request_id
    assert response.headers["Cache-Control"] == "no-store"
    payload = response.json()
    assert payload["request_id"] == request_id
    assert payload["advisory"] == ADVISORY_BOUNDARY
    assert payload["advisory"]["mode"] == "research_only_advisory_only"
    assert payload["advisory"]["prohibited_live_use"] is True
    assert payload["advisory"]["broker_access"] is False
    assert payload["advisory"]["live_trading_allowed"] is False
    return payload


def test_advisory_openapi_is_an_exact_get_only_surface() -> None:
    schema = _client(FakeProvider()).get("/openapi.json").json()
    paths = schema["paths"]

    assert set(paths) == EXPECTED_PATHS
    assert all(set(operations) == {"get"} for operations in paths.values())

    findings: list[tuple[str, list[str]]] = []
    for path in paths:
        segments = {segment.lower() for segment in path.split("/") if segment}
        dangerous = sorted(segments & DANGEROUS_ROUTE_SEGMENTS)
        if dangerous:
            findings.append((path, dangerous))
    assert not findings


def test_normal_advisory_contract_uses_envelopes_and_normalized_inputs() -> None:
    provider = FakeProvider()
    client = _client(provider)
    headers = {"X-Request-ID": "advisory-contract-001"}

    requests = (
        client.get(
            "/instruments/search",
            params={"keyword": "茅台", "limit": 5},
            headers=headers,
        ),
        client.get(
            "/watchlist/quotes",
            params=[("symbols", "600519"), ("symbols", "000001")],
            headers=headers,
        ),
        client.get("/market/overview", headers=headers),
        client.get("/symbols/600519/analysis", params={"period": "day"}, headers=headers),
        client.get("/symbols/600519/minute", headers=headers),
        client.get("/reports", params={"subject": "600519", "limit": 2}, headers=headers),
        client.get(f"/reports/{VALID_REPORT_ID}", headers=headers),
    )

    for response in requests:
        assert response.status_code == 200
        payload = _assert_envelope(response, "advisory-contract-001")
        assert payload["data"]["availability"] == "AVAILABLE"
        assert payload["data"]["provenance"]["source"] == "contract-fixture"
        assert payload["data"]["canonical"] is False
        assert payload["data"]["can_upgrade_gate"] is False

    assert provider.calls == [
        ("search_instruments", "茅台", 5),
        ("watchlist_quotes", ("600519.SH", "000001.SZ")),
        ("market_overview",),
        ("symbol_analysis", "600519.SH", "day"),
        ("symbol_minute", "600519.SH"),
        ("list_reports", "600519.SH", 2),
        ("get_report", VALID_REPORT_ID),
    ]


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/instruments/search", {"keyword": "", "limit": 5}),
        ("/instruments/search", {"keyword": "x" * 65, "limit": 5}),
        ("/instruments/search", {"keyword": "bank", "limit": 0}),
        ("/instruments/search", {"keyword": "bank", "limit": 21}),
        ("/watchlist/quotes", None),
        ("/watchlist/quotes", [("symbols", "https://example.test")]),
        (
            "/watchlist/quotes",
            [("symbols", f"{index:06d}") for index in range(13)],
        ),
        ("/symbols/not-a-symbol/analysis", {"period": "day"}),
        ("/symbols/600519/analysis", {"period": "minute"}),
        ("/symbols/not-a-symbol/minute", None),
        ("/reports", {"subject": "../outside", "limit": 5}),
        ("/reports", {"subject": "600519", "limit": 0}),
        ("/reports", {"subject": "600519", "limit": 81}),
        ("/reports/not-a-report-id", None),
        ("/reports/..%5Coutside", None),
    ],
)
def test_invalid_inputs_fail_before_reaching_the_provider(
    path: str,
    params: dict[str, object] | list[tuple[str, str]] | None,
) -> None:
    provider = FakeProvider()
    response = _client(provider).get(
        path,
        params=params,
        headers={"X-Request-ID": "advisory-invalid-001"},
    )

    assert response.status_code == 422
    payload = _assert_envelope(response, "advisory-invalid-001")
    assert payload["error"]["code"] == "INVALID_REQUEST"
    assert provider.calls == []


def test_missing_valid_report_id_is_a_structured_404() -> None:
    provider = FakeProvider()
    missing_id = "600519_report_20260830T010203123456Z_ffffffffffff.md"

    response = _client(provider).get(
        f"/reports/{missing_id}",
        headers={"X-Request-ID": "advisory-missing-001"},
    )

    assert response.status_code == 404
    payload = _assert_envelope(response, "advisory-missing-001")
    assert payload["error"]["code"] == "REPORT_NOT_FOUND"
    assert provider.calls == [("get_report", missing_id)]


@pytest.mark.parametrize(
    ("item", "expected_freshness"),
    [
        (
            {
                "created_at": "2999-01-01T00:00:00+00:00",
                "expires_at": "2999-01-02T00:00:00+00:00",
            },
            "UNKNOWN",
        ),
        ({"expires_at": "2999-01-02T00:00:00+00:00"}, "UNKNOWN"),
        (
            {
                "created_at": "2020-01-01T00:00:00+00:00",
                "expires_at": "2020-01-02T00:00:00+00:00",
            },
            "STALE",
        ),
    ],
)
def test_report_freshness_fails_closed_for_future_missing_or_expired_times(
    item: dict[str, str],
    expected_freshness: str,
) -> None:
    class TimingProvider(FakeProvider):
        def list_reports(self, subject: str, limit: int) -> dict[str, Any]:
            self.calls.append(("list_reports", subject, limit))
            return {"items": [item]}

    provider = TimingProvider()
    response = _client(provider).get("/reports", params={"subject": "600519", "limit": 1})

    assert response.status_code == 200
    assert response.json()["data"]["freshness"] == expected_freshness
    assert response.json()["data"]["canonical"] is False
    assert response.json()["data"]["can_upgrade_gate"] is False


def test_provider_failure_returns_unavailable_without_leaking_details() -> None:
    class UnavailableProvider(FakeProvider):
        def market_overview(self) -> dict[str, Any]:
            self.calls.append(("market_overview",))
            raise RuntimeError("upstream-secret-detail")

    provider = UnavailableProvider()
    response = _client(provider).get(
        "/market/overview",
        headers={"X-Request-ID": "advisory-unavailable-001"},
    )

    assert response.status_code == 503
    payload = _assert_envelope(response, "advisory-unavailable-001")
    assert payload["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert "upstream-secret-detail" not in json.dumps(payload)
    assert provider.calls == [("market_overview",)]


def test_advisory_app_startup_does_not_open_a_network_connection(monkeypatch) -> None:
    def reject_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access is forbidden during advisory app startup")

    monkeypatch.setattr(socket, "create_connection", reject_network)

    with _client(FakeProvider()) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert set(response.json()["paths"]) == EXPECTED_PATHS


def test_production_app_does_not_mount_bare_legacy_api_routes(tmp_path: Path) -> None:
    from yeuxq.api.app import create_app

    application = create_app(Settings(data_dir=tmp_path / "runtime"), RuntimeSecrets())
    bare_routes = {
        route.path
        for route in application.routes
        if isinstance(route, APIRoute)
        and route.path.startswith("/api/")
        and not route.path.startswith("/api/v1/")
    }

    assert bare_routes == set()

    with TestClient(application) as client:
        for method, path, body in (
            ("get", "/api/health", None),
            ("get", "/api/quote", None),
            ("get", "/api/analyze", None),
            ("post", "/api/backtest", {}),
            ("post", "/api/scan/start", b"{"),
            ("post", "/api/research/report", {}),
            ("get", "/api/orderflow/overview", None),
        ):
            kwargs: dict[str, object] = {"headers": {"host": "localhost"}}
            if isinstance(body, dict):
                kwargs["json"] = body
            elif isinstance(body, bytes):
                kwargs["content"] = body
                kwargs["headers"] = {
                    "host": "localhost",
                    "content-type": "application/json",
                }
            response = client.request(method, path, **kwargs)
            assert response.status_code == 404, f"legacy route is still mounted: {method} {path}"
