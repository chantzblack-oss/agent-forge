"""Provider exceptions — surface differentiated failure modes from concrete providers."""

from __future__ import annotations


class ProviderError(Exception):
    """Generic provider failure. Concrete providers wrap SDK errors in this."""


class ProviderTimeout(ProviderError):
    """Request exceeded the timeout window."""


class ProviderRateLimited(ProviderError):
    """Provider returned a rate-limit response. Caller may retry with backoff."""


class ProviderConfigError(ProviderError):
    """Provider was constructed without required configuration (e.g. API key)."""
