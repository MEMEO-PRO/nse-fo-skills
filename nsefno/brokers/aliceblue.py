"""Alice Blue ANT Open API. Public contract master (no login) + REST on a3.aliceblueonline.com.

The docs give endpoints and body fields but not the exact Authorization header format for
the userSession token; it defaults to 'Bearer <userSession>' and can be overridden with
ALICEBLUE_AUTH_TEMPLATE (e.g. 'Bearer {user_id} {session}')."""

from __future__ import annotations

import datetime as dt
import json
import os

from ..errors import AdapterError
from ..instruments import Instrument
from ..resources import index_rule, normalise_underlying
from .base import Broker, OrderIntent, f, finalise_chain, i, options_for

BASE = "https://a3.aliceblueonline.com/open-api/od"
MASTER = "https://v2api.aliceblueonline.com/restpy/contract_master?exch={ex}"


class AliceBlue(Broker):
    name = "aliceblue"
    display = "Alice Blue"
    env = ("ALICEBLUE_USER_ID", "ALICEBLUE_SESSION")
    VERIFICATION = {"master": "live", "quotes": "docs (ltp+oi only, no depth)", "margin": "docs",
                    "orders": "docs", "auth_header": "unverified (configurable)"}

    def master_sources(self):
        return [("NFO", MASTER.format(ex="NFO")), ("BFO", MASTER.format(ex="BFO"))]

    def parse_master(self, blob, exchange):
        data = json.loads(blob)
        out = []
        for r in data.get(exchange, []):
            opt = r.get("option_type")
            if not r.get("expiry_date"):
                continue
            itype = opt if opt in ("CE", "PE") else ("FUT" if "F" in str(r.get("instrument_type", "")) else None)
            if itype is None:
                continue
            out.append(Instrument(
                exchange=exchange, underlying=normalise_underlying(r["symbol"]), instrument_type=itype,
                expiry=dt.datetime.fromtimestamp(r["expiry_date"] / 1000, tz=dt.UTC).date(),
                strike=max(f(r.get("strike_price"), 0.0), 0.0) if itype != "FUT" else 0.0,
                lot_size=i(r["lot_size"]), tick_size=f(r["tick_size"]), tradingsymbol=r["trading_symbol"],
                token=r["token"], source=self.name, extra=(("exchange_token", r["token"]),)))
        return out

    def _h(self):
        c = self.creds()
        tpl = os.environ.get("ALICEBLUE_AUTH_TEMPLATE", "Bearer {session}")
        return {"Authorization": tpl.format(user_id=c["ALICEBLUE_USER_ID"], session=c["ALICEBLUE_SESSION"]),
                "Content-Type": "application/json"}

    def option_chain(self, index, expiry, master):
        rule = index_rule(index)
        opts = options_for(master, rule["index"], expiry)
        ex = opts[0].exchange
        res = []
        for n in range(0, len(opts), 100):
            body = [{"exchange": ex, "token": str(o.token)} for o in opts[n:n + 100]]
            r = self._request("POST", f"{BASE}/ChartAPIService/chart/get/multi/ohlc", headers=self._h(), json_body=body)
            res += r.get("result") or []
        by = {str(x.get("tk")): x for x in res}
        rows = {}
        for o in opts:
            q = by.get(str(o.token))
            if q:
                s = o.instrument_type.lower()
                rows.setdefault(o.strike, {"strike": o.strike}).update(
                    {f"{s}_ltp": f(q.get("ltp")), f"{s}_oi": f(q.get("oi")), f"{s}_volume": f(q.get("volume"))})
        if not rows:
            raise AdapterError("Alice Blue returned no quotes for this chain.")
        # The documented quote endpoint has no index quote: approximate spot by put-call parity
        # (strike where |C - P| is smallest, adjusted by C - P). Flagged in meta.
        k0 = min(rows, key=lambda k: abs((rows[k].get("ce_ltp") or 1e9) - (rows[k].get("pe_ltp") or 0)))
        approx = k0 + (rows[k0].get("ce_ltp") or 0) - (rows[k0].get("pe_ltp") or 0)
        ch = finalise_chain(rule["index"], expiry, approx, rows, opts[0].lot_size, self.name)
        ch.meta["spot_note"] = "spot approximated from put-call parity (no index quote on this endpoint)"
        return ch

    def basket_margin(self, legs, master=None):
        body = [{"exchange": leg["exchange"], "tradingSymbol": leg["tradingsymbol"], "price": str(leg.get("price") or 0),
                 "quantity": str(int(leg["qty"])), "product": "INTRADAY" if leg.get("product") == "MIS" else "LONGTERM",
                 "priceType": "L" if leg.get("price") else "MKT", "triggerPrice": "0",
                 "transType": "B" if leg["side"].upper() == "BUY" else "S"} for leg in legs]
        r = self._request("POST", f"{BASE}/v1/orders/basket/margin", headers=self._h(), json_body=body)
        return {"broker": self.name, "raw": r}

    def order_payload(self, intent: OrderIntent):
        return {"instrumentId": str(intent.instrument.token), "exchange": intent.instrument.exchange,
                "transactionType": intent.side, "quantity": intent.quantity,
                "product": "INTRADAY" if intent.product == "MIS" else "LONGTERM", "orderComplexity": "REGULAR",
                "orderType": intent.order_type, "validity": "DAY",
                "price": intent.price if intent.order_type == "LIMIT" else 0,
                **({"orderTag": intent.tag[:20]} if intent.tag else {})}

    def place_order(self, payload):
        return self._request("POST", f"{BASE}/v1/orders/placeorder", headers=self._h(), json_body=payload)
