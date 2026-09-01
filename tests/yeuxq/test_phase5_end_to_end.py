from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest

from yeuxq.api.app import create_app
from yeuxq.contracts import SHANGHAI_TZ
from yeuxq.observation_store import ObservationStore
from yeuxq.services.integration_status import IntegrationStatusService
from yeuxq.services.observation import ObservationService
from yeuxq.services.research_facade import ResearchReadinessFacade
from yeuxq.security import RuntimeSecrets
from yeuxq.settings import Settings


ROOT = Path(__file__).resolve().parents[2]


def _analysis_payload(symbol: str, period: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "period": period,
        "klines": [
            {"date": "2026-08-29T09:30:00+08:00", "close": 1498.0},
            {"date": "2026-08-30T09:30:00+08:00", "close": 1500.0},
        ],
        "signal": {
            "action": "强烈买入",
            "score": 91,
            "confidence": 88,
            "prediction": {"horizon_days": 5},
        },
        "meta": {
            "engine": "phase5-fixture",
            "engine_version": "2.0.0",
            "kline_count": 2,
        },
    }


class _ProviderAnalyzer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def analyze(self, symbol: str, period: str = "day") -> dict[str, Any]:
        self.calls.append((symbol, period))
        return _analysis_payload(symbol, period)


class _AdvisoryProvider:
    def __init__(self, analyzer: _ProviderAnalyzer) -> None:
        self.analyzer = analyzer

    def search_instruments(self, keyword: str, limit: int) -> dict[str, Any]:
        return {"results": [{"code": "600519", "name": "贵州茅台", "market": "SH"}]}

    def watchlist_quotes(self, symbols: list[str]) -> dict[str, Any]:
        return {"items": [{"symbol": symbol, "price": 1500.0} for symbol in symbols]}

    def market_overview(self) -> dict[str, Any]:
        return {"index_code": "000001", "last": {"close": 3000.0}}

    def symbol_analysis(self, symbol: str, period: str) -> dict[str, Any]:
        return self.analyzer.analyze(symbol, period)

    def symbol_minute(self, symbol: str) -> dict[str, Any]:
        return {"symbol": symbol, "klines": []}

    def list_reports(self, subject: str | None, limit: int) -> dict[str, Any]:
        return {"items": []}

    def get_report(self, report_id: str) -> dict[str, Any]:
        return {"report_id": report_id, "markdown": "# historical fixture"}


class _V1Provider:
    def __init__(
        self,
        *,
        analyzer: _ProviderAnalyzer,
        store: ObservationStore,
        results_root: Path,
    ) -> None:
        self.analyzer = analyzer
        self.store = store
        self.observation_service = ObservationService(
            ttl=timedelta(minutes=15),
            analyzer=analyzer,
            store=store,
            clock=lambda: datetime(2026, 8, 30, 10, tzinfo=SHANGHAI_TZ),
            id_factory=lambda: "obs-e2e-001",
            source="phase5.provider",
            engine="yeuxq.python.analysis",
        )
        self.readiness = ResearchReadinessFacade(results_root)

    def get_integration_status(self) -> dict[str, Any]:
        return IntegrationStatusService(ROOT / "integration" / "integration_status.json").read()

    def capture_observation(self, symbol: str, period: str) -> Any:
        return self.observation_service.capture_from_service(symbol, period)

    def list_observations(self, *, limit: int, offset: int) -> list[Any]:
        return list(self.store.read_all())[offset : offset + limit]

    def get_observation(self, observation_id: str) -> Any:
        return self.store.get(observation_id)

    def list_research_runs(self, *, limit: int) -> list[str]:
        return self.readiness.list_run_ids(limit=limit)

    def get_research_readiness(self, run_id: str) -> dict[str, Any]:
        return self.readiness.get_readiness(run_id)


def test_provider_observation_api_and_ui_share_one_fail_closed_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analyzer = _ProviderAnalyzer()
    store = ObservationStore(tmp_path / "observations.jsonl")
    results_root = tmp_path / "results"
    results_root.mkdir()
    v1_provider = _V1Provider(analyzer=analyzer, store=store, results_root=results_root)
    advisory_provider = _AdvisoryProvider(analyzer)

    import yeuxq.api.app as app_module

    monkeypatch.setattr(app_module, "get_v1_service_provider", lambda: v1_provider)
    monkeypatch.setattr(app_module, "get_advisory_service_provider", lambda: advisory_provider)
    monkeypatch.setattr(app_module, "init_container", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_module, "shutdown_container", lambda: None)

    app = create_app(Settings(data_dir=tmp_path / "runtime"), RuntimeSecrets())
    with TestClient(app) as client:
        captured = client.post(
            "/api/v1/observations/capture",
            json={"symbol": "600519", "period": "day"},
            headers={"host": "localhost", "X-Request-ID": "phase5-e2e"},
        )
        assert captured.status_code == 201
        captured_payload = captured.json()
        assert captured_payload["data"]["observation_id"] == "obs-e2e-001"
        assert captured_payload["data"]["symbol"] == "600519.SH"
        assert captured_payload["data"]["prohibited_live_use"] is True
        assert captured_payload["data"]["broker_access"] is False

        listed = client.get(
            "/api/v1/observations?limit=20",
            headers={"host": "localhost", "X-Request-ID": "phase5-e2e-list"},
        )
        assert listed.status_code == 200
        assert listed.json()["data"]["items"][0]["observation_id"] == "obs-e2e-001"

        status = client.get(
            "/api/v1/integration/status",
            headers={"host": "localhost", "X-Request-ID": "phase5-e2e-status"},
        )
        assert status.status_code == 200
        assert status.json()["data"]["valid"] is True
        expected_status = v1_provider.get_integration_status()
        assert status.json()["data"]["release_readiness"] == expected_status["release_readiness"]

        readiness = client.get(
            "/api/v1/research/readiness/missing-run",
            headers={"host": "localhost", "X-Request-ID": "phase5-e2e-readiness"},
        )
        assert readiness.status_code == 200
        assert readiness.json()["data"]["decision"] == "BLOCK"
        assert readiness.json()["data"]["read_only"] is True

        analysis = client.get(
            "/api/v1/advisory/symbols/600519/analysis?period=day",
            headers={"host": "localhost", "X-Request-ID": "phase5-e2e-analysis"},
        )
        assert analysis.status_code == 200
        evidence = analysis.json()["data"]
        assert evidence["availability"] == "AVAILABLE"
        assert evidence["canonical"] is False
        assert evidence["can_upgrade_gate"] is False
        assert evidence["payload"]["symbol"] == "600519.SH"

        page = client.get("/", headers={"host": "localhost"})
        assert page.status_code == 200
        assert 'id="evidenceCard"' in page.text
        assert "RESEARCH ONLY" in page.text
        api_script = client.get("/static/js/api.js", headers={"host": "localhost"})
        assert api_script.status_code == 200
        assert "captureLocalResearchObservation" in api_script.text
        assert "const V1 = '/api/v1';" in api_script.text

    assert analyzer.calls == [("600519.SH", "day"), ("600519.SH", "day")]
    assert store.verify_integrity() is True
    assert len(store.read_all()) == 1
