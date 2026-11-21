---
name: broker-margin-check
description: Required margin (SPAN + exposure, and hedge benefit where the broker reports it) for an Indian F&O basket via the user's own broker session - Zerodha Kite, Upstox, Dhan, Fyers, Angel One, Groww, Shoonya (Finvasia), ICICI Breeze, Alice Blue or Kotak Neo. Use when the user asks how much margin a spread, straddle, iron condor or futures position needs, what the hedge benefit is, or before sizing a position by margin.
license: MIT
compatibility: Python 3.11+ with nsefno installed. Requires the user's broker credentials as environment variables (see docs/brokers.md); `nsefno brokers --md` lists which variables each broker needs.
metadata:
  tier: paid
  adapters: kite upstox dhan fyers angel groww shoonya breeze aliceblue kotak_neo
  version: 0.2.0
---

# Broker margin check

## When to use
Margin requirement or hedge benefit for a basket; input for fno-position-sizer.

## Steps
1. Ask which broker the user trades with if not known (`nsefno brokers --md` lists all 12).
2. Write the basket in trader syntax - legs are resolved against that broker's own master,
   so symbols/tokens and lot sizes are right automatically:
   ```json
   [{"instrument":"NIFTY 23 Nov 26200 CE","side":"BUY","lots":1,"price":82},
    {"instrument":"NIFTY 23 Nov 26400 CE","side":"SELL","lots":1,"price":31}]
   ```
3. `python scripts/margin.py --broker upstox --legs basket.json --md`
4. Report `final_total` (required margin), `span`, `exposure`, `hedge_benefit` when present,
   and the `verification` level. Broker differences:
   - Kite, Upstox, Dhan report basket margin with hedge benefit.
   - Shoonya returns SPAN + exposure from SpanCalc; Fyers returns the new-order margin.
   - Kotak Neo sums per-order margins (no hedge benefit) - say so.
   - Angel / Breeze / Alice Blue: fields parsed tolerantly; quote `raw` if a total is missing.

## Credentials
Read only from environment variables / OS keychain. If missing, the tool raises
`ConfigError` naming the variable - tell the user which one to set; never ask them to paste
secrets into the chat or a file.

## Never
- Store, print or log API keys / access tokens.
- Treat the margin figure as permanent: SPAN files update intraday.
