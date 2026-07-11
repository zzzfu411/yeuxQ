"""Generate a data-vendor export request for offline A-share research CSVs."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from quantify.data.csv_contract import RESEARCH_CSV_SCHEMAS
from quantify.utils.config import load_config


@dataclass(frozen=True, slots=True)
class DataExportRequest:
    market: str
    frequency: str
    start: str
    end: str
    min_symbols: int
    cache_path: str
    price_adjustment: str
    universe: dict[str, Any]
    files: list[dict[str, Any]]
    acceptance_criteria: list[str]
    workflow_commands: list[str]
    safety_boundaries: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "frequency": self.frequency,
            "start": self.start,
            "end": self.end,
            "min_symbols": self.min_symbols,
            "cache_path": self.cache_path,
            "price_adjustment": self.price_adjustment,
            "universe": self.universe,
            "files": self.files,
            "acceptance_criteria": self.acceptance_criteria,
            "workflow_commands": self.workflow_commands,
            "safety_boundaries": self.safety_boundaries,
        }

    def to_markdown(self) -> str:
        lines = [
            "# A-share Offline Data Export Request",
            "",
            "Give this request to a broker terminal operator, data vendor, or your own data pipeline.",
            "The files are research inputs only; they are not broker orders or trading instructions.",
            "",
            "## Scope",
            "",
            f"- Market: `{self.market}`",
            f"- Frequency: `{self.frequency}`",
            f"- Date range: `{self.start}` to `{self.end}`",
            f"- Minimum symbols: {self.min_symbols}",
            f"- Cache target: `{self.cache_path}`",
            f"- Price adjustment: `{self.price_adjustment}`",
            f"- Universe mode: `{self.universe['mode']}`",
            f"- Index context: `{self.universe['index_code']}`",
            f"- Include ST in investable universe: `{self.universe['include_st']}`",
            f"- Minimum history days: {self.universe['min_history_days']}",
            "",
            "## Files To Export",
            "",
            "| file | required | columns | purpose |",
            "| --- | --- | --- | --- |",
        ]
        for item in self.files:
            required = "yes" if item["required"] else "recommended"
            lines.append(
                f"| `{item['file_name']}` | `{required}` | "
                f"`{', '.join(item['columns'])}` | {item['description']} |"
            )
        lines.extend(["", "## Acceptance Criteria"])
        lines.extend(f"- {item}" for item in self.acceptance_criteria)
        lines.extend(["", "## Workflow Commands"])
        for command in self.workflow_commands:
            lines.append("")
            lines.append("```powershell")
            lines.append(command)
            lines.append("```")
        lines.extend(["", "## Safety Boundaries"])
        lines.extend(f"- {item}" for item in self.safety_boundaries)
        return "\n".join(lines) + "\n"

    def to_chinese_markdown(self) -> str:
        lines = [
            "# A 股日频真实数据导出请求",
            "",
            "这份清单可以交给券商终端操作员、数据供应商，或你自己的数据管道执行。",
            "这些文件只用于本地研究、数据审计和模拟盘，不是交易指令，也不是实盘下单文件。",
            "",
            "## 导出范围",
            "",
            f"- 市场: `{self.market}`",
            f"- 频率: `{self.frequency}`",
            f"- 日期范围: `{self.start}` 到 `{self.end}`",
            f"- 最少股票数: {self.min_symbols}",
            f"- 写入目标缓存: `{self.cache_path}`",
            f"- 复权口径: `{self.price_adjustment}`",
            f"- 股票池模式: `{self.universe['mode']}`",
            f"- 指数/研究上下文: `{self.universe['index_code']}`",
            f"- 投资股票池是否包含 ST: `{_bool_zh(self.universe['include_st'])}`",
            f"- 最少历史天数: {self.universe['min_history_days']}",
            "",
            "## 需要导出的文件",
            "",
            "| 文件名 | 要求 | 字段 | 中文说明 |",
            "| --- | --- | --- | --- |",
        ]
        for item in self.files:
            required = "必须" if item["required"] else "推荐"
            lines.append(
                f"| `{item['file_name']}` | `{required}` | "
                f"`{', '.join(item['columns'])}` | {_file_purpose_zh(item['role'])} |"
            )
        lines.extend(
            [
                "",
                "## 字段口径",
                "",
                "| 字段 | 含义 |",
                "| --- | --- |",
            ]
        )
        for column in _all_columns(self.files):
            lines.append(f"| `{column}` | {_column_zh(column)} |")
        lines.extend(["", "## 验收标准"])
        lines.extend(f"- {item}" for item in _acceptance_criteria_zh(self))
        lines.extend(["", "## 导出后运行命令"])
        for command in self.workflow_commands:
            lines.append("")
            lines.append("```powershell")
            lines.append(command)
            lines.append("```")
        lines.extend(["", "## 安全边界"])
        lines.extend(f"- {item}" for item in _safety_boundaries_zh())
        return "\n".join(lines) + "\n"


def build_data_export_request(
    *,
    config_path: str | Path | None = None,
    output_dir: str | Path = "data_exports",
    start: str | None = None,
    end: str | None = None,
    min_symbols: int = 300,
) -> DataExportRequest:
    cfg = _load_config_dict(config_path)
    research = cfg.get("research", {})
    data = cfg.get("data", {})
    universe_cfg = cfg.get("universe", {})
    resolved_start = start or str(research.get("start", ""))
    resolved_end = end or str(research.get("end", ""))
    cache_path = str(data.get("cache_path", "./data_cache/research_recent.db"))
    data_dir = Path(output_dir)
    files = [
        {
            "role": schema.role,
            "file_name": schema.file_name,
            "path": str(data_dir / schema.file_name),
            "required": schema.required,
            "columns": schema.columns,
            "description": schema.description,
        }
        for schema in RESEARCH_CSV_SCHEMAS
    ]
    workflow = _workflow_commands(
        data_dir=data_dir,
        config_path=str(config_path or "config\\research_recent.yaml"),
        cache_path=cache_path,
        start=resolved_start,
        end=resolved_end,
        min_symbols=min_symbols,
    )
    return DataExportRequest(
        market="A-share equities",
        frequency="daily",
        start=resolved_start,
        end=resolved_end,
        min_symbols=min_symbols,
        cache_path=cache_path,
        price_adjustment=str(data.get("adjust", "qfq")),
        universe={
            "mode": str(universe_cfg.get("mode", "all_a")),
            "index_code": str(universe_cfg.get("index_code", "")),
            "include_st": bool(universe_cfg.get("include_st", False)),
            "min_history_days": int(universe_cfg.get("min_history_days", 0) or 0),
        },
        files=files,
        acceptance_criteria=[
            "bars.csv must cover the requested date range through the latest completed trading day.",
            f"bars.csv must contain at least {min_symbols} distinct A-share symbols.",
            "Price adjustment must be consistent with the configured qfq/hfq/raw setting.",
            "Template sample rows and demo data must be fully replaced before import.",
            "stock_info should include ST and delist fields so investable filters can be audited.",
            "calendar and suspensions should be supplied when available to support execution gates.",
            "index_constituents should be point-in-time when used as the research universe.",
            "data_source_qa_evidence_worksheet.csv should be filled from real export evidence before answers are written.",
            "data_source_qa_answers.json must be filled and pass source QA preflight.",
        ],
        workflow_commands=workflow,
        safety_boundaries=[
            "This request is for research and paper trading only.",
            "Do not connect exported files to a real broker order workflow.",
            "Do not treat data availability as a promise of strategy profitability.",
            "After import, real_data_bootstrap and data_audit must pass before strategy evaluation.",
        ],
    )


def write_data_export_request(request: DataExportRequest, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "data_export_request.json").write_text(
        json.dumps(request.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "data_export_request.md").write_text(request.to_markdown(), encoding="utf-8")
    (root / "data_export_request_zh.md").write_text(
        request.to_chinese_markdown(),
        encoding="utf-8",
    )
    return root


def _load_config_dict(config_path: str | Path | None) -> dict[str, Any]:
    if config_path is None:
        return {}
    return load_config(config_path).to_dict()


def _workflow_commands(
    *,
    data_dir: Path,
    config_path: str,
    cache_path: str,
    start: str,
    end: str,
    min_symbols: int,
) -> list[str]:
    paths = {schema.role: data_dir / schema.file_name for schema in RESEARCH_CSV_SCHEMAS}
    return [
        f".\\.venv\\Scripts\\python.exe examples\\write_data_export_templates.py --output-dir {data_dir} --overwrite",
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa.py "
            f"--config {config_path} --output-dir {data_dir} --min-symbols {min_symbols}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa_evidence_worksheet.py "
            f"--checklist {data_dir / 'data_source_qa.json'} --output-dir {data_dir}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_data_source_qa_worksheet_preflight.py "
            f"--checklist {data_dir / 'data_source_qa.json'} "
            f"--worksheet {data_dir / 'data_source_qa_evidence_worksheet.csv'} --output-dir {data_dir}"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_source_qa_evidence_manifest.py "
            f"--checklist {data_dir / 'data_source_qa.json'} "
            f"--evidence-dir {data_dir / 'source_qa_evidence'} --output-dir {data_dir} --strict"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_data_source_qa_answers.py "
            f"--checklist {data_dir / 'data_source_qa.json'} "
            f"--worksheet {data_dir / 'data_source_qa_evidence_worksheet.csv'} "
            f"--output {data_dir / 'data_source_qa_answers.json'} "
            f"--evidence-manifest {data_dir / 'source_qa_evidence_manifest.json'} "
            "--require-evidence-manifest"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_preflight.py "
            f"--checklist {data_dir / 'data_source_qa.json'} "
            f"--answers {data_dir / 'data_source_qa_answers.json'} "
            f"--evidence-manifest {data_dir / 'source_qa_evidence_manifest.json'} "
            "--require-evidence-manifest "
            "--output-dir results\\import\\source_qa"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_data_source_qa_review.py "
            f"--checklist {data_dir / 'data_source_qa.json'} "
            f"--answers {data_dir / 'data_source_qa_answers.json'} "
            f"--evidence-manifest {data_dir / 'source_qa_evidence_manifest.json'} "
            "--require-evidence-manifest --output-dir results\\import\\source_qa"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_source_qa_evidence_readiness.py "
            f"--checklist {data_dir / 'data_source_qa.json'} "
            f"--worksheet {data_dir / 'data_source_qa_evidence_worksheet.csv'} "
            f"--answers {data_dir / 'data_source_qa_answers.json'} "
            f"--evidence-manifest {data_dir / 'source_qa_evidence_manifest.json'} "
            "--require-evidence-manifest --output-dir results\\import\\source_qa"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_csv_intake_preview.py "
            f"--data-dir {data_dir} --encoding auto --output-dir results\\import\\csv_preview"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_data_import_doctor.py "
            f"--data-dir {data_dir} --config {config_path} --encoding auto --output-dir results\\import\\doctor"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\validate_research_csv.py "
            f"--bars-csv {paths['bars']} "
            f"--stock-info-csv {paths['stock_info']} "
            f"--fundamentals-csv {paths['fundamentals']} "
            f"--calendar-csv {paths['calendar']} "
            f"--suspensions-csv {paths['suspensions']} "
            f"--index-constituents-csv {paths['index_constituents']} "
            f"--start {start} --end {end} --min-symbols {min_symbols} "
            "--encoding auto --output-dir results\\import\\recent_csv_validation"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\import_research_csv.py "
            f"--cache {cache_path} "
            f"--bars-csv {paths['bars']} "
            f"--stock-info-csv {paths['stock_info']} "
            f"--fundamentals-csv {paths['fundamentals']} "
            f"--calendar-csv {paths['calendar']} "
            f"--suspensions-csv {paths['suspensions']} "
            f"--index-constituents-csv {paths['index_constituents']} "
            f"--validate --start {start} --end {end} --min-symbols {min_symbols} "
            "--encoding auto --output-dir results\\import\\recent_csv"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_real_data_bootstrap.py "
            f"--config {config_path} --output-dir results\\bootstrap_recent "
            f"--min-symbols {min_symbols} --as-of 2026-06-08"
        ),
    ]


def _all_columns(files: list[dict[str, Any]]) -> list[str]:
    columns = []
    for item in files:
        for column in item["columns"]:
            if column not in columns:
                columns.append(column)
    return columns


def _file_purpose_zh(role: str) -> str:
    purposes = {
        "bars": "日频 OHLCV 行情，每只股票每个交易日一行。",
        "stock_info": "股票基础信息，用于 ST、退市、行业和股票池过滤审计。",
        "fundamentals": "点时财务、估值、质量和流动性因子输入。",
        "calendar": "交易日历，用于识别开市日和缺失交易日。",
        "suspensions": "停牌标记，用于模拟盘拒单和人工交易风险提示。",
        "index_constituents": "指数或研究股票池成分，最好是 point-in-time 快照。",
    }
    return purposes.get(role, "研究数据输入。")


def _column_zh(column: str) -> str:
    meanings = {
        "symbol": "6 位 A 股代码，例如 600000 或 000001。",
        "date": "交易日期，推荐 YYYY-MM-DD。",
        "open": "开盘价，复权口径应与配置一致。",
        "high": "最高价，复权口径应与配置一致。",
        "low": "最低价，复权口径应与配置一致。",
        "close": "收盘价，复权口径应与配置一致。",
        "volume": "成交量。",
        "amount": "成交额，缺失时可导入但会产生 WATCH。",
        "name": "证券简称。",
        "exchange": "交易所，例如 SSE/SZSE/BSE。",
        "list_date": "上市日期。",
        "delist_date": "退市日期，未退市可留空。",
        "industry": "行业分类。",
        "is_st": "是否 ST，用 0/1 表示。",
        "pe_ttm": "滚动市盈率。",
        "pb": "市净率。",
        "roe": "净资产收益率。",
        "market_cap": "总市值或可比市值口径。",
        "turnover_rate": "换手率。",
        "is_open": "是否开市，1 表示开市，0 表示休市。",
        "is_suspended": "是否停牌，1 表示停牌，0 表示未停牌。",
        "index_code": "指数或研究股票池代码，例如 000906。",
    }
    return meanings.get(column, "请保持字段名不变，导入器依赖该标准列名。")


def _acceptance_criteria_zh(request: DataExportRequest) -> list[str]:
    return [
        f"bars.csv 必须覆盖 `{request.start}` 到 `{request.end}` 的研究窗口。",
        f"bars.csv 至少包含 {request.min_symbols} 只不同 A 股股票。",
        f"价格口径必须与配置一致: `{request.price_adjustment}`。",
        "模板样例行和 demo 数据必须全部替换为真实导出数据。",
        "stock_info 建议包含 ST、退市和行业字段，方便审计股票池过滤。",
        "calendar 和 suspensions 建议提供，方便模拟盘识别停牌、缺口和不可交易日。",
        "index_constituents 如用于股票池，应尽量提供 point-in-time 成分快照。",
        "必须填写 data_source_qa_answers.json，并先通过 source QA preflight。",
    ]


def _safety_boundaries_zh() -> list[str]:
    return [
        "本请求只服务于研究和模拟盘。",
        "不要把导出的 CSV 文件接入真实 broker 下单流程。",
        "数据可用不等于策略会盈利。",
        "导入后必须重新通过 real_data_bootstrap 和 data_audit，再进入策略研究。",
    ]


def _bool_zh(value: object) -> str:
    return "是" if bool(value) else "否"
