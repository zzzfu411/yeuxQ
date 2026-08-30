# 06 LLM For Quantify

## Source Evidence Boundary

Before LLM advisory review can be useful, the data source must have auditable
evidence. Use the source-QA worksheet to collect real vendor/export facts before
writing `data_source_qa_answers.json`:

LLM review also checks the cache attestation summary carried by
`run_manifest.data_version`: `cache_logical_bar_fingerprint`, its algorithm,
`cache_latest_import_batch_id`, and `cache_lineage_schema_version`. Missing
attestation is advisory `WATCH` in research/paper review and deterministic
`BLOCK` for micro-live readiness and later stages. The logical fingerprint is
never accepted as a substitute for `csv_dataset_fingerprint` or source QA. See
[Cache Provenance Attestation v1](14_Cache_Provenance_Attestation.md).

## Statistical Evidence Boundary

LLM review loads three additional research artifacts when they are available:

- `benchmark_report.json`: reviewed total-return benchmark evidence.
- `multiple_testing_report.json`: DSR and CSCV/PBO multiple-testing diagnostics.
- `trial_registry_review.json`: append-only preregistration and artifact hash review.

The deterministic reviewer does not trust a bare `status` field. It calls the
fail-closed validators in `quantify.research.evidence_validation`, verifies
retained input files and hashes, and records `valid`, validated status, and
validator reasons in the report digest and LLM prompt. The multiple-testing and
trial-registry candidate must match
`candidate_selection.selected_candidate` (with legacy `best_candidate`
fallback). The benchmark symbol must match
`run_manifest.research_parameters.index_code`.

Stage behavior is deliberately asymmetric:

- `research`: missing statistical artifacts are listed under missing evidence
  and next experiments without changing the deterministic decision. A present
  but invalid contract still blocks because it may indicate tampering or an
  identity mismatch.
- `paper`: missing evidence is `WATCH`; a valid non-PASS status is preserved;
  an invalid contract is `BLOCK`.
- `micro_live_ready`, `micro_live`, and `live`: missing, invalid, or non-PASS
  statistical evidence is `BLOCK`.

A validated `PASS` from any of these artifacts can never upgrade the existing
deterministic gate. The LLM prompt states this rule explicitly. These artifacts
are evidence for critique and promotion review, not broker instructions, human
approval, or permission to trade live.

```powershell
.\.venv\Scripts\python.exe examples\write_data_source_qa.py --config config\research_recent.yaml --output-dir data_exports --min-symbols 300 --as-of 2026-06-09
.\.venv\Scripts\python.exe examples\write_data_source_qa_evidence_worksheet.py --checklist data_exports\data_source_qa.json --output-dir data_exports
.\.venv\Scripts\python.exe examples\run_data_source_qa_worksheet_preflight.py --checklist data_exports\data_source_qa.json --worksheet data_exports\data_source_qa_evidence_worksheet.csv --output-dir data_exports
.\.venv\Scripts\python.exe examples\write_source_qa_evidence_manifest.py --checklist data_exports\data_source_qa.json --evidence-dir data_exports\source_qa_evidence --output-dir data_exports --strict
.\.venv\Scripts\python.exe examples\write_data_source_qa_answers.py --checklist data_exports\data_source_qa.json --worksheet data_exports\data_source_qa_evidence_worksheet.csv --output data_exports\data_source_qa_answers.json --evidence-manifest data_exports\source_qa_evidence_manifest.json --require-evidence-manifest
.\.venv\Scripts\python.exe examples\run_source_qa_preflight.py --checklist data_exports\data_source_qa.json --answers data_exports\data_source_qa_answers.json --evidence-manifest data_exports\source_qa_evidence_manifest.json --require-evidence-manifest --output-dir results\import\source_qa
```

The worksheet writes `data_source_qa_evidence_worksheet.json/csv/md`. It is a
fillable human evidence table, not an LLM prompt, not an answers generator, and
not a broker workflow. LLM output can discuss missing evidence and next
experiments, but it cannot replace source evidence, human signoff, deterministic
source QA, or any `PASS/WATCH/BLOCK` decision.

With `--require-evidence-manifest`, `write_data_source_qa_answers.py` writes a
temporary answers file, runs strict source QA against retained local attachment
hashes, and commits `data_source_qa_answers.json` only if that review is not
`BLOCK`.

LLM For Quantify 的 v2 目标不是“AI 自动炒股”,而是“AI 辅助研究审查与模拟盘准备”。系统可以读取一次研究报告,先给出确定性的 PASS / WATCH / BLOCK,再可选调用 OpenAI-compatible LLM 生成 advisory 叙事审查。

## 现有开源方向

可以参考这些路线:

- FinGPT: 金融大语言模型和金融 NLP 任务,适合情绪、新闻、公告、问答等文本能力。
- Microsoft Qlib: AI-oriented 量化投资平台,适合机器学习因子、模型训练、研究流水线。
- FinRobot: 金融 AI Agent 平台,偏财报分析、估值、风险评估和自动化研究。
- TradingAgents: 多智能体 LLM 金融交易框架,用分析师、研究员、交易员、风控等角色组织推理。

这些项目有启发价值,但对本项目最重要的原则是:

```text
先让 LLM 做副驾驶,不要让 LLM 直接接管方向盘。
```

## 本项目的实现边界

新增模块:

```text
src/quantify/llm/
  __init__.py
  client.py
  reviewer.py
```

新增命令:

