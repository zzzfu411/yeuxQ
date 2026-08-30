"""限速扫描 worker。"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from yeuxq.services.analyze import AnalyzeService
from yeuxq.settings import Settings

log = logging.getLogger("yeuxq.scan")


class ScanWorker:
    def __init__(self, analyze: AnalyzeService, settings: Settings) -> None:
        self.analyze = analyze
        self.settings = settings
        self._lock = threading.Lock()
        self._state: Dict[str, Any] = {
            "status": "idle",
            "progress": 0,
            "total": 0,
            "results": [],
            "error": None,
            "stage": "空闲",
            "started_at": None,
            "finished_at": None,
        }

    @property
    def state(self) -> dict:
        with self._lock:
            return dict(self._state)

    def start(self, symbols: Optional[List[str]] = None) -> dict:
        with self._lock:
            if self._state["status"] == "running":
                return {"ok": False, "message": "扫描进行中", "state": dict(self._state)}
            pool = symbols or list(self.settings.scan.default_pool)
            if not pool:
                if self.settings.scan.allow_full_market:
                    pool = [
                        x["code"]
                        for x in self.analyze.data.fetch_symbols(self.settings.scan.max_symbols)
                    ]
                else:
                    return {
                        "ok": False,
                        "message": "未提供股票池。请传 symbols，或在 config 设置 scan.default_pool；全 A 需 allow_full_market=true",
                    }
            pool = pool[: self.settings.scan.max_symbols]
            self._state = {
                "status": "running",
                "progress": 0,
                "total": len(pool),
                "results": [],
                "error": None,
                "stage": f"扫描 {len(pool)} 只股票…",
                "started_at": time.time(),
                "finished_at": None,
            }
        t = threading.Thread(target=self._run, args=(pool,), daemon=True)
        t.start()
        return {"ok": True, "message": f"开始扫描 {len(pool)} 只", "total": len(pool)}

    def _run(self, pool: List[str]) -> None:
        results: List[dict] = []
        workers = max(1, self.settings.scan.max_workers)

        def job(sym: str) -> Optional[dict]:
            try:
                data = self.analyze.analyze(sym, "day")
                if "error" in data:
                    return None
                sig = data.get("signal") or {}
                if sig.get("action") not in ("买入", "强烈买入", "谨慎买入"):
                    return None
                q = data.get("quote") or {}
                return {
                    "symbol": sym,
                    "name": q.get("name", ""),
                    "price": q.get("price"),
                    "pct": q.get("pct"),
                    "action": sig.get("action"),
                    "score": sig.get("score"),
                    "confidence": sig.get("confidence"),
                    "prob_up": (data.get("prediction") or {}).get("prob_up"),
                }
            except Exception as e:
                log.debug("scan %s fail: %s", sym, e)
                return None

        try:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(job, s): s for s in pool}
                done = 0
                for fut in as_completed(futs):
                    done += 1
                    item = fut.result()
                    if item:
                        results.append(item)
                    with self._lock:
                        self._state["progress"] = done
                        self._state["results"] = sorted(
                            results, key=lambda x: x.get("score") or 0, reverse=True
                        )[:50]
            with self._lock:
                self._state["status"] = "done"
                self._state["stage"] = "完成"
                self._state["finished_at"] = time.time()
                self._state["results"] = sorted(
                    results, key=lambda x: x.get("score") or 0, reverse=True
                )[:50]
        except Exception as e:
            with self._lock:
                self._state["status"] = "error"
                self._state["error"] = str(e)
                self._state["finished_at"] = time.time()
