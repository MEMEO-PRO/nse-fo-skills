"""Shoonya (Finvasia) NorenOMS API. Public symbol zips (no login) + jData/jKey REST.

The SDK (NorenRestApiPy) uses host .../NorenWClientTP/, the current docs use .../NorenWClientAPI/.
Default follows the docs; override with SHOONYA_HOST. Docs: MKT orders are rejected (use LMT)."""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import os
import zipfile

from ..errors import AdapterError, ComplianceBlock
from ..instruments import Instrument
from ..resources import index_rule, normalise_underlying
from .base import Broker, OrderIntent, f, finalise_chain, i, options_for

PUBLIC = "https://api.shoonya.com"
DERIV = {"OPTIDX", "FUTIDX", "OPTSTK", "FUTSTK"}
# Exchange index tokens (same NSE/BSE tokens as Fyers' 'underlying scrip code' column).
INDEX_TOKENS = {"NIFTY": ("NSE", "26000"), "BANKNIFTY": ("NSE", "26009"), "FINNIFTY": ("NSE", "26037"),
                "MIDCPNIFTY": ("NSE", "26074"), "NIFTYNXT50": ("NSE", "26013"), "SENSEX": ("BSE", "1"),
                "BANKEX": ("BSE", "12")}


class Shoonya(Broker):
    name = "shoonya"
    display = "Shoonya (Finvasia)"
    env = ("SHOONYA_USER_ID", "SHOONYA_SESSION_TOKEN")
    VERIFICATION = {"master": "live", "option_chain": "docs+sdk", "margin": "sdk (SpanCalc)", "orders": "docs+sdk"}

    @property
    def host(self) -> str:
        return os.environ.get("SHOONYA_HOST", "https://api.shoonya.com/NorenWClientAPI/").rstrip("/") + "/"

    def master_sources(self):
        return [("NFO", f"{PUBLIC}/NFO_symbols.txt.zip"), ("BFO", f"{PUBLIC}/BFO_symbols.txt.zip")]

    def parse_master(self, blob, exchange):
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            text = z.read(z.namelist()[0]).decode("utf-8")
        out = []
        for r in csv.DictReader(io.StringIO(text)):
            if r.get("Instrument") not in DERIV:
                continue
            opt = r["OptionType"]
            itype = opt if opt in ("CE", "PE") else "FUT"
            out.append(Instrument(
                exchange=r["Exchange"], underlying=normalise_underlying(r["Symbol"]), instrument_type=itype,
                expiry=dt.datetime.strptime(r["Expiry"], "%d-%b-%Y").date(),
                strike=f(r["StrikePrice"], 0.0) if itype != "FUT" else 0.0, lot_size=i(r["LotSize"]),
                tick_size=f(r["TickSize"]), tradingsymbol=r["TradingSymbol"], token=r["Token"], source=self.name,
                extra=(("exchange_token", r["Token"]), ("symbol", r["Symbol"]), ("instrument", r["Instrument"]))))
        return out

    def _call(self, route: str, values: dict) -> dict | list:
        c = self.creds()
        values = {"uid": c["SHOONYA_USER_ID"], **values}
        payload = "jData=" + json.dumps(values) + f"&jKey={c['SHOONYA_SESSION_TOKEN']}"
        body = self._request("POST", self.host + route, data=payload,
                             headers={"Content-Type": "application/x-www-form-urlencoded"})
        if isinstance(body, dict) and body.get("stat") == "Not_Ok":
            raise AdapterError(f"Shoonya {route}: {body.get('emsg')}")
        return body

    def option_chain(self, index, expiry, master):
        rule = index_rule(index)
        opts = options_for(master, rule["index"], expiry)
        iex, itok = INDEX_TOKENS[rule["index"]]
        spot = f(self._call("GetQuotes", {"exch": iex, "token": itok}).get("lp"))
        if spot is None:
            raise AdapterError("Shoonya GetQuotes returned no index LTP.")
        atm = min(opts, key=lambda o: abs(o.strike - spot))
        res = self._call("GetOptionChain", {"exch": atm.exchange, "tsym": atm.tradingsymbol,
                                            "strprc": str(atm.strike), "cnt": "40"})
        rows = {}
        for d in res.get("values", []):
            k, s = float(d["strprc"]), d["optt"].lower()
            rows.setdefault(k, {"strike": k}).update({f"{s}_ltp": f(d.get("lp")), f"{s}_oi": f(d.get("oi"))})
        return finalise_chain(rule["index"], expiry, spot, rows, opts[0].lot_size, self.name)

    def basket_margin(self, legs, master=None):
        pos = []
        for leg in legs:
            inst = leg["instrument_obj"]
            buy = int(leg["qty"]) if leg["side"].upper() == "BUY" else 0
            sell = int(leg["qty"]) if leg["side"].upper() == "SELL" else 0
            pos.append({"prd": "I" if leg.get("product") == "MIS" else "M", "exch": inst.exchange,
                        "instname": inst.get("instrument"), "symname": inst.get("symbol"),
                        "exd": inst.expiry.strftime("%d-%b-%Y").upper(),
                        **({"optt": inst.instrument_type, "strprc": f"{inst.strike:.2f}"}
                           if inst.instrument_type != "FUT" else {}),
                        "buyqty": str(buy), "sellqty": str(sell), "netqty": str(buy - sell)})
        d = self._call("SpanCalc", {"actid": os.environ.get("SHOONYA_ACCOUNT_ID") or self.creds()["SHOONYA_USER_ID"],
                                    "pos": pos})
        span, expo = f(d.get("span")), f(d.get("expo"))
        return {"broker": self.name, "span": span, "exposure": expo,
                "final_total": None if span is None or expo is None else round(span + expo, 2), "raw": d}

    def order_payload(self, intent: OrderIntent):
        if intent.order_type != "LIMIT":
            raise ComplianceBlock("Shoonya rejects MKT orders via API (docs) - use LIMIT.")
        return {"actid": "<SHOONYA_ACCOUNT_ID>", "exch": intent.instrument.exchange,
                "tsym": intent.instrument.tradingsymbol, "qty": str(intent.quantity), "prc": str(intent.price),
                "prd": "I" if intent.product == "MIS" else "M", "trantype": "B" if intent.side == "BUY" else "S",
                "prctyp": "LMT", "ret": "DAY", "ordersource": "API", "remarks": (intent.tag or "")[:40]}

    def place_order(self, payload):
        actid = os.environ.get("SHOONYA_ACCOUNT_ID") or self.creds()["SHOONYA_USER_ID"]
        return self._call("PlaceOrder", {**payload, "actid": actid})
