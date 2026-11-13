# yeuxQ (`quantify`)

面向 A 股的证据门控（Evidence-Gated）量化研究与模拟交易系统：涵盖多因子回测、A 股微观交易规则仿真、抗过拟合滚动验证，以及确定性的 `PASS / WATCH / BLOCK` 晋级审查门。

[English](README.md) · 简体中文

## 核心能力

- **可审计的本地数据层** — 基于 SQLite 缓存日线行情、交易日历、停牌、指数成分与基础财务数据；支持 AKShare、券商/终端离线 CSV 合同与通达信 `.day` 导入，内置 ST/退市/停牌过滤与数据指纹溯源。
- **A 股交易微观仿真** — 截面多因子打分（动量、低波、估值、质量、流动性、去极值与标准化）配合事件驱动撮合，完整建模 `T+1`、涨跌停、停牌、整百股手数、印花税、佣金与滑点。
- **抗过拟合与统计检验** — 支持带隔离窗口的 Walk-Forward 滚动验证、冻结压力测试矩阵、全收益基准对比，以及基于哈希链的预注册实验账本（含 DSR 与 CSCV/PBO 诊断）。
- **连续模拟盘与确定性审查门** — 提供按日续跑的本地模拟盘（`run_paper_loop.py`）、一键周度复盘流水线，以及覆盖数据审计、稳健性与资金目标适配的三态准入门（`PASS / WATCH / BLOCK`）。
- **受约束的 LLM 辅助审查** — 自动生成结构化审查报告与外部提示词包（`run_llm_review.py`），可选接入兼容 OpenAI 的模型输出建议，但绝不允许覆盖确定性审查门结论。

## 快速开始

环境要求：**Python 3.11+** 与 **[uv](https://docs.astral.sh/uv/)**。

```bash
git clone https://github.com/zzzfu411/yeuxQ.git
cd yeuxQ
uv sync
```

零配置跑通首份多因子研究报告（本地无缓存时自动生成确定性示例数据）：

```bash
uv run python examples/run_research.py --config config/research.yaml
```

产物输出至 `results/research/<timestamp>/`（含 `summary.json`、`equity.csv`、`positions.csv`、`orders.csv`、`factor_ic.csv`、`drawdown.png` 与 `html_report.html`）。

导入真实 A 股行情并执行周度审查流水线：

```bash
uv run python examples/import_research_data.py --config config/research.yaml --limit 300 --output-dir results/import/latest
uv run python examples/run_real_data_bootstrap.py --config config/research.yaml --output-dir results/bootstrap
uv run python examples/run_weekly_pipeline.py --config config/research.yaml --starting-capital 100000 --target-capital 1000000 --years 8
```

运行测试与代码检查：

```bash
uv run pytest tests/ -q --basetemp ./tmp/pytest -p no:cacheprovider
uv run ruff check .
```

## 目录结构

```text
src/quantify/
├── core/        事件、Bar、投资组合与目标权重模型
├── data/        SQLite 缓存、AKShare/CSV/通达信导入与 DataProvider
├── research/    股票池过滤、因子计算、多因子选股与报告生成
├── engine/      事件驱动回测引擎、BrokerSim 与 PaperBroker
├── audit/       A 股日频数据完整度与时间一致性（PIT）审计
├── market/      市场宽度、趋势与波动状态识别
├── goal/        资金目标约束与候选策略评分
├── paper/       连续模拟盘状态循环与稳定性核验
├── readiness/   确定性晋级门与人工核对参考表
├── llm/         PASS/WATCH/BLOCK 结构化审查与提示词生成
└── ops/         周度流水线、实验预注册账本与策略档案
```

## 文档导航

- [上手指南 (`GETTING_STARTED.md`)](docs/GETTING_STARTED.md) — 从第一份回测报告到周度审查门的主线命令教程
- [新手系列教程 (`00`–`09`)](docs/00_从零开始.md) — 核心概念、报告解读、实盘心智模型与离线 CSV 导入合同
- [真实数据交接清单](docs/11_real_data_handoff.md) 与 [操作员命令手册](docs/OPERATOR_RUNBOOK.md) — AKShare 预检、券商 CSV / 通达信 `.day` 准入与实验注册完整参数参考
- [系统学习笔记](docs/notes/README.md) — 《预测：方法与实践》及因子投资逐章推导与代码映射

## 风险说明

本项目仅用于量化工程学习、历史数据研究与本地模拟盘验证，不接真实券商交易接口，亦不构成任何投资建议或收益承诺。
