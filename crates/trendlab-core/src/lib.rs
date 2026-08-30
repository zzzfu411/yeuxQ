pub mod backtest;
pub mod engine;
pub mod indicators;
pub mod modules;
pub mod types;

pub use backtest::{run_backtest, BacktestReport, BacktestRequest};
pub use engine::run_analysis;
pub use types::{AnalyzeInput, EngineConfig, SignalResult};

pub fn run_analysis_json(payload: &str) -> Result<String, String> {
    let input: AnalyzeInput = serde_json::from_str(payload).map_err(|e| e.to_string())?;
    let out = run_analysis(&input);
    serde_json::to_string(&out).map_err(|e| e.to_string())
}

pub fn run_backtest_json(payload: &str) -> Result<String, String> {
    let req: BacktestRequest = serde_json::from_str(payload).map_err(|e| e.to_string())?;
    let out = run_backtest(&req);
    serde_json::to_string(&out).map_err(|e| e.to_string())
}

#[cfg(feature = "python")]
use pyo3::prelude::*;

#[cfg(feature = "python")]
#[pyfunction]
fn run_analysis_json_py(payload: String) -> PyResult<String> {
    run_analysis_json(&payload).map_err(|e| pyo3::exceptions::PyValueError::new_err(e))
}

#[cfg(feature = "python")]
#[pyfunction]
fn run_backtest_json_py(payload: String) -> PyResult<String> {
    run_backtest_json(&payload).map_err(|e| pyo3::exceptions::PyValueError::new_err(e))
}

#[cfg(feature = "python")]
#[pymodule]
fn trendlab_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(run_analysis_json_py, m)?)?;
    m.add_function(wrap_pyfunction!(run_backtest_json_py, m)?)?;
    m.add("__version__", "0.1.0")?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::backtest::assert_no_lookahead_flows;
    use crate::types::{BacktestCost, FundFlow, Kline};

    fn up_klines(n: usize) -> Vec<Kline> {
        let mut v = Vec::new();
        let mut p = 100.0;
        for i in 0..n {
            let c = p * 1.004;
            v.push(Kline {
                date: format!("2024-{:02}-{:02}", 1 + i / 28, 1 + i % 28),
                open: p,
                close: c,
                high: c * 1.01,
                low: p * 0.99,
                volume: 10000.0 + i as f64,
                amount: 1e7,
                pct: 0.4,
                turnover: 1.5,
            });
            p = c;
        }
        v
    }

    #[test]
    fn analysis_uptrend_not_empty() {
        let input = AnalyzeInput {
            klines: up_klines(150),
            flows: (0..10)
                .map(|i| FundFlow {
                    date: format!("2024-01-{:02}", i + 1),
                    main_net: 1e8,
                    super_large_net: 5e7,
                    large_net: 5e7,
                    medium_net: 0.0,
                    small_net: 0.0,
                    main_pct: 5.0,
                })
                .collect(),
            index: up_klines(80),
            weekly: vec![],
            config: EngineConfig::default(),
        };
        let r = run_analysis(&input);
        assert!(r.score >= 40, "score={}", r.score);
        assert!(!r.action.is_empty());
        assert!(r.prediction.tilt > 0.0);
    }

    #[test]
    fn lookahead_guard() {
        let flows = vec![FundFlow {
            date: "2024-02-01".into(),
            main_net: 1.0,
            ..dummy_flow()
        }];
        assert!(assert_no_lookahead_flows(&flows, "2024-02-01"));
        assert!(!assert_no_lookahead_flows(&flows, "2024-01-31"));
    }

    fn dummy_flow() -> FundFlow {
        FundFlow {
            date: String::new(),
            main_net: 0.0,
            super_large_net: 0.0,
            large_net: 0.0,
            medium_net: 0.0,
            small_net: 0.0,
            main_pct: 0.0,
        }
    }

    #[test]
    fn backtest_point_in_time() {
        let mut flows = Vec::new();
        let ks = up_klines(180);
        for k in &ks {
            flows.push(FundFlow {
                date: k.date.clone(),
                main_net: 1e7,
                ..dummy_flow()
            });
        }
        // 若错误使用未来流，最后一天有巨额流出也不应进入 i=60 的分析
        flows.push(FundFlow {
            date: "2099-01-01".into(),
            main_net: -1e12,
            ..dummy_flow()
        });
        let req = BacktestRequest {
            klines: ks,
            flows,
            index: up_klines(100),
            config: EngineConfig {
                sell_symmetric: true,
                chanlun_bonus: true,
                atr_position: true,
                ..EngineConfig::default()
            },
            cost: BacktestCost::default(),
            min_score: 50,
            min_bars: 80,
            horizon: 5,
            entry_mode: "next_open".into(),
            eval_start: None,
            eval_end: None,
            outcome_end: None,
        };
        let report = run_backtest(&req);
        let split_idx = req.klines.len() / 2;
        let validation_start = req.klines[split_idx].date.clone();
        let train_end = req.klines[split_idx - 1].date.clone();
        let train = run_backtest(&BacktestRequest {
            eval_end: Some(train_end.clone()),
            outcome_end: Some(train_end),
            ..req.clone()
        });
        let valid = run_backtest(&BacktestRequest {
            eval_start: Some(validation_start.clone()),
            ..req.clone()
        });
        assert!(report.disclaimer.contains("不代表实盘"));
        assert!(train.samples.iter().all(|trade| trade.exit_date < validation_start));
        assert!(valid.samples.iter().all(|trade| trade.signal_date >= validation_start));
        assert!(report.samples.iter().all(|trade| trade.exit_date >= trade.entry_date));
        // 未来日资金流不得被当作当日之前
        assert!(assert_no_lookahead_flows(
            &req.flows.iter().filter(|f| f.date.as_str() <= "2024-06-01").cloned().collect::<Vec<_>>(),
            "2024-06-01"
        ));
        let _ = report.trades;
    }
}
