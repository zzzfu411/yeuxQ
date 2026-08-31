from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta
import json
import math
from pathlib import Path
import sys

import pytest

import yeuxq.analysis.engine as engine_module
import yeuxq.analysis.rust_bridge as rust_bridge
from yeuxq.analysis.engine import run_analysis
from yeuxq.contracts import SHANGHAI_TZ, TrendObservation, canonical_sha256
from yeuxq.domain.models import FundFlow, Kline
from yeuxq.observation_store import ObservationIntegrityError, ObservationStore
from yeuxq.services.observation import ObservationService
from yeuxq.services.research_facade import ResearchReadinessFacade
from yeuxq.settings import Settings


def _bars(kind: str, count: int = 150) -> list[Kline]:
    """Build stable offline fixtures that exercise both bridge runtimes."""

    start = date(2024, 1, 1)
    price = 100.0
    rows: list[Kline] = []
    for index in range(count):
        if kind == "up":
            rate = 0.004 if index % 17 else -0.002
        elif kind == "down":
            rate = -0.004 if index % 17 else 0.002
        else:  # pragma: no cover - callers intentionally use named fixtures
            raise ValueError(f"unknown fixture: {kind}")
        close = price * (1.0 + rate)
        rows.append(
            Kline(
                date=(start + timedelta(days=index)).isoformat(),
                open=price,
                close=close,
                high=max(price, close) * 1.01,
                low=min(price, close) * 0.99,
                volume=10_000 + (index % 11) * 500,
                amount=1_000_000,
                turnover=1.5,
            )
        )
        price = close
    return rows


def _flows(rows: list[Kline]) -> list[FundFlow]:
    return [
        FundFlow(
            date=row.date,
            main_net=1_000_000 if index % 4 else -300_000,
            super_large_net=500_000,
            large_net=500_000,
            medium_net=-100_000,
            small_net=-100_000,
            main_pct=1.5,
        )
        for index, row in enumerate(rows)
    ]


def _rust_payload(rows: list[Kline], flows: list[FundFlow], settings: Settings) -> dict:
    return {
        "klines": engine_module._klines_payload(rows),
        "flows": engine_module._flows_payload(flows),
        "index": engine_module._klines_payload(rows),
        "weekly": [],
        "config": engine_module._cfg_payload(settings),
    }


def _observation(observation_id: str, *, minute: int = 0) -> TrendObservation:
    event_time = datetime(2026, 8, 30, 10, minute, tzinfo=SHANGHAI_TZ)
    return TrendObservation(
        observation_id=observation_id,
        symbol="600519.SH",
        event_time=event_time,
        received_at=event_time + timedelta(seconds=1),
        timeframe="1m",
        source="phase5-test",
        engine="yeuxq.python.analysis",
        version="1.0.0",
        data_fingerprint=canonical_sha256({"id": observation_id}),
        code_fingerprint=canonical_sha256({"code": "phase5"}),
        config_fingerprint=canonical_sha256({"window": 5}),
        reason_codes=("TREND_CONFIRMED",),
        stale_after=event_time + timedelta(minutes=1),
        action="HOLD",
        metadata={
            "data_class": "observation",
            "usage_scope": "research-only",
            "research_evidence": False,
            "automatic_research_promotion": False,
        },
    )


def _readiness_payload(decision: str = "BLOCK") -> dict:
    findings = []
    if decision != "PASS":
        findings = [
            {
                "severity": decision,
                "code": f"CANONICAL_{decision}",
                "message": f"Canonical readiness is {decision}.",
            }
        ]
    return {
        "decision": decision,
        "findings": findings,
        "risk_budget": {
            "manual_reference_only": True,
            "auto_order_submission": False,
            "max_position_pct": 0.05,
            "max_strategy_drawdown_stop": 0.15,
            "single_day_loss_stop": 0.02,
            "max_capital_increase_without_new_review": 0.0,
        },
    }


def test_analysis_rust_failure_is_exactly_the_deterministic_python_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _bars("up")
    flows = _flows(rows)
    settings = Settings()

    monkeypatch.delenv("YEUXQ_ENGINE", raising=False)
    canonical = run_analysis(rows, flows=flows, index_klines=rows, settings=settings)

    monkeypatch.setenv("YEUXQ_ENGINE", "rust")
    monkeypatch.setattr(engine_module, "rust_status", lambda: {"available": True})

    def fail_rust(_: dict) -> dict:
        raise RuntimeError("private rust failure must not escape")

    monkeypatch.setattr(engine_module, "analyze_rust", fail_rust)
    fallback = run_analysis(rows, flows=flows, index_klines=rows, settings=settings)

    assert asdict(fallback) == asdict(canonical)
    assert "private rust failure" not in repr(fallback)


