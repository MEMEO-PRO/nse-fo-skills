"""Local snapshot store under ~/.nsefno/ (gzip JSON; parquet export if pyarrow is installed).

Lets skills compare today vs the previous snapshot without re-fetching.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import json
from pathlib import Path

from ..chain import OptionChain
from ..config import home
from ..session import to_ist


def _dir(underlying: str, expiry: dt.date) -> Path:
    p = home() / "snapshots" / underlying.upper() / expiry.isoformat()
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_chain(chain: OptionChain) -> Path:
    ts = to_ist(chain.fetched_at).strftime("%Y%m%dT%H%M%S")
    path = _dir(chain.underlying, chain.expiry) / f"{ts}.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(chain.to_dict(), fh)
    return path


def list_snapshots(underlying: str, expiry: dt.date) -> list[Path]:
    return sorted(_dir(underlying, expiry).glob("*.json.gz"))


def load_chain(path: Path | str) -> OptionChain:
    path = Path(path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        return OptionChain.from_dict(json.load(fh))


def previous_chain(chain: OptionChain) -> OptionChain | None:
    """Most recent stored snapshot strictly older than `chain` (same underlying+expiry)."""
    cur = to_ist(chain.fetched_at).strftime("%Y%m%dT%H%M%S")
    older = [p for p in list_snapshots(chain.underlying, chain.expiry) if p.name.split(".")[0] < cur]
    return load_chain(older[-1]) if older else None


def iv_history_path(underlying: str) -> Path:
    p = home() / "iv_history"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{underlying.upper()}.csv"


def append_iv_history(underlying: str, rec: dict) -> None:
    path = iv_history_path(underlying)
    existing = {r["date"] for r in read_iv_history(underlying)}
    if rec["date"] in existing:
        return
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["date", "expiry", "atm_strike", "forward", "atm_iv"])
        if new:
            w.writeheader()
        w.writerow({k: rec[k] for k in w.fieldnames})


def read_iv_history(underlying: str) -> list[dict]:
    path = iv_history_path(underlying)
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as fh:
        return [{**r, "atm_iv": float(r["atm_iv"])} for r in csv.DictReader(fh)]


def export_parquet(chain: OptionChain, path: Path | str) -> Path:
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.Table.from_pylist(chain.rows)
    table = table.replace_schema_metadata({"meta": json.dumps({k: v for k, v in chain.to_dict().items()
                                                              if k != "rows"})})
    pq.write_table(table, path)
    return Path(path)
