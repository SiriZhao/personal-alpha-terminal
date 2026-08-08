from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from personal_alpha_terminal.backtest.comparison import compare_with_us_benchmarks
from personal_alpha_terminal.backtest.engine import BacktestEngine
from personal_alpha_terminal.backtest.schemas import (
    BacktestBar,
    BacktestConfig,
    BacktestDataset,
    StrategyContext,
    TargetAllocation,
    UniversePoint,
)
from personal_alpha_terminal.backtest.walk_forward import (
    WalkForwardWindow,
    run_walk_forward,
)
from personal_alpha_terminal.core.data_timestamps import daily_bar_timestamps
from personal_alpha_terminal.data.market_data.contracts import AssetPriceRequest
from personal_alpha_terminal.data.market_data.exceptions import ProviderRequestError
from personal_alpha_terminal.data.market_data.normalization import PriceNormalizer
from personal_alpha_terminal.data.market_data_certification import (
    CertificationGateResult,
    CertificationStatus,
)
from personal_alpha_terminal.data.market_data_quality.schemas import (
    ListingAgeBucket,
    MarketSegment,
    SizeBucket,
    UniverseCandidate,
)
from personal_alpha_terminal.data.us_market import (
    LocalArchiveContract,
    LocalUSArchiveProvider,
    USProviderCatalog,
    USRealDataStatus,
    USUniverseObservation,
    USUniverseRules,
    build_us_research_universe,
    certify_us_research_data,
)
from personal_alpha_terminal.research import (
    ResearchDataAuthorization,
    ResearchDataEvidence,
    ResearchDataGate,
    ResearchDataRequest,
    ResearchPurpose,
)


@dataclass(frozen=True)
class OneShotStrategy:
    signal_date: date
    asset_id: int

    @property
    def name(self) -> str:
        return "phase2_one_shot"

    def generate_targets(self, context: StrategyContext) -> TargetAllocation | None:
        if context.signal_date != self.signal_date:
            return None
        return TargetAllocation({self.asset_id: 1.0}, ("fixture",))

    def audit_payload(self) -> dict[str, object]:
        return {"signal_date": self.signal_date.isoformat(), "asset_id": self.asset_id}


def _bar(day: date, asset_id: int = 1, close: float = 100.0) -> BacktestBar:
    timestamps = daily_bar_timestamps(day, "US")
    return BacktestBar(
        asset_id=asset_id,
        symbol=f"S{asset_id}",
        market="US",
        trade_date=day,
        open=close,
        high=close,
        low=close,
        close=close,
        adjusted_close=close,
        volume=1_000_000,
        source="certified_fixture",
        adjustment_method="point_in_time_total_return",
        provider="fixture",
        event_time=timestamps.event_time,
        available_time=timestamps.available_time,
        ingested_time=timestamps.ingested_time,
        open_tradable=True,
    )


def _dataset(*, timeline: tuple[UniversePoint, ...] = ()) -> BacktestDataset:
    sessions = (date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4))
    bars = tuple(_bar(day, asset_id) for day in sessions for asset_id in (1, 2))
    return BacktestDataset(
        market="US",
        bars=bars,
        data_sources=("fixture",),
        calendar=sessions,
        calendar_source="verified_fixture",
        universe_timeline=timeline,
    )


def _config() -> BacktestConfig:
    return BacktestConfig(
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 4),
        rebalance_frequency="daily",
        minimum_sessions=2,
        liquidity_lookback_sessions=2,
        minimum_liquidity_observations=1,
        maximum_adv_participation=1,
        require_pit_universe=True,
    )


