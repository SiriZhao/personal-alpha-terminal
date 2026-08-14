"""ROUND23 incremental refresh planning and provisional forward authorization tests."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy.orm import Session

from personal_alpha_terminal.application.operational_readiness import (
    resolve_current_operational_identity,
)
from personal_alpha_terminal.application.strategy_approval import (
    StrategyApprovalDecision,
    StrategyApprovalStore,
    issue_strategy_approval,
)
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
from personal_alpha_terminal.data.database import build_engine
from personal_alpha_terminal.data.market_data.repository import PriceRepository
from personal_alpha_terminal.data.market_data.service import MarketDataEngine
from personal_alpha_terminal.models import Base, Price, Stock
from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
    USAdaptiveAlphaCoreV1,
)
from personal_alpha_terminal.terminal.cli import _write_performance_trace


class _FakeBatch:
    source = "yahoo_finance"
    provider_id = "yahoo_finance.broad_universe_batch"
    chunk_size = 100

    def __init__(self) -> None:
        self.calls = 0
        self.request_start = None
        self.request_end = None

    def download(self, symbols, *, start_date, end_date):
        self.calls += 1
        self.request_start = start_date
        self.request_end = end_date
        return type(
            "Report",
            (),
            {"received_symbols": tuple(symbols), "failed_symbols": (), "bars": ()},
        )()


def _engine_and_stock(tmp_path: Path, *, end: date):
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    available = datetime(2026, 8, 3, 20, 30, tzinfo=UTC)
    session = Session(engine)
    stock = Stock(
        canonical_code="US:XNAS:PLAN",
        symbol="PLAN",
        name="Plan",
        market="US",
        exchange="XNAS",
        asset_type="stock",
        currency="USD",
        timezone="America/New_York",
        list_date=date(2020, 1, 1),
        is_active=True,
        source="fixture",
        provider="fixture",
        available_time=available,
        ingested_time=available,
    )
    session.add(stock)
    session.flush()
    return engine, session, stock


def _add_price(session: Session, stock: Stock, day: date) -> None:
    available = datetime(2026, 8, 3, 20, 30, tzinfo=UTC)
    session.add(
        Price(
            stock_id=stock.id,
            trade_date=day,
            open=__import__("decimal").Decimal("100"),
            high=__import__("decimal").Decimal("101"),
            low=__import__("decimal").Decimal("99"),
            close=__import__("decimal").Decimal("100"),
            volume=1000,
            asset_type="stock",
            volume_unit="share",
            price_type="unadjusted_ohlcv",
            source="yahoo_finance",
            provider="yahoo_finance.broad_universe_batch",
            event_time=available - timedelta(minutes=30),
            available_time=available,
            ingested_at=available,
        )
    )


def _service(session: Session, tmp_path: Path, batch: _FakeBatch) -> MarketDataEngine:
    return MarketDataEngine(
        providers=[],
        repository=PriceRepository(session),
        settings=Settings(
            market_data_max_retries=0,
            market_data_retry_backoff_seconds=0.0,
            market_data_provider_cache_dir=tmp_path / "cache",
            market_data_timeout_seconds=10,
            market_data_default_start=date(2024, 8, 1),
            market_data_overlap_days=2,
            console_initial_history_days=550,
        ),
        batch_provider=batch,
        batch_threshold=1,
    )


def test_incremental_refresh_requests_only_missing_session(tmp_path: Path) -> None:
    engine, session, stock = _engine_and_stock(tmp_path, end=date(2026, 8, 12))
    _add_price(session, stock, date(2024, 8, 1))
    _add_price(session, stock, date(2026, 8, 12))
    session.flush()
    batch = _FakeBatch()
    report = _service(session, tmp_path, batch)._run_batch_refresh(
        [stock], date(2026, 8, 13), forced_start_date=date(2024, 8, 1)
    )
    assert batch.calls == 1
    assert batch.request_start == date(2026, 8, 13)
    assert batch.request_end == date(2026, 8, 13)
    assert report.results[0].refresh_class == "INCREMENTAL_ONE_SESSION"
    engine.dispose()


def test_fully_current_cache_skips_provider(tmp_path: Path) -> None:
    engine, session, stock = _engine_and_stock(tmp_path, end=date(2026, 8, 13))
    _add_price(session, stock, date(2024, 8, 1))
    _add_price(session, stock, date(2026, 8, 13))
    session.flush()
    batch = _FakeBatch()
    report = _service(session, tmp_path, batch)._run_batch_refresh(
        [stock], date(2026, 8, 13), forced_start_date=date(2024, 8, 1)
    )
    assert batch.calls == 0
    assert report.results[0].status == "cached"
    assert report.results[0].refresh_class == "CACHED_UP_TO_DATE"
    engine.dispose()


def test_gap_requests_only_missing_window(tmp_path: Path) -> None:
    engine, session, stock = _engine_and_stock(tmp_path, end=date(2026, 8, 12))
    _add_price(session, stock, date(2024, 8, 1))
    _add_price(session, stock, date(2026, 8, 1))
    session.flush()
    batch = _FakeBatch()
    report = _service(session, tmp_path, batch)._run_batch_refresh(
        [stock], date(2026, 8, 13), forced_start_date=date(2024, 8, 1)
    )
    assert batch.calls == 1
    assert batch.request_start == date(2026, 8, 2)
    assert batch.request_end == date(2026, 8, 13)
    assert report.results[0].refresh_class == "INCREMENTAL_GAP"
    engine.dispose()


def test_new_listing_uses_full_backfill_window(tmp_path: Path) -> None:
    engine, session, stock = _engine_and_stock(tmp_path, end=date(2026, 8, 12))
    batch = _FakeBatch()
    report = _service(session, tmp_path, batch)._run_batch_refresh(
        [stock], date(2026, 8, 13), forced_start_date=date(2024, 8, 1)
    )
    assert batch.calls == 1
    assert batch.request_start == date(2026, 8, 13) - timedelta(days=550)
    assert report.results[0].refresh_class == "FULL_BACKFILL_REQUIRED"
    engine.dispose()


def test_performance_trace_writes_stages(tmp_path: Path) -> None:
    started = datetime(2026, 8, 14, 1, 0, tzinfo=UTC)
    result = SimpleNamespace(
        run_id="trace-run",
        started_at=started,
        finished_at=started + timedelta(seconds=12),
        stages=(
            SimpleNamespace(
                name="DATA",
                duration_seconds=8.0,
                metadata={"requested_security_count": 4966},
            ),
            SimpleNamespace(name="PIT", duration_seconds=2.0, metadata={}),
            SimpleNamespace(name="FACTOR", duration_seconds=1.0, metadata={}),
        ),
    )
    config = EffectiveRuntimeConfig(report_dir=tmp_path / "reports")
    _write_performance_trace(result, config)  # type: ignore[arg-type]
    payload = json.loads(
        (tmp_path / "reports" / "validation-artifacts" / "daily_performance_trace.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["stages_seconds"]["DATA"] == 8.0
    assert payload["total_seconds"] == 12.0


def test_strategy_approval_absent_blocks_and_valid_provisional_matches(tmp_path: Path) -> None:
    config = EffectiveRuntimeConfig(
        strategy_approval_path=tmp_path / "strategy_approval.json",
        report_dir=tmp_path / "reports",
    )
    strategy = USAdaptiveAlphaCoreV1(config.strategy)
    now = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
    identity = resolve_current_operational_identity(config, strategy, decision_time=now)
    store = StrategyApprovalStore(config.strategy_approval_path)
    approval, reason = store.status(identity, now=now)
    assert approval is None
    assert reason == "STRATEGY_APPROVAL_NOT_CONFIGURED"
    approval = issue_strategy_approval(
        identity=identity,
        decision=StrategyApprovalDecision.ALLOW_PROVISIONAL_FORWARD,
        operator_intent="test provisional forward",
    )
    store.save(approval)
    loaded, reason = store.status(identity, now=now)
    assert loaded is not None and loaded.approval_id == approval.approval_id
    assert reason == "STRATEGY_APPROVAL_EFFECTIVE"


def test_strategy_approval_identity_mismatch_blocks(tmp_path: Path) -> None:
    config = EffectiveRuntimeConfig(
        strategy_approval_path=tmp_path / "strategy_approval.json",
        report_dir=tmp_path / "reports",
    )
    strategy = USAdaptiveAlphaCoreV1(config.strategy)
    now = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
    identity = resolve_current_operational_identity(config, strategy, decision_time=now)
    store = StrategyApprovalStore(config.strategy_approval_path)
    approval = issue_strategy_approval(
        identity=identity,
        decision=StrategyApprovalDecision.ALLOW_PROVISIONAL_FORWARD,
        operator_intent="test",
    )
    store.save(approval)
    changed = EffectiveRuntimeConfig(
        strategy_approval_path=tmp_path / "strategy_approval.json",
        report_dir=tmp_path / "reports",
        broad_universe=__import__("dataclasses").replace(
            config.broad_universe, minimum_operational_universe=99
        ),
    )
    changed_identity = resolve_current_operational_identity(changed, strategy, decision_time=now)
    loaded, reason = store.status(changed_identity, now=now)
    assert loaded is None
    assert reason == "STRATEGY_APPROVAL_IDENTITY_MISMATCH"


def test_provisional_approval_hash_enables_signal_authorization() -> None:
    """Signals produced under an explicit provisional approval hash pass the SIGNAL gate."""
    from personal_alpha_terminal.application.quant_daily_service import _strategy_blocker
    from personal_alpha_terminal.quant_engine.alpha import (
        AlphaDataQuality,
        AlphaSignal,
        AlphaValidationStatus,
    )

    decision_time = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
    signal = AlphaSignal(
        symbol="AAA",
        as_of=decision_time,
        signal_type="test",
        expected_excess_return=0.01,
        horizon=21,
        raw_signal=0.01,
        normalized_signal=0.01,
        confidence=0.0,
        confidence_calibrated=False,
        sample_size=100,
        statistical_strength=0.5,
        economic_strength=0.5,
        decay_half_life=21,
        valid_until=decision_time + timedelta(days=35),
        data_quality=AlphaDataQuality.VALID,
        pit_valid=True,
        validation_status=AlphaValidationStatus.PROVISIONAL_OPERATIONAL_APPROVED,
        model_version="m:1",
        data_version="d1",
        operational_approval_hash="strategy-approval-test",
    )
    assert _strategy_blocker((signal,), decision_time=decision_time) is None
