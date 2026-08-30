from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from scripts.check_secrets import SecretScanError, git_candidate_files, main, scan_file


def test_detects_high_confidence_token_and_redacts_it(tmp_path: Path, capsys) -> None:
    secret = "github" + "_pat_" + "A" * 24
    candidate = tmp_path / "notes.txt"
    candidate.write_text(f"release_token={secret}\n", encoding="utf-8")

    findings = scan_file(candidate)

    assert [finding.rule_id for finding in findings] == ["github-token"]
    assert findings[0].redacted_line == "release_token=[REDACTED]"
    assert secret not in findings[0].redacted_line
    assert main([str(candidate), "--root", str(tmp_path)]) == 1
    output = capsys.readouterr().out
    assert secret not in output
    assert "[REDACTED]" in output


def test_yaml_and_env_assignments_skip_placeholders(tmp_path: Path) -> None:
    yaml_secret = "live" + "-credential-9f8e7d6c"
    yaml_path = tmp_path / "intel.local.yaml"
    yaml_path.write_text(
        'llm_api_key: "' + yaml_secret + '"\n'
        "yeux_mcp_token: ${YEUX_MCP_TOKEN}\n"
        "password: replace_me\n",
        encoding="utf-8",
    )
    env_secret = "broker" + "-password-4b3a2c1d"
    env_path = tmp_path / ".env"
    env_path.write_text(
        "BROKER_PASSWORD=" + env_secret + "\nAPI_KEY=<YOUR_API_KEY>\n",
        encoding="utf-8",
    )

    yaml_findings = scan_file(yaml_path)
    env_findings = scan_file(env_path)

    assert [finding.rule_id for finding in yaml_findings] == ["credential-assignment"]
    assert [finding.rule_id for finding in env_findings] == ["credential-assignment"]
    assert yaml_secret not in yaml_findings[0].redacted_line
    assert env_secret not in env_findings[0].redacted_line


def test_git_candidates_include_tracked_and_untracked_but_exclude_generated(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("ignored.env\n", encoding="utf-8")
    tracked = tmp_path / "tracked.yaml"
    tracked.write_text("api_key: placeholder\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", ".gitignore", "tracked.yaml"], check=True)
    untracked = tmp_path / "candidate.env"
    untracked.write_text("TOKEN=placeholder\n", encoding="utf-8")
    ignored = tmp_path / "ignored.env"
    ignored.write_text("TOKEN=not-a-placeholder-value\n", encoding="utf-8")
    generated = tmp_path / "build"
    generated.mkdir()
    (generated / "artifact.yaml").write_text("api_key: not-a-placeholder-value\n", encoding="utf-8")
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "response.env").write_text("TOKEN=not-a-placeholder-value\n", encoding="utf-8")

    candidates = {path.relative_to(tmp_path).as_posix() for path in git_candidate_files(tmp_path)}

    assert {".gitignore", "tracked.yaml", "candidate.env"} <= candidates
    assert "ignored.env" not in candidates
    assert "build/artifact.yaml" not in candidates
    assert "cache/response.env" not in candidates


def test_unreadable_candidate_fails_closed(tmp_path: Path, monkeypatch, capsys) -> None:
    candidate = tmp_path / "candidate.env"
    candidate.write_text("TOKEN=placeholder\n", encoding="utf-8")

    def deny_read(path: Path) -> bytes:
        raise PermissionError(path)

    monkeypatch.setattr(Path, "read_bytes", deny_read)
    with pytest.raises(SecretScanError, match="could not read"):
        scan_file(candidate)
    assert main([str(candidate), "--root", str(tmp_path)]) == 2
    captured = capsys.readouterr()
    assert "passed" not in captured.out
    assert "could not complete" in captured.err


def test_missing_explicit_candidate_fails_closed(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "missing.env"

    assert main([str(missing), "--root", str(tmp_path)]) == 2
    captured = capsys.readouterr()
    assert "passed" not in captured.out
    assert "could not enumerate" in captured.err
