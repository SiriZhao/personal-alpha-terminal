from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

import personal_alpha_terminal.quant_engine.portfolio.construction as construction_module
from personal_alpha_terminal.quant_engine.alpha import (
    AlphaDataQuality,
    AlphaSignal,
    AlphaValidationStatus,
)
from personal_alpha_terminal.quant_engine.portfolio.construction import (
    PortfolioConstraints,
    PortfolioConstructionEngine,
    PortfolioOperatingMode,
    PortfolioOptimizationStage,
)
from personal_alpha_terminal.quant_engine.portfolio.trades import (
    TradeAction,
    TradeGenerator,
)
from personal_alpha_terminal.quant_engine.risk.budget import RiskBudget
from personal_alpha_terminal.quant_engine.risk.drift import (
    RiskDriftStatus,
    evaluate_risk_drift,
)
from personal_alpha_terminal.quant_engine.risk.model import (
    RiskModelEstimate,
    RiskModelStatus,
    SizeExposureStatus,
    portfolio_volatility,
)
from personal_alpha_terminal.research.data_gate import (
    ResearchDataAuthorization,
    ResearchDataEvidence,
    ResearchDataGate,
    ResearchDataRequest,
    ResearchPurpose,
)

NOW = datetime(2026, 8, 18, 18, tzinfo=UTC)
SYMBOLS = ("A", "B", "C", "D")


def _authorization() -> ResearchDataAuthorization:
    request = ResearchDataRequest(
        ResearchPurpose.PORTFOLIO_DECISION,
        "US",
        "stock",
        date(2025, 1, 1),
        date(2026, 8, 17),
        NOW,
        "point_in_time_total_return",
        "round60-universe",
        timedelta(days=5),
    )
    evidence = ResearchDataEvidence(
        "US",
        "stock",
        "passed",
        "synthetic",
        "deterministic-fixture",
        ("round60-source-a", "round60-source-b"),
        NOW - timedelta(days=1),
        "certified",
        "point_in_time_total_return",
        "round60-universe",
        NOW - timedelta(days=2),
        True,
        True,
        0.0,
        0.0,
        0.0,
        0.0,
        "round60-data-v1",
        True,
        True,
        True,
        True,
    )
    return ResearchDataGate().authorize(request, evidence, evaluated_at=NOW)


def _alpha(symbol: str) -> AlphaSignal:
    return AlphaSignal(
        symbol=symbol,
        as_of=NOW - timedelta(hours=1),
        signal_type="momentum",
        expected_excess_return=0.012,
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
        model_version="round60-alpha-v1",
        data_version="round60-data-v1",
    )


def _risk() -> RiskModelEstimate:
    covariance = np.diag(np.full(len(SYMBOLS), 0.04, dtype=float))
    return RiskModelEstimate(
        symbols=SYMBOLS,
        annualized_covariance=covariance,
        correlation=np.eye(len(SYMBOLS), dtype=float),
        annualized_volatility=dict.fromkeys(SYMBOLS, 0.20),
        beta=dict.fromkeys(SYMBOLS, 0.80),
        sectors={"A": "TECH", "B": "TECH", "C": "HEALTH", "D": "HEALTH"},
        average_daily_dollar_volume=dict.fromkeys(SYMBOLS, 100_000_000.0),
        size_scores={"A": -0.3, "B": -0.1, "C": 0.1, "D": 0.3},
        size_exposure_status=SizeExposureStatus.VALID,
        observations=252,
        status=RiskModelStatus.VALID,
        condition_number=1.0,
        shrinkage=0.5,
        model_version="round60-risk-v1",
        limitations=(),
    )


def _constraints(**changes: float) -> PortfolioConstraints:
    base = PortfolioConstraints(
        maximum_position_weight=0.30,
        maximum_sector_weight=0.60,
        maximum_cluster_weight=0.60,
        maximum_hhi=0.40,
        minimum_cash_weight=0.15,
        maximum_gross_exposure=0.85,
        target_annualized_volatility=0.50,
        maximum_beta=1.10,
        maximum_turnover=0.80,
        maximum_size_exposure=0.50,
        no_trade_band=0.01,
        minimum_rebalance_weight=0.01,
        minimum_trade_value=0.0,
        risk_aversion=2.0,
        turnover_penalty=0.001,
        model_validation_id="round60-validation-v1",
    )
    return replace(base, **changes)


def _construct(
    *,
    current: dict[str, float],
    constraints: PortfolioConstraints,
    budget: RiskBudget | None = None,
):
    return PortfolioConstructionEngine(constraints).construct(
        authorization=_authorization(),
        alpha_signals=tuple(_alpha(symbol) for symbol in SYMBOLS),
        risk=_risk(),
        current_weights=current,
        portfolio_value=1_000_000.0,
        decision_time=NOW,
        risk_budget=budget or RiskBudget(1.0, 1.0, 1.0, True, ()),
    )


