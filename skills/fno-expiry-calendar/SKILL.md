---
name: fno-expiry-calendar
description: Expiry calendar for NSE/BSE index options and futures - next N expiries per index, weekly vs monthly, holiday shifts (expiry moved to the previous trading day), calendar days and trading sessions to expiry, plus current market session state in IST. Use when the user asks "is it expiry tomorrow", "when is the next NIFTY/BANKNIFTY/SENSEX expiry", "how many sessions to expiry", "is the market open", or before any expiry-sensitive analysis.
license: MIT
compatibility: Python 3.11+ with nsefno installed. Works offline (rules + bundled official holiday list) and prefers the live instrument master when reachable.
metadata:
  tier: free
  adapters: kite_public rules
  version: 0.2.0
---

# F&O expiry calendar

## When to use
Any question about expiry dates, expiry day, days/sessions left, or whether the market
is open / a holiday today.

## Steps
1. `python scripts/expiry.py NIFTY -n 6 --md`
   - Source is the instrument master when reachable (authoritative), otherwise the rule set
     (NIFTY weekly Tuesday; BANKNIFTY/FINNIFTY/MIDCPNIFTY monthly last Tuesday; SENSEX weekly
     Thursday; holiday -> previous trading day).
   - Add `--no-master` for an offline, rules-only projection.
2. Market state now: `python scripts/session.py --md` (pre_open 09:00-09:15, open
   09:15-15:30 IST, closed, weekend, holiday).
3. Report: next expiry (date + weekday + weekly/monthly), sessions to expiry, and any
   holiday shift with its reason. If `is_expiry_today` is true, say so first.
4. Surface every entry in `warnings` - especially `holidays_verified: false`, which means
   the official holiday list for that year is not bundled yet.

## Output
`data.expiries[]` with `expiry`, `weekday`, `kind`, `days_to_expiry`,
`sessions_to_expiry` (trading sessions remaining including today if it is a trading day
and the expiry day itself), `shifted_from`, `shift_reason`, `source`, `holidays_verified`.

## Never
- Assume "expiry is every Thursday" (that changed on 1 Sep 2025 for NSE).
- Present a rules-projected date as confirmed when `source` is `rules` and the master disagrees.
