"""Market regime notes for strategy research."""
from __future__ import annotations

from quantify.market.detector import (
    MarketRegimeReport,
    detect_market_regime,
    write_market_regime_report,
)
from quantify.market.index_discovery import (
    MarketIndexCandidate,
    MarketIndexDiscoveryReport,
    build_market_index_discovery_report,
    write_market_index_discovery_report,
)
from quantify.market.operator_packet import (
    MarketContextOperatorItem,
    MarketContextOperatorPacket,
    build_market_context_operator_packet,
    write_market_context_operator_packet,
)
from quantify.market.readiness import (
    MarketContextReadiness,
    MarketContextReadinessFinding,
    build_market_context_readiness_from_payload,
    build_market_context_readiness_from_report,
    write_market_context_readiness,
)
from quantify.market.regime import MarketRegimeNote, write_market_regime_note
from quantify.market.snapshot import (
    MarketContextIndexMetric,
    MarketContextSnapshot,
    build_market_context_snapshot,
    build_market_context_snapshot_from_csvs,
    read_market_context_index_metrics_from_csvs,
    write_market_context_snapshot,
)

__all__ = [
    "MarketContextIndexMetric",
    "MarketContextOperatorItem",
    "MarketContextOperatorPacket",
    "MarketContextReadiness",
    "MarketContextReadinessFinding",
    "MarketContextSnapshot",
    "MarketIndexCandidate",
    "MarketIndexDiscoveryReport",
    "MarketRegimeNote",
    "MarketRegimeReport",
    "build_market_index_discovery_report",
    "build_market_context_operator_packet",
    "build_market_context_readiness_from_payload",
    "build_market_context_readiness_from_report",
    "build_market_context_snapshot",
    "build_market_context_snapshot_from_csvs",
    "detect_market_regime",
    "read_market_context_index_metrics_from_csvs",
    "write_market_index_discovery_report",
    "write_market_context_operator_packet",
    "write_market_context_snapshot",
    "write_market_context_readiness",
    "write_market_regime_note",
    "write_market_regime_report",
]
