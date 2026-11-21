---
name: broker-margin-check
description: Required margin (SPAN + exposure) and hedge benefit for an F&O basket via the user's own broker session - Zerodha Kite Connect basket margin API or Kotak Neo margin API. Use when the user asks how much margin a spread, straddle, iron condor or futures position needs, what the hedge benefit is, or before sizing a position by margin.
license: MIT
compatibility: Python 3.11+ with nsefno installed. Requires a logged-in broker session via environment variables - Kite (KITE_API_KEY, KITE_ACCESS_TOKEN) or Kotak Neo (NEO_CONSUMER_KEY, NEO_MOBILE, NEO_UCC, NEO_MPIN, NEO_TOTP and `pip install neo_api_client`).
metadata:
  tier: paid
  adapters: kite kotak_neo
  version: 0.1.0
---

# Broker margin check

## When to use
Margin requirement or hedge benefit for a basket; input for fno-position-sizer.

## Steps
1. Resolve each leg with nse-instrument-master (tradingsymbol, exchange, lot size; Neo also needs `token`).
2. Write the basket (qty = lots × lot size):
   ```json
   [{"tradingsymbol":"NIFTY26NOV26200CE","exchange":"NFO","side":"BUY","qty":65,"price":82},
    {"tradingsymbol":"NIFTY26NOV26400CE","exchange":"NFO","side":"SELL","qty":65,"price":31}]
   ```
3. `python scripts/margin.py --broker kite --legs basket.json --md`
4. Report final required margin, SPAN, exposure, option premium and hedge benefit
   (`initial_total - final_total`). For Kotak Neo the tool sums per-order margins and says
   that hedge benefit is not reflected.

## Credentials
Read only from environment variables / OS keychain. If missing, the tool raises
`ConfigError` - tell the user which variable to set; never ask them to paste secrets
into the chat or a file in the repo.

## Never
- Store, print or log API keys / access tokens.
- Treat the margin figure as permanent: SPAN files update intraday.
