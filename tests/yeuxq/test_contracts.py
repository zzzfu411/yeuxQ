from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib

import pytest

from yeuxq.contracts import (
    ContractValidationError,
    SHANGHAI_TZ,
    SymbolId,
    TrendAction,
    TrendObservation,
    canonical_json,
    canonical_json_bytes,
    canonical_sha256,
)


def _observation(**overrides: object) -> TrendObservation:
    event_time = datetime(2026, 8, 30, 9, 30, tzinfo=SHANGHAI_TZ)
    values: dict[str, object] = {
        "observation_id": "obs-0001",
        "symbol": "sh600519",
        "event_time": event_time,
        "received_at": event_time + timedelta(seconds=2),
        "timeframe": "1d",
        "source": "stock-adapter",
        "engine": "trend-engine",
        "version": "1.0.0",
        "data_fingerprint": canonical_sha256({"bars": [1, 2, 3]}),
        "code_fingerprint": canonical_sha256({"git": "abc123"}),
        "config_fingerprint": canonical_sha256({"window": 20}),
        "reason_codes": ("MA_CROSS_UP", "VOLUME_CONFIRMED"),
        "stale_after": event_time + timedelta(minutes=5),
        "action": TrendAction.BUY,
        "metadata": {"score": 0.75},
    }
    values.update(overrides)
    return TrendObservation(**values)


@pytest.mark.parametrize("raw", ["sh600519", "SH.600519", "600519.SH", "600519"])
def test_symbol_id_normalizes_common_formats(raw: str) -> None:
    symbol = SymbolId(raw)

    assert str(symbol) == "600519.SH"
    assert symbol.value == "600519.SH"
    assert symbol.vendor_prefix == "sh600519"


def test_symbol_id_infers_other_mainland_exchanges_and_rejects_conflicts() -> None:
    assert str(SymbolId("000001")) == "000001.SZ"
    assert str(SymbolId("830001")) == "830001.BJ"
    with pytest.raises(ContractValidationError, match="conflicting"):
        SymbolId("SH600519.SZ")


@pytest.mark.parametrize("exchange", ["", "  ", 1])
def test_symbol_id_rejects_invalid_explicit_exchange(exchange: object) -> None:
    with pytest.raises(ContractValidationError, match="exchange must"):
        SymbolId("600519", exchange=exchange)  # type: ignore[arg-type]


@pytest.mark.parametrize("raw", ["６００５１９", "60051١", "SH６００５１９"])
def test_symbol_id_rejects_non_ascii_digits(raw: str) -> None:
    with pytest.raises(ContractValidationError, match="six digits"):
        SymbolId(raw)


def test_canonical_json_and_sha256_are_order_independent_and_utf8() -> None:
    first = {"z": 1, "中文": [True, None], "a": 2}
    second = {"a": 2, "中文": [True, None], "z": 1}

    assert canonical_json(first) == '{"a":2,"z":1,"中文":[true,null]}'
    assert canonical_json_bytes(first) == canonical_json(second).encode("utf-8")
    assert canonical_sha256(first) == hashlib.sha256(canonical_json_bytes(first)).hexdigest()


def test_observation_converts_aware_times_to_asia_shanghai_and_checks_freshness() -> None:
    utc_event = datetime(2026, 8, 30, 1, 30, tzinfo=timezone.utc)
    observation = _observation(
        event_time=utc_event,
        received_at=utc_event + timedelta(seconds=1),
        stale_after=utc_event + timedelta(minutes=1),
    )

    assert observation.event_time.hour == 9
    assert observation.event_time.tzinfo is SHANGHAI_TZ
    assert observation.received_at.tzinfo is SHANGHAI_TZ
    assert not observation.is_stale(utc_event + timedelta(seconds=59))
    assert observation.is_stale(utc_event + timedelta(minutes=1))


@pytest.mark.parametrize("field_name", ["event_time", "received_at", "stale_after"])
def test_observation_rejects_naive_contract_times(field_name: str) -> None:
    with pytest.raises(ContractValidationError, match="timezone-aware"):
        _observation(**{field_name: datetime(2026, 8, 30, 9, 30)})


def test_observation_requires_received_order_and_nonexpired_freshness_window() -> None:
    event_time = datetime(2026, 8, 30, 9, 30, tzinfo=SHANGHAI_TZ)
    with pytest.raises(ContractValidationError, match="received_at"):
        _observation(received_at=event_time - timedelta(microseconds=1))
    with pytest.raises(ContractValidationError, match="stale_after"):
        _observation(
            stale_after=event_time + timedelta(seconds=1),
            received_at=event_time + timedelta(seconds=1),
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("data_fingerprint", "abc"),
        ("code_fingerprint", "g" * 64),
        ("config_fingerprint", "0" * 63),
    ],
)
def test_observation_requires_sha256_fingerprints(field_name: str, value: str) -> None:
    with pytest.raises(ContractValidationError, match=field_name):
        _observation(**{field_name: value})


def test_observation_is_advisory_only_and_serializes_explicit_denials() -> None:
    observation = _observation(action="buy")
    payload = observation.to_dict()

    assert observation.action is TrendAction.BUY
    assert payload["prohibited_live_use"] is True
    assert payload["broker_access"] is False
    assert payload["live_trading_allowed"] is False
    assert payload["action"] == "BUY"
    assert TrendObservation.from_dict(payload).to_dict() == payload


@pytest.mark.parametrize(
    "override",
    [
        {"action": "STRONG_BUY"},
        {"prohibited_live_use": False},
        {"broker_access": True},
        {"live_trading_allowed": True},
    ],
)
def test_observation_rejects_unsafe_action_or_capabilities(override: dict[str, object]) -> None:
    with pytest.raises(ContractValidationError):
        _observation(**override)


def test_reason_codes_are_nonempty_normalized_and_unique() -> None:
    assert _observation(reason_codes=["ma_cross_up"]).reason_codes == ("MA_CROSS_UP",)
    with pytest.raises(ContractValidationError, match="at least one"):
        _observation(reason_codes=[])
    with pytest.raises(ContractValidationError, match="duplicate"):
        _observation(reason_codes=["MA_CROSS_UP", "ma_cross_up"])


def test_observation_fingerprint_changes_with_meaningful_content() -> None:
    first = _observation()
    same = TrendObservation.from_dict(first.to_dict())
    changed = _observation(observation_id="obs-0002", action="SELL")

    assert first.fingerprint == same.fingerprint
    assert first.fingerprint != changed.fingerprint


def test_observation_metadata_is_deeply_immutable_and_serializes_to_plain_json() -> None:
    metadata = {"levels": [{"price": 12.5}], "tags": ["research"]}
    observation = _observation(metadata=metadata)
    metadata["levels"][0]["price"] = 99.0

    assert observation.metadata["levels"][0]["price"] == 12.5
    with pytest.raises(TypeError):
        observation.metadata["levels"][0]["price"] = 10.0  # type: ignore[index]
    assert observation.to_dict()["metadata"] == {
        "levels": [{"price": 12.5}],
        "tags": ["research"],
    }


def test_observation_rejects_boolean_schema_version() -> None:
    with pytest.raises(ContractValidationError, match="schema_version"):
        _observation(schema_version=True)


def test_observation_rejects_control_characters_in_contract_identifiers() -> None:
    with pytest.raises(ContractValidationError, match="unsupported characters"):
        _observation(source="provider\nspoofed")
