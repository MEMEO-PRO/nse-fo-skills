# Retail algo / API trading rules relevant to this skill (summary, not legal advice)

SEBI's framework for safer participation of retail investors in algorithmic trading
(circular of 4 Feb 2025; exchange implementation standards; mandatory for all brokers
from **1 April 2026** after extensions):

- **Orders through broker APIs are treated as algo orders** and carry an exchange-issued
  Algo-ID. Strategies under the order-rate threshold use the broker's generic ID.
- **Threshold: 10 orders per second** per exchange (placements + modifications +
  cancellations in a rolling second). Above it the strategy must be registered with the
  exchange via the broker. This pack throttles at 8/s.
- **Static IP**: API orders are accepted only from the static IP registered with the
  broker for the API key (App ID); others are rejected.
- **Daily 2FA / session login** for API access; market orders may be converted by brokers
  to market-price-protection orders - prefer LIMIT orders.
- **Algo providers / vendors** must be empanelled through brokers; selling strategies or
  signals is regulated. This pack sells/ships tools only; orders are always user-confirmed.

Exchange order-level checks the skill pre-validates:
- Quantity in whole lots (lot size per series from the master).
- Quantity freeze limit per order (index-specific, revised periodically) - slice below it.
- Tick size (0.05 for index options) and dynamic price bands.

Sources: SEBI circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013 (4 Feb 2025) and
exchange circulars; broker summaries e.g.
https://support.fyers.in/portal/en/kb/articles/what-are-the-new-sebi-rules-for-retail-algo-trading-from-april-01-2026
Verify against your broker's current API terms before going live.
