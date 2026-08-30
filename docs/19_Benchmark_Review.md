# Benchmark Review

正式 benchmark review 用经过人工复核并绑定文件哈希的全收益基准，比较策略权益曲线与基准日序列。它只生成 benchmark evidence，不会升级、满足或绕过任何 deterministic gate。

## 输入合同

策略文件默认为 CSV 列 `timestamp,equity`。权益必须为正有限数，日期必须有效且唯一。

基准文件默认为 CSV 列 `date,value`。`value` 的解释由 metadata 的 `series_kind` 决定：

- `equity`：基准全收益指数水平，必须为正有限数。
- `returns`：基准日收益率，必须为有限数且不小于 `-1.0`。

metadata 是必需的 UTF-8 JSON object，至少包含：

```json
{
  "artifact_type": "reviewed_benchmark_series",
  "schema_version": 1,
  "symbol": "000906.SH",
  "name": "CSI 800 Total Return",
  "total_return": true,
  "series_kind": "equity",
  "source_vendor": "licensed-vendor",
  "source_exported_at": "2026-07-15T09:30:00+08:00",
  "reviewed_by": "operator-name",
  "reviewed_at": "2026-07-15T10:00:00+08:00",
  "file_sha256": "<benchmark-csv-sha256>"
}
```

`file_sha256` 必须是基准 CSV 原始字节的 64 位十六进制 SHA-256。字段缺失、哈希不匹配或 `total_return` 不是 boolean `true` 时，报告必须 BLOCK，统计量保持 `null`，该数据不能被称为正式全收益基准。

## 运行

```powershell
python examples/run_benchmark_review.py `
  --strategy-equity-csv artifacts/strategy_equity.csv `
  --benchmark-csv evidence/csi800_total_return.csv `
  --benchmark-metadata evidence/csi800_total_return.metadata.json `
  --output-dir artifacts/benchmark_review `
  --periods-per-year 252 `
  --block-size 5 `
  --n-bootstrap 1000 `
  --random-seed 0
```

非默认列名可通过 `--strategy-date-column`、`--strategy-value-column`、`--benchmark-date-column` 和 `--benchmark-value-column` 指定。

输出：

- `benchmark_report.json`
- `benchmark_report.md`

报告记录策略 CSV、基准 CSV 和 metadata JSON 的 SHA-256，两个序列各自的日期覆盖，基准 identity/provenance，对齐后的日期范围与样本数，以及 excess CAGR、annualized tracking error、information ratio 和 moving-block bootstrap 95% confidence intervals。

## 状态规则

先验证输入合同和统计证据完整性，再按 annualized excess-return 95% CI 判级：

- `BLOCK`：metadata/哈希/数据/统计证据不完整，或 CI 上界 `<= 0`。
- `WATCH`：证据可计算但存在覆盖或 bootstrap 警告，或 CI 跨越/接触 `0`。
- `PASS`：所有必需证据完整、没有其他 WATCH/BLOCK，且 CI 下界 `> 0`。

信息比率或其 CI 不可用时不得用 `0`、无穷大或其他替代值补齐；报告保持 `null` 并 BLOCK。

## CLI 失败语义

可审计的证据不完整，例如文件缺失、metadata 字段缺失、哈希不匹配、非全收益基准或样本不足，会尽量写出 BLOCK JSON/Markdown 并正常返回。已有 JSON/CSV 文件若编码或语法不可解析，CLI 返回非零且不生成报告，以免留下不可信的伪数值。

即使报告为 PASS，也只说明 benchmark evidence 合同与统计复核通过。它不是收益承诺，不是实盘批准，也不能改变任何 deterministic promotion gate 的状态。

本项目的当前 universe `index_code` 为 `000906`，下游门会要求 benchmark identity 与
该代码一致。CSI 300、CSI 500、等权股票池或价格指数不能冒充 CSI 800 全收益序列。
