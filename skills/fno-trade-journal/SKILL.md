---
name: fno-trade-journal
description: Local trade journal for Indian F&O - log each trade plan with a setup tag and thesis, record fills (manually or by importing a Zerodha tradebook CSV) with exact statutory costs, and produce a weekly post-mortem - win rate, gross/net P&L, cost drag, average win/loss, slippage versus planned prices and P&L by setup. Use when the user wants to journal a trade, import fills, or review the week.
license: MIT
compatibility: Python 3.11+ with nsefno installed. Stores data in SQLite at ~/.nsefno/journal.sqlite (override with --db). No network needed.
metadata:
  tier: paid
  adapters: local_store rates
  version: 0.1.0
---

# F&O trade journal

## Steps
1. Log a plan before the trade:
   `python scripts/journal.py plan --tag "expiry-straddle-short" --index NIFTY --legs plan.json --thesis "flat GEX, IV rank high" --md`
   -> returns `plan_id`.
2. Log fills (planned_price lets the review measure slippage):
   `python scripts/journal.py fill --plan-id 1 --symbol NIFTY26NOV26200CE --side SELL --qty 65 --price 81.5 --planned-price 82 --md`
   or import a Zerodha Console tradebook: `python scripts/journal.py import --csv tradebook.csv --plan-id 1`.
   Duplicate trade IDs are ignored, so re-importing is safe.
3. Weekly review: `python scripts/journal.py review --days 7 --md`
4. Report win rate, net P&L, cost drag (% of gross), slippage, and the by-setup table.
   Ask the user what they would change - do not prescribe trades.

## Output
`data.trades[]` per plan (closed, gross_pnl, costs, net_pnl, slippage_inr, slippage_pts)
plus period aggregates. Costs per fill use fno-cost-calculator rates for the fill date.

## Never
- Upload the journal anywhere; it is local by design.
- Turn the review into buy/sell advice.
