from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import quantify.data.storage as storage_module
from quantify.data.provenance import (
    LATEST_IMPORT_BATCH_METADATA_KEY,
    LOGICAL_BAR_FINGERPRINT_ALGORITHM,
    LOGICAL_BAR_FINGERPRINT_ALGORITHM_METADATA_KEY,
    LOGICAL_BAR_FINGERPRINT_METADATA_KEY,
    bar_row_fingerprint,
)
from quantify.data.storage import BarStorage


@pytest.fixture
def bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["600001", "000001", "600001"],
            "date": ["2024-01-03", "2024-01-02", "2024-01-02"],
            "open": [10.2, 20.0, 10.0],
            "high": [10.8, 20.9, 10.5],
            "low": [10.1, 19.8, 9.9],
            "close": [10.7, 20.5, 10.2],
            "volume": [12_000.0, 8_000.0, 10_000.0],
            "amount": [125_000.0, 164_000.0, 102_000.0],
        }
    )


def test_logical_fingerprint_is_independent_of_input_order(
    tmp_path: Path,
    bars: pd.DataFrame,
) -> None:
    ordered = BarStorage(tmp_path / "ordered.db")
    shuffled = BarStorage(tmp_path / "shuffled.db")

    ordered_result = ordered.save_bars_with_lineage(bars, source_type="unit_test")
    shuffled_result = shuffled.save_bars_with_lineage(
        bars.sample(frac=1, random_state=17).reset_index(drop=True),
        source_type="unit_test",
    )

    assert ordered_result.post_import_logical_fingerprint == (
        shuffled_result.post_import_logical_fingerprint
    )
    assert ordered.logical_bar_fingerprint() == shuffled.logical_bar_fingerprint()


def test_logical_fingerprint_is_stable_across_vacuum(
    tmp_path: Path,
    bars: pd.DataFrame,
) -> None:
    storage = BarStorage(tmp_path / "vacuum.db")
    storage.save_bars_with_lineage(bars, source_type="unit_test")
    before = storage.logical_bar_fingerprint()

    with sqlite3.connect(storage.db_path) as conn:
        conn.execute("VACUUM")

    assert storage.logical_bar_fingerprint() == before


@pytest.mark.parametrize("column", ["open", "high", "low", "close", "volume", "amount"])
def test_logical_fingerprint_changes_when_any_ohlcva_value_changes(
    tmp_path: Path,
    bars: pd.DataFrame,
    column: str,
) -> None:
    storage = BarStorage(tmp_path / f"changed-{column}.db")
    first = storage.save_bars_with_lineage(bars, source_type="unit_test")
    changed = bars.iloc[[0]].copy()
    changed.loc[changed.index[0], column] += 0.125

    second = storage.save_bars_with_lineage(changed, source_type="unit_test_revision")

    assert second.pre_import_logical_fingerprint == first.post_import_logical_fingerprint
    assert second.post_import_logical_fingerprint != first.post_import_logical_fingerprint


def test_logical_fingerprint_changes_when_a_bar_is_added(
    tmp_path: Path,
    bars: pd.DataFrame,
) -> None:
    storage = BarStorage(tmp_path / "added.db")
    first = storage.save_bars_with_lineage(bars, source_type="unit_test")
    added = bars.iloc[[0]].copy()
    added.loc[added.index[0], "date"] = "2024-01-04"

    second = storage.save_bars_with_lineage(added, source_type="unit_test_append")

    assert second.post_import_logical_fingerprint != first.post_import_logical_fingerprint


def test_logical_fingerprint_changes_when_a_bar_is_deleted(
    tmp_path: Path,
    bars: pd.DataFrame,
) -> None:
    storage = BarStorage(tmp_path / "deleted.db")
    original = storage.save_bars_with_lineage(bars, source_type="unit_test")

    with sqlite3.connect(storage.db_path) as conn:
        conn.execute(
            "DELETE FROM bars WHERE symbol = ? AND date = ?",
            (str(bars.iloc[0]["symbol"]), str(bars.iloc[0]["date"])),
        )

    assert storage.logical_bar_fingerprint() != original.post_import_logical_fingerprint


def test_import_persists_batch_and_row_lineage_without_conflating_csv_fingerprint(
    tmp_path: Path,
    bars: pd.DataFrame,
) -> None:
    storage = BarStorage(tmp_path / "lineage.db")
    csv_fingerprint = "sha256:source-csv-fixture"

    result = storage.save_bars_with_lineage(
        bars,
        source_type="guarded_local_csv",
        source_reference="bars.csv",
        source_fingerprint_kind="csv_dataset_fingerprint",
        source_fingerprint=csv_fingerprint,
        source_metadata={"encoding": "utf-8"},
        cache_metadata={"csv_dataset_fingerprint": csv_fingerprint},
        batch_id="batch-csv-001",
        imported_at_utc="2024-01-05T00:00:00+00:00",
    )

    batches = storage.load_import_batches()
    assert len(batches) == 1
    batch = batches.iloc[0]
    assert batch["batch_id"] == result.batch_id
    assert batch["status"] == "COMMITTED"
    assert batch["source_fingerprint_kind"] == "csv_dataset_fingerprint"
    assert batch["source_fingerprint"] == csv_fingerprint
    assert batch["post_import_logical_fingerprint"] == result.post_import_logical_fingerprint
    assert batch["logical_fingerprint_algorithm"] == LOGICAL_BAR_FINGERPRINT_ALGORITHM
    assert result.post_import_logical_fingerprint != csv_fingerprint

    lineage = storage.load_bar_lineage(result.batch_id)
    assert len(lineage) == len(bars)
    assert set(lineage["batch_id"]) == {result.batch_id}
    expected_row_fingerprints = {
        (str(row.symbol), str(row.date)): bar_row_fingerprint(tuple(row))
        for row in bars[
            ["symbol", "date", "open", "high", "low", "close", "volume", "amount"]
        ].itertuples(index=False)
    }
    actual_row_fingerprints = {
        (str(row.symbol), str(row.date)): str(row.row_fingerprint)
        for row in lineage.itertuples(index=False)
    }
    assert actual_row_fingerprints == expected_row_fingerprints

    metadata = storage.load_metadata()
    assert metadata["csv_dataset_fingerprint"] == csv_fingerprint
    assert metadata[LOGICAL_BAR_FINGERPRINT_METADATA_KEY] == result.post_import_logical_fingerprint
    assert metadata[LOGICAL_BAR_FINGERPRINT_ALGORITHM_METADATA_KEY] == (
        LOGICAL_BAR_FINGERPRINT_ALGORITHM
    )
    assert metadata[LATEST_IMPORT_BATCH_METADATA_KEY] == result.batch_id


