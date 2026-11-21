# Index derivative contract specs (how to reason about them)

Values below are **rules**; quantities always come from the instrument master.

| Index | Exchange | Weekly? | Expiry day | Monthly expiry |
|---|---|---|---|---|
| NIFTY | NSE (NFO) | Yes | Tuesday | Last Tuesday |
| BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50 | NSE (NFO) | No (weeklies discontinued Nov 2024) | - | Last Tuesday |
| SENSEX | BSE (BFO) | Yes | Thursday | Last Thursday |
| BANKEX | BSE (BFO) | No | - | Last Thursday |

- Expiry-day swap took effect 1 Sep 2025 (NSE Thursday -> Tuesday; BSE Tuesday -> Thursday).
- If the expiry day is a trading holiday the contract expires on the **previous trading day**
  (e.g. 24 Nov 2026 Guru Nanak Jayanti -> NIFTY/BANKNIFTY expire Mon 23 Nov 2026;
  31 Mar 2026 Mahavir Jayanti -> 30 Mar 2026).
- Lot-size revisions are announced by exchange circular and apply **per series**: NIFTY
  75 -> 65, BANKNIFTY 35 -> 30, FINNIFTY 65 -> 60, MIDCPNIFTY 140 -> 120 took effect from
  the series after 30 Dec 2025. During a transition, near and far series carry different
  lots - always look up the lot for the specific expiry.
- Freeze quantity (max quantity per order) is published separately by the exchange and is
  not in the Kite dump; the Kotak Neo scrip master carries it (`lFreezeQty`).

## Data sources
- Kite public dump: `https://api.kite.trade/instruments/NFO` and `/BFO` (CSV, no auth,
  refreshed daily ~08:30 IST). Columns: instrument_token, exchange_token, tradingsymbol,
  name, last_price, expiry, strike, tick_size, lot_size, instrument_type, segment, exchange.
- Kotak Neo scrip master: per-segment CSV (`nse_fo`, `bse_fo`) from `client.scrip_master()`.
  `lExpiryDate` for nse_fo counts seconds from 1980-01-01 (add 315511200); strikes in paise.
