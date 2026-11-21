"""Every skill output is wrapped in the same envelope so outputs chain and stay auditable."""

from __future__ import annotations

import datetime as dt
import json
import math
from typing import Any

import numpy as np

from . import DISCLAIMER
from .errors import StaleDataError
from .session import now_ist, to_ist


def envelope(kind: str, data: Any, *, source: str, fetched_at: dt.datetime | None = None,
             stale_after_s: float | None = None, warnings: list[str] | None = None,
             assumptions: list[str] | None = None) -> dict:
    fetched = to_ist(fetched_at or now_ist())
    out = {
        "kind": kind,
        "source": source,
        "fetched_at": fetched.isoformat(timespec="seconds"),
        "stale_after": (fetched + dt.timedelta(seconds=stale_after_s)).isoformat(timespec="seconds")
        if stale_after_s else None,
        "data": data,
        "warnings": warnings or [],
        "assumptions": assumptions or [],
        "disclaimer": DISCLAIMER,
    }
    return out


def ensure_fresh(env_or_ts: dict | str | None, now: dt.datetime | None = None, what: str = "data") -> None:
    """Raise StaleDataError if `stale_after` is in the past."""
    ts = env_or_ts.get("stale_after") if isinstance(env_or_ts, dict) else env_or_ts
    if not ts:
        return
    limit = dt.datetime.fromisoformat(ts)
    now = to_ist(now or now_ist())
    if now > limit:
        raise StaleDataError(
            f"{what} is stale: stale_after={ts}, now={now.isoformat(timespec='seconds')}. "
            "Fetch a fresh snapshot (or pass --allow-stale for after-hours analysis).")


def _default(o):
    if isinstance(o, (np.floating,)):
        f = float(o)
        return None if math.isnan(f) or math.isinf(f) else round(f, 6)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return [_default(x) if isinstance(x, (np.floating, np.integer)) else x for x in o.tolist()]
    if isinstance(o, (dt.date, dt.datetime)):
        return o.isoformat()
    raise TypeError(f"not serialisable: {type(o)}")


def _clean(o):
    if isinstance(o, float):
        return None if math.isnan(o) or math.isinf(o) else round(o, 6)
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


def dumps(obj, indent: int | None = 2) -> str:
    return json.dumps(_clean(obj), default=_default, indent=indent, ensure_ascii=False)
