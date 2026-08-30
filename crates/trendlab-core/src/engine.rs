use crate::indicators::{atr, clamp_i};
use crate::modules::*;
use crate::types::*;
use serde_json::json;

pub fn run_analysis(input: &AnalyzeInput) -> SignalResult {
    let k = &input.klines;
    let cfg = &input.config;
    if k.len() < 30 {
        return SignalResult {
            action: "观望".into(),
            score: 0,
            description: "K线不足".into(),
            ..Default::default()
        };
    }

    let (mut t_score, trend, trend_sigs) = analyze_trend(k);
    let (v_score, vp, vp_sigs) = analyze_volume(k, &input.flows);
    let (p_score, patterns) = analyze_patterns(k);
    let (b_score, breakouts) = analyze_breakout(k);
    let (m_score, momentum) = analyze_momentum(k, &input.flows, &input.index);

    let mut weekly_align = 0i32;
    if input.weekly.len() >= 30 {
        let (wt, wto, _) = analyze_trend(&input.weekly);
        let _ = wt;
        let wd = wto["direction"].as_str().unwrap_or("");
        let td = trend["direction"].as_str().unwrap_or("");
        if wd == "上升" && td == "上升" {
            t_score = (t_score + 5).min(100);
            weekly_align = 1;
        } else if wd == "下降" && td == "上升" {
            t_score = (t_score - 5).max(0);
            weekly_align = -1;
        }
    }

    let mut score = (t_score as f64 * cfg.w_trend
        + m_score as f64 * cfg.w_momentum
        + b_score as f64 * cfg.w_breakout
        + v_score as f64 * cfg.w_volume
        + p_score as f64 * cfg.w_pattern) as i32;
    score = clamp_i(score, 0, 100);

    if cfg.chanlun_bonus {
        score = clamp_i(score + chanlun_bonus_score(k), 0, 100);
    }

    let module_scores = json!({
        "趋势": t_score, "动量质量": m_score, "突破": b_score, "量价": v_score, "形态": p_score
    });
    let modules_ok = [t_score, m_score, b_score, v_score, p_score]
        .iter()
        .filter(|s| **s >= 55)
        .count() as i32;
    let confidence = clamp_i((score as f64 * 0.8) as i32 + 12 * modules_ok - 40, 10, 95);

    let mut action = if score >= cfg.strong_buy_score {
        "强烈买入"
    } else if score >= cfg.buy_score {
        "买入"
    } else if score >= cfg.cautious_score {
        "谨慎买入"
    } else {
        "观望"
    };

    let mut buy_signals = Vec::new();
    let mut sell_signals = Vec::new();
    let td = trend["direction"].as_str().unwrap_or("");
    if td == "下降" {
        sell_signals.push("处于下降趋势".into());
    }
    if vp["direction"].as_str() == Some("看跌") {
        sell_signals.push(format!("量价{}", vp["pattern"].as_str().unwrap_or("")));
    }
    if let Some(arr) = breakouts.as_array() {
        for b in arr {
            let sig = b["signal"].as_str().unwrap_or("");
            let sys = b["system"].as_str().unwrap_or("");
            if sig == "向下突破" || sig == "多头止损" {
                sell_signals.push(format!("{sys}{sig}"));
            }
            if sig == "持仓" || sig == "突破买入" {
                buy_signals.push(format!("{sys}{sig}"));
            }
        }
    }
    if td == "上升" {
        buy_signals.push(format!("趋势{}", trend["stage"].as_str().unwrap_or("")));
    }
    if vp["direction"].as_str() == Some("看涨") {
        buy_signals.push(vp["pattern"].as_str().unwrap_or("").into());
    }

    if cfg.sell_symmetric {
        // 明确离场：结构破坏或价跌量增
        if trend_sigs.iter().any(|s| s.contains("跌破MA20"))
            || vp["pattern"].as_str() == Some("价跌量增")
            || sell_signals.iter().any(|s| s.contains("多头止损") || s.contains("向下突破"))
        {
            if score < 70 {
                action = "卖出";
            }
        }
    } else if sell_signals.len() >= 3 && score < 55 {
        action = "卖出";
    }

    let mut risk_points = 0;
    if td == "下降" {
        risk_points += 2;
    }
    if vp["direction"].as_str() == Some("看跌") {
        risk_points += 2;
    }
    if momentum["m_score"].as_i64().unwrap_or(50) < 30 {
        risk_points += 1;
    }
    let risk_level = if risk_points >= 5 {
        "高"
    } else if risk_points >= 3 {
        "中"
    } else {
        "低"
    };
    let strength = if score >= 75 {
        "强"
    } else if score >= 60 {
        "中"
    } else {
        "弱"
    };

    let plan = build_plan(action, k, &trend, &patterns, &breakouts, cfg);

    let mut warnings = Vec::new();
    if momentum["m_score"].as_i64().unwrap_or(50) < 40 {
        warnings.push("大盘环境偏弱，注意控制仓位".into());
    }
    if vp["pattern"].as_str() == Some("价跌量增") {
        warnings.push("价跌量增，抛压加重".into());
    }

    let mut result = SignalResult {
        action: action.into(),
        score,
        confidence,
        risk_level: risk_level.into(),
        signal_strength: strength.into(),
        plain_summary: format!(
            "综合{score}分({strength})，趋势{td}，建议{action}。量价{}，动量评级{}。",
            vp["pattern"].as_str().unwrap_or(""),
            momentum["grade"].as_str().unwrap_or("")
        ),
        trade_plan: plan,
        module_scores,
        buy_signals,
        sell_signals,
        risk_warnings: warnings,
        key_levels: json!({}),
        description: format!(
            "综合{score}分 | 趋势={td}({t_score}) | 量价={}({v_score}) | 突破={b_score} | 动量={}({m_score}) | 形态={p_score}",
            vp["pattern"].as_str().unwrap_or(""),
            momentum["grade"].as_str().unwrap_or("")
        ),
        trend,
        patterns,
        volume_price: vp,
        breakouts,
        momentum,
        prediction: predict(score, t_score, m_score, v_score, b_score, weekly_align),
        original_action: action.into(),
        ..Default::default()
    };
    apply_risk(&mut result, cfg);
    let _ = (trend_sigs, vp_sigs);
    result
}

