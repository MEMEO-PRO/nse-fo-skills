"""Paths and secrets. Secrets come ONLY from environment variables (or the OS keychain
via `keyring` if installed) - never from SKILL.md, YAML in the repo, or logs."""

from __future__ import annotations

import os
from pathlib import Path

from .errors import ConfigError


def home() -> Path:
    p = Path(os.environ.get("NSEFNO_HOME", Path.home() / ".nsefno"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir() -> Path:
    p = home() / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def secret(name: str, required: bool = True) -> str | None:
    val = os.environ.get(name)
    if not val:
        try:  # optional OS keychain
            import keyring  # type: ignore

            val = keyring.get_password("nsefno", name)
        except Exception:
            val = None
    if not val and required:
        raise ConfigError(f"Missing secret {name}. Set it as an environment variable (never in files).")
    return val


_SECRET_HINTS = ("ACCESS_TOKEN", "REQUEST_TOKEN", "SESSION_TOKEN", "AUTH", "SECRET", "API_KEY",
                 "APIKEY", "PASSWORD", "MPIN", "TOTP", "CONSUMER_KEY", "SID", "COOKIE")
_SAFE_KEYS = {"INSTRUMENT_TOKEN", "EXCHANGE_TOKEN", "TOKEN_ID"}


def _is_secret_key(k) -> bool:
    ku = str(k).upper().replace("-", "_")
    if ku in _SAFE_KEYS:
        return False
    return ku in {"TOKEN", "PIN", "KEY"} or any(h in ku for h in _SECRET_HINTS)


def redact(obj):
    """Recursively mask values whose key looks like a credential."""
    if isinstance(obj, dict):
        return {k: ("***" if _is_secret_key(k) else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj
