"""Normalised option chain + analytics (forward, IV, Greeks, ATM, PCR, max pain).

Schema (one row per strike, OI always in CONTRACTS - adapters convert):
  strike, ce_ltp, ce_bid, ce_ask, ce_oi, ce_doi, ce_volume, ce_iv_src,
          pe_ltp, pe_bid, pe_ask, pe_oi, pe_doi, pe_volume, pe_iv_src
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

import numpy as np

from . import greeks as g
from .session import to_ist

SIDES = ("ce", "pe")
FIELDS = ("ltp", "bid", "ask", "oi", "doi", "volume", "iv_src")
DEFAULT_RATE = 0.055  # ~91-day T-bill; impact on weekly Black-76 prices is negligible.


@dataclass
class OptionChain:
    underlying: str
    expiry: dt.date
    spot: float
    fetched_at: dt.datetime
    source: str
    lot_size: int | None
    rows: list[dict]
    futures_price: float | None = None
    stale_after_s: float = 120.0
    meta: dict = field(default_factory=dict)

    # ---------- (de)serialisation ----------
    def to_dict(self) -> dict:
        return {
            "underlying": self.underlying, "expiry": self.expiry.isoformat(), "spot": self.spot,
            "fetched_at": to_ist(self.fetched_at).isoformat(timespec="seconds"), "source": self.source,
            "lot_size": self.lot_size, "futures_price": self.futures_price,
            "stale_after_s": self.stale_after_s, "meta": self.meta, "rows": self.rows,
        }

    @classmethod
    def from_dict(cls, d: dict) -> OptionChain:
        return cls(
            underlying=d["underlying"], expiry=dt.date.fromisoformat(d["expiry"]), spot=float(d["spot"]),
            fetched_at=dt.datetime.fromisoformat(d["fetched_at"]), source=d["source"],
            lot_size=d.get("lot_size"), rows=d["rows"], futures_price=d.get("futures_price"),
            stale_after_s=d.get("stale_after_s", 120.0), meta=d.get("meta", {}),
        )

    def col(self, name: str) -> np.ndarray:
        return np.array([np.nan if r.get(name) is None else float(r[name]) for r in self.rows], dtype=float)

    @property
    def strikes(self) -> np.ndarray:
        return self.col("strike")


def _mid(bid: np.ndarray, ask: np.ndarray, ltp: np.ndarray) -> np.ndarray:
    ok = (bid > 0) & (ask > 0) & (ask >= bid)
    spread_ok = ok & ((ask - bid) <= np.maximum(0.25 * (ask + bid) / 2, 2.0))
    return np.where(spread_ok, (bid + ask) / 2, np.where(ltp > 0, ltp, np.nan))


def implied_forward(chain: OptionChain, t: float, r: float) -> tuple[float, str]:
    """Synthetic forward from put-call parity (median over the 5 strikes nearest spot),
    falling back to the futures price, then spot*e^{rt}."""
    K = chain.strikes
    c = _mid(chain.col("ce_bid"), chain.col("ce_ask"), chain.col("ce_ltp"))
    p = _mid(chain.col("pe_bid"), chain.col("pe_ask"), chain.col("pe_ltp"))
    ok = ~np.isnan(c) & ~np.isnan(p)
    if ok.sum() >= 3:
        idx = np.where(ok)[0]
        idx = idx[np.argsort(np.abs(K[idx] - chain.spot))][:5]
        fwd = K[idx] + (c[idx] - p[idx]) * math.exp(r * t)
        return float(np.median(fwd)), "put_call_parity"
    if chain.futures_price:
        return float(chain.futures_price), "futures"
    return float(chain.spot * math.exp(r * t)), "spot_carry"


def max_pain(strikes: np.ndarray, ce_oi: np.ndarray, pe_oi: np.ndarray) -> float:
    """Settlement strike minimising total intrinsic value paid to option holders."""
    ce = np.nan_to_num(ce_oi)
    pe = np.nan_to_num(pe_oi)
    pain = [np.sum(ce * np.maximum(s - strikes, 0)) + np.sum(pe * np.maximum(strikes - s, 0)) for s in strikes]
    return float(strikes[int(np.argmin(pain))])


def analyse(chain: OptionChain, now: dt.datetime | None = None, r: float = DEFAULT_RATE) -> dict:
    """Compute IV (own Black-76 solve on mids), Greeks and summary stats for a chain."""
    now = to_ist(now or chain.fetched_at)
    t = g.year_fraction(now, chain.expiry)
    F, f_src = implied_forward(chain, t, r)
    K = chain.strikes
    out_rows = []
    res = {}
    for side, is_call in (("ce", True), ("pe", False)):
        mid = _mid(chain.col(f"{side}_bid"), chain.col(f"{side}_ask"), chain.col(f"{side}_ltp"))
        iv = g.implied_vols(mid, F, K, t, r, is_call)
        src_iv = chain.col(f"{side}_iv_src") / 100.0
        iv = np.where(np.isnan(iv), np.where(src_iv > 0, src_iv, np.nan), iv)
        gk = g.greeks(F, K, t, np.where(np.isnan(iv), np.nan, iv), r, is_call)
        res[side] = {"mid": mid, "iv": iv, **gk}
    for i, k in enumerate(K):
        row = {"strike": float(k)}
        for side in SIDES:
            s = res[side]
            row.update({
                f"{side}_mid": s["mid"][i], f"{side}_iv": s["iv"][i] * 100 if not np.isnan(s["iv"][i]) else None,
                f"{side}_delta": s["delta"][i], f"{side}_gamma": s["gamma"][i],
                f"{side}_vega": s["vega"][i], f"{side}_theta": s["theta"][i],
                f"{side}_oi": chain.rows[i].get(f"{side}_oi"), f"{side}_doi": chain.rows[i].get(f"{side}_doi"),
                f"{side}_volume": chain.rows[i].get(f"{side}_volume"),
            })
        out_rows.append(row)
    ce_oi, pe_oi = chain.col("ce_oi"), chain.col("pe_oi")
    atm_idx = int(np.argmin(np.abs(K - F)))
    atm_iv_vals = [res[s]["iv"][atm_idx] for s in SIDES if not np.isnan(res[s]["iv"][atm_idx])]
    atm_iv = float(np.mean(atm_iv_vals)) * 100 if atm_iv_vals else None
    straddle = res["ce"]["mid"][atm_idx] + res["pe"]["mid"][atm_idx]
    tot_ce, tot_pe = float(np.nansum(ce_oi)), float(np.nansum(pe_oi))
    ce_doi, pe_doi = chain.col("ce_doi"), chain.col("pe_doi")
    summary = {
        "underlying": chain.underlying, "expiry": chain.expiry.isoformat(),
        "spot": chain.spot, "forward": round(F, 2), "forward_source": f_src,
        "t_years": t, "days_to_expiry": round(t * 365, 3), "rate": r,
        "atm_strike": float(K[atm_idx]), "atm_iv": None if atm_iv is None else round(atm_iv, 2),
        "atm_straddle": None if np.isnan(straddle) else round(float(straddle), 2),
        "expected_move_1sd": None if atm_iv is None else round(F * atm_iv / 100 * math.sqrt(t), 1),
        "pcr_oi": round(tot_pe / tot_ce, 3) if tot_ce else None,
        "pcr_doi": round(float(np.nansum(pe_doi)) / float(np.nansum(ce_doi)), 3)
        if np.nansum(ce_doi) not in (0, 0.0) else None,
        "total_ce_oi_contracts": tot_ce, "total_pe_oi_contracts": tot_pe,
        "max_pain": max_pain(K, ce_oi, pe_oi),
        "max_ce_oi_strike": float(K[int(np.nanargmax(np.nan_to_num(ce_oi)))]),
        "max_pe_oi_strike": float(K[int(np.nanargmax(np.nan_to_num(pe_oi)))]),
        "lot_size": chain.lot_size,
    }
    return {"summary": summary, "rows": out_rows}
