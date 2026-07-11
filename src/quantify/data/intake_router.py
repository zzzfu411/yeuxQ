"""Route recent A-share data acquisition toward the best guarded intake path."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from quantify.data.acquisition_plan import (
    RecentDataAcquisitionPlan,
    build_recent_data_acquisition_plan_from_config,
)
from quantify.data.offline_package import (
    OfflineDataPackageReport,
    build_offline_data_package_report,
)
from quantify.data.tdx_discovery import TdxDayDiscoveryReport, build_tdx_day_discovery_report
from quantify.utils.config import load_config

IntakeRouteStatus = Literal["PASS", "WATCH", "BLOCK"]


@dataclass(frozen=True, slots=True)
class DataIntakeRoute:
    name: str
    status: IntakeRouteStatus
    priority: int
    candidate_scope: list[str]
    message: str
    blockers: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "priority": self.priority,
            "candidate_scope": self.candidate_scope,
            "message": self.message,
            "blockers": self.blockers,
            "next_actions": self.next_actions,
            "commands": self.commands,
            "evidence": self.evidence,
        }


@dataclass(frozen=True, slots=True)
class DataIntakeRouterReport:
    status: IntakeRouteStatus
    recommended_route: str
    config_path: str
    data_dir: str
    latest_import_report_path: str
    as_of: str | None
    routes: list[DataIntakeRoute]
    next_actions: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "recommended_route": self.recommended_route,
            "config_path": self.config_path,
            "data_dir": self.data_dir,
            "latest_import_report_path": self.latest_import_report_path,
            "as_of": self.as_of,
            "routes": [route.to_dict() for route in self.routes],
            "next_actions": self.next_actions,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Data Intake Router: {self.status}",
            "",
            f"- Recommended route: `{self.recommended_route or 'none'}`",
            f"- Config: `{self.config_path}`",
            f"- Data directory: `{self.data_dir}`",
            f"- Latest import report: `{self.latest_import_report_path or 'not supplied'}`",
            f"- As of: `{self.as_of or 'unspecified'}`",
            "",
            "This report is a route selector for data intake. It is not a strategy approval, "
            "profitability claim, or live trading permission.",
            "",
            "## Routes",
            "",
            "| route | status | priority | scope | message | blockers |",
            "| --- | --- | ---: | --- | --- | --- |",
        ]
        for route in self.routes:
            scope = ", ".join(route.candidate_scope)
            blockers = "; ".join(route.blockers) if route.blockers else "none"
            lines.append(
                f"| `{route.name}` | `{route.status}` | {route.priority} | "
                f"`{scope}` | {route.message} | {blockers} |"
            )
        lines.extend(["", "## Next Actions"])
        lines.extend(f"- {action}" for action in self.next_actions)
        recommended = self.route(self.recommended_route)
        if recommended and recommended.commands:
            lines.extend(["", "## Recommended Commands"])
            for command in recommended.commands:
                lines.append("")
                lines.append("```powershell")
                lines.append(command)
                lines.append("```")
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {action}" for action in self.prohibited_actions)
        return "\n".join(lines) + "\n"

    def route(self, name: str) -> DataIntakeRoute | None:
        return next((route for route in self.routes if route.name == name), None)


def build_data_intake_router(
    *,
    data_dir: str | Path = "data_exports",
    config_path: str | Path = "config/research_recent.yaml",
    source_qa_answers: str | Path | None = None,
    source_qa_evidence_manifest: str | Path | None = None,
    require_source_qa_evidence_manifest: bool = False,
    latest_import_report_path: str | Path | None = "results/import/recent/data_import.json",
    tdx_search_dirs: list[str | Path] | None = None,
    min_symbols: int = 300,
    as_of: str | None = None,
    encoding: str = "utf-8-sig",
    max_tdx_files_to_probe: int = 2000,
    acquisition_plan: RecentDataAcquisitionPlan | None = None,
    tdx_discovery: TdxDayDiscoveryReport | None = None,
    offline_package: OfflineDataPackageReport | None = None,
) -> DataIntakeRouterReport:
    """Build a conservative route selector across provider, TDX, and CSV paths."""
    cfg = load_config(config_path)
    data_root = Path(data_dir)
    answers_path = Path(source_qa_answers) if source_qa_answers else data_root / "data_source_qa_answers.json"
    acquisition = acquisition_plan or build_recent_data_acquisition_plan_from_config(
        config_path=config_path,
        as_of=as_of,
        min_symbols=min_symbols,
        import_limit=max(min_symbols, 500),
        latest_import_report_path=latest_import_report_path,
    )
    discovery = tdx_discovery or build_tdx_day_discovery_report(
        search_dirs=tdx_search_dirs,
        config_path=config_path,
        output_dir="results/first_million",
        data_output_dir=data_root,
        min_symbols=min_symbols,
        start=str(cfg.research.start),
        end=str(cfg.research.end),
        as_of=as_of,
        max_files_to_probe=max_tdx_files_to_probe,
    )
    package = offline_package or build_offline_data_package_report(
        data_dir=data_root,
        config_path=config_path,
        source_qa_answers=answers_path,
        source_qa_evidence_manifest=source_qa_evidence_manifest,
        require_source_qa_evidence_manifest=require_source_qa_evidence_manifest,
        min_symbols=min_symbols,
        as_of=as_of,
        encoding=encoding,
    )
    routes = [
        _provider_route(acquisition),
        _tdx_route(discovery),
        _broker_vendor_csv_route(package),
    ]
    recommended = _recommended_route(routes)
    return DataIntakeRouterReport(
        status=recommended.status,
        recommended_route=recommended.name,
        config_path=str(config_path),
        data_dir=str(data_root),
        latest_import_report_path=str(latest_import_report_path or ""),
        as_of=as_of,
        routes=routes,
        next_actions=_next_actions(recommended),
        prohibited_actions=[
            "Do not treat a route PASS as strategy evidence or data-readiness approval.",
            "Do not run candidate experiments until source QA, offline intake, and bootstrap gates pass.",
            "Do not use demo/template/stale data as capital-allocation evidence.",
            "Do not use OHLCV-only routes for valuation or quality factor claims.",
            "Do not connect any intake route to real broker order submission.",
        ],
    )


def write_data_intake_router(report: DataIntakeRouterReport, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "data_intake_router.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "data_intake_router.md").write_text(report.to_markdown(), encoding="utf-8")
    return root


def _provider_route(plan: RecentDataAcquisitionPlan) -> DataIntakeRoute:
    attempt = plan.latest_import_attempt
    evidence = {
        "plan_status": plan.status,
        "bootstrap_decision": plan.bootstrap_decision,
        "network_blocked": attempt.network_blocked,
        "latest_import_status": attempt.status,
        "actual_bar_start": attempt.actual_bar_start,
        "actual_bar_end": attempt.actual_bar_end,
        "evidence_status": attempt.evidence_status,
    }
    commands = [
        step.command for step in plan.steps if step.name in {"try_akshare_import", "bootstrap_recent_cache"}
    ]
    if not attempt.attempted:
        return DataIntakeRoute(
            name="provider_akshare",
            status="WATCH",
            priority=30,
            candidate_scope=["research data cache"],
            message="Provider route has not been tried in the current evidence set.",
            next_actions=["Try provider import only if network and provider access are available."],
            commands=commands,
            evidence=evidence,
        )
    if attempt.network_blocked:
        return DataIntakeRoute(
            name="provider_akshare",
            status="BLOCK",
            priority=80,
            candidate_scope=["research data cache"],
            message="Provider route is currently blocked by network/proxy access.",
            blockers=[attempt.message],
            next_actions=["Use an offline TDX or broker/vendor CSV route until provider access is fixed."],
            commands=commands,
            evidence=evidence,
        )
    if attempt.evidence_status == "PASS" and plan.bootstrap_decision == "PASS":
        return DataIntakeRoute(
            name="provider_akshare",
            status="PASS",
            priority=10,
            candidate_scope=["research data cache"],
            message="Provider import and current bootstrap evidence are PASS.",
            next_actions=["Run data audit, robustness, and paper-stage reviews before strategy promotion."],
            commands=commands,
            evidence=evidence,
        )
    if attempt.evidence_status == "PASS":
        return DataIntakeRoute(
            name="provider_akshare",
            status="WATCH",
            priority=20,
            candidate_scope=["research data cache"],
            message="Provider import passed, but current cache/bootstrap evidence still needs review.",
            next_actions=["Run recent bootstrap and data audit against the imported cache."],
            commands=commands,
            evidence=evidence,
        )
    return DataIntakeRoute(
        name="provider_akshare",
        status="BLOCK",
        priority=70,
        candidate_scope=["research data cache"],
        message="Provider route has BLOCK evidence.",
        blockers=[attempt.message],
        next_actions=[attempt.next_action],
        commands=commands,
        evidence=evidence,
    )


def _tdx_route(discovery: TdxDayDiscoveryReport) -> DataIntakeRoute:
    commands = list(discovery.next_commands)
    evidence = {
        "discovery_status": discovery.status,
        "best_root": discovery.best_root,
        "root_count": len(discovery.roots),
    }
    if discovery.status == "PASS":
        return DataIntakeRoute(
            name="tdx_ohlcv",
            status="PASS",
            priority=10,
            candidate_scope=["OHLCV-only candidate family"],
            message="Local TDX OHLCV files were discovered and can enter guarded intake.",
            next_actions=["Run TDX OHLCV intake, then fill source QA evidence before any candidate launch."],
            commands=commands,
            evidence=evidence,
        )
    if discovery.status == "WATCH":
        blockers = [root.message for root in discovery.roots if root.status == "WATCH"]
        return DataIntakeRoute(
            name="tdx_ohlcv",
            status="WATCH",
            priority=20,
            candidate_scope=["OHLCV-only candidate family"],
            message="Local TDX OHLCV files exist, but breadth or date coverage needs review.",
            blockers=blockers,
            next_actions=discovery.next_actions,
            commands=commands,
            evidence=evidence,
        )
    return DataIntakeRoute(
        name="tdx_ohlcv",
        status="BLOCK",
        priority=50,
        candidate_scope=["OHLCV-only candidate family"],
        message="No usable local TDX OHLCV root was discovered.",
        blockers=discovery.next_actions,
        next_actions=discovery.next_actions,
        commands=commands,
        evidence=evidence,
    )


def _broker_vendor_csv_route(package: OfflineDataPackageReport) -> DataIntakeRoute:
    blocking_items = [item for item in package.items if item.status == "BLOCK"]
    watch_items = [item for item in package.items if item.status == "WATCH"]
    blockers = [f"{item.name}: {item.message}" for item in blocking_items]
    evidence = {
        "package_status": package.status,
        "data_dir": package.data_dir,
        "source_qa_answers_path": package.source_qa_answers_path,
        "csv_file_count": len(package.csv_files),
    }
    if package.status == "PASS":
        return DataIntakeRoute(
            name="broker_vendor_csv",
            status="PASS",
            priority=15,
            candidate_scope=["OHLCV candidates; PIT candidates only if fundamentals are PIT-audited"],
            message="Offline broker/vendor CSV package is ready for guarded intake.",
            next_actions=package.next_actions,
            commands=package.next_commands,
            evidence=evidence,
        )
    if package.status == "WATCH":
        return DataIntakeRoute(
            name="broker_vendor_csv",
            status="WATCH",
            priority=25,
            candidate_scope=["research data cache with documented WATCH evidence"],
            message="Offline broker/vendor CSV package has WATCH evidence.",
            blockers=[f"{item.name}: {item.message}" for item in watch_items],
            next_actions=package.next_actions,
            commands=package.next_commands,
            evidence=evidence,
        )
    return DataIntakeRoute(
        name="broker_vendor_csv",
        status="BLOCK",
        priority=40,
        candidate_scope=["research data cache"],
        message="Offline broker/vendor CSV package is not ready for guarded intake.",
        blockers=blockers,
        next_actions=package.next_actions,
        commands=package.next_commands,
        evidence=evidence,
    )


def _recommended_route(routes: list[DataIntakeRoute]) -> DataIntakeRoute:
    return sorted(routes, key=lambda route: (_status_rank(route.status), route.priority))[0]


def _status_rank(status: IntakeRouteStatus) -> int:
    return {"PASS": 0, "WATCH": 1, "BLOCK": 2}[status]


def _next_actions(route: DataIntakeRoute) -> list[str]:
    prefix = f"Recommended route `{route.name}` is {route.status}: {route.message}"
    return [prefix, *route.next_actions]
