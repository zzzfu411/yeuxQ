/* 主控：研判编排（竞态保护）、视图切换、搜索、模式、启动 */
import { state, bus, LS } from './state.js';
import { $, jget, jset, setStatus, toast } from './util.js';
import { getJSON } from './api.js';
import { chart, renderKline, renderMinute, renderFlow, applyRange, paintHud } from './charts.js';
import { bindCells } from './cells.js';
import { renderQuote, renderAll, renderChanlunMinute, renderEngineTag, updateTrack } from './rail.js';
import { bindPanels, bindScan, renderWatch, addHist, loadMarket } from './panels.js';
import { loadSavedAI, loadSavedBrief, runAI, runBrief } from './research.js';
import { loadOF, runBacktest, runCompare } from './orderflow.js';
import { runVision, loadSavedVision } from './vision.js';

/* ---------- 加载遮罩 ---------- */
const deck = document.querySelector('.deck');
const deckLoadingEl = document.createElement('div');
deckLoadingEl.className = 'deck-loading';
deckLoadingEl.innerHTML = '<div class="spinner"></div>';
deck.appendChild(deckLoadingEl);
function deckLoading(on) { deckLoadingEl.classList.toggle('show', !!on); }

/* ---------- 研判（generation token + AbortController 防串票） ---------- */
let analyzeGen = 0;
let analyzeCtrl = null;

async function analyze(symbol) {
  if (!symbol) return;
  const code = (String(symbol).replace(/\D/g, '') || symbol).slice(0, 6);
  if (!code) return;
  const gen = ++analyzeGen;
  if (analyzeCtrl) analyzeCtrl.abort();
  const ctrl = new AbortController();
  analyzeCtrl = ctrl;

  state.symbol = code;
  $('kw').value = code;
  jset(LS.last, code);
  setStatus('研判中…');
  deckLoading(true);
  try {
    const period = state.view === 'week' ? 'week' : 'day';
    const [a, ch] = await Promise.all([
      getJSON(`/api/analyze?symbol=${code}&period=${period}`, { signal: ctrl.signal }),
      getJSON(`/api/chanlun_daily?symbol=${code}&period=${period}`, { signal: ctrl.signal }),
    ]);
    if (gen !== analyzeGen) return; // 已切票，丢弃旧响应
    if (a.error) { setStatus(a.error); return; }

    const prev = (state.lastAction[code] || {}).action;
    state.signal = a.signal;
    state.klines = a.klines || [];
    state.chan = ch;
    state.quoteName = (a.quote || {}).name || '';
    state.flows = a.flows || [];
    const act = (a.signal || {}).action;
    if (prev && act && prev !== act) toast(`${state.quoteName || code} ${prev} → ${act}`);
    state.lastAction[code] = { action: act };

    addHist(code, state.quoteName, a.signal);
    updateTrack(code, a.quote, a.signal);
    renderQuote(a.quote);
    renderEngineTag((a.meta || {}).engine);
    renderAll(a.signal, a.prediction || a.signal?.prediction, ch, a.meta);
    renderKline();
    renderFlow(a.flows || []);
    renderWatch();
    setStatus('');
    loadSavedAI(code);
    loadSavedVision(code);
    loadMarket();
    if (state.view === 'minute') loadMinute();
  } catch (err) {
    if (err.name === 'AbortError') return;
    setStatus(err.message);
  } finally {
    if (gen === analyzeGen) deckLoading(false);
  }
}

async function loadMinute() {
  const gen = analyzeGen;
  try {
    const [m, ch] = await Promise.all([
      getJSON(`/api/minute?symbol=${state.symbol}`),
      getJSON(`/api/chanlun_minute?symbol=${state.symbol}`),
    ]);
    if (gen !== analyzeGen) return;
    state.minute = m;
    renderMinute();
    renderChanlunMinute(ch);
  } catch (e) { /* 分时不可用时保持现状 */ }
}

bus.on('analyze', (code) => analyze(code));

