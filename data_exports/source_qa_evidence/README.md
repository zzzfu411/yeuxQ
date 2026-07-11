# Source QA Evidence Folder

Place only real local evidence files in this directory. The manifest command hashes these files; it does not verify that their content is truthful.

Suggested current attachments are listed in:

- `results\first_million\source_qa_evidence_attachment_plan.csv`
- `results\first_million\source_qa_evidence_attachment_plan.md`

After adding or replacing files, run:

```powershell
.\.venv\Scripts\python.exe examples\write_source_qa_evidence_manifest.py --checklist data_exports\data_source_qa.json --evidence-dir data_exports\source_qa_evidence --output-dir data_exports --strict
```

Do not put fabricated screenshots, blank PDFs, generated placeholders, or files you are not allowed to retain here.
Passing this folder check is not a strategy approval and never permits real broker order submission.
