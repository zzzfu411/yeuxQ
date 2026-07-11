# 因子 07: 盈利、质量与投资因子

## 这一章解决什么问题

本章研究公司基本面是否能解释未来收益。盈利和质量看公司好不好,投资因子看公司是否过度扩张。

## 先用人话理解

买股票不是只买价格,也是买公司。盈利因子看公司赚钱能力,质量因子看赚钱是否稳健,投资因子警惕公司盲目扩张。

## 核心概念

- ROE: 净利润/净资产。
- ROA: 净利润/总资产。
- 毛利率、净利率。
- 现金流质量。
- 资产增长率。
- 过度投资。

## 数学公式与推导

ROE:

```text
ROE = NetIncome / BookEquity
```

杜邦拆解:

```text
ROE = (NetIncome / Sales) * (Sales / Assets) * (Assets / Equity)
```

即:

```text
ROE = 净利率 * 资产周转率 * 权益乘数
```

推导: 右边分子分母相消:

```text
(NI/Sales) * (Sales/Assets) * (Assets/Equity) = NI/Equity
```

投资因子常用资产增长:

```text
AssetGrowth = Assets_t / Assets_{t-1} - 1
```

若过度扩张降低未来回报,则资产增长越高,预期收益可能越低。

## 放到 A 股量化里怎么用

- 财务数据必须考虑披露滞后。
- 高 ROE 可能来自高杠杆,要结合资产负债率。
- 投资因子对周期行业解释要谨慎。

## 和本项目代码的对应关系

- `src/quantify/research/factors.py`: `QualityFactor` 使用 `roe`。
- `src/quantify/data/storage.py`: `fundamentals` 表保存财务字段。

## 常见误区

- ROE 高一定好,忽略杠杆。
- 用未来财报做过去选股。
- 只看利润,不看现金流。

## 本章练习

构造一个质量分: `ROE` 高、`PB` 不太高、低波动。说明每一项的作用。

## 读完检查清单

- 我能推导杜邦公式。
- 我知道高盈利不一定等于高质量。
- 我知道财务因子最怕披露滞后。

## 参考链接

- [FactorWar](https://www.factorwar.com/)
