/* 右栏渲染：Hero 判断卡 + 决策/结构各栏 */
import { state, LS } from './state.js';
import { $, jget, jset, setTxt, clip, cls, tone, esc } from './util.js';
import { setDot } from './cells.js';

const RING_LEN = 226.2; // 2πr, r=36

export function renderQuote(q) {
  if (!q) {
    $('quoteBar').innerHTML = `<div class="qh-left"><div class="qh-name">—</div><div class="qh-code">输入代码研判</div></div><div class="qh-px"><div class="px">—</div><div class="chg">—</div></div>`;
    return;
  }
  const up = (q.pct || 0) >= 0;
  const c = up ? 'up' : 'dn';
  const sign = up ? '+' : '';
  $('quoteBar').innerHTML = `<div class="qh-left">
      <div class="qh-name">${esc(q.name) || '—'}</div>
      <div class="qh-code">${esc(q.code) || state.symbol || ''} · 换手 ${q.turnover || 0}%</div>
    </div>
    <div class="qh-px">
      <div class="px ${c}">${q.price}</div>
      <div class="chg ${c}">${sign}${q.pct}%</div>
    </div>`;
}

export function renderEngineTag(engine) {
  state.engine = engine || null;
  const el = $('engineTag');
  if (!el) return;
  if (!engine) { el.innerHTML = ''; return; }
  if (engine.available) {
    el.innerHTML = `<span class="dot ok"></span>Rust · ${esc(engine.mode || '')}`;
    el.title = '信号引擎：Rust 计算核（' + (engine.mode || '') + '）';
  } else {
    el.innerHTML = `<span class="dot warn"></span>Python 回退`;
    el.title = '未找到 Rust 计算核，当前为 Python 回退：对称卖出 / ATR 仓位等规则不生效';
  }
}

function engineBanner(engine) {
  if (engine && engine.available === false) {
    return `<div class="hero-warn" style="display:block">引擎降级：Rust 核不可用，当前为 Python 回退，对称卖出 / ATR 仓位规则未生效。</div>`;
  }
  return '';
}

