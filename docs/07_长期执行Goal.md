# 07 长期执行 Goal: A 股日频小额实盘准备系统
> 风险提示: 这个 goal 的目标是实盘准备,不是立即实盘。本项目不会自动提交真实 broker 订单。
## 目标

把 Quantify 长期推进为 A 股日频量化工作台:

```text
数据审计 -> 稳健性研究 -> 模拟盘日报 -> LLM 风控审查 -> 人工审批 -> micro_live_ready
```

`micro_live_ready` 只表示材料准备完毕,仍然只能人工决策和人工下单。
## 每周节奏

- 周一: 跑数据审计。
- 周二: 跑研究和稳健性实验。
- 周三: 跑 LLM 审查和模拟盘日报。
- 周四: 修复数据、策略、风控或执行问题。
- 周五: 生成 readiness 材料和周复盘。

## 命令链
推荐每周先跑真实数据启动检查,再跑一键离线流水线:

```powershell
uv run python examples/run_recent_data_plan.py --config config/research_recent.yaml --output-dir results/bootstrap_recent --as-of 2026-06-08
uv run python examples/run_real_data_bootstrap.py --config config/research_recent.yaml --output-dir results/bootstrap_recent --min-symbols 300 --as-of 2026-06-08
uv run python examples/run_weekly_pipeline.py --config config/research_recent.yaml --review-stage paper --paper-state-dir results/paper/core --wf-train-days 120 --wf-test-days 60 --wf-step-days 60
```

流水线会自动生成真实数据 bootstrap、研究报告、近期真实数据门、数据审计、市场状态、稳健性报告、walk-forward、候选策略 walk-forward、候选策略分行情验证、候选策略筛选、模拟盘日报、模拟盘稳定性审查、LLM-ready 确定性审查、LLM prompt、周度复盘和策略档案快照。它默认不调用外部 LLM、不写人工审批记录、不生成真实 broker 指令。未提供连续 paper 状态目录时,历史回测只生成 `research_execution_preview.json/md`,`paper_daily_review.json` 固定为 `BLOCK/NO_CONTINUOUS_PAPER_RUN`,`paper_stability.json` 也明确 BLOCK,且历史回测天数不会计入连续模拟盘观察期。
如果需要逐步排查,可以按下面命令链分步跑。
如果 AKShare 或行情接口被网络/权限限制挡住,使用离线 CSV 合同补齐真实数据入口:

