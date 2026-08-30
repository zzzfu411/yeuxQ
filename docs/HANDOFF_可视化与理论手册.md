# 可视化与理论手册:实施交接文档

> **用途**:本文档用于把"给项目增加可视化仪表盘 + 配套理论手册"这项工作交接给
> 另一个 AI 或另一个会话。读完即可对齐上下文、无歧义地继续实施。
> **状态**:方案已定稿并获用户确认。经 2026-07-15 复核,
> `src/quantify/analytics/dashboard.py`、`examples/build_report_dashboard.py`、
> `tests/test_dashboard.py` 和 `docs/可视化与指标理论手册.md` 仍不存在,
> 因此 dashboard 代码和配套理论手册尚未实现。

---

## 1. 背景与用户诉求

用户(量化学习者,母语中文,环境用 `uv` 管理 Python)提出:
> "有可视化的使用方案吗?若没有你能不能设计一个?或者来一个详细的使用手册和理论知识补充。"

经调研确认:**项目现有可视化很弱**,需要新建。用户通过选择题明确了两个交付方向:

1. **交付形式** = 自包含 HTML 仪表盘(不是升级现有报告、不是证据链总控面板、不是纯文档)。
2. **理论深度** = 配套理论手册(中等深度,讲每个图表/指标的含义和怎么用它判断策略好坏,**不堆数学公式推导**)。

---

## 2. 现状调研结论(已核实,可直接引用)

### 2.1 现有可视化能力(很弱)

- **唯一的图**:`src/quantify/analytics/plot.py` → `plot_equity()`,用 matplotlib
  (backend=Agg)生成**一张静态 PNG**:上轴净值曲线+买卖点(`^`绿买/`v`红卖),
  下轴回撤填充。输出 `drawdown.png`。
- **唯一的 HTML**:`src/quantify/research/report.py` → `_html_report()`,一个
  **纯表格**页面:核心指标 table + 假设 ul + 证据 ul + 最近 10 行持仓
  `to_html()`。图表部分只写了一句"请查看同目录下的 drawdown.png"——**HTML 里没有内嵌任何图**。
- 全项目 **只有 report.py 生成 HTML**,**只有 plot.py + report.py 用 matplotlib**
  (已 grep 确认,排除 `__pycache__`)。
- **依赖**:纯 matplotlib。`pyproject.toml` / `uv.lock` 里**没有** plotly / bokeh /
  dash / streamlit / flask / fastapi / jinja / echarts。→ **设计约束:不引入新依赖。**

### 2.2 数据源(仪表盘要读的文件,schema 已核实)

每个研究报告目录 `results/research/<时间戳>/` 里有:

| 文件 | 关键字段/列(已核实) |
| --- | --- |
| `summary.json` | 顶层:`initial_equity, final_equity, total_return, annualized_return, annualized_volatility, sharpe_ratio, max_drawdown, n_round_trips, win_rate, n_bars`;嵌套:`assumptions{}, evidence{}, risk_notice` |
| `equity.csv` | `timestamp, equity` |
| `factor_ic.csv` | `date, rank_ic` |
| `turnover.csv` | `date, turnover, turnover_pct` |
| `orders.csv` | `timestamp, symbol, direction, quantity, price, status, reason`(status ∈ filled/rejected;reason 如 t_plus_one/cash/not_buyable/no_price) |
| `trades.csv` | `timestamp, symbol, direction, quantity, fill_price, commission, tax, gross_value` |
| `positions.csv` | `date, symbol, quantity, available_qty, price, market_value, weight, avg_cost` |
| `data_audit.json` | `status`(PASS/WATCH/BLOCK), `findings[]`, `metrics{}` |
| `llm_review.json` | `decision`(PASS/WATCH/BLOCK), `findings[{severity,code,...}]` — **可能不存在**(需先跑 run_llm_review.py),要容错 |

### 2.3 现有样本的证据边界(2026-07-15 复核)

