# Phase 6 release rehearsal

Status: complete
Evidence date: 2026-09-01
Rehearsed commit: `e998be3149e3198ed7ec2584589c8be46e11aff7`
Canonical branch: `codex/integrate-stock-v2`

This rehearsal validates the committed repository in a new Windows clone.
Owner rights, credential rotation and public-disclosure approval are recorded in
the machine-readable attestation. The candidate branch is pushed, its local and
remote SHA values match, and the exact-SHA remote CI run is green. The attested
candidate `b59affe` is an ancestor of this release-evidence follow-up commit.

## Clean-checkout correction

The first ordinary Windows clone exposed two release-only defects that the
source working tree did not show:

1. global `core.autocrlf=true` changed bytes covered by provenance/vendor
   SHA-256 records;
2. a clean test invocation did not guarantee that the `./tmp` parent existed.

Commit `32c7cf4` fixes both conditions:

- `.gitattributes` enforces LF checkout for text and marks common binary
  formats as binary;
- the donor-manifest regression requires all hash-controlled targets to remain
  LF byte streams;
- CI creates `./tmp` before passing `--basetemp ./tmp/pytest-ci`.

In the final `bbf48a0` rehearsal clone, Git reported `core.autocrlf=true` while
`integration/donor_migration_manifest.json`, `src/yeuxq/__init__.py`, and
`src/yeuxq/web/vendor/manifest.json` all remained `i/lf w/lf`.

## Passed evidence

| Check | Result |
| --- | --- |
| Locked clean install | PASS — `uv sync --locked --all-groups` |
| Clean targeted regression | PASS — 282 passed, 6 skipped |
| Ruff lint/format | PASS — repository lint and 96 integrated files formatted |
| Rust workspace | PASS — 3 passed |
| First-party JavaScript | PASS — 13 modules passed `node --check` |
| Secret scan | PASS — 652 candidate files checked |
| Wheel/sdist build | PASS — both archives built from the clean clone |
| Distribution compliance | PASS — 2 archives audited |
| Project license | PASS — Apache-2.0, copyright 2026 `zzzfu411`, root LICENSE/NOTICE and PEP 639 metadata packaged |
| License-focused acceptance | PASS — 53 tests and 654-candidate secret scan |
| Release operations runbook | PASS — one install/start/config/upgrade/rollback and donor-deprecation procedure |
| Canonical/donor boundary | PASS — executable preflight plus 5 focused tests; combined Phase 6 operations suite 57 passed and 657 candidates passed secret scan |
| Owner closeout contract | PASS — rights, both credential rotations and public disclosure confirmed by `zzzfu411`; no credential values recorded |
| Attested pre-push acceptance | PASS — 58 focused tests, 658-candidate secret scan, Ruff over 97 files, JSON/diff checks and 2 rebuilt archives audited |
| Wheel import/startup smoke | PASS — `quantify` and `yeuxq` import, bounded v1 app starts with an explicit writable `YEUXQ_DATA_DIR` |
| Source-checkout UI | PASS — desktop, mobile and integration status projections |
| Wheel UI | PASS — packaged assets render; source-only integration page fails closed |
| Full clean regression at `32c7cf4` | INVESTIGATED — 1313 passed, 6 skipped, 1 test-isolation failure |
| Isolated router correction | PASS — failing case passed alone; related router/status/CI/distribution suite passed 76 tests |
| Final full clean regression at `bbf48a0` | PASS — 1314 passed, 6 skipped, 1 tracked deprecation warning |
| Final local regression at `e998be3` | PASS — 1329 passed, 3 skipped, 1 tracked Starlette/httpx deprecation warning |
| Exact branch SHA | PASS — at candidate push verification, local `HEAD` and `origin/codex/integrate-stock-v2` both resolved to `e998be3149e3198ed7ec2584589c8be46e11aff7` |
| Exact-SHA GitHub Actions | PASS — run `33467767571`; Python/contracts/secrets/build and Rust/JavaScript jobs succeeded |
| Final status projection | PASS — `integration/integration_status.json` and `integration/index.html` project `7 / 7`, `100%`, `PASS` |
| Final evidence commit CI | PASS — `d794cc4ec4143b4b7b2ba7a1c23ed83323532586` and run `33469734584` passed the complete workflow |

The single full-suite failure was not a product-path regression. The test did
not provide `latest_import_report_path`, so its expected router result depended
on whether the checkout happened to contain the untracked workspace artifact
`results/import/recent/data_import.json`. A clean checkout correctly produced
`WATCH` under the existing data-intake-router contract, while the long-lived
working tree produced `BLOCK`. The test now supplies an explicitly missing path
inside `tmp_path` and asserts the contracted `WATCH` result. A new ordinary
Windows clone of commit `bbf48a0` then passed the isolated case and the complete
Python regression. Ruff, Rust, JavaScript, secret scanning, archive build and
distribution compliance also passed from that clone.

## Browser acceptance

The clean source checkout was served on loopback and inspected in a real
browser:

- desktop `1440x1000`: no horizontal overflow; zero console warnings/errors;
- mobile `390x844`: no horizontal overflow; research-only and no-broker
  boundaries remain visible;
- unavailable scan, morning brief, backtest, compare, order-flow, news,
  earnings and AI-image controls remain disabled;
