# FPP 08: ARIMA

## 这一章解决什么问题

本章讲如何用序列自己的过去和过去误差预测未来。ARIMA 是经典时间序列模型,尤其强调平稳性和差分。

## 先用人话理解

如果今天的状态很大程度受昨天影响,这是 AR。如果今天的异常包含昨天预测错留下的影响,这是 MA。如果原序列像醉汉位置一样越走越飘,先看每一步的变化,这就是差分。

## 核心概念

- AR: 自回归。
- MA: 移动平均误差项。
- I: 差分阶数。
- 平稳性: 统计结构不随时间漂移。
- ACF/PACF: 识别滞后结构的工具。

## 数学公式与推导

AR(1):

```text
Y_t = phi Y_{t-1} + epsilon_t
```

若 `|phi| < 1`,递归展开:

```text
Y_t = phi^k Y_{t-k} + sum_{j=0}^{k-1} phi^j epsilon_{t-j}
```

当 `k -> infinity`, `phi^k -> 0`,冲击影响衰减,序列可平稳。

MA(1):

```text
Y_t = epsilon_t + theta epsilon_{t-1}
```

ARIMA(p,d,q):

```text
Phi(B)(1-B)^d Y_t = Theta(B) epsilon_t
```

其中:

- `B` 是滞后算子, `B Y_t = Y_{t-1}`。
- `(1-B)Y_t = Y_t - Y_{t-1}` 是一阶差分。
- `p` 是 AR 阶数, `q` 是 MA 阶数。

随机游走 `Y_t = Y_{t-1}+epsilon_t` 差分后:

```text
(1-B)Y_t = epsilon_t
```

所以随机游走是 ARIMA(0,1,0)。

## 放到 A 股量化里怎么用

- 股价常像随机游走,收益率更适合建模。
- ARIMA 可用于成交量、波动率、宏观变量,但对个股方向预测通常很难。
- 不要把 ARIMA 当赚钱机器。

## 和本项目代码的对应关系

- `src/quantify/research/factors.py`: 动量因子使用历史价格变化。
- `src/quantify/analytics/metrics.py`: 用收益率计算波动和夏普。

## 常见误区

- 非平稳价格直接回归。
- 只看模型拟合,不看样本外。
- 以为 ARIMA 捕捉到的自相关一定可交易。

## 本章练习

选择一只股票,比较价格和日收益率的 ACF。观察哪个更接近平稳。

## 读完检查清单

- 我能写出 AR(1)、MA(1)、ARIMA。
- 我知道差分为何能处理随机游走。
- 我知道金融收益很难预测。

## 参考链接

- [OTexts《预测: 方法与实践》](https://otexts.com/fppcn/)
