"""ROUND 5: candidate compression unit tests."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from personal_alpha_terminal.quant_engine.alpha import (
    AlphaDataQuality,
    AlphaSignal,
    AlphaValidationStatus,
)
from personal_alpha_terminal.quant_engine.candidates import compress_candidates

DECISION = datetime(2026, 8, 12, 21, tzinfo=UTC)


def _signal(symbol: str, alpha: float) -> AlphaSignal:
    return AlphaSignal(
        symbol=symbol,
        as_of=DECISION,
        signal_type="test",
        expected_excess_return=alpha,
        horizon=21,
        raw_signal=alpha,
        normalized_signal=alpha,
        confidence=0.5,
        confidence_calibrated=False,
        sample_size=100,
        statistical_strength=0.5,
        economic_strength=0.5,
        decay_half_life=21,
        valid_until=DECISION + timedelta(days=35),
        data_quality=AlphaDataQuality.VALID,
        pit_valid=True,
        validation_status=AlphaValidationStatus.RESEARCH,
        model_version="m:1",
        data_version="d1",
    )


def _many(seed: int = 0, count: int = 40) -> tuple[AlphaSignal, ...]:
    return tuple(
        _signal(f"S{index:03d}", (seed + index) / 1000.0) for index in range(count)
    )


def test_candidate_compression_records_each_step() -> None:
    signals = _many(count=40)
    result = compress_candidates(
        signals,
        candidate_max=10,
        candidate_min_alpha=0.0,
    )
    names = [step.name for step in result.steps]
    assert names == [
        "factor_ranked",
        "alpha_positive",
        "minimum_alpha",
        "liquidity",
        "risk_screening",
        "candidate_bound",
    ]
    assert result.steps[0].count == 40
    assert result.steps[-1].count == 10
    assert len(result.candidate_symbols) == 10
    assert result.document()["candidate_count"] == 10


def test_candidate_compression_orders_by_alpha_descending() -> None:
    signals = _many(count=20)
    result = compress_candidates(signals, candidate_max=5, candidate_min_alpha=0.0)
    by_alpha = {item.symbol: item.expected_excess_return for item in signals}
    expected = sorted(
        (item.symbol for item in signals),
        key=lambda symbol: (-by_alpha[symbol], symbol),
    )[:5]
    assert result.candidate_symbols == tuple(expected)


def test_candidate_compression_is_deterministic() -> None:
    signals = _many(count=30)
    first = compress_candidates(signals, candidate_max=8, candidate_min_alpha=0.0)
    second = compress_candidates(signals, candidate_max=8, candidate_min_alpha=0.0)
    assert first.candidate_symbols == second.candidate_symbols
    assert first.document() == second.document()


def test_candidate_compression_with_min_alpha_threshold() -> None:
    signals = _many(count=20)  # all positive
    result = compress_candidates(signals, candidate_max=100, candidate_min_alpha=0.015)
    # Only symbols with expected alpha >= 0.015 survive the minimum-alpha step.
    by_alpha = {item.symbol: item.expected_excess_return for item in signals}
    expected = tuple(
        sorted(
            (item.symbol for item in signals if item.expected_excess_return >= 0.015),
            key=lambda symbol: -by_alpha[symbol],
        )
    )
    assert result.candidate_symbols == expected


def test_candidate_compression_no_positive_alpha_yields_empty_pool() -> None:
    signals = tuple(_signal(f"Z{index:03d}", -0.01) for index in range(10))
    result = compress_candidates(signals, candidate_max=5, candidate_min_alpha=0.0)
    assert result.candidate_symbols == ()
    assert result.steps[1].rejected == 10
