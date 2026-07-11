# A-share Data Source QA Checklist

Use this before replacing the offline CSV templates with real vendor exports.
It is a source-quality and reproducibility checklist, not a trading signal.

## Scope

- Market: `A-share equities`
- Frequency: `daily`
- Date range: `2024-06-03` to `2026-06-05`
- As-of: `2026-07-06`
- Minimum symbols: 300
- Price adjustment: `qfq`
- Universe mode: `all_a`
- Index context: `000906`
- Include ST in investable universe: `False`
- Minimum history days: 120

## Source Metadata To Fill

| field | value |
| --- | --- |
| `data_vendor_or_broker` | `` |
| `terminal_or_product_name` | `` |
| `export_operator` | `` |
| `exported_at_local_time` | `` |
| `market` | `A-share equities` |
| `frequency` | `daily` |
| `date_range` | `2024-06-03 to 2026-06-05` |
| `price_adjustment` | `qfq` |
| `encoding` | `utf-8-sig or gbk` |
| `license_or_usage_scope` | `research and paper trading only` |
| `known_limitations` | `` |
| `reviewed_by` | `` |
| `reviewed_at` | `` |

## Expected Files

| file | required | columns |
| --- | --- | --- |
| `bars.csv` | `yes` | `symbol, date, open, high, low, close, volume, amount` |
| `stock_info.csv` | `recommended` | `symbol, name, exchange, list_date, delist_date, industry, is_st` |
| `fundamentals.csv` | `recommended` | `symbol, date, pe_ttm, pb, roe, market_cap, turnover_rate` |
| `calendar.csv` | `recommended` | `date, is_open` |
| `suspensions.csv` | `recommended` | `symbol, date, is_suspended` |
| `index_constituents.csv` | `recommended` | `index_code, date, symbol` |

## QA Questions

| id | stage | severity | question | required evidence | why it matters |
| --- | --- | --- | --- | --- | --- |
| `source_identity` | `source` | `BLOCK_IF_NO` | Can the vendor, terminal/product, export operator, and export time be identified? | Filled source_metadata fields or a vendor export receipt. | Unidentified data cannot be reproduced or audited after a surprising backtest. |
| `license_scope` | `source` | `BLOCK_IF_NO` | Is the data license limited to lawful research/paper use in this project? | License note, account permission, or vendor terms kept with the export. | The system must not rely on data that cannot be legally used or retained. |
| `date_window` | `csv_validation` | `BLOCK_IF_NO` | Does bars.csv cover the configured research window through the latest completed trading day? | Doctor/CSV validation summary showing bars_start and bars_end. | Stale or partial bars can create false strategy stability. |
| `symbol_breadth` | `csv_validation` | `BLOCK_IF_NO` | Does the export contain enough A-share symbols for the configured minimum universe? | CSV validation metric bars_symbol_count >= min_symbols. | A small universe can turn a broad-market strategy into a cherry-picked sample. |
| `price_adjustment` | `source` | `BLOCK_IF_NO` | Are OHLC prices exported with the configured adjustment method `qfq`? | Vendor export setting screenshot or metadata note. | Mixed raw/qfq/hfq prices invalidate returns, drawdowns, and factor ranks. |
| `calendar` | `csv_validation` | `WATCH_IF_NO` | Is a trading calendar supplied or clearly inferable from bars.csv? | calendar.csv or validation note that calendar was inferred. | Missing open-day evidence weakens missing-bar and paper execution checks. |
| `suspensions_limits` | `csv_validation` | `WATCH_IF_NO` | Are suspensions and limit-up/limit-down constraints available or documented as missing? | suspensions.csv plus vendor notes for unavailable limit flags. | Paper fills become too optimistic if non-tradable days are invisible. |
| `st_delist_flags` | `csv_validation` | `WATCH_IF_NO` | Does stock_info include ST and delist fields for investable-universe audit? | stock_info.csv columns is_st and delist_date. | ST/delist gaps can hide risks that manual trading must avoid. |
| `point_in_time` | `source` | `BLOCK_IF_NO` | Are fundamentals and index constituents point-in-time or explicitly marked as non-PIT? | Vendor documentation or a note that non-PIT data must remain research-only. | Non-point-in-time data can leak future information into strategy selection. |
| `file_fingerprint` | `csv_validation` | `BLOCK_IF_NO` | Will the imported files be fingerprinted and kept unchanged after validation? | csv_validation dataset_fingerprint and file sha256 values. | Every research result must be traceable to the exact data batch used. |
| `manual_signoff` | `source` | `BLOCK_IF_NO` | Has a human reviewed source QA before strategy research uses the cache? | reviewed_by and reviewed_at filled in the metadata template or approval notes. | Human approval owns source risk; LLM output cannot bless uncertain data. |

