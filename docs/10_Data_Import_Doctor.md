# 10 Data Import Doctor

> 风险提示: 这个工具只诊断离线 CSV 数据是否能进入本地研究缓存。它不连接券商,不提交真实订单,也不能证明策略未来会赚钱。

当前一百万元复利目标的第一道阻塞是: `data_cache/research_recent.db` 为空。`run_data_import_doctor.py` 的作用是把这个阻塞拆成可执行清单:

```text
检查 data_exports 目录 -> 复用 CSV validator -> 写出诊断报告 -> 给出下一条命令
```

## 什么时候使用

- AKShare 或外部行情接口不可用。
- 已经从券商终端或数据商导出 A 股日频 CSV。
- `capital_goal_status.md` 提示 `data_cache` 是 BLOCK。
- 不确定 `bars.csv`、`stock_info.csv`、`calendar.csv` 等文件是否齐全。

## 推荐命令

先生成或检查导出目录:

```powershell
.\.venv\Scripts\python.exe examples\write_data_export_request.py --config config\research_recent.yaml --output-dir data_exports --min-symbols 300
.\.venv\Scripts\python.exe examples\write_data_source_qa.py --config config\research_recent.yaml --output-dir data_exports --min-symbols 300 --as-of 2026-06-08
.\.venv\Scripts\python.exe examples\write_data_source_qa_evidence_worksheet.py --checklist data_exports\data_source_qa.json --output-dir data_exports
.\.venv\Scripts\python.exe examples\run_data_source_qa_worksheet_preflight.py --checklist data_exports\data_source_qa.json --worksheet data_exports\data_source_qa_evidence_worksheet.csv --output-dir data_exports
.\.venv\Scripts\python.exe examples\write_source_qa_evidence_manifest.py --checklist data_exports\data_source_qa.json --evidence-dir data_exports\source_qa_evidence --output-dir data_exports --strict
.\.venv\Scripts\python.exe examples\write_data_source_qa_answers.py --checklist data_exports\data_source_qa.json --worksheet data_exports\data_source_qa_evidence_worksheet.csv --output data_exports\data_source_qa_answers.json --evidence-manifest data_exports\source_qa_evidence_manifest.json --require-evidence-manifest
.\.venv\Scripts\python.exe examples\run_data_source_qa_review.py --checklist data_exports\data_source_qa.json --answers data_exports\data_source_qa_answers.json --evidence-manifest data_exports\source_qa_evidence_manifest.json --require-evidence-manifest --output-dir results\import\source_qa
.\.venv\Scripts\python.exe examples\write_data_export_templates.py --output-dir data_exports --overwrite
```

`data_export_request.md` / `data_export_request_zh.md` 是给券商终端操作员、数据商或你自己的数据管道看的导出说明;
CSV 模板只是文件名和字段名壳子。

如果券商或数据商给的是原始日线 CSV,先规范成标准 `bars.csv`:

```powershell
.\.venv\Scripts\python.exe examples\normalize_vendor_bars.py `
  --input "<raw-vendor-bars.csv>" `
  --output-dir data_exports `
  --encoding auto `
  --start 2024-06-03 `
  --end 2026-06-05 `
  --min-symbols 300
```

Use `--encoding auto` when the original broker/vendor CSV is exported as
GBK/GB18030. Common Chinese OHLCV headers such as `证券代码`, `交易日期`,
`开盘价`, `最高价`, `最低价`, `收盘价`, `成交量`, and `成交额`
are mapped by the normalizer before the doctor and CSV validator run.

这个步骤只做本地格式规范化和预检,不等于 source QA、CSV validation、缓存导入、策略通过或实盘许可。

把模板行替换成真实 A 股日频导出或完成规范化后,运行 doctor:

```powershell
.\.venv\Scripts\python.exe examples\run_data_import_doctor.py `
  --data-dir data_exports `
  --config config\research_recent.yaml `
  --output-dir results\import\doctor
