from __future__ import annotations

import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pandas as pd
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.application.daily_result import StageStatus
from personal_alpha_terminal.application.data_certification import DailyDataCertifier
from personal_alpha_terminal.application.data_service import DataService
from personal_alpha_terminal.application.universe import MINIMUM_US_RESEARCH_UNIVERSE
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.models import DataSnapshotManifest, Price, Stock
from personal_alpha_terminal.quant_engine.production_pipeline import _history_is_available

ANALYSIS_DATE = date(2026, 8, 7)
DECISION_TIME = datetime(2026, 8, 8, 21, tzinfo=UTC)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        runtime_profile="TEST",
        database_url="sqlite://",
        daily_pipeline_report_path=tmp_path / "daily.md",
        console_initial_history_days=90,
        console_data_stale_days=3,
    )


def _seed(
    session: Session,
    tmp_path: Path,
    *,
    omit: set[str] | None = None,
    short: set[str] | None = None,
    stale: set[str] | None = None,
    future: set[str] | None = None,
    reconciled: bool = True,
    corporate_actions: bool = True,
) -> DataSnapshotManifest:
    omit = omit or set()
    short = short or set()
    stale = stale or set()
    future = future or set()
    assets = tuple(MINIMUM_US_RESEARCH_UNIVERSE)
    dates = [item.date() for item in pd.bdate_range(end=ANALYSIS_DATE, periods=126)]
    for asset in assets:
        stock = Stock(
            canonical_code=asset.canonical_code,
            symbol=asset.ticker,
            name=asset.name,
            market="US",
            exchange=asset.exchange,
            asset_type=asset.asset_type,
            currency="USD",
            timezone="America/New_York",
        )
        session.add(stock)
        session.flush()
        if asset.ticker in omit:
            continue
        selected = dates[-20:] if asset.ticker in short else dates
        if asset.ticker in stale:
            selected = [item - timedelta(days=10) for item in selected]
        for index, day in enumerate(selected):
            available = datetime.combine(day, time(21), tzinfo=UTC)
            if asset.ticker in future and index == len(selected) - 1:
                available = DECISION_TIME + timedelta(days=1)
            close = Decimal("100") + Decimal(index) / Decimal("100")
            session.add(
                Price(
                    stock_id=stock.id,
                    trade_date=day,
                    open=close,
                    high=close + 1,
                    low=close - 1,
                    close=close,
                    volume=(None if asset.asset_type == "index" else 1_000_000),
                    asset_type=asset.asset_type,
                    volume_unit=("none" if asset.asset_type == "index" else "share"),
                    price_currency="USD",
                    price_type=(
                        "index_level_ohlcv"
                        if asset.asset_type == "index"
                        else "unadjusted_ohlcv"
                    ),
                    source="fixture-primary",
                    provider="fixture.primary",
                    event_time=datetime.combine(day, time(20), tzinfo=UTC),
                    available_time=available,
                    ingested_at=max(available, DECISION_TIME),
                )
            )
    identity = uuid4().hex
    target = tmp_path / f"manifest-{identity}.json"
    action_status = "PASS" if corporate_actions else "UNAVAILABLE"
    reconciliation_status = "PASS" if reconciled else "UNAVAILABLE"
    coverage_rows = []
    action_rows = []
    reconciliation_rows = []
    for asset in assets:
        selected_count = 0 if asset.ticker in omit else (20 if asset.ticker in short else 126)
        coverage_rows.append(
            {
                "symbol": asset.ticker,
                "required": asset.required,
                "expected": 126,
                "matched": selected_count,
                "missing": 126 - selected_count,
                "unexpected": 0,
                "duplicate": 0,
                "rejected": 0,
                "valid": selected_count,
                "latest": ANALYSIS_DATE.isoformat(),
            }
        )
        action_rows.append(
            {
                "symbol": asset.ticker,
                "status": action_status,
                "events_found": 0,
                "errors": [],
            }
        )
        reconciliation_rows.append(
            {
                "symbol": asset.ticker,
                "status": reconciliation_status,
                "secondary_provider": "fixture-secondary",
                "primary_rows": selected_count,
                "secondary_rows": selected_count if reconciled else 0,
                "matched_rows": selected_count if reconciled else 0,
                "coverage": 1.0 if selected_count and reconciled else 0.0,
                "warning_divergences": 0,
                "blocking_divergences": 0,
                "reason": "fixture evidence" if reconciled else "fixture unavailable",
            }
        )
    target.write_text(
        json.dumps(
            {
                "provider_reconciled": reconciled,
                "provider_reconciliation_status": reconciliation_status,
                "corporate_action_status": action_status,
                "bar_coverage": coverage_rows,
                "corporate_action_symbol_results": action_rows,
                "provider_reconciliation_symbol_results": reconciliation_rows,
                "pit_data_cutoff": DECISION_TIME.isoformat(),
                "latest_completed_session": ANALYSIS_DATE.isoformat(),
                "decision_timestamp_convention": "fixture next-session execution",
                "evidence": {},
            }
        ),
        encoding="utf-8",
    )
    required = sorted(item.ticker for item in assets if item.required)
    manifest = DataSnapshotManifest(
        snapshot_id=f"fixture-{identity}",
        provider_name="fixture-primary,fixture-secondary" if reconciled else "fixture-primary",
        provider_adapter="fixture.primary,fixture.secondary" if reconciled else "fixture.primary",
        requested_at=DECISION_TIME - timedelta(hours=1),
        completed_at=DECISION_TIME,
        market="US",
        asset_type="mixed",
        symbols=[item.ticker for item in assets],
        required_symbols=required,
        start_date=dates[0],
        end_date=ANALYSIS_DATE,
        observed_at=DECISION_TIME,
        timezone="America/New_York",
        currency="USD",
        price_adjustment_policy="raw_ohlcv; adjusted_close_research_only",
        corporate_action_policy=(
            "certified_pit_ledger"
            if corporate_actions
            else "not_certified_for_pit_portfolio_decisions"
        ),
        raw_row_count=0,
        accepted_row_count=0,
        rejected_row_count=0,
        duplicate_count=0,
        missingness_summary={},
        stale_symbol_summary=[],
        failed_symbols=[],
        schema_version="market-snapshot-v1",
        application_version="test",
        content_hash=identity.ljust(64, "0"),
        immutable_reference=str(target),
        quality_status="passed",
        certification_result="CERTIFIED",
        is_demo=False,
    )
    session.add(manifest)
    session.flush()
    return manifest


