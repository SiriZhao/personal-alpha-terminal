"""Provider error classification for ROUND 10.

Every provider failure is classified explicitly instead of collapsing to
"All providers failed".  Each classification declares whether it is retryable,
and a structured error record carries provider, symbol, timestamp, attempt,
classification, retryable and a sanitized reason.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class ProviderErrorClassification(StrEnum):
    SYMBOL_NOT_FOUND = "SYMBOL_NOT_FOUND"
    NO_PRICE_HISTORY = "NO_PRICE_HISTORY"
    SCHEMA_CHANGED = "SCHEMA_CHANGED"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    TRANSIENT_NETWORK = "TRANSIENT_NETWORK"
    HTTP_BLOCKED = "HTTP_BLOCKED"
    BOT_CHALLENGE = "BOT_CHALLENGE"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    STALE_RESPONSE = "STALE_RESPONSE"
    PARTIAL_RESPONSE = "PARTIAL_RESPONSE"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    DATA_QUALITY_FAILURE = "DATA_QUALITY_FAILURE"
    UNKNOWN_PROVIDER_ERROR = "UNKNOWN_PROVIDER_ERROR"


# Only these are safe to retry with backoff.  Structural failures (schema,
# bot challenge, auth, symbol-not-found) must never be hammered.
RETRYABLE_CLASSIFICATIONS = frozenset(
    {
        ProviderErrorClassification.TIMEOUT,
        ProviderErrorClassification.TRANSIENT_NETWORK,
        ProviderErrorClassification.RATE_LIMITED,
        ProviderErrorClassification.PARTIAL_RESPONSE,
        ProviderErrorClassification.PROVIDER_UNAVAILABLE,
        # Unknown errors are genuinely ambiguous; a bounded retry is safer than
        # failing the whole refresh on a transient blip.
        ProviderErrorClassification.UNKNOWN_PROVIDER_ERROR,
    }
)

# These indicate a provider-level incident; tripping the circuit avoids
# repeating the request for thousands of tickers.
CIRCUIT_TRIPPING_CLASSIFICATIONS = frozenset(
    {
        ProviderErrorClassification.BOT_CHALLENGE,
        ProviderErrorClassification.SCHEMA_CHANGED,
        ProviderErrorClassification.HTTP_BLOCKED,
        ProviderErrorClassification.AUTH_REQUIRED,
        ProviderErrorClassification.RATE_LIMITED,
    }
)


@dataclass(frozen=True, slots=True)
class StructuredProviderError:
    provider: str
    symbol: str
    timestamp: datetime
    attempt: int
    classification: ProviderErrorClassification
    retryable: bool
    sanitized_reason: str

    def document(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "attempt": self.attempt,
            "classification": self.classification.value,
            "retryable": self.retryable,
            "sanitized_reason": self.sanitized_reason,
        }


def retryable(classification: ProviderErrorClassification) -> bool:
    return classification in RETRYABLE_CLASSIFICATIONS


def circuit_tripping(classification: ProviderErrorClassification) -> bool:
    return classification in CIRCUIT_TRIPPING_CLASSIFICATIONS


def classify_provider_error(
    provider: str,
    error: BaseException,
    *,
    symbol: str,
    attempt: int,
    content_hint: str | None = None,
    status_code: int | None = None,
    timestamp: datetime | None = None,
) -> StructuredProviderError:
    """Classify a provider error into the structured taxonomy."""
    message = sanitize_reason(str(error))
    lowered = message.lower()
    hint = (content_hint or "").lower()
    combined = lowered + " " + hint

    if status_code in (401, 403) or "unauthorized" in combined or "auth" in combined:
        classification = ProviderErrorClassification.AUTH_REQUIRED
    elif (
        status_code == 429
        or "rate" in combined
        or "quota" in combined
        or "too many requests" in combined
    ):
        classification = ProviderErrorClassification.RATE_LIMITED
    elif (
        "browser challenge" in combined
        or "javascript" in combined
        or "requires javascript" in combined
        or "cf-challenge" in combined
    ):
        classification = ProviderErrorClassification.BOT_CHALLENGE
    elif isinstance(error, TimeoutError) or "timeout" in combined or "timed out" in combined:
        classification = ProviderErrorClassification.TIMEOUT
    elif isinstance(error, ConnectionError) or "connection" in combined or "temporar" in combined:
        classification = ProviderErrorClassification.TRANSIENT_NETWORK
    elif "missing columns" in combined or "schema" in combined or "multiindex" in combined:
        classification = ProviderErrorClassification.SCHEMA_CHANGED
    elif "json" in combined or "decode" in combined or "parse" in combined:
        classification = ProviderErrorClassification.MALFORMED_RESPONSE
    elif "not found" in combined or "symbol" in combined and "no data" in combined:
        classification = ProviderErrorClassification.SYMBOL_NOT_FOUND
    elif "no rows" in combined or "no data" in combined or "no price history" in combined:
        classification = ProviderErrorClassification.NO_PRICE_HISTORY
    elif "stale" in combined:
        classification = ProviderErrorClassification.STALE_RESPONSE
    elif "partial" in combined:
        classification = ProviderErrorClassification.PARTIAL_RESPONSE
    elif "quality" in combined or "non-finite" in combined or "nan" in combined:
        classification = ProviderErrorClassification.DATA_QUALITY_FAILURE
    elif status_code in (403, 503) or "blocked" in combined or "html" in combined:
        classification = ProviderErrorClassification.HTTP_BLOCKED
    else:
        classification = ProviderErrorClassification.UNKNOWN_PROVIDER_ERROR

    return StructuredProviderError(
        provider=provider,
        symbol=symbol,
        timestamp=timestamp or datetime.now(UTC),
        attempt=attempt,
        classification=classification,
        retryable=retryable(classification),
        sanitized_reason=message,
    )


_URL_PATTERN = re.compile(r"https?://[^\s'\"]+", re.IGNORECASE)
_KEY_PATTERN = re.compile(
    r"(api[_-]?key|token|authorization|cookie|session|secret|password)=[^\s'\"]+",
    re.IGNORECASE,
)


def sanitize_reason(reason: str) -> str:
    """Strip URLs and credential-like tokens from a provider error message."""
    cleaned = _URL_PATTERN.sub("[URL]", reason)
    cleaned = _KEY_PATTERN.sub(r"\1=[REDACTED]", cleaned)
    return cleaned
