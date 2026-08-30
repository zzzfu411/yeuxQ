from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

import pytest

from yeuxq.intel.report_store import ReportExpiredError, ReportNotFoundError
from yeuxq.services.report_read_facade import ReportReadFacade


NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def _report_id(created_at: datetime, *, subject: str = "600519", kind: str = "report") -> str:
    stamp = created_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{subject}_{kind}_{stamp}_0123456789ab.md"


def _facade(root: Path, *, ttl_hours: float = 24) -> ReportReadFacade:
    return ReportReadFacade(root, ttl_hours=ttl_hours, max_bytes=1024 * 1024)


def _snapshot(root: Path) -> dict[str, tuple[bytes, int, int]]:
    return {
        path.name: (path.read_bytes(), path.stat().st_size, path.stat().st_mtime_ns)
        for path in sorted(root.iterdir())
    }


def test_list_and_read_preserve_report_bytes_metadata_and_directory_membership(
    tmp_path: Path,
) -> None:
    root = tmp_path / "reports"
    root.mkdir()
    report_id = _report_id(NOW)
    report = root / report_id
    report.write_bytes(b"# Historical advisory\n\nRead only.\n")
    unrelated = root / "operator-note.txt"
    unrelated.write_text("leave me alone", encoding="utf-8")
    before = _snapshot(root)
    directory_mtime = root.stat().st_mtime_ns

    facade = _facade(root)
    items = facade.list(subject="600519", limit=10, now=NOW + timedelta(minutes=1))
    document = facade.read(report_id, now=NOW + timedelta(minutes=1))

    assert [item["report_id"] for item in items] == [report_id]
    assert document["report_id"] == report_id
    assert document["markdown"] == "# Historical advisory\n\nRead only.\n"
    assert document["ok"] is True
    assert _snapshot(root) == before
    assert root.stat().st_mtime_ns == directory_mtime


def test_expired_report_is_hidden_without_being_deleted_or_rewritten(tmp_path: Path) -> None:
    root = tmp_path / "reports"
    root.mkdir()
    report_id = _report_id(NOW - timedelta(hours=2))
    report = root / report_id
    report.write_bytes(b"expired but retained")
    before = (report.read_bytes(), report.stat().st_mtime_ns)
    facade = _facade(root, ttl_hours=1)

    assert facade.list(subject="600519", now=NOW) == []
    with pytest.raises(ReportExpiredError):
        facade.read(report_id, now=NOW)

    assert report.is_file()
    assert (report.read_bytes(), report.stat().st_mtime_ns) == before


def test_get_style_operations_do_not_create_a_missing_report_root(tmp_path: Path) -> None:
    root = tmp_path / "missing" / "reports"
    facade = _facade(root)
    report_id = _report_id(NOW)

    assert facade.list(subject="600519", now=NOW + timedelta(minutes=1)) == []
    with pytest.raises(ReportNotFoundError):
        facade.read(report_id, now=NOW + timedelta(minutes=1))

    assert not root.exists()


def test_read_facade_uses_read_only_file_descriptor(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "reports"
    root.mkdir()
    report_id = _report_id(NOW)
    (root / report_id).write_text("read only", encoding="utf-8")
    opened_flags: list[int] = []
    real_open = os.open

    def capture_open(path: os.PathLike[str] | str, flags: int, *args: object) -> int:
        opened_flags.append(flags)
        return real_open(path, flags, *args)

    monkeypatch.setattr(os, "open", capture_open)
    document = _facade(root).read(report_id, now=NOW + timedelta(minutes=1))

    assert document["markdown"] == "read only"
    assert opened_flags
    write_mask = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
    assert all(flags & write_mask == 0 for flags in opened_flags)
