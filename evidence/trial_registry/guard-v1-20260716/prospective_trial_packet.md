# Prospective Trial Packet: FROZEN_RESEARCH_ONLY

- Packet: `guard_v1`
- Trial: `guard-v1-20260716`
- Candidate: `liquidity_neutral_momentum_guard_price_volume`
- Created at UTC: `2026-07-15T19:10:01+00:00`
- Development cutoff: `2026-07-14`
- Packet SHA-256: `b33e834ef03feeac10b4427015c48952a293adedff7fcf38abe565d73682f2a9`
- Parameter fingerprint: `d57d8ee8b2d76d45782dd0473dfe862b61a750047eeabaa4f71f09ec23892b5d`
- Protocol fingerprint: `b8f93274dc8fabe2d7123adc2ef7053b3209779e4cf14c76982c639260dd4eae`
- Config fingerprint: `925a335e2a4a4b96e5c852a20bc9fd5f86e4b05e404cb297c8a1569df60d0fe7`
- Development prefix fingerprint: `af9b9346ddcfe6f43046e677c80a509772a39e9149c1df6e734aa8f77f76c48d`
- Registry append allowed: `True`
- Experiment execution allowed: `False`

## Frozen Boundaries

- train: `2024-06-03` to `2025-06-30`
- selection: `2025-07-01` to `2026-07-14`
- test: `2026-07-17` to `2026-10-16`

## Missing Evidence

- Promotion-safe source QA and import lineage are not PASS: Cache has no data_import_batches provenance table.
- PASS market_evidence_preflight.json for CSI 800 total return and PIT membership.

## Blockers

- None.

## Stop Conditions

- Any source-QA, PIT-universe, dataset-identity, or benchmark provenance gate is BLOCK
- Trial-corrected primary metric fails
- Fresh-holdout maximum drawdown exceeds 20%
- The 100000 CNY portfolio cannot execute under lot and minimum-commission constraints
- A rule or parameter is changed after the holdout is opened

## Prohibited Actions

- Do not use observations dated before test_start as prospective holdout evidence.
- Do not change candidate code, parameters, boundaries, metrics, or stop rules after registration.
- Do not treat this packet or registry append as data provenance, benchmark, strategy, or promotion PASS.
- Do not enter paper or micro-live readiness while any deterministic evidence gate is BLOCK.
- Do not generate or submit real broker orders from this workflow.

This artifact freezes a falsification protocol only. It is not a profit claim, data approval, paper approval, or live-trading authorization.
