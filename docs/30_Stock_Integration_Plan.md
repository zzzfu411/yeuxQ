# yeuxQ × stock_v2 集成与完善计划

> 状态：执行中
> 计划基线：2026-08-30
> Canonical repository：`D:\Develop\claude\quantify` / `https://github.com/zzzfu411/yeuxQ`
> Donor：`D:\Develop\grok\stock\stock_v2`
> Reference-only：`D:\Develop\grok\stock\趋势分析实时买卖点工具-v4.0-发行版`
> 机器可读进度：`integration/integration_status.json`

## 1. 结论先行

两个项目采用“**单一 canonical 仓库 + donor 逐组件迁移 + 契约隔离**”的方式集成，
不做目录覆盖、全量复制或 Git 历史拼接：

- `quantify/yeuxQ` 是唯一 canonical repository、唯一发布源和唯一问题追踪入口；
- `src/quantify` 继续作为研究数据、可复现实验、回测、证据链和
  `PASS/WATCH/BLOCK` 晋级门的权威实现；
- `stock_v2` 仅作为 FastAPI、实时行情观察、技术分析、可视化和可选 Rust 计算核的
  donor；每个组件必须经过许可证、秘密、数据语义和测试审查后再迁移；
- 新的集成边界放在 `src/yeuxq`。实时数据先进入 append-only observation 合同，
  **不会自动成为研究数据或晋级证据**；
- v4 发行版存在许可证文件、签发程序、打包依赖和来源/再分发权不清晰的问题，
  因此只能用于需求与行为对照，不复制代码、页面、二进制、数据或授权材料；
- 系统保持 research-only / advisory-only：不接券商、不读取交易账户、不自动下单，
  不把“预测”“交易计划”“实时资金流”包装成实盘授权或投资建议。

初始仓库审计和 Phase 1 架构/合同/合规基线已经完成：核心合同、observation store、
fail-closed secret scan、双包构建与前端只读状态投影均已通过验收。项目 LICENSE 选择和
donor 中两项凭据轮换仍是最终发布阻塞项，但不再阻塞受控的本地迁移。此处的“完成”只表示
边界与工程基线可执行，不表示 donor 已获得第三方再分发许可，也不表示任何策略、数据源或
实盘能力通过验证。

## 2. 项目目标与成功标准

### 2.1 目标

1. 在 yeuxQ 中提供一个统一的、本地优先的研究工作台；
2. 保留 quantify 已有的证据治理、试验治理和 fail-closed 晋级门；
3. 吸收 stock_v2 的看板、FastAPI 服务、技术指标、扫描和实时观察能力；
4. 用明确合同隔离实时 observation、研究数据、研究结果和人工决策；
5. 让前端能从一个机器可读状态源展示每个集成阶段、风险和阻塞项；
6. 最终只从 `zzzfu411/yeuxQ` 构建、测试和发布。

### 2.2 集成完成的硬标准

- canonical 仓库从干净环境可安装、可启动、可运行全部测试；
- donor 迁移清单中的每个文件都有 `adopt/rewrite/reject/reference` 处置记录；
- v4 发行版没有任何源码、静态资源、许可证、密钥、数据库或 vendored library
  被带入 Git；
- observation 合同固定声明 `prohibited_live_use=true`、`broker_access=false`、
  `live_trading_allowed=false`，并由测试锁定；
- observation 存储 append-only、哈希链可验证，篡改、重复 ID 和越界路径 fail closed；
- 实时数据不能绕过 source QA、许可证明、调整口径、交易日历、lineage 和 fingerprint
  进入 `src/quantify` 的研究缓存；
- donor 回测/技术评分不能覆盖或升级 canonical 的 `PASS/WATCH/BLOCK`；
- 前端始终展示来源、观测时间、接收时间、新鲜度、可用性和 research-only 提示；
- 不存在 broker SDK、订单端点、账户资产端点、自动交易开关或隐藏的 live-order 路径；
- secrets 扫描、第三方许可证检查、单元测试、合同测试、集成测试和离线启动测试通过；
- `integration/integration_status.json` 中所有必需阶段为 `completed`，P0 风险全部关闭；
- 本地 HEAD、`origin/main` 和发布证据中的提交 SHA 一致。

## 3. 已完成的仓库审计

