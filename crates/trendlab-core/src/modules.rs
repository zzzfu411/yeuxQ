use crate::indicators::*;
use crate::types::{FundFlow, Kline};
use serde_json::{json, Value};

pub fn analyze_trend(klines: &[Kline]) -> (i32, Value, Vec<String>) {
    if klines.len() < 30 {
        return (
            50,
            json!({"direction":"未知","strength":50,"stage":"数据不足","ma_arrangement":"未知","signals":["K线不足"]}),
            vec!["K线不足".into()],
        );
    }
    let closes: Vec<f64> = klines.iter().map(|k| k.close).collect();
    let highs: Vec<f64> = klines.iter().map(|k| k.high).collect();
    let lows: Vec<f64> = klines.iter().map(|k| k.low).collect();
    let ma5 = sma_series(&closes, 5);
    let ma10 = sma_series(&closes, 10);
    let ma20 = sma_series(&closes, 20);
    let ma60 = sma_series(&closes, 60);
    let d20 = ma_direction(&ma20, 5);
    let d60 = if closes.len() >= 65 {
        ma_direction(&ma60, 5)
    } else {
        "未知"
    };
    let price = *closes.last().unwrap();
    let ma20_v = ma20.last().and_then(|x| *x).unwrap_or(price);
    let ma60_v = ma60.last().and_then(|x| *x).unwrap_or(price);
    let ma5_v = ma5.last().and_then(|x| *x).unwrap_or(price);
    let ma10_v = ma10.last().and_then(|x| *x).unwrap_or(price);

    let mut scores = vec![
        ("ma20_dir", if d20 == "向上" { 30 } else if d20 == "走平" { 10 } else { 0 }),
        ("ma60_dir", if d60 == "向上" { 25 } else if d60 == "走平" { 10 } else if d60 == "未知" { 12 } else { 0 }),
        ("price_vs_ma20", if price >= ma20_v { 15 } else { 0 }),
        ("price_vs_ma60", if price >= ma60_v { 10 } else { 0 }),
        ("resonance", 8),
    ];
    let short_up = price >= ma5_v && ma5_v >= ma10_v;
    let mid_up = d20 == "向上";
    let long_up = price >= ma60_v * 0.98;
    if short_up && mid_up && long_up {
        scores[4].1 = 20;
    } else if mid_up && price >= ma20_v {
        scores[4].1 = 12;
    } else if d20 == "向下" && price < ma20_v {
        scores[4].1 = 0;
    }
    let mut strength = scores.iter().map(|s| s.1).sum::<i32>();
    let arrangement = if ma5_v >= ma10_v && ma10_v >= ma20_v && ma20_v >= ma60_v {
        "多头排列"
    } else if ma5_v <= ma10_v && ma10_v <= ma20_v && ma20_v <= ma60_v {
        "空头排列"
    } else {
        "纠缠"
    };
    let gain20 = if closes.len() >= 21 {
        pct_change(closes[closes.len() - 21], price)
    } else {
        0.0
    };
    let (direction, stage) = if arrangement == "多头排列" && d20 == "向上" && gain20 > 5.0 {
        ("上升", "强势上升阶段")
    } else if d20 == "向上" && price >= ma20_v {
        ("上升", "上升阶段")
    } else if d20 == "向下" && price < ma20_v {
        ("下降", "下降阶段")
    } else if arrangement == "空头排列" {
        ("下降", "弱势下降阶段")
    } else {
        ("震荡", "震荡整理阶段")
    };
    let adx = adx_approx(&highs, &lows, &closes, 14);
    if adx > 40.0 && direction == "上升" {
        strength = (strength + 5).min(100);
    }
    if adx > 40.0 && direction == "下降" {
        strength = (strength - 5).max(0);
    }
    let mut signals = Vec::new();
    if d20 == "向上" {
        signals.push("MA20向上".into());
    } else if d20 == "向下" {
        signals.push("MA20向下".into());
    }
    if price >= ma60_v {
        signals.push("站上60日决策线".into());
    } else {
        signals.push("受压60日决策线".into());
    }
    if price < ma20_v && d20 != "向上" {
        signals.push("跌破MA20".into());
    }
    if arrangement == "多头排列" {
        signals.push("均线多头排列".into());
    } else if arrangement == "空头排列" {
        signals.push("均线空头排列".into());
    }
    let obj = json!({
        "direction": direction,
        "strength": strength,
        "stage": stage,
        "ma_arrangement": arrangement,
        "ma_scores": scores.iter().map(|(k,v)| (*k,*v)).collect::<std::collections::HashMap<_,_>>(),
        "signals": signals,
        "adx": adx,
    });
    (strength, obj, signals)
}

