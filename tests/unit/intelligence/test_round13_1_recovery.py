from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from personal_alpha_terminal.agents.llm.schemas import LLMRequest, LLMResponse
from personal_alpha_terminal.intelligence.cache import InMemoryExtractionCache
from personal_alpha_terminal.intelligence.round13_contracts import (
    FEATURE_TRANSFORM_VERSION,
    PROMPT_VERSION,
    AcceptedSecEvent,
    EvidenceStatus,
    build_shadow_features,
)
from personal_alpha_terminal.intelligence.round13_extraction import Round13SecExtractor
from personal_alpha_terminal.intelligence.schemas import RawInformation
from personal_alpha_terminal.intelligence.sec_edgar_acquisition import (
    SEC_FORM_TYPES,
    parse_edgar_submissions,
)
from personal_alpha_terminal.terminal.cli import build_parser
from personal_alpha_terminal.terminal.config import load_config
from personal_alpha_terminal.terminal.intelligence_cli import _persist_research_dataset

ACCEPTED = datetime(2025, 5, 1, 20, 30, tzinfo=UTC)
SPAN_ONE = "Revenue increased 20 percent due to durable customer demand."
SPAN_TWO = "The board authorized a new five billion dollar share repurchase program."


class StaticProvider:
    name = "deepseek"
    model = "deepseek-v4-flash"

    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0
        self.last_request: LLMRequest | None = None

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        self.last_request = request
        return LLMResponse(
            content=self.content,
            provider=self.name,
            model=self.model,
            is_mock=False,
            prompt_tokens=100,
            completion_tokens=50,
        )


def _raw(*, body: str = f"<p>{SPAN_ONE}</p><p>{SPAN_TWO}</p>") -> RawInformation:
    return RawInformation(
        raw_id="sec-320193-000032019325000001",
        source="sec-edgar",
        source_identifier="0000320193-25-000001",
        title="Apple Inc. 8-K",
        body=body,
        issuer_id="320193",
        permanent_security_id="SEC-AAPL",
        ticker_as_of="AAPL",
        document_type="8-K",
        published_at=ACCEPTED,
        observed_at=ACCEPTED,
        ingested_at=ACCEPTED + timedelta(hours=1),
        data_cutoff=ACCEPTED + timedelta(hours=1),
        filed_at=ACCEPTED,
        accepted_at=ACCEPTED,
        available_at=ACCEPTED,
    )


def _event(span: str, event_type: str, *, confidence: float = 0.95) -> dict[str, object]:
    return {
        "issuer_id": "320193",
        "ticker_asof": "AAPL",
        "event_type": event_type,
        "direction": "POSITIVE",
        "magnitude": 1.0,
        "materiality": "HIGH",
        "novelty": "NEW",
        "horizon": "MEDIUM",
        "extraction_confidence": confidence,
        "source_section": "Item 2.02",
        "source_span": span,
        "event_timestamp": ACCEPTED.isoformat(),
        "available_at": ACCEPTED.isoformat(),
        "summary": "Literal filing fact.",
        "model": "deepseek-v4-flash",
        "prompt_version": PROMPT_VERSION,
    }


def _payload(events: list[dict[str, object]]) -> str:
    return json.dumps({"document_summary": "Two material facts.", "events": events})


def _accepted(**updates: object) -> AcceptedSecEvent:
    base = AcceptedSecEvent(
        event_id="a" * 64,
        raw_id="r" * 64,
        issuer_id="320193",
        ticker_asof="AAPL",
        event_type="GUIDANCE_RAISE",
        direction="POSITIVE",
        magnitude=1.0,
        materiality="HIGH",
        novelty="NEW",
        horizon="MEDIUM",
        extraction_confidence=0.95,
        source_section="Item 2.02",
        source_span=SPAN_ONE,
        summary="Raised guidance.",
        evidence_hash="e" * 64,
        event_timestamp=ACCEPTED,
        available_at=ACCEPTED,
        model_provider="deepseek",
        model_name="deepseek-v4-flash",
        response_hash="f" * 64,
        prompt_version=PROMPT_VERSION,
    )
    return replace(base, **updates)


def test_cli_registers_complete_intelligence_command_family() -> None:
    parser = build_parser()
    for action in ("status", "acquire", "backfill", "process", "inspect", "audit"):
        suffix = [action]
        if action in {"acquire", "backfill"}:
            suffix += ["--cik", "320193"]
        if action == "inspect":
            suffix += ["--ticker", "AAPL"]
        args = parser.parse_args(["intelligence", *suffix])
        assert args.command == "intelligence"
        assert args.intelligence_action == action


