"""SEBI-aware order preparation. DRY-RUN BY DEFAULT.

Guardrails (all enforced in code, not just in SKILL.md):
  * Never sends without a confirmation token bound to the exact payload; tokens expire in 60 s.
  * Refuses to send outside the normal session (pre-open, closed, weekend, holiday).
  * Quantity must be a whole number of lots from the day's instrument master.
  * Slices orders strictly below the exchange freeze quantity.
  * Limit price must sit on the tick grid and inside the price band when one is known.
  * Throttles below 10 orders/second (SEBI retail-algo threshold, per exchange).
  * Max-lots cap per leg from config; Algo-ID tag field; static-IP reminder.
  * Every prepared/sent payload is appended (redacted) to ~/.nsefno/logs/orders.jsonl.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from collections import deque
from pathlib import Path

import yaml

from . import session
from .config import home, redact
from .errors import ComplianceBlock
from .instruments import Instrument, InstrumentMaster

TOKEN_TTL_S = 60
SEBI_OPS_LIMIT = 10          # orders/sec per exchange above which strategy registration is required
DEFAULT_OPS = 8              # our throttle - stays safely under the limit


# ----------------------------- config -----------------------------

def load_config() -> dict:
    p = home() / "config.yaml"
    cfg = {"broker": "kite", "max_lots_per_leg": 10, "algo_id": None, "static_ip": None,
           "product": "NRML", "orders_per_second": DEFAULT_OPS}
    if p.exists():
        cfg.update(yaml.safe_load(p.read_text()) or {})
    if cfg["orders_per_second"] >= SEBI_OPS_LIMIT:
        raise ComplianceBlock(f"orders_per_second={cfg['orders_per_second']} must stay below {SEBI_OPS_LIMIT} "
                              "unless the strategy is exchange-registered.")
    return cfg


# ----------------------------- throttle -----------------------------

class RateLimiter:
    """Sliding-window limiter: at most `max_per_sec` calls in any rolling 1-second window."""

    def __init__(self, max_per_sec: int = DEFAULT_OPS, clock=time.monotonic, sleep=time.sleep):
        self.max = max_per_sec
        self.clock, self.sleep = clock, sleep
        self.calls: deque[float] = deque()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        with self.lock:
            while True:
                now = self.clock()
                while self.calls and now - self.calls[0] >= 1.0:
                    self.calls.popleft()
                if len(self.calls) < self.max:
                    self.calls.append(now)
                    return
                self.sleep(1.0 - (now - self.calls[0]) + 1e-3)


# ----------------------------- slicing / checks -----------------------------

def slice_quantity(qty: int, lot: int, freeze_qty: int | None) -> list[int]:
    """Split `qty` into slices that are whole lots and strictly below `freeze_qty`."""
    if qty <= 0 or qty % lot:
        raise ComplianceBlock(f"Quantity {qty} is not a positive multiple of lot size {lot}.")
    if not freeze_qty:
        return [qty]
    max_lots = (freeze_qty - 1) // lot
    if max_lots < 1:
        raise ComplianceBlock(f"Freeze qty {freeze_qty} is below one lot ({lot}).")
    per = max_lots * lot
    out = [per] * (qty // per)
    if qty % per:
        out.append(qty % per)
    return out


def check_price(price: float | None, tick: float, band: tuple[float, float] | None, order_type: str) -> list[str]:
    issues = []
    if order_type == "MARKET":
        issues.append("MARKET order: brokers convert these to market-price-protection orders; prefer LIMIT.")
        return issues
    if price is None or price <= 0:
        raise ComplianceBlock("LIMIT order needs a positive price.")
    ticks = price / tick
    if abs(ticks - round(ticks)) > 1e-6:
        raise ComplianceBlock(f"Price {price} is not a multiple of tick size {tick}.")
    if band:
        lo, hi = band
        if not (lo <= price <= hi):
            raise ComplianceBlock(f"Price {price} outside exchange price band [{lo}, {hi}].")
    return issues


# ----------------------------- confirmation token -----------------------------

def _key() -> bytes:
    p = home() / ".confirm_key"
    if not p.exists():
        p.write_bytes(secrets.token_bytes(32))
        os.chmod(p, 0o600)
    return p.read_bytes()


def payload_hash(orders: list[dict]) -> str:
    canon = json.dumps(orders, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


def issue_token(orders: list[dict], now: float | None = None) -> str:
    exp = int((now or time.time()) + TOKEN_TTL_S)
    sig = hmac.new(_key(), f"{payload_hash(orders)}.{exp}".encode(), hashlib.sha256).hexdigest()[:20]
    return f"{exp}.{sig}"


def verify_token(token: str, orders: list[dict], now: float | None = None) -> None:
    try:
        exp_s, sig = token.split(".")
        exp = int(exp_s)
    except ValueError:
        raise ComplianceBlock("Malformed confirmation token.") from None
    if (now or time.time()) > exp:
        raise ComplianceBlock("Confirmation token expired (60 s). Re-run the dry run and confirm again.")
    good = hmac.new(_key(), f"{payload_hash(orders)}.{exp}".encode(), hashlib.sha256).hexdigest()[:20]
    if not hmac.compare_digest(good, sig):
        raise ComplianceBlock("Confirmation token does not match this exact order payload.")


def _log(event: str, body: dict) -> None:
    p = home() / "logs"
    p.mkdir(exist_ok=True)
    with (p / "orders.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": session.now_ist().isoformat(timespec="seconds"), "event": event,
                             **redact(body)}) + "\n")


# ----------------------------- prepare / send -----------------------------

def _kite_payload(inst: Instrument, side: str, qty: int, order_type: str, price: float | None,
                  product: str, tag: str | None) -> dict:
    p = {"exchange": inst.exchange, "tradingsymbol": inst.tradingsymbol, "transaction_type": side,
         "quantity": qty, "order_type": order_type, "product": product, "validity": "DAY"}
    if order_type == "LIMIT":
        p["price"] = price
    if tag:
        p["tag"] = tag[:20]
    return p


def prepare(plan: list[dict], master: InstrumentMaster, cfg: dict | None = None,
            bands: dict[str, tuple[float, float]] | None = None, freeze: dict[str, int] | None = None,
            now: dt.datetime | None = None) -> dict:
    """Build the exact payloads + checklist. plan legs: {"instrument": text|tradingsymbol, "side",
    "lots", "order_type": LIMIT|MARKET, "price"}."""
    cfg = cfg or load_config()
    bands, freeze = bands or {}, freeze or {}
    state = session.market_state(now)
    orders, checklist, warnings = [], [], []
    for leg in plan:
        inst = master.resolve(leg["instrument"])
        side = leg["side"].upper()
        if side not in ("BUY", "SELL"):
            raise ComplianceBlock(f"side must be BUY/SELL, got {side}")
        lots = int(leg["lots"])
        if lots > cfg["max_lots_per_leg"]:
            raise ComplianceBlock(f"{inst.tradingsymbol}: {lots} lots exceeds max_lots_per_leg="
                                  f"{cfg['max_lots_per_leg']} (edit ~/.nsefno/config.yaml to change).")
        qty = lots * inst.lot_size
        otype = leg.get("order_type", "LIMIT").upper()
        warnings += check_price(leg.get("price"), inst.tick_size, bands.get(inst.tradingsymbol), otype)
        fq = inst.freeze_qty or freeze.get(inst.underlying) or freeze.get(inst.tradingsymbol)
        if fq is None:
            warnings.append(f"No freeze quantity known for {inst.underlying}; pass --freeze-qty "
                            "or use a master that carries it (Kotak Neo). Not slicing.")
        slices = slice_quantity(qty, inst.lot_size, fq)
        for q in slices:
            orders.append(_kite_payload(inst, side, q, otype, leg.get("price"), leg.get("product", cfg["product"]),
                                        cfg.get("algo_id")))
        checklist.append({"leg": leg["instrument"], "resolved": inst.tradingsymbol, "expiry": inst.expiry.isoformat(),
                          "lot_size": inst.lot_size, "lots": lots, "qty": qty, "slices": slices,
                          "tick_size": inst.tick_size, "freeze_qty": fq})
    if not cfg.get("static_ip"):
        warnings.append("No static_ip in ~/.nsefno/config.yaml. From 1 Apr 2026, API orders are accepted only "
                        "from the static IP whitelisted with your broker.")
    if not cfg.get("algo_id"):
        warnings.append("No algo_id configured. Orders via broker APIs carry the broker-assigned (generic) Algo-ID; "
                        "strategies above 10 orders/sec need exchange registration.")
    if time.localtime().tm_gmtoff != 19800:
        warnings.append("This machine's clock is not on IST - check that your broker allows API orders from "
                        "this location/IP (algo servers are expected to be in India).")
    sendable = state["state"] == "open"
    if not sendable:
        warnings.append(f"Market state is '{state['state']}': sending is blocked (no AMO/pre-open orders in v0.1).")
    token = issue_token(orders) if sendable else None
    result = {"mode": "dry_run", "market_state": state, "orders": orders, "n_orders": len(orders),
              "checklist": checklist, "warnings": warnings, "payload_sha256": payload_hash(orders),
              "confirm_token": token, "token_expires_in_s": TOKEN_TTL_S if token else None,
              "how_to_send": "Show this dry run to the user. ONLY if they explicitly confirm, run "
                             "`nsefno order send --sha <payload_sha256> --confirm <token>` within 60 s." if token else
              "Sending is blocked right now."}
    _log("prepared", {"payload_sha256": result["payload_sha256"], "orders": orders, "warnings": warnings})
    pending_path(result["payload_sha256"]).write_text(json.dumps(orders))
    return result


def send(prepared_orders: list[dict], token: str, broker: str = "kite", now: dt.datetime | None = None,
         sender=None, limiter: RateLimiter | None = None) -> list[dict]:
    """Send previously prepared orders after verifying the confirmation token."""
    verify_token(token, prepared_orders)
    state = session.market_state(now)
    if state["state"] != "open":
        raise ComplianceBlock(f"Refusing to send: market state is '{state['state']}'.")
    cfg = load_config()
    limiter = limiter or RateLimiter(cfg["orders_per_second"])
    if sender is None:
        if broker != "kite":
            raise ComplianceBlock("Live sending is implemented for Kite in v0.1; use the dry-run payload with "
                                  "your Kotak Neo client.")
        from .adapters import kite

        sender = kite.place_order
    results = []
    for o in prepared_orders:
        limiter.acquire()
        try:
            res = sender(o)
            results.append({"order": o, "status": "sent", "response": res})
        except Exception as e:  # report, stop on first failure (no partial blind retries)
            results.append({"order": o, "status": "error", "error": str(e)})
            _log("send_error", {"order": o, "error": str(e)})
            break
    _log("sent", {"payload_sha256": payload_hash(prepared_orders), "results": results})
    return results


def pending_path(sha: str) -> Path:
    p = home() / "pending"
    p.mkdir(exist_ok=True)
    return p / f"{sha}.json"