fn adx_approx(highs: &[f64], lows: &[f64], closes: &[f64], period: usize) -> f64 {
    if closes.len() < period + 1 {
        return 0.0;
    }
    let mut up = 0.0;
    let mut down = 0.0;
    for i in closes.len() - period..closes.len() {
        let u = highs[i] - highs[i - 1];
        let d = lows[i - 1] - lows[i];
        if u > d && u > 0.0 {
            up += u;
        } else if d > u && d > 0.0 {
            down += d;
        }
    }
    let tot = up + down;
    if tot <= 0.0 {
        0.0
    } else {
        ((up - down).abs() / tot * 100.0).min(100.0)
    }
}

pub fn analyze_volume(klines: &[Kline], flows: &[FundFlow]) -> (i32, Value, Vec<String>) {
    if klines.len() < 10 {
        return (
            50,
            json!({"pattern":"数据不足","direction":"中性","confidence":50,"signals":[]}),
            vec![],
        );
    }
    let closes: Vec<f64> = klines.iter().map(|k| k.close).collect();
    let vols: Vec<f64> = klines.iter().map(|k| k.volume).collect();
    let n = closes.len();
    let g8 = if closes[n - 8] != 0.0 {
        (closes[n - 1] - closes[n - 8]) / closes[n - 8] * 100.0
    } else {
        0.0
    };
    let price_dir = if g8 > 2.0 {
        "涨"
    } else if g8 < -2.0 {
        "跌"
    } else {
        "平"
    };
    let vol_change = if vols.len() >= 8 {
        let ma3 = vols[n - 3..].iter().sum::<f64>() / 3.0;
        let ma5p = vols[n - 8..n - 3].iter().sum::<f64>() / 5.0;
        if ma5p != 0.0 {
            (ma3 - ma5p) / ma5p * 100.0
        } else {
            0.0
        }
    } else {
        0.0
    };
    let vol_dir = if vol_change > 30.0 {
        "增"
    } else if vol_change < -30.0 {
        "缩"
    } else {
        "平"
    };
    let (pattern, direction, mut conf) = match (price_dir, vol_dir) {
        ("涨", "增") => ("量价齐升", "看涨", 82),
        ("涨", "缩") => ("价涨量缩", "中性", 45),
        ("涨", "平") => ("价涨量平", "看涨", 60),
        ("跌", "增") => ("价跌量增", "看跌", 75),
        ("跌", "缩") => ("缩量回调", "中性", 55),
        ("跌", "平") => ("价跌量平", "看跌", 58),
        ("平", "增") => ("放量滞涨", "中性", 48),
        ("平", "缩") => ("缩量整理", "中性", 52),
        _ => ("量价平衡", "中性", 50),
    };
    let (flow_label, bonus, streak) = flow_features(flows);
    conf = clamp_i(conf + bonus, 20, 100);
    let mut signals = Vec::new();
    if direction == "看涨" {
        signals.push("量价配合良好".into());
    }
    if pattern == "价跌量增" {
        signals.push("价跌量增".into());
    }
    if !flow_label.is_empty() {
        signals.push(flow_label.clone());
    }
    if flow_label.contains("净流入") {
        signals.push("主力净流入".into());
    }
    if flow_label.contains("流出") {
        signals.push("主力净流出".into());
    }
    let score = if direction == "看涨" {
        conf
    } else if direction == "看跌" {
        (100 - conf).max(20)
    } else {
        50
    };
    let vol_ma = sma_last(&vols, 5).max(1.0);
    let volume_ratio = vols[n - 1] / vol_ma;
    let obj = json!({
        "pattern": pattern,
        "direction": direction,
        "confidence": conf,
        "volume_ratio": (volume_ratio * 100.0).round() / 100.0,
        "turnover": klines.last().map(|k| k.turnover).unwrap_or(0.0),
        "obv_trend": "走平",
        "signals": signals,
        "flow_features": {"main_flow_streak": streak, "label": flow_label, "bonus": bonus},
    });
    (score, obj, signals)
}

