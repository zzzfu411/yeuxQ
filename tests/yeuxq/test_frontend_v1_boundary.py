from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "src" / "yeuxq" / "web"
API_JS = WEB / "js" / "api.js"
UTIL_JS = WEB / "js" / "util.js"

FIRST_PARTY_ASSETS = (
    WEB / "index.html",
    *sorted((WEB / "js").glob("*.js")),
)

V1_BASE = "/api/v1"
QUOTED_API_LITERAL = re.compile(r"""(?P<quote>["'\x60])(?P<path>/api/[^\s"'\x60]*)(?P=quote)""")
V1_CALL_LITERAL = re.compile(r"""\bv1\(\s*(?P<quote>["'\x60])(?P<path>/[^"'\x60]*)(?P=quote)""")
JS_ENCODED_ID = r"\$\{encodeURIComponent\([A-Za-z_][A-Za-z0-9_]*\)\}"
ALLOWED_V1_ROUTES = (
    re.compile(r"^/api/v1/health$"),
    re.compile(r"^/api/v1/integration/status$"),
    re.compile(
        rf"^/api/v1/observations"
        rf"(?:/capture|/(?:\{{observation_id\}}|{JS_ENCODED_ID}))?$"
    ),
    re.compile(r"^/api/v1/research/runs$"),
    re.compile(rf"^/api/v1/research/readiness/(?:\{{run_id\}}|{JS_ENCODED_ID})$"),
)
DANGEROUS_ROUTE_SEGMENTS = {
    "account",
    "accounts",
    "broker",
    "brokers",
    "cancel",
    "execute",
    "execution",
    "order",
    "orders",
    "trade",
    "trades",
}


def _sources() -> dict[Path, str]:
    return {path: path.read_text(encoding="utf-8") for path in FIRST_PARTY_ASSETS}


def _location(path: Path, source: str, offset: int) -> str:
    line = source.count("\n", 0, offset) + 1
    return f"{path.relative_to(ROOT).as_posix()}:{line}"


def _quoted_api_literals(sources: dict[Path, str]) -> list[tuple[str, str]]:
    literals: list[tuple[str, str]] = []
    for path, source in sources.items():
        for match in QUOTED_API_LITERAL.finditer(source):
            literals.append((_location(path, source, match.start()), match.group("path")))
    return literals


def _effective_routes(sources: dict[Path, str]) -> list[tuple[str, str]]:
    routes = [
        (location, path) for location, path in _quoted_api_literals(sources) if path != V1_BASE
    ]
    api_source = sources[API_JS]
    for match in V1_CALL_LITERAL.finditer(api_source):
        routes.append(
            (
                f"{_location(API_JS, api_source, match.start())} (v1 helper)",
                f"{V1_BASE}{match.group('path')}",
            )
        )
    return routes


def _route_shape(path: str) -> str:
    return re.split(r"[?#]", path, maxsplit=1)[0]


def _format_findings(findings: list[tuple[str, str]]) -> str:
    return "\n".join(f"- {location}: {value}" for location, value in findings)


def test_first_party_api_calls_use_only_the_bounded_v1_allowlist() -> None:
    sources = _sources()
    literals = _quoted_api_literals(sources)
    base_literals = [(location, path) for location, path in literals if path == V1_BASE]

    assert literals, (
        "No first-party API literals were found; the boundary check is not exercising code."
    )
    assert len(base_literals) == 1
    assert base_literals[0][0].startswith(API_JS.relative_to(ROOT).as_posix())

    violations: list[tuple[str, str]] = []
    for location, path in _effective_routes(sources):
        route = _route_shape(path)
        if not route.startswith(f"{V1_BASE}/"):
            violations.append((location, f"{route} (not versioned)"))
            continue
        if not any(pattern.fullmatch(route) for pattern in ALLOWED_V1_ROUTES):
            violations.append((location, f"{route} (outside bounded allowlist)"))

    assert not violations, (
        "First-party frontend code must call only the bounded /api/v1 facade:\n"
        f"{_format_findings(violations)}"
    )


def test_frontend_api_paths_expose_no_execution_or_brokerage_segments() -> None:
    findings: list[tuple[str, str]] = []
    for location, path in _effective_routes(_sources()):
        segments = {segment.lower() for segment in _route_shape(path).split("/") if segment}
        dangerous = sorted(segments & DANGEROUS_ROUTE_SEGMENTS)
        if dangerous:
            findings.append((location, f"{path} -> {', '.join(dangerous)}"))

    assert not findings, (
        "Frontend API paths must not expose brokerage or execution capabilities:\n"
        f"{_format_findings(findings)}"
    )


def test_frontend_states_safety_freshness_provenance_and_observation_times() -> None:
    source = "\n".join(_sources().values()).lower()
    requirements = {
        "research-only or non-investment-advice boundary": (
            r"research[\s-]?only|advisory|非投资建议"
        ),
        "no broker, account connection, order, or live execution": (
            r"no broker|不连接(?:实盘)?账户|不提供交易执行|不产生委托|不会触发交易"
        ),
        "explicit unavailable state": r"unavailable|暂不可用|不可用",
        "fresh versus stale semantics": r"\bfreshness\b|\bfresh\b|\bstale\b",
        "provenance or source semantics": r"\bprovenance\b|\bsource\b|来源",
        "observation event time": (r"\bevent_time\b|\bobserved_at\b|事件时间|观测时间|数据时间"),
        "observation receipt time": r"\breceived_at\b|接收时间|入库时间",
    }
    missing = [label for label, pattern in requirements.items() if not re.search(pattern, source)]

    assert not missing, (
        "The frontend must make research safety and evidence timing explicit; "
        f"missing: {', '.join(missing)}"
    )


def test_marked_output_reaches_html_only_through_fail_closed_dompurify() -> None:
    sources = _sources()
    util = sources[UTIL_JS]
    marked_sites: list[str] = []
    for path, source in sources.items():
        for match in re.finditer(r"\bmarked(?:\?\.|\.)parse\b", source):
            marked_sites.append(_location(path, source, match.start()))

    assert marked_sites
    assert all(
        location.startswith(UTIL_JS.relative_to(ROOT).as_posix()) for location in marked_sites
    ), f"marked.parse must be isolated to util.js, found: {marked_sites}"
    assert re.search(
        r"return\s+window\.DOMPurify\.sanitize\(\s*"
        r"window\.marked\.parse\(\s*text\s*\)\s*\)\s*;",
        util,
    )
    assert re.search(
        r"if\s*\(\s*!window\.marked\?\.parse\s*\|\|\s*"
        r"!window\.DOMPurify\?\.sanitize\s*\)\s*"
        r"return\s+esc\(\s*text\s*\)\s*;",
        util,
    )
    assert re.search(
        r"catch\s*\([^)]*\)\s*\{\s*return\s+esc\(\s*text\s*\)\s*;\s*\}",
        util,
    )
