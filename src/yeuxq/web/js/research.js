/* 研报 / 资讯 / 财报 / 晨报：读回、生成（分阶段进度 + 可取消）、24h 落盘 */
import { state } from './state.js';
import { $, setTxt, esc, md2html, toast } from './util.js';
import { getJSON, postJSON } from './api.js';
import { openCell } from './cells.js';
import { setDot } from './cells.js';
import {
  renderToolTrace, bindToolTrace, agenticMetaBits, agenticBudgetHtml,
  mergeAbortSignals, AGENTIC_TIMEOUT_MS,
} from './trace.js';

export function kindLabel(k) {
  return k === 'earnings' ? '财报' : k === 'news' ? '资讯' : k === 'brief' ? '晨报' : k === 'vision' ? '看图' : '速报';
}

export function remainLabel(sec, ttl) {
  const hours = ttl != null ? ttl : 24;
  if (sec == null) return `保留 ${hours} 小时`;
  const h = Math.max(0, Math.floor(sec / 3600));
  const m = Math.max(0, Math.floor((sec % 3600) / 60));
  if (h >= 20) return `约 ${hours} 小时内有效`;
  if (h >= 1) return `还剩 ${h} 小时`;
  if (m >= 1) return `还剩 ${m} 分钟`;
  return '即将过期';
}

/* ---------- 分阶段任务进度（前端节奏提示，真实进度以后端返回为准） ---------- */
export class TaskProgress {
  constructor(host, stages) {
    this.host = host;
    this.stages = stages;
    this.t0 = Date.now();
    this.ctrl = new AbortController();
    this.timer = null;
    this.cancelled = false;
  }
  start() {
    this.host.innerHTML = `<div class="task">
      <div class="task-head"><span class="spinner"></span><span class="task-stage"></span>
        <span class="task-time"></span><button type="button" class="task-cancel">取消</button></div>
      <div class="task-steps">${this.stages.map(() => '<i></i>').join('')}</div>
    </div>`;
    this.host.querySelector('.task-cancel').onclick = () => this.cancel();
    this.tick();
    this.timer = setInterval(() => this.tick(), 500);
    return this.ctrl.signal;
  }
  tick() {
    const sec = (Date.now() - this.t0) / 1000;
    const n = this.stages.length;
    // 节奏启发：前几段各给几秒，最后一段等到响应回来
    const idx = Math.min(n - 1, Math.floor(sec / (sec < 20 ? 4 : 12)));
    const stageEl = this.host.querySelector('.task-stage');
    const timeEl = this.host.querySelector('.task-time');
    if (stageEl) stageEl.textContent = this.stages[idx] + '…';
    if (timeEl) timeEl.textContent = sec.toFixed(0) + 's';
    this.host.querySelectorAll('.task-steps i').forEach((el, i) => el.classList.toggle('done', i <= idx));
  }
  finish() {
    clearInterval(this.timer);
    const t = this.host.querySelector('.task');
    if (t) t.remove();
  }
  cancel() {
    this.cancelled = true;
    this.ctrl.abort();
    this.finish();
    this.host.innerHTML = '<div class="disc">已取消（服务端任务可能仍会完成并落盘）。</div>';
  }
}

/* 自主调查任务：第二/首段拉长，提示 1–3 分钟 */
class AIAgenticProgress extends TaskProgress {
  start() {
    const sig = super.start();
    const t = this.host.querySelector('.task');
    if (t) t.classList.add('vision-task');
    return sig;
  }
  tick() {
    const sec = (Date.now() - this.t0) / 1000;
    const n = this.stages.length;
    let longIdx = this.stages.findIndex((s) => s.includes('自主调查'));
    if (longIdx < 0) longIdx = 0;
    let idx = 0;
    if (n <= 1) idx = 0;
    else if (sec < 6 && longIdx > 0) idx = 0;
    else if (sec < 150) idx = longIdx;
    else if (sec < 200) idx = Math.min(n - 1, longIdx + 1);
    else idx = n - 1;
    const stageEl = this.host.querySelector('.task-stage');
    const timeEl = this.host.querySelector('.task-time');
    if (stageEl) {
      const long = (this.stages[idx] || '').includes('自主调查');
      stageEl.textContent = long
        ? (this.stages[idx] + '… 模型正在自行检索与核对，通常 1–3 分钟')
        : (this.stages[idx] + '…');
    }
    if (timeEl) timeEl.textContent = sec.toFixed(0) + 's';
    this.host.querySelectorAll('.task-steps i').forEach((el, i) => el.classList.toggle('done', i <= idx));
  }
}

