# Selection-Safe Walk-Forward v2

## 目的

本协议防止两类常见回测泄漏：

1. 用 test 窗的结果选择 test 窗赢家。
2. 把缺少时间隔离证明的旧 `PASS` 报告继续用于 paper 或晋级。

它不会证明策略未来盈利，也不会把研究结果变成实盘指令。真实 broker、自动下单和
LLM 越权仍被禁止。

## 五段时间顺序

每一折必须按交易日严格排列：

```text
train -> purge -> selection -> embargo -> test
```

- `train`: 形成候选及历史训练证据。
- `purge`: 隔离 train 与 selection 的相邻标签或持有期影响。
- `selection`: 在 test 开始前完成候选排名和锁定。
- `embargo`: 隔离 selection 与 test。
- `test`: 只验证已锁定候选，只能降级，不能改选赢家。

支持两种训练窗：

- `expanding`: train 起点固定，终点逐折扩展。
- `rolling`: train 长度固定，起点逐折移动。

`step_days` 必须大于或等于 `test_days`，否则 test 窗重叠，入口直接报错。

## 候选锁定

每一折对所有候选只使用 train 和 selection 指标排序。rank 1 候选在 test 开始前
锁定，test 只运行这个候选。

报告保留两个不同概念：

- `selected_candidate`: 最新一折在 test 前锁定的候选，是唯一可被下游继续审查的
  候选身份。
- `top_candidate`: 其他研究排名第一名，只用于诊断，不能覆盖
  `selected_candidate`。

若锁定候选在 test 中失败，结果必须降级为 `WATCH` 或 `BLOCK`；系统不得改用另一
个在同一 test 窗表现更好的候选。

## 完整 v2 合同

`walk_forward_report.json` 与 `candidate_walk_forward_report.json` 只有同时满足以下
条件，才属于 selection-safe 证据：

- `artifact_type` 与文件类型一致。
- `schema_version == 2`。
- `selection_protocol == "quantify.walk-forward-selection.v2"`。
- `selection_safe is true`，必须是 JSON boolean。
- `test_used_for_selection is false`。
- `configuration` 含 mode 和六个阶段/步长参数。
- `window_count` 与实际 windows 数量一致。
- 每折阶段边界有序，test 窗不重叠。
- candidate 报告每折均有完整的 pretest 排名，test 候选必须等于 rank 1。

只写入 `{"selection_safe": true}` 不构成证据。缺字段、字符串 `"true"`、旧 schema、
错误协议名、阶段重叠、排名缺失或候选不一致都会 fail closed。

## 旧报告处理

旧报告不会被删除，也不会被伪造补写。它们仍可用于研究历史展示，但按
`selection_safe=false` 处理，并被以下链路阻断：

- candidate selection
- candidate experiment evidence/execution/completion
- paper candidate plan
- weekly/goal status
- LLM deterministic review
- strategy registry 与 promotion review
- micro-live readiness

registry 只累计同时满足数据 provenance attestation 和完整 selection-safe 合同的
非 demo 观察。旧观察保留，但计入排除统计。

## Robustness v2 合同

`robustness_report.json` 使用
`quantify.robustness-selection.v2`。标准场景矩阵必须在任何测试结果产生前冻结，且
至少包含：

- `baseline`
- `holdings_low`
- `holdings_high`
- `max_weight_low`
- `rebalance_alt`
- `high_cost`

每一个场景都必须在每一折的 test 阶段运行。test 结果不能删除场景、改变场景顺序
或选择压力测试赢家。完整合同还会核验：

- `configuration` 与五阶段窗口计数。
- `fold_count`、`scenario_count` 与实际行数一致。
- 每折 test 窗不重叠。
- 每折场景名称与冻结矩阵完整同序。
- 聚合场景与冻结矩阵完整同序。
- `baseline_scenario == "baseline"`。

没有完整 test fold 时固定 `BLOCK`；只有 1-2 个完整 folds 时，即使所有场景通过，
总结果最多为 `WATCH`；至少 3 folds 才可能 `PASS`。`high_cost` 在原配置成本为零时
仍会使用非零佣金、最低佣金、印花税和滑点底线。

CLI 可以用 `--scenario` 跑研究诊断子集，但缺少任一标准场景时
`selection_safe=false`，不能进入 paper、readiness 或 registry 晋级证据。旧的
full-sample robustness 报告继续保留为历史记录，并由完整 v2 验证器 fail closed。

## 命令

```powershell
.\.venv\Scripts\python.exe examples\run_walk_forward.py `
  --config config\research.yaml `
  --output-dir results\research\<timestamp> `
  --mode expanding `
  --train-days 120 --purge-days 5 --selection-days 20 `
  --embargo-days 5 --test-days 60 --step-days 60

.\.venv\Scripts\python.exe examples\run_candidate_walk_forward.py `
  --config config\research.yaml `
  --output-dir results\research\<timestamp> `
  --mode rolling `
  --train-days 120 --purge-days 5 --selection-days 20 `
  --embargo-days 5 --test-days 60 --step-days 60

.\.venv\Scripts\python.exe examples\run_robustness.py `
  --config config\research.yaml `
  --output-dir results\research\<timestamp> `
  --mode expanding `
  --train-days 120 --purge-days 5 --selection-days 20 `
  --embargo-days 5 --test-days 60 --step-days 60
```

weekly pipeline 提供对应的 `--wf-mode`、`--wf-train-days`、`--wf-purge-days`、
`--wf-selection-days`、`--wf-embargo-days`、`--wf-test-days` 和
`--wf-step-days`。

## 已知研究限制

- 截至 2026-07-14 的既有样本已被多轮候选研究使用，仍是受污染开发样本，不能
  重新命名为独立 holdout。
- `top_candidate` 只能作为研究诊断，不得进入 paper 或人工交易参考表。
- 新生成的完整 robustness v2 报告可作为 selection-safe 候选证据，但不能覆盖数据
  provenance、其他确定性门或人工审批。
- PIT 股票池、真实且经复核的 CSI 800 全收益输入和独立新 holdout 仍未到位。
  benchmark、DSR/PBO 与 trial-registry 报告代码已经接入门禁，但没有这些外部证据时
  必须继续 BLOCK，不能用开发样本生成伪 PASS。
