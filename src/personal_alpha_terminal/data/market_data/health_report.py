"""Daily provider health and data coverage report for ROUND 10.

A formal daily report records per-provider health (requests, success, partial,
no-data, rate-limited, timeout, schema error, bot challenge, failure rate,
latency p50/p95, circuit state) and per-layer coverage (directory, security
type, priced, fresh, history sufficient, liquidity, factor eligible,
quarantined, provider failed).  Coverage is compared to a recent baseline and
an abnormal collapse fails closed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from statistics import median
from typing import Any

from personal_alpha_terminal.data.market_data.circuit_breaker import (
    ProviderCircuitRecord,
)
from personal_alpha_terminal.data.market_data.error_classification import (
    ProviderErrorClassification,
)


class MarketDataVerdict(StrEnum):
    PASS = "PASS"
    PASS_DEGRADED = "PASS_DEGRADED"
    BLOCKED_PROVIDER_FAILURE = "BLOCKED_PROVIDER_FAILURE"
    BLOCKED_STALE_DATA = "BLOCKED_STALE_DATA"
    BLOCKED_COVERAGE_COLLAPSE = "BLOCKED_COVERAGE_COLLAPSE"


@dataclass(frozen=True, slots=True)
class ProviderHealthRow:
    provider: str
    health: str
    requests: int = 0
    success: int = 0
    partial: int = 0
    no_data: int = 0
    rate_limited: int = 0
    timeout: int = 0
    schema_error: int = 0
    bot_challenge: int = 0
    failure_rate: float | None = None
    latency_p50_ms: float | None = None
    latency_p95_ms: float | None = None
    circuit_state: str = "HEALTHY"

    def document(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "health": self.health,
            "requests": self.requests,
            "success": self.success,
            "partial": self.partial,
            "no_data": self.no_data,
            "rate_limited": self.rate_limited,
            "timeout": self.timeout,
            "schema_error": self.schema_error,
            "bot_challenge": self.bot_challenge,
            "failure_rate": self.failure_rate,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p95_ms": self.latency_p95_ms,
            "circuit_state": self.circuit_state,
        }


@dataclass(frozen=True, slots=True)
class CoverageSnapshot:
    directory_stocks: int = 0
    security_type_eligible: int = 0
    priced: int = 0
    fresh: int = 0
    history_sufficient: int = 0
    liquidity_eligible: int = 0
    factor_eligible: int = 0
    quarantined: int = 0
    provider_failed: int = 0

    def document(self) -> dict[str, Any]:
        return {
            "directory_stocks": self.directory_stocks,
            "security_type_eligible": self.security_type_eligible,
            "priced": self.priced,
            "fresh": self.fresh,
            "history_sufficient": self.history_sufficient,
            "liquidity_eligible": self.liquidity_eligible,
            "factor_eligible": self.factor_eligible,
            "quarantined": self.quarantined,
            "provider_failed": self.provider_failed,
        }


@dataclass(frozen=True, slots=True)
class DailyMarketDataHealth:
    as_of: datetime
    data_mode: str  # LIVE_REFRESH or CACHE_REPLAY
    expected_latest_trade_date: date | None
    actual_latest_trade_date: date | None
    primary_provider: str | None
    fallback_provider: str | None
    providers: tuple[ProviderHealthRow, ...] = ()
    coverage: CoverageSnapshot = field(default_factory=CoverageSnapshot)
    coverage_baseline: dict[str, float] | None = None
    verdict: MarketDataVerdict = MarketDataVerdict.PASS_DEGRADED
    reasons: tuple[str, ...] = ()

    def document(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "data_mode": self.data_mode,
            "expected_latest_trade_date": (
                self.expected_latest_trade_date.isoformat()
                if self.expected_latest_trade_date
                else None
            ),
            "actual_latest_trade_date": (
                self.actual_latest_trade_date.isoformat()
                if self.actual_latest_trade_date
                else None
            ),
            "primary_provider": self.primary_provider,
            "fallback_provider": self.fallback_provider,
            "providers": [item.document() for item in self.providers],
            "coverage": self.coverage.document(),
            "coverage_baseline": self.coverage_baseline,
            "verdict": self.verdict.value,
            "reasons": list(self.reasons),
        }


def coverage_verdict(
    coverage: CoverageSnapshot,
    *,
    baseline_factor_eligible: float | None,
    collapse_ratio: float,
    minimum_factor_eligible: int,
) -> tuple[MarketDataVerdict, tuple[str, ...]]:
    """Fail-closed coverage verdict versus recent baseline and absolute floor."""
    reasons: list[str] = []
    if coverage.factor_eligible < minimum_factor_eligible:
        reasons.append(
            f"FACTOR_ELIGIBLE_BELOW_MINIMUM:{coverage.factor_eligible}<{minimum_factor_eligible}"
        )
    if (
        baseline_factor_eligible is not None
        and coverage.factor_eligible < collapse_ratio * baseline_factor_eligible
    ):
        reasons.append(
            f"FACTOR_ELIGIBLE_COLLAPSE:{coverage.factor_eligible} < "
            f"{collapse_ratio} x baseline {baseline_factor_eligible:.0f}"
        )
    if coverage.provider_failed > 0 and coverage.provider_failed >= coverage.priced:
        reasons.append("PROVIDER_FAILURE_OVERTAKES_PRICED_COVERAGE")
    if reasons:
        verdict = MarketDataVerdict.BLOCKED_COVERAGE_COLLAPSE
    elif coverage.factor_eligible == 0:
        verdict = MarketDataVerdict.BLOCKED_PROVIDER_FAILURE
    else:
        verdict = MarketDataVerdict.PASS
    return verdict, tuple(reasons)


def summarize_provider_health(
    *,
    outcomes_by_provider: dict[str, list[dict[str, Any]]],
    circuits: dict[str, ProviderCircuitRecord],
    latencies_by_provider: dict[str, list[float]],
) -> tuple[ProviderHealthRow, ...]:
    """Aggregate per-provider outcome counters into health rows."""
    rows: list[ProviderHealthRow] = []
    for provider in sorted(set(outcomes_by_provider) | set(circuits)):
        outcomes = outcomes_by_provider.get(provider, [])
        counts: dict[str, int] = {}
        for item in outcomes:
            classification = str(item.get("classification", "UNKNOWN_PROVIDER_ERROR"))
            counts[classification] = counts.get(classification, 0) + 1
        success = counts.pop("SUCCESS", 0)
        requests = success + sum(counts.values())
        circuit = circuits.get(provider)
        latencies = latencies_by_provider.get(provider, [])
        rows.append(
            ProviderHealthRow(
                provider=provider,
                health=(
                    "HEALTHY"
                    if not circuit or circuit.state.value == "HEALTHY"
                    else circuit.state.value
                ),
                requests=requests,
                success=success,
                partial=counts.get(ProviderErrorClassification.PARTIAL_RESPONSE.value, 0),
                no_data=counts.get(ProviderErrorClassification.NO_PRICE_HISTORY.value, 0),
                rate_limited=counts.get(ProviderErrorClassification.RATE_LIMITED.value, 0),
                timeout=counts.get(ProviderErrorClassification.TIMEOUT.value, 0),
                schema_error=counts.get(ProviderErrorClassification.SCHEMA_CHANGED.value, 0),
                bot_challenge=counts.get(ProviderErrorClassification.BOT_CHALLENGE.value, 0),
                failure_rate=(1 - success / requests) if requests else None,
                latency_p50_ms=(median(latencies) if latencies else None),
                latency_p95_ms=_p95(latencies),
                circuit_state=(circuit.state.value if circuit else "HEALTHY"),
            )
        )
    return tuple(rows)


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(0.95 * len(ordered)) - 1))
    return ordered[index]
