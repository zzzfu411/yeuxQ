# ADR-0001：统一 yeuxQ 架构与 stock_v2 迁移边界

- 状态：Accepted
- 日期：2026-08-30
- 决策者：yeuxQ maintainers
- 适用仓库：`https://github.com/zzzfu411/yeuxQ`
- 关联计划：`docs/30_Stock_Integration_Plan.md`
- 关联状态：`integration/integration_status.json`

## Context

现有 `quantify` 是证据驱动的 A 股研究与模拟系统，重点在数据 provenance、可复现实验、
holdout、walk-forward 和确定性晋级门。`stock_v2` 是本地 FastAPI 技术分析工作台，拥有
实时行情观察、技术指标、扫描、看板、智能研报和可选 Rust 计算核。v4 发行包是更早的
许可绑定实现。

直接拼接会产生四个不可接受的问题：

1. 两套数据缓存、两套回测和两套风险词汇会形成多个真相源；
2. 实时 provider 数据可能绕过 quantify 的 source QA/lineage/fingerprint；
3. trade plan、预测和实时资金流容易被 UI 或调用方理解成实盘指令；
4. donor 的整体许可、真实凭据和 v4 的发行材料不能安全地直接公开。

因此，集成首先是“权威边界和数据身份”的设计问题，而不是复制文件的问题。

## Decision drivers

- 保持 `PASS/WATCH/BLOCK` 和研究证据链的唯一权威；
- 保证实时 observation 可以使用但不能污染研究；
- 让 donor 能按组件迁移，并可随时回滚；
- 默认离线、本地、无券商、无自动执行；
- 对来源、许可证、秘密和第三方依赖可审计；
- 前端与实际完成状态一致；
- Python 路径始终可用，Rust 只做可选优化；
- 在最小运维复杂度下提供统一 UI/API。

## Decision

### 1. 单一 canonical repository

`D:\Develop\claude\quantify`（GitHub `zzzfu411/yeuxQ`）是唯一 canonical repository。
所有新提交、CI、发布、issue 和文档只在这里维护。

`D:\Develop\grok\stock\stock_v2` 被标记为 donor：它不作为 submodule、不合并 Git 历史、
不在两个目录同时开发。组件迁移完成后 donor 保持只读 provenance。

v4 被标记为 reference-only：不进入源树、不进入构建上下文、不进入测试 fixture，且扫描规则
应阻止其许可证、zip、vendored libs 和资源误提交。

### 2. 模块化单体，而不是双服务

第一版采用一个 Python 环境和一个 FastAPI shell：

- `src/quantify` 是研究安全内核；
- `src/yeuxq` 是集成合同、observation、API 和 UI shell；
- 两者通过公共 DTO/facade 调用，不共享内部 ORM/model；
- observation storage 与 research storage 物理分离；
- Rust 核通过 adapter 加载，失败时使用 Python fallback。

这保留清晰边界，同时避免网络 RPC、两个部署单元和分布式事务。只有在测量证明单体无法满足
吞吐或隔离需求后，才另写 ADR 拆服务。

### 3. 实时数据定义为 observation

任何来自 quote、minute、orderflow、book、block trade 或实时 provider 的数据，默认身份都是
`TrendObservation`。合同与 canonical serialization 位于 `src/yeuxq/contracts.py`；
append-only 哈希链存储位于 `src/yeuxq/observation_store.py`。

合同固定安全属性：

- `prohibited_live_use=true`；
- `broker_access=false`；
- `live_trading_allowed=false`；
- advisory/research-only，不是订单或持仓指令。

写入 observation store 不会把它变成研究数据。store 必须拒绝重复 observation ID、非法路径、
记录篡改和断裂的 `prev_hash`/`record_hash` 链。

### 4. 研究数据和晋级门保持 canonical

只有 `src/quantify` 的 reviewed import、lineage、fingerprint、实验和 gate 可以产出发布证据。

- observation API 不写 research DB；
- UI 不直接修改 gate；
- donor 技术评分、点时回测和 LLM 输出只能 advisory；
- 未来 observation-to-research promotion 必须是独立命令、独立批次和独立 ADR，默认不存在；
- 任一缺失/冲突/无法验证状态按 fail closed 处理。

### 5. API 与 UI 是投影，不是真相源

FastAPI 路由只读取 service/facade：

- observation 路由投影 observation store；
- research 路由只读投影 quantify 报告和 gates；
- integration status 路由只读投影 `integration/integration_status.json`；
- 不提供 account、broker、order、cancel 或 live-execution 路由。

UI 必须区分：

1. 实时观察及其 staleness；
2. 研究证据及其 `PASS/WATCH/BLOCK`；
3. paper simulation；
4. 人工决定。

UI 不得把四者合并成单一“买卖”颜色或按钮。

### 6. 迁移采用 allowlist + clean-room

每个 donor 组件必须先分类：

- `adopt`：许可与来源清晰，可保留必要 notices 后迁移；
- `rewrite`：按接口、行为和测试 clean-room 重写；
- `reject`：秘密、数据、产物、危险或重复能力，不迁移；
- `reference`：仅用于需求比对，不复制表达性实现。

