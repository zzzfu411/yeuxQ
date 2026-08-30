from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quantify.research.benchmark_report import (
    build_benchmark_review_report,
    write_benchmark_review_report,
)
from quantify.research.multiple_testing import (
    build_multiple_testing_report,
    write_multiple_testing_report,
)
from quantify.research.selection_evidence import (
    build_selection_evidence_manifest,
    write_selection_evidence_manifest,
)
from quantify.research.trial_registry import append_preregistration, append_result
from quantify.research.trial_registry_review import (
    REQUIRED_EVIDENCE_FILES,
    build_trial_registry_review,
    write_trial_registry_review,
)


def write_statistical_evidence_fixtures(
    root: Path,
    *,
    candidate: str = "core_multifactor",
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    manifest = _normalize_run_manifest(root)
    _normalize_candidate_selection(root, candidate)
    _ensure_required_trial_artifacts(root)
    write_selection_evidence_manifest(build_selection_evidence_manifest(root), root)
    _write_multiple_testing(root, candidate)
    _write_benchmark(root, str(manifest["research_parameters"]["index_code"]))
    registry = root / "trial_registry.jsonl"
    _write_bound_trial(registry, root, manifest, candidate)
    review = build_trial_registry_review(registry, root, selected_candidate=candidate)
    assert review.status == "PASS", review.blockers
    write_trial_registry_review(review, root)


def _normalize_run_manifest(root: Path) -> dict[str, Any]:
    path = root / "run_manifest.json"
    payload = _read_json(path)
    if not str(payload.get("created_at_utc") or "").strip():
        payload["created_at_utc"] = "2026-07-15T09:00:00+00:00"
    if not str(payload.get("config_sha256") or "").strip():
        payload["config_sha256"] = "test-config-fingerprint"
    if not str(payload.get("cache_sha256") or "").strip():
        payload["cache_sha256"] = "test-cache-fingerprint"
    payload.setdefault("start", "2024-01-01")
    payload.setdefault("end", "2024-12-31")
    payload.setdefault("in_sample_end", "2024-06-30")
    payload.setdefault("out_sample_start", "2024-07-01")
    if not _ordered_manifest_dates(payload):
        payload.update(
            {
                "start": "2024-01-01",
                "in_sample_end": "2024-06-30",
                "out_sample_start": "2024-07-01",
                "end": "2024-12-31",
            }
        )
    version = payload.get("data_version")
    if not isinstance(version, dict):
        version = {}
    if not any(
        str(version.get(key) or "").strip()
        for key in (
            "cache_logical_bar_fingerprint",
            "csv_dataset_fingerprint",
            "raw_vendor_bars_sha256",
        )
    ):
        version["cache_logical_bar_fingerprint"] = "test-logical-data-fingerprint"
    payload["data_version"] = version
    parameters = payload.get("research_parameters")
    if not isinstance(parameters, dict):
        parameters = {}
    if not str(parameters.get("index_code") or "").strip():
        parameters["index_code"] = "000906"
    payload["research_parameters"] = parameters
    _write_json(path, payload)
    return payload


def _normalize_candidate_selection(root: Path, candidate: str) -> None:
    path = root / "candidate_selection.json"
    payload = _read_json(path)
    payload.setdefault("status", "PASS")
    payload["selected_candidate"] = candidate
    payload.setdefault("best_candidate", candidate)
    _write_json(path, payload)


def _ensure_required_trial_artifacts(root: Path) -> None:
    for filename in REQUIRED_EVIDENCE_FILES:
        path = root / filename
        if not path.exists():
            _write_json(path, {"status": "PASS", "artifact": filename})


def _write_multiple_testing(root: Path, candidate: str) -> None:
    input_path = root / "frozen_trial_returns.csv"
    pattern = np.array([-0.0015, -0.0010, -0.0005, 0.0, 0.0005, 0.0010, 0.0015, 0.0020])
    repeated = np.tile(pattern, 8)
    pd.DataFrame(
        {
            candidate: 0.0040 + repeated,
            "stable_middle": 0.0015 + repeated * 1.4,
            "stable_weak": -0.0010 + repeated * 1.8,
        },
        index=pd.date_range("2024-01-01", periods=len(repeated), freq="D"),
    ).to_csv(input_path, index_label="date")
    report = build_multiple_testing_report(
        input_path,
        selected_candidate=candidate,
        periods_per_year=252,
        partition_count=8,
    )
    assert report.status == "PASS"
    write_multiple_testing_report(report, root)


def _write_benchmark(root: Path, index_code: str) -> None:
    active_returns = np.tile(np.array([0.0010, 0.0018, 0.0026, 0.0014, 0.0022]), 8)
    benchmark_returns = np.tile(
        np.array([0.0010, -0.0008, 0.0015, 0.0002, -0.0004]),
        8,
    )
    strategy_returns = benchmark_returns + active_returns
    dates = pd.date_range("2024-01-01", periods=len(active_returns) + 1, freq="D")
    strategy_equity = 100_000.0 * np.cumprod(
        np.concatenate(([1.0], 1.0 + strategy_returns))
    )
    strategy_path = root / "benchmark_strategy_equity.csv"
    benchmark_path = root / "reviewed_benchmark.csv"
    metadata_path = root / "reviewed_benchmark_metadata.json"
    pd.DataFrame({"timestamp": dates, "equity": strategy_equity}).to_csv(
        strategy_path,
        index=False,
    )
    pd.DataFrame({"date": dates[1:], "value": benchmark_returns}).to_csv(
        benchmark_path,
        index=False,
    )
    _write_json(
        metadata_path,
        {
            "artifact_type": "reviewed_benchmark_series",
            "schema_version": 1,
            "symbol": f"{index_code}.SH",
            "name": "CSI 800 Total Return",
            "total_return": True,
            "series_kind": "returns",
            "source_vendor": "licensed-test-vendor",
            "source_exported_at": "2026-07-15T09:30:00+08:00",
            "reviewed_by": "research-test-operator",
            "reviewed_at": "2026-07-15T10:00:00+08:00",
            "file_sha256": _sha256(benchmark_path),
        },
    )
    report = build_benchmark_review_report(
        strategy_path,
        benchmark_path,
        metadata_path,
        block_size=4,
        n_bootstrap=100,
        random_seed=17,
    )
    assert report.status == "PASS"
    write_benchmark_review_report(report, root)


def _write_bound_trial(
    registry: Path,
    root: Path,
    manifest: dict[str, Any],
    candidate: str,
) -> None:
    start = date.fromisoformat(str(manifest["start"]))
    in_sample_end = date.fromisoformat(str(manifest["in_sample_end"]))
    selection_start = in_sample_end
    train_end = start
    if train_end >= selection_start:
        selection_start = start + timedelta(days=1)
        in_sample_end = selection_start
    data_version = manifest.get("data_version", {})
    data_fingerprint = next(
        (
            str(data_version.get(key))
            for key in (
                "cache_logical_bar_fingerprint",
                "csv_dataset_fingerprint",
                "raw_vendor_bars_sha256",
            )
            if str(data_version.get(key) or "").strip()
        ),
        str(manifest["cache_sha256"]),
    )
    append_preregistration(
        registry,
        trial_id="guard-v1",
        candidate=candidate,
        hypothesis="The frozen candidate survives the prospective holdout and evidence gates.",
        parameter_fingerprint="test-parameter-fingerprint",
        data_fingerprint=data_fingerprint,
        config_fingerprint=str(manifest["config_sha256"]),
        train_boundary={"start": str(manifest["start"]), "end": train_end.isoformat()},
        selection_boundary={
            "start": selection_start.isoformat(),
            "end": str(manifest["in_sample_end"]),
        },
        test_boundary={
            "start": str(manifest["out_sample_start"]),
            "end": str(manifest["end"]),
        },
        created_at="2026-07-14T09:00:00+00:00",
        prohibited_live_use=True,
    )
    fingerprint_names = [*REQUIRED_EVIDENCE_FILES]
    fingerprint_names.extend(["multiple_testing_report.json", "benchmark_report.json"])
    append_result(
        registry,
        trial_id="guard-v1",
        result_id="guard-v1:final",
        result={
            "candidate": candidate,
            "decision": "PASS",
            "artifact_fingerprints": {
                filename: _sha256(root / filename) for filename in fingerprint_names
            },
        },
        created_at="2026-07-16T09:00:00+00:00",
    )


def _ordered_manifest_dates(payload: dict[str, Any]) -> bool:
    try:
        start = date.fromisoformat(str(payload["start"]))
        in_sample = date.fromisoformat(str(payload["in_sample_end"]))
        out_sample = date.fromisoformat(str(payload["out_sample_start"]))
        end = date.fromisoformat(str(payload["end"]))
    except (KeyError, ValueError):
        return False
    return start < in_sample < out_sample <= end


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2),
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
