/* 自选 / 历史 / 一览 弹出层 + 扫描弹窗 + 大盘状态条 */
import { state, bus, LS } from './state.js';
import { $, jget, jset, esc } from './util.js';
import { getAdvisoryMarketOverview, getAdvisoryWatchlistQuotes } from './api.js';

export function watchList() { return jget(LS.watch) || []; }
export function histList() { return jget(LS.hist) || []; }

export function percentEvidence(value) {
  const number = value == null || value === '' ? null : Number(value);
  if (!Number.isFinite(number)) return { text: 'UNKNOWN', className: 'dim' };
  return { text: `${number}%`, className: number >= 0 ? 'up' : 'dn' };
}

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
  const selected = w.slice(0, 12);
  try {
    const response = await getAdvisoryWatchlistQuotes(selected.map((item) => item.code));
    const quotes = new Map((response.items || []).map((quote) => [
      String(quote.symbol || '').slice(0, 6),
      quote,
    ]));
    $('wpOv').innerHTML = selected.map((item) => {
      const quote = quotes.get(item.code);
      if (!quote) {
        return `<div class="wp-item" data-code="${esc(item.code)}"><span class="wp-code">${esc(item.code)}</span><span class="wp-name">${esc(item.name || '')}</span><span class="dim">UNAVAILABLE</span></div>`;
      }
      const pct = percentEvidence(quote.pct);
      return `<div class="wp-item" data-code="${esc(item.code)}"><span class="wp-code">${esc(item.code)}</span><span class="wp-name">${esc(quote.name || item.name)}</span><span class="${pct.className}">${esc(pct.text)}</span></div>`;
    }).join('');
    $('wpOv').querySelectorAll('.wp-item').forEach((el) => {
      el.onclick = () => bus.emit('analyze', el.dataset.code);
    });
  } catch (error) {
    $('wpOv').innerHTML = '<div class="wp-empty">UNAVAILABLE · advisory 自选报价暂不可用</div>';
  }
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

export function bindScan() {
  const trigger = $('btnScan');
  trigger.disabled = true;
  trigger.setAttribute('aria-disabled', 'true');
  trigger.title = 'UNAVAILABLE：扫描尚未进入只读 advisory 合同';
  trigger.onclick = null;
  $('scanClose').onclick = () => { $('scanOv').classList.remove('show'); };
  $('scanOv').addEventListener('click', (e) => {
    if (e.target === $('scanOv')) $('scanOv').classList.remove('show');
  });
}

/* ---------- 大盘状态条 ---------- */
export async function loadMarket() {
  try {
    const m = await getAdvisoryMarketOverview();
    const last = m.last || {}, br = m.breadth || {};
    const evidence = m._evidence || {};
    const marketChange = percentEvidence(m.change_pct);
    const eng = state.engine;
    const engHtml = eng
      ? (eng.available
        ? `<span class="tape-item"><span class="dot ok"></span>Rust ${esc(eng.mode || '')}</span>`
        : `<span class="tape-item"><span class="dot warn"></span>Python 回退</span>`)
      : '';
    $('marketBar').innerHTML = `
      <span class="tape-item">上证 <b>${last.close ?? '—'}</b></span>
      <span class="tape-item ${marketChange.className}">${esc(marketChange.text)}</span>
      <span class="tape-sep"></span>
      <span class="tape-item">涨 <b class="up">${br.up ?? '—'}</b> / 跌 <b class="dn">${br.down ?? '—'}</b></span>
      <span class="tape-sep"></span>
      <span class="tape-item dim">ADVISORY · ${esc(evidence.freshness || 'UNKNOWN')} · 非 canonical</span>
      <span class="tape-right">${engHtml}<span class="tape-item dim">研报留存 24h</span></span>`;
  } catch (e) {
    $('marketBar').innerHTML = '<span class="tape-item dim">UNAVAILABLE · advisory 大盘数据暂不可用</span>';
  }
}
