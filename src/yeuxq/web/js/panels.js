/* 自选 / 历史 / 一览 弹出层 + 扫描弹窗 + 大盘状态条 */
import { state, bus, LS } from './state.js';
import { $, jget, jset, esc, setTxt } from './util.js';
import { getJSON, postJSON } from './api.js';

export function watchList() { return jget(LS.watch) || []; }
export function histList() { return jget(LS.hist) || []; }

export function saveWatch(a) { jset(LS.watch, a); renderWatch(); }

export function toggleStar() {
  if (!state.symbol) return;
  const a = watchList();
  const i = a.findIndex((x) => x.code === state.symbol);
  if (i >= 0) a.splice(i, 1);
  else a.unshift({
    code: state.symbol, name: state.quoteName || '',
    action: (state.signal || {}).action || '', score: (state.signal || {}).score || 0, t: Date.now(),
  });
  saveWatch(a.slice(0, 40));
}

export function addHist(code, name, sig) {
  const a = histList().filter((x) => x.code !== code);
  a.unshift({ code, name, action: (sig || {}).action || '', score: (sig || {}).score || 0, t: Date.now() });
  jset(LS.hist, a.slice(0, 30));
}

export function renderWatch() {
  const w = watchList(), h = histList();
  const star = $('btnStar');
  const starred = w.some((x) => x.code === state.symbol);
  star.textContent = starred ? '★' : '☆';
  star.classList.toggle('on', starred);
  const row = (x) => `<div class="wp-item" data-code="${esc(x.code)}"><span class="wp-code">${esc(x.code)}</span><span class="wp-name">${esc(x.name || '')}</span><span>${esc(x.action || '—')}</span></div>`;
  $('wpWatch').innerHTML = w.length ? w.map(row).join('') : '<div class="wp-empty">点 ☆ 收入自选</div>';
  $('wpHist').innerHTML = h.length ? h.map(row).join('') : '<div class="wp-empty">暂无历史</div>';
  [...$('wpWatch').querySelectorAll('.wp-item'), ...$('wpHist').querySelectorAll('.wp-item')]
    .forEach((el) => { el.onclick = () => bus.emit('analyze', el.dataset.code); });
}

function switchTab(t) {
  document.querySelectorAll('.wp-tabs button').forEach((b) => b.classList.toggle('on', b.dataset.tab === t));
  $('wpWatch').style.display = t === 'watch' ? 'block' : 'none';
  $('wpHist').style.display = t === 'hist' ? 'block' : 'none';
  $('wpOv').style.display = t === 'ov' ? 'block' : 'none';
  if (t === 'ov') loadOverview();
}

async function loadOverview() {
  const w = watchList();
  if (!w.length) { $('wpOv').innerHTML = '<div class="wp-empty">先加自选</div>'; return; }
  const rows = await Promise.all(w.slice(0, 12).map(async (x) => {
    try {
      const q = await getJSON(`/api/quote?symbol=${x.code}`);
      return `<div class="wp-item" data-code="${esc(x.code)}"><span class="wp-code">${esc(x.code)}</span><span class="wp-name">${esc(q.name || x.name)}</span><span class="${(q.pct || 0) >= 0 ? 'up' : 'dn'}">${q.pct ?? '—'}%</span></div>`;
    } catch (e) { return ''; }
  }));
  $('wpOv').innerHTML = rows.join('');
  $('wpOv').querySelectorAll('.wp-item').forEach((el) => { el.onclick = () => bus.emit('analyze', el.dataset.code); });
}

export function bindPanels() {
  $('btnStar').onclick = toggleStar;
  $('btnWatch').onclick = () => { $('wp').classList.toggle('show'); switchTab('watch'); };
  $('btnHist').onclick = () => { $('wp').classList.add('show'); switchTab('hist'); };
  document.querySelectorAll('.wp-tabs button').forEach((b) => { b.onclick = () => switchTab(b.dataset.tab); });
  document.addEventListener('click', (e) => {
    const wp = $('wp');
    if (wp.classList.contains('show') && !e.target.closest('#wp') && !e.target.closest('#btnWatch') && !e.target.closest('#btnHist')) {
      wp.classList.remove('show');
    }
  });
}

/* ---------- 扫描 ---------- */
let scanTimer = null;

async function openScan() {
  $('scanOv').classList.add('show');
  const w = watchList().map((x) => x.code);
  await postJSON('/api/scan/start', w.length ? { symbols: w } : {});
  pollScan();
}

function pollScan() {
  clearInterval(scanTimer);
  scanTimer = setInterval(async () => {
    let s;
    try { s = await getJSON('/api/scan'); } catch (e) { return; }
    const tot = s.total || 1, p = s.progress || 0;
    $('scanStage').textContent = s.stage || s.status || '';
    $('scanBar').style.width = (p / tot * 100) + '%';
    $('scanStat').textContent = `${p}/${tot}`;
    $('scanTb').innerHTML = (s.results || []).map((r, i) =>
      `<tr><td>${i + 1}</td><td>${esc(r.symbol)}</td><td>${esc(r.name || '')}</td><td><b>${esc(r.action || '')}</b></td><td>${r.score ?? ''}</td><td class="${(r.pct || 0) >= 0 ? 'up' : 'dn'}">${r.pct ?? ''}</td><td><button data-c="${esc(r.symbol)}">开</button></td></tr>`
    ).join('');
    $('scanTb').querySelectorAll('button').forEach((b) => {
      b.onclick = () => { $('scanOv').classList.remove('show'); bus.emit('analyze', b.dataset.c); };
    });
    if (s.status === 'done' || s.status === 'error' || s.status === 'idle') clearInterval(scanTimer);
  }, 800);
}

export function bindScan() {
  $('btnScan').onclick = openScan;
  $('scanClose').onclick = () => { $('scanOv').classList.remove('show'); clearInterval(scanTimer); };
  $('scanOv').addEventListener('click', (e) => {
    if (e.target === $('scanOv')) { $('scanOv').classList.remove('show'); clearInterval(scanTimer); }
  });
}

/* ---------- 大盘状态条 ---------- */
export async function loadMarket() {
  try {
    const m = await getJSON('/api/market/overview');
    const last = m.last || {}, br = m.breadth || {};
    const eng = state.engine;
    const engHtml = eng
      ? (eng.available
        ? `<span class="tape-item"><span class="dot ok"></span>Rust ${esc(eng.mode || '')}</span>`
        : `<span class="tape-item"><span class="dot warn"></span>Python 回退</span>`)
      : '';
    $('marketBar').innerHTML = `
      <span class="tape-item">上证 <b>${last.close ?? '—'}</b></span>
      <span class="tape-item ${(m.change_pct || 0) >= 0 ? 'up' : 'dn'}">${m.change_pct ?? ''}%</span>
      <span class="tape-sep"></span>
      <span class="tape-item">涨 <b class="up">${br.up ?? '—'}</b> / 跌 <b class="dn">${br.down ?? '—'}</b></span>
      <span class="tape-sep"></span>
      <span class="tape-item dim">公开行情 · 无暗盘</span>
      <span class="tape-right">${engHtml}<span class="tape-item dim">研报留存 24h</span></span>`;
  } catch (e) {
    $('marketBar').innerHTML = '<span class="tape-item dim">大盘暂不可用</span>';
  }
}
