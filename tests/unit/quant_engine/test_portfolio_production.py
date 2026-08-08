from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from personal_alpha_terminal.quant_engine.alpha import (
    AlphaDataQuality,
    AlphaSignal,
    AlphaValidationStatus,
)
from personal_alpha_terminal.quant_engine.attribution import attribute_portfolio_period
from personal_alpha_terminal.quant_engine.costs import (
    TransactionCostConfig,
    TransactionCostModel,
)
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
    DynamicRiskBudget,
    PortfolioRiskState,
    RegimeRiskInput,
    RiskBudget,
)
from personal_alpha_terminal.quant_engine.risk.model import (
    AssetRiskMetadata,
    PortfolioRiskModel,
    RiskModelConfig,
    RiskModelStatus,
)
from personal_alpha_terminal.research.data_gate import (
    ResearchDataAuthorization,
    ResearchDataEvidence,
    ResearchDataGate,
    ResearchDataRequest,
    ResearchPurpose,
)

NOW = datetime(2026, 8, 8, 21, tzinfo=UTC)
SYMBOLS = ("A", "B", "C", "D")


def _authorization() -> ResearchDataAuthorization:
    request = ResearchDataRequest(
        ResearchPurpose.PORTFOLIO_DECISION,
        "US",
        "stock",
        date(2025, 1, 1),
        date(2026, 8, 7),
        NOW,
        "point_in_time_total_return",
        "universe-v1",
        timedelta(days=5),
    )
    evidence = ResearchDataEvidence(
        "US",
        "stock",
        "passed",
        "primary",
        "fixture-adapter",
        ("source-a", "source-b"),
        NOW - timedelta(days=1),
        "certified",
        "point_in_time_total_return",
        "universe-v1",
        NOW - timedelta(days=2),
        True,
        True,
        0.0,
        0.0,
        0.0,
        0.0,
        "data-v1",
        True,
        True,
        True,
        True,
    )
    return ResearchDataGate().authorize(request, evidence, evaluated_at=NOW)


def _market_data(seed: int = 7) -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.default_rng(seed)
    market = rng.normal(0.0003, 0.009, 180)
    values = {
        symbol: 0.8 * market + rng.normal(0.0002 + index * 0.00005, 0.006, 180)
        for index, symbol in enumerate(SYMBOLS)
    }
    index = pd.bdate_range("2025-11-24", periods=180)
    return pd.DataFrame(values, index=index), pd.Series(market, index=index)


def _metadata() -> tuple[AssetRiskMetadata, ...]:
    return tuple(
        AssetRiskMetadata(
            symbol,
            "Technology" if index < 2 else "Healthcare",
            50_000_000 + index * 10_000_000,
            (index - 1.5) / 4,
        )
        for index, symbol in enumerate(SYMBOLS)
    )


def _alpha(symbol: str, expected: float = 0.012) -> AlphaSignal:
    return AlphaSignal(
        symbol=symbol,
        as_of=NOW - timedelta(hours=1),
        signal_type="momentum" if symbol in {"A", "B"} else "quality",
        expected_excess_return=expected,
        horizon=20,
        raw_signal=1.0,
        normalized_signal=0.8,
        confidence=0.8,
        confidence_calibrated=True,
        sample_size=200,
        statistical_strength=0.75,
        economic_strength=0.70,
        decay_half_life=40,
        valid_until=NOW + timedelta(days=3),
        data_quality=AlphaDataQuality.VALID,
        pit_valid=True,
        validation_status=AlphaValidationStatus.PRODUCTION_APPROVED,
        model_version="alpha-v1",
        data_version="data-v1",
    )


def _constraints() -> PortfolioConstraints:
    return PortfolioConstraints(
        maximum_position_weight=0.30,
        maximum_sector_weight=0.50,
        maximum_cluster_weight=0.60,
        maximum_hhi=0.30,
        minimum_cash_weight=0.15,
        maximum_gross_exposure=0.85,
        target_annualized_volatility=0.25,
        maximum_beta=1.10,
        maximum_turnover=0.80,
        maximum_size_exposure=0.50,
        no_trade_band=0.002,
        minimum_rebalance_weight=0.003,
        minimum_trade_value=50,
        risk_aversion=2.0,
        turnover_penalty=0.001,
        model_validation_id="fixture-oos-validation-v1",
    )


def _risk():
    returns, benchmark = _market_data()
    return PortfolioRiskModel().fit(
        returns,
        metadata=_metadata(),
        benchmark_returns=benchmark,
    )