在 donor 整体许可证未解决时，默认是 `rewrite` 或 `reject`，不是 `adopt`。第三方 web 依赖
单独核对许可证；项目本身的 LICENSE 由用户明确选择，agent 不代替权利人决定。

### 7. 状态 JSON 是集成 UI 的单一真相源

`integration/integration_status.json` 使用版本化结构和有限状态枚举。阶段完成必须有时间和
证据；P0 风险开放时 release readiness 必须是 `BLOCK`。UI 只读，不自行修改或推断状态。

每个可验收工作包在同一提交中完成：实现、测试、证据、状态更新。若 JSON 缺失、损坏、版本
不支持或与证据矛盾，UI 显示“状态不可验证”，不显示成功。

## Rejected alternatives

### A. 将 stock_v2 整目录复制进 canonical

拒绝。会带入真实秘密、数据库、报告、构建产物、重复缓存、许可不清文件和两个包的历史债务，
也无法证明哪些能力真正通过了 canonical gate。

### B. 保持两个独立服务，通过 HTTP 互调

当前拒绝。会过早引入服务发现、认证、版本漂移、端口冲突、双配置和跨服务故障。模块化单体
足以承载当前本地工作台。将来可依据测量结果另写 ADR。

### C. 让 donor 的 SQLite 成为统一数据库

拒绝。donor cache 不具备 source QA、atomic import、lineage 和 fingerprint；将其设为研究
真相源会降低现有证据标准。

### D. 把实时 observation 自动沉淀为历史研究数据

拒绝。实时数据的许可、完整性、复权、交易日历、缺失、provider fallback 和 as-of 语义未被
研究合同验证。自动沉淀会造成数据污染、幸存者偏差或虚假的独立 holdout。

### E. 让 Rust core 成为强依赖

拒绝。会增加工具链、平台和构建失败面，并可能掩盖 Python/Rust 指标漂移。只有 parity 和许可
通过后才作为可选优化。

### F. 复用 v4 页面与许可机制

拒绝。v4 的再分发权不清晰，且激活/许可证逻辑与公开 research-only 项目目标无关。只允许从
抽象行为编写新的需求和测试。

### G. 增加 broker/order 接口但默认关闭

拒绝。隐藏或默认关闭的实盘路径仍扩大风险和误用面，也与当前 research-only 目标冲突。如未来
确有需求，必须单独 threat model、权限体系、人工审批和新 ADR。

## Consequences

### Positive

- 研究证据标准不会被实时便利性稀释；
- donor 可以按小步、可测试、可回滚的工作包迁移；
- UI 能同时展示实时能力和证据状态而不混淆；
- 秘密、许可证和运行数据更难误入公开仓库；
- Python fallback 保证本地安装和 CI 可用；
- 单一仓库和状态源降低维护与发布歧义。

### Negative / costs

- clean-room 重写比整树复制慢；
- 需要维护 adapter、合同和更多反向安全测试；
- observation 与 research 可能暂时重复保存部分字段；
- donor 现有页面和 API 不能保证 1:1 兼容；
- Rust 优化、智能研报和高级 orderflow 会后置；
- 整体 LICENSE 与 donor 权利确认需要用户/权利人参与。

## Invariants

以下不变量在后续 ADR 中只能被更严格化，不能被普通功能提交绕过：

1. canonical repo 唯一；
2. v4 reference-only；
3. secrets、license material、local DB/report/build artifact 不进入 Git；
4. observation 与 research storage 分离；
5. observation 不自动成为 research evidence；
6. canonical gate 唯一有权发布 `PASS/WATCH/BLOCK`；
7. LLM、技术评分、donor backtest 不能升级 gate；
8. `prohibited_live_use=true`、`broker_access=false`、
   `live_trading_allowed=false`；
9. 无 broker/order/account/live-execution 能力；
10. 状态缺失或冲突时 fail closed。

## Verification

至少用以下测试守护本 ADR：

- contracts：枚举、symbol、timezone、canonical hash 和固定安全字段；
- observation store：append、重复、篡改、断链、路径越界和恢复；
- boundary：observation API 无 research write；LLM/score 不可升级 gate；
- provenance：donor allowlist、secret scan、artifact denylist、third-party notices；
- API：schema snapshot、错误 envelope、报告路径 allowlist、无 order/account endpoints；
- UI：source/time/stale/unavailable/research-only 和 gate 分栏；
- Rust：Python parity 与缺少扩展时 fallback；
- release：clean checkout、全量测试、状态 JSON、HEAD/remote SHA 一致。

## Follow-up decisions

需要后续独立 ADR 的事项：

- 项目整体 LICENSE 的用户选择与 donor 权利确认；
- observation-to-research 显式提升流程（如确实需要）；
- Rust core 的来源、许可证和支持平台；
- 是否在测量后拆分 API/worker 服务；
- 任何超出 research-only 的 broker 或执行能力。当前不授权这些事项。
