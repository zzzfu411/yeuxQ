from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from quantify.data.export_request import build_data_export_request, write_data_export_request


def test_build_data_export_request_reads_recent_config(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    _write_config(config)

    request = build_data_export_request(config_path=config, output_dir=tmp_path / "data_exports")
    out = write_data_export_request(request, tmp_path / "data_exports")

    assert request.start == "2024-06-03"
    assert request.end == "2026-06-05"
    assert request.min_symbols == 300
    assert request.price_adjustment == "qfq"
    assert request.universe["mode"] == "all_a"
    assert request.universe["index_code"] == "000906"
    assert request.universe["include_st"] is False
    assert request.universe["min_history_days"] == 120
    assert any(item["file_name"] == "bars.csv" and item["required"] for item in request.files)
    assert (out / "data_export_request.json").exists()
    assert "A-share Offline Data Export Request" in (out / "data_export_request.md").read_text(
        encoding="utf-8"
    )
    zh = (out / "data_export_request_zh.md").read_text(encoding="utf-8")
    assert "A 股日频真实数据导出请求" in zh
    assert "2024-06-03" in zh
    assert "不要把导出的 CSV 文件接入真实 broker 下单流程" in zh


def test_write_data_export_request_cli_writes_outputs(tmp_path: Path) -> None:
    config = tmp_path / "research_recent.yaml"
    output = tmp_path / "data_exports"
    _write_config(config)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/write_data_export_request.py",
            "--config",
            str(config),
            "--output-dir",
            str(output),
            "--min-symbols",
            "300",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((output / "data_export_request.json").read_text(encoding="utf-8"))
    commands = "\n".join(payload["workflow_commands"])
    assert completed.returncode == 0
    assert payload["start"] == "2024-06-03"
    assert payload["files"][0]["file_name"] == "bars.csv"
    assert "write_data_source_qa.py" in commands
    assert "write_data_source_qa_evidence_worksheet.py" in commands
    assert "write_data_source_qa_answers.py" in commands
    assert "run_source_qa_preflight.py" in commands
    assert "run_source_qa_evidence_readiness.py" in commands
    assert "run_csv_intake_preview.py" in commands
    assert "--encoding auto" in commands
    assert "run_data_import_doctor.py" in commands
    assert (output / "data_export_request_zh.md").exists()


def _write_config(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "research:",
                '  start: "2024-06-03"',
                '  end: "2026-06-05"',
                "data:",
                '  cache_path: "./data_cache/research_recent.db"',
                "  adjust: qfq",
                "universe:",
                "  mode: all_a",
                '  index_code: "000906"',
                "  include_st: false",
                "  min_history_days: 120",
            ]
        ),
        encoding="utf-8",
    )
