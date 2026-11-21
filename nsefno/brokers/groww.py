"""Groww Trade API. Public instrument CSV (no login) + REST (paths from the official growwapi SDK)."""

from __future__ import annotations

import csv
import datetime as dt
import io
import uuid

from ..errors import AdapterError
from ..instruments import Instrument
from ..resources import index_rule, normalise_underlying
from .base import Broker, OrderIntent, f, finalise_chain, i, options_for

API = "https://api.groww.in/v1"
MASTER = "https://growwapi-assets.groww.in/instruments/instrument.csv"
EX = {"NSE": "NFO", "BSE": "BFO"}
EX_BACK = {"NFO": "NSE", "BFO": "BSE"}


class Groww(Broker):
    name = "groww"
    display = "Groww"
    env = ("GROWW_ACCESS_TOKEN",)
    VERIFICATION = {"master": "live", "option_chain": "sdk", "margin": "sdk", "orders": "sdk+docs"}

    def master_sources(self):
        return [("ALL", MASTER)]

    def parse_master(self, blob, exchange):
        text = blob.decode("utf-8") if isinstance(blob, bytes) else blob
        out = []
        for r in csv.DictReader(io.StringIO(text)):
            if r.get("segment") != "FNO" or r.get("exchange") not in EX or r.get("instrument_type") not in ("CE", "PE", "FUT"):
                continue
            out.append(Instrument(
                exchange=EX[r["exchange"]], underlying=normalise_underlying(r["underlying_symbol"]),
                instrument_type=r["instrument_type"], expiry=dt.date.fromisoformat(r["expiry_date"]),
                strike=max(f(r["strike_price"], 0.0), 0.0) if r["instrument_type"] != "FUT" else 0.0,
                lot_size=i(r["lot_size"]), tick_size=f(r["tick_size"]), tradingsymbol=r["trading_symbol"],
                token=r["exchange_token"], freeze_qty=i(r.get("freeze_quantity")) or None, source=self.name,
                extra=(("exchange_token", r["exchange_token"]), ("groww_symbol", r.get("groww_symbol")))))
        return out

    def _h(self):
        return {"Authorization": f"Bearer {self.creds()['GROWW_ACCESS_TOKEN']}", "Accept": "application/json",
                "Content-Type": "application/json", "x-api-version": "1.0", "x-request-id": str(uuid.uuid4())}

    @staticmethod
    def _ok(body):
        if body.get("status") != "SUCCESS":
            raise AdapterError(f"Groww error: {body.get('error') or body}")
        return body.get("payload")

    def option_chain(self, index, expiry, master):
        rule = index_rule(index)
        opts = options_for(master, rule["index"], expiry)
        ex = EX_BACK[opts[0].exchange]
        p = self._ok(self._request("GET", f"{API}/option-chain/exchange/{ex}/underlying/{rule['index']}",
                                   headers=self._h(), params={"expiry_date": expiry.isoformat()}))
        rows = {}
        for k_str, sides in (p.get("strikes") or {}).items():
            k = float(k_str)
            row = rows.setdefault(k, {"strike": k})
            for side in ("CE", "PE"):
                d = sides.get(side) or {}
                s = side.lower()
                row.update({f"{s}_ltp": d.get("ltp"), f"{s}_oi": d.get("open_interest"),
                            f"{s}_volume": d.get("volume"), f"{s}_iv_src": (d.get("greeks") or {}).get("iv")})
        if p.get("underlying_ltp") is None:
            raise AdapterError("Groww option chain returned no underlying_ltp.")
        return finalise_chain(rule["index"], expiry, p["underlying_ltp"], rows, opts[0].lot_size, self.name)

    def basket_margin(self, legs, master=None):
        body = [{"trading_symbol": leg["tradingsymbol"], "transaction_type": leg["side"].upper(),
                 "quantity": int(leg["qty"]), "price": float(leg.get("price") or 0),
                 "order_type": "LIMIT" if leg.get("price") else "MARKET", "product": leg.get("product", "NRML"),
                 "exchange": EX_BACK[leg["exchange"]]} for leg in legs]
        p = self._ok(self._request("POST", f"{API}/margins/detail/orders", headers=self._h(), json_body=body,
                                   params={"segment": "FNO"})) or {}
        return {"broker": self.name, "final_total": f(p.get("total_requirement")), "span": f(p.get("span_required")),
                "exposure": f(p.get("exposure_required")), "option_premium": f(p.get("option_buy_premium")), "raw": p}

    def order_payload(self, intent: OrderIntent):
        ref = (intent.tag or "nsefno")[:8] + uuid.uuid4().hex[:10]
        return {"trading_symbol": intent.instrument.tradingsymbol, "quantity": intent.quantity,
                "price": intent.price if intent.order_type == "LIMIT" else 0, "trigger_price": 0, "validity": "DAY",
                "exchange": EX_BACK[intent.instrument.exchange], "segment": "FNO", "product": intent.product,
                "order_type": intent.order_type, "transaction_type": intent.side,
                "order_reference_id": "".join(ch for ch in ref if ch.isalnum())[:20]}

    def place_order(self, payload):
        return self._ok(self._request("POST", f"{API}/order/create", headers=self._h(), json_body=payload))
