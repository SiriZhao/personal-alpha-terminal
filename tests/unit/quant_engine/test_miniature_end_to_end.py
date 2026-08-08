from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from json import loads
from pathlib import Path

import exchange_calendars as xcals
import numpy as np
import pandas as pd
import pytest

from personal_alpha_terminal.backtest.schemas import BacktestBar, UniversePoint
from personal_alpha_terminal.core.market_time import market_close_utc
from personal_alpha_terminal.quant_engine.alpha import (
    AlphaDataQuality,
    AlphaSignal,
    AlphaValidationStatus,
)
from personal_alpha_terminal.quant_engine.backtest.production import (
    BacktestTarget,
    CorporateAction,
    CorporateActionType,
    ProductionBacktestConfig,
    ProductionBacktestDataset,
    ProductionBacktestEngine,
)
from personal_alpha_terminal.quant_engine.costs import (
    TransactionCostConfig,
    TransactionCostModel,
)
from personal_alpha_terminal.quant_engine.factors.cross_sectional import (
    FactorSpec,
    process_cross_section,
)
from personal_alpha_terminal.quant_engine.pit import select_fundamental_vintages
from personal_alpha_terminal.quant_engine.portfolio.construction import (
    PortfolioConstraints,
    PortfolioConstructionEngine,
)
from personal_alpha_terminal.quant_engine.production_pipeline import (
    DailyQuantInput,
    DailyQuantPipeline,
    ProductionPipelineStatus,
)
from personal_alpha_terminal.quant_engine.risk.budget import (
    PortfolioRiskState,
    RegimeRiskInput,
)
from personal_alpha_terminal.quant_engine.risk.model import AssetRiskMetadata
from personal_alpha_terminal.research.data_gate import (
    ResearchDataEvidence,
    ResearchDataGate,
    ResearchDataRequest,
    ResearchPurpose,
)

SYMBOLS = ("AAA", "BBB", "CCC", "DDD", "EEE")
ASSET_IDS = {symbol: index + 1 for index, symbol in enumerate(SYMBOLS)}
DECISION_TIME = datetime(2024, 1, 9, 22, tzinfo=UTC)


def _sessions() -> tuple[date, ...]:
    calendar = xcals.get_calendar("XNYS")
    return tuple(
        item.date()
        for item in calendar.sessions_in_range("2024-01-02", "2024-05-31")[:80]
    )


def _authorization():
    request = ResearchDataRequest(
        ResearchPurpose.PORTFOLIO_DECISION,
        "US",
        "stock",
        _sessions()[0],
        DECISION_TIME.date(),
        DECISION_TIME,
        "point_in_time_total_return",
        "mini-universe-v1",
        timedelta(days=7),
    )
    evidence = ResearchDataEvidence(
        "US",
        "stock",
        "passed",
        "fixture-primary",
        "fixture-adapter",
        ("fixture-primary", "fixture-validation"),
        DECISION_TIME - timedelta(hours=1),
        "certified",
        "point_in_time_total_return",
        "mini-universe-v1",
        DECISION_TIME - timedelta(days=1),
        True,
        True,
        0.0,
        0.0,
        0.0,
        0.0,
        "mini-data-v1",
        True,
        True,
        True,
        True,
    )
    return ResearchDataGate().authorize(request, evidence, evaluated_at=DECISION_TIME)