def test_primary_iteration_limit_uses_deterministic_feasibility_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_minimize = construction_module.minimize
    calls = 0

    def fail_primary_then_run_projection(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            return SimpleNamespace(
                success=False,
                message="Iteration limit reached",
                nit=500,
                x=np.asarray(args[1], dtype=float),
            )
        return real_minimize(*args, **kwargs)

    monkeypatch.setattr(construction_module, "minimize", fail_primary_then_run_projection)
    target = _construct(
        current=dict.fromkeys(SYMBOLS, 0.10),
        constraints=_constraints(),
    )

    assert target.production_approved, target.blockers
    assert target.optimization_stage is PortfolioOptimizationStage.FEASIBILITY_RECOVERY
    assert target.optimizer_provenance is not None
    assert target.optimizer_provenance["primary_success"] is False
    assert target.optimizer_provenance["optimizer_status"] == "FEASIBILITY_RECOVERY_PASS"


@pytest.mark.parametrize(
    ("current", "proposed", "changes", "mandatory_symbol"),
    [
        (
            {"A": 0.303, "B": 0.10, "C": 0.10, "D": 0.10},
            np.asarray([0.30, 0.10, 0.10, 0.10]),
            {"maximum_position_weight": 0.30},
            "A",
        ),
        (
            {"A": 0.251, "B": 0.251, "C": 0.10, "D": 0.10},
            np.asarray([0.249, 0.251, 0.10, 0.10]),
            {"maximum_sector_weight": 0.50},
            "A",
        ),
        (
            {"A": 0.252, "B": 0.20, "C": 0.20, "D": 0.20},
            np.asarray([0.25, 0.20, 0.20, 0.20]),
            {"maximum_gross_exposure": 0.85},
            "A",
        ),
    ],
)
def test_no_trade_threshold_never_suppresses_mandatory_risk_repair(
    monkeypatch: pytest.MonkeyPatch,
    current: dict[str, float],
    proposed: np.ndarray,
    changes: dict[str, float],
    mandatory_symbol: str,
) -> None:
    monkeypatch.setattr(
        construction_module,
        "minimize",
        lambda *_args, **_kwargs: SimpleNamespace(
            success=True,
            message="synthetic primary pass",
            nit=1,
            x=proposed,
        ),
    )
    target = _construct(current=current, constraints=_constraints(**changes))

    assert target.production_approved, target.blockers
    assert mandatory_symbol in target.risk_repair_symbols
    trades = TradeGenerator().generate(
        target=target,
        current_weights=current,
        portfolio_value=1_000_000.0,
        evidence={},
        risk_contribution={},
        average_daily_dollar_volume=_risk().average_daily_dollar_volume,
        minimum_trade_weight=0.01,
        mandatory_trade_symbols=frozenset(target.risk_repair_symbols),
    )
    repaired = next(item for item in trades if item.ticker == mandatory_symbol)
    assert repaired.action is TradeAction.REDUCE
    assert repaired.delta_weight < 0


def test_valid_tiny_alpha_rebalance_remains_suppressed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = dict.fromkeys(SYMBOLS, 0.10)
    proposed = np.asarray([0.102, 0.098, 0.10, 0.10])
    monkeypatch.setattr(
        construction_module,
        "minimize",
        lambda *_args, **_kwargs: SimpleNamespace(
            success=True,
            message="synthetic primary pass",
            nit=1,
            x=proposed,
        ),
    )

    target = _construct(current=current, constraints=_constraints())

    assert target.production_approved, target.blockers
    assert target.target_weights == pytest.approx(current)
    assert target.risk_repair_symbols == ()


def test_mandatory_repair_that_still_violates_another_constraint_remains_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = {"A": 0.303, "B": 0.20, "C": 0.20, "D": 0.20}
    proposed = np.asarray([0.30, 0.20, 0.20, 0.20])
    monkeypatch.setattr(
        construction_module,
        "minimize",
        lambda *_args, **_kwargs: SimpleNamespace(
            success=True,
            message="synthetic invalid recovery",
            nit=1,
            x=proposed,
        ),
    )

    target = _construct(current=current, constraints=_constraints())

    assert not target.operational_approved
    assert target.optimization_stage is PortfolioOptimizationStage.BLOCKED
    assert target.blockers[0] == "PORTFOLIO_BLOCKED_NO_FEASIBLE_TARGET"


def test_severe_risk_routes_to_sell_only_without_new_or_increased_positions() -> None:
    current = {"A": 0.20, "B": 0.20}
    risk = _risk()
    target = _construct(
        current=current,
        constraints=_constraints(),
        budget=RiskBudget(0.40, 1.0, 1.0, False, ("severe observed risk",)),
    )

    assert target.production_approved, target.blockers
    assert target.operating_mode is PortfolioOperatingMode.RISK_REDUCTION_ONLY
    assert target.optimization_stage is PortfolioOptimizationStage.SELL_ONLY_FALLBACK
    assert all(
        target.target_weights.get(symbol, 0.0) <= current.get(symbol, 0.0) + 1e-8
        for symbol in SYMBOLS
    )
    assert set(target.target_weights) <= set(current)
    assert sum(target.target_weights.values()) <= sum(current.values()) + 1e-8
    assert target.cash_weight >= 1 - sum(current.values()) - 1e-8
    current_vector = np.asarray([current.get(symbol, 0.0) for symbol in SYMBOLS])
    target_vector = np.asarray([target.target_weights.get(symbol, 0.0) for symbol in SYMBOLS])
    assert portfolio_volatility(
        target_vector, risk.annualized_covariance
    ) <= portfolio_volatility(current_vector, risk.annualized_covariance) + 1e-8


def test_invalid_sell_only_recovery_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        construction_module,
        "minimize",
        lambda *_args, **_kwargs: SimpleNamespace(
            success=True,
            message="synthetic bound violation",
            nit=1,
            x=np.asarray([0.10, 0.10, 0.05, 0.0]),
        ),
    )
    target = _construct(
        current={"A": 0.20, "B": 0.20},
        constraints=_constraints(),
        budget=RiskBudget(0.40, 1.0, 1.0, False, ("severe observed risk",)),
    )

    assert not target.operational_approved
    assert target.blockers[0] == "PORTFOLIO_BLOCKED_NO_FEASIBLE_TARGET"
    assert target.optimizer_provenance is not None
    assert "sell-only fallback increased a position" in str(
        target.optimizer_provenance["attempts"]
    )