## Workflow Commands

```powershell
.\.venv\Scripts\python.exe examples\write_data_export_request.py --config config\research_recent.yaml --output-dir data_exports --min-symbols 300
```

```powershell
.\.venv\Scripts\python.exe examples\write_data_source_qa.py --config config\research_recent.yaml --output-dir data_exports --min-symbols 300 --as-of 2026-07-06
```

```powershell
.\.venv\Scripts\python.exe examples\write_data_source_qa_evidence_worksheet.py --checklist data_exports\data_source_qa.json --output-dir data_exports
```

```powershell
.\.venv\Scripts\python.exe examples\write_source_qa_evidence_manifest.py --checklist data_exports\data_source_qa.json --evidence-dir data_exports\source_qa_evidence --output-dir data_exports --strict
```

```powershell
.\.venv\Scripts\python.exe examples\write_data_source_qa_answers.py --checklist data_exports\data_source_qa.json --output data_exports\data_source_qa_answers.json --evidence-manifest data_exports\source_qa_evidence_manifest.json --require-evidence-manifest --vendor <vendor-or-broker> --terminal <terminal-name> --operator <operator> --exported-at <local-time> --price-adjustment qfq --price-adjustment-evidence <evidence> --license-evidence <evidence> --point-in-time-evidence <evidence-or-non-pit-note> --reviewed-by <name> --reviewed-at <date>
```

```powershell
.\.venv\Scripts\python.exe examples\run_source_qa_preflight.py --checklist data_exports\data_source_qa.json --answers data_exports\data_source_qa_answers.json --output-dir results\import\source_qa
```

```powershell
.\.venv\Scripts\python.exe examples\run_data_source_qa_review.py --checklist data_exports\data_source_qa.json --answers data_exports\data_source_qa_answers.json --evidence-manifest data_exports\source_qa_evidence_manifest.json --require-evidence-manifest --output-dir results\import\source_qa
```

```powershell
.\.venv\Scripts\python.exe examples\write_data_export_templates.py --output-dir data_exports
```

```powershell
.\.venv\Scripts\python.exe examples\run_offline_data_intake.py --data-dir data_exports --config config\research_recent.yaml --output-dir results\import\offline_intake --raw-bars-csv <raw-vendor-bars.csv> --source-vendor <vendor-or-broker> --source-terminal <terminal-name> --source-operator <operator> --source-exported-at <local-time> --source-price-adjustment qfq --source-price-adjustment-evidence <evidence> --source-license-evidence <evidence> --source-point-in-time-evidence <evidence-or-non-pit-note> --source-reviewed-by <name> --source-reviewed-at <date> --min-symbols 300 --min-trading-days 240 --source-qa-answers data_exports\data_source_qa_answers.json --as-of 2026-07-06
```

## Safety Boundaries
- This QA checklist is for data sourcing, research, and paper trading only.
- Do not use a source checklist as evidence that a strategy is profitable.
- Do not continue while any BLOCK_IF_NO source question is unanswered or negative.
- Do not connect these CSV exports to real broker order submission.
- After CSV import, real_data_bootstrap, data_audit, robustness, and paper gates still decide readiness.
