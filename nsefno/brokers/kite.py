"""Zerodha Kite Connect. Public instruments dump (no login) + Connect REST (login)."""

from __future__ import annotations

import csv
import datetime as dt
import io

from ..chain import OptionChain
from ..instruments import Instrument
from ..resources import index_rule, normalise_underlying
from .base import Broker, OrderIntent, finalise_chain, options_for

BASE = "https://api.kite.trade"
SPOT_KEYS = {"NIFTY": "NSE:NIFTY 50", "BANKNIFTY": "NSE:NIFTY BANK", "FINNIFTY": "NSE:NIFTY FIN SERVICE",
             "MIDCPNIFTY": "NSE:NIFTY MID SELECT", "NIFTYNXT50": "NSE:NIFTY NEXT 50", "SENSEX": "BSE:SENSEX",
             "BANKEX": "BSE:BANKEX"}


class Kite(Broker):
    name = "kite"
    display = "Zerodha Kite"
    env = ("KITE_API_KEY", "KITE_ACCESS_TOKEN")
    VERIFICATION = {"master": "live", "quotes": "sdk", "margin": "sdk", "orders": "sdk"}

    def master_sources(self):
        return [("NFO", f"{BASE}/instruments/NFO"), ("BFO", f"{BASE}/instruments/BFO")]

    def parse_master(self, blob, exchange):
        text = blob.decode("utf-8") if isinstance(blob, bytes) else blob
        out = []
        for r in csv.DictReader(io.StringIO(text)):
            itype = r.get("instrument_type", "")
            if itype not in ("CE", "PE", "FUT") or not r.get("expiry"):
                continue
            out.append(Instrument(
                exchange=exchange, underlying=normalise_underlying(r["name"].strip('"')), instrument_type=itype,
                expiry=dt.date.fromisoformat(r["expiry"]), strike=float(r["strike"] or 0),
                lot_size=int(float(r["lot_size"])), tick_size=float(r["tick_size"]),
                tradingsymbol=r["tradingsymbol"], token=r["instrument_token"], source="kite_public",
                extra=(("exchange_token", r.get("exchange_token")),)))
        return out

    def _headers(self):
        c = self.creds()
        return {"X-Kite-Version": "3", "Authorization": f"token {c['KITE_API_KEY']}:{c['KITE_ACCESS_TOKEN']}"}

    def _data(self, body):
        if body.get("status") != "success":
            from ..errors import AdapterError

            raise AdapterError(f"Kite error: {body.get('error_type')} {body.get('message')}")
        return body["data"]

    def quotes(self, keys: list[str]) -> dict:
        out = {}
        for n in range(0, len(keys), 500):
            params = [("i", k) for k in keys[n:n + 500]]
            out.update(self._data(self._request("GET", f"{BASE}/quote", headers=self._headers(), params=params)))
        return out

    def option_chain(self, index, expiry, master) -> OptionChain:
        rule = index_rule(index)
        opts = options_for(master, rule["index"], expiry)
        seg = opts[0].exchange
        spot_key = SPOT_KEYS[rule["index"]]
        q = self.quotes([f"{seg}:{o.tradingsymbol}" for o in opts] + [spot_key])
        rows: dict[float, dict] = {}
        for o in opts:
            d = q.get(f"{seg}:{o.tradingsymbol}")
            if not d:
                continue
            s = o.instrument_type.lower()
            depth = d.get("depth") or {}
            rows.setdefault(o.strike, {"strike": o.strike}).update({
                f"{s}_ltp": d.get("last_price"),
                f"{s}_bid": ((depth.get("buy") or [{}])[0].get("price")) or None,
                f"{s}_ask": ((depth.get("sell") or [{}])[0].get("price")) or None,
                f"{s}_oi": d.get("oi"), f"{s}_volume": d.get("volume")})
        return finalise_chain(rule["index"], expiry, q[spot_key]["last_price"], rows, opts[0].lot_size, self.name)

    def basket_margin(self, legs, master=None):
        orders = [{"exchange": leg["exchange"], "tradingsymbol": leg["tradingsymbol"],
                   "transaction_type": leg["side"].upper(), "variety": "regular",
                   "product": leg.get("product", "NRML"), "order_type": "LIMIT" if leg.get("price") else "MARKET",
                   "quantity": int(leg["qty"]), "price": float(leg.get("price") or 0), "trigger_price": 0}
                  for leg in legs]
        data = self._data(self._request("POST", f"{BASE}/margins/basket", headers=self._headers(), json_body=orders,
                                        params={"consider_positions": "true", "mode": "compact"}))
        ini, fin = data.get("initial", {}), data.get("final", {})
        return {"broker": self.name, "initial_total": ini.get("total"), "final_total": fin.get("total"),
                "span": fin.get("span"), "exposure": fin.get("exposure"), "option_premium": fin.get("option_premium"),
                "hedge_benefit": None if ini.get("total") is None or fin.get("total") is None
                else round(ini["total"] - fin["total"], 2), "raw": data}

    def order_payload(self, intent: OrderIntent) -> dict:
        p = {"exchange": intent.instrument.exchange, "tradingsymbol": intent.instrument.tradingsymbol,
             "transaction_type": intent.side, "quantity": intent.quantity, "order_type": intent.order_type,
             "product": intent.product, "validity": "DAY"}
        if intent.order_type == "LIMIT":
            p["price"] = intent.price
        if intent.tag:
            p["tag"] = intent.tag[:20]
        return p

    def place_order(self, payload):
        return self._data(self._request("POST", f"{BASE}/orders/regular", headers=self._headers(), data=payload))
