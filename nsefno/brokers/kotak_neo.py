"""Kotak Neo. Scrip master CSV (URLs come from the logged-in SDK) + the official neo_api_client SDK."""

from __future__ import annotations

from ..adapters import kotak_neo as _neo
from ..errors import ConfigError
from .base import Broker, OrderIntent


class KotakNeo(Broker):
    name = "kotak_neo"
    display = "Kotak Neo"
    env = ("NEO_CONSUMER_KEY", "NEO_MOBILE", "NEO_UCC", "NEO_MPIN", "NEO_TOTP")
    VERIFICATION = {"master": "format from SDK docs (synthetic fixture)", "margin": "sdk", "orders": "sdk"}

    def load_master(self, ttl: float = 6 * 3600):
        raise ConfigError("Kotak Neo's scrip master needs a login: download nse_fo.csv / bse_fo.csv via "
                          "client.scrip_master() and pass --master kotak_neo --master-file <csv>.")

    def parse_master(self, blob, exchange):
        return _neo.parse_scrip_master(blob.decode("utf-8") if isinstance(blob, bytes) else blob)

    def basket_margin(self, legs, master=None):
        c = _neo.client()
        per = [c.margin_required(exchange_segment="nse_fo" if leg["exchange"] == "NFO" else "bse_fo",
                                 price=str(leg.get("price") or 0), order_type="L" if leg.get("price") else "MKT",
                                 product=leg.get("product", "NRML"), quantity=str(int(leg["qty"])),
                                 instrument_token=str(leg["token"]),
                                 transaction_type="B" if leg["side"].upper() == "BUY" else "S") for leg in legs]
        return {"broker": self.name, "per_order": per,
                "note": "Sum of per-order margins; hedge benefit not reflected."}

    def order_payload(self, intent: OrderIntent):
        return {"exchange_segment": "nse_fo" if intent.instrument.exchange == "NFO" else "bse_fo",
                "product": intent.product, "price": str(intent.price if intent.order_type == "LIMIT" else 0),
                "order_type": "L" if intent.order_type == "LIMIT" else "MKT", "quantity": str(intent.quantity),
                "validity": "DAY", "trading_symbol": intent.instrument.tradingsymbol,
                "transaction_type": "B" if intent.side == "BUY" else "S", "amo": "NO",
                **({"tag": intent.tag[:20]} if intent.tag else {})}

    def place_order(self, payload):
        return _neo.client().place_order(**payload)
