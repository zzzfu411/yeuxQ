/* ECharts：K线 / 分时 / 资金流 + 指标计算 + 十字 HUD */
import { state } from './state.js';
import { $, fmtPx, fmtVol } from './util.js';

export const C = {
  up: '#f0334b', down: '#0bbf6e', text: '#f2f3f7', dim: '#7c8090',
  ma5: '#f5a524', ma10: '#64d2ff', ma20: '#bf5af2', ma60: '#0bbf6e',
  grid: '#14161c', axis: '#262a33',
};

export const chart = echarts.init($('chart'), null, { renderer: 'canvas' });
export const flowChart = echarts.init($('flowChart'), null, { renderer: 'canvas' });
window.addEventListener('resize', () => { chart.resize(); flowChart.resize(); });

/* ---------- 指标 ---------- */
export function sma(arr, n) {
  return arr.map((_, i) => i < n - 1 ? null : +(arr.slice(i - n + 1, i + 1).reduce((a, b) => a + b, 0) / n).toFixed(4));
}
function ema(arr, n) {
  const o = Array(arr.length).fill(null);
  if (arr.length < n) return o;
  let p = arr.slice(0, n).reduce((a, b) => a + b, 0) / n;
  o[n - 1] = p;
  const k = 2 / (n + 1);
  for (let i = n; i < arr.length; i++) { p = k * arr[i] + (1 - k) * p; o[i] = +p.toFixed(4); }
  return o;
}
function macd(c) {
  const e12 = ema(c, 12), e26 = ema(c, 26);
  const dif = c.map((_, i) => e12[i] != null && e26[i] != null ? +(e12[i] - e26[i]).toFixed(4) : null);
  const dea = ema(dif.map((x) => x ?? 0), 9);
  const hist = dif.map((d, i) => d != null && dea[i] != null ? +((d - dea[i]) * 2).toFixed(4) : null);
  return { dif, dea, hist };
}
function rsi(c, n) {
  const o = Array(c.length).fill(null);
  for (let i = n; i < c.length; i++) {
    let g = 0, l = 0;
    for (let j = i - n + 1; j <= i; j++) { const d = c[j] - c[j - 1]; if (d > 0) g += d; else l -= d; }
    o[i] = l === 0 ? 100 : +(100 - 100 / (1 + g / l)).toFixed(2);
  }
  return o;
}
function kdj(h, l, c, n = 9) {
  const k = [], d = [], j = [];
  let pk = 50, pd = 50;
  for (let i = 0; i < c.length; i++) {
    if (i < n - 1) { k.push(null); d.push(null); j.push(null); continue; }
    const hh = Math.max(...h.slice(i - n + 1, i + 1)), ll = Math.min(...l.slice(i - n + 1, i + 1));
    const rsv = hh === ll ? 50 : (c[i] - ll) / (hh - ll) * 100;
    pk = 2 / 3 * pk + 1 / 3 * rsv; pd = 2 / 3 * pd + 1 / 3 * pk;
    k.push(+pk.toFixed(2)); d.push(+pd.toFixed(2)); j.push(+(3 * pk - 2 * pd).toFixed(2));
  }
  return { k, d, j };
}
function boll(c, n = 20) {
  const mid = sma(c, n), up = [], dn = [];
  for (let i = 0; i < c.length; i++) {
    if (i < n - 1 || mid[i] == null) { up.push(null); dn.push(null); continue; }
    const sl = c.slice(i - n + 1, i + 1), m = mid[i];
    const sd = Math.sqrt(sl.reduce((s, x) => s + (x - m) ** 2, 0) / n);
    up.push(+(m + 2 * sd).toFixed(2)); dn.push(+(m - 2 * sd).toFixed(2));
  }
  return { mid, up, dn };
}
function wr(h, l, c, n = 14) {
  return c.map((_, i) => {
    if (i < n - 1) return null;
    const hh = Math.max(...h.slice(i - n + 1, i + 1)), ll = Math.min(...l.slice(i - n + 1, i + 1));
    return hh === ll ? -50 : +((-100 * (hh - c[i]) / (hh - ll)).toFixed(2));
  });
}

