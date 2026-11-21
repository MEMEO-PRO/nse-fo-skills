"""Symphony XTS (used by IIFL, Jainam and other brokers). Orders only in v0.2.

Each broker hosts its own XTS root URL (XTS_ROOT). exchangeInstrumentID is the exchange
contract token, so any public master (default kite_public, which carries exchange_token)
can resolve instruments. Paths and string enums follow the official xts-pythonclient SDK."""

from __future__ import annotations

import os
import uuid

from ..errors import AdapterError
from .base import Broker, OrderIntent

SEG = {"NFO": "NSEFO", "BFO": "BSEFO"}


class XTS(Broker):
    name = "xts"
    display = "Symphony XTS (IIFL, Jainam, ...)"
    env = ("XTS_ROOT", "XTS_INTERACTIVE_TOKEN")
    VERIFICATION = {"orders": "sdk (paths, string enums)", "master": "use kite_public (exchange tokens)"}

    def order_payload(self, intent: OrderIntent):
        tok = intent.instrument.get("exchange_token")
        if not tok:
            raise AdapterError("XTS needs the exchange token; use a master that carries it (kite_public, upstox, ...).")
        return {"exchangeSegment": SEG[intent.instrument.exchange], "exchangeInstrumentID": int(tok),
                "productType": "MIS" if intent.product == "MIS" else "NRML", "orderType": intent.order_type,
                "orderSide": intent.side, "timeInForce": "DAY", "disclosedQuantity": 0,
                "orderQuantity": intent.quantity, "limitPrice": intent.price if intent.order_type == "LIMIT" else 0,
                "stopPrice": 0, "apiOrderSource": "WEBAPI",
                "orderUniqueIdentifier": (intent.tag or "nsefno")[:10] + uuid.uuid4().hex[:6]}

    def place_order(self, payload):
        c = self.creds()
        if os.environ.get("XTS_CLIENT_ID"):          # dealer / non-investor logins must name the client
            payload = {**payload, "clientID": os.environ["XTS_CLIENT_ID"]}
        res = self._request("POST", c["XTS_ROOT"].rstrip("/") + "/interactive/orders", json_body=payload,
                            headers={"Authorization": c["XTS_INTERACTIVE_TOKEN"], "Content-Type": "application/json"})
        if res.get("type") != "success":
            raise AdapterError(f"XTS: {res.get('description')}")
        return res.get("result")
