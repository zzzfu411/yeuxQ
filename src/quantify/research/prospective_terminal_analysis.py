"""One-time terminal analysis for an admitted frozen prospective trial.

This module is orchestration only.  It does not alter any packet-bound strategy,
factor, engine, broker, or risk implementation.  Before running it recomputes
prospective admission, then claims the trial exactly once.  The only registry
mutation is one terminal result append after immutable artifacts are published.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
import csv
import gc
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
from typing import Any, Literal
from uuid import uuid4

import pandas as pd
import yaml

from quantify.analytics.metrics import compute_report
from quantify.audit import audit_data, write_data_audit
from quantify.core.portfolio import Portfolio
from quantify.data.demo import is_demo_contaminated
from quantify.data.provider import DataProvider
from quantify.data.storage import BarStorage
from quantify.engine.paper_broker import PaperBroker, PaperBrokerConfig
from quantify.ops.run_manifest import build_run_manifest, write_run_manifest
from quantify.research.benchmark import BenchmarkIdentity, analyze_benchmark
from quantify.research.candidates import (
    CandidateSpec,
    TrendFilteredTargetStrategy,
    candidate_spec_by_name,
)
from quantify.research.engine import ResearchEngine, ResearchResult
from quantify.research.factors import FactorPipeline
from quantify.research.prospective_trial_admission import (
    ProspectiveTrialAdmission,
    build_prospective_trial_admission,
)
from quantify.research.prospective_execution_cache_materialization import (
    build_prospective_execution_cache_materialization_verification,
)
from quantify.research.prospective_trial_packet import (
    build_prospective_trial_packet_verification,
)
from quantify.research.report import research_evidence_digest, write_research_report
from quantify.research.strategy import MultiFactorStrategyConfig, MultiFactorTargetStrategy
from quantify.research.trial_registry import (
    ResultEvent,
    TrialRegistryError,
    append_result,
    verify_registry,
)
from quantify.research.turnover import summarize_turnover
from quantify.research.universe import UniverseConfig, UniverseFilter
from quantify.utils.config import Config

TerminalStatus = Literal["PASS", "BLOCK"]
TerminalDecision = Literal["PASS", "WATCH", "BLOCK"]

ARTIFACT_TYPE = "prospective_terminal_analysis"
SCHEMA_VERSION = 1
ARTIFACT_FILENAME = "prospective_terminal_analysis.json"
MARKDOWN_FILENAME = "prospective_terminal_analysis.md"
CLAIM_FILENAME = "prospective_terminal_analysis.claim.json"
RECEIPT_FILENAME = "prospective_terminal_result_receipt.json"
DERIVED_CONFIG_FILENAME = "terminal_execution_config.yaml"
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z")

PROHIBITED_ACTIONS = (
    "Do not run terminal analysis before deterministic admission PASS.",
    "Do not retry, replace, tune, or select a different candidate after the one-time claim.",
    "Do not edit packet-bound code, parameters, dates, costs, risk limits, or materialized cache.",
    "Do not inspect intermediate results to decide whether to append the terminal result.",
    "Do not treat terminal PASS as paper, micro-live, live-trading, profit, or broker authorization.",
    "Do not generate or submit real broker orders from this workflow.",
)


class ProspectiveTerminalAnalysisError(ValueError):
    """A terminal run cannot be started or completed without weakening evidence."""


@dataclass(frozen=True, slots=True)
class TerminalCheck:
    code: str
    status: TerminalStatus
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "status": self.status, "message": self.message}


@dataclass(frozen=True, slots=True)
class ProspectiveTerminalAnalysis:
    artifact_type: str
    schema_version: int
    status: TerminalStatus
    completed: bool
    decision: TerminalDecision
    evaluated_at_utc: str
    trial_id: str
    candidate: str
    test_start: str
    test_end: str
    admission: dict[str, Any]
    materialization: dict[str, str]
    execution: dict[str, Any]
    primary_metrics: dict[str, Any]
    small_capital_stress: dict[str, Any]
    benchmark_analysis: dict[str, Any]
    data_audit: dict[str, Any]
    evidence_files: dict[str, dict[str, str]]
    checks: tuple[TerminalCheck, ...]
    blockers: tuple[str, ...]
    findings: tuple[str, ...]
    prohibited_actions: tuple[str, ...]
    artifact_sha256: str

    @property
    def sufficient(self) -> bool:
        return self.status == "PASS" and self.completed

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "schema_version": self.schema_version,
            "operation": "one_time_frozen_prospective_terminal_analysis",
            "network_access": False,
            "broker_access": False,
            "paper_trading_allowed": False,
            "live_trading_allowed": False,
            "status": self.status,
            "sufficient": self.sufficient,
            "completed": self.completed,
            "decision": self.decision,
            "evaluated_at_utc": self.evaluated_at_utc,
            "trial_id": self.trial_id,
            "candidate": self.candidate,
            "test_start": self.test_start,
            "test_end": self.test_end,
            "admission": self.admission,
            "materialization": self.materialization,
            "execution": self.execution,
            "primary_metrics": self.primary_metrics,
            "small_capital_stress": self.small_capital_stress,
            "benchmark_analysis": self.benchmark_analysis,
            "data_audit": self.data_audit,
            "evidence_files": self.evidence_files,
            "checks": [item.to_dict() for item in self.checks],
            "blockers": list(self.blockers),
            "findings": list(self.findings),
            "prohibited_actions": list(self.prohibited_actions),
            "artifact_sha256": self.artifact_sha256,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Prospective Terminal Analysis: {self.status}",
            "",
            f"- Trial: `{self.trial_id or 'unavailable'}`",
            f"- Candidate: `{self.candidate or 'unavailable'}`",
            f"- Completed: `{self.completed}`",
            f"- Frozen test: `{self.test_start}` to `{self.test_end}`",
            f"- Terminal decision: `{self.decision}`",
            f"- Artifact SHA-256: `{self.artifact_sha256 or 'unavailable'}`",
            "- Network access: `False`",
            "- Broker access: `False`",
            "",
            "## Checks",
            "",
        ]
        lines.extend(f"- `{item.status}` `{item.code}`: {item.message}" for item in self.checks)
        lines.extend(["", "## Primary Metrics", ""])
        lines.extend(f"- `{key}`: `{value}`" for key, value in self.primary_metrics.items())
        lines.extend(["", "## Findings", ""])
        lines.extend(f"- {item}" for item in self.findings or ("None.",))
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- {item}" for item in self.blockers or ("None.",))
        lines.extend(["", "## Prohibited Actions", ""])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        lines.append("")
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class ProspectiveTerminalAnalysisVerification:
    artifact_type: str
    schema_version: int
    status: TerminalStatus
    trial_id: str
    decision: TerminalDecision
    artifact_path: str
    artifact_sha256: str
    registry_result_event_hash: str
    checks: tuple[TerminalCheck, ...]
    blockers: tuple[str, ...]

    @property
    def sufficient(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "schema_version": self.schema_version,
            "operation": "read_only_prospective_terminal_result_verification",
            "network_access": False,
            "broker_access": False,
            "status": self.status,
            "sufficient": self.sufficient,
            "trial_id": self.trial_id,
            "decision": self.decision,
            "artifact_path": self.artifact_path,
            "artifact_sha256": self.artifact_sha256,
            "registry_result_event_hash": self.registry_result_event_hash,
            "checks": [item.to_dict() for item in self.checks],
            "blockers": list(self.blockers),
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Prospective Terminal Result Verification: {self.status}",
            "",
            f"- Trial: `{self.trial_id or 'unavailable'}`",
            f"- Decision: `{self.decision}`",
            f"- Artifact: `{self.artifact_path}`",
            f"- Artifact canonical SHA-256: `{self.artifact_sha256 or 'unavailable'}`",
            f"- Registry result event hash: `{self.registry_result_event_hash or 'unavailable'}`",
            "- Network access: `False`",
            "- Broker access: `False`",
            "",
            "## Checks",
            "",
        ]
        lines.extend(f"- `{item.status}` `{item.code}`: {item.message}" for item in self.checks)
        lines.extend(["", "## Blockers", ""])
        lines.extend(f"- {item}" for item in self.blockers or ("None.",))
        lines.append("")
        return "\n".join(lines)


def run_prospective_terminal_analysis(
    *,
    packet_dir: str | Path,
    registry_path: str | Path,
    materialization_artifact: str | Path,
    benchmark_csv: str | Path,
    benchmark_metadata: str | Path,
    membership_csv: str | Path,
    membership_metadata: str | Path,
    output_dir: str | Path,
    workspace_root: str | Path | None = None,
    minimum_members_per_snapshot: int = 700,
) -> ProspectiveTerminalAnalysis:
    """Run and register the frozen terminal analysis exactly once."""
    root = _workspace_root(workspace_root)
    packet_root = _resolve_path(packet_dir, root)
    registry = _resolve_path(registry_path, root)
    materialization_path = _resolve_path(materialization_artifact, root)
    output = _resolve_path(output_dir, root)
    now = _runtime_now()
    admission = build_prospective_trial_admission(
        packet_dir=packet_root,
        registry_path=registry,
        benchmark_csv=_resolve_path(benchmark_csv, root),
        benchmark_metadata=_resolve_path(benchmark_metadata, root),
        membership_csv=_resolve_path(membership_csv, root),
        membership_metadata=_resolve_path(membership_metadata, root),
        workspace_root=root,
        minimum_members_per_snapshot=minimum_members_per_snapshot,
        materialization_artifact=materialization_path,
    )
    packet, packet_error = _load_json_object(packet_root / "prospective_trial_packet.json")
    materialization, materialization_error = _load_json_object(materialization_path)
    checks: list[TerminalCheck] = []
    _check(
        checks,
        "TERMINAL_ADMISSION",
        admission.sufficient,
        "Dynamic prospective admission passes for one terminal research run."
        if admission.sufficient
        else "Dynamic prospective admission is BLOCK; terminal execution is prohibited.",
    )
    _check(
        checks,
        "PACKET_JSON",
        not packet_error,
        "Frozen packet JSON is readable and strict."
        if not packet_error
        else f"Frozen packet cannot be read: {packet_error}",
    )
    _check(
        checks,
        "MATERIALIZATION_JSON",
        not materialization_error,
        "Materialization artifact JSON is readable and strict."
        if not materialization_error
        else f"Materialization artifact cannot be read: {materialization_error}",
    )
    trial_id = _text(packet.get("trial_id"))
    candidate = _text(packet.get("candidate"))
    boundaries = packet.get("boundaries") if isinstance(packet.get("boundaries"), dict) else {}
    test = boundaries.get("test") if isinstance(boundaries.get("test"), dict) else {}
    test_start = _text(test.get("start"))
    test_end = _text(test.get("end"))
    materialization_hash = (
        _file_sha256(materialization_path) if materialization_path.is_file() else ""
    )
    materialization_canonical_hash = _text(materialization.get("artifact_sha256"))
    execution_cache = Path(admission.execution_cache_path)
    cache_hash_before = _file_sha256(execution_cache) if execution_cache.is_file() else ""

    cfg, config_errors = _derived_config(packet, execution_cache)
    _check(
        checks,
        "FROZEN_CONFIG_OVERRIDE",
        cfg is not None and not config_errors,
        "Derived config changes only the packet-authorized materialized cache path."
        if cfg is not None and not config_errors
        else "; ".join(config_errors) or "Frozen execution config is invalid.",
    )
    spec: CandidateSpec | None = None
    candidate_ready = False
    if cfg is not None:
        try:
            spec = candidate_spec_by_name(cfg, candidate)
        except (AttributeError, TypeError, ValueError):
            spec = None
        candidate_ready = spec is not None and _candidate_snapshot(spec) == packet.get(
            "candidate_snapshot"
        )
    _check(
        checks,
        "FROZEN_CANDIDATE_SNAPSHOT",
        candidate_ready,
        "Runtime candidate factors and parameters exactly match the frozen snapshot."
        if candidate_ready
        else "Runtime candidate does not exactly match the frozen packet snapshot.",
    )

    quarantine = _materialization_quarantine(materialization, root)
    claim_path = quarantine / CLAIM_FILENAME
    output_ready = not output.exists() and not claim_path.exists()
    _check(
        checks,
        "ONE_TIME_TERMINAL_OUTPUT",
        output_ready,
        "Terminal output and global one-time claim are both unused."
        if output_ready
        else "Terminal output or one-time claim already exists; repeat analysis is prohibited.",
    )
    isolation_ready = _paths_disjoint(
        output,
        packet_root,
        registry,
        materialization_path,
        execution_cache,
        quarantine,
    )
    _check(
        checks,
        "TERMINAL_OUTPUT_ISOLATION",
        isolation_ready,
        "Terminal output is disjoint from packet, registry, cache, materialization, and quarantine."
        if isolation_ready
        else "Terminal output overlaps immutable input or registry paths.",
    )
    blockers = _blockers(checks)
    if blockers:
        return _blocked_report(
            now=now,
            admission=admission,
            trial_id=trial_id,
            candidate=candidate,
            test_start=test_start,
            test_end=test_end,
            materialization_path=materialization_path,
            materialization_hash=materialization_hash,
            materialization_canonical_hash=materialization_canonical_hash,
            checks=checks,
            blockers=blockers,
        )
    if cfg is None or spec is None:  # pragma: no cover - guarded above
        raise ProspectiveTerminalAnalysisError("terminal config/candidate invariant failed")

    claim_payload = {
        "artifact_type": "prospective_terminal_analysis_claim",
        "schema_version": 1,
        "trial_id": trial_id,
        "candidate": candidate,
        "output_dir": str(output),
        "materialization_artifact_sha256": materialization_hash,
        "materialization_canonical_sha256": materialization_canonical_hash,
        "execution_cache_sha256": cache_hash_before,
        "terminal_orchestrator_sha256": _file_sha256(Path(__file__)),
        "claimed_at_utc": now.replace(microsecond=0).isoformat(),
        "one_time": True,
    }
    claim_bytes = _canonical_json(claim_payload)
    try:
        with claim_path.open("xb") as handle:
            if handle.write(claim_bytes) != len(claim_bytes):  # pragma: no cover
                raise OSError("short terminal-claim write")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ProspectiveTerminalAnalysisError(
            "terminal analysis claim already exists; rerun is prohibited"
        ) from exc

    staging = output.with_name(f".{output.name}.{uuid4().hex}.tmp")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging.mkdir()
    try:
        derived_config = staging / DERIVED_CONFIG_FILENAME
        derived_config.write_text(
            yaml.safe_dump(cfg.to_dict(), sort_keys=False),
            encoding="utf-8",
        )
        storage = BarStorage(execution_cache)
        provider = DataProvider(storage)
        primary_result, trend_days = _run_candidate(
            provider,
            cfg,
            spec,
            initial_cash=float(cfg.research.initial_cash),
            start=test_start,
            end=test_end,
        )
        stress_result, stress_trend_days = _run_candidate(
            provider,
            cfg,
            spec,
            initial_cash=100_000.0,
            start=test_start,
            end=test_end,
        )
        primary_metrics = compute_report(
            primary_result.equity_curve,
            primary_result.fills,
            initial_equity=primary_result.portfolio.initial_cash,
        ).to_dict()
        stress_metrics = compute_report(
            stress_result.equity_curve,
            stress_result.fills,
            initial_equity=stress_result.portfolio.initial_cash,
        ).to_dict()
        primary_execution = _execution_summary(primary_result, trend_days)
        stress_execution = _execution_summary(stress_result, stress_trend_days)
        stress = {"metrics": stress_metrics, **stress_execution}
        benchmark = _benchmark_analysis(
            primary_result,
            admission,
            test_start=test_start,
            test_end=test_end,
        )
        audit = audit_data(
            provider,
            test_start,
            test_end,
            data_source=str(cfg.data.source),
            cache_path=str(execution_cache),
            demo_data_used=is_demo_contaminated(provider.all_symbols()),
        )
        decision, findings = _decision(
            primary_metrics,
            primary_execution,
            stress,
            benchmark.to_dict(),
            audit.status,
            max_drawdown_stop=float(cfg.risk.max_drawdown_stop),
        )
        manifest = build_run_manifest(
            provider,
            cfg,
            storage=storage,
            config_path=derived_config,
            purpose="prospective_terminal_holdout",
            demo_data_used=is_demo_contaminated(provider.all_symbols()),
        )
        manifest = replace(
            manifest,
            config_path=str(output / DERIVED_CONFIG_FILENAME),
            config_sha256=_file_sha256(derived_config),
        )
        assumptions = {
            "trial_id": trial_id,
            "candidate": candidate,
            "test_start": test_start,
            "test_end": test_end,
            "initial_cash": float(cfg.research.initial_cash),
            "cache_path": str(execution_cache),
            "materialization_artifact_sha256": materialization_hash,
            "one_time_terminal_analysis": True,
            "notice": "Frozen prospective research only; no broker or live-trading authorization.",
        }
        write_research_report(
            primary_result,
            staging,
            title=f"Frozen prospective terminal trial: {trial_id}",
            assumptions=assumptions,
            evidence=research_evidence_digest(audit=audit, manifest=manifest),
        )
        write_data_audit(audit, staging)
        write_run_manifest(manifest, staging)
        (staging / "benchmark_analysis.json").write_text(
            json.dumps(benchmark.to_dict(), ensure_ascii=False, allow_nan=False, indent=2),
            encoding="utf-8",
        )
        (staging / "small_capital_stress.json").write_text(
            json.dumps(stress, ensure_ascii=False, allow_nan=False, indent=2),
            encoding="utf-8",
        )
        (staging / "prospective_trial_admission.json").write_text(
            json.dumps(admission.to_dict(), ensure_ascii=False, allow_nan=False, indent=2),
            encoding="utf-8",
        )
        cache_hash_after = _file_sha256(execution_cache)
        if cache_hash_after != cache_hash_before:
            raise ProspectiveTerminalAnalysisError(
                "materialized execution cache changed during terminal analysis"
            )
        evidence_files = _evidence_files(staging, published_root=output)
        report = _completed_report(
            now=now,
            admission=admission,
            trial_id=trial_id,
            candidate=candidate,
            test_start=test_start,
            test_end=test_end,
            materialization_path=materialization_path,
            materialization_hash=materialization_hash,
            materialization_canonical_hash=materialization_canonical_hash,
            execution_cache=execution_cache,
            cache_hash=cache_hash_after,
            claim_path=claim_path,
            claim_sha256=hashlib.sha256(claim_bytes).hexdigest(),
            primary_metrics=primary_metrics,
            primary_execution=primary_execution,
            stress=stress,
            benchmark=benchmark.to_dict(),
            audit=audit.to_dict(),
            evidence_files=evidence_files,
            checks=checks,
            decision=decision,
            findings=findings,
        )
        (staging / ARTIFACT_FILENAME).write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, allow_nan=False, indent=2),
            encoding="utf-8",
        )
        (staging / MARKDOWN_FILENAME).write_text(report.to_markdown(), encoding="utf-8")
        if output.exists():
            raise ProspectiveTerminalAnalysisError(
                "terminal output appeared after claim; replacement is prohibited"
            )
        _publish_directory(staging, output)
        artifact_file_hash = _file_sha256(output / ARTIFACT_FILENAME)
        event = append_result(
            registry,
            trial_id=trial_id,
            result={
                "artifact_type": "prospective_terminal_result",
                "schema_version": 1,
                "decision": decision,
                "terminal_artifact_sha256": report.artifact_sha256,
                "terminal_artifact_file_sha256": artifact_file_hash,
                "materialization_artifact_sha256": materialization_hash,
                "execution_cache_sha256": cache_hash_after,
                "summary_sha256": _file_sha256(output / "summary.json"),
                "benchmark_analysis_sha256": _file_sha256(output / "benchmark_analysis.json"),
                "run_manifest_sha256": _file_sha256(output / "run_manifest.json"),
                "test_start": test_start,
                "test_end": test_end,
                "total_return": primary_metrics["total_return"],
                "max_drawdown": primary_metrics["max_drawdown"],
            },
            created_at=now.replace(microsecond=0).isoformat(),
        )
        _write_receipt(output, report, event, artifact_file_hash)
        return report
    except Exception:
        if staging.exists():
            _remove_tree(staging)
        raise


def build_prospective_terminal_analysis_verification(
    artifact_path: str | Path,
    *,
    packet_dir: str | Path,
    registry_path: str | Path,
    materialization_artifact: str | Path,
    workspace_root: str | Path | None = None,
) -> ProspectiveTerminalAnalysisVerification:
    """Verify the single published result without rerunning the strategy."""
    root = _workspace_root(workspace_root)
    artifact_file = _resolve_path(artifact_path, root)
    packet_root = _resolve_path(packet_dir, root)
    registry = _resolve_path(registry_path, root)
    materialization_path = _resolve_path(materialization_artifact, root)
    payload, payload_error = _load_json_object(artifact_file)
    checks: list[TerminalCheck] = []
    contract_ready = (
        not payload_error
        and payload.get("artifact_type") == ARTIFACT_TYPE
        and payload.get("schema_version") == SCHEMA_VERSION
        and payload.get("operation") == "one_time_frozen_prospective_terminal_analysis"
        and payload.get("status") == "PASS"
        and payload.get("sufficient") is True
        and payload.get("completed") is True
        and payload.get("decision") in {"PASS", "WATCH", "BLOCK"}
        and payload.get("network_access") is False
        and payload.get("broker_access") is False
        and payload.get("paper_trading_allowed") is False
        and payload.get("live_trading_allowed") is False
    )
    _check(
        checks,
        "TERMINAL_ARTIFACT_CONTRACT",
        contract_ready,
        "Terminal artifact contract, completion state, and safety flags verify."
        if contract_ready
        else payload_error or "Terminal artifact contract or safety flags are invalid.",
    )
    claimed_hash = _text(payload.get("artifact_sha256"))
    body = {key: value for key, value in payload.items() if key != "artifact_sha256"}
    actual_hash = _canonical_sha256(body) if payload else ""
    artifact_hash_ready = _valid_hash(claimed_hash) and claimed_hash == actual_hash
    _check(
        checks,
        "TERMINAL_ARTIFACT_SHA256",
        artifact_hash_ready,
        "Terminal artifact canonical SHA-256 matches."
        if artifact_hash_ready
        else "Terminal artifact canonical SHA-256 mismatch.",
    )

    packet_verification = build_prospective_trial_packet_verification(
        packet_root,
        registry,
        workspace_root=root,
    )
    trial_id = _text(payload.get("trial_id"))
    packet_ready = packet_verification.status == "PASS" and packet_verification.trial_id == trial_id
    _check(
        checks,
        "TERMINAL_PACKET_BINDING",
        packet_ready,
        "Frozen packet, code bindings, prefix, and preregistration still verify."
        if packet_ready
        else "Frozen packet or terminal trial binding no longer verifies.",
    )
    materialization_verification = build_prospective_execution_cache_materialization_verification(
        materialization_path,
        packet_dir=packet_root,
        registry_path=registry,
        workspace_root=root,
    )
    materialization = (
        payload.get("materialization") if isinstance(payload.get("materialization"), dict) else {}
    )
    materialization_ready = (
        materialization_verification.status == "PASS"
        and Path(_text(materialization.get("path"))).resolve() == materialization_path.resolve()
        and _text(materialization.get("file_sha256")) == _file_sha256(materialization_path)
    )
    _check(
        checks,
        "TERMINAL_MATERIALIZATION_BINDING",
        materialization_ready,
        "Post-holdout materialization and exact file binding still verify."
        if materialization_ready
        else "Materialization artifact, cache, claim, or terminal binding changed.",
    )

    output_root = artifact_file.parent
    evidence = payload.get("evidence_files")
    evidence_ready = isinstance(evidence, dict) and bool(evidence)
    if evidence_ready:
        for name, item in evidence.items():
            if not isinstance(name, str) or not isinstance(item, dict):
                evidence_ready = False
                break
            path = Path(_text(item.get("path")))
            if (
                path.resolve() != (output_root / name).resolve()
                or not path.is_file()
                or _file_sha256(path) != _text(item.get("sha256"))
            ):
                evidence_ready = False
                break
    _check(
        checks,
        "TERMINAL_EVIDENCE_FILES",
        evidence_ready,
        "Every terminal report/config file matches its final path and SHA-256."
        if evidence_ready
        else "One or more terminal evidence files are missing, moved, or changed.",
    )

    execution = payload.get("execution") if isinstance(payload.get("execution"), dict) else {}
    execution_cache = Path(_text(execution.get("cache_path")) or "__missing_cache__")
    cache_ready = (
        execution_cache.resolve() == Path(materialization_verification.output_cache_path).resolve()
        and execution_cache.is_file()
        and _file_sha256(execution_cache) == _text(execution.get("cache_sha256"))
    )
    _check(
        checks,
        "TERMINAL_EXECUTION_CACHE",
        cache_ready,
        "Terminal execution cache path and bytes match materialization."
        if cache_ready
        else "Terminal execution cache path or SHA-256 changed.",
    )

    claim_path = Path(_text(execution.get("claim_path")) or "__missing_claim__")
    claim, claim_error = _load_json_object(claim_path)
    claim_ready = (
        not claim_error
        and claim.get("artifact_type") == "prospective_terminal_analysis_claim"
        and claim.get("schema_version") == 1
        and claim.get("trial_id") == trial_id
        and claim.get("candidate") == payload.get("candidate")
        and Path(_text(claim.get("output_dir"))).resolve() == output_root.resolve()
        and claim.get("materialization_artifact_sha256") == materialization.get("file_sha256")
        and claim.get("execution_cache_sha256") == execution.get("cache_sha256")
        and claim.get("claimed_at_utc") == payload.get("evaluated_at_utc")
        and claim.get("one_time") is True
        and _file_sha256(claim_path) == _text(execution.get("claim_sha256"))
    )
    _check(
        checks,
        "ONE_TIME_TERMINAL_CLAIM",
        claim_ready,
        "Global one-time terminal claim is intact and bound to this output."
        if claim_ready
        else claim_error or "Global one-time terminal claim is inconsistent.",
    )

    packet, _ = _load_json_object(packet_root / "prospective_trial_packet.json")
    risk = packet.get("execution_config", {}).get("risk", {})
    max_drawdown_stop = float(risk.get("max_drawdown_stop") or 0.0)
    expected_decision, expected_findings = _decision(
        payload.get("primary_metrics") if isinstance(payload.get("primary_metrics"), dict) else {},
        execution,
        payload.get("small_capital_stress")
        if isinstance(payload.get("small_capital_stress"), dict)
        else {},
        payload.get("benchmark_analysis")
        if isinstance(payload.get("benchmark_analysis"), dict)
        else {},
        _text(
            payload.get("data_audit", {}).get("status")
            if isinstance(payload.get("data_audit"), dict)
            else ""
        ),
        max_drawdown_stop=max_drawdown_stop,
    )
    decision_ready = payload.get("decision") == expected_decision and payload.get(
        "findings"
    ) == list(expected_findings)
    _check(
        checks,
        "TERMINAL_DECISION_RECOMPUTATION",
        decision_ready,
        "Terminal PASS/WATCH/BLOCK decision recomputes from retained metrics."
        if decision_ready
        else "Terminal decision or findings disagree with retained metrics.",
    )

    registry_error = ""
    try:
        events = verify_registry(registry)
    except (OSError, TrialRegistryError) as exc:
        events = []
        registry_error = f"{type(exc).__name__}: {exc}"
    results = [
        event for event in events if isinstance(event, ResultEvent) and event.trial_id == trial_id
    ]
    result_event = results[0] if len(results) == 1 else None
    artifact_file_hash = _file_sha256(artifact_file) if artifact_file.is_file() else ""
    registry_ready = (
        not registry_error
        and result_event is not None
        and result_event.result.get("decision") == payload.get("decision")
        and result_event.result.get("terminal_artifact_sha256") == claimed_hash
        and result_event.result.get("terminal_artifact_file_sha256") == artifact_file_hash
        and result_event.result.get("execution_cache_sha256") == execution.get("cache_sha256")
        and result_event.created_at == payload.get("evaluated_at_utc")
    )
    _check(
        checks,
        "UNIQUE_REGISTRY_RESULT",
        registry_ready,
        "Exactly one registry result is hash-bound to this terminal artifact."
        if registry_ready
        else registry_error or f"Expected one matching result; found {len(results)}.",
    )

    receipt_path = output_root / RECEIPT_FILENAME
    receipt, receipt_error = _load_json_object(receipt_path)
    receipt_ready = (
        not receipt_error
        and result_event is not None
        and receipt.get("artifact_type") == "prospective_terminal_result_receipt"
        and receipt.get("trial_id") == trial_id
        and receipt.get("decision") == payload.get("decision")
        and receipt.get("terminal_artifact_sha256") == claimed_hash
        and receipt.get("terminal_artifact_file_sha256") == artifact_file_hash
        and receipt.get("registry_result_id") == result_event.result_id
        and receipt.get("registry_sequence") == result_event.sequence
        and receipt.get("registry_event_hash") == result_event.event_hash
        and receipt.get("broker_access") is False
        and receipt.get("live_trading_allowed") is False
    )
    _check(
        checks,
        "TERMINAL_RESULT_RECEIPT",
        receipt_ready,
        "Terminal receipt matches the unique registry event and artifact hashes."
        if receipt_ready
        else receipt_error or "Terminal receipt is missing or inconsistent.",
    )
    blockers = _blockers(checks)
    decision = (
        payload.get("decision")
        if payload.get("decision") in {"PASS", "WATCH", "BLOCK"}
        else "BLOCK"
    )
    return ProspectiveTerminalAnalysisVerification(
        artifact_type="prospective_terminal_analysis_verification",
        schema_version=1,
        status="BLOCK" if blockers else "PASS",
        trial_id=trial_id,
        decision=decision,
        artifact_path=str(artifact_file),
        artifact_sha256=actual_hash,
        registry_result_event_hash=result_event.event_hash if result_event is not None else "",
        checks=tuple(checks),
        blockers=blockers,
    )


def write_prospective_terminal_analysis_verification(
    verification: ProspectiveTerminalAnalysisVerification,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "prospective_terminal_analysis_verification.json").write_text(
        json.dumps(
            verification.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (root / "prospective_terminal_analysis_verification.md").write_text(
        verification.to_markdown(),
        encoding="utf-8",
    )
    return root


def _run_candidate(
    data: DataProvider,
    cfg: Config,
    spec: CandidateSpec,
    *,
    initial_cash: float,
    start: str,
    end: str,
) -> tuple[ResearchResult, int]:
    pipeline = FactorPipeline(factors=spec.factors)
    universe = UniverseFilter(
        UniverseConfig(
            mode=cfg.universe.mode,
            index_code=cfg.universe.index_code,
            include_st=cfg.universe.include_st,
            min_history_days=cfg.universe.min_history_days,
        )
    )
    strategy_config = MultiFactorStrategyConfig(
        n_holdings=spec.n_holdings,
        max_weight=spec.max_weight,
        hold_rank_buffer=spec.hold_rank_buffer,
        min_trade_weight=spec.min_trade_weight,
        max_new_positions=spec.max_new_positions,
        score_smoothing_observations=spec.score_smoothing_observations,
        score_smoothing_step_days=spec.score_smoothing_step_days,
    )
    strategy: MultiFactorTargetStrategy
    if spec.trend_filter:
        strategy = TrendFilteredTargetStrategy(
            universe,
            pipeline,
            strategy_config,
            trend_scale=spec.trend_scale,
            trend_gate=spec.trend_gate,
        )
    else:
        strategy = MultiFactorTargetStrategy(universe, pipeline, strategy_config)
    broker = PaperBroker(
        PaperBrokerConfig(
            commission_rate=cfg.broker.commission_rate,
            min_commission=cfg.broker.min_commission,
            stamp_tax=cfg.broker.stamp_tax,
            slippage_bps=cfg.broker.slippage_bps,
            price_limit_pct=cfg.broker.price_limit_pct,
            lot_size=cfg.broker.lot_size,
        )
    )
    result = ResearchEngine(
        data,
        strategy,
        broker,
        Portfolio(initial_cash=initial_cash),
        pipeline,
        max_drawdown_stop=cfg.risk.max_drawdown_stop,
    ).run(start, end, rebalance=spec.rebalance)
    return result, int(getattr(strategy, "active_days", 0))


def _benchmark_analysis(
    result: ResearchResult,
    admission: ProspectiveTrialAdmission,
    *,
    test_start: str,
    test_end: str,
):
    market = admission.market_evidence
    metadata = market.benchmark_metadata
    benchmark_path = Path(market.benchmark_csv.file.path)
    rows: list[tuple[str, float]] = []
    with benchmark_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            date_text = _text(row.get("date"))
            if test_start <= date_text <= test_end:
                rows.append((date_text, float(row["value"])))
    benchmark_series = pd.Series(
        [value for _, value in rows],
        index=pd.DatetimeIndex([date_text for date_text, _ in rows]),
        dtype=float,
    )
    strategy_series = pd.Series(
        [equity for _, equity in result.equity_curve],
        index=pd.DatetimeIndex([timestamp for timestamp, _ in result.equity_curve]),
        dtype=float,
    )
    return analyze_benchmark(
        strategy_series,
        benchmark_series,
        BenchmarkIdentity(
            symbol=_text(metadata.get("symbol")),
            name=_text(metadata.get("name")),
            total_return=metadata.get("total_return") is True,
        ),
        strategy_series_kind="equity",
        benchmark_series_kind="equity",
        periods_per_year=252,
        block_size=5,
        n_bootstrap=1_000,
        random_seed=0,
    )


def _execution_summary(result: ResearchResult, trend_days: int) -> dict[str, Any]:
    order_count = len(result.orders)
    rejects = [order for order in result.orders if order.status == "rejected"]
    turnover = summarize_turnover(result.turnover)
    return {
        "initial_cash": result.portfolio.initial_cash,
        "order_count": order_count,
        "reject_count": len(rejects),
        "reject_rate": len(rejects) / order_count if order_count else 0.0,
        "below_lot_reject_count": sum(order.reason == "below_lot" for order in rejects),
        "fill_count": len(result.fills),
        "trend_filter_active_days": trend_days,
        **turnover,
    }


def _decision(
    metrics: dict[str, Any],
    execution: dict[str, Any],
    stress: dict[str, Any],
    benchmark: dict[str, Any],
    audit_status: str,
    *,
    max_drawdown_stop: float,
) -> tuple[TerminalDecision, tuple[str, ...]]:
    findings: list[str] = []
    hard_block = False
    if audit_status != "PASS":
        hard_block = True
        findings.append(f"Terminal data audit is {audit_status}; PASS is required.")
    if float(metrics.get("max_drawdown") or 0.0) > max_drawdown_stop:
        hard_block = True
        findings.append("Fresh-holdout maximum drawdown exceeds the frozen risk limit.")
    if float(stress.get("metrics", {}).get("max_drawdown") or 0.0) > max_drawdown_stop:
        hard_block = True
        findings.append("CNY 100,000 stress drawdown exceeds the frozen risk limit.")
    if float(stress.get("reject_rate") or 0.0) >= 0.50:
        hard_block = True
        findings.append("CNY 100,000 execution reject rate is at least 50%.")
    if float(metrics.get("total_return") or 0.0) <= 0.0:
        hard_block = True
        findings.append("Fresh-holdout total return is non-positive.")
    if benchmark.get("status") == "BLOCK":
        hard_block = True
        findings.append("Formal benchmark analysis is BLOCK.")
    benchmark_metrics = benchmark.get("metrics", {})
    if (
        benchmark_metrics.get("excess_cagr") is not None
        and float(benchmark_metrics["excess_cagr"]) <= 0.0
    ):
        hard_block = True
        findings.append("Fresh-holdout benchmark excess CAGR is non-positive.")
    if hard_block:
        return "BLOCK", tuple(findings)
    excess_interval = benchmark.get("annualized_excess_return_ci", {})
    lower = excess_interval.get("lower")
    if benchmark.get("status") == "WATCH" or lower is None or float(lower) <= 0.0:
        findings.append("Benchmark-relative evidence is positive but not statistically decisive.")
        return "WATCH", tuple(findings)
    if float(execution.get("reject_rate") or 0.0) >= 0.20:
        findings.append("Primary execution reject rate is elevated.")
        return "WATCH", tuple(findings)
    findings.append("Frozen efficacy, risk, benchmark, and small-capital checks pass.")
    return "PASS", tuple(findings)


def _derived_config(
    packet: dict[str, Any],
    execution_cache: Path,
) -> tuple[Config | None, list[str]]:
    frozen = packet.get("execution_config")
    if not isinstance(frozen, dict):
        return None, ["Packet execution_config is missing."]
    payload = json.loads(json.dumps(frozen))
    data = payload.get("data")
    if not isinstance(data, dict):
        return None, ["Packet execution_config.data is missing."]
    data["cache_path"] = str(execution_cache)
    materialized = json.loads(json.dumps(payload))
    materialized["data"]["cache_path"] = frozen.get("data", {}).get("cache_path")
    if materialized != frozen:
        return None, ["Derived config changed fields other than data.cache_path."]
    return Config(payload), []


def _candidate_snapshot(spec: CandidateSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "description": spec.description,
        "factors": [
            {
                "class": f"{factor.__class__.__module__}.{factor.__class__.__qualname__}",
                "name": factor.name,
                "higher_is_better": factor.higher_is_better,
            }
            for factor in spec.factors
        ],
        "n_holdings": spec.n_holdings,
        "max_weight": spec.max_weight,
        "rebalance": spec.rebalance,
        "trend_filter": spec.trend_filter,
        "trend_scale": spec.trend_scale,
        "trend_gate": spec.trend_gate,
        "data_dependency": spec.data_dependency,
        "hold_rank_buffer": spec.hold_rank_buffer,
        "min_trade_weight": spec.min_trade_weight,
        "max_new_positions": spec.max_new_positions,
        "score_smoothing_observations": spec.score_smoothing_observations,
        "score_smoothing_step_days": spec.score_smoothing_step_days,
    }


def _completed_report(
    *,
    now: datetime,
    admission: ProspectiveTrialAdmission,
    trial_id: str,
    candidate: str,
    test_start: str,
    test_end: str,
    materialization_path: Path,
    materialization_hash: str,
    materialization_canonical_hash: str,
    execution_cache: Path,
    cache_hash: str,
    claim_path: Path,
    claim_sha256: str,
    primary_metrics: dict[str, Any],
    primary_execution: dict[str, Any],
    stress: dict[str, Any],
    benchmark: dict[str, Any],
    audit: dict[str, Any],
    evidence_files: dict[str, dict[str, str]],
    checks: list[TerminalCheck],
    decision: TerminalDecision,
    findings: tuple[str, ...],
) -> ProspectiveTerminalAnalysis:
    materialization = {
        "path": str(materialization_path),
        "file_sha256": materialization_hash,
        "canonical_sha256": materialization_canonical_hash,
    }
    execution = {
        "cache_path": str(execution_cache),
        "cache_sha256": cache_hash,
        "claim_path": str(claim_path),
        "claim_sha256": claim_sha256,
        **primary_execution,
    }
    body = _report_body(
        status="PASS",
        completed=True,
        decision=decision,
        now=now,
        trial_id=trial_id,
        candidate=candidate,
        test_start=test_start,
        test_end=test_end,
        admission=admission.to_dict(),
        materialization=materialization,
        execution=execution,
        primary_metrics=primary_metrics,
        stress=stress,
        benchmark=benchmark,
        audit=audit,
        evidence_files=evidence_files,
        checks=checks,
        blockers=(),
        findings=findings,
    )
    artifact_hash = _canonical_sha256(body)
    return ProspectiveTerminalAnalysis(
        artifact_type=ARTIFACT_TYPE,
        schema_version=SCHEMA_VERSION,
        status="PASS",
        completed=True,
        decision=decision,
        evaluated_at_utc=body["evaluated_at_utc"],
        trial_id=trial_id,
        candidate=candidate,
        test_start=test_start,
        test_end=test_end,
        admission=body["admission"],
        materialization=materialization,
        execution=execution,
        primary_metrics=primary_metrics,
        small_capital_stress=stress,
        benchmark_analysis=benchmark,
        data_audit=audit,
        evidence_files=evidence_files,
        checks=tuple(checks),
        blockers=(),
        findings=findings,
        prohibited_actions=PROHIBITED_ACTIONS,
        artifact_sha256=artifact_hash,
    )


def _blocked_report(
    *,
    now: datetime,
    admission: ProspectiveTrialAdmission,
    trial_id: str,
    candidate: str,
    test_start: str,
    test_end: str,
    materialization_path: Path,
    materialization_hash: str,
    materialization_canonical_hash: str,
    checks: list[TerminalCheck],
    blockers: tuple[str, ...],
) -> ProspectiveTerminalAnalysis:
    return ProspectiveTerminalAnalysis(
        artifact_type=ARTIFACT_TYPE,
        schema_version=SCHEMA_VERSION,
        status="BLOCK",
        completed=False,
        decision="BLOCK",
        evaluated_at_utc=now.replace(microsecond=0).isoformat(),
        trial_id=trial_id,
        candidate=candidate,
        test_start=test_start,
        test_end=test_end,
        admission=admission.to_dict(),
        materialization={
            "path": str(materialization_path),
            "file_sha256": materialization_hash,
            "canonical_sha256": materialization_canonical_hash,
        },
        execution={},
        primary_metrics={},
        small_capital_stress={},
        benchmark_analysis={},
        data_audit={},
        evidence_files={},
        checks=tuple(checks),
        blockers=blockers,
        findings=(),
        prohibited_actions=PROHIBITED_ACTIONS,
        artifact_sha256="",
    )


def _report_body(
    *,
    status: str,
    completed: bool,
    decision: str,
    now: datetime,
    trial_id: str,
    candidate: str,
    test_start: str,
    test_end: str,
    admission: dict[str, Any],
    materialization: dict[str, Any],
    execution: dict[str, Any],
    primary_metrics: dict[str, Any],
    stress: dict[str, Any],
    benchmark: dict[str, Any],
    audit: dict[str, Any],
    evidence_files: dict[str, Any],
    checks: list[TerminalCheck],
    blockers: tuple[str, ...],
    findings: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "artifact_type": ARTIFACT_TYPE,
        "schema_version": SCHEMA_VERSION,
        "operation": "one_time_frozen_prospective_terminal_analysis",
        "network_access": False,
        "broker_access": False,
        "paper_trading_allowed": False,
        "live_trading_allowed": False,
        "status": status,
        "sufficient": status == "PASS" and completed,
        "completed": completed,
        "decision": decision,
        "evaluated_at_utc": now.replace(microsecond=0).isoformat(),
        "trial_id": trial_id,
        "candidate": candidate,
        "test_start": test_start,
        "test_end": test_end,
        "admission": admission,
        "materialization": materialization,
        "execution": execution,
        "primary_metrics": primary_metrics,
        "small_capital_stress": stress,
        "benchmark_analysis": benchmark,
        "data_audit": audit,
        "evidence_files": evidence_files,
        "checks": [item.to_dict() for item in checks],
        "blockers": list(blockers),
        "findings": list(findings),
        "prohibited_actions": list(PROHIBITED_ACTIONS),
    }


def _evidence_files(
    root: Path,
    *,
    published_root: Path,
) -> dict[str, dict[str, str]]:
    names = (
        "summary.json",
        "equity.csv",
        "orders.csv",
        "trades.csv",
        "positions.csv",
        "turnover.csv",
        "factor_ic.csv",
        "data_audit.json",
        "run_manifest.json",
        "benchmark_analysis.json",
        "small_capital_stress.json",
        "prospective_trial_admission.json",
        DERIVED_CONFIG_FILENAME,
    )
    return {
        name: {
            "path": str(published_root / name),
            "sha256": _file_sha256(root / name),
        }
        for name in names
    }


def _write_receipt(
    output: Path,
    report: ProspectiveTerminalAnalysis,
    event: ResultEvent,
    artifact_file_hash: str,
) -> None:
    payload = {
        "artifact_type": "prospective_terminal_result_receipt",
        "schema_version": 1,
        "trial_id": report.trial_id,
        "decision": report.decision,
        "terminal_artifact_sha256": report.artifact_sha256,
        "terminal_artifact_file_sha256": artifact_file_hash,
        "registry_result_id": event.result_id,
        "registry_sequence": event.sequence,
        "registry_event_hash": event.event_hash,
        "broker_access": False,
        "live_trading_allowed": False,
    }
    (output / RECEIPT_FILENAME).write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2),
        encoding="utf-8",
    )


def _materialization_quarantine(payload: dict[str, Any], root: Path) -> Path:
    inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
    raw = _text(inputs.get("quarantine_root"))
    return _resolve_path(raw or "__missing_quarantine__", root)


def _check(checks: list[TerminalCheck], code: str, passed: bool, message: str) -> None:
    checks.append(TerminalCheck(code, "PASS" if passed else "BLOCK", message))


def _blockers(checks: list[TerminalCheck]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.message for item in checks if item.status == "BLOCK"))


def _paths_disjoint(output: Path, *inputs: Path) -> bool:
    target = output.resolve()
    for item in inputs:
        resolved = item.resolve()
        if target == resolved:
            return False
        try:
            target.relative_to(resolved)
        except ValueError:
            pass
        else:
            return False
        try:
            resolved.relative_to(target)
        except ValueError:
            pass
        else:
            return False
    return True


def _publish_directory(staging: Path, output: Path) -> None:
    gc.collect()
    for attempt in range(10):
        try:
            os.replace(staging, output)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.05 * (attempt + 1))


def _remove_tree(path: Path) -> None:
    gc.collect()
    for attempt in range(10):
        try:
            shutil.rmtree(path)
            return
        except PermissionError:
            if attempt == 9:
                return
            time.sleep(0.05 * (attempt + 1))


def _load_json_object(path: Path) -> tuple[dict[str, Any], str]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return {}, f"{type(exc).__name__}: {exc}"
    if not isinstance(payload, dict):
        return {}, "JSON root is not an object"
    return payload, ""


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError(f"duplicate JSON key {key!r}")
        output[key] = value
    return output


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value!r}")


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and _HASH_PATTERN.fullmatch(value) is not None


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _workspace_root(value: str | Path | None) -> Path:
    if value is not None:
        return Path(value).resolve()
    return Path(__file__).resolve().parents[3]


def _resolve_path(value: str | Path, root: Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _runtime_now() -> datetime:
    return datetime.now(UTC)
