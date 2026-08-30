# Reviewed Exchange-Calendar Evidence Dropzone

Place real reviewed A-share exchange-calendar evidence here only after it has
been obtained from the named source and reviewed. The expected evidence is a
CSV and its hash-binding metadata JSON; see
`docs/26_Reviewed_Exchange_Calendar.md` for the exact contract and commands.

This directory intentionally contains no sample CSV or metadata. Do not create
placeholder files, copy test fixtures, infer holidays from missing bars, or
fabricate source/reviewer fields. A missing pair is a real evidence gap and the
strict preflight must remain `BLOCK`.

Before review, finalize the CSV bytes. Record the SHA-256 of those exact bytes
in `file_sha256`, use actual timezone-aware export/review timestamps, and do not
edit the CSV afterward. Keep the CSV and metadata together when running the
preflight or continuity report.

All files in this directory except this README are ignored by Git because they
may contain real licensed or operational evidence. Retain and transfer the
evidence through the approved external evidence store; never force-add it to
the repository.
