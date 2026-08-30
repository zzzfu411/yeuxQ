"""Stable, fail-closed contracts shared by the integrated yeuxQ application.

The objects in this module deliberately carry no broker capability.  A trend
observation is an advisory data point, not an order, signal approval, or piece
of automatically admissible research evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Any, Mapping
from zoneinfo import ZoneInfo


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SYMBOL_PATTERN = re.compile(
    r"^(?:(?P<prefix>SH|SZ|BJ)[.\-_]?)?(?P<code>[0-9]{6})(?:[.\-_]?(?P<suffix>SH|SZ|BJ))?$",
    re.IGNORECASE,
)
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_REASON_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_.:-]{0,63}$")


class ContractValidationError(ValueError):
    """Raised when an application contract is incomplete or unsafe."""


def _infer_exchange(code: str) -> str:
    """Infer the mainland exchange for an unqualified six-digit symbol."""

    if code.startswith(("4", "8", "92")):
        return "BJ"
    if code.startswith(("5", "6", "9")):
        return "SH"
    return "SZ"


@dataclass(frozen=True, slots=True, init=False)
class SymbolId:
    """Canonical mainland security identifier.

    ``sh600519``, ``600519.SH`` and the inferred bare form ``600519`` all
    normalize to ``600519.SH``.  Explicit exchange qualifiers always win, but
    conflicting prefix/suffix qualifiers are rejected.
    """

    code: str
    exchange: str

    def __init__(self, value: str | SymbolId, exchange: str | None = None) -> None:
        if isinstance(value, SymbolId):
            if exchange is not None and exchange.strip().upper() != value.exchange:
                raise ContractValidationError("exchange conflicts with the supplied SymbolId")
            object.__setattr__(self, "code", value.code)
            object.__setattr__(self, "exchange", value.exchange)
            return
        if not isinstance(value, str):
            raise ContractValidationError("symbol must be a string or SymbolId")

        candidate = value.strip().upper()
        match = _SYMBOL_PATTERN.fullmatch(candidate)
        if match is None:
            raise ContractValidationError(
                "symbol must be six digits with an optional SH, SZ, or BJ qualifier"
            )
        code = match.group("code")
        prefix = match.group("prefix")
        suffix = match.group("suffix")
        if exchange is not None and (not isinstance(exchange, str) or not exchange.strip()):
            raise ContractValidationError("exchange must be SH, SZ, or BJ")
        explicit_exchange = exchange.strip().upper() if isinstance(exchange, str) else None
        qualifiers = [item.upper() for item in (prefix, suffix, explicit_exchange) if item]
        if any(item not in {"SH", "SZ", "BJ"} for item in qualifiers):
            raise ContractValidationError("exchange must be SH, SZ, or BJ")
        if len(set(qualifiers)) > 1:
            raise ContractValidationError("symbol contains conflicting exchange qualifiers")

        object.__setattr__(self, "code", code)
        object.__setattr__(self, "exchange", qualifiers[0] if qualifiers else _infer_exchange(code))

    @classmethod
    def parse(cls, value: str | SymbolId) -> SymbolId:
        """Parse *value* into a canonical identifier."""

        return value if isinstance(value, cls) else cls(value)

    @property
    def canonical(self) -> str:
        return f"{self.code}.{self.exchange}"

    @property
    def value(self) -> str:
        """Alias used by adapters that model identifiers as value objects."""

        return self.canonical

    @property
    def vendor_prefix(self) -> str:
        return f"{self.exchange.lower()}{self.code}"

    def __str__(self) -> str:
        return self.canonical


class TrendAction(str, Enum):
    """The complete advisory action vocabulary accepted by yeuxQ."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def parse(cls, value: str | TrendAction) -> TrendAction:
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise ContractValidationError("action must be BUY, SELL, HOLD, or UNKNOWN")
        try:
            return cls(value.strip().upper())
        except ValueError as exc:
            raise ContractValidationError(
                "action must be advisory BUY, SELL, HOLD, or UNKNOWN"
            ) from exc


