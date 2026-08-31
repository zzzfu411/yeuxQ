"""Validate the canonical release source and donor deprecation contract."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = "docs/31_Release_Operations.md"


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _stock_v2_imports(root: Path) -> list[str]:
    findings: list[str] = []
    for path in sorted((root / "src").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            findings.append(f"cannot parse canonical module {path.relative_to(root)}: {exc}")
            continue
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(name == "stock_v2" or name.startswith("stock_v2.") for name in names):
                findings.append(
                    f"canonical runtime imports donor package: {path.relative_to(root)}"
                )
                break
    return findings


def inspect_release_boundary(root: Path = ROOT) -> list[str]:
    """Return deterministic contract findings without reading donor-local secrets."""
    errors: list[str] = []
    manifest_path = root / "integration" / "donor_migration_manifest.json"
    status_path = root / "integration" / "integration_status.json"
    runbook_path = root / RUNBOOK

    try:
        manifest = _load_json(manifest_path)
        status = _load_json(status_path)
        pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        return [f"release contract input is unreadable: {exc}"]

    release = manifest.get("release_boundary")
    if not isinstance(release, dict):
        return ["donor manifest release_boundary must be an object"]

    expected_license = {
        "spdx": "Apache-2.0",
        "copyright": "Copyright 2026 zzzfu411",
        "license_file": "LICENSE",
        "notice_file": "NOTICE",
        "third_party_notice_file": "THIRD_PARTY_NOTICES.md",
        "scope": "canonical_material_with_confirmed_redistribution_rights",
    }
    if release.get("project_license") != expected_license:
        errors.append(
            "donor manifest project license does not match the canonical Apache-2.0 policy"
        )

    lifecycle = release.get("donor_lifecycle")
    required_lifecycle = {
        "role": "read_only_migration_evidence",
        "feature_changes_allowed": False,
        "runtime_dependency_allowed": False,
        "release_source": False,
        "canonical_release_source": "zzzfu411/yeuxQ",
        "preserve_original": True,
        "delete_original": False,
        "accept_new_runtime_data": False,
        "redistribution_rights": "unresolved",
        "credential_rotation_required": True,
        "deprecation_status": "migration_complete_release_blocked",
    }
    if lifecycle != required_lifecycle:
        errors.append("donor lifecycle is not the exact read-only release-blocked contract")

    project = pyproject.get("project", {})
    build = pyproject.get("tool", {}).get("uv", {}).get("build-backend", {})
    if project.get("license") != "Apache-2.0":
        errors.append("pyproject project license must be Apache-2.0")
    if build.get("module-name") != ["quantify", "yeuxq"]:
        errors.append("only quantify and yeuxq may be Python release modules")
    for filename in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"):
        if not (root / filename).is_file():
            errors.append(f"missing canonical release document: {filename}")

    overall = status.get("overall", {})
    if overall.get("release_readiness") != "BLOCK":
        errors.append(
            "release readiness must remain BLOCK while donor owner actions are unresolved"
        )
    risks = {risk.get("id"): risk for risk in status.get("risks", []) if isinstance(risk, dict)}
    if risks.get("P0-01", {}).get("status") != "open":
        errors.append("donor redistribution-rights risk P0-01 must remain open")
    if risks.get("P0-03", {}).get("status") != "open":
        errors.append("donor credential-rotation risk P0-03 must remain open")

    if not runbook_path.is_file():
        errors.append(f"missing release operations runbook: {RUNBOOK}")
    else:
        runbook = runbook_path.read_text(encoding="utf-8")
        required_markers = (
            "## Install from a source checkout",
            "## Install from a wheel",
            "## Runtime configuration",
            "## Upgrade",
            "## Rollback",
            "## Donor deprecation",
            "scripts/check_release_boundary.py",
            "scripts/check_distribution.py",
        )
        if any(marker not in runbook for marker in required_markers):
            errors.append("release operations runbook is missing a required procedure")

    errors.extend(_stock_v2_imports(root))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    findings = inspect_release_boundary(args.root.resolve())
    if findings:
        print("release boundary validation failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print("release boundary contract passed: canonical source only; owner actions remain BLOCK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