def test_transaction_cost_model_requires_adv_and_separates_components() -> None:
    model = TransactionCostModel()
    estimate = model.estimate(
        trade_value=100_000,
        average_daily_dollar_volume=20_000_000,
    )
    assert estimate.total_cost == pytest.approx(
        estimate.commission + estimate.spread + estimate.slippage + estimate.market_impact
    )
    assert estimate.participation_rate == pytest.approx(0.005)
    with pytest.raises(ValueError, match="ADV"):
        model.estimate(trade_value=100, average_daily_dollar_volume=0)


def test_attribution_reconciles_symbol_sector_alpha_risk_and_cost() -> None:
    report = attribute_portfolio_period(
        starting_weights={"A": 0.2, "B": 0.3},
        asset_returns={"A": 0.05, "B": -0.02},
        sectors={"A": "Technology", "B": "Healthcare"},
        alpha_source_weights={
            "A": {"Momentum/Trend": 0.7, "Quality": 0.3},
            "B": {"Volatility": 1.0},
        },
        covariance=np.array([[0.04, 0.01], [0.01, 0.03]]),
        symbol_order=("A", "B"),
        regime_adjustment=-0.001,
        risk_reduction=0.0005,
        transaction_cost_drag=0.0002,
    )
    assert sum(report.symbol_contribution.values()) == pytest.approx(0.004)
    assert sum(report.sector_contribution.values()) == pytest.approx(0.004)
    assert sum(report.alpha_source_contribution.values()) == pytest.approx(0.004)
    assert sum(report.risk_contribution.values()) == pytest.approx(1.0)
    assert report.reconciled_total == pytest.approx(0.0033)


def test_ledoit_wolf_risk_model_is_psd_and_reports_exposures() -> None:
    risk = _risk()
    assert risk.status is RiskModelStatus.VALID
    assert risk.observations == 180
    assert np.linalg.eigvalsh(risk.annualized_covariance).min() > 0
    assert set(risk.beta) == set(SYMBOLS)
    assert risk.sectors["A"] == "Technology"


def test_zero_variance_and_insufficient_covariance_fail_closed() -> None:
    returns, benchmark = _market_data()
    returns["A"] = 0.0
    risk = PortfolioRiskModel().fit(
        returns,
        metadata=_metadata(),
        benchmark_returns=benchmark,
    )
    assert risk.status is RiskModelStatus.BLOCKED
    short = PortfolioRiskModel(RiskModelConfig(minimum_observations=200)).fit(
        returns,
        metadata=_metadata(),
        benchmark_returns=benchmark,
    )
    assert short.status is RiskModelStatus.BLOCKED


def test_dynamic_risk_budget_ignores_uncalibrated_probability() -> None:
    state = PortfolioRiskState(-0.02, 0.12, 0.8, 0.12, 0.3, 0.25)
    uncalibrated = RegimeRiskInput(0.05, 0.05, 0.90, 1.0, False, "score-v1")
    calibrated = replace(uncalibrated, calibrated=True, model_version="calibrated-v1")
    engine = DynamicRiskBudget()
    raw = engine.evaluate(
        regime=uncalibrated,
        state=state,
        configured_target_volatility=0.15,
    )
    reduced = engine.evaluate(
        regime=calibrated,
        state=state,
        configured_target_volatility=0.15,
    )
    assert "ignored" in raw.reasons[0]
    assert reduced.gross_exposure_multiplier < raw.gross_exposure_multiplier


def test_optimizer_uses_alpha_risk_cost_and_constraints() -> None:
    cost_model = TransactionCostModel(
        TransactionCostConfig(maximum_adv_participation=0.05)
    )
    engine = PortfolioConstructionEngine(_constraints(), cost_model)
    target = engine.construct(
        authorization=_authorization(),
        alpha_signals=tuple(_alpha(symbol) for symbol in SYMBOLS),
        risk=_risk(),
        current_weights={},
        portfolio_value=1_000_000,
        decision_time=NOW,
        risk_budget=RiskBudget(1.0, 1.0, 1.0, True, ()),
    )
    assert target.production_approved, target.blockers
    assert 0 < sum(target.target_weights.values()) <= 0.85
    assert max(target.target_weights.values()) <= 0.30 + 1e-6
    assert target.cash_weight >= 0.15 - 1e-6
    assert target.turnover <= 0.80 + 1e-6
    assert target.expected_volatility is not None and target.expected_volatility <= 0.25
    assert target.estimated_transaction_cost > 0
    assert target.alpha_contributions
    unvalidated = PortfolioConstructionEngine(
        replace(_constraints(), model_validation_id=None), cost_model
    ).construct(
        authorization=_authorization(),
        alpha_signals=tuple(_alpha(symbol) for symbol in SYMBOLS),
        risk=_risk(),
        current_weights={},
        portfolio_value=1_000_000,
        decision_time=NOW,
        risk_budget=RiskBudget(1.0, 1.0, 1.0, True, ()),
    )
    assert not unvalidated.production_approved
    assert "OOS validation" in unvalidated.blockers[0]


