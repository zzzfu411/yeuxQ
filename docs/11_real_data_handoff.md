# Real Data Handoff Checklist

This page describes the operator-facing checklist for closing real A-share data
blockers before strategy experiments.

The checklist is intentionally conservative:

- It does not connect to a broker.
- It does not submit or generate live orders.
- It does not prove profitability.
- It does not let LLM output override deterministic gates or human approval.

## Command

```powershell
.\.venv\Scripts\python.exe examples\run_real_data_handoff.py `
  --data-dir data_exports `
  --config config\research_recent.yaml `
  --output-dir results\first_million `
  --source-qa-answers data_exports\data_source_qa_answers.json `
  --as-of 2026-06-08 `
  --min-symbols 300 `
  --min-trading-days 240
```

Outputs:

- `real_data_handoff_checklist.json`
- `real_data_handoff_checklist.md`

The first-million pipeline also writes these files automatically.

## Provider Smoke Readiness

Before relying on the provider route, keep the tiny AKShare import and its
diagnostic card separate from real-data readiness:

```powershell
.\.venv\Scripts\python.exe examples\import_research_data.py `
  --config config\research_recent.yaml `
  --cache tmp\akshare_smoke.db `
  --symbols 600519,000001 `
  --limit 2 `
  --output-dir results\import\smoke_akshare

.\.venv\Scripts\python.exe examples\run_provider_smoke_readiness.py `
  --config config\research_recent.yaml `
  --latest-import-report results\import\smoke_akshare\data_import.json `
  --output-dir results\first_million `
  --as-of 2026-06-12 `
  --min-symbols 300 `
  --min-trading-days 240
```

Outputs:

- `provider_smoke_readiness.json`
- `provider_smoke_readiness.md`

This card only records provider endpoint viability, sample coverage, network
blockers, and next route actions. A small provider smoke success is not source
QA, not data audit, not bootstrap readiness, not strategy evidence, and not a
paper/live trading permission. The first-million pipeline also writes it from
`--latest-import-report` and surfaces it as an advisory readiness gate; it
cannot upgrade deterministic `PASS/WATCH/BLOCK` decisions.

Before scaling from a tiny smoke to a broader AKShare/provider batch, run the
staged acquisition ramp. It writes to an isolated
`tmp/provider_acquisition_ramp.db` cache by default so probe data cannot
silently become the configured research cache:

```powershell
.\.venv\Scripts\python.exe examples\run_provider_acquisition_ramp.py `
  --config config\research_recent.yaml `
  --stage-sizes 2,20,100,300 `
  --output-dir results\import\provider_acquisition_ramp
```

Outputs:

- `provider_acquisition_ramp.json`
- `provider_acquisition_ramp.md`
- per-stage `data_import.json/md`

The ramp stops on the first `BLOCK`. If every stage passes, treat it only as
bounded provider acquisition viability; it does not grant source QA/provenance
`PASS`, promotion readiness, paper trading, live trading, or broker-order
permission.
Pass the JSON to `run_first_million_pipeline.py` with
`--provider-acquisition-ramp-report results\import\provider_acquisition_ramp\provider_acquisition_ramp.json`
when you want first-million readiness and goal status to show these route
diagnostics. The copied report is route diagnostics only: neither `PASS` nor
`BLOCK` can replace source QA, offline intake, promotion gates, candidate
readiness, or trading gates.

When the AKShare all-A spot-list endpoint is blocked but explicit per-symbol
daily bars work, import only from a reviewed symbol file into an isolated cache:

```powershell
.\.venv\Scripts\python.exe examples\import_research_data.py `
  --config config\research_recent.yaml `
  --cache tmp\akshare_recent_explicit_50.db `
  --symbols-file config\akshare_explicit_50_symbols.txt `
  --limit 50 `
  --output-dir results\import\akshare_recent_explicit_50

.\.venv\Scripts\python.exe examples\run_real_data_bootstrap.py `
  --config config\research_recent.yaml `
  --cache tmp\akshare_recent_explicit_50.db `
  --output-dir results\import\akshare_recent_explicit_50_bootstrap `
  --as-of 2026-06-10 `
  --min-symbols 50 `
  --min-trading-days 240
```

Follow with `run_data_audit.py` and `run_market_regime.py` on the same isolated
cache. This route documents provider viability for the listed symbols only. It
does not replace the broad A-share universe requirement, source QA evidence,
offline intake, candidate robustness, paper stability, or human approval.

The same pipeline writes `data_evidence_action_packet.json/md` before source QA
preflight. That packet is the shortest operator work order when data gates are
blocked. `first_million_readiness.json/md` includes it as a dedicated gate, and
`first_million_strategy_brief.json/md` shows its first next action before any
candidate experiment instruction.

The action packet writer also emits:

