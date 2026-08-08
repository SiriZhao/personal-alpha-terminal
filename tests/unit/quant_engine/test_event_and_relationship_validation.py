from datetime import date, timedelta

import pandas as pd
import pytest

from personal_alpha_terminal.quant_engine.event_validation import validate_event_effects
from personal_alpha_terminal.quant_engine.relationship_validation import (
    RelationshipEvidence,
    RelationshipUse,
    validate_relationship_for_alpha,
)


def test_event_effect_reports_decay_and_chronological_stability() -> None:
    rows = []
    start = date(2020, 1, 1)
    for horizon, effect in ((1, 0.012), (5, 0.008), (20, 0.004)):
        rows.extend(
            {
                "event_id": f"{horizon}-{index}",
                "event_date": start + timedelta(days=index * 3),
                "horizon": horizon,
                "abnormal_return": effect + (index % 3 - 1) / 10_000,
                "regime": "risk_on" if index % 2 else "neutral",
            }
            for index in range(80)
        )
    result = validate_event_effects(pd.DataFrame(rows))
    assert result.peak_horizon == 1
    assert result.approximate_half_life == 20
    assert result.stable


def test_event_validation_rejects_duplicate_overlapping_event_ids() -> None:
    frame = pd.DataFrame(
        [
            {
                "event_id": "same",
                "event_date": "2024-01-01",
                "horizon": 5,
                "abnormal_return": 0.1,
            },
            {
                "event_id": "same",
                "event_date": "2024-01-02",
                "horizon": 5,
                "abnormal_return": 0.2,
            },
        ]
    )
    with pytest.raises(ValueError, match="deduplicated"):
        validate_event_effects(frame)


def test_relationship_needs_significance_oos_and_after_cost_value() -> None:
    valid = validate_relationship_for_alpha(
        RelationshipEvidence(0.01, 0.012, 0.002, 4, 0.75, 80)
    )
    false_edge = validate_relationship_for_alpha(
        RelationshipEvidence(0.01, 0.001, 0.002, 4, 0.75, 80)
    )
    assert valid.use is RelationshipUse.ALPHA_CANDIDATE
    assert false_edge.use is RelationshipUse.RESEARCH_INSIGHT
    assert "after cost" in false_edge.blockers[-1]
