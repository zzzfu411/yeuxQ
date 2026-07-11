from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock, patch

import pandas as pd

from quantify.llm import LLMClient, LLMClientConfig, LLMReviewPromptBuilder, review_report


def test_llm_review_blocks_demo_data_for_live(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {"demo_data_used": True},
        },
    )

    result = review_report(tmp_path, intended_stage="live")

    assert result.decision == "BLOCK"
    assert any(finding.code == "DEMO_DATA_FOR_LIVE" for finding in result.findings)


def test_llm_review_blocks_live_when_drawdown_is_too_high(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.30,
            "max_drawdown": 0.31,
            "sharpe_ratio": 1.1,
            "n_bars": 252,
            "assumptions": {"demo_data_used": False},
        },
    )

    result = review_report(tmp_path, intended_stage="micro_live")

    assert result.decision == "BLOCK"
    assert any(finding.code == "DRAWDOWN_BLOCK" for finding in result.findings)


def test_llm_review_blocks_demo_data_for_micro_live_ready(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {"demo_data_used": True},
        },
    )

    result = review_report(tmp_path, intended_stage="micro_live_ready")

    assert result.decision == "BLOCK"
    assert "connect_live_broker" in result.prohibited_actions


def test_llm_review_blocks_when_data_audit_blocks(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {
                "demo_data_used": False,
                "in_sample_end": "2020-12-31",
                "out_sample_start": "2021-01-01",
            },
        },
    )
    _write_json(
        tmp_path / "data_audit.json",
        {"status": "BLOCK", "findings": [{"severity": "BLOCK", "code": "MISSING_BARS"}]},
    )

    result = review_report(tmp_path, intended_stage="paper")

    assert result.decision == "BLOCK"
    assert any(finding.code == "DATA_AUDIT_BLOCK" for finding in result.findings)


def test_llm_review_micro_live_ready_blocks_missing_audit_and_manifest(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {
                "demo_data_used": False,
                "in_sample_end": "2020-12-31",
                "out_sample_start": "2021-01-01",
            },
        },
        write_evidence=False,
    )

    result = review_report(tmp_path, intended_stage="micro_live_ready")

    assert result.decision == "BLOCK"
    assert any(finding.code == "MISSING_DATA_AUDIT" for finding in result.findings)
    assert any(finding.code == "MISSING_RUN_MANIFEST" for finding in result.findings)


def test_llm_review_blocks_manifest_demo_data_for_micro_live_ready(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {
                "demo_data_used": False,
                "in_sample_end": "2020-12-31",
                "out_sample_start": "2021-01-01",
            },
        },
    )
    _write_json(tmp_path / "run_manifest.json", {"demo_data_used": True})

    result = review_report(tmp_path, intended_stage="micro_live_ready")

    assert result.decision == "BLOCK"
    demo = next(finding for finding in result.findings if finding.code == "DEMO_DATA_FOR_LIVE")
    assert demo.evidence["manifest_demo_data_used"] is True


def test_llm_review_warns_on_execution_quality(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.09,
            "max_drawdown": 0.07,
            "sharpe_ratio": 0.9,
            "n_bars": 252,
            "assumptions": {"demo_data_used": False},
        },
        order_status=["filled", "rejected", "filled", "filled"],
    )

    result = review_report(tmp_path, intended_stage="paper")

    assert result.decision == "WATCH"
    assert any(finding.code == "ORDER_REJECT_WATCH" for finding in result.findings)


def test_llm_review_warns_when_paper_stage_lacks_out_of_sample_split(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {"demo_data_used": False},
        },
    )

    result = review_report(tmp_path, intended_stage="paper")

    assert result.decision == "WATCH"
    assert any(finding.code == "MISSING_OUT_OF_SAMPLE_SPLIT" for finding in result.findings)
    assert result.missing_evidence
    assert result.next_experiments