- `source_qa_worksheet_todo.csv/md`
- `source_qa_attachment_todo.csv/md`
- `source_qa_evidence_attachment_plan.csv/md`
- `data_export_todo.csv/md`
- `operator_handoff.csv/md`
- `operator_handoff_status.json/md`

`operator_handoff.csv/md` is the unified operator queue. It combines missing
source QA worksheet rows, source QA attachment tasks, file-level export actions,
next commands, completion criteria, and a fixed gate note. It is only a handoff
aid; deterministic source QA, import, audit, readiness gates, and human approval
still decide whether any stage can advance.

`source_qa_evidence_attachment_plan.csv/md` points to suggested local files
under `data_exports\source_qa_evidence` and records examples of weak evidence
that must not be used. It does not create screenshots, PDFs, or approval notes;
operators must attach real retained evidence and regenerate
`source_qa_evidence_manifest.json` before strict source QA can pass.

For each data export row, `data_export_todo.csv` and `operator_handoff.csv`
also include CSV preview columns: `preview_status`, `raw_columns`,
`mapped_columns`, `missing_columns`, and `preview_message`. These fields only
show whether the current file can be mapped into the research CSV schema. A
`PASS` preview can still be blocked by template rows, stale dates, source QA,
validation, audit, or paper gates.

`operator_handoff_status.json/md` is the progress view for that queue. It
reports open P0/P1 counts and the first remaining actions, but it is not a
separate approval gate and cannot replace source QA or offline intake.

```powershell
.\.venv\Scripts\python.exe examples\run_operator_handoff_status.py `
  --data-dir data_exports `
  --config config\research_recent.yaml `
  --output-dir results\first_million `
  --source-qa-answers data_exports\data_source_qa_answers.json `
  --as-of 2026-06-08 `
  --min-symbols 300
```

`results\first_million\evidence_intake_kit` is the staging kit for the same
handoff. It merges the required source QA attachments, real CSV export requests,
and broad-index CSV request into one manifest and three empty incoming
directories:

- `incoming_source_qa_evidence`
- `incoming_data_exports`
- `incoming_market_indices`

Refresh it directly:

```powershell
.\.venv\Scripts\python.exe examples\run_first_million_evidence_intake_kit.py `
  --report-dir results\first_million `
  --data-dir data_exports `
  --as-of 2026-06-10
```

The kit is not evidence. It creates instructions and staging directories only;
it must not create placeholder screenshots, PDFs, market rows, source QA
answers, approvals, or broker instructions. After real files are copied into
the target paths, rerun source QA evidence inbox, manifest generation, raw bars
discovery, market index discovery, and the first-million pipeline.

If the real files are placed into the `incoming_*` staging directories first,
review the receipt before copying:

```powershell
.\.venv\Scripts\python.exe examples\run_first_million_evidence_intake_receiver.py `
  --manifest results\first_million\evidence_intake_kit\first_million_evidence_intake_manifest.csv `
  --data-dir data_exports `
  --report-dir results\first_million `
  --as-of 2026-06-10
```

Only after review, rerun with `--apply` to copy accepted files to their
`target_path` values. The receiver rejects empty files, README files,
template/sample/generated/placeholder material, and non-normalizable bars CSVs.
It is a receipt and copy aid only; deterministic source QA, raw bars discovery,
market context readiness, and the first-million pipeline still decide status.

`first_million_evidence_work_order.json/md/csv` turns that same intake state
into ordered batches:

1. source QA worksheet
2. source QA attachments
3. real `bars.csv`
4. recommended audit CSVs
5. broad-index CSV
6. deterministic reruns

Refresh it directly:

```powershell
.\.venv\Scripts\python.exe examples\run_first_million_evidence_work_order.py `
  --report-dir results\first_million `
  --data-dir data_exports `
  --as-of 2026-06-10
```

The work order is only a sequencing view. It cannot mark a batch complete
unless the underlying evidence artifact changes and the owning deterministic
gate confirms it.

For the first batch, `fill_data_source_qa_evidence_worksheet.py` can write the
worksheet from explicit operator-provided source fields and retained evidence
notes:

```powershell
.\.venv\Scripts\python.exe examples\fill_data_source_qa_evidence_worksheet.py `
  --checklist data_exports\data_source_qa.json `
  --worksheet data_exports\data_source_qa_evidence_worksheet.csv `
  --vendor "<vendor-or-broker>" `
  --terminal "<terminal-name>" `
  --operator "<operator>" `
  --exported-at "<local-time>" `
  --price-adjustment qfq `
  --license-scope "research and paper trading only" `
  --reviewed-by "<name>" `
  --reviewed-at "<YYYY-MM-DD>" `
  --source-identity-evidence "<retained-source-identity-evidence>" `
  --license-evidence "<retained-license-evidence>" `
  --price-adjustment-evidence "<retained-price-adjustment-evidence>" `
  --point-in-time-evidence "<retained-PIT-evidence-or-OHLCV-only-note>" `
  --manual-signoff-evidence "<retained-human-review-evidence>"
