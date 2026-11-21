"""5paisa OpenAPI (Xstream). Public ScripMaster CSVs (no login) + REST {head:{key}, body:{...}}.

Option-chain response fields could not be read from the docs; parsing is tolerant and raw
data is returned. A margin endpoint for arbitrary baskets is not wired (fields unverified)."""

from __future__ import annotations

import calendar
import csv
import datetime as dt
import io
import uuid

from ..errors import AdapterError
from ..instruments import Instrument
from ..resources import index_rule, normalise_underlying
from .base import Broker, OrderIntent, f, finalise_chain, first, i, options_for

BASE = "https://Openapi.5paisa.com/VendorsAPI/Service1.svc/"
EX = {"N": "NFO", "B": "BFO"}
EX_BACK = {"NFO": "N", "BFO": "B"}


class FivePaisa(Broker):
    name = "fivepaisa"
    display = "5paisa"
    env = ("FIVEPAISA_APP_KEY", "FIVEPAISA_ACCESS_TOKEN", "FIVEPAISA_CLIENT_CODE")
    VERIFICATION = {"master": "live", "option_chain": "sdk (path); response fields tolerant", "orders": "docs"}

    def master_sources(self):
        return [("NFO", f"{BASE}ScripMaster/segment/NSE_FO"), ("BFO", f"{BASE}ScripMaster/segment/BSE_FO")]

    def parse_master(self, blob, exchange):
        text = blob.decode("utf-8") if isinstance(blob, bytes) else blob
        out = []
        for r in csv.DictReader(io.StringIO(text)):
            if r.get("ExchType") != "D" or r.get("Exch") not in EX or r.get("ScripType") not in ("CE", "PE", "XX"):
                continue
            itype = r["ScripType"] if r["ScripType"] in ("CE", "PE") else "FUT"
            out.append(Instrument(
                exchange=EX[r["Exch"]], underlying=normalise_underlying(r["SymbolRoot"]), instrument_type=itype,
                expiry=dt.date.fromisoformat(r["Expiry"][:10]),
                strike=f(r["StrikeRate"], 0.0) if itype != "FUT" else 0.0, lot_size=i(r["LotSize"]),
                tick_size=f(r["TickSize"]), tradingsymbol=r["Name"], token=r["ScripCode"],
                max_order_qty=i(r.get("QtyLimit")) or None, source=self.name,
                extra=(("exchange_token", r["ScripCode"]), ("scrip_data", r.get("ScripData")))))
        return out

    def _call(self, route: str, body: dict) -> dict:
        c = self.creds()
        res = self._request("POST", BASE + route, json_body={"head": {"key": c["FIVEPAISA_APP_KEY"]},
                                                             "body": {"ClientCode": c["FIVEPAISA_CLIENT_CODE"], **body}},
                            headers={"Authorization": f"bearer {c['FIVEPAISA_ACCESS_TOKEN']}",
                                     "Content-Type": "application/json"})
        return res.get("body") or {}

    def option_chain(self, index, expiry, master):
        rule = index_rule(index)
        opts = options_for(master, rule["index"], expiry)
        ms = calendar.timegm(dt.datetime.combine(expiry, dt.time(0, 0)).timetuple()) * 1000
        body = self._call("GetOptionsForSymbol", {"Exch": EX_BACK[opts[0].exchange], "Symbol": rule["index"],
                                                  "ExpiryDate": f"/Date({ms})/"})
        rows = {}
        for d in body.get("Options") or []:
            k = f(first(d, "StrikeRate", "StrikePrice"))
            side = str(first(d, "CPType", "OptionType", default="")).lower()
            if k is None or side not in ("ce", "pe"):
                continue
            rows.setdefault(k, {"strike": k}).update({f"{side}_ltp": f(first(d, "LastRate", "LTP")),
                                                      f"{side}_oi": f(first(d, "OpenInterest", "OI")),
                                                      f"{side}_volume": f(first(d, "Volume"))})
        spot = f(first(body, "UnderlyingLastRate", "SpotPrice"))
        if not rows or spot is None:
            raise AdapterError(f"5paisa option chain: unexpected response keys {list(body)[:10]}")
        return finalise_chain(rule["index"], expiry, spot, rows, opts[0].lot_size, self.name)

    def order_payload(self, intent: OrderIntent):
        return {"OrderType": "B" if intent.side == "BUY" else "S", "Exchange": EX_BACK[intent.instrument.exchange],
                "ExchangeType": "D", "ScripCode": str(intent.instrument.token),
                "ScripData": intent.instrument.get("scrip_data") or "",
                "Price": intent.price if intent.order_type == "LIMIT" else 0, "Qty": intent.quantity, "DisQty": 0,
                "StopLossPrice": 0, "IsIntraday": intent.product == "MIS", "AHPlaced": "N",
                "RemoteOrderID": (intent.tag or "nsefno")[:10] + uuid.uuid4().hex[:10]}

    def place_order(self, payload):
        return self._call("V1/PlaceOrderRequest", payload)
