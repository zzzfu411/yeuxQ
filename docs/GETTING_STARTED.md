# 上手指南:用这个项目学习量化完整流程

这份指南带你把一条量化研究链**从头跑一遍**,每一步都说明"你正在学的是什么"。
它面向"学习量化完整流程"这个目标,不是投资建议。

> 风险提示:历史回测、LLM 分析和模拟盘都不能保证未来收益。本项目帮你建立
> "持续少犯大错"的研究纪律,不承诺赚钱。

## 这个项目在教什么

量化交易不是"让机器预测涨跌",而是把交易拆成一条**可复现、可审计、可暂停**
的流水线。核心心智是一句话:

```text
目标约束 → 市场假设 → 数据证据 → 策略规则 → 回测检验
        → 模拟执行 → 小额实盘 → 监控复盘 → 迭代或下线
```

**任何一步没有证据,都不能跳到下一步。** 项目把这条纪律固化成了一套确定性门
(deterministic gate):每个环节都产出 `PASS / WATCH / BLOCK` 三态,而且
LLM 永远不能把 `BLOCK` 升级成 `PASS`。你学这个项目,本质是学这套纪律。

整条链的数据流是:

```text
SQLite 缓存 → DataProvider → 因子/多因子策略 → PaperBroker(模拟A股撮合)
           → 研究报告 → 审查门(PASS/WATCH/BLOCK)→ 人工审批 →(才谈实盘)
```

---

## 0. 环境准备(一次性)

