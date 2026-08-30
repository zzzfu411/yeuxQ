/* Bounded, same-origin yeuxQ v1 client. No credential or arbitrary URL support. */
const V1 = '/api/v1';
const MAX_RESPONSE_BYTES = 1024 * 1024;
const SAFE_OBSERVATION_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;
const SAFE_RUN_ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/;
const SAFE_SYMBOL = /^\d{6}(?:\.(?:SH|SZ|BJ))?$/;
const DECISIONS = new Set(['PASS', 'WATCH', 'BLOCK']);

export class V1UnavailableError extends Error {
  constructor(message, { code = 'UNAVAILABLE', status = 0, requestId = '' } = {}) {
    super(message);
    this.name = 'V1UnavailableError';
    this.code = code;
    this.status = status;
    this.requestId = requestId;
  }
}

function boundedInteger(value, fallback, min, max) {
  const parsed = Number(value ?? fallback);
  if (!Number.isInteger(parsed) || parsed < min || parsed > max) {
    throw new TypeError('value must be an integer between ' + min + ' and ' + max);
  }
  return parsed;
}

function requireSafeId(value, pattern, label) {
  const normalized = String(value || '').trim();
  if (!pattern.test(normalized)) {
    throw new TypeError(label + ' is outside the facade boundary');
  }
  return normalized;
}

function assertAdvisoryBoundary(value, response) {
  if (
    !value
    || value.prohibited_live_use !== true
    || value.broker_access !== false
    || value.live_trading_allowed !== false
  ) {
    throw new V1UnavailableError('bounded facade advisory contract is invalid', {
      code: 'SERVICE_CONTRACT_VIOLATION',
      status: response.status,
    });
  }
}

function assertSafeObservation(value) {
  if (
    !value
    || typeof value !== 'object'
    || !SAFE_OBSERVATION_ID.test(String(value.observation_id || ''))
    || typeof value.symbol !== 'string'
    || value.prohibited_live_use !== true
    || value.broker_access !== false
    || value.live_trading_allowed !== false
  ) {
    throw new V1UnavailableError('observation contract is invalid', {
      code: 'SERVICE_CONTRACT_VIOLATION',
    });
  }
  return value;
}

function assertReadiness(value) {
  if (
    !value
    || typeof value !== 'object'
    || !SAFE_RUN_ID.test(String(value.run_id || ''))
    || !DECISIONS.has(value.decision)
    || value.read_only !== true
    || value.broker_access !== false
    || value.live_trading_allowed !== false
  ) {
    throw new V1UnavailableError('canonical readiness contract is invalid', {
      code: 'SERVICE_CONTRACT_VIOLATION',
    });
  }
  return value;
}

async function v1(path, { method = 'GET', body, signal } = {}) {
  const options = {
    method,
    signal,
    cache: 'no-store',
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
  };
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(V1 + path, options);
  } catch (error) {
    if (error?.name === 'AbortError') throw error;
    throw new V1UnavailableError('bounded facade unavailable');
  }

  const declaredLength = Number(response.headers.get('content-length') || 0);
  if (Number.isFinite(declaredLength) && declaredLength > MAX_RESPONSE_BYTES) {
    throw new V1UnavailableError('bounded facade response exceeds the client boundary', {
      code: 'RESPONSE_TOO_LARGE',
      status: response.status,
    });
  }

  let envelope;
  try {
    envelope = await response.json();
  } catch (error) {
    throw new V1UnavailableError('bounded facade returned invalid JSON', {
      code: 'INVALID_RESPONSE',
      status: response.status,
    });
  }

  if (!envelope || typeof envelope !== 'object') {
    throw new V1UnavailableError('bounded facade returned an invalid envelope', {
      code: 'INVALID_RESPONSE',
      status: response.status,
    });
  }
  assertAdvisoryBoundary(envelope.advisory, response);

  if (!response.ok || !Object.hasOwn(envelope, 'data')) {
    throw new V1UnavailableError(
      envelope.error?.message || 'bounded facade unavailable',
      {
        code: envelope.error?.code || 'UNAVAILABLE',
        status: response.status,
        requestId: envelope.request_id || '',
      },
    );
  }
  return {
    data: envelope.data,
    advisory: envelope.advisory,
    requestId: envelope.request_id || '',
  };
}

export const getV1Health = ({ signal } = {}) =>
  v1('/health', { signal });

export const getV1IntegrationStatus = ({ signal } = {}) =>
  v1('/integration/status', { signal });

