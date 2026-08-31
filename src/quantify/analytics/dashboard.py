"""Build a self-contained, dependency-free HTML view of a research report.

The regular research report deliberately remains a small, file-oriented
artifact.  This module adds a companion view for people who want to inspect a
run in a browser without installing a dashboard framework or loading assets
from the network.  It only reads the report directory and emits inline CSS and
SVG; it never changes a report or creates a trading instruction.

The parser is intentionally conservative.  ``summary.json`` is required,
while all other evidence files are optional.  Missing, malformed or unknown
gate states are rendered as unavailable/BLOCK (the safe default) instead of
being silently treated as a passing result.
"""

from __future__ import annotations

import csv
from collections import Counter, deque
from collections.abc import Mapping, Sequence
import html
import json
import math
from pathlib import Path
from typing import Any


RISK_NOTICE = (
    "风险提示：历史回测不代表未来收益。本页面仅用于研究与仿真，"
    "不构成投资建议，不连接券商，不自动下单。"
)
_VALID_GATE_STATES = {"PASS", "WATCH", "BLOCK"}
_MAX_CHART_POINTS = 180
_POSITION_COLUMNS = (
    "date",
    "symbol",
    "quantity",
    "available_qty",
    "price",
    "market_value",
    "weight",
)
_POSITION_LABELS = {
    "date": "日期",
    "symbol": "标的",
    "quantity": "数量",
    "available_qty": "可用",
    "price": "价格",
    "market_value": "市值",
    "weight": "权重",
}
_OPTIONAL_JSON_FILES = {
    "data_audit": "data_audit.json",
    "llm_review": "llm_review.json",
}
_GOAL_JSON_FILES = (
    "goal_status.json",
    "capital_goal_status.json",
    "first_million_readiness.json",
)


class DashboardInputError(ValueError):
    """Raised when the required report input is missing or invalid."""


