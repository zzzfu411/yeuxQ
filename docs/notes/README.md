# 量化读书笔记总目录

这套笔记服务一个目标: 让零基础读者用最短路径掌握量化研究需要的预测、统计、因子投资和项目实践能力。笔记不是原书摘抄,而是原创学习讲义: 用人话建立直觉,用公式补严谨性,再落到本项目代码。

如果你觉得逐章笔记太短,先读两份深度讲义:

- [FPP 全书深度讲义](fpp/deep_lecture.md)
- [因子投资全书深度讲义](factor/deep_lecture.md)

它们按“课程讲义”写,比逐章速记更完整: 概念地图、公式推导、例题、项目实验和误区都会集中展开。逐章文件用于回查、练习和后续继续加深。

> 风险提示: 本笔记只用于学习和研究。历史回测、因子有效性和模型预测都不能保证未来收益。

## 建议学习顺序

1. 先跑项目: [../00_从零开始.md](../00_从零开始.md)
2. 学预测基础: [fpp/01_intro.md](fpp/01_intro.md) 到 [fpp/03_toolbox.md](fpp/03_toolbox.md)
3. 学因子基础: [factor/01_factor_basics.md](factor/01_factor_basics.md) 和 [factor/02_methodology.md](factor/02_methodology.md)
4. 补数学工具: [math/01_probability.md](math/01_probability.md)、[math/02_ols.md](math/02_ols.md)、[math/03_time_series.md](math/03_time_series.md)、[math/04_portfolio.md](math/04_portfolio.md)
5. 学主流因子和多因子: [factor/03_main_factors.md](factor/03_main_factors.md) 到 [factor/09_multifactor_models.md](factor/09_multifactor_models.md)
6. 最后学实践风险: [fpp/12_practical.md](fpp/12_practical.md)、[factor/11_research_state.md](factor/11_research_state.md)、[factor/12_practice.md](factor/12_practice.md)

## 《预测: 方法与实践》笔记

- [FPP 全书深度讲义](fpp/deep_lecture.md)
- [01 入门](fpp/01_intro.md)
- [02 时间序列图形](fpp/02_graphics.md)
- [03 预测工具箱](fpp/03_toolbox.md)
- [04 判断预测](fpp/04_judgment.md)
- [05 时间序列回归](fpp/05_regression.md)
- [06 时间序列分解](fpp/06_decomposition.md)
- [07 指数平滑](fpp/07_exponential_smoothing.md)
- [08 ARIMA](fpp/08_arima.md)
- [09 动态回归](fpp/09_dynamic_regression.md)
- [10 分层和分组时间序列](fpp/10_hierarchical.md)
- [11 高级预测方法](fpp/11_advanced.md)
- [12 实际预测问题](fpp/12_practical.md)

## 因子投资笔记

- [因子投资全书深度讲义](factor/deep_lecture.md)
- [01 因子投资基础](factor/01_factor_basics.md)
- [02 因子研究方法论](factor/02_methodology.md)
- [03 主流因子总览](factor/03_main_factors.md)
- [04 价值因子](factor/04_value.md)
- [05 规模因子](factor/05_size.md)
- [06 动量与反转因子](factor/06_momentum_reversal.md)
- [07 盈利、质量与投资因子](factor/07_profitability_quality_investment.md)
- [08 低波动与流动性因子](factor/08_low_vol_liquidity.md)
- [09 多因子模型](factor/09_multifactor_models.md)
- [10 异象研究](factor/10_anomalies.md)
- [11 因子研究现状](factor/11_research_state.md)
- [12 因子投资实践](factor/12_practice.md)

## 数学补充

- [概率、期望、方差](math/01_probability.md)
- [最小二乘与回归推导](math/02_ols.md)
- [时间序列数学基础](math/03_time_series.md)
- [组合收益、风险和回撤](math/04_portfolio.md)

## 和本项目代码的关系

- 因子计算: `src/quantify/research/factors.py`
- 股票池过滤: `src/quantify/research/universe.py`
- 多因子目标权重策略: `src/quantify/research/strategy.py`
- 研究引擎: `src/quantify/research/engine.py`
- 纸面交易: `src/quantify/engine/paper_broker.py`
- 指标和图表: `src/quantify/analytics/metrics.py`, `src/quantify/analytics/plot.py`

读每章时都问自己三个问题:

1. 这个概念解决什么真实问题?
2. 它需要哪些数学假设?
3. 我能在项目里用哪段代码验证它?
