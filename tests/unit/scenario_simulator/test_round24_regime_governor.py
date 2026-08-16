"""ROUND24 regime engine v1 + drawdown governor + crowding + research agenda tests."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from personal_alpha_terminal.quant_engine.risk.drawdown_governor import (
    GovernorInputs,
    GovernorState,
    evaluate_governor,
)
from personal_alpha_terminal.quant_engine.risk.factor_crowding import (
    diagnose_factor_crash_risk,
)
from personal_alpha_terminal.quant_engine.round24_alpha_candidates import (
    CANDIDATES,
    CandidateStatus,
    research_agenda_document,
)
from personal_alpha_terminal.scenario_simulator.regime_engine_v1 import (
    RegimeInputs,
    classify_regime,
    compute_regime_inputs,
)


def test_regime_risk_on() -> None:
    verdict = classify_regime(
        RegimeInputs(
            spy_return_63=0.10,
            qqq_return_63=0.12,
            spy_above_ma200=True,
            qqq_above_ma200=True,
            breadth_pct_above_ma50=0.70,
            cross_sectional_dispersion_21=None,
            realized_volatility_21=0.15,
            average_pairwise_correlation_21=0.40,
            universe_adv_ratio_63=1.1,
            spy_drawdown_252=-0.03,
        ),
        as_of_date=date(2026, 8, 13),
    )
    assert verdict.regime == "RISK_ON"
    assert verdict.model_status == "OBSERVATION_ONLY"


def test_regime_stress() -> None:
    verdict = classify_regime(
        RegimeInputs(
            spy_return_63=-0.25,
            qqq_return_63=-0.30,
            spy_above_ma200=False,
            qqq_above_ma200=False,
            breadth_pct_above_ma50=0.10,
            cross_sectional_dispersion_21=None,
            realized_volatility_21=0.50,
            average_pairwise_correlation_21=0.85,
            universe_adv_ratio_63=0.40,
            spy_drawdown_252=-0.22,
        ),
        as_of_date=date(2026, 8, 13),
    )
    assert verdict.regime in {"STRESS", "RISK_OFF"}


def test_regime_neutral() -> None:
    verdict = classify_regime(
        RegimeInputs(
            spy_return_63=-0.01,
            qqq_return_63=0.0,
            spy_above_ma200=None,
            qqq_above_ma200=None,
            breadth_pct_above_ma50=0.5,
            cross_sectional_dispersion_21=None,
            realized_volatility_21=0.18,
            average_pairwise_correlation_21=0.5,
            universe_adv_ratio_63=1.0,
            spy_drawdown_252=-0.05,
        ),
        as_of_date=date(2026, 8, 13),
    )
    assert verdict.regime == "NEUTRAL"


def test_regime_inputs_from_pit_frames() -> None:
    dates = pd.date_range("2024-08-01", periods=300, freq="B")
    rows: list[dict[str, object]] = []
    for index, session in enumerate(dates):
        rows.append(
            {"symbol": "SPY", "trade_date": session, "close": 100 * np.exp(0.0005 * index)}
        )
        rows.append(
            {"symbol": "QQQ", "trade_date": session, "close": 100 * np.exp(0.0007 * index)}
        )
    benchmark = pd.DataFrame(rows)
    inputs = compute_regime_inputs(benchmark, None, as_of_date=dates[-1].date())
    assert inputs.spy_above_ma200 is True
    assert inputs.spy_return_63 is not None
    assert inputs.spy_return_63 > 0


def test_governor_activates_with_hysteresis() -> None:
    advice, state = evaluate_governor(
        GovernorInputs(
            portfolio_drawdown=-0.30,
            benchmark_drawdown=-0.20,
            realized_volatility=0.50,
            correlation_spike=True,
        )
    )
    assert not state.active
    assert advice.action == "NO_ACTION"
    advice, state = evaluate_governor(
        GovernorInputs(-0.30, -0.20, 0.50, True),
        previous=state,
    )
    advice, state = evaluate_governor(
        GovernorInputs(-0.30, -0.20, 0.50, True),
        previous=state,
    )
    assert state.active
    assert advice.action == "REDUCE_GROSS_AND_INCREASE_CASH"
    assert advice.freeze_new_buys and advice.increase_cash


def test_governor_no_churn_on_recovery() -> None:
    state = GovernorState(active=True, severity=2, consecutive_observations=3)
    advice, next_state = evaluate_governor(
        GovernorInputs(-0.05, -0.02, 0.20, False),
        previous=state,
    )
    # still active while hysteresis clears
    assert next_state.active or advice.action in {"NO_ACTION", "FREEZE_NEW_BUYS"}


def test_factor_crowding_diagnostics() -> None:
    diagnostics = diagnose_factor_crash_risk(
        factor_exposures={"momentum": 0.9, "trend": 0.1},
        cross_sectional_dispersion=0.02,
        dispersion_reference=0.05,
        momentum_recent_return=-0.15,
        average_correlation=0.80,
    )
    assert diagnostics.momentum_reversal_flag
    assert diagnostics.correlation_spike_flag
    assert diagnostics.single_factor_dominance == "momentum"
    assert any("FACTOR_CROWDING" in warning for warning in diagnostics.warnings)


def test_research_agenda_fundamentals_blocked() -> None:
    by_name = {item.name: item for item in CANDIDATES}
    assert by_name["value"].status is CandidateStatus.BLOCKED_BY_PIT_FUNDAMENTALS
    assert by_name["quality"].status is CandidateStatus.BLOCKED_BY_PIT_FUNDAMENTALS
    assert by_name["residual_momentum"].status is CandidateStatus.RESEARCH_CANDIDATE
    assert by_name["residual_momentum"].price_only
    document = research_agenda_document()
    assert document["auto_promotion"] is False
    assert document["classical_champion_unchanged"] is True
    assert len(document["promotion_gates"]) == 7