def _mark_to_market(
    weights: dict[str, float],
    multipliers: dict[str, float],
) -> dict[str, float]:
    cash = 1 - sum(weights.values())
    marked = {
        symbol: weight * multipliers.get(symbol, 1.0)
        for symbol, weight in weights.items()
    }
    total = cash + sum(marked.values())
    return {symbol: value / total for symbol, value in marked.items()}


def test_risk_drift_distinguishes_ok_warning_and_hard_breaches() -> None:
    risk = _risk()
    budget = RiskBudget(1.0, 1.0, 1.0, True, ())
    base = PortfolioConstraints(model_validation_id="round60-drift")

    ok = evaluate_risk_drift(
        current_weights={"A": 0.05, "B": 0.05, "C": 0.05, "D": 0.05},
        risk=risk,
        constraints=base,
        risk_budget=budget,
    )
    warning = evaluate_risk_drift(
        current_weights={"A": 0.11, "B": 0.05, "C": 0.05, "D": 0.05},
        risk=risk,
        constraints=base,
        risk_budget=budget,
    )
    position_breach = evaluate_risk_drift(
        current_weights=_mark_to_market(
            {"A": 0.11, "B": 0.05, "C": 0.05, "D": 0.05},
            {"A": 1.30},
        ),
        risk=risk,
        constraints=base,
        risk_budget=budget,
    )
    sector_breach = evaluate_risk_drift(
        current_weights=_mark_to_market(
            {"A": 0.10, "B": 0.09, "C": 0.05, "D": 0.05},
            {"A": 1.20, "B": 1.20},
        ),
        risk=risk,
        constraints=replace(base, maximum_sector_weight=0.20),
        risk_budget=budget,
    )
    hhi_breach = evaluate_risk_drift(
        current_weights=_mark_to_market(
            dict.fromkeys(SYMBOLS, 0.10),
            {"A": 4.0},
        ),
        risk=risk,
        constraints=replace(
            base,
            maximum_position_weight=0.50,
            maximum_sector_weight=1.0,
            maximum_cluster_weight=1.0,
            maximum_hhi=0.08,
        ),
        risk_budget=budget,
    )

    assert ok.status is RiskDriftStatus.OK
    assert ok.detail == "RISK DRIFT: OK"
    assert warning.status is RiskDriftStatus.WARNING
    assert position_breach.status is RiskDriftStatus.HARD_BREACH
    assert any(item.constraint == "SINGLE_NAME" for item in position_breach.events)
    assert any(item.constraint.startswith("SECTOR:") for item in sector_breach.events)
    assert any(item.constraint == "HHI" for item in hhi_breach.events)
    assert "RISK DRIFT: HARD BREACH" in position_breach.detail