export function renderAll(sig, pred, ch, meta) {
  const t = tone(sig.action);
  const badge = $('sumBadge');
  badge.className = 'badge ' + t;
  badge.textContent = sig.action || '观望';
  const sc = $('sumScore');
  sc.className = cls(sig.action);
  sc.textContent = sig.score ?? '—';
  const ring = $('ringVal');
  if (ring) {
    const v = Math.max(0, Math.min(100, sig.score || 0));
    ring.style.strokeDashoffset = String(RING_LEN * (1 - v / 100));
    ring.style.stroke = t === 'buy' ? 'var(--up)' : t === 'sell' ? 'var(--dn)' : 'var(--warn)';
  }
  $('sumLead').textContent = sig.plain_summary || '';
  const warnEl = $('sumWarn');
  const veto = sig.original_action && sig.original_action !== sig.action
    ? `优化 ${sig.original_action}→${sig.action} ${sig.veto_reason || ''}` : '';
  if (veto) {
    warnEl.style.display = 'block';
    warnEl.textContent = veto;
  } else {
    warnEl.style.display = 'none';
    warnEl.textContent = '';
  }
  const bannerHost = $('engineBanner');
  if (bannerHost) bannerHost.innerHTML = engineBanner(meta?.engine);
  $('sumFoot').textContent = `风险 ${sig.risk_level || '—'} · 强度 ${sig.signal_strength || '—'} · 置信 ${sig.confidence || '—'} · 非投资建议`;

  /* 操作计划 */
  const p = sig.trade_plan || {};
  $('planBody').innerHTML = `<div class="tri">
    <div><small>入手</small><b>${p.entry_price ?? '—'}</b></div>
    <div><small>止损</small><b class="dn">${p.stop_loss ?? '—'}</b></div>
    <div><small>目标</small><b class="up">${p.target_price ?? '—'}</b></div>
  </div>
  <div class="row"><span>仓位</span><b>${esc(sig.position_advice || p.position_size || '—')}</b></div>
  <div class="row"><span>盈亏比</span><b>${p.risk_reward_ratio ?? sig.risk_reward ?? '—'}</b></div>
  <div class="row"><span>周期</span><b>${esc(p.holding_period || '中线')}</b></div>
  <div class="disc">${esc(p.notes || '')}</div>`;
  setTxt('planPrev', `入手 ${p.entry_price ?? '—'} · 止损 ${p.stop_loss ?? '—'}`);
  setTxt('planChip', p.risk_reward_ratio ?? sig.risk_reward ?? '—');
  setDot('plan', sig.action?.includes('买') ? 'up' : sig.action?.includes('卖') ? 'dn' : '');

  /* 五维评分 */
  const ms = sig.module_scores || {};
  const keys = ['趋势', '动量质量', '突破', '量价', '形态'];
  $('modBody').innerHTML = keys.map((k) => {
    const v = ms[k] ?? 0;
    const lv = v >= 70 ? 'high' : v >= 55 ? '' : v >= 40 ? 'mid' : 'low';
    return `<div class="row"><span>${k}</span><b>${v}</b></div><div class="bar"><i class="${lv}" style="width:${v}%"></i></div>`;
  }).join('');
  let topK = '—', topV = -1;
  keys.forEach((k) => { const v = ms[k] ?? 0; if (v > topV) { topV = v; topK = k; } });
  setTxt('modPrev', keys.map((k) => `${k} ${ms[k] ?? 0}`).join(' · '));
  setTxt('modChip', topK === '—' ? '—' : `${topK} ${topV}`);
  setDot('mod', topV >= 70 ? 'up' : topV >= 55 ? 'acc' : '');

  /* 买卖信号 */
  const buys = sig.buy_signals || [], sells = sig.sell_signals || [];
  $('sigBody').innerHTML = [
    ...buys.map((s, i) => `<div class="sig-buy">${i < 2 ? '【核】' : ''} 买 ${esc(s)}</div>`),
    ...sells.map((s) => `<div class="sig-sell">卖 ${esc(s)}</div>`),
  ].join('') || '—';
  setTxt('sigPrev', buys[0] || sells[0] || '暂无信号');
  setTxt('sigChip', `买${buys.length} 卖${sells.length}`);
  setDot('sig', buys.length > sells.length ? 'up' : sells.length > buys.length ? 'dn' : '');

  /* 动量质量 */
  const m = sig.momentum || sig.canslim;
  $('momBody').innerHTML = m ? `<div class="plain"><b>白话</b> 评级 ${esc(m.grade)}（${m.total}分）。价量近似，不是完整财报 CAN SLIM。</div>
    <div class="pro"><div class="row"><span>C/A/N/S</span><b>${m.c_score}/${m.a_score}/${m.n_score}/${m.s_score}</b></div>
    <div class="row"><span>L/I/M</span><b>${m.l_score}/${m.i_score}/${m.m_score}</b></div></div>` : '—';
  setTxt('momPrev', m ? `评级 ${m.grade} · ${m.total}分` : '暂无');
  setTxt('momChip', m ? m.grade : '—');
  setDot('mom', m && (m.grade === 'A' || m.grade === 'B') ? 'up' : m && (m.m_score ?? 50) < 40 ? 'warn' : '');

  /* 倾向：未校准的规则倾向，不画成胜率 */
  if (pred) {
    const tilt = Math.max(0, Math.min(1, pred.tilt ?? pred.prob_up ?? 0.5));
    const idx = Math.round(tilt * 100);
    const drivers = (pred.drivers || []).slice(0, 6);
    $('predBody').innerHTML = `
      <div class="row"><span>方向</span><b>${esc(pred.direction || '中性')} · ${pred.horizon_days || 5} 日</b></div>
      <div class="tilt-meter"><span class="disc" style="margin:0">偏空</span>
        <div class="tilt-track"><i class="tilt-pin" style="left:${idx}%"></i></div>
        <span class="disc" style="margin:0">偏多</span>
      </div>
      <div class="row"><span>倾向指数</span><b>${idx}</b></div>
      ${drivers.length ? `<div class="drivers">${drivers.map((d) => `<span>${esc(d)}</span>`).join('')}</div>` : ''}
      <div class="disc">${esc(pred.disclaimer || '') || '规则倾向（sigmoid 映射），未做概率校准，不是历史胜率。'}</div>`;
    setTxt('predPrev', drivers[0] || '规则倾向 · 未校准');
    const chip = $('predChip');
    chip.textContent = pred.direction || '—';
    chip.className = 'cell-chip ' + (pred.direction === '看多' ? 'up' : pred.direction === '看空' ? 'dn' : '');
    setDot('pred', pred.direction === '看多' ? 'up' : pred.direction === '看空' ? 'dn' : '');
  }

  /* 关键价位 */
  const lv = sig.key_levels || {};
  const lvKeys = Object.keys(lv);
  $('lvlBody').innerHTML = lvKeys.map((k) => `<div class="row"><span>${esc(k)}</span><b>${lv[k]}</b></div>`).join('') || '—';
  setTxt('lvlPrev', lvKeys.length ? `${lvKeys[0]} ${lv[lvKeys[0]]}` : '暂无');
  setTxt('lvlChip', lvKeys.length ? String(lvKeys.length) : '—');

  renderChanlunDaily(ch);

  /* 风险 */
  const w = [...(sig.risk_warnings || []), ...(sig.risk_notes || [])];
  $('riskBody').innerHTML = w.length ? w.map((x) => `<div class="warn">· ${esc(x)}</div>`).join('') : '暂无';
  setTxt('riskPrev', w[0] || '暂无风险提示');
  setTxt('riskChip', w.length ? `${w.length}条` : '无');
  setDot('risk', w.length ? 'warn' : '');
}

