# Phase 6 release rehearsal

Status: in progress
Evidence date: 2026-08-31
Rehearsed commit: `bbf48a0c380ad2d16017dbf0edf539370a676614`
Canonical branch: `codex/integrate-stock-v2`

This rehearsal validates the committed repository in a new Windows clone. It
does not grant donor redistribution rights, rotate owner credentials, choose a
project-wide license, or prove a GitHub push that has not occurred.

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
| Wheel import/startup smoke | PASS — `quantify` and `yeuxq` import, bounded v1 app starts with an explicit writable `YEUXQ_DATA_DIR` |
| Source-checkout UI | PASS — desktop, mobile and integration status projections |
| Wheel UI | PASS — packaged assets render; source-only integration page fails closed |
| Full clean regression at `32c7cf4` | INVESTIGATED — 1313 passed, 6 skipped, 1 test-isolation failure |
| Isolated router correction | PASS — failing case passed alone; related router/status/CI/distribution suite passed 76 tests |
| Final full clean regression at `bbf48a0` | PASS — 1314 passed, 6 skipped, 1 tracked deprecation warning |

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
  Phase 6 `50%`, and `BLOCK` snapshot; the checked-in status is advanced only
  as later evidence is committed.

The wheel-installed app was started with a temporary explicit
`YEUXQ_DATA_DIR`. Its main workbench rendered the packaged JavaScript/CSS,
showed `RESEARCH ONLY` and `NO BROKER`, and had no horizontal overflow or
console warnings/errors. `/integration/` returned the intentional source-only
`503` JSON response rather than inventing packaged status evidence.

After recording the final `bbf48a0` clean-clone results, the source status page
was served again and inspected in the in-app browser. It projected Phase 6 as
`75% / IN PROGRESS`, full regression as `1314 passed / 0 failed`, secret scan as
`652 candidate files`, and release readiness as `BLOCK`. At the browser's
1280-pixel viewport, document width remained within the viewport and no console
warning or error was recorded.

## Remaining blockers

Phase 6 remains in progress and public release remains `BLOCK` until all of the
following are resolved:

1. the owner confirms donor redistribution rights or the affected material is
   replaced by independently authorized clean-room work;
2. the owner rotates the two credentials detected only in donor-local config;
3. the owner selects a project-wide `LICENSE`;
4. GitHub authentication is repaired, the canonical branch is pushed, and the
   local/remote/UI commit SHA is verified.
