"""Fyers API v3. Public symbol master CSVs (no login) + REST with 'app_id:access_token'."""

from __future__ import annotations

import csv
import io
import re

from ..errors import AdapterError
from ..instruments import Instrument
from ..resources import index_rule, normalise_underlying
from .base import Broker, OrderIntent, f, finalise_chain, i, ist_date_from_epoch, options_for

API = "https://api-t1.fyers.in/api/v3"
DATA = "https://api-t1.fyers.in/data"
PUBLIC = "https://public.fyers.in/sym_details"
# Index symbols verified in Fyers' NSE_CM / BSE_CM symbol masters.
INDEX_SYMBOLS = {"NIFTY": "NSE:NIFTY50-INDEX", "BANKNIFTY": "NSE:NIFTYBANK-INDEX", "FINNIFTY": "NSE:FINNIFTY-INDEX",
                 "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX", "NIFTYNXT50": "NSE:NIFTYNXT50-INDEX",
                 "SENSEX": "BSE:SENSEX-INDEX", "BANKEX": "BSE:BANKEX-INDEX"}
# Column positions of the header-less CSV (Fyers symbol master format).
C_FYTOKEN, C_TYPE, C_LOT, C_TICK, C_EXPIRY, C_TICKER, C_SCRIP, C_UNDER, C_STRIKE, C_OPT = 0, 2, 3, 4, 8, 9, 12, 13, 15, 16
DERIV_TYPES = {"11", "13", "14", "15"}   # index fut, stock fut, index opt, stock opt


class Fyers(Broker):
    name = "fyers"
    display = "Fyers"
    env = ("FYERS_APP_ID", "FYERS_ACCESS_TOKEN")
    VERIFICATION = {"master": "live", "option_chain": "sdk+docs", "margin": "docs", "orders": "sdk+docs"}

    def master_sources(self):
        return [("NFO", f"{PUBLIC}/NSE_FO.csv"), ("BFO", f"{PUBLIC}/BSE_FO.csv")]

    def parse_master(self, blob, exchange):
        text = blob.decode("utf-8") if isinstance(blob, bytes) else blob
        out = []
        for r in csv.reader(io.StringIO(text)):
            if len(r) < 17 or r[C_TYPE] not in DERIV_TYPES:
                continue
            opt = r[C_OPT].strip()
            itype = opt if opt in ("CE", "PE") else "FUT"
            out.append(Instrument(
                exchange=exchange, underlying=normalise_underlying(r[C_UNDER]), instrument_type=itype,
                expiry=ist_date_from_epoch(float(r[C_EXPIRY])), strike=max(f(r[C_STRIKE], 0.0), 0.0),
                lot_size=i(r[C_LOT]), tick_size=f(r[C_TICK]), tradingsymbol=r[C_TICKER], token=r[C_FYTOKEN],
                source=self.name, extra=(("exchange_token", r[C_SCRIP]),)))
        return out

    def _h(self):
        c = self.creds()
        return {"Authorization": f"{c['FYERS_APP_ID']}:{c['FYERS_ACCESS_TOKEN']}"}

    @staticmethod
    def _ok(body):
        if body.get("s") != "ok":
            raise AdapterError(f"Fyers error {body.get('code')}: {body.get('message')}")
        return body

    def option_chain(self, index, expiry, master):
        rule = index_rule(index)
        opts = options_for(master, rule["index"], expiry)
        sym = INDEX_SYMBOLS[rule["index"]]
        first_call = self._ok(self._request("GET", f"{DATA}/options-chain-v3", headers=self._h(),
                                            params={"symbol": sym, "strikecount": 1}))
        want = expiry.strftime("%d-%m-%Y")
        ts = next((e["expiry"] for e in first_call["data"].get("expiryData", []) if e.get("date") == want), None)
        if ts is None:
            raise AdapterError(f"Fyers lists no {rule['index']} expiry {want}.")
        data = self._ok(self._request("GET", f"{DATA}/options-chain-v3", headers=self._h(),
                                      params={"symbol": sym, "strikecount": 50, "timestamp": ts}))["data"]
        rows, spot = {}, None
        for d in data.get("optionsChain", []):
            if f(d.get("strike_price"), -1) < 0 or not d.get("option_type"):
                spot = d.get("ltp")
                continue
            k, side = float(d["strike_price"]), d["option_type"].lower()
            rows.setdefault(k, {"strike": k}).update({
                f"{side}_ltp": d.get("ltp"), f"{side}_bid": d.get("bid") or None, f"{side}_ask": d.get("ask") or None,
                f"{side}_oi": d.get("oi"), f"{side}_doi": d.get("oich"), f"{side}_volume": d.get("volume")})
        if spot is None:
            raise AdapterError("Fyers option chain: underlying row missing.")
        return finalise_chain(rule["index"], expiry, spot, rows, opts[0].lot_size, self.name)

    def basket_margin(self, legs, master=None):
        data = [{"symbol": leg["tradingsymbol"], "qty": int(leg["qty"]), "side": 1 if leg["side"].upper() == "BUY" else -1,
                 "type": 1 if leg.get("price") else 2, "productType": "INTRADAY" if leg.get("product") == "MIS" else "MARGIN",
                 "limitPrice": float(leg.get("price") or 0), "stopPrice": 0, "stopLoss": 0, "takeProfit": 0}
                for leg in legs]
        d = self._ok(self._request("POST", f"{API}/multiorder/margin", headers=self._h(), json_body={"data": data}))
        d = d.get("data", {})
        return {"broker": self.name, "final_total": d.get("margin_new_order"), "margin_total": d.get("margin_total"),
                "available": d.get("margin_avail"), "hedge_benefit": None, "raw": d}

    def order_payload(self, intent: OrderIntent):
        tag = re.sub(r"[^A-Za-z0-9]", "", intent.tag or "")[:30]
        return {"symbol": intent.instrument.tradingsymbol, "qty": intent.quantity,
                "type": 1 if intent.order_type == "LIMIT" else 2, "side": 1 if intent.side == "BUY" else -1,
                "productType": "INTRADAY" if intent.product == "MIS" else "MARGIN",
                "limitPrice": intent.price if intent.order_type == "LIMIT" else 0, "stopPrice": 0, "validity": "DAY",
                "disclosedQty": 0, "offlineOrder": False, **({"orderTag": tag} if tag else {})}

    def place_order(self, payload):
        return self._ok(self._request("POST", f"{API}/orders/sync", headers=self._h(), json_body=payload))
