pub fn sma_last(values: &[f64], period: usize) -> f64 {
    if values.len() < period || period == 0 {
        return 0.0;
    }
    values[values.len() - period..].iter().sum::<f64>() / period as f64
}

pub fn sma_series(values: &[f64], period: usize) -> Vec<Option<f64>> {
    if period == 0 || values.is_empty() {
        return vec![];
    }
    let mut out = vec![None; values.len()];
    let mut run = 0.0;
    for (i, &v) in values.iter().enumerate() {
        run += v;
        if i >= period {
            run -= values[i - period];
        }
        if i + 1 >= period {
            out[i] = Some(run / period as f64);
        }
    }
    out
}

pub fn ema_series(values: &[f64], period: usize) -> Vec<Option<f64>> {
    let mut out = vec![None; values.len()];
    if period == 0 || values.len() < period {
        return out;
    }
    let alpha = 2.0 / (period as f64 + 1.0);
    let mut prev = values[..period].iter().sum::<f64>() / period as f64;
    out[period - 1] = Some(prev);
    for i in period..values.len() {
        prev = alpha * values[i] + (1.0 - alpha) * prev;
        out[i] = Some(prev);
    }
    out
}

pub fn ma_direction(ma: &[Option<f64>], lookback: usize) -> &'static str {
    let valid: Vec<f64> = ma.iter().copied().flatten().collect();
    if valid.len() < lookback + 1 {
        return "未知";
    }
    let n = valid.len();
    let first = valid[n - lookback - 1];
    let last = valid[n - 1];
    let slope = last - first;
    let thr = first.abs() * 0.002;
    if slope > thr {
        "向上"
    } else if slope < -thr {
        "向下"
    } else {
        "走平"
    }
}

pub fn pct_change(old: f64, new: f64) -> f64 {
    if old == 0.0 {
        0.0
    } else {
        (new - old) / old * 100.0
    }
}

pub fn true_range(high: f64, low: f64, pre_close: f64) -> f64 {
    (high - low)
        .max((high - pre_close).abs())
        .max((low - pre_close).abs())
}

pub fn atr(highs: &[f64], lows: &[f64], closes: &[f64], period: usize) -> f64 {
    if closes.len() < period + 1 {
        return 0.0;
    }
    let start = closes.len() - period;
    let mut s = 0.0;
    for i in start..closes.len() {
        s += true_range(highs[i], lows[i], closes[i - 1]);
    }
    s / period as f64
}

pub fn find_peaks(values: &[f64], window: usize) -> Vec<usize> {
    let n = values.len();
    let mut peaks = Vec::new();
    if n < window * 2 + 1 {
        return peaks;
    }
    for i in window..n - window {
        let lo = i - window;
        let hi = i + window;
        if (lo..=hi).filter(|&j| j != i).all(|j| values[i] >= values[j])
            && !(lo..=hi).all(|j| values[j] == values[i])
        {
            peaks.push(i);
        }
    }
    peaks
}

pub fn find_troughs(values: &[f64], window: usize) -> Vec<usize> {
    let n = values.len();
    let mut out = Vec::new();
    if n < window * 2 + 1 {
        return out;
    }
    for i in window..n - window {
        let lo = i - window;
        let hi = i + window;
        if (lo..=hi).filter(|&j| j != i).all(|j| values[i] <= values[j])
            && !(lo..=hi).all(|j| values[j] == values[i])
        {
            out.push(i);
        }
    }
    out
}

pub fn clamp_i(v: i32, lo: i32, hi: i32) -> i32 {
    v.max(lo).min(hi)
}

pub fn clamp_f(v: f64, lo: f64, hi: f64) -> f64 {
    v.max(lo).min(hi)
}
