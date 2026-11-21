---
name: option-chain-snapshot
description: Clean option-chain snapshot for one NSE index expiry (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY) - LTP, bid/ask mid, OI and change in OI (in contracts), volume, IV solved with Black-76 on the put-call-parity forward, Greeks, ATM strike, ATM straddle, expected move, PCR and max pain. Use when the user asks for the option chain, ATM IV, straddle price, PCR, max pain, OI build-up at strikes, or needs a chain as input to GEX or skew.
license: MIT
compatibility: Python 3.11+ with nsefno installed. Starter path uses the NSE public option-chain JSON (best effort, no login); `--source kite` uses Kite Connect quotes (KITE_API_KEY, KITE_ACCESS_TOKEN); `--file` analyses a saved chain offline.
metadata:
  tier: free
  adapters: nse_public kite local_store
  version: 0.1.0
---

# Option chain snapshot

## When to use
The user wants the chain, ATM IV / straddle, PCR, max pain, highest-OI strikes, or another
skill (GEX, skew) needs a fresh chain.

## Steps
1. `python scripts/snapshot.py NIFTY --expiry next --md`
   - `--expiry` accepts `next`, `far`, `monthly` or `YYYY-MM-DD` (resolved against the
     instrument master, so holiday-shifted dates are right).
   - `--save` stores the snapshot under `~/.nsefno/snapshots/` so later runs can diff.
   - `--source kite` for broker quotes (needed for SENSEX/BANKEX, which NSE does not publish).
   - `--file path.json` to analyse a saved NSE payload or a saved snapshot.
2. If the command fails with `StaleDataError`, the chain is older than `stale_after`
   (120 s for NSE public). Say so. Only use `--allow-stale` when the user explicitly wants
   after-hours / historical analysis, and label the result as stale.
3. Report: spot, forward, DTE, ATM strike + ATM IV, straddle and 1-sd expected move,
   PCR(OI), max pain, highest CE/PE OI strikes, then the strike table.

## Output
`data.summary` (spot, forward, forward_source, atm_strike, atm_iv, atm_straddle,
expected_move_1sd, pcr_oi, pcr_doi, max_pain, max_ce_oi_strike, max_pe_oi_strike,
lot_size) and `data.rows[]` (per strike: mids, IVs, delta, gamma, vega, theta, OI, dOI,
volume). Field meanings: `references/field-glossary.md`.

## Never
- Treat PCR or max pain as a directional signal or give buy/sell advice.
- Mix OI units: OI here is in contracts; multiply by lot size for units.
- Use the NSE public feed for live trading decisions - it is unofficial and delayed.
