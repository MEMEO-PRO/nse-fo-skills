---
name: sebi-order-prep
description: Turn a trade plan for NSE/BSE index options or futures into exact broker order payloads with SEBI retail-algo and exchange guardrails - lot-size validation from the instrument master, freeze-quantity slicing, tick-size and price-band checks, max-lots cap, sub-10 orders/sec throttle, Algo-ID tag field, static-IP reminder - shown as a DRY RUN. Sends only after the user explicitly confirms, using a 60-second confirmation token bound to the exact payload. Use when the user wants to prepare, check or place an F&O order.
license: MIT
compatibility: Python 3.11+ with nsefno installed. Dry run needs only a public instrument master. Sending needs the user's broker credentials (kite, upstox, dhan, fyers, angel, groww, shoonya, breeze, fivepaisa, aliceblue, kotak_neo or xts) during market hours from the broker-whitelisted static IP.
metadata:
  tier: paid
  adapters: kite upstox dhan fyers angel groww shoonya breeze fivepaisa aliceblue kotak_neo xts
  version: 0.2.0
---

# SEBI-aware order prep

This skill prepares orders. It is NOT an automated strategy and must never send an order
the user has not explicitly confirmed in this conversation.

## Steps
1. Write the plan (one entry per leg; `instrument` in nse-instrument-master syntax):
   ```json
   [{"instrument":"NIFTY 23 Nov 26200 CE","side":"BUY","lots":2,"order_type":"LIMIT","price":82.05},
    {"instrument":"NIFTY 23 Nov 26400 CE","side":"SELL","lots":2,"order_type":"LIMIT","price":31.10}]
   ```
2. Dry run: `python scripts/order.py prep --plan plan.json --broker <broker> --index NIFTY --md`
   - The payload is built in that broker's exact API format from its own instrument master.
   - Upstox, 5paisa, Angel, Groww and Kotak masters carry the per-order quantity cap, so slicing
     is automatic. For others pass `--freeze-qty` (exchange figure, e.g. NIFTY 1801) or a warning
     is shown and orders are not sliced.
   - Shoonya and Breeze reject MARKET orders via API: the prep fails fast.
3. Show the user the full dry run: resolved symbols, lot sizes, quantities, slices, the
   JSON payload and EVERY warning. Ask: "Send these N orders? (yes/no)".
4. Only on an explicit "yes" for this exact payload, within 60 s:
   `python scripts/order.py send --sha <payload_sha256> --confirm <confirm_token>`
   If the token expired or the plan changed, go back to step 2.
5. Report each order's status; stop on the first error (no blind retries).

## Guardrails (enforced in code)
Dry-run default · token expires in 60 s and is bound to the payload hash · sending blocked
outside 09:15-15:30 IST trading sessions (no pre-open/AMO) · qty must be whole lots ·
slices strictly below freeze qty · tick-size and price-band check · `max_lots_per_leg`
cap (default 10, `~/.nsefno/config.yaml`) · throttle 8 orders/s (< SEBI 10/s) · payloads
logged (redacted) to `~/.nsefno/logs/orders.jsonl`. Rules summary: `references/sebi-algo-rules.md`.

## Never
- Send without an explicit user confirmation of the exact dry-run payload.
- Generate the confirmation yourself, reuse an old token, or loop sends.
- Suggest bypassing static-IP, Algo-ID, freeze or price-band rules.
- Recommend what to trade.