fn flow_features(flows: &[FundFlow]) -> (String, i32, i32) {
    if flows.is_empty() {
        return ("无资金流".into(), 0, 0);
    }
    let mains: Vec<f64> = flows.iter().map(|f| f.main_net).collect();
    let mut streak = 0i32;
    for v in mains.iter().rev() {
        if *v > 0.0 {
            streak += 1;
        } else {
            break;
        }
    }
    let sum5: f64 = mains.iter().rev().take(5).sum();
    let last = *mains.last().unwrap();
    let (mut bonus, mut label) = if streak >= 3 {
        (15, format!("连续{streak}日主力净流入"))
    } else if sum5 < 0.0 && last < -5e8 {
        (-15, "今日主力大幅流出".into())
    } else if sum5 > 0.0 && last > 0.0 {
        (10, "5日主力净流入".into())
    } else if sum5 < 0.0 {
        (-8, "5日主力净流出".into())
    } else {
        (0, "主力资金温和".into())
    };
    let super5: f64 = flows.iter().rev().take(5).map(|f| f.super_large_net).sum();
    let abs_m: f64 = flows.iter().rev().take(5).map(|f| f.main_net.abs()).sum::<f64>().max(1.0);
    if super5 / abs_m > 0.5 && last > 0.0 {
        bonus += 5;
        label.push_str("·超大单占优");
    }
    (label, bonus, streak)
}

pub fn analyze_patterns(klines: &[Kline]) -> (i32, Value) {
    if klines.len() < 20 {
        return (50, json!([]));
    }
    let price = klines.last().unwrap().close;
    let mut found = Vec::new();
    if let Some(p) = detect_box(klines, price) {
        found.push(p);
    }
    if let Some(p) = detect_double_bottom(klines, price) {
        found.push(p);
    }
    if let Some(p) = detect_hs_bottom(klines, price) {
        found.push(p);
    }
    if let Some(p) = detect_double_top(klines, price) {
        found.push(p);
    }
    found.sort_by(|a, b| b["confidence"].as_i64().cmp(&a["confidence"].as_i64()));
    found.truncate(5);
    let mut total = 50.0;
    for p in &found {
        let dir = p["direction"].as_str().unwrap_or("");
        let sign = if dir == "看涨" { 1.0 } else if dir == "看跌" { -1.0 } else { 0.0 };
        total += sign * p["confidence"].as_f64().unwrap_or(0.0) * 0.2;
    }
    (clamp_i(total as i32, 20, 100), json!(found))
}

fn detect_box(klines: &[Kline], price: f64) -> Option<Value> {
    let w = &klines[klines.len() - 20..];
    let upper = w.iter().map(|k| k.high).fold(f64::MIN, f64::max);
    let lower = w.iter().map(|k| k.low).fold(f64::MAX, f64::min);
    if upper <= lower {
        return None;
    }
    let amp = (upper - lower) / lower * 100.0;
    if !(5.0..=25.0).contains(&amp) {
        return None;
    }
    let (status, direction, conf, target) = if price >= upper * 0.98 {
        ("已突破", "看涨", 70, upper + (upper - lower))
    } else if price <= lower * 1.02 {
        ("跌破", "看跌", 65, lower - (upper - lower))
    } else {
        ("震荡中", "中性", 50, upper)
    };
    Some(json!({"name":"箱体","direction":direction,"confidence":conf,"status":status,"target_price": (target*100.0).round()/100.0,"key_levels":{"上沿":upper,"下沿":lower}}))
}

