# Agent Team Execution

This file records how the first-million objective is split across agents. It is
an execution note, not a profit claim and not live-trading permission.

## Current Truth

- Recent A-share cache is not usable for strategy evidence.
- `data_cache/research_recent.db` has no usable recent bars.
- AKShare/Eastmoney smoke import is blocked by network/proxy access.
- `data_exports/bars.csv` is a tiny stale sample ending on `2024-01-03`.
- `data_source_qa_answers.json` is missing.
- No candidate strategy may be promoted from this evidence state.

## Agent Roles

| role | responsibility | allowed output |
| --- | --- | --- |
| Data pipeline | Make real-data acquisition, CSV validation, TDX/OHLCV intake, and import evidence harder to misuse. | Code/tests for data modules and import scripts. |
| Strategy experiments | Map the smallest honest OHLCV-only experiment path, especially `price_volume_defensive` and `regime_pause_price_volume`. | Read-only findings, command chain, missing artifacts. |
| Risk and goal control | Keep the one-million compounding goal gated by real data, robustness, paper stability, and approval evidence. | Code/tests for goal/readiness gates. |
| Main integrator | Review agent outputs, resolve conflicts, run validation, and decide what is actually proven. | Integrated code, refreshed evidence artifacts, final status. |

## Non-Negotiable Gates

- Demo, template, stale, empty, or unverifiable data cannot support a strategy claim.
- Promotion-facing caches must carry `csv_dataset_fingerprint`,
  `data_source_qa_status=PASS`, `data_source_csv_qa_status=PASS`, and retained
  source QA checklist/answers hashes in SQLite `research_metadata`; see
  [Promotion Metadata Gate](13_Promotion_Metadata_Gate.md).
- LLM output cannot upgrade deterministic `PASS/WATCH/BLOCK`.
- No broker integration and no unattended live orders.
- OHLCV-only data can only support OHLCV-only candidates.
- PIT fundamentals and index membership are required before fundamental-dependent candidates run.
- Any `BLOCK` keeps the workflow in research/data-preparation mode.

## Next Evidence Needed

1. Real daily A-share OHLCV covering `2024-06-03` to `2026-06-05`.
2. At least 300 symbols for broad recent-research evidence.
3. Source QA answers with vendor/export/license/adjustment proof.
4. CSV validation with no `BLOCK`.
5. Guarded offline intake that records CSV fingerprint, PASS source QA
   metadata, retained evidence hashes, and then real-data bootstrap `PASS`.
6. Candidate experiment execution, completion, robustness, and paper stability evidence.
7. Human approval before any `micro_live_ready` claim.

## Current Operator Packet

`data_evidence_action_packet.json/md` is the shared work order for the agent
team while real-data evidence is blocked. The readiness card includes it as a
gate, and the strategy brief uses its first next action to keep all agents
pointed at source QA, CSV replacement, and guarded offline intake before any
strategy experiment.
The capital-goal status dashboard also reads this packet when present, so the
one-million compounding objective stays closed until the packet's blockers are
resolved by real evidence.
`operator_handoff.csv/md` is generated alongside the packet as the unified
operator queue. Agents may use it to coordinate row-level source QA evidence
tasks and file-level CSV export tasks, but it cannot approve data, strategy
research, paper trading, live trading, or profitability claims.
`operator_handoff_status.json/md` summarizes that queue with open P0/P1 counts
and the first remaining actions. It is a progress board only; deterministic
data and readiness gates still decide whether work can advance.

## Candidate Regime Evidence

`candidate_selection` now consumes `candidate_regime_validation_report.json`
when it exists. The selection report records per-candidate regime validation
status and summary counts, and the weekly pipeline passes the generated regime
validation report into candidate selection automatically. Missing or unmatched
regime evidence remains insufficient promotion evidence, while candidate-level
BLOCK regime buckets block that candidate from `selected_candidate`.

## Research-Only Candidate Precheck

`examples/run_candidate_research_precheck.py` is the formal way to do a fast,
non-promotional candidate triage on an existing cache. It intentionally does not
accept `--gate-report-dir`, does not call the launch gate, and always writes a
`candidate_research_precheck.json/md` plus `research_precheck_notice.json/md`
with `status=RESEARCH_ONLY` and `promotion_decision=BLOCK`.

Typical single-candidate use:

```powershell
python examples/run_candidate_research_precheck.py --config config/research_recent.yaml --cache tmp\akshare_recent_explicit_300_stratified.db --output-dir results\research_recent\<timestamp>_low_turnover_precheck --candidate low_turnover_price_volume
```

Optional, slower evidence:

```powershell
python examples/run_candidate_research_precheck.py --config config/research_recent.yaml --cache tmp\akshare_recent_explicit_300_stratified.db --output-dir results\research_recent\<timestamp>_low_turnover_precheck --candidate low_turnover_price_volume --include-factor-diagnostics --include-regime-validation
```

This precheck may inform the next preregistered experiment, but it cannot
satisfy `candidate_experiment_launch.json`, enter paper, approve micro-live
readiness, or generate broker instructions.

## Candidate Next Experiments

`candidate_next_experiments.json/md/csv` turns blocked precheck or candidate
selection evidence into a research-only follow-up queue. It diagnoses issues
such as negative recent returns, high turnover, weak Sharpe, drawdown pressure,
trend-filter cash drag, missing factor diagnostics, missing regime validation,
and missing promotion evidence.

It is generated automatically by `run_candidate_research_precheck.py` and can
also merge one or more existing report directories:

```powershell
python examples/run_candidate_next_experiments.py --report-dir results\research_recent\<timestamp>_low_turnover_precheck --report-dir results\research_recent\<timestamp>_trend_filtered_price_volume_precheck --output-dir results\research_recent\next_experiments
```

The output is deliberately fenced with `status=RESEARCH_ONLY` and
`promotion_decision=BLOCK`. It may propose only offline research actions. It
cannot approve paper, satisfy guarded launch, generate broker instructions, or
change deterministic gates.

## Candidate Experiment Design Matrix

`candidate_experiment_design_matrix.json/md/csv` expands the pre-registered
candidate queue into candidate-by-stress-scenario coverage before backtest
results are known. It records the baseline, concentration, rebalance,
turnover/stability, cost-stress, and trend-filter ablation scenarios that later
stress-matrix runs must cover.

```powershell
python examples/write_candidate_experiment_design_matrix.py --config config\research_recent.yaml --output-dir results\first_million --as-of 2026-06-10
```

The artifact is a design contract, not research evidence. It keeps
`can_enter_paper=false` and `can_generate_broker_orders=false`; it cannot rank
candidates, approve guarded launch, or replace source QA and completion gates.

## Candidate Stress Matrix

`candidate_stress_matrix.json/md/csv` runs candidate-specific parameter and
cost stress scenarios while preserving the candidate's factors and data
dependency. Typical scenarios include baseline, wider basket, lower
concentration, alternate rebalance cadence, high cost, and trend-filter
ablation for trend-filtered candidates.

```powershell
python examples/run_candidate_research_stress_matrix.py --config config\research_recent.yaml --cache tmp\akshare_recent_explicit_300_stratified.db --output-dir results\research_recent\<timestamp>_stress --candidate low_turnover_price_volume
```

The artifact is research evidence only. It is always fenced with
`status=RESEARCH_ONLY` and `promotion_decision=BLOCK`; even if one scenario
passes basic stress thresholds, source QA, launch, completion, paper stability,
and human approval gates still own promotion decisions.

Use `examples/run_candidate_stress_matrix.py` only inside the guarded candidate
execution chain after `candidate_experiment_launch.json` is `PASS`. For ungated
research triage, use `examples/run_candidate_research_stress_matrix.py`; it
does not accept `--gate-report-dir` and cannot create paper or broker
permission.

## Current Candidate Pool

The preregistered pool now has thirteen OHLCV-only candidates before any
PIT-fundamental strategy is allowed to compete:

- `price_volume_defensive`: the first defensive OHLCV-only baseline.
- `low_turnover_price_volume`: a quarterly, broader low-turnover defensive
  variant.
- `low_turnover_low_concentration_price_volume`: the same quarterly low-turnover
  path with a lower max-weight cap to test whether concentration relief improves
  drawdown or Sharpe.
- `trend_filtered_price_volume`: an OHLCV-only price-volume variant that cuts
  target exposure when the broad universe trend is weak.
- `trend_filtered_quarterly_price_volume`: the quarterly cadence version of the
  trend-filtered defensive path, added to test whether slower rebalance reduces
  noise without hiding cash drag.
- `trend_filtered_quarterly_low_concentration_price_volume`: the lower max-weight
  version suggested by the quarterly trend-filtered stress matrix; it must be
  rerun as a separate research candidate before it can be compared.
