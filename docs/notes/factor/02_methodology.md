# 因子 02: 因子研究方法论

## 这一章解决什么问题

本章说明如何严肃检验一个因子: 不是看一次回测曲线,而是看分组、IC、RankIC、样本外、交易成本和稳健性。

## 先用人话理解

研究因子像试药。不能找几个成功案例就说有效,要有对照组、样本外、统计检验和副作用分析。交易成本、换手和容量就是因子的副作用。

## 核心概念

- 单因子排序。
- 分组回测。
- 多空组合。
- IC 和 RankIC。
- t 值。
- 样本内/样本外。
- 多重检验。

## 数学公式与推导

IC:

```text
IC_t = Corr(f_{i,t}, R_{i,t+1})
```

RankIC:

```text
RankIC_t = Corr(rank(f_{i,t}), rank(R_{i,t+1}))
```

IC 均值的 t 值:

```text
t = mean(IC_t) / (std(IC_t) / sqrt(T))
```

推导: 若 `IC_t` 近似独立同分布,样本均值的标准误为 `std(IC_t)/sqrt(T)`。t 值就是均值离 0 有多少个标准误。若 IC 有自相关,这个标准误会偏小,需要 Newey-West 等调整。

## 放到 A 股量化里怎么用

一个因子至少要看:

- 高分组是否跑赢低分组。
- RankIC 是否长期为正。
- 交易成本后是否有效。
- 牛熊市是否都不过度崩。
- 是否只是小市值或行业暴露。

## 和本项目代码的对应关系

- `src/quantify/research/factors.py`: `rank_ic` 和因子标准化。
- `src/quantify/research/engine.py`: 生成 `factor_ic.csv`。
- `src/quantify/engine/paper_broker.py`: 模拟交易成本。

## 常见误区

- 只挑最好看的时间段。
- 试很多因子后不做多重检验修正。
- 只看 IC 均值,不看波动和极端失效期。

## 本章练习

用一个因子做 5 分组回测设计,写出每组如何构造、持有多久、如何计算收益。

## 读完检查清单

- 我能写出 IC 和 RankIC。
- 我知道 t 值的分母是标准误。
- 我知道因子研究必须看交易成本。

## 参考链接

- [FactorWar](https://www.factorwar.com/)
