from __future__ import annotations

import fnmatch
import hashlib
import json
from pathlib import Path
import re
import tomllib


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "integration" / "donor_migration_manifest.json"
SHA256 = re.compile(r"^[0-9a-f]{64}$")

EXPECTED_WEB_SOURCES = {
    "web/css/app.css",
    "web/index.html",
    "web/js/api.js",
    "web/js/cells.js",
    "web/js/charts.js",
    "web/js/main.js",
    "web/js/orderflow.js",
    "web/js/panels.js",
    "web/js/rail.js",
    "web/js/research.js",
    "web/js/state.js",
    "web/js/trace.js",
    "web/js/util.js",
    "web/js/vision.js",
    "web/vendor/echarts.min.js",
    "web/vendor/marked.min.js",
    "web/vendor/purify.min.js",
}

REQUIRED_REJECTS = {
    "config/intel.local.yaml",
    "data/*.db",
    "data/reports/**",
    "output/**",
    "target/**",
    "*.egg-info/**",
    "**/*.egg-info/**",
}

V4_PROHIBITED_MATERIAL = {
    "source_code",
    "web_assets",
    "binaries",
    "archives",
    "license_files",
    "runtime_data",
    "vendored_libraries",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_donor_migration_manifest_is_complete_and_release_safe() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == 2
    assert manifest["donor"] == "stock_v2"
    assert set(manifest) == {
        "schema_version",
        "donor",
        "generated_on",
        "release_boundary",
        "reference_only",
        "transformations",
        "entries",
        "rejected",
    }

    entries = manifest["entries"]
    assert entries
    assert len({entry["source"] for entry in entries}) == len(entries)
    assert len({entry["target"] for entry in entries}) == len(entries)
    for entry in entries:
        assert set(entry) == {
            "source",
            "target",
            "source_sha256",
            "target_sha256",
            "disposition",
        }
        assert entry["source"] and not Path(entry["source"]).is_absolute()
        assert entry["target"] and not Path(entry["target"]).is_absolute()
        assert SHA256.fullmatch(entry["source_sha256"])
        assert SHA256.fullmatch(entry["target_sha256"])
        assert entry["disposition"]

        target = ROOT / entry["target"]
        assert target.is_file(), entry["target"]
        assert _sha256(target) == entry["target_sha256"], entry["target"]

    rejected = manifest["rejected"]
    reject_patterns = {item["source"] for item in rejected}
    assert REQUIRED_REJECTS <= reject_patterns
    for item in rejected:
        assert set(item) == {
            "source",
            "target",
            "disposition",
            "content_read",
            "hash_policy",
        }
        assert item["target"] is None
        assert item["disposition"].startswith("rejected_")
        assert item["content_read"] is False
        assert item["hash_policy"] == "not_computed"
        assert "sha256" not in item
        assert not any(
            fnmatch.fnmatchcase(entry[field], item["source"])
            for entry in entries
            for field in ("source", "target")
        )

    web_entries = [entry for entry in entries if entry["source"].startswith("web/")]
    assert {entry["source"] for entry in web_entries} == EXPECTED_WEB_SOURCES
    assert {entry["target"] for entry in web_entries} == {
        f"src/yeuxq/{source}" for source in EXPECTED_WEB_SOURCES
    }
    for entry in web_entries:
        if entry["source"].startswith("web/vendor/"):
            assert entry["disposition"] == "migrated_web_vendor_verbatim"
        else:
            assert entry["disposition"] in {
                "migrated_web_first_party_hardened",
                "migrated_web_first_party_verbatim",
            }

    reference_only = manifest["reference_only"]
    assert len(reference_only) == 1
    v4 = reference_only[0]
    assert v4["source"] == "v4_distribution/**"
    assert v4["target"] is None
    assert v4["disposition"] == "reference_only_never_migrate"
    assert set(v4["prohibited_material"]) == V4_PROHIBITED_MATERIAL
    migrated_paths = {entry[field].lower() for entry in entries for field in ("source", "target")}
    assert not any("v4_distribution" in path for path in migrated_paths)
    assert not any(path.endswith(("license.dat", "gen_license.py")) for path in migrated_paths)

    release = manifest["release_boundary"]
    wheel = release["python_wheel"]
    rust = release["rust"]
    assert wheel["package_modules"] == ["quantify", "yeuxq"]
    assert wheel["rust_included"] is False
    assert set(wheel["excluded_rust_paths"]) == {
        "Cargo.toml",
        "Cargo.lock",
        "crates/**",
        "target/**",
    }
    assert rust == {
        "lifecycle": "development_only",
        "activation": "explicit_opt_in",
        "canonical_runtime": "python",
        "parity_required_before_default": True,
    }
    assert release["project_license"] == {
        "spdx": "Apache-2.0",
        "copyright": "Copyright 2026 zzzfu411",
        "license_file": "LICENSE",
        "notice_file": "NOTICE",
        "third_party_notice_file": "THIRD_PARTY_NOTICES.md",
        "scope": "canonical_material_with_confirmed_redistribution_rights",
    }
    assert release["donor_lifecycle"] == {
        "role": "read_only_migration_evidence",
        "feature_changes_allowed": False,
        "runtime_dependency_allowed": False,
        "release_source": False,
        "canonical_release_source": "zzzfu411/yeuxQ",
        "preserve_original": True,
        "delete_original": False,
        "accept_new_runtime_data": False,
        "redistribution_rights": "owner_confirmed",
        "credential_rotation_required": False,
        "deprecation_status": "migration_complete_release_candidate",
    }

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["tool"]["uv"]["build-backend"]["module-name"] == ["quantify", "yeuxq"]


def test_hash_controlled_checkout_uses_lf_bytes() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "* text=auto eol=lf" in attributes

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for entry in manifest["entries"]:
        target = ROOT / entry["target"]
        assert b"\r\n" not in target.read_bytes(), entry["target"]
