# Raw Bars Dropzone Kit

- Dropzone directory: `data_exports\raw`
- Source-QA evidence directory: `data_exports\source_qa_evidence`

Place retained broker/vendor A-share daily-bars exports here before running discovery. This kit is an operator instruction sheet only; it does not create market data, source evidence, strategy approval, or broker connectivity.

## Accepted Files

- Extensions: `.csv, .zip`
- Prefer one retained raw CSV exported directly from the broker/vendor terminal.
- Zip archives may be retained as evidence, but discovery will stay BLOCK until the daily-bars CSV is extracted.
- Do not edit the retained raw CSV after export; normalization reports its sha256.

## Columns

- Required: `symbol, date, open, high, low, close, volume`
- Optional: `amount`
- Common Chinese broker headers are accepted by the normalizer; use `--encoding auto` for GBK/GB18030 exports.

## Source QA Files
- `data_exports\data_source_qa.json`
- `data_exports\data_source_qa_evidence_worksheet.csv`
- `data_exports\source_qa_evidence`
- `data_exports\source_qa_evidence_manifest.json`
- `data_exports\data_source_qa_answers.json`

## Checklist
- Copy the retained raw broker/vendor daily-bars CSV into the dropzone.
- Keep the original export and any zip/archive receipt as retained evidence.
- Confirm the export covers the configured research window and the latest completed trading day.
- Confirm the price adjustment matches the config, for example qfq/hfq/raw.
- Attach source identity, license, export timestamp, price-adjustment, and human-review evidence under the source-QA evidence directory.
- Run discovery before normalization; only normalize PASS/WATCH candidates after source QA evidence is prepared.
- Rerun the first-million pipeline after guarded intake writes a traceable research cache.

## Command Sequence

1.

```powershell
.\.venv\Scripts\python.exe examples\run_raw_bars_discovery.py --search-dir data_exports\raw --config config\research_recent.yaml --output-dir results\first_million --data-output-dir data_exports --encoding auto --min-symbols 300
```

2.

```powershell
.\.venv\Scripts\python.exe examples\normalize_vendor_bars.py --input "data_exports\raw\<broker_vendor_daily_bars.csv>" --output-dir data_exports --report-dir results\first_million --encoding auto --start 2024-06-03 --end 2026-06-05 --min-symbols 300
```

3.

```powershell
.\.venv\Scripts\python.exe examples\write_data_source_qa.py --config config\research_recent.yaml --output-dir data_exports --min-symbols 300
```

4.

```powershell
.\.venv\Scripts\python.exe examples\write_data_source_qa_evidence_worksheet.py --checklist data_exports\data_source_qa.json --output-dir data_exports
```

5.

```powershell
.\.venv\Scripts\python.exe examples\write_source_qa_evidence_manifest.py --checklist data_exports\data_source_qa.json --evidence-dir data_exports\source_qa_evidence --output-dir data_exports --strict
```

6.

```powershell
.\.venv\Scripts\python.exe examples\write_data_source_qa_answers.py --checklist data_exports\data_source_qa.json --worksheet data_exports\data_source_qa_evidence_worksheet.csv --output data_exports\data_source_qa_answers.json --evidence-manifest data_exports\source_qa_evidence_manifest.json --require-evidence-manifest
```

7.

```powershell
.\.venv\Scripts\python.exe examples\run_ohlcv_intake_closeout.py --data-dir data_exports --report-dir results\first_million --config config\research_recent.yaml --source-qa-answers data_exports\data_source_qa_answers.json --source-qa-evidence-manifest data_exports\source_qa_evidence_manifest.json --require-source-qa-evidence-manifest --min-symbols 300 --min-trading-days 240
```

8.

```powershell
.\.venv\Scripts\python.exe examples\run_first_million_pipeline.py --config config\research_recent.yaml --data-dir data_exports --output-dir results\first_million --source-qa-answers data_exports\data_source_qa_answers.json --source-qa-evidence-manifest data_exports\source_qa_evidence_manifest.json --require-source-qa-evidence-manifest --min-symbols 300 --min-trading-days 240
```

## Prohibited Actions
- Do not fabricate, edit, or backfill raw bars to satisfy coverage checks.
- Do not treat this dropzone README as source QA, license evidence, strategy approval, or profit evidence.
- Do not use OHLCV-only data for point-in-time fundamentals, valuation, or quality claims.
- Do not connect this workflow to real broker order submission.