```powershell
uv run python examples/write_data_export_request.py --config config/research_recent.yaml --output-dir data_exports --min-symbols 300
uv run python examples/write_candidate_hypotheses.py --config config/research_recent.yaml --output-dir results\first_million --as-of 2026-06-08
uv run python examples/write_candidate_experiment_queue.py --config config/research_recent.yaml --output-dir results\first_million --as-of 2026-06-08
uv run python examples/run_data_gap_action_plan.py --data-dir data_exports --config config/research_recent.yaml --output-dir results\first_million --min-symbols 300 --as-of 2026-06-08
uv run python examples/write_data_source_qa.py --config config/research_recent.yaml --output-dir data_exports --min-symbols 300 --as-of 2026-06-08
uv run python examples/write_data_source_qa_evidence_worksheet.py --checklist data_exports\data_source_qa.json --output-dir data_exports
uv run python examples/run_data_source_qa_worksheet_preflight.py --checklist data_exports\data_source_qa.json --worksheet data_exports\data_source_qa_evidence_worksheet.csv --output-dir data_exports
uv run python examples/write_source_qa_evidence_manifest.py --checklist data_exports\data_source_qa.json --evidence-dir data_exports\source_qa_evidence --output-dir data_exports --strict
uv run python examples/write_data_source_qa_answers.py --checklist data_exports\data_source_qa.json --worksheet data_exports\data_source_qa_evidence_worksheet.csv --output data_exports\data_source_qa_answers.json --evidence-manifest data_exports\source_qa_evidence_manifest.json --require-evidence-manifest
uv run python examples/run_data_source_qa_review.py --checklist data_exports\data_source_qa.json --answers data_exports\data_source_qa_answers.json --evidence-manifest data_exports\source_qa_evidence_manifest.json --require-evidence-manifest --output-dir results\import\source_qa
uv run python examples/write_data_export_templates.py --output-dir data_exports
uv run python examples/normalize_vendor_bars.py --input "<raw-vendor-bars.csv>" --output-dir data_exports --start 2024-06-03 --end 2026-06-05 --min-symbols 300
uv run python examples/convert_tdx_day.py --input-dir "<tdx-vipdoc-or-lday-dir>" --output-dir data_exports --start 2024-06-03 --end 2026-06-05
uv run python examples/run_data_import_doctor.py --data-dir data_exports --config config/research_recent.yaml --output-dir results\import\doctor
uv run python examples/run_offline_data_package.py --data-dir data_exports --config config\research_recent.yaml --output-dir results\first_million --source-qa-answers data_exports\data_source_qa_answers.json --source-qa-evidence-manifest data_exports\source_qa_evidence_manifest.json --require-source-qa-evidence-manifest --as-of 2026-06-08 --min-symbols 300
uv run python examples/run_offline_data_intake.py --raw-bars-csv "<raw-vendor-bars.csv>" --data-dir data_exports --config config/research_recent.yaml --output-dir results\import\offline_intake --source-qa-answers data_exports\data_source_qa_answers.json --source-vendor "<vendor-or-broker>" --source-terminal "<terminal-name>" --source-operator "<operator>" --source-exported-at "<local-time>" --source-price-adjustment qfq --source-price-adjustment-evidence "<evidence>" --source-license-evidence "<evidence>" --source-point-in-time-evidence "<evidence-or-non-pit-note>" --source-reviewed-by "<name>" --source-reviewed-at "<date>" --as-of 2026-06-08 --min-symbols 300 --min-trading-days 240
uv run python examples/run_goal_status.py --report-dir results\goal --config config/research_recent.yaml --source-qa-dir results\import\source_qa --import-doctor-dir results\import\doctor --offline-intake-dir results\import\offline_intake --as-of 2026-06-08 --starting-capital 100000 --target-capital 1000000 --years 8 --min-symbols 300 --min-trading-days 240
uv run python examples/run_first_million_pipeline.py --config config/research_recent.yaml --data-dir data_exports --output-dir results\first_million --raw-bars-csv "<raw-vendor-bars.csv>" --source-vendor "<vendor-or-broker>" --source-terminal "<terminal-name>" --source-operator "<operator>" --source-exported-at "<local-time>" --source-price-adjustment qfq --source-price-adjustment-evidence "<evidence>" --source-license-evidence "<evidence>" --source-point-in-time-evidence "<evidence-or-non-pit-note>" --source-reviewed-by "<name>" --source-reviewed-at "<date>" --as-of 2026-06-08 --min-symbols 300 --min-trading-days 240
uv run python examples/validate_research_csv.py --bars-csv data_exports\bars.csv --stock-info-csv data_exports\stock_info.csv --fundamentals-csv data_exports\fundamentals.csv --calendar-csv data_exports\calendar.csv --suspensions-csv data_exports\suspensions.csv --index-constituents-csv data_exports\index_constituents.csv --start 2024-06-03 --end 2026-06-05 --min-symbols 300 --output-dir results\import\recent_csv_validation
uv run python examples/import_research_csv.py --cache .\data_cache\research_recent.db --bars-csv data_exports\bars.csv --stock-info-csv data_exports\stock_info.csv --fundamentals-csv data_exports\fundamentals.csv --calendar-csv data_exports\calendar.csv --suspensions-csv data_exports\suspensions.csv --index-constituents-csv data_exports\index_constituents.csv --validate --start 2024-06-03 --end 2026-06-05 --min-symbols 300 --output-dir results\import\recent_csv
```

详见 [09_离线真实数据导入合同.md](09_离线真实数据导入合同.md)。离线导入通过后,仍必须重新跑 `real_data_bootstrap` 和 `data_audit`。

Blocked first-million runs should be worked from
`first_million_resolution_plan.json/md/csv`. The plan groups P0 source QA
worksheet rows, required source evidence attachments, and CSV export
replacement tasks before any P2 candidate or capital-goal work. Refresh it with:

```powershell
uv run python examples/run_first_million_resolution_plan.py --report-dir results\first_million --as-of 2026-06-10
```

This file is an operator queue only. It does not change deterministic gates,
does not approve paper or micro-live work, and does not authorize broker orders.

先跑研究:

```powershell
uv run python examples/run_research.py --config config/research.yaml
```

对报告目录跑数据审计:

```powershell
uv run python examples/run_recent_data_plan.py --config config/research_recent.yaml --output-dir results/research/<timestamp>
uv run python examples/run_real_data_bootstrap.py --config config/research_recent.yaml --output-dir results/research/<timestamp>
uv run python examples/run_real_data_gate.py --config config/research_recent.yaml --output-dir results/research/<timestamp>
uv run python examples/run_data_coverage.py --config config/research_recent.yaml --output-dir results/research/<timestamp>
uv run python examples/run_data_audit.py --config config/research_recent.yaml --output-dir results/research/<timestamp>
```

