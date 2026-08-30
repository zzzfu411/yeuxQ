/* AI 看图：保留本地预览与历史只读；远程生成在统一前端中显式禁用。 */
import { state } from './state.js';
import { $, setTxt, esc, md2html, toast } from './util.js';
import { getAdvisoryReport, listAdvisoryReports } from './api.js';
import { chart, flowChart } from './charts.js';
import { openCell, setDot } from './cells.js';
import { kindLabel, remainLabel } from './research.js';
import {
  renderToolTrace, bindToolTrace, agenticMetaBits, agenticBudgetHtml,
} from './trace.js';

export { renderToolTrace };

const SNAP_BG = '#0a0b0e';
const SNAP_GAP = '#262a33';
const DEFAULT_PREV = '历史看图报告只读；生成暂不可用';
const DEFAULT_META =
  'UNAVAILABLE：统一工作台只读展示已保存的看图报告，不会截取或上传当前图表。';

function hasSeriesData(inst) {
  try {
    const series = inst.getOption()?.series || [];
    return series.some((s) => Array.isArray(s?.data) && s.data.length > 0);
  } catch (e) {
    return false;
  }
}

function snapChart(inst) {
  try {
    if (!inst || !hasSeriesData(inst)) return '';
    return inst.getDataURL({ pixelRatio: 2, backgroundColor: SNAP_BG }) || '';
  } catch (e) {
    return '';
  }
}

function loadImage(src) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });
}

/** 主图在上、资金流在下，合成 JPEG dataURI；都失败则 "" */
export async function captureChartImage() {
  const mainUrl = snapChart(chart);
  const flowUrl = snapChart(flowChart);
  const urls = [mainUrl, flowUrl].filter(Boolean);
  if (!urls.length) return '';
  const imgs = [];
  for (const u of urls) {
    const img = await loadImage(u);
    if (img) imgs.push(img);
  }
  if (!imgs.length) return '';
  const w = Math.max(...imgs.map((i) => i.naturalWidth || i.width));
  const gap = imgs.length > 1 ? 1 : 0;
  const h = imgs.reduce((s, i) => s + (i.naturalHeight || i.height), 0) + gap;
  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = SNAP_BG;
  ctx.fillRect(0, 0, w, h);
  let y = 0;
  imgs.forEach((img, i) => {
    const iw = img.naturalWidth || img.width;
    const ih = img.naturalHeight || img.height;
    const x = Math.floor((w - iw) / 2);
    ctx.drawImage(img, x, y);
    y += ih;
    if (i < imgs.length - 1) {
      ctx.fillStyle = SNAP_GAP;
      ctx.fillRect(0, y, w, 1);
      y += 1;
    }
  });
  return canvas.toDataURL('image/jpeg', 0.85);
}

export function buildContext() {
  return {
    quote: { name: state.quoteName, code: state.symbol },
    signal: state.signal || null,
    prediction: state.signal?.prediction || null,
    flows: state.flows || [],
  };
}

function hhmm(d = new Date()) {
  return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
}

export function buildVisionMetaHtml(r, saved, ttl) {
  const newsTag = r.news_ok === true ? '资讯✓' : r.news_ok === false ? '资讯✗' : '无资讯';
  const visTag = r.vision ? '带图' : '纯数据(图未送达)';
  const bits = [esc(r.model || 'grok-4.6'), newsTag, ...agenticMetaBits(r), visTag];
  if (saved) bits.push('已存 ' + esc(saved));
  bits.push('保留 ' + esc(String(ttl != null ? ttl : 24)) + ' 小时');
  return bits.join(' · ') + agenticBudgetHtml(r);
}

function showVisionSuccess(r) {
  const ttl = r.ttl_hours || 24;
  const saved = r.report_id || '';
  if ($('visionMeta')) $('visionMeta').innerHTML = buildVisionMetaHtml(r, saved, ttl);
  const md = r.report_markdown || '';
  if ($('visionBody')) {
    $('visionBody').innerHTML = renderToolTrace(r) + (md ? `<div class="md">${md2html(md)}</div>` : '');
    bindToolTrace($('visionBody'));
  }
  const chip = extractVisionChip(md);
  setTxt('visionPrev', `看图 ${hhmm()} · ${r.vision ? '带图' : '纯数据'}`);
  setVisionChip(chip.label, chip.cls);
}

/* 自测 / 预览：把一份响应画到卡片上（不发请求） */
export function applyVisionResult(r) {
  openCell('vision');
  setDot('vision', 'acc');
  showVisionSuccess(r || {});
}

