"""进程内 TTL 缓存。"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock
from typing import Any, Optional


class CacheState(StrEnum):
    MISS = "MISS"
    HIT = "HIT"
    STALE = "STALE"


@dataclass(frozen=True)
class CacheLookup:
    state: CacheState
    value: Any = None
    age_seconds: float | None = None
    ttl_seconds: float | None = None

    @property
    def is_fresh(self) -> bool:
        return self.state is CacheState.HIT

    def diagnostic(self, namespace: str) -> dict[str, Any]:
        return {
            "namespace": namespace,
            "state": self.state.value,
            "age_seconds": None if self.age_seconds is None else round(self.age_seconds, 6),
            "ttl_seconds": self.ttl_seconds,
        }


class MemoryCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock = Lock()
        self._lookups: deque[tuple[int, dict[str, Any]]] = deque(maxlen=128)
        self._sequence = 0

    @staticmethod
    def _namespace(key: str) -> str:
        return str(key).partition(":")[0][:32] or "unknown"

    def _record(self, key: str, lookup: CacheLookup) -> None:
        self._sequence += 1
        self._lookups.append((self._sequence, lookup.diagnostic(self._namespace(key))))

    def lookup(self, key: str, ttl: float) -> CacheLookup:
        """Return explicit cache state; stale values are reported but never fresh."""
        ttl_seconds = max(0.0, float(ttl))
        with self._lock:
            item = self._store.get(key)
            if not item:
                result = CacheLookup(CacheState.MISS, ttl_seconds=ttl_seconds)
                self._record(key, result)
                return result
            value, stored_at = item
            age = max(0.0, time.time() - stored_at)
            if age >= ttl_seconds:
                self._store.pop(key, None)
                result = CacheLookup(
                    CacheState.STALE,
                    value=value,
                    age_seconds=age,
                    ttl_seconds=ttl_seconds,
                )
                self._record(key, result)
                return result
            result = CacheLookup(
                CacheState.HIT,
                value=value,
                age_seconds=age,
                ttl_seconds=ttl_seconds,
            )
            self._record(key, result)
            return result

    def get(self, key: str, ttl: float) -> Optional[Any]:
        lookup = self.lookup(key, ttl)
        return lookup.value if lookup.is_fresh else None

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = (value, time.time())

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def diagnostic_cursor(self) -> int:
        with self._lock:
            return self._sequence

    def diagnostics(self, *, since: int = 0, limit: int = 16) -> list[dict[str, Any]]:
        with self._lock:
            bounded = max(1, min(int(limit), 32))
            return [dict(item) for seq, item in self._lookups if seq > since][-bounded:]
