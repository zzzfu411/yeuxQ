/* 同源 API 封装，支持 AbortSignal */
export async function getJSON(path, { signal } = {}) {
  const r = await fetch(path, { signal });
  return r.json();
}
export async function postJSON(path, body, { signal } = {}) {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
    signal,
  });
  return r.json();
}
