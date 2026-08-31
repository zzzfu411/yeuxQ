# yeuxQ

> Python distribution name remains `quantify`; `yeuxQ` is the canonical
> integrated repository and application name.

> **新手入口:** 想学习量化完整流程,先读 [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) ——
> 它把"研究报告 → 审查门 → 真实数据 → 周度流水线"的学习主线串成了可复制命令。
> 本 README 其余部分是完整的操作 runbook。

## Unified project boundary

`yeuxQ` is the single canonical project that combines the existing
`src/quantify` research core with the reviewed, clean-room `src/yeuxq`
observation/advisory workbench. The local `stock_v2` checkout is a donor only;
it is not a second runtime, release source, or bulk-copied tree. The integration
plan, migration manifest, and machine-readable UI status are maintained in:

- [docs/30_Stock_Integration_Plan.md](docs/30_Stock_Integration_Plan.md)
- [integration/integration_status.json](integration/integration_status.json)
- [integration/index.html](integration/index.html)

The application is research-only and advisory-only. Live observations are
append-only, hash-chained and physically separate from canonical research
storage. They cannot upgrade a `PASS/WATCH/BLOCK` research gate; there is no
broker, account, order, cancel, or automatic trading endpoint.

The current status is `6/7 · 86%`: Phase 5 hardening is complete and the Phase 6
release rehearsal is active. Public release remains `BLOCK` until donor
redistribution rights, the two donor-local credential rotations, and a
project-wide `LICENSE` are resolved by the repository owner.

## Real Data Handoff Checklist

### AKShare Smoke Evidence

Before a broad provider import, run a tiny AKShare network smoke into an
isolated cache. If it is `BLOCK`, pass that report into downstream readiness so
the network/proxy failure stays explicit while the real recent cache remains
unpromoted:

```powershell
.\.venv\Scripts\python.exe examples\import_research_data.py --config config\research_recent.yaml --cache tmp\akshare_smoke.db --symbols 600519,000001 --limit 2 --output-dir results\import\smoke_akshare
.\.venv\Scripts\python.exe examples\run_provider_smoke_readiness.py --config config\research_recent.yaml --latest-import-report results\import\smoke_akshare\data_import.json --output-dir results\first_million --as-of 2026-06-12 --min-symbols 300 --min-trading-days 240
.\.venv\Scripts\python.exe examples\run_first_million_pipeline.py --config config\research_recent.yaml --data-dir data_exports --output-dir results\first_million --source-qa-answers data_exports\data_source_qa_answers.json --latest-import-report results\import\smoke_akshare\data_import.json --provider-acquisition-ramp-report results\import\provider_acquisition_ramp\provider_acquisition_ramp.json --as-of 2026-06-09 --min-symbols 300 --min-trading-days 240 --no-registry
```

`provider_smoke_readiness.json/md` is a route-diagnostics card. A small AKShare
smoke `PASS` only proves the endpoint worked for that sample; it cannot approve
source QA, make the recent cache research-ready, launch candidate experiments,
or create broker/live-order permission. The first-million pipeline writes this
card automatically from `--latest-import-report` and keeps it advisory while the
deterministic data gates decide `PASS/WATCH/BLOCK`.

Before scaling from a tiny AKShare smoke to a larger provider batch, use the
research-only staged acquisition ramp. By default it writes to an isolated
`tmp/provider_acquisition_ramp.db` cache rather than the configured research
cache:

```powershell
.\.venv\Scripts\python.exe examples\run_provider_acquisition_ramp.py --config config\research_recent.yaml --stage-sizes 2,20,100,300 --output-dir results\import\provider_acquisition_ramp
```

`provider_acquisition_ramp.json/md` records each stage and stops on the first
`BLOCK`. A ramp `PASS` is only bounded provider-acquisition evidence; it is not
source QA/provenance `PASS`, does not affect promotion gates, and must not be
connected to paper/live trading or broker orders.
Pass the JSON to the first-million pipeline with
`--provider-acquisition-ramp-report results\import\provider_acquisition_ramp\provider_acquisition_ramp.json`
when you want readiness and goal status to show these route diagnostics. It
cannot upgrade source QA, offline intake, promotion, candidate, or trading
gates.

If the AKShare all-A spot-list endpoint is blocked but per-symbol daily bars are
reachable, use an explicit reviewed symbol file and an isolated cache:

```powershell
.\.venv\Scripts\python.exe examples\import_research_data.py --config config\research_recent.yaml --cache tmp\akshare_recent_explicit_50.db --symbols-file config\akshare_explicit_50_symbols.txt --limit 50 --output-dir results\import\akshare_recent_explicit_50
.\.venv\Scripts\python.exe examples\run_real_data_bootstrap.py --config config\research_recent.yaml --cache tmp\akshare_recent_explicit_50.db --output-dir results\import\akshare_recent_explicit_50_bootstrap --as-of 2026-06-10 --min-symbols 50 --min-trading-days 240
.\.venv\Scripts\python.exe examples\run_data_audit.py --config config\research_recent.yaml --cache tmp\akshare_recent_explicit_50.db --output-dir results\import\akshare_recent_explicit_50_audit
.\.venv\Scripts\python.exe examples\run_market_regime.py --config config\research_recent.yaml --cache tmp\akshare_recent_explicit_50.db --output-dir results\import\akshare_recent_explicit_50_regime
```

This path proves batch daily-bar viability for the listed symbols only. It is
not a broad A-share universe, not source QA, and not enough to claim a stable
compounding strategy.

When recent A-share data is blocked by network access or missing local evidence,
generate the handoff checklist before running strategy experiments:

```powershell
.\.venv\Scripts\python.exe examples\run_real_data_handoff.py --data-dir data_exports --config config\research_recent.yaml --output-dir results\first_million --source-qa-answers data_exports\data_source_qa_answers.json --as-of 2026-06-08 --min-symbols 300 --min-trading-days 240
```

Outputs: `real_data_handoff_checklist.json` and `real_data_handoff_checklist.md`.
The checklist separates the OHLCV-only path for `price_volume_defensive` from
the PIT-fundamental path for value/quality candidates. It is not a profit claim,
broker order workflow, or override for deterministic gates and human approval.

To answer the narrower question "can the current OHLCV CSV package launch the
first guarded research experiment?", run:

```powershell
.\.venv\Scripts\python.exe examples\run_ohlcv_experiment_package.py --data-dir data_exports --report-dir results\first_million --config config\research_recent.yaml --source-qa-answers data_exports\data_source_qa_answers.json --source-qa-evidence-manifest data_exports\source_qa_evidence_manifest.json --require-source-qa-evidence-manifest --as-of 2026-06-10 --min-symbols 300 --min-trading-days 240
```

Outputs: `ohlcv_experiment_package.json`, `ohlcv_experiment_package.md`, and
`ohlcv_experiment_package.csv`. A `PASS` or `WATCH` here only opens the
`price_volume_defensive` OHLCV-only research path after guarded intake and
candidate readiness agree. It does not approve paper trading, live trading,
PIT-fundamental candidates, broker orders, or any buy/sell decision.

When you receive or locate a real raw broker/vendor daily-bars export, first run
the read-only discovery preflight. It scans candidate CSVs, estimates whether
they can become `bars.csv`, and writes the exact normalization command without
overwriting the current data contract:

```powershell
.\.venv\Scripts\python.exe examples\run_raw_bars_discovery.py --search-dir data_exports\raw --config config\research_recent.yaml --output-dir results\first_million --data-output-dir data_exports --write-dropzone-kit --min-symbols 300
```

Outputs: `raw_bars_discovery.json`, `raw_bars_discovery.md`, and
`data_exports\raw\README_raw_bars_dropzone.md`. Discovery is not source QA,
license evidence, strategy approval, or a broker workflow. The dropzone README
only tells a human operator where to place retained raw CSVs, which evidence
files to attach, and which guarded commands to rerun; it does not create
`bars.csv` or source QA answers.

To close discovery into guarded intake, run the source-first OHLCV closeout:

