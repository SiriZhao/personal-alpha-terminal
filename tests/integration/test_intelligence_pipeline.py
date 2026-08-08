from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import exchange_calendars as xcals
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from personal_alpha_terminal.agents.llm.schemas import LLMRequest, LLMResponse
from personal_alpha_terminal.intelligence.budget import (
    IntelligenceBudget,
    IntelligenceBudgetConfig,
)
from personal_alpha_terminal.intelligence.cache import InMemoryExtractionCache
from personal_alpha_terminal.intelligence.event_study import PointInTimeEventStudyEngine
from personal_alpha_terminal.intelligence.extraction import StructuredEventExtractor
from personal_alpha_terminal.intelligence.scanner import ScannerMode
from personal_alpha_terminal.intelligence.schemas import IntelligenceStatus, RawInformation
from personal_alpha_terminal.intelligence.service import IntelligenceService
from personal_alpha_terminal.models.base import Base
from personal_alpha_terminal.models.intelligence import IntelligenceEvent
from personal_alpha_terminal.quant_engine.alpha import (
    AlphaDataQuality,
    AlphaSignal,
    AlphaValidationStatus,
)
from personal_alpha_terminal.quant_engine.probability import (
    estimate_conditional_probability_2,
)
from personal_alpha_terminal.research.data_gate import (
    GateDecision,
    GateStatus,
    ResearchDataAuthorization,
    ResearchDataRequest,
    ResearchPurpose,
)


@dataclass
class DeterministicProvider:
    name: str = "fixture"
    model: str = "fixture-v1"

    def generate(self, request: LLMRequest) -> LLMResponse:
        payload = json.loads(request.user_prompt)["information"]
        result = {
            "symbol": "MSFT",
            "entity": "Microsoft",
            "sector": "Technology",
            "industry": "Software",
            "event_type": "EARNINGS",
            "event_subtype": "quarterly",
            "summary": "Frozen structured event.",
            "direction": "POSITIVE",
            "magnitude": 0.1,
            "surprise": 0.04,
            "relevance": 0.9,
            "novelty": 0.8,
            "confidence": 0.8,
            "expected_horizon": 20,
            "affected_assets": ["MSFT"],
            "affected_sectors": ["Technology"],
            "themes": ["Earnings"],
            "effective_at": payload["published_at"],
        }
        return LLMResponse(json.dumps(result), self.name, self.model, False)


def test_raw_information_to_frozen_event_and_replay() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    observed = datetime(2026, 8, 7, 20, tzinfo=UTC)
    raw_items = tuple(
        RawInformation(
            raw_id=f"raw-{index}",
            source=f"wire-{index}",
            source_identifier=f"story-{index}",
            title="Microsoft reports quarterly earnings",
            body="Supplied figures and release text.",
            published_at=observed + timedelta(seconds=index),
            observed_at=observed + timedelta(seconds=index + 1),
            ingested_at=observed + timedelta(seconds=index + 2),
            data_cutoff=observed + timedelta(seconds=index + 2),
        )
        for index in range(2)
    )
    with Session(engine) as session:
        extractor = StructuredEventExtractor(
            DeterministicProvider(),
            InMemoryExtractionCache(),
            IntelligenceBudget(IntelligenceBudgetConfig()),
            clock=lambda: observed + timedelta(minutes=1),
        )
        service = IntelligenceService(session, extractor)
        materialized = service.materialize(raw_items)
        session.commit()
        replay_one = service.replay(observed + timedelta(minutes=2))
        replay_two = service.replay(observed + timedelta(minutes=2))
        count = len(session.scalars(select(IntelligenceEvent)).all())
    assert materialized.status is IntelligenceStatus.READY
    assert len(materialized.accepted_events) == 1
    assert len(materialized.accepted_events[0].evidence) == 2
    assert count == 1
    assert replay_one == replay_two