/* ---------- 范围 / HUD ---------- */
function rangeStart(n) {
  const r = state.range;
  if (!r || r <= 0 || r >= n) return 0;
  return +(Math.max(0, (1 - r / n) * 100).toFixed(2));
}
export function applyRange() {
  const n = (state.klines || []).length;
  if (!n) return;
  chart.dispatchAction({ type: 'dataZoom', start: rangeStart(n), end: 100 });
}
function axisPtr() {
  return {
    type: 'cross', snap: true,
    label: { backgroundColor: '#20242e', color: '#f2f3f7', fontSize: 11, padding: [3, 6] },
    lineStyle: { color: 'rgba(255,255,255,0.28)', width: 1, type: 'dashed' },
    crossStyle: { color: 'rgba(255,255,255,0.28)', width: 1 },
  };
}
function yRight(fmt, split, gridIdx) {
  return {
    gridIndex: gridIdx || 0, scale: true, position: 'right', splitNumber: split || 5,
    axisLabel: { color: C.dim, fontSize: 10, formatter: fmt || ((v) => fmtPx(v)) },
    axisLine: { show: false }, axisTick: { show: false },
    splitLine: { lineStyle: { color: C.grid, width: 1 } },
  };
}
function xCat(data, show, gridIdx) {
  return {
    gridIndex: gridIdx || 0, type: 'category', data, boundaryGap: true,
    axisLabel: { show: !!show, color: C.dim, fontSize: 10, hideOverlap: true },
    axisLine: { lineStyle: { color: C.axis } }, axisTick: { show: false }, splitLine: { show: false },
  };
}

export function paintHud(i) {
  const box = $('kHud');
  if (!box) return;
  if (state.view === 'minute') {
    const m = state.minute;
    if (!m || !m.prices || !m.prices.length) { box.innerHTML = ''; return; }
    if (typeof i === 'string') i = (m.times || []).indexOf(i);
    if (i == null || i < 0 || i >= m.prices.length) i = m.prices.length - 1;
    const px = m.prices[i], pre = m.pre_close || px, avg = (m.avg || [])[i], vol = (m.volumes || [])[i];
    const c = px >= pre ? 'up' : 'dn';
    const pct = pre ? ((px - pre) / pre * 100) : 0;
    box.innerHTML = `<span>${(m.times || [])[i] || ''}</span><span>价 <b class="${c}">${fmtPx(px)}</b></span><span class="${c}">${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%</span><span>均 <b>${fmtPx(avg)}</b></span><span>量 <b>${fmtVol(vol)}</b></span>`;
    return;
  }
  const ks = state.viewKs || [];
  if (!ks.length) { box.innerHTML = ''; return; }
  if (typeof i === 'string') i = ks.findIndex((k) => k.date === i);
  if (i == null || i < 0 || i >= ks.length) i = ks.length - 1;
  const k = ks[i];
  const up = k.close >= k.open;
  const cc = up ? 'up' : 'dn';
  const pct = k.pct != null ? +k.pct : (k.open ? ((k.close - k.open) / k.open * 100) : 0);
  const closes = ks.map((x) => x.close);
  const v5 = sma(closes, 5)[i], v10 = sma(closes, 10)[i], v20 = sma(closes, 20)[i], v60 = sma(closes, 60)[i];
  box.innerHTML = `<span>${k.date || ''}</span><span>开 <b>${fmtPx(k.open)}</b></span><span>高 <b class="up">${fmtPx(k.high)}</b></span><span>低 <b class="dn">${fmtPx(k.low)}</b></span><span>收 <b class="${cc}">${fmtPx(k.close)}</b></span><span class="${cc}">${pct >= 0 ? '+' : ''}${(+pct).toFixed(2)}%</span><span>量 <b>${fmtVol(k.volume)}</b></span><span style="color:${C.ma5}">MA5 ${v5 ?? '—'}</span><span style="color:${C.ma10}">MA10 ${v10 ?? '—'}</span><span style="color:${C.ma20}">MA20 ${v20 ?? '—'}</span><span style="color:${C.ma60}">MA60 ${v60 ?? '—'}</span>`;
}

let ptrBound = false;
function bindChartPointer() {
  if (ptrBound) return;
  ptrBound = true;
  chart.on('updateAxisPointer', (ev) => {
    const info = (ev.axesInfo || [])[0];
    let i = info && info.value != null ? info.value : null;
    if (i == null && ev.dataIndex != null) i = ev.dataIndex;
    paintHud(i);
  });
  chart.getZr().on('globalout', () => paintHud(-1));
}

