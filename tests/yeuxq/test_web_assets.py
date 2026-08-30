from __future__ import annotations

import hashlib
from importlib import resources
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "src" / "yeuxq" / "web"
VENDOR = WEB / "vendor"

FIRST_PARTY_ASSETS = (
    WEB / "index.html",
    WEB / "css" / "app.css",
    *sorted((WEB / "js").glob("*.js")),
)

EXPECTED_VENDOR = {
    "Apache ECharts": (
        "5.5.0",
        "Apache-2.0",
        "echarts.min.js",
        "42f8329d989b6f6539dd2b15bbdf0d82025762ac112fbb60dc57b27d7bcf3946",
    ),
    "Marked": (
        "12.0.2",
        "MIT",
        "marked.min.js",
        "15fabce5b65898b32b03f5ed25e9f891a729ad4c0d6d877110a7744aa847a894",
    ),
    "DOMPurify": (
        "3.1.6",
        "Apache-2.0 OR MPL-2.0",
        "purify.min.js",
        "c0845096a7c4a6741f362ac506c94c1c7d27dc603bcc1bf64a587f76f2dbe3a1",
    ),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_web_assets_are_importable_package_resources() -> None:
    package_root = resources.files("yeuxq.web")

    assert package_root.joinpath("index.html").is_file()
    assert package_root.joinpath("css", "app.css").is_file()
    assert package_root.joinpath("js", "main.js").is_file()
    assert package_root.joinpath("vendor", "manifest.json").is_file()
    for _, (_, _, filename, _) in EXPECTED_VENDOR.items():
        assert package_root.joinpath("vendor", filename).is_file()


def test_vendor_manifest_has_verifiable_provenance_and_exact_hashes() -> None:
    manifest = json.loads((VENDOR / "manifest.json").read_text(encoding="utf-8"))
    packages = {item["name"]: item for item in manifest["packages"]}

    assert manifest["schema_version"] == 1
    assert set(packages) == set(EXPECTED_VENDOR)
    for name, (version, spdx, filename, digest) in EXPECTED_VENDOR.items():
        item = packages[name]
        assert item["version"] == version
        assert item["spdx"] == spdx
        assert all(item[key].startswith("https://") for key in ("upstream", "release", "license"))
        assert item["files"] == [{"path": filename, "sha256": digest}]
        assert _sha256(VENDOR / filename) == digest


def test_notices_cover_every_vendored_component_without_project_license_claim() -> None:
    notice = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

    assert "does not declare a\nlicense for the yeuxQ project as a whole" in notice
    for name, (version, spdx, filename, digest) in EXPECTED_VENDOR.items():
        assert all(value in notice for value in (name, version, spdx, filename, digest))


def test_page_is_offline_only_and_exposes_read_only_integration_boundary() -> None:
    index = (WEB / "index.html").read_text(encoding="utf-8")
    first_party_text = "\n".join(path.read_text(encoding="utf-8") for path in FIRST_PARTY_ASSETS)

    external_reference = (
        r"(?:src|href)\s*=\s*['\"](?:https?:)?//"
        r"|url\(\s*['\"]?(?:https?:)?//"
        r"|(?:fetch|import)\s*\(\s*['\"](?:https?:)?//"
    )
    assert not re.search(external_reference, first_party_text, re.IGNORECASE)
    assert "connect-src 'self'" in index
    app = (ROOT / "src" / "yeuxq" / "api" / "app.py").read_text(encoding="utf-8")
    assert '"Content-Security-Policy": "frame-ancestors \'none\'"' in app
    assert '"X-Frame-Options": "DENY"' in app
    assert 'href="/integration/"' in index
    assert "RESEARCH ONLY" in index
    assert "NO BROKER" in index
    assert "不提供交易执行" in index


def test_frontend_does_not_handle_credentials_or_call_brokerage_write_routes() -> None:
    source = "\n".join(path.read_text(encoding="utf-8") for path in FIRST_PARTY_ASSETS)
    credential_terms = r"access[_-]?token|authorization|bearer\s|api[_-]?key|client[_-]?secret"
    write_routes = r"/api/(?:broker|orders?|positions?|accounts?|execution|live|trade)(?:[/?'\"]|$)"

    assert not re.search(credential_terms, source, re.IGNORECASE)
    assert not re.search(write_routes, source, re.IGNORECASE)
    assert "WebSocket(" not in source
    assert "EventSource(" not in source


def test_workbench_uses_only_the_bounded_v1_facade_for_integration_evidence() -> None:
    api = (WEB / "js" / "api.js").read_text(encoding="utf-8")
    main = (WEB / "js" / "main.js").read_text(encoding="utf-8")
    state = (WEB / "js" / "state.js").read_text(encoding="utf-8")
    index = (WEB / "index.html").read_text(encoding="utf-8")
    combined = "\n".join((api, main, state, index))

    assert "const V1 = '/api/v1';" in api
    for bounded_path in (
        "/integration/status",
        "/observations?limit=",
        "/observations/capture",
        "/research/runs?limit=",
        "/research/readiness/",
    ):
        assert bounded_path in api
    assert "getV1IntegrationStatus" in main
    assert "listV1Observations" in main
    assert "getV1CanonicalReadiness" in main
    assert "captureLocalResearchObservation" in main
    assert not re.search(r"fetch\([^)]*(?:integration_status\.json|micro_live_readiness)", combined)

    assert 'id="v1BoundaryStatus"' in index
    assert 'id="evidenceCard"' in index
    assert 'id="btnCaptureObs"' in index
    assert "本地 research observation" in combined
    for contract_term in ("UNAVAILABLE", "freshness", "provenance"):
        assert contract_term in combined

    prohibited = r"/api/(?:broker|orders?|positions?|accounts?|execution|live|trade)(?:[/?'\"]|$)"
    assert not re.search(prohibited, combined, re.IGNORECASE)


def test_markdown_renderer_fails_closed_to_escaped_text() -> None:
    util = (WEB / "js" / "util.js").read_text(encoding="utf-8")

    assert "if (!window.marked?.parse || !window.DOMPurify?.sanitize) return esc(text);" in util
    assert re.search(r"catch \(e\) \{\s*return esc\(text\);\s*\}", util)
    assert "window.DOMPurify ? window.DOMPurify.sanitize(raw) : raw" not in util
