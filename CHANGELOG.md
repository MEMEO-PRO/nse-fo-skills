# Changelog

## 0.2.0 - 2026-11-21
- **12 broker adapters** behind one interface (`nsefno/brokers/`): Zerodha Kite, Upstox, Dhan, Fyers,
  Angel One, Groww, Shoonya (Finvasia), ICICI Breeze, 5paisa, Alice Blue, Kotak Neo, Symphony XTS
  (IIFL, Jainam, ...). Data vendor: Global Datafeeds.
- Public instrument masters for 10 brokers, verified live; native option chains (Upstox, Dhan, Fyers,
  Groww), basket margin for 9 brokers, broker-specific order payloads for all 12.
- `nsefno brokers` capability matrix; `--broker/--source/--master <broker>` across skills.
- Automatic OI-unit detection (contracts vs units); both freeze-quantity conventions handled.
- Universal exchange token on every instrument.
- 37 new tests (152 total), network blocked during tests.

## 0.1.0 - 2026-11-21
- 10 skills: instrument master, expiry calendar, option-chain snapshot, IV skew, GEX,
  cost calculator, position sizer, broker margin check, SEBI-aware order prep, trade journal.
- 4 workflows: premarket-fno-check, trade-plan-to-order, expiry-day-risk, weekly-review.
- `nsefno` package: Black-76 Greeks/IV, GEX with explicit dealer conventions, skew metrics,
  dated Indian charges (post-1-Apr-2026 STT), 2026 NSE/BSE holiday calendar, adapters for
  Kite (public instruments dump + Connect), NSE public chain, NSE bhavcopy, Kotak Neo.
