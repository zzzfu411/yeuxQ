from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

from quantify.data.cache_metadata import (
    build_promotion_metadata_check,
    write_promotion_metadata_check,
)
from quantify.data.storage import BarStorage


def test_promotion_metadata_check_passes_complete_metadata(tmp_path: Path) -> None:
    cache = tmp_path / "recent.db"
    storage = BarStorage(cache)
    storage.save_metadata(_complete_metadata(tmp_path))

    check = build_promotion_metadata_check(cache)
    out = write_promotion_metadata_check(check, tmp_path / "out")

    payload = json.loads((out / "promotion_metadata_check.json").read_text(encoding="utf-8"))
    markdown = (out / "promotion_metadata_check.md").read_text(encoding="utf-8")
    assert check.status == "PASS"
    assert payload["status"] == "PASS"
    assert payload["blockers"] == []
    assert "Promotion Metadata Check: PASS" in markdown


def test_promotion_metadata_check_blocks_missing_source_qa_metadata(tmp_path: Path) -> None:
    cache = tmp_path / "recent.db"
    storage = BarStorage(cache)
    storage.save_metadata({"csv_dataset_fingerprint": "unit-test-fingerprint"})

    check = build_promotion_metadata_check(cache)

    assert check.status == "BLOCK"
    assert any("data_source_qa_status" in blocker for blocker in check.blockers)
    assert any("Rerun guarded offline intake" in action for action in check.next_actions)


def test_promotion_metadata_check_blocks_stale_source_qa_hash(tmp_path: Path) -> None:
    cache = tmp_path / "recent.db"
    metadata = _complete_metadata(tmp_path)
    checklist = Path(metadata["data_source_qa_checklist_path"])
    checklist.write_text('{"changed": true}', encoding="utf-8")
    storage = BarStorage(cache)
    storage.save_metadata(metadata)

    check = build_promotion_metadata_check(cache)

    assert check.status == "BLOCK"
    assert any("does not match current source QA checklist file hash" in blocker for blocker in check.blockers)
    assert any("provenance hashes" in action for action in check.next_actions)


def test_promotion_metadata_check_strict_manifest_requires_manifest_metadata(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "recent.db"
    storage = BarStorage(cache)
    storage.save_metadata(_complete_metadata(tmp_path))

    check = build_promotion_metadata_check(cache, require_evidence_manifest=True)

    assert check.status == "BLOCK"
    assert any("Missing data_source_qa_evidence_manifest_path" in blocker for blocker in check.blockers)


def test_promotion_metadata_cli_writes_pass_outputs(tmp_path: Path) -> None:
    cache = tmp_path / "recent.db"
    storage = BarStorage(cache)
    storage.save_metadata(_complete_metadata(tmp_path))
    output_dir = tmp_path / "promotion_check"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/check_promotion_metadata.py",
            "--cache",
            str(cache),
            "--output-dir",
            str(output_dir),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((output_dir / "promotion_metadata_check.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["status"] == "PASS"


def test_promotion_metadata_cli_returns_nonzero_on_block(tmp_path: Path) -> None:
    cache = tmp_path / "recent.db"
    BarStorage(cache)
    output_dir = tmp_path / "promotion_check"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/check_promotion_metadata.py",
            "--cache",
            str(cache),
            "--output-dir",
            str(output_dir),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((output_dir / "promotion_metadata_check.json").read_text(encoding="utf-8"))
    assert completed.returncode == 2
    assert payload["status"] == "BLOCK"
    assert payload["blockers"]


def test_promotion_metadata_cli_accepts_config_cache(tmp_path: Path) -> None:
    cache = tmp_path / "recent.db"
    storage = BarStorage(cache)
    storage.save_metadata(_complete_metadata(tmp_path))
    config = tmp_path / "research_recent.yaml"
    _write_config(config, cache)
    output_dir = tmp_path / "promotion_check"

    completed = subprocess.run(
        [
            sys.executable,
            "examples/check_promotion_metadata.py",
            "--config",
            str(config),
            "--output-dir",
            str(output_dir),
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads((output_dir / "promotion_metadata_check.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0
    assert payload["cache_path"] == str(cache)
    assert payload["status"] == "PASS"


def _complete_metadata(root: Path) -> dict[str, str]:
    qa_dir = root / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    checklist = qa_dir / "data_source_qa.json"
    answers = qa_dir / "data_source_qa_answers.json"
    checklist.write_text('{"checklist": [{"id": "source_identity"}]}', encoding="utf-8")
    answers.write_text('{"answers": {"source_identity": "yes"}}', encoding="utf-8")
    return {
        "csv_dataset_fingerprint": "unit-test-csv-fingerprint",
        "data_source_qa_status": "PASS",
        "data_source_csv_qa_status": "PASS",
        "data_source_qa_checklist_path": str(checklist),
        "data_source_qa_checklist_sha256": _sha256(checklist),
        "data_source_qa_answers_path": str(answers),
        "data_source_qa_answers_sha256": _sha256(answers),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_config(path: Path, cache: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "research:",
                '  start: "2024-01-02"',
                '  end: "2024-01-05"',
                "data:",
                f"  cache_path: '{cache}'",
            ]
        ),
        encoding="utf-8",
    )
