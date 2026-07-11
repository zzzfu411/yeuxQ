"""Research hypothesis catalog for strategy candidates.

The catalog is deliberately evidence-light: it records what each candidate is
supposed to prove before the system has real-data results. It is not a ranking,
not a broker instruction, and not permission to promote capital.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quantify.research.candidates import CandidateSpec, default_candidate_specs
from quantify.research.factors import (
    LiquidityFactor,
    LowVolatilityFactor,
    ShortMomentumFactor,
    VeryLowVolatilityFactor,
)

CATALOG_STATUS = "RESEARCH_ONLY"
DEFAULT_PROHIBITED_ACTIONS = [
    "Do not treat any hypothesis as proof of profitability.",
    "Do not connect hypothesis output to a real broker.",
    "Do not let an LLM promote a candidate past deterministic gates.",
    "Do not increase capital based on this catalog alone.",
]
COMMON_REQUIRED_VALIDATION_GATES = [
    "Recent real A-share daily data passes source QA, CSV validation, import doctor, and data audit.",
    "Research report records in-sample and out-of-sample windows.",
    "Baseline robustness, parameter perturbation, and cost stress tests do not BLOCK.",
    "Candidate walk-forward validation has enough windows and no unresolved BLOCK.",
    "Candidate factor diagnostics show the composite is not a single-factor accident.",
    "Regime validation includes neutral, defensive, and adverse windows where available.",
    "Paper-stage observation records orders, rejects, fills, holdings, cash, and NAV.",
    "LLM advisory review lists risks without changing the deterministic decision.",
    "Human approval is recorded before any micro-live readiness claim.",
]
OHLCV_ONLY_REQUIRED_VALIDATION_GATES = [
    "OHLCV-only candidate path records that no point-in-time valuation or accounting fields were used.",
    "If the data package lacks point-in-time fundamentals, fundamental-dependent candidates stay downgraded until provenance is resolved.",
]
COMMON_DOWNGRADE_CONDITIONS = [
    "Any real-data, robustness, walk-forward, regime, paper, or LLM deterministic gate returns BLOCK.",
    "Evidence is demo-only, stale, template-based, or missing source QA answers.",
    "Out-of-sample results are missing or materially worse than in-sample results.",
    "Reject rate, turnover, drawdown, or liquidity flags exceed the configured budget.",
    "Manual approval is missing for a stage that requires approval.",
]
COMMON_PAPER_REQUIREMENTS = [
    "At least 4-8 weeks of continuous paper records before micro-live readiness review.",
    "Daily state must be recoverable from paper_state, orders, positions, and daily review files.",
    "Target portfolio can only produce a manual trade sheet, not broker orders.",
    "Every rejected or skipped order must have a recorded reason.",
]


@dataclass(frozen=True, slots=True)
class CandidateHypothesis:
    name: str
    description: str
    hypothesis: str
    intended_regimes: list[str]
    factors: list[str]
    key_risks: list[str]
    required_validation_gates: list[str]
    automatic_downgrade_conditions: list[str]
    paper_readiness_requirements: list[str]
    prohibited_actions: list[str]
    n_holdings: int
    max_weight: float
    rebalance: str
    data_dependency: str
    trend_filter: bool
    trend_scale: float
    trend_gate: str = "weak_trend"
    hold_rank_buffer: int = 0
    min_trade_weight: float = 0.0
    max_new_positions: int = 0
    score_smoothing_observations: int = 0
    score_smoothing_step_days: int = 20

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "hypothesis": self.hypothesis,
            "intended_regimes": self.intended_regimes,
            "factors": self.factors,
            "key_risks": self.key_risks,
            "required_validation_gates": self.required_validation_gates,
            "automatic_downgrade_conditions": self.automatic_downgrade_conditions,
            "paper_readiness_requirements": self.paper_readiness_requirements,
            "prohibited_actions": self.prohibited_actions,
            "n_holdings": self.n_holdings,
            "max_weight": self.max_weight,
            "rebalance": self.rebalance,
            "data_dependency": self.data_dependency,
            "trend_filter": self.trend_filter,
            "trend_scale": self.trend_scale,
            "trend_gate": self.trend_gate,
            "hold_rank_buffer": self.hold_rank_buffer,
            "min_trade_weight": self.min_trade_weight,
            "max_new_positions": self.max_new_positions,
            "score_smoothing_observations": self.score_smoothing_observations,
            "score_smoothing_step_days": self.score_smoothing_step_days,
        }


@dataclass(frozen=True, slots=True)
class CandidateHypothesisCatalog:
    status: str
    as_of: str | None
    candidate_count: int
    candidates: list[CandidateHypothesis]
    required_evidence_before_screening: list[str]
    prohibited_actions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "as_of": self.as_of,
            "candidate_count": self.candidate_count,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "required_evidence_before_screening": self.required_evidence_before_screening,
            "prohibited_actions": self.prohibited_actions,
        }

    def to_markdown(self) -> str:
        lines = [
            f"# Candidate Hypotheses: {self.status}",
            "",
            f"- As of: `{self.as_of or 'unspecified'}`",
            f"- Candidate count: {self.candidate_count}",
            "",
            "This catalog is a research hypothesis register, not a live trading instruction.",
            "",
            "## Required Evidence Before Screening",
        ]
        lines.extend(f"- {item}" for item in self.required_evidence_before_screening)
        lines.extend(["", "## Candidates"])
        for candidate in self.candidates:
            lines.extend(
                [
                    "",
                    f"### `{candidate.name}`",
                    "",
                    candidate.hypothesis,
                    "",
                    f"- Description: {candidate.description}",
                    f"- Factors: {', '.join(candidate.factors) or 'none'}",
                    f"- Holdings: {candidate.n_holdings}",
                    f"- Max weight: {candidate.max_weight:.2%}",
                    f"- Rebalance: `{candidate.rebalance}`",
                    f"- Data dependency: `{candidate.data_dependency}`",
                    f"- Trend filter: `{candidate.trend_filter}`",
                    f"- Trend scale: `{candidate.trend_scale:.2f}`",
                    f"- Trend gate: `{candidate.trend_gate}`",
                    f"- Hold-rank buffer: `{candidate.hold_rank_buffer}`",
                    f"- Min trade weight: `{candidate.min_trade_weight:.2%}`",
                    f"- Max new positions: `{candidate.max_new_positions}`",
                    f"- Score smoothing observations: `{candidate.score_smoothing_observations}`",
                    f"- Score smoothing step days: `{candidate.score_smoothing_step_days}`",
                    "- Intended regimes: " + "; ".join(candidate.intended_regimes),
                    "",
                    "Required validation gates:",
                ]
            )
            lines.extend(f"- {item}" for item in candidate.required_validation_gates)
            lines.append("")
            lines.append("Automatic downgrade conditions:")
            lines.extend(f"- {item}" for item in candidate.automatic_downgrade_conditions)
            lines.append("")
            lines.append("Paper readiness requirements:")
            lines.extend(f"- {item}" for item in candidate.paper_readiness_requirements)
            lines.append("")
            lines.append("Key risks:")
            lines.extend(f"- {item}" for item in candidate.key_risks)
        lines.extend(["", "## Prohibited Actions"])
        lines.extend(f"- {item}" for item in self.prohibited_actions)
        return "\n".join(lines) + "\n"


def build_candidate_hypothesis_catalog(
    cfg,
    *,
    as_of: str | None = None,
    specs: list[CandidateSpec] | None = None,
) -> CandidateHypothesisCatalog:
    candidates = [_build_candidate_hypothesis(spec) for spec in candidate_hypothesis_specs(cfg, specs=specs)]
    return CandidateHypothesisCatalog(
        status=CATALOG_STATUS,
        as_of=as_of,
        candidate_count=len(candidates),
        candidates=candidates,
        required_evidence_before_screening=[
            "Filled data_source_qa_answers.json with vendor, terminal, export time, license, and adjustment evidence.",
            "Non-template recent A-share CSV exports or a verified recent research cache.",
            "Passing source QA review, CSV validation, import doctor, and offline intake.",
            "A run manifest linking config, cache, data fingerprints, sample windows, and safety boundaries.",
        ],
        prohibited_actions=DEFAULT_PROHIBITED_ACTIONS,
    )


def write_candidate_hypothesis_catalog(
    catalog: CandidateHypothesisCatalog,
    output_dir: str | Path,
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "candidate_hypotheses.json").write_text(
        json.dumps(catalog.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "candidate_hypotheses.md").write_text(catalog.to_markdown(), encoding="utf-8")
    return root


def candidate_hypothesis_specs(cfg, *, specs: list[CandidateSpec] | None = None) -> list[CandidateSpec]:
    base_specs = list(specs or default_candidate_specs(cfg))
    if any(spec.name == "regime_pause_price_volume" for spec in base_specs):
        return base_specs
    base_holdings = int(cfg.strategy.n_holdings)
    base_weight = float(cfg.strategy.max_weight)
    return [
        *base_specs,
        CandidateSpec(
            name="regime_pause_price_volume",
            description=(
                "OHLCV-only defensive basket with explicit regime-pause behavior when the broad trend turns risk-off."
            ),
            factors=[
                VeryLowVolatilityFactor(),
                LowVolatilityFactor(),
                ShortMomentumFactor(),
                LiquidityFactor(),
            ],
            n_holdings=max(50, base_holdings),
            max_weight=min(base_weight, 0.03),
            rebalance="monthly",
            trend_filter=True,
            trend_scale=0.0,
            trend_gate="defensive_or_worse",
            data_dependency="ohlcv_only",
        ),
    ]


def _build_candidate_hypothesis(spec: CandidateSpec) -> CandidateHypothesis:
    profile = _profile(spec.name)
    common_gates = list(COMMON_REQUIRED_VALIDATION_GATES)
    if spec.data_dependency == "ohlcv_only":
        common_gates.extend(OHLCV_ONLY_REQUIRED_VALIDATION_GATES)
    return CandidateHypothesis(
        name=spec.name,
        description=spec.description,
        hypothesis=str(profile["hypothesis"]),
        intended_regimes=list(profile["intended_regimes"]),
        factors=[factor.name for factor in spec.factors],
        key_risks=list(profile["key_risks"]),
        required_validation_gates=common_gates + list(profile["extra_gates"]),
        automatic_downgrade_conditions=COMMON_DOWNGRADE_CONDITIONS
        + list(profile["downgrade_conditions"]),
        paper_readiness_requirements=COMMON_PAPER_REQUIREMENTS + list(profile["paper_requirements"]),
        prohibited_actions=DEFAULT_PROHIBITED_ACTIONS,
        n_holdings=spec.n_holdings,
        max_weight=spec.max_weight,
        rebalance=spec.rebalance,
        data_dependency=spec.data_dependency,
        trend_filter=spec.trend_filter,
        trend_scale=spec.trend_scale,
        trend_gate=spec.trend_gate,
        hold_rank_buffer=spec.hold_rank_buffer,
        min_trade_weight=spec.min_trade_weight,
        max_new_positions=spec.max_new_positions,
        score_smoothing_observations=spec.score_smoothing_observations,
        score_smoothing_step_days=spec.score_smoothing_step_days,
    )


def _profile(name: str) -> dict[str, list[str] | str]:
    profiles: dict[str, dict[str, list[str] | str]] = {
        "price_volume_defensive": {
            "hypothesis": (
                "An OHLCV-only blend of momentum, short momentum, low volatility, very low volatility, "
                "and liquidity can be the first candidate tested when recent A-share data has reliable bars "
                "but no audited point-in-time fundamentals."
            ),
            "intended_regimes": ["neutral", "defensive", "choppy recovery"],
            "key_risks": [
                "Price-volume signals can overfit recent microstructure or liquidity conditions.",
                "Without fundamentals, the candidate may miss valuation, quality, and balance-sheet deterioration.",
                "Liquidity filters based only on amount can still admit crowded or event-driven names.",
            ],
            "extra_gates": [
                "Factor diagnostics must verify the composite is not only a liquidity or low-volatility proxy.",
                "Compare against fundamental-dependent candidates only after their PIT data provenance is available.",
                "Paper reviews must record that this is an OHLCV-only research path, not a complete quality model.",
            ],
            "downgrade_conditions": [
                "Downgrade if OHLCV data lacks adjustment evidence, has template rows, or has unresolved source QA.",
                "Downgrade if adding vetted PIT fundamentals materially changes the target basket or risk profile.",
            ],
            "paper_requirements": [
                "Paper plan should track turnover, liquidity amount, and realized slippage assumptions at every rebalance.",
            ],
        },
        "low_turnover_price_volume": {
            "hypothesis": (
                "An OHLCV-only basket with quarterly rebalance, broader diversification, low-volatility, "
                "liquidity, and slower momentum may reduce turnover and cost sensitivity versus the monthly "
                "price-volume baseline."
            ),
            "intended_regimes": ["defensive", "neutral low breadth", "choppy recovery"],
            "key_risks": [
                "Lower turnover can delay exits when a holding deteriorates quickly.",
                "Quarterly rebalancing may miss short recovery windows or hold stale momentum names.",
                "Reduced turnover is useful only if drawdown and RankIC improve after costs.",
            ],
            "extra_gates": [
                "Compare turnover, drawdown, and high-cost stress directly against price_volume_defensive.",
                "Walk-forward evidence must show lower turnover does not come from simply holding losers longer.",
                "Factor diagnostics must verify the candidate is not only a low-volatility or liquidity screen.",
            ],
            "downgrade_conditions": [
                "Downgrade if turnover is not meaningfully lower than the monthly OHLCV baseline.",
                "Downgrade if worst walk-forward windows show slower exits increasing drawdown.",
            ],
            "paper_requirements": [
                "Paper review should track skipped trades, holding age, realized turnover, and stale-position risk.",
            ],
        },
        "low_turnover_low_concentration_price_volume": {
            "hypothesis": (
                "An OHLCV-only low-turnover basket with the same quarterly cadence but lower position concentration "
                "may keep the defensive profile while improving drawdown resilience versus the baseline low-turnover variant."
            ),
            "intended_regimes": ["defensive", "neutral low breadth", "choppy recovery"],
            "key_risks": [
                "Lower concentration can dilute the signal enough to reduce return margin below the capital path.",
                "If turnover stays high anyway, the extra diversification may only add complexity without execution relief.",
                "Reduced drawdown must come from better basket construction, not from becoming an underinvested low-signal sleeve.",
            ],
            "extra_gates": [
                "Compare directly against low_turnover_price_volume on the same real-cache defensive windows.",
                "Stress high-cost, wider-basket, and lower-concentration scenarios to verify the improvement is not accidental.",
                "Show that drawdown or Sharpe improves without a material collapse in annualized return.",
            ],
            "downgrade_conditions": [
                "Downgrade if lower concentration reduces return margin more than it improves drawdown resilience.",
                "Downgrade if turnover, reject rate, or worst walk-forward drawdown do not improve meaningfully versus low_turnover_price_volume.",
            ],
            "paper_requirements": [
                "Paper review should compare concentration, turnover, and realized target drift versus the baseline low-turnover variant.",
            ],
        },
        "trend_filtered_price_volume": {
            "hypothesis": (
                "An OHLCV-only price-volume basket with a broad-trend exposure filter may reduce damage "
                "during defensive or weak-breadth markets while keeping the first OHLCV research path simple."
            ),
            "intended_regimes": ["defensive", "risk-off recovery", "neutral low breadth"],
            "key_risks": [
                "Trend filters can cut exposure after damage has already occurred.",
                "Cash drag and missed rebounds can make the one-million compounding path unrealistic.",
                "A broad universe trend proxy may not match the actual selected holdings.",
            ],
            "extra_gates": [
                "Compare filtered versus unfiltered price_volume_defensive on identical windows.",
                "Record active filter days, exposure scale, cash drag, and missed-rebound cost.",
                "Do not treat lower drawdown as success unless the required annual return path remains plausible.",
            ],
            "downgrade_conditions": [
                "Downgrade if the filter only lowers drawdown by staying mostly in cash.",
                "Downgrade if missed rebounds erase the return margin required for the capital goal.",
            ],
            "paper_requirements": [
                "Paper review should record filter-active days, target exposure scale, cash drag, and skipped exposure.",
            ],
        },
        "trend_filtered_quarterly_price_volume": {
            "hypothesis": (
                "An OHLCV-only trend-filtered price-volume basket with quarterly rebalance may preserve more of the "
                "signal than the monthly filtered baseline while still reducing exposure in weak-breadth markets."
            ),
            "intended_regimes": ["defensive", "risk-off recovery", "neutral low breadth"],
            "key_risks": [
                "Quarterly cadence can leave the basket stale if the trend filter reacts too slowly after market damage.",
                "Improved return may come with higher path dependence in a small number of windows.",
                "The broad-trend proxy still may not align with the actual selected holdings during rebound phases.",
            ],
            "extra_gates": [
                "Compare directly against trend_filtered_price_volume using identical windows and market-regime evidence.",
                "Record whether quarterly cadence improves Sharpe because of lower noise or only because of one favorable rebound path.",
                "Do not treat better filtered returns as success unless cash drag, missed rebounds, and reject rate remain visible.",
            ],
            "downgrade_conditions": [
                "Downgrade if quarterly cadence improves one full-sample run but weakens walk-forward resilience.",
                "Downgrade if drawdown remains too high relative to the added return margin.",
            ],
            "paper_requirements": [
                "Paper review should record filter-active days, quarterly rebalance drift, cash drag, and missed-rebound notes.",
            ],
        },
        "trend_filtered_quarterly_low_concentration_price_volume": {
            "hypothesis": (
                "The lower-concentration stress scenario for the quarterly trend-filtered price-volume basket may "
                "keep most of the trend-filter benefit while reducing drawdown, turnover, and concentration risk."
            ),
            "intended_regimes": ["defensive", "risk-off recovery", "neutral low breadth"],
            "key_risks": [
                "Lower concentration can reduce drawdown by diluting the useful signal and leaving the return gap unresolved.",
                "The variant may simply replay one favorable lower-weight stress scenario instead of improving robustness.",
                "Trend-filter cash drag and missed rebounds still need explicit review despite lower per-name weights.",
            ],
            "extra_gates": [
                "Compare directly against trend_filtered_quarterly_price_volume on identical windows.",
                "Require lower drawdown or turnover without a worse capital-goal return margin after cost stress.",
                "Record whether the lower max_weight improves breadth resilience or only lowers both risk and return.",
            ],
            "downgrade_conditions": [
                "Downgrade if lower concentration reduces return margin more than it improves drawdown or turnover.",
                "Downgrade if the lower-weight result fails walk-forward or high-cost stress when rerun as a candidate.",
            ],
            "paper_requirements": [
                "Paper review records concentration, target drift, filter-active days, turnover, and missed-rebound notes.",
            ],
        },
        "defensive_scaled_quarterly_price_volume": {
            "hypothesis": (
                "A quarterly price-volume basket with moderate concentration and a stronger defensive-regime "
                "exposure cut may keep more neutral-market rebound participation than the low-concentration "
                "variant while reducing the defensive bucket losses seen in walk-forward validation."
            ),
            "intended_regimes": ["defensive", "risk-off recovery", "neutral rebound"],
            "key_risks": [
                "The defensive gate can cut exposure after damage has already occurred.",
                "Partial defensive exposure may still lose money in adverse windows while lowering full-sample return.",
                "The candidate may overfit the observed defensive/neutral split instead of improving broad stability.",
            ],
            "extra_gates": [
                "Compare directly against trend_filtered_quarterly_price_volume and the low-concentration variant on identical windows.",
                "Require defensive bucket losses to shrink without weakening neutral bucket participation below the low-concentration path.",
                "Record filter-active days, cash drag, missed rebounds, turnover, and reject rate together.",
            ],
            "downgrade_conditions": [
                "Downgrade if defensive bucket return remains non-positive without a clear drawdown improvement.",
                "Downgrade if neutral windows lose too much return relative to trend_filtered_quarterly_price_volume.",
                "Downgrade if positive walk-forward ratio does not improve beyond the current 2/6 evidence.",
            ],
            "paper_requirements": [
                "Paper review records defensive-gate activations, target exposure scale, cash drag, and missed-rebound notes.",
            ],
        },
        "stable_universe_slow_signal_price_volume": {
            "hypothesis": (
                "An OHLCV-only wide quarterly basket using very low volatility, low volatility, liquidity, "
                "and long momentum that skips recent short-term moves may reduce structural turnover better "
                "than hold-rank buffers, drift thresholds, or score-smoothing overlays."
            ),
            "intended_regimes": ["neutral", "defensive", "low breadth stabilization"],
            "key_risks": [
                "A slower signal can hold deteriorating names too long when the market rotates quickly.",
                "The wide basket can dilute useful factor exposure and leave return margin below the capital path.",
                "Liquidity and low-volatility components can dominate unless factor diagnostics prove long momentum contributes.",
            ],
            "extra_gates": [
                "Compare directly against defensive_scaled_quarterly_price_volume on identical recent real-cache windows.",
                "Require maintenance turnover to improve without relying on hold-rank buffers, trade thresholds, or score smoothing.",
                "Factor diagnostics must show the long-momentum component is not redundant with liquidity or low volatility.",
            ],
            "downgrade_conditions": [
                "Downgrade if maintenance turnover remains high despite the slow-signal design.",
                "Downgrade if slower entries and exits reduce return margin more than they improve drawdown or turnover.",
                "Downgrade if factor diagnostics show the candidate is only a liquidity or low-volatility proxy.",
            ],
            "paper_requirements": [
                "Paper review records holding age, maintenance turnover, target drift, and slow-signal stale-position risk.",
            ],
        },
        "long_momentum_liquidity_monthly_price_volume": {
            "hypothesis": (
                "An OHLCV-only monthly component-ablation candidate using only long momentum and liquidity "
                "can test whether the slow-signal basket was weakened by low-volatility components rather "
                "than by the long-momentum/liquidity signal itself."
            ),
            "intended_regimes": ["neutral", "improving breadth", "liquid momentum recovery"],
            "key_risks": [
                "The candidate may become a two-factor momentum/liquidity proxy with weak defensive behavior.",
                "Monthly cadence can raise turnover or chase rebounds after most of the move has occurred.",
                "Removing low-volatility components can improve return while increasing adverse-window drawdown.",
            ],
            "extra_gates": [
                "Compare directly against stable_universe_slow_signal_price_volume and defensive_scaled_quarterly_price_volume on identical windows.",
                "Require factor diagnostics to show the composite is not only a liquidity screen or long-momentum accident.",
                "Run high-cost, wider-basket, and quarterly-cadence stress before treating the component ablation as useful.",
            ],
            "downgrade_conditions": [
                "Downgrade if higher return comes with worse adverse-window drawdown or high maintenance turnover.",
                "Downgrade if component diagnostics show long momentum or liquidity alone dominates the composite.",
                "Downgrade if the candidate only works in one recent rebound window.",
            ],
            "paper_requirements": [
                "Paper review records momentum/liquidity concentration, holding age, turnover, and missed-reversal risk.",
            ],
        },
        "liquidity_neutral_momentum_guard_price_volume": {
            "hypothesis": (
                "An OHLCV-only guarded basket using liquidity-neutral long momentum and very low volatility "
                "can test whether the long-momentum signal survives after removing liquidity exposure while "
                "a defensive-or-worse exposure cut reduces the adverse-regime losses."
            ),
            "intended_regimes": ["neutral", "defensive stabilization", "liquidity-neutral recovery"],
            "key_risks": [
                "Residualizing liquidity can remove much of the apparent return if the prior signal was mostly liquidity exposure.",
                "The defensive gate can create cash drag and missed rebounds while still arriving after drawdown.",
                "Adding very low volatility may again dilute long-momentum evidence if it dominates the composite.",
            ],
            "extra_gates": [
                "Compare directly against long_momentum_liquidity_monthly_price_volume on identical windows.",
                "Require factor diagnostics to show the liquidity-neutral momentum component contributes beyond very low volatility.",
                "Regime validation must show defensive buckets improve without destroying neutral-market return margin.",
            ],
            "downgrade_conditions": [
                "Downgrade if return disappears after liquidity neutralization.",
                "Downgrade if defensive bucket losses remain non-positive without a drawdown improvement.",
                "Downgrade if cash drag or missed rebounds leave the capital-goal return margin worse than the unguarded ablation.",
            ],
            "paper_requirements": [
                "Paper review records liquidity-neutral residual exposure, defensive-gate activations, cash drag, and missed-rebound risk.",
            ],
        },
        "defensive_cash_guard_price_volume": {
            "hypothesis": (
                "An OHLCV-only, very low concentration defensive basket with a stronger broad-trend "
                "cash guard may reduce defensive-regime losses when ordinary price-volume defensive "
                "recipes still lose money."
            ),
            "intended_regimes": ["defensive", "risk_off", "low breadth"],
            "key_risks": [
                "The candidate may protect capital mainly through cash drag and miss rebounds.",
                "Very low concentration per name can reduce drawdown but also dilute any useful signal.",
                "OHLCV-only evidence cannot validate business quality or valuation resilience.",
            ],
            "extra_gates": [
                "Stress matrix must compare baseline, lower concentration, high cost, and trend-filter-off cases.",
                "Regime validation must show defensive buckets improve without hiding mostly uninvested cash.",
                "Factor diagnostics must show it is not only a liquidity or very-low-volatility screen.",
            ],
            "downgrade_conditions": [
                "Downgrade if defensive-regime return remains non-positive after stronger cash guard.",
                "Downgrade if improved drawdown comes only from excessive cash drag or missed rebound.",
            ],
            "paper_requirements": [
                "Paper review must record filter activations, target exposure, cash drag, and missed-rebound notes.",
            ],
        },
        "risk_off_cash_stop_price_volume": {
            "hypothesis": (
                "An OHLCV-only defensive basket with a strict weak-trend cash stop may avoid "
                "defensive-regime losses that persisted after partial exposure cuts."
            ),
            "intended_regimes": ["defensive", "risk_off", "low breadth"],
            "key_risks": [
                "A full cash stop can avoid losses but make the compounding target unreachable through cash drag.",
                "The broad trend proxy can exit after damage and re-enter after rebounds have already happened.",
                "Frequent full exits can create high turnover and tax friction in choppy markets.",
            ],
            "extra_gates": [
                "Stress matrix must compare cash-stop baseline, trend-filter-off, high-cost, and wider-basket cases.",
                "Regime validation must show defensive buckets improve without destroying neutral-market participation.",
                "Missed-rebound cost must be recorded before any paper-stage discussion.",
            ],
            "downgrade_conditions": [
                "Downgrade if strict cash stops still leave defensive-regime returns non-positive.",
                "Downgrade if neutral or rebound regimes lose the return margin required for the capital goal.",
            ],
            "paper_requirements": [
                "Paper review must record every full-cash activation, re-entry, turnover spike, and missed-rebound note.",
            ],
        },
        "regime_pause_price_volume": {
            "hypothesis": (
                "An OHLCV-only defensive basket with explicit regime-pause logic may do better than broad-trend "
                "exposure scaling when weak-market evidence says the candidate should stop taking risk instead of "
                "remaining a diluted invested basket."
            ),
            "intended_regimes": ["neutral", "choppy recovery", "explicit regime pause"],
            "key_risks": [
                "Regime-pause logic can still arrive after damage and leave the candidate holding a late exit.",
                "Frequent pause and resume cycles can create turnover spikes and missed-rebound cost.",
                "OHLCV-only evidence cannot prove whether cash pauses are superior to fundamental quality filters.",
            ],
            "extra_gates": [
                "Regime validation must show pause episodes are explicit, reviewable, and not just broad-trend drift.",
                "Compare pause-on versus pause-off behavior on identical adverse and recovery windows.",
                "Paper reviews must record every pause trigger, resume trigger, and skipped exposure note.",
            ],
            "downgrade_conditions": [
                "Downgrade if the candidate behaves like another generic broad-trend tweak instead of a distinct regime-pause path.",
                "Downgrade if pause logic cuts drawdown only by missing most rebound participation.",
            ],
            "paper_requirements": [
                "Paper review must flag each regime pause, the trigger context, and whether re-entry lag created missed-rebound cost.",
            ],
        },
        "core_multifactor": {
            "hypothesis": (
                "A balanced blend of momentum, low volatility, value, quality, and liquidity may be "
                "more robust than a single-theme strategy in daily A-share research."
            ),
            "intended_regimes": ["neutral breadth", "moderate risk-on", "mild defensive"],
            "key_risks": [
                "Composite score may hide weak or contradictory factor components.",
                "Broad factor exposure can still crowd into the same industry or market-cap bucket.",
                "Monthly rebalance may lag rapid regime changes.",
            ],
            "extra_gates": [
                "Factor diagnostics must show at least two useful components across windows.",
                "Industry and liquidity concentration must be reviewed before paper-stage promotion.",
            ],
            "downgrade_conditions": [
                "Downgrade if one component explains most of the return or if adverse regimes are missing.",
            ],
            "paper_requirements": [
                "Paper plan should track factor score drift and target-weight concentration by rebalance date.",
            ],
        },
        "defensive_low_vol": {
            "hypothesis": (
                "A low-volatility and liquidity-focused basket may reduce drawdown enough to justify lower "
                "upside when the market is choppy or defensive."
            ),
            "intended_regimes": ["defensive", "risk-off recovery", "neutral low breadth"],
            "key_risks": [
                "Low-volatility names can become crowded and expensive.",
                "The candidate may lag badly in strong risk-on markets.",
                "Defensive behavior may disappear after transaction costs.",
            ],
            "extra_gates": [
                "Drawdown improvement versus core_multifactor must survive cost stress.",
                "Risk-on opportunity cost must be visible in regime validation, not ignored.",
            ],
            "downgrade_conditions": [
                "Downgrade if drawdown is not meaningfully better than the core candidate.",
            ],
            "paper_requirements": [
                "Paper review should compare realized drawdown and turnover against the core candidate.",
            ],
        },
        "momentum_quality": {
            "hypothesis": (
                "Momentum combined with quality and liquidity may capture persistent winners while avoiding "
                "some low-quality rebound traps."
            ),
            "intended_regimes": ["risk-on", "improving breadth", "sector leadership"],
            "key_risks": [
                "Momentum reversal can create abrupt drawdowns.",
                "Turnover may rise above the daily strategy budget.",
                "Recent winners can concentrate into one hot theme.",
            ],
            "extra_gates": [
                "Turnover and cost stress must be stricter than the core candidate.",
                "Regime validation must include at least one reversal or defensive window before promotion.",
            ],
            "downgrade_conditions": [
                "Downgrade if turnover, cost sensitivity, or theme concentration exceeds budget.",
            ],
            "paper_requirements": [
                "Paper loop should flag any rebalance dominated by a single hot industry or concept.",
            ],
        },
        "value_low_vol": {
            "hypothesis": (
                "Value plus low volatility may provide a slower mean-reversion candidate with lower behavioral "
                "chasing risk than pure momentum."
            ),
            "intended_regimes": ["neutral", "defensive", "post-drawdown stabilization"],
            "key_risks": [
                "Value traps may remain cheap for fundamental reasons.",
                "Low turnover can delay exits from deteriorating names.",
                "Accounting or point-in-time data gaps can overstate factor quality.",
            ],
            "extra_gates": [
                "Fundamental and valuation fields must have point-in-time evidence or be treated as non-PIT.",
                "Out-of-sample validation must check whether value signals decay slowly or vanish.",
            ],
            "downgrade_conditions": [
                "Downgrade if valuation data provenance is unclear or non-PIT leakage risk is unresolved.",
            ],
            "paper_requirements": [
                "Paper review should record whether stale fundamentals drive target holdings.",
            ],
        },
        "trend_filtered_core": {
            "hypothesis": (
                "A broad-trend exposure filter may reduce damage in weak markets while keeping the diversified "
                "core factor engine intact during healthier regimes."
            ),
            "intended_regimes": ["neutral", "defensive", "risk-off"],
            "key_risks": [
                "Trend filters can whipsaw and reduce compounding in sideways markets.",
                "Lower exposure may make the one-million capital path unrealistic.",
                "A broad index proxy may not match the selected universe.",
            ],
            "extra_gates": [
                "Compare filtered versus unfiltered core across the same walk-forward windows.",
                "Cash drag and missed-rebound cost must be explicitly reported.",
            ],
            "downgrade_conditions": [
                "Downgrade if the filter lowers drawdown only by giving up too much return for the goal path.",
            ],
            "paper_requirements": [
                "Paper state must record active filter days and target exposure scale.",
            ],
        },
    }
    return profiles.get(name, _fallback_profile(name))


def _fallback_profile(name: str) -> dict[str, list[str] | str]:
    return {
        "hypothesis": f"{name} is an unvalidated research candidate that must earn evidence before ranking.",
        "intended_regimes": ["unknown"],
        "key_risks": ["No bespoke risk profile has been written for this candidate."],
        "extra_gates": ["Write a bespoke hypothesis before promotion review."],
        "downgrade_conditions": ["Downgrade until a bespoke hypothesis and validation plan exist."],
        "paper_requirements": ["Do not enter paper observation until its hypothesis is reviewed."],
    }
