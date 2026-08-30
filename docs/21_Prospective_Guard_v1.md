# Prospective Guard v1

`guard_v1` is a frozen falsification protocol for
`liquidity_neutral_momentum_guard_price_volume`. It is not a selected strategy,
paper approval, profit claim, or live-trading authorization.

## Why a Prefix Fingerprint Exists

A genuinely prospective holdout is not available when the protocol is
registered. The registry therefore binds the canonical logical fingerprint of
all bars through `selection.end`. The actual packet points its execution config
at that same development cache, so holdout bars must not be appended there.
After the holdout, a guarded materialization rebuilds a new cache and recomputes
the frozen prefix; any change to a pre-holdout bar invalidates admission.

This only proves temporal identity. It does not repair missing source QA,
retained vendor files, PIT membership, benchmark provenance, or import lineage.
Those deterministic gates remain independent and fail closed.

## Freeze and Register

```powershell
.\.venv\Scripts\python.exe examples\run_prospective_trial_packet.py `
  --plan tmp\provider_probe_20260715\preregistered_guard_v1_plan.json `
  --base-config tmp\provider_probe_20260715\research_current_300_v2.yaml `
  --development-cache tmp\provider_probe_20260715\akshare_current_300_v2.db `
  --execution-cache tmp\provider_probe_20260715\akshare_current_300_v2.db `
  --trial-id guard-v1-20260716 `
  --candidate liquidity_neutral_momentum_guard_price_volume `
  --train-start 2024-06-03 --train-end 2025-06-30 `
  --selection-start 2025-07-01 --selection-end 2026-07-14 `
  --test-start 2026-07-17 --test-end 2026-10-16 `
  --output-dir results\prospective\guard_v1_20260716 `
  --append-registry `
  --registry results\trial_registry\research_trials.jsonl
```

The command refuses retroactive registration, writes the exact frozen YAML
configuration, and appends only a `prohibited_live_use=true` event. The current
AKShare/Sina cache remains development-only and promotion-ineligible even when
the protocol append succeeds.

Verify the retained plan, packet, config, code, pre-holdout data prefix, and
registry binding with:

```powershell
.\.venv\Scripts\python.exe examples\verify_prospective_trial_packet.py `
  --packet-dir evidence\trial_registry\guard-v1-20260716 `
  --registry evidence\trial_registry\research_trials.jsonl
```

Integrity `PASS` still leaves `execution_allowed=false` while source QA and the
market-evidence preflight are incomplete.

The packet field is an immutable registration-time snapshot. Do not rebuild or
edit the packet when later evidence arrives. Recompute dynamic admission with:

```powershell
.\.venv\Scripts\python.exe examples\run_prospective_trial_admission.py `
  --packet-dir evidence\trial_registry\guard-v1-20260716 `
  --registry evidence\trial_registry\research_trials.jsonl `
  --benchmark-csv data_exports\indices\csi800_total_return.csv `
  --benchmark-metadata data_exports\indices\csi800_total_return.metadata.json `
  --membership-csv data_exports\indices\csi800_pit_membership.csv `
  --membership-metadata data_exports\indices\csi800_pit_membership.metadata.json `
  --materialization-artifact results\prospective\guard_v1_20260716\terminal_materialization\prospective_execution_cache_materialization.json `
  --output-dir results\prospective\guard_v1_20260716\operational_status\admission
```

The admission gate uses the `Asia/Shanghai` market date, has no caller-supplied
clock override, and keeps terminal analysis blocked through `2026-10-16` even
if all collection evidence arrives earlier. See
`docs/22_Prospective_Trial_Admission.md` for the complete contract.

## Registered Development Diagnostic

After registration, the candidate was rerun only on data through `2026-07-14`
at CNY 100,000 starting capital. The output stayed `RESEARCH_ONLY/BLOCK`:

- Three walk-forward windows returned `+2.12%`, `+9.16%`, and `-3.29%`.
- Zero of two factor components passed; factor diagnostics stayed `WATCH`.
- The risk-off window returned `-3.29%` with Sharpe `-1.27`.
- The latest selection window rejected `56.00%` of orders.
- Annualized return was `11.83%`, leaving a `-21.53%` margin to the configured
  one-million capital path.

The retained artifacts are under
`evidence/trial_registry/guard-v1-20260716/development_diagnostics/`. They are
not terminal trial evidence and cannot authorize paper or live use.

## After Registration

- Do not change the emitted config, candidate code, factor code, boundaries,
  metrics, or stop conditions.
- Do not use bars dated `2026-07-15` or `2026-07-16` as holdout observations;
  the embargoed test starts on `2026-07-17`.
- Acquire reviewed source data, CSI 800 total-return data, and PIT membership
  separately. Their gates must PASS on their own evidence.
- Do not execute or inspect the frozen holdout until the configured end date.
- Retain finalized daily exports, if available, only through the sealed
  quarantine intake in `docs/23_Sealed_Holdout_Intake.md`; quarantine cannot
  upgrade source QA or write the execution cache.
- The frozen-universe AKShare collector in
  `docs/24_Prospective_Daily_Acquisition.md` may run only after its post-close
  preflight passes; it uses `persist=False` with no storage handle.
- Retain only real, reviewed, hash-bound exchange-calendar evidence under
  `data_exports/calendars/` and validate it under
  `docs/26_Reviewed_Exchange_Calendar.md`. Missing, partial, placeholder,
  malformed, or hash-mismatched evidence is not a market-closure record.
- Audit cross-day gaps with `docs/25_Prospective_Collection_Status.md`. Without
  reviewed evidence, weekdays remain conservative candidates. With a strict
  calendar PASS, only `is_open=1` dates require retained bars; `is_open=0`
  dates are recorded as `REVIEWED_MARKET_CLOSED`, never silently inferred.
- After `2026-10-16`, use the one-time new-cache protocol in
  `docs/28_Prospective_Execution_Cache_Materialization.md`; never patch or
  append to `tmp/provider_probe_20260715/akshare_current_300_v2.db`.
- A result event must be appended only after all required artifacts exist and
  must bind their SHA-256 values.
- Review the terminal evidence by exact `--trial-id`; a trial with more than one
  result event is automatically BLOCK so no reviewer can pick the best-looking
  replacement result.
