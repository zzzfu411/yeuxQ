# yeuxQ (`quantify`)

An evidence-gated A-share quantitative research and paper-trading system in Python—combining multi-factor backtesting, market-microstructure simulation, and deterministic `PASS / WATCH / BLOCK` promotion gates.

English · [简体中文](README.zh-CN.md)

## Capabilities

- **Audited local data layer** — SQLite research cache populated via AKShare, contract-validated vendor CSV exports, or TongDaXin `.day` files, with universe filtering (ST, delisted, suspended) and dataset provenance hashes.
- **A-share execution simulation** — Cross-sectional multi-factor ranking (momentum, low volatility, value, quality, liquidity) paired with event-driven simulation of `T+1` settlement, price limits, suspensions, 100-share lots, stamp duty, commissions, and slippage.
- **Selection-safe validation** — Purged/embargoed walk-forward evaluation, frozen stress matrices, total-return benchmark checks, and an append-only hash-chained trial registry with DSR and CSCV/PBO diagnostics.
- **Continuous paper loop & release gates** — Stateful daily paper trading (`run_paper_loop.py`), automated weekly review pipelines, and deterministic `PASS / WATCH / BLOCK` promotion gates across data QA, robustness, and capital-goal fit.
- **Advisory LLM review** — Produces structured review prompts and optional OpenAI-compatible narrative assessments (`run_llm_review.py`) strictly subordinate to deterministic gates.

## Quick Start

Requires **Python 3.11+** and **[uv](https://docs.astral.sh/uv/)**.

```bash
git clone https://github.com/zzzfu411/yeuxQ.git
cd yeuxQ
uv sync
```

Run a complete multi-factor study out of the box (automatically generates a deterministic synthetic dataset when no local cache is present):

```bash
uv run python examples/run_research.py --config config/research.yaml
```

Artifacts (`summary.json`, `equity.csv`, `positions.csv`, `orders.csv`, `factor_ic.csv`, `drawdown.png`, `html_report.html`) are written to `results/research/<timestamp>/`.

Import real A-share market data and run the weekly audit pipeline:

```bash
uv run python examples/import_research_data.py --config config/research.yaml --limit 300 --output-dir results/import/latest
uv run python examples/run_real_data_bootstrap.py --config config/research.yaml --output-dir results/bootstrap
uv run python examples/run_weekly_pipeline.py --config config/research.yaml --starting-capital 100000 --target-capital 1000000 --years 8
```

Run tests and lint:

```bash
uv run pytest tests/ -q --basetemp ./tmp/pytest -p no:cacheprovider
uv run ruff check .
```

## Architecture

```text
src/quantify/
├── core/        Events, bars, portfolio state, and target weights
├── data/        SQLite cache, AKShare/CSV/TDX importers, and DataProvider
├── research/    Universe filters, factor pipeline, ranking, and study reports
├── engine/      Event-driven backtester, BrokerSim, and PaperBroker
├── audit/       Daily bar integrity, coverage, and point-in-time checks
├── market/      Breadth, trend, and volatility regime detection
├── goal/        Capital-goal constraints and candidate scoring
├── paper/       Stateful daily paper-trading loop and stability checks
├── readiness/   Deterministic promotion gates and manual review sheets
├── llm/         Structured PASS/WATCH/BLOCK review and prompt generation
└── ops/         Weekly pipelines, trial registry, and strategy ledger
```

## Documentation

- [Getting Started](docs/GETTING_STARTED.md) — End-to-end walkthrough of the research-to-paper workflow
- [Beginner Tutorials (`00`–`09`)](docs/00_从零开始.md) — Core concepts, reading reports, mental models, and offline CSV contracts
- [Real-Data Handoff](docs/11_real_data_handoff.md) & [Operator Runbook](docs/OPERATOR_RUNBOOK.md) — Detailed CLI workflows for AKShare, vendor CSVs, TDX `.day` intake, and trial registration
- [Study Notes](docs/notes/README.md) — Chapter-by-chapter notes on forecasting and factor investing mapped to codebase modules

## Disclaimer

For quantitative engineering education, historical research, and local paper simulation only. Nothing in this repository constitutes investment advice, a return guarantee, or live broker order execution.