```

The helper is only a typing aid. It does not create attachments, answers,
approvals, strategy evidence, or broker instructions, and the batch remains
open until worksheet preflight and the downstream deterministic gates accept
the real evidence.

`source_qa_operator_packet.json/md/csv` is the smallest handoff packet for a
human data operator. It merges missing worksheet rows and required attachment
evidence into one checklist with acceptable evidence, forbidden weak evidence,
and the command sequence to run after filling. The first command is a
`fill_data_source_qa_evidence_worksheet.py` template with placeholders that must
be replaced by retained real vendor/export evidence. It never creates answers,
evidence files, approvals, or broker instructions. With `--write-dropzone-kit`,
it also writes
`data_exports\source_qa_evidence\README_source_qa_evidence_dropzone.md`, a
local checklist for the retained evidence files required by strict source QA.

```powershell
.\.venv\Scripts\python.exe examples\run_source_qa_operator_packet.py `
  --data-dir data_exports `
  --report-dir results\first_million `
  --as-of 2026-06-10 `
  --write-dropzone-kit
```

`source_qa_evidence_inbox.json/md/csv` is the read-only local attachment inbox.
It scans `data_exports\source_qa_evidence`, compares files to required Source
QA attachment ids, surfaces missing or unmatched evidence, and reuses the strict
attachment validator to flag generated or placeholder-like files. It also emits
`worksheet_fill_command` for `fill_data_source_qa_evidence_worksheet.py`.
Source evidence arguments in that command are ready only when each value points
to an existing matched or suggested local evidence file. `target_path` values
from the attachment plan and angle-bracket values are human placeholders, even
when they look like useful paths; they must remain not ready until the inbox
matches or suggests a real retained evidence file. The human operator must
still replace vendor, terminal, operator, timestamp, reviewer, and license
placeholders from retained real records. It cannot create evidence, fill
answers, approve Source QA, or change any deterministic `PASS/WATCH/BLOCK`
decision.

```powershell
.\.venv\Scripts\python.exe examples\run_source_qa_evidence_inbox.py `
  --data-dir data_exports `
  --report-dir results\first_million `
  --as-of 2026-06-10
```

`data_intake_status.json/md/csv` is the combined operator status for deciding
what to fix next. It rolls up the source QA evidence inbox, worksheet-fill
readiness, answers, manifest, raw bars discovery, Source QA closeout, and OHLCV
closeout into one read-only card with `next_area`, `next_action`, and
`next_command`. It cannot approve data or strategies and cannot change any
deterministic gate.

```powershell
.\.venv\Scripts\python.exe examples\run_data_intake_status.py `
  --report-dir results\first_million `
  --data-dir data_exports `
  --as-of 2026-06-10
```

`source_qa_closeout.json/md/csv` is the source-QA cover sheet over the operator
packet, evidence inbox, and deterministic readiness report. It lists the
artifact manifest, blocking counts, a prioritized next action, allowed next
stage, and capability flags. It does not create evidence or clear gates. A
`PASS` closeout only means Source QA evidence can move to guarded offline-intake
review; it still cannot approve candidate research, paper trading, live trading,
or broker orders.

```powershell
.\.venv\Scripts\python.exe examples\run_source_qa_closeout.py `
  --data-dir data_exports `
  --report-dir results\first_million `
  --checklist data_exports\data_source_qa.json `
  --worksheet data_exports\data_source_qa_evidence_worksheet.csv `
  --answers data_exports\data_source_qa_answers.json `
  --evidence-manifest data_exports\source_qa_evidence_manifest.json `
  --require-evidence-manifest `
  --as-of 2026-06-10
```

The first-million pipeline also writes `first_million_daily_brief.json/md`.
Use it as the daily operator entrypoint: it rolls up the pipeline decision,
operator handoff batch, source QA closeout, market context readiness,
candidate readiness, and resolution plan into one focused work batch with top
commands. It is not a strategy signal, gate override, evidence generator, or
broker workflow. If the source QA evidence inbox is blocked by target-path or
placeholder worksheet arguments, the daily brief should keep that as missing
evidence and point back to the inbox or source QA collection steps.

The daily brief has a `ranking_status` summary that mirrors
`strategy_discovery_plan.json`. When `can_rank_candidates=false`, the named top
candidate is only a pre-registered research priority. It is not a ranked winner,
paper approval, or capital allocation instruction.

`candidate_experiment_design_matrix.json/md/csv` expands the pre-registered
queue into candidate-by-stress-scenario coverage before results are known. It
lists baseline, concentration, rebalance, turnover/stability, cost-stress, and
trend-filter ablation scenarios with command hints for later guarded research.
It is not evidence, ranking, paper approval, or a broker workflow; all rows keep
`can_enter_paper=false` and `can_generate_broker_orders=false`.

```powershell
.\.venv\Scripts\python.exe examples\write_candidate_experiment_design_matrix.py `
  --config config\research_recent.yaml `
  --output-dir results\first_million `
  --as-of 2026-06-10
```