def test_llm_review_prompt_keeps_gate_authoritative(tmp_path: Path) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {
                "demo_data_used": False,
                "in_sample_end": "2020-12-31",
                "out_sample_start": "2021-01-01",
            },
        },
    )
    result = review_report(tmp_path, intended_stage="paper")

    prompt = LLMReviewPromptBuilder().build(result)

    assert "deterministic gate decision is authoritative" in prompt.user
    assert "paper_stage_constraints" in prompt.user
    assert result.decision == "PASS"


def test_llm_client_missing_api_key_returns_advisory_error(tmp_path: Path) -> None:
    prompt = LLMReviewPromptBuilder().build(_passing_result(tmp_path))
    client = LLMClient(LLMClientConfig(api_key=None, model="test-model"))

    narrative = client.review(prompt)

    assert not narrative.ok
    assert "OPENAI_API_KEY" in narrative.error


def test_llm_client_posts_openai_compatible_request_body(tmp_path: Path) -> None:
    prompt = LLMReviewPromptBuilder().build(_passing_result(tmp_path))
    client = LLMClient(
        LLMClientConfig(
            base_url="https://example.test/v1",
            api_key="sk-test",
            model="test-model",
            timeout_seconds=3,
        )
    )
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=None)
    response.read.return_value = (
        b'{"choices":[{"message":{"content":"advisory review text"}}]}'
    )

    with patch("urllib.request.urlopen", return_value=response) as urlopen:
        narrative = client.review(prompt)

    request = urlopen.call_args.args[0]
    body = json.loads(request.data.decode("utf-8"))
    assert narrative.ok
    assert narrative.content == "advisory review text"
    assert request.full_url == "https://example.test/v1/chat/completions"
    assert body["model"] == "test-model"
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["role"] == "user"


def test_llm_client_model_override_wins_over_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    monkeypatch.setenv("OPENAI_MODEL", "env-model")

    config = LLMClientConfig.from_env(model="cli-model")

    assert config.model == "cli-model"
    assert config.api_key == "sk-env"


def test_cli_call_llm_without_key_writes_narrative_error(tmp_path: Path, monkeypatch) -> None:
    _write_report(
        tmp_path,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {
                "demo_data_used": False,
                "in_sample_end": "2020-12-31",
                "out_sample_start": "2021-01-01",
            },
        },
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_llm_review.py",
            "--report-dir",
            str(tmp_path),
            "--stage",
            "paper",
            "--call-llm",
            "--model",
            "cli-model",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    narrative = (tmp_path / "llm_narrative.md").read_text(encoding="utf-8")
    narrative_json = json.loads((tmp_path / "llm_narrative.json").read_text(encoding="utf-8"))
    assert "OPENAI_API_KEY" in narrative
    assert narrative_json["model"] == "cli-model"


def test_llm_review_candidate_experiment_dir_without_summary_blocks_missing_artifacts(
    tmp_path: Path,
) -> None:
    _write_json(
        tmp_path / "candidate_walk_forward_report.json",
        {
            "status": "PASS",
            "best_candidate": "price_volume_defensive",
            "window_count": 3,
            "summaries": [
                {
                    "candidate": "price_volume_defensive",
                    "avg_total_return": 0.06,
                    "avg_max_drawdown": 0.04,
                    "avg_sharpe_ratio": 0.9,
                }
            ],
        },
    )

    result = review_report(tmp_path, intended_stage="paper")

    assert result.decision == "BLOCK"
    assert result.snapshot.assumptions["review_mode"] == "candidate_experiment"
    assert any(finding.code == "CANDIDATE_ARTIFACT_MISSING" for finding in result.findings)


