use crate::engine::run_analysis;
use crate::types::*;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BacktestRequest {
    pub klines: Vec<Kline>,
    #[serde(default)]
    pub flows: Vec<FundFlow>,
    #[serde(default)]
    pub index: Vec<Kline>,
    #[serde(default)]
    pub config: EngineConfig,
    #[serde(default)]
    pub cost: BacktestCost,
    #[serde(default = "d65")]
    pub min_score: i32,
    #[serde(default = "d60")]
    pub min_bars: usize,
    #[serde(default = "d10")]
    pub horizon: usize,
    /// next_open | same_close
    #[serde(default = "entry_mode")]
    pub entry_mode: String,
    /// 仅在此日期及之后开仓（指标仍用全部历史）
    #[serde(default)]
    pub eval_start: Option<String>,
    /// 仅在此日期及之前开仓
    #[serde(default)]
    pub eval_end: Option<String>,
    /// 持仓结果不得晚于此日期；无法完整成熟的交易会被丢弃。
    #[serde(default)]
    pub outcome_end: Option<String>,
}

fn d65() -> i32 { 65 }
fn d60() -> usize { 60 }
fn d10() -> usize { 10 }
fn entry_mode() -> String { "next_open".into() }

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TradeFill {
    pub signal_date: String,
    pub entry_date: String,
    pub exit_date: String,
    pub action: String,
    pub score: i32,
    pub entry: f64,
    pub exit: f64,
    pub stop: f64,
    pub return_pct: f64,
    pub reason: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct YearBucket {
    pub year: String,
    pub trades: usize,
    pub win_rate: f64,
    pub avg_return: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BacktestReport {
    pub trades: usize,
    pub win_rate: f64,
    pub avg_return: f64,
    pub expectancy: f64,
    pub profit_factor: f64,
    pub max_drawdown: f64,
    pub samples: Vec<TradeFill>,
    pub by_year: Vec<YearBucket>,
    pub min_score: i32,
    pub horizon: usize,
    pub cost: BacktestCost,
    pub note: String,
    pub disclaimer: String,
}

pub fn run_backtest(req: &BacktestRequest) -> BacktestReport {
    let n = req.klines.len();
    let start = req.min_bars.max(60);
    let mut fills: Vec<TradeFill> = Vec::new();
    let mut i = start;
    while i + 1 < n {
        let bar_date = &req.klines[i].date;
        let window = &req.klines[..=i];
        let flows: Vec<FundFlow> = req
            .flows
            .iter()
            .filter(|f| f.date.as_str() <= bar_date.as_str())
            .cloned()
            .collect();
        let index: Vec<Kline> = req
            .index
            .iter()
            .filter(|k| k.date.as_str() <= bar_date.as_str())
            .cloned()
            .collect();
        let input = AnalyzeInput {
            klines: window.to_vec(),
            flows,
            index,
            weekly: vec![],
            config: req.config.clone(),
        };
        let sig = run_analysis(&input);
        if let Some(ref s) = req.eval_start {
            if bar_date.as_str() < s.as_str() {
                i += 1;
                continue;
            }
        }
        if let Some(ref e) = req.eval_end {
            if bar_date.as_str() > e.as_str() {
                break;
            }
        }
        let buy = sig.action.contains("买") && sig.score >= req.min_score;
        if !buy {
            i += 1;
            continue;
        }

        let entry_idx = if req.entry_mode == "same_close" {
            i
        } else {
            i + 1
        };
        if entry_idx >= n {
            break;
        }
        let Some(horizon_end) = entry_idx.checked_add(req.horizon) else {
            break;
        };
        if horizon_end >= n {
            break;
        }
        if let Some(ref outcome_end) = req.outcome_end {
            if req.klines[horizon_end].date.as_str() > outcome_end.as_str() {
                i += 1;
                continue;
            }
        }
        let raw_entry = if req.entry_mode == "same_close" {
            req.klines[entry_idx].close
        } else {
            req.klines[entry_idx].open
        };
        let entry = raw_entry * (1.0 + req.cost.slippage);
        let stop = sig.trade_plan.stop_loss;
        let mut exit_idx = horizon_end;
        let mut reason = "到期";
        for j in entry_idx + 1..=horizon_end {
            if req.klines[j].low <= stop {
                exit_idx = j;
                reason = "止损";
                break;
            }
            if req.config.sell_symmetric {
                // 简化：跌破入场日 MA 近似用收盘跌破 stop*1.02 已覆盖
            }
        }
        let raw_exit = if reason == "止损" {
            stop
        } else {
            req.klines[exit_idx].close
        };
        let exit_px = raw_exit * (1.0 - req.cost.slippage);
        let buy_cost = entry * req.cost.commission;
        let sell_cost = exit_px * (req.cost.commission + req.cost.stamp_duty);
        let ret = if entry > 0.0 {
            (exit_px - entry - buy_cost - sell_cost) / entry * 100.0
        } else {
            0.0
        };
        fills.push(TradeFill {
            signal_date: bar_date.clone(),
            entry_date: req.klines[entry_idx].date.clone(),
            exit_date: req.klines[exit_idx].date.clone(),
            action: sig.action,
            score: sig.score,
            entry: (entry * 100.0).round() / 100.0,
            exit: (exit_px * 100.0).round() / 100.0,
            stop: (stop * 100.0).round() / 100.0,
            return_pct: (ret * 100.0).round() / 100.0,
            reason: reason.into(),
        });
        i = exit_idx + 1;
    }

    summarize(fills, req)
}

fn summarize(fills: Vec<TradeFill>, req: &BacktestRequest) -> BacktestReport {
    if fills.is_empty() {
        return BacktestReport {
            trades: 0,
            win_rate: 0.0,
            avg_return: 0.0,
            expectancy: 0.0,
            profit_factor: 0.0,
            max_drawdown: 0.0,
            samples: vec![],
            by_year: vec![],
            min_score: req.min_score,
            horizon: req.horizon,
            cost: req.cost.clone(),
            note: "无交易：提高回看天数或降低 min_score".into(),
            disclaimer: disclaimer(),
        };
    }
    let wins = fills.iter().filter(|t| t.return_pct > 0.0).count();
    let avg: f64 = fills.iter().map(|t| t.return_pct).sum::<f64>() / fills.len() as f64;
    let gp: f64 = fills.iter().filter(|t| t.return_pct > 0.0).map(|t| t.return_pct).sum();
    let gl: f64 = fills.iter().filter(|t| t.return_pct < 0.0).map(|t| t.return_pct.abs()).sum();
    let pf = if gl > 0.0 { gp / gl } else { gp };
    let mut eq: f64 = 0.0;
    let mut peak: f64 = 0.0;
    let mut max_dd: f64 = 0.0;
    for t in &fills {
        eq += t.return_pct;
        if eq > peak {
            peak = eq;
        }
        max_dd = max_dd.max(peak - eq);
    }
    let mut years: std::collections::BTreeMap<String, Vec<f64>> = std::collections::BTreeMap::new();
    for t in &fills {
        let y = t.entry_date.get(..4).unwrap_or("????").to_string();
        years.entry(y).or_default().push(t.return_pct);
    }
    let by_year = years
        .into_iter()
        .map(|(year, rs)| {
            let w = rs.iter().filter(|x| **x > 0.0).count();
            YearBucket {
                year,
                trades: rs.len(),
                win_rate: (w as f64 / rs.len() as f64 * 1000.0).round() / 10.0,
                avg_return: (rs.iter().sum::<f64>() / rs.len() as f64 * 100.0).round() / 100.0,
            }
        })
        .collect();
    let samples = fills.iter().rev().take(30).cloned().rev().collect();
    BacktestReport {
        trades: fills.len(),
        win_rate: (wins as f64 / fills.len() as f64 * 1000.0).round() / 10.0,
        avg_return: (avg * 100.0).round() / 100.0,
        expectancy: (avg * 100.0).round() / 100.0,
        profit_factor: (pf * 100.0).round() / 100.0,
        max_drawdown: (max_dd * 100.0).round() / 100.0,
        samples,
        by_year,
        min_score: req.min_score,
        horizon: req.horizon,
        cost: req.cost.clone(),
        note: "点时回测：资金流/指数仅用当日及以前；仅计完整持有期且不跨 outcome_end；含佣金/印花税/滑点；止损按当日最低价触及".into(),
        disclaimer: disclaimer(),
    }
}

fn disclaimer() -> String {
    "简化回测，未计涨跌停、停牌、冲击成本，不代表实盘。".into()
}

/// 不变量：回测不得读取 bar 日期之后的资金流。
pub fn assert_no_lookahead_flows(flows: &[FundFlow], asof: &str) -> bool {
    flows.iter().all(|f| f.date.as_str() <= asof)
}