fn build_plan(
    action: &str,
    k: &[Kline],
    trend: &serde_json::Value,
    patterns: &serde_json::Value,
    breakouts: &serde_json::Value,
    cfg: &EngineConfig,
) -> TradePlan {
    let entry = k.last().unwrap().close;
    let fixed = entry * (1.0 - cfg.fixed_stop_pct);
    let mut atr_stop = fixed;
    if let Some(arr) = breakouts.as_array() {
        for b in arr {
            let sig = b["signal"].as_str().unwrap_or("");
            if (sig == "持仓" || sig == "突破买入") && b["stop_loss"].as_f64().unwrap_or(0.0) > 0.0 {
                atr_stop = b["stop_loss"].as_f64().unwrap();
                break;
            }
        }
    }
    let mut stop = match cfg.stop_loss.as_str() {
        "fixed_pct" => fixed,
        "atr_2n" => atr_stop,
        _ => {
            let mut cands = vec![fixed, atr_stop];
            cands.retain(|s| *s < entry && *s > 0.0);
            cands.into_iter().fold(fixed, f64::max)
        }
    };
    let highs: Vec<f64> = k.iter().map(|x| x.high).collect();
    let lows: Vec<f64> = k.iter().map(|x| x.low).collect();
    let closes: Vec<f64> = k.iter().map(|x| x.close).collect();
    let n = atr(&highs, &lows, &closes, 20);
    if n > 0.0 && cfg.stop_loss == "hybrid" {
        let atr2 = entry - 2.0 * n;
        if atr2 < entry {
            stop = stop.max(atr2);
        }
    }

    let mut target = entry * 1.10;
    if let Some(arr) = patterns.as_array() {
        for name in ["头肩底", "双底", "箱体"] {
            if let Some(p) = arr.iter().find(|p| p["name"] == name && p["direction"] == "看涨") {
                if let Some(t) = p["target_price"].as_f64() {
                    if t > entry {
                        target = t;
                        break;
                    }
                }
            }
        }
    }
    let risk = entry - stop;
    let rr = if risk > 0.0 { ((target - entry) / risk * 10.0).round() / 10.0 } else { 0.0 };
    let pos = if cfg.atr_position && n > 0.0 && entry > 0.0 {
        let vol = n / entry;
        if vol > 0.04 {
            "轻仓(1/4) — ATR波动偏大"
        } else if vol > 0.025 {
            "半仓(1/2) — ATR中等"
        } else {
            "正常仓位 — ATR偏低"
        }
    } else if action.contains("买") {
        "半仓(1/2)"
    } else {
        "空仓等待"
    };
    TradePlan {
        action: action.into(),
        entry_price: (entry * 100.0).round() / 100.0,
        stop_loss: (stop * 100.0).round() / 100.0,
        target_price: (target * 100.0).round() / 100.0,
        position_size: pos.into(),
        holding_period: "中线(1-3月)".into(),
        risk_reward_ratio: rr,
        max_loss_pct: if entry > 0.0 { ((entry - stop) / entry * 1000.0).round() / 10.0 } else { 5.0 },
        notes: format!("趋势{}", trend["direction"].as_str().unwrap_or("")),
        stop_method: cfg.stop_loss.clone(),
    }
}