/* ---------- 日/周 K ---------- */
export function renderKline() {
  if (state.view === 'minute') return;
  const ks = state.klines || [];
  state.viewKs = ks;
  const cats = ks.map((k) => k.date);
  const ohlc = ks.map((k) => [k.open, k.close, k.low, k.high]);
  const closes = ks.map((k) => k.close);
  const highs = ks.map((k) => k.high);
  const lows = ks.map((k) => k.low);
  const vols = ks.map((k) => ({ value: k.volume, itemStyle: { color: k.close >= k.open ? C.up + '99' : C.down + '99' } }));
  const plan = state.signal?.trade_plan || {};
  const markPoints = [], markLines = [];
  if (plan.stop_loss) markLines.push({ yAxis: plan.stop_loss, lineStyle: { color: C.down, type: 'dashed', width: 1 }, label: { formatter: '止损 ' + fmtPx(plan.stop_loss), color: C.down, position: 'insideEndTop', fontSize: 10 } });
  if (plan.target_price) markLines.push({ yAxis: plan.target_price, lineStyle: { color: C.up, type: 'dashed', width: 1 }, label: { formatter: '目标 ' + fmtPx(plan.target_price), color: C.up, position: 'insideEndTop', fontSize: 10 } });
  if (plan.entry_price) markLines.push({ yAxis: plan.entry_price, lineStyle: { color: C.ma5, type: 'dotted', width: 1 }, label: { formatter: '入场 ' + fmtPx(plan.entry_price), color: C.ma5, position: 'insideEndTop', fontSize: 10 } });
  const last = ks[ks.length - 1];
  if (last) markLines.push({ yAxis: last.close, lineStyle: { color: last.close >= last.open ? C.up : C.down, type: 'dashed', width: 1, opacity: 0.55 }, label: { formatter: fmtPx(last.close), color: last.close >= last.open ? C.up : C.down, position: 'end', fontSize: 10 } });
  const ch = state.chan || {};
  (ch.signals || []).slice(-10).forEach((s) => {
    const k = ks.find((x) => x.date === s.date);
    if (!k) return;
    const buy = (s.type || '').startsWith('buy');
    markPoints.push({
      name: s.type_name, coord: [s.date, buy ? k.low : k.high],
      symbol: 'triangle', symbolRotate: buy ? 0 : 180, symbolSize: 10,
      itemStyle: { color: buy ? C.up : C.down },
      label: { show: true, formatter: s.type_name, fontSize: 9, position: buy ? 'bottom' : 'top', color: buy ? C.up : C.down, distance: 4 },
    });
  });
  const markArea = (ch.zhongshus || []).slice(-4).map((z) => [
    { xAxis: z.start_date, yAxis: z.zd, itemStyle: { color: 'rgba(98,208,192,0.07)' } },
    { xAxis: z.end_date, yAxis: z.zg },
  ]);
  const bollOn = state.ind === 'boll';
  const showInd = !bollOn;
  const start = rangeStart(ks.length);
  const xIdx = showInd ? [0, 1, 2] : [0, 1];
  const grids = showInd ? [
    { left: 10, right: 58, top: 18, height: '56%' },
    { left: 10, right: 58, top: '66%', height: '10%' },
    { left: 10, right: 58, top: '80%', height: '16%' },
  ] : [
    { left: 10, right: 58, top: 18, height: '70%' },
    { left: 10, right: 58, top: '80%', height: '16%' },
  ];
  const xAxes = [xCat(cats, false, 0), xCat(cats, !showInd, 1)];
  const yAxes = [yRight((v) => fmtPx(v), 6, 0), yRight((v) => fmtVol(v), 2, 1)];
  if (showInd) { xAxes.push(xCat(cats, true, 2)); yAxes.push(yRight((v) => (+v).toFixed(2), 3, 2)); }
  const series = [
    {
      name: 'K', type: 'candlestick', xAxisIndex: 0, yAxisIndex: 0, data: ohlc, barMaxWidth: 14,
      itemStyle: { color: C.up, color0: C.down, borderColor: C.up, borderColor0: C.down, borderColorDoji: '#8a8f9c' },
      markPoint: { data: markPoints, animation: false },
      markLine: { symbol: 'none', animation: false, data: markLines, silent: true },
      markArea: { data: markArea, silent: true },
    },
    { name: 'MA5', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: sma(closes, 5), showSymbol: false, lineStyle: { width: 1, color: C.ma5 } },
    { name: 'MA10', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: sma(closes, 10), showSymbol: false, lineStyle: { width: 1, color: C.ma10 } },
    { name: 'MA20', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: sma(closes, 20), showSymbol: false, lineStyle: { width: 1, color: C.ma20 } },
    { name: 'MA60', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: sma(closes, 60), showSymbol: false, lineStyle: { width: 1, color: C.ma60 } },
    { name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: vols, barMaxWidth: 14 },
  ];
  if (bollOn) {
    const bb = boll(closes, 20);
    series.push({ name: 'BOLL上', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: bb.up, showSymbol: false, lineStyle: { width: 1, type: 'dashed', color: '#8a8f9c' } });
    series.push({ name: 'BOLL中', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: bb.mid, showSymbol: false, lineStyle: { width: 1, color: '#8a8f9c' } });
    series.push({ name: 'BOLL下', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: bb.dn, showSymbol: false, lineStyle: { width: 1, type: 'dashed', color: '#8a8f9c' } });
  } else {
    let indSeries = [];
    if (state.ind === 'macd') {
      const m = macd(closes);
      indSeries = [
        { name: 'DIF', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: m.dif, showSymbol: false, lineStyle: { width: 1, color: '#64d2ff' } },
        { name: 'DEA', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: m.dea, showSymbol: false, lineStyle: { width: 1, color: '#ff9f0a' } },
        { name: 'MACD', type: 'bar', xAxisIndex: 2, yAxisIndex: 2, data: m.hist.map((v) => v == null ? null : { value: v, itemStyle: { color: v >= 0 ? C.up : C.down } }), barMaxWidth: 8 },
      ];
    } else if (state.ind === 'rsi') {
      indSeries = [
        { name: 'RSI6', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: rsi(closes, 6), showSymbol: false, lineStyle: { width: 1, color: C.ma5 } },
        { name: 'RSI12', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: rsi(closes, 12), showSymbol: false, lineStyle: { width: 1, color: C.ma10 } },
        { name: 'RSI24', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: rsi(closes, 24), showSymbol: false, lineStyle: { width: 1, color: C.ma60 } },
      ];
    } else if (state.ind === 'kdj') {
      const k = kdj(highs, lows, closes);
      indSeries = [
        { name: 'K', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: k.k, showSymbol: false, lineStyle: { width: 1, color: C.ma5 } },
        { name: 'D', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: k.d, showSymbol: false, lineStyle: { width: 1, color: C.ma10 } },
        { name: 'J', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: k.j, showSymbol: false, lineStyle: { width: 1, color: C.ma20 } },
      ];
    } else {
      indSeries = [{ name: 'WR', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: wr(highs, lows, closes, 14), showSymbol: false, lineStyle: { width: 1, color: C.ma10 } }];
    }
    series.push(...indSeries);
  }
  const titles = [{ text: '成交量', left: 12, top: showInd ? '64.5%' : '78.5%', textStyle: { color: '#565a68', fontSize: 10, fontWeight: 500 } }];
  if (showInd) titles.push({ text: (state.ind || 'MACD').toUpperCase(), left: 12, top: '78.5%', textStyle: { color: '#565a68', fontSize: 10, fontWeight: 500 } });
  chart.setOption({
    backgroundColor: 'transparent',
    animation: false,
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    legend: { data: ['MA5', 'MA10', 'MA20', 'MA60'], top: 0, left: 8, itemWidth: 12, itemHeight: 2, textStyle: { color: C.dim, fontSize: 10 } },
    title: titles,
    tooltip: { trigger: 'axis', showContent: false, axisPointer: axisPtr() },
    grid: grids,
    xAxis: xAxes,
    yAxis: yAxes,
    dataZoom: [{ type: 'inside', xAxisIndex: xIdx, start, end: 100, zoomOnMouseWheel: true, moveOnMouseMove: true, moveOnMouseWheel: false }],
    series,
  }, true);
  bindChartPointer();
  paintHud(-1);
  chart.resize();
}