- the integration page showed the then-current `6 / 7`, `86%`, `release`,
  Phase 6 `50%`, and `BLOCK` snapshot; that output is retained as historical
  pre-push evidence, not the final candidate status.

The wheel-installed app was started with a temporary explicit
`YEUXQ_DATA_DIR`. Its main workbench rendered the packaged JavaScript/CSS,
showed `RESEARCH ONLY` and `NO BROKER`, and had no horizontal overflow or
console warnings/errors. `/integration/` returned the intentional source-only
`503` JSON response rather than inventing packaged status evidence.

After recording the final `bbf48a0` clean-clone results, the source status page
was served again and inspected in the in-app browser. That historical snapshot
projected Phase 6 as `75% / IN PROGRESS`, full regression as `1314 passed / 0
failed`, secret scan as `652 candidate files`, and release readiness as `BLOCK`.
At the browser's 1280-pixel viewport, document width remained within the
viewport and no console warning or error was recorded. The final status source
was subsequently updated and rechecked at desktop `1440x1000` and mobile
`390x844`: it projects `7 / 7`, `100%`, `PASS`, with no horizontal overflow,
console errors or external requests.

GitHub CLI authentication was then rechecked outside the restricted execution
environment on 2026-08-31. The host keyring authenticated account `zzzfu411`,
the GitHub user API succeeded, and the active token reported the repository and
workflow scopes required by the planned push. Authentication is therefore no
longer a release blocker. The candidate branch push, remote SHA comparison and
exact-SHA GitHub Actions verification are now complete (run `33467767571`).

The repository owner selected Apache-2.0 and explicitly chose GitHub username
`zzzfu411` as the copyright holder. The complete Apache-2.0 text is stored in
the root `LICENSE`; `NOTICE` records `Copyright 2026 zzzfu411`; `pyproject.toml`
declares the SPDX expression and three license files. A rebuilt wheel and sdist
both passed the strengthened offline audit, and the wheel metadata includes the
Apache-2.0 expression plus `LICENSE`, `NOTICE`, and
`THIRD_PARTY_NOTICES.md`. Repository owner `zzzfu411` subsequently confirmed
ownership or sufficient redistribution and relicensing rights for the donor
source and migrated results in the release attestation.

Phase 6 now has one canonical operations runbook at
`docs/31_Release_Operations.md`. It covers source and wheel installation,
runtime configuration, immutable-environment upgrades, executable rollback,
release preflight and final publication. The donor manifest records `stock_v2`
as read-only migration evidence, prohibits feature changes, runtime dependency,
release use and new runtime data, and preserves the original directory without
allowing release automation to delete it. `scripts/check_release_boundary.py`
validates this contract, rejects canonical `stock_v2` imports and verifies the
owner attestation. Its focused suite passed five tests before the final
attestation update and the exact-SHA CI run passed the same boundary check.

A read-only GitHub audit on 2026-08-31 confirmed that `zzzfu411/yeuxQ` is
public, its default branch is `main`, and remote branch
`codex/integrate-stock-v2` was at `02471852469229c0744a51d7f2c186bbb6fa1da9`
while the verified local release-operations commit was
`bc9a6f2b0b2a9def28891f341ae02c3bc0b1e102`. The local branch was eight commits
ahead; no push occurred. Three legacy root-level pytest temp directories were
also found and are now covered by `tmp_pytest_*/` so they cannot enter Git
candidate enumeration or produce release-tool permission warnings.

Because the donor directory has no Git metadata, root license, pyproject author
or pyproject license metadata, local files alone could not establish
redistribution rights. Repository owner `zzzfu411` therefore completed
`integration/owner_release_attestation.json` at
`2026-08-31T22:41:07+08:00`, confirming ownership or sufficient redistribution
and relicensing rights, rotation of both donor-local credentials, and public
disclosure approval for candidate `b59affe` plus attestation/release-evidence
follow-ups. The record contains identities, timestamps, basis and candidate SHA
but no credential values. P0-01 and P0-03 are closed.

## Final closeout and non-blocking follow-ups

Phase 6 is complete for the verified candidate branch. At candidate push
verification, local `HEAD` and `origin/codex/integrate-stock-v2` both resolved
to `e998be3149e3198ed7ec2584589c8be46e11aff7`, and GitHub Actions run
`33467767571` passed that exact SHA across Python, contracts, secret scanning,
release-boundary, distribution, Rust and first-party JavaScript checks. The
final evidence commit `d794cc4ec4143b4b7b2ba7a1c23ed83323532586` was then
pushed and run `33469734584` passed the same complete workflow. The
machine-readable status and its static UI projection now show `7 / 7`, `100%`,
`PASS`.

The following are intentionally non-release-blocking follow-ups, not failed
closeout checks:

1. Complete the real-data boundary dictionary/fixtures for timezone, calendar,
   adjustment and suspension semantics (P1-02).
2. Finish the planned visible freshness, versioned API, artifact-denylist and
   capability-matrix re-audits before changing the corresponding P1 risks from
   `mitigated` to `closed` (P1-03, P1-06, P1-08, P1-09).
3. Do not merge `main` or publish a release tag without a separate instruction
   from the repository owner; the current PASS is candidate-branch readiness,
   not an authorization for live trading or investment use.
