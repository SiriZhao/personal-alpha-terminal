class MarketDataError(Exception):
    """Base exception for the unified market-data layer."""


class UnsupportedMarketError(MarketDataError):
    """Raised when no provider is configured for a market."""


class ProviderDependencyError(MarketDataError):
    """Raised when an optional provider package is not installed."""


class ProviderRequestError(MarketDataError):
    """Raised when a provider request or response cannot be processed."""


class DataQualityError(MarketDataError):
    """Raised when a response contains data but none of it is safe to store."""


class InstrumentNotFoundError(MarketDataError):
    """Raised when an update targets an instrument absent from the stock master."""