/* ---------- 分时 ---------- */
export function renderMinute() {
  const m = state.minute;
  if (!m || m.error) return;
  const times = m.times || [], prices = m.prices || [], avgs = m.avg || [], vols = m.volumes || [];
  const pre = m.pre_close || (prices[0] || 0);
  const last = prices[prices.length - 1] || pre;
  const up = last >= pre;
  const pColor = up ? C.up : C.down;
  const lo = Math.min(pre, ...prices.filter(Boolean), m.low || pre);
  const hi = Math.max(pre, ...prices.filter(Boolean), m.high || pre);
  const pad = (hi - lo) * 0.08 || pre * 0.01;
  const volBars = vols.map((v, i) => {
    const p = prices[i] || pre;
    return { value: v, itemStyle: { color: p >= pre ? C.up + '88' : C.down + '88' } };
  });
  chart.setOption({
    backgroundColor: 'transparent',
    animation: false,
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    legend: { show: false },
    title: [{ text: '成交量', left: 12, top: '78.5%', textStyle: { color: '#565a68', fontSize: 10, fontWeight: 500 } }],
    tooltip: { trigger: 'axis', showContent: false, axisPointer: axisPtr() },
    grid: [
      { left: 10, right: 58, top: 10, height: '70%' },
      { left: 10, right: 58, top: '82%', height: '14%' },
    ],
    xAxis: [
      { type: 'category', gridIndex: 0, data: times, boundaryGap: false, axisLabel: { show: false }, axisTick: { show: false }, axisLine: { lineStyle: { color: C.axis } }, splitLine: { show: true, lineStyle: { color: C.grid, type: 'dashed' } } },
      { type: 'category', gridIndex: 1, data: times, boundaryGap: true, axisLabel: { color: C.dim, fontSize: 10, interval: Math.max(0, Math.floor(times.length / 5) - 1), hideOverlap: true }, axisTick: { show: false }, axisLine: { lineStyle: { color: C.axis } } },
    ],
    yAxis: [
      {
        scale: true, gridIndex: 0, position: 'right', min: lo - pad, max: hi + pad,
        axisLabel: { color: C.dim, fontSize: 10, formatter: (v) => { const pct = pre ? ((v - pre) / pre * 100) : 0; return fmtPx(v) + '\n' + (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%'; } },
        axisLine: { show: false }, axisTick: { show: false }, splitLine: { lineStyle: { color: C.grid } },
      },
      { scale: true, gridIndex: 1, position: 'right', splitNumber: 2, axisLabel: { color: C.dim, fontSize: 10, formatter: (v) => fmtVol(v) }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { lineStyle: { color: C.grid } } },
    ],
    dataZoom: [],
    series: [
      {
        name: '价格', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: prices, showSymbol: false,
        lineStyle: { color: pColor, width: 1.4 },
        areaStyle: { color: up ? 'rgba(240,51,75,0.10)' : 'rgba(11,191,110,0.10)' },
        markLine: { silent: true, symbol: 'none', animation: false, data: [{ yAxis: pre, lineStyle: { color: '#565a68', type: 'dashed', width: 1 }, label: { formatter: '昨收 ' + fmtPx(pre), color: '#7c8090', fontSize: 10, position: 'insideEndTop' } }] },
      },
      { name: '均价', type: 'line', xAxisIndex: 0, yAxisIndex: 0, data: avgs, showSymbol: false, lineStyle: { color: '#ff9f0a', width: 1, type: 'dashed' } },
      { name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volBars, barMaxWidth: 6 },
    ],
  }, true);
  bindChartPointer();
  paintHud(-1);
  chart.resize();
}

/* ---------- 主力净流入 ---------- */
export function renderFlow(flows) {
  const dates = (flows || []).map((f) => (f.date || '').slice(5));
  const main = (flows || []).map((f) => +((f.main_net || 0) / 1e8).toFixed(3));
  const title = (!flows || !flows.length) ? '主力净流入 · 无数据'
    : (flows.length < 3 ? `主力净流入 · 仅${flows.length}日` : `主力净流入 · ${flows.length}日 · 亿`);
  flowChart.setOption({
    backgroundColor: 'transparent', animation: false,
    title: { text: title, left: 12, top: 5, textStyle: { color: C.dim, fontSize: 11, fontWeight: 500 } },
    grid: { left: 10, right: 58, top: 26, bottom: 18 },
    tooltip: {
      trigger: 'axis', backgroundColor: '#181b23', borderColor: '#2a2d36',
      textStyle: { color: '#f2f3f7', fontSize: 12 },
      formatter: (p) => p && p[0] ? `${p[0].axisValue}<br/>主力 ${p[0].value >= 0 ? '+' : ''}${p[0].value} 亿` : '',
    },
    xAxis: { type: 'category', data: dates, axisLabel: { color: C.dim, fontSize: 10 }, axisLine: { lineStyle: { color: C.axis } }, axisTick: { show: false } },
    yAxis: { position: 'right', axisLabel: { color: C.dim, fontSize: 10 }, axisLine: { show: false }, splitLine: { lineStyle: { color: C.grid } } },
    series: [{ type: 'bar', data: main.map((v) => ({ value: v, itemStyle: { color: v >= 0 ? C.up : C.down } })), barMaxWidth: 12 }],
  }, true);
}
