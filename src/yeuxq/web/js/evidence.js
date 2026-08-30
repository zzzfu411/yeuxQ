/* Canonical evidence projection. Unknown or invalid input always fails closed. */

const DAY_MS = 24 * 60 * 60 * 1000;
const GATE_RANK = Object.freeze({ PASS: 0, WATCH: 1, BLOCK: 2 });
const FRESHNESS_RANK = Object.freeze({ FRESH: 0, UNKNOWN: 1, STALE: 2 });

function timestampMs(value) {
  if (!value) return null;
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : null;
}

export function timestampFreshness(value, { maxAgeMs = DAY_MS, nowMs = Date.now() } = {}) {
  const parsed = timestampMs(value);
  if (parsed == null || !Number.isFinite(nowMs) || parsed > nowMs) return 'UNKNOWN';
  return nowMs - parsed <= maxAgeMs ? 'FRESH' : 'STALE';
}

export function observationFreshness(value, { nowMs = Date.now() } = {}) {
  const eventTime = timestampMs(value?.event_time);
  const receivedAt = timestampMs(value?.received_at);
  const staleAfter = timestampMs(value?.stale_after);
  if (
    eventTime == null
    || receivedAt == null
    || staleAfter == null
    || !Number.isFinite(nowMs)
    || eventTime > nowMs
    || receivedAt > nowMs
    || receivedAt < eventTime
    || staleAfter <= receivedAt
  ) return 'UNKNOWN';
  return nowMs < staleAfter ? 'FRESH' : 'STALE';
}

export function aggregateGate(integration, readiness, errors = {}) {
  if (
    errors.integration
    || errors.readiness
    || integration?.valid !== true
    || !(integration.release_readiness in GATE_RANK)
    || !(readiness?.decision in GATE_RANK)
  ) return 'BLOCK';
  return GATE_RANK[integration.release_readiness] >= GATE_RANK[readiness.decision]
    ? integration.release_readiness
    : readiness.decision;
}

export function aggregateFreshness(values) {
  const normalized = (values || []).filter((value) => value in FRESHNESS_RANK);
  if (!normalized.length) return 'UNKNOWN';
  return normalized.reduce((worst, value) => (
    FRESHNESS_RANK[value] > FRESHNESS_RANK[worst] ? value : worst
  ), 'FRESH');
}
