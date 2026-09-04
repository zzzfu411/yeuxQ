/* 侧栏手风琴卡片 + 焦点放大层 */
import { $, jget, jset } from './util.js';
import { LS } from './state.js';

export function persistOpen() {
  const o = {};
  document.querySelectorAll('.cell[data-key]').forEach((c) => { o[c.dataset.key] = c.classList.contains('open'); });
  jset(LS.open, o);
}

export function setCellOpen(key, on) {
  const cell = document.querySelector('.cell[data-key="' + key + '"]');
  if (!cell) return;
  cell.classList.toggle('open', !!on);
  const btn = cell.querySelector('.cell-h');
  if (btn) btn.setAttribute('aria-expanded', cell.classList.contains('open') ? 'true' : 'false');
}

export function openCell(key) {
  setCellOpen(key, true);
  persistOpen();
  const cell = document.querySelector('.cell[data-key="' + key + '"]');
  if (cell && !cell.classList.contains('is-focus')) {
    cell.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
}

/* 展开并放大到焦点层（仅用户主动点放大按钮时用） */
export function revealCard(key) {
  openCell(key);
  const el = document.querySelector('.cell[data-key="' + key + '"]');
  if (el) openFocus(el);
}

export function setDot(key, tone) {
  const d = document.querySelector('.cell-dot[data-dot="' + key + '"]');
  if (d) d.className = 'cell-dot' + (tone ? ' ' + tone : '');
}

function focusIcon(out) {
  return out
    ? '<svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M6 2H2v4M10 2h4v4M2 10v4h4M14 10v4h-4"/></svg>'
    : '<svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M2 6h4V2M14 6h-4V2M2 10h4v4M14 10h-4v4"/></svg>';
}

export function bindCells() {
  const saved = jget(LS.open);
  document.querySelectorAll('.cell[data-key]').forEach((c) => {
    const on = saved && typeof saved === 'object' ? !!saved[c.dataset.key] : false;
    c.classList.toggle('open', on);
    const btn = c.querySelector('.cell-h');
    if (btn) {
      btn.setAttribute('aria-expanded', on ? 'true' : 'false');
      btn.onclick = (e) => {
        if (e.target.closest('.focus-btn')) return;
        if (c.classList.contains('is-focus')) return;
        c.classList.toggle('open');
        btn.setAttribute('aria-expanded', c.classList.contains('open') ? 'true' : 'false');
        persistOpen();
      };
    }
  });
  bindFocusButtons();
}

function bindFocusButtons() {
  document.querySelectorAll('.cell, .hero').forEach((el) => {
    if (el.querySelector(':scope > .focus-btn')) return;
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'focus-btn';
    b.title = '放大到画面中心';
    b.setAttribute('aria-label', '放大到画面中心');
    b.innerHTML = focusIcon(true);
    b.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); toggleFocus(el); });
    b.addEventListener('mousedown', (e) => e.stopPropagation());
    if (el.classList.contains('hero')) el.appendChild(b);
    else el.appendChild(b);
  });
  const scrim = $('focusScrim');
  if (scrim && !scrim._bound) {
    scrim._bound = true;
    scrim.onclick = () => closeFocus();
  }
  if (!window._focusEsc) {
    window._focusEsc = true;
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeFocus(); });
  }
}

function toggleFocus(el) {
  if (el.classList.contains('is-focus')) closeFocus();
  else openFocus(el);
}

function openFocus(el) {
  if (!el) return;
  closeFocus(true);
  if (el.classList.contains('cell')) {
    el.classList.add('open');
    const hb = el.querySelector('.cell-h');
    if (hb) hb.setAttribute('aria-expanded', 'true');
    persistOpen();
  }
  const from = el.getBoundingClientRect();
  const ph = document.createElement('div');
  ph.className = el.classList.contains('hero') ? 'hero-ph' : 'cell-ph';
  ph.style.height = from.height + 'px';
  el.after(ph);
  el._ph = ph;
  document.body.appendChild(el);
  el.classList.add('is-focus');
  document.body.classList.add('has-focus');
  $('focusScrim').classList.add('show');
  const btn = el.querySelector('.focus-btn');
  if (btn) { btn.innerHTML = focusIcon(false); btn.title = '收回侧栏'; btn.setAttribute('aria-label', '收回侧栏'); }
  const to = el.getBoundingClientRect();
  const dx = from.left + from.width / 2 - (to.left + to.width / 2);
  const dy = from.top + from.height / 2 - (to.top + to.height / 2);
  const sx = Math.max(0.2, from.width / to.width);
  const sy = Math.max(0.2, from.height / to.height);
  el.animate(
    [{ transform: `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px)) scale(${sx},${sy})` }, { transform: 'translate(-50%,-50%) scale(1)' }],
    { duration: 380, easing: 'cubic-bezier(0.22, 1, 0.36, 1)' }
  );
}

function parkFocus(el) {
  if (el._ph && el._ph.parentNode) el._ph.replaceWith(el);
  el._ph = null;
  el.classList.remove('is-focus');
  document.body.classList.remove('has-focus');
  const s = $('focusScrim');
  if (s) s.classList.remove('show');
  const btn = el.querySelector('.focus-btn');
  if (btn) { btn.innerHTML = focusIcon(true); btn.title = '放大到画面中心'; btn.setAttribute('aria-label', '放大到画面中心'); }
}

export function closeFocus(instant) {
  const el = document.querySelector('.is-focus');
  if (!el) {
    document.body.classList.remove('has-focus');
    const s = $('focusScrim');
    if (s) s.classList.remove('show');
    return;
  }
  if (instant || !el._ph) { parkFocus(el); return; }
  const from = el.getBoundingClientRect();
  const ph = el._ph.getBoundingClientRect();
  const dx = ph.left + ph.width / 2 - (from.left + from.width / 2);
  const dy = ph.top + ph.height / 2 - (from.top + from.height / 2);
  const sx = Math.max(0.2, ph.width / from.width);
  const sy = Math.max(0.2, ph.height / from.height);
  const a = el.animate(
    [{ transform: 'translate(-50%,-50%) scale(1)' }, { transform: `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px)) scale(${sx},${sy})` }],
    { duration: 300, easing: 'cubic-bezier(0.22, 1, 0.36, 1)' }
  );
  a.onfinish = () => parkFocus(el);
}
