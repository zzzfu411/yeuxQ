# A 股日频真实数据导出请求

这份清单可以交给券商终端操作员、数据供应商，或你自己的数据管道执行。
这些文件只用于本地研究、数据审计和模拟盘，不是交易指令，也不是实盘下单文件。

## 导出范围

- 市场: `A-share equities`
- 频率: `daily`
- 日期范围: `2024-06-03` 到 `2026-06-05`
- 最少股票数: 300
- 写入目标缓存: `./data_cache/research_recent.db`
- 复权口径: `qfq`
- 股票池模式: `all_a`
- 指数/研究上下文: `000906`
- 投资股票池是否包含 ST: `否`
- 最少历史天数: 120

## 需要导出的文件

| 文件名 | 要求 | 字段 | 中文说明 |
| --- | --- | --- | --- |
| `bars.csv` | `必须` | `symbol, date, open, high, low, close, volume, amount` | 日频 OHLCV 行情，每只股票每个交易日一行。 |
| `stock_info.csv` | `推荐` | `symbol, name, exchange, list_date, delist_date, industry, is_st` | 股票基础信息，用于 ST、退市、行业和股票池过滤审计。 |
| `fundamentals.csv` | `推荐` | `symbol, date, pe_ttm, pb, roe, market_cap, turnover_rate` | 点时财务、估值、质量和流动性因子输入。 |
| `calendar.csv` | `推荐` | `date, is_open` | 交易日历，用于识别开市日和缺失交易日。 |
| `suspensions.csv` | `推荐` | `symbol, date, is_suspended` | 停牌标记，用于模拟盘拒单和人工交易风险提示。 |
| `index_constituents.csv` | `推荐` | `index_code, date, symbol` | 指数或研究股票池成分，最好是 point-in-time 快照。 |

## 字段口径

| 字段 | 含义 |
| --- | --- |
| `symbol` | 6 位 A 股代码，例如 600000 或 000001。 |
| `date` | 交易日期，推荐 YYYY-MM-DD。 |
| `open` | 开盘价，复权口径应与配置一致。 |
| `high` | 最高价，复权口径应与配置一致。 |
| `low` | 最低价，复权口径应与配置一致。 |
| `close` | 收盘价，复权口径应与配置一致。 |
| `volume` | 成交量。 |
| `amount` | 成交额，缺失时可导入但会产生 WATCH。 |
| `name` | 证券简称。 |
| `exchange` | 交易所，例如 SSE/SZSE/BSE。 |
| `list_date` | 上市日期。 |
| `delist_date` | 退市日期，未退市可留空。 |
| `industry` | 行业分类。 |
| `is_st` | 是否 ST，用 0/1 表示。 |
| `pe_ttm` | 滚动市盈率。 |
| `pb` | 市净率。 |
| `roe` | 净资产收益率。 |
| `market_cap` | 总市值或可比市值口径。 |
| `turnover_rate` | 换手率。 |
| `is_open` | 是否开市，1 表示开市，0 表示休市。 |
| `is_suspended` | 是否停牌，1 表示停牌，0 表示未停牌。 |
| `index_code` | 指数或研究股票池代码，例如 000906。 |

## 验收标准
- bars.csv 必须覆盖 `2024-06-03` 到 `2026-06-05` 的研究窗口。
- bars.csv 至少包含 300 只不同 A 股股票。
- 价格口径必须与配置一致: `qfq`。
- 模板样例行和 demo 数据必须全部替换为真实导出数据。
- stock_info 建议包含 ST、退市和行业字段，方便审计股票池过滤。
- calendar 和 suspensions 建议提供，方便模拟盘识别停牌、缺口和不可交易日。
- index_constituents 如用于股票池，应尽量提供 point-in-time 成分快照。
- 必须填写 data_source_qa_answers.json，并先通过 source QA preflight。

## 导出后运行命令

```powershell
.\.venv\Scripts\python.exe examples\write_data_export_templates.py --output-dir data_exports --overwrite
```

