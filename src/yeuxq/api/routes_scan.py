from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from yeuxq.api.deps import get_container

router = APIRouter(tags=["scan"])


class ScanStartRequest(BaseModel):
    symbols: Optional[List[str]] = None


@router.get("/api/scan")
def scan_status(action: Optional[str] = None):
    c = get_container()
    if action == "start":
        # 兼容 v1：无 symbols 时走配置池
        return c.scan.start(None)
    return c.scan.state


@router.post("/api/scan/start")
def scan_start(req: ScanStartRequest):
    return get_container().scan.start(req.symbols)
