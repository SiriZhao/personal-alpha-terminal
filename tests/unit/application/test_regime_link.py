"""Contract tests for the read-only market-regime link.

Part 3 requirement 3: regime is an optional overlay.  Only a walk-forward
calibrated run with validated point-in-time probabilities may feed the risk
budget; score-only or missing evidence must leave the core pipeline untouched.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from personal_alpha_terminal.application.regime_link import (
    REGIME_UNAVAILABLE,
    latest_regime_link,
)
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.data.database import build_engine
from personal_alpha_terminal.models import (
    Base,
    MarketRegimeObservation,
    MarketRegimeRun,
    Stock,
)
from personal_alpha_terminal.quant_engine.risk.budget import RegimeRiskInput

DECISION_TIME = datetime(2027, 8, 6, 22, 0, tzinfo=UTC)
SETTINGS = Settings(_env_file=None, database_url="sqlite://")


def _seed_run(
    session: Session,
    *,
    calibration_status: str,
    end_date: date,
    probabilities: bool,
) -> MarketRegimeRun:
    existing = session.get(Stock, 1)
    if existing is None:
        session.add(
            Stock(
                canonical_code="US:XCBO:^VIX",
                symbol="^VIX",
                name="CBOE Volatility Index",
                market="US",
                exchange="XCBO",
                asset_type="index",
                currency="USD",
                timezone="America/New_York",
                source="fixture",
                provider="isolated-test",
            )
        )
        session.flush()
    run = MarketRegimeRun(
        start_date=end_date - timedelta(days=300),
        end_date=end_date,
        market="US",
        model_type="statistical",
        model_version="regime-v1",
        vix_stock_id=1,
        rate_stock_id=1,
        dollar_stock_id=1,
        benchmark_stock_id=1,
        status="completed",
        parameters={
            "probability_label_horizon": 20,
            "probability_return_threshold": 0.02,
            "probability_minimum_training_observations": 252,
        },
        calibration_status=calibration_status,
        calibration_method="walk-forward-beta",
        calibration_observation_count=60,
        brier_score=Decimal("0.18") if calibration_status == "calibrated" else None,
    )
    session.add(run)
    session.flush()
    session.add(
        MarketRegimeObservation(
            run_id=run.id,
            as_of_date=end_date,
            regime="risk_off",
            risk_on_score=Decimal("0.10"),
            risk_off_score=Decimal("0.65"),
            neutral_score=Decimal("0.25"),
            risk_on_probability=Decimal("0.10") if probabilities else None,
            risk_off_probability=Decimal("0.65") if probabilities else None,
            neutral_probability=Decimal("0.25") if probabilities else None,
            composite_score=Decimal("0.42"),
            breadth_constituent_count=12,
            feature_values={"vix_level": 22.0},
            feature_zscores={"vix_level": 1.1},
            feature_contributions={"vix_level": 0.2},
        )
    )
    session.flush()
    return run


def test_no_regime_run_is_optional_unavailable() -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        link = latest_regime_link(session, SETTINGS, decision_time=DECISION_TIME)
    assert link.regime_input is None
    assert link.display_status == REGIME_UNAVAILABLE
    assert "REGIME OPTIONAL" in link.detail
    engine.dispose()


def test_score_only_regime_never_enters_risk_budget() -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_run(
            session,
            calibration_status="score_only",
            end_date=DECISION_TIME.date(),
            probabilities=False,
        )
        link = latest_regime_link(session, SETTINGS, decision_time=DECISION_TIME)
    assert link.regime_input is None
    assert link.display_status == "REGIME_OPTIONAL_RISK_OFF_SCORE_ONLY"
    assert "never change alpha" in link.detail
    engine.dispose()


def test_calibrated_regime_feeds_risk_budget_with_pit_probability() -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_run(
            session,
            calibration_status="calibrated",
            end_date=DECISION_TIME.date(),
            probabilities=True,
        )
        link = latest_regime_link(session, SETTINGS, decision_time=DECISION_TIME)
    assert isinstance(link.regime_input, RegimeRiskInput)
    assert link.regime_input.calibrated is True
    assert link.regime_input.risk_off_probability == 0.65
    assert link.display_status == "REGIME_CALIBRATED_RISK_OFF"
    assert "walk-forward calibrated" in link.detail
    engine.dispose()


def test_future_regime_observation_is_not_visible_at_cutoff() -> None:
    """PIT guard: an observation dated after the decision cutoff must not be used."""

    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_run(
            session,
            calibration_status="calibrated",
            end_date=DECISION_TIME.date() + timedelta(days=5),
            probabilities=True,
        )
        link = latest_regime_link(session, SETTINGS, decision_time=DECISION_TIME)
    assert link.regime_input is None
    assert link.display_status == REGIME_UNAVAILABLE
    engine.dispose()


def test_calibrated_run_without_probabilities_stays_advisory() -> None:
    engine = build_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_run(
            session,
            calibration_status="calibrated",
            end_date=DECISION_TIME.date(),
            probabilities=False,
        )
        link = latest_regime_link(session, SETTINGS, decision_time=DECISION_TIME)
    assert link.regime_input is None
    assert link.display_status == "REGIME_OPTIONAL_RISK_OFF_SCORE_ONLY"
    engine.dispose()
