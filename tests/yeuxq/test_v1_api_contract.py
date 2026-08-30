from __future__ import annotations

from pathlib import Path
import json
import socket
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from yeuxq.api.routes_v1 import ADVISORY_BOUNDARY, create_v1_router
from yeuxq.services.integration_status import IntegrationStatusService
from yeuxq.security import RuntimeSecrets
from yeuxq.settings import Settings


ROOT = Path(__file__).resolve().parents[2]


def _observation(observation_id: str) -> dict[str, Any]:
    return {
        "observation_id": observation_id,
        "symbol": "600519.SH",
        "action": "HOLD",
        "prohibited_live_use": True,
        "broker_access": False,
        "live_trading_allowed": False,
    }


def _readiness(run_id: str, decision: str = "BLOCK") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "decision": decision,
        "findings": [],
        "risk_budget": {},
        "reason": None,
        "authority": "src/quantify/readiness",
        "read_only": True,
        "broker_access": False,
        "live_trading_allowed": False,
        "artifact_sha256": None,
        "artifact_mtime": None,
        "artifact_size_bytes": None,
    }


class FakeProvider:
    def __init__(self, *, status: dict[str, Any] | None = None) -> None:
        self.status = (
            status
            or IntegrationStatusService(ROOT / "integration" / "integration_status.json").read()
        )
        self.observations = {
            "obs-001": _observation("obs-001"),
            "obs-002": _observation("obs-002"),
        }
        self.capture_calls: list[tuple[str, str]] = []
        self.list_calls: list[tuple[int, int]] = []

    def get_integration_status(self) -> dict[str, Any]:
        return self.status

    def capture_observation(self, symbol: str, period: str) -> dict[str, Any]:
        self.capture_calls.append((symbol, period))
        value = _observation("obs-captured")
        value["symbol"] = symbol
        return value

    def list_observations(self, *, limit: int, offset: int) -> list[dict[str, Any]]:
        self.list_calls.append((limit, offset))
        return list(self.observations.values())[offset : offset + limit]

    def get_observation(self, observation_id: str) -> dict[str, Any] | None:
        return self.observations.get(observation_id)

    def list_research_runs(self, *, limit: int) -> list[str]:
        return ["run_002", "run_001"][:limit]

    def get_research_readiness(self, run_id: str) -> dict[str, Any]:
        return _readiness(run_id)


def _client(provider: FakeProvider) -> TestClient:
    app = FastAPI()
    app.include_router(create_v1_router(provider))
    return TestClient(app)


def _assert_envelope(payload: dict[str, Any], request_id: str) -> None:
    assert payload["request_id"] == request_id
    assert payload["advisory"] == ADVISORY_BOUNDARY


def test_normal_v1_contract_uses_only_explicit_bounded_facades() -> None:
    provider = FakeProvider()
    client = _client(provider)
    headers = {"X-Request-ID": "contract-test-001"}

    health = client.get("/api/v1/health", headers=headers)
    assert health.status_code == 200
    assert health.json()["data"] == {"status": "ok", "api_version": "v1"}
    _assert_envelope(health.json(), "contract-test-001")

    status = client.get("/api/v1/integration/status", headers=headers)
    assert status.status_code == 200
    assert status.json()["data"]["valid"] is True
    assert status.json()["data"]["release_readiness"] == "BLOCK"
    _assert_envelope(status.json(), "contract-test-001")

    captured = client.post(
        "/api/v1/observations/capture",
        json={"symbol": "600519", "period": "day"},
        headers=headers,
    )
    assert captured.status_code == 201
    assert captured.json()["data"]["symbol"] == "600519.SH"
    assert provider.capture_calls == [("600519.SH", "day")]
    _assert_envelope(captured.json(), "contract-test-001")

    observations = client.get("/api/v1/observations?limit=1&offset=1", headers=headers)
    assert observations.status_code == 200
    assert observations.json()["data"]["items"][0]["observation_id"] == "obs-002"
    assert provider.list_calls == [(1, 1)]

    observation = client.get("/api/v1/observations/obs-001", headers=headers)
    assert observation.status_code == 200
    assert observation.json()["data"]["broker_access"] is False

    runs = client.get("/api/v1/research/runs?limit=1", headers=headers)
    assert runs.status_code == 200
    assert runs.json()["data"]["items"] == ["run_002"]

    readiness = client.get("/api/v1/research/readiness/run_002", headers=headers)
    assert readiness.status_code == 200
    assert readiness.json()["data"]["decision"] == "BLOCK"
    assert readiness.json()["data"]["read_only"] is True


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ("{not-json", "STATUS_INVALID"),
        ('{"schema_version":"9.0.0"}', "STATUS_SCHEMA_UNSUPPORTED"),
        ('{"schema_version":"1.0.0","schema_version":"1.0.0"}', "STATUS_INVALID"),
    ],
)
def test_invalid_or_unknown_integration_status_fails_closed(
    tmp_path: Path, content: str, reason: str
) -> None:
    source = tmp_path / "integration_status.json"
    source.write_text(content, encoding="utf-8")
    provider = FakeProvider(status=IntegrationStatusService(source).read())

    response = _client(provider).get("/api/v1/integration/status")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "valid": False,
        "release_readiness": "BLOCK",
        "reason": reason,
        "status": None,
    }
    assert response.json()["advisory"]["live_trading_allowed"] is False


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        (
            "post",
            "/api/v1/observations/capture",
            {"symbol": "https://example.test", "period": "day"},
        ),
        ("post", "/api/v1/observations/capture", {"symbol": "600519", "period": "minute"}),
        (
            "post",
            "/api/v1/observations/capture",
            {"symbol": "600519", "period": "day", "path": "../outside"},
        ),
        ("get", "/api/v1/observations?limit=101", None),
        ("get", "/api/v1/research/readiness/..%5Coutside", None),
    ],
)
def test_strict_inputs_return_structured_422(
    method: str, path: str, json_body: dict[str, Any] | None
) -> None:
    provider = FakeProvider()
    response = _client(provider).request(
        method,
        path,
        json=json_body,
        headers={"X-Request-ID": "invalid-request-001"},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "INVALID_REQUEST"
    _assert_envelope(body, "invalid-request-001")
    assert provider.capture_calls == []


def test_missing_observation_returns_structured_404() -> None:
    response = _client(FakeProvider()).get(
        "/api/v1/observations/obs-missing",
        headers={"X-Request-ID": "missing-001"},
    )

    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "OBSERVATION_NOT_FOUND",
        "message": "observation was not found",
    }
    _assert_envelope(response.json(), "missing-001")


