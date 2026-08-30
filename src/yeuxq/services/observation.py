"""Explicit bridge from application analysis results to observations.

The bridge deliberately has no research-storage or broker dependency.  Building
an observation is pure; persistence only happens through an explicitly named
``capture`` method and an injected :class:`~yeuxq.observation_store.ObservationStore`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
import math
from typing import Any, Protocol
from uuid import uuid4

from yeuxq.contracts import (
    ContractValidationError,
    SHANGHAI_TZ,
    SymbolId,
    TrendAction,
    TrendObservation,
    canonical_json_bytes,
    canonical_sha256,
)
from yeuxq.observation_store import ObservationStore


DEFAULT_SOURCE = "yeuxq.analyze"
DEFAULT_ENGINE = "yeuxq.python.analysis"
MAX_METADATA_BYTES = 4_096
MAX_METADATA_TEXT = 128


class ObservationBuildError(ValueError):
    """Raised when an analysis result cannot safely become an observation."""


class AnalyzeRunner(Protocol):
    """Structural subset of :class:`AnalyzeService` used by this bridge."""

    def analyze(self, symbol: str, period: str = "day") -> dict[str, Any]: ...


class ObservationAppender(Protocol):
    """Narrow persistence capability accepted by :class:`ObservationService`."""

    def append(self, observation: TrendObservation) -> str: ...


Clock = Callable[[], datetime]
ObservationIdFactory = Callable[[], str]


_ACTION_MAP: dict[str, TrendAction] = {
    "BUY": TrendAction.BUY,
    "STRONG_BUY": TrendAction.BUY,
    "买入": TrendAction.BUY,
    "强烈买入": TrendAction.BUY,
    "谨慎买入": TrendAction.BUY,
    "逢低买入": TrendAction.BUY,
    "SELL": TrendAction.SELL,
    "STRONG_SELL": TrendAction.SELL,
    "卖出": TrendAction.SELL,
    "强烈卖出": TrendAction.SELL,
    "减仓": TrendAction.SELL,
    "清仓": TrendAction.SELL,
    "止损": TrendAction.SELL,
    "HOLD": TrendAction.HOLD,
    "WAIT": TrendAction.HOLD,
    "NEUTRAL": TrendAction.HOLD,
    "观望": TrendAction.HOLD,
    "持有": TrendAction.HOLD,
    "等待": TrendAction.HOLD,
    "不操作": TrendAction.HOLD,
}


def _default_clock() -> datetime:
    return datetime.now(SHANGHAI_TZ)


def _default_id_factory() -> str:
    return f"obs-{uuid4().hex}"


def map_donor_action(value: object) -> TrendAction:
    """Map only exact, known donor labels to the advisory action vocabulary.

    Substring and fuzzy matching are intentionally avoided.  For example,
    ``"不要买入"`` must not accidentally acquire BUY semantics.
    """

    if isinstance(value, TrendAction):
        return value
    if not isinstance(value, str):
        return TrendAction.UNKNOWN
    return _ACTION_MAP.get(value.strip().upper(), TrendAction.UNKNOWN)


def _require_mapping(value: object, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ObservationBuildError(f"{field_name} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise ObservationBuildError(f"{field_name} keys must be strings")
    return value


def _bounded_text(value: object, *, limit: int = MAX_METADATA_TEXT) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized[:limit]


def _finite_number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _aware_received_at(clock: Clock) -> datetime:
    value = clock()
    if not isinstance(value, datetime):
        raise ObservationBuildError("clock must return a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ObservationBuildError("clock must return a timezone-aware datetime")
    return value.astimezone(SHANGHAI_TZ)


def _event_time(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ObservationBuildError("latest kline date must use ISO-8601") from exc
    else:
        raise ObservationBuildError("latest kline must contain an ISO-8601 date")

    # Donor daily bars carry a market-local calendar date without an offset.
    # Midnight preserves that stated date and remains valid during an open session.
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=SHANGHAI_TZ)
    return parsed.astimezone(SHANGHAI_TZ)


def _positive_ttl(value: timedelta) -> timedelta:
    if not isinstance(value, timedelta) or value <= timedelta(0):
        raise ObservationBuildError("ttl must be an explicit positive timedelta")
    return value


def _version(payload: Mapping[str, Any]) -> str:
    meta_value = payload.get("meta")
    if meta_value is None:
        return "unknown"
    meta = _require_mapping(meta_value, "meta")
    value = _bounded_text(meta.get("engine_version"))
    return value or "unknown"


def _metadata(
    *,
    raw_action: object,
    signal: Mapping[str, Any],
    kline_count: int,
    latest_date: object,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "data_class": "observation",
        "usage_scope": "research-only",
        "research_evidence": False,
        "automatic_research_promotion": False,
        "broker_access": False,
        "live_trading_allowed": False,
        "donor_action": _bounded_text(raw_action, limit=64),
        "score": _finite_number(signal.get("score")),
        "confidence": _finite_number(signal.get("confidence")),
        "kline_count": kline_count,
        "latest_kline_date": _bounded_text(
            latest_date.isoformat() if isinstance(latest_date, datetime) else latest_date
        ),
    }
    try:
        encoded = canonical_json_bytes(metadata)
    except (TypeError, ValueError) as exc:
        raise ObservationBuildError("observation metadata is not canonical JSON") from exc
    if len(encoded) > MAX_METADATA_BYTES:
        raise ObservationBuildError("observation metadata exceeds its size boundary")
    return metadata


class ObservationService:
    """Build and explicitly capture advisory observations from analysis output."""

    def __init__(
        self,
        *,
        ttl: timedelta,
        analyzer: AnalyzeRunner | None = None,
        store: ObservationAppender | ObservationStore | None = None,
        clock: Clock = _default_clock,
        id_factory: ObservationIdFactory = _default_id_factory,
        source: str = DEFAULT_SOURCE,
        engine: str = DEFAULT_ENGINE,
    ) -> None:
        self._ttl = _positive_ttl(ttl)
        if not callable(clock):
            raise ObservationBuildError("clock must be callable")
        if not callable(id_factory):
            raise ObservationBuildError("id_factory must be callable")
        self._analyzer = analyzer
        self._store = store
        self._clock = clock
        self._id_factory = id_factory
        self._source = source
        self._engine = engine

    def build(
        self,
        payload: Mapping[str, Any],
        *,
        expected_symbol: str | SymbolId | None = None,
    ) -> TrendObservation:
        """Purely build one observation; this method never writes to a store."""

        result = _require_mapping(payload, "analysis payload")
        if "error" in result:
            raise ObservationBuildError("analysis payload reports an error")

        try:
            symbol = SymbolId.parse(result.get("symbol"))
        except ContractValidationError as exc:
            raise ObservationBuildError("analysis payload has an invalid symbol") from exc
        if expected_symbol is not None:
            try:
                requested = SymbolId.parse(expected_symbol)
            except ContractValidationError as exc:
                raise ObservationBuildError("requested symbol is invalid") from exc
            if symbol != requested:
                raise ObservationBuildError("analysis result symbol does not match the request")

        period = result.get("period")
        if not isinstance(period, str) or not period.strip():
            raise ObservationBuildError("analysis payload has no period")
        timeframe = period.strip().lower()

        klines_value = result.get("klines")
        if not isinstance(klines_value, Sequence) or isinstance(
            klines_value, (str, bytes, bytearray)
        ):
            raise ObservationBuildError("analysis payload klines must be an array")
        if not klines_value:
            raise ObservationBuildError("analysis payload contains no klines")
        latest = _require_mapping(klines_value[-1], "latest kline")
        latest_date = latest.get("date")
        event_time = _event_time(latest_date)

        signal = _require_mapping(result.get("signal"), "signal")
        raw_action = signal.get("action")
        action = map_donor_action(raw_action)
        received_at = _aware_received_at(self._clock)

        try:
            stale_after = received_at + self._ttl
        except OverflowError as exc:
            raise ObservationBuildError("ttl produces an invalid stale boundary") from exc

        meta_value = result.get("meta")
        meta = {} if meta_value is None else _require_mapping(meta_value, "meta")
        code_descriptor = {
            "engine": self._engine,
            "version": _version(result),
            "runtime": meta.get("engine"),
        }
        config_descriptor = {
            "period": timeframe,
            "reported_kline_count": _finite_number(meta.get("kline_count")),
            "prediction_horizon_days": _finite_number(
                (signal.get("prediction") or {}).get("horizon_days")
                if isinstance(signal.get("prediction"), Mapping)
                else None
            ),
        }
        try:
            data_fingerprint = canonical_sha256(dict(result))
            code_fingerprint = canonical_sha256(code_descriptor)
            config_fingerprint = canonical_sha256(config_descriptor)
        except (TypeError, ValueError) as exc:
            raise ObservationBuildError("analysis payload is not canonical JSON") from exc

        reason = f"ANALYSIS_ACTION_{action.value}"
        try:
            return TrendObservation(
                observation_id=self._id_factory(),
                symbol=symbol,
                event_time=event_time,
                received_at=received_at,
                timeframe=timeframe,
                source=self._source,
                engine=self._engine,
                version=_version(result),
                data_fingerprint=data_fingerprint,
                code_fingerprint=code_fingerprint,
                config_fingerprint=config_fingerprint,
                reason_codes=(reason,),
                stale_after=stale_after,
                action=action,
                metadata=_metadata(
                    raw_action=raw_action,
                    signal=signal,
                    kline_count=len(klines_value),
                    latest_date=latest_date,
                ),
                prohibited_live_use=True,
                broker_access=False,
                live_trading_allowed=False,
            )
        except ContractValidationError as exc:
            raise ObservationBuildError(
                "analysis payload violates the observation contract"
            ) from exc

    def build_from_service(self, symbol: str, period: str = "day") -> TrendObservation:
        """Call the injected AnalyzeService-compatible object, without persistence."""

        if self._analyzer is None:
            raise ObservationBuildError("analyzer is required for service-based builds")
        payload = self._analyzer.analyze(symbol, period)
        return self.build(payload, expected_symbol=symbol)

    def capture(
        self,
        value: Mapping[str, Any] | TrendObservation,
        *,
        expected_symbol: str | SymbolId | None = None,
    ) -> TrendObservation:
        """Append a supplied or newly built observation to the injected store."""

        if self._store is None:
            raise ObservationBuildError("store is required for capture")
        observation = (
            value
            if isinstance(value, TrendObservation)
            else self.build(value, expected_symbol=expected_symbol)
        )
        self._store.append(observation)
        return observation

    def capture_from_service(self, symbol: str, period: str = "day") -> TrendObservation:
        """Analyze, validate, and explicitly append a new observation."""

        if self._store is None:
            raise ObservationBuildError("store is required for capture")
        observation = self.build_from_service(symbol, period)
        self._store.append(observation)
        return observation


def build_observation(
    payload: Mapping[str, Any],
    *,
    ttl: timedelta,
    clock: Clock = _default_clock,
    id_factory: ObservationIdFactory = _default_id_factory,
    source: str = DEFAULT_SOURCE,
    engine: str = DEFAULT_ENGINE,
) -> TrendObservation:
    """Functional entry point for callers that do not need a service object."""

    return ObservationService(
        ttl=ttl,
        clock=clock,
        id_factory=id_factory,
        source=source,
        engine=engine,
    ).build(payload)


__all__ = [
    "AnalyzeRunner",
    "DEFAULT_ENGINE",
    "DEFAULT_SOURCE",
    "MAX_METADATA_BYTES",
    "ObservationAppender",
    "ObservationBuildError",
    "ObservationService",
    "build_observation",
    "map_donor_action",
]
