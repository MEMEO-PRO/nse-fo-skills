---
name: iv-skew-analyzer
description: Volatility surface read for NSE index options - OTM IV smile per expiry, 25-delta and 10-delta risk reversal and butterfly, ATM IV term structure (contango/backwardation) and IV percentile/rank versus daily history built from NSE bhavcopy. Use when the user asks about skew, smile, risk reversal, butterfly, term structure, whether IV is high or low, IV percentile/rank, or how put vs call wings are priced.
license: MIT
compatibility: Python 3.11+ with nsefno installed. Uses option-chain-snapshot inputs (NSE public, Kite, or saved files). IV history uses the official NSE bhavcopy archive (no login). Charts need matplotlib.
metadata:
  tier: free
  adapters: nse_public kite nse_archives local_store
  version: 0.1.0
---

# IV skew analyzer

## When to use
Skew, smile, RR/BF, term structure, "is IV cheap/expensive", IV percentile or rank.

## Steps
1. Skew + term structure across expiries:
   `python scripts/skew.py NIFTY --expiries next,far,monthly --md --chart skew.png`
   (or `--file a.json --file b.json` for saved chains).
2. IV percentile needs >= 20 daily points. If `iv_percentile.note` says so, backfill once:
   `python scripts/backfill_history.py NIFTY --days 260` (one bhavcopy per trading day,
   cached; takes a few minutes the first time).
3. Report per expiry: ATM IV, 25d RR (negative = puts richer), 25d BF (wing premium over
   ATM), then the term-structure shape and IV percentile/rank with `n_obs`.

## Output
`data.per_expiry[]` (atm_iv, call_25d_iv, put_25d_iv, rr_25d, bf_25d, rr_10d, bf_10d,
skew_read), `data.term_structure` (points, shape), `data.iv_percentile`, optional
`data.smiles` (`--smile`) and `data.chart`. Method: `references/skew-method.md`.

## Never
- Call a vol level "cheap" or "expensive" as a trade instruction - describe percentile/rank only.
- Compare IV percentile computed on fewer than 20 observations.