fn detect_double_bottom(klines: &[Kline], price: f64) -> Option<Value> {
    if klines.len() < 40 {
        return None;
    }
    let lows: Vec<f64> = klines.iter().map(|k| k.low).collect();
    let highs: Vec<f64> = klines.iter().map(|k| k.high).collect();
    let troughs = find_troughs(&lows, 3);
    if troughs.len() < 2 {
        return None;
    }
    let t1 = troughs[troughs.len() - 2];
    let t2 = troughs[troughs.len() - 1];
    if t2 - t1 < 5 {
        return None;
    }
    let (p1, p2) = (lows[t1], lows[t2]);
    if (p1 - p2).abs() / p1.max(p2) > 0.03 {
        return None;
    }
    let neck = highs[t1..=t2].iter().copied().fold(f64::MIN, f64::max);
    let bottom = p1.min(p2);
    let (status, conf) = if price >= neck * 0.995 {
        ("已突破", 62)
    } else if price > bottom * 1.02 {
        ("形成中", 48)
    } else {
        return None;
    };
    Some(json!({"name":"双底","direction":"看涨","confidence":conf,"status":status,"target_price":((neck+(neck-bottom))*100.0).round()/100.0,"key_levels":{"颈线":neck,"底部":bottom}}))
}

fn detect_hs_bottom(klines: &[Kline], price: f64) -> Option<Value> {
    if klines.len() < 50 {
        return None;
    }
    let lows: Vec<f64> = klines.iter().map(|k| k.low).collect();
    let highs: Vec<f64> = klines.iter().map(|k| k.high).collect();
    let troughs = find_troughs(&lows, 4);
    if troughs.len() < 3 {
        return None;
    }
    let (l, h, r) = (troughs[troughs.len()-3], troughs[troughs.len()-2], troughs[troughs.len()-1]);
    if !(lows[h] < lows[l] && lows[h] < lows[r]) {
        return None;
    }
    if (lows[l] - lows[r]).abs() / lows[l].max(lows[r]) > 0.05 {
        return None;
    }
    let neck = highs[l..=r].iter().copied().fold(f64::MIN, f64::max);
    let bottom = lows[h];
    let status = if price >= neck * 0.995 { "已突破" } else { "形成中" };
    let conf = if status == "已突破" { 68 } else { 50 };
    Some(json!({"name":"头肩底","direction":"看涨","confidence":conf,"status":status,"target_price":((neck+(neck-bottom))*100.0).round()/100.0,"key_levels":{"颈线":neck,"头部":bottom}}))
}

fn detect_double_top(klines: &[Kline], price: f64) -> Option<Value> {
    if klines.len() < 40 {
        return None;
    }
    let highs: Vec<f64> = klines.iter().map(|k| k.high).collect();
    let lows: Vec<f64> = klines.iter().map(|k| k.low).collect();
    let peaks = find_peaks(&highs, 3);
    if peaks.len() < 2 {
        return None;
    }
    let (p1, p2) = (peaks[peaks.len()-2], peaks[peaks.len()-1]);
    if p2 - p1 < 5 {
        return None;
    }
    let (h1, h2) = (highs[p1], highs[p2]);
    if (h1 - h2).abs() / h1.max(h2) > 0.03 {
        return None;
    }
    let neck = lows[p1..=p2].iter().copied().fold(f64::MAX, f64::min);
    let top = h1.max(h2);
    let (status, conf) = if price <= neck * 1.005 {
        ("已跌破", 62)
    } else {
        ("形成中", 48)
    };
    Some(json!({"name":"双顶","direction":"看跌","confidence":conf,"status":status,"target_price":((neck-(top-neck))*100.0).round()/100.0,"key_levels":{"颈线":neck,"顶部":top}}))
}