`first_million_strategy_brief.json/md` includes a `compounding_goal` section.
It ties `candidate_selection.json`, `goal/capital_goal_status.json`, and
`goal/compounding_path_review.json` into one gap list: selected candidate,
required annual return, projected capital, capital shortfall, and unresolved
BLOCK/WATCH findings. This makes the one-million path auditable, but it is still
not a profit claim and cannot upgrade deterministic gates.

```powershell
.\.venv\Scripts\python.exe examples\run_first_million_daily_brief.py `
  --report-dir results\first_million `
  --as-of 2026-06-10
```

The same pipeline writes `strategy_discovery_plan.json/md/csv`, the strategy
search matrix for the first-million objective. It lists every pre-registered
candidate, current readiness stage, allowed stage, first blocker, required
outputs, and next command. While real-data evidence is blocked it only points
back to source QA and export tasks; once a candidate is READY it points to
`run_candidate_experiment_run_packet.py`. The packet wraps guarded launch,
dry-run, explicit execution, stress matrix, completion, and next-experiment
commands. It is not a buy/sell signal, expected return ranking, or paper/live
approval. Formal ranking requires non-BLOCK pipeline evidence, READY candidate
readiness, completed research evidence, and PASS `candidate_selection.json`.

```powershell
.\.venv\Scripts\python.exe examples\run_strategy_discovery_plan.py `
  --report-dir results\first_million `
  --as-of 2026-06-10
```

`first_million_evidence_ranking_dashboard.json/md/csv` is the operator bridge
between real-data evidence and formal ranking. It shows source QA worksheet
readiness, source evidence attachments, raw bars/OHLCV closeout, market context,
candidate readiness, completion review, and the ranking gate in one ordered
chain. It is read-only: it cannot create evidence, rank strategies, approve
paper/live stages, or generate broker instructions.

```powershell
.\.venv\Scripts\python.exe examples\run_first_million_evidence_ranking_dashboard.py `
  --report-dir results\first_million `
  --data-dir data_exports `
  --as-of 2026-06-10
```

## Market Index Discovery

When cache-derived `market_regime.json` is not available yet, use local
reviewed index CSVs only to prepare a temporary
`market_context_snapshot.json`. Run market index discovery before writing the
snapshot:

```powershell
.\.venv\Scripts\python.exe examples\run_market_index_discovery.py `
  --search-dir data_exports\indices `
  --output-dir results\first_million `
  --as-of 2026-06-10
```

Recommended input directory: `data_exports\indices`.

CSV requirements:

- Required columns: `date`, `close`
- Optional long-form identifier columns: `index`, `name`, `symbol`, `code`
- Optional breadth columns: `breadth_above_ma20`, `breadth_above_ma60`

`market_index_discovery.json/md` is read-only discovery. It scans local index
CSV candidates, reports the best file, and emits the next snapshot/readiness
commands. It is not market evidence by itself, does not replace
`market_regime.json`, does not approve any strategy, and does not create broker
instructions.

The guarded market-context command chain is:

```powershell
.\.venv\Scripts\python.exe examples\run_market_index_discovery.py `
  --search-dir data_exports\indices `
  --output-dir results\first_million `
  --as-of 2026-06-10

.\.venv\Scripts\python.exe examples\write_market_context_snapshot.py `
  --output-dir results\first_million `
  --as-of 2026-06-10 `
  --source "<reviewed-index-csv-export>" `
  --reviewed-by "<name>" `
  --reviewed-at 2026-06-10 `
  --index-csv data_exports\indices\indices.csv `
  --encoding auto

.\.venv\Scripts\python.exe examples\run_market_context_readiness.py `
  --report-dir results\first_million `
  --as-of 2026-06-10

.\.venv\Scripts\python.exe examples\run_first_million_pipeline.py `
  --config config\research_recent.yaml `
  --data-dir data_exports `
  --output-dir results\first_million `
  --source-qa-answers data_exports\data_source_qa_answers.json `
  --source-qa-evidence-manifest data_exports\source_qa_evidence_manifest.json `
  --require-source-qa-evidence-manifest `
  --as-of 2026-06-10 `
  --min-symbols 300 `
  --min-trading-days 240