def test_duplicate_keys_fail_before_opening_a_database_transaction(
    tmp_path: Path,
    bars: pd.DataFrame,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = BarStorage(tmp_path / "duplicates.db")
    duplicate = pd.concat([bars, bars.iloc[[0]]], ignore_index=True)

    with monkeypatch.context() as patch:
        patch.setattr(storage_module, "sqlite3", _sqlite_that_must_not_connect())
        with pytest.raises(ValueError, match="duplicate"):
            storage.save_bars_with_lineage(duplicate, source_type="unit_test")

    _assert_no_import_writes(storage)


@pytest.mark.parametrize("invalid_value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_values_fail_before_opening_a_database_transaction(
    tmp_path: Path,
    bars: pd.DataFrame,
    monkeypatch: pytest.MonkeyPatch,
    invalid_value: float,
) -> None:
    storage = BarStorage(tmp_path / "non-finite.db")
    invalid = bars.copy()
    invalid.loc[0, "close"] = invalid_value

    with monkeypatch.context() as patch:
        patch.setattr(storage_module, "sqlite3", _sqlite_that_must_not_connect())
        with pytest.raises(ValueError, match="finite"):
            storage.save_bars_with_lineage(invalid, source_type="unit_test")

    _assert_no_import_writes(storage)


def test_lineage_insert_failure_rolls_back_bars_batch_and_metadata(
    tmp_path: Path,
    bars: pd.DataFrame,
) -> None:
    storage = BarStorage(tmp_path / "rollback.db")
    baseline = storage.save_bars_with_lineage(
        bars,
        source_type="unit_test",
        cache_metadata={"retained_metadata": "before"},
        batch_id="baseline-batch",
    )
    before = _database_state(storage)
    changed = bars.iloc[[0]].copy()
    changed.loc[changed.index[0], "close"] += 5.0
    added = bars.iloc[[1]].copy()
    added.loc[added.index[0], "date"] = "2024-01-04"
    attempted = pd.concat([changed, added], ignore_index=True)

    with sqlite3.connect(storage.db_path) as conn:
        conn.execute(
            """
            CREATE TRIGGER reject_lineage_insert
            BEFORE INSERT ON bar_import_lineage
            BEGIN
                SELECT RAISE(ABORT, 'forced lineage failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="forced lineage failure"):
        storage.save_bars_with_lineage(
            attempted,
            source_type="unit_test_revision",
            cache_metadata={
                "retained_metadata": "after",
                "must_not_be_written": "rollback",
            },
            batch_id="failed-batch",
        )

    assert _database_state(storage) == before
    assert storage.logical_bar_fingerprint() == baseline.post_import_logical_fingerprint


def test_legacy_bars_are_not_given_fabricated_batches_or_lineage(
    tmp_path: Path,
    bars: pd.DataFrame,
) -> None:
    storage = BarStorage(tmp_path / "legacy.db")

    storage.save_bars(bars)

    assert storage.load_import_batches().empty
    assert storage.load_bar_lineage().empty
    metadata = storage.load_metadata()
    assert LATEST_IMPORT_BATCH_METADATA_KEY not in metadata
    assert LOGICAL_BAR_FINGERPRINT_METADATA_KEY not in metadata
    assert storage.logical_bar_fingerprint()


def _sqlite_that_must_not_connect() -> SimpleNamespace:
    def fail_connect(*args: object, **kwargs: object) -> None:
        raise AssertionError("invalid input must be rejected before sqlite3.connect")

    return SimpleNamespace(connect=fail_connect)


def _assert_no_import_writes(storage: BarStorage) -> None:
    assert storage.load_import_batches().empty
    assert storage.load_bar_lineage().empty
    assert storage.load_metadata() == {}
    with sqlite3.connect(storage.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM bars").fetchone()[0] == 0


def _database_state(storage: BarStorage) -> tuple[list[tuple[object, ...]], ...]:
    with sqlite3.connect(storage.db_path) as conn:
        bars = conn.execute(
            """
            SELECT symbol, date, open, high, low, close, volume, amount
            FROM bars ORDER BY symbol, date
            """
        ).fetchall()
        batches = conn.execute(
            "SELECT * FROM data_import_batches ORDER BY batch_id"
        ).fetchall()
        lineage = conn.execute(
            """
            SELECT batch_id, symbol, date, row_fingerprint, recorded_at_utc
            FROM bar_import_lineage ORDER BY lineage_id
            """
        ).fetchall()
        metadata = conn.execute(
            "SELECT key, value FROM research_metadata ORDER BY key"
        ).fetchall()
    return bars, batches, lineage, metadata
