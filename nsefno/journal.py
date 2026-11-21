"""Trade journal: plans + fills in SQLite (~/.nsefno/journal.sqlite) and a weekly post-mortem."""

from __future__ import annotations

import csv
import datetime as dt
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from .config import home
from .costs import Leg, leg_cost

SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, tag TEXT, underlying TEXT,
  thesis TEXT, legs TEXT NOT NULL, status TEXT DEFAULT 'open');
CREATE TABLE IF NOT EXISTS fills (
  id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id INTEGER REFERENCES plans(id), ts TEXT NOT NULL,
  tradingsymbol TEXT NOT NULL, instrument TEXT NOT NULL, side TEXT NOT NULL, qty INTEGER NOT NULL,
  price REAL NOT NULL, planned_price REAL, exchange TEXT DEFAULT 'NSE', costs REAL, ext_id TEXT UNIQUE);
"""


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(str(path or home() / "journal.sqlite"))
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def add_plan(con, tag: str, underlying: str, legs: list[dict], thesis: str = "",
             created_at: str | None = None) -> int:
    cur = con.execute("INSERT INTO plans(created_at, tag, underlying, thesis, legs) VALUES (?,?,?,?,?)",
                      (created_at or dt.datetime.now().isoformat(timespec="seconds"), tag, underlying.upper(),
                       thesis, json.dumps(legs)))
    con.commit()
    return cur.lastrowid


def _instrument_of(sym: str) -> str:
    s = sym.upper()
    return "FUT" if s.endswith("FUT") else s[-2:]


def add_fill(con, plan_id: int | None, ts: str, tradingsymbol: str, side: str, qty: int, price: float,
             planned_price: float | None = None, exchange: str = "NSE", broker: str = "zerodha",
             ext_id: str | None = None) -> int | None:
    inst = _instrument_of(tradingsymbol)
    c = leg_cost(Leg(inst, side.upper(), price, qty, exchange), broker,
                 on=dt.date.fromisoformat(ts[:10]))["total"]
    try:
        cur = con.execute("INSERT INTO fills(plan_id, ts, tradingsymbol, instrument, side, qty, price, planned_price,"
                          " exchange, costs, ext_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                          (plan_id, ts, tradingsymbol.upper(), inst, side.upper(), int(qty), float(price),
                           planned_price, exchange, c, ext_id))
    except sqlite3.IntegrityError:
        return None  # duplicate ext_id (re-import of the same tradebook)
    con.commit()
    return cur.lastrowid


def import_kite_tradebook(con, path: str, plan_id: int | None = None) -> int:
    """Zerodha Console tradebook CSV (symbol, trade_date, exchange, trade_type, quantity, price, trade_id,
    order_execution_time)."""
    n = 0
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            ts = r.get("order_execution_time") or r["trade_date"]
            ex = "BSE" if r.get("exchange", "").upper() in ("BFO", "BSE") else "NSE"
            if add_fill(con, plan_id, ts.replace(" ", "T"), r["symbol"], r["trade_type"], int(float(r["quantity"])),
                        float(r["price"]), exchange=ex, ext_id=r.get("trade_id")):
                n += 1
    return n


def _plan_pnl(fills: list[sqlite3.Row]) -> dict:
    net_qty: dict[str, int] = defaultdict(int)
    cash = 0.0
    costs = 0.0
    slip = 0.0
    slip_units = 0
    for f in fills:
        sgn = 1 if f["side"] == "BUY" else -1
        net_qty[f["tradingsymbol"]] += sgn * f["qty"]
        cash -= sgn * f["qty"] * f["price"]
        costs += f["costs"] or 0
        if f["planned_price"] is not None:
            # Positive slippage = worse than plan (paid more on buys, received less on sells).
            slip += sgn * (f["price"] - f["planned_price"]) * f["qty"]
            slip_units += f["qty"]
    closed = all(q == 0 for q in net_qty.values())
    return {"closed": closed, "gross_pnl": round(cash, 2) if closed else None, "costs": round(costs, 2),
            "net_pnl": round(cash - costs, 2) if closed else None, "slippage_inr": round(slip, 2),
            "slippage_pts": round(slip / slip_units, 3) if slip_units else None}


def weekly_review(con, start: dt.date, end: dt.date) -> dict:
    plans = con.execute("SELECT * FROM plans WHERE date(created_at) BETWEEN ? AND ?",
                        (start.isoformat(), end.isoformat())).fetchall()
    per = []
    for p in plans:
        fills = con.execute("SELECT * FROM fills WHERE plan_id=? ORDER BY ts", (p["id"],)).fetchall()
        if not fills:
            continue
        per.append({"plan_id": p["id"], "tag": p["tag"], "underlying": p["underlying"], **_plan_pnl(fills)})
    closed = [x for x in per if x["closed"]]
    wins = [x for x in closed if x["net_pnl"] > 0]
    gross = sum(x["gross_pnl"] for x in closed)
    cost = sum(x["costs"] for x in closed)
    by_tag: dict[str, list] = defaultdict(list)
    for x in closed:
        by_tag[x["tag"] or "untagged"].append(x["net_pnl"])
    return {
        "period": f"{start.isoformat()}..{end.isoformat()}", "trades_closed": len(closed),
        "trades_open": len(per) - len(closed),
        "win_rate_pct": round(100 * len(wins) / len(closed), 1) if closed else None,
        "gross_pnl": round(gross, 2), "costs": round(cost, 2), "net_pnl": round(gross - cost, 2),
        "cost_drag_pct_of_gross": round(100 * cost / abs(gross), 1) if gross else None,
        "avg_win": round(sum(x["net_pnl"] for x in wins) / len(wins), 2) if wins else None,
        "avg_loss": round(sum(x["net_pnl"] for x in closed if x["net_pnl"] <= 0) /
                          max(1, len(closed) - len(wins)), 2) if len(closed) > len(wins) else None,
        "total_slippage_inr": round(sum(x["slippage_inr"] for x in per), 2),
        "by_tag": {k: {"n": len(v), "net_pnl": round(sum(v), 2)} for k, v in by_tag.items()},
        "trades": per,
    }
