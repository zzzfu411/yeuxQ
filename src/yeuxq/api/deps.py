"""应用依赖容器。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Optional

from yeuxq.intel.research import ResearchService
from yeuxq.intel.report_store import ReportStore
from yeuxq.observation_store import ObservationStore
from yeuxq.providers.composite import CompositeMarketData
from yeuxq.providers.orderflow import OrderFlowProvider
from yeuxq.scan.worker import ScanWorker
from yeuxq.services.analyze import AnalyzeService
from yeuxq.services.backtest import BacktestService
from yeuxq.security import RuntimeSecrets
from yeuxq.services.integration_status import IntegrationStatusService
from yeuxq.services.observation import ObservationService
from yeuxq.services.research_facade import ResearchReadinessFacade
from yeuxq.settings import PROJECT_ROOT, Settings, get_settings
from yeuxq.storage.cache import MemoryCache
from yeuxq.storage.kline_store import KlineStore


@dataclass(frozen=True)
class V1Services:
    """Narrow adapter exposed to the versioned research-only API."""

    integration_status: IntegrationStatusService
    observation_store: ObservationStore
    observation_service: ObservationService
    research_readiness: ResearchReadinessFacade

    def get_integration_status(self) -> dict:
        return self.integration_status.read()

    def capture_observation(self, symbol: str, period: str):
        return self.observation_service.capture_from_service(symbol, period)

    def list_observations(self, *, limit: int, offset: int):
        if isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("limit is outside the v1 boundary")
        if isinstance(offset, bool) or not 0 <= offset <= 10_000:
            raise ValueError("offset is outside the v1 boundary")
        values = self.observation_store.read_all()
        return values[offset : offset + limit]

    def get_observation(self, observation_id: str):
        return self.observation_store.get(observation_id)

    def list_research_runs(self, *, limit: int):
        return self.research_readiness.list_run_ids(limit=limit)

    def get_research_readiness(self, run_id: str):
        return self.research_readiness.get_readiness(run_id)


@dataclass
class AppContainer:
    settings: Settings
    secrets: RuntimeSecrets
    cache: MemoryCache
    store: KlineStore
    data: CompositeMarketData
    orderflow: OrderFlowProvider
    analyze: AnalyzeService
    backtest: BacktestService
    scan: ScanWorker
    research: ResearchService
    report_store: ReportStore
    v1: V1Services


_container: Optional[AppContainer] = None


def _integration_status_path(settings: Settings) -> Path:
    if PROJECT_ROOT is not None:
        return PROJECT_ROOT / "integration" / "integration_status.json"
    return settings.resolve_data_path("integration_status.json")


def _canonical_results_root(settings: Settings) -> Path:
    root = (
        PROJECT_ROOT / "results"
        if PROJECT_ROOT is not None
        else settings.resolve_data_path("results")
    )
    root.mkdir(parents=True, exist_ok=True)
    return root


def init_container(
    settings: Optional[Settings] = None,
    runtime_secrets: RuntimeSecrets | None = None,
) -> AppContainer:
    global _container
    settings = settings or get_settings()
    runtime_secrets = runtime_secrets or RuntimeSecrets.from_env()
    cache = MemoryCache()
    store = KlineStore(settings.resolve_data_path(settings.data.kline_store))
    data = CompositeMarketData(settings, cache, store)
    orderflow = OrderFlowProvider(settings.data, cache, http=data.http)
    analyze = AnalyzeService(data, settings)
    backtest = BacktestService(data, settings)
    scan = ScanWorker(analyze, settings)
    report_store = ReportStore(
        settings.resolve_data_path(settings.research.report_dir),
        ttl_hours=settings.research.ttl_hours,
        replace_same_kind=settings.research.replace_same_kind,
        max_bytes=settings.research.max_report_bytes,
    )
    research = ResearchService(
        analyze,
        public_config=settings.research,
        runtime_secrets=runtime_secrets,
        report_store=report_store,
    )
    observation_store = ObservationStore(settings.resolve_data_path("observations.jsonl"))
    observation_service = ObservationService(
        ttl=timedelta(minutes=15),
        analyzer=analyze,
        store=observation_store,
    )
    v1 = V1Services(
        integration_status=IntegrationStatusService(_integration_status_path(settings)),
        observation_store=observation_store,
        observation_service=observation_service,
        research_readiness=ResearchReadinessFacade(_canonical_results_root(settings)),
    )
    _container = AppContainer(
        settings=settings,
        secrets=runtime_secrets,
        cache=cache,
        store=store,
        data=data,
        orderflow=orderflow,
        analyze=analyze,
        backtest=backtest,
        scan=scan,
        research=research,
        report_store=report_store,
        v1=v1,
    )
    return _container


def get_container() -> AppContainer:
    if _container is None:
        return init_container()
    return _container


class ContainerV1ServiceProvider:
    """Resolve the active container lazily so app creation remains side-effect free."""

    @staticmethod
    def _services() -> V1Services:
        return get_container().v1

    def get_integration_status(self):
        return self._services().get_integration_status()

    def capture_observation(self, symbol: str, period: str):
        return self._services().capture_observation(symbol, period)

    def list_observations(self, *, limit: int, offset: int):
        return self._services().list_observations(limit=limit, offset=offset)

    def get_observation(self, observation_id: str):
        return self._services().get_observation(observation_id)

    def list_research_runs(self, *, limit: int):
        return self._services().list_research_runs(limit=limit)

    def get_research_readiness(self, run_id: str):
        return self._services().get_research_readiness(run_id)


def get_v1_service_provider() -> ContainerV1ServiceProvider:
    return ContainerV1ServiceProvider()


def shutdown_container() -> None:
    global _container
    if _container:
        _container.data.close()
        _container = None
