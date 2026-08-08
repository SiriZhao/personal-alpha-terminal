from dataclasses import replace
from datetime import date
from decimal import Decimal

from personal_alpha_terminal.data.market_data_certification import (
    CertificationStatus,
    CorporateActionEvidence,
    InstrumentEvidence,
    RealMarketDataCertificationValidator,
    SourceBar,
    TradingStatusEvidence,
)
from personal_alpha_terminal.data.market_data_quality.schemas import MarketSegment


def bar(
    *,
    source: str,
    day: int,
    close: str,
    volume: str = "1000",
    adjusted: str | None = None,
) -> SourceBar:
    value = Decimal(close)
    return SourceBar(
        source=source,
        provider=f"{source}.daily",
        trade_date=date(2026, 7, day),
        open=value,
        high=value,
        low=value,
        close=value,
        volume=Decimal(volume),
        adjusted_close=Decimal(adjusted) if adjusted is not None else value,
    )


def evidence(*, bars: tuple[SourceBar, ...]) -> InstrumentEvidence:
    return InstrumentEvidence(
        symbol="TEST",
        market="US",
        segment=MarketSegment.NASDAQ,
        security_type="stock",
        expected_sessions=(date(2026, 7, 29), date(2026, 7, 30)),
        bars=bars,
        action_coverage_sources=("source_a", "source_b"),
    )


def test_cross_source_ohlcv_passes_with_rounding_tolerance() -> None:
    result = RealMarketDataCertificationValidator().validate_instrument(
        evidence(
            bars=(
                bar(source="source_a", day=29, close="100", volume="1000"),
                bar(source="source_a", day=30, close="101", volume="1100"),
                bar(source="source_b", day=29, close="100.01", volume="1001"),
                bar(source="source_b", day=30, close="101.01", volume="1099"),
            )
        )
    )

    assert result.status == CertificationStatus.PASSED
    assert result.matched_sessions == 2
    assert result.price_mismatches == 0
    assert result.volume_mismatches == 0


def test_missing_second_source_is_blocking() -> None:
    result = RealMarketDataCertificationValidator().validate_instrument(
        evidence(
            bars=(
                bar(source="source_a", day=29, close="100"),
                bar(source="source_a", day=30, close="101"),
            )
        )
    )

    assert result.status == CertificationStatus.BLOCKED
    assert "insufficient_price_sources" in {item.code for item in result.findings}


def test_missing_session_requires_two_source_suspension_evidence() -> None:
    base = evidence(
        bars=(
            bar(source="source_a", day=29, close="100"),
            bar(source="source_b", day=29, close="100"),
        )
    )
    one_source = replace(
        base,
        trading_status=(
            TradingStatusEvidence("status_a", "status_a.feed", date(2026, 7, 30), "suspended"),
        ),
    )
    two_sources = replace(
        base,
        trading_status=(
            TradingStatusEvidence("status_a", "status_a.feed", date(2026, 7, 30), "suspended"),
            TradingStatusEvidence("status_b", "status_b.feed", date(2026, 7, 30), "suspended"),
        ),
    )

    failed = RealMarketDataCertificationValidator().validate_instrument(one_source)
    passed = RealMarketDataCertificationValidator().validate_instrument(two_sources)

    assert "incomplete_source_history" in {item.code for item in failed.findings}
    assert passed.status == CertificationStatus.PASSED
    assert passed.has_suspension_case


def test_split_requires_two_matching_ledgers_and_adjusted_continuity() -> None:
    actions = (
        CorporateActionEvidence(
            "action_a", "action_a.feed", "split", date(2026, 7, 30), split_ratio=Decimal("2")
        ),
        CorporateActionEvidence(
            "action_b", "action_b.feed", "split", date(2026, 7, 30), split_ratio=Decimal("2")
        ),
    )
    item = InstrumentEvidence(
        symbol="SPLT",
        market="US",
        segment=MarketSegment.NASDAQ,
        security_type="stock",
        expected_sessions=(date(2026, 7, 29), date(2026, 7, 30)),
        bars=(
            bar(source="source_a", day=29, close="100", adjusted="50"),
            bar(source="source_a", day=30, close="50", adjusted="50"),
            bar(source="source_b", day=29, close="100", adjusted="50"),
            bar(source="source_b", day=30, close="50", adjusted="50"),
        ),
        action_coverage_sources=("action_a", "action_b"),
        actions=actions,
    )

    result = RealMarketDataCertificationValidator().validate_instrument(item)

    assert result.status == CertificationStatus.PASSED
    assert result.has_split_case


def test_gate_refuses_empty_or_under_quota_sample() -> None:
    result = RealMarketDataCertificationValidator().validate_gate(())

    assert result.status == CertificationStatus.BLOCKED
    assert any("Random sample requires 104" in item for item in result.blockers)
    assert any("hk_etf requires 5" in item for item in result.blockers)
