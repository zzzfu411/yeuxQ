# A-share Offline Data Export Request

Give this request to a broker terminal operator, data vendor, or your own data pipeline.
The files are research inputs only; they are not broker orders or trading instructions.

## Scope

- Market: `A-share equities`
- Frequency: `daily`
- Date range: `2024-06-03` to `2026-06-05`
- Minimum symbols: 300
- Cache target: `./data_cache/research_recent.db`
- Price adjustment: `qfq`
- Universe mode: `all_a`
- Index context: `000906`
- Include ST in investable universe: `False`
- Minimum history days: 120

## Files To Export

| file | required | columns | purpose |
| --- | --- | --- | --- |
| `bars.csv` | `yes` | `symbol, date, open, high, low, close, volume, amount` | Daily OHLCV bars. One row per symbol and trading date. |
| `stock_info.csv` | `recommended` | `symbol, name, exchange, list_date, delist_date, industry, is_st` | Static symbol metadata used for universe filtering and audit context. |
| `fundamentals.csv` | `recommended` | `symbol, date, pe_ttm, pb, roe, market_cap, turnover_rate` | Point-in-time factor inputs for value, quality, size, and liquidity features. |
| `calendar.csv` | `recommended` | `date, is_open` | Trading calendar. Closed days should use is_open=0 or be omitted. |
| `suspensions.csv` | `recommended` | `symbol, date, is_suspended` | Suspension flags used by paper execution and manual-readiness gates. |
| `index_constituents.csv` | `recommended` | `index_code, date, symbol` | Point-in-time index or research-universe membership snapshots. |

## Acceptance Criteria
- bars.csv must cover the requested date range through the latest completed trading day.
- bars.csv must contain at least 300 distinct A-share symbols.
- Price adjustment must be consistent with the configured qfq/hfq/raw setting.
- Template sample rows and demo data must be fully replaced before import.
- stock_info should include ST and delist fields so investable filters can be audited.
- calendar and suspensions should be supplied when available to support execution gates.
- index_constituents should be point-in-time when used as the research universe.
- data_source_qa_evidence_worksheet.csv should be filled from real export evidence before answers are written.
- data_source_qa_answers.json must be filled and pass source QA preflight.

## Workflow Commands

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

## Safety Boundaries
- This request is for research and paper trading only.
- Do not connect exported files to a real broker order workflow.
- Do not treat data availability as a promise of strategy profitability.
- After import, real_data_bootstrap and data_audit must pass before strategy evaluation.