fn predict(score: i32, trend: i32, mom: i32, vp: i32, brk: i32, weekly: i32) -> Prediction {
    let z = -0.2
        + 0.035 * (score as f64 - 50.0)
        + 0.008 * (trend as f64 - 50.0)
        + 0.006 * (mom as f64 - 50.0)
        + 0.005 * (vp as f64 - 50.0)
        + 0.004 * (brk as f64 - 50.0)
        + 0.04 * weekly as f64;
    let tilt = 1.0 / (1.0 + (-z.clamp(-30.0, 30.0)).exp());
    let direction = if tilt >= 0.58 {
        "看多"
    } else if tilt <= 0.42 {
        "看空"
    } else {
        "中性"
    };
    let mut drivers = Vec::new();
    if score > 60 {
        drivers.push("综合分偏强".into());
    }
    if trend > 60 {
        drivers.push("趋势多头".into());
    }
    if weekly > 0 {
        drivers.push("周线共振".into());
    }
    if mom < 40 {
        drivers.push("动量偏弱".into());
    }
    Prediction {
        direction: direction.into(),
        horizon_days: 5,
        score: score as f64,
        tilt: (tilt * 10000.0).round() / 10000.0,
        confidence: ((tilt - 0.5).abs() * 1.4).min(0.95),
        drivers,
        model: "rule_v2_rust".into(),
        disclaimer: "tilt 为未校准规则倾向，不是历史胜率，不构成投资建议".into(),
    }
}

