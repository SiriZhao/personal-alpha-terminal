from __future__ import annotations

import json
from pathlib import Path

import pytest

from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
from personal_alpha_terminal.quant_engine.probability_assessment import (
    ProbabilityAssessmentRegistry,
    build_round4_probability_assessment,
)


def test_real_round4_assessment_is_hashed_non_promoting_and_idempotent(
    tmp_path: Path,
) -> None:
    source = Path("var/round4-research/latest.json")
    assessment = build_round4_probability_assessment(
        source,
        strategy_parameter_hash=EffectiveRuntimeConfig().strategy_parameter_hash,
    )

    assert assessment.verify_hash()
    assert assessment.verdict == "NO_INCREMENTAL_ALPHA"
    assert assessment.production_influence == 0.0
    assert assessment.target_change_count == 0
    assert assessment.brier_score > assessment.baseline_brier_score
    assert "AFTER_COST_OOS_NOT_IMPROVED" in assessment.blockers

    registry = ProbabilityAssessmentRegistry(tmp_path)
    first = registry.write(assessment)
    second = registry.write(assessment)
    assert first == second
    assert json.loads(first.read_text(encoding="utf-8"))["artifact_hash"] == (
        assessment.artifact_hash
    )


def test_probability_assessment_refuses_mutating_an_immutable_id(tmp_path: Path) -> None:
    assessment = build_round4_probability_assessment(
        Path("var/round4-research/latest.json"),
        strategy_parameter_hash=EffectiveRuntimeConfig().strategy_parameter_hash,
    )
    registry = ProbabilityAssessmentRegistry(tmp_path)
    path = registry.write(assessment)
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="immutable"):
        registry.write(assessment)
