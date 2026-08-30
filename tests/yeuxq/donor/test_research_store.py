from pathlib import Path
import os
import time

from yeuxq.intel import research as R


def test_save_replaces_same_kind(tmp_path: Path):
    folder = tmp_path / "reports"
    first = R._save_report("600519", "report", "# first", folder=folder)
    assert Path(first["saved_path"]).is_file()
    second = R._save_report("600519", "report", "# second", folder=folder)
    files = list(folder.glob("*.md"))
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8") == "# second"
    assert second["purged_replaced"] >= 1
    assert second["ttl_hours"] == 24


def test_keep_different_kinds(tmp_path: Path):
    folder = tmp_path / "reports"
    R._save_report("600519", "report", "# r", folder=folder)
    R._save_report("600519", "news", "# n", folder=folder)
    R._save_report("600519", "earnings", "# e", folder=folder)
    names = sorted(p.name.split("_")[1] for p in folder.glob("*.md"))
    assert names == ["earnings", "news", "report"]


def test_purge_expired_on_list(tmp_path: Path):
    folder = tmp_path / "reports"
    folder.mkdir()
    old = folder / "000001_report_20200101_000000.md"
    old.write_text("stale", encoding="utf-8")
    past = time.time() - 25 * 3600
    os.utime(old, (past, past))
    R._save_report("600519", "report", "# fresh", folder=folder)
    items = R.list_saved_reports(symbol="000001", folder=folder)
    assert items == []
    assert not old.exists()
    kept = R.list_saved_reports(symbol="600519", folder=folder)
    assert len(kept) == 1
    assert kept[0]["ttl_remain_sec"] > 20 * 3600


def test_read_ok_and_rejects_path_traversal(tmp_path: Path):
    folder = tmp_path / "reports"
    saved = R._save_report("600519", "report", "# body", folder=folder)
    one = R.read_saved_report(saved["filename"], folder=folder)
    assert one["ok"] is True
    assert "# body" in one["markdown"]
    assert one["ttl_hours"] == 24
    bad = R.read_saved_report("../secret.md", folder=folder)
    assert bad["ok"] is False
    missing = R.read_saved_report("600519_report_20990101_000000.md", folder=folder)
    assert missing["ok"] is False


def test_empty_markdown_not_saved(tmp_path: Path):
    meta = R._save_report("600519", "report", "   ", folder=tmp_path)
    assert meta["saved_path"] == ""
    assert list(tmp_path.glob("*.md")) == []


def test_normalize_symbols():
    assert R._normalize_symbols(["600519.SH", "000001", "000001", "abc", "1"]) == [
        "600519",
        "000001",
    ]


def test_row_from_analyze_ok_and_error():
    ok = R.row_from_analyze(
        "600519",
        {
            "quote": {"name": "茅台", "pct": 1.2},
            "signal": {"action": "买入", "score": 72, "confidence": 55, "plain_summary": "多头"},
        },
    )
    assert ok["ok"] is True
    assert ok["name"] == "茅台"
    assert ok["score"] == 72
    bad = R.row_from_analyze("000001", {"error": "K线不足"})
    assert bad["ok"] is False
    assert bad["action"] == "失败"


def test_format_and_save_watch_brief(tmp_path: Path):
    rows = [
        R.row_from_analyze(
            "600519",
            {
                "quote": {"name": "茅台", "pct": -0.5},
                "signal": {"action": "观望", "score": 50, "plain_summary": "纠缠"},
            },
        )
    ]
    md = R.format_watch_brief_markdown(
        rows, news_text="要闻A", llm_text="偏中性", generated_at="2026-08-13"
    )
    assert "| 600519 | 茅台 | 观望 |" in md
    assert "## 市场检索" in md
    assert "## 组合点评" in md
    saved = R._save_report("WATCH", "brief", md, folder=tmp_path / "reports")
    assert saved["filename"].startswith("WATCH_brief_")
    listed = R.list_saved_reports(symbol="WATCH", folder=tmp_path / "reports")
    assert listed[0]["kind"] == "brief"