pub fn analyze_breakout(klines: &[Kline]) -> (i32, Value) {
    if klines.len() < 60 {
        return (50, json!([]));
    }
    let s1 = one_system(klines, 20, "系统一(20日)", 10);
    let s2 = one_system(klines, 55, "系统二(55日)", 20);
    let arr = json!([s1, s2]);
    let mut score = 50;
    for b in arr.as_array().unwrap() {
        let sig = b["signal"].as_str().unwrap_or("");
        if sig == "持仓" || sig == "突破买入" {
            let units = b["position_units"].as_i64().unwrap_or(1) as i32;
            score = score.max(62 + (units * 2).min(8));
        } else if sig == "向下突破" || sig == "多头止损" {
            score = score.min(35);
        }
    }
    (clamp_i(score, 20, 100), arr)
}

fn calc_n(klines: &[Kline], period: usize) -> f64 {
    if klines.len() < period + 1 {
        return 0.0;
    }
    let mut s = 0.0;
    for i in klines.len() - period..klines.len() {
        s += true_range(klines[i].high, klines[i].low, klines[i - 1].close);
    }
    (s / period as f64 * 10000.0).round() / 10000.0
}

fn donchian(klines: &[Kline], period: usize) -> (f64, f64) {
    let window = if klines.len() <= period {
        if klines.len() > 1 { &klines[..klines.len()-1] } else { klines }
    } else {
        &klines[klines.len() - period - 1..klines.len() - 1]
    };
    let ch = window.iter().map(|k| k.high).fold(f64::MIN, f64::max);
    let cl = window.iter().map(|k| k.low).fold(f64::MAX, f64::min);
    (ch, cl)
}

fn one_system(klines: &[Kline], period: usize, name: &str, exit_period: usize) -> Value {
    let n = calc_n(klines, 20);
    let (ch, cl) = donchian(klines, period);
    let price = klines.last().unwrap().close;
    let mut signal = "观望";
    let mut entry_price = None;
    let mut stop = 0.0;
    let mut units = 0;
    let mut next_add = None;
    let mut signals: Vec<String> = Vec::new();
    // 简化：现价相对通道
    if price >= ch {
        signal = "突破买入";
        entry_price = Some(ch);
        stop = if n > 0.0 { ch - 2.0 * n } else { ch * 0.95 };
        units = 1;
        next_add = if n > 0.0 { Some(ch + 0.5 * n) } else { None };
        signals.push(format!("上破{period}日通道{ch}"));
    } else if price <= cl {
        signal = "向下突破";
        stop = if n > 0.0 { cl + 2.0 * n } else { cl * 1.05 };
        signals.push(format!("下破{period}日通道{cl}"));
    } else if price > cl && ch > 0.0 && price > ch * 0.97 {
        // 接近上沿视为持仓近似（与 py 回溯不完全一致，回测用信号即可）
        signal = "持仓";
        entry_price = Some(ch);
        stop = if n > 0.0 { ch - 2.0 * n } else { ch * 0.95 };
        units = 1;
        signals.push(format!("持有多头，止损{stop:.2}"));
    }
    // 离场：近 exit_period 低点
    if signal == "持仓" && klines.len() >= exit_period {
        let exit_low = klines[klines.len()-exit_period..].iter().map(|k| k.low).fold(f64::MAX, f64::min);
        if price < stop || klines.last().unwrap().low <= exit_low && price < entry_price.unwrap_or(price) {
            if price < stop {
                signal = "多头止损";
                signals.push(format!("触发止损{stop:.2}"));
            }
        }
    }
    json!({
        "system": name,
        "signal": signal,
        "breakout_price": ch,
        "current_n": n,
        "stop_loss": (stop*100.0).round()/100.0,
        "entry_price": entry_price,
        "position_units": units,
        "channel_high": ch,
        "channel_low": cl,
        "next_add_price": next_add,
        "signals": signals,
    })
}

