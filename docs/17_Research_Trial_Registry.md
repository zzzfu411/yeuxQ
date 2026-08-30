# Research Trial Registry

## 目的

Research Trial Registry 用于在实验开始前固定研究假设、候选策略、输入指纹和样本边界，并在实验结束后追加结果。它是研究审计记录，不是策略晋级证明、交易信号或实盘授权。

Registry 采用 UTF-8 canonical JSONL。每一行都是独立事件，包含严格递增的 `sequence`、上一事件的 `previous_hash` 和当前事件的 `event_hash`。哈希算法固定为 SHA-256。

操作入口只有三个子命令：

- `preregister`：追加 preregistration 事件。
- `record-result`：向已经注册的 trial 追加 result 事件。
- `verify`：验证完整文件、事件顺序和哈希链。

没有 update、edit、delete、replace 或 backfill 命令。历史行不得重写。

## Preregister Payload

所有业务输入从 UTF-8 JSON 文件读取。命令行只传 registry 路径和 payload 文件路径，不在命令行中展开复杂边界或结果对象。

示例 `trial-preregistration.json`：

```json
{
  "trial_id": "trial-001",
  "candidate": "momentum",
  "hypothesis": "Positive twelve-month returns persist over the test window.",
  "parameter_fingerprint": "parameters-sha256-001",
  "data_fingerprint": "data-sha256-001",
  "config_fingerprint": "config-sha256-001",
  "train_boundary": {
    "start": "2020-01-01",
    "end": "2023-12-31"
  },
  "selection_boundary": {
    "start": "2024-01-01",
    "end": "2024-12-31"
  },
  "test_boundary": {
    "start": "2025-01-01",
    "end": "2025-12-31"
  },
  "created_at": "2026-07-16T09:00:00+00:00",
  "prohibited_live_use": true
}
```

`prohibited_live_use` 必须在文件中明确存在，并且必须是 JSON boolean `true`。缺失、字符串 `"true"` 或 boolean `false` 都会失败。CLI 不会代替操作者静默补充这个声明。

Payload 字段必须与命令 schema 完全一致。以下链字段由 registry 自己生成，不能放入输入文件：

- `schema_version`
- `sequence`
- `event_type`
- `hash_algorithm`
- `previous_hash`
- `event_hash`

执行：

```powershell
.\.venv\Scripts\python.exe examples\run_trial_registry.py preregister `
  --registry results\research\trial_registry.jsonl `
  --payload trial-preregistration.json
```

相同 `trial_id` 不能再次 preregister。若已有文件无法通过完整验证，新事件不会追加。

## Record Result Payload

示例 `trial-result.json`：

```json
{
  "trial_id": "trial-001",
  "result_id": "trial-001:final",
  "result": {
    "decision": "PASS",
    "metrics": {
      "sharpe_ratio": 1.25,
      "max_drawdown": -0.12
    },
    "artifact_fingerprints": {
      "run_manifest.json": "<sha256>",
      "robustness_report.json": "<sha256>",
      "walk_forward_report.json": "<sha256>",
      "candidate_walk_forward_report.json": "<sha256>",
      "candidate_selection.json": "<sha256>",
      "selection_evidence_manifest.json": "<sha256>"
    }
  },
  "created_at": "2026-07-16T10:00:00+00:00"
}
```

`result_id` 可省略；省略时使用 `<trial_id>:result`。若一个 trial 确实需要保留多个结果事件，每个结果必须提供不同的 `result_id`，并按 `created_at` 非递减顺序追加。

执行：

```powershell
.\.venv\Scripts\python.exe examples\run_trial_registry.py record-result `
  --registry results\research\trial_registry.jsonl `
  --payload trial-result.json
```

`record-result` 只能关联文件中已经出现的 preregistration。registry 不存在、trial 未注册、结果 ID 重复、结果时间早于注册时间或原文件验证失败时，命令返回非零且不追加事件。

## Verify

执行：

```powershell
.\.venv\Scripts\python.exe examples\run_trial_registry.py verify `
  --registry results\research\trial_registry.jsonl
