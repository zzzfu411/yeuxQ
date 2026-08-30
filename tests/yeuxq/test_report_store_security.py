from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

import pytest

from yeuxq.intel import report_store as report_module
from yeuxq.intel.report_store import (
    ReportExpiredError,
    ReportId,
    ReportKind,
    ReportPathError,
    ReportStore,
    ReportValidationError,
)


NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def test_store_round_trip_replaces_only_same_subject_and_kind(tmp_path: Path) -> None:
    store = ReportStore(tmp_path / "reports", replace_same_kind=True)
    first = store.save("600519", ReportKind.REPORT, "# first\n", now=NOW)
    other = store.save("000001", ReportKind.REPORT, "# other\n", now=NOW)
    latest = store.save(
        "600519.SH", ReportKind.REPORT, "# latest\n", now=NOW + timedelta(seconds=1)
    )

    assert latest.purged_replaced == 1
    assert store.read(latest.report_id, now=NOW).markdown == "# latest\n"
    assert store.read(other.report_id, now=NOW).markdown == "# other\n"
    assert [row.report_id for row in store.list(now=NOW)] == [latest.report_id, other.report_id]
    assert not (store.root / first.report_id.value).exists()
    assert "saved_path" not in latest.to_dict()
    assert "path" not in latest.to_dict()


@pytest.mark.parametrize(
    "value",
    [
        "../600519_report.md",
        "..\\600519_report.md",
        "C:\\outside.md",
        "\\\\server\\share\\outside.md",
        "/absolute.md",
        "*_report_20260830T120000000000Z_aaaaaaaaaaaa.md",
        "%2e%2e%2foutside.md",
        "600519.SH_report_20261399T999999999999Z_aaaaaaaaaaaa.md",
    ],
)
def test_report_id_rejects_traversal_globs_and_invalid_dates(value: str) -> None:
    with pytest.raises(ReportValidationError):
        ReportId.parse(value)


@pytest.mark.parametrize(
    "symbol",
    ["*", "../escape", "..\\escape", "６００５１９", "600519/../../escape"],
)
def test_save_rejects_non_ascii_or_path_shaped_symbols_without_mutation(
    tmp_path: Path, symbol: str
) -> None:
    store = ReportStore(tmp_path / "reports")
    existing = store.save("600519", "news", "# existing", now=NOW)

    with pytest.raises(ReportValidationError):
        store.save(symbol, "news", "# attacker", now=NOW + timedelta(seconds=1))

    assert store.read(existing.report_id, now=NOW).markdown == "# existing"
    assert len(list(store.root.glob("*.md"))) == 1


def test_failed_new_write_never_deletes_existing_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ReportStore(tmp_path / "reports")
    existing = store.save("600519", "report", "# existing", now=NOW)

    def fail_write(descriptor: int, payload: object) -> int:
        raise OSError("synthetic write failure")

    monkeypatch.setattr(report_module.os, "write", fail_write)
    with pytest.raises(OSError, match="synthetic"):
        store.save("600519", "report", "# replacement", now=NOW + timedelta(seconds=1))

    assert (store.root / existing.report_id.value).is_file()
    assert len(list(store.root.glob("*.md"))) == 1


def test_expiry_is_hidden_on_read_and_only_explicit_purge_deletes(tmp_path: Path) -> None:
    store = ReportStore(tmp_path / "reports", ttl_hours=1, replace_same_kind=False)
    report = store.save("600519", "earnings", "# earnings", now=NOW)
    late = NOW + timedelta(hours=2)

    with pytest.raises(ReportExpiredError):
        store.read(report.report_id, now=late)
    assert (store.root / report.report_id.value).is_file()
    assert store.list(now=late) == []
    assert store.purge_expired(now=late) == 1
    assert not (store.root / report.report_id.value).exists()


def test_purge_ignores_unrecognized_files_and_directories(tmp_path: Path) -> None:
    store = ReportStore(tmp_path / "reports", ttl_hours=1, replace_same_kind=False)
    report = store.save("600519", "news", "# news", now=NOW)
    unrelated = store.root / "notes.md"
    unrelated.write_text("keep", encoding="utf-8")
    directory = store.root / "600519.SH_news_20260830T120000000000Z_aaaaaaaaaaaa.md"
    directory.mkdir()

    assert store.purge_expired(now=NOW + timedelta(hours=2)) == 1
    assert not (store.root / report.report_id.value).exists()
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert directory.is_dir()


def test_symlink_report_is_never_read_or_deleted(tmp_path: Path) -> None:
    store = ReportStore(tmp_path / "reports")
    store.list(now=NOW)  # Prepare the root.
    outside = tmp_path / "outside.md"
    outside.write_text("outside secret", encoding="utf-8")
    report_id = ReportId.new("600519", "news", now=NOW)
    link = store.root / report_id.value
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable on this platform")

    with pytest.raises(ReportPathError):
        store.read(report_id, now=NOW)
    with pytest.raises(ReportPathError):
        store.delete(report_id)
    assert outside.read_text(encoding="utf-8") == "outside secret"


def test_root_and_delete_inputs_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(ReportPathError):
        ReportStore(tmp_path / "reports" / ".." / "outside")

    store = ReportStore(tmp_path / "reports")
    store.save("600519", "vision", "# vision", now=NOW)
    before = set(os.listdir(store.root))
    with pytest.raises(ReportValidationError):
        store.delete("../outside.md")
    assert set(os.listdir(store.root)) == before
