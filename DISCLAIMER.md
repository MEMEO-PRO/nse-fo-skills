# Disclaimer

**nse-fo-skills is an analytics and tooling project. It is not investment advice.**

- The authors and contributors are **not registered with SEBI** as Investment Advisers
  (IA) or Research Analysts (RA). Nothing produced by these skills - including GEX levels,
  skew readings, PCR, max pain, position sizes or order payloads - is a recommendation to
  buy, sell or hold any security or derivative.
- The skills describe market positioning, costs and arithmetic. They deliberately never
  output buy/sell calls, targets or stop levels.
- **Not designed for fully automated trading or signal outsourcing.** Order preparation
  is a dry run by default; any order is sent only by the user, from their own broker
  account, after explicit confirmation. You are responsible for complying with SEBI's
  retail algorithmic trading framework, exchange rules and your broker's API terms
  (static IP, Algo-ID, order-rate limits, 2FA).
- Data from the NSE public website is unofficial, delayed, rate-limited and may break or
  be wrong. Do not use it for live trading decisions. Each user fetches data with their
  own session; this repository redistributes no exchange market data (test fixtures are
  synthetic, except a small sample of public contract metadata).
- Tax and charge rates (STT, exchange, SEBI, stamp, GST, brokerage) are bundled with
  effective dates and sources, but can change at any time. Verify against your contract note.
- Derivatives trading involves substantial risk. SEBI studies have found that a large
  majority of individual F&O traders incur net losses.
- The software is provided "AS IS", without warranty of any kind (see LICENSE).