```

验证成功时，stdout 输出单行机器可读 JSON：

```json
{
  "command": "verify",
  "event_count": 2,
  "hash_algorithm": "sha256",
  "last_event_hash": "<64 lowercase hexadecimal characters>",
  "preregistration_count": 1,
  "registry_path": "results\\research\\trial_registry.jsonl",
  "result_count": 1,
  "schema_version": 1,
  "status": "PASS",
  "trial_count": 1,
  "trial_ids": [
    "trial-001"
  ],
  "valid": true
}
```

验证范围包括：

- 文件必须以完整换行结束，截断的最后一行失败。
- 每行必须是 canonical JSON object，不允许空行、重复 key、NaN 或 Infinity。
- schema、事件字段、ID 和带时区的 `created_at` 必须有效。
- `sequence` 必须与物理行顺序一致。
- `previous_hash` 必须连接上一行，首行必须连接 genesis hash。
- `event_hash` 必须匹配该行 canonical payload 的 SHA-256。
- preregistration ID、result ID 和 trial/result 顺序必须有效。

篡改、截断、不规范 JSON 或不存在的 registry 都返回非零。失败的 `verify` 仍在 stdout 输出单行 JSON，其中 `status` 为 `FAIL`、`valid` 为 `false`，并提供 `error_type` 和 `error`。不要仅检查文本；自动化调用方必须同时检查进程退出码。

## Payload 拒绝规则

两个写入命令都会拒绝：

- 顶层不是 JSON object 的文件。
- NaN、Infinity、`-Infinity` 和重复 JSON key。
- 缺失字段或命令 schema 之外的字段。
- 不符合底层 registry schema 的 ID、时间戳、边界和结果对象。
- 调用者提供的链元数据或历史定位字段。

这意味着不能通过 payload 指定旧 `sequence`、伪造 `previous_hash`，也不能把新事件插入文件中间。

## 退出码与输出

- `0`：事件已追加，或 registry 验证通过。
- `1`：payload、I/O、顺序、重复、未知 trial 或完整性验证失败。
- `2`：argparse 用法错误，例如未知子命令或缺少必需参数。

`preregister` 和 `record-result` 成功时在 stdout 输出 `status=APPENDED` 及完整事件。它们的操作失败摘要写入 stderr。`verify` 的成功和失败摘要都写入 stdout，便于监控程序只解析一个通道。

## 下游 Trial Registry Review

Registry 验证通过并不代表当前报告目录与某个预注册 trial 相符。下游审查器会把已验证的 registry 事件与当前 run artifacts 做字节级绑定：

```powershell
.\.venv\Scripts\python.exe examples\run_trial_registry_review.py `
  --registry results\research\trial_registry.jsonl `
  --report-dir results\research\<run-dir>
```

默认从 `candidate_selection.json` 的 `selected_candidate` 读取候选。也可以显式传入：

```powershell
.\.venv\Scripts\python.exe examples\run_trial_registry_review.py `
  --registry results\research\trial_registry.jsonl `
  --report-dir results\research\<run-dir> `
  --selected-candidate locked_candidate
```

审查顺序如下：

1. 完整验证 registry canonical JSONL、事件顺序和 SHA-256 hash chain。
2. 找到 `candidate` 等于当前 selected candidate 的 preregistration，以及同一 `trial_id` 的后续 result。
3. 要求 preregistration 的 `config_fingerprint` 等于 `run_manifest.json.config_sha256`。
4. 要求 `data_fingerprint` 等于 `cache_sha256`，或等于 `data_version` 明确记录的 `cache_logical_bar_fingerprint`、`csv_dataset_fingerprint`、`raw_vendor_bars_sha256` 之一。
5. 验证 preregistration 早于 `run_manifest.created_at_utc`，result 不早于该 run manifest，阻止事后结果冒充预注册证据。
6. 验证 result 中的 candidate 身份及所有当前 artifact SHA-256。

可验证的边界锚点为：

- `train.start == run_manifest.start`
- `selection.end == run_manifest.in_sample_end`
- `test.start == run_manifest.out_sample_start`
- `test.end == run_manifest.end`
- train、selection、test 各自有效，并按时间严格有序、互不重叠。

Result 的 `artifact_fingerprints` 至少必须绑定：

- `run_manifest.json`
- `robustness_report.json`
- `walk_forward_report.json`
- `candidate_walk_forward_report.json`
- `candidate_selection.json`
- `selection_evidence_manifest.json`

如果报告目录已经存在 `multiple_testing_report.json` 或 `benchmark_report.json`，它们也立即成为必需绑定。每个 fingerprint 是对应文件原始 bytes 的 lowercase SHA-256，不是格式化后的 JSON hash。

审查总会写出：

- `trial_registry_review.json`
- `trial_registry_review.md`

报告包含 `artifact_type=trial_registry_review`、schema version、registry 文件 SHA-256、已验证 tail hash、匹配的 trial/result ID、逐文件证据绑定和 blockers。`can_upgrade_deterministic_gate` 永远是 `false`；PASS 只表示当前证据与预注册记录一致，不会升级任何确定性 gate。

审查内容得到 BLOCK 时，CLI 仍写出完整 BLOCK 报告并返回 `0`，便于流水线保留审计产物。registry 或 report 参数路径不存在、类型错误等命令用法问题由 argparse 返回非零。缺失、哈希不匹配、JSON 损坏、registry 篡改和事后未注册都只能 BLOCK；审查器不提供伪造、回填或修改历史的修复命令。

## 完整性事件处理

发现篡改或截断后：

1. 停止追加，不要删除、截断、格式化或手工修复原文件。
2. 保留原始 bytes、文件元数据和失败摘要用于审计。
3. 从独立保存且已经核对尾哈希的完整副本恢复到新路径。
4. 对恢复副本再次运行 `verify`，再决定是否继续研究记录。

SHA-256 哈希链用于发现历史 bytes、顺序和链接变化；它不等同于数字签名。需要跨主机证明来源时，应在独立可信系统保存尾哈希或对归档文件签名。

## 研究与实盘边界

Registry 只保存 preregistration 和研究结果。它不连接 broker，不提交订单，不读取或改变实盘状态，也不授予任何 live use 权限。`prohibited_live_use=true` 是强制审计声明，不能被 result 事件覆盖。