跑稳健性实验:

```powershell
uv run python examples/run_robustness.py --config config/research.yaml --output-dir results/research/<timestamp> --mode expanding --train-days 120 --purge-days 5 --selection-days 20 --embargo-days 5 --test-days 60 --step-days 60
uv run python examples/run_walk_forward.py --config config/research.yaml --output-dir results/research/<timestamp>
uv run python examples/run_candidate_walk_forward.py --config config/research.yaml --output-dir results/research/<timestamp>
uv run python examples/run_candidate_regime_validation.py --config config/research.yaml --output-dir results/research/<timestamp>
```

新 holdout 实验必须先登记、后运行、再追加结果；旧结果不能回填成预注册：

```powershell
.\.venv\Scripts\python.exe examples\run_trial_registry.py preregister --registry results\research\trial_registry.jsonl --payload trial-preregistration.json
.\.venv\Scripts\python.exe examples\run_multiple_testing_review.py --input-csv results\research\frozen_trial_returns.csv --output-dir results\research\<timestamp> --selected-candidate <candidate> --periods-per-year 252 --partition-count 8
.\.venv\Scripts\python.exe examples\run_benchmark_review.py --strategy-equity-csv results\research\<timestamp>\equity.csv --benchmark-csv evidence\csi800_total_return.csv --benchmark-metadata evidence\csi800_total_return.metadata.json --output-dir results\research\<timestamp>
.\.venv\Scripts\python.exe examples\run_trial_registry.py record-result --registry results\research\trial_registry.jsonl --payload trial-result.json
.\.venv\Scripts\python.exe examples\run_trial_registry.py verify --registry results\research\trial_registry.jsonl
.\.venv\Scripts\python.exe examples\run_trial_registry_review.py --registry results\research\trial_registry.jsonl --report-dir results\research\<timestamp>
```

生成模拟盘日报:

```powershell
uv run python examples/run_paper_candidate_plan.py --report-dir results/research/<timestamp> --config config/research_recent.yaml --paper-state-dir results/paper/core
uv run python examples/run_paper_loop.py --config config/research_recent.yaml --state-dir results/paper/core --candidate core_multifactor
uv run python examples/run_paper_stability.py --paper-dir results/paper/core
uv run python examples/run_paper_daily.py --report-dir results/research/<timestamp>
uv run python examples/run_target_plan.py --config config/research.yaml --output-dir results/research/<timestamp> --current-positions results/research/<timestamp>/paper_positions.csv
```

跑 LLM-ready 审查:

```powershell
uv run python examples/run_llm_review.py --report-dir results/research/<timestamp> --stage micro_live_ready
```

生成市场状态和候选策略筛选:

```powershell
uv run python examples/run_market_regime.py --config config/research.yaml --output-dir results/research/<timestamp>
uv run python examples/run_candidate_selection.py --config config/research.yaml --output-dir results/research/<timestamp> --starting-capital 100000 --target-capital 1000000 --years 8
```

写人工审批记录:

```powershell
uv run python examples/run_readiness.py --report-dir results/research/<timestamp> --approved-by "your-name" --approval-notes "manual review only"
uv run python examples/run_capital_scaling_plan.py --report-dir results/research/<timestamp> --current-capital 100000 --proposed-capital 120000
```

生成周度复盘:

```powershell
uv run python examples/run_weekly_review.py --report-dir results/research/<timestamp>
```

## 产物