```powershell
.\.venv\Scripts\python.exe examples\run_ohlcv_intake_closeout.py --data-dir data_exports --report-dir results\first_million --config config\research_recent.yaml --source-qa-answers data_exports\data_source_qa_answers.json --source-qa-evidence-manifest data_exports\source_qa_evidence_manifest.json --require-source-qa-evidence-manifest --as-of 2026-06-08 --min-symbols 300 --min-trading-days 240
```

Outputs: `ohlcv_intake_closeout.json`, `ohlcv_intake_closeout.md`, and
`ohlcv_intake_closeout.csv`. Closeout refuses to normalize raw OHLCV while
source QA is `BLOCK`, then passes `raw_bars_discovery.best_candidate` into
guarded offline intake when source QA and raw discovery allow it. The report
records raw sha256, normalized rows, CSV fingerprint, cache metadata, bootstrap
latest bar, blockers, and next commands. It still cannot approve strategy
research, paper promotion, broker orders, or live trading.

After a specific raw CSV is chosen, build the batch onboarding plan before
launching research:

```powershell
.\.venv\Scripts\python.exe examples\run_real_data_batch_onboarding.py --data-dir data_exports --report-dir results\first_million --config config\research_recent.yaml --raw-bars-csv "<raw-vendor-bars.csv>" --source-qa-answers data_exports\data_source_qa_answers.json --source-qa-evidence-manifest data_exports\source_qa_evidence_manifest.json --require-source-qa-evidence-manifest --as-of 2026-06-10 --min-symbols 300 --min-trading-days 240
```

Outputs: `real_data_batch_onboarding.json`, `real_data_batch_onboarding.md`,
and `real_data_batch_onboarding.csv`. This is the operator SOP for raw file
retention, normalization, source QA, market context, OHLCV preflight, guarded
offline intake, and pipeline refresh. It cannot create evidence or upgrade any
deterministic gate.

For local TongDaXin `.day` data, fill source QA with the TDX-specific helper
after conversion:

```powershell
.\.venv\Scripts\python.exe examples\write_tdx_source_qa_answers.py --checklist data_exports\data_source_qa.json --output data_exports\data_source_qa_answers.json --tdx-export-report data_exports\tdx_day_export.json --input-dir "<tdx-vipdoc-or-lday-dir>" --operator "<operator>" --exported-at "2026-06-08 18:00:00" --price-adjustment qfq --price-adjustment-evidence "<real-tdx-adjustment-evidence>" --license-evidence "<real-license-evidence>" --reviewed-by "<name>" --reviewed-at "2026-06-08" --write-support-artifacts
.\.venv\Scripts\python.exe examples\run_tdx_ohlcv_intake.py --input-dir "<tdx-vipdoc-or-lday-dir>" --data-dir data_exports --output-dir results\first_million --config config\research_recent.yaml --source-qa-answers data_exports\data_source_qa_answers.json --source-qa-evidence-manifest data_exports\source_qa_evidence_manifest.json --require-source-qa-evidence-manifest --run-guarded-intake --as-of 2026-06-08 --min-symbols 300 --min-trading-days 240
```

This records TDX as OHLCV-only evidence unless separate PIT fundamentals are
supplied, so value/quality candidates stay blocked until their data exists. The
strict manifest flag makes retained source QA attachment hashes mandatory for
promotion-facing caches; missing or stale manifest evidence blocks guarded
intake instead of silently degrading provenance.

The one-command first-million pipeline can also route against a known local TDX
directory:

```powershell
.\.venv\Scripts\python.exe examples\run_first_million_pipeline.py --config config\research_recent.yaml --data-dir data_exports --output-dir results\first_million --tdx-input-dir "<tdx-vipdoc-or-lday-dir>" --tdx-operator "<operator>" --tdx-exported-at "2026-06-08 18:00:00" --tdx-price-adjustment qfq --tdx-price-adjustment-evidence "<real-tdx-adjustment-evidence>" --tdx-license-evidence "<real-license-evidence>" --tdx-reviewed-by "<name>" --tdx-reviewed-at "2026-06-08" --latest-import-report results\import\recent\data_import.json --as-of 2026-06-08 --min-symbols 300 --min-trading-days 240
```

`--tdx-input-dir` converts local `.day` files into the offline CSV contract and
writes `tdx_day_export.json/md` under `data_exports`. When the `--tdx-*`
evidence fields are supplied, it also writes reviewable TDX OHLCV-only
`data_source_qa_answers.json`. Use `--tdx-search-dir` when you only want
discovery and route selection without conversion. These modes still cannot
bypass guarded offline intake, deterministic gates, or the no-broker/no-live-order
boundary. Do not combine `--tdx-input-dir` with `--raw-bars-csv`; the pipeline
blocks ambiguous local data inputs.

When guarded offline intake imports a converted TDX batch, it preserves
`tdx_day_export.json` traceability in `data_import.json`, SQLite
`research_metadata`, and `run_manifest.json`. The capital-goal status report
checks this as `tdx_day_traceability`; a missing or mismatched export report
keeps strategy search gated.
Every promotion-facing cache must include source QA, retained evidence hashes,
an atomic import batch, complete bar lineage, and a verified logical-bars
fingerprint. CSV routes additionally require `csv_dataset_fingerprint` and
`data_source_csv_qa_status=PASS`; API/provider routes must not fabricate a CSV
fingerprint. `import_research_csv.py --validate` can write the CSV fingerprint,
but first-million readiness still requires guarded intake or an equivalent
source-QA-provenance chain before strategy experiments can launch. See
[Promotion Metadata Gate](docs/13_Promotion_Metadata_Gate.md) and
[Cache Provenance Attestation v1](docs/14_Cache_Provenance_Attestation.md).
Candidate goal research also executes with the goal's actual starting capital,
records below-lot rejections, and runs mandatory CNY 100,000 cost scenarios. See
[Small-Capital Execution Contract](docs/15_Small_Capital_Execution_Contract.md).
Walk-forward v2 now locks candidates before each test window and validates the
complete train/purge/selection/embargo/test envelope. Legacy or bare-boolean
reports fail closed. Robustness v2 freezes the standard stress matrix before
evaluation, runs every scenario on every isolated test fold, requires at least
three complete folds for `PASS`, and rejects incomplete scenario matrices. See
[Selection-Safe Walk-Forward v2](docs/16_Selection_Safe_Walk_Forward.md).
New research trials can be preregistered in a hash-chained, append-only ledger;
there is no edit, delete, or retroactive backfill command. Frozen trial-return
matrices can then produce DSR and CSCV/PBO diagnostics whose output is advisory
and can never upgrade a deterministic gate. See
[Research Trial Registry](docs/17_Research_Trial_Registry.md) and
[Multiple-Testing Diagnostics](docs/18_Multiple_Testing_Diagnostics.md). A
formal benchmark review requires a retained, human-reviewed total-return series
whose file hash and identity match the configured index. See
[Benchmark Review](docs/19_Benchmark_Review.md).
To inspect this layer directly without mutating the cache, run:

```powershell
.\.venv\Scripts\python.exe examples\check_promotion_metadata.py --config config\research_recent.yaml --output-dir results\import\promotion_metadata
```

To preregister a genuinely new holdout experiment and later review a frozen
trial-return matrix, run:

```powershell
.\.venv\Scripts\python.exe examples\run_trial_registry.py preregister --registry results\research\trial_registry.jsonl --payload trial-preregistration.json
.\.venv\Scripts\python.exe examples\run_multiple_testing_review.py --input-csv results\research\frozen_trial_returns.csv --output-dir results\research\<timestamp> --selected-candidate <candidate> --periods-per-year 252 --partition-count 8
.\.venv\Scripts\python.exe examples\run_benchmark_review.py --strategy-equity-csv results\research\<timestamp>\equity.csv --benchmark-csv evidence\csi800_total_return.csv --benchmark-metadata evidence\csi800_total_return.metadata.json --output-dir results\research\<timestamp>
.\.venv\Scripts\python.exe examples\run_trial_registry.py record-result --registry results\research\trial_registry.jsonl --payload trial-result.json
.\.venv\Scripts\python.exe examples\run_trial_registry.py verify --registry results\research\trial_registry.jsonl
.\.venv\Scripts\python.exe examples\run_trial_registry_review.py --registry results\research\trial_registry.jsonl --report-dir results\research\<timestamp>
```

