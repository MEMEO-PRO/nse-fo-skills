"""ICICI Direct Breeze API. Public SecurityMaster.zip (no login) + REST with SHA-256 checksum headers.

Per the Breeze docs, market orders are not permitted via API, orders need a registered
static IP, and the combined order rate limit is 10/sec."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import zipfile

from ..errors import AdapterError, ComplianceBlock
from ..instruments import Instrument
from ..resources import index_rule, normalise_underlying
from .base import Broker, OrderIntent, f, finalise_chain, first, i, options_for

API = "https://api.icicidirect.com/breezeapi/api/v1/"
MASTER = "https://directlink.icicidirect.com/NewSecurityMaster/SecurityMaster.zip"
FILES = {"NFO": "FONSEScripMaster.txt", "BFO": "FOBSEScripMaster.txt"}
OPT, FUT = {"OPTIDX", "OPTSTK", "OPTIND"}, {"FUTIDX", "FUTSTK", "FUTIND"}


def breeze_expiry(d: dt.date) -> str:
    return f"{d.isoformat()}T06:00:00.000Z"


class Breeze(Broker):
    name = "breeze"
    display = "ICICI Direct Breeze"
    env = ("BREEZE_APP_KEY", "BREEZE_SECRET_KEY", "BREEZE_SESSION_TOKEN")
    VERIFICATION = {"master": "live", "option_chain": "sdk (path) + docs; response fields tolerant",
                    "margin": "docs", "orders": "sdk"}

    def master_sources(self):
        return [("ALL", MASTER)]

    def parse_master(self, blob, exchange):
        out = []
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            for ex, name in FILES.items():
                text = z.read(name).decode("utf-8", "replace")
                for r in csv.DictReader(io.StringIO(text)):
                    inst = r.get("InstrumentName")
                    if inst not in OPT | FUT:
                        continue
                    itype = r["OptionType"] if inst in OPT else "FUT"
                    if itype not in ("CE", "PE", "FUT"):
                        continue
                    exp = dt.datetime.strptime(r["ExpiryDate"], "%d-%b-%Y").date()
                    strike = f(r["StrikePrice"], 0.0) if itype != "FUT" else 0.0
                    code = r["ShortName"]
                    out.append(Instrument(
                        exchange=ex, underlying=normalise_underlying(code), instrument_type=itype, expiry=exp,
                        strike=strike, lot_size=i(r["LotSize"]), tick_size=round(f(r["TickSize"]) / 100, 4),
                        tradingsymbol=f"{code}{exp:%d%b%y}{'' if itype == 'FUT' else f'{strike:g}'}{itype}".upper(),
                        token=r["Token"], source=self.name,
                        extra=(("exchange_token", r["Token"]), ("stock_code", code))))
        return out

    def _call(self, method: str, endpoint: str, body: dict):
        c = self.creds()
        payload = json.dumps(body, separators=(",", ":"))
        ts = dt.datetime.now(dt.UTC).isoformat()[:19] + ".000Z"
        checksum = hashlib.sha256((ts + payload + c["BREEZE_SECRET_KEY"]).encode()).hexdigest()
        headers = {"Content-Type": "application/json", "X-Checksum": "token " + checksum, "X-Timestamp": ts,
                   "X-AppKey": c["BREEZE_APP_KEY"], "X-SessionToken": c["BREEZE_SESSION_TOKEN"]}
        res = self._request(method, API + endpoint, headers=headers, data=payload)
        if res.get("Status") not in (200, "200") or res.get("Error"):
            raise AdapterError(f"Breeze {endpoint}: {res.get('Error') or res}")
        return res.get("Success")

    def option_chain(self, index, expiry, master):
        rule = index_rule(index)
        opts = options_for(master, rule["index"], expiry)
        code = opts[0].get("stock_code")
        rows, spot = {}, None
        for right, side in (("call", "ce"), ("put", "pe")):
            res = self._call("GET", "optionchain", {"stock_code": code, "exchange_code": opts[0].exchange,
                                                    "expiry_date": breeze_expiry(expiry), "product_type": "options",
                                                    "right": right, "strike_price": ""}) or []
            for d in res:
                k = f(d.get("strike_price"))
                if k is None:
                    continue
                spot = f(first(d, "spot_price", "underlying_value"), spot)
                rows.setdefault(k, {"strike": k}).update({
                    f"{side}_ltp": f(d.get("ltp")), f"{side}_bid": f(d.get("best_bid_price")) or None,
                    f"{side}_ask": f(d.get("best_offer_price")) or None, f"{side}_oi": f(d.get("open_interest")),
                    f"{side}_doi": f(d.get("chnge_oi")), f"{side}_volume": f(d.get("total_quantity_traded"))})
        if spot is None:
            raise AdapterError("Breeze option chain carried no spot price; pass --source with another broker.")
        return finalise_chain(rule["index"], expiry, spot, rows, opts[0].lot_size, self.name)

    def basket_margin(self, legs, master=None):
        pos = []
        for leg in legs:
            inst = leg["instrument_obj"]
            pos.append({"strike_price": "0" if inst.instrument_type == "FUT" else f"{inst.strike:g}",
                        "quantity": str(int(leg["qty"])), "right": {"CE": "call", "PE": "put"}.get(inst.instrument_type, "others"),
                        "product": "futures" if inst.instrument_type == "FUT" else "options",
                        "action": leg["side"].lower(), "price": str(leg.get("price") or 0),
                        "expiry_date": breeze_expiry(inst.expiry), "stock_code": inst.get("stock_code"),
                        "cover_order_flow": "N", "fresh_order_type": "N", "cover_limit_rate": "0",
                        "cover_sltp_price": "0", "fresh_limit_rate": "0", "open_quantity": "0"})
        res = self._call("POST", "margincalculator", {"list_of_positions": pos, "exchange_code": legs[0]["exchange"]})
        return {"broker": self.name, "final_total": f(first(res or {}, "margin_calulation", "total_margin")),
                "raw": res}

    def order_payload(self, intent: OrderIntent):
        if intent.order_type != "LIMIT":
            raise ComplianceBlock("Breeze does not permit market orders via API - use LIMIT.")
        inst = intent.instrument
        return {"stock_code": inst.get("stock_code"), "exchange_code": inst.exchange,
                "product": "futures" if inst.instrument_type == "FUT" else "options",
                "action": intent.side.lower(), "order_type": "limit", "quantity": str(intent.quantity),
                "price": str(intent.price), "validity": "day", "stoploss": "", "disclosed_quantity": "0",
                "expiry_date": breeze_expiry(inst.expiry),
                "right": {"CE": "call", "PE": "put"}.get(inst.instrument_type, "others"),
                "strike_price": "0" if inst.instrument_type == "FUT" else f"{inst.strike:g}",
                "user_remark": (intent.tag or "")[:20]}

    def place_order(self, payload):
        return self._call("POST", "order", payload)
