from __future__ import annotations

import io
from pathlib import Path
import tarfile
import zipfile

import pytest

from scripts.check_distribution import DistributionViolation, check_archives, inspect_archive


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist-compliance"


def test_built_wheel_and_sdist_pass_release_boundary() -> None:
    wheel = DIST / "quantify-0.1.0-py3-none-any.whl"
    sdist = DIST / "quantify-0.1.0.tar.gz"
    if not wheel.exists() or not sdist.exists():
        pytest.skip("build compliance archives first")
    check_archives((wheel, sdist))


def test_archive_checker_rejects_runtime_artifacts(tmp_path: Path) -> None:
    archive = tmp_path / "bad.whl"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("quantify/data.sqlite3", b"runtime")
    findings = inspect_archive(archive)
    assert any("forbidden artifact" in finding for finding in findings)


def test_archive_checker_rejects_incomplete_license_text(tmp_path: Path) -> None:
    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        payload = b"MIT License"
        info = tarfile.TarInfo("quantify-0.1.0/yeuxq/web/vendor/licenses/MIT.txt")
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
    findings = inspect_archive(archive)
    assert any("incomplete MIT.txt" in finding for finding in findings)
    with pytest.raises(DistributionViolation):
        check_archives((archive,))