- `real_data_bootstrap.json/md`: 真实数据启动检查,汇总缓存存在性、样本拆分、demo 风险、近期真实数据门、覆盖率和下一步命令。
- `recent_data_acquisition_plan.json/md`: 近期真实 A 股数据采集计划和当前 BLOCK 原因。
- `data_gap_action_plan.json/md`: 数据缺口行动清单,把 source QA、CSV 模板、必填元数据、import doctor 和下一步命令汇总到一个可执行清单。
- `candidate_hypotheses.json/md`: 候选策略假设目录,记录每个候选的研究假设、适用行情、验证门槛、自动降级条件、paper 观察要求和禁止动作。它不是策略排名,也不是实盘指令。
- `candidate_experiment_queue.json/md`: 候选策略预注册实验队列,记录验证顺序、命令链、成功标准、证伪测试、停止条件和产物; 它不能提高任何候选的审查结论。
- `price_volume_defensive`: 通达信或券商日线只提供 OHLCV 时优先验证的候选,不使用估值、质量字段,但仍必须通过 source QA、offline intake、数据审计、稳健性和模拟盘门。缺少 PIT 财务字段时,估值、质量依赖候选会在 `candidate_selection` 中被数据依赖门降级。
- `candidate_experiment_readiness.json/md`: 候选实验可运行性审查,只有 source QA、offline intake 和实验队列都 PASS 时才允许按预注册队列启动候选实验。
- `candidate_experiment_launch.json/md`: 候选实验启动计划,在 readiness PASS 后锁定首个候选、运行 ID、实验目录、命令链与 required outputs; readiness BLOCK 时只记录阻塞原因。
- `candidate_experiment_completion.json/md`: 候选实验完成审查,确认启动计划要求的产物存在且无 BLOCK,防止只挑选好看的部分结果进入 paper。
- `trial_registry.jsonl`: canonical JSONL 预注册与结果账本，使用 SHA-256 链检测改写、截断和乱序；不提供历史回填命令。
- `multiple_testing_report.json/md`: 冻结 trial 日收益矩阵上的 DSR 与 CSCV/PBO 诊断；证据不足时 BLOCK，且永远不能升级确定性门。
- `benchmark_report.json/md`: 经人工复核、文件哈希绑定且身份匹配 `000906` 的全收益基准审查；记录超额 CAGR、跟踪误差、信息比率和 moving-block bootstrap 95% CI。
- `trial_registry_review.json/md`: 把前瞻 preregistration/result 与当前研究 artifacts 逐文件 SHA-256 绑定；事后注册、候选错配或文件改写均 BLOCK。
- `run_manifest.json/md`: 运行证据清单,记录配置哈希、缓存哈希、CSV 数据指纹、raw vendor 文件指纹、样本窗口、股票数、交易日数和安全边界。
- `real_data_gate.json/md`: 近期真实数据门。
- `data_coverage.json/md/csv`: 每只股票覆盖范围、缺口和过期诊断。
- `data_audit.json/md`: 数据可信度审计。
- `market_regime.json/md`: 本地行情市场状态检测。
- `robustness_report.json/md`: 预冻结标准场景矩阵，并在隔离 test folds 上完整运行的参数扰动与成本压力测试；少于 3 个完整 folds 最多为 WATCH。
- `walk_forward_report.json/md`: 滚动窗口稳定性验证。
- `candidate_walk_forward_report.json/md`: 候选策略滚动窗口稳定性比较。
- `candidate_factor_diagnostics.json/md`: 候选策略因子组件诊断,检查是否过度依赖单一因子。周流水线默认诊断当前 best candidate。
- `candidate_regime_validation_report.json/md`: 候选策略按市场状态分桶的稳定性验证。
- `candidate_selection.json/md/csv`: 候选策略排名和资金目标匹配。
- `paper_candidate_plan.json/md`: 候选进入连续模拟盘观察的门禁计划和本地 paper loop 命令。
- `research_execution_preview.json/md`: 历史回测的执行预览,固定 `promotion_eligible=false`; 不能替代连续 paper checkpoint,不能累计模拟盘观察天数。
- `capital_goal_status.json/md`: 第一桶金目标总控面板,汇总数据、稳健性、候选策略、模拟盘、审批和晋级证据; raw vendor CSV 路径下还会用 `raw_vendor_traceability` 确认 normalization、import metadata、SQLite metadata 与 run manifest 的原始文件指纹一致。
- `first_million_readiness.json/md`: 第一桶金就绪卡片,把数据缺口、source QA、offline intake、候选实验闭环和资金目标总控汇成首屏 PASS/WATCH/BLOCK。
- `capital_scaling_plan.json/md`: 资金递增审查,限制每次资金提高的最大幅度。
- `paper_state.json`: 只由连续本地 paper loop 生成的可恢复模拟盘状态; 必须绑定 candidate、run context、local-paper backend 和 checkpoint。
- `paper_orders.csv`: 模拟订单。
- `paper_positions.csv`: 最新模拟持仓。
- `paper_daily.csv`: 连续模拟盘每日状态。
- `paper_stability.json/md`: 连续模拟盘稳定性审查。
- `paper_daily_review.md`: 模拟盘日报。
- `target_portfolio.json/md/csv`: 下一次目标组合和手工差额参考。
- `approval_record.json`: 人工审批记录。
- `micro_live_readiness.json/md`: 小额实盘准备门结论。
- `risk_budget.json`: 手工阶段风险预算。
- `manual_trade_sheet.csv`: 人工参考表,优先来自目标组合计划,包含流动性、参与率、ST/退市/停牌/涨跌停等风险标记; 当前持仓即使被目标股票池过滤也会保留为人工处理行,不是真实订单。
- `weekly_review.json/md`: 周度证据矩阵和继续/降级/暂停结论。
- `weekly_pipeline.json/md`: 一键流水线阶段记录和最终周度结论。
- `strategy_registry_snapshot.json/md`: 当前周策略档案快照。
- `results/strategy_registry/strategy_registry.json/md`: v3 长期候选档案；只有 provenance、selection safety、benchmark、multiple-testing 和 prospective trial binding 全部通过的观察才计入晋级统计。
- `strategy_promotion_review.json/md`: 对照资金目标路径和候选策略 walk-forward 的策略晋级审查。