/* ---------- 搜索建议 ---------- */
let suggestTimer = null;
$('kw').addEventListener('input', (e) => {
  clearTimeout(suggestTimer);
  const kw = e.target.value.trim();
  if (kw.length < 1) { $('suggest').style.display = 'none'; return; }
  suggestTimer = setTimeout(async () => {
    try {
      const data = await getJSON(`/api/search?keyword=${encodeURIComponent(kw)}`);
      const list = data.results || [];
      if (!list.length) { $('suggest').style.display = 'none'; return; }
      $('suggest').innerHTML = list.map((x) =>
        `<div data-code="${x.code}">${x.code} <span>${x.name || ''}</span></div>`
      ).join('');
      $('suggest').style.display = 'block';
      $('suggest').querySelectorAll('div').forEach((d) => {
        d.onclick = () => { $('suggest').style.display = 'none'; analyze(d.dataset.code); };
      });
    } catch (err) { /* 检索失败静默 */ }
  }, 200);
});
$('kw').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { $('suggest').style.display = 'none'; analyze($('kw').value.trim()); }
});
document.addEventListener('click', (e) => {
  if (!e.target.closest('.search-box')) $('suggest').style.display = 'none';
});

/* ---------- 顶栏 / 工具栏 ---------- */
$('btnAnalyze').onclick = () => analyze($('kw').value.trim() || state.symbol);
document.querySelectorAll('.hot [data-s]').forEach((b) => { b.onclick = () => analyze(b.dataset.s); });

document.querySelectorAll('#viewSeg [data-view]').forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll('#viewSeg [data-view]').forEach((x) => x.classList.remove('on'));
    b.classList.add('on');
    state.view = b.dataset.view;
    state.period = state.view === 'week' ? 'week' : 'day';
    if (state.view === 'minute') loadMinute();
    else analyze(state.symbol);
  };
});
document.querySelectorAll('#rangeSeg [data-range]').forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll('#rangeSeg [data-range]').forEach((x) => x.classList.remove('on'));
    b.classList.add('on');
    state.range = +b.dataset.range;
    if (state.view === 'minute') return;
    applyRange();
  };
});
document.querySelectorAll('#indSeg [data-ind]').forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll('#indSeg [data-ind]').forEach((x) => x.classList.remove('on'));
    b.classList.add('on');
    state.ind = b.dataset.ind;
    if (state.view === 'minute') return;
    renderKline();
  };
});

$('btnBacktest').onclick = runBacktest;
$('btnCompare').onclick = runCompare;
$('btnOrderFlow').onclick = loadOF;
$('btnNews').onclick = () => runAI('news');
$('btnReport').onclick = () => runAI('report');
$('btnEarnings').onclick = () => runAI('earnings');
$('btnVision').onclick = runVision;
$('btnBrief').onclick = runBrief;

/* ---------- 专家 / 小白 ---------- */
function setMode(m) {
  document.body.classList.remove('mode-pro', 'mode-simple');
  document.body.classList.add(m === 'simple' ? 'mode-simple' : 'mode-pro');
  $('mt-pro').classList.toggle('on', m !== 'simple');
  $('mt-simple').classList.toggle('on', m === 'simple');
  jset(LS.mode, m);
}
$('mt-pro').onclick = () => setMode('pro');
$('mt-simple').onclick = () => setMode('simple');

/* ---------- 快捷键 ---------- */
document.addEventListener('keydown', (e) => {
  if (e.key === '/' && !/INPUT|TEXTAREA/.test(document.activeElement?.tagName || '')) {
    e.preventDefault();
    $('kw').focus();
    $('kw').select();
  }
  if (e.key === 'Escape') {
    $('suggest').style.display = 'none';
    $('wp').classList.remove('show');
    $('scanOv').classList.remove('show');
  }
});

/* ---------- 启动 ---------- */
setMode(jget(LS.mode) || 'pro');
bindCells();
bindPanels();
bindScan();
renderWatch();
loadMarket();
loadSavedBrief();
analyze(jget(LS.last) || '600519');
setInterval(loadMarket, 60000);
