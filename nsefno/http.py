"""Small HTTP helper: one session, timeouts, exponential backoff, on-disk TTL cache."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import requests

from . import __version__
from .config import cache_dir
from .errors import AdapterError

# Plain product token: the NSE archive CDN stalls requests whose UA embeds a URL.
USER_AGENT = f"nsefno/{__version__}"
_session: requests.Session | None = None


def session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"})
    return _session


def _cache_path(url: str, suffix: str) -> Path:
    return cache_dir() / f"{hashlib.sha1(url.encode()).hexdigest()[:16]}{suffix}"


def get(url: str, *, ttl: float = 0, retries: int = 3, timeout: float = 20, binary: bool = False,
        sess: requests.Session | None = None, headers: dict | None = None):
    """GET with retry/backoff; if ttl>0, serve from disk cache when fresh."""
    suffix = ".bin" if binary else ".txt"
    path = _cache_path(url, suffix)
    if ttl > 0 and path.exists() and time.time() - path.stat().st_mtime < ttl:
        return path.read_bytes() if binary else path.read_text(encoding="utf-8")
    s = sess or session()
    last: Exception | None = None
    for attempt in range(retries):
        try:
            hdrs = {"Accept-Encoding": "identity", **(headers or {})} if binary else headers
            r = s.get(url, timeout=timeout, headers=hdrs)
            if r.status_code == 429 or r.status_code >= 500:
                raise AdapterError(f"HTTP {r.status_code} from {url}")
            r.raise_for_status()
            body = r.content if binary else r.text
            if ttl > 0:
                if binary:
                    path.write_bytes(body)
                else:
                    path.write_text(body, encoding="utf-8")
            return body
        except (requests.RequestException, AdapterError) as e:
            last = e
            time.sleep(min(8.0, 0.5 * 2 ** attempt))
    raise AdapterError(f"GET {url} failed after {retries} attempts: {last}")


def get_json(url: str, **kw):
    return json.loads(get(url, **kw))