- `defensive_scaled_quarterly_price_volume`: a quarterly price-volume path that
  keeps moderate concentration but cuts target exposure in defensive-or-worse
  regimes to test whether the 2025-2026 defensive bucket losses can be reduced
  without giving up neutral-market rebound participation.
- `stable_universe_slow_signal_price_volume`: a wide quarterly OHLCV-only
  basket using very low volatility, low volatility, liquidity, and
  `long_momentum_120d_skip20d` to test whether slower raw signals reduce
  structural turnover better than hold buffers, drift bands, new-position caps,
  or score smoothing.
- `long_momentum_liquidity_monthly_price_volume`: a monthly OHLCV-only
  component-ablation path using only `long_momentum_120d_skip20d` and liquidity
  to test whether the slow-signal basket was diluted by low-volatility
  components. It is a diagnostic research candidate, not a promotion.
- `liquidity_neutral_momentum_guard_price_volume`: a guarded OHLCV-only
  liquidity-neutral momentum path using a residualized long-momentum signal,
  very low volatility, quarterly rebalance, and defensive-or-worse exposure
  scaling. It tests whether the prior momentum/liquidity evidence survives
  without direct liquidity alpha and with lower defensive-window damage.
- `defensive_cash_guard_price_volume`: a stronger cash-guard variant with a
  broader basket, lower max weight, quarterly rebalance, and a lower weak-trend
  exposure scale.
- `risk_off_cash_stop_price_volume`: a stricter risk-off cash-stop path that
  tests whether full weak-trend avoidance is better than partial exposure cuts.
- `regime_pause_price_volume`: an explicit regime-pause path that stops risk
  taking on reviewed weak-market evidence instead of acting like a generic
  broad-trend tweak.

`trend_filtered_price_volume`, `trend_filtered_quarterly_price_volume`,
`trend_filtered_quarterly_low_concentration_price_volume`,
`defensive_scaled_quarterly_price_volume`,
`stable_universe_slow_signal_price_volume`,
`long_momentum_liquidity_monthly_price_volume`,
`liquidity_neutral_momentum_guard_price_volume`,
`defensive_cash_guard_price_volume`, `risk_off_cash_stop_price_volume`, and
`regime_pause_price_volume` are
research hypotheses for weak markets, not paper or live permissions. Their key
falsification checks are cash drag, missed-rebound cost, and whether lower
drawdown simply comes from being mostly uninvested or from a non-distinct
pause/resume rule.

`low_turnover_low_concentration_price_volume`,
`trend_filtered_quarterly_price_volume`, and
`trend_filtered_quarterly_low_concentration_price_volume` are now explicit
comparison candidates, not generic variants. `defensive_scaled_quarterly_price_volume`
is a follow-up defensive-regime hypothesis generated from the latest
walk-forward/regime split, where neutral windows were profitable but defensive
windows drove losses. `stable_universe_slow_signal_price_volume` is the next
structural turnover hypothesis after turnover controls and past-only score
smoothing failed to materially reduce maintenance turnover.
`long_momentum_liquidity_monthly_price_volume` is the preregistered follow-up
component ablation after the slow-signal diagnostics showed low-volatility
dilution and long-momentum/liquidity dominance. Their next experiments must be
head-to-head checks versus
their immediate baselines (`low_turnover_price_volume`,
`trend_filtered_price_volume`, `trend_filtered_quarterly_price_volume`, and the
low-concentration quarterly variant, plus `defensive_scaled_quarterly_price_volume`
for the slow-signal path, plus `stable_universe_slow_signal_price_volume` for
the component-ablation path) across full-sample, walk-forward, factor, regime, and
stress evidence before any further parameter search.

## 2026-06-12 Recent A-share Candidate Evidence

Using `tmp\akshare_recent_explicit_300_stratified.db`, two OHLCV-only defensive
candidates were rerun with factor diagnostics and regime validation:

- `results\research_recent\20260612_203004_low_turnover_full_precheck`
- `results\research_recent\20260612_203004_trend_filtered_full_precheck`
- merged follow-up queue:
  `results\research_recent\20260612_203004_next_experiments_full`

Both prechecks remain `RESEARCH_ONLY` with `promotion_decision=BLOCK`.

`low_turnover_price_volume`:

- latest selection annualized return: `-18.70%`
- latest Sharpe: `-1.62`
- average turnover: `93.34%`
- factor diagnostics: `WATCH`, component PASS ratio `0%`, best single factor
  return `6.86x` composite return