Do not use these commands to relabel the repeatedly inspected data through
2026-07-14 as an independent holdout. A preregistration written after results
already exist is not prospective evidence.

The first-million pipeline now writes the same `promotion_metadata_check.json/md`
under `results\first_million` after guarded offline intake.
It also writes `ohlcv_intake_closeout.json/md/csv` as the auditable bridge from
`raw_bars_discovery.best_candidate` to guarded offline intake, preserving
source-first behavior and raw vendor hash traceability.

`data_gap_action_plan.json/md` also detects `tdx_day_export.json` and switches
its next commands to the TDX-specific source QA and first-million pipeline path.

Before running a candidate experiment, write the research-only run packet. The
packet emits `candidate_experiment_run_packet.json/md/csv` with launch, guarded
dry-run, explicit execution, stress matrix, completion, and next-experiment
commands. It does not execute commands, approve paper/live trading, or generate
broker orders.

```powershell
.\.venv\Scripts\python.exe examples\run_candidate_experiment_run_packet.py --report-dir results\first_million --config config\research_recent.yaml --as-of 2026-06-08
.\.venv\Scripts\python.exe examples\run_first_million_pipeline.py --config config\research_recent.yaml --data-dir data_exports --output-dir results\first_million --raw-bars-csv "<raw-vendor-bars.csv>" --source-qa-worksheet data_exports\data_source_qa_evidence_worksheet.csv --as-of 2026-06-08 --min-symbols 300 --min-trading-days 240 --execute-candidate-experiment
.\.venv\Scripts\python.exe examples\run_candidate_experiment_execution.py --report-dir results\first_million
.\.venv\Scripts\python.exe examples\run_candidate_experiment_completion.py --report-dir results\first_million --as-of 2026-06-08
```

Without `--execute-candidate-experiment`, `run_first_million_pipeline.py` only
writes a dry-run command validation. With the flag, it calls the same guarded
executor that only accepts whitelisted research/paper scripts from the launch
plan. This captures experiment logs and checks required outputs. It is still
research-only, not a profitability claim, paper promotion, broker workflow, or
live trading permission.

For the long-running first-million objective, work is coordinated through a
small agent team with explicit gates for data, strategy experiments, and risk
control. See [docs/12_Agent_Team_Execution.md](docs/12_Agent_Team_Execution.md).

面向 A 股的教学型量化研究与仿真系统。项目现在包含三条路径:

- 新手路径: 从 0 开始理解股票、回测、因子、本地 SQLite 缓存,并跑出第一份多因子研究报告。
- 工程路径: 保留原有事件驱动单股回测,新增低换手多因子研究、纸面交易、风控和文件化报告。
- 实盘准备路径: 用量化实盘心智模型和 LLM-ready 审查门,把策略升级限制在可解释、可复盘、可停止的流程里。

> 风险提示: 历史回测不代表未来收益。本项目帮助你学习和验证策略,不能保证赚钱。

## 5 分钟跑通

### 1. 安装依赖

```powershell
uv sync
```

### 2. 跑多因子研究

```powershell
uv run python examples/run_research.py --config config/research.yaml
```

如果本地没有真实缓存数据,系统会自动生成一份确定性的 demo 数据,让你先学会完整流程。报告会写在:

```text
results/research/<timestamp>/
```

重点查看:

- `summary.json`: 收益、回撤、夏普、胜率等核心指标
- `equity.csv`: 每日净值
- `positions.csv`: 每日持仓
- `orders.csv`: 订单与拒单原因
- `trades.csv`: 成交明细
- `factor_ic.csv`: 因子 RankIC
- `drawdown.png`: 净值与回撤图
- `html_report.html`: 可用浏览器打开的报告

如果要做真实 A 股研究,先导入真实缓存:

```powershell
uv run python examples/import_research_data.py --config config/research.yaml --limit 300 --output-dir results/import/latest
```

如果目标是最近大 A 验证,使用隔离的近期配置,不要用旧教学缓存:

```powershell
uv run python examples/run_recent_data_plan.py --config config/research_recent.yaml --output-dir results/bootstrap_recent --as-of 2026-06-08
uv run python examples/import_research_data.py --config config/research_recent.yaml --limit 500 --output-dir results/import/recent
uv run python examples/run_real_data_bootstrap.py --config config/research_recent.yaml --output-dir results/bootstrap_recent --min-symbols 300 --as-of 2026-06-08
```

每周开局可以先跑一百万目标状态预检; 如果 `data_cache` 是 BLOCK,先补近期真实数据,不要继续做策略晋级:

```powershell
uv run python examples/run_goal_status.py --report-dir results/goal --config config/research_recent.yaml --source-qa-dir results\import\source_qa --import-doctor-dir results\import\doctor --offline-intake-dir results\import\offline_intake --as-of 2026-06-08 --starting-capital 100000 --target-capital 1000000 --years 8 --min-symbols 300 --min-trading-days 240
```

如果网络行情接口不可用,先走离线 CSV 合同:

```powershell
uv run python examples/write_data_export_request.py --config config/research_recent.yaml --output-dir data_exports --min-symbols 300
uv run python examples/write_candidate_hypotheses.py --config config/research_recent.yaml --output-dir results\first_million --as-of 2026-06-08
uv run python examples/write_candidate_experiment_queue.py --config config/research_recent.yaml --output-dir results\first_million --as-of 2026-06-08
uv run python examples/write_candidate_experiment_design_matrix.py --config config/research_recent.yaml --output-dir results\first_million --as-of 2026-06-08
uv run python examples/run_data_gap_action_plan.py --data-dir data_exports --config config/research_recent.yaml --output-dir results\first_million --min-symbols 300 --as-of 2026-06-08
uv run python examples/write_data_source_qa.py --config config/research_recent.yaml --output-dir data_exports --min-symbols 300 --as-of 2026-06-08
uv run python examples/write_data_evidence_action_packet.py --data-dir data_exports --config config/research_recent.yaml --output-dir results\first_million --min-symbols 300 --as-of 2026-06-08
uv run python examples/write_data_source_qa_evidence_worksheet.py --checklist data_exports\data_source_qa.json --output-dir data_exports
uv run python examples/fill_data_source_qa_evidence_worksheet.py --checklist data_exports\data_source_qa.json --worksheet data_exports\data_source_qa_evidence_worksheet.csv --vendor "<vendor-or-broker>" --terminal "<terminal-name>" --operator "<operator>" --exported-at "<local-time>" --price-adjustment qfq --license-scope "research and paper trading only" --reviewed-by "<name>" --reviewed-at "<YYYY-MM-DD>" --source-identity-evidence "<retained-source-identity-evidence>" --license-evidence "<retained-license-evidence>" --price-adjustment-evidence "<retained-price-adjustment-evidence>" --point-in-time-evidence "<retained-PIT-evidence-or-OHLCV-only-note>" --manual-signoff-evidence "<retained-human-review-evidence>"
uv run python examples/run_data_source_qa_worksheet_preflight.py --checklist data_exports\data_source_qa.json --worksheet data_exports\data_source_qa_evidence_worksheet.csv --output-dir data_exports
uv run python examples/write_source_qa_evidence_manifest.py --checklist data_exports\data_source_qa.json --evidence-dir data_exports\source_qa_evidence --output-dir data_exports --strict
uv run python examples/write_data_source_qa_answers.py --checklist data_exports\data_source_qa.json --worksheet data_exports\data_source_qa_evidence_worksheet.csv --output data_exports\data_source_qa_answers.json --evidence-manifest data_exports\source_qa_evidence_manifest.json --require-evidence-manifest
uv run python examples/run_data_source_qa_review.py --checklist data_exports\data_source_qa.json --answers data_exports\data_source_qa_answers.json --evidence-manifest data_exports\source_qa_evidence_manifest.json --require-evidence-manifest --output-dir results\import\source_qa
uv run python examples/write_data_export_templates.py --output-dir data_exports
uv run python examples/normalize_vendor_bars.py --input "<raw-vendor-bars.csv>" --output-dir data_exports --start 2024-06-03 --end 2026-06-05 --min-symbols 300
uv run python examples/convert_tdx_day.py --input-dir "<tdx-vipdoc-or-lday-dir>" --output-dir data_exports --start 2024-06-03 --end 2026-06-05
uv run python examples/run_data_import_doctor.py --data-dir data_exports --config config/research_recent.yaml --output-dir results\import\doctor
uv run python examples/run_offline_data_package.py --data-dir data_exports --config config/research_recent.yaml --output-dir results\first_million --source-qa-answers data_exports\data_source_qa_answers.json --source-qa-evidence-manifest data_exports\source_qa_evidence_manifest.json --require-source-qa-evidence-manifest --as-of 2026-06-08 --min-symbols 300
uv run python examples/run_offline_data_intake.py --raw-bars-csv "<raw-vendor-bars.csv>" --data-dir data_exports --config config/research_recent.yaml --output-dir results\import\offline_intake --source-qa-answers data_exports\data_source_qa_answers.json --source-vendor "<vendor-or-broker>" --source-terminal "<terminal-name>" --source-operator "<operator>" --source-exported-at "<local-time>" --source-price-adjustment qfq --source-price-adjustment-evidence "<evidence>" --source-license-evidence "<evidence>" --source-point-in-time-evidence "<evidence-or-non-pit-note>" --source-reviewed-by "<name>" --source-reviewed-at "<date>" --as-of 2026-06-08 --min-symbols 300 --min-trading-days 240
uv run python examples/run_first_million_pipeline.py --config config/research_recent.yaml --data-dir data_exports --output-dir results\first_million --raw-bars-csv "<raw-vendor-bars.csv>" --source-vendor "<vendor-or-broker>" --source-terminal "<terminal-name>" --source-operator "<operator>" --source-exported-at "<local-time>" --source-price-adjustment qfq --source-price-adjustment-evidence "<evidence>" --source-license-evidence "<evidence>" --source-point-in-time-evidence "<evidence-or-non-pit-note>" --source-reviewed-by "<name>" --source-reviewed-at "<date>" --as-of 2026-06-08 --min-symbols 300 --min-trading-days 240
uv run python examples/run_first_million_pipeline.py --config config/research_recent.yaml --data-dir data_exports --output-dir results\first_million --source-qa-worksheet data_exports\data_source_qa_evidence_worksheet.csv --as-of 2026-06-08 --min-symbols 300 --min-trading-days 240
uv run python examples/run_first_million_pipeline.py --config config/research_recent.yaml --data-dir data_exports --output-dir results\first_million --raw-bars-csv "<raw-vendor-bars.csv>" --source-qa-worksheet data_exports\data_source_qa_evidence_worksheet.csv --as-of 2026-06-08 --min-symbols 300 --min-trading-days 240
uv run python examples/run_first_million_pipeline.py --config config/research_recent.yaml --data-dir data_exports --output-dir results\first_million --raw-bars-csv "<raw-vendor-bars.csv>" --source-qa-worksheet data_exports\data_source_qa_evidence_worksheet.csv --as-of 2026-06-08 --min-symbols 300 --min-trading-days 240 --execute-candidate-experiment
uv run python examples/run_candidate_experiment_run_packet.py --report-dir results\first_million --config config/research_recent.yaml --as-of 2026-06-08
uv run python examples/run_candidate_experiment_launch.py --report-dir results\first_million --config config/research_recent.yaml --as-of 2026-06-08
uv run python examples/run_candidate_experiment_execution.py --report-dir results\first_million --dry-run
uv run python examples/run_candidate_experiment_completion.py --report-dir results\first_million --as-of 2026-06-08
uv run python examples/run_first_million_readiness.py --report-dir results\first_million --as-of 2026-06-08
uv run python examples/validate_research_csv.py --bars-csv data_exports\bars.csv --stock-info-csv data_exports\stock_info.csv --fundamentals-csv data_exports\fundamentals.csv --calendar-csv data_exports\calendar.csv --suspensions-csv data_exports\suspensions.csv --index-constituents-csv data_exports\index_constituents.csv --start 2024-06-03 --end 2026-06-05 --min-symbols 300 --output-dir results\import\recent_csv_validation
uv run python examples/import_research_csv.py --cache .\data_cache\research_recent.db --bars-csv data_exports\bars.csv --stock-info-csv data_exports\stock_info.csv --fundamentals-csv data_exports\fundamentals.csv --calendar-csv data_exports\calendar.csv --suspensions-csv data_exports\suspensions.csv --index-constituents-csv data_exports\index_constituents.csv --validate --start 2024-06-03 --end 2026-06-05 --min-symbols 300 --output-dir results\import\recent_csv
```

For broker/vendor CSV exports with Chinese headers, prefer `--encoding auto`
on the normalization/intake/pipeline commands. The normalizer accepts common
aliases such as `code`/`symbol`, `代码`, `证券代码`, `股票代码`,
`date`/`trade_date`, `日期`, `交易日期`, `开盘`, `开盘价`, `最高`,
`最高价`, `最低`, `最低价`, `收盘`, `收盘价`, `成交量`,
`成交量(股)`, `成交量(手)`, `成交额`, `成交金额`, `成交额(元)`,
and `成交金额(元)`.

`data_evidence_action_packet.json/md` is the shortest current work order when
the first-million pipeline is blocked by missing recent A-share evidence. It
summarizes current data blockers, required CSV exports, source QA fields,
source evidence questions, operator checklist items, immediate commands, and
completion criteria. It is research-only and cannot turn any deterministic
`BLOCK` into `PASS`.
The first-million readiness card now treats this packet as its own gate, and
the strategy brief surfaces its first next action before any candidate research
instruction. This keeps the operator focused on evidence collection while the
system is still blocked by data.
`capital_goal_status.json/md` also reads the packet when present, so the
one-million compounding dashboard closes strategy search and points first to
`data_evidence_action_packet.md` while source data evidence remains `BLOCK`.
The packet writer also creates operator-facing todo files:
`source_qa_worksheet_todo.csv/md`, `source_qa_attachment_todo.csv/md`,
`source_qa_evidence_attachment_plan.csv/md`, `data_export_todo.csv/md`, and
`operator_handoff.csv/md`. The attachment plan points to suggested local files
under `data_exports\source_qa_evidence` and records weak-evidence warnings; it
does not create or approve evidence. The handoff is a unified queue combining
row-level source QA gaps, attachment tasks, file-level CSV export actions, next
commands, completion criteria, and a fixed gate note. It is only an execution
aid; deterministic source QA, import, audit, readiness gates, and human approval
still decide stage access.
It also writes `operator_handoff_status.json/md`, a progress view with open
P0/P1 task counts and the first remaining actions. You can refresh it directly:

```powershell
uv run python examples/run_operator_handoff_status.py --data-dir data_exports --config config/research_recent.yaml --output-dir results\first_million --source-qa-answers data_exports\data_source_qa_answers.json --min-symbols 300 --as-of 2026-06-08
```

This status report never replaces the deterministic data gates.

The pipeline also writes an evidence intake kit under
`results\first_million\evidence_intake_kit`. It combines required source QA
attachments, real data export CSVs, and reviewed broad-index CSV requests into
one staging manifest:

```powershell
uv run python examples/run_first_million_evidence_intake_kit.py --report-dir results\first_million --data-dir data_exports --as-of 2026-06-10
```

The kit creates only `README.md`, `first_million_evidence_intake_kit.json/md`,
`first_million_evidence_intake_manifest.csv`, and empty staging directories.
It does not create screenshots, PDFs, CSV market rows, source QA answers, or
approval notes. Operators must copy real retained files into the target paths
and rerun deterministic source QA, discovery, intake, and pipeline commands.

If files were first placed in the `incoming_*` staging directories, review them
before copying:

```powershell
uv run python examples/run_first_million_evidence_intake_receiver.py --manifest results\first_million\evidence_intake_kit\first_million_evidence_intake_manifest.csv --data-dir data_exports --report-dir results\first_million --as-of 2026-06-10
```

Add `--apply` only after the receipt says the staged files would be accepted.
The receiver rejects empty, README, template, sample, generated, placeholder,
and non-normalizable files; it still does not replace source QA, raw bars
discovery, market context readiness, or pipeline gates.

For the daily execution order, generate the evidence work order:

```powershell
uv run python examples/run_first_million_evidence_work_order.py --report-dir results\first_million --data-dir data_exports --as-of 2026-06-10
```

It writes `first_million_evidence_work_order.json/md/csv`, grouping the intake
work into ordered batches: source QA worksheet, source QA attachments, real
`bars.csv`, recommended audit CSVs, broad-index CSV, and deterministic reruns.
It is only a batch view over existing blockers and cannot close tasks without
changed evidence.

The guarded first-million pipeline also writes
`first_million_resolution_plan.json/md/csv`. This is the long-running BLOCK
resolution queue: P0 rows point to source QA worksheet cells, required evidence
attachments, and CSV exports that must be replaced with real A-share data; P1
rows summarize deterministic data/source gates; P2 rows keep downstream
candidate, paper, and capital-goal work waiting until upstream evidence passes.
Refresh it without rerunning the whole pipeline:

```powershell
uv run python examples/run_first_million_resolution_plan.py --report-dir results\first_million --as-of 2026-06-10
```

This plan is only an execution queue. It cannot upgrade PASS/WATCH/BLOCK,
cannot close tasks without changed evidence, and cannot authorize broker orders
or live trading.

The pipeline also writes `first_million_daily_brief.json/md`, a compact daily
operator entrypoint over the pipeline, operator handoff, source QA readiness,
market context, candidate readiness, and resolution plan. It chooses the next
human work batch and top verification commands, but it is still only a brief:
it cannot approve a strategy, change deterministic gates, generate evidence, or
authorize broker orders. When it reports the source QA evidence inbox, it is
only reflecting the inbox artifact: source evidence worksheet arguments are
ready only when every source evidence argument comes from a real matched or
suggested local evidence file, not from a target path or placeholder. Refresh it
without rerunning the whole pipeline:

The daily brief also mirrors the strategy discovery ranking gate in a
`ranking_status` section. `can_rank_candidates=false` means any displayed top
candidate is still a pre-registered research priority, not a deterministic
ranking or paper-trading permission.

```powershell
uv run python examples/run_first_million_daily_brief.py --report-dir results\first_million --as-of 2026-06-10
```

`strategy_discovery_plan.json/md/csv` is the companion strategy-search matrix.
It shows each pre-registered candidate, current readiness stage, allowed stage,
first blocker, required outputs, and next command. When data is still blocked it
only points back to source QA and real-data collection; when a candidate is
READY it points to `run_candidate_experiment_run_packet.py`, which wraps the
guarded launch, dry-run, explicit execution, stress matrix, completion, and
next-experiment commands. It is not a buy/sell signal or expected-return
ranking. Formal ranking stays disabled until the pipeline, candidate readiness,
completion review, and `candidate_selection.json` all provide deterministic
PASS evidence.

```powershell
uv run python examples/run_strategy_discovery_plan.py --report-dir results\first_million --as-of 2026-06-10
```

`first_million_evidence_ranking_dashboard.json/md/csv` links the same evidence
chain from source QA and raw bars through market context, candidate readiness,
completion review, and the strategy ranking gate. Use it to see which upstream
artifact currently blocks formal candidate ranking. It is read-only and cannot
rank candidates, approve paper trading, or create broker instructions.

```powershell
uv run python examples/run_first_million_evidence_ranking_dashboard.py --report-dir results\first_million --data-dir data_exports --as-of 2026-06-10
```

`source_qa_operator_packet.json/md/csv` is the handoff packet for the human data
operator. It merges worksheet rows and required attachment evidence into one
fillable checklist with acceptable evidence, forbidden weak evidence, and the
command sequence to run after filling. The first command is a
`fill_data_source_qa_evidence_worksheet.py` template with placeholders that must
be replaced by retained real vendor/export evidence. It does not create answers
or evidence. With `--write-dropzone-kit`, it also writes
`data_exports\source_qa_evidence\README_source_qa_evidence_dropzone.md`, a
local checklist for the real source evidence files that must be attached before
strict source QA can pass.

```powershell
uv run python examples/run_source_qa_operator_packet.py --data-dir data_exports --report-dir results\first_million --as-of 2026-06-10 --write-dropzone-kit
```

`source_qa_evidence_inbox.json/md/csv` scans `data_exports\source_qa_evidence`
and maps retained local files to required Source QA attachment ids. It is
read-only: it can flag missing, unmatched, generated, or placeholder-like files,
and it emits a `worksheet_fill_command` for
`fill_data_source_qa_evidence_worksheet.py`. Source evidence arguments in that
command are ready only when each value comes from an existing matched or
suggested local evidence file. Any `target_path` value from the attachment plan,
and any angle-bracket placeholder value, is a human placeholder that must remain
not ready until a real file is present in the inbox and matched or suggested. A
human still has to replace vendor, terminal, operator, timestamp, reviewer, and
license placeholders from retained real records. It cannot create evidence, fill
answers, or change deterministic gates.

```powershell
uv run python examples/run_source_qa_evidence_inbox.py --data-dir data_exports --report-dir results\first_million --as-of 2026-06-10
```

`data_intake_status.json/md/csv` is the combined first screen for the intake
bottleneck. It rolls up source QA evidence, worksheet-fill readiness, answers,
manifest, raw bars discovery, Source QA closeout, and OHLCV closeout into one
operator card with a single next area, next action, and next command. It is
still read-only: it cannot approve data, rank strategies, or change any
deterministic gate.

```powershell
uv run python examples/run_data_intake_status.py --report-dir results\first_million --data-dir data_exports --as-of 2026-06-10
```

`source_qa_closeout.json/md/csv` is the single source-QA cover sheet for the
operator packet, evidence inbox, and deterministic readiness report. It shows
the artifact manifest, missing worksheet/attachment counts, one prioritized
next action, and capability flags. A `PASS` closeout only allows the next
guarded offline-intake review; it does not approve candidate research, paper
trading, live trading, or broker orders.

```powershell
uv run python examples/run_source_qa_closeout.py --data-dir data_exports --report-dir results\first_million --checklist data_exports\data_source_qa.json --worksheet data_exports\data_source_qa_evidence_worksheet.csv --answers data_exports\data_source_qa_answers.json --evidence-manifest data_exports\source_qa_evidence_manifest.json --require-evidence-manifest --as-of 2026-06-10
```

`write_data_source_qa.py` also writes `data_source_qa_evidence_worksheet.json`,
`data_source_qa_evidence_worksheet.csv`, and
`data_source_qa_evidence_worksheet.md`. The worksheet is a fillable human
evidence table for vendor, terminal, export time, price adjustment, license
scope, point-in-time notes, and manual review. It does not generate fake
answers, does not write broker orders, and cannot weaken deterministic
`PASS/WATCH/BLOCK` gates; blank or placeholder evidence still keeps source QA
blocked.

If you prefer a command-line fill step instead of editing the CSV by hand, use
the explicit-input helper. It only writes worksheet rows and its own fill report;
it does not create attachments, answers, approvals, strategy evidence, or broker
orders:

```powershell
uv run python examples/fill_data_source_qa_evidence_worksheet.py --checklist data_exports\data_source_qa.json --worksheet data_exports\data_source_qa_evidence_worksheet.csv --vendor "<vendor-or-broker>" --terminal "<terminal-name>" --operator "<operator>" --exported-at "<local-time>" --price-adjustment qfq --license-scope "research and paper trading only" --reviewed-by "<name>" --reviewed-at "<YYYY-MM-DD>" --source-identity-evidence "<retained-source-identity-evidence>" --license-evidence "<retained-license-evidence>" --price-adjustment-evidence "<retained-price-adjustment-evidence>" --point-in-time-evidence "<retained-PIT-evidence-or-OHLCV-only-note>" --manual-signoff-evidence "<retained-human-review-evidence>"
```

After filling the worksheet with real export evidence, preflight the worksheet first:

```powershell
uv run python examples/run_data_source_qa_worksheet_preflight.py --checklist data_exports\data_source_qa.json --worksheet data_exports\data_source_qa_evidence_worksheet.csv --output-dir data_exports
```

Only after that preflight is not `BLOCK`, convert it into
`data_source_qa_answers.json` with:

```powershell
uv run python examples/write_source_qa_evidence_manifest.py --checklist data_exports\data_source_qa.json --evidence-dir data_exports\source_qa_evidence --output-dir data_exports --strict
uv run python examples/write_data_source_qa_answers.py --checklist data_exports\data_source_qa.json --worksheet data_exports\data_source_qa_evidence_worksheet.csv --output data_exports\data_source_qa_answers.json --evidence-manifest data_exports\source_qa_evidence_manifest.json --require-evidence-manifest
```

The strict conversion first writes a temporary answers file, runs deterministic
source QA against the retained attachment manifest, and only commits
`data_source_qa_answers.json` when the review is not `BLOCK`.
`run_source_qa_preflight.py` and `run_data_source_qa_review.py` still reject
blank, placeholder, or weak evidence before any offline intake can pass.

The first-million pipeline also writes `first_million_strategy_brief.json/md`.
This brief combines source-data gaps, offline package status, candidate
experiment readiness, the data evidence action packet, and market context into
a research work order. It can say `PREPARE_DATA`, `RUN_RESEARCH`, `PAPER_ONLY`,
or `PAUSE`, but it cannot promote a candidate, promise profits, or submit
broker orders.

When the full A-share cache is still unavailable, you can record an explicit
index-level context snapshot for review notes. If the snapshot will come from
local index daily CSV exports, run read-only discovery first against the
recommended directory `data_exports\indices`:

```powershell
uv run python examples/run_market_index_discovery.py --search-dir data_exports\indices --output-dir results\first_million --as-of 2026-06-09
```

`market_index_discovery.json/md` only discovers local, already-reviewed index
CSV candidates before `market_context_snapshot.json` is written. Each CSV must
have `date` and `close` columns. Long-form files may also include one of
`index`, `name`, `symbol`, or `code`, and breadth fields
`breadth_above_ma20` and `breadth_above_ma60` are optional. Discovery is not
market evidence by itself and cannot replace cache-derived
`market_regime.json`.

Then create the reviewed snapshot manually or from the selected CSV:

```powershell
uv run python examples/write_market_context_snapshot.py --output-dir results\first_million --as-of 2026-06-09 --source "<reviewed-index-source>" --reviewed-by "<name>" --reviewed-at 2026-06-09 --index "CSI300,0.01,0.03,0.04,0.08,0.22,0.55,0.50,offline note"
```

If discovery selected a local index daily CSV export, let the system calculate
the metrics:

```powershell
uv run python examples/write_market_context_snapshot.py --output-dir results\first_million --as-of 2026-06-09 --source "<reviewed-index-csv-export>" --reviewed-by "<name>" --reviewed-at 2026-06-09 --index-csv data_exports\indices\indices.csv --encoding auto
```

The normal command chain is:

```powershell
uv run python examples/run_market_index_discovery.py --search-dir data_exports\indices --output-dir results\first_million --as-of 2026-06-09
uv run python examples/write_market_context_snapshot.py --output-dir results\first_million --as-of 2026-06-09 --source "<reviewed-index-csv-export>" --reviewed-by "<name>" --reviewed-at 2026-06-09 --index-csv data_exports\indices\indices.csv --encoding auto
uv run python examples/run_market_context_readiness.py --report-dir results\first_million --as-of 2026-06-09
uv run python examples/run_first_million_pipeline.py --config config\research_recent.yaml --data-dir data_exports --output-dir results\first_million --source-qa-answers data_exports\data_source_qa_answers.json --source-qa-evidence-manifest data_exports\source_qa_evidence_manifest.json --require-source-qa-evidence-manifest --as-of 2026-06-09 --min-symbols 300 --min-trading-days 240
```

This writes `market_context_snapshot.json/md`. The strategy brief can display it
when `market_regime.json` is missing, but it is forced to WATCH-level context and
does not replace cache-derived market regime detection, data QA, robustness,
paper stability, human approval, or broker safety boundaries. Neither discovery
nor the snapshot can approve a strategy, give a candidate permission to trade,
or produce real broker instructions.

`market_context_operator_packet.json/md/csv` is the operator checklist for this
market-context gap. It lists the preferred cache-derived `market_regime.json`
path, the fallback snapshot fields (`as_of`, `source`, `reviewed_by`,
`reviewed_at`), required index metrics, acceptable evidence, forbidden weak
evidence, and command sequence. It does not create evidence or approve
strategies.

```powershell
uv run python examples/run_market_context_operator_packet.py --report-dir results\first_million --as-of 2026-06-09
```

Review the market context evidence explicitly with:

```powershell
uv run python examples/run_market_context_readiness.py --report-dir results\first_million --as-of 2026-06-09
```

This writes `market_context_readiness.json/md`. Missing market context is
`BLOCK`; a fully reviewed `market_context_snapshot.json` is still only `WATCH`;
only a fresh cache-derived `market_regime.json` can make this market-context
gate `PASS`. The gate is evidence for candidate research only and cannot
override deterministic `PASS/WATCH/BLOCK` decisions.

It also writes `goal/compounding_path_review.json/md`. This deterministic
review checks whether the selected candidate evidence, completion review, paper
stability, human approval, drawdown budget, Sharpe, and required annual return
can support the path from current capital to the target capital. A missing or
single-run candidate keeps this review `BLOCK`; it is not a profit guarantee
even when it eventually passes.

`normalize_vendor_bars.py` 只把原始券商/数据商日线 CSV 规范成合同格式 `bars.csv`; 它不等于 source QA、CSV validation、缓存导入、策略通过或实盘许可。`run_offline_data_intake.py --raw-bars-csv ... --source-* ...` 可以把规范化和 source QA answers 写入同一条受控流水线,`run_first_million_pipeline.py --raw-bars-csv ...` 也会先规范化 raw bars 再进入同一套受控审查,但所有 `--source-*` 字段都必须来自真实导出证据。

详细说明见 [docs/09_离线真实数据导入合同.md](docs/09_离线真实数据导入合同.md)。

### 3. 原双均线回测仍可用

```powershell
uv run python examples/download_data.py --symbol 600519 --start 2020-01-01 --end 2025-01-01
uv run python examples/run_backtest.py --config config/default.yaml
```

### 4. LLM-ready 研究审查

先跑出一份研究报告,再把 `<timestamp>` 换成实际目录:

```powershell
uv run python examples/run_llm_review.py --report-dir results/research/<timestamp> --stage paper
```

审查结果会写在同一个报告目录:

- `llm_review.json`: 结构化 PASS / WATCH / BLOCK 结论
- `llm_review.md`: 人类可读审查报告
- `llm_prompt.md`: 可复制给外部 LLM 的提示词包

默认不会调用外部模型。如果你配置了 OpenAI-compatible 接口,可以额外生成 advisory 叙事审查:

```powershell
$env:OPENAI_API_KEY="..."
$env:OPENAI_BASE_URL="https://api.openai.com/v1"
$env:OPENAI_MODEL="gpt-4o-mini"
uv run python examples/run_llm_review.py --report-dir results/research/<timestamp> --stage paper --call-llm
```

LLM 输出只作为研究建议,不能修改确定性审查门的 PASS / WATCH / BLOCK。

### 5. 每周一键审查流水线

正式使用真实 A 股缓存前,先跑一次只读检查单:

```powershell
uv run python examples/run_real_data_bootstrap.py --config config/research.yaml --output-dir results/bootstrap
```

```powershell
uv run python examples/run_weekly_pipeline.py --config config/research.yaml --starting-capital 100000 --target-capital 1000000 --years 8 --wf-train-days 120 --wf-test-days 60 --wf-step-days 60
```

如果已经有连续 paper loop 状态目录,把它纳入周审查:

```powershell
uv run python examples/run_weekly_pipeline.py --config config/research.yaml --paper-state-dir results/paper/core --starting-capital 100000 --target-capital 1000000 --years 8
```

Optional micro-live readiness preparation is explicit opt-in. It writes only
manual review artifacts (`target_portfolio.json/md/csv`,
`manual_trade_sheet.csv`, `risk_budget.json`, and
`micro_live_readiness.json/md`) and does not create approval records or broker
orders. The opt-in automatically uses the `micro_live_ready` deterministic
review stage:

```powershell
uv run python examples/run_weekly_pipeline.py --config config/research.yaml --paper-state-dir results/paper/core --prepare-micro-live-readiness --micro-live-candidate price_volume_defensive --micro-live-capital 100000
```

Without `approval_record.json`, the readiness gate stays `BLOCK`. Run readiness
once to prepare `manual_trade_sheet.csv` and `risk_budget.json`, review those
materials, then create the human approval; approval regenerates and fingerprints
both files together with the target plan and research evidence. Re-evaluation
does not overwrite locked review materials, so any manual-sheet or risk-budget
change returns readiness to `BLOCK` until a new approval is written. Approval is
also bound to the current `run_manifest.json`, which must include in-sample and
out-of-sample dates plus CSV/source-QA provenance metadata. The gate checks that
target CSV/JSON rows agree, prices and lot-sized quantities are valid, weights
and exposure fit the declared capital, and the manual sheet remains a manual-only
copy of the target's core fields. The manual trade sheet is a human reference only and is
never a broker basket.

流水线会生成真实数据 bootstrap、研究报告、数据审计、市场状态、稳健性报告、walk-forward、候选策略 walk-forward、候选策略分行情验证、候选策略筛选、模拟盘日报、模拟盘稳定性审查、LLM-ready 确定性审查、LLM prompt 和周度复盘。它默认不调用外部 LLM、不连接真实 broker、不写人工审批记录。未提供连续 paper 状态目录时,历史回测只写入 `research_execution_preview.json/md`,`paper_daily_review.json` 固定为 `BLOCK/NO_CONTINUOUS_PAPER_RUN`,`paper_stability.json` 也保持 BLOCK,且不会生成可被误认成连续模拟盘的 `paper_state.json`。

## 新手教程

从零开始请读:

- [docs/00_从零开始.md](docs/00_从零开始.md)
- [docs/01_核心概念.md](docs/01_核心概念.md)
- [docs/02_运行第一个研究实验.md](docs/02_运行第一个研究实验.md)
- [docs/03_如何阅读研究报告.md](docs/03_如何阅读研究报告.md)
- [docs/04_修改参数与常见错误.md](docs/04_修改参数与常见错误.md)
- [docs/05_量化实盘交易心智模型.md](docs/05_量化实盘交易心智模型.md)
- [docs/06_LLM_For_Quantify.md](docs/06_LLM_For_Quantify.md)
- [docs/07_长期执行Goal.md](docs/07_长期执行Goal.md)
- [docs/08_第一桶金策略研究路线.md](docs/08_第一桶金策略研究路线.md)
- [docs/09_离线真实数据导入合同.md](docs/09_离线真实数据导入合同.md)
- [docs/术语表.md](docs/术语表.md)

## 系统学习笔记

如果你想系统学习《预测: 方法与实践》和因子投资,读:

- [docs/notes/README.md](docs/notes/README.md)
- [docs/notes/fpp/01_intro.md](docs/notes/fpp/01_intro.md)
- [docs/notes/factor/01_factor_basics.md](docs/notes/factor/01_factor_basics.md)
- [docs/notes/math/01_probability.md](docs/notes/math/01_probability.md)

逐章笔记包含人话解释、数学推导、A 股量化映射、项目代码对应和练习。

## 当前能力

- 本地 SQLite 数据缓存: 日线行情、股票基础信息、交易日历、指数成分、停牌、基础财务/估值数据。
- 股票池过滤: ST、退市、停牌、无价格数据过滤。
- 多因子研究: 动量、低波动、估值、质量、流动性,截面去极值和标准化。
- 月度调仓策略: 因子综合打分,前 N 只股票,等权配置,单票上限。
- 纸面交易: 目标权重转订单,T+1,涨跌停/停牌不可交易,整百股,手续费,印花税,滑点,现金约束。
- 文件化报告: JSON、CSV、PNG、HTML。
- LLM-ready 审查: 读取研究报告,输出 PASS/WATCH/BLOCK、缺失证据、下一步实验、外部 LLM 提示词,并可选调用 OpenAI-compatible advisory 模型。
- 小额实盘准备骨架: 数据审计、稳健性实验、模拟盘日报、人工审批记录、`micro_live_ready` 准备门和人工参考表; 准备门会读取目标组合风险标记,阻断 ST、退市、停牌、涨跌停和缺价行。
- 资金目标筛选: 把 100 万元目标转成年化收益、回撤预算和候选策略评分,拒绝不现实或证据不足的策略。
- 候选策略假设目录: `candidate_hypotheses.json/md` 在真实数据到位前固定每个候选策略的假设、适用行情、验证门槛、自动降级条件和禁止动作。
- 候选实验队列: `candidate_experiment_queue.json/md` 把候选假设转成预注册验证顺序、命令链、成功标准、证伪测试和停止条件,并记录资金目标适配测试、最小证据窗口、风控预算检查、paper 准入要求和抗过拟合控制项,防止后续挑回测好看的结果。
- Candidate experiment design matrix: `candidate_experiment_design_matrix.json/md/csv` expands the queue into pre-registered candidate-by-stress-scenario coverage before results are known. It is a research design artifact only: it cannot rank candidates, approve paper, or generate broker orders.
- 候选实验可运行性审查: `candidate_experiment_readiness.json/md` 检查 source QA、offline intake 和实验队列是否都通过,未通过时阻止候选实验开跑并给出下一步。
- 候选实验启动计划: `candidate_experiment_launch.json/md` 在可运行性 PASS 后锁定首个候选、运行 ID、实验目录、命令链和 required outputs; BLOCK 时只记录阻塞原因,不允许开跑。
- 候选实验完成审查: `candidate_experiment_completion.json/md` 检查启动计划要求的实验产物是否齐全且无 BLOCK,防止只挑好看的部分结果进入 paper。
- 候选策略实验器: 一次比较 OHLCV-only 防守价量、低换手价量、趋势过滤价量、防守现金保护价量、核心多因子、防守低波、动量质量、价值低波和趋势过滤策略; 缺少 PIT 财务字段时,估值/质量依赖候选会被数据依赖门降级。
- 慢信号 OHLCV 候选: `stable_universe_slow_signal_price_volume` 使用更宽的季度篮子、`long_momentum_120d_skip20d`、超低波、低波和流动性,用于在 hold buffer、漂移阈值、新仓上限和分数平滑失效后测试结构性降换手; 它仍然只是 research-only 候选,不能覆盖 source QA、launch、completion、paper、人审或 broker 安全门。
- 长动量+流动性 OHLCV 消融候选: `long_momentum_liquidity_monthly_price_volume` 使用 `long_momentum_120d_skip20d` 和流动性做月度 component-ablation,验证慢信号候选是否被低波组件稀释; 它仍然只是 research-only 候选,不能覆盖 source QA、launch、completion、paper、人审或 broker 安全门。
- 流动性中性动量防守 OHLCV 候选: `liquidity_neutral_momentum_guard_price_volume` 使用 residualized long momentum、超低波、季度调仓和 defensive-or-worse 缩仓来测试流动性依赖和防御窗口亏损; 如果继续 BLOCK,`candidate_next_experiments` 会生成 `liquidity_neutral_guard_lineage_review`,固定比较 slow-signal、long-momentum+liquidity 和 liquidity-neutral guard 三条谱系,而不是默认继续加因子; 它仍然只是 research-only 候选,不能覆盖 source QA、launch、completion、paper、人审或 broker 安全门。
- 候选资金目标适配: `candidate_selection.json/csv` 为每个候选写入 `capital_goal_fit_review`,把目标年化收益、收益安全垫、回撤预算、候选 walk-forward 最差窗口、夏普、拒单率和换手率合并成 PASS/WATCH/BLOCK; `selected_candidate` 只能来自未被 BLOCK 的候选,`top_candidate` 仍可保留研究排序第一名。
- Candidate regime validation is now consumed by `candidate_selection`: when
  `candidate_regime_validation_report.json` is present, each candidate gets a
  `candidate_regime_validation_review` and CSV status columns. Missing,
  unmatched, or report-level warning evidence stays advisory/WATCH-like and
  cannot upgrade a candidate; any candidate-level BLOCK bucket blocks selection.