def test_openapi_contains_no_dangerous_execution_or_account_routes() -> None:
    schema = _client(FakeProvider()).get("/openapi.json").json()
    paths = set(schema["paths"])

    assert paths == {
        "/api/v1/health",
        "/api/v1/integration/status",
        "/api/v1/observations/capture",
        "/api/v1/observations",
        "/api/v1/observations/{observation_id}",
        "/api/v1/research/runs",
        "/api/v1/research/readiness/{run_id}",
    }
    assert not any(
        term in path.lower()
        for path in paths
        for term in ("order", "account", "broker", "cancel", "execute")
    )


def test_router_startup_and_health_do_not_open_a_network_connection(monkeypatch) -> None:
    def reject_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access is forbidden during router startup")

    monkeypatch.setattr(socket, "create_connection", reject_network)

    with _client(FakeProvider()) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"


def test_production_app_mounts_v1_without_an_execution_surface(tmp_path: Path) -> None:
    from yeuxq.api.app import create_app

    application = create_app(Settings(data_dir=tmp_path / "runtime"), RuntimeSecrets())
    schema = TestClient(application).get("/openapi.json", headers={"host": "localhost"}).json()
    v1_paths = {
        path: operations
        for path, operations in schema["paths"].items()
        if path.startswith("/api/v1")
    }

    assert set(v1_paths) == {
        "/api/v1/health",
        "/api/v1/integration/status",
        "/api/v1/observations/capture",
        "/api/v1/observations",
        "/api/v1/observations/{observation_id}",
        "/api/v1/research/runs",
        "/api/v1/research/readiness/{run_id}",
    }
    assert {path for path, operations in v1_paths.items() if "post" in operations} == {
        "/api/v1/observations/capture"
    }
    assert all(set(operations) <= {"get", "post"} for operations in v1_paths.values())
    assert not any(
        term in path.lower()
        for path in v1_paths
        for term in ("order", "account", "broker", "cancel", "execute", "trade")
    )


def test_container_v1_adapter_reads_only_the_canonical_quantify_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import yeuxq.api.deps as deps_module

    project = tmp_path / "project"
    integration = project / "integration"
    results = project / "results"
    run = results / "run_001"
    integration.mkdir(parents=True)
    run.mkdir(parents=True)
    (integration / "integration_status.json").write_bytes(
        (ROOT / "integration" / "integration_status.json").read_bytes()
    )
    (run / "micro_live_readiness.json").write_text(
        json.dumps(
            {
                "decision": "PASS",
                "findings": [],
                "risk_budget": {
                    "manual_reference_only": True,
                    "auto_order_submission": False,
                    "max_position_pct": 0.05,
                    "max_strategy_drawdown_stop": 0.15,
                    "single_day_loss_stop": 0.02,
                    "max_capital_increase_without_new_review": 0.0,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(deps_module, "PROJECT_ROOT", project)

    container = deps_module.init_container(
        Settings(data_dir=tmp_path / "runtime"),
        RuntimeSecrets(),
    )
    try:
        assert container.v1.get_integration_status()["valid"] is True
        assert container.v1.list_research_runs(limit=10) == ["run_001"]
        readiness = container.v1.get_research_readiness("run_001")
        assert readiness["decision"] == "PASS"
        assert readiness["authority"] == "src/quantify/readiness"
        assert readiness["read_only"] is True
        assert readiness["broker_access"] is False
        assert readiness["live_trading_allowed"] is False
        assert not hasattr(container.v1, "execute_trade")
        assert not hasattr(container.v1, "submit_order")
    finally:
        deps_module.shutdown_container()