def test_complete_required_data_is_pass(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    with session_factory.begin() as session:
        manifest = _seed(session, tmp_path)
        result = DailyDataCertifier(session, _settings(tmp_path)).certify(
            analysis_date=ANALYSIS_DATE,
            decision_time=DECISION_TIME,
            manifest=manifest,
        )
    assert result.status is StageStatus.PASS
    assert result.coverage == 1.0
    assert result.fallback_provider is not None
    assert "stooq:etf/stock" in result.fallback_provider
    assert not result.blockers


def test_missing_optional_data_is_pass_degraded(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    optional = next(item.ticker for item in MINIMUM_US_RESEARCH_UNIVERSE if not item.required)
    with session_factory.begin() as session:
        manifest = _seed(session, tmp_path, omit={optional})
        result = DailyDataCertifier(session, _settings(tmp_path)).certify(
            analysis_date=ANALYSIS_DATE,
            decision_time=DECISION_TIME,
            manifest=manifest,
        )
    assert result.status is StageStatus.PASS_DEGRADED
    assert optional in result.optional_missing_symbols
    assert not result.blockers


def test_missing_required_data_is_fail_blocking(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    required = next(item.ticker for item in MINIMUM_US_RESEARCH_UNIVERSE if item.required)
    with session_factory.begin() as session:
        manifest = _seed(session, tmp_path, omit={required})
        result = DailyDataCertifier(session, _settings(tmp_path)).certify(
            analysis_date=ANALYSIS_DATE,
            decision_time=DECISION_TIME,
            manifest=manifest,
        )
    assert result.status is StageStatus.FAIL_BLOCKING
    assert required in result.missing_symbols


def test_partial_history_below_strategy_threshold_is_blocking(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    required = next(item.ticker for item in MINIMUM_US_RESEARCH_UNIVERSE if item.required)
    with session_factory.begin() as session:
        manifest = _seed(session, tmp_path, short={required})
        result = DailyDataCertifier(session, _settings(tmp_path)).certify(
            analysis_date=ANALYSIS_DATE,
            decision_time=DECISION_TIME,
            manifest=manifest,
        )
    assert result.status is StageStatus.FAIL_BLOCKING
    assert any("insufficient history" in item for item in result.blockers)


def test_future_available_price_is_blocking(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    required = next(item.ticker for item in MINIMUM_US_RESEARCH_UNIVERSE if item.required)
    with session_factory.begin() as session:
        manifest = _seed(session, tmp_path, future={required})
        result = DailyDataCertifier(session, _settings(tmp_path)).certify(
            analysis_date=ANALYSIS_DATE,
            decision_time=DECISION_TIME,
            manifest=manifest,
        )
    assert result.status is StageStatus.FAIL_BLOCKING
    assert result.future_rows == 1


def test_missing_or_reversed_timestamp_contract_is_blocking(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    with session_factory.begin() as session:
        manifest = _seed(session, tmp_path)
        row = session.query(Price).first()
        assert row is not None
        row.event_time = None
        session.flush()
        result = DailyDataCertifier(session, _settings(tmp_path)).certify(
            analysis_date=ANALYSIS_DATE,
            decision_time=DECISION_TIME,
            manifest=manifest,
        )
    assert result.status is StageStatus.FAIL_BLOCKING
    assert result.timezone_violations == 1


def test_stale_required_price_is_blocking(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    required = next(item.ticker for item in MINIMUM_US_RESEARCH_UNIVERSE if item.required)
    with session_factory.begin() as session:
        manifest = _seed(session, tmp_path, stale={required})
        result = DailyDataCertifier(session, _settings(tmp_path)).certify(
            analysis_date=ANALYSIS_DATE,
            decision_time=DECISION_TIME,
            manifest=manifest,
        )
    assert result.status is StageStatus.FAIL_BLOCKING
    assert required in result.stale_symbols


def test_uncertified_lineage_and_corporate_actions_are_blocking(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    with session_factory.begin() as session:
        manifest = _seed(
            session,
            tmp_path,
            reconciled=False,
            corporate_actions=False,
        )
        result = DailyDataCertifier(session, _settings(tmp_path)).certify(
            analysis_date=ANALYSIS_DATE,
            decision_time=DECISION_TIME,
            manifest=manifest,
        )
    assert result.status is StageStatus.FAIL_BLOCKING
    assert result.provider_reconciliation == "UNAVAILABLE"
    assert result.corporate_action_status == "UNAVAILABLE"


def test_cold_database_requests_full_history(
    session_factory: sessionmaker[Session], tmp_path: Path
) -> None:
    settings = _settings(tmp_path)
    with session_factory.begin() as session:
        start = DataService(session, settings).refresh_start_date(
            analysis_date=ANALYSIS_DATE
        )
    assert start == ANALYSIS_DATE - timedelta(days=settings.console_initial_history_days)


def test_strategy_and_benchmark_share_the_same_pit_cutoff() -> None:
    safe = pd.Series(
        [0.01, -0.01],
        index=pd.DatetimeIndex(
            [DECISION_TIME - timedelta(days=2), DECISION_TIME - timedelta(days=1)]
        ),
    )
    future = pd.concat(
        [safe, pd.Series([0.50], index=pd.DatetimeIndex([DECISION_TIME + timedelta(days=1)]))]
    )
    assert _history_is_available(safe, DECISION_TIME)
    assert not _history_is_available(future, DECISION_TIME)
