/* 大单 / 五档 / 大宗 + 回测 / 规则对照 */
import { state } from './state.js';
import { $, setTxt, esc, fmtPx, fmtVol, fmtAmt, sideCls } from './util.js';
import { getJSON, postJSON } from './api.js';
import { openCell, setDot } from './cells.js';
import { watchList } from './panels.js';

function renderBook(book) {
  const asks = (book && book.asks) || [], bids = (book && book.bids) || [];
  if (!asks.length && !bids.length) return '<div class="disc">五档暂不可用</div>';
  const row = (x) => `<div class="lvl"><span>${fmtPx(x.price)}</span><span>${fmtVol(x.volume_hand || x.volume)}</span></div>`;
  return `<div class="book"><div class="asks"><h4>卖盘</h4>${[...asks].reverse().map(row).join('')}</div><div class="bids"><h4>买盘</h4>${bids.map(row).join('')}</div></div>`;
}

function renderOfTable(orders, limit) {
  const rows = (orders || []).slice(0, limit || 15);
  if (!rows.length) return '<div class="disc">当前分笔未筛出大单。阈值随股价自适应。</div>';
  return `<table class="of"><thead><tr><th>时间</th><th>方向</th><th>价</th><th>额</th></tr></thead><tbody>`
    + rows.map((o) => `<tr><td>${esc(o.time || '')}</td><td class="${sideCls(o.side)}">${esc(o.side || '—')}</td><td>${fmtPx(o.price)}</td><td class="${sideCls(o.side)}">${fmtAmt(o.amount)}</td></tr>`).join('')
    + `</tbody></table>`;
}

/* 大单：只在侧栏展开，不强制焦点层（需要放大用卡片上的焦点按钮） */
export async function loadOF() {
  if (!state.symbol) return;
  openCell('of');
  setDot('of', 'acc');
  $('ofBody').textContent = '…';
  setTxt('ofPrev', '加载中…');
  try {
    const r = await getJSON(`/api/orderflow/overview?symbol=${state.symbol}`);
    const L = r.large_orders || {}, S = L.summary || {}, th = L.thresholds || {};
    const Bl = r.block_trades || {}, book = r.order_book || {};
    const orders = L.large_orders || [];
    const supers = L.super_orders || [];
    const blocks = Bl.trades || [];
    const net = S.large_net_amount;
    $('ofBody').innerHTML = `<div class="disc">${esc(L.note || '')} 阈值 大单 ${fmtAmt(th.large)} / 超大 ${fmtAmt(th.super)}</div>
      <div class="row"><span>分笔 / 大单 / 超大</span><b>${S.tick_count || 0} / ${S.large_count || 0} / ${S.super_count || 0}</b></div>
      <div class="row"><span>大单净额</span><b class="${(net || 0) >= 0 ? 'up' : 'dn'}">${fmtAmt(net)}</b></div>
      ${renderBook(book)}
      <div class="row"><span>最近大单</span><b>${Math.min(orders.length, 15)} 笔</b></div>
      ${renderOfTable(orders, 15)}
      ${supers.length ? `<div class="row"><span>超大单</span><b>${supers.length} 笔</b></div>${renderOfTable(supers, 8)}` : ''}
      <div class="row"><span>大宗</span><b>${Bl.count || 0} · ${fmtAmt(Bl.total_amount)}</b></div>
      ${blocks.length ? `<table class="of"><thead><tr><th>日期</th><th>价</th><th>额</th><th>买方</th></tr></thead><tbody>${blocks.slice(0, 6).map((t) => `<tr><td>${esc(t.date || '')}</td><td>${fmtPx(t.price)}</td><td>${fmtAmt(t.amount)}</td><td>${esc(t.buyer || '—')}</td></tr>`).join('')}</tbody></table>` : '<div class="disc">暂无大宗披露</div>'}
      <div class="warn">${esc((r.dark_pool || {}).message || '真暗盘不可用')}</div>`;
    setTxt('ofPrev', `大单 ${S.large_count || 0} · 净额 ${fmtAmt(net)}`);
    const chip = $('ofChip');
    chip.textContent = String(S.large_count || 0);
    chip.className = 'cell-chip ' + ((net || 0) >= 0 ? 'up' : 'dn');
  } catch (e) {
    $('ofBody').textContent = e.message;
    setTxt('ofPrev', e.message);
  }
}

export async function runBacktest() {
  if (!state.symbol) return;
  openCell('bt');
  setDot('bt', 'acc');
  $('btBody').textContent = '回测中…';
  setTxt('btPrev', '回测中…');
  try {
    const r = await postJSON('/api/backtest', { symbol: state.symbol, horizon: 5, min_score: 60, lookback: 250, point_in_time: true });
    if (r.error) { $('btBody').textContent = r.error; setTxt('btPrev', r.error); return; }
    const exp = r.expectancy ?? r.avg_return;
    $('btBody').innerHTML = `<div class="row"><span>${esc(r.engine || '')}</span><b>${r.trades}笔 · 胜率${r.win_rate}% · 期望${exp}%</b></div><div class="disc">${esc(r.disclaimer || '')}</div>`;
    setTxt('btPrev', `${r.trades}笔 · 胜率 ${r.win_rate}%`);
    const chip = $('btChip');
    chip.textContent = `${exp}%`;
    chip.className = 'cell-chip ' + ((exp || 0) >= 0 ? 'up' : 'dn');
  } catch (e) {
    $('btBody').textContent = e.message;
    setTxt('btPrev', e.message);
  }
}

export async function runCompare() {
  openCell('bt');
  setDot('bt', 'acc');
  $('btBody').textContent = '对照中…';
  setTxt('btPrev', '对照中…');
  const pool = [state.symbol, ...watchList().map((x) => x.code), '600519', '000001']
    .filter((v, i, a) => v && a.indexOf(v) === i).slice(0, 6);
  try {
    const r = await postJSON('/api/backtest/compare', { symbols: pool, horizon: 5, min_score: 60, lookback: 200 });
    if (r.error) { $('btBody').textContent = r.error; setTxt('btPrev', r.error); return; }
    $('btBody').innerHTML = Object.entries(r.summary || {}).map(([k, v]) =>
      `<div class="row"><span>${esc(k)}${k === r.suggested_variant ? ' ←' : ''}</span><b class="${(v.valid_expectancy || 0) >= 0 ? 'up' : 'dn'}">验 ${v.valid_expectancy}%</b></div>`
    ).join('');
    setTxt('btPrev', r.suggested_variant ? `建议 ${r.suggested_variant}` : '对照完成');
    setTxt('btChip', '对照');
  } catch (e) {
    $('btBody').textContent = e.message;
    setTxt('btPrev', e.message);
  }
}
