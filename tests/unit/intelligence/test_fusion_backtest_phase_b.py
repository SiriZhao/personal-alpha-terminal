from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from personal_alpha_terminal.intelligence.backtest_matrix import (
    BacktestMatrixEvaluator,
    BacktestVariantInput,
    IntelligenceVariant,
    SampleClassification,
)
from personal_alpha_terminal.intelligence.fusion import (
    ResearchFeatureType,
    SignalFusionConfig,
    ValidatedResearchFeature,
    ValidatedSignalFusion,
)
from personal_alpha_terminal.intelligence.research import PromotionStatus
from personal_alpha_terminal.intelligence.schemas import BacktestSafety

CUTOFF = datetime(2026, 8, 8, 20, tzinfo=UTC)


def _feature(status: PromotionStatus) -> ValidatedResearchFeature:
    return ValidatedResearchFeature(
        feature_id="narrative-feature-1",
        symbol="MSFT",
        feature_type=ResearchFeatureType.NARRATIVE,
        expected_return_lift=0.02,
        confidence=0.8,
        promotion_status=status,
        backtest_safety=BacktestSafety.BACKTEST_SAFE,
        data_cutoff=CUTOFF - timedelta(days=1),
        valid_until=CUTOFF + timedelta(days=5),
        source_ids=("event-1",),
        model_version="narrative-v1",
        data_version="data-v1",
        real_data_validated=True,
    )


def test_research_only_feature_cannot_change_quant_ranking() -> None:
    fusion = ValidatedSignalFusion(
        SignalFusionConfig(narrative_weight=0.05, max_narrative_feature_contribution=0.05)
    )
    result = fusion.fuse(
        "MSFT", (_feature(PromotionStatus.RESEARCH_ONLY),), as_of=CUTOFF
    )
    assert result.weighted_contribution == 0
    assert not result.applied_feature_ids
    assert result.unavailable_or_research_only


def test_manually_approved_real_pit_feature_respects_contribution_cap() -> None:
    fusion = ValidatedSignalFusion(
        SignalFusionConfig(narrative_weight=0.05, max_narrative_feature_contribution=0.05)
    )
    result = fusion.fuse(
        "MSFT", (_feature(PromotionStatus.PRODUCTION_APPROVED),), as_of=CUTOFF
    )
    assert result.applied_feature_ids == ("narrative-feature-1",)
    assert 0 < result.weighted_contribution <= 2.5


def _variant(variant: IntelligenceVariant) -> BacktestVariantInput:
    index = pd.date_range(end=CUTOFF, periods=80, freq="B", tz="UTC")
    gross = pd.Series(np.where(np.arange(80) % 3, 0.002, -0.001), index=index)
    net = gross - 0.0002
    return BacktestVariantInput(
        variant=variant,
        gross_returns=gross,
        net_returns=net,
        benchmark_returns=pd.Series(0.0005, index=index),
        turnover=pd.Series(0.02, index=index),
        exposure=pd.Series(0.8, index=index),
        sample_classification=SampleClassification.OUT_OF_SAMPLE,
        data_version="data-v1",
        model_version="model-v1",
        transaction_cost_model_version="cost-v1",
        backtest_safety=BacktestSafety.BACKTEST_SAFE,
    )


def test_backtest_matrix_is_cost_adjusted_oos_and_deterministic() -> None:
    evaluator = BacktestMatrixEvaluator()
    variants = (
        _variant(IntelligenceVariant.QUANT_ONLY),
        _variant(IntelligenceVariant.QUANT_EVENT),
        _variant(IntelligenceVariant.QUANT_EVENT_PROBABILITY),
        _variant(IntelligenceVariant.FULL_VALIDATED_INTELLIGENCE),
    )
    first = evaluator.evaluate(variants, data_cutoff=CUTOFF)
    second = evaluator.evaluate(variants, data_cutoff=CUTOFF)
    assert first == second
    assert first.comparison_status == "OOS_COMPARABLE"
    assert all(item.transaction_cost_drag > 0 for item in first.results)
    assert all(item.maximum_drawdown <= 0 for item in first.results)


def test_backtest_matrix_rejects_future_data() -> None:
    variant = _variant(IntelligenceVariant.QUANT_ONLY)
    with pytest.raises(ValueError, match="PIT cutoff"):
        BacktestMatrixEvaluator().evaluate(
            (variant,), data_cutoff=CUTOFF - timedelta(days=180)
        )
