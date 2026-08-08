from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import cast

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from personal_alpha_terminal.intelligence.extraction import StructuredEventExtractor
from personal_alpha_terminal.intelligence.integration import (
    IntegratedDailyInput,
    IntegratedIntelligencePipeline,
    IntegratedPipelineStatus,
)
from personal_alpha_terminal.intelligence.relationship import (
    RelationshipNode,
    RelationshipNodeType,
)
from personal_alpha_terminal.intelligence.research import (
    FeatureCondition,
    HypothesisDefinition,
    HypothesisObservation,
    HypothesisStatus,
)
from personal_alpha_terminal.intelligence.research_service import (
    PhaseBResearchEngine,
    PhaseBResearchInput,
)
from personal_alpha_terminal.intelligence.scanner import (
    CandidateStatus,
    DailyOpportunityScanner,
    ScannerMode,
)
from personal_alpha_terminal.intelligence.schemas import BacktestSafety
from personal_alpha_terminal.intelligence.service import IntelligenceService
from personal_alpha_terminal.intelligence.storage import IntelligenceRepository
from personal_alpha_terminal.models.base import Base
from personal_alpha_terminal.models.intelligence import (
    IntelligenceHypothesis,
    IntelligenceNarrative,
    IntelligenceRelationship,
)
from personal_alpha_terminal.quant_engine.portfolio.construction import (
    PortfolioConstructionEngine,
)
from personal_alpha_terminal.quant_engine.production_pipeline import (
    DailyQuantInput,
    DailyQuantPipeline,
)
from personal_alpha_terminal.quant_engine.risk.budget import (
    PortfolioRiskState,
    RegimeRiskInput,
)
from personal_alpha_terminal.quant_engine.risk.model import AssetRiskMetadata
from personal_alpha_terminal.research.data_gate import GateStatus, ResearchPurpose
from tests.unit.intelligence.helpers import make_event
from tests.unit.intelligence.test_scanner_storage import (
    _alpha,
    _authorization,
    _proposal,
)
from tests.unit.quant_engine.test_miniature_end_to_end import (
    DECISION_TIME,
    SYMBOLS,
    _constraints,
    _pit_factors,
)
from tests.unit.quant_engine.test_miniature_end_to_end import (
    _authorization as miniature_authorization,
)
from tests.unit.quant_engine.test_miniature_end_to_end import (
    _returns as miniature_returns,
)

CUTOFF = datetime(2026, 8, 8, 20, tzinfo=UTC)


def _hypothesis(
    cutoff: datetime,
) -> tuple[HypothesisDefinition, tuple[HypothesisObservation, ...]]:
    start = date(2023, 1, 1)
    definition = HypothesisDefinition(
        hypothesis_id="integration-hypothesis",
        description="Frozen relationship hypothesis for integration",
        features=(FeatureCondition(feature="leader_momentum", operator=">", threshold=0.08),),
        target="AVGO",
        benchmark="SPY",
        horizon=10,
        creator="fixture-agent",
        model_version="fixture-hypothesis-v1",
        discovery_period=(start, start + timedelta(days=29)),
        validation_period=(start + timedelta(days=30), start + timedelta(days=59)),
        test_period=(start + timedelta(days=60), start + timedelta(days=89)),
        created_at=cutoff,
        data_cutoff=cutoff - timedelta(seconds=1),
        backtest_safety=BacktestSafety.BACKTEST_SAFE,
        status=HypothesisStatus.FORMALIZED,
    )
    observations = []
    for position in range(90):
        session = start + timedelta(days=position)
        signal = datetime.combine(session, datetime.min.time(), tzinfo=UTC)
        observations.append(
            HypothesisObservation(
                session=session,
                condition_matched=True,
                forward_excess_return=0.008 + (position % 4) * 0.001,
                transaction_cost=0.0005,
                drawdown=-0.03,
                turnover=0.1,
                regime="RISK_ON" if position % 2 else "NEUTRAL",
                signal_time=signal,
                features_available_at=signal - timedelta(minutes=1),
                outcome_available_at=signal + timedelta(days=11),
            )
        )
    return definition, tuple(observations)