```

Keep the safety boundary explicit: discovery only helps an operator find local,
already-reviewed broad index CSVs for the snapshot workflow. The resulting
snapshot remains advisory `WATCH` context unless a separate cache-derived
`market_regime.json` is available and fresh.

## OHLCV Experiment Package Preflight

`ohlcv_experiment_package.json/md/csv` answers one narrow question: whether the
current recent A-share OHLCV CSV package can launch the first guarded
`price_volume_defensive` research experiment. It reuses CSV preview, source QA,
offline package, real-data handoff, and market-context evidence.

```powershell
.\.venv\Scripts\python.exe examples\run_ohlcv_experiment_package.py `
  --data-dir data_exports `
  --report-dir results\first_million `
  --config config\research_recent.yaml `
  --source-qa-answers data_exports\data_source_qa_answers.json `
  --source-qa-evidence-manifest data_exports\source_qa_evidence_manifest.json `
  --require-source-qa-evidence-manifest `
  --as-of 2026-06-10 `
  --min-symbols 300 `
  --min-trading-days 240
```

Decision meaning:

- `BLOCK`: do not launch candidate research; source QA, bars, market context, or
  the OHLCV minimum path is still missing or invalid.
- `WATCH`: research may be prepared only with the warnings retained in the
  experiment report; paper/live remain forbidden.
- `PASS`: the OHLCV-only package is ready to launch guarded research for
  `price_volume_defensive` after downstream readiness agrees.

This preflight never approves PIT-fundamental candidates, paper trading,
micro-live readiness, broker connectivity, or buy/sell decisions.

## Real Data Batch Onboarding

When a raw broker/vendor daily-bars export arrives or may already exist locally,
run the read-only discovery preflight first:

```powershell
.\.venv\Scripts\python.exe examples\run_raw_bars_discovery.py `
  --search-dir data_exports\raw `
  --config config\research_recent.yaml `
  --output-dir results\first_million `
  --data-output-dir data_exports `
  --write-dropzone-kit `
  --min-symbols 300
```

`raw_bars_discovery.json/md` scans candidate CSVs, reports the best raw bars
candidate, and emits the normalization/onboarding commands. It does not write
`bars.csv`, does not create source QA evidence, and cannot approve research or
broker activity. With `--write-dropzone-kit`, it also writes
`data_exports\raw\README_raw_bars_dropzone.md`, a local operator checklist for
placing retained raw CSVs and source-QA attachments before guarded intake.

Discovery recognizes `.csv` candidates and `.zip` archives, but archives remain
`BLOCK` until the retained daily-bars CSV is extracted by the operator. For raw
broker/vendor CSVs, use `--encoding auto` downstream when the file may be
GBK/GB18030, and keep common Chinese OHLCV headers such as `证券代码`,
`交易日期`, `开盘价`, `最高价`, `最低价`, `收盘价`, `成交量`, and
`成交额`; the normalizer maps them into the local `bars.csv` contract.

To carry the discovered candidate into guarded intake without hand-stitching
commands, run the OHLCV intake closeout:

```powershell
.\.venv\Scripts\python.exe examples\run_ohlcv_intake_closeout.py `
  --data-dir data_exports `
  --report-dir results\first_million `
  --config config\research_recent.yaml `
  --source-qa-answers data_exports\data_source_qa_answers.json `
  --source-qa-evidence-manifest data_exports\source_qa_evidence_manifest.json `
  --require-source-qa-evidence-manifest `
  --as-of 2026-06-10 `
  --min-symbols 300 `
  --min-trading-days 240
```

`ohlcv_intake_closeout.json/md/csv` is source-first: if source QA is `BLOCK`, it
does not normalize raw bars and does not write the research cache. Once source
QA is not blocked and raw discovery has a PASS/WATCH candidate, it calls
guarded offline intake with `raw_bars_discovery.best_candidate`. The report
records raw sha256, normalized row and symbol counts, CSV fingerprint, cache
metadata, bootstrap latest bar, remaining blockers, and next commands. It is
still not a strategy signal, paper promotion, broker workflow, or live-trading
permission.

After a specific raw CSV path is chosen, use
`real_data_batch_onboarding.json/md/csv` as the batch SOP before running
strategy research. It records whether the raw file exists, which normalization
command to run, which source QA rows and evidence attachments remain, whether
market context exists, whether OHLCV preflight is BLOCK/WATCH/PASS, and how to
refresh guarded offline intake.

```powershell
.\.venv\Scripts\python.exe examples\run_real_data_batch_onboarding.py `
  --data-dir data_exports `
  --report-dir results\first_million `
  --config config\research_recent.yaml `
  --raw-bars-csv "<raw-vendor-bars.csv>" `
  --source-qa-answers data_exports\data_source_qa_answers.json `
  --source-qa-evidence-manifest data_exports\source_qa_evidence_manifest.json `
  --require-source-qa-evidence-manifest `
  --as-of 2026-06-10 `
  --min-symbols 300 `
  --min-trading-days 240
