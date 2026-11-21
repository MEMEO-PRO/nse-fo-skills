# Indian F&O charges (as bundled; see nsefno/data/charges.yaml for sources)

| Charge | Options | Futures | Side | Effective |
|---|---|---|---|---|
| STT | 0.15% of premium | 0.05% of value | Sell | 1 Apr 2026 (Budget 2026; was 0.10% / 0.02%) |
| STT on exercise | 0.15% of intrinsic value | - | Buyer of exercised ITM option | 1 Apr 2026 (was 0.125%) |
| NSE transaction | 0.03553% of premium | 0.00183% | Both | 1 Mar 2026 (IPFT folded in; was 0.03503% / 0.00173%) |
| BSE transaction (SENSEX/BANKEX) | 0.0325% of premium | 0 | Both | Oct 2024 |
| SEBI turnover fee | ₹10 / crore | ₹10 / crore | Both | |
| Stamp duty | 0.003% | 0.002% | Buy | 1 Jul 2020 |
| GST | 18% on brokerage + transaction + SEBI fee | | | |
| Brokerage (Zerodha) | ₹20 / executed order | min(0.03%, ₹20) | Both | |
| Brokerage (Kotak Neo Trade Free) | ₹10 / executed order | ₹10 / executed order | Both | |

Formulas per leg (turnover = price × quantity):
- stt = turnover × rate (sell legs only)
- txn = turnover × exchange rate
- sebi = turnover × 10 / 1e7
- stamp = turnover × rate (buy legs only)
- gst = 18% × (brokerage + txn + sebi)
- breakeven_points = total round-trip cost / position units (max leg quantity)

`charges.yaml` has a `reviewed_on` date; CI fails when it is older than 90 days so the
table is re-checked after every budget / exchange circular.