def build_dashboard(report_dir: str | Path, *, title: str | None = None) -> str:
    """Return a complete, self-contained HTML dashboard for ``report_dir``.

    ``summary.json`` is the only required input.  The standard report CSVs and
    gate JSON files are read on a best-effort basis so a partially generated
    run can still be inspected.  Optional input failures are shown in the
    resulting page and never upgrade a gate to PASS.
    """

    root = Path(report_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"Research report directory does not exist: {root}")

    summary = _read_required_json(root / "summary.json")
    assumptions = _mapping(summary.get("assumptions"))
    evidence = _mapping(summary.get("evidence"))

    optional: dict[str, dict[str, Any]] = {}
    issues: list[str] = []
    for key, filename in _OPTIONAL_JSON_FILES.items():
        payload, issue = _read_optional_json(root / filename)
        optional[key] = payload
        if issue:
            issues.append(issue)

    goal_payload: dict[str, Any] = {}
    goal_filename: str | None = None
    for filename in _GOAL_JSON_FILES:
        candidate = root / filename
        if candidate.is_file():
            goal_payload, issue = _read_optional_json(candidate)
            goal_filename = filename
            if issue:
                issues.append(issue)
            break

    equity_rows, issue = _read_csv(root / "equity.csv")
    if issue:
        issues.append(issue)
    factor_rows, issue = _read_csv(root / "factor_ic.csv")
    if issue:
        issues.append(issue)
    turnover_rows, issue = _read_csv(root / "turnover.csv")
    if issue:
        issues.append(issue)
    order_rows, issue = _read_csv(root / "orders.csv")
    if issue:
        issues.append(issue)
    position_rows, issue = _read_csv(root / "positions.csv", tail=10)
    if issue:
        issues.append(issue)

    equity_all_points = _numeric_series(equity_rows, ("equity",), downsample=False)
    equity_points = _downsample(equity_all_points)
    drawdown_points = _drawdown_series(equity_all_points)
    factor_points = _numeric_series(factor_rows, ("rank_ic", "factor_ic", "ic"))
    turnover_all_points, turnover_is_rate = _turnover_series(turnover_rows, downsample=False)
    turnover_points = _downsample(turnover_all_points)

    rejected_count, order_count, rejection_counts = _rejection_stats(order_rows)
    reject_rate = rejected_count / order_count if order_count else None
    if not order_rows:
        summary_reject_rate = _number(summary.get("reject_rate"))
        summary_order_count = _integer(summary.get("order_count"))
        summary_rejected_count = _integer(summary.get("rejected_order_count"))
        if summary_reject_rate is not None:
            reject_rate = summary_reject_rate
        if summary_order_count is not None:
            order_count = summary_order_count
        if summary_rejected_count is not None:
            rejected_count = summary_rejected_count

    average_turnover = (
        _mean([value for _, value in turnover_all_points]) if turnover_is_rate else None
    )
    data_status, data_available, data_detail = _gate_state(
        optional["data_audit"],
        ("status",),
        # A summary digest is useful context, but it cannot substitute for a
        # missing or malformed audit artifact.  Keep the gate fail-closed.
        fallback=evidence.get("data_audit_status") if optional["data_audit"] else None,
    )
    llm_status, llm_available, llm_detail = _gate_state(
        optional["llm_review"],
        ("decision", "status"),
    )
    goal_status, goal_available, goal_detail = _gate_state(
        goal_payload,
        ("decision", "status", "release_readiness", "overall_status"),
    )

    display_title = title or _optional_text(summary.get("title")) or f"研究报告 · {root.name}"
    source = _optional_text(assumptions.get("data_source")) or "未记录"
    start = _optional_text(assumptions.get("start"))
    end = _optional_text(assumptions.get("end"))
    date_range = f"{start} → {end}" if start and end else "日期范围未记录"

    kpis = [
        _kpi_card("total_return", "总收益", _number(summary.get("total_return")), "percent"),
        _kpi_card(
            "annualized_return",
            "几何年化",
            _number(summary.get("annualized_return")),
            "percent",
        ),
        _kpi_card("sharpe_ratio", "夏普比率", _number(summary.get("sharpe_ratio")), "number"),
        _kpi_card("max_drawdown", "最大回撤", _number(summary.get("max_drawdown")), "percent"),
        _kpi_card("win_rate", "胜率", _number(summary.get("win_rate")), "percent"),
        _kpi_card("average_turnover", "平均换手", average_turnover, "percent"),
        _kpi_card("reject_rate", "拒单率", reject_rate, "percent"),
    ]

    audit_findings = _finding_lines(optional["data_audit"].get("findings"))
    llm_findings = _finding_lines(optional["llm_review"].get("findings"))
    if audit_findings:
        finding_block = (
            f'<div class="finding-group"><h3>数据审计提示</h3>{_list_html(audit_findings)}</div>'
        )
    else:
        finding_block = '<div class="finding-group"><h3>数据审计提示</h3><p class="muted">暂无可读审计条目。</p></div>'
    if llm_findings:
        finding_block += (
            f'<div class="finding-group"><h3>研究审查提示</h3>{_list_html(llm_findings)}</div>'
        )

    optional_note = ""
    if not optional["llm_review"]:
        optional_note = "llm_review.json 未提供；审查门按安全默认显示 BLOCK。"
    if goal_filename and not goal_payload:
        optional_note = f"{goal_filename} 无法读取；目标门按安全默认显示 BLOCK。"
    if optional_note:
        issues.append(optional_note)

    issue_html = ""
    if issues:
        unique_issues = list(dict.fromkeys(issues))
        issue_html = (
            '<section class="card input-status" aria-labelledby="input-status-title">'
            '<h2 id="input-status-title">输入与证据状态</h2>'
            f"{_list_html(unique_issues, class_name='status-list')}"
            "</section>"
        )

    goal_card = ""
    if goal_filename or goal_payload:
        goal_card = _gate_card(
            "目标审查",
            "goal",
            goal_status,
            goal_available,
            goal_detail,
            source=goal_filename or "goal_status.json",
        )

    positions_html = _positions_table(position_rows)
    order_summary = (
        f"共记录 {_format_count(order_count)} 条订单，拒单 {_format_count(rejected_count)} 条。"
        if order_count
        else "未找到可统计的订单记录。"
    )
    turnover_label = "换手率（turnover_pct）" if turnover_is_rate else "换手数据"
    turnover_hint = (
        "换手越高，佣金、印花税和滑点越可能吞噬纸面收益。"
        if turnover_is_rate
        else "未找到 turnover_pct 列，无法把原始换手金额换算为比例。"
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="referrer" content="no-referrer">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:;">
  <title>{_escape(display_title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #17202a;
      --muted: #64748b;
      --line: #dbe3ec;
      --paper: #f5f7fb;
      --card: #ffffff;
      --accent: #2563eb;
      --good: #16803c;
      --watch: #a16207;
      --bad: #b42318;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--paper); color: var(--ink); font-family: Arial, "Microsoft YaHei", "Noto Sans CJK SC", sans-serif; line-height: 1.5; }}
    main {{ width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 30px 0 48px; }}
    header {{ margin-bottom: 18px; }}
    h1, h2, h3, p {{ margin-top: 0; }}
    h1 {{ margin-bottom: 8px; font-size: clamp(1.55rem, 3vw, 2.25rem); letter-spacing: -.02em; }}
    h2 {{ margin-bottom: 12px; font-size: 1.05rem; }}
    h3 {{ margin-bottom: 8px; font-size: .92rem; }}
    .subtitle {{ color: var(--muted); margin-bottom: 14px; }}
    .notice {{ margin: 0 0 18px; padding: 13px 16px; border: 1px solid #f3c77a; border-radius: 10px; color: #7c4a03; background: #fff8e8; font-weight: 600; }}
    .boundary {{ display: inline-flex; flex-wrap: wrap; gap: 8px; color: var(--muted); font-size: .78rem; letter-spacing: .04em; }}
    .boundary span {{ padding: 4px 8px; border: 1px solid var(--line); border-radius: 999px; background: #fff; }}
    .card {{ background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 18px; box-shadow: 0 5px 18px rgba(27, 47, 74, .04); }}
    .gate-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin: 18px 0; }}
    .gate {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 70px; }}
    .gate-label {{ font-weight: 700; }}
    .gate-source {{ color: var(--muted); font-size: .78rem; margin-top: 3px; overflow-wrap: anywhere; }}
    .badge {{ display: inline-flex; align-items: center; justify-content: center; min-width: 68px; padding: 5px 9px; border-radius: 999px; font-size: .75rem; font-weight: 800; letter-spacing: .04em; }}
    .badge-pass {{ color: #075e2d; background: #dcfce7; border: 1px solid #86efac; }}
    .badge-watch {{ color: #854d0e; background: #fef3c7; border: 1px solid #fcd34d; }}
    .badge-block {{ color: #8a1c13; background: #fee2e2; border: 1px solid #fca5a5; }}
    .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin: 0 0 18px; }}
    .kpi {{ padding: 14px; background: var(--card); border: 1px solid var(--line); border-radius: 12px; }}
    .kpi-label {{ color: var(--muted); font-size: .8rem; }}
    .kpi-value {{ margin-top: 5px; font-size: 1.35rem; font-weight: 800; font-variant-numeric: tabular-nums; }}
    .kpi-good .kpi-value {{ color: var(--good); }}
    .kpi-watch .kpi-value {{ color: var(--watch); }}
    .kpi-bad .kpi-value {{ color: var(--bad); }}
    .kpi-na .kpi-value {{ color: var(--muted); font-size: 1rem; }}
    .chart-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }}
    .chart-card {{ min-width: 0; }}
    .chart-card.wide {{ grid-column: 1 / -1; }}
    .chart-caption {{ margin: 7px 0 0; color: var(--muted); font-size: .84rem; }}
    .chart-wrap {{ width: 100%; overflow-x: auto; }}
    svg.chart {{ display: block; width: 100%; min-width: 360px; height: auto; }}
    svg.chart text {{ font-family: Arial, "Microsoft YaHei", sans-serif; fill: #64748b; font-size: 11px; }}
    .meta {{ display: flex; flex-wrap: wrap; gap: 8px 18px; margin: 0 0 18px; color: var(--muted); font-size: .86rem; }}
    .meta strong {{ color: var(--ink); }}
    .positions {{ overflow-x: auto; }}
    table {{ width: 100%; min-width: 620px; border-collapse: collapse; font-size: .84rem; }}
    th, td {{ padding: 8px 9px; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap; }}
    th {{ color: var(--muted); font-weight: 700; background: #f8fafc; }}
    .findings {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; margin-top: 14px; }}
    .finding-group {{ padding: 13px; border: 1px solid var(--line); border-radius: 10px; background: #fbfdff; }}
    .finding-list, .status-list {{ margin: 0; padding-left: 20px; color: #475569; font-size: .86rem; }}
    .muted, .empty {{ color: var(--muted); }}
    .input-status {{ margin-top: 14px; }}
    footer {{ margin-top: 22px; color: var(--muted); font-size: .78rem; }}
    @media (max-width: 720px) {{
      main {{ width: min(100% - 20px, 1180px); padding-top: 20px; }}
      .chart-grid {{ grid-template-columns: 1fr; }}
      .chart-card.wide {{ grid-column: auto; }}
      .card {{ padding: 14px; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>{_escape(display_title)}</h1>
      <p class="subtitle">数据源：{_escape(source)}　|　样本：{_escape(date_range)}　|　报告目录：{_escape(root.name)}</p>
      <p class="notice" role="note">{_escape(RISK_NOTICE)}</p>
      <div class="boundary" aria-label="运行边界">
        <span>RESEARCH-ONLY</span><span>NO BROKER</span><span>NO LIVE ORDERS</span>
      </div>
    </header>

    <section class="gate-grid" aria-label="审查门状态">
      {_gate_card("数据审计", "data-audit", data_status, data_available, data_detail, source="data_audit.json")}
      {_gate_card("研究审查", "llm-review", llm_status, llm_available, llm_detail, source="llm_review.json")}
      {goal_card}
    </section>

    <section class="kpi-grid" aria-label="核心指标">
      {"".join(kpis)}
    </section>

    <div class="meta">
      <span><strong>样本点：</strong>{_format_count(_integer(summary.get("n_bars")))}</span>
      <span><strong>完整交易回合：</strong>{_format_count(_integer(summary.get("n_round_trips")))}</span>
      <span><strong>订单：</strong>{_format_count(order_count)}</span>
      <span><strong>拒单：</strong>{_format_count(rejected_count)}</span>
    </div>

    <section class="chart-grid" aria-label="研究图表">
      <article class="card chart-card wide">
        <h2>净值曲线与回撤</h2>
        <div class="chart-wrap">{_svg_line_chart(equity_points, title="净值曲线", color="#2563eb")}</div>
        <p class="chart-caption">看曲线是否持续、是否频繁创新高；回撤越深或恢复越慢，策略承受压力越大。</p>
      </article>
      <article class="card chart-card">
        <h2>最大回撤轨迹</h2>
        <div class="chart-wrap">{_svg_line_chart(drawdown_points, title="回撤（负值）", color="#c2413a", area=True, percent=True)}</div>
        <p class="chart-caption">这里把峰值到当前的损失画成负值；KPI 的最大回撤仍以正比例展示。</p>
      </article>
      <article class="card chart-card">
        <h2>因子 RankIC</h2>
        <div class="chart-wrap">{_svg_bar_chart(factor_points, title="因子 RankIC", color_mode="ic", percent=False)}</div>
        <p class="chart-caption">长期稳定为正比单次尖峰更有意义；接近 0 表示排序信号缺少预测力。</p>
      </article>
      <article class="card chart-card">
        <h2>{_escape(turnover_label)}</h2>
        <div class="chart-wrap">{_svg_bar_chart(turnover_points, title=turnover_label, color_mode="turnover", percent=turnover_is_rate)}</div>
        <p class="chart-caption">{_escape(turnover_hint)}</p>
      </article>
      <article class="card chart-card">
        <h2>拒单原因分布</h2>
        <div class="chart-wrap">{_svg_horizontal_bar_chart(rejection_counts, title="拒单原因分布")}</div>
        <p class="chart-caption">{_escape(order_summary)} T+1、涨跌停、停牌和现金约束都应进入人工复盘。</p>
      </article>
    </section>

    <section class="card positions" style="margin-top:14px" aria-labelledby="positions-title">
      <h2 id="positions-title">最近持仓快照</h2>
      {positions_html}
    </section>

    <section class="card findings" aria-label="审查提示">
      {finding_block}
    </section>

    {issue_html}

    <footer>本页是报告文件的只读可视化投影；任何图表或评分都不会改变确定性 PASS/WATCH/BLOCK 门，也不会产生交易许可。</footer>
  </main>
</body>
</html>
"""


def write_dashboard(
    report_dir: str | Path,
    output_path: str | Path | None = None,
    *,
    title: str | None = None,
) -> Path:
    """Render ``report_dir`` and write the HTML file, returning its path."""

    root = Path(report_dir)
    target = Path(output_path) if output_path is not None else root / "dashboard.html"
    content = build_dashboard(root, title=title)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _read_required_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Required report file is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DashboardInputError(f"Could not read required JSON file: {path}") from exc
    if not isinstance(payload, dict):
        raise DashboardInputError(f"Required JSON file must contain an object: {path}")
    return payload


def _read_optional_json(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.is_file():
        return {}, f"{path.name} 未提供。"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}, f"{path.name} 无法读取，相关状态按 BLOCK 处理。"
    if not isinstance(payload, dict):
        return {}, f"{path.name} 不是 JSON 对象，相关状态按 BLOCK 处理。"
    return payload, None


def _read_csv(
    path: Path,
    *,
    tail: int | None = None,
    max_rows: int | None = 100_000,
) -> tuple[list[dict[str, str]], str | None]:
    """Read a bounded CSV while retaining a useful tail for positions."""

    if not path.is_file():
        return [], f"{path.name} 未提供。"
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                return [], f"{path.name} 没有可用列名。"
            rows: deque[dict[str, str]] | list[dict[str, str]]
            rows = deque(maxlen=tail) if tail is not None else []
            truncated = False
            for index, raw in enumerate(reader):
                if max_rows is not None and index >= max_rows and tail is None:
                    truncated = True
                    break
                if not raw:
                    continue
                row = {
                    str(key).strip(): "" if value is None else str(value).strip()
                    for key, value in raw.items()
                    if key is not None
                }
                if tail is not None:
                    rows.append(row)
                else:
                    rows.append(row)  # type: ignore[union-attr]
            issue = (
                f"{path.name} 超过 {max_rows:,} 行，图表只读取前 {max_rows:,} 行。"
                if truncated and max_rows is not None
                else None
            )
            return list(rows), issue
    except (OSError, UnicodeError, csv.Error):
        return [], f"{path.name} 无法读取，相关图表显示为不可用。"


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _integer(value: object) -> int | None:
    number = _number(value)
    if number is None:
        return None
    return int(number)


def _text_value(value: object) -> str:
    if value is None:
        return "—"
    text = str(value).strip()
    return text or "—"


def _optional_text(value: object) -> str:
    """Return blank for absent metadata (use ``_text_value`` for UI cells)."""

    if value is None:
        return ""
    return str(value).strip()


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _row_value(row: Mapping[str, str], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is not None and value.strip() != "":
            return value
    return None


def _numeric_series(
    rows: Sequence[Mapping[str, str]],
    value_keys: Sequence[str],
    *,
    downsample: bool = True,
) -> list[tuple[str, float]]:
    points: list[tuple[str, float]] = []
    for row in rows:
        value = _number(_row_value(row, value_keys))
        if value is None:
            continue
        label = _row_value(row, ("timestamp", "date", "signal_date")) or str(len(points) + 1)
        points.append((_text_value(label), value))
    return _downsample(points) if downsample else points


def _turnover_series(
    rows: Sequence[Mapping[str, str]],
    *,
    downsample: bool = True,
) -> tuple[list[tuple[str, float]], bool]:
    rate_rows: list[tuple[str, float]] = []
    for row in rows:
        value = _number(_row_value(row, ("turnover_pct", "turnover_percent")))
        if value is None:
            continue
        label = _row_value(row, ("date", "timestamp", "signal_date")) or str(len(rate_rows) + 1)
        rate_rows.append((_text_value(label), value))
    if rate_rows:
        return (_downsample(rate_rows) if downsample else rate_rows), True

    # Keep an amount-only series visible, but do not present it as a rate.
    amount_rows: list[tuple[str, float]] = []
    for row in rows:
        value = _number(_row_value(row, ("turnover",)))
        if value is None:
            continue
        label = _row_value(row, ("date", "timestamp", "signal_date")) or str(len(amount_rows) + 1)
        amount_rows.append((_text_value(label), value))
    return (_downsample(amount_rows) if downsample else amount_rows), False


def _drawdown_series(points: Sequence[tuple[str, float]]) -> list[tuple[str, float]]:
    peak: float | None = None
    result: list[tuple[str, float]] = []
    for label, value in points:
        if peak is None or value > peak:
            peak = value
        if peak is None or peak <= 0:
            drawdown = 0.0
        else:
            drawdown = value / peak - 1.0
        result.append((label, drawdown * 100.0))
    return _downsample(result)


def _downsample(
    points: Sequence[tuple[str, float]], limit: int = _MAX_CHART_POINTS
) -> list[tuple[str, float]]:
    if len(points) <= limit:
        return list(points)
    if limit < 2:
        return [points[0]]
    indexes = {round(i * (len(points) - 1) / (limit - 1)) for i in range(limit)}
    return [points[index] for index in sorted(indexes)]


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _rejection_stats(rows: Sequence[Mapping[str, str]]) -> tuple[int, int, Counter[str]]:
    rejected = 0
    reasons: Counter[str] = Counter()
    for row in rows:
        status = (_row_value(row, ("status",)) or "").strip().lower()
        if status == "rejected":
            rejected += 1
            reason = _row_value(row, ("reason",)) or "未说明"
            reasons[_text_value(reason)] += 1
    return rejected, len(rows), reasons


def _normalise_gate(value: object) -> str:
    state = str(value).strip().upper() if value is not None else ""
    return state if state in _VALID_GATE_STATES else "BLOCK"


def _gate_state(
    payload: Mapping[str, Any],
    keys: Sequence[str],
    *,
    fallback: object = None,
) -> tuple[str, bool, str]:
    present = [(key, payload.get(key)) for key in keys if key in payload]
    if present:
        states: list[str] = []
        for _, raw in present:
            raw_state = str(raw).strip().upper() if raw is not None else ""
            if raw_state not in _VALID_GATE_STATES:
                return "BLOCK", False, "未知状态，按安全默认 BLOCK"
            states.append(raw_state)
        if len(set(states)) > 1:
            fields = ", ".join(key for key, _ in present)
            return "BLOCK", False, f"状态字段冲突（{fields}），按安全默认 BLOCK"
        state = states[0]
        return state, True, f"状态：{state}"
    if fallback is not None:
        state = _normalise_gate(fallback)
        if state == "BLOCK" and str(fallback).strip().upper() not in _VALID_GATE_STATES:
            return state, False, "未知状态，按安全默认 BLOCK"
        return state, True, f"状态：{state}（来自 summary.evidence）"
    return "BLOCK", False, "未提供，按安全默认 BLOCK"


def _status_class(status: str) -> str:
    return {"PASS": "pass", "WATCH": "watch", "BLOCK": "block"}.get(status, "block")


def _gate_card(
    label: str,
    key: str,
    status: str,
    available: bool,
    detail: str,
    *,
    source: str,
) -> str:
    css = _status_class(status)
    availability = "" if available else " · 不可验证"
    return (
        f'<article class="card gate" data-gate="{_escape(key)}">'
        f'<div><div class="gate-label">{_escape(label)}</div>'
        f'<div class="gate-source">{_escape(source)} · {_escape(detail)}{_escape(availability)}</div></div>'
        f'<span class="badge badge-{css}">{_escape(status)}</span></article>'
    )


def _kpi_card(key: str, label: str, value: float | None, kind: str) -> str:
    if value is None:
        formatted = "不可用"
        state = "na"
    else:
        formatted = _format_metric(value, kind)
        state = _kpi_state(key, value)
    return (
        f'<article class="kpi kpi-{state}" data-kpi="{_escape(key)}">'
        f'<div class="kpi-label">{_escape(label)}</div>'
        f'<div class="kpi-value">{_escape(formatted)}</div></article>'
    )


def _format_metric(value: float, kind: str) -> str:
    if kind == "percent":
        return f"{value:.2%}"
    return f"{value:.2f}"


def _kpi_state(key: str, value: float) -> str:
    if key in {"total_return", "annualized_return"}:
        return "good" if value >= 0 else "bad"
    if key == "sharpe_ratio":
        return "good" if value >= 0.8 else "watch" if value >= 0 else "bad"
    if key == "max_drawdown":
        return "bad" if value > 0.20 else "watch" if value > 0.10 else "good"
    if key == "reject_rate":
        return "bad" if value >= 0.20 else "watch" if value > 0.10 else "good"
    if key == "average_turnover":
        return "bad" if value > 0.20 else "watch" if value > 0.10 else "good"
    return "good"


def _format_count(value: int | None) -> str:
    return "—" if value is None else f"{value:,}"


def _finding_lines(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    lines: list[str] = []
    for item in value[:12]:
        if isinstance(item, Mapping):
            code = _text_value(item.get("code"))
            message = _text_value(item.get("message"))
            if code != "—" and message != "—":
                lines.append(f"{code}: {message}")
            elif message != "—":
                lines.append(message)
        elif item is not None:
            lines.append(_text_value(item))
    return lines


def _list_html(items: Sequence[str], *, class_name: str = "finding-list") -> str:
    if not items:
        return '<p class="muted">暂无</p>'
    list_items = "".join(f"<li>{_escape(item)}</li>" for item in items)
    return f'<ul class="{_escape(class_name)}">{list_items}</ul>'


def _positions_table(rows: Sequence[Mapping[str, str]]) -> str:
    if not rows:
        return '<p class="empty">暂无可用持仓数据。</p>'
    available = [column for column in _POSITION_COLUMNS if any(column in row for row in rows)]
    if not available:
        return '<p class="empty">positions.csv 缺少可识别列。</p>'
    header = "".join(f"<th>{_escape(_POSITION_LABELS[column])}</th>" for column in available)
    body_rows: list[str] = []
    for row in rows:
        cells = "".join(
            f"<td>{_escape(_format_cell(row.get(column, ''), column))}</td>" for column in available
        )
        body_rows.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def _format_cell(value: str, column: str) -> str:
    if not value:
        return "—"
    if column in {"quantity", "available_qty"}:
        number = _number(value)
        return f"{number:,.0f}" if number is not None else value
    if column in {"price", "market_value"}:
        number = _number(value)
        return f"{number:,.2f}" if number is not None else value
    if column == "weight":
        number = _number(value)
        return f"{number:.2%}" if number is not None else value
    return value


def _chart_svg_start(title: str, width: int, height: int) -> str:
    return (
        f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{_escape(title)}"><title>{_escape(title)}</title>'
    )


def _empty_svg(title: str, message: str = "暂无可用数据") -> str:
    return (
        _chart_svg_start(title, 760, 220)
        + f'<text x="380" y="116" text-anchor="middle">{_escape(message)}</text></svg>'
    )


def _bounds(values: Sequence[float], *, include_zero: bool = False) -> tuple[float, float]:
    low = min(values)
    high = max(values)
    if include_zero:
        low = min(low, 0.0)
        high = max(high, 0.0)
    if math.isclose(low, high):
        padding = max(abs(low) * 0.12, 1.0)
        low -= padding
        high += padding
    else:
        padding = (high - low) * 0.08
        low -= padding
        high += padding
    return low, high


def _axis_label(value: float, *, percent: bool = False) -> str:
    return f"{value:.1f}%" if percent else f"{value:.2f}"


def _svg_line_chart(
    points: Sequence[tuple[str, float]],
    *,
    title: str,
    color: str,
    area: bool = False,
    percent: bool = False,
) -> str:
    if not points:
        return _empty_svg(title)
    width, height = 760, 250
    left, right, top, bottom = 58, 18, 28, 34
    plot_width, plot_height = width - left - right, height - top - bottom
    values = [value for _, value in points]
    low, high = _bounds(values)

    def xy(index: int, value: float) -> tuple[float, float]:
        x = left if len(points) == 1 else left + index * plot_width / (len(points) - 1)
        y = top + (high - value) / (high - low) * plot_height
        return x, y

    coords = [xy(index, value) for index, (_, value) in enumerate(points)]
    polyline = " ".join(f"{x:.2f},{y:.2f}" for x, y in coords)
    chunks = [_chart_svg_start(title, width, height)]
    for tick in range(5):
        ratio = tick / 4
        y = top + ratio * plot_height
        value = high - ratio * (high - low)
        chunks.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{width - right}" y2="{y:.2f}" stroke="#e7edf4"/>'
        )
        chunks.append(
            f'<text x="{left - 8}" y="{y + 4:.2f}" text-anchor="end">{_escape(_axis_label(value, percent=percent))}</text>'
        )
    if area:
        zero_y = top + (high - 0.0) / (high - low) * plot_height
        area_points = f"{left:.2f},{zero_y:.2f} {polyline} {coords[-1][0]:.2f},{zero_y:.2f}"
        chunks.append(
            f'<polygon points="{area_points}" fill="{_escape(color)}" fill-opacity=".16"/>'
        )
    chunks.append(
        f'<polyline points="{polyline}" fill="none" stroke="{_escape(color)}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>'
    )
    for (label, value), (x, y) in zip(points, coords):
        chunks.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="2.4" fill="{_escape(color)}"><title>{_escape(label)} · {_escape(_axis_label(value, percent=percent))}</title></circle>'
        )
    chunks.append(f'<text x="{left}" y="{height - 8}">{_escape(points[0][0])}</text>')
    chunks.append(
        f'<text x="{width - right}" y="{height - 8}" text-anchor="end">{_escape(points[-1][0])}</text>'
    )
    chunks.append("</svg>")
    return "".join(chunks)


def _svg_bar_chart(
    points: Sequence[tuple[str, float]],
    *,
    title: str,
    color_mode: str,
    percent: bool,
) -> str:
    if not points:
        return _empty_svg(title)
    width, height = 760, 250
    left, right, top, bottom = 58, 18, 28, 34
    plot_width, plot_height = width - left - right, height - top - bottom
    values = [value for _, value in points]
    low, high = _bounds(values, include_zero=True)

    def y_for(value: float) -> float:
        return top + (high - value) / (high - low) * plot_height

    zero_y = y_for(0.0)
    slot = plot_width / max(len(points), 1)
    bar_width = max(1.5, min(22.0, slot * 0.72))
    chunks = [_chart_svg_start(title, width, height)]
    for tick in range(5):
        ratio = tick / 4
        y = top + ratio * plot_height
        value = high - ratio * (high - low)
        chunks.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{width - right}" y2="{y:.2f}" stroke="#e7edf4"/>'
        )
        chunks.append(
            f'<text x="{left - 8}" y="{y + 4:.2f}" text-anchor="end">{_escape(_axis_label(value, percent=percent))}</text>'
        )
    chunks.append(
        f'<line x1="{left}" y1="{zero_y:.2f}" x2="{width - right}" y2="{zero_y:.2f}" stroke="#9aa8b8" stroke-width="1.1"/>'
    )
    if color_mode == "ic":
        mean_value = _mean(values)
        if mean_value is not None:
            mean_y = y_for(mean_value)
            chunks.append(
                f'<line x1="{left}" y1="{mean_y:.2f}" x2="{width - right}" y2="{mean_y:.2f}" '
                'stroke="#475569" stroke-width="1.2" stroke-dasharray="5 4"/>'
            )
            chunks.append(
                f'<text x="{width - right - 4}" y="{mean_y - 5:.2f}" text-anchor="end">'
                f"均值 {_escape(_axis_label(mean_value, percent=percent))}</text>"
            )
    for index, (label, value) in enumerate(points):
        x = left + index * slot + (slot - bar_width) / 2
        y_value = y_for(value)
        y = min(y_value, zero_y)
        bar_height = max(abs(zero_y - y_value), 1.0)
        if color_mode == "ic":
            fill = "#16803c" if value >= 0 else "#c2413a"
        else:
            fill = "#d97706"
        chunks.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width:.2f}" height="{bar_height:.2f}" rx="1.5" fill="{fill}"><title>{_escape(label)} · {_escape(_axis_label(value, percent=percent))}</title></rect>'
        )
    chunks.append(f'<text x="{left}" y="{height - 8}">{_escape(points[0][0])}</text>')
    chunks.append(
        f'<text x="{width - right}" y="{height - 8}" text-anchor="end">{_escape(points[-1][0])}</text>'
    )
    chunks.append("</svg>")
    return "".join(chunks)


def _svg_horizontal_bar_chart(counts: Mapping[str, int], *, title: str) -> str:
    if not counts:
        return _empty_svg(title, "暂无拒单记录")
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:12]
    width = 760
    row_height = 30
    height = max(150, 54 + row_height * len(ordered))
    left, right, top = 154, 42, 30
    max_count = max(count for _, count in ordered) or 1
    chunks = [_chart_svg_start(title, width, height)]
    for index, (reason, count) in enumerate(ordered):
        y = top + index * row_height
        bar_width = (width - left - right) * count / max_count
        chunks.append(
            f'<text x="{left - 10}" y="{y + 17}" text-anchor="end">{_escape(reason)}</text>'
        )
        chunks.append(
            f'<rect x="{left}" y="{y + 4}" width="{bar_width:.2f}" height="20" rx="4" fill="#c2413a"><title>{_escape(reason)} · {_escape(count)}</title></rect>'
        )
        chunks.append(f'<text x="{left + bar_width + 7:.2f}" y="{y + 18}">{_escape(count)}</text>')
    chunks.append("</svg>")
    return "".join(chunks)


__all__ = ["DashboardInputError", "build_dashboard", "write_dashboard"]