/* ---------- 研报卡片（读回 + 历史） ---------- */
function paintAIHist(items, current) {
  const box = $('aiHist');
  if (!box) return;
  if (!items || !items.length) { box.innerHTML = ''; return; }
  box.innerHTML = items.slice(0, 12).map((it) =>
    `<button type="button" data-f="${esc(it.report_id)}" class="${it.report_id === current ? 'on' : ''}">${kindLabel(it.kind)} ${esc(it.stamp || '')}</button>`
  ).join('');
  box.querySelectorAll('button').forEach((b) => { b.onclick = () => openSavedAI(b.dataset.f); });
}

function paintAI(md, meta, items, current, extra) {
  $('aiMeta').textContent = meta || '';
  if (!md) {
    $('aiBody').innerHTML = '<div class="disc">还没有保存的分析。点资讯 / 速报 / 财报后会写入本地，默认保留 24 小时。</div>';
  } else {
    $('aiBody').innerHTML = renderToolTrace(extra) + `<div class="md">${md2html(md)}</div>`;
    bindToolTrace($('aiBody'));
  }
  paintAIHist(items, current);
}

function buildAIMetaHtml(r, saved, ttl) {
  const bits = [esc(r.model || 'grok-4.6'), 'xhigh', ...agenticMetaBits(r)];
  if (saved) bits.push('已存 ' + esc(saved));
  bits.push(esc(remainLabel((ttl || 24) * 3600, ttl || 24)));
  return bits.join(' · ') + agenticBudgetHtml(r);
}

export async function loadSavedAI(symbol) {
  if (!symbol || !$('aiBody')) return;
  try {
    const r = await getJSON(`/api/research/reports?symbol=${encodeURIComponent(symbol)}`);
    if (symbol !== state.symbol) return; // 换票后丢弃旧响应
    const items = r.items || [];
    const ttl = r.ttl_hours || 24;
    if (!items.length) {
      paintAI('', `尚未生成。点工具栏「资讯 / 速报 / 财报」后自动保存 ${ttl} 小时；再次生成同类型会覆盖。`, [], '');
      setTxt('aiPrev', '资讯 / 速报 / 财报'); setTxt('aiChip', '—');
      setDot('ai', '');
      return;
    }
    const last = items[0];
    const one = await getJSON(`/api/research/reports/${encodeURIComponent(last.report_id)}`);
    if (symbol !== state.symbol) return;
    if (!one.ok) { paintAI('', one.error || '读取失败', items, ''); return; }
    paintAI(one.markdown, `已保存 · ${kindLabel(one.kind)} · ${one.stamp} · ${remainLabel(one.ttl_remain_sec, ttl)}`, items, one.report_id, one);
    setTxt('aiPrev', `上次${kindLabel(one.kind)} ${one.stamp}`);
    setTxt('aiChip', remainLabel(last.ttl_remain_sec, ttl));
    setDot('ai', 'acc');
  } catch (e) {
    if (e.name !== 'AbortError') paintAI('', e.message, [], '');
  }
}

