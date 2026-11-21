# Field glossary

| Field | Meaning |
|---|---|
| `spot` | Index value from the feed at `fetched_at` |
| `forward` | Synthetic forward: median of K + (C - P)·e^{rt} over the 5 strikes nearest spot (bid/ask mids). Falls back to futures, then spot·e^{rt} |
| `t_years` / `days_to_expiry` | ACT/365 time from snapshot to 15:30 IST on expiry day |
| `*_mid` | (bid+ask)/2 when the spread is sane (≤ 25% of mid or ≤ ₹2), else LTP |
| `*_iv` | Implied vol (%) from Black-76 on the forward, solved by Brent's method on the mid; exchange IV only when our solve fails |
| `*_delta/gamma` | Black-76 Greeks w.r.t. the forward. Gamma per 1 index point |
| `*_vega` | Price change per 1 vol point |
| `*_theta` | Price change per calendar day |
| `*_oi`, `*_doi` | Open interest and change in OI, **in contracts** |
| `atm_straddle` | ATM call mid + ATM put mid |
| `expected_move_1sd` | F · ATM IV · √t - a 1-standard-deviation range under the lognormal model, not a forecast |
| `pcr_oi` | Total put OI / total call OI for this expiry |
| `max_pain` | Settlement level minimising total intrinsic value paid to option holders |
| `rate` | Discount rate (default 5.5%); its effect on weekly prices is negligible |

Why Black-76 and not Black-Scholes on spot: Indian index options are European and
cash-settled against the index; pricing on the forward removes the dividend-yield guess.