def test_no_trade_band_preserves_small_rebalance_and_optimizer_failure_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = dict.fromkeys(SYMBOLS, 0.10)
    constraints = replace(
        _constraints(),
        no_trade_band=1.0,
        minimum_rebalance_weight=0.0,
        minimum_trade_value=0.0,
    )
    target = PortfolioConstructionEngine(constraints).construct(
        authorization=_authorization(),
        alpha_signals=tuple(_alpha(symbol) for symbol in SYMBOLS),
        risk=_risk(),
        current_weights=current,
        portfolio_value=1_000_000,
        decision_time=NOW,
        risk_budget=RiskBudget(1.0, 1.0, 1.0, True, ()),
    )
    assert target.production_approved
    assert target.target_weights == pytest.approx(current)
    assert target.turnover == pytest.approx(0.0)

    def fail_optimizer(*args: object, **kwargs: object) -> object:
        raise ValueError("synthetic optimizer failure")

    monkeypatch.setattr(PortfolioConstructionEngine, "construct", fail_optimizer)
    returns, benchmark = _market_data()
    blocked = DailyQuantPipeline(construction=PortfolioConstructionEngine()).run(
        DailyQuantInput(
            authorization=_authorization(),
            decision_time=NOW,
            alpha_signals=tuple(_alpha(symbol) for symbol in SYMBOLS),
            returns=returns,
            benchmark_returns=benchmark,
            risk_metadata=_metadata(),
            current_weights={},
            portfolio_value=1_000_000,
            portfolio_risk_state=PortfolioRiskState(-0.01, 0.12, 0, 0, 0.3, 0.25),
            regime=None,
            pit_valid=True,
            universe_snapshot_id="universe-v1",
            data_quality="VALID",
        )
    )
    assert blocked.status is ProductionPipelineStatus.BLOCKED
    assert "optimizer failure" in blocked.blockers[0]


@pytest.mark.parametrize("seed", range(5))
def test_optimizer_property_constraints_hold(seed: int) -> None:
    returns, benchmark = _market_data(seed + 20)
    risk = PortfolioRiskModel().fit(
        returns,
        metadata=_metadata(),
        benchmark_returns=benchmark,
    )
    target = PortfolioConstructionEngine(_constraints()).construct(
        authorization=_authorization(),
        alpha_signals=tuple(_alpha(symbol, 0.008 + seed * 0.0002) for symbol in SYMBOLS),
        risk=risk,
        current_weights={},
        portfolio_value=1_000_000,
        decision_time=NOW,
        risk_budget=RiskBudget(1.0, 1.0, 1.0, True, ()),
    )
    assert target.production_approved, target.blockers
    assert all(np.isfinite(value) and value >= 0 for value in target.target_weights.values())
    assert sum(target.target_weights.values()) <= 0.85 + 1e-6
    assert all(value <= 0.30 + 1e-6 for value in target.target_weights.values())


def test_daily_pipeline_blocks_unapproved_alpha_and_runs_without_ai() -> None:
    returns, benchmark = _market_data()
    base = DailyQuantInput(
        authorization=_authorization(),
        decision_time=NOW,
        alpha_signals=tuple(_alpha(symbol) for symbol in SYMBOLS),
        returns=returns,
        benchmark_returns=benchmark,
        risk_metadata=_metadata(),
        current_weights={},
        portfolio_value=1_000_000,
        portfolio_risk_state=PortfolioRiskState(-0.01, 0.12, 0.0, 0.0, 0.3, 0.25),
        regime=None,
        pit_valid=True,
        universe_snapshot_id="universe-v1",
        data_quality="VALID",
    )
    pipeline = DailyQuantPipeline(
        construction=PortfolioConstructionEngine(_constraints())
    )
    ready = pipeline.run(base)
    assert ready.status is ProductionPipelineStatus.READY, ready.blockers
    assert ready.target is not None and ready.target.production_approved
    assert ready.trades
    assert ready.decision is not None
    assert not ready.decision.automatic_execution_allowed
    blocked = pipeline.run(
        replace(
            base,
            alpha_signals=tuple(
                replace(item, validation_status=AlphaValidationStatus.TESTED)
                for item in base.alpha_signals
            ),
        )
    )
    assert blocked.status is ProductionPipelineStatus.BLOCKED
    assert blocked.trades == ()
    future_returns = returns.copy()
    future_returns.loc[pd.Timestamp("2026-08-10")] = 0.0
    future = pipeline.run(replace(base, returns=future_returns))
    assert future.status is ProductionPipelineStatus.BLOCKED
    assert "after decision_time" in future.blockers[0]