def test_pit_universe_blocks_survivor_and_future_membership() -> None:
    point = UniversePoint(
        snapshot_id=1,
        as_of_date=date(2024, 1, 2),
        available_at=datetime(2024, 1, 2, 20, tzinfo=UTC),
        asset_ids=frozenset({1}),
        source="historical_membership_fixture",
    )
    with pytest.raises(ValueError, match="not in the point-in-time universe"):
        BacktestEngine().run(
            _dataset(timeline=(point,)),
            OneShotStrategy(date(2024, 1, 2), 2),
            _config(),
        )

    future = UniversePoint(
        snapshot_id=2,
        as_of_date=date(2024, 1, 2),
        available_at=datetime(2024, 1, 3, 20, tzinfo=UTC),
        asset_ids=frozenset({2}),
        source="future_membership_fixture",
    )
    with pytest.raises(ValueError, match="no snapshot was available"):
        BacktestEngine().run(
            _dataset(timeline=(future,)),
            OneShotStrategy(date(2024, 1, 2), 2),
            _config(),
        )


def test_local_archive_preserves_lineage_and_never_falls_back_asset_type(
    tmp_path: Path,
) -> None:
    root = tmp_path
    stock_dir = root / "stock"
    stock_dir.mkdir()
    (stock_dir / "AAPL.csv").write_text(
        "date,open,high,low,close,volume,event_time,available_time,ingested_time\n"
        "2024-01-02,100,102,99,101,1000,2024-01-02T21:00:00+00:00,"
        "2024-01-02T21:01:00+00:00,2024-01-02T22:00:00+00:00\n",
        encoding="utf-8",
    )
    provider = LocalUSArchiveProvider(
        root,
        provider_id="licensed_archive_a",
        contract=LocalArchiveContract(
            asset_type="stock",
            raw_volume_unit="share",
            volume_unit="share",
            price_type="unadjusted_ohlcv",
        ),
    )
    request = AssetPriceRequest("AAPL", "US", "stock", "USD", date(2024, 1, 2), date(2024, 1, 2))
    batch = provider.fetch_raw(request)
    normalized = PriceNormalizer().normalize(batch)
    assert normalized[0].available_time == datetime(2024, 1, 2, 21, 1, tzinfo=UTC)

    catalog = USProviderCatalog()
    catalog.register(provider, asset_type="stock", role="primary")
    with pytest.raises(ProviderRequestError, match="no explicit US verification provider"):
        catalog.fetch_pair(request)
    etf_request = AssetPriceRequest("SPY", "US", "etf", "USD", date(2024, 1, 2), date(2024, 1, 2))
    with pytest.raises(ProviderRequestError, match="typed capability"):
        provider.fetch_raw(etf_request)


def test_phase2_certification_remains_blocked_without_real_pit_evidence() -> None:
    gate = CertificationGateResult(
        status=CertificationStatus.BLOCKED,
        results=(),
        blockers=("Random sample requires 104, got 0.",),
        segment_counts={},
    )
    result = certify_us_research_data(
        gate,
        has_pit_universe_history=False,
        has_pit_corporate_actions=False,
        has_verified_calendar=True,
        has_delisting_and_symbol_history=False,
    )
    assert result.status is USRealDataStatus.BLOCKED
    assert not result.permits_quant_research
    assert "point-in-time universe history is incomplete" in result.blockers


def test_us_universe_filter_is_deterministic_and_fail_closed() -> None:
    candidate = UniverseCandidate(
        stock_id=1,
        symbol="AAPL",
        market="US",
        exchange="NASDAQ",
        segment=MarketSegment.NASDAQ,
        asset_type="stock",
        size_bucket=SizeBucket.LARGE,
        listing_age_bucket=ListingAgeBucket.ESTABLISHED,
        list_date=date(1980, 12, 12),
        delist_date=None,
        source="historical_membership",
        provider="fixture",
    )
    result = build_us_research_universe(
        (
            USUniverseObservation(candidate, 100, 50_000_000, 500, True),
            USUniverseObservation(
                candidate=replace(candidate, stock_id=2, symbol="LOWQ"),
                latest_price=1,
                average_dollar_volume=1_000,
                observed_sessions=20,
                data_quality_passed=False,
            ),
        ),
        USUniverseRules(),
    )
    assert [item.stock_id for item in result.members] == [1]
    assert set(result.exclusions[2]) == {
        "price_below_threshold_or_missing",
        "liquidity_below_threshold_or_missing",
        "insufficient_listing_history",
        "data_quality_not_passed",
    }