export async function listV1Observations({ limit = 50, offset = 0, signal } = {}) {
  const safeLimit = boundedInteger(limit, 50, 1, 100);
  const safeOffset = boundedInteger(offset, 0, 0, 10000);
  const result = await v1(
    '/observations?limit=' + safeLimit + '&offset=' + safeOffset,
    { signal },
  );
  if (!result.data || !Array.isArray(result.data.items)) {
    throw new V1UnavailableError('observation list contract is invalid', {
      code: 'SERVICE_CONTRACT_VIOLATION',
    });
  }
  result.data.items.forEach(assertSafeObservation);
  return result;
}

export async function getV1Observation(observationId, { signal } = {}) {
  const normalized = requireSafeId(
    observationId,
    SAFE_OBSERVATION_ID,
    'observation id',
  );
  const result = await v1(
    `/observations/${encodeURIComponent(normalized)}`,
    { signal },
  );
  assertSafeObservation(result.data);
  return result;
}

export async function captureLocalResearchObservation(
  symbol,
  period = 'day',
  { signal } = {},
) {
  const normalized = requireSafeId(symbol, SAFE_SYMBOL, 'symbol');
  if (!['day', 'week', 'month'].includes(period)) {
    throw new TypeError('period is outside the observation contract');
  }
  const result = await v1('/observations/capture', {
    method: 'POST',
    body: { symbol: normalized, period },
    signal,
  });
  assertSafeObservation(result.data);
  return result;
}

export async function listV1ResearchRuns({ limit = 50, signal } = {}) {
  const safeLimit = boundedInteger(limit, 50, 1, 100);
  const result = await v1('/research/runs?limit=' + safeLimit, { signal });
  if (
    !result.data
    || !Array.isArray(result.data.items)
    || result.data.items.some((item) => !SAFE_RUN_ID.test(String(item || '')))
  ) {
    throw new V1UnavailableError('research run list contract is invalid', {
      code: 'SERVICE_CONTRACT_VIOLATION',
    });
  }
  return result;
}

export async function getV1CanonicalReadiness(runId, { signal } = {}) {
  const normalized = requireSafeId(runId, SAFE_RUN_ID, 'run id');
  const result = await v1(
    `/research/readiness/${encodeURIComponent(normalized)}`,
    { signal },
  );
  assertReadiness(result.data);
  return result;
}

/* Versioned read-only advisory workbench. It cannot upgrade the canonical gate. */
const ADVISORY_V1 = V1 + '/advisory';
export const ADVISORY_V1_ROUTES = Object.freeze({
  SEARCH: '/instruments/search',
  WATCHLIST_QUOTES: '/watchlist/quotes',
  MARKET_OVERVIEW: '/market/overview',
  ANALYSIS: '/symbols/{symbol}/analysis',
  MINUTE: '/symbols/{symbol}/minute',
  REPORTS: '/reports',
  REPORT: '/reports/{report_id}',
});

const SAFE_ADVISORY_SYMBOL = /^\d{6}$/;
const SAFE_REPORT_SUBJECT = /^(?:\d{6}|WATCH)$/;
const SAFE_REPORT_ID = /^(?:\d{6}(?:\.(?:SH|SZ|BJ))?|WATCH)_(?:news|report|earnings|brief|vision)_\d{8}T\d{12}Z_[0-9a-f]{12}\.md$/;

export class AdvisoryUnavailableError extends Error {
  constructor(message, { code = 'ADVISORY_UNAVAILABLE', status = 0, requestId = '' } = {}) {
    super(message);
    this.name = 'AdvisoryUnavailableError';
    this.code = code;
    this.status = status;
    this.requestId = requestId;
  }
}

function advisoryQuery(entries) {
  const query = new URLSearchParams();
  entries.forEach(([key, value]) => query.append(key, String(value)));
  const encoded = query.toString();
  return encoded ? '?' + encoded : '';
}

function assertAdvisoryProjection(value, response) {
  if (
    !value
    || typeof value !== 'object'
    || !['AVAILABLE', 'DEGRADED', 'UNAVAILABLE'].includes(value.availability)
    || !['FRESH', 'STALE', 'UNKNOWN'].includes(value.freshness)
    || !value.provenance
    || typeof value.provenance !== 'object'
    || value.canonical !== false
    || value.can_upgrade_gate !== false
  ) {
    throw new AdvisoryUnavailableError('advisory evidence contract is invalid', {
      code: 'SERVICE_CONTRACT_VIOLATION',
      status: response.status,
    });
  }
}

