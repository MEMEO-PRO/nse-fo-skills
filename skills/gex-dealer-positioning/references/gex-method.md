# GEX method

**Per strike** (INR per 1% move):

    GEX_k = Γ_k × OI_k × lot_size × S² × 0.01

- Γ_k: Black-76 gamma at the strike's own implied vol (option-chain-snapshot).
- OI_k: open interest in contracts; × lot size = units.
- S² × 0.01 converts gamma (Δ per point) into rupee delta per 1% move.
- Reported in INR crore (÷ 1e7).

**Sign convention (an assumption, always printed):**

| Convention | Calls | Puts | Story |
|---|---|---|---|
| `classic` (default) | + | − | Customers sell calls / buy puts; dealers long calls, short puts (SqueezeMetrics / SpotGamma convention) |
| `dealer_short` | − | − | Dealers net short every customer option |

Indian index options differ from US single-stock flow: a large share of option writing is
done by prop desks and HNIs rather than market makers, and retail are heavy option
buyers of both calls and puts. Neither convention is "true"; use both as a range.

**Flip level**: net GEX is re-computed on a grid of spot levels (±6%, IV held fixed per
strike, forward scaled with spot); the zero crossing closest to spot is the flip.

**Walls**: call wall = strike ≥ spot with the largest |call GEX|; put wall = strike ≤ spot
with the largest |put GEX|.

**Caveats**
- OI is end-of-previous-update; intraday OI on NSE updates every few minutes.
- Near expiry, ATM gamma explodes (∝ 1/√t); GEX is dominated by a few strikes.
- Gamma here is w.r.t. the forward; for weeklies forward ≈ spot so the difference is tiny.
