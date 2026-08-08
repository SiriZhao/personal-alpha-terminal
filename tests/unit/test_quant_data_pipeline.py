from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from personal_alpha_terminal.quant_engine.data import (
    DataPipeline,
    FundamentalObservation,
    LocalResearchCache,
    MacroObservation,
    MarketBar,
    MarketDataQuery,
)
from personal_alpha_terminal.research.data_gate import (
    ResearchDataEvidence,
    ResearchDataRequest,
    ResearchPurpose,
)


class FixtureProvider:
    provider_id = "fixture"

    def __init__(self, bars: tuple[MarketBar, ...]) -> None:
        self.bars = bars
        self.calls = 0

    def get_market_data(self, query: MarketDataQuery) -> tuple[MarketBar, ...]:
        self.calls += 1
        return self.bars

    def get_fundamentals(
        self, permanent_security_id: str, start_date: date, end_date: date
    ) -> tuple[FundamentalObservation, ...]:
        return ()

    def get_macro_data(
        self, series: tuple[str, ...], start_date: date, end_date: date
    ) -> tuple[MacroObservation, ...]:
        return ()


def _bar(*, available_time: datetime) -> MarketBar:
    return MarketBar(
        permanent_security_id="US-TEST-1",
        ticker="TEST",
        trade_date=date(2026, 1, 2),
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("99"),
        close=Decimal("101"),
        adjusted_close=Decimal("101"),
        volume=Decimal("1000000"),
        currency="USD",
        event_time=datetime(2026, 1, 2, 21, tzinfo=UTC),
        available_time=available_time,
        ingested_time=available_time + timedelta(minutes=1),
        source="fixture-source",
        provider="fixture",
        adjustment_mode="raw",
    )


def _request() -> ResearchDataRequest:
    return ResearchDataRequest(
        purpose=ResearchPurpose.DISPLAY,
        market="US",
        asset_type="stock",
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 2),
        decision_time=datetime(2026, 1, 3, tzinfo=UTC),
        adjustment_mode="raw",
        maximum_age=timedelta(days=10),
    )


def _evidence() -> ResearchDataEvidence:
    return ResearchDataEvidence(
        market="US",
        asset_type="stock",
        quality_status="passed",
        source="fixture-source",
        provider="fixture",
        source_ids=("fixture:TEST:2026-01-02",),
        latest_available_time=datetime(2026, 1, 2, 22, tzinfo=UTC),
        point_in_time_status="uncertified",
        adjustment_mode="raw",
        universe_snapshot_id=None,
        universe_available_time=None,
        corporate_actions_complete=False,
        trading_calendar_complete=True,
        missing_rate=0,
        anomaly_rate=0,
        maximum_missing_rate=0.01,
        maximum_anomaly_rate=0.01,
        data_version="fixture-v1",
        allow_backtest=False,
        allow_display=True,
        allow_portfolio_decision=False,
        dual_source_verified=False,
    )


def test_pipeline_gates_validates_and_caches_market_data(tmp_path: Path) -> None:
    provider = FixtureProvider((_bar(available_time=datetime(2026, 1, 2, 22, tzinfo=UTC)),))
    pipeline = DataPipeline(provider, LocalResearchCache(tmp_path / "quant-cache.db"))
    query = MarketDataQuery(
        permanent_security_id="US-TEST-1",
        ticker="TEST",
        market="US",
        asset_type="stock",
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 2),
        currency="USD",
        adjustment_mode="raw",
    )

    first = pipeline.load_market_data(query=query, request=_request(), evidence=_evidence())
    second = pipeline.load_market_data(query=query, request=_request(), evidence=_evidence())

    assert not first.from_cache
    assert second.from_cache
    assert provider.calls == 1
    assert second.bars == first.bars


def test_pipeline_rejects_future_available_bar(tmp_path: Path) -> None:
    provider = FixtureProvider((_bar(available_time=datetime(2026, 1, 4, tzinfo=UTC)),))
    pipeline = DataPipeline(provider, LocalResearchCache(tmp_path / "quant-cache.db"))
    query = MarketDataQuery(
        "US-TEST-1", "TEST", "US", "stock", date(2026, 1, 2), date(2026, 1, 2), "USD", "raw"
    )

    with pytest.raises(ValueError, match="future-available"):
        pipeline.load_market_data(query=query, request=_request(), evidence=_evidence())


def test_pipeline_revalidates_cached_lineage_on_every_request(tmp_path: Path) -> None:
    provider = FixtureProvider((_bar(available_time=datetime(2026, 1, 2, 22, tzinfo=UTC)),))
    pipeline = DataPipeline(provider, LocalResearchCache(tmp_path / "quant-cache.db"))
    query = MarketDataQuery(
        "US-TEST-1", "TEST", "US", "stock", date(2026, 1, 2), date(2026, 1, 2), "USD", "raw"
    )
    pipeline.load_market_data(query=query, request=_request(), evidence=_evidence())

    with pytest.raises(ValueError, match="source lineage"):
        pipeline.load_market_data(
            query=query,
            request=_request(),
            evidence=replace(_evidence(), source="different-certified-source"),
        )