def test_extended_sec_form_taxonomy_and_amendments() -> None:
    required = {"6-K", "20-F", "40-F", "DEF 14A", "4"}
    assert required <= SEC_FORM_TYPES
    assert {f"{item}/A" for item in required} <= SEC_FORM_TYPES
    recent = []
    for index, form in enumerate(sorted(required), 1):
        recent.append(
            {
                "accessionNumber": f"0000320193-25-{index:06d}",
                "form": form,
                "filingDate": "2025-05-01",
                "reportDate": "2025-04-30",
                "primaryDocument": f"form-{index}.htm",
                "acceptanceDateTime": ACCEPTED.isoformat(),
            }
        )
    records = parse_edgar_submissions(
        {"name": "Issuer", "filings": {"recent": recent}},
        cik=320193,
        required_start=ACCEPTED.date(),
        required_end=ACCEPTED.date(),
    )
    assert {item.form_type for item in records} == required


def test_multi_event_literal_evidence_and_cache() -> None:
    provider = StaticProvider(
        _payload([_event(SPAN_ONE, "REVENUE_CHANGE"), _event(SPAN_TWO, "BUYBACK")])
    )
    extractor = Round13SecExtractor(provider, InMemoryExtractionCache())
    first = extractor.extract(_raw())
    second = extractor.extract(_raw())
    assert first.structured_events == 2
    assert len(first.accepted) == 2
    assert first.quarantine_reasons == ()
    assert second.cache_hit is True
    assert provider.calls == 1
    assert provider.last_request is not None
    assert "BUY" not in provider.last_request.system_prompt.split("recommend")[0]


def test_unsupported_low_confidence_hallucination_and_duplicate_are_quarantined() -> None:
    unsupported = _event("This sentence does not occur in the filing source.", "EARNINGS")
    low = _event(SPAN_ONE, "EARNINGS", confidence=0.2)
    hallucinated = _event(SPAN_TWO, "BUYBACK")
    hallucinated["model"] = "invented-model"
    provider = StaticProvider(_payload([unsupported, low, hallucinated]))
    result = Round13SecExtractor(provider, InMemoryExtractionCache()).extract(_raw())
    assert set(result.quarantine_reasons) == {
        EvidenceStatus.UNSUPPORTED_CLAIM,
        EvidenceStatus.LOW_CONFIDENCE,
        EvidenceStatus.HALLUCINATION_SUSPECTED,
    }
    duplicate_provider = StaticProvider(
        _payload([_event(SPAN_ONE, "EARNINGS"), _event(SPAN_ONE, "EARNINGS")])
    )
    duplicate = Round13SecExtractor(duplicate_provider, InMemoryExtractionCache()).extract(_raw())
    assert len(duplicate.accepted) == 1
    assert duplicate.quarantine_reasons == (EvidenceStatus.CONFLICTING_EVIDENCE,)


def test_shadow_features_decay_cutoff_missing_semantics_and_authority() -> None:
    later = _accepted(event_id="b" * 64, available_at=ACCEPTED + timedelta(days=1))
    at_cutoff = build_shadow_features((_accepted(), later), as_of=ACCEPTED)
    names = {item.feature_name for item in at_cutoff}
    assert len(names) == 15
    assert all(item.event_ids == ("a" * 64,) for item in at_cutoff)
    assert all(item.event_ages_days == (0.0,) for item in at_cutoff)
    assert all(item.decay_weights == (1.0,) for item in at_cutoff)
    assert all(item.production_influence == 0.0 for item in at_cutoff)
    assert all(item.transform_version == FEATURE_TRANSFORM_VERSION for item in at_cutoff)
    delayed = build_shadow_features((_accepted(),), as_of=ACCEPTED + timedelta(days=30))
    guidance = next(item for item in delayed if item.feature_name == "guidance_revision_score")
    assert 0 < guidance.value < 1
    assert "no accepted PIT-visible" in guidance.missing_semantics


def test_research_features_and_future_outcomes_are_separate(tmp_path: Path) -> None:
    config = load_config(Path("config.yaml"))
    payload: dict[str, object] = {
        "decision_cutoff": ACCEPTED.isoformat(),
        "events": [
            {
                "issuer_id": "320193",
                "ticker_asof": "AAPL",
                "evidence_hash": "e" * 64,
            }
        ],
        "features": [
            {
                "issuer_id": "320193",
                "ticker_asof": "AAPL",
                "feature_name": "llm_event_momentum",
                "value": 0.5,
            }
        ],
    }
    _persist_research_dataset(tmp_path, "d" * 64, payload, config)
    feature_path = tmp_path / "research" / "features" / f"{'d' * 64}.json"
    outcome_path = tmp_path / "research" / "outcomes" / f"{'d' * 64}.json"
    features = json.loads(feature_path.read_text(encoding="utf-8"))
    outcomes = json.loads(outcome_path.read_text(encoding="utf-8"))
    assert features["status"] == "RESEARCH_LIMITED_SURVIVORSHIP"
    assert features["future_outcomes_read_during_build"] is False
    assert "outcomes" not in features
    assert outcomes["outcomes"] == []
    assert features["production_influence"] == "NONE"