pub fn analyze_momentum(klines: &[Kline], flows: &[FundFlow], index: &[Kline]) -> (i32, Value) {
    let (c, _) = c_score(klines);
    let (a, _) = a_score(klines);
    let (n, _) = n_score(klines);
    let (s, _) = s_score(klines);
    let (l, _) = l_score(klines, index);
    let (i, _) = i_score(flows);
    let (m, _) = m_score(index, klines);
    let total = clamp_i(
        (c as f64 * 0.15 + a as f64 * 0.10 + n as f64 * 0.25 + s as f64 * 0.05 + l as f64 * 0.20 + i as f64 * 0.15 + m as f64 * 0.10) as i32,
        0,
        100,
    );
    let grade = if total >= 85 { "A+" } else if total >= 70 { "A" } else if total >= 60 { "B+" } else if total >= 50 { "B" } else if total >= 40 { "C+" } else if total >= 30 { "C" } else { "D" };
    let obj = json!({
        "c_score": c, "a_score": a, "n_score": n, "s_score": s,
        "l_score": l, "i_score": i, "m_score": m,
        "total": total, "grade": grade,
        "signals": [
            format!("C(近期动量){c}分"), format!("A(中期趋势){a}分"),
            format!("N(新高形态){n}分"), format!("S(供需){s}分"),
            format!("L(相对强度){l}分"), format!("I(资金流代理){i}分"),
            format!("M(市场环境){m}分"),
        ],
        "description": format!("动量质量{total}分 评级{grade}"),
    });
    (total, obj)
}

