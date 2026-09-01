# yeuxQ release operations

This is the single installation, startup, configuration, upgrade, rollback and
donor-deprecation runbook for the canonical `zzzfu411/yeuxQ` release source.
Commands are written for PowerShell from the repository root unless noted.

The application is research-only and advisory-only. These procedures do not
enable broker access, account access, live orders or automatic trading.

## Release preflight

Use a clean checkout at the exact candidate commit. Do not build a public
release from `D:\Develop\grok\stock` or from generated/runtime directories.

```powershell
uv sync --locked --all-groups
uv run ruff check .
uv run ruff format --check src/yeuxq tests/yeuxq scripts
uv run python scripts/check_secrets.py --root .
uv run python scripts/check_release_boundary.py
New-Item -ItemType Directory -Force -Path .\tmp | Out-Null
uv run pytest tests -q --basetemp .\tmp\pytest-release -p no:cacheprovider
cargo test --workspace --locked
Get-ChildItem src\yeuxq\web\js -Filter *.js | ForEach-Object { node --check $_.FullName }
uv build --no-sources --out-dir dist-release
uv run python scripts/check_distribution.py `
  dist-release\quantify-0.1.0-py3-none-any.whl `
  dist-release\quantify-0.1.0.tar.gz
```

Stop if any check fails. A passing technical preflight does not override the
machine-readable `release_readiness=BLOCK` state or any unresolved owner action.

## Install from a source checkout

```powershell
git clone https://github.com/zzzfu411/yeuxQ.git yeuxQ
Set-Location yeuxQ
git checkout <RELEASE_TAG_OR_SHA>
uv sync --locked --all-groups
$env:YEUXQ_DATA_DIR = "$env:LOCALAPPDATA\yeuxQ"
uv run yeuxq
```

Keep the checkout and runtime data in separate directories. Never copy the
donor's local configuration, databases, reports, output, browser state or build
artifacts into the canonical checkout.

## Install from a wheel

```powershell
py -3.11 -m venv .venv-release
.\.venv-release\Scripts\python.exe -m pip install `
  .\dist-release\quantify-0.1.0-py3-none-any.whl
$env:YEUXQ_DATA_DIR = "$env:LOCALAPPDATA\yeuxQ"
.\.venv-release\Scripts\yeuxq.exe
```

The wheel contains both `quantify` and `yeuxq`. Rust remains a development-only,
explicit opt-in and is not included in the Python wheel.

## Runtime configuration

- Default bind: loopback only.
- Writable state: set `YEUXQ_DATA_DIR` to an absolute, owner-controlled path.
- Network mode: requires the existing host allowlist, access-token and TLS
  security contract; do not store secrets in tracked YAML or JSON.
- Provider credentials: inject through environment variables or an external
  secret manager only.
- Public configuration: start from `config/yeuxq.default.yaml`; never reuse
  donor-local `config/intel.local.yaml`.

Before startup, back up only the runtime data root—not the source checkout:

```powershell
Copy-Item -Recurse -LiteralPath $env:YEUXQ_DATA_DIR `
  -Destination "$env:YEUXQ_DATA_DIR.backup-<UTC_TIMESTAMP>"
```

## Upgrade

1. Stop the running yeuxQ process.
2. Record the current commit/tag and installed wheel filename.
3. Back up `YEUXQ_DATA_DIR` to a new timestamped directory.
4. Create a new checkout or virtual environment; do not upgrade the active
   environment in place.
5. Run the complete release preflight against the new commit.
6. Start the new version on loopback and verify `/`, `/docs`,
   `/api/v1/integration/status` and `/integration/`.
7. Switch the operator shortcut/service only after the smoke test passes.

Source-checkout upgrade example:

```powershell
git fetch --tags origin
git switch --detach <NEW_RELEASE_TAG_OR_SHA>
uv sync --locked --all-groups
uv run python scripts/check_release_boundary.py
uv run pytest tests/yeuxq -q -p no:cacheprovider
```

## Rollback

Rollback changes the executable version first. Restore runtime data only when a
documented data migration made the current data unreadable; never overwrite the
only data copy.

```powershell
# Source checkout rollback
git switch --detach <PREVIOUS_RELEASE_TAG_OR_SHA>
uv sync --locked --all-groups
uv run python scripts/check_release_boundary.py
uv run pytest tests/yeuxq -q -p no:cacheprovider

# Wheel rollback in a fresh environment
py -3.11 -m venv .venv-rollback
.\.venv-rollback\Scripts\python.exe -m pip install `
  .\release-cache\quantify-<PREVIOUS_VERSION>-py3-none-any.whl
```

Start rollback candidates on loopback with the same external
`YEUXQ_DATA_DIR`, confirm hash-chain and report reads, and switch traffic only
after smoke verification. Retain the failed release checkout and logs for audit.

## Donor deprecation

`D:\Develop\grok\stock` is migration evidence only:

- it is never an install, build, package, tag or release source;
- it accepts no new yeuxQ feature work or runtime data from this project;
- canonical runtime code must not import `stock_v2`;
- the original donor directory is preserved and is not deleted by release
  automation;
- any filesystem archival/read-only change remains owner-managed;
- repository owner `zzzfu411` confirmed sufficient redistribution and
  relicensing rights and rotation of both donor-local credentials on
  2026-08-31 in the machine-readable owner attestation.

The authoritative lifecycle fields are in
`integration/donor_migration_manifest.json`. CI executes
`scripts/check_release_boundary.py`, which verifies that the donor cannot become
a runtime dependency or release source and that the completed owner attestation
is consistent with the release-risk state.

Owner closeout is recorded in
`integration/owner_release_attestation.json`. Its status is `complete`; it
records the confirming GitHub username, timestamps, rights basis and approved
candidate commit. The credential section records only the required rotation
count and confirmation—never token or secret values.

## Final publication

Before pushing a release candidate or merging to `main`, the repository owner
must record:

1. donor redistribution-rights confirmation or clean-room replacement evidence;
2. rotation of both donor-local credentials without exposing their values;
3. explicit approval for public disclosure of the exact candidate SHA.

These three owner confirmations were recorded on 2026-08-31 for candidate
`b59affe` and its attestation/release-evidence follow-ups. The approved
follow-up candidate `e998be3149e3198ed7ec2584589c8be46e11aff7` is pushed on
`codex/integrate-stock-v2`; local and remote SHAs match, and GitHub Actions run
`33467767571` passed for that exact SHA. The final status evidence is recorded
in `integration/integration_status.json`. Do not merge `main` without a
separate owner instruction.