```

This report is an operator checklist only. It does not normalize data by
itself, does not create source QA answers, does not approve candidate research,
and cannot override `ohlcv_experiment_package`, candidate readiness, paper, or
human approval gates.

## Local TongDaXin Discovery

If AKShare is blocked and you may have TongDaXin daily `.day` files locally,
run discovery before conversion:

```powershell
.\.venv\Scripts\python.exe examples\run_tdx_day_discovery.py `
  --config config\research_recent.yaml `
  --output-dir results\first_million `
  --data-output-dir data_exports `
  --search-dir "C:\new_tdx\vipdoc" `
  --min-symbols 300
```

Outputs:

- `tdx_day_discovery.json`
- `tdx_day_discovery.md`

Discovery scans local `.day` files, estimates A-share symbol breadth and date
coverage, and writes the next `convert_tdx_day.py` command. It does not prove
license scope, price-adjustment method, ST flags, suspensions, or PIT
fundamentals. Those still require source QA and offline intake.

After a usable root is found, the guarded one-command OHLCV workflow is:

```powershell
.\.venv\Scripts\python.exe examples\run_tdx_ohlcv_intake.py `
  --input-dir "C:\new_tdx\vipdoc" `
  --data-dir data_exports `
  --output-dir results\first_million `
  --config config\research_recent.yaml `
  --source-qa-answers data_exports\data_source_qa_answers.json `
  --as-of 2026-06-08 `
  --min-symbols 300 `
  --min-trading-days 240
```

This writes `tdx_ohlcv_intake.json/md` and stops before guarded cache import by
default. Add `--run-guarded-intake` only after source QA answers are filled with
real evidence and the retained source QA evidence manifest is ready. Promotion
facing runs should also pass `--source-qa-evidence-manifest
data_exports\source_qa_evidence_manifest.json` and
`--require-source-qa-evidence-manifest`; otherwise guarded intake can remain
research-only but cannot satisfy strict provenance gates. A successful TDX OHLCV
intake can still be `WATCH` when fundamentals, suspensions, or full PIT evidence
are missing; that state only supports the OHLCV-only research path.

To fill source QA for this TDX OHLCV path, prefer the TDX-specific answers
writer:

```powershell
.\.venv\Scripts\python.exe examples\write_tdx_source_qa_answers.py `
  --checklist data_exports\data_source_qa.json `
  --output data_exports\data_source_qa_answers.json `
  --tdx-export-report data_exports\tdx_day_export.json `
  --input-dir "C:\new_tdx\vipdoc" `
  --operator "<operator>" `
  --exported-at "2026-06-08 18:00:00" `
  --price-adjustment qfq `
  --price-adjustment-evidence "<real TDX adjustment setting evidence>" `
  --license-evidence "<real license or account-scope evidence>" `
  --reviewed-by "<name>" `
  --reviewed-at "2026-06-08" `
  --write-support-artifacts
```

This command writes `data_source_qa_answers.json` with TDX provenance and an
explicit OHLCV-only PIT note. With `--write-support-artifacts`, it also writes
`data_source_qa_evidence_worksheet.csv`, note-style local evidence attachments,
and `source_qa_evidence_manifest.json` from the evidence fields you supplied.
It does not auto-fill fake evidence and does not promote value or quality
candidates; those still require separate PIT fundamentals and index-constituent
evidence.

After reviewing those files, rerun the TDX workflow with strict guarded intake:

```powershell
.\.venv\Scripts\python.exe examples\run_tdx_ohlcv_intake.py `
  --input-dir "C:\new_tdx\vipdoc" `
  --data-dir data_exports `
  --output-dir results\first_million `
  --config config\research_recent.yaml `
  --source-qa-answers data_exports\data_source_qa_answers.json `
  --source-qa-evidence-manifest data_exports\source_qa_evidence_manifest.json `
  --require-source-qa-evidence-manifest `
  --run-guarded-intake `
  --as-of 2026-06-08 `
  --min-symbols 300 `
  --min-trading-days 240
```

If `source_qa_evidence_manifest.json` is missing, empty, stale, or points at
placeholder/generated files, `guarded_offline_intake` stays `BLOCK` and no
promotion-ready cache should be created.

If you already know the local TDX root, the first-million pipeline can reuse it
for conversion, route selection, and the standalone discovery artifact:

```powershell
.\.venv\Scripts\python.exe examples\run_first_million_pipeline.py `
  --config config\research_recent.yaml `
  --data-dir data_exports `
  --output-dir results\first_million `
  --tdx-input-dir "C:\new_tdx\vipdoc" `
  --tdx-operator "<operator>" `
  --tdx-exported-at "2026-06-08 18:00:00" `
  --tdx-price-adjustment qfq `
  --tdx-price-adjustment-evidence "<real-tdx-adjustment-evidence>" `
  --tdx-license-evidence "<real-license-evidence>" `
  --tdx-reviewed-by "<name>" `
  --tdx-reviewed-at "2026-06-08" `
  --latest-import-report results\import\recent\data_import.json `
  --as-of 2026-06-08 `
  --min-symbols 300 `
  --min-trading-days 240
```