async function openSavedAI(reportId) {
  if (!reportId) return;
  const one = await getJSON(`/api/research/reports/${encodeURIComponent(reportId)}`);
  if (!one.ok) { toast(one.error || '读取失败'); return; }
  const list = await getJSON(`/api/research/reports?symbol=${encodeURIComponent(state.symbol)}`);
  const ttl = list.ttl_hours || one.ttl_hours || 24;
  paintAI(one.markdown, `已保存 · ${kindLabel(one.kind)} · ${one.stamp} · ${remainLabel(one.ttl_remain_sec, ttl)}`, list.items || [], one.report_id, one);
  openCell('ai');
}

/* ---------- 生成：资讯 / 速报 / 财报 ---------- */
const AI_STAGES = {
  news: ['Grok 自主调查（检索资讯）', '整理资讯', '落盘保存'],
  report: ['Grok 自主调查（检索 + 数据核对）', '综合研判成稿', '落盘保存'],
  earnings: ['Grok 自主调查（检索财报 + 估值核对）', '综合研判成稿', '落盘保存'],
};

export async function runAI(kind) {
  if (!state.symbol) { toast('先研判一只股票'); return; }
  openCell('ai');
  setDot('ai', 'acc');
  const task = new AIAgenticProgress($('aiBody'), AI_STAGES[kind] || AI_STAGES.report);
  const taskSignal = task.start();
  const timeoutCtrl = new AbortController();
  const timeoutId = setTimeout(() => timeoutCtrl.abort(), AGENTIC_TIMEOUT_MS);
  const signal = mergeAbortSignals(taskSignal, timeoutCtrl.signal);
  setTxt('aiPrev', kind === 'news' ? '检索资讯中…' : kind === 'earnings' ? '撰写财报中…' : '撰写速报中…');
  $('aiMeta').textContent = 'grok-4.6 · xhigh' + ($('deepMode').checked ? ' · 深检索' : '');
  const deep = $('deepMode').checked;
  try {
    let r, md;
    if (kind === 'news') {
      r = await postJSON('/api/research/news', { symbol: state.symbol, name: state.quoteName, deep }, { signal });
      md = r.ok ? `# 资讯\n\n${r.text || ''}` : (r.error || '失败');
    } else {
      const url = kind === 'earnings' ? '/api/research/earnings' : '/api/research/report';
      r = await postJSON(url, { symbol: state.symbol, deep }, { signal });
      md = r.report_markdown || r.error || '';
    }
    clearTimeout(timeoutId);
    task.finish();
    const ttl = r.ttl_hours || 24;
    const saved = r.report_id || '';
    if (r.ok === false) {
      $('aiMeta').textContent = r.error || '失败';
      $('aiBody').textContent = md || r.error || '失败';
      setTxt('aiPrev', r.error || '失败');
      setTxt('aiChip', '失败');
      return;
    }
    $('aiMeta').innerHTML = buildAIMetaHtml(r, saved, ttl);
    $('aiBody').innerHTML = renderToolTrace(r) + `<div class="md">${md2html(md)}</div>`;
    bindToolTrace($('aiBody'));
    setTxt('aiPrev', kind === 'news' ? '资讯已保存' : kind === 'earnings' ? '财报已保存' : '速报已保存');
    setTxt('aiChip', remainLabel(ttl * 3600, ttl));
    try {
      const list = await getJSON(`/api/research/reports?symbol=${encodeURIComponent(state.symbol)}`);
      paintAIHist(list.items || [], saved);
    } catch (e) { /* 后端未落盘时保留当前渲染 */ }
    openCell('ai');
  } catch (e) {
    clearTimeout(timeoutId);
    if (e.name === 'AbortError') {
      if (task.cancelled) return;
      task.finish();
      $('aiBody').textContent = '调查超时（已等待 6 分钟）。可点取消后重试，或稍后再试。';
      setTxt('aiPrev', '超时');
      return;
    }
    task.finish();
    $('aiBody').textContent = e.message;
    setTxt('aiPrev', e.message);
  }
}

