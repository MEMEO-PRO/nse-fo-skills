"""Dhan (DhanHQ API v2). Public scrip master CSV (no login) + REST with access-token/client-id."""

from __future__ import annotations

import csv
import datetime as dt
import io
import uuid

from ..errors import AdapterError
from ..instruments import Instrument
from ..resources import index_rule, normalise_underlying
from .base import Broker, OrderIntent, f, finalise_chain, i, options_for

API = "https://api.dhan.co/v2"
MASTER = "https://images.dhan.co/api-data/api-scrip-master.csv"
EX = {"NSE": "NFO", "BSE": "BFO"}
SEGMENT = {"NFO": "NSE_FNO", "BFO": "BSE_FNO"}
# Index security IDs (segment IDX_I), verified in Dhan's scrip master (SEM_INSTRUMENT_NAME == INDEX).
INDEX_IDS = {"NIFTY": 13, "BANKNIFTY": 25, "FINNIFTY": 27, "NIFTYNXT50": 38, "MIDCPNIFTY": 442,
             "SENSEX": 51, "BANKEX": 69}
DERIV = {"OPTIDX", "FUTIDX", "OPTSTK", "FUTSTK"}


class Dhan(Broker):
    name = "dhan"
    display = "Dhan"
    env = ("DHAN_CLIENT_ID", "DHAN_ACCESS_TOKEN")
    VERIFICATION = {"master": "live", "option_chain": "docs", "margin": "docs (multi-leg body differs "
                    "between table and example)", "orders": "docs"}

    def master_sources(self):
        return [("ALL", MASTER)]

    def parse_master(self, blob, exchange):
        text = blob.decode("utf-8") if isinstance(blob, bytes) else blob
        out = []
        for r in csv.DictReader(io.StringIO(text)):
            if r["SEM_SEGMENT"] != "D" or r["SEM_INSTRUMENT_NAME"] not in DERIV or r["SEM_EXM_EXCH_ID"] not in EX:
                continue
            opt = r["SEM_OPTION_TYPE"]
            out.append(Instrument(
                exchange=EX[r["SEM_EXM_EXCH_ID"]],
                underlying=normalise_underlying(r["SEM_TRADING_SYMBOL"].split("-")[0]),
                instrument_type=opt if opt in ("CE", "PE") else "FUT",
                expiry=dt.date.fromisoformat(r["SEM_EXPIRY_DATE"][:10]),
                strike=max(f(r["SEM_STRIKE_PRICE"], 0.0), 0.0) if opt in ("CE", "PE") else 0.0,
                lot_size=i(r["SEM_LOT_UNITS"]), tick_size=round(f(r["SEM_TICK_SIZE"]) / 100, 4),
                tradingsymbol=r["SEM_TRADING_SYMBOL"], token=r["SEM_SMST_SECURITY_ID"], source=self.name,
                extra=(("exchange_token", r["SEM_SMST_SECURITY_ID"]), ("custom_symbol", r["SEM_CUSTOM_SYMBOL"]))))
        return out

    def _h(self):
        c = self.creds()
        return {"access-token": c["DHAN_ACCESS_TOKEN"], "client-id": c["DHAN_CLIENT_ID"],
                "Accept": "application/json", "Content-Type": "application/json"}

    def option_chain(self, index, expiry, master):
        rule = index_rule(index)
        opts = options_for(master, rule["index"], expiry)
        body = {"UnderlyingScrip": INDEX_IDS[rule["index"]], "UnderlyingSeg": "IDX_I", "Expiry": expiry.isoformat()}
        res = self._request("POST", f"{API}/optionchain", headers=self._h(), json_body=body)
        data = res.get("data") or {}
        if not data.get("oc"):
            raise AdapterError(f"Dhan option chain empty: {str(res)[:200]}")
        rows = {}
        for k_str, sides in data["oc"].items():
            k = float(k_str)
            row = rows.setdefault(k, {"strike": k})
            for side in ("ce", "pe"):
                d = sides.get(side) or {}
                oi, prev = d.get("oi"), d.get("previous_oi")
                row.update({f"{side}_ltp": d.get("last_price"), f"{side}_bid": d.get("top_bid_price") or None,
                            f"{side}_ask": d.get("top_ask_price") or None, f"{side}_oi": oi,
                            f"{side}_doi": None if oi is None or prev is None else oi - prev,
                            f"{side}_volume": d.get("volume"), f"{side}_iv_src": d.get("implied_volatility")})
        return finalise_chain(rule["index"], expiry, data["last_price"], rows, opts[0].lot_size, self.name)

    def basket_margin(self, legs, master=None):
        c = self.creds()
        scripts = [{"exchangeSegment": SEGMENT[leg["exchange"]], "transactionType": leg["side"].upper(),
                    "quantity": int(leg["qty"]), "productType": "INTRADAY" if leg.get("product") == "MIS" else "MARGIN",
                    "securityId": str(leg["token"]), "price": float(leg.get("price") or 0)} for leg in legs]
        body = {"dhanClientId": c["DHAN_CLIENT_ID"], "includePosition": False, "includeOrders": False,
                "scripts": scripts}
        d = self._request("POST", f"{API}/margincalculator/multi", headers=self._h(), json_body=body)
        d = d.get("data", d)
        return {"broker": self.name, "final_total": f(d.get("total_margin")), "span": f(d.get("span_margin")),
                "exposure": f(d.get("exposure_margin")), "hedge_benefit": f(d.get("hedge_benefit")), "raw": d}

    def order_payload(self, intent: OrderIntent):
        return {"dhanClientId": "<DHAN_CLIENT_ID>", "correlationId": uuid.uuid4().hex[:20],
                "transactionType": intent.side, "exchangeSegment": SEGMENT[intent.instrument.exchange],
                "productType": "INTRADAY" if intent.product == "MIS" else "MARGIN", "orderType": intent.order_type,
                "validity": "DAY", "securityId": str(intent.instrument.token), "quantity": intent.quantity,
                "disclosedQuantity": 0, "price": intent.price if intent.order_type == "LIMIT" else 0,
                "triggerPrice": 0, "afterMarketOrder": False}

    def place_order(self, payload):
        payload = {**payload, "dhanClientId": self.creds()["DHAN_CLIENT_ID"]}
        return self._request("POST", f"{API}/orders", headers=self._h(), json_body=payload)
