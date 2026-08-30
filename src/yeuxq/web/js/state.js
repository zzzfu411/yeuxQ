/* 全局状态 + 轻量事件总线（避免模块循环依赖） */
export const LS = {
  mode: 'tl_mode',
  watch: 'tl_watch',
  hist: 'tl_hist',
  last: 'tl_last',
  track: 'tl_track',
  open: 'tl_open_cells',
};

export const state = {
  symbol: '',
  view: 'day',        // day | week | minute
  period: 'day',
  range: 250,
  ind: 'macd',
  klines: [],
  viewKs: [],
  signal: null,
  chan: null,
  minute: null,
  quoteName: '',
  lastAction: {},
  engine: null,       // /api/analyze meta.engine
  flows: [],          // analyze 返回的主力净流入，供看图 context
};

const handlers = {};
export const bus = {
  on(evt, fn) { (handlers[evt] ??= []).push(fn); },
  emit(evt, ...args) { (handlers[evt] || []).forEach((f) => f(...args)); },
};
