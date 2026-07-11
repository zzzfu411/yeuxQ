# Data Source QA Evidence Worksheet

Fill this worksheet from real vendor, terminal, export, license, and human review evidence.
It is a collection aid only; it does not create `data_source_qa_answers.json` or weaken gates.

- Checklist: `data_exports\data_source_qa.json`

## Rows To Fill

| type | id | CLI argument | severity | question or field | required evidence |
| --- | --- | --- | --- | --- | --- |
| `metadata` | `data_vendor_or_broker` | `--vendor` | `REQUIRED` | data_vendor_or_broker | Exact vendor, broker, or terminal data source name. |
| `metadata` | `terminal_or_product_name` | `--terminal` | `REQUIRED` | terminal_or_product_name | Terminal/product name and version when available. |
| `metadata` | `export_operator` | `--operator` | `REQUIRED` | export_operator | Human or process that produced the export. |
| `metadata` | `exported_at_local_time` | `--exported-at` | `REQUIRED` | exported_at_local_time | Local timestamp for the export batch. |
| `metadata` | `price_adjustment` | `--price-adjustment` | `REQUIRED` | price_adjustment | Configured adjustment setting such as raw, qfq, or hfq. |
| `metadata` | `license_or_usage_scope` | `--license-scope` | `REQUIRED` | license_or_usage_scope | Allowed use scope from vendor terms, broker account, or internal policy. |
| `metadata` | `reviewed_by` | `--reviewed-by` | `REQUIRED` | reviewed_by | Human reviewer name or identifier. |
| `metadata` | `reviewed_at` | `--reviewed-at` | `REQUIRED` | reviewed_at | Review date or timestamp. |
| `source_question` | `source_identity` | `--vendor/--terminal/--operator/--exported-at` | `BLOCK_IF_NO` | Can the vendor, terminal/product, export operator, and export time be identified? | Filled source_metadata fields or a vendor export receipt. |
| `source_question` | `license_scope` | `--license-evidence` | `BLOCK_IF_NO` | Is the data license limited to lawful research/paper use in this project? | License note, account permission, or vendor terms kept with the export. |
| `source_question` | `price_adjustment` | `--price-adjustment-evidence` | `BLOCK_IF_NO` | Are OHLC prices exported with the configured adjustment method `qfq`? | Vendor export setting screenshot or metadata note. |
| `source_question` | `point_in_time` | `--point-in-time-evidence` | `BLOCK_IF_NO` | Are fundamentals and index constituents point-in-time or explicitly marked as non-PIT? | Vendor documentation or a note that non-PIT data must remain research-only. |
| `source_question` | `manual_signoff` | `--reviewed-by/--reviewed-at` | `BLOCK_IF_NO` | Has a human reviewed source QA before strategy research uses the cache? | reviewed_by and reviewed_at filled in the metadata template or approval notes. |

## Workflow Commands

```powershell
.\.venv\Scripts\python.exe examples\write_data_source_qa_evidence_worksheet.py --checklist data_exports\data_source_qa.json --output-dir data_exports
```

```powershell
.\.venv\Scripts\python.exe examples\fill_data_source_qa_evidence_worksheet.py --checklist data_exports\data_source_qa.json --worksheet data_exports\data_source_qa_evidence_worksheet.csv --vendor "<vendor-or-broker>" --terminal "<terminal-name>" --operator "<operator>" --exported-at "<local-time>" --price-adjustment "<raw-or-qfq-or-hfq>" --license-scope "research and paper trading only" --reviewed-by "<name>" --reviewed-at "<YYYY-MM-DD>" --source-identity-evidence "<retained-source-identity-evidence>" --license-evidence "<retained-license-evidence>" --price-adjustment-evidence "<retained-price-adjustment-evidence>" --point-in-time-evidence "<retained-PIT-evidence-or-research-only-note>" --manual-signoff-evidence "<retained-human-review-evidence>"
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

## Safety Boundaries
- This worksheet is a human evidence collection aid, not an automatic approval.
- Do not invent answers or evidence to make source QA pass.
- Leaving rows blank keeps the deterministic source QA and preflight gates BLOCK.
- The worksheet cannot modify PASS/WATCH/BLOCK decisions.
- This workflow is for research and paper trading only; it must not connect to a real broker.
