/* 主控：研判编排（竞态保护）、视图切换、搜索、模式、启动 */
import { state, bus, LS } from './state.js';
import { $, jget, jset, setStatus, toast } from './util.js';
import {
  captureLocalResearchObservation,
  getAdvisoryAnalysis,
  getAdvisoryMinute,
  getV1CanonicalReadiness,
  getV1IntegrationStatus,
  listV1Observations,
  listV1ResearchRuns,
  searchAdvisoryInstruments,
} from './api.js';
import {
  aggregateFreshness,
  aggregateGate,
  observationFreshness,
  timestampFreshness,
} from './evidence.js';
import { chart, renderKline, renderMinute, renderFlow, applyRange, paintHud } from './charts.js';
import { bindCells } from './cells.js';
import {
  renderQuote,
  renderAll,
  renderAnalysisUnavailable,
  renderChanlunMinute,
  renderEngineTag,
  updateTrack,
} from './rail.js';
import { bindPanels, bindScan, renderWatch, addHist, loadMarket } from './panels.js';
import { loadSavedAI, loadSavedBrief } from './research.js';
import { loadSavedVision } from './vision.js';

/* ---------- 加载遮罩 ---------- */
const deck = document.querySelector('.deck');
const deckLoadingEl = document.createElement('div');
deckLoadingEl.className = 'deck-loading';
deckLoadingEl.innerHTML = '<div class="spinner"></div>';
deck.appendChild(deckLoadingEl);
function deckLoading(on) { deckLoadingEl.classList.toggle('show', !!on); }

/* ---------- /api/v1 bounded facade：状态、观察、canonical gate ---------- */
let v1Ctrl = null;

function shortHash(value) {
  const text = String(value || '');
  return text ? `${text.slice(0, 12)}…` : '—';
}

function timeLabel(value) {
  if (!value) return 'UNKNOWN';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? 'UNKNOWN' : parsed.toLocaleString('zh-CN');
}

function renderV1Workspace() {
  const view = state.v1;
  const integration = view.integration;
  const integrationStatus = integration?.status;
  const integrationFreshness = integration?.valid === true
    ? timestampFreshness(integrationStatus?.updated_at)
    : 'UNKNOWN';
  const integrationLine = integration?.valid === true
    ? `${integration.release_readiness} · freshness ${integrationFreshness} · updated ${timeLabel(integrationStatus?.updated_at)} · provenance ${integrationStatus?.project?.canonical_repo_id || 'integration_status'}`
    : `UNAVAILABLE · ${integration?.reason || view.errors?.integration || 'STATUS_UNAVAILABLE'} · freshness UNKNOWN`;
  $('integrationEvidence').textContent = integrationLine;

  const readiness = view.readiness;
  const readinessFreshness = timestampFreshness(readiness?.artifact_mtime);
  const readinessLine = readiness
    ? `${readiness.decision} · run ${view.runId || '—'} · freshness ${readinessFreshness} · artifact ${timeLabel(readiness.artifact_mtime)} · provenance ${readiness.authority || 'UNKNOWN'} / sha256 ${shortHash(readiness.artifact_sha256)}`
    : `UNAVAILABLE · ${view.errors?.readiness || 'NO_CANONICAL_RUN'} · freshness UNKNOWN · provenance src/quantify/readiness`;
  $('readinessEvidence').textContent = readinessLine;

  const observations = Array.isArray(view.observations) ? view.observations : [];
  if (view.errors?.observations) {
    $('observationEvidence').textContent = `UNAVAILABLE · ${view.errors.observations} · freshness UNKNOWN`;
  } else if (!observations.length) {
    $('observationEvidence').textContent = 'AVAILABLE · 0 条本地 research observation · provenance local append-only log';
  } else {
    const lines = observations.slice(0, 8).map((item) => {
      const freshness = observationFreshness(item);
      return `${item.observation_id || 'UNKNOWN'} · ${item.symbol || 'UNKNOWN'} · freshness ${freshness} · event_time ${timeLabel(item.event_time)} · received_at ${timeLabel(item.received_at)} · stale_after ${timeLabel(item.stale_after)} · provenance ${item.source || 'UNKNOWN'} / ${item.engine || 'UNKNOWN'} / ${shortHash(item.data_fingerprint)}`;
    });
    const host = $('observationEvidence');
    host.replaceChildren();
    lines.forEach((line, index) => {
      if (index) host.appendChild(document.createElement('br'));
      host.appendChild(document.createTextNode(line));
    });
  }

  const gate = aggregateGate(integration, readiness, view.errors);
  const freshnessParts = [integrationFreshness, readinessFreshness];
  observations.forEach((item) => freshnessParts.push(observationFreshness(item)));
  const overallFreshness = view.available
    ? aggregateFreshness(freshnessParts)
    : 'UNKNOWN';
  view.freshness = overallFreshness;
  $('evidenceChip').textContent = gate;
  $('evidenceChip').classList.remove('up', 'dn', 'warn');
  $('evidenceChip').classList.add(gate === 'PASS' ? 'up' : 'warn');
  $('evidencePrev').textContent = `${view.available ? 'AVAILABLE' : 'UNAVAILABLE'} · freshness ${overallFreshness}`;
  $('v1BoundaryStatus').textContent = `BOUNDED FACADE · ${gate} · freshness ${overallFreshness} · provenance ${readiness?.authority || 'UNKNOWN'}`;
}

