from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from quantify.core.event import PortfolioTarget
from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.paper import run_paper_loop
from quantify.research.demo_data import seed_demo_data
from quantify.utils.config import Config


def test_paper_loop_recovers_state_and_appends_new_days(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    state_dir = tmp_path / "paper"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-06-30")
    storage.save_metadata({"csv_dataset_fingerprint": "paper-dataset-v1"})
    cfg = _cfg(cache)

    first = run_paper_loop(
        DataProvider(storage),
        cfg,
        state_dir=state_dir,
        start="2020-04-01",
        end="2020-05-15",
        initial_cash=100_000,
    )
    second = run_paper_loop(
        DataProvider(storage),
        cfg,
        state_dir=state_dir,
        start="2020-05-18",
        end="2020-06-30",
        initial_cash=100_000,
    )
    state = json.loads((state_dir / "paper_state.json").read_text(encoding="utf-8"))
    daily = pd.read_csv(state_dir / "paper_daily.csv")

    assert first.state.as_of == "2020-05-15"
    assert second.run_days[0] > "2020-05-15"
    assert state["as_of"] == "2020-06-30"
    assert state["broker_connection"] == "none"
    assert len(state["run_context"]["data"]["cache_sha256"]) == 64
    assert state["run_context"]["data"]["dataset_fingerprint"] == "paper-dataset-v1"
    assert state["run_context"]["broker"]["price_limit_pct"] == 0.10
    assert state["run_context"]["strategy"]["candidate"] == "price_volume_defensive"
    assert len(daily) == state["observed_days"]
    assert (state_dir / "paper_positions.csv").exists()
    assert (state_dir / "paper_orders.csv").exists()
    assert (state_dir / "paper_daily_review.md").exists()


def test_paper_loop_uses_prior_day_factor_data_and_next_day_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = tmp_path / "signal_execution.db"
    storage = BarStorage(cache)
    _seed_signal_execution_data(storage)
    factor_observations: list[tuple[str, float]] = []

    monkeypatch.setattr(
        "quantify.research.universe.UniverseFilter.symbols",
        lambda self, as_of, data: ["SIGNAL"],
    )

    def prior_close_scores(self, as_of, universe, data):
        observed_close = data.latest_prices(universe, as_of)["SIGNAL"]
        factor_observations.append((as_of, observed_close))
        return pd.DataFrame(
            {"date": [as_of], "symbol": ["SIGNAL"], "score": [observed_close]}
        )

    monkeypatch.setattr(
        "quantify.research.factors.FactorPipeline.composite_scores",
        prior_close_scores,
    )

    state_dir = tmp_path / "paper_signal_execution"
    result = run_paper_loop(
        DataProvider(storage),
        _cfg(cache),
        state_dir=state_dir,
        start="2020-01-02",
        end="2020-01-03",
        initial_cash=100_000,
    )
    review = json.loads((state_dir / "paper_daily_review.json").read_text(encoding="utf-8"))

    assert factor_observations == [("2020-01-02", 10.0)]
    assert len(result.orders) == 1
    assert result.orders[0].timestamp.date().isoformat() == "2020-01-03"
    assert result.orders[0].price == 10.5
    assert result.daily[0]["order_count"] == 0
    assert result.daily[0]["signal_date"] == ""
    assert result.daily[0]["execution_date"] == ""
    assert result.daily[1]["signal_date"] == "2020-01-02"
    assert result.daily[1]["execution_date"] == "2020-01-03"
    assert review["signal_date"] == "2020-01-02"
    assert review["execution_date"] == "2020-01-03"


def test_paper_loop_restores_prior_day_for_t_plus_one_release(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    state_dir = tmp_path / "paper_release"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-01-10")
    cfg = _cfg(cache)
    run_context = run_paper_loop(
        DataProvider(storage),
        cfg,
        state_dir=tmp_path / "paper_context_seed",
        start="2020-01-01",
        end="2020-01-02",
        initial_cash=100_000,
    ).state.run_context
    state_dir.mkdir()
    (state_dir / "paper_state.json").write_text(
        json.dumps(
            {
                "as_of": "2020-01-02",
                "observed_days": 1,
                "candidate": "price_volume_defensive",
                "initial_cash": 100_000,
                "cash": 95_000,
                "last_equity": 100_000,
                "position_count": 1,
                "order_count": 1,
                "rejected_order_count": 0,
                "broker_connection": "none",
                "run_context": run_context,
            }
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        {
            "date": ["2020-01-02"],
            "symbol": ["DEMO001"],
            "quantity": [500],
            "available_qty": [0],
            "price": [10.0],
            "market_value": [5_000.0],
            "weight": [0.05],
            "avg_cost": [10.0],
        }
    ).to_csv(state_dir / "paper_positions.csv", index=False)
    pd.DataFrame(
        {
            "date": ["2020-01-02"],
            "candidate": ["price_volume_defensive"],
            "cash": [95_000.0],
            "equity": [100_000.0],
            "position_count": [1],
            "rebalanced": [True],
            "order_count": [1],
            "rejected_order_count": [0],
            "broker_connection": ["none"],
        }
    ).to_csv(state_dir / "paper_daily.csv", index=False)

    run_paper_loop(
        DataProvider(storage),
        cfg,
        state_dir=state_dir,
        start="2020-01-01",
        end="2020-01-03",
        initial_cash=100_000,
    )
    positions = pd.read_csv(state_dir / "paper_positions.csv")

    restored = positions.loc[positions["symbol"] == "DEMO001"].iloc[0]
    assert int(restored["quantity"]) == 500
    assert int(restored["available_qty"]) == 500


def test_paper_loop_segmented_run_matches_continuous_run(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-06-30")
    cfg = _cfg(cache)
    provider = DataProvider(storage)
    continuous_dir = tmp_path / "paper_continuous"
    segmented_dir = tmp_path / "paper_segmented"

    run_paper_loop(
        provider,
        cfg,
        state_dir=continuous_dir,
        start="2020-04-01",
        end="2020-06-30",
        initial_cash=100_000,
    )
    run_paper_loop(
        provider,
        cfg,
        state_dir=segmented_dir,
        start="2020-04-01",
        end="2020-06-01",
        initial_cash=100_000,
    )
    run_paper_loop(
        provider,
        cfg,
        state_dir=segmented_dir,
        start="2020-05-18",
        end="2020-06-30",
        initial_cash=100_000,
    )

    continuous_state = json.loads((continuous_dir / "paper_state.json").read_text(encoding="utf-8"))
    segmented_state = json.loads((segmented_dir / "paper_state.json").read_text(encoding="utf-8"))
    assert _state_core(segmented_state) == _state_core(continuous_state)
    pd.testing.assert_frame_equal(
        _canonical_frame(segmented_dir / "paper_positions.csv"),
        _canonical_frame(continuous_dir / "paper_positions.csv"),
    )
    pd.testing.assert_frame_equal(
        _canonical_frame(segmented_dir / "paper_orders.csv"),
        _canonical_frame(continuous_dir / "paper_orders.csv"),
    )
    pd.testing.assert_frame_equal(
        _canonical_frame(segmented_dir / "paper_daily.csv"),
        _canonical_frame(continuous_dir / "paper_daily.csv"),
    )


def test_paper_loop_segmented_price_limit_boundary_matches_continuous_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = tmp_path / "price_limit.db"
    storage = BarStorage(cache)
    _seed_price_limit_boundary_data(storage)
    cfg = _cfg(cache)
    provider = DataProvider(storage)
    continuous_dir = tmp_path / "price_limit_continuous"
    segmented_dir = tmp_path / "price_limit_segmented"

    class BoundaryStrategy:
        def on_rebalance(self, as_of: str, data: DataProvider, portfolio) -> list[PortfolioTarget]:
            timestamp = datetime.fromisoformat(as_of)
            if as_of == "2020-01-02":
                return [
                    PortfolioTarget(timestamp, "BASE", 0.25),
                    PortfolioTarget(timestamp, "LIMIT_DOWN", 0.25),
                ]
            return [PortfolioTarget(timestamp, "LIMIT_UP", 0.5)]

    monkeypatch.setattr(
        "quantify.paper.loop._strategy_for_candidate",
        lambda cfg, spec: BoundaryStrategy(),
    )

    continuous = run_paper_loop(
        provider,
        cfg,
        state_dir=continuous_dir,
        start="2020-01-02",
        end="2020-02-04",
        initial_cash=100_000,
    )
    run_paper_loop(
        provider,
        cfg,
        state_dir=segmented_dir,
        start="2020-01-02",
        end="2020-02-03",
        initial_cash=100_000,
    )
    resumed = run_paper_loop(
        provider,
        cfg,
        state_dir=segmented_dir,
        start="2020-01-02",
        end="2020-02-04",
        initial_cash=100_000,
    )

    continuous_boundary_orders = [
        order for order in continuous.orders if order.timestamp.date().isoformat() == "2020-02-04"
    ]
    assert [_order_core(order) for order in resumed.orders] == [
        _order_core(order) for order in continuous_boundary_orders
    ]
    assert any(
        order.symbol == "LIMIT_UP" and order.status == "rejected" and order.reason == "not_buyable"
        for order in resumed.orders
    )
    assert any(
        order.symbol == "LIMIT_DOWN"
        and order.status == "rejected"
        and order.reason == "not_sellable"
        for order in resumed.orders
    )
    pd.testing.assert_frame_equal(
        _canonical_frame(segmented_dir / "paper_orders.csv"),
        _canonical_frame(continuous_dir / "paper_orders.csv"),
    )
    pd.testing.assert_frame_equal(
        _canonical_frame(segmented_dir / "paper_daily.csv"),
        _canonical_frame(continuous_dir / "paper_daily.csv"),
    )


def test_paper_loop_rejects_initial_cash_drift(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-05-29")
    cfg = _cfg(cache)
    state_dir = tmp_path / "paper_initial_cash_lock"

    run_paper_loop(
        DataProvider(storage),
        cfg,
        state_dir=state_dir,
        start="2020-04-01",
        end="2020-04-30",
        initial_cash=100_000,
    )

    with pytest.raises(ValueError, match="initial_cash"):
        run_paper_loop(
            DataProvider(storage),
            cfg,
            state_dir=state_dir,
            start="2020-04-01",
            end="2020-05-29",
            initial_cash=200_000,
        )


def test_paper_loop_rejects_recorded_broker_context_drift(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-05-29")
    state_dir = tmp_path / "paper_broker_context_lock"

    run_paper_loop(
        DataProvider(storage),
        _cfg(cache),
        state_dir=state_dir,
        start="2020-04-01",
        end="2020-04-30",
        initial_cash=100_000,
    )

    with pytest.raises(ValueError, match="run context differs.*broker"):
        run_paper_loop(
            DataProvider(storage),
            _cfg(cache, price_limit_pct=0.20),
            state_dir=state_dir,
            start="2020-04-01",
            end="2020-05-29",
            initial_cash=100_000,
        )


def test_paper_loop_rejects_cache_identity_drift_at_same_path(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-05-29")
    storage.save_metadata({"csv_dataset_fingerprint": "paper-dataset-v1"})
    cfg = _cfg(cache)
    state_dir = tmp_path / "paper_data_identity_lock"

    run_paper_loop(
        DataProvider(storage),
        cfg,
        state_dir=state_dir,
        start="2020-04-01",
        end="2020-04-30",
        initial_cash=100_000,
    )
    storage.save_metadata({"csv_dataset_fingerprint": "paper-dataset-v2"})

    with pytest.raises(ValueError, match="run context differs.*data"):
        run_paper_loop(
            DataProvider(storage),
            cfg,
            state_dir=state_dir,
            start="2020-04-01",
            end="2020-05-29",
            initial_cash=100_000,
        )


def test_paper_loop_rejects_legacy_state_without_run_context(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-05-29")
    cfg = _cfg(cache)
    state_dir = tmp_path / "paper_legacy_state"

    run_paper_loop(
        DataProvider(storage),
        cfg,
        state_dir=state_dir,
        start="2020-04-01",
        end="2020-04-30",
        initial_cash=100_000,
    )
    state_path = state_dir / "paper_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.pop("run_context")
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="missing run_context"):
        run_paper_loop(
            DataProvider(storage),
            cfg,
            state_dir=state_dir,
            start="2020-04-01",
            end="2020-05-29",
            initial_cash=100_000,
        )


def test_paper_loop_rejects_research_manifest_identity_mismatch(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-05-29")
    storage.save_metadata({"csv_dataset_fingerprint": "paper-dataset-v1"})

    with pytest.raises(ValueError, match="cache_sha256"):
        run_paper_loop(
            DataProvider(storage),
            _cfg(cache),
            state_dir=tmp_path / "paper_manifest_identity",
            start="2020-04-01",
            end="2020-04-30",
            initial_cash=100_000,
            expected_cache_sha256="not-the-current-cache-hash",
            expected_dataset_fingerprint="paper-dataset-v1",
        )


def test_paper_loop_rejects_candidate_switch_in_same_state_dir(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-06-30")
    cfg = _cfg(cache)
    state_dir = tmp_path / "paper_candidate_lock"

    run_paper_loop(
        DataProvider(storage),
        cfg,
        state_dir=state_dir,
        start="2020-04-01",
        end="2020-05-15",
        candidate="price_volume_defensive",
        initial_cash=100_000,
    )

    with pytest.raises(ValueError, match="separate state_dir"):
        run_paper_loop(
            DataProvider(storage),
            cfg,
            state_dir=state_dir,
            start="2020-04-01",
            end="2020-06-30",
            candidate="core_multifactor",
            initial_cash=100_000,
        )


def test_paper_loop_cli_writes_outputs(tmp_path: Path) -> None:
    configured_cache = tmp_path / "configured.db"
    cache = tmp_path / "override.db"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-06-30")
    storage.save_metadata({"csv_dataset_fingerprint": "paper-cli-dataset"})
    expected_cache_sha256 = _sha256(cache)
    cfg_path = tmp_path / "research.yaml"
    cfg_path.write_text(_cfg_yaml(configured_cache), encoding="utf-8")
    state_dir = tmp_path / "paper_cli"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_paper_loop.py",
            "--config",
            str(cfg_path),
            "--cache",
            str(cache),
            "--expected-cache-sha256",
            expected_cache_sha256,
            "--expected-dataset-fingerprint",
            "paper-cli-dataset",
            "--state-dir",
            str(state_dir),
            "--start",
            "2020-04-01",
            "--end",
            "2020-06-30",
            "--initial-cash",
            "100000",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    state = json.loads((state_dir / "paper_state.json").read_text(encoding="utf-8"))
    assert state["run_context"]["data"]["cache_path"] == str(cache.resolve())
    assert (state_dir / "paper_state.json").exists()
    assert (state_dir / "paper_daily_review.json").exists()
    assert (state_dir / "paper_loop_run.json").exists()
    assert (state_dir / "paper_stability.json").exists()


def test_paper_loop_adds_regime_pause_manual_question(tmp_path: Path) -> None:
    cache = tmp_path / "research.db"
    state_dir = tmp_path / "paper_regime_pause"
    storage = BarStorage(cache)
    seed_demo_data(storage, "2020-01-01", "2020-06-30")
    cfg = _cfg(cache)

    run_paper_loop(
        DataProvider(storage),
        cfg,
        state_dir=state_dir,
        start="2020-04-01",
        end="2020-06-30",
        candidate="regime_pause_price_volume",
        initial_cash=100_000,
    )
    review = json.loads((state_dir / "paper_daily_review.json").read_text(encoding="utf-8"))

    assert any("regime pause or resume" in item.lower() for item in review["manual_review_questions"])


def test_paper_loop_regime_pause_reduces_targets_under_detected_defensive_market(tmp_path: Path) -> None:
    cache = tmp_path / "weak_regime.db"
    state_dir = tmp_path / "paper_regime_runtime"
    storage = BarStorage(cache)
    _seed_weak_market_data(storage)
    cfg = _cfg(cache)

    run_paper_loop(
        DataProvider(storage),
        cfg,
        state_dir=state_dir,
        start="2020-08-03",
        end="2020-12-31",
        candidate="regime_pause_price_volume",
        initial_cash=100_000,
    )
    daily = pd.read_csv(state_dir / "paper_daily.csv")

    rebalanced = daily[daily["rebalanced"] == True]  # noqa: E712
    assert not rebalanced.empty
    assert float(rebalanced["target_weight_sum"].min()) == 0.0


def _cfg(cache_path: Path, *, price_limit_pct: float = 0.10) -> Config:
    return Config(
        {
            "research": {
                "start": "2020-04-01",
                "end": "2020-06-30",
                "initial_cash": 100_000.0,
                "rebalance": "monthly",
            },
            "data": {"source": "demo", "cache_path": str(cache_path)},
            "universe": {
                "mode": "all_a",
                "index_code": "000906",
                "include_st": False,
                "min_history_days": 20,
            },
            "strategy": {"n_holdings": 5, "max_weight": 0.10},
            "broker": {
                "commission_rate": 0.0,
                "min_commission": 0.0,
                "stamp_tax": 0.0,
                "slippage_bps": 0.0,
                "price_limit_pct": price_limit_pct,
                "lot_size": 100,
            },
        }
    )


def _cfg_yaml(cache_path: Path) -> str:
    return f"""
research:
  start: "2020-04-01"
  end: "2020-06-30"
  initial_cash: 100000.0
  rebalance: monthly
  allow_demo_data: true
data:
  source: demo
  cache_path: "{cache_path.as_posix()}"
universe:
  mode: all_a
  index_code: "000906"
  include_st: false
  min_history_days: 20
strategy:
  n_holdings: 5
  max_weight: 0.10
risk:
  max_drawdown_stop: 0.2
broker:
  commission_rate: 0.0
  min_commission: 0.0
  stamp_tax: 0.0
  slippage_bps: 0.0
  price_limit_pct: 0.10
  lot_size: 100
"""


def _state_core(payload: dict) -> dict:
    keys = [
        "as_of",
        "observed_days",
        "candidate",
        "cash",
        "last_equity",
        "position_count",
        "order_count",
        "rejected_order_count",
        "broker_connection",
    ]
    return {
        key: round(float(payload[key]), 6) if key in {"cash", "last_equity"} else payload[key]
        for key in keys
    }


def _canonical_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    sort_cols = [column for column in ["timestamp", "date", "symbol", "direction"] if column in frame]
    if sort_cols:
        frame = frame.sort_values(sort_cols).reset_index(drop=True)
    for column in frame.select_dtypes(include=["float"]).columns:
        frame[column] = frame[column].round(6)
    return frame


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _order_core(order) -> tuple[str, str, str, int, float, str, str]:
    return (
        order.timestamp.date().isoformat(),
        order.symbol,
        order.direction.value,
        order.quantity,
        order.price,
        order.status,
        order.reason,
    )


def _seed_price_limit_boundary_data(storage: BarStorage) -> None:
    dates = ["2020-01-02", "2020-01-03", "2020-02-03", "2020-02-04"]
    symbols = ["BASE", "LIMIT_DOWN", "LIMIT_UP"]
    storage.save_calendar(dates)
    storage.save_stock_info(pd.DataFrame({"symbol": symbols}))
    storage.save_bars(
        pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "date": day,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1_000_000,
                    "amount": close * 1_000_000,
                }
                for symbol, closes in {
                    "BASE": [10.0, 10.0, 10.0, 10.0],
                    "LIMIT_DOWN": [10.0, 10.0, 10.0, 9.0],
                    "LIMIT_UP": [10.0, 10.0, 10.0, 11.0],
                }.items()
                for day, close in zip(dates, closes, strict=True)
            ]
        )
    )


def _seed_signal_execution_data(storage: BarStorage) -> None:
    dates = ["2020-01-02", "2020-01-03"]
    storage.save_calendar(dates)
    storage.save_stock_info(pd.DataFrame({"symbol": ["SIGNAL"]}))
    storage.save_bars(
        pd.DataFrame(
            [
                {
                    "symbol": "SIGNAL",
                    "date": "2020-01-02",
                    "open": 9.0,
                    "high": 10.2,
                    "low": 8.9,
                    "close": 10.0,
                    "volume": 1_000_000,
                    "amount": 10_000_000,
                },
                {
                    "symbol": "SIGNAL",
                    "date": "2020-01-03",
                    "open": 10.5,
                    "high": 10.9,
                    "low": 10.4,
                    "close": 10.8,
                    "volume": 1_000_000,
                    "amount": 10_800_000,
                },
            ]
        )
    )


def _seed_weak_market_data(storage: BarStorage) -> None:
    symbols = [f"600{i:03d}" for i in range(1, 9)]
    dates = pd.bdate_range("2020-01-01", "2020-12-31")
    storage.save_calendar(dates)
    storage.save_stock_info(
        pd.DataFrame(
            {
                "symbol": symbols,
                "name": [f"weak_{i}" for i, _symbol in enumerate(symbols, start=1)],
                "exchange": ["SSE"] * len(symbols),
                "list_date": ["2015-01-01"] * len(symbols),
                "delist_date": [""] * len(symbols),
                "industry": ["test"] * len(symbols),
                "is_st": [0] * len(symbols),
            }
        )
    )
    frames = []
    for idx, symbol in enumerate(symbols, start=1):
        steps = pd.Series(range(len(dates)), dtype=float)
        close = (30.0 + idx) * (1 - 0.0012 * steps).clip(lower=0.35)
        volume = 1_000_000 + idx * 10_000
        frames.append(
            pd.DataFrame(
                {
                    "symbol": symbol,
                    "date": [day.date().isoformat() for day in dates],
                    "open": close * 1.001,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": volume,
                    "amount": close * volume,
                }
            )
        )
    storage.save_bars(pd.concat(frames, ignore_index=True))
