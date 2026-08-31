"""Audit wheel/sdist contents for release-safe packaging and license provenance.

The check is intentionally offline: it inspects already-built archives, verifies
the project Apache-2.0 metadata and notices, checks vendored web manifest hashes,
and requires the complete SPDX license texts that accompany those files. It
never prints archive contents that could contain credentials.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
import zipfile
from collections.abc import Iterable


REQUIRED_LICENSES = {
    "Apache-2.0.txt": (
        "Apache License",
        "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION",
    ),
    "MIT.txt": ("MIT License", "Permission is hereby granted", "THE SOFTWARE IS PROVIDED"),
    "MPL-2.0.txt": (
        "Mozilla Public License Version 2.0",
        "10. Versions of the License",
        "Exhibit A - Source Code Form License Notice",
    ),
}
REQUIRED_NOTICE = "yeuxq/web/vendor/THIRD_PARTY_NOTICES.md"
MANIFEST_PATH = "yeuxq/web/vendor/manifest.json"
PROJECT_DOCUMENTS = {
    "LICENSE": (
        "Apache License",
        "Version 2.0, January 2004",
        "3. Grant of Patent License.",
        "END OF TERMS AND CONDITIONS",
    ),
    "NOTICE": ("yeuxQ", "Copyright 2026 zzzfu411", "THIRD_PARTY_NOTICES.md"),
    "THIRD_PARTY_NOTICES.md": (
        "# Third-Party Notices",
        "Apache ECharts",
        "Marked",
        "DOMPurify",
    ),
}
PROJECT_METADATA_MARKERS = (
    "License-Expression: Apache-2.0",
    "License-File: LICENSE",
    "License-File: NOTICE",
    "License-File: THIRD_PARTY_NOTICES.md",
)
FORBIDDEN_PARTS = {
    ".env",
    "data",
    "reports",
    "output",
    "target",
    "build",
    "dist",
    ".playwright-cli",
}
FORBIDDEN_SUFFIXES = (".db", ".sqlite", ".sqlite3")
FORBIDDEN_NAME_RE = re.compile(
    r"(?:^|[._-])(secret|token|credential|password|api[-_]?key)(?:[._-]|$)", re.I
)


class DistributionViolation(RuntimeError):
    """Raised when an archive violates the release boundary."""


def _member_names(path: Path) -> list[str]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return archive.namelist()
    if path.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(path, "r:gz") as archive:
            return [member.name for member in archive.getmembers()]
    raise DistributionViolation(f"unsupported archive type: {path.name}")


def _read_member(path: Path, member: str) -> bytes:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return archive.read(member)
    with tarfile.open(path, "r:gz") as archive:
        item = archive.extractfile(member)
        if item is None:
            raise KeyError(member)
        return item.read()


def _relative_member(member: str) -> PurePosixPath:
    # Archive roots (e.g. ``quantify-0.1.0/``) are not part of package policy.
    path = PurePosixPath(member)
    return PurePosixPath(*path.parts[1:]) if len(path.parts) > 1 else path


def _forbidden(member: str) -> bool:
    relative = _relative_member(member)
    parts = [part.lower() for part in relative.parts]
    raw_parts = [part.lower() for part in PurePosixPath(member).parts]
    # ``quantify/data`` is a valid import package; only runtime data roots are
    # forbidden.  Package source paths are therefore exempt from this check.
    package_path = any(part in {"quantify", "yeuxq"} for part in raw_parts[:-1])
    if not package_path and any(part in FORBIDDEN_PARTS for part in parts):
        return True
    lower_name = relative.name.lower()
    if lower_name.endswith(FORBIDDEN_SUFFIXES):
        return True
    return bool(FORBIDDEN_NAME_RE.search(lower_name))


def _check_manifest(path: Path, members: set[str]) -> list[str]:
    errors: list[str] = []
    candidates = [
        member
        for member in members
        if member.endswith("/" + MANIFEST_PATH) or member == MANIFEST_PATH
    ]
    if len(candidates) != 1:
        return [f"expected exactly one {MANIFEST_PATH}, found {len(candidates)}"]
    manifest_member = candidates[0]
    try:
        payload = json.loads(_read_member(path, manifest_member).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"invalid vendor manifest: {exc}"]
    if payload.get("schema_version") != 1:
        errors.append("vendor manifest schema_version must be 1")
    for package in payload.get("packages", []):
        for entry in package.get("files", []):
            rel = str(entry.get("path", ""))
            expected = str(entry.get("sha256", ""))
            suffix = "yeuxq/web/vendor/" + rel
            matches = [
                member for member in members if member == suffix or member.endswith("/" + suffix)
            ]
            if len(matches) != 1:
                errors.append(f"vendor asset missing or duplicated: {rel}")
                continue
            actual = hashlib.sha256(_read_member(path, matches[0])).hexdigest()
            if actual != expected:
                errors.append(f"vendor asset hash mismatch: {rel}")
    return errors


def _project_document_matches(path: Path, members: set[str], filename: str) -> list[str]:
    if path.suffix == ".whl":
        return [
            member
            for member in members
            if ".dist-info/licenses/" in member and PurePosixPath(member).name == filename
        ]
    return [member for member in members if _relative_member(member) == PurePosixPath(filename)]


def _check_project_license(path: Path, members: set[str]) -> list[str]:
    errors: list[str] = []
    for filename, markers in PROJECT_DOCUMENTS.items():
        matches = _project_document_matches(path, members, filename)
        if len(matches) != 1:
            errors.append(f"expected exactly one packaged project document: {filename}")
            continue
        text = _read_member(path, matches[0]).decode("utf-8", errors="replace")
        if any(marker not in text for marker in markers):
            errors.append(f"incomplete project document: {filename}")

    if path.suffix == ".whl":
        metadata_matches = [member for member in members if member.endswith(".dist-info/METADATA")]
    else:
        metadata_matches = [
            member for member in members if _relative_member(member) == PurePosixPath("PKG-INFO")
        ]
    if len(metadata_matches) != 1:
        errors.append("expected exactly one package metadata document")
    else:
        metadata = _read_member(path, metadata_matches[0]).decode("utf-8", errors="replace")
        if any(marker not in metadata for marker in PROJECT_METADATA_MARKERS):
            errors.append("package metadata does not declare the complete Apache-2.0 license set")
    return errors


def inspect_archive(path: Path) -> list[str]:
    """Return deterministic, redacted policy findings for one archive."""
    members = set(_member_names(path))
    errors: list[str] = []
    for member in sorted(members):
        if _forbidden(member):
            errors.append(f"forbidden artifact or secret-shaped path: {_relative_member(member)}")
    errors.extend(_check_project_license(path, members))
    notice_matches = [
        member
        for member in members
        if member.endswith("/" + REQUIRED_NOTICE) or member == REQUIRED_NOTICE
    ]
    if len(notice_matches) != 1:
        errors.append(f"expected exactly one packaged notice: {REQUIRED_NOTICE}")
    for filename, markers in REQUIRED_LICENSES.items():
        required = f"yeuxq/web/vendor/licenses/{filename}"
        matches = [
            member for member in members if member.endswith("/" + required) or member == required
        ]
        if len(matches) != 1:
            errors.append(f"expected exactly one complete license text: {required}")
            continue
        text = _read_member(path, matches[0]).decode("utf-8", errors="replace")
        missing = [marker for marker in markers if marker not in text]
        if missing:
            errors.append(f"incomplete {filename}: missing required clauses")
    errors.extend(_check_manifest(path, members))
    return errors


def check_archives(paths: Iterable[Path]) -> None:
    findings = {path: inspect_archive(path) for path in paths}
    failures = [(path, error) for path, errors in findings.items() for error in errors]
    if failures:
        lines = [f"{path}: {error}" for path, error in failures]
        raise DistributionViolation("distribution compliance failed:\n" + "\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit built wheel and sdist archives")
    parser.add_argument("archives", nargs="+", type=Path)
    args = parser.parse_args(argv)
    try:
        check_archives(args.archives)
    except (DistributionViolation, OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"distribution compliance passed: {len(args.archives)} archive(s) checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