/* 自测：把一份响应画到研报卡上（不发请求） */
export function applyAIResult(r, kind) {
  openCell('ai');
  setDot('ai', 'acc');
  const ttl = r.ttl_hours || 24;
  const saved = r.report_id || '';
  const md = kind === 'news'
    ? (r.ok === false ? (r.error || '') : `# 资讯\n\n${r.text || r.report_markdown || ''}`)
    : (r.report_markdown || r.error || '');
  $('aiMeta').innerHTML = buildAIMetaHtml(r || {}, saved, ttl);
  $('aiBody').innerHTML = renderToolTrace(r) + (md ? `<div class="md">${md2html(md)}</div>` : '');
  bindToolTrace($('aiBody'));
}

/* ---------- 自选晨报 ---------- */
function briefSymbols() {
  const w = (JSON.parse(localStorage.getItem('tl_watch') || 'null') || []).map((x) => x.code).filter(Boolean);
  if (w.length) return w.slice(0, 8);
  const hot = [...document.querySelectorAll('.hot [data-s]')].map((b) => b.dataset.s);
  const cur = state.symbol ? [state.symbol] : [];
  return [...cur, ...hot].filter((v, i, a) => v && a.indexOf(v) === i).slice(0, 8);
}

function paintBrief(md, meta) {
  $('briefMeta').textContent = meta || '';
  $('briefBody').innerHTML = md ? md2html(md)
    : '<div class="disc">点顶栏「晨报」：先扫自选技术面，再可选资讯与 grok 点评。保存 24 小时。</div>';
}

export async function loadSavedBrief() {
  if (!$('briefBody')) return;
  try {
    const r = await getJSON('/api/research/reports?symbol=WATCH');
    const items = r.items || [];
    const ttl = r.ttl_hours || 24;
    const last = items.find((it) => it.kind === 'brief') || items[0];
    if (!last) {
      paintBrief('', '尚未生成。☆自选后点「晨报」。');
      setTxt('briefPrev', '点顶栏「晨报」生成自选一览'); setTxt('briefChip', '—');
      return;
    }
    const one = await getJSON(`/api/research/reports/${encodeURIComponent(last.report_id)}`);
    if (!one.ok) { paintBrief('', one.error || '读取失败'); return; }
    paintBrief(one.markdown, `已保存 · ${one.stamp} · ${remainLabel(one.ttl_remain_sec, ttl)}`);
    setTxt('briefPrev', `上次晨报 ${one.stamp}`);
    setTxt('briefChip', remainLabel(one.ttl_remain_sec, ttl));
    setDot('brief', 'acc');
  } catch (e) { paintBrief('', e.message); }
}

export async function runBrief() {
  const symbols = briefSymbols();
  if (!symbols.length) { toast('先☆自选或打开一只股票'); return; }
  openCell('brief');
  setDot('brief', 'acc');
  const task = new TaskProgress($('briefBody'), ['扫描自选技术面', '检索市场资讯', 'Grok 组合点评', '落盘保存']);
  const signal = task.start();
  setTxt('briefPrev', '生成中…');
  $('briefMeta').textContent = `${symbols.length} 只自选 · 含资讯与点评`;
  const deep = $('deepMode').checked;
  try {
    const r = await postJSON('/api/research/brief', { symbols, deep, with_news: true, with_llm: true }, { signal });
    task.finish();
    const md = r.report_markdown || r.error || '';
    const ttl = r.ttl_hours || 24;
    paintBrief(md, r.ok === false ? (r.error || '失败') : `已保存 · ${symbols.length} 只 · ${remainLabel(ttl * 3600, ttl)}`);
    setTxt('briefPrev', r.ok === false ? (r.error || '失败') : `晨报 ${symbols.length} 只`);
    setTxt('briefChip', r.ok === false ? '失败' : `${symbols.length}只`);
    if (r.ok !== false) openCell('brief');
  } catch (e) {
    if (e.name === 'AbortError') return;
    task.finish();
    paintBrief('', e.message);
    setTxt('briefPrev', e.message);
  }
}