fn apply_risk(r: &mut SignalResult, cfg: &EngineConfig) {
    let original = r.action.clone();
    let m_score = r.momentum["m_score"].as_i64().unwrap_or(50) as i32;
    let mut text = String::new();
    if let Some(arr) = r.trend["signals"].as_array() {
        for s in arr {
            if let Some(s) = s.as_str() {
                text.push_str(s);
                text.push(' ');
            }
        }
    }
    if let Some(arr) = r.volume_price["signals"].as_array() {
        for s in arr {
            if let Some(s) = s.as_str() {
                text.push_str(s);
                text.push(' ');
            }
        }
    }
    text.push_str(r.volume_price["pattern"].as_str().unwrap_or(""));

    let hard = ["跌破MA20", "价跌量增", "OBV下降", "OBV走低", "OBV下行"]
        .iter()
        .find(|k| text.contains(*k));
    let soft = ["MA20向下", "MA20下行", "受压60日"]
        .iter()
        .find(|k| text.contains(*k));

    let scores = [
        r.module_scores["趋势"].as_i64().unwrap_or(50),
        r.module_scores["动量质量"].as_i64().unwrap_or(50),
        r.module_scores["突破"].as_i64().unwrap_or(50),
        r.module_scores["量价"].as_i64().unwrap_or(50),
        r.module_scores["形态"].as_i64().unwrap_or(50),
    ];
    let above = scores.iter().filter(|s| **s >= 55).count() as i32;
    let mut action = r.action.clone();
    let mut veto = String::new();
    let is_sell = action.contains("卖出");
    let is_buy = action.contains("买");

    if !is_sell {
        if hard.is_some() && (is_buy || r.score >= cfg.cautious_score) {
            action = "观望".into();
            veto = format!("硬否决：{}", hard.unwrap());
        } else {
            action = if r.score >= cfg.strong_buy_score
                && r.confidence >= cfg.strong_buy_confidence
                && above >= cfg.strong_buy_modules
            {
                "强烈买入".into()
            } else if r.score >= cfg.buy_score && r.confidence >= cfg.buy_confidence && above >= cfg.buy_modules {
                "买入".into()
            } else if r.score >= cfg.cautious_score {
                "谨慎买入".into()
            } else {
                "观望".into()
            };
            if let Some(s) = soft {
                if action == "强烈买入" {
                    action = "买入".into();
                    veto = format!("软否决：{s}");
                } else if action == "买入" {
                    action = "谨慎买入".into();
                    veto = format!("软否决：{s}");
                }
            }
        }
    }

    let mut position = if action.contains("买") {
        if m_score < 40 {
            if action == "强烈买入" {
                action = "买入".into();
            } else if action == "买入" {
                action = "谨慎买入".into();
            }
            "轻仓(1/4) — 大盘偏空".to_string()
        } else if m_score < 55 {
            "半仓(1/2) — 大盘中性偏弱".into()
        } else if r.trade_plan.position_size.contains("ATR") {
            r.trade_plan.position_size.clone()
        } else {
            "半仓(1/2)".into()
        }
    } else {
        "空仓等待".into()
    };

    if cfg.atr_position && action.contains("买") && r.trade_plan.position_size.contains("ATR") {
        position = r.trade_plan.position_size.clone();
    }

    let mut notes = Vec::new();
    let mut rr = r.trade_plan.risk_reward_ratio;
    let entry = r.trade_plan.entry_price;
    let stop = r.trade_plan.stop_loss;
    let target = r.trade_plan.target_price;
    if entry > stop && target > 0.0 {
        if rr == 0.0 {
            rr = ((target - entry) / (entry - stop) * 10.0).round() / 10.0;
        }
        if rr < 1.0 {
            notes.push(format!("盈亏比{rr}倒挂，不建议入场"));
            if action.contains("买") {
                action = "观望".into();
                veto = format!("{}盈亏比{rr}倒挂", if veto.is_empty() { String::new() } else { veto + "；" });
            }
        } else if rr < 1.5 {
            notes.push(format!("盈亏比{rr}偏低，谨慎操作"));
        } else {
            notes.push(format!("盈亏比{rr}"));
        }
    }

    r.original_action = original.clone();
    r.action = action.clone();
    r.veto_reason = veto.clone();
    r.position_advice = position.clone();
    r.risk_notes = notes;
    r.risk_reward = rr;
    r.trade_plan.action = action.clone();
    r.trade_plan.position_size = position;
    r.trade_plan.risk_reward_ratio = rr;
    if !veto.is_empty() {
        r.risk_warnings.insert(0, veto.clone());
    }
    if !veto.is_empty() && action != original {
        r.plain_summary = format!("[优化：{original}→{action}] {veto}。{}", r.plain_summary);
    }
}