def _pit_factors() -> tuple[AlphaSignal, ...]:
    fundamentals = []
    for index, symbol in enumerate(SYMBOLS):
        fundamentals.append(
            {
                "permanent_security_id": symbol,
                "fiscal_period_end": "2023-09-30",
                "fiscal_period": "Q3-2023",
                "filing_date": "2023-11-15",
                "publication_time": "2023-11-15T20:00:00Z",
                "available_at": "2023-11-15T21:00:00Z",
                "ingested_at": "2023-11-15T22:00:00Z",
                "revision_id": "original",
                "data_version": "mini-data-v1",
                "quality": 10.0 + index,
                "sector": "Technology" if index < 3 else "Healthcare",
                "market_cap": 10_000_000_000 * (index + 1),
            }
        )
    fundamentals.append(
        {
            **fundamentals[0],
            "filing_date": "2024-05-01",
            "publication_time": "2024-05-01T20:00:00Z",
            "available_at": "2024-05-01T21:00:00Z",
            "ingested_at": "2024-05-01T22:00:00Z",
            "revision_id": "future-perfect-revision",
            "data_version": "future-v2",
            "quality": 999.0,
        }
    )
    selected = select_fundamental_vintages(
        pd.DataFrame(fundamentals), information_cutoff=DECISION_TIME
    )
    assert "future-perfect-revision" not in set(selected.frame["revision_id"])
    cross_section = process_cross_section(
        selected.frame,
        (
            FactorSpec(
                "quality",
                minimum_observations=5,
                sector_neutral=True,
                size_neutral=True,
            ),
        ),
        as_of=DECISION_TIME,
        minimum_required_factors=1,
    )
    output: list[AlphaSignal] = []
    for _, row in cross_section.frame.iterrows():
        normalized = float(row["quality__normalized"])
        output.append(
            AlphaSignal(
                symbol=str(row["permanent_security_id"]),
                as_of=DECISION_TIME - timedelta(hours=1),
                signal_type="Quality",
                expected_excess_return=0.006 + max(normalized, 0.0) * 0.001,
                horizon=20,
                raw_signal=float(row["quality__raw"]),
                normalized_signal=normalized,
                confidence=0.80,
                confidence_calibrated=True,
                sample_size=180,
                statistical_strength=0.75,
                economic_strength=0.65,
                decay_half_life=40,
                valid_until=DECISION_TIME + timedelta(days=5),
                data_quality=AlphaDataQuality.VALID,
                pit_valid=True,
                validation_status=AlphaValidationStatus.PRODUCTION_APPROVED,
                model_version="mini-locked-factor-v1",
                data_version="mini-data-v1",
            )
        )
    return tuple(output)


def _returns() -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(20240808)
    market = np.concatenate(
        [rng.normal(0.0004, 0.006, 40), rng.normal(-0.0002, 0.016, 40)]
    )
    frame = pd.DataFrame(
        {
            symbol: 0.75 * market + rng.normal(0.0001 * index, 0.005, 80)
            for index, symbol in enumerate(SYMBOLS)
        },
        index=pd.bdate_range("2023-08-01", periods=80),
    )
    frame.loc[frame.index[:4], "EEE"] = np.nan  # IPO history begins later.
    return frame, pd.Series(market, index=frame.index)


def _constraints() -> PortfolioConstraints:
    return PortfolioConstraints(
        maximum_position_weight=0.25,
        maximum_sector_weight=0.55,
        maximum_cluster_weight=0.70,
        maximum_hhi=0.30,
        minimum_cash_weight=0.20,
        maximum_gross_exposure=0.80,
        target_annualized_volatility=0.22,
        maximum_beta=1.10,
        maximum_turnover=0.75,
        maximum_size_exposure=0.60,
        no_trade_band=0.002,
        minimum_rebalance_weight=0.003,
        minimum_trade_value=50,
        risk_aversion=2.5,
        turnover_penalty=0.001,
        model_validation_id="mini-oos-validation-v1",
    )


def _run_daily():
    returns, benchmark = _returns()
    metadata = tuple(
        AssetRiskMetadata(
            symbol,
            "Technology" if index < 3 else "Healthcare",
            100_000_000 + index * 20_000_000,
            (index - 2) / 5,
        )
        for index, symbol in enumerate(SYMBOLS)
    )
    return DailyQuantPipeline(
        construction=PortfolioConstructionEngine(_constraints())
    ).run(
        DailyQuantInput(
            authorization=_authorization(),
            decision_time=DECISION_TIME,
            alpha_signals=_pit_factors(),
            returns=returns,
            benchmark_returns=benchmark,
            risk_metadata=metadata,
            current_weights={},
            portfolio_value=1_000_000,
            portfolio_risk_state=PortfolioRiskState(
                -0.04,
                0.20,
                0.0,
                0.0,
                0.55,
                0.30,
            ),
            regime=RegimeRiskInput(0.10, 0.25, 0.65, 0.80, True, "regime-cal-v1"),
            pit_valid=True,
            universe_snapshot_id="mini-universe-v1",
            data_quality="VALID",
        )
    )


