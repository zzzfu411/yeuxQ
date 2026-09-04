from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from yeuxq.api.advisory_app import create_advisory_app


ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "src" / "yeuxq" / "web"
JS = WEB / "js"

EVIDENCE_JS = JS / "evidence.js"
PANELS_JS = JS / "panels.js"
MAIN_JS = JS / "main.js"
CELLS_JS = JS / "cells.js"
RESEARCH_JS = JS / "research.js"
VISION_JS = JS / "vision.js"
ORDERFLOW_JS = JS / "orderflow.js"
INDEX_HTML = WEB / "index.html"

GENERATION_CONTROL_IDS = {
    "btnBrief",
    "btnNews",
    "btnReport",
    "btnEarnings",
    "btnVision",
    "deepMode",
}
UNMIGRATED_ACTION_IDS = {
    "btnScan",
    "btnBacktest",
    "btnCompare",
    "btnOrderFlow",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _js_function(source: str, name: str) -> str:
    """Return one ordinary JS function, ignoring braces inside strings/comments."""
    declaration = re.search(
        rf"(?:export\s+)?(?:async\s+)?function\s+{re.escape(name)}\s*\(",
        source,
    )
    assert declaration is not None, f"JavaScript function {name!r} was not found"
    opening = source.find("{", declaration.end())
    assert opening >= 0, f"JavaScript function {name!r} has no body"

    depth = 0
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    index = opening
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""

        if line_comment:
            if char in "\r\n":
                line_comment = False
            index += 1
            continue
        if block_comment:
            if char == "*" and next_char == "/":
                block_comment = False
                index += 2
            else:
                index += 1
            continue
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue

        if char == "/" and next_char == "/":
            line_comment = True
            index += 2
            continue
        if char == "/" and next_char == "*":
            block_comment = True
            index += 2
            continue
        if char in {"'", '"', "`"}:
            quote = char
            index += 1
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[declaration.start() : index + 1]
        index += 1

    raise AssertionError(f"JavaScript function {name!r} has an unterminated body")


class _ElementsById(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.elements: dict[str, tuple[str, dict[str, str | None]]] = {}

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        element_id = attributes.get("id")
        if element_id:
            self.elements[element_id] = (tag, attributes)


def test_evidence_runtime_fails_closed_and_uses_worst_gate() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable; only the ESM runtime check is skipped")

    module_url = EVIDENCE_JS.resolve().as_uri()
    panels_url = PANELS_JS.resolve().as_uri()
    script = f"""
import assert from 'node:assert/strict';

const evidence = await import({json.dumps(module_url)});
const panels = await import({json.dumps(panels_url)});
const nowMs = Date.parse('2026-08-30T12:00:00.000Z');
const hourMs = 60 * 60 * 1000;

assert.equal(evidence.timestampFreshness(null, {{ nowMs, maxAgeMs: hourMs }}), 'UNKNOWN');
assert.equal(
  evidence.timestampFreshness('2026-08-30T12:00:00.001Z', {{ nowMs, maxAgeMs: hourMs }}),
  'UNKNOWN',
);
assert.equal(
  evidence.timestampFreshness('2026-08-30T10:59:59.999Z', {{ nowMs, maxAgeMs: hourMs }}),
  'STALE',
);
assert.equal(
  evidence.timestampFreshness('2026-08-30T11:00:00.000Z', {{ nowMs, maxAgeMs: hourMs }}),
  'FRESH',
);

const valid = {{
  event_time: '2026-08-30T11:59:00.000Z',
  received_at: '2026-08-30T11:59:01.000Z',
  stale_after: '2026-08-30T12:01:00.000Z',
}};
assert.equal(evidence.observationFreshness(valid, {{ nowMs }}), 'FRESH');
assert.equal(
  evidence.observationFreshness({{ ...valid, stale_after: '2026-08-30T12:00:00.000Z' }}, {{ nowMs }}),
  'STALE',
);
assert.equal(
  evidence.observationFreshness({{ ...valid, received_at: null }}, {{ nowMs }}),
  'UNKNOWN',
);
assert.equal(
  evidence.observationFreshness({{
    event_time: '2026-08-30T12:00:00.001Z',
    received_at: '2026-08-30T12:00:00.002Z',
    stale_after: '2026-08-30T12:01:00.000Z',
  }}, {{ nowMs }}),
  'UNKNOWN',
);
assert.equal(
  evidence.observationFreshness({{
    ...valid,
    received_at: '2026-08-30T11:58:59.000Z',
  }}, {{ nowMs }}),
  'UNKNOWN',
);
assert.equal(
  evidence.observationFreshness({{
    ...valid,
    stale_after: '2026-08-30T11:59:01.000Z',
  }}, {{ nowMs }}),
  'UNKNOWN',
);

const integration = (release_readiness) => ({{ valid: true, release_readiness }});
const readiness = (decision) => ({{ decision }});
assert.equal(evidence.aggregateGate(integration('PASS'), readiness('WATCH')), 'WATCH');
assert.equal(evidence.aggregateGate(integration('BLOCK'), readiness('PASS')), 'BLOCK');
assert.equal(evidence.aggregateGate(integration('WATCH'), readiness('BLOCK')), 'BLOCK');
assert.equal(evidence.aggregateGate(integration('PASS'), readiness('PASS')), 'PASS');
assert.equal(evidence.aggregateGate(integration('PASS'), readiness('PASS'), {{ readiness: 'down' }}), 'BLOCK');
assert.equal(evidence.aggregateFreshness(['FRESH', 'UNKNOWN']), 'UNKNOWN');
assert.equal(evidence.aggregateFreshness(['FRESH', 'STALE']), 'STALE');
assert.deepEqual(panels.percentEvidence(null), {{ text: 'UNKNOWN', className: 'dim' }});
assert.deepEqual(panels.percentEvidence(''), {{ text: 'UNKNOWN', className: 'dim' }});
assert.deepEqual(panels.percentEvidence('not-a-number'), {{ text: 'UNKNOWN', className: 'dim' }});
assert.deepEqual(panels.percentEvidence(0), {{ text: '0%', className: 'up' }});
assert.deepEqual(panels.percentEvidence(-1.2), {{ text: '-1.2%', className: 'dn' }});
"""
    result = subprocess.run(
        [node, "--input-type=module", "--eval", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, (
        "evidence.js failed the Node ESM runtime contract:\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_symbol_switches_discard_stale_main_and_report_responses() -> None:
    main = _read(MAIN_JS)
    analyze = _js_function(main, "analyze")
    minute = _js_function(main, "loadMinute")

    assert re.search(r"const\s+gen\s*=\s*\+\+analyzeGen\s*;", analyze)
    assert re.search(r"if\s*\(\s*analyzeCtrl\s*\)\s*analyzeCtrl\.abort\(\)\s*;", analyze)
    analyze_request = analyze.index("await getAdvisoryAnalysis")
    analyze_guard = re.search(
        r"if\s*\(\s*gen\s*!==\s*analyzeGen(?:\s*\|\|[^)]*)?\)\s*return\s*;",
        analyze,
    )
    assert analyze_guard is not None
    assert analyze_request < analyze_guard.start() < analyze.index("state.signal = a.signal")
    cleared = analyze.index("clearInstrumentView(code, 'LOADING')")
    ai_history = analyze.index("loadSavedAI(code)")
    vision_history = analyze.index("loadSavedVision(code)")
    assert cleared < ai_history < analyze_request
    assert cleared < vision_history < analyze_request

    minute_request = minute.index("await getAdvisoryMinute")
    minute_guard = re.search(
        r"if\s*\([^)]*gen\s*!==\s*analyzeGen[^)]*symbol\s*!==\s*state\.symbol[^)]*\)\s*return\s*;",
        minute,
    )
    assert minute_guard is not None
    assert minute_request < minute_guard.start() < minute.index("state.minute = snapshot.minute")

    for path, function_name in (
        (RESEARCH_JS, "loadSavedAI"),
        (VISION_JS, "loadSavedVision"),
    ):
        function = _js_function(_read(path), function_name)
        list_request = function.index("await listAdvisoryReports")
        first_guard = re.search(
            r"if\s*\(\s*symbol\s*!==\s*state\.symbol\s*\)\s*return\s*;",
            function[list_request:],
        )
        assert first_guard is not None, f"{path.name}:{function_name} lacks a list-response guard"
        first_guard_offset = list_request + first_guard.start()
        report_request = function.index("await getAdvisoryReport", first_guard_offset)
        second_guard = re.search(
            r"if\s*\(\s*symbol\s*!==\s*state\.symbol\s*\)\s*return\s*;",
            function[report_request:],
        )
        assert second_guard is not None, (
            f"{path.name}:{function_name} lacks a detail-response guard"
        )
        assert list_request < first_guard_offset < report_request


def test_unavailable_actions_are_disabled_and_generation_is_not_bound_in_main() -> None:
    parser = _ElementsById()
    parser.feed(_read(INDEX_HTML))

    findings: list[str] = []
    for element_id in sorted(GENERATION_CONTROL_IDS | UNMIGRATED_ACTION_IDS):
        element = parser.elements.get(element_id)
        if element is None:
            findings.append(f"{element_id}: missing")
            continue
        _tag, attributes = element
        if "disabled" not in attributes:
            findings.append(f"{element_id}: not disabled")
        if attributes.get("aria-disabled") != "true":
            findings.append(f"{element_id}: aria-disabled is not true")
    assert not findings, "Fail-closed controls regressed:\n- " + "\n- ".join(findings)

    main = _read(MAIN_JS)
    for element_id in sorted(GENERATION_CONTROL_IDS):
        assert not re.search(rf"(['\"`]){re.escape(element_id)}\1", main), (
            f"main.js must not bind or otherwise activate disabled generation control {element_id}"
        )
    for function_name in ("runAI", "runBrief", "runVision"):
        assert not re.search(rf"\b{function_name}\b", main), (
            f"main.js must not import or call generation stub {function_name}"
        )


def test_generation_scan_and_orderflow_stubs_cannot_make_network_calls() -> None:
    stubs = {
        "research.js:runAI": _js_function(_read(RESEARCH_JS), "runAI"),
        "research.js:runBrief": _js_function(_read(RESEARCH_JS), "runBrief"),
        "vision.js:runVision": _js_function(_read(VISION_JS), "runVision"),
        "panels.js:bindScan": _js_function(_read(PANELS_JS), "bindScan"),
        "orderflow.js:loadOF": _js_function(_read(ORDERFLOW_JS), "loadOF"),
        "orderflow.js:runBacktest": _js_function(_read(ORDERFLOW_JS), "runBacktest"),
        "orderflow.js:runCompare": _js_function(_read(ORDERFLOW_JS), "runCompare"),
    }
    network_call = re.compile(r"\b(?:fetch|getJSON|postJSON|getAdvisory[A-Za-z0-9_]*)\s*\(")
    findings = [name for name, source in stubs.items() if network_call.search(source)]

    assert not findings, (
        "Fail-closed generation/scan/orderflow stubs must not make requests: " + ", ".join(findings)
    )


def test_focus_controls_are_not_nested_inside_card_header_buttons() -> None:
    bind_focus = _js_function(_read(CELLS_JS), "bindFocusButtons")

    assert ".cell-trail" not in bind_focus
    assert "else el.appendChild(b);" in bind_focus


def test_advisory_report_history_exposes_get_only() -> None:
    app = create_advisory_app(
        object()
    )  # Provider methods are never invoked during route inspection.
    report_routes = {
        route.path: set(route.methods or set())
        for route in app.routes
        if getattr(route, "path", "").startswith("/reports")
    }

    assert report_routes == {
        "/reports": {"GET"},
        "/reports/{report_id}": {"GET"},
    }
    write_methods = {"POST", "PUT", "PATCH", "DELETE"}
    assert all(not methods & write_methods for methods in report_routes.values())
