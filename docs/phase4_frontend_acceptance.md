# Phase 4 frontend acceptance record

Date: 2026-08-30  
Branch: `codex/integrate-stock-v2`

Phase 4 closes the clean-room frontend and bounded advisory surface. The
application now renders observation, research-readiness and historical-report
states through the versioned read-only contracts, while unavailable generation,
scan, order-flow and AI actions remain disabled.

## Evidence

- `tests/yeuxq`: **266 passed, 3 skipped**.
- Full Python regression: **1305 passed, 3 skipped** in 1195.35 seconds.
- Secret scan: **723 candidate files checked, passed**; no credential values
  were copied into the repository.
- Rust workspace: **3 passed**.
- First-party browser JavaScript: all 10 top-level modules passed `node --check`.
- Distribution build: current wheel and sdist built with `uv build
  --no-sources`.
- Desktop browser acceptance at `1440x1000`: document/body width 1440,
  zero horizontal overflow, zero application console errors or warnings, zero
  off-screen controls, and only bounded `/api/v1/*` GET requests.
- Mobile browser acceptance at `390x844`: document/body width 390, zero
  horizontal overflow, zero off-screen controls, and all unavailable controls
  remained disabled.
- Controlled API-failure acceptance: injected `503` responses left the UI in
  `UNAVAILABLE`/`BLOCK`/`RESEARCH ONLY` state without displaying
  `DATA_AVAILABLE` or issuing mutation requests.

## Boundary decisions

The browser's native console reports a resource error when a test deliberately
forces an offline connection or a synthetic HTTP 503. Those entries are
transport diagnostics, not uncaught application exceptions. The normal service
session had zero console errors and warnings; the controlled failure session is
recorded separately so the fail-closed behavior is not confused with a runtime
crash.

Phase 5 starts immediately after this record. It owns parity, storage/recovery,
distribution-compliance and reverse-boundary tests; release remains `BLOCK`
until donor redistribution rights, credential rotation and project licensing
are resolved by the repository owner.
