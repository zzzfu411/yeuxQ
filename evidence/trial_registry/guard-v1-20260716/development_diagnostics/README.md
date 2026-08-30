# Guard v1 Development Diagnostics

These files were generated after preregistration from the contaminated
development prefix ending `2026-07-14`. They are retained for falsification and
audit only. They are not a holdout result and must never be appended as the
terminal result for `guard-v1-20260716`.

The run used CNY 100,000 starting capital, three selection-safe windows, both
candidate factor components, and regime validation. Deterministic outcomes:

- Precheck: `RESEARCH_ONLY`
- Promotion: `BLOCK`
- Walk-forward: `WATCH`; returns `+2.12%`, `+9.16%`, `-3.29%`
- Factor diagnostics: `WATCH`; zero of two components passed
- Regime validation: `WATCH`; risk-off return `-3.29%`
- Latest selection-window reject rate: `56.00%`
- Capital-goal annual-return margin: `-21.53%`
- Paper, micro-live, and broker-order permissions: all `false`

The run manifest config SHA differs from the frozen execution config SHA. This
prevents the development run from matching the formal trial review contract.
