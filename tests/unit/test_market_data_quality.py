from dataclasses import replace
from datetime import date
from decimal import Decimal

from personal_alpha_terminal.core.data_timestamps import daily_bar_timestamps
from personal_alpha_terminal.data.market_data.quality import DataQualityChecker
from personal_alpha_terminal.data.market_data.schemas import PriceBar


def bar(
    trade_date: date,
    *,
    close: str = "10",
    high: str = "11",
    low: str = "9",
    volume: int | None = 100,
) -> PriceBar:
    timestamps = daily_bar_timestamps(trade_date, "A")
    return PriceBar(
        symbol="000001",
        market="A",
        date=trade_date,
        open=Decimal("10"),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=volume,
        event_time=timestamps.event_time,
        available_time=timestamps.available_time,
        ingested_time=timestamps.ingested_time,
    )


def test_quality_checker_deduplicates_and_keeps_last_row() -> None:
    checker = DataQualityChecker()
    trade_date = date(2026, 7, 29)

    result = checker.validate(
        [bar(trade_date, close="10"), bar(trade_date, close="10.5")],
        expected_symbol="000001",
        expected_market="A",
        start_date=trade_date,
        end_date=trade_date,
    )

    assert result.input_count == 2
    assert len(result.bars) == 1
    assert result.bars[0].close == Decimal("10.5")
    assert result.has_errors
    assert "duplicate_bar" in {issue.code for issue in result.issues}


def test_quality_checker_rejects_invalid_ohlc_and_negative_volume() -> None:
    checker = DataQualityChecker()
    trade_date = date(2026, 7, 29)

    result = checker.validate(
        [bar(trade_date, high="9.5"), bar(trade_date, volume=-1)],
        expected_symbol="000001",
        expected_market="A",
        start_date=trade_date,
        end_date=trade_date,
    )

    assert not result.bars
    assert result.rejected_count == 2
    assert {"invalid_high", "negative_volume"} <= {issue.code for issue in result.issues}


def test_quality_checker_allows_missing_index_volume_with_warning() -> None:
    checker = DataQualityChecker()
    trade_date = date(2026, 7, 29)

    result = checker.validate(
        [bar(trade_date, volume=None)],
        expected_symbol="000001",
        expected_market="A",
        start_date=trade_date,
        end_date=trade_date,
        require_volume=False,
    )

    assert len(result.bars) == 1
    assert "missing_volume" in {item.code for item in result.issues}


def test_quality_checker_blocks_missing_stock_volume() -> None:
    trade_date = date(2026, 7, 29)
    result = DataQualityChecker().validate(
        [bar(trade_date, volume=None)],
        expected_symbol="000001",
        expected_market="A",
        start_date=trade_date,
        end_date=trade_date,
    )

    assert result.has_errors
    assert "missing_volume" in {item.code for item in result.issues}


def test_quality_checker_rejects_wrong_instrument_and_date_range() -> None:
    checker = DataQualityChecker()
    requested_date = date(2026, 7, 29)
    wrong = bar(date(2026, 7, 30))
    wrong = PriceBar(
        symbol="OTHER",
        market=wrong.market,
        date=wrong.date,
        open=wrong.open,
        high=wrong.high,
        low=wrong.low,
        close=wrong.close,
        volume=wrong.volume,
        event_time=wrong.event_time,
        available_time=wrong.available_time,
        ingested_time=wrong.ingested_time,
    )

    result = checker.validate(
        [wrong],
        expected_symbol="000001",
        expected_market="A",
        start_date=requested_date,
        end_date=requested_date,
    )

    assert not result.bars
    assert result.rejected_count == 1
    assert {
        "instrument_mismatch",
        "date_out_of_range",
    } <= {issue.code for issue in result.issues}


def test_quality_checker_rejects_nonfinite_price() -> None:
    checker = DataQualityChecker()
    trade_date = date(2026, 7, 29)

    result = checker.validate(
        [bar(trade_date, close="NaN")],
        expected_symbol="000001",
        expected_market="A",
        start_date=trade_date,
        end_date=trade_date,
    )

    assert not result.bars
    assert result.issues[0].code == "invalid_price"


def test_quality_checker_rejects_invalid_adjusted_close() -> None:
    checker = DataQualityChecker()
    trade_date = date(2026, 7, 29)
    source = bar(trade_date)
    invalid = PriceBar(
        symbol=source.symbol,
        market=source.market,
        date=source.date,
        open=source.open,
        high=source.high,
        low=source.low,
        close=source.close,
        volume=source.volume,
        event_time=source.event_time,
        available_time=source.available_time,
        ingested_time=source.ingested_time,
        adjusted_close=Decimal("-1"),
    )

    result = checker.validate(
        [invalid],
        expected_symbol="000001",
        expected_market="A",
        start_date=trade_date,
        end_date=trade_date,
    )

    assert not result.bars
    assert result.issues[0].code == "invalid_adjusted_close"


def test_quality_checker_requires_adjustment_lineage() -> None:
    trade_date = date(2026, 7, 29)
    source = replace(bar(trade_date), adjusted_close=Decimal("10"))

    result = DataQualityChecker().validate(
        [source],
        expected_symbol="000001",
        expected_market="A",
        start_date=trade_date,
        end_date=trade_date,
    )

    assert result.has_errors
    assert "missing_adjustment_lineage" in {
        issue.code for issue in result.issues
    }


def test_quality_checker_blocks_unexplained_extreme_adjusted_return() -> None:
    first = bar(date(2026, 7, 29))
    second_source = replace(
        bar(date(2026, 7, 30), close="25", high="26", low="24"),
        open=Decimal("25"),
    )
    first = replace(
        first,
        adjusted_close=Decimal("10"),
        adjustment_method="test_provider_total_return",
    )
    second = replace(
        second_source,
        adjusted_close=Decimal("25"),
        adjustment_method="test_provider_total_return",
    )

    result = DataQualityChecker().validate(
        [first, second],
        expected_symbol="000001",
        expected_market="A",
        start_date=first.date,
        end_date=second.date,
    )

    assert result.has_errors
    assert "extreme_adjusted_return" in {issue.code for issue in result.issues}
