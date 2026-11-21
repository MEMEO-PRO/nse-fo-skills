"""Angel One SmartAPI. Public OpenAPIScripMaster.json (no login) + REST (JWT + API key).

Paths and headers come from the official smartapi-python SDK route table. Quote/margin
RESPONSE field names could not be read from the (client-rendered) docs, so parsing is
tolerant and the raw response is always returned alongside the normalised fields."""

from __future__ import annotations

import datetime as dt
import json
import os

from ..errors import AdapterError
from ..instruments import Instrument
from ..resources import index_rule, normalise_underlying
from .base import Broker, OrderIntent, f, finalise_chain, first, i, options_for

ROOT = "https://apiconnect.angelone.in"
MASTER = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
R_QUOTE = "/rest/secure/angelbroking/market/v1/quote"
R_MARGIN = "/rest/secure/angelbroking/margin/v1/batch"
R_ORDER = "/rest/secure/angelbroking/order/v1/placeOrder"
DERIV = {"OPTIDX", "FUTIDX", "OPTSTK", "FUTSTK"}


class Angel(Broker):
    name = "angel"
    display = "Angel One SmartAPI"
    env = ("ANGEL_API_KEY", "ANGEL_JWT_TOKEN")
    VERIFICATION = {"master": "live", "quotes": "sdk (paths); response fields tolerant", "margin": "sdk (path)",
                    "orders": "sdk"}

    def __init__(self):
        self.index_tokens: dict[str, tuple[str, str]] = {}

    def master_sources(self):
        return [("ALL", MASTER)]

    def parse_master(self, blob, exchange):
        out = []
        for r in json.loads(blob):
            if r.get("instrumenttype") == "AMXIDX":
                self.index_tokens.setdefault(normalise_underlying(r["name"]), (r["exch_seg"], r["token"]))
                continue
            if r.get("instrumenttype") not in DERIV or r.get("exch_seg") not in ("NFO", "BFO"):
                continue
            sym = r["symbol"]
            itype = sym[-2:] if sym[-2:] in ("CE", "PE") else "FUT"
            out.append(Instrument(
                exchange=r["exch_seg"], underlying=normalise_underlying(r["name"]), instrument_type=itype,
                expiry=dt.datetime.strptime(r["expiry"], "%d%b%Y").date(),
                strike=max(f(r["strike"], 0.0), 0.0) / 100 if itype != "FUT" else 0.0,
                lot_size=i(r["lotsize"]), tick_size=round(f(r["tick_size"]) / 100, 4), tradingsymbol=sym,
                token=r["token"], freeze_qty=i(r.get("freeze_qty")) or None, source=self.name,
                extra=(("exchange_token", r["token"]),)))
        return out

    def _h(self):
        c = self.creds()
        return {"Authorization": f"Bearer {c['ANGEL_JWT_TOKEN']}", "X-PrivateKey": c["ANGEL_API_KEY"],
                "Content-Type": "application/json", "Accept": "application/json", "X-UserType": "USER",
                "X-SourceID": "WEB", "X-ClientLocalIP": os.environ.get("ANGEL_CLIENT_LOCAL_IP", "127.0.0.1"),
                "X-ClientPublicIP": os.environ.get("ANGEL_CLIENT_PUBLIC_IP", "127.0.0.1"),
                "X-MACAddress": os.environ.get("ANGEL_MAC_ADDRESS", "00:00:00:00:00:00")}

    @staticmethod
    def _ok(body):
        if not body.get("status"):
            raise AdapterError(f"Angel error {body.get('errorcode')}: {body.get('message')}")
        return body.get("data")

    def quotes(self, exchange_tokens: dict[str, list[str]]) -> list[dict]:
        out = []
        for ex, toks in exchange_tokens.items():
            for n in range(0, len(toks), 50):
                d = self._ok(self._request("POST", ROOT + R_QUOTE, headers=self._h(),
                                           json_body={"mode": "FULL", "exchangeTokens": {ex: toks[n:n + 50]}}))
                out.extend((d or {}).get("fetched", []))
        return out

    def option_chain(self, index, expiry, master):
        rule = index_rule(index)
        opts = options_for(master, rule["index"], expiry)
        if not self.index_tokens:
            self.load_master()
        if rule["index"] not in self.index_tokens:
            raise AdapterError(f"No Angel index token for {rule['index']}.")
        idx_ex, idx_tok = self.index_tokens[rule["index"]]
        ex = opts[0].exchange
        fetched = self.quotes({ex: [o.token for o in opts]}) + self.quotes({idx_ex: [idx_tok]})
        by_tok = {str(first(q, "symbolToken", "token")): q for q in fetched}
        spot = f(first(by_tok.get(str(idx_tok), {}), "ltp", "lastTradedPrice"))
        rows = {}
        for o in opts:
            q = by_tok.get(str(o.token))
            if not q:
                continue
            s = o.instrument_type.lower()
            depth = q.get("depth") or {}
            rows.setdefault(o.strike, {"strike": o.strike}).update({
                f"{s}_ltp": f(first(q, "ltp", "lastTradedPrice")),
                f"{s}_bid": f(((depth.get("buy") or [{}])[0]).get("price")) or None,
                f"{s}_ask": f(((depth.get("sell") or [{}])[0]).get("price")) or None,
                f"{s}_oi": f(first(q, "opnInterest", "openInterest", "oi")),
                f"{s}_volume": f(first(q, "tradeVolume", "volume"))})
        if spot is None:
            raise AdapterError("Angel quote for the index returned no LTP.")
        return finalise_chain(rule["index"], expiry, spot, rows, opts[0].lot_size, self.name)

    def basket_margin(self, legs, master=None):
        pos = [{"exchange": leg["exchange"], "qty": int(leg["qty"]), "price": float(leg.get("price") or 0),
                "productType": "INTRADAY" if leg.get("product") == "MIS" else "CARRYFORWARD", "token": str(leg["token"]),
                "tradeType": leg["side"].upper(), "orderType": "LIMIT" if leg.get("price") else "MARKET"}
               for leg in legs]
        d = self._ok(self._request("POST", f"{ROOT}/{R_MARGIN.lstrip('/')}", headers=self._h(),
                                   json_body={"positions": pos})) or {}
        comp = d.get("marginComponents") or {}
        return {"broker": self.name, "final_total": f(d.get("totalMarginRequired")),
                "span": f(comp.get("spanMargin")), "exposure": f(comp.get("exposureMargin")), "raw": d}

    def order_payload(self, intent: OrderIntent):
        return {"variety": "NORMAL", "tradingsymbol": intent.instrument.tradingsymbol,
                "symboltoken": str(intent.instrument.token), "transactiontype": intent.side,
                "exchange": intent.instrument.exchange, "ordertype": intent.order_type,
                "producttype": "INTRADAY" if intent.product == "MIS" else "CARRYFORWARD", "duration": "DAY",
                "price": str(intent.price if intent.order_type == "LIMIT" else 0), "quantity": str(intent.quantity),
                **({"ordertag": intent.tag[:20]} if intent.tag else {})}

    def place_order(self, payload):
        return self._ok(self._request("POST", ROOT + R_ORDER, headers=self._h(), json_body=payload))
