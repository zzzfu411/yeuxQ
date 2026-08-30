"""Research report writers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from quantify.analytics.metrics import compute_report
from quantify.analytics.plot import plot_equity
from quantify.research.engine import ResearchResult

if TYPE_CHECKING:
    from quantify.audit import DataAuditReport
    from quantify.ops.run_manifest import RunManifest

_TRADE_COLUMNS = [
    "timestamp",
    "symbol",
    "direction",
    "quantity",
    "fill_price",
    "commission",
    "tax",
    "gross_value",
]
_ORDER_COLUMNS = ["timestamp", "symbol", "direction", "quantity", "price", "status", "reason"]
_POSITION_COLUMNS = [
    "date",
    "symbol",
    "quantity",
    "available_qty",
    "price",
    "market_value",
    "weight",
    "avg_cost",
]
_TURNOVER_COLUMNS = ["date", "signal_date", "turnover", "turnover_pct"]


def write_research_report(
    result: ResearchResult,
    output_dir: str | Path,
    title: str,
    assumptions: dict[str, object] | None = None,
    evidence: dict[str, object] | None = None,
) -> Path:
    """Persist a full file-based research report and return the run directory."""
    run_dir = Path(output_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    report = compute_report(
        result.equity_curve,
        result.fills,
        initial_equity=result.portfolio.initial_cash,
    )
    summary = report.to_dict()
    summary["assumptions"] = assumptions or {}
    summary["evidence"] = evidence or {}
    summary["risk_notice"] = "Historical backtests do not predict or guarantee future profits."

    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    _fills_frame(result).to_csv(run_dir / "trades.csv", index=False)
    _orders_frame(result).to_csv(run_dir / "orders.csv", index=False)
    pd.DataFrame(result.positions, columns=_POSITION_COLUMNS).to_csv(
        run_dir / "positions.csv",
        index=False,
    )
    pd.DataFrame(result.equity_curve, columns=["timestamp", "equity"]).to_csv(
        run_dir / "equity.csv", index=False
    )
    pd.DataFrame(result.turnover, columns=_TURNOVER_COLUMNS).to_csv(
        run_dir / "turnover.csv",
        index=False,
    )
    result.factor_ic.to_csv(run_dir / "factor_ic.csv", index=False)

    plot_equity(result.equity_curve, result.fills, run_dir / "drawdown.png", title=title)
    (run_dir / "html_report.html").write_text(
        _html_report(title, summary, result),
        encoding="utf-8",
    )
    return run_dir


def _fills_frame(result: ResearchResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "timestamp": fill.timestamp.isoformat(),
                "symbol": fill.symbol,
                "direction": fill.direction.value,
                "quantity": fill.quantity,
                "fill_price": fill.fill_price,
                "commission": fill.commission,
                "tax": fill.tax,
                "gross_value": fill.gross_value,
            }
            for fill in result.fills
        ],
        columns=_TRADE_COLUMNS,
    )


def _orders_frame(result: ResearchResult) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "timestamp": order.timestamp.isoformat(),
                "symbol": order.symbol,
                "direction": order.direction.value,
                "quantity": order.quantity,
                "price": order.price,
                "status": order.status,
                "reason": order.reason,
            }
            for order in result.orders
        ],
        columns=_ORDER_COLUMNS,
    )


def _html_report(title: str, summary: dict[str, object], result: ResearchResult) -> str:
    rows = "\n".join(
        f"<tr><th>{key}</th><td>{value}</td></tr>"
        for key, value in summary.items()
        if key not in {"assumptions", "evidence"}
    )
    assumptions = summary.get("assumptions", {})
    assumption_rows = "\n".join(
        f"<li><strong>{key}</strong>: {value}</li>"
        for key, value in dict(assumptions).items()
    )
    evidence = summary.get("evidence", {})
    evidence_rows = "\n".join(
        f"<li><strong>{key}</strong>: {value}</li>"
        for key, value in dict(evidence).items()
    )
    if not evidence_rows:
        evidence_rows = "<li>No data evidence digest recorded.</li>"
    last_positions = pd.DataFrame(result.positions).tail(10)
    positions_html = (
        last_positions.to_html(index=False, escape=True)
        if not last_positions.empty
        else "<p>No open positions recorded.</p>"
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    body {{ font-family: Arial, "Microsoft YaHei", sans-serif; margin: 32px; line-height: 1.55; }}
    table {{ border-collapse: collapse; margin: 16px 0; min-width: 520px; }}
    th, td {{ border: 1px solid #ddd; padding: 8px 10px; text-align: left; }}
    th {{ background: #f5f5f5; }}
    .notice {{ color: #8a4b00; background: #fff7e6; padding: 12px; border: 1px solid #ffd591; }}
  </style>
</head>
<body>
  <h1>{title}</h1>
  <p class="notice">风险提示: 历史回测不代表未来收益, 本系统只用于研究与仿真。</p>
  <h2>核心指标</h2>
  <table>{rows}</table>
  <h2>实验假设</h2>
  <ul>{assumption_rows}</ul>
  <h2>Data Evidence</h2>
  <ul>{evidence_rows}</ul>
  <h2>最近持仓快照</h2>
  {positions_html}
  <h2>净值与回撤</h2>
  <p>请查看同目录下的 <code>drawdown.png</code>。</p>
</body>
</html>
"""