```

输出文件:

- `data_import_doctor.json`
- `data_import_doctor.md`

报告里的 `Export Requirements` / `export_requirements` 会列出本轮需要的数据窗口、
最少股票数量、股票池、复权口径、必需文件和推荐文件。按当前 `config/research_recent.yaml`,
核心要求是 2024-06-03 到 2026-06-05 的 A 股日频数据、至少 300 只股票、前复权 `qfq`,
股票池为 `all_a` / `000906` 研究上下文,且不把 ST 作为默认可投资股票池。

如果 status 是 `BLOCK`,先修复报告里的 finding。不要继续导入缓存。

如果只是刚运行过 `write_data_export_templates.py`,doctor 会给出
`TEMPLATE_EXPORT_UNREPLACED` 并保持 `BLOCK`。这是刻意设计: 模板文件只用来告诉你字段名,
不能作为近期真实 A 股研究证据。

如果 status 是 `WATCH`,可以继续研究性导入,但必须保留 WATCH 证据,并在后续 `real_data_bootstrap`、`data_audit`、`llm_review` 中继续审查。

如果 status 是 `PASS`,再运行报告里的 import 命令,然后必须重新跑:

受控 intake 前可以先跑包级 readiness,把 source QA、CSV inventory、模板行检测和 doctor 合成一张离线数据包就绪卡:

```powershell
.\.venv\Scripts\python.exe examples\run_offline_data_package.py `
  --data-dir data_exports `
  --config config\research_recent.yaml `
  --output-dir results\first_million `
  --source-qa-answers data_exports\data_source_qa_answers.json `
  --as-of 2026-06-08 `
  --min-symbols 300
```

也可以使用受控 intake 命令让系统按顺序执行 doctor、CSV validation、import 和 bootstrap。
它会在任一 BLOCK 时停止,不会把模板样例写进研究缓存:

```powershell
.\.venv\Scripts\python.exe examples\run_offline_data_intake.py `
  --raw-bars-csv "<raw-vendor-bars.csv>" `
  --data-dir data_exports `
  --config config\research_recent.yaml `
  --output-dir results\import\offline_intake `
  --source-qa-answers data_exports\data_source_qa_answers.json `
  --source-vendor "<vendor-or-broker>" `
  --source-terminal "<terminal-name>" `
  --source-operator "<operator>" `
  --source-exported-at "<local-time>" `
  --source-price-adjustment qfq `
  --source-price-adjustment-evidence "<evidence>" `
  --source-license-evidence "<evidence>" `
  --source-point-in-time-evidence "<evidence-or-non-pit-note>" `
  --source-reviewed-by "<name>" `
  --source-reviewed-at "<date>" `
  --as-of 2026-06-08 `
  --min-symbols 300 `
  --min-trading-days 240
```

传入 `--raw-bars-csv` 时,intake 会先把原始券商/数据商日线 CSV 规范成 `bars.csv`,并把 `vendor_bars_normalization.json/md` 作为第一步证据留下。这个步骤 BLOCK 时不会继续 doctor、validation 或写缓存。

For raw vendor CSV intake, the first evidence file must keep the raw input
fingerprint. Check that `vendor_bars_normalization.json.raw_sha256` matches
`data_import.json.metadata.raw_vendor_bars_sha256` and SQLite
`research_metadata.raw_vendor_bars_sha256` after a successful guarded import.

传入 `--source-*` 时,intake 会从这些显式证据写出 `data_source_qa_answers.json`。这些字段必须是真实导出证据; 缺字段、占位符或弱证据会让 source QA 保持 BLOCK。

```powershell
.\.venv\Scripts\python.exe examples\run_goal_status.py `
  --report-dir results\goal `
  --config config\research_recent.yaml `
  --source-qa-dir results\import\source_qa `
  --import-doctor-dir results\import\doctor `
  --offline-intake-dir results\import\offline_intake `
  --as-of 2026-06-08 `
  --starting-capital 100000 `
  --target-capital 1000000 `
  --years 8 `
  --min-symbols 300 `
  --min-trading-days 240
```

```powershell
.\.venv\Scripts\python.exe examples\run_first_million_pipeline.py `
  --config config\research_recent.yaml `
  --data-dir data_exports `
  --output-dir results\first_million `
  --source-qa-answers data_exports\data_source_qa_answers.json `
  --as-of 2026-06-08 `
  --min-symbols 300 `
  --min-trading-days 240
```

```powershell
.\.venv\Scripts\python.exe examples\run_real_data_bootstrap.py `
  --config config\research_recent.yaml `
  --output-dir results\bootstrap_recent `
  --min-symbols 300 `
  --as-of 2026-06-08
```

## 安全边界

- 不要把模板样例行当作真实数据。
- 不要在 doctor 为 BLOCK 时继续 bootstrap。
- CSV PASS 只代表数据合同可导入,不是策略通过。
- LLM 不能覆盖 deterministic gate。
- 本项目仍然不连接真实 broker,不自动下单。
