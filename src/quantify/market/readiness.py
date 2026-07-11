"""Readiness review for market context evidence.

The review is descriptive only. It cannot promote a strategy, approve paper
trading, or override deterministic source/data gates.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from typing import Any, Literal

MarketContextDecision = Literal["PASS", "WATCH", "BLOCK"]
MarketContextFindingSeverity = Literal["WATCH", "BLOCK"]

PROHIBITED_ACTIONS = [
    "Do not treat market context as a buy/sell signal.",
    "Do not use market_context_snapshot.json to replace cache-derived market_regime.json.",
    "Market context cannot override deterministic PASS/WATCH/BLOCK gates.",
    "Do not use market context to upgrade source QA, offline intake, candidate, paper, or approval gates.",
    "Do not connect market context evidence to real broker order submission.",
    "Do not let LLM output modify deterministic market context readiness.",
]


@dataclass(frozen=True, slots=True)
class MarketContextReadinessFinding:
    severity: MarketContextFindingSeverity
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class MarketContextReadiness:
    decision: MarketContextDecision
    source: str
    label: str
    artifact: str
    artifact_status: str
    artifact_as_of: str
    target_as_of: str
    max_staleness_days: int
    findings: list[MarketContextReadinessFinding]
    next_actions: list[str]
    prohibited_actions: list[str]
    note: str

    @property
    def blockers(self) -> list[str]:
        return [item.message for item in self.findings if item.severity == "BLOCK"]

    @property
    def watch_items(self) -> list[str]:
        return [item.message for item in self.findings if item.severity == "WATCH"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "source": self.source,
            "label": self.label,
            "artifact": self.artifact,
            "artifact_status": self.artifact_status,
            "artifact_as_of": self.artifact_as_of,
            "target_as_of": self.target_as_of,
            "max_staleness_days": self.max_staleness_days,
            "findings": [item.to_dict() for item in self.findings],
            "blockers": self.blockers,
            "watch_items": self.watch_items,
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
            "note": self.note,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Market Context Readiness: {self.decision}",
            "",
            f"- Source: `{self.source}`",
            f"- Label: `{self.label}`",
            f"- Artifact: `{self.artifact or 'missing'}`",
            f"- Artifact status: `{self.artifact_status}`",
            f"- Artifact as-of: `{self.artifact_as_of or 'missing'}`",
            f"- Target as-of: `{self.target_as_of or 'unspecified'}`",
            "",
            self.note,
            "",
            "## Findings",
        ]
        if self.findings:
            lines.extend(f"- `{item.severity}` {item.code}: {item.message}" for item in self.findings)
        else:
            lines.append("- None.")
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {item}" for item in self.next_actions)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"

    def to_candidate_review(self) -> dict[str, str]:
        return {
            "source": self.source,
            "status": self.decision,
            "label": self.label,
            "message": _candidate_message(self),
            "note": self.note,
        }


def build_market_context_readiness_from_report(
    report_dir: str | Path,
    *,
    as_of: str | None = None,
    max_staleness_days: int = 7,
) -> MarketContextReadiness:
    root = Path(report_dir)
    root_regime = root / "market_regime.json"
    weekly_regime = root / "weekly" / "market_regime.json"
    snapshot = root / "market_context_snapshot.json"
    if root_regime.exists():
        return build_market_context_readiness_from_payload(
            {"source": "market_regime", "payload": _read_json(root_regime), "artifact": str(root_regime)},
            as_of=as_of,
            max_staleness_days=max_staleness_days,
        )
    if weekly_regime.exists():
        return build_market_context_readiness_from_payload(
            {"source": "market_regime", "payload": _read_json(weekly_regime), "artifact": str(weekly_regime)},
            as_of=as_of,
            max_staleness_days=max_staleness_days,
        )
    if snapshot.exists():
        return build_market_context_readiness_from_payload(
            {"source": "market_context_snapshot", "payload": _read_json(snapshot), "artifact": str(snapshot)},
            as_of=as_of,
            max_staleness_days=max_staleness_days,
        )
    return build_market_context_readiness_from_payload(
        {"source": "missing", "payload": {}, "artifact": str(root / "market_regime.json")},
        as_of=as_of,
        max_staleness_days=max_staleness_days,
    )


def build_market_context_readiness_from_payload(
    market_context: dict[str, Any] | None,
    *,
    as_of: str | None = None,
    max_staleness_days: int = 7,
) -> MarketContextReadiness:
    if market_context is None:
        return MarketContextReadiness(
            decision="PASS",
            source="not_reviewed",
            label="unknown",
            artifact="",
            artifact_status="NOT_REVIEWED",
            artifact_as_of="",
            target_as_of=str(as_of or ""),
            max_staleness_days=max_staleness_days,
            findings=[],
            next_actions=[
                "Market context gate was not requested for this direct readiness call.",
            ],
            prohibited_actions=PROHIBITED_ACTIONS,
            note="Market context gate was not requested for this direct readiness call.",
        )
    source = str(market_context.get("source") or "missing")
    payload = _dict_payload(market_context.get("payload"))
    artifact = str(market_context.get("artifact") or "")
    if source == "market_regime":
        return _review_market_regime(
            payload,
            artifact=artifact,
            as_of=as_of,
            max_staleness_days=max_staleness_days,
        )
    if source == "market_context_snapshot":
        return _review_market_context_snapshot(
            payload,
            artifact=artifact,
            as_of=as_of,
            max_staleness_days=max_staleness_days,
        )
    return _missing_readiness(
        artifact=artifact,
        as_of=as_of,
        max_staleness_days=max_staleness_days,
    )


def write_market_context_readiness(
    readiness: MarketContextReadiness,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "market_context_readiness.json").write_text(
        json.dumps(readiness.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "market_context_readiness.md").write_text(readiness.to_markdown(), encoding="utf-8")
    return root


def _review_market_regime(
    payload: dict[str, Any],
    *,
    artifact: str,
    as_of: str | None,
    max_staleness_days: int,
) -> MarketContextReadiness:
    artifact_status = str(payload.get("status") or "MISSING").upper()
    label = str(payload.get("label") or "unknown")
    artifact_as_of = str(payload.get("as_of") or payload.get("end") or "")
    findings: list[MarketContextReadinessFinding] = []
    if not payload:
        findings.append(
            _finding(
                "BLOCK",
                "MARKET_REGIME_EMPTY",
                "market_regime.json is missing or empty; generate it from audited recent A-share daily data.",
            )
        )
    if artifact_status == "BLOCK":
        findings.append(
            _finding(
                "BLOCK",
                "MARKET_REGIME_BLOCK",
                "market_regime=BLOCK: cache-derived market context blocks candidate experiment readiness.",
            )
        )
    elif artifact_status == "WATCH":
        findings.append(
            _finding(
                "WATCH",
                "MARKET_REGIME_WATCH",
                f"market_regime={label}: WATCH market context; keep candidate experiments research-only.",
            )
        )
    elif artifact_status != "PASS":
        findings.append(
            _finding(
                "BLOCK",
                "MARKET_REGIME_STATUS_UNKNOWN",
                f"market_regime status is {artifact_status}; expected PASS or WATCH.",
            )
        )
    if not artifact_as_of:
        findings.append(
            _finding(
                "WATCH",
                "MARKET_REGIME_AS_OF_MISSING",
                "market_regime.json does not record as_of/end; regenerate the cache-derived regime report.",
            )
        )
    findings.extend(_staleness_findings(artifact_as_of, as_of, max_staleness_days))
    if label == "unknown" and artifact_status == "PASS":
        findings.append(
            _finding(
                "WATCH",
                "MARKET_REGIME_LABEL_UNKNOWN",
                "market_regime.json is PASS but label is unknown; review market regime detection output.",
            )
        )
    decision = _decision(findings)
    return MarketContextReadiness(
        decision=decision,
        source="market_regime",
        label=label,
        artifact=artifact,
        artifact_status=artifact_status,
        artifact_as_of=artifact_as_of,
        target_as_of=str(as_of or ""),
        max_staleness_days=max_staleness_days,
        findings=findings,
        next_actions=_next_actions("market_regime", findings),
        prohibited_actions=PROHIBITED_ACTIONS,
        note="Cache-derived market_regime.json is the preferred market context evidence.",
    )


def _review_market_context_snapshot(
    payload: dict[str, Any],
    *,
    artifact: str,
    as_of: str | None,
    max_staleness_days: int,
) -> MarketContextReadiness:
    artifact_status = str(payload.get("status") or "MISSING").upper()
    label = str(payload.get("label") or "unknown")
    artifact_as_of = str(payload.get("as_of") or "")
    findings: list[MarketContextReadinessFinding] = []
    if str(payload.get("artifact_type") or "") != "market_context_snapshot":
        findings.append(
            _finding(
                "BLOCK",
                "SNAPSHOT_TYPE_INVALID",
                "market_context_snapshot.json is missing artifact_type=market_context_snapshot.",
            )
        )
    for field in ("as_of", "source", "reviewed_by", "reviewed_at"):
        if not str(payload.get(field) or "").strip():
            findings.append(
                _finding(
                    "BLOCK",
                    "SNAPSHOT_REVIEW_METADATA_MISSING",
                    f"market_context_snapshot.json is missing reviewed evidence field: {field}.",
                )
            )
    index_metrics = payload.get("index_metrics")
    if not isinstance(index_metrics, list) or not index_metrics:
        findings.append(
            _finding(
                "BLOCK",
                "SNAPSHOT_INDEX_METRICS_MISSING",
                "market_context_snapshot.json must include reviewed index_metrics.",
            )
        )
    if bool(payload.get("can_replace_market_regime")):
        findings.append(
            _finding(
                "BLOCK",
                "SNAPSHOT_BOUNDARY_INVALID",
                "market_context_snapshot.json claims it can replace market_regime.json; this is prohibited.",
            )
        )
    if bool(payload.get("can_approve_strategy")) or bool(payload.get("can_generate_broker_orders")):
        findings.append(
            _finding(
                "BLOCK",
                "SNAPSHOT_PERMISSION_INVALID",
                "market_context_snapshot.json claims strategy approval or broker-order permission; this is prohibited.",
            )
        )
    if artifact_status == "BLOCK":
        findings.append(
            _finding(
                "BLOCK",
                "SNAPSHOT_STATUS_BLOCK",
                "market_context_snapshot=BLOCK: reviewed market context snapshot is not usable.",
            )
        )
    elif artifact_status not in {"PASS", "WATCH"}:
        findings.append(
            _finding(
                "BLOCK",
                "SNAPSHOT_STATUS_UNKNOWN",
                f"market_context_snapshot status is {artifact_status}; expected PASS, WATCH, or BLOCK.",
            )
        )
    for item in payload.get("findings", []) or []:
        text = str(item or "")
        if text.startswith("BLOCK:"):
            findings.append(_finding("BLOCK", "SNAPSHOT_FINDING_BLOCK", text))
        elif text.startswith("WATCH:"):
            findings.append(_finding("WATCH", "SNAPSHOT_FINDING_WATCH", text))
    findings.extend(_staleness_findings(artifact_as_of, as_of, max_staleness_days))
    if not any(item.severity == "BLOCK" for item in findings):
        findings.append(
            _finding(
                "WATCH",
                "SNAPSHOT_ADVISORY_ONLY",
                "Only market_context_snapshot is available; it is advisory context and cannot replace cache-derived market_regime.json.",
            )
        )
    decision = _decision(findings)
    return MarketContextReadiness(
        decision=decision,
        source="market_context_snapshot",
        label=label,
        artifact=artifact,
        artifact_status=artifact_status,
        artifact_as_of=artifact_as_of,
        target_as_of=str(as_of or ""),
        max_staleness_days=max_staleness_days,
        findings=findings,
        next_actions=_next_actions("market_context_snapshot", findings),
        prohibited_actions=PROHIBITED_ACTIONS,
        note=(
            "Reviewed market_context_snapshot.json can provide temporary advisory context, "
            "but it keeps readiness at WATCH until cache-derived market_regime.json exists."
        ),
    )


def _missing_readiness(
    *,
    artifact: str,
    as_of: str | None,
    max_staleness_days: int,
) -> MarketContextReadiness:
    findings = [
        _finding(
            "BLOCK",
            "MARKET_CONTEXT_MISSING",
            (
                "market_context=MISSING: provide cache-derived market_regime.json or a reviewed "
                "market_context_snapshot.json before launching candidate experiments."
            ),
        )
    ]
    return MarketContextReadiness(
        decision="BLOCK",
        source="missing",
        label="unknown",
        artifact=artifact,
        artifact_status="MISSING",
        artifact_as_of="",
        target_as_of=str(as_of or ""),
        max_staleness_days=max_staleness_days,
        findings=findings,
        next_actions=_next_actions("missing", findings),
        prohibited_actions=PROHIBITED_ACTIONS,
        note="Recent A-share market context must be attached to candidate experiment readiness.",
    )


def _candidate_message(readiness: MarketContextReadiness) -> str:
    if readiness.source == "missing":
        return readiness.blockers[0] if readiness.blockers else "market_context=MISSING."
    if readiness.source == "market_regime":
        if readiness.decision == "BLOCK":
            return readiness.blockers[0] if readiness.blockers else "market_regime=BLOCK."
        if readiness.decision == "WATCH":
            return readiness.watch_items[0] if readiness.watch_items else (
                f"market_regime={readiness.label}: WATCH market context; keep candidate experiments research-only."
            )
        return ""
    if readiness.source == "market_context_snapshot":
        if readiness.decision == "BLOCK":
            return readiness.blockers[0] if readiness.blockers else (
                "market_context_snapshot=BLOCK: reviewed market context snapshot is not usable."
            )
        return next(
            (
                item
                for item in readiness.watch_items
                if "Only market_context_snapshot" in item
            ),
            readiness.watch_items[0] if readiness.watch_items else (
                "Only market_context_snapshot is available; it is advisory context and cannot replace cache-derived market_regime.json."
            ),
        )
    return readiness.blockers[0] if readiness.blockers else ""


def _staleness_findings(
    artifact_as_of: str,
    target_as_of: str | None,
    max_staleness_days: int,
) -> list[MarketContextReadinessFinding]:
    if not artifact_as_of or not target_as_of:
        return []
    artifact_date = _parse_date(artifact_as_of)
    target_date = _parse_date(target_as_of)
    if artifact_date is None or target_date is None:
        return [
            _finding(
                "WATCH",
                "MARKET_CONTEXT_DATE_PARSE",
                f"Could not parse market context as_of `{artifact_as_of}` or target `{target_as_of}`.",
            )
        ]
    age = (target_date - artifact_date).days
    if age > max_staleness_days:
        return [
            _finding(
                "BLOCK",
                "MARKET_CONTEXT_STALE",
                (
                    f"market_context=STALE: artifact as_of {artifact_as_of} is {age} calendar days "
                    f"before target {target_as_of}; refresh market context evidence."
                ),
            )
        ]
    if age < 0:
        return [
            _finding(
                "WATCH",
                "MARKET_CONTEXT_FUTURE_AS_OF",
                f"Market context as_of {artifact_as_of} is after target {target_as_of}; verify dates.",
            )
        ]
    return []


def _next_actions(source: str, findings: list[MarketContextReadinessFinding]) -> list[str]:
    if any(item.code == "MARKET_CONTEXT_STALE" for item in findings):
        return [
            (
                ".\\.venv\\Scripts\\python.exe examples\\run_market_regime.py --config "
                "config\\research_recent.yaml --output-dir results\\first_million"
            ),
            (
                "If cache-derived market_regime.json is not available yet, write a reviewed "
                "market_context_snapshot.json from local index evidence and keep the workflow at WATCH."
            ),
        ]
    if source == "market_regime" and not any(item.severity == "BLOCK" for item in findings):
        return ["Continue candidate experiment readiness; market context does not override other gates."]
    if source == "market_context_snapshot" and not any(item.severity == "BLOCK" for item in findings):
        return [
            (
                "Generate cache-derived market_regime.json from audited A-share daily data before "
                "treating market context as complete."
            )
        ]
    return [
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_market_regime.py --config "
            "config\\research_recent.yaml --output-dir results\\first_million"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\run_market_index_discovery.py "
            "--search-dir data_exports\\indices --output-dir results\\first_million "
            "--as-of <YYYY-MM-DD>"
        ),
        (
            ".\\.venv\\Scripts\\python.exe examples\\write_market_context_snapshot.py --output-dir "
            'results\\first_million --as-of <YYYY-MM-DD> --source "<reviewed-index-source>" '
            '--reviewed-by "<name>" --reviewed-at <YYYY-MM-DD> --index '
            '"CSI300,0.01,0.03,0.04,0.08,0.22,0.55,0.50,reviewed note"'
        ),
    ]


def _decision(findings: list[MarketContextReadinessFinding]) -> MarketContextDecision:
    if any(item.severity == "BLOCK" for item in findings):
        return "BLOCK"
    if any(item.severity == "WATCH" for item in findings):
        return "WATCH"
    return "PASS"


def _finding(
    severity: MarketContextFindingSeverity,
    code: str,
    message: str,
) -> MarketContextReadinessFinding:
    return MarketContextReadinessFinding(severity=severity, code=code, message=message)


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _dict_payload(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
