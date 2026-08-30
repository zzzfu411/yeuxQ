/* DOM / 格式化 / 存储 小工具 */
export const $ = (id) => document.getElementById(id);

export const jget = (k) => {
  try { return JSON.parse(localStorage.getItem(k) || 'null'); } catch (e) { return null; }
};
export const jset = (k, v) => localStorage.setItem(k, JSON.stringify(v));

export function setTxt(id, t) {
  const e = $(id);
  if (e) e.textContent = t == null || t === '' ? '—' : t;
}
export function clip(s, n) {
  s = String(s || '');
  return s.length > n ? s.slice(0, n) + '…' : s;
}

/* 动作 → 颜色类（A 股习惯：红涨绿跌） */
export function cls(a) {
  if (!a) return '';
  if (a.includes('卖')) return 'dn';
  if (a.includes('买')) return 'up';
  return '';
}
export function tone(a) {
  if (!a) return 'watch';
  if (a.includes('买')) return 'buy';
  if (a.includes('卖')) return 'sell';
  return 'watch';
}
export function sideCls(s) {
  return (s || '').includes('买') ? 'up' : (s || '').includes('卖') ? 'dn' : '';
}

export function fmtVol(v) {
  v = +v || 0;
  const a = Math.abs(v);
  if (a >= 1e8) return (v / 1e8).toFixed(2) + '亿';
  if (a >= 1e4) return (v / 1e4).toFixed(1) + '万';
  return a ? String(Math.round(v)) : '0';
}
export function fmtPx(v) {
  if (v == null || v === '' || isNaN(+v)) return '—';
  return (+v).toFixed(2);
}
export function fmtAmt(v) {
  if (v == null || isNaN(v)) return '—';
  const a = Math.abs(v);
  if (a >= 1e8) return (v / 1e8).toFixed(2) + '亿';
  if (a >= 1e4) return (v / 1e4).toFixed(1) + '万';
  return (+v).toFixed(0);
}

/* 外部文本进 innerHTML 前必须转义 */
export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

/* Markdown → 消毒后的 HTML */
export function md2html(md) {
  if (!md) return '';
  const text = String(md);
  try {
    if (!window.marked?.parse || !window.DOMPurify?.sanitize) return esc(text);
    return window.DOMPurify.sanitize(window.marked.parse(text));
  } catch (e) {
    return esc(text);
  }
}

export function toast(msg) {
  const box = $('toasts');
  if (!box) return;
  const d = document.createElement('div');
  d.className = 'toast';
  d.textContent = msg;
  box.appendChild(d);
  setTimeout(() => d.remove(), 8000);
}

export function setStatus(t) {
  const el = $('status');
  if (el) el.textContent = t || '';
}