This may make `data_intake_router.json` recommend `tdx_ohlcv`, but it still
does not import a cache, approve a strategy, or grant broker access unless the
later source QA, offline intake, bootstrap, audit, robustness, paper, and human
approval gates pass. Supplying the `--tdx-*` evidence fields writes
`data_source_qa_answers.json` with an OHLCV-only boundary; omitted or placeholder
evidence keeps source QA blocked. Use `--tdx-search-dir` instead when you only
want local TDX discovery without converting files. Do not combine
`--tdx-input-dir` with `--raw-bars-csv`; the pipeline will block ambiguous local
data inputs.

When a converted TDX batch reaches guarded offline intake, the system carries
`tdx_day_export.json` traceability through `data_import.json`, SQLite
`research_metadata`, and `run_manifest.json`. `capital_goal_status.json` then
checks the chain as `tdx_day_traceability`; a missing export report or hash
mismatch blocks strategy search even if the normalized CSV files are readable.
`data_gap_action_plan.json/md` detects the same `tdx_day_export.json` artifact
and emits TDX-specific source QA and first-million pipeline commands.

## Evidence Paths

`ohlcv_minimum_path` is the narrowest path for the first candidate:

- Candidate scope: `price_volume_defensive`
- Required file: `bars.csv`
- Required evidence: filled source QA answers, real non-template OHLCV rows,
  and import doctor with no `BLOCK`
- Raw vendor CSV evidence: when OHLCV comes from `--raw-bars-csv`, the
  normalization report raw fingerprint must be retained in guarded intake,
  `data_import.json`, SQLite `research_metadata`, and the run manifest.
- TDX `.day` evidence: when OHLCV comes from `--tdx-input-dir`,
  `tdx_day_export.json` and its sha256 must be retained in guarded intake,
  `data_import.json`, SQLite `research_metadata`, and the run manifest.
- Recommended files: `stock_info.csv`, `calendar.csv`, `suspensions.csv`

`pit_fundamental_candidate_path` is required before comparing value or quality
candidates:

- Candidate scope: `core_multifactor`, `defensive_low_vol`,
  `trend_filtered_core`, `value_low_vol`, `momentum_quality`
- Required files: `bars.csv`, `fundamentals.csv`
- Required evidence: point-in-time provenance for fields such as `pe_ttm` and
  `roe`
- Recommended files: `stock_info.csv`, `calendar.csv`, `suspensions.csv`,
  `index_constituents.csv`

If the OHLCV path is usable but the PIT path is blocked, keep
fundamental-dependent candidates downgraded. That state is research-only and
still requires offline intake, bootstrap, data audit, robustness, paper
stability, and human approval before any micro-live readiness claim.

## Candidate-Level Readiness

`candidate_experiment_readiness.json` evaluates each queued candidate against
its own evidence path:

- `price_volume_defensive` uses `ohlcv_minimum_path`.
- Value, quality, and core multi-factor candidates use
  `pit_fundamental_candidate_path`.

When the OHLCV path is `PASS` but the PIT path is `BLOCK`, readiness becomes
`WATCH`: the OHLCV-only candidate can be launched as a research experiment, and
fundamental-dependent candidates remain `BLOCKED`. This does not grant paper
promotion, live trading, capital scaling, or broker access. It only prevents
missing fundamentals from unnecessarily blocking the first price-volume research
experiment after the hard data gates pass.

In the full first-million pipeline this state has a deliberately narrow meaning:

- `candidate_experiment_launch.json` may become `PASS` for
  `price_volume_defensive`.
- `candidate_experiment_run_packet.json/md/csv` is the research-only operator
  packet for that candidate. It contains the launch command, launch-plan
  research steps, guarded dry-run, explicit execution, completion review, and
  next-experiment diagnosis. Its capability flags remain false for paper,
  live, micro-live readiness, broker orders, and unattended execution.
- `market_context_readiness.json` must be reviewed before launch. Missing,
  stale, incomplete, or permission-expanding market context is `BLOCK`; a
  reviewed `market_context_snapshot.json` is only advisory `WATCH`; a fresh
  cache-derived `market_regime.json` is the preferred `PASS` evidence.