/* 从第一章节粗提取：出逃 / 流入 / 拉锯；提取不到则「已研判」 */
function extractVisionChip(md) {
  const text = String(md || '').replace(/\r/g, '');
  if (!text.trim()) return { label: '已研判', cls: '' };
  const hasH2 = /^##\s+/m.test(text);
  const parts = text.split(/^##\s+/m);
  const sec = parts.length >= 2 ? parts[1] : text.slice(0, 1200);
  if (sec.includes('出逃')) return { label: '出逃', cls: 'dn' }; // A 股绿 = .dn = 流出
  if (sec.includes('流入')) return { label: '流入', cls: 'up' };
  if (hasH2 || sec.includes('拉锯')) return { label: '拉锯', cls: '' };
  return { label: '已研判', cls: '' };
}

function setVisionChip(label, extraCls) {
  const el = $('visionChip');
  if (!el) return;
  el.textContent = label || '—';
  el.className = 'cell-chip' + (extraCls ? ' ' + extraCls : '');
}

function paintVisionHist(items, current) {
  const box = $('visionHist');
  if (!box) return;
  if (!items || !items.length) { box.innerHTML = ''; return; }
  box.innerHTML = items.slice(0, 12).map((it) =>
    `<button type="button" data-f="${esc(it.report_id)}" class="${it.report_id === current ? 'on' : ''}">${kindLabel(it.kind)} ${esc(it.stamp || '')}</button>`
  ).join('');
  box.querySelectorAll('button').forEach((b) => { b.onclick = () => openSavedVision(b.dataset.f); });
}

function paintVision(md, meta, items, current, extra) {
  if ($('visionMeta')) $('visionMeta').textContent = meta || '';
  if ($('visionBody')) {
    if (!md) {
      $('visionBody').innerHTML =
        '<div class="disc">没有可读的历史看图报告；统一工作台不提供生成或上传。</div>';
    } else {
      $('visionBody').innerHTML = renderToolTrace(extra) + `<div class="md">${md2html(md)}</div>`;
      bindToolTrace($('visionBody'));
    }
  }
  paintVisionHist(items, current);
}

async function openSavedVision(reportId) {
  if (!reportId) return;
  const symbol = state.symbol;
  try {
    const one = await getAdvisoryReport(reportId);
    if (symbol !== state.symbol) return;
    if (!one.ok) { toast(one.error || '读取失败'); return; }
    const list = await listAdvisoryReports(symbol, { limit: 12 });
    if (symbol !== state.symbol) return;
    const items = (list.items || []).filter((it) => it.kind === 'vision');
    const ttl = list.ttl_hours || one.ttl_hours || 24;
    const chip = extractVisionChip(one.markdown);
    paintVision(
      one.markdown,
      `已保存 · ${kindLabel(one.kind)} · ${one.stamp} · ${remainLabel(one.ttl_remain_sec, ttl)}`,
      items,
      one.report_id,
      one,
    );
    setTxt('visionPrev', `看图 ${one.stamp || ''}`.trim());
    setVisionChip(chip.label, chip.cls);
    openCell('vision');
  } catch (error) {
    if (symbol !== state.symbol) return;
    toast(error?.message || '读取失败');
  }
}

export async function loadSavedVision(symbol) {
  if (!symbol || !$('visionBody')) return;
  $('visionMeta').textContent = `${symbol} · 历史看图报告读取中…`;
  $('visionBody').textContent = '…';
  paintVisionHist([], '');
  setTxt('visionPrev', '历史看图报告读取中…');
  setVisionChip('—', '');
  setDot('vision', '');
  try {
    const r = await listAdvisoryReports(symbol, { limit: 12 });
    if (symbol !== state.symbol) return;
    const items = (r.items || []).filter((it) => it.kind === 'vision');
    const ttl = r.ttl_hours || 24;
    if (!items.length) {
      paintVision('', DEFAULT_META, [], '');
      setTxt('visionPrev', DEFAULT_PREV);
      setVisionChip('—', '');
      setDot('vision', '');
      return;
    }
    const last = items[0];
    const one = await getAdvisoryReport(last.report_id);
    if (symbol !== state.symbol) return;
    if (!one.ok) { paintVision('', one.error || '读取失败', items, ''); return; }
    const chip = extractVisionChip(one.markdown);
    paintVision(one.markdown, `已保存 · ${kindLabel(one.kind)} · ${one.stamp} · ${remainLabel(one.ttl_remain_sec, ttl)}`, items, one.report_id, one);
    setTxt('visionPrev', `看图 ${one.stamp || ''}`.trim());
    setVisionChip(chip.label, chip.cls);
    setDot('vision', 'acc');
  } catch (e) {
    if (symbol !== state.symbol) return;
    if (e.name !== 'AbortError') paintVision('', e.message, [], '');
  }
}

export async function runVision() {
  openCell('vision');
  setDot('vision', '');
  if ($('visionMeta')) {
    $('visionMeta').textContent = 'UNAVAILABLE · RESEARCH ONLY · 不会截取或上传图表';
  }
  if ($('visionBody')) {
    $('visionBody').textContent =
      'AI 看图生成暂不可用；本操作只更新界面，不会发起网络请求。';
  }
  setTxt('visionPrev', 'AI 看图生成暂不可用');
  setVisionChip('BLOCK', '');
}