async function loadV1Workspace() {
  if (v1Ctrl) v1Ctrl.abort();
  const ctrl = new AbortController();
  v1Ctrl = ctrl;
  const next = {
    available: false,
    integration: null,
    observations: [],
    readiness: null,
    runId: '',
    freshness: 'UNKNOWN',
    provenance: {},
    fetchedAt: new Date().toISOString(),
    errors: {},
  };
  const [integration, observations, runs] = await Promise.allSettled([
    getV1IntegrationStatus({ signal: ctrl.signal }),
    listV1Observations({ limit: 20, offset: 0, signal: ctrl.signal }),
    listV1ResearchRuns({ limit: 20, signal: ctrl.signal }),
  ]);
  if (ctrl.signal.aborted) return;

  if (integration.status === 'fulfilled') {
    next.integration = integration.value.data;
    next.provenance.integrationRequestId = integration.value.requestId;
    if (next.integration?.valid !== true) {
      next.errors.integration = next.integration?.reason || 'STATUS_INVALID';
    }
  } else {
    next.errors.integration = integration.reason?.code || 'UNAVAILABLE';
  }
  if (observations.status === 'fulfilled') {
    next.observations = observations.value.data?.items || [];
    next.provenance.observationRequestId = observations.value.requestId;
    next.available = true;
  } else {
    next.errors.observations = observations.reason?.code || 'UNAVAILABLE';
  }
  if (runs.status === 'fulfilled') {
    const runIds = runs.value.data?.items || [];
    next.runId = runIds[0] || '';
    next.provenance.runListRequestId = runs.value.requestId;
    if (next.runId) {
      try {
        const readiness = await getV1CanonicalReadiness(next.runId, { signal: ctrl.signal });
        next.readiness = readiness.data;
        next.provenance.readinessRequestId = readiness.requestId;
        next.available = true;
      } catch (error) {
        if (error?.name === 'AbortError') return;
        next.errors.readiness = error?.code || 'UNAVAILABLE';
      }
    } else {
      next.errors.readiness = 'NO_CANONICAL_RUN';
    }
  } else {
    next.errors.readiness = runs.reason?.code || 'UNAVAILABLE';
  }
  if (ctrl.signal.aborted) return;
  next.available = Object.keys(next.errors).length === 0;
  state.v1 = next;
  renderV1Workspace();
}

async function captureObservation() {
  if (!state.symbol || !state.signal) {
    toast('请先完成一次研判，再保存本地 research observation。');
    return;
  }
  const button = $('btnCaptureObs');
  button.disabled = true;
  try {
    const period = ['day', 'week', 'month'].includes(state.period) ? state.period : 'day';
    const captured = await captureLocalResearchObservation(state.symbol, period);
    toast(`已保存本地 research observation：${captured.data?.observation_id || '完成'}；不会触发交易。`);
    await loadV1Workspace();
  } catch (error) {
    toast(`本地 research observation 保存失败：${error?.code || 'UNAVAILABLE'}`);
  } finally {
    button.disabled = false;
  }
}

/* ---------- 研判（generation token + AbortController 防串票） ---------- */
let analyzeGen = 0;
let analyzeCtrl = null;