```powershell
.\.venv\Scripts\python.exe examples\write_data_source_qa.py --config config\research_recent.yaml --output-dir data_exports --min-symbols 300
```

```powershell
.\.venv\Scripts\python.exe examples\write_data_source_qa_evidence_worksheet.py --checklist data_exports\data_source_qa.json --output-dir data_exports
```

```powershell
.\.venv\Scripts\python.exe examples\run_data_source_qa_worksheet_preflight.py --checklist data_exports\data_source_qa.json --worksheet data_exports\data_source_qa_evidence_worksheet.csv --output-dir data_exports
```

```powershell
.\.venv\Scripts\python.exe examples\write_source_qa_evidence_manifest.py --checklist data_exports\data_source_qa.json --evidence-dir data_exports\source_qa_evidence --output-dir data_exports --strict
```

```powershell
.\.venv\Scripts\python.exe examples\write_data_source_qa_answers.py --checklist data_exports\data_source_qa.json --worksheet data_exports\data_source_qa_evidence_worksheet.csv --output data_exports\data_source_qa_answers.json --evidence-manifest data_exports\source_qa_evidence_manifest.json --require-evidence-manifest
```

```powershell
.\.venv\Scripts\python.exe examples\run_source_qa_preflight.py --checklist data_exports\data_source_qa.json --answers data_exports\data_source_qa_answers.json --evidence-manifest data_exports\source_qa_evidence_manifest.json --require-evidence-manifest --output-dir results\import\source_qa
```

```powershell
.\.venv\Scripts\python.exe examples\run_data_source_qa_review.py --checklist data_exports\data_source_qa.json --answers data_exports\data_source_qa_answers.json --evidence-manifest data_exports\source_qa_evidence_manifest.json --require-evidence-manifest --output-dir results\import\source_qa
```

```powershell
.\.venv\Scripts\python.exe examples\run_source_qa_evidence_readiness.py --checklist data_exports\data_source_qa.json --worksheet data_exports\data_source_qa_evidence_worksheet.csv --answers data_exports\data_source_qa_answers.json --evidence-manifest data_exports\source_qa_evidence_manifest.json --require-evidence-manifest --output-dir results\import\source_qa
```

```powershell
.\.venv\Scripts\python.exe examples\run_csv_intake_preview.py --data-dir data_exports --encoding auto --output-dir results\import\csv_preview
```

```powershell
.\.venv\Scripts\python.exe examples\run_data_import_doctor.py --data-dir data_exports --config config\research_recent.yaml --encoding auto --output-dir results\import\doctor
```

```powershell
.\.venv\Scripts\python.exe examples\validate_research_csv.py --bars-csv data_exports\bars.csv --stock-info-csv data_exports\stock_info.csv --fundamentals-csv data_exports\fundamentals.csv --calendar-csv data_exports\calendar.csv --suspensions-csv data_exports\suspensions.csv --index-constituents-csv data_exports\index_constituents.csv --start 2024-06-03 --end 2026-06-05 --min-symbols 300 --encoding auto --output-dir results\import\recent_csv_validation
```

```powershell
.\.venv\Scripts\python.exe examples\import_research_csv.py --cache ./data_cache/research_recent.db --bars-csv data_exports\bars.csv --stock-info-csv data_exports\stock_info.csv --fundamentals-csv data_exports\fundamentals.csv --calendar-csv data_exports\calendar.csv --suspensions-csv data_exports\suspensions.csv --index-constituents-csv data_exports\index_constituents.csv --validate --start 2024-06-03 --end 2026-06-05 --min-symbols 300 --encoding auto --output-dir results\import\recent_csv
```

```powershell
.\.venv\Scripts\python.exe examples\run_real_data_bootstrap.py --config config\research_recent.yaml --output-dir results\bootstrap_recent --min-symbols 300 --as-of 2026-06-08
```

## 安全边界
- 本请求只服务于研究和模拟盘。
- 不要把导出的 CSV 文件接入真实 broker 下单流程。
- 数据可用不等于策略会盈利。
- 导入后必须重新通过 real_data_bootstrap 和 data_audit，再进入策略研究。