### 3.1 Canonical：quantify / yeuxQ

当前 canonical 仓库的职责已经比较清晰：

- `src/quantify/data`：数据接入、存储、原子批次、lineage 和数据指纹；
- `src/quantify/research`：候选研究、walk-forward、稳健性、多重检验和试验登记；
- `src/quantify/engine`、`paper`、`risk`：事件驱动模拟、纸面执行和风险约束；
- `src/quantify/readiness`、`goal`、`audit`：确定性晋级门、目标状态和审计；
- `results`、`evidence`、`data_exports`：有明确来源与保留策略的研究工件。

这些能力是集成后不可被 donor 降级的“安全内核”。尤其禁止用一个实时技术评分、
一次点时回测或一个 LLM 结论替代完整的数据与研究证据链。

### 3.2 Donor：stock_v2

`stock_v2` 可贡献的能力包括：

- FastAPI 应用工厂、路由组织和静态看板服务；
- quote/kline/minute、market overview、资金流和 order-book observation；
- 趋势、动量、形态、突破、量价、缠论等技术分析；
- 单股分析、多股扫描、规则倾向和带成本的点时回测；
- SQLite K 线缓存、内存缓存和多 provider fallback；
- Rust `trendlab-core` 计算核及 Python fallback；
- YeuX/Grok 辅助研报工作流。

但 donor 不能直接整树复制，审计已发现以下高风险事实：

- 项目根没有可确认的整体再分发许可证；在权利未澄清前只能逐文件迁移或 clean-room
  重写；
- `config/intel.local.yaml` 含真实、非占位的 LLM/MCP 凭据；不得读取进输出、不得复制，
  必须轮换并由秘密扫描阻止再次提交；
- `data/*.db`、研报、`target`、`output`、`.playwright-cli`、`__pycache__` 等是本地或构建
  产物，不属于迁移输入；
- web vendor 依赖至少涉及 ECharts（Apache-2.0）、Marked（MIT）和 DOMPurify
  （Apache-2.0/MPL-2.0），必须保留版本、来源和第三方声明；
- donor 的 trade plan、规则预测和点时回测属于界面/研究辅助语义，不能升级为实盘建议；
- donor 的 SQLite 缓存没有 canonical 研究证据合同，不能直接并入研究数据库。

### 3.3 v4 发行版

v4 包含 `license.dat`、`gen_license.py`、激活流程、打包的第三方库、发行页面和运行数据。
当前没有足以支持公开仓库再分发的清晰权利链。因此它的唯一允许用途是：

- 比对公开可见的功能名称和交互流程；
- 提炼不受版权保护的抽象需求，例如“展示指标来源和时间”；
- 编写全新的验收测试与交互实现；
- 记录差异，不反编译、不绕过授权、不复用表达性代码或资源。

## 4. 目标架构

采用模块化单体，避免一开始引入两个独立服务、两个数据库真相源和分布式一致性问题：

```text
Browser / local UI
        |
        v
FastAPI shell (src/yeuxq)
  |-- Integration status (read-only)
  |-- Observation API -------- provider adapters / optional Rust kernel
  |                               |
  |                               v
  |                       append-only observation store
  |
  `-- Research API ---------- src/quantify facade
                                  |
                                  v
                  source QA -> lineage -> experiments -> gates