- 候选下一实验队列: `candidate_next_experiments.json/md/csv` 把被 BLOCK 或证据不足的候选结果转成 research-only 后续实验,覆盖高换手、负收益窗口、弱夏普、回撤压力、趋势过滤现金拖累、缺因子诊断和缺行情分层验证; 它固定 `promotion_decision=BLOCK`,不能进入 paper、micro-live 或 broker。
- 候选压力矩阵: `candidate_stress_matrix.json/md/csv` 对候选专属因子组合跑持仓数、最大权重、调仓频率、成本上调和趋势过滤开关压力测试,保留 `RESEARCH_ONLY/BLOCK` 边界,用于判断下一轮研究参数而不是批准交易。
- 资金目标总控: `capital_goal_status.json/md` 汇总数据、稳健性、候选策略、模拟盘、审批和晋级证据,并在 raw vendor CSV 路径下检查 `raw_vendor_traceability`,在 TDX `.day` 路径下检查 `tdx_day_traceability`,明确离一百万元复利目标还缺哪些硬条件。
- 第一桶金就绪卡片: `first_million_readiness.json/md` 把数据缺口、source QA、offline intake、候选实验 readiness/launch/completion 和资金目标总控压成一张首屏结论。
- 资金递增门: `capital_scaling_plan.json/md` 约束每次资金提高的最大幅度,任何 BLOCK 都会把允许资金重置为当前资金。
- Paper 候选计划: `paper_candidate_plan.json/md` 审查候选是否允许进入连续 paper loop,并只生成本地模拟命令。生成的命令固定传入 research `run_manifest` 记录的 cache path、cache SHA256 和 dataset fingerprint；`paper_state.run_context` 会保存同一身份,旧状态缺少上下文或续跑时身份漂移都会拒绝继续。
- 研究执行预览隔离: 没有 `run_paper_loop` checkpoint 时,`equity.csv/orders.csv/positions.csv` 只能生成 `research_execution_preview.json/md`; 这些历史天数不计入连续 paper 观察期,也不能生成 promotion-eligible paper 状态。
- 股票池时间一致性审查: AKShare 当前快照或手工 symbol list 会写入非 PIT universe 元数据；`data_audit` 和 LLM review 会显式提示 `UNIVERSE_NOT_POINT_IN_TIME`,在补齐历史成分与退市样本前只允许 research-only 使用。
- 晋级证据身份门: `micro_live_readiness.json/md` 要求 candidate selection、experiment completion、walk-forward、regime validation、paper state 和 target portfolio 指向同一候选,并要求 paper cache SHA256/fingerprint 与 research run manifest 一致；不能拼接不同运行的 `PASS` 产物。
- 候选因子诊断: `candidate_factor_diagnostics.json/md` 检查候选是否过度依赖单一因子组件,防止把偶然暴露误当成稳定复利能力。周流水线默认诊断当前 best candidate,全量候选诊断可手动运行。
- 市场状态检测: 从本地 A 股日线缓存计算等权市场趋势、宽度、波动和回撤,生成 `market_regime.json/md`,作为候选策略筛选的研究上下文。
- 最近数据采集计划: `recent_data_acquisition_plan.json/md` 明确近期 A 股配置、缓存、导入方式和当前 BLOCK 原因。
- 数据缺口行动清单: `data_gap_action_plan.json/md` 汇总 source QA、CSV 模板、必填元数据、import doctor 和下一步命令,防止把模板或缺证据数据推进策略实验。
- 真实数据启动检查: `real_data_bootstrap.json/md` 汇总缓存是否存在、是否 demo、样本拆分、近期真实数据门、覆盖率和下一步导入/流水线命令。
- 运行证据清单: `run_manifest.json/md` 记录配置哈希、缓存哈希、CSV 数据指纹、raw vendor 文件指纹、样本窗口、股票数量、交易日数量和安全边界。
- 近期真实数据门: `real_data_gate.json/md` 检查缓存是否为非 demo、足够新、覆盖股票数和交易日数是否足够。
- 数据覆盖诊断: `data_coverage.json/md/csv` 输出每只股票首末日期、bar 数、覆盖率、缺失天数和过期标记。
- 滚动窗口验证: `walk_forward_report.json/md` 检查策略在多个连续测试窗口中的收益、回撤、夏普和拒单率。
- 候选策略滚动验证: `candidate_walk_forward_report.json/md` 对所有候选策略做跨窗口稳定性比较,防止只按单一区间排名。
- 候选策略分行情验证: `candidate_regime_validation_report.json/md` 把候选策略 walk-forward 窗口按市场状态分桶,检查是否只在单一行情里有效。
- 人工目标组合计划: `target_portfolio.json/md/csv` 和 `manual_trade_sheet.csv` 基于本地最新数据生成手工参考表,不是 broker 订单。
- 手工执行可行性检查: 目标组合会标注 20 日成交额、参与率、行业、低流动性、集中度、ST、退市、停牌和涨跌停风险; 当前持仓即使不再进入目标股票池也会保留为人工处理行。
- 连续模拟盘循环: `run_paper_loop.py` 用同一个 state 目录逐日恢复现金、持仓、订单和净值,并生成 `paper_stability.json/md`,只做本地 paper 记录。
- 周度审查: 汇总数据审计、市场状态、稳健性、候选策略、LLM 审查、模拟盘和 readiness 证据,生成 `weekly_review.json/md`,给出继续纸面观察、只研究或暂停修复的结论。
- 一键周度流水线: `run_weekly_pipeline.py` 自动生成离线研究到周复盘的完整证据目录,但不进入真实交易。
- 策略档案: `strategy_registry.json/md` 使用 v3 合同长期累积候选结果。只有同时通过数据 provenance、selection-safe walk-forward/robustness、正式 benchmark、multiple-testing 和 prospective trial binding 的观察才计入可晋级真实观察；旧、demo 或合同不完整记录保留但排除。
- 策略晋级审查: `strategy_promotion_review.json/md` 对照资金目标路径、真实数据观察和候选策略 walk-forward 证据,判断候选是否值得继续 paper-stage 深挖。
- 真实数据导入: 通过 AKShare 批量导入 A 股股票基础信息、日线行情、交易日历和指数成分占位。
- 离线 CSV 导入: 从券商/终端导出的 bars、stock_info、fundamentals、calendar、suspensions、index_constituents CSV 先经过 `csv_validation.json/md` 合同校验,再写入同一研究缓存。

## 测试

```powershell
uv run pytest tests/ -q --basetemp ./tmp/pytest -p no:cacheprovider
uv run ruff check .
```

如果 `uv run` 因用户目录缓存权限失败,可以使用本地虚拟环境:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q --basetemp .\tmp\pytest -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check .
```

## 项目结构

```text
src/quantify/
  core/       事件、Bar、Portfolio、目标权重
  data/       CSV/AKShare/SQLite/DataProvider
  research/   股票池、因子、多因子策略、研究引擎、报告
  engine/     原回测引擎、BrokerSim、PaperBroker
  risk/       原风控和头寸计算
  llm/        LLM-ready 研究审查与实盘发布门
  audit/      A 股日频数据可信度审计
  goal/       资金目标规划和策略候选评分
  market/     当前市场状态假设记录和本地行情状态检测
  ops/        周度执行复盘、证据矩阵、策略档案和离线流水线
  paper/      模拟盘日报产物
  readiness/  小额实盘准备门和人工审批记录
  analytics/  指标和图表
  utils/      配置加载
```

## 下一步建议

第一阶段先用 demo 数据理解流程。第二阶段下载/导入真实 A 股数据。第三阶段用 `data_audit`、`robustness` 和 `llm_review` 审查研究质量。第四阶段连续跑模拟盘日报。第五阶段才考虑人工小额实盘准备,且不接自动下单。
## Turnover Evidence Note

Candidate research reports split turnover into `initial_turnover_pct` for the
first deployment and `avg_maintenance_turnover_pct` /
`max_maintenance_turnover_pct` for recurring post-deployment turnover. The
`turnover_control`, stronger `stability_control`, and past-only
`score_smoothing` stress scenarios are research-only diagnostics; they cannot
approve paper, micro-live readiness, or broker instructions, and they cannot
override deterministic BLOCK gates.
