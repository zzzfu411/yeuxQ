"""Human-curated market regime notes for the current A-share research cycle."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class MarketRegimeNote:
    as_of: str
    market: str
    summary: str
    assumptions: list[str]
    strategy_implications: list[str]
    risk_warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "market": self.market,
            "summary": self.summary,
            "assumptions": self.assumptions,
            "strategy_implications": self.strategy_implications,
            "risk_warnings": self.risk_warnings,
        }

    def to_markdown(self) -> str:
        lines = [
            "# Market Regime Note",
            "",
            f"- As of: `{self.as_of}`",
            f"- Market: `{self.market}`",
            "",
            "## Summary",
            self.summary,
            "",
            "## Assumptions",
        ]
        lines.extend(f"- {item}" for item in self.assumptions)
        lines.extend(["", "## Strategy Implications"])
        lines.extend(f"- {item}" for item in self.strategy_implications)
        lines.extend(["", "## Risk Warnings"])
        lines.extend(f"- {item}" for item in self.risk_warnings)
        return "\n".join(lines) + "\n"


def write_market_regime_note(note: MarketRegimeNote, output_dir: str | Path) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "market_regime.json").write_text(
        json.dumps(note.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "market_regime.md").write_text(note.to_markdown(), encoding="utf-8")
    return root
