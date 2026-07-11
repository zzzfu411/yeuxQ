# 因子 12: 因子投资实践

## 这一章解决什么问题

本章把因子研究落到完整系统: 数据、清洗、股票池、因子、组合、交易成本、风控、报告和持续复盘。

## 先用人话理解

因子投资不是写一个公式就结束,而是开一家工厂。原料是数据,流水线是清洗和计算,质检是回测和风控,出厂报告是复盘。任何环节偷懒,成品都不可靠。

## 核心概念

- 数据治理。
- 股票池过滤。
- 因子标准化。
- 组合构建。
- 交易成本。
- 风险控制。
- 绩效归因。
- 持续监控。

## 数学公式与推导

交易成本后收益:

```text
R_net = R_gross - Cost
```

若单边换手率为 `Turnover_t`,单边成本率为 `c`,近似:

```text
Cost_t ≈ c * Turnover_t
```

多期净值:

```text
Equity_T = Equity_0 prod_t (1 + R_{gross,t} - Cost_t)
```

这说明高换手策略即使毛收益高,也可能被成本吃掉。低换手月度调仓是新手更稳的起点。

## 放到 A 股量化里怎么用

实践清单:

- 只用调仓日前可得数据。
- 过滤 ST、退市、停牌。
- 处理涨跌停不可交易。
- 买入按 100 股整数倍。
- 加入佣金、印花税、滑点。
- 输出完整报告。

## 和本项目代码的对应关系

- `src/quantify/data/provider.py`: 数据读取。
- `src/quantify/research/universe.py`: 股票池。
- `src/quantify/research/factors.py`: 因子。
- `src/quantify/research/engine.py`: 研究引擎。
- `src/quantify/engine/paper_broker.py`: 交易成本和约束。
- `src/quantify/research/report.py`: 报告。

## 常见误区

- 数据还没治理好就调模型。
- 回测没有交易成本。
- 没有记录实验配置。

## 本章练习

运行 `examples/run_research.py`,打开 `orders.csv`,找出所有 `rejected` 订单并解释原因。

## 读完检查清单

- 我能画出完整因子投资流程。
- 我知道交易成本如何进入净值。
- 我能把书本概念对应到项目模块。

## 参考链接

- [FactorWar](https://www.factorwar.com/)
