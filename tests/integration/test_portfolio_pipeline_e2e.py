"""End-to-end portfolio pipeline tests (Part 2, requirement 10).

Test A drives the real DailyQuantOrchestrator against an isolated SQLite
database with a certified 18-symbol universe and NO portfolio.  It proves the
production no-portfolio contract: DATA/PIT/FEATURE/FACTOR/SIGNAL PASS, PORTFOLIO
REQUIRED, RISK/DECISION/EXECUTION blocked, zero BUY/SELL, zero future rows.

Test B seeds an isolated TEST portfolio plus the exact-fingerprint governance
artifacts (model approval, portfolio validation, probability calibration) into a
temporary database and artifact directory, then drives ProductionDailyWorkflow
through the complete chain: Portfolio -> Construction -> Risk -> Stress ->
Decision -> manual Execution Plan -> persistence.  A negative variant proves the
chain still fails closed when the approval artifacts are absent.

Nothing here touches the production database; all state lives in memory or in
pytest-managed temporary directories and is discarded afterwards.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from personal_alpha_terminal.application.app_service import ApplicationService
from personal_alpha_terminal.application.data_service import DataService
from personal_alpha_terminal.application.operational_readiness import (
    DEFAULT_ALLOWED_RESEARCH_STATES,
    OperationalPolicyDecision,
    OperationalPolicyStore,
    build_operational_identity,
    issue_operational_policy,
)
from personal_alpha_terminal.application.quant_daily_service import (
    ProductionDailyWorkflow,
)
from personal_alpha_terminal.application.universe import MINIMUM_US_RESEARCH_UNIVERSE
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
from personal_alpha_terminal.data.database import build_engine, build_session_factory
from personal_alpha_terminal.data.us_market.broad_universe import (
    parse_symbol_directories,
    write_directory_snapshot,
)
from personal_alpha_terminal.data.us_market.pit_total_return import (
    PITRawBar,
    PointInTimeTotalReturnBuilder,
)
from personal_alpha_terminal.data.us_market.repository import USPointInTimeRepository
from personal_alpha_terminal.models import (
    Base,
    DataSnapshotManifest,
    DelistingHistory,
    ExchangeSession,
    Industry,
    MarketDataQualityRun,
    MarketUniverseMember,
    MarketUniverseSnapshot,
    Portfolio,
    PortfolioPosition,
    Price,
    QuantDecisionRun,
    ResearchDataCertification,
    Stock,
    TradingStatus,
    UniverseDefinition,
    UniverseMembership,
)
from personal_alpha_terminal.quant_engine.model_registry import (
    ModelPromotionEvidence,
    ModelRegistryService,
)
from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
    USAdaptiveAlphaCoreV1,
)
from personal_alpha_terminal.quant_engine.validation_artifacts import (
    PortfolioValidationIdentity,
    ProbabilityCalibrationIdentity,
    ValidationArtifactRegistry,
)

# ---------------------------------------------------------------------------
# Deterministic fixture constants.  Test A reproduces the real weekend run:
# decision on Sunday 2026-08-09, analysis session 2026-08-07 (latest completed
# XNYS session), trade date 2026-08-10.  No weekend bars are ever fabricated.
# ---------------------------------------------------------------------------
TEST_A_DECISION_TIME = datetime(2026, 8, 9, 14, 0, tzinfo=UTC)
TEST_A_ANALYSIS_DATE = date(2026, 8, 7)
TEST_A_BAR_COUNT = 270

# Test B uses a future decision horizon so that governance artifacts created at
# real wall-clock time are unambiguously available at decision time (the same
# convention as the quant-critical vertical contract suite).
TEST_B_DECISION_TIME = datetime(2027, 8, 6, 22, 0, tzinfo=UTC)
TEST_B_BAR_COUNT = 270


def _bar_dates(end: date, periods: int) -> list[date]:
    return [item.date() for item in pd.bdate_range(end=end, periods=periods)]


def _write_test_b_current_directory(
    config: EffectiveRuntimeConfig,
    *,
    decision_time: datetime,
) -> None:
    """Seed explicit current-directory provenance for the isolated TEST fixture."""

    source_date = decision_time.date().strftime("%m%d%Y")
    nasdaq_rows = [
        "Symbol|Security Name|Market Category|Test Issue|Financial Status|"
        "Round Lot Size|ETF|NextShares"
    ]
    other_rows = [
        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|"
        "Test Issue|NASDAQ Symbol"
    ]
    for asset in MINIMUM_US_RESEARCH_UNIVERSE:
        if asset.asset_type != "stock":
            continue
        if asset.exchange == "XNAS":
            nasdaq_rows.append(
                f"{asset.ticker}|{asset.name} Common Stock|Q|N|N|100|N|N"
            )
        elif asset.exchange in {"XNYS", "XASE"}:
            exchange = "N" if asset.exchange == "XNYS" else "A"
            other_rows.append(
                f"{asset.ticker}|{asset.name} Common Stock|{exchange}|"
                f"{asset.ticker}|N|100|N|{asset.ticker}"
            )
    nasdaq_rows.append(f"File Creation Time: {source_date}1200|||||||")
    other_rows.append(f"File Creation Time: {source_date}1200|||||||")
    snapshot = parse_symbol_directories(
        "\n".join(nasdaq_rows),
        "\n".join(other_rows),
        retrieved_at=decision_time - timedelta(hours=1),
    )
    write_directory_snapshot(snapshot, config.cache_dir / "us-current-directory")


def _deterministic_close(session_index: int, symbol_index: int) -> float:
    """Smooth, strictly positive, upward-drifting price path."""

    return 100.0 + 5.0 * symbol_index + session_index * (
        0.02 + 0.015 * symbol_index
    ) + 2.0 * float(np.sin(session_index / (10.0 + symbol_index)))


def _risk_aligned_close(session_index: int, symbol_index: int) -> float:
    """Cross-sectionally distinct paths with beta below the unchanged live cap."""

    base = 100.0 + 5.0 * symbol_index
    loading = 1.0 if symbol_index == 0 else 0.74 + 0.01 * (symbol_index % 5)
    market_cycle = loading * 0.02 * float(np.sin(session_index / 12.0))
    idiosyncratic = 0.002 * float(np.sin(session_index / (7.0 + symbol_index % 4)))
    drift = 0.0002 * (1.0 + 0.02 * symbol_index) * session_index
    return base * (1.0 + drift + market_cycle + idiosyncratic)


def _seed_securities(session: Session) -> dict[str, Stock]:
    industries: dict[str, Industry] = {}
    industry_codes = {
        "Broad Market ETF": "FIX_BME",
        "Treasury ETF": "FIX_TSY",
        "Technology": "FIX_TECH",
        "Communication": "FIX_COMM",
        "Diversified I": "FIX_DIV1",
        "Diversified II": "FIX_DIV2",
    }
    for name, code in industry_codes.items():
        industry = Industry(taxonomy="FIXTURE", code=code, name=name)
        session.add(industry)
        industries[name] = industry
    session.flush()
    # Every sector group must contain at least two members so that the frozen
    # within-sector neutralization contract validates in the isolated fixture.
    sector_by_symbol = {
        "SPY": "Broad Market ETF",
        "QQQ": "Broad Market ETF",
        "IWD": "Broad Market ETF",
        "IWM": "Broad Market ETF",
        "VTI": "Broad Market ETF",
        "TLT": "Treasury ETF",
        "SGOV": "Treasury ETF",
        "GLD": "Diversified I",
        "^VIX": "Broad Market ETF",
        "AAPL": "Technology",
        "MSFT": "Technology",
        "NVDA": "Technology",
        "AMZN": "Communication",
        "GOOGL": "Communication",
        "META": "Communication",
        # Keep the equity-only cross-section independently neutralizable now that
        # GLD is correctly excluded from stock factor ranking.
        "JPM": "Diversified II",
        "JNJ": "Diversified II",
        "XOM": "Diversified II",
    }
    stocks: dict[str, Stock] = {}
    now = datetime.now(UTC)
    for asset in MINIMUM_US_RESEARCH_UNIVERSE:
        stock = Stock(
            canonical_code=asset.canonical_code,
            symbol=asset.ticker,
            name=asset.name,
            market="US",
            exchange=asset.exchange,
            asset_type=asset.asset_type,
            currency="USD",
            timezone="America/New_York",
            list_date=date(2015, 1, 2),
            source="fixture-universe",
            provider="isolated-test",
            available_time=now - timedelta(days=400),
            ingested_time=now - timedelta(days=400),
            industry_id=industries[sector_by_symbol[asset.ticker]].id,
        )
        session.add(stock)
        stocks[asset.ticker] = stock
    session.flush()
    return stocks


def _seed_prices(
    session: Session,
    stocks: dict[str, Stock],
    *,
    end_date: date,
    periods: int,
    decision_time: datetime,
    close_function: Callable[[int, int], float] = _deterministic_close,
) -> dict[str, list[date]]:
    dates = _bar_dates(end_date, periods)
    for symbol_index, asset in enumerate(MINIMUM_US_RESEARCH_UNIVERSE):
        stock = stocks[asset.ticker]
        is_index = asset.asset_type == "index"
        for session_index, trade_date in enumerate(dates):
            close = close_function(session_index, symbol_index)
            available = datetime.combine(
                trade_date, datetime.min.time(), tzinfo=UTC
            ) + timedelta(hours=20, minutes=30)
            assert available <= decision_time
            session.add(
                Price(
                    stock_id=stock.id,
                    trade_date=trade_date,
                    open=Decimal(str(round(close * 0.999, 6))),
                    high=Decimal(str(round(close * 1.001, 6))),
                    low=Decimal(str(round(close * 0.998, 6))),
                    close=Decimal(str(round(close, 6))),
                    volume=None if is_index else 1_000_000 + symbol_index * 1_000,
                    asset_type=asset.asset_type,
                    volume_unit="none" if is_index else "share",
                    price_type=(
                        "index_level_ohlcv" if is_index else "unadjusted_ohlcv"
                    ),
                    source="fixture_primary",
                    provider="isolated-test",
                    event_time=available - timedelta(minutes=30),
                    available_time=available,
                )
            )
    session.flush()
    return {asset.ticker: dates for asset in MINIMUM_US_RESEARCH_UNIVERSE}


def _seed_pit_series(
    session: Session,
    stocks: dict[str, Stock],
    *,
    dates: list[date],
    decision_time: datetime,
    symbols: tuple[str, ...],
    close_function: Callable[[int, int], float] = _deterministic_close,
) -> None:
    repository = USPointInTimeRepository(session)
    builder = PointInTimeTotalReturnBuilder()
    for symbol_index, asset in enumerate(MINIMUM_US_RESEARCH_UNIVERSE):
        if asset.ticker not in symbols:
            continue
        bars = tuple(
            PITRawBar(
                permanent_security_id=asset.canonical_code,
                trade_date=trade_date,
                close=close_function(index, symbol_index),
                source_id=f"fixture:{asset.canonical_code}:{trade_date.isoformat()}",
                available_at=datetime.combine(
                    trade_date, datetime.min.time(), tzinfo=UTC
                )
                + timedelta(hours=20, minutes=30),
            )
            for index, trade_date in enumerate(dates)
        )
        series = builder.build(bars=bars, actions=(), as_of_time=decision_time)
        repository.persist_total_return_series(
            series,
            stock_id=stocks[asset.ticker].id,
            corporate_action_ledger_hash="fixture-ledger-hash",
            certification_status="CERTIFIED",
        )
    session.flush()


def _seed_universe_snapshot_members(
    session: Session, stocks: dict[str, Stock], *, analysis_date: date
) -> MarketUniverseSnapshot:
    """Snapshot without definition_id (MarketUniverseMember path, Test A)."""

    now = datetime.now(UTC)
    snapshot = MarketUniverseSnapshot(
        market="US",
        as_of_date=analysis_date,
        source="console_minimum_universe",
        provider="isolated-test",
        available_time=now - timedelta(days=30),
        ingested_time=now - timedelta(days=30),
        version_id="fixture-universe-v1",
        data_version="fixture-data-version-a",
        content_hash="fixture-content-hash-a",
        certification_status="CERTIFIED",
    )
    session.add(snapshot)
    session.flush()
    for asset in MINIMUM_US_RESEARCH_UNIVERSE:
        session.add(
            MarketUniverseMember(
                snapshot_id=snapshot.id,
                stock_id=stocks[asset.ticker].id,
                segment="fixture",
                size_bucket="unknown",
                listing_age_bucket="unknown",
                reason="isolated test universe",
            )
        )
    session.flush()
    return snapshot


def _seed_universe_with_memberships(
    session: Session,
    stocks: dict[str, Stock],
    *,
    analysis_date: date,
    data_version: str,
    decision_time: datetime,
) -> MarketUniverseSnapshot:
    """Snapshot with definition_id (UniverseMembership path with market caps)."""

    definition = UniverseDefinition(
        definition_id="fixture-defined-universe",
        version="1",
        market="US",
        name="Isolated test universe",
        rules={"scope": "isolated_test"},
        source="fixture",
        provider="isolated-test",
        capability_status="CERTIFIED",
    )
    session.add(definition)
    session.flush()
    available = decision_time - timedelta(days=30)
    snapshot = MarketUniverseSnapshot(
        market="US",
        as_of_date=analysis_date,
        source="console_minimum_universe",
        provider="isolated-test",
        available_time=available,
        ingested_time=available,
        definition_id=definition.id,
        version_id="fixture-universe-v2",
        data_version=data_version,
        content_hash="fixture-content-hash-b",
        certification_status="CERTIFIED",
    )
    session.add(snapshot)
    session.flush()
    for index, asset in enumerate(MINIMUM_US_RESEARCH_UNIVERSE):
        session.add(
            UniverseMembership(
                definition_id=definition.id,
                stock_id=stocks[asset.ticker].id,
                effective_from=date(2020, 1, 2),
                effective_to=None,
                available_time=available,
                ingested_time=available,
                inclusion_reason="isolated test member",
                market_cap=Decimal(str((index + 1) * 10_000_000_000)),
                revision_id="fixture-revision-1",
                source="fixture",
                provider="isolated-test",
            )
        )
    session.flush()
    return snapshot


def _seed_certification(
    session: Session,
    *,
    snapshot: MarketUniverseSnapshot,
    decision_time: datetime,
    data_version: str,
    allow_portfolio_decision: bool,
) -> None:
    quality = MarketDataQualityRun(
        history_start=date(2025, 1, 2),
        history_end=decision_time.date(),
        random_seed=0,
        minimum_sample_size=18,
        sample_count=18,
        status="passed",
        source_snapshot_ids=[snapshot.id],
        aggregate_metrics={
            "source": "fixture_selected_source",
            "provider": "isolated-test",
            "latest_available_time": (decision_time - timedelta(hours=1)).isoformat(),
            "missing_rate": 0.0,
            "anomaly_rate": 0.0,
            "maximum_missing_rate": 0.01,
            "maximum_anomaly_rate": 0.005,
            "us_point_in_time_status": "certified",
            "us_adjustment_mode": "point_in_time_total_return",
            "us_corporate_actions_certified": True,
            "us_trading_calendar_certified": True,
            "us_dual_source_verified": False,
            "source_conflict": False,
            "data_version": data_version,
            "allow_display": True,
            "allow_backtest": False,
            "allow_portfolio_decision": allow_portfolio_decision,
        },
        blockers=[],
    )
    session.add(quality)
    session.flush()
    session.add(
        ResearchDataCertification(
            market="US",
            asset_type="mixed",
            data_version=data_version,
            status="APPROVED",
            evidence_fingerprint="fixture-evidence-fingerprint",
            quality_run_id=quality.id,
            universe_snapshot_id=snapshot.id,
            allow_display=True,
            allow_backtest=False,
            allow_portfolio_decision=allow_portfolio_decision,
            valid_from=decision_time - timedelta(days=1),
            valid_until=None,
            blockers=[],
            warnings=[],
        )
    )
    session.flush()


# ---------------------------------------------------------------------------
# Test A: production orchestrator, certified data, NO portfolio.
# ---------------------------------------------------------------------------


def _manifest_document(analysis_date: date, decision_time: datetime) -> dict:
    return {
        "bar_coverage": [
            {
                "symbol": asset.ticker,
                "required": asset.required,
                "expected": TEST_A_BAR_COUNT,
                "matched": TEST_A_BAR_COUNT,
                "missing": 0,
                "unexpected": 0,
                "duplicate": 0,
                "rejected": 0,
                "valid": TEST_A_BAR_COUNT,
                "latest": analysis_date.isoformat(),
                "missing_dates": [],
                "unexpected_dates": [],
            }
            for asset in MINIMUM_US_RESEARCH_UNIVERSE
        ],
        "corporate_action_status": "PASS",
        "corporate_action_symbol_results": [
            {"symbol": asset.ticker, "status": "PASS", "events_found": 0, "errors": []}
            for asset in MINIMUM_US_RESEARCH_UNIVERSE
        ],
        "provider_reconciliation_symbol_results": [],
        "pit_data_cutoff": (decision_time - timedelta(hours=2)).isoformat(),
        "latest_completed_session": analysis_date.isoformat(),
        "decision_timestamp_convention": (
            "daily close inputs available after provider publication; "
            "next-session manual execution"
        ),
        "evidence": {
            "corporate_actions": "corporate_action_certificate.json",
            "certification_matrix": "data_certification_matrix.json",
        },
    }


def test_a_production_no_portfolio_blocks_trading_without_signals(
    tmp_path: Path,
) -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)

    settings = Settings(
        _env_file=None,
        database_url="sqlite://",
        console_initial_history_days=120,
    )

    manifest_dir = tmp_path / "data-snapshots" / "FIXTURE-SNAPSHOT"
    manifest_dir.mkdir(parents=True)
    manifest_path = manifest_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            _manifest_document(TEST_A_ANALYSIS_DATE, TEST_A_DECISION_TIME),
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    with factory.begin() as session:
        stocks = _seed_securities(session)
        _seed_prices(
            session,
            stocks,
            end_date=TEST_A_ANALYSIS_DATE,
            periods=TEST_A_BAR_COUNT,
            decision_time=TEST_A_DECISION_TIME,
        )
        pit_dates = _bar_dates(TEST_A_ANALYSIS_DATE, TEST_A_BAR_COUNT)
        research_symbols = tuple(
            asset.ticker
            for asset in MINIMUM_US_RESEARCH_UNIVERSE
            if asset.asset_type in {"stock", "etf"}
        )
        _seed_pit_series(
            session,
            stocks,
            dates=pit_dates,
            decision_time=TEST_A_DECISION_TIME,
            symbols=research_symbols,
        )
        snapshot = _seed_universe_snapshot_members(
            session, stocks, analysis_date=TEST_A_ANALYSIS_DATE
        )
        _seed_certification(
            session,
            snapshot=snapshot,
            decision_time=TEST_A_DECISION_TIME,
            data_version="fixture-data-version-a",
            allow_portfolio_decision=True,
        )
        session.add(
            DataSnapshotManifest(
                snapshot_id="FIXTURE-SNAPSHOT",
                content_hash="fixture-manifest-hash",
                immutable_reference=str(manifest_path),
                provider_name="fixture_primary",
                provider_adapter="isolated-test",
                requested_at=TEST_A_DECISION_TIME - timedelta(hours=3),
                completed_at=TEST_A_DECISION_TIME - timedelta(hours=2),
                market="US",
                asset_type="mixed",
                symbols=[asset.ticker for asset in MINIMUM_US_RESEARCH_UNIVERSE],
                required_symbols=sorted(
                    asset.ticker
                    for asset in MINIMUM_US_RESEARCH_UNIVERSE
                    if asset.required
                ),
                start_date=pit_dates[0],
                end_date=TEST_A_ANALYSIS_DATE,
                observed_at=TEST_A_DECISION_TIME - timedelta(hours=2),
                timezone="America/New_York",
                currency="USD",
                price_adjustment_policy="raw_ohlcv; adjusted_close_research_only",
                corporate_action_policy="certified_pit_ledger",
                raw_row_count=TEST_A_BAR_COUNT * 18,
                accepted_row_count=TEST_A_BAR_COUNT * 18,
                rejected_row_count=0,
                duplicate_count=0,
                missingness_summary={},
                stale_symbol_summary=[],
                failed_symbols=[],
                schema_version="market-snapshot-v2",
                application_version="test",
                quality_status="passed",
                certification_result="CERTIFIED",
                is_demo=False,
            )
        )

    effective_config = EffectiveRuntimeConfig(
        report_dir=tmp_path / "reports", settings=settings
    )
    service = ApplicationService(
        factory,
        settings,
        snapshot_root=tmp_path / "reports",
        effective_config=effective_config,
    )
    result = service.run_daily_quant_report(
        portfolio_id=None,
        decision_time=TEST_A_DECISION_TIME,
        refresh=False,
    )

    stages = {item.name: item for item in result.stages}
    # Session convention: weekend decision anchors to the latest completed session.
    assert result.analysis_date == TEST_A_ANALYSIS_DATE
    assert result.trade_date == date(2026, 8, 10)
    assert result.market_session == "CLOSED"

    # Research chain stays green.
    from personal_alpha_terminal.application.daily_result import StageStatus

    for name in ("CALENDAR", "DATA", "PIT", "FEATURE", "FACTOR"):
        assert stages[name].status in {
            StageStatus.PASS,
            StageStatus.PASS_DEGRADED,
        }, name
    assert stages["SIGNAL"].status is StageStatus.FAIL_BLOCKING
    assert "STRATEGY_NOT_PRODUCTION_APPROVED" in stages["SIGNAL"].message
    assert stages["PROBABILITY"].status is StageStatus.PASS_DEGRADED
    assert stages["PERSISTENCE"].status is StageStatus.PASS

    # Portfolio is REQUIRED; downstream stages are blocked, not silently green.
    assert stages["PORTFOLIO"].status is StageStatus.FAIL_BLOCKING
    assert "PORTFOLIO NOT INITIALIZED" in stages["PORTFOLIO"].message
    for name in ("RISK", "DECISION", "EXECUTION"):
        assert stages[name].status is StageStatus.NOT_RUN, name
        assert stages[name].metadata.get("blocked_by") == "SIGNAL"

    # No formal decision, no execution legs, no BUY/SELL anywhere.
    assert result.portfolio.status == "NOT_INITIALIZED"
    assert result.final_decisions == ()
    assert result.execution_plan.status == "BLOCKED"
    assert result.execution_plan.legs == ()
    assert result.actionable is False
    # Completed PIT factor diagnostics stay valid even though SIGNAL and the
    # missing manual ledger keep the run strictly non-actionable.
    assert result.run_classification == "VALID_ANALYSIS_NON_ACTIONABLE"
    assert any("PORTFOLIO NOT INITIALIZED" in item for item in result.blockers)

    # Data certification invariants must not regress.
    data_metadata = stages["DATA"].metadata
    assert data_metadata["future_rows"] == 0
    assert data_metadata["duplicate_rows"] == 0
    assert data_metadata["invalid_ohlc"] == 0
    assert data_metadata["timezone_violations"] == 0
    assert data_metadata["pit_integrity_status"] == "PASS"
    assert data_metadata["coverage"] == 1.0
    assert len(data_metadata["certified_symbols"]) == 18
    assert data_metadata["required_certified"] == data_metadata["required_total"] == 15

    # Benchmark requirement 4/5: SPY + QQQ share the SAME PIT window; no future
    # offset between strategy cutoff and benchmark.  Observation count is the
    # number of RETURNS (bars - 1): the first session has no prior close.
    by_name = {item.name: item for item in result.benchmarks}
    assert "SPY" in by_name and "QQQ" in by_name
    spy, qqq = by_name["SPY"], by_name["QQQ"]
    assert spy.status == "PIT PROXY"
    assert qqq.status == "PIT PROXY"
    assert spy.observation_count == qqq.observation_count == TEST_A_BAR_COUNT - 1
    assert spy.start_date == qqq.start_date == pit_dates[1]
    assert spy.end_date == qqq.end_date == TEST_A_ANALYSIS_DATE
    assert spy.period_return is not None and qqq.period_return is not None
    assert spy.annualized_volatility is not None
    assert spy.max_drawdown is not None and spy.max_drawdown <= 0

    engine.dispose()


# ---------------------------------------------------------------------------
# Test B: isolated TEST portfolio through the complete decision chain.
# ---------------------------------------------------------------------------


def _seed_test_b_state(
    session: Session,
    tmp_path: Path,
    *,
    produce_artifacts: bool,
) -> tuple[int, EffectiveRuntimeConfig]:
    config = EffectiveRuntimeConfig(
        cache_dir=tmp_path / "cache",
        report_dir=tmp_path / "reports",
        operational_policy_path=tmp_path / "operational_policy.json",
    )
    data_version = "fixture-data-version-b"
    decision_time = TEST_B_DECISION_TIME
    analysis_date = decision_time.date()
    _write_test_b_current_directory(config, decision_time=decision_time)

    stocks = _seed_securities(session)
    _seed_prices(
        session,
        stocks,
        end_date=analysis_date,
        periods=TEST_B_BAR_COUNT,
        decision_time=decision_time,
        close_function=_risk_aligned_close,
    )
    dates = _bar_dates(analysis_date, TEST_B_BAR_COUNT)
    research_symbols = tuple(
        asset.ticker
        for asset in MINIMUM_US_RESEARCH_UNIVERSE
        if asset.asset_type in {"stock", "etf"}
    )
    _seed_pit_series(
        session,
        stocks,
        dates=dates,
        decision_time=decision_time,
        symbols=research_symbols,
        close_function=_risk_aligned_close,
    )
    snapshot = _seed_universe_with_memberships(
        session,
        stocks,
        analysis_date=analysis_date,
        data_version=data_version,
        decision_time=decision_time,
    )
    _seed_certification(
        session,
        snapshot=snapshot,
        decision_time=decision_time,
        data_version=data_version,
        allow_portfolio_decision=True,
    )

    # PIT tradability evidence for every stock/ETF member (B2 writer output shape).
    for asset in MINIMUM_US_RESEARCH_UNIVERSE:
        if asset.asset_type not in {"stock", "etf"}:
            continue
        session.add(
            TradingStatus(
                stock_id=stocks[asset.ticker].id,
                status="TRADABLE",
                effective_time=decision_time - timedelta(days=1),
                available_time=decision_time - timedelta(days=1),
                ingested_time=decision_time - timedelta(days=1),
                reason="certified PIT bar evidence; no known delisting record",
                source="certified_live_universe",
                provider="isolated-test",
            )
        )

    # Isolated TEST portfolio: two small positions + cash (never the production
    # DB).  Weights stay well inside the frozen position/turnover constraints so
    # the optimizer is feasible, and two holdings keep the correlation baseline
    # evidence VALID.
    portfolio = Portfolio(
        name="ISOLATED TEST PORTFOLIO",
        base_currency="USD",
        cash_balance=Decimal("100000"),
        source="test-fixture",
    )
    session.add(portfolio)
    session.flush()
    session.add_all(
        (
            PortfolioPosition(
                portfolio_id=portfolio.id,
                stock_id=stocks["SGOV"].id,
                as_of_date=analysis_date,
                quantity=Decimal("40"),
                average_cost=Decimal("100"),
            ),
            PortfolioPosition(
                portfolio_id=portfolio.id,
                stock_id=stocks["TLT"].id,
                as_of_date=analysis_date,
                quantity=Decimal("40"),
                average_cost=Decimal("110"),
            ),
        )
    )

    # Certified next-tradable-open session after the decision cutoff.
    next_open_date = date(2027, 8, 9)
    session.add(
        ExchangeSession(
            exchange="XNYS",
            session_date=next_open_date,
            is_open=True,
            open_time=datetime(2027, 8, 9, 13, 30, tzinfo=UTC),
            close_time=datetime(2027, 8, 9, 20, 0, tzinfo=UTC),
            timezone="America/New_York",
            source="exchange_calendars",
            provider="exchange_calendars:XNYS",
            available_time=decision_time - timedelta(days=1),
            ingested_time=decision_time - timedelta(days=1),
        )
    )
    session.flush()

    strategy = USAdaptiveAlphaCoreV1(config.strategy)
    parameter_fingerprint = strategy.config.parameter_fingerprint
    alpha_model_version = f"{strategy.model_id}:{strategy.version}"

    if produce_artifacts:
        registry = ValidationArtifactRegistry(config.validation_artifact_dir)
        portfolio_artifact = registry.produce_portfolio_approval(
            validation_id="isolated-test-portfolio-validation",
            locked_oos_evidence_id="isolated-test-locked-oos",
            identity=PortfolioValidationIdentity(
                alpha_model_version=alpha_model_version,
                alpha_data_version=data_version,
                strategy_parameter_hash=parameter_fingerprint,
                portfolio_constraint_hash=config.portfolio_constraint_hash,
                risk_model_hash=config.risk_model_hash,
                cost_model_hash=config.cost_model_hash,
                runtime_config_hash=config.runtime_config_hash,
                benchmark_definition=config.benchmark,
            ),
            validation_start=date(2025, 1, 2),
            validation_end=date(2027, 12, 31),
            embargo_sessions=21,
            walk_forward_configuration="expanding-252-63",
            source_git_commit="isolated-test",
            created_at=decision_time - timedelta(days=2),
        )
        registry.produce_probability_calibration(
            calibration_id="isolated-test-probability-calibration",
            identity=ProbabilityCalibrationIdentity(
                alpha_model_version=alpha_model_version,
                alpha_data_version=data_version,
                strategy_parameter_hash=parameter_fingerprint,
            ),
            method="isotonic",
            calibration_version="isolated-v1",
            train_start=date(2024, 1, 1),
            train_end=date(2024, 12, 31),
            calibration_start=date(2025, 1, 1),
            calibration_end=date(2025, 12, 31),
            oos_start=date(2026, 1, 1),
            oos_end=date(2027, 12, 31),
            brier_score=0.2,
            log_loss=0.6,
            expected_calibration_error=0.03,
            sample_count=500,
            reliability_bins=((0.4, 0.41, 100), (0.6, 0.59, 100)),
            created_at=decision_time - timedelta(days=2),
        )
        models = ModelRegistryService(session)
        record = models.ensure_registered(
            model_id=strategy.model_id,
            version=strategy.version,
            objective="isolated full-chain test",
            inputs=["PIT prices"],
            data_requirements=["certified US universe"],
            hyperparameters=asdict(config.strategy),
            limitations=["isolated fixture proves code path only"],
        )
        record.status = "Tested"
        session.flush()
        models.promote(
            record,
            ModelPromotionEvidence(
                data_version=data_version,
                parameter_fingerprint=parameter_fingerprint,
                validation_manifest_hash=portfolio_artifact.artifact_hash,
                locked_oos=True,
                pit_certified=True,
                survivorship_bias_controlled=True,
                costs_included=True,
                approved_by="isolated test producer",
                notes="fixture-only; never upgrades live-capital readiness",
            ),
        )
    session.flush()
    return portfolio.id, config


def test_b_isolated_test_portfolio_runs_full_chain(tmp_path: Path) -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        portfolio_id, config = _seed_test_b_state(
            session, tmp_path, produce_artifacts=True
        )
        workflow = ProductionDailyWorkflow(session, config)
        result = workflow.run(
            portfolio_id=portfolio_id, decision_time=TEST_B_DECISION_TIME
        )

        # Full chain executed: decision generated and persisted.
        assert result.status == "GENERATED"
        assert result.data_certification == "APPROVED"
        assert result.model_status == "PRODUCTION_APPROVED"
        assert result.portfolio_status == "TARGET_COMPUTED"
        assert result.portfolio_value is not None and result.portfolio_value > 0
        assert result.blockers == ()

        stages = {item.name: item.status for item in result.pipeline_stages}
        assert stages["Data Quality Gate"] == "VALID"
        assert stages["Point-in-Time Inputs"] == "VALID"
        assert stages["Alpha Signals"] == "VALID"
        assert stages["Risk Model"] == "VALID"
        assert stages["Portfolio Construction"] == "PRODUCTION_APPROVED"
        assert stages["Stress Risk"] == "PASS"
        assert stages["Daily Decision"] == "READY"

        # Risk engine actually executed with real evidence.
        assert result.risk is not None
        assert result.risk.valid_for_optimization
        assert result.risk.size_exposure_status.value == "VALID"
        assert result.stress is not None
        assert result.stress.status.value == "PASS"
        assert result.stress.hard_failures == ()
        assert result.risk_state is not None
        assert result.risk_state.correlation_status.value == "VALID"
        assert result.risk_state.average_correlation is not None
        assert result.risk_state.baseline_average_correlation is not None
        assert result.risk_state.correlation_recent_samples == 63
        assert result.risk_state.correlation_baseline_samples >= 126

        # Target, trades and manual execution plan were produced.
        assert result.target is not None and result.target.production_approved
        assert result.target.model_validation_id == (
            "isolated-test-portfolio-validation"
        )
        assert result.trades
        assert all(item.manual_confirmation_required for item in result.trades)
        actionable = [item for item in result.trades if item.action.value != "HOLD"]
        assert actionable
        assert result.recommendations
        assert all(item.earliest_execution_time > TEST_B_DECISION_TIME
                   for item in result.recommendations)
        # Candidate ranking is not a decision: only the validated chain produced these.
        assert result.gross_target is not None
        assert result.cash_target is not None

        # Persistence: quant decision run + recommendations in the isolated DB.
        run = session.scalar(
            select(QuantDecisionRun).where(
                QuantDecisionRun.portfolio_id == portfolio_id
            )
        )
        assert run is not None
        assert run.status == "generated"
        assert run.gate_status == "APPROVED"
        assert run.recommendations
        for recommendation in run.recommendations:
            assert recommendation.action in {"BUY", "ADD", "REDUCE", "SELL", "HOLD"}
            assert recommendation.review_status == "pending"
            assert recommendation.reference_price > 0

    engine.dispose()


def test_b_without_approval_artifacts_fails_closed(tmp_path: Path) -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        portfolio_id, config = _seed_test_b_state(
            session, tmp_path, produce_artifacts=False
        )
        workflow = ProductionDailyWorkflow(session, config)
        result = workflow.run(
            portfolio_id=portfolio_id, decision_time=TEST_B_DECISION_TIME
        )

        # No approval artifacts -> the chain fails closed.  Without the model
        # approval the signals stay RESEARCH (never PRODUCTION_APPROVED), so
        # the pipeline stops before construction; no BUY/SELL can ever exist.
        assert result.status == "BLOCKED"
        assert result.recommendations == ()
        assert result.trades == ()
        assert result.target is None
        stages = {item.name: item.status for item in result.pipeline_stages}
        # The chain stops at the first failing gate (Alpha Signals without a
        # model approval); a construction stage is only reached when the gates
        # before it pass.
        assert "Portfolio Construction" not in stages or (
            stages["Portfolio Construction"] == "BLOCKED"
        )
        assert any(
            "STRATEGY_NOT_PRODUCTION_APPROVED" in item
            for item in result.blockers
        ) or any(
            "locked OOS validation manifest" in item for item in result.blockers
        )

        run = session.scalar(
            select(QuantDecisionRun).where(
                QuantDecisionRun.portfolio_id == portfolio_id
            )
        )
        assert run is not None
        assert run.status == "blocked"
        assert run.gate_status == "BLOCKED"
        assert run.recommendations == []
    engine.dispose()


def test_b_provisional_operational_approval_runs_without_research_artifacts(
    tmp_path: Path,
) -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        portfolio_id, config = _seed_test_b_state(
            session, tmp_path, produce_artifacts=False
        )
        strategy = USAdaptiveAlphaCoreV1(config.strategy)
        policy = issue_operational_policy(
            identity=build_operational_identity(config, strategy),
            decision=OperationalPolicyDecision.ALLOW_PROVISIONAL,
            research_states_allowed=DEFAULT_ALLOWED_RESEARCH_STATES,
            issued_by="USER:test:e2e",
            reason="isolated provisional operational mode: current data and PIT gates pass",
            created_at=TEST_B_DECISION_TIME - timedelta(days=1),
        )
        OperationalPolicyStore(config.operational_policy_path).save(policy)

        workflow = ProductionDailyWorkflow(session, config)
        result = workflow.run(
            portfolio_id=portfolio_id,
            decision_time=TEST_B_DECISION_TIME,
        )

        assert result.status == "GENERATED"
        assert result.model_status == "PROVISIONAL_OPERATIONAL_APPROVED"
        assert result.production_approval_artifact_id == "NOT_APPROVED"
        assert result.operational_policy_id == policy.policy_id
        assert result.operational_policy_decision == "ALLOW_PROVISIONAL"
        assert result.operationally_allowed
        assert result.operational_approval_artifact_id == policy.policy_id
        assert result.operational_readiness == "PROVISIONAL_ACTIONABLE"
        assert result.target is not None
        assert result.target.operational_approved
        assert not result.target.production_approved
        assert result.target.model_validation_id == policy.policy_id
        assert result.recommendations
        assert result.trades

    engine.dispose()


# ---------------------------------------------------------------------------
# B2 writer: tradability evidence is PIT-honest and fail-closed.
# ---------------------------------------------------------------------------


def test_tradability_writer_is_pit_honest_and_fail_closed(tmp_path: Path) -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    decision_time = TEST_B_DECISION_TIME
    with Session(engine) as session:
        stocks = _seed_securities(session)
        _seed_prices(
            session,
            stocks,
            end_date=decision_time.date(),
            periods=TEST_B_BAR_COUNT,
            decision_time=decision_time,
        )
        # One security has a known delisting record -> never TRADABLE.
        session.add(
            DelistingHistory(
                stock_id=stocks["XOM"].id,
                effective_date=decision_time.date() - timedelta(days=10),
                available_time=decision_time - timedelta(days=9),
                ingested_time=decision_time - timedelta(days=9),
                reason="fixture delisting",
                revision_id="fixture-revision",
                source="fixture",
                provider="isolated-test",
            )
        )
        # One security has no bar evidence -> stays UNKNOWN (no row written).
        no_bar_stock = stocks["JNJ"]
        session.execute(delete(Price).where(Price.stock_id == no_bar_stock.id))
        session.flush()

        service = DataService(
            session,
            Settings(_env_file=None, database_url="sqlite://"),
            snapshot_root=tmp_path,
        )
        members = tuple(stocks.values())
        service._materialize_tradability_evidence(
            members=members, decision_time=decision_time
        )

        statuses = {
            session.get(Stock, row.stock_id).symbol: row
            for row in session.scalars(select(TradingStatus))
        }
        # Index is skipped; delisted and bar-less securities get no TRADABLE row.
        assert "^VIX" not in statuses
        assert "XOM" not in statuses
        assert "JNJ" not in statuses
        tradable = {symbol for symbol, row in statuses.items() if row.status == "TRADABLE"}
        assert "AAPL" in tradable and "SPY" in tradable
        for row in statuses.values():
            # PIT honesty: availability is the ingestion moment, never backdated.
            # SQLite returns naive datetimes, so re-attach UTC before comparing.
            stored_available = row.available_time.replace(tzinfo=UTC)
            assert stored_available == decision_time
            assert row.effective_time.replace(tzinfo=UTC) == decision_time
            assert stored_available >= row.effective_time.replace(tzinfo=UTC)

        # Idempotent: a second run adds no duplicate rows.
        before = session.scalar(select(func.count()).select_from(TradingStatus))
        service._materialize_tradability_evidence(
            members=members, decision_time=decision_time
        )
        after = session.scalar(select(func.count()).select_from(TradingStatus))
        assert before == after
    engine.dispose()