```powershell
uv run python examples/run_llm_review.py --report-dir results/research/<timestamp>
```

它会在报告目录写入:

```text
llm_review.json  结构化审查结果
llm_review.md    人类可读审查报告
llm_prompt.md    可复制给外部 LLM 的严格提示词包
llm_narrative.md 可选 LLM 叙事审查
```

## 研究执行口径

研究回测采用明确的两阶段时序,不能把信号和成交都记在同一个收盘价上:

- 调仓日收盘后,使用当日收盘数据计算因子和目标组合,即
  `signal_timing=rebalance_day_close`。
- 订单在下一交易日开盘进入模拟成交,即
  `execution_timing=next_trading_day_open`;成交仍受滑点、涨跌停、停牌、现金和
  T+1 等模拟约束影响。

因此研究结果表示“调仓日收盘信号、下一交易日开盘模拟成交”,不是调仓日收盘即刻成交,
也不代表真实券商成交。

## 审查门含义

结果只有三个等级:

- `PASS`: 没有触发阻断或观察项,可以进入下一阶段审查。
- `WATCH`: 可以继续研究或模拟盘,但不应自动进入实盘。
- `BLOCK`: 不能升级,尤其不能连接真实券商或扩大资金。

当前检查包括:

- 是否使用 demo 数据。
- `run_manifest.data_version` 是否记录缓存导入版本、数据集指纹或来源审计元数据；
  缺失时 research/paper 至少为 `WATCH`，进入 `micro_live_ready` 及以后为
  `BLOCK`。
- 是否记录合法、互不重叠的样本内/样本外验证窗口。
- paper-stage 是否存在实际的 `walk_forward_report.json` 或
  `candidate_walk_forward_report.json`,且至少一个有效窗口从
  `out_sample_start` 当日或之后开始。只在 `summary.json` 填写日期不再足够。
- 回测长度是否过短。
- 最大回撤是否超过阈值。
- 扣费后收益是否为正。
- 夏普是否过低。
- 订单拒单率是否过高。
- 换手率是否过高。
- 因子 RankIC 样本数和均值是否可靠。
- 缺少哪些关键证据。
- 下一轮应该补做哪些实验。

## 推荐流程

先跑研究:

```powershell
uv run python examples/run_research.py --config config/research.yaml
```

然后对最新报告做审查:

```powershell
uv run python examples/run_llm_review.py --report-dir results/research/<timestamp> --stage paper
```

paper-stage 要求样本外证据落到实际 walk-forward 报告中。仅填写
`in_sample_end` 和 `out_sample_start`、但缺少上述报告或报告没有覆盖
`out_sample_start` 的有效窗口时,确定性审查不能 PASS,会给出
`MISSING_OUT_OF_SAMPLE_RESULTS` 并保持 `WATCH`。进入 `micro_live_ready`、
`micro_live` 或 `live` 时,同一缺口会升级为 `BLOCK`。

审查结果中的 paper 允许动作只指本地
`paper_trading_without_broker_credentials`。它不允许配置真实 broker 凭据、发送真实订单
或绕过 first-million/weekly 的确定性门。

如果想审查是否进入小额实盘准备门:

```powershell
uv run python examples/run_llm_review.py --report-dir results/research/<timestamp> --stage micro_live_ready
```

只要报告使用的是 demo 数据,`micro_live_ready`、`micro_live` 和 `live` 默认会被 `BLOCK`。

## 如何接入真正的 LLM

默认不会调用外部模型。你可以继续把 `llm_prompt.md` 发给 OpenAI、DeepSeek、Qwen、本地 Ollama 或其他模型。也可以配置 OpenAI-compatible 接口,让命令自动生成 advisory 叙事审查:

```powershell
$env:OPENAI_API_KEY="..."
$env:OPENAI_BASE_URL="https://api.openai.com/v1"
$env:OPENAI_MODEL="gpt-4o-mini"
uv run python examples/run_llm_review.py --report-dir results/research/<timestamp> --stage paper --call-llm
```

可选参数:

```powershell
uv run python examples/run_llm_review.py `
  --report-dir results/research/<timestamp> `
  --stage paper `
  --call-llm `
  --model gpt-4o-mini `
  --llm-output llm_narrative.md
```

如果没有配置 `OPENAI_API_KEY`,或模型请求失败,命令仍会完成确定性审查,并把错误写进 `llm_narrative.md`。提示词已经要求模型:

- 不能升级 deterministic gate 的结论。
- 必须区分证据和猜测。
- 必须输出风险、缺失证据、下一步实验。
- 不能给个性化投资建议。
- 不能建议绕过风控或直接实盘。

当前 provider 流程:

```text
Research Report -> Deterministic Gate -> PromptPack -> LLMClient -> LLMNarrativeReview
```

`LLMNarrativeReview` 只作为 advisory 输出。deterministic gate 仍然必须保留在 LLM 前面。

## 下一步路线

建议按这个顺序推进:

1. 完成真实 A 股数据缓存和数据质量审计。
2. 持续积累覆盖样本外区间的 walk-forward 与候选 walk-forward 证据。
3. 给 `llm_review` 增加参数扰动、压力测试和成交质量检查。
4. 增加人工审批记录。
5. 建立模拟盘连续运行日志。
6. 最后才考虑券商模拟盘或小额实盘接口。

真正的 LLM For Quantify 应该像一个严厉的风控同事: 它帮你想清楚,但不能替你按下买入键。

长期执行路线见 [07_长期执行Goal.md](07_长期执行Goal.md)。
