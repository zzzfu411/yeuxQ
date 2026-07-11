"""Write a fillable evidence worksheet for A-share source QA."""
from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from quantify.data.source_qa import (
    build_data_source_qa_evidence_worksheet,
    write_data_source_qa_evidence_worksheet,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a fillable source-QA evidence worksheet.")
    parser.add_argument("--checklist", default="data_exports/data_source_qa.json")
    parser.add_argument("--output-dir", default="data_exports")
    args = parser.parse_args()

    worksheet = build_data_source_qa_evidence_worksheet(
        checklist_path=args.checklist,
        output_dir=args.output_dir,
    )
    out = write_data_source_qa_evidence_worksheet(worksheet, Path(args.output_dir))
    logger.info("Data source QA evidence worksheet written to {}", out.resolve())


if __name__ == "__main__":
    main()