@pytest.mark.parametrize("fixture", ["up", "down"])
def test_optional_rust_analysis_stays_within_documented_parity_tolerance(
    fixture: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rust is optional; when present, compare only bounded decision fields.

    The Python implementation remains canonical.  The fixture deliberately
    disables Rust-only sell/position options so the comparison covers the
    shared indicator path rather than asserting that an experimental Rust
    policy is authoritative.
    """

    executable = rust_bridge._find_cli()
    if executable is None or not executable.is_file():
        pytest.skip("optional trendlab CLI is not available")

    rows = _bars(fixture)
    flows = _flows(rows)
    settings = Settings()
    settings.engine.sell_symmetric = False
    settings.engine.atr_position = False
    settings.engine.chanlun_bonus = False

    monkeypatch.delenv("YEUXQ_ENGINE", raising=False)
    canonical = run_analysis(rows, flows=flows, index_klines=rows, settings=settings)

    # Force the subprocess path even if an unrelated globally installed
    # pyo3 module happens to be importable in the developer environment.
    monkeypatch.setenv("YEUXQ_RUST_BIN", str(executable))
    monkeypatch.setitem(sys.modules, "trendlab_core", None)
    rust = rust_bridge.analyze_rust(_rust_payload(rows, flows, settings))

    assert rust["action"] == canonical.action
    assert abs(int(rust["score"]) - canonical.score) <= 5
    assert abs(int(rust["confidence"]) - canonical.confidence) <= 5
    for name, expected in canonical.module_scores.items():
        assert abs(int(rust["module_scores"][name]) - expected) <= 5

    rust_plan = rust["trade_plan"]
    for name in ("entry_price", "stop_loss", "target_price"):
        assert math.isclose(
            float(rust_plan[name]),
            float(getattr(canonical.trade_plan, name)),
            rel_tol=0.0,
            abs_tol=0.05,
        )
    assert rust["prediction"]["direction"] == canonical.prediction.direction
    assert abs(float(rust["prediction"]["tilt"]) - canonical.prediction.tilt) <= 0.15


def test_source_checkout_does_not_trust_an_ambient_trendlab_on_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rust_bridge, "PROJECT_ROOT", tmp_path)
    ambient = tmp_path / "ambient" / "trendlab.exe"
    monkeypatch.setattr(rust_bridge.shutil, "which", lambda _: str(ambient))

    assert rust_bridge._find_cli() is None


def test_verified_copy_is_the_only_hash_chain_recovery_path(tmp_path: Path) -> None:
    source = ObservationStore(tmp_path / "source")
    source.append(_observation("obs-1"))
    source.append(_observation("obs-2", minute=1))
    known_good = source.path.read_bytes()
    expected = source.read_all()
    expected_head = source.last_record_hash

    # A tampered journal remains unusable and is never repaired in place.
    source.path.write_bytes(known_good.replace(b'"action":"HOLD"', b'"action":"SELL"'))
    with pytest.raises(ObservationIntegrityError):
        source.verify_integrity()
    with pytest.raises(ObservationIntegrityError):
        source.append(_observation("obs-3", minute=2))

    recovered_path = tmp_path / "recovered" / "observations.jsonl"
    recovered_path.parent.mkdir()
    recovered_path.write_bytes(known_good)
    recovered = ObservationStore(recovered_path)

    assert recovered.verify_integrity() is True
    assert recovered.read_all() == expected
    assert recovered.last_record_hash == expected_head
    assert source.path.read_bytes() != known_good


def test_partial_chain_recovery_requires_an_independent_complete_copy(tmp_path: Path) -> None:
    source = ObservationStore(tmp_path / "source")
    source.append(_observation("obs-1"))
    known_good = source.path.read_bytes()
    source.path.write_bytes(known_good.removesuffix(b"\n"))

    with pytest.raises(ObservationIntegrityError, match="partial"):
        source.read_all()

    recovered_path = tmp_path / "recovered.jsonl"
    recovered_path.write_bytes(known_good)
    recovered = ObservationStore(recovered_path)
    recovered_head = recovered.last_record_hash
    assert recovered.validate() == recovered_head
    assert len(recovered.read_all()) == 1


def test_observation_capture_cannot_change_canonical_research_readiness(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    run_root = results_root / "blocked_run"
    run_root.mkdir(parents=True)
    artifact = run_root / "micro_live_readiness.json"
    artifact.write_text(
        json.dumps(
            {
                **_readiness_payload("BLOCK"),
                "observation_decision": "PASS",
                "llm_decision": "PASS",
                "donor_score": 100,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    before = artifact.read_bytes()

    observation_store = ObservationStore(tmp_path / "observations")
    service = ObservationService(
        ttl=timedelta(hours=1),
        store=observation_store,
        clock=lambda: datetime(2026, 8, 30, 11, tzinfo=SHANGHAI_TZ),
        id_factory=lambda: "obs-cross-boundary",
    )
    payload = {
        "symbol": "600519.SH",
        "period": "day",
        "signal": {"action": "强烈买入", "score": 99, "confidence": 99},
        "klines": [{"date": "2026-08-30", "close": 1_500.0}],
        "meta": {"engine_version": "2.0.0"},
    }
    observation = service.capture(payload)

    view = ResearchReadinessFacade(results_root).read("blocked_run")
    assert observation.metadata["research_evidence"] is False
    assert observation.metadata["automatic_research_promotion"] is False
    assert view["decision"] == "BLOCK"
    assert view["reason"] is None
    assert artifact.read_bytes() == before
    assert not (tmp_path / "observations" / "blocked_run").exists()
