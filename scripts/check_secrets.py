"""Conservative secret scanner for files that could enter the repository.

The default file set is Git's tracked files plus non-ignored, untracked files.
Explicit files or directories can also be supplied, which is useful before a
file has reached that candidate set. Output deliberately never includes a
complete credential.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence


EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".cache",
        ".mypy_cache",
        ".playwright-cli",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".uv-cache",
        ".venv",
        "__pycache__",
        "build",
        "cache",
        "dist",
        "htmlcov",
        "node_modules",
        "output",
        "target",
        "venv",
    }
)


@dataclass(frozen=True)
class SecretPattern:
    rule_id: str
    expression: re.Pattern[str]


@dataclass(frozen=True)
class Finding:
    path: Path
    line_number: int
    rule_id: str
    redacted_line: str


class SecretScanError(RuntimeError):
    """Raised when a requested candidate cannot be enumerated or read safely."""


TOKEN_PATTERNS = (
    SecretPattern(
        "private-key",
        re.compile(r"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----"),
    ),
    SecretPattern(
        "github-token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{22,255})\b"),
    ),
    SecretPattern(
        "openai-api-key",
        re.compile(r"\bsk-(?:(?:proj|svcacct)-)?[A-Za-z0-9_-]{20,255}\b"),
    ),
    SecretPattern(
        "aws-access-key",
        re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    ),
    SecretPattern(
        "google-api-key",
        re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    ),
    SecretPattern(
        "slack-token",
        re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,255}\b"),
    ),
    SecretPattern(
        "stripe-live-secret",
        re.compile(r"\bsk_live_[0-9A-Za-z]{20,255}\b"),
    ),
)

ASSIGNMENT_PATTERN = re.compile(
    r"^\s*(?:export\s+)?"
    r"(?P<key>\"[^\"\r\n]+\"|'[^'\r\n]+'|[A-Za-z_][A-Za-z0-9_.-]*)"
    r"\s*[:=]\s*(?P<value>.*?)\s*$"
)
JSON_ASSIGNMENT_PATTERN = re.compile(
    r"(?P<key>\"[^\"\r\n]+\")\s*:\s*"
    r"(?P<value>\"(?:\\.|[^\"\\])*\"|[^,}\]\r\n]+)"
)
SENSITIVE_KEY_PARTS = frozenset(
    {
        "api_key",
        "apikey",
        "access_key",
        "access_token",
        "auth_token",
        "client_secret",
        "credential",
        "credentials",
        "password",
        "passwd",
        "private_key",
        "secret",
        "token",
    }
)
CONFIG_SUFFIXES = frozenset({".cfg", ".conf", ".ini", ".json", ".toml", ".yaml", ".yml"})
PLACEHOLDER_WORDS = frozenset(
    {
        "changeme",
        "dummy",
        "example",
        "fake",
        "none",
        "null",
        "placeholder",
        "redacted",
        "replace_me",
        "replace-this",
        "test",
        "todo",
        "your_api_key",
        "your_token",
    }
)


def _is_excluded(path: Path, root: Path | None = None) -> bool:
    try:
        parts = path.resolve().relative_to(root.resolve()).parts if root else path.parts
    except ValueError:
        parts = path.parts
    return any(part in EXCLUDED_DIRECTORY_NAMES for part in parts[:-1])


def _is_env_or_config(path: Path) -> bool:
    name = path.name.lower()
    return name == ".env" or name.startswith(".env.") or path.suffix.lower() in CONFIG_SUFFIXES


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_").replace(".", "_")
    return any(
        normalized == part or normalized.endswith(f"_{part}") for part in SENSITIVE_KEY_PARTS
    )


def _unquote(value: str) -> str:
    value = value.strip().rstrip(",")
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def _is_placeholder(value: str) -> bool:
    value = _unquote(value)
    lowered = value.lower()
    compact = re.sub(r"\s+", "_", lowered)
    if not value or compact in PLACEHOLDER_WORDS:
        return True
    if value.startswith(("${", "{{", "<")) and value.endswith(("}", "}}", ">")):
        return True
    if re.fullmatch(r"\$[A-Za-z_][A-Za-z0-9_]*", value):
        return True
    if any(marker in lowered for marker in ("replace with", "insert your", "set me", "not-set")):
        return True
    if lowered in {"true", "false", "yes", "no", "on", "off"}:
        return True
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", value):
        return True
    return len(value) < 6


def _credential_matches(path: Path, line: str) -> list[tuple[str, tuple[int, int]]]:
    if not _is_env_or_config(path):
        return []
    matches = (
        list(JSON_ASSIGNMENT_PATTERN.finditer(line))
        if path.suffix.lower() == ".json"
        else ([match] if (match := ASSIGNMENT_PATTERN.match(line)) is not None else [])
    )
    findings: list[tuple[str, tuple[int, int]]] = []
    for match in matches:
        key = _unquote(match.group("key"))
        if not _is_sensitive_key(key):
            continue
        raw_value = match.group("value")
        value_without_comment = raw_value.split(" #", 1)[0].strip().rstrip(",")
        if _is_placeholder(value_without_comment):
            continue
        start = match.start("value")
        findings.append(("credential-assignment", (start, start + len(value_without_comment))))
    return findings


def _redact(line: str, spans: Iterable[tuple[int, int]]) -> str:
    """Replace every detected span before a line can reach logs or test output."""
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    for start, end in reversed(merged):
        line = f"{line[:start]}[REDACTED]{line[end:]}"
    line = line.strip()
    return line if len(line) <= 180 else f"{line[:177]}..."


def scan_file(path: Path) -> list[Finding]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise SecretScanError(f"could not read candidate: {path}") from exc
    if b"\x00" in payload[:8192]:
        return []
    text = payload.decode("utf-8", errors="replace")
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        detected: list[tuple[str, tuple[int, int]]] = []
        for rule in TOKEN_PATTERNS:
            detected.extend(
                (rule.rule_id, match.span()) for match in rule.expression.finditer(line)
            )
        detected.extend(_credential_matches(path, line))
        if not detected:
            continue
        safe_line = _redact(line, (span for _, span in detected))
        findings.extend(
            Finding(
                path=path,
                line_number=line_number,
                rule_id=rule_id,
                redacted_line=safe_line,
            )
            for rule_id, _ in detected
        )
    return findings


def git_candidate_files(root: Path) -> list[Path]:
    """Return tracked and non-ignored untracked files, excluding generated trees."""
    command = [
        "git",
        "-C",
        str(root),
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
    ]
    completed = subprocess.run(command, check=False, capture_output=True)
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or f"git ls-files failed with exit code {completed.returncode}")
    paths = [root / os.fsdecode(item) for item in completed.stdout.split(b"\x00") if item]
    return sorted(
        {path for path in paths if not _is_excluded(path, root)},
        key=lambda item: item.as_posix(),
    )


def _walk_explicit(paths: Iterable[Path], root: Path) -> list[Path]:
    files: set[Path] = set()

    def fail_walk(error: OSError) -> None:
        raise SecretScanError(f"could not enumerate candidate tree: {error.filename or '[path]'}")

    for candidate in paths:
        candidate = candidate if candidate.is_absolute() else root / candidate
        if candidate.is_file() and not _is_excluded(candidate, root):
            files.add(candidate)
            continue
        if candidate.is_dir():
            for current, directory_names, file_names in os.walk(candidate, onerror=fail_walk):
                directory_names[:] = [
                    name for name in directory_names if name not in EXCLUDED_DIRECTORY_NAMES
                ]
                current_path = Path(current)
                files.update(current_path / name for name in file_names)
            continue
        raise SecretScanError(f"explicit candidate is missing or unsupported: {candidate}")
    return sorted(files, key=lambda item: item.as_posix())


def scan_paths(paths: Iterable[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        findings.extend(scan_file(path))
    return findings


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scan Git candidate files for high-confidence credentials without revealing them."
    )
    parser.add_argument("paths", nargs="*", type=Path, help="optional files or directories to scan")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    root = arguments.root.resolve()
    try:
        files = (
            _walk_explicit(arguments.paths, root) if arguments.paths else git_candidate_files(root)
        )
    except (RuntimeError, SecretScanError) as error:
        print(f"secret scan could not enumerate candidates: {error}", file=sys.stderr)
        return 2
    try:
        findings = scan_paths(files)
    except SecretScanError as error:
        print(f"secret scan could not complete: {error}", file=sys.stderr)
        return 2
    for finding in findings:
        print(
            f"{_display_path(finding.path, root)}:{finding.line_number}: "
            f"{finding.rule_id}: {finding.redacted_line}"
        )
    if findings:
        print(f"secret scan failed: {len(findings)} potential secret(s) found")
        return 1
    print(f"secret scan passed: {len(files)} candidate file(s) checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
