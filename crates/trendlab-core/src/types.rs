use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Kline {
    pub date: String,
    pub open: f64,
    pub close: f64,
    pub high: f64,
    pub low: f64,
    #[serde(default)]
    pub volume: f64,
    #[serde(default)]
    pub amount: f64,
    #[serde(default)]
    pub pct: f64,
    #[serde(default)]
    pub turnover: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FundFlow {
    pub date: String,
    pub main_net: f64,
    #[serde(default)]
    pub super_large_net: f64,
    #[serde(default)]
    pub large_net: f64,
    #[serde(default)]
    pub medium_net: f64,
    #[serde(default)]
    pub small_net: f64,
    #[serde(default)]
    pub main_pct: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EngineConfig {
    #[serde(default = "w_trend")]
    pub w_trend: f64,
    #[serde(default = "w_mom")]
    pub w_momentum: f64,
    #[serde(default = "w_bo")]
    pub w_breakout: f64,
    #[serde(default = "w_vp")]
    pub w_volume: f64,
    #[serde(default = "w_pat")]
    pub w_pattern: f64,
    #[serde(default = "d75")]
    pub strong_buy_score: i32,
    #[serde(default = "d60")]
    pub strong_buy_confidence: i32,
    #[serde(default = "d4")]
    pub strong_buy_modules: i32,
    #[serde(default = "d65")]
    pub buy_score: i32,
    #[serde(default = "d45")]
    pub buy_confidence: i32,
    #[serde(default = "d3")]
    pub buy_modules: i32,
    #[serde(default = "d60")]
    pub cautious_score: i32,
    #[serde(default = "stop_name")]
    pub stop_loss: String,
    #[serde(default = "d05")]
    pub fixed_stop_pct: f64,
    #[serde(default)]
    pub chanlun_bonus: bool,
    #[serde(default)]
    pub sell_symmetric: bool,
    #[serde(default)]
    pub atr_position: bool,
}

fn w_trend() -> f64 { 0.25 }
fn w_mom() -> f64 { 0.20 }
fn w_bo() -> f64 { 0.20 }
fn w_vp() -> f64 { 0.20 }
fn w_pat() -> f64 { 0.15 }
fn d75() -> i32 { 75 }
fn d65() -> i32 { 65 }
fn d60() -> i32 { 60 }
fn d45() -> i32 { 45 }
fn d4() -> i32 { 4 }
fn d3() -> i32 { 3 }
fn d05() -> f64 { 0.05 }
fn stop_name() -> String { "hybrid".into() }

impl Default for EngineConfig {
    fn default() -> Self {
        serde_json::from_value(serde_json::json!({})).unwrap()
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BacktestCost {
    /// 单边佣金（成交额比例），默认万 2.5
    #[serde(default = "comm")]
    pub commission: f64,
    /// 卖出印花税
    #[serde(default = "stamp")]
    pub stamp_duty: f64,
    /// 滑点（价格比例）
    #[serde(default = "slip")]
    pub slippage: f64,
}

fn comm() -> f64 { 0.00025 }
fn stamp() -> f64 { 0.0005 }
fn slip() -> f64 { 0.001 }

impl Default for BacktestCost {
    fn default() -> Self {
        Self {
            commission: comm(),
            stamp_duty: stamp(),
            slippage: slip(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AnalyzeInput {
    pub klines: Vec<Kline>,
    #[serde(default)]
    pub flows: Vec<FundFlow>,
    #[serde(default)]
    pub index: Vec<Kline>,
    #[serde(default)]
    pub weekly: Vec<Kline>,
    #[serde(default)]
    pub config: EngineConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct TradePlan {
    pub action: String,
    pub entry_price: f64,
    pub stop_loss: f64,
    pub target_price: f64,
    pub position_size: String,
    pub holding_period: String,
    pub risk_reward_ratio: f64,
    pub max_loss_pct: f64,
    pub notes: String,
    pub stop_method: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Prediction {
    pub direction: String,
    pub horizon_days: i32,
    pub score: f64,
    /// 未校准倾向 0~1，UI 应显示为「规则倾向」而非胜率
    pub tilt: f64,
    pub confidence: f64,
    pub drivers: Vec<String>,
    pub model: String,
    pub disclaimer: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SignalResult {
    pub action: String,
    pub score: i32,
    pub confidence: i32,
    pub risk_level: String,
    pub signal_strength: String,
    pub plain_summary: String,
    pub trade_plan: TradePlan,
    pub module_scores: serde_json::Value,
    pub buy_signals: Vec<String>,
    pub sell_signals: Vec<String>,
    pub risk_warnings: Vec<String>,
    pub key_levels: serde_json::Value,
    pub description: String,
    pub trend: serde_json::Value,
    pub patterns: serde_json::Value,
    pub volume_price: serde_json::Value,
    pub breakouts: serde_json::Value,
    pub momentum: serde_json::Value,
    pub prediction: Prediction,
    pub original_action: String,
    pub veto_reason: String,
    pub position_advice: String,
    pub risk_notes: Vec<String>,
    pub risk_reward: f64,
}
