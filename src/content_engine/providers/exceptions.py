"""Provider exception hierarchy.

Errors are translated at the provider boundary so that SDK-specific
exceptions never leak into the application/domain layer (ARCHITECTURE §18).
"""


class ProviderError(Exception):
    """Base exception for all provider errors."""

    def __init__(self, message: str, provider: str, model: str | None = None):
        self.provider = provider
        self.model = model
        super().__init__(message)


class ProviderConfigurationError(ProviderError):
    """Raised when the provider is misconfigured (missing key, invalid model, etc.)."""


class ProviderQuotaError(ProviderError):
    """Raised when a provider quota or rate-limit is exceeded."""


class ProviderAPIError(ProviderError):
    """Raised for general API or network failures."""
