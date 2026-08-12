"""Canary provider smoke test for ROUND 10.

Highly-liquid symbols (SPY, QQQ, AAPL, MSFT, NVDA, AMZN, META, GOOGL, AFRM)
determine whether a provider works at all.  If several canaries fail with a
structural classification at once, that is a provider incident, not per-ticker
quarantine.
"""
from __future__ import annotations

from dataclasses import dataclass

from personal_alpha_terminal.data.market_data.error_classification import (
    ProviderErrorClassification,
    StructuredProviderError,
)

CANARY_SYMBOLS: tuple[str, ...] = (
    "SPY",
    "QQQ",
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "META",
    "GOOGL",
    "AFRM",
)

INCIDENT_CLASSIFICATIONS = frozenset(
    {
        ProviderErrorClassification.SCHEMA_CHANGED,
        ProviderErrorClassification.BOT_CHALLENGE,
        ProviderErrorClassification.HTTP_BLOCKED,
        ProviderErrorClassification.AUTH_REQUIRED,
        ProviderErrorClassification.MALFORMED_RESPONSE,
        ProviderErrorClassification.DATA_QUALITY_FAILURE,
    }
)

PROVIDER_INCIDENT_THRESHOLD = 3


@dataclass(frozen=True, slots=True)
class CanaryResult:
    provider: str
    total: int
    success: int
    failures: tuple[StructuredProviderError, ...]
    incident: bool
    incident_reason: str | None

    def document(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "total": self.total,
            "success": self.success,
            "failures": [item.document() for item in self.failures],
            "incident": self.incident,
            "incident_reason": self.incident_reason,
        }


def classify_canary_outcome(
    provider: str,
    *,
    failures: tuple[StructuredProviderError, ...],
) -> CanaryResult:
    """Decide whether simultaneous canary failures indicate a provider incident."""
    incident_classifications = [
        item.classification
        for item in failures
        if item.classification in INCIDENT_CLASSIFICATIONS
    ]
    incident = len(incident_classifications) >= PROVIDER_INCIDENT_THRESHOLD
    reason = None
    if incident:
        from collections import Counter

        counts = Counter(item.value for item in incident_classifications)
        reason = "PROVIDER_INCIDENT: " + ", ".join(
            f"{name}={count}" for name, count in sorted(counts.items())
        )
    return CanaryResult(
        provider=provider,
        total=CANARY_SYMBOLS.__len__(),
        success=max(0, CANARY_SYMBOLS.__len__() - len(failures)),
        failures=failures,
        incident=incident,
        incident_reason=reason,
    )


def provider_incident_reason(
    failures: tuple[StructuredProviderError, ...],
) -> str | None:
    """Return the canary-derived incident reason, or None for symbol-level issues."""
    result = classify_canary_outcome(failures[0].provider, failures=failures)
    return result.incident_reason
