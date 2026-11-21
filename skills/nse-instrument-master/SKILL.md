---
name: nse-instrument-master
description: Resolve NSE/BSE index derivative contracts (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50, SENSEX, BANKEX) from the day's instrument master - exact trading symbol, token, lot size, tick size and listed expiries. Use whenever a lot size, contract symbol, strike availability or expiry date is needed, e.g. "lot size of NIFTY next expiry 26000 CE", "what's the SENSEX lot size", "is there a 23 Nov BANKNIFTY expiry". Never answer these from memory.
license: MIT
compatibility: Python 3.11+ with nsefno installed (pip install -e . from the repo). Network access to any broker public master (Kite, Upstox, Dhan, Fyers, Angel, Groww, Shoonya, ICICI, 5paisa, Alice Blue - no login) or a Kotak Neo CSV.
metadata:
  tier: free
  adapters: kite_public upstox dhan fyers angel groww shoonya breeze fivepaisa aliceblue kotak_neo file
  version: 0.2.0
---

# NSE instrument master

Lot sizes, tick sizes and expiry dates change (NIFTY 75 -> 65 from the Jan-2026 series;
SENSEX lots differ *between* series during a transition). This skill reads them from the
current exchange contract list every time. Treat any number you "remember" as wrong.

## When to use
- The user names a contract in trader shorthand and you need the exact instrument.
- Any calculation needs lot size, tick size or a listed expiry (costs, sizing, GEX, orders).
- The user asks which expiries / strikes are listed.

## Steps
1. Resolve a contract:
   `python scripts/instrument.py resolve "NIFTY 23 Nov 26000 CE" --md`
   Accepted forms: `NIFTY 26000 CE` (nearest expiry), `NIFTY 23 Nov 26000 CE`,
   `NIFTY 2026-12-01 26000 PE`, `BANKNIFTY monthly 59000 PE`, `NIFTY FUT`, or a raw
   trading symbol like `NIFTY26NOV26000CE`.
2. Lot sizes per listed expiry: `python scripts/instrument.py lots SENSEX --md`
3. Listed expiries: `python scripts/instrument.py expiries NIFTY --md`
4. If resolution fails, the error lists the nearest valid strikes/expiries - relay them; do
   not guess a substitute contract silently.

## Output
JSON envelope (`data` = instrument dict with `tradingsymbol`, `token`, `lot_size`,
`tick_size`, `expiry`, `strike`, `instrument_type`, `source`), or markdown with `--md`.
Quote the `source` and mention that lot size is per series when lots differ across expiries.

## Options
- `--master <broker>` reads that broker's own public master (no login): `kite_public` (default),
  `upstox`, `dhan`, `fyers`, `angel`, `groww`, `shoonya`, `breeze`, `fivepaisa`, `aliceblue`.
  Use the user's own broker so the `tradingsymbol`/`token` match what that broker expects.
  `--master kotak_neo --master-file nse_fo.csv` for a Kotak Neo CSV.
- Output also carries `extra.exchange_token` (same across brokers) and `order_qty_cap`
  (max quantity per order, where the master publishes a freeze/limit).
- `--today YYYY-MM-DD` to evaluate as of another date.

## Never
- Hardcode or recall lot sizes, freeze quantities or expiry dates.
- Assume a weekday for expiry: holidays move expiries to the previous trading day.

See `references/contract-specs.md` for how expiries and lots are set.
