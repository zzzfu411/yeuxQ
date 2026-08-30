/* 未迁移的 donor 能力保持 fail-closed；这些导出不会发出网络请求。 */
import { $, setTxt } from './util.js';
import { openCell, setDot } from './cells.js';

function renderUnavailable(card, body, preview, capability) {
  openCell(card);
  setDot(card, '');
  const message = `UNAVAILABLE · ${capability} 尚未进入只读 advisory 合同；未发送请求。`;
  const bodyElement = $(body);
  if (bodyElement) bodyElement.textContent = message;
  setTxt(preview, 'UNAVAILABLE · research-only');
}

export async function loadOF() {
  renderUnavailable('of', 'ofBody', 'ofPrev', '大单与订单流');
}

export async function runBacktest() {
  renderUnavailable('bt', 'btBody', 'btPrev', 'donor 回测');
}

export async function runCompare() {
  renderUnavailable('bt', 'btBody', 'btPrev', 'donor 策略对照');
}