export function renderChanlunDaily(ch) {
  if (!ch || ch.error) {
    $('clBody').textContent = '—';
    setTxt('clPrev', '暂无'); setTxt('clChip', '—');
    setDot('cl', '');
    return;
  }
  const sigs = ch.signals || [], zs = ch.zhongshus || [], px = ch.current_price;
  const cur = px != null ? zs.find((z) => px >= z.zd && px <= z.zg) : null;
  let html = `<div class="plain"><b>白话</b> ${esc(ch.summary || '暂无买卖点')}</div>`;
  if (cur) html += `<div class="zs">现价 ${px} 在中枢 [${cur.zd}–${cur.zg}] 内</div>`;
  html += sigs.map((s) => `<div class="${(s.type || '').startsWith('buy') ? 'sig-buy' : 'sig-sell'}">${esc(s.type_name)} ${esc(s.description || '')} <span class="disc">${esc(s.date || '')}</span></div>`).join('');
  html += `<div class="disc pro">${ch.fractal_count || 0}分型 / ${ch.stroke_count || 0}笔 / ${ch.zhongshu_count || 0}中枢</div>`;
  $('clBody').innerHTML = html;
  setTxt('clPrev', clip(ch.summary || '暂无买卖点', 22));
  setTxt('clChip', `${ch.zhongshu_count || 0}中枢`);
  setDot('cl', sigs.length ? 'acc' : '');
}

export function renderChanlunMinute(ch) {
  if (!ch) { $('clmBody').textContent = '—'; return; }
  $('clmBody').innerHTML = `<div class="plain"><b>白话</b> ${esc(ch.summary || '分时暂无信号')}</div>`
    + (ch.signals || []).map((s) => `<div>${esc(s.type_name || s.type)} ${esc(s.description || '')}</div>`).join('');
  setTxt('clmPrev', clip(ch.summary || '分时暂无信号', 22));
  setTxt('clmChip', `${(ch.signals || []).length}条`);
  setDot('clm', (ch.signals || []).length ? 'acc' : '');
}

/* 对照备忘：同一股票两次分析的价格/动作对照 */
export function updateTrack(code, q, sig) {
  const tr = jget(LS.track) || {};
  const prev = tr[code];
  let extra = '同一股票分析两次以上才有对照。';
  if (prev && prev.price && q && q.price) {
    const chg = (q.price - prev.price) / prev.price * 100;
    extra = `上次 ${prev.action}@${prev.price} → 现 ${q.price} (${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%)。`;
  }
  tr[code] = { action: sig.action, price: q && q.price, t: Date.now() };
  jset(LS.track, tr);
  $('trackBody').textContent = extra;
  setTxt('trackPrev', extra);
  setTxt('trackChip', prev ? '对照' : '—');
  setDot('track', prev ? 'acc' : '');
}
