---
name: fno-position-sizer
description: Size an Indian index options or futures position by risk budget and margin - exact expiry payoff max loss, max profit and breakevens for spreads, condors, straddles and futures, units allowed by capital × risk %, margin cap, max-lots cap, and warnings for naked short legs or unlimited risk. Use when the user asks how many lots they can trade, what the max loss of a structure is, or whether a structure has naked/undefined risk.
license: MIT
compatibility: Python 3.11+ with nsefno installed. Lot size from the instrument master (network) or --lot-size; margin optional from broker-margin-check.
metadata:
  tier: free
  adapters: kite_public rates
  version: 0.1.0
---

# F&O position sizer

## When to use
"How many lots of this iron condor with ₹5L and 2% risk?", "max loss of this spread",
"is this strangle naked?".

## Steps
1. Legs are per ONE unit of the structure (`lots` per leg = ratio):
   `python scripts/size.py --index NIFTY --capital 500000 --risk-pct 2 --spot 26150 --leg "BUY 1 CE 26200 @ 82" --leg "SELL 1 CE 26400 @ 31" --md`
2. Optional inputs:
   - `--margin-per-unit` (from broker-margin-check) and `--max-margin-pct` (default 50% of capital).
   - `--cost-per-unit` (from fno-cost-calculator total for one unit) to include charges in the risk.
   - `--max-lots` hard cap.
3. Report: max loss/profit per unit, breakevens, units allowed (and which constraint binds),
   max loss at that size, and every warning verbatim.

## Output
`data.risk` (max_loss_per_unit, max_profit_per_unit, unlimited_loss, breakevens,
naked_short_legs, credit_or_debit), `data.units_by_risk`, `data.units_by_margin`,
`data.units_allowed`, `data.lots_per_leg`, `data.max_loss_at_size`, `data.warnings`.

Max loss is computed exactly from the piecewise-linear expiry payoff (kinks at strikes).
It ignores early adverse marks, gap risk on exits and IV changes before expiry.

## Never
- Size an unlimited-risk structure by risk budget (the tool returns 0 units and a warning).
- Tell the user to take the trade; report the arithmetic only.