```

所有跨边界调用都经过显式 DTO/adapter，不允许 API 或页面直接导入 canonical 的内部数据库
对象。目标命名空间为：

- `src/quantify/**`：现有研究安全内核；
- `src/yeuxq/contracts.py`：SymbolId、TrendAction、TrendObservation 和 canonical hash；
- `src/yeuxq/observation_store.py`：append-only observation JSONL 与哈希链校验；
- `src/yeuxq/api/**`：后续 FastAPI shell 与版本化路由；
- `src/yeuxq/providers/**`：实时 provider adapter，只产出 observation；
- `src/yeuxq/web/**`：后续 clean-room UI；
- `crates/trendlab-core/**`：仅在来源与许可通过后迁移的可选优化；
- `integration/integration_status.json`：前端进度单一真相源。

详细决策见 `docs/adr/0001-unified-yeuxq-architecture.md`。

## 5. 两条数据通道的强制边界

### 5.1 实时 observation 通道

实时数据是对某一来源在某一时刻的“观察”，不是经过审查的研究证据。每条 observation
至少携带：

- schema version、稳定 observation ID；
- canonical symbol 与市场；
- provider/source identity；
- `observed_at` 与 `received_at`，且时区明确；
- 数据类型、payload、单位/口径；
- staleness、完整性、fallback 和错误状态；
- canonical JSON hash、前一条记录 hash 和当前记录 hash；
- `prohibited_live_use=true`、`broker_access=false`、
  `live_trading_allowed=false`。

实时接口的允许用途：看板展示、人工检查、技术分析演示、provider 健康检查和临时扫描。
实时数据不可因为“已写入本地”而改变身份；进入 observation store 后仍然是 observation。

### 5.2 research-only 通道

研究数据必须独立完成：

1. 数据来源和再使用许可审查；
2. 原始输入留存与 SHA-256；
3. 标的、时区、交易日历、复权、停牌、涨跌停和缺失值口径归一化；
4. 原子导入批次、行级 lineage 与逻辑数据指纹；
5. as-of、PIT 和 look-ahead 检查；
6. 预注册、冻结 holdout、walk-forward、稳健性与 benchmark 审查；
7. 确定性 `PASS/WATCH/BLOCK` 和人工审批。

从 observation 到 research 不提供隐式 adapter。未来若确需提升 observation，必须由一个
独立、显式、可审计的 promotion/import command 创建新研究批次；默认不存在该命令，
且 observation 的 hash 只能作为来源证据之一，不能代替上述审查。

### 5.3 UI 强制表达

任何实时页面必须同时显示：

- `来源 + observed_at + received_at + 新鲜度`；
- 数据不可用时显示 `unavailable`，不得用 0、空趋势或旧缓存伪装实时值；
- “仅供研究与观察，不构成投资建议，不连接券商，不自动下单”；
- 技术评分是规则倾向，不是历史胜率或已校准概率；
- 研究晋级状态与实时趋势信号分栏展示，颜色和词汇不得混用。

## 6. Donor 组件处置清单

| Donor 能力 | 目标处置 | 进入位置 | 前置条件 | 明确禁止 |
| --- | --- | --- | --- | --- |
| FastAPI app/routes | clean-room 重组 | `src/yeuxq/api` | 合同、错误模型、安全默认值 | 整树复制、无版本 API |
| Web dashboard | clean-room 重建 | `src/yeuxq/web` | 依赖许可清单、CSP/输入转义 | 复制 v4 页面或打包资源 |
| quote/kline/minute provider | adapter 后采用 | `src/yeuxq/providers` | 来源、限速、时区、新鲜度合同 | 写入研究 cache |
| orderflow/book/block | observation-only | `src/yeuxq/providers` | 能力检测、unavailable 语义 | 宣称 L2/暗盘或成交意图 |
| technical analysis | 逐模块移植/重写 | `src/yeuxq/analysis` | 黄金样本和等价性测试 | 用技术分数升级研究 gate |
| donor backtest | 仅作快速诊断 | adapter 或删除 | 与 canonical 指标差异说明 | 替代 canonical 回测 |
| SQLite kline store | 仅 observation cache | 独立存储 | schema/version/locking 测试 | 与 research DB 共表/共路径 |
| scan worker | 有界并发重写 | `src/yeuxq/services` | rate limit、取消、超时 | 无界扫描或静默 fallback |
| Rust core | 可选、后置 | `crates/trendlab-core` | 权利确认、Python parity、fallback | 成为启动硬依赖 |
| YeuX/Grok research | opt-in advisory | `src/yeuxq/intel` | secrets 注入、审计、引用 | 密钥入库、LLM 改 gate |
| v4 任意文件 | reference-only | 不进入仓库 | 无 | 复制、反编译、绕过 license |

## 7. 分阶段实施计划

状态只允许 `not_started`、`in_progress`、`completed`、`blocked`。每完成一个可验收工作包，
必须先完成测试与证据，再在同一提交中更新 `integration/integration_status.json`；前端只读
该文件对应的 API/静态投影，避免口头进度和真实仓库脱节。

### Phase 0 — Audit（已完成）

工作包：

- 固定 canonical、donor、reference-only 三种角色；
- 盘点 Python、Rust、前端、配置、数据库、构建产物和许可证文件；
- 找出 donor 的真实凭据文件和 v4 的授权/发行风险；
- 建立 adopt/rewrite/reject/reference 规则；
- 建立 P0/P1 风险登记和不复制清单。

验收：审计事实写入本计划和状态 JSON；`stock_v2`、v4 均未被整树复制；发现的秘密未出现在
日志、补丁或状态文件中。完成 Phase 0 不代表再分发许可已解决。

### Phase 1 — Contracts and compliance baseline（已完成）

验收结果：`src/yeuxq/contracts.py` 与 `src/yeuxq/observation_store.py` 已落盘；合同、存储、
secret scan 与状态 UI 共 51 个定向测试通过；原有与新增测试合计 1076 项通过；Ruff、格式、
diff check 和覆盖 521 个候选文件的 canonical secret scan 通过；wheel/sdist 构建成功且 wheel
同时包含 `quantify` 与 `yeuxq`；Playwright 在 1440×1000 与 390×844 视口验证页面无横向
溢出，正常状态控制台零错误，离线请求会把所有证据降为 BLOCK。donor 的 local intel 配置
单独扫描命中 2 项并完全脱敏；命中项不得迁移且必须轮换。整体 LICENSE 仍由用户选择，
未决定前最终发布门保持 BLOCK。

工作包：

- 实现 `SymbolId`、`TrendAction`、`TrendObservation`；
- 实现 deterministic canonical JSON/bytes/SHA-256；
- 实现 append-only JSONL、`prev_hash`/`record_hash` 链和全链验证；
- 拒绝重复 ID、篡改记录、非法枚举、naive datetime 和路径越界；
- 把 research-only 与 no-broker/no-live-trading 写入不可省略的合同字段；
- 建立 `.gitignore`、secret scanner、第三方 notices 和 donor 文件 allowlist；
- 定义 status JSON 的版本、枚举、阶段、风险、验收证据和 UI 刷新行为。

验收：合同与 store 单测通过；固定安全字段无法被调用者改为 false/true 的危险组合；秘密
扫描能命中 synthetic fixture 且仓库扫描为 PASS；整体 LICENSE 选择由用户明确决定，未决定前
发布门保持 BLOCK；状态 JSON 可被标准 JSON parser 读取。

### Phase 2 — Observation platform migration（进行中）

工作包：

- 在 `src/yeuxq/providers` 定义 provider protocol 和错误分类；
- 迁移 quote/kline/minute/market overview，统一 symbol、Asia/Shanghai、数值单位和时效；
- 把资金流、五档和大宗交易建模为可缺失 capability；
- 引入限速、重试上限、熔断、缓存 TTL 和 explicit stale；
- donor SQLite 与 canonical research storage 使用不同路径和 schema；
- Rust core 仅在权利通过后以 optional adapter 接入，并保留 Python fallback。

验收：离线 fixture、超时、限流、空响应、错误 schema、stale cache 和 provider fallback 测试
通过；任何运行路径都不能写入 research DB；网络关闭时 UI/API 明确降级而非伪造数据。

### Phase 3 — Unified API and research facade（未开始）

工作包：

- 创建 FastAPI application factory、版本化 observation/research/status 路由；
- 路由只依赖 service/facade 和公共 DTO，不导入数据库内部类型；
- 为 canonical 研究报告、gate 与 provenance 提供只读 facade；
- 分离实时趋势、研究证据、paper simulation 三类响应；
- 统一错误 envelope、request ID、超时、最大 payload 和安全 header；
- 禁止任意路径读取、任意 URL 代理和未经 allowlist 的报告文件访问。

验收：OpenAPI/contract snapshot、输入模糊测试、路径穿越测试和无网络启动测试通过；不存在
order/account/broker endpoint；实时 endpoint 响应固定含 advisory 边界。

### Phase 4 — Clean-room frontend and continuous UI status（未开始）

工作包：

- 在 canonical 仓库重建看板，不复制 v4 表达性页面；
- 迁移 donor 交互前先记录来源与第三方依赖；
- 增加“集成进度”页，读取 status JSON 投影，显示阶段、阻塞、P0/P1 和更新时间；
- 实现 observation 的来源/时间/新鲜度/unavailable 展示；
- 明确区分 observation signal、research gate 和 paper simulation；
- DOMPurify/Marked/ECharts 按确认许可证使用并保留 notices；
- 对研报 Markdown、symbol、文件名和 API 错误做输出编码。

验收：状态页与 JSON 一致；窄屏/桌面、空数据、stale、BLOCK、网络失败和长文本截图测试通过；
页面没有“立即买入/卖出”“胜率保证”“已接实盘”等误导性表述。

### Phase 5 — Research integration and regression hardening（未开始）

工作包：

- 用 adapter 将 observation 展示和 canonical 研究报告关联，但保持物理与权限隔离；
- 对 donor 技术指标建立黄金样本、浮点容差和 Python/Rust parity；
- 对重复回测能力做一主一辅裁决：canonical 是发布证据，donor 只允许诊断；
- 运行全量 tests、ruff、secret/license scan、dependency audit 和 hash-chain verify；
- 新增端到端用例：provider → observation → API → UI；
- 新增反向安全用例：observation 无法升级 gate、LLM 无法升级 gate、API 无法下单。

验收：原有 quantify 测试无回归；新增合同/集成测试通过；P0 风险关闭；P1 风险都有 owner、
期限或显式接受记录；关键结果包含可复查的命令、提交 SHA 和输出摘要。

### Phase 6 — Release, migration and deprecation（未开始）

工作包：

- 完成用户选择的项目 LICENSE 和第三方 notices；
- 提供单一安装、启动、配置、升级和回滚文档；
- 建立 GitHub Actions：lint、test、secret scan、license check、frontend smoke；
- 从干净 checkout 做 release rehearsal；
- 将 donor 设置为只读归档/迁移说明，保留 provenance，不删除原目录；
- 推送 canonical 分支、核对远端 SHA，再合并到 `main`。

验收：干净环境演练通过；所有阶段完成；P0 为 0；状态 UI 显示完成且提交 SHA 与远端一致；
旧 donor 不再接受功能变更。

## 8. 风险登记

### 8.1 P0：发布或安全硬阻塞

| ID | 风险 | 当前状态 | 关闭条件 |
| --- | --- | --- | --- |
| P0-01 | donor 整体许可证缺失，公开再分发权不清 | open | 用户/权利人确认，或仅 clean-room 重写并保留逐文件 provenance |
| P0-02 | v4 含 license/material/vendor bundle，误复制会产生合规与秘密风险 | mitigated | reference-only 规则、扫描与 diff 审查持续通过 |
| P0-03 | donor 本地配置含真实 LLM/MCP 凭据 | open | 凭据轮换；ignore 与 secret scanner 测试通过；历史无泄露 |
| P0-04 | 实时 observation 污染研究 cache/证据链 | open | 物理存储隔离、无隐式 promotion、反向安全测试通过 |
| P0-05 | trade plan/预测被误解为实盘指令 | open | 合同、API、UI 固定 research-only；无 broker/order 能力 |
| P0-06 | 双回测/双 gate 产生互相矛盾的晋级结论 | open | canonical gate 唯一权威；donor 输出只能 advisory |
| P0-07 | UI 进度与仓库状态分叉 | open | status JSON 单一真相源；阶段变更与证据同提交并有校验 |

### 8.2 P1：应在发布前解决或明确接受

| ID | 风险 | 当前状态 | 关闭条件 |
| --- | --- | --- | --- |
| P1-01 | symbol/市场代码规则不一致 | open | canonical SymbolId + 跨市场 fixture |
| P1-02 | 时区、交易日历、复权与停牌语义不一致 | open | 数据字典、边界测试与显式 unavailable |
| P1-03 | provider 限流/失败导致旧缓存冒充实时 | open | TTL、stale、fallback reason 和 UI 标签 |
| P1-04 | SQLite 并发/锁与 schema 演进 | open | 独立 DB、迁移版本、并发与恢复测试 |
| P1-05 | Python 与 Rust 指标漂移 | open | parity suite、容差定义和自动 fallback |
| P1-06 | API 文件读取、URL 代理或富文本产生安全面 | open | allowlist、路径约束、无任意代理、输出净化 |
| P1-07 | web vendor 版本与 notices 不完整 | open | 锁版本、保留来源与许可证文本、自动核查 |
| P1-08 | donor 构建/运行产物扩大仓库与泄露数据 | open | denylist、ignore、staged secret/artifact scan |
| P1-09 | README/命令和 UI 对“实时”能力过度承诺 | open | 能力矩阵、降级语义和 research-only 文案审查 |

## 9. 前端进度同步合同

`integration/integration_status.json` 是人工与 UI 共用的单一真相源，更新规则如下：

1. 每个工作包只有在实现、测试和证据都可复查时才增加进度；
2. `status=completed` 必须同时写 `completed_at` 和非空 `evidence`；
3. `status=blocked` 必须写 blocker、owner 和解除条件；
4. 任一 P0 `open/blocked` 时，`release_readiness` 必须是 `BLOCK`；
5. 前端不得自行推算或覆盖阶段状态，只显示 JSON 投影；
6. 前端轮询时使用 `updated_at`/ETag，只在内容变化时刷新；
7. JSON 无法读取、schema version 不支持或过期时，UI 显示“状态不可验证”，不能显示绿色；
8. 状态更新与对应代码/测试在同一提交中，避免“先宣布完成、后补实现”；
9. merge/rebase 后重新计算 overall counts，禁止只改百分比；
10. release 证据额外记录本地、远端和 UI 展示的 commit SHA。

当前快照必须明确显示：`audit=completed`、`contracts=in_progress`，其余阶段
`not_started`。随着并行任务落地，由负责该工作包的 agent/owner 更新 evidence 和状态。

## 10. 排除清单

本轮以及最终公开项目均排除：

- v4 的源码、HTML/CSS/JS、图片、PDF、zip、`license.dat`、`gen_license.py`、vendored libs；
- donor 的真实密钥、`.grok`/local secret config、数据库、研报、浏览器状态和构建产物；
- broker SDK、券商登录、账户读取、订单创建/撤销、自动执行和资金划转；
- L2、暗池或“主力意图”能力的虚假宣称；
- 通过调试模式绕过任何许可证；
- 将 observation 自动回填、提升或重新命名为独立 holdout/research evidence；
- 将 LLM、实时技术评分或 donor 点时回测用于升级确定性 gate；
- 把两个目录简单复制到一个仓库、保留两套启动方式或合并二进制构建产物；
- 在未获得许可前重新公开 donor/v4 的表达性实现；
- 任何收益承诺、个性化投资建议或“可直接实盘”的表述。

## 11. 验证命令与证据原则

具体命令随实现完善，但每个阶段至少保留以下类别：

```powershell
# 机器可读状态
python -m json.tool integration\integration_status.json

# Python 质量与回归
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest

# Git 与发布一致性
git status --short
git diff --check
git rev-parse HEAD
git ls-remote origin refs/heads/main
```

禁止把只在开发机存在的绝对路径、网络成功、缓存命中或手工截图当作唯一证据。测试输出应
记录版本、时间、SHA、输入 fixture 和失败模式；外部 provider 测试必须与离线 deterministic
测试分开。

## 12. 回滚策略

- 迁移以小提交进行；每个阶段可通过 revert 回滚，不修改 donor 原目录；
- observation provider、Rust 和智能研报均为可选能力，失败时退回 unavailable/offline；
- canonical research core 不依赖 FastAPI、浏览器或 Rust 才能运行；
- schema 变更采用版本化读写，新 writer 上线前先保证旧数据可验证；
- status JSON 若与实现不一致，安全默认值是 `BLOCK` 和“状态不可验证”；
- 任何秘密或受限文件误入 staged diff 时立即停止发布、移除、轮换并审查 Git 历史。

## 13. 当前下一步

Phase 1 已完成，当前推进 Phase 2：按 allowlist 迁移 donor 的可维护 Python 源码、测试、
静态资源与可选 Rust crate，统一到 `src/yeuxq`，同时修复研报路径/安全删除、非本机绑定
鉴权、秘密注入、指数 fallback、全市场宽度、预测 horizon 和回测分段边界。v4、真实凭据、
数据库、研报、浏览器状态和构建产物继续严格排除。项目 LICENSE 与凭据轮换作为发布阻塞项
持续展示在状态 UI 中，不允许因迁移进展而自动解除。
