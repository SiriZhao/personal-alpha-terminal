"""ROUND 10: error classification, circuit breaker, canary, health report tests."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from personal_alpha_terminal.data.market_data.canary import (
    classify_canary_outcome,
)
from personal_alpha_terminal.data.market_data.circuit_breaker import (
    ProviderCircuitBreaker,
    ProviderCircuitState,
)
from personal_alpha_terminal.data.market_data.error_classification import (
    ProviderErrorClassification,
    StructuredProviderError,
    classify_provider_error,
    retryable,
    sanitize_reason,
)
from personal_alpha_terminal.data.market_data.health_report import (
    CoverageSnapshot,
    MarketDataVerdict,
    coverage_verdict,
    summarize_provider_health,
)


def _err(classification, symbol="AFRM", provider="yahoo"):
    return StructuredProviderError(
        provider=provider,
        symbol=symbol,
        timestamp=datetime(2026, 8, 13, tzinfo=UTC),
        attempt=1,
        classification=classification,
        retryable=retryable(classification),
        sanitized_reason=classification.value,
    )


def test_error_classification_bot_challenge() -> None:
    structured = classify_provider_error(
        "stooq",
        RuntimeError("Stooq is unavailable: HTML/JavaScript browser challenge returned"),
        symbol="AFRM",
        attempt=1,
    )
    assert structured.classification is ProviderErrorClassification.BOT_CHALLENGE
    assert structured.retryable is False


def test_error_classification_rate_limit_and_timeout() -> None:
    rate = classify_provider_error(
        "yahoo", RuntimeError("Too Many Requests (429)"), symbol="SPY", attempt=1
    )
    assert rate.classification is ProviderErrorClassification.RATE_LIMITED
    assert rate.retryable is True
    timeout = classify_provider_error(
        "yahoo", TimeoutError("timed out"), symbol="SPY", attempt=1
    )
    assert timeout.classification is ProviderErrorClassification.TIMEOUT
    assert timeout.retryable is True


def test_error_classification_schema_changed() -> None:
    # ProviderErrorClassification is not an exception; the message path is used.
    structured2 = classify_provider_error(
        "yahoo",
        RuntimeError("Provider response is missing columns: ('Close', 'close')"),
        symbol="AFRM",
        attempt=1,
    )
    assert structured2.classification is ProviderErrorClassification.SCHEMA_CHANGED
    assert structured2.retryable is False


def test_sanitize_reason_redacts_urls_and_keys() -> None:
    cleaned = sanitize_reason(
        "failed at https://query1.finance.yahoo.com/v8?api_key=SECRET123 token=abc"
    )
    assert "SECRET123" not in cleaned
    assert "abc" not in cleaned
    assert "[URL]" in cleaned


def test_circuit_breaker_trips_on_repeated_bot_challenge(tmp_path: Path) -> None:
    breaker = ProviderCircuitBreaker(tmp_path, trip_threshold=3)
    for index in range(3):
        breaker.record_failure(
            "stooq",
            ProviderErrorClassification.BOT_CHALLENGE,
            symbol=f"T{index}",
        )
    assert breaker.state("stooq") is ProviderCircuitState.OPEN_CIRCUIT
    assert breaker.allows_request("stooq") is False


def test_circuit_breaker_recovers_after_probe_success(tmp_path: Path) -> None:
    breaker = ProviderCircuitBreaker(
        tmp_path, trip_threshold=2, probe_interval_seconds=0.0
    )
    breaker.record_failure("yahoo", ProviderErrorClassification.SCHEMA_CHANGED, symbol="A")
    breaker.record_failure("yahoo", ProviderErrorClassification.SCHEMA_CHANGED, symbol="B")
    assert breaker.state("yahoo") is ProviderCircuitState.OPEN_CIRCUIT
    now = datetime(2026, 8, 13, tzinfo=UTC)
    breaker.mark_recovering("yahoo", now=now)
    assert breaker.state("yahoo") is ProviderCircuitState.RECOVERING
    later = now + __import__("datetime").timedelta(seconds=1)
    assert breaker.allows_request("yahoo", now=later) is True
    breaker.record_success("yahoo", now=now + __import__("datetime").timedelta(seconds=1))
    assert breaker.state("yahoo") is ProviderCircuitState.HEALTHY


def test_canary_incident_vs_symbol_level() -> None:
    many = tuple(
        _err(ProviderErrorClassification.SCHEMA_CHANGED, symbol=s)
        for s in ("SPY", "AAPL", "MSFT")
    )
    result = classify_canary_outcome("yahoo", failures=many)
    assert result.incident is True
    assert "PROVIDER_INCIDENT" in (result.incident_reason or "")
    single = (_err(ProviderErrorClassification.NO_PRICE_HISTORY, symbol="AEXA"),)
    result2 = classify_canary_outcome("yahoo", failures=single)
    assert result2.incident is False


def test_coverage_collapse_fails_closed() -> None:
    verdict, reasons = coverage_verdict(
        CoverageSnapshot(factor_eligible=300, priced=400),
        baseline_factor_eligible=1959.0,
        collapse_ratio=0.5,
        minimum_factor_eligible=50,
    )
    assert verdict is MarketDataVerdict.BLOCKED_COVERAGE_COLLAPSE
    assert any("COLLAPSE" in reason for reason in reasons)
    ok_verdict, _ = coverage_verdict(
        CoverageSnapshot(factor_eligible=1900, priced=4000),
        baseline_factor_eligible=1959.0,
        collapse_ratio=0.5,
        minimum_factor_eligible=50,
    )
    assert ok_verdict is MarketDataVerdict.PASS


def test_provider_health_summary() -> None:
    rows = summarize_provider_health(
        outcomes_by_provider={
            "yahoo": [
                {"classification": "SUCCESS"},
                {"classification": "SUCCESS"},
                {"classification": "TIMEOUT"},
            ],
            "stooq": [
                {"classification": "BOT_CHALLENGE"},
            ],
        },
        circuits={},
        latencies_by_provider={"yahoo": [100.0, 200.0, 300.0]},
    )
    by_name = {row.provider: row for row in rows}
    assert by_name["yahoo"].requests == 3
    assert by_name["yahoo"].success == 2
    assert by_name["yahoo"].failure_rate == __import__("pytest").approx(1 / 3)
    assert by_name["yahoo"].latency_p50_ms == 200.0
    assert by_name["stooq"].bot_challenge == 1
