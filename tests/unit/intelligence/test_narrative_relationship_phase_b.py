from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from personal_alpha_terminal.intelligence.cross_asset import (
    CrossAssetContextEngine,
    CrossAssetDefinition,
)
from personal_alpha_terminal.intelligence.narrative import (
    NarrativeConfig,
    NarrativeDetectionEngine,
)
from personal_alpha_terminal.intelligence.relationship import (
    MarketRelationshipGraphEngine,
    RelationshipGraphConfig,
    RelationshipNode,
    RelationshipNodeType,
    RelationshipType,
)
from personal_alpha_terminal.intelligence.schemas import IntelligenceStatus
from personal_alpha_terminal.quant_engine.relationship_validation import RelationshipUse
from tests.unit.intelligence.helpers import make_event

CUTOFF = datetime(2026, 8, 8, 20, tzinfo=UTC)


def _returns() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    index = pd.date_range(end=CUTOFF, periods=140, freq="B", tz="UTC")
    leader = rng.normal(0, 0.01, len(index))
    follower = 0.85 * leader + rng.normal(0, 0.002, len(index))
    return pd.DataFrame({"MSFT": leader, "AVGO": follower}, index=index)


def _nodes() -> tuple[RelationshipNode, ...]:
    return (
        RelationshipNode(
            node_id="stock-msft",
            symbol="MSFT",
            node_type=RelationshipNodeType.STOCK,
            sector="Technology",
            data_version="data-v1",
        ),
        RelationshipNode(
            node_id="stock-avgo",
            symbol="AVGO",
            node_type=RelationshipNodeType.STOCK,
            sector="Technology",
            data_version="data-v1",
        ),
    )


def test_narrative_requires_diverse_sources_and_decays() -> None:
    engine = NarrativeDetectionEngine(
        NarrativeConfig(half_life_days=7, minimum_emerging_sources=2)
    )
    first = make_event("narrative-a", CUTOFF - timedelta(days=7), source="wire-a")
    assert not engine.detect((first,), data_cutoff=CUTOFF).narratives
    second = make_event(
        "narrative-b",
        CUTOFF - timedelta(days=1),
        symbol="AVGO",
        source="wire-b",
    )
    result = engine.detect((first, second), data_cutoff=CUTOFF)

    assert len(result.narratives) == 1
    narrative = result.narratives[0]
    assert narrative.strength <= 0.5
    assert narrative.decay_score < 1
    assert {item.symbol for item in result.exposures} == {"MSFT", "AVGO"}
    assert all(item.status.value == "RESEARCH_ONLY" for item in result.momentum_features)


def test_future_narrative_evidence_is_invisible() -> None:
    past = make_event("past-news", CUTOFF - timedelta(days=1), source="wire-a")
    future = make_event("future-news", CUTOFF + timedelta(days=1), source="wire-b")
    result = NarrativeDetectionEngine().detect((past, future), data_cutoff=CUTOFF)
    assert not result.narratives
    assert result.unavailable_reason is not None


def test_relationship_graph_is_pit_statistical_context_not_causation() -> None:
    graph = MarketRelationshipGraphEngine(
        RelationshipGraphConfig(
            windows=(20, 60),
            minimum_sample_size=60,
            maximum_lag=2,
            minimum_abs_strength=0.10,
        )
    ).build(
        _returns(),
        nodes=_nodes(),
        data_cutoff=CUTOFF,
        data_version="data-v1",
        regime="RISK_ON",
    )

    assert graph.edges
    assert any(item.relationship_type is RelationshipType.CORRELATION for item in graph.edges)
    assert all("caus" in item.causal_disclaimer.lower() for item in graph.edges)
    assert all(item.relationship_use is RelationshipUse.RESEARCH_INSIGHT for item in graph.edges)
    assert all(item.adjusted_p_value >= item.raw_p_value for item in graph.edges)


def test_relationship_and_cross_asset_reject_future_observations() -> None:
    future = _returns().copy()
    future.loc[pd.Timestamp(CUTOFF + timedelta(days=1))] = (0.01, 0.01)
    engine = MarketRelationshipGraphEngine(
        RelationshipGraphConfig(windows=(20, 60), minimum_sample_size=60)
    )
    with pytest.raises(ValueError, match="future"):
        engine.build(
            future,
            nodes=_nodes(),
            data_cutoff=CUTOFF,
            data_version="data-v1",
        )
    prices = pd.Series(
        np.linspace(100, 130, 60),
        index=pd.date_range(end=CUTOFF + timedelta(days=1), periods=60, tz="UTC"),
    )
    with pytest.raises(ValueError, match="future"):
        CrossAssetContextEngine((CrossAssetDefinition("MARKET", "SPY"),)).evaluate(
            {"SPY": prices}, data_cutoff=CUTOFF
        )


def test_cross_asset_missing_optional_series_degrades_without_fabrication() -> None:
    prices = pd.Series(
        np.linspace(100, 130, 80),
        index=pd.date_range(end=CUTOFF, periods=80, freq="B", tz="UTC"),
    )
    context = CrossAssetContextEngine(
        (
            CrossAssetDefinition("MARKET", "SPY"),
            CrossAssetDefinition("VOLATILITY", "^VIX"),
        )
    ).evaluate({"SPY": prices}, data_cutoff=CUTOFF)
    assert context.status is IntelligenceStatus.DEGRADED
    assert context.states[1].status is IntelligenceStatus.UNAVAILABLE