async function advisoryV1(path, { signal } = {}) {
  let response;
  try {
    response = await fetch(ADVISORY_V1 + path, {
      method: 'GET',
      signal,
      cache: 'no-store',
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    });
  } catch (error) {
    if (error?.name === 'AbortError') throw error;
    throw new AdvisoryUnavailableError('advisory workbench unavailable');
  }
  const contentType = response.headers.get('content-type') || '';
  if (!contentType.toLowerCase().includes('application/json')) {
    throw new AdvisoryUnavailableError('advisory workbench returned non-JSON data', {
      code: 'INVALID_CONTENT_TYPE',
      status: response.status,
    });
  }
  let envelope;
  try {
    envelope = await response.json();
  } catch (error) {
    throw new AdvisoryUnavailableError('advisory workbench returned invalid JSON', {
      code: 'INVALID_RESPONSE',
      status: response.status,
    });
  }
  if (!envelope || typeof envelope !== 'object') {
    throw new AdvisoryUnavailableError('advisory workbench returned an invalid envelope', {
      code: 'INVALID_RESPONSE',
      status: response.status,
    });
  }
  assertAdvisoryBoundary(envelope.advisory, response);
  if (!response.ok || !Object.hasOwn(envelope, 'data')) {
    throw new AdvisoryUnavailableError(
      envelope.error?.message || 'advisory workbench unavailable',
      {
        code: envelope.error?.code || 'ADVISORY_UNAVAILABLE',
        status: response.status,
        requestId: envelope.request_id || '',
      },
    );
  }
  assertAdvisoryProjection(envelope.data, response);
  if (envelope.data.availability === 'UNAVAILABLE') {
    throw new AdvisoryUnavailableError('advisory data is unavailable', {
      code: 'DATA_UNAVAILABLE',
      status: response.status,
      requestId: envelope.request_id || '',
    });
  }
  const payload = envelope.data.payload;
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new AdvisoryUnavailableError('advisory payload contract is invalid', {
      code: 'SERVICE_CONTRACT_VIOLATION',
      status: response.status,
      requestId: envelope.request_id || '',
    });
  }
  return { ...payload, _evidence: envelope.data };
}

function advisorySymbol(value) {
  return requireSafeId(value, SAFE_ADVISORY_SYMBOL, 'symbol');
}

export const getAdvisoryAnalysis = (symbol, period = 'day', { signal } = {}) => {
  const normalized = advisorySymbol(symbol);
  if (!['day', 'week'].includes(period)) throw new TypeError('period is outside the advisory contract');
  const path = ADVISORY_V1_ROUTES.ANALYSIS.replace('{symbol}', encodeURIComponent(normalized));
  return advisoryV1(path + advisoryQuery([['period', period]]), { signal });
};

export const getAdvisoryMinute = (symbol, { signal } = {}) => {
  const path = ADVISORY_V1_ROUTES.MINUTE.replace(
    '{symbol}',
    encodeURIComponent(advisorySymbol(symbol)),
  );
  return advisoryV1(path, { signal });
};

export const searchAdvisoryInstruments = (keyword, { limit = 10, signal } = {}) => {
  const normalized = String(keyword || '').trim();
  if (!normalized || normalized.length > 64) {
    throw new TypeError('keyword is outside the advisory contract');
  }
  const safeLimit = boundedInteger(limit, 10, 1, 20);
  return advisoryV1(
    ADVISORY_V1_ROUTES.SEARCH + advisoryQuery([
      ['keyword', normalized],
      ['limit', safeLimit],
    ]),
    { signal },
  );
};

export const getAdvisoryWatchlistQuotes = (symbols, { signal } = {}) => {
  if (!Array.isArray(symbols) || !symbols.length || symbols.length > 12) {
    throw new TypeError('watchlist is outside the advisory contract');
  }
  const entries = symbols.map((symbol) => ['symbols', advisorySymbol(symbol)]);
  return advisoryV1(
    ADVISORY_V1_ROUTES.WATCHLIST_QUOTES + advisoryQuery(entries),
    { signal },
  );
};

export const getAdvisoryMarketOverview = ({ signal } = {}) =>
  advisoryV1(ADVISORY_V1_ROUTES.MARKET_OVERVIEW, { signal });

export const listAdvisoryReports = (subject, { limit = 30, signal } = {}) => {
  const normalized = requireSafeId(subject, SAFE_REPORT_SUBJECT, 'report subject');
  const safeLimit = boundedInteger(limit, 30, 1, 80);
  return advisoryV1(
    ADVISORY_V1_ROUTES.REPORTS + advisoryQuery([
      ['subject', normalized],
      ['limit', safeLimit],
    ]),
    { signal },
  );
};

export const getAdvisoryReport = (reportId, { signal } = {}) => {
  const normalized = requireSafeId(reportId, SAFE_REPORT_ID, 'report id');
  const path = ADVISORY_V1_ROUTES.REPORT.replace(
    '{report_id}',
    encodeURIComponent(normalized),
  );
  return advisoryV1(path, { signal });
};
