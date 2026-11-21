"""Typed errors so skills can fail loudly and the agent can explain why."""


class NseFnoError(Exception):
    """Base class."""


class StaleDataError(NseFnoError):
    """Data is older than its `stale_after` timestamp; refuse to compute on it."""


class InstrumentNotFound(NseFnoError):
    """A symbol/strike/expiry could not be resolved against the instrument master."""


class AdapterError(NseFnoError):
    """A data source failed (network, auth, schema change)."""


class ComplianceBlock(NseFnoError):
    """An order-prep guardrail refused the action."""


class ConfigError(NseFnoError):
    """Missing or invalid configuration (credentials, paths)."""