- `market_index_discovery.json/md` may help locate local reviewed index CSVs
  before writing `market_context_snapshot.json`, but discovery itself is not
  market evidence and cannot relax the market-context gate.
- `market_context_operator_packet.json/md/csv` records the human market-context
  evidence checklist when the cache-derived regime is missing. It names the
  required snapshot metadata, index metrics, acceptable evidence, forbidden weak
  evidence, and commands. It cannot replace `market_regime.json`, approve
  strategy research, or generate broker orders.
- `candidate_experiment_execution.json` is written by the first-million
  pipeline as a dry-run command validation by default. It is `WATCH`, not proof
  that the research experiment ran.
- Passing `--execute-candidate-experiment` to `run_first_million_pipeline.py`
  explicitly opts in to the same guarded research executor used by
  `run_candidate_experiment_execution.py`. The executor still only runs the
  launch plan's whitelisted research/paper scripts and rejects broker/live
  tokens.
- `first_million_pipeline.json` can still remain `BLOCK`, because completion,
  robustness, paper stability, capital-goal evidence, and human approval are not
  done yet.
- `weekly_pipeline` may stay `SKIPPED` while offline intake is only `WATCH`.
- The next allowed action is to run the generated research commands in the
  fixed candidate experiment directory, then complete the required experiment
  artifacts and rerun the deterministic reviews.
- This is not a signal to trade, not paper promotion, and not micro-live
  readiness.

To actually run the generated research work order with logs:

```powershell
.\.venv\Scripts\python.exe examples\run_candidate_experiment_run_packet.py `
  --report-dir results\first_million `
  --config config\research_recent.yaml `
  --as-of 2026-06-08

.\.venv\Scripts\python.exe examples\run_first_million_pipeline.py `
  --config config\research_recent.yaml `
  --data-dir data_exports `
  --output-dir results\first_million `
  --raw-bars-csv "<raw-vendor-bars.csv>" `
  --source-qa-worksheet data_exports\data_source_qa_evidence_worksheet.csv `
  --as-of 2026-06-08 `
  --min-symbols 300 `
  --min-trading-days 240 `
  --execute-candidate-experiment

.\.venv\Scripts\python.exe examples\run_candidate_experiment_execution.py `
  --report-dir results\first_million
```

Use `--dry-run` first if you only want to validate the command whitelist. The
executor writes `candidate_experiment_execution.json/md` and per-step logs under
the selected candidate experiment directory. Either route remains research-only:
execution `PASS` is not profitability evidence, paper promotion, broker access,
or micro-live readiness. In non-dry-run mode, the executor also preflights the
foundational evidence source named by `run_candidate_experiment_evidence.py`.
If `summary.json`, `run_manifest.json`, `real_data_bootstrap.json`,
`real_data_gate.json`, `data_audit.json`, `robustness_report.json`, or
`walk_forward_report.json` is missing, unreadable, demo-only, or BLOCK, the
executor stops before running candidate research commands and writes the
blocker to `candidate_experiment_execution.json`. After execution, rerun:

The launch plan binds candidate-level research commands to the selected
candidate. In an OHLCV-only state, commands such as walk-forward, regime
validation, and candidate selection are generated with
`--candidate price_volume_defensive`, so missing PIT fundamentals do not cause
fundamental-dependent candidates to be run accidentally.

```powershell
.\.venv\Scripts\python.exe examples\run_candidate_experiment_completion.py `
  --report-dir results\first_million `
  --as-of 2026-06-08
```

Completion still requires every output named by the launch plan. A successful
execution only proves that commands ran and logs were captured; it does not
prove the strategy is profitable.

## Optional Micro-Live Readiness Preparation

After the weekly evidence stage is allowed to run, the first-million pipeline
can explicitly prepare manual micro-live readiness materials:

```powershell
.\.venv\Scripts\python.exe examples\run_first_million_pipeline.py `
  --config config\research_recent.yaml `
  --data-dir data_exports `
  --output-dir results\first_million `
  --prepare-micro-live-readiness `
  --micro-live-candidate price_volume_defensive `
  --micro-live-capital 100000 `
  --paper-state-dir results\paper\core
```

The artifacts are written under `results\first_million\weekly`:

- `target_portfolio.json/md/csv`
- `manual_trade_sheet.csv`
- `risk_budget.json`
- `micro_live_readiness.json/md`

This mode does not write `approval_record.json`, does not connect to any broker,
and does not generate executable broker orders. The manual trade sheet is only a
human reference. Without an approval record, `micro_live_readiness` remains
`BLOCK` with `MISSING_APPROVAL`; any later approval must be created and reviewed
as a separate human-controlled record. The opt-in automatically reviews weekly
evidence as `micro_live_ready`, and the manual target planner rejects non-positive
capital or a cash buffer outside `[0, 1)` before any target CSV is written.