- `results/research/20260712_064935/` 是 **demo-contaminated** 目录。虽然
  `run_manifest.json`、`data_audit.json` 和 `summary.json` 自报
  `data_source=akshare`、`demo_data_used=false`,但 `orders.csv`、`trades.csv`、
  `positions.csv` 和 `html_report.html` 实际包含大量 `DEMO001`、`DEMO002` 等
  `DEMO*` 标的。自报元数据与实际载荷冲突,因此该目录**不可作为真实研究证据**,
  也不可用于策略晋级;它只能作为 dashboard 的 **UI fixture**,用于验证解析、缺失文件
  容错和渲染效果。
- `tmp/akshare_recent_explicit_300_stratified.db` 的 `bars` 表确有 300 只股票、
  145506 条 bars,日期范围为 2024-06-03 至 2026-06-05;但
  `research_metadata` 和 `fundamentals` 均为空表。该库只能作为**研究候选输入**,
  不能被称为晋级证据,也不能让候选策略进入 paper、micro-live 或任何更高阶段。

### 2.4 指标的精确算法(手册必须与此一致,来自 `analytics/metrics.py`)

- `TRADING_DAYS_PER_YEAR = 252`
- `total_return = final/initial - 1`
- `annualized_return = (final/initial) ** (252/n_periods) - 1`,其中 `n_periods = len(equity)-1`(几何年化)
- `annualized_volatility = daily_ret.std() * sqrt(252)`
- `sharpe_ratio = (excess.mean()/excess.std()) * sqrt(252)`,默认 `risk_free_rate=0`
- `max_drawdown = max(1 - s/cummax)`(正数表示的最大峰谷相对损失)
- `win_rate`:FIFO 配对 —— 每个 EXIT 与该 symbol 最早的 LONG 队列配对,
  `卖出净额(扣佣金+印花税) > 对应买入成本` 记为一次 win;`win_rate = wins/round_trips`
- `factor_ic`(RankIC):在 `research/engine.py::_compute_factor_ic`,
  当日因子分数的 rank 与**次日**收益率的 rank 求 Spearman 相关。

### 2.5 项目铁律(仪表盘和手册都必须遵守)

- 每份报告顶部必须有**风险提示**:"历史回测不代表未来收益"。现有 HTML、summary.json
  都带,新仪表盘也要带。
- 不连券商、不自动下单;LLM 不能升级 PASS/WATCH/BLOCK。可视化只是"看",不产生任何交易许可。
- 中文优先(项目文档、HTML lang="zh-CN"、字体 `"Microsoft YaHei"`)。

---

## 3. 已确认的设计方案

### 3.1 成果一:自包含 HTML 仪表盘

**目标**:一条命令把一个结果目录渲染成一个**双击即开、零依赖、可离线分享**的
`dashboard.html`(所有图表用**内联 SVG**手绘,不依赖 matplotlib 也不依赖任何 JS/CDN)。

**为什么用内联 SVG 而不是 matplotlib PNG**:
- 交互性(hover 看数值)PNG 做不到;
- 自包含单文件(PNG 要外链或 base64,SVG 直接进 HTML);
- 零新依赖,契合项目"纯 matplotlib、少依赖"的既有取向;
- 生成逻辑是纯字符串拼接的纯函数,好测试。

**建议的模块划分**:

- `src/quantify/analytics/dashboard.py`(新增,纯函数,零 IO 副作用除了最后写文件)
  - `build_dashboard(report_dir) -> str`:读目录内文件 → 返回完整 HTML 字符串。
  - 内部小函数:`_svg_line_chart(...)`(净值/回撤)、`_svg_bar_chart(...)`
    (因子IC柱、换手率)、`_svg_donut_or_bars(...)`(拒单原因分布)、
    `_kpi_cards(summary)`(指标卡片,按阈值上色)、`_gate_badge(status)`
    (PASS=绿/WATCH=黄/BLOCK=红 徽章)。
  - 全部容错:文件缺失(如 llm_review.json)时跳过对应板块,不报错。
- `examples/build_report_dashboard.py`(新增 CLI)
  - `--report-dir <dir>`(必填):结果目录。
  - `--output <path>`(可选,默认 `<report-dir>/dashboard.html`)。
  - `--open`(可选):生成后用 `webbrowser` 打开。
  - 复用项目现有 CLI 风格(argparse + loguru,参考 examples/run_llm_review.py)。