def research_evidence_digest(
    *,
    audit: DataAuditReport | None = None,
    manifest: RunManifest | None = None,
) -> dict[str, object]:
    """Build a compact evidence digest to embed in summary.json."""
    digest: dict[str, object] = {}
    if audit is not None:
        digest.update(
            {
                "data_audit_status": audit.status,
                "data_audit_finding_count": len(audit.findings),
                "data_audit_demo_data_used": audit.demo_data_used,
                "data_audit_missing_bar_ratio": audit.metrics.get("missing_bar_ratio", 0),
                "data_audit_st_symbol_count": audit.metrics.get("st_symbol_count", 0),
                "data_audit_delisted_symbol_count": audit.metrics.get("delisted_symbol_count", 0),
                "data_audit_suspension_symbol_day_count": audit.metrics.get(
                    "suspension_symbol_day_count",
                    0,
                ),
                "data_audit_limit_up_count": audit.metrics.get("limit_up_count", 0),
                "data_audit_limit_down_count": audit.metrics.get("limit_down_count", 0),
            }
        )
    if manifest is not None:
        data_version = manifest.data_version
        digest.update(
            {
                "run_manifest_purpose": manifest.purpose,
                "run_manifest_config_sha256": manifest.config_sha256,
                "run_manifest_cache_sha256": manifest.cache_sha256,
                "run_manifest_cache_size_bytes": manifest.cache_size_bytes,
                "run_manifest_demo_data_used": manifest.demo_data_used,
                "run_manifest_latest_bar_date": manifest.latest_bar_date,
                "run_manifest_symbol_count": manifest.symbol_count,
                "run_manifest_trading_day_count": manifest.trading_day_count,
                "cache_logical_bar_fingerprint": data_version.get(
                    "cache_logical_bar_fingerprint",
                    "",
                ),
                "cache_logical_bar_fingerprint_algorithm": data_version.get(
                    "cache_logical_bar_fingerprint_algorithm",
                    "",
                ),
                "cache_latest_import_batch_id": data_version.get(
                    "cache_latest_import_batch_id",
                    "",
                ),
                "cache_lineage_schema_version": data_version.get(
                    "cache_lineage_schema_version",
                    "",
                ),
                "csv_dataset_fingerprint": data_version.get("csv_dataset_fingerprint", ""),
                "raw_vendor_bars_sha256": data_version.get("raw_vendor_bars_sha256", ""),
            }
        )
    return digest
