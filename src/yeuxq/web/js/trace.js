/* 调查过程：工具调用 trace 渲染 / meta 查证片段 / 超时信号。看图、财报、资讯共用 */
import { $, esc } from './util.js';

export const AGENTIC_TIMEOUT_MS = 360000; // 后端硬上限约 330 秒，留余量覆盖上传与响应传输

export const TOOL_LABEL = {
  yeux_search: '资讯检索',
  yeux_deep_search: '深度检索',
  get_fund_flow: '资金流核对',
  get_realtime_flow: '分时资金',
  get_quote: '行情快照',
  get_finance_snapshot: '财务估值',
  get_klines: 'K线数据',
};

export function mergeAbortSignals(a, b) {
  if (typeof AbortSignal.any === 'function') return AbortSignal.any([a, b]);
  const c = new AbortController();
  const abort = () => c.abort();
  if (a?.aborted || b?.aborted) { c.abort(); return c.signal; }
  if (a) a.addEventListener('abort', abort, { once: true });
  if (b) b.addEventListener('abort', abort, { once: true });
  return c.signal;
}

export function withTimeout(signal, ms = AGENTIC_TIMEOUT_MS) {
  const timeoutCtrl = new AbortController();
  const timeoutId = setTimeout(() => timeoutCtrl.abort(), ms);
  return {
    signal: mergeAbortSignals(signal, timeoutCtrl.signal),
    clear() { clearTimeout(timeoutId); },
  };
}

function toolLabel(name) {
  return TOOL_LABEL[name] || String(name || '工具');
}

function toolArgsText(name, args) {
  args = args && typeof args === 'object' ? args : {};
  if (name === 'yeux_search' || name === 'yeux_deep_search') {
    return args.query != null && args.query !== '' ? String(args.query) : '';
  }
  const bits = [];
  Object.keys(args).forEach((k) => {
    if (k === 'symbol') return;
    const v = args[k];
    if (v == null || v === '') return;
    bits.push(k + '=' + v);
  });
  return bits.join(' ');
}

function fmtElapsed(sec) {
  const s = Number(sec);
  if (sec == null || isNaN(s)) return '';
  return (s >= 10 ? s.toFixed(1) : s.toFixed(2)) + 's';
}

/** 调查过程 HTML；trace 为空/缺失则 ""。外部字符串一律 esc() */
export function renderToolTrace(r) {
  const trace = Array.isArray(r?.tool_trace) ? r.tool_trace : [];
  if (!trace.length) return '';
  const n = r.tool_calls_count != null ? r.tool_calls_count : trace.length;
  const rounds = r.rounds != null ? r.rounds : '—';
  const rows = trace.map((raw) => {
    const t = raw || {};
    const name = t.name || '';
    const argText = toolArgsText(name, t.args);
    const elapsed = fmtElapsed(t.elapsed_sec);
    const ok = t.ok !== false;
    const summary = t.summary != null ? String(t.summary) : '';
    return `<div class="vision-trace-row${ok ? '' : ' fail'}" title="${esc(summary)}">
      <span class="vision-trace-name">${esc(toolLabel(name))}</span>
      ${argText ? `<span class="vision-trace-args">${esc(argText)}</span>` : ''}
      ${elapsed ? `<span class="vision-trace-time">${esc(elapsed)}</span>` : ''}
      <span class="vision-trace-flag">${ok ? '✓' : '✗'}</span>
    </div>`;
  }).join('');
  return `<div class="vision-trace">
    <button type="button" class="vision-trace-h" aria-expanded="false">调查过程 · ${esc(String(n))} 次工具调用 / ${esc(String(rounds))} 轮</button>
    <div class="vision-trace-list" hidden>${rows}</div>
  </div>`;
}

/** meta 查证片段：查证 N 次 / 查证 N 次+回落成稿 / 未启用工具 */
export function agenticMetaBits(r) {
  const bits = [];
  if (!r) return bits;
  const n = Number(r.tool_calls_count);
  const traceLen = Array.isArray(r.tool_trace) ? r.tool_trace.length : 0;
  const count = (r.tool_calls_count != null && Number.isFinite(n)) ? n : traceLen;
  // 1. 正常 agentic：查证 N 次  2. 回落但查过：查证 N 次 + 回落成稿  3. 纯 legacy：未启用工具
  if (count > 0) {
    bits.push('查证 ' + count + ' 次');
    if (r.agentic === false) bits.push('回落成稿');
  } else if (r.agentic === false) {
    bits.push('未启用工具');
  }
  return bits;
}

export function agenticBudgetHtml(r) {
  return r && r.budget_hit === true ? ' · <b class="vision-budget">预算截断</b>' : '';
}

export function bindToolTrace(host) {
  const root = host || $('visionBody');
  if (!root) return;
  root.querySelectorAll('.vision-trace-h').forEach((btn) => {
    if (btn._bound) return;
    btn._bound = true;
    btn.onclick = () => {
      const list = btn.nextElementSibling;
      const open = btn.getAttribute('aria-expanded') === 'true';
      btn.setAttribute('aria-expanded', open ? 'false' : 'true');
      if (list) list.hidden = open;
    };
  });
}