**仪表盘板块建议**(从上到下):

1. 顶部:标题 + 风险提示横幅 + 三个门徽章(data_audit / llm_review / 若有 goal_status)。
2. KPI 卡片行:总收益、年化、夏普、最大回撤、胜率、换手(均值)、拒单率。
   带阈值上色(如夏普<0.8 黄、回撤>预算 红),阈值参考 `goal/planner.py::screen_strategy_candidate`。
3. 净值曲线(SVG 折线)+ 回撤(SVG 面积,红)——对应现有 drawdown.png 但可交互。
4. 因子 RankIC 时间序列(SVG 柱,正绿负红)+ 均值线;标注"IC 长期为正才有意义"。
5. 换手率时间序列(SVG 柱)——高换手=高摩擦成本预警。
6. 拒单原因分布(SVG 横条)——按 reason 分组计数,教用户"拒单是 A 股约束的常态"。
7. 最近持仓快照表(复用现有 positions 逻辑)。

每个图表下方配**一句话解读**("这是什么/怎么看"),与手册呼应。

### 3.2 成果二:配套理论手册

**文件**:`docs/可视化与指标理论手册.md`

**定位**:补 `docs/03_如何阅读研究报告.md` 的空白。现有 03 只说"字段是什么",
本手册讲"**为什么、怎么用它判断策略好坏**"。中等深度,不堆公式推导
(那是 `docs/notes/` 的活),但要给出与 §2.4 一致的**计算口径**。

**建议章节**(每节:直觉 → 计算口径 → 怎么判断好坏 → 常见陷阱 → 对应仪表盘哪块):

1. 净值曲线:复利视角、为什么看形状不只看终点。
2. 最大回撤:定义、为什么比收益更决定能否实盘、回撤预算概念。
3. 夏普比率:风险调整收益、rf=0 的含义、为什么 <0.8 要警惕、年化的 √252。
4. 年化收益 vs 总收益:几何年化口径、样本长度陷阱(n_bars 太小不可信)。
5. 因子 RankIC:信号质量、为什么看**长期为正**而非单期、IC≈0 说明因子没预测力。
6. 换手率:摩擦成本、A股佣金+印花税+滑点如何吃掉纸面收益、高换手预警。
7. 胜率与盈亏比:胜率高≠赚钱、FIFO 配对口径、为什么要结合盈亏幅度看。
8. T+1 与拒单:为什么会拒单(t_plus_one/涨跌停/停牌/现金)、拒单率的意义。
9. PASS/WATCH/BLOCK:确定性门的哲学、LLM 为何不能升级门、如何顺着门找下一步。