- regime validation: `WATCH`; neutral bucket `PASS`, defensive bucket `WATCH`
  with non-positive average return

`trend_filtered_price_volume`:

- latest selection annualized return: `-16.67%`
- latest Sharpe: `-1.00`
- average turnover: `82.75%`
- trend filter active days across recent windows: `3`
- factor diagnostics: `WATCH`, component PASS ratio `0%`
- regime validation: `WATCH`; neutral bucket `PASS`, defensive bucket `WATCH`
  with non-positive average return

Interpretation: neither candidate is currently usable for paper or micro-live
preparation. The evidence points to defensive-regime failure, weak recent
risk-adjusted returns, high turnover, and insufficient component robustness.
The next research loop should focus on regime-aware risk reduction and turnover
control, while source QA/offline-intake blockers remain the top system gate.

Additional recent failed-window stress matrices were run for `2026-02-27` to
`2026-05-27`:

- `results\research_recent\20260612_204230_low_turnover_stress_recent_failed_window`
- `results\research_recent\20260612_204230_trend_filtered_stress_recent_failed_window`

Stress interpretation:

- `low_turnover_price_volume`: all four tested scenarios stayed `WATCH`; the
  baseline lost `-4.73%`, wider basket lost `-5.78%`, and high-cost stress lost
  `-4.83%`. Turnover remained high at roughly `80.68%` to `93.50%`.
- `trend_filtered_price_volume`: all six tested scenarios stayed `WATCH`. The
  best defensive-window trade-off was `lower_concentration`, improving turnover
  to `58.78%` and max drawdown to `7.08%`, but it still lost `-3.56%`.
- Trend-filter ablation did not rescue the failed window: `trend_filter_off`
  lost `-4.31%`, while `trend_filter_stronger` lost `-4.12%`.

Conclusion: lower concentration helps execution/risk hygiene for the
trend-filtered candidate, but it does not solve the defensive-regime return
failure. These candidates remain research-only, and the next strategy work
should search for a different defensive signal or explicitly avoid deploying
these recipes in defensive regimes.

## Defensive Cash Guard Candidate

`defensive_cash_guard_price_volume` was added as the next OHLCV-only research
hypothesis after the ordinary low-turnover and trend-filtered defensive recipes
failed the recent defensive window. It uses very-low-volatility, low-volatility,
and liquidity factors, holds at least 60 names, caps single-name weight at
2.5%, rebalances quarterly, and scales weak-trend target exposure to 15%.

This candidate is intentionally conservative but not approved. Its first
required evidence is a direct comparison against the failed `2026-02-27` to
`2026-05-27` window and a stress matrix covering baseline, wider basket, lower
concentration, high cost, trend-filter-off, and stronger-filter scenarios. It
must remain `RESEARCH_ONLY/BLOCK` until source QA, guarded launch, completion,
paper stability, and human approval gates pass.

## 2026-06-13 Defensive Cash Guard Evidence

`defensive_cash_guard_price_volume` was rerun on
`tmp\akshare_recent_explicit_300_stratified.db` with factor diagnostics and
regime validation:

- precheck:
  `results\research_recent\20260613_003229_defensive_cash_guard_precheck`
- failed-window stress:
  `results\research_recent\20260613_004112_defensive_cash_guard_stress_recent_failed_window`
- merged next-experiment queue:
  `results\research_recent\20260613_004112_next_experiments_with_cash_guard`

The precheck remains `RESEARCH_ONLY` with `promotion_decision=BLOCK`; no
candidate was selected for paper. Latest-window candidate selection over
`2026-02-27` to `2026-05-27` returned `BLOCK`:

- annualized return: `-11.96%`
- total return: `-2.94%`
- max drawdown: `5.59%`
- Sharpe: `-1.33`
- average turnover: `86.88%`
- trend-scale parameter: `0.15`

Walk-forward remained `WATCH`: three recent windows produced one `PASS` and
two `WATCH`, with only `33.33%` positive forward windows. Factor diagnostics
also stayed `WATCH`: zero of three components passed, and the best single
component still had negative average return. Regime validation stayed `WATCH`:
the neutral bucket passed, but the defensive bucket had average return
`-2.23%` and Sharpe `-0.99`.

The failed-window stress matrix also did not rescue the candidate. All six
scenarios were `WATCH`:

- baseline: `-2.94%`
- wider basket: `-3.42%`
- lower concentration: `-2.94%`
- high cost: `-3.04%`
- trend filter off: `-4.93%`
- stronger trend filter: `-2.78%`

Interpretation: stronger cash guarding reduced damage versus turning the trend
filter off, but it still lost money in the defensive window and did not solve
turnover or risk-adjusted return. The three OHLCV-only defensive candidates now
share the same failure pattern: negative adverse-window returns, weak Sharpe,
high turnover, and watch-only regime evidence. They remain research-only, and
the next loop should either find a different defensive signal or explicitly
gate these recipes away from defensive regimes.

## 2026-06-18 Risk-Off Cash Stop Evidence

`risk_off_cash_stop_price_volume` was rerun on the same recent A-share cache
with factor diagnostics, regime validation, and failed-window stress:

- precheck:
  `results\research_recent\20260613_005900_risk_off_cash_stop_precheck`
- failed-window stress:
  `results\research_recent\20260613_010300_risk_off_cash_stop_stress_recent_failed_window`
- merged next-experiment queue:
  `results\research_recent\20260618_021500_next_experiments_with_cash_stop`

The candidate remained `RESEARCH_ONLY` with `promotion_decision=BLOCK`.
Latest-window candidate selection over `2026-02-27` to `2026-05-27` was worse
than the partial cash-guard variant:

- annualized return: `-24.47%`
- total return: `-6.36%`
- max drawdown: `7.35%`
- Sharpe: `-2.57`
- average turnover: `67.17%`
- trend-scale parameter: `0.00`

Walk-forward stayed `WATCH`: three windows produced one `PASS` and two
`WATCH`, with only `33.33%` positive forward windows and a worst window of
`-6.36%`. Factor diagnostics stayed `WATCH`: all three components were still
`WATCH`, with `0/3` passing. Regime validation stayed `WATCH`: neutral windows
passed, but defensive windows averaged `-4.24%` with Sharpe `-1.76`.

The failed-window stress matrix also stayed `WATCH` for all six scenarios. The
best variant was `wider_basket` at `-5.67%`, while `trend_filter_off` still
lost `-6.34%`. The strict cash-stop logic almost never activated, so the
candidate behaved more like a weaker invested basket than a real cash stop.

Interpretation: the full cash-stop idea does not solve the recent defensive
window. It is worse than `defensive_cash_guard_price_volume`, worse than the
older `trend_filtered_price_volume`, and worse than `low_turnover_price_volume`
on the same failed-window comparison. This direction should be treated as
another research-only failure, not a better defensive recipe.

## 2026-06-18 New Variant Evidence

Two additional OHLCV-only comparison candidates were tested on the same recent
A-share cache:

- precheck output:
  `results\research_recent_real_candidates\20260618_new_variants_precheck`
- stress output:
  `results\research_recent_real_candidates\20260618_new_variants_stress`

Both remained research-only and did not earn promotion:

- `low_turnover_low_concentration_price_volume`: best stress path reached about
  `12.46%` annualized return, `0.81` Sharpe, and `13.9%` max drawdown, but the
  latest walk-forward window was still negative.
- `trend_filtered_quarterly_price_volume`: best stress path reached about
  `21.14%` annualized return, `1.13` Sharpe, and `18.3%` max drawdown, but the
  latest walk-forward window was also negative.
- The `lower_concentration` stress scenario inside
  `trend_filtered_quarterly_price_volume` reached `PASS` with about `15.72%`
  annualized return, `1.14` Sharpe, `13.8%` max drawdown, and `73.06%` turnover.
  That is a hypothesis-generation signal only, so it is now registered as
  `trend_filtered_quarterly_low_concentration_price_volume` for a separate
  research-only rerun.

Interpretation: both variants were directionally better than their immediate
baselines in at least one stress path, but neither has enough walk-forward
resilience to justify promotion. The right next step is not another isolated
tweak. It is a direct baseline comparison:

- `low_turnover_low_concentration_price_volume` versus
  `low_turnover_price_volume`
- `trend_filtered_quarterly_price_volume` versus
  `trend_filtered_price_volume`
- `trend_filtered_quarterly_low_concentration_price_volume` versus
  `trend_filtered_quarterly_price_volume`

That comparison should use the same real cache, all available windows, factor
diagnostics, regime validation, and stress scenarios. Until then, all three
remain research-only comparison candidates.

## 2026-07-05 Defensive-Scaled Quarterly Evidence

