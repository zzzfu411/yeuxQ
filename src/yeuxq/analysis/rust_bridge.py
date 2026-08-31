"""Optional yeuxQ bridge to the technical ``trendlab-core`` component."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from yeuxq.settings import PROJECT_ROOT

log = logging.getLogger("yeuxq.rust")


@lru_cache(maxsize=1)
def rust_status() -> dict[str, Any]:
    try:
        import trendlab_core  # type: ignore

        return {
            "available": True,
            "mode": "pyo3",
            "module": getattr(trendlab_core, "__version__", "0.1.0"),
        }
    except Exception:
        pass
    exe = _find_cli()
    if exe:
        return {"available": True, "mode": "cli", "path": str(exe)}
    return {"available": False, "mode": None}


def _find_cli() -> Optional[Path]:
    env = os.environ.get("YEUXQ_RUST_BIN")
    if env and Path(env).is_file():
        return Path(env).resolve()
    project_candidates = (
        (
            PROJECT_ROOT / "target" / "release" / "trendlab.exe",
            PROJECT_ROOT / "target" / "release" / "trendlab",
            PROJECT_ROOT / "target" / "debug" / "trendlab.exe",
            PROJECT_ROOT / "target" / "debug" / "trendlab",
        )
        if PROJECT_ROOT is not None
        else ()
    )
    for p in project_candidates:
        if p.is_file():
            return p
    # A source checkout must never silently pick up an unrelated executable
    # with the same basename from PATH (for example a donor/developer build).
    # That executable may implement a different schema or decision chain and
    # would make the optional adapter look healthy while returning drifted
    # results.  In a wheel/runtime install there is no project target tree, so
    # an explicitly installed ``trendlab`` on PATH remains a useful opt-in.
    if PROJECT_ROOT is None:
        which = shutil.which("trendlab")
        return Path(which).resolve() if which else None
    return None


def _call_json(cmd: str, payload: dict[str, Any]) -> dict[str, Any]:
    blob = json.dumps(payload, ensure_ascii=False)
    try:
        import trendlab_core  # type: ignore

        fn = (
            trendlab_core.run_analysis_json_py
            if cmd == "analyze"
            else trendlab_core.run_backtest_json_py
        )
        return json.loads(fn(blob))
    except Exception as e:
        log.debug("pyo3 path failed: %s", e)

    exe = _find_cli()
    if not exe:
        raise RuntimeError("Rust engine unavailable")
    r = subprocess.run(
        [str(exe), cmd],
        input=blob.encode("utf-8"),
        capture_output=True,
        timeout=180,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", errors="replace")[:500])
    return json.loads(r.stdout.decode("utf-8"))


def analyze_rust(payload: dict[str, Any]) -> dict[str, Any]:
    return _call_json("analyze", payload)


def backtest_rust(payload: dict[str, Any]) -> dict[str, Any]:
    return _call_json("backtest", payload)
