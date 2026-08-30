from pathlib import Path

from yeuxq.domain.models import Kline
from yeuxq.storage.cache import MemoryCache
from yeuxq.storage.kline_store import KlineStore


def test_memory_cache(tmp_path=None):
    c = MemoryCache()
    c.set("a", 123)
    assert c.get("a", 10) == 123
    assert c.get("missing", 10) is None


def test_kline_store(tmp_path: Path):
    db = tmp_path / "t.db"
    store = KlineStore(db)
    ks = [
        Kline(date="2024-01-01", open=1, close=2, high=3, low=1, volume=100),
        Kline(date="2024-01-02", open=2, close=3, high=4, low=2, volume=110),
    ]
    store.save_many("600519", "day", ks)
    loaded = store.load("600519", "day", 10)
    assert len(loaded) == 2
    assert loaded[-1].date == "2024-01-02"
    assert store.latest_date("600519", "day") == "2024-01-02"
