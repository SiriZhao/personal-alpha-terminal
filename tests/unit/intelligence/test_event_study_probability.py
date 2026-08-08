from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import numpy as np
import pandas as pd
import pytest

from personal_alpha_terminal.intelligence.event_study import (
    PointInTimeEventStudyEngine,
)
from personal_alpha_terminal.intelligence.probability import (
    ConditionalDefinition,
    ConditionalEvidenceEngine,
    ConditionalObservation,
)
from personal_alpha_terminal.intelligence.schemas import IntelligenceStatus
from personal_alpha_terminal.quant_engine.backtest.validation import (
    build_walk_forward_folds,
)
from personal_alpha_terminal.quant_engine.probability import (
    estimate_conditional_probability_2,
    evaluate_probability_calibration,
)
from tests.unit.intelligence.helpers import make_event


def test_event_study_uses_sessions_abnormal_returns_and_rejects_future_events() -> None:
    calendar = xcals.get_calendar("XNYS")
    sessions = calendar.sessions_in_range("2020-01-02", "2024-12-31")
    index = pd.DatetimeIndex(sessions)
    benchmark = pd.Series(np.power(1.0002, np.arange(len(index))), index=index)
    asset = pd.Series(np.power(1.0005, np.arange(len(index))), index=index)
    new_york = ZoneInfo("America/New_York")
    event_indices = tuple(range(20, len(index) - 25, 25))[:35]
    events = tuple(
        make_event(
            f"event-{position}",
            datetime.combine(
                index[position].date(),
                datetime.min.time(),
                new_york,
            ).replace(hour=16),
        )
        for position in event_indices
    )
    future = make_event(
        "future",
        datetime(2027, 1, 4, 16, tzinfo=new_york),
    )
    as_of = calendar.session_close(index[-1]).to_pydatetime() + timedelta(minutes=1)
    result = PointInTimeEventStudyEngine(bootstrap_resamples=1_000).run(
        (*events, future),
        asset_total_returns={"MSFT": asset},
        benchmark_total_return=benchmark,
        benchmark_symbol="SPY",
        as_of=as_of,
    )
    one_day = next(item for item in result.statistics if item.horizon == 1)
    assert result.status is IntelligenceStatus.READY
    assert future.event_id in result.rejected_event_ids
    assert one_day.status is IntelligenceStatus.READY
    assert one_day.sample_size == 35
    assert one_day.mean_abnormal_return is not None
    assert one_day.mean_abnormal_return > 0
    assert one_day.percentiles.keys() == {5, 25, 75, 95}
    assert one_day.expected_shortfall_5 is not None


def test_next_session_close_is_invisible_at_event_cutoff() -> None:
    calendar = xcals.get_calendar("XNYS")
    sessions = calendar.sessions_in_range("2026-08-03", "2026-08-14")
    index = pd.DatetimeIndex(sessions)
    values = pd.Series(np.linspace(100, 110, len(index)), index=index)
    observed = calendar.session_close(index[2]).to_pydatetime()
    event = make_event("no-future-close", observed)
    as_of = observed + timedelta(minutes=1)
    result = PointInTimeEventStudyEngine(bootstrap_resamples=1_000).run(
        (event,),
        asset_total_returns={"MSFT": values},
        benchmark_total_return=values,
        benchmark_symbol="SPY",
        as_of=as_of,
    )
    assert result.observations == ()
    assert result.status is IntelligenceStatus.INSUFFICIENT_SAMPLE


def test_conditional_probability_shrinks_small_samples_and_reports_calibration() -> None:
    invalid = estimate_conditional_probability_2(
        (0.1, 0.2),
        tuple(0.01 if index % 2 else -0.01 for index in range(60)),
        minimum_sample_size=30,
        effective_sample_size=2,
    )
    assert not invalid.valid
    estimate = estimate_conditional_probability_2(
        tuple([0.02] * 24 + [-0.01] * 16),
        tuple([0.01] * 50 + [-0.01] * 50),
        minimum_sample_size=30,
        effective_sample_size=32,
        prior_strength=20,
    )
    assert estimate.valid
    assert estimate.raw_probability == 0.6
    assert estimate.adjusted_probability is not None
    assert 0.5 < estimate.adjusted_probability < 0.6
    probabilities = tuple([0.2] * 50 + [0.8] * 50)
    outcomes = tuple([False] * 40 + [True] * 10 + [False] * 10 + [True] * 40)
    calibration = evaluate_probability_calibration(probabilities, outcomes)
    assert calibration.calibrated
    assert calibration.expected_calibration_error is not None
    assert len(calibration.reliability_buckets) == 2


def test_conditional_walk_forward_is_chronological_and_oos() -> None:
    sessions = tuple(pd.bdate_range("2018-01-01", periods=420).date)
    folds = build_walk_forward_folds(
        sessions,
        train_sessions=120,
        validation_sessions=60,
        test_sessions=60,
        step_sessions=60,
        embargo_sessions=2,
    )
    observations = tuple(
        ConditionalObservation(
            session=session,
            condition_matched=index % 2 == 0,
            forward_return=(0.02 if index % 4 != 0 else -0.01),
        )
        for index, session in enumerate(sessions)
    )
    result = ConditionalEvidenceEngine().walk_forward(
        ConditionalDefinition("earnings-risk-on", ("event", "regime"), 5),
        observations,
        folds,
    )
    assert len(result.folds) >= 2
    assert all(item.fold_id > 0 for item in result.folds)
    first = result.folds[0]
    mutated = list(observations)
    last = mutated[-1]
    mutated[-1] = ConditionalObservation(
        last.session, -0.99, last.condition_matched, last.independent_weight, last.regime
    )
    rerun = ConditionalEvidenceEngine().walk_forward(
        result.definition, tuple(mutated), folds
    )
    assert rerun.folds[0].estimate == first.estimate


def test_conditional_definition_and_sample_guards_fail_closed() -> None:
    with pytest.raises(ValueError, match="six features"):
        ConditionalDefinition("too-many", tuple(f"f{i}" for i in range(7)), 5)
    with pytest.raises(ValueError, match="at least 30"):
        ConditionalEvidenceEngine(minimum_sample_size=29)
    sessions = tuple(pd.bdate_range("2020-01-01", periods=250).date)
    folds = build_walk_forward_folds(
        sessions,
        train_sessions=80,
        validation_sessions=40,
        test_sessions=40,
        step_sessions=40,
    )
    observations = tuple(
        ConditionalObservation(session, 0.01, True) for session in sessions
    )
    disabled = ConditionalEvidenceEngine().walk_forward(
        ConditionalDefinition("not-preregistered", ("event",), 5, preregistered=False),
        observations,
        folds,
    )
    assert disabled.status == "DISABLED"
    with pytest.raises(ValueError, match="chronological"):
        ConditionalEvidenceEngine().walk_forward(
            ConditionalDefinition("unordered", ("event",), 5),
            tuple(reversed(observations)),
            folds,
        )
