/* 研报 / 资讯 / 财报 / 晨报：只读历史；生成能力在统一前端中显式禁用。 */
import { state } from './state.js';
import { $, setTxt, esc, md2html, toast } from './util.js';
import { getAdvisoryReport, listAdvisoryReports } from './api.js';
import { openCell } from './cells.js';
import { setDot } from './cells.js';
import {
  renderToolTrace, bindToolTrace, agenticMetaBits, agenticBudgetHtml,
} from './trace.js';

const GENERATION_UNAVAILABLE =
  'UNAVAILABLE：统一工作台当前仅开放历史报告只读浏览；生成能力不会发起网络请求。';

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
    $('aiBody').innerHTML =
      '<div class="disc">没有可读的历史报告；资讯、速报与财报生成暂不可用。</div>';
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
  $('aiMeta').textContent = `${symbol} · 历史报告读取中…`;
  $('aiBody').textContent = '…';
  paintAIHist([], '');
  setTxt('aiPrev', '历史报告读取中…');
  setTxt('aiChip', '—');
  setDot('ai', '');
  try {
    const r = await listAdvisoryReports(symbol, { limit: 12 });
    if (symbol !== state.symbol) return; // 换票后丢弃旧响应
    const items = r.items || [];
    const ttl = r.ttl_hours || 24;
    if (!items.length) {
      paintAI('', '历史报告为空；统一工作台不会发起生成请求。', [], '');
      setTxt('aiPrev', '历史报告为空 · 生成暂不可用'); setTxt('aiChip', '—');
      setDot('ai', '');
      return;
    }
    const last = items[0];
    const one = await getAdvisoryReport(last.report_id);
    if (symbol !== state.symbol) return;
    if (!one.ok) { paintAI('', one.error || '读取失败', items, ''); return; }
    paintAI(one.markdown, `已保存 · ${kindLabel(one.kind)} · ${one.stamp} · ${remainLabel(one.ttl_remain_sec, ttl)}`, items, one.report_id, one);
    setTxt('aiPrev', `上次${kindLabel(one.kind)} ${one.stamp}`);
    setTxt('aiChip', remainLabel(last.ttl_remain_sec, ttl));
    setDot('ai', 'acc');
  } catch (e) {
    if (symbol !== state.symbol) return;
    if (e.name !== 'AbortError') paintAI('', e.message, [], '');
  }
}

async function openSavedAI(reportId) {
  if (!reportId) return;
  const symbol = state.symbol;
  try {
    const one = await getAdvisoryReport(reportId);
    if (symbol !== state.symbol) return;
    if (!one.ok) { toast(one.error || '读取失败'); return; }
    const list = await listAdvisoryReports(symbol, { limit: 12 });
    if (symbol !== state.symbol) return;
    const ttl = list.ttl_hours || one.ttl_hours || 24;
    paintAI(
      one.markdown,
      `已保存 · ${kindLabel(one.kind)} · ${one.stamp} · ${remainLabel(one.ttl_remain_sec, ttl)}`,
      list.items || [],
      one.report_id,
      one,
    );
    openCell('ai');
  } catch (error) {
    if (symbol !== state.symbol) return;
    toast(error?.message || '读取失败');
  }
}

/* ---------- 生成：资讯 / 速报 / 财报 ---------- */
export async function runAI(kind) {
  openCell('ai');
  setDot('ai', '');
  const label = kindLabel(kind);
  $('aiMeta').textContent = 'UNAVAILABLE · RESEARCH ONLY · 不会发起网络请求';
  $('aiBody').textContent = `${label}生成 ${GENERATION_UNAVAILABLE}`;
  setTxt('aiPrev', `${label}生成暂不可用`);
  setTxt('aiChip', 'BLOCK');
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
function paintBrief(md, meta) {
  $('briefMeta').textContent = meta || '';
  $('briefBody').innerHTML = md ? md2html(md)
    : '<div class="disc">没有可读的历史晨报；晨报生成暂不可用。</div>';
}

export async function loadSavedBrief() {
  if (!$('briefBody')) return;
  try {
    const r = await listAdvisoryReports('WATCH', { limit: 12 });
    const items = r.items || [];
    const ttl = r.ttl_hours || 24;
    const last = items.find((it) => it.kind === 'brief') || items[0];
    if (!last) {
      paintBrief('', '历史晨报为空；统一工作台不会发起生成请求。');
      setTxt('briefPrev', '历史晨报为空 · 生成暂不可用'); setTxt('briefChip', '—');
      return;
    }
    const one = await getAdvisoryReport(last.report_id);
    if (!one.ok) { paintBrief('', one.error || '读取失败'); return; }
    paintBrief(one.markdown, `已保存 · ${one.stamp} · ${remainLabel(one.ttl_remain_sec, ttl)}`);
    setTxt('briefPrev', `上次晨报 ${one.stamp}`);
    setTxt('briefChip', remainLabel(one.ttl_remain_sec, ttl));
    setDot('brief', 'acc');
  } catch (e) { paintBrief('', e.message); }
}

export async function runBrief() {
  openCell('brief');
  setDot('brief', '');
  $('briefMeta').textContent = 'UNAVAILABLE · RESEARCH ONLY · 不会发起网络请求';
  $('briefBody').textContent = `晨报生成 ${GENERATION_UNAVAILABLE}`;
  setTxt('briefPrev', '晨报生成暂不可用');
  setTxt('briefChip', 'BLOCK');
}