def test_llm_review_cli_writes_candidate_experiment_review_without_summary(tmp_path: Path) -> None:
    _write_json(tmp_path / "candidate_experiment_evidence.json", {"status": "PASS", "copied_artifacts": []})
    _write_json(
        tmp_path / "candidate_walk_forward_report.json",
        {
            "status": "PASS",
            "best_candidate": "price_volume_defensive",
            "window_count": 3,
            "summaries": [
                {
                    "candidate": "price_volume_defensive",
                    "avg_total_return": 0.06,
                    "avg_max_drawdown": 0.04,
                    "avg_sharpe_ratio": 0.9,
                }
            ],
        },
    )
    _write_json(tmp_path / "candidate_factor_diagnostics.json", {"status": "PASS"})
    _write_json(tmp_path / "candidate_regime_validation_report.json", {"status": "PASS"})
    _write_json(tmp_path / "candidate_selection.json", {"status": "PASS", "best_candidate": "price_volume_defensive"})

    completed = subprocess.run(
        [
            sys.executable,
            "examples/run_llm_review.py",
            "--report-dir",
            str(tmp_path),
            "--stage",
            "paper",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((tmp_path / "llm_review.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["snapshot"]["summary"]["assumptions"]["review_mode"] == "candidate_experiment"
    assert (tmp_path / "llm_prompt.md").exists()


def test_llm_review_includes_candidate_walk_forward_tail_metrics_in_prompt(
    tmp_path: Path,
) -> None:
    _write_json(tmp_path / "candidate_experiment_evidence.json", {"status": "PASS", "copied_artifacts": []})
    _write_candidate_walk_forward(
        tmp_path,
        positive_return_ratio=1.0,
        worst_total_return=0.01,
        worst_max_drawdown=0.04,
    )
    _write_json(tmp_path / "candidate_factor_diagnostics.json", {"status": "PASS"})
    _write_json(tmp_path / "candidate_regime_validation_report.json", {"status": "PASS"})
    _write_json(tmp_path / "candidate_selection.json", {"status": "PASS", "best_candidate": "price_volume_defensive"})

    result = review_report(tmp_path, intended_stage="paper")
    prompt = LLMReviewPromptBuilder().build(result)
    markdown = result.to_markdown()

    summary = result.snapshot.summary
    assert summary["candidate_walk_forward_positive_return_ratio"] == 1.0
    assert summary["candidate_walk_forward_worst_total_return"] == 0.01
    assert "candidate_walk_forward_positive_return_ratio" in prompt.user
    assert "candidate_walk_forward_worst_total_return" in prompt.user
    assert "candidate_walk_forward_worst_max_drawdown" in markdown


def test_llm_review_warns_on_low_candidate_walk_forward_positive_ratio(
    tmp_path: Path,
) -> None:
    _write_json(tmp_path / "candidate_experiment_evidence.json", {"status": "PASS", "copied_artifacts": []})
    _write_candidate_walk_forward(
        tmp_path,
        status="PASS",
        positive_return_ratio=0.50,
        worst_total_return=0.01,
        worst_max_drawdown=0.04,
    )
    _write_json(tmp_path / "candidate_factor_diagnostics.json", {"status": "PASS"})
    _write_json(tmp_path / "candidate_regime_validation_report.json", {"status": "PASS"})
    _write_json(tmp_path / "candidate_selection.json", {"status": "PASS", "best_candidate": "price_volume_defensive"})

    result = review_report(tmp_path, intended_stage="paper")

    assert result.decision == "WATCH"
    assert any(
        finding.code == "LOW_CANDIDATE_WALK_FORWARD_POSITIVE_RATIO"
        for finding in result.findings
    )
    assert any("forward window" in item for item in result.next_experiments)


def test_llm_review_blocks_candidate_walk_forward_tail_loss(tmp_path: Path) -> None:
    _write_json(tmp_path / "candidate_experiment_evidence.json", {"status": "PASS", "copied_artifacts": []})
    _write_candidate_walk_forward(
        tmp_path,
        status="PASS",
        positive_return_ratio=0.67,
        worst_total_return=-0.12,
        worst_max_drawdown=0.08,
    )
    _write_json(tmp_path / "candidate_factor_diagnostics.json", {"status": "PASS"})
    _write_json(tmp_path / "candidate_regime_validation_report.json", {"status": "PASS"})
    _write_json(tmp_path / "candidate_selection.json", {"status": "PASS", "best_candidate": "price_volume_defensive"})

    result = review_report(tmp_path, intended_stage="paper")

    assert result.decision == "BLOCK"
    assert any(finding.code == "CANDIDATE_WALK_FORWARD_TAIL_LOSS" for finding in result.findings)
    assert any("tail-window post-mortem" in item for item in result.next_experiments)


def test_llm_review_flags_missing_candidate_walk_forward_tail_metrics(
    tmp_path: Path,
) -> None:
    _write_json(tmp_path / "candidate_experiment_evidence.json", {"status": "PASS", "copied_artifacts": []})
    _write_json(
        tmp_path / "candidate_walk_forward_report.json",
        {
            "status": "PASS",
            "best_candidate": "price_volume_defensive",
            "window_count": 3,
            "summaries": [
                {
                    "candidate": "price_volume_defensive",
                    "status": "PASS",
                    "window_count": 3,
                    "avg_total_return": 0.06,
                    "avg_max_drawdown": 0.04,
                    "avg_sharpe_ratio": 0.9,
                }
            ],
        },
    )
    _write_json(tmp_path / "candidate_factor_diagnostics.json", {"status": "PASS"})
    _write_json(tmp_path / "candidate_regime_validation_report.json", {"status": "PASS"})
    _write_json(tmp_path / "candidate_selection.json", {"status": "PASS", "best_candidate": "price_volume_defensive"})

    result = review_report(tmp_path, intended_stage="paper")

    assert result.decision == "WATCH"
    assert any(
        finding.code == "CANDIDATE_WALK_FORWARD_METRICS_MISSING"
        for finding in result.findings
    )
    assert any("tail-risk metrics" in item for item in result.missing_evidence)


def _passing_result(report_dir: Path):
    _write_report(
        report_dir,
        summary={
            "total_return": 0.12,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.2,
            "n_bars": 252,
            "assumptions": {
                "demo_data_used": False,
                "in_sample_end": "2020-12-31",
                "out_sample_start": "2021-01-01",
            },
        },
    )
    return review_report(report_dir, intended_stage="paper")


def _write_report(
    report_dir: Path,
    summary: dict[str, object],
    order_status: list[str] | None = None,
    write_evidence: bool = True,
) -> None:
    (report_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False),
        encoding="utf-8",
    )
    if write_evidence:
        assumptions = summary.get("assumptions", {})
        assumptions = assumptions if isinstance(assumptions, dict) else {}
        demo = bool(assumptions.get("demo_data_used", False))
        _write_json(report_dir / "data_audit.json", {"status": "PASS", "demo_data_used": demo})
        _write_json(
            report_dir / "run_manifest.json",
            {
                "demo_data_used": demo,
                "latest_bar_date": "2021-12-31",
                "data_version": {"csv_dataset_fingerprint": "unit-test-fingerprint"},
            },
        )
    pd.DataFrame(
        {
            "status": order_status or ["filled", "filled"],
            "symbol": ["AAA"] * len(order_status or ["filled", "filled"]),
        }
    ).to_csv(report_dir / "orders.csv", index=False)
    pd.DataFrame({"turnover_pct": [0.1, 0.2, 0.15]}).to_csv(
        report_dir / "turnover.csv",
        index=False,
    )
    pd.DataFrame({"rank_ic": [0.05, 0.02, 0.01]}).to_csv(
        report_dir / "factor_ic.csv",
        index=False,
    )


def _write_candidate_walk_forward(
    report_dir: Path,
    *,
    status: str = "PASS",
    positive_return_ratio: float,
    worst_total_return: float,
    worst_max_drawdown: float,
) -> None:
    _write_json(
        report_dir / "candidate_walk_forward_report.json",
        {
            "status": status,
            "best_candidate": "price_volume_defensive",
            "window_count": 3,
            "summaries": [
                {
                    "candidate": "price_volume_defensive",
                    "status": status,
                    "window_count": 3,
                    "pass_count": 3 if status == "PASS" else 1,
                    "watch_count": 0 if status == "PASS" else 2,
                    "block_count": 1 if status == "BLOCK" else 0,
                    "avg_total_return": 0.06,
                    "avg_max_drawdown": 0.04,
                    "avg_sharpe_ratio": 0.9,
                    "positive_return_ratio": positive_return_ratio,
                    "worst_total_return": worst_total_return,
                    "worst_max_drawdown": worst_max_drawdown,
                }
            ],
        },
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
