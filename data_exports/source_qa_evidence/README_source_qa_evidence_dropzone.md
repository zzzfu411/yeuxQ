# Source QA Evidence Dropzone Kit

- Evidence directory: `data_exports\source_qa_evidence`
- Worksheet: `data_exports\data_source_qa_evidence_worksheet.csv`
- Manifest: `data_exports\source_qa_evidence_manifest.json`
- Answers: `data_exports\data_source_qa_answers.json`

Place retained source-QA evidence files here before generating the strict manifest. This kit is an operator instruction sheet only; it does not create evidence, answer source QA, approve data, approve a strategy, or connect to a broker.

## Required Files

| id | suggested file | required evidence | do not use |
| --- | --- | --- | --- |
| `source_identity` | `data_exports\source_qa_evidence\source_identity_receipt.png` | Filled source_metadata fields or a vendor export receipt. | unlabeled screenshots, copied vendor names without terminal/export timestamp, or generated receipts |
| `license_scope` | `data_exports\source_qa_evidence\license_scope_note.pdf` | License note, account permission, or vendor terms kept with the export. | assumed license text, copied public marketing pages, or notes without account/vendor context |
| `price_adjustment` | `data_exports\source_qa_evidence\price_adjustment_qfq.png` | Vendor export setting screenshot or metadata note. | unverified adjustment labels, mixed raw/qfq/hfq exports, or screenshots without the setting visible |
| `point_in_time` | `data_exports\source_qa_evidence\point_in_time_note.md` | Vendor documentation or a note that non-PIT data must remain research-only. | after-the-fact fundamentals claims, survivorship-only notes, or vague PIT assertions |
| `manual_signoff` | `data_exports\source_qa_evidence\manual_signoff.md` | reviewed_by and reviewed_at filled in the metadata template or approval notes. | unsigned notes, LLM-generated approvals, or signoff without reviewer/date |

## Checklist
- Copy retained vendor, broker, terminal, license, adjustment, PIT/limitation, and human-review evidence files into the evidence directory.
- Use filenames that include the source QA id when practical, for example source_identity_receipt.png or price_adjustment_qfq.png.
- Fill data_source_qa_evidence_worksheet.csv from the retained evidence; do not use placeholders or generated examples.
- Run worksheet preflight before converting worksheet rows into data_source_qa_answers.json.
- Regenerate source_qa_evidence_manifest.json with --strict after every evidence-file change.
- Rerun source QA evidence readiness and the first-million pipeline after the manifest and answers pass deterministic review.

## Command Sequence

1.

```powershell
.\.venv\Scripts\python.exe examples\fill_data_source_qa_evidence_worksheet.py --checklist data_exports\data_source_qa.json --worksheet data_exports\data_source_qa_evidence_worksheet.csv --output-dir data_exports --vendor "<real-vendor-or-broker>" --terminal "<terminal-product-and-version>" --operator "<export-operator>" --exported-at "<local-export-time>" --price-adjustment "<raw-qfq-or-hfq>" --license-scope "<retained-license-scope>" --reviewed-by "<human-reviewer>" --reviewed-at "<review-date>" --source-identity-evidence "<retained-source-identity-evidence>" --license-evidence "<retained-license-evidence>" --price-adjustment-evidence "<retained-adjustment-evidence>" --point-in-time-evidence "<retained-pit-or-non-pit-limitation-evidence>" --manual-signoff-evidence "<retained-human-signoff-evidence>"
```

2.

```powershell
.\.venv\Scripts\python.exe examples\run_data_source_qa_worksheet_preflight.py --checklist data_exports\data_source_qa.json --worksheet data_exports\data_source_qa_evidence_worksheet.csv --output-dir data_exports
```

3.

```powershell
.\.venv\Scripts\python.exe examples\write_source_qa_evidence_manifest.py --checklist data_exports\data_source_qa.json --evidence-dir data_exports\source_qa_evidence --output-dir data_exports --strict
```

4.

```powershell
.\.venv\Scripts\python.exe examples\write_data_source_qa_answers.py --checklist data_exports\data_source_qa.json --worksheet data_exports\data_source_qa_evidence_worksheet.csv --output data_exports\data_source_qa_answers.json --evidence-manifest data_exports\source_qa_evidence_manifest.json --require-evidence-manifest
```

5.

```powershell
.\.venv\Scripts\python.exe examples\run_source_qa_evidence_readiness.py --checklist data_exports\data_source_qa.json --worksheet data_exports\data_source_qa_evidence_worksheet.csv --answers data_exports\data_source_qa_answers.json --evidence-manifest data_exports\source_qa_evidence_manifest.json --require-evidence-manifest --output-dir results\first_million\source_qa
```

6.

```powershell
.\.venv\Scripts\python.exe examples\run_source_qa_evidence_inbox.py --data-dir data_exports --report-dir results\prospective\guard_v1_20260716\operational_status
```

7.

```powershell
.\.venv\Scripts\python.exe examples\run_first_million_pipeline.py --config config\research_recent.yaml --data-dir data_exports --output-dir results\first_million --source-qa-answers data_exports\data_source_qa_answers.json --source-qa-evidence-manifest data_exports\source_qa_evidence_manifest.json --require-source-qa-evidence-manifest --as-of <YYYY-MM-DD> --min-symbols 300 --no-registry
```

## Prohibited Actions
- Do not fabricate worksheet answers, screenshots, PDFs, notes, or approval records.
- Do not use generated todo files, templates, or this packet as source evidence.
- Do not convert a worksheet into data_source_qa_answers.json while preflight is BLOCK.
- Do not run guarded offline intake until source QA answers and evidence manifest pass deterministic review.
- Do not treat source QA readiness as strategy approval, profit evidence, or broker permission.
- Do not let LLM text sign off source evidence or human approval.