`defensive_scaled_quarterly_price_volume` is the current best research-only
candidate in the first-million rollup, but it is not paper-ready:

- precheck:
  `results\research_recent_real_candidates\20260705_defensive_scaled_quarterly_precheck_lite`
- stress:
  `results\research_recent_real_candidates\20260705_defensive_scaled_quarterly_stress_lite`
- lightweight factor/regime triage:
  `results\research_recent_real_candidates\20260705_defensive_scaled_quarterly_factor_diag_tiny`
- merged next-experiment queue:
  `results\research_recent_real_candidates\20260705_defensive_scaled_quarterly_next_experiments_v2`

The latest rollup still reports `RESEARCH_ONLY/BLOCK`: annualized return is
about `25.41%`, max drawdown `16.63%`, Sharpe `1.47`, turnover `90.04%`, reject
rate `6.48%`, and capital-goal return margin `-7.94%`. Walk-forward, factor,
regime, and stress evidence are all `WATCH`.

Full factor diagnostics on the recent cache were too slow for the daily
research loop, so factor diagnostics now support a lightweight triage cap:

```powershell
python examples/run_candidate_research_precheck.py --config config/research_recent.yaml --output-dir results/research_recent/<timestamp> --candidate defensive_scaled_quarterly_price_volume --include-factor-diagnostics --factor-max-components 1
```

This cap must be treated as incomplete evidence. The generated report records
`component_count`, `total_component_count`, and `component_limit`, and a limited
diagnostic stays `WATCH` until the full component set can be reviewed.

The first-million mainline remains blocked by data evidence, not by strategy
ranking. `results\first_million\source_qa_closeout.json` is still `BLOCK` with
13 worksheet gaps, 5 missing attachments, and 29 open actions. No paper,
micro-live readiness, or broker-order workflow is allowed until source QA,
offline intake, launch/completion evidence, paper stability, and human approval
are all present.

## 2026-07-05 Turnover-Control Ablation

The research engine now supports three low-turnover target-generation controls
and one signal-stability control:

- `hold_rank_buffer`: keep existing holdings if they remain within the top
  `n_holdings + buffer` ranked names.
- `min_trade_weight`: skip tiny target-weight drift trades below the configured
  weight band.
- `max_new_positions`: cap how many previously unheld symbols can enter the
  portfolio on one rebalance.
- `score_smoothing_observations` / `score_smoothing_step_days`: average
  composite scores from `as_of` and earlier trading days only, testing whether
  ranking jumps are the source of recurring turnover.

These controls are exposed through the research-only stress scenario
`turnover_control`. The stronger research-only scenario `stability_control`
adds a full-basket hold-rank buffer, a wider drift threshold, and a per-rebalance
new-position cap. The research-only scenario `score_smoothing` uses past-only
score smoothing. These are not broker permissions and do not change any
deterministic gate.

Turnover evidence is split into `initial_turnover_pct` for the first deployment
and `avg_maintenance_turnover_pct` / `max_maintenance_turnover_pct` for
recurring post-deployment turnover. Maintenance turnover is the recurring
friction signal; all stress and next-experiment outputs remain research-only and
cannot upgrade gates.

A 2026 smoke stress was run for `defensive_scaled_quarterly_price_volume`:

- stress output:
  `results\research_recent_real_candidates\20260705_defensive_scaled_turnover_control_stress_2026_smoke`
- merged next-experiment queue:
  `results\research_recent_real_candidates\20260705_defensive_scaled_turnover_control_next_experiments`

Result: `turnover_control` did not improve the candidate. Baseline and
turnover-control both had total return `3.76%`, max drawdown `17.11%`, Sharpe
`0.54`, average turnover `82.36%`, and maintenance turnover `82.70%` on the
smoke window. The next-experiment report therefore flags
`turnover_control_ablation_failed` and explicitly says not to promote the
hold-buffer/min-trade-threshold variant.

The stronger `stability_control` scenario was then run on the same 2026 smoke
window:

- stress output:
  `results\research_recent_real_candidates\20260705_defensive_scaled_stability_control_stress_2026_smoke`
- merged next-experiment queue:
  `results\research_recent_real_candidates\20260705_defensive_scaled_stability_control_next_experiments`

It also failed to change the realized path: baseline, `turnover_control`, and
`stability_control` all had total return `3.76%`, max drawdown `17.11%`, Sharpe
`0.54`, average turnover `82.36%`, and maintenance turnover `82.70%`.
The next-experiment queue now flags both `turnover_control_ablation_failed` and
`stability_control_ablation_failed`.

