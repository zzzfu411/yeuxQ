# 06 LLM For Quantify

## Source Evidence Boundary

Before LLM advisory review can be useful, the data source must have auditable
evidence. Use the source-QA worksheet to collect real vendor/export facts before
writing `data_source_qa_answers.json`:

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

## 审查门含义

结果只有三个等级:

- `PASS`: 没有触发阻断或观察项,可以进入下一阶段审查。
- `WATCH`: 可以继续研究或模拟盘,但不应自动进入实盘。
- `BLOCK`: 不能升级,尤其不能连接真实券商或扩大资金。

当前检查包括:

- 是否使用 demo 数据。
- 是否记录样本内/样本外验证窗口。
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
2. 把研究报告拆成样本内、样本外和滚动窗口。
3. 给 `llm_review` 增加参数扰动、压力测试和成交质量检查。
4. 增加人工审批记录。
5. 建立模拟盘连续运行日志。
6. 最后才考虑券商模拟盘或小额实盘接口。

真正的 LLM For Quantify 应该像一个严厉的风控同事: 它帮你想清楚,但不能替你按下买入键。

长期执行路线见 [07_长期执行Goal.md](07_长期执行Goal.md)。