def _aware_shanghai(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ContractValidationError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ContractValidationError(f"{field_name} must be timezone-aware")
    return value.astimezone(SHANGHAI_TZ)


def _datetime_text(value: datetime) -> str:
    return value.isoformat(timespec="microseconds")


def _normalize_for_json(value: Any) -> Any:
    if isinstance(value, SymbolId):
        return value.canonical
    if isinstance(value, datetime):
        return _datetime_text(_aware_shanghai(value, "datetime"))
    if isinstance(value, Enum):
        return _normalize_for_json(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            return _normalize_for_json(to_dict())
        return {item.name: _normalize_for_json(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical JSON object keys must be strings")
            normalized[key] = _normalize_for_json(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_normalize_for_json(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical JSON does not permit NaN or infinity")
        return value
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Return deterministic UTF-8 JSON text suitable for signing and storage."""

    return json.dumps(
        _normalize_for_json(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Return :func:`canonical_json` encoded as UTF-8."""

    return canonical_json(value).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    """Return the lowercase SHA-256 digest of a canonical JSON value."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _fingerprint(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ContractValidationError(f"{field_name} must be a SHA-256 hex string")
    normalized = value.strip().lower()
    if SHA256_PATTERN.fullmatch(normalized) is None:
        raise ContractValidationError(f"{field_name} must contain exactly 64 hexadecimal digits")
    return normalized


def _short_text(value: str, field_name: str, *, identifier: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > 128:
        raise ContractValidationError(f"{field_name} must not exceed 128 characters")
    if identifier and _IDENTIFIER_PATTERN.fullmatch(normalized) is None:
        raise ContractValidationError(f"{field_name} contains unsupported characters")
    return normalized


def _freeze_json(value: Any) -> Any:
    """Deep-freeze an already normalized JSON value.

    A top-level mapping proxy alone is insufficient because callers could
    otherwise mutate nested dictionaries or lists after an observation had
    been fingerprinted or appended.
    """

    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    """Return plain JSON containers for serialization and API responses."""

    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class TrendObservation:
    """Immutable, provenance-complete advisory trend observation.

    The three capability flags are deliberately part of the serialized
    contract.  They are validated fail-closed and cannot be used to opt into
    order routing or live trading.
    """

    observation_id: str
    symbol: SymbolId | str
    event_time: datetime
    received_at: datetime
    timeframe: str
    source: str
    engine: str
    version: str
    data_fingerprint: str
    code_fingerprint: str
    config_fingerprint: str
    reason_codes: tuple[str, ...] | list[str]
    stale_after: datetime
    action: TrendAction | str = TrendAction.UNKNOWN
    metadata: Mapping[str, Any] = field(default_factory=dict)
    prohibited_live_use: bool = True
    broker_access: bool = False
    live_trading_allowed: bool = False
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "observation_id",
            _short_text(self.observation_id, "observation_id", identifier=True),
        )
        object.__setattr__(self, "symbol", SymbolId.parse(self.symbol))
        event_time = _aware_shanghai(self.event_time, "event_time")
        received_at = _aware_shanghai(self.received_at, "received_at")
        stale_after = _aware_shanghai(self.stale_after, "stale_after")
        if received_at < event_time:
            raise ContractValidationError("received_at must not be earlier than event_time")
        if stale_after <= received_at:
            raise ContractValidationError("stale_after must be later than received_at")
        object.__setattr__(self, "event_time", event_time)
        object.__setattr__(self, "received_at", received_at)
        object.__setattr__(self, "stale_after", stale_after)

        object.__setattr__(
            self, "timeframe", _short_text(self.timeframe, "timeframe", identifier=True)
        )
        object.__setattr__(self, "source", _short_text(self.source, "source", identifier=True))
        object.__setattr__(self, "engine", _short_text(self.engine, "engine", identifier=True))
        object.__setattr__(self, "version", _short_text(self.version, "version", identifier=True))
        object.__setattr__(
            self, "data_fingerprint", _fingerprint(self.data_fingerprint, "data_fingerprint")
        )
        object.__setattr__(
            self, "code_fingerprint", _fingerprint(self.code_fingerprint, "code_fingerprint")
        )
        object.__setattr__(
            self, "config_fingerprint", _fingerprint(self.config_fingerprint, "config_fingerprint")
        )
        object.__setattr__(self, "action", TrendAction.parse(self.action))

        if not isinstance(self.reason_codes, (tuple, list)) or not self.reason_codes:
            raise ContractValidationError("reason_codes must contain at least one reason")
        reasons: list[str] = []
        for reason in self.reason_codes:
            if not isinstance(reason, str):
                raise ContractValidationError("each reason code must be a string")
            normalized_reason = reason.strip().upper()
            if _REASON_CODE_PATTERN.fullmatch(normalized_reason) is None:
                raise ContractValidationError(f"invalid reason code: {reason!r}")
            if normalized_reason in reasons:
                raise ContractValidationError(f"duplicate reason code: {normalized_reason}")
            reasons.append(normalized_reason)
        object.__setattr__(self, "reason_codes", tuple(reasons))

        if not isinstance(self.metadata, Mapping):
            raise ContractValidationError("metadata must be a JSON object")
        try:
            metadata_copy = json.loads(canonical_json(dict(self.metadata)))
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(
                "metadata must contain only canonical JSON values"
            ) from exc
        object.__setattr__(self, "metadata", _freeze_json(metadata_copy))

        if self.prohibited_live_use is not True:
            raise ContractValidationError("prohibited_live_use is permanently true")
        if self.broker_access is not False:
            raise ContractValidationError("broker_access is permanently false")
        if self.live_trading_allowed is not False:
            raise ContractValidationError("live_trading_allowed is permanently false")
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ContractValidationError("unsupported TrendObservation schema_version")

    @property
    def fingerprint(self) -> str:
        """Content fingerprint of the complete serialized observation."""

        return canonical_sha256(self.to_dict())

    def is_stale(self, at: datetime | None = None) -> bool:
        reference = datetime.now(SHANGHAI_TZ) if at is None else _aware_shanghai(at, "at")
        return reference >= self.stale_after

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "observation_id": self.observation_id,
            "symbol": str(self.symbol),
            "event_time": _datetime_text(self.event_time),
            "received_at": _datetime_text(self.received_at),
            "timeframe": self.timeframe,
            "source": self.source,
            "engine": self.engine,
            "version": self.version,
            "data_fingerprint": self.data_fingerprint,
            "code_fingerprint": self.code_fingerprint,
            "config_fingerprint": self.config_fingerprint,
            "reason_codes": list(self.reason_codes),
            "stale_after": _datetime_text(self.stale_after),
            "action": self.action.value,
            "metadata": _thaw_json(self.metadata),
            "prohibited_live_use": self.prohibited_live_use,
            "broker_access": self.broker_access,
            "live_trading_allowed": self.live_trading_allowed,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TrendObservation:
        if not isinstance(value, Mapping):
            raise ContractValidationError("observation payload must be an object")
        expected = {
            "schema_version",
            "observation_id",
            "symbol",
            "event_time",
            "received_at",
            "timeframe",
            "source",
            "engine",
            "version",
            "data_fingerprint",
            "code_fingerprint",
            "config_fingerprint",
            "reason_codes",
            "stale_after",
            "action",
            "metadata",
            "prohibited_live_use",
            "broker_access",
            "live_trading_allowed",
        }
        missing = expected.difference(value)
        extra = set(value).difference(expected)
        if missing or extra:
            details = []
            if missing:
                details.append(f"missing={sorted(missing)!r}")
            if extra:
                details.append(f"extra={sorted(extra)!r}")
            raise ContractValidationError("invalid observation fields: " + ", ".join(details))
        try:
            event_time = datetime.fromisoformat(value["event_time"])
            received_at = datetime.fromisoformat(value["received_at"])
            stale_after = datetime.fromisoformat(value["stale_after"])
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("observation timestamps must use ISO-8601") from exc
        return cls(
            observation_id=value["observation_id"],
            symbol=value["symbol"],
            event_time=event_time,
            received_at=received_at,
            timeframe=value["timeframe"],
            source=value["source"],
            engine=value["engine"],
            version=value["version"],
            data_fingerprint=value["data_fingerprint"],
            code_fingerprint=value["code_fingerprint"],
            config_fingerprint=value["config_fingerprint"],
            reason_codes=value["reason_codes"],
            stale_after=stale_after,
            action=value["action"],
            metadata=value["metadata"],
            prohibited_live_use=value["prohibited_live_use"],
            broker_access=value["broker_access"],
            live_trading_allowed=value["live_trading_allowed"],
            schema_version=value["schema_version"],
        )


__all__ = [
    "ContractValidationError",
    "SHANGHAI_TZ",
    "SymbolId",
    "TrendAction",
    "TrendObservation",
    "canonical_json",
    "canonical_json_bytes",
    "canonical_sha256",
]
