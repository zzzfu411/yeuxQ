from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "integration"
HTML_PATH = INTEGRATION / "index.html"
CSS_PATH = INTEGRATION / "status.css"
JS_PATH = INTEGRATION / "status.js"
STATUS_PATH = INTEGRATION / "integration_status.json"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_status_ui_assets_exist_and_are_local_only() -> None:
    for path in (HTML_PATH, CSS_PATH, JS_PATH):
        assert path.is_file(), f"missing status UI asset: {path}"
        assert path.stat().st_size > 500

    html = _read(HTML_PATH)
    assert 'href="status.css"' in html
    assert 'src="status.js"' in html
    assert not re.search(r"(?:href|src)=[\"'](?:https?:)?//", html, re.IGNORECASE)
    assert 'http-equiv="Content-Security-Policy"' in html
    assert "default-src 'none'" in html
    assert 'name="referrer" content="no-referrer"' in html
    assert "@import" not in _read(CSS_PATH)
    assert "url(" not in _read(CSS_PATH)


def test_projection_is_read_only_and_uses_one_json_source() -> None:
    javascript = _read(JS_PATH)
    html = _read(HTML_PATH)

    assert javascript.count('"./integration_status.json"') == 1
    assert "fetch(STATUS_SOURCE" in javascript
    assert 'method: "GET"' in javascript
    assert "integration_status.json" not in html
    assert "schema_version" not in html

    forbidden_write_surfaces = (
        'method: "POST"',
        'method: "PUT"',
        'method: "PATCH"',
        'method: "DELETE"',
        "XMLHttpRequest",
        "WebSocket",
        "sendBeacon",
        "localStorage",
        "sessionStorage",
        "indexedDB",
    )
    for marker in forbidden_write_surfaces:
        assert marker not in javascript

    status = json.loads(_read(STATUS_PATH))
    assert status["frontend_sync"]["source_of_truth"] == ("integration/integration_status.json")
    assert status["frontend_sync"]["ui_mutation_allowed"] is False


def test_fail_closed_copy_boundaries_and_status_enums_are_explicit() -> None:
    html = _read(HTML_PATH)
    javascript = _read(JS_PATH)

    assert "BLOCK — 状态未验证" in html
    assert "未知、缺失或不支持的状态一律按 BLOCK 处理" in html
    assert "RESEARCH-ONLY" in html
    assert "NO BROKER / NO LIVE ORDERS" in html
    assert "不连接券商" in html
    assert '"PASS", "WATCH", "BLOCK"' in javascript
    assert '"not_started", "in_progress", "completed", "blocked"' in javascript
    assert '"open", "mitigated", "closed"' in javascript
    assert "包含未知状态枚举" in javascript
    assert "unknown_or_invalid_state" in javascript
    assert "FULL REGRESSION" in javascript
    assert "PACKAGE BUILD" in javascript


def test_dynamic_content_uses_safe_dom_and_accessible_responsive_contracts() -> None:
    html = _read(HTML_PATH)
    css = _read(CSS_PATH)
    javascript = _read(JS_PATH)

    assert "innerHTML" not in javascript
    assert "outerHTML" not in javascript
    assert "insertAdjacentHTML" not in javascript
    assert ".textContent" in javascript
    assert "document.createElement" in javascript
    assert "replaceChildren" in javascript

    assert 'aria-live="assertive"' in html
    assert 'role="progressbar"' in html
    assert 'href="#main-content"' in html
    assert 'type="button"' in html
    assert "<noscript>" in html
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "@media (max-width: 48rem)" in css
    assert ":focus-visible" in css


def test_status_ui_avoids_disallowed_generic_visual_tropes() -> None:
    css = _read(CSS_PATH).lower()
    font_declarations = re.findall(r"font-family:\s*([^;]+);", css)

    assert all(
        not re.search(r"(?:^|[\s\"'])inter(?:$|[\s,\"'])", item) for item in font_declarations
    )
    assert all(
        not re.search(r"(?:^|[\s\"'])arial(?:$|[\s,\"'])", item) for item in font_declarations
    )
    assert "purple" not in css
    assert "#7c3aed" not in css
    assert "#8b5cf6" not in css
    assert "--orange: #ff5a1f" in css
    assert '"bodoni mt"' in css


def test_node_validator_accepts_current_contract_and_blocks_invalid_states() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed; static UI contract tests still ran")

    smoke = r"""
const fs = require("node:fs");
const api = require(process.argv[1]);
const valid = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}
function expectBlocked(payload, label) {
  const validation = api.validateStatusPayload(payload);
  const display = api.deriveDisplayState(payload);
  if (validation.ok || display.status !== "BLOCK") {
    throw new Error(`${label} did not fail closed`);
  }
}

const accepted = api.validateStatusPayload(valid);
if (!accepted.ok) {
  throw new Error(`current status rejected: ${accepted.errors.join(" | ")}`);
}
if (api.deriveDisplayState(valid).status !== valid.overall.release_readiness) {
  throw new Error("valid readiness was not projected");
}

const unknownPhase = clone(valid);
unknownPhase.phases[0].status = "mystery";
expectBlocked(unknownPhase, "unknown phase status");

const missingOverall = clone(valid);
delete missingOverall.overall;
expectBlocked(missingOverall, "missing overall");

const unsupportedSchema = clone(valid);
unsupportedSchema.schema_version = "2.0.0";
expectBlocked(unsupportedSchema, "unsupported schema");

const unknownRisk = clone(valid);
unknownRisk.risks[0].status = "waived";
expectBlocked(unknownRisk, "unknown risk status");

const brokerEnabled = clone(valid);
brokerEnabled.boundaries.execution.broker_integration = true;
expectBlocked(brokerEnabled, "broker boundary violation");

const falsePass = clone(valid);
falsePass.overall.release_readiness = "PASS";
expectBlocked(falsePass, "open release risk with PASS readiness");
"""
    completed = subprocess.run(
        [node, "-e", smoke, str(JS_PATH), str(STATUS_PATH)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