def test_full_raw_event_study_probability_scanner_chain() -> None:
    calendar = xcals.get_calendar("XNYS")
    sessions = calendar.sessions_in_range("2020-01-02", "2024-12-31")
    selected = tuple(range(20, len(sessions) - 25, 25))[:35]
    raw_items = tuple(
        RawInformation(
            raw_id=f"raw-{position}",
            source="fixture-wire",
            source_identifier=f"story-{position}",
            title=f"Microsoft earnings release {position}",
            body="Frozen earnings release evidence.",
            published_at=calendar.session_close(sessions[position]).to_pydatetime(),
            observed_at=(
                calendar.session_close(sessions[position]).to_pydatetime()
                + timedelta(seconds=1)
            ),
            ingested_at=(
                calendar.session_close(sessions[position]).to_pydatetime()
                + timedelta(seconds=2)
            ),
            data_cutoff=(
                calendar.session_close(sessions[position]).to_pydatetime()
                + timedelta(seconds=2)
            ),
        )
        for position in selected
    )
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    as_of = calendar.session_close(sessions[-1]).to_pydatetime() + timedelta(minutes=1)
    with Session(engine) as session:
        extractor = StructuredEventExtractor(
            DeterministicProvider(),
            InMemoryExtractionCache(),
            IntelligenceBudget(
                IntelligenceBudgetConfig(max_requests_per_run=50, max_tokens_per_run=500_000)
            ),
            clock=lambda: as_of,
        )
        service = IntelligenceService(session, extractor)
        materialized = service.materialize(raw_items)
        prices = pd.Series(
            np.power(1.0005, np.arange(len(sessions))),
            index=pd.DatetimeIndex(sessions),
        )
        benchmark = pd.Series(
            np.power(1.0002, np.arange(len(sessions))),
            index=pd.DatetimeIndex(sessions),
        )
        study = PointInTimeEventStudyEngine(bootstrap_resamples=1_000).run(
            materialized.accepted_events,
            asset_total_returns={"MSFT": prices},
            benchmark_total_return=benchmark,
            benchmark_symbol="SPY",
            as_of=as_of,
        )
        one_day = next(item for item in study.statistics if item.horizon == 1)
        abnormal = tuple(
            item.abnormal_return for item in study.observations if item.horizon == 1
        )
        probability = estimate_conditional_probability_2(
            abnormal,
            tuple([-0.001, 0.001] * 50),
            minimum_sample_size=30,
        )
        alpha = AlphaSignal(
            "MSFT",
            as_of - timedelta(minutes=10),
            "QUALITY_MOMENTUM",
            0.03,
            20,
            1.0,
            1.2,
            0.8,
            True,
            120,
            0.8,
            0.7,
            20,
            as_of + timedelta(days=5),
            AlphaDataQuality.VALID,
            True,
            AlphaValidationStatus.PRODUCTION_APPROVED,
            "alpha-v1",
            "data-v1",
        )
        request = ResearchDataRequest(
            ResearchPurpose.RESEARCH,
            "US",
            "stock",
            sessions[0].date(),
            sessions[-1].date(),
            as_of,
            "point_in_time_total_return",
            "universe-v1",
        )
        decision = GateDecision(
            GateStatus.RESEARCH_ONLY,
            ResearchPurpose.RESEARCH,
            (),
            (),
            ("descriptive_research",),
            "fingerprint",
            as_of,
        )
        authorization = ResearchDataAuthorization(decision, request, as_of, "auth")
        candidates = service.scan(
            authorization=authorization,
            alpha_signals=(alpha,),
            proposals=(),
            probability_by_symbol={"MSFT": probability},
            event_statistics_by_symbol={"MSFT": one_day},
            current_weights={"MSFT": 0.0},
            risk_flags_by_symbol={},
            mode=ScannerMode.QUANT_PLUS_EVENT,
            ai_ready=True,
            as_of=as_of,
        )
        session.commit()
    assert materialized.status is IntelligenceStatus.READY
    assert study.status is IntelligenceStatus.READY
    assert probability.valid
    assert candidates[0].symbol == "MSFT"
    assert candidates[0].target_weight_candidate is None


def test_sequential_article_update_preserves_historical_replay() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    observed = datetime(2026, 8, 7, 20, tzinfo=UTC)

    def raw(index: int, when: datetime) -> RawInformation:
        return RawInformation(
            raw_id=f"sequential-{index}",
            source=f"wire-{index}",
            source_identifier=f"sequential-story-{index}",
            title="Microsoft reports quarterly earnings",
            body="Frozen release or subsequent corroborating update.",
            published_at=when,
            observed_at=when + timedelta(seconds=1),
            ingested_at=when + timedelta(seconds=2),
            data_cutoff=when + timedelta(seconds=2),
        )

    with Session(engine) as session:
        extractor = StructuredEventExtractor(
            DeterministicProvider(),
            InMemoryExtractionCache(),
            IntelligenceBudget(IntelligenceBudgetConfig()),
            clock=lambda: observed + timedelta(hours=3),
        )
        service = IntelligenceService(session, extractor)
        service.materialize((raw(1, observed),))
        session.commit()
        service.materialize((raw(2, observed + timedelta(hours=2)),))
        session.commit()
        historical = service.replay(observed + timedelta(minutes=1))
        current = service.replay(observed + timedelta(hours=3))
    assert len(historical) == 1 and len(historical[0].evidence) == 1
    assert len(current) == 1 and len(current[0].evidence) == 2
