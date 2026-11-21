# Brokers and data providers

`nsefno brokers --md` prints this matrix from code. Every adapter implements the same interface
(`nsefno/brokers/base.py`): public instrument master, option chain, basket margin, order payload, place order.

## Coverage

| Provider | `--broker` / `--source` / `--master` | Public master (no login) | Option chain | Margin | Orders | Credentials (env vars) |
|---|---|---|---|---|---|---|
| Zerodha Kite Connect | `kite` (`kite_public` for the master) | yes | yes (quotes) | yes, with hedge benefit | yes | `KITE_API_KEY`, `KITE_ACCESS_TOKEN` |
| Upstox | `upstox` | yes (carries max order qty) | yes (native chain + IV) | yes, with hedge benefit | yes (v3) | `UPSTOX_ACCESS_TOKEN` |
| Dhan | `dhan` | yes | yes (native chain + IV) | yes, with hedge benefit | yes | `DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN` |
| Fyers | `fyers` | yes | yes (native chain) | yes | yes | `FYERS_APP_ID`, `FYERS_ACCESS_TOKEN` |
| Angel One SmartAPI | `angel` | yes (carries freeze qty) | yes (quotes) | yes | yes | `ANGEL_API_KEY`, `ANGEL_JWT_TOKEN` (+ optional `ANGEL_CLIENT_LOCAL_IP`, `ANGEL_CLIENT_PUBLIC_IP`, `ANGEL_MAC_ADDRESS`) |
| Groww | `groww` | yes (carries freeze qty) | yes (native chain + IV) | yes | yes | `GROWW_ACCESS_TOKEN` |
| Shoonya (Finvasia) | `shoonya` | yes | yes (LTP + OI) | yes (SpanCalc) | yes (LIMIT only) | `SHOONYA_USER_ID`, `SHOONYA_SESSION_TOKEN` (+ `SHOONYA_ACCOUNT_ID`, `SHOONYA_HOST`) |
| ICICI Direct Breeze | `breeze` | yes | yes | yes | yes (LIMIT only) | `BREEZE_APP_KEY`, `BREEZE_SECRET_KEY`, `BREEZE_SESSION_TOKEN` |
| 5paisa | `fivepaisa` | yes (carries max order qty) | yes (LTP + OI) | - | yes | `FIVEPAISA_APP_KEY`, `FIVEPAISA_ACCESS_TOKEN`, `FIVEPAISA_CLIENT_CODE` |
| Alice Blue | `aliceblue` | yes | yes (LTP + OI) | yes | yes | `ALICEBLUE_USER_ID`, `ALICEBLUE_SESSION` (+ `ALICEBLUE_AUTH_TEMPLATE`) |
| Kotak Neo | `kotak_neo` | CSV via SDK | - | yes (SDK) | yes (SDK) | `NEO_CONSUMER_KEY`, `NEO_MOBILE`, `NEO_UCC`, `NEO_MPIN`, `NEO_TOTP` |
| Symphony XTS (IIFL, Jainam, ...) | `xts` | uses any public master | - | - | yes | `XTS_ROOT`, `XTS_INTERACTIVE_TOKEN` (+ `XTS_CLIENT_ID`) |
| NSE public website | `nse_public` | - | yes (best effort, no login) | - | - | none |
| NSE archives (bhavcopy) | used by `ivhistory` | - | end-of-day | - | - | none |
| Global Datafeeds | `gdfl` | - | yes | - | - | `GDFL_ENDPOINT`, `GDFL_ACCESS_KEY` |

## How each part was verified (Nov 2026)

| Level | Meaning |
|---|---|
| **live** | Downloaded from the real public endpoint and parsed by this code. Covers all 10 public masters: Kite, Upstox, Dhan, Fyers, Angel, Groww, Shoonya, ICICI, 5paisa and Alice Blue. All 10 agree on NIFTY lot 65, the holiday-shifted 23 Nov 2026 expiry, BANKNIFTY 30, SENSEX 20→25 across series, and exchange token 64497 for NIFTY 23-Nov-26 26000 CE |
| **sdk** | Paths, headers and body fields come from the broker's official Python SDK source: smartapi-python 1.5.5, fyers-apiv3 3.3.0, growwapi 1.5.0, NorenRestApiPy 0.0.22, breeze-connect 1.0.69, py5paisa 0.7.21, kiteconnect 5.2.2 and xts-pythonclient |
| **docs** | Endpoint and field names come from the broker's official API documentation |

Authenticated endpoints (chain, margin, orders) are tested against mocked responses shaped exactly as the docs/SDKs describe. They have **not** been called with real credentials. Before relying on one, run it once yourself with your own login (a dry-run `order prep` sends nothing).

### Known documentation gaps (handled defensively)
- **Angel One:** the docs are rendered in the browser and could not be read. Quote and margin response fields are parsed tolerantly, and the raw response is always returned.
- **Shoonya:** the SDK uses host `NorenWClientTP`, while the current docs use `NorenWClientAPI`. The default follows the docs; set `SHOONYA_HOST` to override. Per the docs, the API rejects MKT orders.
- **Alice Blue:** the docs don't give the format of the session `Authorization` header. It defaults to `Bearer <session>` and can be changed with `ALICEBLUE_AUTH_TEMPLATE`. The quote endpoint has LTP and OI but no depth and no index quote, so spot is approximated by put-call parity; this is flagged in `meta.spot_note`.
- **Dhan multi-leg margin:** the field table and the example in the docs disagree (`scripts` vs `scripList`). The adapter follows the table.
- **5paisa:** the response fields for the option chain aren't documented, so parsing is tolerant. A basket-margin endpoint is not wired up.
- **Breeze:** market orders are not allowed through the API, and the OptionChain response fields are parsed tolerantly.
- **Not included:** TrueData (its docs and SDK repository were unreachable) and the BSE public API (it returns 403 to API clients). Contributions are welcome.

## Open-interest units

Brokers report OI either in **contracts** or in **units** (shares). `finalise_chain` detects which: exchange OI in units is always a multiple of the lot size, while OI in contracts almost never is across a whole chain. Every chain is converted to contracts and the original unit is recorded in `meta.oi_unit_reported`.

## Order-quantity caps

Two conventions are in use, and both are handled (`Instrument.order_qty_cap`):
- **Exchange freeze figure.** Orders must be strictly below it, e.g. NIFTY `1801`. Angel and Groww publish this figure.
- **Max order quantity.** This cap is inclusive and is already a whole number of lots, e.g. NIFTY `1755` = 27 × 65. Upstox and 5paisa publish this figure.

Either way, NIFTY slices at 27 lots per order.

## Universal exchange tokens

NSE/BSE contract tokens are the same across brokers, so every instrument stores `extra.exchange_token`. Symphony XTS orders use this token directly, which means any public master can resolve contracts for an XTS broker.