配 ASCII 图解(如净值+回撤的示意、IC 时间序列示意),风格参考 `docs/notes` 里
用 ` ```text ` 画的图。

---

## 4. 历史基线与当前工作区

以下 git 历史是原交接记录中的基线(分支 `main`,4 个提交):

```
5bce3b9 chore: update package description to match current scope
1bc1456 docs: add learning-oriented GETTING_STARTED guide
e4819b8 Apply safe ruff autofixes (import order, f-strings, redundant parens)
ab3164c Initial baseline: teaching-grade A-share quant research system
```

- **ab3164c**:首次基线提交(405 文件)。此前项目零 commit。
- **e4819b8**:ruff F/I/UP/B/SIM 安全自动修复 162 处,净减 138 行,行为不变,已过测试。
- **1bc1456**:新增 `docs/GETTING_STARTED.md`(学习导向上手指南)+ README 顶部入口。
- **5bce3b9**:修正 `pyproject.toml` 描述。
- `.gitignore` 已加固(缓存目录 + `data_exports/` 真实数据/证据子目录);已用
  `git check-ignore` 验证模板保留、真实数据被挡。
- 分支已 `master` → `main`;空目录 `.agents/.codex` 已删。

**不要沿用“工作区干净”的旧结论。** 2026-07-15 复核时 `git status --short`
包含多处已修改代码、测试和未跟踪文件,且有其他 Agent 同时工作。接手者必须保留这些
并行改动,不得为了实施 dashboard 而 reset、checkout 或清理工作区。

**可视化 + 理论手册相关代码/文档仍未实现。**
`src/quantify/analytics/dashboard.py`、`examples/build_report_dashboard.py`、
`tests/test_dashboard.py`、`docs/可视化与指标理论手册.md` **均不存在**。

---

## 5. 待办清单(接手者从这里继续)

按依赖顺序:

- [ ] **T6 写 dashboard 模块** `src/quantify/analytics/dashboard.py`
      纯函数读结果目录 → 自包含 dashboard.html(内联 SVG:净值/回撤/因子IC/换手/拒单;
      KPI 卡片按阈值上色;门徽章)。零新依赖。文件缺失需容错。
- [ ] **T7 写 CLI** `examples/build_report_dashboard.py`
      `--report-dir`(必填)/`--output`(默认 report-dir/dashboard.html)/`--open`。
      argparse + loguru,风格对齐 examples/run_llm_review.py。
- [ ] **T8 写测试** `tests/test_dashboard.py`
      用最小 result 目录 fixture(可参考 tests/test_research.py 造 summary.json+CSV)
      验证:dashboard.html 生成、含关键 KPI 文本、含 `<svg`、含风险提示；
      llm_review.json 缺失时不报错；CLI smoke(写出文件)。
- [ ] **T9 写理论手册** `docs/可视化与指标理论手册.md`（章节见 §3.2，口径对齐 §2.4）。
- [ ] **T10 验证并接入**
      - 先用 §6 的 demo-contaminated UI fixture 验证 dashboard.html 的解析与渲染;
        不得把该步骤写成真实研究验证。
      - 跑测试 + `ruff check .`(注意 §6 pytest 坑）。
      - 在 README 和 docs/GETTING_STARTED.md 链接新命令与手册。
      - 提交(建议拆两个 commit:代码+测试一个，手册一个）。

---

## 6. 接手者必须知道的环境坑(已踩过)

- **pytest 必须用全新 basetemp**:复用旧 `--basetemp` 目录会在 Windows 上产生
  数百个 Permission ERROR(单文件重跑却能过)。命令:
  `uv run pytest tests/ -q --basetemp .\tmp\pytest_新目录 -p no:cacheprovider`。
  或用 `.\.venv\Scripts\python.exe -m pytest ...`。全量 733 用例约 13 分钟。
- **候选研究输入缓存**:`tmp/akshare_recent_explicit_300_stratified.db`
  (300 股、145506 bars、2024-06-03~2026-06-05,被 gitignore)。它的
  `research_metadata` 和 `fundamentals` 为空,只能用于候选研究输入,不能晋级。
  `data_cache/research_recent.db` 是空的(2 股 0 bar),别用。
- **仅供 UI fixture 的报告目录**:`results/research/20260712_064935/`。
  它包含 summary.json / equity.csv / factor_ic.csv / turnover.csv / orders.csv /
  drawdown.png / html_report.html / llm_review.json,但载荷中存在 `DEMO*` 标的,
  属于 demo-contaminated。可用它测试 dashboard 的布局和容错,不可把结果解释为
  真实研究证据。
- **AKShare/东方财富在线接口在本环境被网络/代理挡住**,拉新数据走不通;
  真实数据只能用已有 tmp 缓存或离线 CSV 合同。
- **不污染全局 Python**:一律 `uv` 或 `.\.venv\Scripts\python.exe`。
- 生成/验证时的临时产物写到 `tmp/`(已 gitignore),别提交。

---

## 7. 快速上手命令(接手者验证环境用)

```powershell
# 环境
cd D:\Develop\claude\quantify
uv sync

# 跑一份研究报告(如需新的验证目录)
uv run python examples/run_research.py --config config/research.yaml

# 仅供 UI fixture 的 demo-contaminated 报告目录:
#   results/research/20260712_064935/

# 快速测试(只跑核心,避免 13 分钟全量)
uv run pytest tests/test_research.py tests/test_analytics.py -q --basetemp .\tmp\pt_new -p no:cacheprovider
uv run ruff check .
```
