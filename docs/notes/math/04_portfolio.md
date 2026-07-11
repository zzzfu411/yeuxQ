# 数学补充 04: 组合收益、风险和回撤

## 这一章解决什么问题

量化策略最终不是预测一个数,而是管理一个组合。本章解释组合收益、复利、波动、夏普、信息比率和最大回撤。

## 先用人话理解

组合像一支球队。单个球员表现重要,但总成绩取决于每个人的上场时间和配合。股票的上场时间就是权重。

## 核心概念

- 权重 `w_i`: 第 `i` 只股票占组合的比例。
- 单期组合收益: 各资产收益的加权和。
- 复利: 每期收益滚动乘起来。
- 夏普: 单位波动获得的超额收益。
- 最大回撤: 从历史高点跌到低点的最大损失。

## 数学公式与推导

单期组合收益:

```text
R_p = sum_i w_i R_i
```

推导: 若初始资产 `V`,第 `i` 个资产投入 `w_i V`,期末变成 `w_i V(1+R_i)`,总资产:

```text
V_1 = sum_i w_i V(1+R_i)
    = V sum_i w_i + V sum_i w_i R_i
```

若权重和为 1:

```text
V_1 / V - 1 = sum_i w_i R_i
```

复利净值:

```text
Equity_T = Equity_0 prod_t (1 + R_t)
```

最大回撤:

```text
Peak_t = max_{s <= t} Equity_s
Drawdown_t = 1 - Equity_t / Peak_t
MaxDD = max_t Drawdown_t
```

夏普比率:

```text
Sharpe = mean(R_t - R_f) / std(R_t - R_f) * sqrt(252)
```

信息比率:

```text
IR = mean(R_p - R_b) / std(R_p - R_b) * sqrt(252)
```

其中 `R_b` 是基准收益。

适用条件:

- 夏普默认收益近似稳定,且波动能代表风险。
- 最大回撤强依赖样本区间。
- 组合权重会因价格变化漂移,需要调仓。

## 放到 A 股量化里怎么用

- 多因子策略输出目标权重。
- PaperBroker 把目标权重转成可成交订单。
- 每日净值用于计算收益、波动和回撤。

## 和本项目代码的对应关系

- 组合记账: `src/quantify/core/portfolio.py`
- 目标权重成交: `src/quantify/engine/paper_broker.py`
- 绩效指标: `src/quantify/analytics/metrics.py`

## 常见误区

- 只看年化收益,不看回撤。
- 忽略交易成本,导致净值虚高。
- 用单次回测最大回撤当作未来最大亏损上限。

## 本章练习

用 `equity.csv` 手工计算最大回撤,再和 `summary.json` 中的 `max_drawdown` 比较。

## 读完检查清单

- 我能推导组合收益公式。
- 我知道夏普和信息比率的区别。
- 我能解释最大回撤为什么重要。

## 参考链接

- [OTexts《预测: 方法与实践》](https://otexts.com/fppcn/)
- [FactorWar](https://www.factorwar.com/)