## 升级条件
进入 `micro_live_ready` 前必须满足:

- 近期真实数据门没有 BLOCK。
- 真实数据 bootstrap 没有 BLOCK。
- 真实数据通过审计。
- 稳健性测试没有 BLOCK。
- 滚动窗口验证没有 BLOCK。
- 候选策略滚动窗口验证没有 BLOCK。
- 候选策略分行情验证没有 BLOCK。
- benchmark、multiple-testing 与 trial registry review 均为完整合同 PASS。
- LLM deterministic review 没有 BLOCK。
- 模拟盘状态存在且不连接 broker。
- 连续模拟盘稳定性没有 BLOCK。
- 目标组合计划只输出人工参考表,不生成 broker 指令。
- 目标组合计划没有 ST、退市、停牌、涨跌停或缺价等阻断执行标记; 低流动性、高参与率或高权重标记至少触发 WATCH。
- 有人工审批记录。
- `manual_trade_sheet.csv` 只作为人工参考。

任何 BLOCK 都会降级为 research 或 paper。
## 周度决策

`weekly_review` 只做汇总和降级,不做乐观升级:

- `continue_paper`: 核心证据全 PASS,继续模拟盘观察。
- `research_only`: 没有 BLOCK,但仍有 WATCH 或 readiness 证据不足,继续研究和补实验。
- `pause_and_fix`: 出现 BLOCK、核心证据缺失或 broker 边界被破坏,暂停推进并修复。

它不会生成真实 broker 指令,也不能证明策略未来稳定赚钱。
## 策略档案

每次候选策略筛选后,系统会把结果追加到长期 registry:

```powershell
uv run python examples/update_strategy_registry.py --report-dir results/research/<timestamp>
```

长期策略不能只凭单次回测晋级。至少要看:

- 多次观察中 PASS/WATCH/BLOCK 的分布。
- 平均收益是否接近资金目标路径。
- 平均回撤是否低于预算。
- 夏普、拒单率、换手是否稳定。
- demo 数据观察和真实数据观察必须分开理解。

Registry 的晋级资格规则:

- demo-only 历史永远不能晋级。
- 至少需要 3 次真实数据观察。
- 至少需要 2 次真实数据 PASS。
- 真实数据历史中不能出现 BLOCK。
- 至少需要 3 次真实数据候选策略 walk-forward 观察。
- 至少需要 2 次真实数据候选策略 walk-forward PASS。
- 候选策略 walk-forward 不能出现 BLOCK,平均窗口 PASS 比例不能低于 60%。
- 每个计入的真实观察都必须有 PASS benchmark、multiple-testing 和 trial registry review；旧 v2 summary 不得绕过。
- 至少需要 3 次真实数据候选策略分行情验证观察。
- 至少需要 1 次真实数据候选策略分行情验证 PASS。
- 晋级前必须见过 defensive 或 risk_off 窗口,避免只在顺风行情里评估策略。
- 真实数据平均回撤和拒单率必须低于预算。

满足这些条件也只表示可以进入更深入的 paper-stage review,仍然不是实盘指令。
## 晋级审查

对长期 registry 做资金目标审查:

```powershell
uv run python examples/review_strategy_promotions.py --registry results/strategy_registry/strategy_registry.json --output-dir results/strategy_registry --starting-capital 100000 --target-capital 1000000 --years 8
```

晋级审查会检查:

- 真实观察次数和真实 PASS 次数。
- 真实平均年化收益是否达到资金目标路径。
- 真实平均回撤是否低于预算。
- 真实平均夏普是否达到观察线。

`PASS` 只表示候选可以进入更深入的 paper-stage review。它不允许连接 broker、不允许自动下单、不允许提高资金。
