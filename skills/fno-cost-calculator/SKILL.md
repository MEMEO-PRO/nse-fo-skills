---
name: fno-cost-calculator
description: Full round-trip cost of Indian F&O trades (NSE/BSE index options and futures) - brokerage, STT at the post-1-Apr-2026 rates (0.15% on option sell premium, 0.05% on futures sell), exchange transaction charges, SEBI fee, stamp duty, GST - and the breakeven move in premium points. Use when the user asks what a trade, spread, straddle or iron condor will cost, the STT on a trade, cost drag, or the breakeven after charges.
license: MIT
compatibility: Python 3.11+ with nsefno installed. Rates are bundled in nsefno/data/charges.yaml (dated, with sources); lot size comes from the instrument master (network) or --lot-size.
metadata:
  tier: free
  adapters: rates kite_public
  version: 0.1.0
---

# F&O cost calculator

## When to use
"What will 2 lots of a 26200/26400 bull call spread cost round trip?", "STT on selling
a straddle", "cost of this iron condor", "how many points just to break even after charges".

## Steps
1. Express each leg as `SIDE LOTS TYPE [STRIKE] @ PRICE`:
   `python scripts/cost.py --index NIFTY --leg "BUY 2 CE 26200 @ 82" --leg "SELL 2 CE 26400 @ 31" --md`
   - Lot size comes from the instrument master for that index (or pass `--lot-size`).
   - `--broker zerodha | kotak_neo | zero` (brokerage plans in charges.yaml).
   - `--exit-prices 120,45` to cost the exit at specific prices (default: entry prices).
   - `--one-way` for entry only. `--trade-date YYYY-MM-DD` to apply historic rates.
2. Report the total, the breakdown line by line, and `breakeven_points`.
3. If a long option may be exercised ITM at expiry, mention exercise STT (0.15% of
   intrinsic value, paid by the buyer), which is not in the round-trip total.

## Output
`data.lines[]` (per phase/leg: turnover, brokerage, stt, exchange_txn, sebi_fee,
stamp_duty, gst, total), `data.totals`, `data.breakeven_points`, `data.rates_used` with
effective dates. Rate table and formulas: `references/charges.md`.

## Never
- Use remembered STT/charge rates - read them from the output's `rates_used`.
- Ignore that STT on options is on premium for sells, but on intrinsic value on exercise.
