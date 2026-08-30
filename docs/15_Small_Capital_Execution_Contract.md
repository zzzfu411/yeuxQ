# Small-Capital Execution Contract

## Why This Exists

The capital-goal workflow starts from CNY 100,000. A candidate cannot be scored
against that goal while its backtest silently uses the CNY 1,000,000 value from
the general research config. Candidate selection now uses
`CapitalGoal.starting_capital` as the actual portfolio cash.

This change can reduce returns, increase cash drag, and turn prior WATCH results
into BLOCK. That is expected: a strategy that works only after multiplying the
capital base has not passed the small-capital execution test.

## Lot Rejections

For A-share buys, the paper broker rounds quantities to 100-share lots. When a
positive target requests fewer than one lot, the broker now records an order:

```text
status = rejected
reason = below_lot
quantity = unrounded requested shares
```

It no longer silently skips the target. `below_lot` therefore contributes to
the reported order rejection rate.

## Reported Evidence

Candidate selection and stress results record:

- `execution_initial_cash`;
- `final_cash_ratio`;
- `min_commission_hit_count`;
- `below_lot_reject_count`;
- regular order count, rejection rate, turnover, drawdown, and return metrics.

The execution cash is also written at the top level of
`candidate_selection.json`.

## Mandatory Stress Scenarios

Every default candidate stress set includes:

- `small_capital_5bps`;
- `small_capital_10bps`;
- `small_capital_20bps`.

Each uses CNY 100,000, a 100-share lot, CNY 5 minimum commission, 0.05% stamp
tax, and the named slippage assumption. The existing `high_cost` scenario also
applies non-zero floors, so a zero-cost demo config cannot produce a zero-cost
stress result.

These outputs remain research-only. They do not prove liquidity, future
profitability, paper stability, or permission to submit real orders.
