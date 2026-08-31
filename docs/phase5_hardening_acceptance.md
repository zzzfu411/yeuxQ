# Phase 5 hardening acceptance

Status: completed
Applicable evidence date: 2026-08-30
Canonical branch: `codex/integrate-stock-v2`

Phase 5 hardens the integrated `yeuxQ` boundary without changing the canonical
research authority in `src/quantify`. Runtime observations, donor calculations,
LLM output and the advisory UI remain non-canonical and cannot promote a
research gate or invoke a broker.

## Acceptance summary

| Area | Result | Evidence |
| --- | --- | --- |
| Python/Rust deterministic fallback | PASS | `tests/yeuxq/test_phase5_parity_recovery.py` |
| Optional Rust parity | PASS/optional | Up/down fixtures with bounded tolerances; skipped when no project binary exists |
| Observation hash-chain recovery | PASS | Independent-copy recovery, tamper and partial-line tests |
| Observation → research boundary | PASS | Capture leaves canonical readiness and artifacts unchanged |
| Provider → observation → API → UI | PASS | `tests/yeuxq/test_phase5_end_to_end.py` |
| Full Python regression | PASS | 1316 passed, 3 skipped |
| Integrated namespace regression | PASS | 274 passed, 3 skipped |
| Rust workspace | PASS | 3 passed |
| First-party JavaScript syntax | PASS | 13 modules passed `node --check` |
| Secret scan | PASS | 649 candidate files checked |
| Wheel/sdist compliance | PASS | Complete Apache-2.0, MIT and MPL-2.0 texts; manifest hashes and forbidden-path audit |

## Commands and outputs

The following commands were run from the canonical checkout:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/yeuxq -q -p no:cacheprovider --basetemp .\tmp\pytest-phase5-yeuxq
# 274 passed, 3 skipped

.\.venv\Scripts\python.exe -m pytest tests -q --basetemp .\tmp\pytest-phase5-full -p no:cacheprovider
# 1316 passed, 3 skipped, 1 Starlette TestClient deprecation warning

.\.venv\Scripts\ruff.exe check src/yeuxq tests/yeuxq scripts
.\.venv\Scripts\ruff.exe format --check src/yeuxq tests/yeuxq scripts
# all checks passed; 96 files already formatted

cargo test --workspace --locked
# 3 passed

Get-ChildItem src/yeuxq/web/js -Filter '*.js' | ForEach-Object { node --check $_.FullName }
# 13 modules passed

.\.venv\Scripts\python.exe scripts/check_secrets.py --root .
# secret scan passed: 649 candidate file(s) checked

uv build --no-sources --out-dir dist-phase5
.\.venv\Scripts\python.exe scripts/check_distribution.py `
  dist-phase5/quantify-0.1.0-py3-none-any.whl `
  dist-phase5/quantify-0.1.0.tar.gz
# distribution compliance passed: 2 archive(s) checked
```

## Safety decisions retained

- `src/quantify/readiness` remains the only `PASS/WATCH/BLOCK` gate authority.
- `TrendObservation` remains `prohibited_live_use=true`,
  `broker_access=false`, and `live_trading_allowed=false`.
- A source checkout no longer trusts an unrelated `trendlab` executable found
  on `PATH`; an explicit project binary or explicit runtime opt-in is required.
- A corrupted or partial observation journal is never repaired in place. A
  recovery requires an independently retained complete copy that passes the
  full hash-chain verifier.
- Distribution checks never print archive contents or secret values. They only
  emit bounded policy findings.

## Remaining release blockers

Phase 5 closes engineering hardening items but does not grant external rights.
Release remains `BLOCK` until the repository owner resolves:

1. redistribution rights for donor-derived material, or replaces any such
   material with independently authorized clean-room implementations;
2. rotation of the two credentials found in the donor's local configuration;
3. selection and addition of a project-wide `LICENSE`.

Phase 6 release rehearsal is therefore active but cannot be marked complete.
