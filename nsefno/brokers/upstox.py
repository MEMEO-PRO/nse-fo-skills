"""Upstox API v2/v3. Public instrument JSON (no login) + REST with a Bearer access token."""

from __future__ import annotations

import gzip
import json

from ..errors import AdapterError
from ..instruments import Instrument
from ..resources import index_rule, normalise_underlying
from .base import Broker, OrderIntent, f, finalise_chain, i, ist_date_from_epoch, options_for

API = "https://api.upstox.com/v2"
HFT = "https://api-hft.upstox.com/v3"
ASSETS = "https://assets.upstox.com/market-quote/instruments/exchange"
SEG = {"NSE_FO": "NFO", "BSE_FO": "BFO"}


class Upstox(Broker):
    name = "upstox"
    display = "Upstox"
    env = ("UPSTOX_ACCESS_TOKEN",)
    VERIFICATION = {"master": "live", "option_chain": "docs", "margin": "docs", "orders": "docs (v3)"}

    def master_sources(self):
        return [("NFO", f"{ASSETS}/NSE.json.gz"), ("BFO", f"{ASSETS}/BSE.json.gz")]

    def parse_master(self, blob, exchange):
        raw = gzip.decompress(blob) if isinstance(blob, bytes) and blob[:2] == b"\x1f\x8b" else blob
        out = []
        for r in json.loads(raw):
            if r.get("segment") not in SEG or r.get("instrument_type") not in ("CE", "PE", "FUT"):
                continue
            out.append(Instrument(
                exchange=SEG[r["segment"]], underlying=normalise_underlying(r.get("underlying_symbol") or r["name"]),
                instrument_type=r["instrument_type"], expiry=ist_date_from_epoch(r["expiry"] / 1000),
                strike=f(r.get("strike_price"), 0.0), lot_size=i(r["lot_size"]),
                tick_size=round(f(r["tick_size"]) / 100, 4), tradingsymbol=r["trading_symbol"],
                token=r["instrument_key"], max_order_qty=i(r.get("freeze_quantity")), source=self.name,
                extra=(("exchange_token", r.get("exchange_token")), ("underlying_key", r.get("underlying_key")))))
        return out

    def _h(self):
        return {"Authorization": f"Bearer {self.creds()['UPSTOX_ACCESS_TOKEN']}", "Accept": "application/json",
                "Content-Type": "application/json"}

    @staticmethod
    def _ok(body):
        if body.get("status") != "success":
            raise AdapterError(f"Upstox error: {body.get('errors') or body}")
        return body["data"]

    def option_chain(self, index, expiry, master):
        rule = index_rule(index)
        opts = options_for(master, rule["index"], expiry)
        ukey = opts[0].get("underlying_key")
        data = self._ok(self._request("GET", f"{API}/option/chain", headers=self._h(),
                                      params={"instrument_key": ukey, "expiry_date": expiry.isoformat()}))
        rows, spot = {}, None
        for d in data:
            k = float(d["strike_price"])
            spot = d.get("underlying_spot_price", spot)
            row = rows.setdefault(k, {"strike": k})
            for side, key in (("ce", "call_options"), ("pe", "put_options")):
                md = (d.get(key) or {}).get("market_data") or {}
                gk = (d.get(key) or {}).get("option_greeks") or {}
                row.update({f"{side}_ltp": md.get("ltp"), f"{side}_bid": md.get("bid_price") or None,
                            f"{side}_ask": md.get("ask_price") or None, f"{side}_oi": md.get("oi"),
                            f"{side}_doi": None if md.get("oi") is None or md.get("prev_oi") is None
                            else md["oi"] - md["prev_oi"],
                            f"{side}_volume": md.get("volume"), f"{side}_iv_src": gk.get("iv")})
        if spot is None:
            raise AdapterError("Upstox option chain returned no data.")
        return finalise_chain(rule["index"], expiry, spot, rows, opts[0].lot_size, self.name)

    def basket_margin(self, legs, master=None):
        body = {"instruments": [{"instrument_key": leg["token"], "quantity": int(leg["qty"]),
                                 "transaction_type": leg["side"].upper(),
                                 "product": "I" if leg.get("product") == "MIS" else "D",
                                 **({"price": float(leg["price"])} if leg.get("price") else {})} for leg in legs]}
        data = self._ok(self._request("POST", f"{API}/charges/margin", headers=self._h(), json_body=body))
        m = data.get("margins") or []
        return {"broker": self.name, "final_total": data.get("final_margin"),
                "initial_total": data.get("required_margin"),
                "span": sum(f(x.get("span_margin"), 0) for x in m) if m else None,
                "exposure": sum(f(x.get("exposure_margin"), 0) for x in m) if m else None,
                "hedge_benefit": None if data.get("required_margin") is None or data.get("final_margin") is None
                else round(data["required_margin"] - data["final_margin"], 2), "raw": data}

    def order_payload(self, intent: OrderIntent):
        return {"instrument_token": intent.instrument.token, "quantity": intent.quantity,
                "product": "I" if intent.product == "MIS" else "D", "validity": "DAY",
                "price": intent.price if intent.order_type == "LIMIT" else 0, "order_type": intent.order_type,
                "transaction_type": intent.side, "disclosed_quantity": 0, "trigger_price": 0, "is_amo": False,
                "slice": False, **({"tag": intent.tag[:40]} if intent.tag else {})}

    def place_order(self, payload):
        return self._ok(self._request("POST", f"{HFT}/order/place", headers=self._h(), json_body=payload))