function clearInstrumentView(code, reason) {
  state.signal = null;
  state.klines = [];
  state.viewKs = [];
  state.chan = null;
  state.minute = null;
  state.quoteName = '';
  state.flows = [];
  state.engine = null;
  chart.clear();
  renderFlow([]);
  renderAnalysisUnavailable(code, reason);
  paintHud(-1);
}

async function analyze(symbol) {
  if (!symbol) return;
  const code = String(symbol).replace(/\D/g, '').slice(0, 6);
  if (!/^\d{6}$/.test(code)) {
    toast('请输入 6 位 A 股、基金或北交所代码。');
    return;
  }
  const gen = ++analyzeGen;
  if (analyzeCtrl) analyzeCtrl.abort();
  const ctrl = new AbortController();
  analyzeCtrl = ctrl;

  state.symbol = code;
  clearInstrumentView(code, 'LOADING');
  loadSavedAI(code);
  loadSavedVision(code);
  $('kw').value = code;
  jset(LS.last, code);
  setStatus('研判中…');
  deckLoading(true);
  try {
    const period = state.view === 'week' ? 'week' : 'day';
    const a = await getAdvisoryAnalysis(code, period, { signal: ctrl.signal });
    if (gen !== analyzeGen) return; // 已切票，丢弃旧响应
    if (a.error) throw new Error(a.error);
    const ch = a.chanlun || null;

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
    renderAll(a.signal, a.prediction || a.signal?.prediction, ch, {
      ...(a.meta || {}),
      advisory_evidence: a._evidence,
    });
    renderKline();
    renderFlow(a.flows || []);
    renderWatch();
    setStatus('');
    loadMarket();
    if (state.view === 'minute') loadMinute();
  } catch (err) {
    if (err.name === 'AbortError') return;
    const reason = err?.code || err?.message || 'ANALYSIS_UNAVAILABLE';
    clearInstrumentView(code, reason);
    setStatus(`${code} · UNAVAILABLE · ${reason}`);
  } finally {
    if (gen === analyzeGen) deckLoading(false);
  }
}

async function loadMinute() {
  const gen = analyzeGen;
  const symbol = state.symbol;
  state.minute = null;
  chart.clear();
  paintHud(-1);
  renderChanlunMinute(null);
  try {
    const snapshot = await getAdvisoryMinute(symbol, { signal: analyzeCtrl?.signal });
    if (gen !== analyzeGen || symbol !== state.symbol) return;
    if (snapshot.error) throw new Error(snapshot.error);
    state.minute = snapshot.minute;
    renderMinute();
    renderChanlunMinute(snapshot.chanlun || null);
    setStatus('');
  } catch (error) {
    if (error?.name === 'AbortError') return;
    if (gen !== analyzeGen || symbol !== state.symbol) return;
    state.minute = null;
    chart.clear();
    paintHud(-1);
    renderChanlunMinute(null);
    setStatus(`${symbol} 分时 · UNAVAILABLE · ${error?.code || error?.message || 'NO_DATA'}`);
  }
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
      const data = await searchAdvisoryInstruments(kw);
      if ($('kw').value.trim() !== kw) return;
      const list = data.results || data.items || [];
      if (!list.length) { $('suggest').style.display = 'none'; return; }
      const host = $('suggest');
      host.replaceChildren();
      list.forEach((item) => {
        const code = String(item?.code || item?.symbol || '').replace(/\D/g, '').slice(0, 6);
        if (!/^\d{6}$/.test(code)) return;
        const row = document.createElement('div');
        row.dataset.code = code;
        row.appendChild(document.createTextNode(`${code} `));
        const name = document.createElement('span');
        name.textContent = String(item?.name || '').slice(0, 80);
        row.appendChild(name);
        row.onclick = () => { host.style.display = 'none'; analyze(code); };
        host.appendChild(row);
      });
      host.style.display = host.childElementCount ? 'block' : 'none';
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

$('btnCaptureObs').onclick = captureObservation;
$('btnEvidenceRefresh').onclick = loadV1Workspace;
$('btnEvidence').onclick = () => {
  const card = $('evidenceCard');
  const header = card?.querySelector('.cell-h');
  if (header && header.getAttribute('aria-expanded') !== 'true') header.click();
  card?.scrollIntoView({ behavior: 'smooth', block: 'center' });
};

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
loadV1Workspace();
analyze(jget(LS.last) || '600519');
setInterval(loadMarket, 60000);
setInterval(loadV1Workspace, 60000);