本项目用 [uv](https://astral.sh/uv) 管理虚拟环境和依赖,**不要污染全局 Python**。

```powershell
cd D:\Develop\claude\quantify
uv sync
```

没有 uv 就先装:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

验证环境可用(应看到测试通过、ruff 干净):

```powershell
uv run pytest tests/ -q --basetemp .\tmp\pytest -p no:cacheprovider
uv run ruff check .
```

> 全量测试约 700+ 用例、十几分钟。想快速验证可只跑核心几个文件,例如
> `uv run pytest tests/test_core.py tests/test_research.py -q --basetemp .\tmp\pytest -p no:cacheprovider`。

---

## 1. 跑通第一份研究报告(理解"回测 ≠ 赚钱")

```powershell
uv run python examples/run_research.py --config config/research.yaml
```

**在教什么:** 一条完整的多因子研究是怎么跑出来的。系统会:

1. 从本地 SQLite 缓存读日线行情(没有真实缓存时自动生成 demo 数据教流程);
2. 过滤股票池(排除 ST、退市、停牌、无价格);
3. 计算因子(动量、低波动、估值、质量、流动性),横截面去极值 + 标准化;
4. 每月调仓,综合打分选前 N 只、等权、单票限重;
5. 用 `PaperBroker` 模拟 A 股撮合(T+1、涨跌停/停牌拒单、100 股整数倍、
   佣金、印花税、滑点、现金约束);
6. 写出报告目录 `results/research/<时间戳>/`。

**去看这些产物**(报告目录里):

| 文件 | 看什么 |
| --- | --- |
| `summary.json` | 收益、年化、夏普、最大回撤、胜率、`n_bars` |
| `equity.csv` | 每日净值曲线 |
| `positions.csv` | 每日持仓 |
| `orders.csv` | 订单**和拒单原因**(重点:量化里拒单是常态) |
| `trades.csv` | 成交明细 |
| `factor_ic.csv` | 因子 RankIC(因子有没有预测力) |
| `drawdown.png` | 净值与回撤图 |
| `html_report.html` | 浏览器打开的汇总报告 |
| `data_audit.json` | 数据质量审计结论(PASS/WATCH/BLOCK) |
| `run_manifest.json` | 配置哈希、缓存哈希、样本窗口——**可复现性凭证** |

**学习重点:** 不要只看 `total_return`。真正决定能否实盘的是**回撤、换手、
拒单率、样本外表现、因子 IC 是否长期为正**。这正是 `docs/03_如何阅读研究报告.md`
展开讲的内容。

---

## 2. 过一次审查门(理解 PASS / WATCH / BLOCK)

把上一步的报告目录换进来:

```powershell
uv run python examples/run_llm_review.py --report-dir results\research\<时间戳> --stage paper
```

**在教什么:** 一份回测报告要进入下一阶段(paper 模拟盘)前,必须先过一道
**确定性审查门**。它检查数据审计状态、样本长度、因子 IC、换手、拒单等,给出
结构化结论:

- `llm_review.json` —— `PASS / WATCH / BLOCK` 以及每条 finding 的代码和原因;
- `llm_review.md` —— 人类可读版本;
- `llm_prompt.md` —— 可复制给外部 LLM 的提示词包。

默认**不调用**外部大模型。这一步是纯确定性规则。如果你配置了
OpenAI-compatible 接口,可以加 `--call-llm` 生成额外的**建议性**叙述审查,但
它**不能**改动 PASS/WATCH/BLOCK。

**学习重点:** 记住这个架构分层——引擎产生证据 → 确定性门先判 → LLM 只做解释
和追问 → 人工审批 → 才谈券商执行。LLM 在系统里是"审查助手",不是"决策者"。
详见 `docs/05_量化实盘交易心智模型.md` 和 `docs/06_LLM_For_Quantify.md`。

---

## 3. 原始双均线回测(理解事件驱动引擎)

```powershell
uv run python examples/run_backtest.py --config config/default.yaml
```

**在教什么:** 项目最早的一条路径——单股票、事件驱动的双均线策略。它比多因子
研究简单,适合先看懂"事件 → 信号 → 下单 → 撮合 → 组合更新"的骨架。
配置在 `config/default.yaml`(注意注释里解释了为什么起始资金要 100 万级别:
茅台约 1700 元/股 × 100 股最小手 = 17 万,低资金看不到完整买卖流程)。

想要真实单股数据时(需要网络):

```powershell
uv run python examples/download_data.py --symbol 600519 --start 2020-01-01 --end 2025-01-01
```

---

## 4. 用真实近期数据做候选研究(理解"数据门")

前面几步用的是教学缓存(`config/research.yaml`,2020-2021)。要做**近期 A 股**
研究,项目用一套独立的隔离配置 `config/research_recent.yaml`
(窗口 2024-06 ~ 2026-06,`allow_demo_data: false`),**绝不**用旧教学缓存冒充。

### 4a. 如果本机已有真实近期缓存

本项目在研究过程中可能已生成过真实缓存(检查 `tmp\*.db`)。例如一份
300 只股票、覆盖 2024-06-03 ~ 2026-06-05 的缓存可直接用来做**研究型**候选预检:

```powershell
# 先看市场处于什么状态(趋势/宽度/波动/回撤)
uv run python examples/run_market_regime.py --config config/research_recent.yaml --cache tmp\akshare_recent_explicit_300_stratified.db --output-dir results\research_recent\regime

# 对一个 OHLCV-only 候选做研究型预检(不进 paper、不批实盘)
uv run python examples/run_candidate_research_precheck.py --config config/research_recent.yaml --cache tmp\akshare_recent_explicit_300_stratified.db --output-dir results\research_recent\pv_defensive_precheck --candidate price_volume_defensive
```

**在教什么:** 真实市场里,防守/中性/进攻不同行情下同一策略表现差异巨大。
`market_regime.json` 给出当前行情标签;候选预检产出
`candidate_research_precheck.json`,并**强制**带上
`status=RESEARCH_ONLY` + `promotion_decision=BLOCK`——它可以启发下一个实验,
但**不能**进入 paper、不能批准实盘、不能生成券商指令。

**学习重点:** 看 `docs/12_Agent_Team_Execution.md`。里面记录了十几个候选策略
(low_turnover、trend_filtered、defensive_cash_guard、liquidity_neutral_guard…)
的真实实验结论——**它们几乎全部在近期防守行情里亏钱、高换手、弱夏普,全被
BLOCK**。这不是失败,这正是量化研究的常态:大多数假设会被证伪,系统的价值在于
**诚实地记录证伪、不让好看的偶然结果蒙混进实盘**。

### 4b. 如果没有真实缓存(网络被挡时的离线路径)

AKShare/东方财富行情接口常被网络或代理挡住。这时项目走**离线 CSV 合同**:
你从券商/终端导出日线 CSV,经过 `csv_validation` 合同校验 + `source QA`(数据
来源问卷)+ 守卫式离线导入,才能进入研究缓存。完整命令链见 `README.md` 的
"离线 CSV 合同"章节和 `docs/09_离线真实数据导入合同.md`。

一键看"离一百万复利目标还差哪些硬条件":

```powershell
uv run python examples/run_goal_status.py --report-dir results\goal --config config/research_recent.yaml --as-of 2026-06-08 --starting-capital 100000 --target-capital 1000000 --years 8 --min-symbols 300 --min-trading-days 240
```

**在教什么:** `capital_goal_status.json` 把 20+ 个证据项(数据缓存、来源 QA、
稳健性、候选筛选、模拟盘、审批…)汇成一张总控表。现在它几乎全是 `BLOCK`,
因为缺一份合规的真实近期数据。**这就是纪律:没有数据证据,策略搜索就被关闭。**

---

## 5. 每周一键流水线(把整条链串起来)

```powershell
uv run python examples/run_weekly_pipeline.py --config config/research.yaml --starting-capital 100000 --target-capital 1000000 --years 8 --wf-train-days 120 --wf-test-days 60 --wf-step-days 60
```

**在教什么:** 这一条命令把"离线研究 → 数据审计 → 市场状态 → 稳健性 →
walk-forward 滚动验证 → 候选筛选 → 模拟盘日报 → 稳定性审查 → LLM 审查 →
周度复盘"全部生成到一个证据目录里。它**默认不调用外部 LLM、不连券商、不写
人工审批**。没有连续 paper 状态目录时,`paper_stability.json` 会明确 `BLOCK`。

**学习重点:** 这是"复盘不是写感想,而是留证据降低下次犯错概率"的工程化体现。
`docs/07_长期执行Goal.md` 讲长期怎么用它。

---

## 推荐学习顺序

**先跑,再读概念,最后看数学**,不会一上来被公式劝退:

1. 跑通本指南第 1-2 步。
2. 读 `docs/00_从零开始.md` → `docs/01_核心概念.md` → `docs/03_如何阅读研究报告.md`。
3. 读 `docs/05_量化实盘交易心智模型.md`(整个项目的哲学总纲)。
4. 跑本指南第 4-5 步,对照 `docs/08_第一桶金策略研究路线.md` 和
   `docs/12_Agent_Team_Execution.md` 看真实实验结论。
5. 系统学习:`docs/notes/README.md` 下有《预测:方法与实践》、因子投资、数学
   三条逐章笔记(人话解释 + 数学推导 + A 股映射 + 项目代码对应 + 练习)。

## 代码地图(想改代码时看这里)

```text
src/quantify/
  core/       事件、Bar、Portfolio、目标权重(最薄,先看这里理解骨架)
  data/       CSV/AKShare/TDX/SQLite + 数据校验与来源 QA(最厚)
  research/   股票池、因子、多因子策略、研究引擎、候选实验
  engine/     原回测引擎、BrokerSim、PaperBroker(A股撮合模拟)
  ops/        周度流水线、第一桶金编排、证据矩阵、策略档案
  goal/       资金目标规划、候选评分、目标状态总控
  llm/        确定性审查门 + 可选 OpenAI advisory
  market/     市场状态检测、快照、就绪门
  readiness/  小额实盘准备门、人工审批记录、资金递增门
  audit/      A 股日频数据可信度审计
  paper/      模拟盘日报、连续 paper loop、稳定性审查
  risk/ analytics/ strategy/ utils/  风控、指标图表、双均线、配置
```

**入门读代码建议路径:** `core/event.py` → `core/portfolio.py` →
`research/factors.py` → `research/strategy.py` → `engine/paper_broker.py` →
`research/engine.py`。这条线覆盖了"事件/组合 → 因子 → 选股 → 撮合 → 引擎"
的完整骨架,是理解整个系统最短的路径。

## 两条不可逾越的安全边界

1. **不连券商、不自动下单。** 项目最高只做到"人工参考表"和"准备门",
   任何时候都没有真实下单能力。
2. **LLM 不能越过风控门。** LLM 只做解释、追问、生成实验清单;
   PASS/WATCH/BLOCK 永远由确定性规则 + 人工审批决定。
