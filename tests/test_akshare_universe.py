from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pandas as pd

from quantify.data.akshare_universe import build_akshare_index_universe


def test_build_akshare_index_universe_writes_symbol_and_metadata_files(tmp_path: Path) -> None:
    raw = _raw_constituents()

    with patch("akshare.index_stock_cons_csindex", return_value=raw):
        report = build_akshare_index_universe(
            index_code="000906",
            limit=2,
            output_dir=tmp_path,
        )

    payload = json.loads((tmp_path / "akshare_universe.json").read_text(encoding="utf-8"))
    symbols = (tmp_path / "akshare_000906_2_symbols.txt").read_text(encoding="utf-8").splitlines()
    stock_info = pd.read_csv(tmp_path / "akshare_000906_2_stock_info.csv", dtype={"symbol": str})
    constituents = pd.read_csv(
        tmp_path / "akshare_000906_2_index_constituents.csv",
        dtype={"index_code": str, "symbol": str},
    )

    assert report.status == "PASS"
    assert report.symbol_count == 2
    assert report.selection_method == "stratified_exchange"
    assert symbols == ["000001", "600000"]
    assert stock_info["symbol"].tolist() == ["000001", "600000"]
    assert stock_info["exchange"].tolist() == ["SZSE", "SSE"]
    assert constituents["index_code"].tolist() == ["000906", "000906"]
    assert constituents["date"].tolist() == ["2026-06-11", "2026-06-11"]
    assert payload["source_endpoint"] == "index_stock_cons_csindex"
    assert payload["selection_method"] == "stratified_exchange"
    assert payload["metadata"]["selection_order"] == "exchange_stratified_then_provider_row_order"
    assert payload["metadata"]["full_exchange_counts"] == {"SZSE": 2, "SSE": 1}
    assert payload["metadata"]["exchange_counts"] == {"SZSE": 1, "SSE": 1}
    assert "not audited point-in-time history" in payload["warnings"][0]
    assert any("import_research_data.py" in item for item in payload["next_actions"])


def test_build_akshare_index_universe_preserves_provider_order_before_limit(
    tmp_path: Path,
) -> None:
    raw = _raw_constituents().iloc[[2, 0, 1]].reset_index(drop=True)

    with patch("akshare.index_stock_cons_csindex", return_value=raw):
        build_akshare_index_universe(
            index_code="000906",
            limit=2,
            output_dir=tmp_path,
            selection_method="provider_order",
        )

    symbols = (tmp_path / "akshare_000906_2_symbols.txt").read_text(encoding="utf-8").splitlines()
    payload = json.loads((tmp_path / "akshare_universe.json").read_text(encoding="utf-8"))

    assert symbols == ["600000", "000001"]
    assert payload["metadata"]["exchange_counts"] == {"SSE": 1, "SZSE": 1}
    assert payload["metadata"]["selection_order"] == "provider_row_order"
    assert "provider-order bias" in payload["warnings"][2]


def test_build_akshare_universe_cli_writes_report(tmp_path: Path) -> None:
    raw = _raw_constituents()
    script = (
        "from unittest.mock import patch\n"
        "import pandas as pd, runpy\n"
        f"raw = pd.DataFrame({raw.to_dict(orient='list')!r})\n"
        "with patch('akshare.index_stock_cons_csindex', return_value=raw):\n"
        "    runpy.run_path('examples/build_akshare_universe.py', run_name='__main__')\n"
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            "--index-code",
            "000906",
            "--limit",
            "2",
            "--selection-method",
            "provider_order",
            "--output-dir",
            str(tmp_path),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((tmp_path / "akshare_universe.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["status"] == "PASS"
    assert payload["selection_method"] == "provider_order"
    assert payload["symbol_count"] == 2


def _raw_constituents() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "日期": ["2026-06-11", "2026-06-11", "2026-06-11"],
            "指数代码": ["000906", "000906", "000906"],
            "指数名称": ["中证800", "中证800", "中证800"],
            "指数英文名称": ["CSI 800", "CSI 800", "CSI 800"],
            "成分券代码": ["000001", "000002", "600000"],
            "成分券名称": ["平安银行", "万科A", "浦发银行"],
            "成分券英文名称": ["Ping An Bank", "Vanke", "SPDB"],
            "交易所": ["深圳证券交易所", "深圳证券交易所", "上海证券交易所"],
            "交易所英文名称": [
                "Shenzhen Stock Exchange",
                "Shenzhen Stock Exchange",
                "Shanghai Stock Exchange",
            ],
        }
    )
