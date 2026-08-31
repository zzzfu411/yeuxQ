from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_workflow_is_read_only_locked_and_covers_release_checks() -> None:
    assert WORKFLOW.is_file()
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "pull_request_target" not in source
    assert "${{ secrets." not in source
    assert not re.search(r"^\s+[a-z-]+:\s*write\s*$", source, re.MULTILINE)
    assert "permissions:\n  contents: read" in source
    assert source.count("persist-credentials: false") == 2
    assert source.count("timeout-minutes:") == 2

    required_actions = (
        "actions/checkout@v7",
        "actions/setup-python@v7",
        "astral-sh/setup-uv@v10.0.1",
        "dtolnay/rust-toolchain@stable",
        "Swatinem/rust-cache@v2",
        "actions/setup-node@v7",
    )
    for action in required_actions:
        assert action in source

    required_commands = (
        "uv sync --locked --all-groups",
        "uv run ruff check .",
        "uv run ruff format --check src/yeuxq tests/yeuxq scripts",
        "uv run python scripts/check_secrets.py --root .",
        "uv run python scripts/check_release_boundary.py",
        "mkdir -p ./tmp",
        "uv run pytest tests -q",
        "--basetemp ./tmp/pytest-ci",
        "-p no:cacheprovider",
        "uv build --no-sources --out-dir dist-ci",
        "uv run python scripts/check_distribution.py dist-ci/*.whl dist-ci/*.tar.gz",
        "cargo test --workspace --locked",
        "node --check",
    )
    for command in required_commands:
        assert command in source
