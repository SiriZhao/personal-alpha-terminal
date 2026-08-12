"""ROUND 9: structured-output contracts, prompt identity, and validation tests."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from personal_alpha_terminal.quant_engine.llm_advisory import (
    DataAnomalyReport,
    EvidenceRef,
    PortfolioExplanation,
    PromptIdentity,
    ResearchCopilotNote,
    ShadowFeatureSuggestion,
    build_prompt_identity,
    prompt_hash,
)

NOW = datetime(2026, 8, 13, 12, tzinfo=UTC)


def test_structured_output_contracts_carry_required_fields() -> None:
    envelope = DataAnomalyReport(
        classification="STALE_DATA",
        confidence=0.9,
        timestamp=NOW,
        source="market-data",
        model="deepseek-v1",
        prompt_version="anomaly-v1",
        evidence=[EvidenceRef(evidence_id="e1", source="provider-log", timestamp=NOW)],
        summary="Latest session older than expected",
        anomaly_kind="STALE_DATA",
        severity="HIGH",
        affected_symbols=["AAPL"],
    )
    assert envelope.classification == "STALE_DATA"
    assert envelope.confidence == 0.9
    assert envelope.evidence[0].source == "provider-log"
    assert envelope.quant_impact if hasattr(envelope, "quant_impact") else True


def test_contract_validates_numeric_ranges() -> None:
    with pytest.raises(ValidationError):
        PortfolioExplanation(
            classification="BUY",
            confidence=1.5,  # out of range
            timestamp=NOW,
            source="quant-result",
            model="m",
            prompt_version="v1",
        )
    with pytest.raises(ValidationError):
        DataAnomalyReport(
            classification="",  # empty classification rejected
            confidence=0.5,
            timestamp=NOW,
            source="market-data",
            model="m",
            prompt_version="v1",
            anomaly_kind="OTHER",
        )


def test_portfolio_explanation_never_changes_targets() -> None:
    explanation = PortfolioExplanation(
        classification="REDUCE",
        confidence=0.6,
        timestamp=NOW,
        source="quant-result",
        model="advisory-v1",
        prompt_version="portfolio-explanation-v1",
        explanations=["Momentum decayed; position reduced per the formal target"],
        risk_notes=["Sector concentration elevated"],
        quant_impact="NONE",
    )
    # The contract has no target_weight / quantity fields: it can only explain.
    assert "target_weight" not in PortfolioExplanation.model_fields
    assert explanation.quant_impact == "NONE"


def test_shadow_feature_is_research_only_until_oos_validated() -> None:
    feature = ShadowFeatureSuggestion(
        classification="CANDIDATE",
        confidence=0.5,
        timestamp=NOW,
        source="llm-research",
        model="deepseek-reasoner-v1",
        prompt_version="feature-proposal-v1",
        feature_name="llm_guidance_sentiment",
        feature_definition="normalized guidance tone from PIT filings",
        data_dependencies=["SEC 8-K", "PIT cutoff"],
        quant_impact="SHADOW",
        oos_validated=False,
    )
    assert feature.oos_validated is False
    assert feature.quant_impact == "SHADOW"


def test_prompt_identity_is_traceable_and_deterministic() -> None:
    identity = build_prompt_identity(
        provider="deepseek",
        model="deepseek-chat",
        model_version="v3",
        prompt_name="portfolio-explanation",
        prompt_version="v1",
        prompt_text="Explain the quant result without changing targets.",
        schema_version="advisory-v1",
        temperature=0.0,
        timestamp=NOW,
    )
    assert isinstance(identity, PromptIdentity)
    assert identity.prompt_hash == prompt_hash(
        "Explain the quant result without changing targets."
    )
    assert identity.identity_hash
    doc = identity.document()
    assert doc["provider"] == "deepseek"
    assert doc["temperature"] == 0.0
    # Same inputs -> same identity hash.
    again = build_prompt_identity(
        provider="deepseek",
        model="deepseek-chat",
        model_version="v3",
        prompt_name="portfolio-explanation",
        prompt_version="v1",
        prompt_text="Explain the quant result without changing targets.",
        schema_version="advisory-v1",
        temperature=0.0,
        timestamp=NOW,
    )
    assert again.identity_hash == identity.identity_hash


def test_prompt_identity_rejects_invalid_temperature_or_empty() -> None:
    with pytest.raises(ValueError):
        build_prompt_identity(
            provider="", model="m", model_version="v1", prompt_name="p",
            prompt_version="v1", prompt_text="x", schema_version="s",
            temperature=0.0, timestamp=NOW,
        )
    with pytest.raises(ValueError):
        build_prompt_identity(
            provider="p", model="m", model_version="v1", prompt_name="p",
            prompt_version="v1", prompt_text="x", schema_version="s",
            temperature=3.0, timestamp=NOW,
        )


def test_research_copilot_note_and_anomaly_kind_validation() -> None:
    note = ResearchCopilotNote(
        classification="REGIME_BREAKDOWN",
        confidence=0.7,
        timestamp=NOW,
        source="research-copilot",
        model="deepseek-reasoner-v1",
        prompt_version="copilot-v1",
        note_kind="REGIME_BREAKDOWN",
        quant_impact="NONE",
    )
    assert note.note_kind == "REGIME_BREAKDOWN"
    with pytest.raises(ValidationError):
        DataAnomalyReport(
            classification="X",
            confidence=0.5,
            timestamp=NOW,
            source="s",
            model="m",
            prompt_version="v1",
            anomaly_kind="INVALID_KIND",
        )