def _approved_authorization() -> ResearchDataAuthorization:
    request = ResearchDataRequest(
        purpose=ResearchPurpose.PORTFOLIO_DECISION,
        market="US",
        asset_type="stock",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 2),
        decision_time=datetime(2024, 1, 3, tzinfo=UTC),
        adjustment_mode="point_in_time_total_return",
        universe_snapshot_id="1",
    )
    evidence = ResearchDataEvidence(
        market="US",
        asset_type="stock",
        quality_status="passed",
        source="primary",
        provider="provider_a",
        source_ids=("a", "b"),
        latest_available_time=datetime(2024, 1, 2, 23, tzinfo=UTC),
        point_in_time_status="certified",
        adjustment_mode="point_in_time_total_return",
        universe_snapshot_id="1",
        universe_available_time=datetime(2024, 1, 2, 22, tzinfo=UTC),
        corporate_actions_complete=True,
        trading_calendar_complete=True,
        missing_rate=0,
        anomaly_rate=0,
        maximum_missing_rate=0.01,
        maximum_anomaly_rate=0.01,
        data_version="fixture-v1",
        allow_backtest=True,
        allow_display=True,
        allow_portfolio_decision=True,
        dual_source_verified=True,
    )
    return ResearchDataGate().authorize(request, evidence, evaluated_at=request.decision_time)


def test_benchmark_comparison_reports_missing_inception_without_backfill() -> None:
    result = BacktestEngine().run(
        _dataset(),
        OneShotStrategy(date(2024, 1, 2), 1),
        BacktestConfig(
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 4),
            rebalance_frequency="daily",
            minimum_sessions=2,
            liquidity_lookback_sessions=2,
            minimum_liquidity_observations=1,
            maximum_adv_participation=1,
        ),
    )
    levels = tuple((item.trade_date, 100.0 + index) for index, item in enumerate(result.points))
    comparison = compare_with_us_benchmarks(result, {"SPY": levels})
    assert [item.benchmark.name for item in comparison.benchmarks] == ["SPY"]
    assert comparison.missing_benchmarks == ("VOO", "QQQ", "QQQM", "RSP")


@dataclass
class LeakageProbeTrainer:
    latest_visible_date: date | None = None

    def fit(
        self,
        dataset: BacktestDataset,
        *,
        train_start: date,
        train_end: date,
        validation_start: date,
        validation_end: date,
    ) -> OneShotStrategy:
        del train_start, train_end, validation_start
        self.latest_visible_date = max(item.trade_date for item in dataset.bars)
        assert self.latest_visible_date == validation_end
        return OneShotStrategy(validation_end, 1)


def test_walk_forward_hides_locked_test_rows_from_trainer() -> None:
    sessions = (
        date(2024, 1, 2),
        date(2024, 1, 3),
        date(2024, 1, 4),
        date(2024, 1, 5),
        date(2024, 1, 8),
        date(2024, 1, 9),
        date(2024, 1, 10),
        date(2024, 1, 11),
        date(2024, 1, 12),
    )
    dataset = BacktestDataset(
        market="US",
        bars=tuple(_bar(item) for item in sessions),
        data_sources=("fixture",),
        calendar=sessions,
        calendar_source="verified_fixture",
    )
    trainer = LeakageProbeTrainer()
    results = run_walk_forward(
        dataset,
        BacktestConfig(
            start_date=sessions[0],
            end_date=sessions[-1],
            rebalance_frequency="daily",
            minimum_sessions=2,
            liquidity_lookback_sessions=2,
            minimum_liquidity_observations=1,
            maximum_adv_participation=1,
        ),
        (
            WalkForwardWindow(
                train_start=sessions[0],
                train_end=sessions[2],
                validation_start=sessions[3],
                validation_end=sessions[5],
                test_start=sessions[6],
                test_end=sessions[8],
            ),
        ),
        trainer,
    )
    assert trainer.latest_visible_date == sessions[5]
    assert results[0].test.start_date == sessions[6]