def _phase_b_input(cutoff: datetime = CUTOFF) -> PhaseBResearchInput:
    rng = np.random.default_rng(9)
    index = pd.date_range(end=cutoff, periods=140, freq="B", tz="UTC")
    leader = rng.normal(0, 0.01, len(index))
    returns = pd.DataFrame(
        {"MSFT": leader, "AVGO": leader * 0.8 + rng.normal(0, 0.002, len(index))},
        index=index,
    )
    nodes = (
        RelationshipNode(
            node_id="stock-msft",
            symbol="MSFT",
            node_type=RelationshipNodeType.STOCK,
            data_version="data-v1",
        ),
        RelationshipNode(
            node_id="stock-avgo",
            symbol="AVGO",
            node_type=RelationshipNodeType.STOCK,
            data_version="data-v1",
        ),
    )
    definition, observations = _hypothesis(cutoff)
    events = (
        make_event("phase-b-a", cutoff - timedelta(days=2), source="wire-a"),
        make_event(
            "phase-b-b",
            cutoff - timedelta(days=1),
            symbol="AVGO",
            source="wire-b",
        ),
    )
    spy = pd.Series(
        np.linspace(100, 125, 80),
        index=pd.date_range(end=cutoff, periods=80, freq="B", tz="UTC"),
    )
    return PhaseBResearchInput(
        events=events,
        returns=returns,
        relationship_nodes=nodes,
        cross_asset_prices={"SPY": spy},
        hypothesis_definitions=(definition,),
        hypothesis_observations={definition.hypothesis_id: observations},
        data_cutoff=cutoff,
        data_version="data-v1",
        regime="RISK_ON",
        real_data_validated=False,
    )


def test_phase_b_full_research_chain_is_replayable_and_cannot_bypass_portfolio() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        repository = IntelligenceRepository(session)
        research = PhaseBResearchEngine(repository)
        first = research.run(_phase_b_input())
        session.flush()
        second = research.run(_phase_b_input())
        session.flush()
        counts = (
            session.scalar(select(func.count()).select_from(IntelligenceNarrative)),
            session.scalar(select(func.count()).select_from(IntelligenceRelationship)),
            session.scalar(select(func.count()).select_from(IntelligenceHypothesis)),
        )
    engine.dispose()

    assert first.narratives == second.narratives
    assert first.relationships == second.relationships
    assert first.hypotheses == second.hypotheses
    assert first.status == "RESEARCH_ONLY"
    assert counts[0] == 1 and counts[1] and counts[1] > 0 and counts[2] == 1
    assert first.research_features_by_symbol["AVGO"]

    scanner = DailyOpportunityScanner()
    candidate = scanner.scan(
        authorization=_authorization(
            ResearchPurpose.PORTFOLIO_DECISION, GateStatus.APPROVED
        ),
        alpha_signals=(_alpha(),),
        proposals=(_proposal(),),
        probability_by_symbol={},
        event_statistics_by_symbol={},
        current_weights={"MSFT": 0.05},
        risk_flags_by_symbol={},
        mode=ScannerMode.QUANT_FULL_VALIDATED_INTELLIGENCE,
        ai_ready=False,
        research_features_by_symbol={
            "MSFT": first.research_features_by_symbol.get("MSFT", ())
        },
        lineage_by_symbol={"MSFT": first.lineage_by_symbol.get("MSFT", {})},
        as_of=CUTOFF,
    )[0]
    assert candidate.status is CandidateStatus.ACTIONABLE
    assert candidate.target_weight_candidate == _proposal().target_weight
    assert candidate.narrative_context
    assert candidate.narrative_score == 50.0
    assert candidate.ai_readiness == "INTELLIGENCE_DEGRADED"


def test_application_integration_runs_quant_portfolio_risk_before_scanner() -> None:
    returns, benchmark = miniature_returns()
    metadata = tuple(
        AssetRiskMetadata(
            symbol,
            "Technology" if index < 3 else "Healthcare",
            100_000_000 + index * 20_000_000,
            (index - 2) / 5,
        )
        for index, symbol in enumerate(SYMBOLS)
    )
    quant_input = DailyQuantInput(
        authorization=miniature_authorization(),
        decision_time=DECISION_TIME,
        alpha_signals=_pit_factors(),
        returns=returns,
        benchmark_returns=benchmark,
        risk_metadata=metadata,
        current_weights={},
        portfolio_value=1_000_000,
        portfolio_risk_state=PortfolioRiskState(-0.04, 0.20, 0.0, 0.0, 0.55, 0.30),
        regime=RegimeRiskInput(0.10, 0.25, 0.65, 0.80, True, "regime-cal-v1"),
        pit_valid=True,
        universe_snapshot_id="mini-universe-v1",
        data_quality="VALID",
    )
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        service = IntelligenceService(
            session,
            cast(StructuredEventExtractor, object()),
        )
        pipeline = IntegratedIntelligencePipeline(
            service,
            DailyQuantPipeline(
                construction=PortfolioConstructionEngine(_constraints())
            ),
        )
        output = pipeline.run(
            IntegratedDailyInput(
                quant=quant_input,
                research=_phase_b_input(DECISION_TIME),
                probability_by_symbol={},
                event_statistics_by_symbol={},
                risk_flags_by_symbol={},
                portfolio_constraints_by_symbol={},
                ai_ready=False,
            )
        )
        session.commit()
    engine.dispose()

    assert output.status is IntegratedPipelineStatus.DEGRADED
    assert output.quant.target is not None and output.quant.target.production_approved
    assert output.candidates
    assert all(
        candidate.target_weight_candidate
        == output.quant.target.target_weights.get(candidate.symbol)
        for candidate in output.candidates
        if candidate.target_weight_candidate is not None
    )