def _backtest_dataset() -> ProductionBacktestDataset:
    sessions = _sessions()
    bars: list[BacktestBar] = []
    for index, session in enumerate(sessions):
        for symbol, asset_id in ASSET_IDS.items():
            if symbol == "EEE" and index < 4:
                continue
            if symbol == "EEE" and index >= 60:
                continue
            if symbol == "CCC" and index == 40:
                continue
            price = 100 + index * (0.05 + asset_id * 0.01)
            if symbol == "AAA" and index >= 20:
                price /= 2
            close_time = market_close_utc(session, "US")
            bars.append(
                BacktestBar(
                    asset_id,
                    symbol,
                    "US",
                    session,
                    price,
                    price,
                    price,
                    price,
                    price,
                    10_000_000,
                    "mini-primary",
                    "point_in_time_total_return",
                    "fixture",
                    close_time,
                    close_time + timedelta(minutes=5),
                    close_time + timedelta(minutes=10),
                    True,
                )
            )
    universe = UniversePoint(
        1,
        sessions[5],
        datetime.combine(sessions[5], time(20), UTC),
        frozenset(ASSET_IDS.values()),
        "mini-certified-universe",
    )
    actions = (
        CorporateAction(
            ASSET_IDS["AAA"],
            CorporateActionType.SPLIT,
            sessions[20],
            sessions[10],
            datetime.combine(sessions[10], time(20), UTC),
            ratio=2,
            source="mini-actions",
        ),
        CorporateAction(
            ASSET_IDS["BBB"],
            CorporateActionType.CASH_DIVIDEND,
            sessions[30],
            sessions[15],
            datetime.combine(sessions[15], time(20), UTC),
            cash_amount=0.5,
            source="mini-actions",
        ),
        CorporateAction(
            ASSET_IDS["EEE"],
            CorporateActionType.DELISTING,
            sessions[60],
            sessions[50],
            datetime.combine(sessions[50], time(20), UTC),
            cash_amount=104.0,
            source="mini-actions",
        ),
    )
    return ProductionBacktestDataset(
        tuple(bars),
        sessions,
        "mini-verified-us-calendar",
        (universe,),
        actions,
        True,
        True,
        "mini-data-v1",
    )


def test_miniature_market_runs_deterministic_full_chain() -> None:
    daily = _run_daily()
    assert daily.status is ProductionPipelineStatus.READY, daily.blockers
    assert daily.target is not None and daily.target.production_approved
    dataset = _backtest_dataset()
    target = BacktestTarget(
        DECISION_TIME,
        dataset.calendar[6],
        {
            ASSET_IDS[symbol]: weight
            for symbol, weight in daily.target.target_weights.items()
        },
        1,
        "mini-data-v1",
        daily.target.model_version,
        "PRODUCTION_APPROVED",
        {
            ASSET_IDS[symbol]: {"Quality": 1.0}
            for symbol in daily.target.target_weights
        },
        "mini-parameter-lock-sha256",
        daily.target.model_validation_id,
    )
    cost_model = TransactionCostModel(
        TransactionCostConfig(maximum_adv_participation=0.10)
    )
    result = ProductionBacktestEngine(cost_model).run(
        dataset,
        (target,),
        ProductionBacktestConfig(
            initial_capital=1_000_000,
            minimum_sessions=60,
            git_commit="mini-fixture",
            benchmark_returns=tuple((session, 0.0) for session in dataset.calendar[1:]),
        ),
        sectors={
            asset_id: ("Technology" if asset_id <= 3 else "Healthcare")
            for asset_id in ASSET_IDS.values()
        },
    )
    repeated = ProductionBacktestEngine(cost_model).run(
        dataset,
        (target,),
        ProductionBacktestConfig(
            initial_capital=1_000_000,
            minimum_sessions=60,
            git_commit="mini-fixture",
            benchmark_returns=tuple((session, 0.0) for session in dataset.calendar[1:]),
        ),
        sectors={
            asset_id: ("Technology" if asset_id <= 3 else "Healthcare")
            for asset_id in ASSET_IDS.values()
        },
    )
    assert result.status == "PRODUCTION_APPROVED"
    assert result.result_hash == repeated.result_hash
    assert result.run_manifest_hash == repeated.run_manifest_hash
    assert result.metrics.transaction_cost > 0
    assert result.alpha_source_contribution
    assert daily.decision is not None and not daily.decision.automatic_execution_allowed
    golden = loads(
        Path("tests/fixtures/quant_engine/part2_golden.json").read_text(encoding="utf-8")
    )
    assert result.result_hash == golden["result_hash"]
    assert result.run_manifest_hash == golden["manifest_hash"]
    assert result.points[-1].equity == pytest.approx(golden["ending_equity"])
    assert result.metrics.net_return == pytest.approx(golden["net_return"])
    assert len(result.trades) == golden["trade_count"]
    assert daily.target.target_weights == pytest.approx(golden["target_weights"])
