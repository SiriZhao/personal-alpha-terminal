"""ROUND 9: LLM failure isolation.

Any LLM failure -- API timeout, quota exceeded, malformed JSON, hallucination
detection, provider unavailable -- must degrade only the advisory layer and
never block the Classical Quant Core.  The guard always returns a structured
DEGRADED result so callers can continue.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class LLMGuardStatus(StrEnum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class LLMGuardResult:
    status: LLMGuardStatus
    reason: str | None = None
    quant_impact: str = "NONE"
    fallback: str = "CLASSICAL_CORE_CONTINUES"


class LLMGuard:
    """Fail-closed wrapper: LLM never blocks the classical quant core."""

    def __init__(self) -> None:
        self._failures: list[tuple[str, str]] = []

    def run(
        self,
        callable_fn: Callable[[], None],
        *,
        task_name: str,
    ) -> LLMGuardResult:
        """Execute an advisory callable; any failure yields a DEGRADED result."""
        try:
            callable_fn()
            return LLMGuardResult(LLMGuardStatus.OK)
        except Exception as error:  # noqa: BLE001 - isolation boundary
            category = _categorize(error)
            self._failures.append((task_name, category))
            return LLMGuardResult(
                LLMGuardStatus.DEGRADED,
                reason=f"{task_name} failed ({category})",
                quant_impact="NONE",
                fallback="CLASSICAL_CORE_CONTINUES",
            )

    @property
    def failures(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._failures)


def _categorize(error: Exception) -> str:
    from urllib.error import HTTPError, URLError

    message = str(error)
    lowered = message.lower()
    if isinstance(error, TimeoutError):
        return "TIMEOUT"
    if isinstance(error, (HTTPError, URLError)):
        if "quota" in lowered or "rate" in lowered or "429" in message:
            return "QUOTA_EXCEEDED"
        return "PROVIDER_UNAVAILABLE"
    if "json" in lowered or "schema" in lowered:
        return "MALFORMED_JSON"
    if "hallucin" in lowered or "grounding" in lowered:
        return "HALLUCINATION_RISK"
    return "PROVIDER_ERROR"
