---
name: gex-dealer-positioning
description: Compute net gamma exposure (GEX) by strike for NSE index options (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY), the zero-gamma flip level and the call/put gamma walls, with the dealer-positioning assumption stated explicitly. Use when the user asks about GEX, dealer gamma, gamma flip, gamma walls, pinning, or whether the index is likely to be sticky or volatile into expiry.
license: MIT
compatibility: Python 3.11+ with nsefno installed; a fresh chain from option-chain-snapshot (NSE public, Kite, or saved file) and the lot size from nse-instrument-master. Charts need matplotlib.
metadata:
  tier: free
  adapters: nse_public kite local_store
  version: 0.1.0
---

# GEX & dealer positioning

## When to use
Gamma exposure, flip level, walls, pin risk, or volatility regime for an index.

## Steps
1. `python scripts/gex.py NIFTY --expiry next --md --chart gex.png --compare-previous`
   It fetches a chain (option-chain-snapshot), takes lot size from the instrument master,
   and refuses a chain older than `stale_after` (`StaleDataError`) - stop and say so.
2. Read `net_gex_cr`, `regime`, `flip_level`, `spot_vs_flip`, `call_wall`, `put_wall`,
   `top_strikes[]`, `vs_previous`.
3. Report in this order:
   1. Spot vs flip: **above** -> hedging tends to dampen moves; **below** -> tends to
      amplify. If `flip_level` is null there is no zero crossing within ±6%.
   2. Call wall and put wall (largest call/put gamma above/below spot).
   3. Change vs the previous stored snapshot (needs earlier `--save` runs).
4. ALWAYS state the assumption from `data.assumption`. For a sensitivity check run again
   with `--convention dealer_short` and mention if the regime flips.

## Output format
A 5-line summary, then a table of the top 10 strikes by |net GEX|, then the chart path.
Units: INR crore of index delta to re-hedge per 1% move. Method and caveats:
`references/gex-method.md`.

## Never
- Give buy/sell recommendations, targets or stop levels.
- Hardcode lot sizes; use the multiplier from nse-instrument-master.
- Present GEX as fact about dealer books - it is a model of an assumed positioning.