The `score_smoothing` scenario was then run on the same 2026 smoke window:

- stress output:
  `results\research_recent_real_candidates\20260705_defensive_scaled_score_smoothing_stress_2026_smoke`
- merged next-experiment queue:
  `results\research_recent_real_candidates\20260705_defensive_scaled_score_smoothing_next_experiments`

It also failed as a promotion path. Baseline total return was `3.76%`, max
drawdown `17.11%`, Sharpe `0.54`, and maintenance turnover `82.70%`.
`score_smoothing` moved total return to `-1.74%`, max drawdown to `7.30%`,
Sharpe to `-0.40`, and maintenance turnover only to `82.16%`. The
next-experiment queue now flags `score_smoothing_ablation_failed`. The next
research direction should move away from these order-path controls toward a
more stable universe or a different slower-turnover signal definition.

`stable_universe_slow_signal_price_volume` has therefore been registered as
the next research-only structural test. It uses a wide quarterly basket,
`long_momentum_120d_skip20d`, very low volatility, low volatility, and
liquidity, and should be compared head-to-head against
`defensive_scaled_quarterly_price_volume` before any further target-generation
control is added. It cannot enter paper while source QA and promotion evidence
remain `BLOCK`.

The first 2026 smoke stress for this candidate was run at:

- `results\research_recent_real_candidates\20260705_stable_universe_slow_signal_stress_2026_smoke`
- next-experiment output:
  `results\research_recent_real_candidates\20260705_stable_universe_slow_signal_next_experiments`

The result stayed `RESEARCH_ONLY/BLOCK/WATCH`. Baseline total return was
`-2.62%`, max drawdown `9.16%`, Sharpe `-0.43`, average turnover `69.49%`,
and maintenance turnover `50.29%`. The monthly `rebalance_alt` scenario was the
least-bad path, with total return `0.83%`, max drawdown `7.50%`, Sharpe `0.23`,
average turnover `44.73%`, and maintenance turnover `35.94%`. Interpretation:
the slow-signal design did reduce recurring turnover versus the defensive-scaled
baseline, but it did not produce enough return or risk-adjusted evidence to
change the research focus. `defensive_scaled_quarterly_price_volume` remains the
current best research-only candidate, and source QA still blocks all paper or
broker-related stages.

A full research precheck with factor diagnostics and regime validation was then
run at:

- `results\research_recent_real_candidates\20260705_stable_universe_slow_signal_precheck_full_diag`

This stronger evidence also stayed `RESEARCH_ONLY/BLOCK`: full-sample
annualized return was `12.66%`, total return `25.84%`, max drawdown `11.86%`,
Sharpe `0.84`, average turnover `69.77%`, maintenance turnover `67.63%`, and
capital-goal return margin `-20.69%`. Walk-forward stayed `WATCH` with three
windows, one `PASS`, two `WATCH`, a `33.33%` positive-window ratio, and a worst
window of `-5.32%`. Factor diagnostics stayed `WATCH`: no component passed,
`long_momentum_120d_skip20d` was the best component, and the best single-factor
return was `25.97x` the composite return. Regime validation stayed `WATCH`.

Interpretation: this is not a stable compounding candidate. The useful evidence
is diagnostic: low-volatility components appear to dilute the candidate, while
long momentum and liquidity carry most of the signal. The next research step
should be a pre-registered component-ablation path, not paper observation and
not another execution-control overlay.

`long_momentum_liquidity_monthly_price_volume` has therefore been registered as
that pre-registered component-ablation path. It remains `RESEARCH_ONLY/BLOCK`
until independently tested; it cannot bypass source QA, experiment launch,
completion, paper stability, human approval, or broker safety gates.

Its first 2026 smoke stress was run at:

- `results\research_recent_real_candidates\20260705_long_momentum_liquidity_stress_2026_smoke`

The result stayed `RESEARCH_ONLY/BLOCK/WATCH`. Baseline total return was
`6.46%`, max drawdown `17.23%`, Sharpe `0.77`, average turnover `44.87%`, and
maintenance turnover `36.58%`. The `rebalance_alt` scenario reached `9.80%`
total return and Sharpe `1.07`, but average turnover rose to `72.32%` and
maintenance turnover to `58.29%`. High-cost stress also stayed `WATCH`.

A full research precheck with factor diagnostics and regime validation was then
run at:

- `results\research_recent_real_candidates\20260705_long_momentum_liquidity_precheck_full_diag`

This also stayed `RESEARCH_ONLY/BLOCK`. Full-sample annualized return was
`22.22%`, total return `47.26%`, max drawdown `17.80%`, Sharpe `1.01`, average
turnover `43.19%`, maintenance turnover `41.36%`, and capital-goal return
margin `-11.13%`. Walk-forward stayed `WATCH` with three windows, one `PASS`,
two `WATCH`, a `33.33%` positive-window ratio, worst return `-8.11%`, and worst
drawdown `16.11%`. Factor diagnostics stayed `WATCH`: zero of two components
passed, `liquidity_amount_20d` was the best component, and the dependency ratio
was `0.98`. Regime validation stayed `WATCH`: the neutral bucket passed, but
the defensive bucket averaged `-6.21%` with `13.10%` drawdown.

Interpretation: the component ablation improved headline full-sample return
versus the slow-signal basket, but it is not a stable compounding candidate.
The evidence points to liquidity dependency, defensive-regime weakness, high
drawdown pressure, and insufficient forward-window consistency. The next
research step should test whether long momentum can survive a liquidity-neutral
or defensive-regime guard ablation before adding any new execution control. It
still cannot enter paper, micro-live readiness, or broker workflows.

`liquidity_neutral_momentum_guard_price_volume` has therefore been registered
as a direct test of that failure mode. It uses a liquidity-neutral
`long_momentum_120d_skip20d` residual plus very low volatility, with a
defensive-or-worse exposure guard. This is a research-only mechanism test, not
a promotion candidate.

The first comparative precheck was run at:

- `results\research_recent_real_candidates\20260705_liquidity_neutral_guard_precheck_full_diag`

It compared `defensive_scaled_quarterly_price_volume`,
`long_momentum_liquidity_monthly_price_volume`, and
`liquidity_neutral_momentum_guard_price_volume`. The result stayed
`RESEARCH_ONLY/BLOCK`. The top research candidate remained
`defensive_scaled_quarterly_price_volume`. The liquidity-neutral guard had
full-sample annualized return `21.60%`, total return `45.82%`, max drawdown
`8.13%`, Sharpe `1.52`, average turnover `68.37%`, maintenance turnover
`76.92%`, and capital-goal return margin `-11.75%`. Walk-forward stayed
`WATCH` with three windows, one `PASS`, two `WATCH`, a `33.33%` positive-window
ratio, worst return `-2.98%`, and worst drawdown `7.59%`. Factor diagnostics
from the completed diagnostic pass stayed `WATCH`: zero of two components
passed, the liquidity-neutral momentum residual was the best component, and the
dependency ratio was `1.13`. Regime validation stayed `WATCH`: the defensive
bucket improved versus the unguarded ablation but still averaged `-1.88%`.

Its first 2026 stress matrix was run at:

- `results\research_recent_real_candidates\20260705_liquidity_neutral_guard_stress_2026_smoke`

The stress result stayed `RESEARCH_ONLY/BLOCK/WATCH`. No scenario passed.
Baseline total return was `3.79%`, max drawdown `7.67%`, Sharpe `0.79`,
average turnover `91.09%`, and maintenance turnover `91.29%`. The monthly
`rebalance_alt` scenario lost `-2.36%` with `10.49%` drawdown; turning the trend
filter off also lost `-0.22%`. High-cost stress remained `WATCH`.

Interpretation: liquidity neutralization and defensive guarding lowered
drawdown and reject pressure, but it also reduced the return path too much and
did not fix positive-window stability or turnover. It is useful as evidence
that defensive risk control can reduce damage, but it is not a stable
compounding candidate and cannot enter paper. The next research focus remains
finding a signal that improves forward-window consistency and return margin
without reintroducing high drawdown or liquidity dependency.

The next-experiment queue now treats this as a lineage closeout, not a prompt
to add another factor. `liquidity_neutral_guard_lineage_review` compares
`stable_universe_slow_signal_price_volume`,
`long_momentum_liquidity_monthly_price_volume`, and
`liquidity_neutral_momentum_guard_price_volume` on identical windows so the
team can attribute whether the damage came from the slow-signal base, liquidity
dependency, liquidity neutralization, quarterly cadence, or the defensive guard.
The output remains `RESEARCH_ONLY/BLOCK` and cannot enter paper, micro-live
readiness, or any broker workflow.
