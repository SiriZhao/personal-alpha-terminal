from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from personal_alpha_terminal.data.market_data_quality.history import (
    HistoricalQualityAnalyzer,
)
from personal_alpha_terminal.data.market_data_quality.schemas import (
    CalendarSession,
    CorporateActionRecord,
    CorporateActionType,
    HistoricalBar,
    ListingAgeBucket,
    MarketSegment,
    SizeBucket,
    UniverseCandidate,
)


def instrument() -> UniverseCandidate:
    return UniverseCandidate(
        stock_id=1,
        symbol="000001",
        market="A",
        exchange="SZSE",
        segment=MarketSegment.SZSE_MAIN,
        asset_type="stock",
        size_bucket=SizeBucket.LARGE,
        listing_age_bucket=ListingAgeBucket.ESTABLISHED,
        list_date=date(1991, 4, 3),
        delist_date=None,
    )


def session(day: date) -> CalendarSession:
    timestamp = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    return CalendarSession(
        exchange="SZSE",
        session_date=day,
        is_open=True,
        open_time=timestamp,
        close_time=timestamp.replace(hour=7),
        timezone="Asia/Shanghai",
        source="szse",
        provider="official_calendar_import",
        available_time=timestamp,
        ingested_time=timestamp,
    )


def bar(day: date, close: str, adjusted: str) -> HistoricalBar:
    timestamp = datetime.combine(day, datetime.min.time(), tzinfo=UTC)
    return HistoricalBar(
        trade_date=day,
        close=Decimal(close),
        adjusted_close=Decimal(adjusted),
        source="akshare",
        provider="akshare.stock_zh_a_hist.eastmoney",
        event_time=timestamp,
        available_time=timestamp,
        ingested_time=timestamp,
    )


def test_history_analyzer_blocks_missing_exchange_session() -> None:
    first = date(2026, 7, 29)
    second = date(2026, 7, 30)

    result = HistoricalQualityAnalyzer().analyze(
        instrument=instrument(),
        bars=[bar(first, "10", "10")],
        sessions=[session(first), session(second)],
        corporate_actions=[],
        start_date=first,
        end_date=second,
    )

    assert not result.passed
    assert result.missing_sessions == 1
    assert result.missing_rate == 0.5
    assert "unclassified_missing_session" in {
        issue.code for issue in result.issues
    }


def test_matching_split_explains_raw_jump_and_adjusted_series_stays_continuous() -> None:
    first = date(2026, 7, 29)
    second = date(2026, 7, 30)
    timestamp = datetime(2026, 7, 29, tzinfo=UTC)
    action = CorporateActionRecord(
        stock_id=1,
        action_type=CorporateActionType.SPLIT,
        effective_date=second,
        announcement_date=first,
        available_date=first,
        event_time=timestamp,
        available_time=timestamp,
        ingested_time=timestamp,
        source="szse",
        provider="official_action_import",
        split_ratio=Decimal("2"),
    )

    result = HistoricalQualityAnalyzer().analyze(
        instrument=instrument(),
        bars=[bar(first, "100", "50"), bar(second, "50", "50")],
        sessions=[session(first), session(second)],
        corporate_actions=[action],
        start_date=first,
        end_date=second,
    )

    assert result.passed
    assert result.missing_rate == 0
    assert result.anomaly_rate == 0


def test_cash_dividend_label_cannot_mask_split_sized_price_jump() -> None:
    first = date(2026, 7, 29)
    second = date(2026, 7, 30)
    timestamp = datetime(2026, 7, 29, tzinfo=UTC)
    action = CorporateActionRecord(
        stock_id=1,
        action_type=CorporateActionType.CASH_DIVIDEND,
        effective_date=second,
        announcement_date=first,
        available_date=first,
        event_time=timestamp,
        available_time=timestamp,
        ingested_time=timestamp,
        source="szse",
        provider="official_action_import",
        cash_amount=Decimal("0.1"),
        currency="CNY",
    )

    result = HistoricalQualityAnalyzer().analyze(
        instrument=instrument(),
        bars=[bar(first, "100", "50"), bar(second, "50", "50")],
        sessions=[session(first), session(second)],
        corporate_actions=[action],
        start_date=first,
        end_date=second,
    )

    assert not result.passed
    assert "unexplained_raw_price_jump" in {
        issue.code for issue in result.issues
    }


def test_history_analyzer_rejects_calendar_with_unreported_closed_day() -> None:
    friday = date(2026, 7, 31)
    monday = date(2026, 8, 3)
    sessions = [session(friday), session(monday)]

    result = HistoricalQualityAnalyzer().analyze(
        instrument=instrument(),
        bars=[bar(friday, "10", "10"), bar(monday, "10.1", "10.1")],
        sessions=sessions,
        corporate_actions=[],
        start_date=friday,
        end_date=monday,
    )

    assert not result.passed
    assert {
        issue.trade_date
        for issue in result.issues
        if issue.code == "incomplete_calendar_coverage"
    } == {friday + timedelta(days=1)}
