from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from yeuxq.contracts import SHANGHAI_TZ, TrendAction, canonical_sha256
from yeuxq.observation_store import ObservationStore
from yeuxq.services.observation import (
    MAX_METADATA_BYTES,
    ObservationBuildError,
    ObservationService,
    map_donor_action,
)


NOW = datetime(2024, 6, 15, 9, 30, tzinfo=SHANGHAI_TZ)


def _payload(*, action: object = "强烈买入", last_date: object = "2024-06-14") -> dict:
    return {
        "symbol": "sh600519",
        "period": "day",
        "quote": {"price": 1_500.0},
        "signal": {
            "action": action,
            "score": 78,
            "confidence": 66,
            "prediction": {"horizon_days": 5},
        },
        "klines": [
            {"date": "2024-06-13", "close": 1_490.0},
            {"date": last_date, "close": 1_500.0},
        ],
        "flows": [],
        "breadth": {"available": True, "complete": True},
        "meta": {
            "engine_version": "2.1.0",
            "kline_count": 250,
            "engine": {"available": False, "mode": None},
        },
        "disclaimer": "仅供技术分析学习，不构成投资建议",
    }


def _builder(**kwargs: object) -> ObservationService:
    return ObservationService(
        ttl=timedelta(hours=2),
        clock=lambda: NOW,
        id_factory=lambda: "obs-fixed",
        **kwargs,
    )


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("强烈买入", TrendAction.BUY),
        ("谨慎买入", TrendAction.BUY),
        ("卖出", TrendAction.SELL),
        ("减仓", TrendAction.SELL),
        ("观望", TrendAction.HOLD),
        ("hold", TrendAction.HOLD),
        ("不要买入", TrendAction.UNKNOWN),
        (None, TrendAction.UNKNOWN),
    ],
)
def test_donor_action_mapping_is_an_exact_fail_closed_allowlist(
    label: object,
    expected: TrendAction,
) -> None:
    assert map_donor_action(label) is expected
    assert _builder().build(_payload(action=label)).action is expected


def test_build_uses_last_kline_date_shanghai_clock_and_explicit_ttl() -> None:
    observation = _builder().build(_payload())

    assert str(observation.symbol) == "600519.SH"
    assert observation.event_time == datetime(2024, 6, 14, tzinfo=SHANGHAI_TZ)
    assert observation.received_at == NOW
    assert observation.stale_after == NOW + timedelta(hours=2)
    assert not observation.is_stale(NOW + timedelta(hours=1, minutes=59))
    assert observation.is_stale(NOW + timedelta(hours=2))
    assert observation.prohibited_live_use is True
    assert observation.broker_access is False
    assert observation.live_trading_allowed is False


def test_fingerprints_are_canonical_and_sensitive_to_analysis_data() -> None:
    payload = _payload()
    first = _builder().build(payload)
    same = _builder().build(deepcopy(payload))
    changed_payload = deepcopy(payload)
    changed_payload["signal"]["score"] = 79
    changed = _builder().build(changed_payload)

    assert first.data_fingerprint == canonical_sha256(payload)
    assert first.fingerprint == same.fingerprint
    assert first.data_fingerprint != changed.data_fingerprint
    assert first.fingerprint != changed.fingerprint
    assert len(first.code_fingerprint) == len(first.config_fingerprint) == 64


def test_metadata_is_small_json_and_carries_fixed_research_only_policy() -> None:
    payload = _payload(action="X" * 10_000)
    observation = _builder().build(payload)
    metadata = observation.to_dict()["metadata"]

    assert metadata["data_class"] == "observation"
    assert metadata["usage_scope"] == "research-only"
    assert metadata["research_evidence"] is False
    assert metadata["automatic_research_promotion"] is False
    assert metadata["broker_access"] is False
    assert metadata["live_trading_allowed"] is False
    assert len(metadata["donor_action"]) == 64
    assert len(str(metadata).encode("utf-8")) < MAX_METADATA_BYTES
    assert "trade_plan" not in metadata
    assert "klines" not in metadata


@pytest.mark.parametrize(
    "payload",
    [
        {"error": "provider unavailable"},
        {**_payload(), "klines": []},
        {**_payload(), "signal": None},
        {**_payload(), "klines": [{"date": "not-a-date"}]},
    ],
)
def test_error_incomplete_and_empty_payloads_fail_closed(payload: dict) -> None:
    with pytest.raises(ObservationBuildError):
        _builder().build(payload)


def test_invalid_clock_and_ttl_fail_closed() -> None:
    with pytest.raises(ObservationBuildError, match="positive timedelta"):
        ObservationService(ttl=timedelta(0))

    service = ObservationService(
        ttl=timedelta(minutes=5),
        clock=lambda: datetime(2024, 6, 15, 9, 30),
    )
    with pytest.raises(ObservationBuildError, match="timezone-aware"):
        service.build(_payload())


def test_build_never_writes_and_capture_is_the_explicit_append(tmp_path) -> None:
    store = ObservationStore(tmp_path)
    service = _builder(store=store)

    built = service.build(_payload())
    assert not store.path.exists()

    captured = service.capture(built)
    assert captured is built
    assert store.path.exists()
    assert store.read_all() == (built,)


def test_service_call_checks_symbol_and_only_capture_writes(tmp_path) -> None:
    class Analyzer:
        calls: list[tuple[str, str]] = []

        def analyze(self, symbol: str, period: str = "day") -> dict:
            self.calls.append((symbol, period))
            return _payload()

    analyzer = Analyzer()
    store = ObservationStore(tmp_path)
    ids = iter(("obs-service-build", "obs-service-capture"))
    service = ObservationService(
        ttl=timedelta(minutes=30),
        analyzer=analyzer,
        store=store,
        clock=lambda: NOW,
        id_factory=lambda: next(ids),
    )

    built = service.build_from_service("600519.SH", "day")
    assert built.observation_id == "obs-service-build"
    assert not store.path.exists()

    captured = service.capture_from_service("600519", "day")
    assert captured.observation_id == "obs-service-capture"
    assert store.read_all() == (captured,)
    assert analyzer.calls == [("600519.SH", "day"), ("600519", "day")]

    with pytest.raises(ObservationBuildError, match="does not match"):
        service.build_from_service("000001.SZ", "day")
