# Source QA Evidence Manifest Preflight: BLOCK

- Checklist: `data_exports\data_source_qa.json`
- Manifest: `data_exports\source_qa_evidence_manifest.json`
- Evidence directory: `data_exports\source_qa_evidence`
- Required attachments: 5
- Valid required attachments: 0
- Missing required attachments: 5
- Invalid attachments: 0

## Findings

| status | code | id | message | fix |
| --- | --- | --- | --- | --- |
| `BLOCK` | `SOURCE_QA_EVIDENCE_ATTACHMENT_MISSING` | `source_identity` | Required source QA evidence attachment is missing or invalid. | Place a retained local evidence file under source_qa_evidence and regenerate the manifest. |
| `BLOCK` | `SOURCE_QA_EVIDENCE_ATTACHMENT_MISSING` | `license_scope` | Required source QA evidence attachment is missing or invalid. | Place a retained local evidence file under source_qa_evidence and regenerate the manifest. |
| `BLOCK` | `SOURCE_QA_EVIDENCE_ATTACHMENT_MISSING` | `price_adjustment` | Required source QA evidence attachment is missing or invalid. | Place a retained local evidence file under source_qa_evidence and regenerate the manifest. |
| `BLOCK` | `SOURCE_QA_EVIDENCE_ATTACHMENT_MISSING` | `point_in_time` | Required source QA evidence attachment is missing or invalid. | Place a retained local evidence file under source_qa_evidence and regenerate the manifest. |
| `BLOCK` | `SOURCE_QA_EVIDENCE_ATTACHMENT_MISSING` | `manual_signoff` | Required source QA evidence attachment is missing or invalid. | Place a retained local evidence file under source_qa_evidence and regenerate the manifest. |

## Next Commands

```powershell
.\.venv\Scripts\python.exe examples\write_source_qa_evidence_manifest.py --checklist data_exports\data_source_qa.json --evidence-dir data_exports\source_qa_evidence --output-dir data_exports --strict
```

## Prohibited Actions
- Do not fabricate evidence files to satisfy manifest coverage.
- Do not use generated worksheet, plan, sample, placeholder, or README files as retained source evidence.
- Do not treat manifest preflight PASS as source QA approval by itself.
- Do not import offline data until strict source QA review passes.
- Do not connect this workflow to real broker order submission.