fn c_score(k: &[Kline]) -> (i32, String) {
    if k.len() < 10 { return (50, String::new()); }
    let c = k.last().unwrap().close;
    let g20 = if k.len() >= 21 { pct_change(k[k.len()-21].close, c) } else { 0.0 };
    let g5 = pct_change(k[k.len()-6].close, c);
    let s20 = if g20 > 20.0 {90} else if g20>15.0{80} else if g20>10.0{70} else if g20>5.0{60} else if g20>0.0{50} else if g20>-5.0{35} else {20};
    let s5 = if g5>5.0{80} else if g5>2.0{70} else if g5>0.0{60} else if g5>-5.0{50} else {35};
    (s20.max(s5), String::new())
}
fn a_score(k: &[Kline]) -> (i32, String) {
    if k.len() < 60 { return (50, String::new()); }
    let n = 121.min(k.len());
    let g = pct_change(k[k.len()-n].close, k.last().unwrap().close);
    let s = if g>150.0{90} else if g>30.0{75} else if g>15.0{70} else if g>12.0{60} else if g>5.0{50} else if g>-15.0{35} else {20};
    (s, String::new())
}
fn n_score(k: &[Kline]) -> (i32, String) {
    if k.len() < 60 { return (50, String::new()); }
    let w = if k.len()>=100 { &k[k.len()-250.min(k.len())..] } else { k };
    let high = w.iter().map(|x| x.high).fold(f64::MIN, f64::max);
    let price = k.last().unwrap().close;
    let dist = if high>0.0 { (high-price)/high*100.0 } else {100.0};
    let s = if dist<=2.0{90} else if dist<=5.0{80} else if dist<=10.0{70} else if dist<=15.0{55} else {40};
    (s, String::new())
}
fn s_score(k: &[Kline]) -> (i32, String) {
    let turns: Vec<f64> = k.iter().rev().take(10).map(|x| x.turnover).filter(|t| *t>0.0).collect();
    if turns.is_empty() {
        let vols: Vec<f64> = k.iter().map(|x| x.volume).collect();
        if vols.len()<10 { return (50, String::new()); }
        let ratio = vols[vols.len()-1] / (vols[vols.len()-10..vols.len()-1].iter().sum::<f64>()/9.0 + 1e-9);
        let s = if (1.2..=3.0).contains(&ratio) {70} else if ratio<1.2 {55} else {40};
        return (s, String::new());
    }
    let last = turns[0];
    let s = if (1.5..=8.0).contains(&last) {70} else if last<1.5 {55} else if last<=15.0 {45} else {30};
    (s, String::new())
}
fn l_score(k: &[Kline], index: &[Kline]) -> (i32, String) {
    if k.len()<60 { return (50, String::new()); }
    let g60 = pct_change(k[k.len()-61].close, k.last().unwrap().close);
    let mut base = if g60>=20.0{75} else if g60>=10.0{65} else if g60>=1.0{50} else if g60>=-9.0{35} else {20};
    if index.len()>=61 {
        let ig = pct_change(index[index.len()-61].close, index.last().unwrap().close);
        let rel = g60 - ig;
        if rel>10.0 { base = (base+15).min(100); }
        else if rel>0.0 { base = (base+8).min(100); }
        else if rel < -10.0 { base = (base-15).max(0); }
    }
    (base, String::new())
}
fn i_score(flows: &[FundFlow]) -> (i32, String) {
    if flows.is_empty() { return (50, String::new()); }
    let mains: Vec<f64> = flows.iter().map(|f| f.main_net).collect();
    let mut streak = 0;
    for v in mains.iter().rev().take(5) {
        if *v>0.0 { streak += 1; } else { break; }
    }
    let sum5: f64 = mains.iter().rev().take(5).sum();
    let last = *mains.last().unwrap();
    let s = if streak>=3 {85} else if sum5<0.0 && last<0.0 { if last < -5e8 {20} else {35} } else if sum5>0.0 && last>0.0 {75} else if sum5>0.0 {65} else {45};
    (s, String::new())
}
fn m_score(index: &[Kline], stock: &[Kline]) -> (i32, String) {
    let src = if index.len()>=30 { index } else { stock };
    if src.len()<30 { return (50, String::new()); }
    let closes: Vec<f64> = src.iter().map(|k| k.close).collect();
    let ma20 = sma_series(&closes, 20);
    let ma60 = sma_series(&closes, 60);
    let ma20_v = match ma20.last().and_then(|x| *x) { Some(v)=>v, None=>return (50,String::new()) };
    let ma60_v = ma60.last().and_then(|x| *x).unwrap_or(ma20_v);
    let up_days = (closes.len()-20..closes.len()).filter(|&i| closes[i]>closes[i-1]).count();
    let s = if ma20_v>ma60_v && up_days>=13 {80} else if ma20_v>ma60_v && up_days>=7 {70} else if ma20_v>ma60_v {60} else if index.len()>=30 {15} else {35};
    (s, String::new())
}

/// 简化缠论加减分：用近端高低结构近似一二类点
pub fn chanlun_bonus_score(klines: &[Kline]) -> i32 {
    if klines.len() < 40 {
        return 0;
    }
    let n = klines.len();
    let last = klines[n - 1].close;
    let low20 = klines[n - 20..].iter().map(|k| k.low).fold(f64::MAX, f64::min);
    let high20 = klines[n - 20..].iter().map(|k| k.high).fold(f64::MIN, f64::max);
    let prev_low = klines[n - 40..n - 20].iter().map(|k| k.low).fold(f64::MAX, f64::min);
    let prev_high = klines[n - 40..n - 20].iter().map(|k| k.high).fold(f64::MIN, f64::max);
    // 近端未破前低且从低点反弹 → 类二买 +4
    if last > low20 * 1.02 && low20 >= prev_low * 0.995 && last < high20 {
        return 4;
    }
    // 近端未过前高且从高点回落 → 类二卖 -4
    if last < high20 * 0.98 && high20 <= prev_high * 1.005 && last > low20 {
        return -4;
    }
    0
}
