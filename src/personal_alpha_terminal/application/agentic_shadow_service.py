"""Production-parity Agentic Shadow computation.

This module owns the non-authoritative branch:
PIT events -> structured thesis -> debate -> bounded semantic proxy ->
shadow ranking -> canonical optimizer/risk counterfactual.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from math import isfinite
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.agents.llm.providers import LLMProvider
from personal_alpha_terminal.application.daily_result import StageResult
from personal_alpha_terminal.application.quant_daily_service import (
    TodayResult,
    build_daily_quant_pipeline,
)
from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
from personal_alpha_terminal.intelligence.agentic_engine import (
    CompanyThesisAnalyzer,
    EventAnalysis,
    build_hybrid_security_view,
    build_market_intelligence,
    debate_quant_and_events,
    portfolio_semantic_risk,
    raw_event_score,
)
from personal_alpha_terminal.intelligence.agentic_models import (
    AlphaAttribution,
    DebateDecision,
    EventIntelligenceFeatures,
    EventRecord,
    EventType,
    HybridActionView,
    HybridIntelligenceStatus,
    LLMCompanyThesis,
    LLMInferenceRecord,
    LLMInfluenceLevel,
    LLMQuantDebate,
    QuantThesis,
    SecurityIdentity,
)
from personal_alpha_terminal.intelligence.schemas import (
    BacktestSafety,
    EventDirection,
    UnifiedEvent,
)
from personal_alpha_terminal.models import SecurityMaster
from personal_alpha_terminal.models.intelligence import IntelligenceRawInformation
from personal_alpha_terminal.quant_engine.alpha import AlphaSignal
from personal_alpha_terminal.quant_engine.production_pipeline import (
    DailyQuantOutput,
    ProductionPipelineStatus,
)

SHADOW_LAMBDA = 0.20
MAX_RELATIVE_SEMANTIC_ADJUSTMENT = 0.25
MAX_ABSOLUTE_SEMANTIC_ADJUSTMENT = 0.005


@dataclass(frozen=True, slots=True)
class ShadowCompanyEvidence:
    security: SecurityIdentity
    company_name: str
    business_summary: str
    events: tuple[EventRecord, ...]
    analyses: tuple[EventAnalysis, ...]


@dataclass(frozen=True, slots=True)
class AgenticShadowEvidence:
    companies: dict[str, ShadowCompanyEvidence]
    rejected_events: tuple[str, ...] = ()


def load_agentic_shadow_evidence(
    session: Session,
    *,
    events: tuple[UnifiedEvent, ...],
    eligible_symbols: tuple[str, ...],
    decision_time: datetime,
) -> AgenticShadowEvidence:
    """Bind visible stored events to the security master and raw provenance."""

    as_of = _utc(decision_time)
    symbols = tuple(sorted(set(eligible_symbols)))
    stocks = tuple(
        item
        for item in session.scalars(
            select(SecurityMaster).where(SecurityMaster.symbol.in_(symbols))
        )
        if _utc(item.available_time) <= as_of
    )
    stock_by_symbol: dict[str, SecurityMaster] = {}
    rejected: list[str] = []
    for symbol in symbols:
        candidates = tuple(item for item in stocks if item.symbol == symbol)
        canonical_ids = {item.canonical_code for item in candidates}
        if len(canonical_ids) != 1:
            rejected.append(f"{symbol}:SECURITY_IDENTITY_AMBIGUOUS_OR_MISSING")
            continue
        stock_by_symbol[symbol] = max(
            candidates,
            key=lambda item: (_utc(item.available_time), item.id),
        )

    source_hashes = tuple(
        sorted(
            {
                evidence.source_hash
                for event in events
                for evidence in event.evidence
            }
        )
    )
    raw_records = (
        tuple(
            session.scalars(
                select(IntelligenceRawInformation).where(
                    IntelligenceRawInformation.source_hash.in_(source_hashes),
                    IntelligenceRawInformation.data_cutoff <= as_of,
                )
            )
        )
        if source_hashes
        else ()
    )
    raw_by_hash = {item.source_hash: item for item in raw_records}
    visible_events = tuple(
        event
        for event in events
        if event.at_cutoff(as_of) is not None
        and event.symbol in stock_by_symbol
    )

    issuer_ids_by_symbol: dict[str, set[str]] = {
        symbol: set() for symbol in stock_by_symbol
    }
    for event in visible_events:
        assert event.symbol is not None
        stock = stock_by_symbol[event.symbol]
        for evidence in event.evidence:
            row = raw_by_hash.get(evidence.source_hash)
            if (
                row is not None
                and row.permanent_security_id == stock.canonical_code
                and row.ticker_as_of == event.symbol
                and row.issuer_id
            ):
                issuer_ids_by_symbol[event.symbol].add(row.issuer_id)

    identities: dict[str, SecurityIdentity] = {}
    for symbol, stock in stock_by_symbol.items():
        issuer_ids = issuer_ids_by_symbol[symbol]
        if len(issuer_ids) > 1:
            rejected.append(f"{symbol}:COMPANY_IDENTITY_AMBIGUOUS")
            continue
        identities[symbol] = SecurityIdentity(
            permanent_security_id=stock.canonical_code,
            company_id=(
                next(iter(issuer_ids))
                if issuer_ids
                else f"SECURITY_MASTER:{stock.canonical_code}"
            ),
            symbol=symbol,
            symbol_as_of_time=_utc(stock.available_time),
        )

    event_rows: dict[str, list[tuple[EventRecord, EventAnalysis]]] = {
        symbol: [] for symbol in identities
    }
    for unified in visible_events:
        assert unified.symbol is not None
        identity = identities.get(unified.symbol)
        if identity is None:
            continue
        raw_rows = tuple(
            raw_by_hash.get(evidence.source_hash)
            for evidence in unified.evidence
        )
        if any(row is None for row in raw_rows):
            rejected.append(f"{unified.event_id}:RAW_PROVENANCE_MISSING")
            continue
        mapped_rows = tuple(row for row in raw_rows if row is not None)
        if any(
            row.permanent_security_id != identity.permanent_security_id
            or row.ticker_as_of != identity.symbol
            or (
                row.issuer_id is not None
                and not identity.company_id.startswith("SECURITY_MASTER:")
                and row.issuer_id != identity.company_id
            )
            for row in mapped_rows
        ):
            rejected.append(f"{unified.event_id}:SECURITY_IDENTITY_MISMATCH")
            continue
        try:
            record = _agentic_event(unified, identity, as_of)
            analysis = _stored_event_analysis(unified, record, as_of)
        except ValueError as error:
            rejected.append(f"{unified.event_id}:{type(error).__name__}:{error}")
            continue
        event_rows[unified.symbol].append((record, analysis))

    companies = {
        symbol: ShadowCompanyEvidence(
            security=identity,
            company_name=stock_by_symbol[symbol].name,
            business_summary=(
                f"{stock_by_symbol[symbol].market}/{stock_by_symbol[symbol].exchange} "
                f"{stock_by_symbol[symbol].asset_type}; PIT profile unavailable."
            ),
            events=tuple(item[0] for item in event_rows[symbol]),
            analyses=tuple(item[1] for item in event_rows[symbol]),
        )
        for symbol, identity in identities.items()
    }
    return AgenticShadowEvidence(
        companies=companies,
        rejected_events=tuple(sorted(set(rejected))),
    )


def build_agentic_shadow_document(
    *,
    workflow: TodayResult,
    llm_stage: StageResult | None,
    evidence: AgenticShadowEvidence | None = None,
    provider: LLMProvider | None = None,
    effective_config: EffectiveRuntimeConfig | None = None,
) -> dict[str, object]:
    """Run the actual Shadow branch while preserving formal Quant output."""

    metadata = llm_stage.metadata if llm_stage is not None else {}
    provider_name = str(
        getattr(provider, "name", metadata.get("provider", "UNAVAILABLE"))
    )
    model = str(getattr(provider, "model", metadata.get("model", "UNAVAILABLE")))
    connectivity = str(metadata.get("connectivity", "NOT_TESTED"))
    evidence = evidence or AgenticShadowEvidence(companies={})
    target_weights = workflow.target.target_weights if workflow.target is not None else {}
    current_weights = workflow.current_weights or {}
    probability = workflow.probability_counterfactual
    factors = tuple(sorted(workflow.factors, key=lambda item: (item.rank, item.symbol)))

    quant_by_symbol: dict[str, QuantThesis] = {}
    thesis_by_symbol: dict[str, LLMCompanyThesis] = {}
    debate_by_symbol: dict[str, LLMQuantDebate] = {}
    semantic_scores: dict[str, float] = {}
    raw_adjustments: dict[str, float] = {}
    applied_adjustments: dict[str, float] = {}
    failures: dict[str, tuple[str, ...]] = {}
    themes: dict[str, tuple[str, ...]] = {}
    risks: dict[str, tuple[str, ...]] = {}
    event_ids: dict[str, tuple[str, ...]] = {}
    inferences: list[dict[str, object]] = []
    thesis_analyzer = CompanyThesisAnalyzer(provider)

    for factor in factors:
        company = evidence.companies.get(factor.symbol)
        quant = QuantThesis(
            symbol=factor.symbol,
            security=company.security if company is not None else None,
            quant_rank=float(factor.rank),
            expected_alpha=float(factor.expected_alpha),
            factor_contributions={
                name: float(value) for name, value in factor.components.items()
            },
            probability_evidence=_optional_finite(
                probability.get(factor.symbol, {}).get("conditional_probability")
            ),
            uncertainty=max(0.0, min(1.0, 1.0 - float(factor.evidence_coverage))),
        )
        quant_by_symbol[factor.symbol] = quant
        if company is None:
            failures[factor.symbol] = ("SECURITY_IDENTITY_UNAVAILABLE",)
            debate_by_symbol[factor.symbol] = _insufficient_debate(
                quant, "SECURITY_IDENTITY_UNAVAILABLE"
            )
            semantic_scores[factor.symbol] = 0.0
            raw_adjustments[factor.symbol] = 0.0
            applied_adjustments[factor.symbol] = 0.0
            continue
        if not company.events:
            failures[factor.symbol] = ("NO_PIT_EVENTS",)
            debate_by_symbol[factor.symbol] = _insufficient_debate(
                quant, "NO_PIT_EVENTS"
            )
            semantic_scores[factor.symbol] = 0.0
            raw_adjustments[factor.symbol] = 0.0
            applied_adjustments[factor.symbol] = 0.0
            continue

        thesis_result = thesis_analyzer.analyze(
            quant=quant,
            events=company.events,
            decision_time=workflow.decision_time,
        )
        inferences.append(thesis_result.inference.model_dump(mode="json"))
        thesis = thesis_result.thesis
        if thesis is not None:
            thesis_by_symbol[factor.symbol] = thesis
            themes[factor.symbol] = thesis.key_catalysts
            risks[factor.symbol] = thesis.risk_flags
        else:
            failures[factor.symbol] = (
                thesis_result.fallback_reason or "THESIS_UNAVAILABLE",
            )
        debate = debate_quant_and_events(
            quant,
            company.events,
            company.analyses,
            thesis,
        )
        debate_by_symbol[factor.symbol] = debate
        event_ids[factor.symbol] = tuple(item.event_id for item in company.events)
        semantic_score = (
            _semantic_score(company.analyses, debate) if thesis is not None else 0.0
        )
        semantic_scores[factor.symbol] = semantic_score
        raw_adjustments[factor.symbol] = _semantic_alpha_proxy(
            float(factor.expected_alpha),
            semantic_score,
        )
        applied_adjustments[factor.symbol] = (
            SHADOW_LAMBDA * raw_adjustments[factor.symbol]
        )

    shadow_output = _run_shadow_pipeline(
        workflow=workflow,
        effective_config=effective_config,
        adjustments=applied_adjustments,
    )
    shadow_targets = (
        shadow_output.target.target_weights
        if shadow_output is not None and shadow_output.target is not None
        else {}
    )
    shadow_ranking = tuple(
        sorted(
            (
                {
                    "symbol": factor.symbol,
                    "quant_rank": factor.rank,
                    "quant_expected_alpha": float(factor.expected_alpha),
                    "semantic_score": semantic_scores.get(factor.symbol, 0.0),
                    "semantic_alpha_proxy": raw_adjustments.get(
                        factor.symbol, 0.0
                    ),
                    "shadow_expected_alpha": (
                        float(factor.expected_alpha)
                        + applied_adjustments.get(factor.symbol, 0.0)
                    ),
                }
                for factor in factors
            ),
            key=_shadow_ranking_key,
        )
    )

    securities = []
    for factor in factors:
        company = evidence.companies.get(factor.symbol)
        thesis = thesis_by_symbol.get(factor.symbol)
        debate = debate_by_symbol[factor.symbol]
        trace = probability.get(factor.symbol, {})
        raw_probability_impact = trace.get("probability_weight_impact")
        raw_adjustment = raw_adjustments.get(factor.symbol, 0.0)
        applied_adjustment = applied_adjustments.get(factor.symbol, 0.0)
        attribution = AlphaAttribution(
            symbol=factor.symbol,
            mu_quant=float(factor.expected_alpha),
            delta_mu_semantic_raw=raw_adjustment,
            lambda_applied=SHADOW_LAMBDA if raw_adjustment else 0.0,
            delta_mu_semantic_applied=applied_adjustment,
            mu_final=float(factor.expected_alpha) + applied_adjustment,
            production_influence=0.0,
            weight_quant_counterfactual=target_weights.get(factor.symbol, 0.0),
            weight_hybrid=shadow_targets.get(factor.symbol, 0.0),
        )
        securities.append(
            build_hybrid_security_view(
                quant=quant_by_symbol[factor.symbol],
                thesis=thesis,
                debate=debate,
                attribution=attribution,
                company_name=company.company_name if company is not None else "UNAVAILABLE",
                business_summary=(
                    company.business_summary if company is not None else "Identity unavailable."
                ),
                latest_event=(
                    company.events[-1].title
                    if company is not None and company.events
                    else None
                ),
                semantic_risk=(
                    ", ".join(thesis.risk_flags)
                    if thesis is not None and thesis.risk_flags
                    else None
                ),
                probability_contribution=(
                    float(raw_probability_impact)
                    if isinstance(raw_probability_impact, (int, float))
                    else None
                ),
                influence_level=LLMInfluenceLevel.LEVEL_1_SHADOW_ALPHA,
            )
        )

    all_events = tuple(
        event
        for company in evidence.companies.values()
        for event in company.events
    )
    all_analyses = tuple(
        analysis
        for company in evidence.companies.values()
        for analysis in company.analyses
    )
    market = build_market_intelligence(
        as_of=workflow.decision_time,
        quant_regime=workflow.risk_regime,
        events=all_events,
        analyses=all_analyses,
    )
    semantic_risk = portfolio_semantic_risk(
        tuple(sorted(set(current_weights) | set(target_weights) | set(shadow_targets))),
        themes,
        risks,
        event_ids,
    )
    real_theses = len(thesis_by_symbol)
    real_decisions = sum(value != 0.0 for value in applied_adjustments.values())
    status = HybridIntelligenceStatus(
        provider=provider_name,
        model=model,
        data_freshness=workflow.data_freshness,
        event_intelligence="AVAILABLE" if all_events else "DEGRADED",
        company_intelligence="AVAILABLE" if real_theses else "DEGRADED",
        market_intelligence="AVAILABLE" if all_analyses else "DEGRADED",
        semantic_alpha="SHADOW_ACTIVE" if real_theses else "SHADOW_DEGRADED",
        promotion_gate="INSUFFICIENT_FORWARD_EVIDENCE",
        formal_economic_influence=0.0,
    )
    return {
        "schema_version": "hybrid-intelligence-artifact-v2",
        "status": status.model_dump(mode="json"),
        "securities": [item.model_dump(mode="json") for item in securities],
        "actions": _shadow_actions(workflow, target_weights, shadow_targets, shadow_output),
        "market": market.model_dump(mode="json"),
        "portfolio_semantic_risk": semantic_risk.model_dump(mode="json"),
        "shadow_ranking": list(shadow_ranking),
        "llm_inferences": inferences,
        "structured_theses": {
            symbol: thesis.model_dump(mode="json")
            for symbol, thesis in sorted(thesis_by_symbol.items())
        },
        "debates": {
            symbol: debate.model_dump(mode="json")
            for symbol, debate in sorted(debate_by_symbol.items())
        },
        "event_provenance": {
            symbol: [item.model_dump(mode="json") for item in company.events]
            for symbol, company in sorted(evidence.companies.items())
            if company.events
        },
        "degradation": {
            "by_symbol": {symbol: list(value) for symbol, value in sorted(failures.items())},
            "rejected_events": list(evidence.rejected_events),
            "connectivity": connectivity,
        },
        "shadow_pipeline": _shadow_pipeline_document(shadow_output),
        "decision_attribution": {
            "quant_only": "persisted deterministic production target",
            "hybrid": "independent shadow rerun through canonical optimizer and risk wall",
            "llm_formal_influence": 0.0,
            "production_optimizer_final_authority": True,
            "shadow_lambda": SHADOW_LAMBDA,
            "semantic_alpha_semantics": (
                "bounded engineering proxy; not validated expected return"
            ),
        },
        "counts": {
            "real_structured_theses": real_theses,
            "real_shadow_llm_decisions": real_decisions,
            "hybrid_counterfactual_executed": int(shadow_output is not None),
            "pit_events": len(all_events),
        },
        "invariants": {
            "long_only": True,
            "auto_execution": False,
            "manual_confirmation": True,
            "llm_cannot_bypass_risk": True,
            "production_lambda": 0.0,
            "pre_optimizer_top_n": None,
            "fixed_holdings_cap": None,
            "all_eligible_securities_retained": len(securities) == len(factors),
            "production_targets_unchanged": True,
        },
    }


def _run_shadow_pipeline(
    *,
    workflow: TodayResult,
    effective_config: EffectiveRuntimeConfig | None,
    adjustments: dict[str, float],
) -> DailyQuantOutput | None:
    context = getattr(workflow, "shadow_context", None)
    if context is None or effective_config is None:
        return None
    signals = tuple(
        _shadow_signal(signal, adjustments.get(signal.symbol, 0.0))
        for signal in context.inputs.alpha_signals
    )
    pipeline = build_daily_quant_pipeline(
        effective_config,
        context.validation_id,
        operational_mode=context.operational_mode,
    )
    return pipeline.run(replace(context.inputs, alpha_signals=signals))


def _shadow_signal(signal: AlphaSignal, adjustment: float) -> AlphaSignal:
    if not isfinite(adjustment):
        raise ValueError("shadow semantic adjustment must be finite")
    return replace(
        signal,
        expected_excess_return=signal.expected_excess_return + adjustment,
        model_version=f"{signal.model_version}|AGENTIC_SHADOW_V1",
    )


def _shadow_actions(
    workflow: TodayResult,
    quant_targets: dict[str, float],
    shadow_targets: dict[str, float],
    shadow_output: DailyQuantOutput | None,
) -> list[dict[str, object]]:
    current = workflow.current_weights or {}
    symbols = sorted(set(current) | set(quant_targets) | set(shadow_targets))
    blocked = (
        shadow_output is not None
        and shadow_output.status is ProductionPipelineStatus.BLOCKED
    )
    actions: list[dict[str, object]] = []
    for symbol in symbols:
        quant_target = float(quant_targets.get(symbol, 0.0))
        hybrid_target = float(shadow_targets.get(symbol, 0.0))
        delta = hybrid_target - float(current.get(symbol, 0.0))
        action = (
            "BLOCKED_BY_DETERMINISTIC_RISK"
            if blocked
            else "BUY"
            if delta > 1e-12
            else "SELL"
            if delta < -1e-12
            else "HOLD"
        )
        actions.append(
            HybridActionView(
                symbol=symbol,
                current_weight=float(current.get(symbol, 0.0)),
                quant_only_target=quant_target,
                hybrid_target=hybrid_target,
                final_risk_adjusted_target=(
                    float(current.get(symbol, 0.0)) if blocked else hybrid_target
                ),
                action=action,
            ).model_dump(mode="json")
        )
    return actions


def _shadow_pipeline_document(output: DailyQuantOutput | None) -> dict[str, object]:
    if output is None:
        return {
            "status": "NOT_RUN",
        "reason": "SHADOW_CONTEXT_UNAVAILABLE",
            "deterministic_risk_evaluated": False,
        }
    target = output.target
    return {
        "status": output.status.value,
        "stages": [asdict(item) for item in output.stages],
        "blockers": list(output.blockers),
        "target_weights": dict(target.target_weights) if target is not None else {},
        "turnover": target.turnover if target is not None else None,
        "estimated_transaction_cost": (
            target.estimated_transaction_cost if target is not None else None
        ),
        "hhi": target.hhi if target is not None else None,
        "deterministic_risk_evaluated": output.risk is not None,
        "risk_status": output.risk.status.value if output.risk is not None else "NOT_RUN",
        "stress": asdict(output.stress) if output.stress is not None else None,
        "manual_only": True,
        "production_authority": False,
    }


def _semantic_score(analyses: tuple[EventAnalysis, ...], debate: LLMQuantDebate) -> float:
    values = [
        raw_event_score(item.features)
        for item in analyses
        if item.status == "AVAILABLE"
    ]
    values.append(debate.semantic_adjustment_direction * debate.confidence)
    return max(-1.0, min(1.0, mean(values))) if values else 0.0


def _shadow_ranking_key(item: dict[str, object]) -> tuple[float, str]:
    alpha = item.get("shadow_expected_alpha")
    numeric = float(alpha) if isinstance(alpha, (int, float)) else float("-inf")
    return -numeric, str(item.get("symbol", ""))


def _semantic_alpha_proxy(mu_quant: float, semantic_score: float) -> float:
    scale = min(
        MAX_ABSOLUTE_SEMANTIC_ADJUSTMENT,
        max(abs(mu_quant), 1e-6) * MAX_RELATIVE_SEMANTIC_ADJUSTMENT,
    )
    return max(-1.0, min(1.0, semantic_score)) * scale


def _optional_finite(value: object) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    numeric = float(value)
    return numeric if isfinite(numeric) else None


def _insufficient_debate(quant: QuantThesis, reason: str) -> LLMQuantDebate:
    return LLMQuantDebate(
        symbol=quant.symbol,
        security=quant.security,
        decision=DebateDecision.INSUFFICIENT_INFORMATION,
        agreement_strength=0.0,
        semantic_adjustment_direction=0.0,
        confidence=0.0,
        reason_codes=(reason,),
    )


def _agentic_event(
    event: UnifiedEvent,
    identity: SecurityIdentity,
    decision_time: datetime,
) -> EventRecord:
    visible = event.at_cutoff(decision_time)
    if visible is None or visible.symbol is None:
        raise ValueError("event is not visible at decision cutoff")
    available_at = max(
        _utc(item.available_at or item.observed_at) for item in visible.evidence
    )
    return EventRecord(
        event_id=visible.event_id,
        symbol=identity.symbol,
        company_id=identity.company_id,
        security=identity,
        event_type=_agentic_event_type(visible),
        source_id=visible.source_identifier,
        source_name=visible.source,
        source_type="STORED_STRUCTURED_EVENT",
        source_reliability_class=visible.backtest_safety.value,
        title=visible.title,
        summary=visible.summary,
        published_at=_utc(visible.published_at),
        first_seen_at=_utc(visible.observed_at),
        ingested_at=max(_utc(visible.ingested_at), available_at),
        effective_from=_utc(visible.effective_at),
        decision_cutoff=_utc(decision_time),
        available_at=available_at,
        content_hash=visible.source_hash,
        source_hash=visible.source_hash,
        raw_payload_reference=visible.source_identifier,
    )


def _stored_event_analysis(
    event: UnifiedEvent,
    record: EventRecord,
    decision_time: datetime,
) -> EventAnalysis:
    direction = {
        EventDirection.POSITIVE: 1.0,
        EventDirection.NEGATIVE: -1.0,
        EventDirection.MIXED: 0.0,
        EventDirection.NEUTRAL: 0.0,
        EventDirection.UNKNOWN: 0.0,
    }[event.direction]
    age_days = max(
        0.0,
        (_utc(decision_time) - record.available_at).total_seconds() / 86_400,
    )
    horizon = max(1, event.expected_horizon)
    features = EventIntelligenceFeatures(
        direction=direction,
        magnitude=min(abs(event.magnitude or 0.0), 1.0),
        novelty=event.novelty,
        company_relevance=event.relevance,
        market_surprise=max(-1.0, min(1.0, event.surprise or 0.0)),
        confidence=event.confidence,
        source_quality=(
            1.0 if event.backtest_safety is BacktestSafety.BACKTEST_SAFE else 0.0
        ),
        time_decay=max(0.0, 1.0 - age_days / horizon),
        expected_horizon_sessions=horizon,
        evidence_event_ids=(event.event_id,),
    )
    inference = LLMInferenceRecord(
        inference_id=f"stored-event-{event.event_id}",
        provider=event.source,
        model=event.model_version,
        model_version=event.model_version,
        prompt_version=event.prompt_version,
        schema_version_used=event.schema_version,
        request_timestamp=_utc(event.observed_at),
        response_timestamp=_utc(event.created_at),
        input_hash=sha256(event.source_hash.encode()).hexdigest(),
        output_hash=sha256(event.model_dump_json().encode("utf-8")).hexdigest(),
        temperature=0.0,
        latency_ms=max(
            0,
            round(
                (_utc(event.created_at) - _utc(event.observed_at)).total_seconds()
                * 1000
            ),
        ),
        status="STORED_VALIDATED_OUTPUT",
        event_ids=(event.event_id,),
        parsed_output=features.model_dump(mode="json"),
        evidence_references=tuple(item.evidence_id for item in event.evidence),
    )
    return EventAnalysis(features=features, inference=inference, status="AVAILABLE")


def _agentic_event_type(event: UnifiedEvent) -> EventType:
    mapping = {
        "MERGER_ACQUISITION": EventType.M_AND_A,
        "REGULATION": EventType.REGULATORY,
        "ANALYST_ACTION": EventType.ANALYST,
        "FINANCING": EventType.CAPITAL_RAISE,
        "GEOPOLITICS": EventType.GEOPOLITICAL,
        "INDUSTRY": EventType.SECTOR,
    }
    try:
        return EventType(event.event_type.value.casefold())
    except ValueError:
        return mapping.get(event.event_type.value, EventType.OTHER)


def _utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=UTC)
        if value.tzinfo is None or value.utcoffset() is None
        else value.astimezone(UTC)
    )
