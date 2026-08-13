"""ROUND 13.1 SEC/PIT intelligence commands; all outputs are research SHADOW."""

from __future__ import annotations

import json
import os
from argparse import Namespace
from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

import pandas as pd
from rich.console import Console
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personal_alpha_terminal.agents.llm.foundation import LLMGateway, deepseek_model_registry
from personal_alpha_terminal.agents.llm.providers import DeepSeekProvider
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
from personal_alpha_terminal.data.database import get_session_factory, session_scope
from personal_alpha_terminal.data.migrations import upgrade_database
from personal_alpha_terminal.intelligence.issuer_identity import (
    IssuerIdentityResolver,
    extract_issuer_identity_candidates,
    import_issuer_security_mappings,
    remap_landing_zone,
)
from personal_alpha_terminal.intelligence.llm_runtime import (
    DEFAULT_LLM_RUNTIME_STATUS_PATH,
    llm_runtime_status,
)
from personal_alpha_terminal.intelligence.round13_contracts import (
    FEATURE_TRANSFORM_VERSION,
    PRODUCTION_INFLUENCE,
    PROMPT_VERSION,
    AcceptedSecEvent,
    LLMShadowFeature,
    build_shadow_features,
)
from personal_alpha_terminal.intelligence.round13_extraction import (
    Round13ExtractionResult,
    Round13SecExtractor,
)
from personal_alpha_terminal.intelligence.round14_dataset import (
    build_outcomes,
    write_outcome_dataset,
)
from personal_alpha_terminal.intelligence.schemas import (
    BacktestSafety,
    EventDirection,
    EventEvidence,
    EventType,
    RawInformation,
    UnifiedEvent,
)
from personal_alpha_terminal.intelligence.sec_edgar_acquisition import (
    CikSecurityMapping,
    EdgarFilingRecord,
    SecEdgarAcquisitionConfig,
    SecEdgarClient,
    SecEdgarRateLimiter,
    acquire_company_corpus,
    load_cik_mapping_manifest,
    verify_sec_edgar_landing_zone,
)
from personal_alpha_terminal.intelligence.storage import (
    DatabaseExtractionCache,
    DatabaseLLMUsageLedger,
    IntelligenceRepository,
)
from personal_alpha_terminal.intelligence.text_corpus import (
    TextCorpusSource,
    TextCorpusSourceKind,
)
from personal_alpha_terminal.models.intelligence import (
    IntelligenceEvent,
    IntelligenceFeature,
    IntelligenceRawInformation,
    IntelligenceResearchResult,
)
from personal_alpha_terminal.models.market import Price, Stock
from personal_alpha_terminal.quant_engine.round14_llm_alpha_research import (
    build_round15_dataset,
    run_round14_alpha_research,
    write_immutable_json,
)
from personal_alpha_terminal.quant_engine.round15_probability_research import (
    run_round15_probability_research,
)
from personal_alpha_terminal.quant_engine.round15_probability_research import (
    write_immutable_json as write_probability_immutable_json,
)

console = Console()
ROOT = Path("var/intelligence/sec-edgar")
PROVIDER_VERSION = "sec-edgar-v1"


def intelligence_command(args: Namespace, config: EffectiveRuntimeConfig) -> int:
    action = str(args.intelligence_action)
    root = Path(getattr(args, "root", ROOT))
    if action == "status":
        return _status(root, config.settings)
    if action in {"acquire", "backfill"}:
        return _acquire(args, root, backfill=action == "backfill")
    if action == "process":
        return _process(args, root, config)
    if action == "inspect":
        return _inspect(root, str(args.ticker).upper())
    if action == "audit":
        return _audit(root)
    if action == "outcomes":
        return _outcomes(args, root, config)
    if action == "alpha-research":
        return _alpha_research(args, root, config)
    if action == "probability-research":
        return _probability_research(args, root)
    if action == "identity":
        return _identity(args, root, config)
    raise ValueError(f"unsupported intelligence action: {action}")


def _acquire(args: Namespace, root: Path, *, backfill: bool) -> int:
    user_agent = os.environ.get("SEC_EDGAR_USER_AGENT", "").strip()
    if not user_agent:
        console.print("BLOCKED_EXTERNAL_SEC_DATA: SEC_EDGAR_USER_AGENT is required.")
        return 2
    cik = int(args.cik)
    end = _date_arg(getattr(args, "end", None)) or datetime.now(UTC).date()
    default_days = 365 * 3 if backfill else 14
    start = _date_arg(getattr(args, "start", None)) or end - timedelta(days=default_days)
    mapping_override = (
        _mapping_for_cik(Path(args.mapping), cik)
        if getattr(args, "mapping", None) is not None
        else None
    )
    acquisition_id = str(getattr(args, "acquisition_id", None) or f"cik-{cik}")
    output = root / "landing" / acquisition_id
    source = TextCorpusSource(
        source_id="sec-edgar",
        source_kind=TextCorpusSourceKind.SEC_FILING,
        provider="sec-edgar-immutable",
        availability_timestamp_proven=True,
        revision_history=True,
        symbol_mapping=True,
        timezone=True,
        raw_payload_immutable=True,
        rate_limit_compliant=True,
        coverage_start=start,
        coverage_end=end,
    )
    upgrade_database()
    try:
        with session_scope(get_session_factory()) as session:
            resolver = IssuerIdentityResolver(session)

            def resolve_mapping(record: EdgarFilingRecord) -> CikSecurityMapping | None:
                if mapping_override is not None:
                    return mapping_override
                if record.acceptance_datetime is None:
                    return None
                return resolver.security_mapping_for(cik, record.acceptance_datetime)

            report = acquire_company_corpus(
                cik=cik,
                mapping=mapping_override,
                mapping_resolver=resolve_mapping,
                config=SecEdgarAcquisitionConfig(user_agent=user_agent),
                client=SecEdgarClient(
                    SecEdgarAcquisitionConfig(user_agent=user_agent),
                    rate_limiter=SecEdgarRateLimiter(max_requests_per_second=1.0),
                ),
                source=source,
                output=output,
                acquisition_id=acquisition_id,
                required_start=start,
                required_end=end,
                max_documents=int(getattr(args, "max_documents", 20)),
                provider_version=PROVIDER_VERSION,
            )
            repository = IntelligenceRepository(session)
            for document in _load_documents(root):
                repository.upsert_raw(document)
            session.flush()
    except Exception as error:
        console.print(f"BLOCKED_EXTERNAL_SEC_DATA: {type(error).__name__}: {error}")
        return 2
    console.print(json.dumps(report.document(), ensure_ascii=False, indent=2, sort_keys=True))
    mapped_documents = sum(
        1 for document in _load_documents(root) if document.permanent_security_id
    )
    if mapping_override is None and mapped_documents == 0:
        console.print(
            "RESEARCH_LIMITED_SURVIVORSHIP: issuer-level corpus; PIT ticker mapping unavailable."
        )
    elif mapped_documents:
        console.print(
            "RESEARCH_PIT_IDENTITY: canonical issuer/security mapping applied "
            f"to {mapped_documents} documents."
        )
    return 0 if report.acquired_document_count else 3


def _process(args: Namespace, root: Path, config: EffectiveRuntimeConfig) -> int:
    documents = _load_documents(root)
    if not documents:
        console.print("No SEC raw documents found. Run intelligence acquire/backfill first.")
        return 3
    limit = int(getattr(args, "max_documents", 10))
    cutoff = _datetime_arg(getattr(args, "cutoff", None)) or datetime.now(UTC)
    eligible = tuple(
        sorted(
            (
                item
                for item in documents
                if item.available_at is not None and item.available_at <= cutoff
            ),
            key=lambda item: (item.permanent_security_id is None, item.available_at),
        )
    )[:limit]
    if not eligible:
        console.print("NO_PIT_ELIGIBLE_DOCUMENTS_AT_CUTOFF")
        return 3
    upgrade_database()
    with session_scope(get_session_factory()) as session:
        credential = config.settings.deepseek_api_key
        if not credential:
            console.print("DEEPSEEK_CREDENTIAL_MISSING")
            return 2
        provider = DeepSeekProvider(
            api_key=credential,
            model=config.settings.deepseek_model,
            timeout_seconds=config.settings.llm_timeout_seconds,
            max_retries=config.settings.llm_max_retries,
            base_url=config.settings.deepseek_base_url,
        )
        gateway = LLMGateway(provider, DatabaseLLMUsageLedger(session), deepseek_model_registry())
        cache = DatabaseExtractionCache(
            session, model_version=gateway.model, prompt_version=PROMPT_VERSION
        )
        extractor = Round13SecExtractor(gateway, cache)
        repository = IntelligenceRepository(session)
        results: list[Round13ExtractionResult] = []
        events: list[AcceptedSecEvent] = []
        for raw in eligible:
            repository.upsert_raw(raw)
            result = extractor.extract(raw)
            results.append(result)
            events.extend(result.accepted)
        raw_by_id = {item.raw_id: item for item in eligible}
        for event in events:
            if not repository.event_exists(event.event_id):
                repository.upsert_event(_to_unified_event(event, raw_by_id[event.raw_id]))
        features = build_shadow_features(tuple(events), as_of=cutoff)
        _persist_shadow_features(session, features)
        payload: dict[str, Any] = {
            "mode": "HISTORICAL_PIT_REPLAY"
            if getattr(args, "historical_replay", False)
            else "INCREMENTAL",
            "decision_cutoff": cutoff.isoformat(),
            "processed_documents": len(eligible),
            "processed_raw_ids": [item.raw_id for item in eligible],
            "structured_events": sum(item.structured_events for item in results),
            "llm_calls": sum(item.llm_calls for item in results),
            "llm_cache_hits": sum(item.cache_hit for item in results),
            "events_accepted": len(events),
            "events_quarantined": sum(len(item.quarantine_reasons) for item in results),
            "blocked_security_mapping_events": sum(
                1 for item in events if item.security_mapping_status != "SECURITY_MAPPED"
            ),
            "shadow_features_generated": len(features),
            "tokens_in": sum(item.prompt_tokens for item in results),
            "tokens_out": sum(item.completion_tokens for item in results),
            "estimated_api_cost_usd": sum(item.estimated_cost_usd for item in results),
            "latency_ms": sum(item.latency_ms for item in results),
            "provider": gateway.name,
            "model": gateway.model,
            "prompt_version": PROMPT_VERSION,
            "feature_transform_version": FEATURE_TRANSFORM_VERSION,
            "production_influence": PRODUCTION_INFLUENCE,
            "events": [_json(asdict(item)) for item in events],
            "quarantine": [
                {"raw_id": item.raw_id, "reasons": item.quarantine_reasons}
                for item in results
                if item.quarantine_reasons
            ],
            "features": [_json(asdict(item)) for item in features],
            "research_label": "RESEARCH_LIMITED_SURVIVORSHIP",
            "auto_execution": False,
            "manual_execution_only": True,
        }
        result_id = sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        repository.add_result(
            result_id=result_id,
            result_type="ROUND13_SEC_SHADOW_FEATURES",
            schema_version="round13-feature-foundation-v1",
            model_version=gateway.model,
            prompt_version=PROMPT_VERSION,
            data_cutoff=cutoff,
            status="SHADOW",
            payload=payload,
        )
        _persist_research_dataset(root, result_id, payload, config)
    output = root / "processed" / f"{result_id}.json"
    _write_immutable_json(output, payload)
    _write_latest(root / "processed" / "latest.json", {"result_id": result_id, **payload})
    console.print(
        json.dumps(
            {
                key: value
                for key, value in payload.items()
                if key not in {"events", "features", "quarantine"}
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if events and features else 3


def _status(root: Path, settings: Settings) -> int:
    documents = _load_documents(root)
    latest = _read_json(root / "processed" / "latest.json")
    upgrade_database()
    with session_scope(get_session_factory()) as session:
        counts = {
            "raw_documents_database": session.scalar(
                select(func.count()).select_from(IntelligenceRawInformation)
            )
            or 0,
            "events_database": session.scalar(select(func.count()).select_from(IntelligenceEvent))
            or 0,
            "shadow_features_database": session.scalar(
                select(func.count()).select_from(IntelligenceFeature)
            )
            or 0,
            "research_results_database": session.scalar(
                select(func.count()).select_from(IntelligenceResearchResult)
            )
            or 0,
        }
    pit = tuple(
        item for item in documents if item.accepted_at and item.available_at == item.accepted_at
    )
    issuer_resolved = tuple(item for item in documents if item.issuer_id)
    security_mapped = tuple(item for item in documents if item.permanent_security_id)
    processable = tuple(item for item in pit if item.issuer_id)
    runtime = llm_runtime_status(settings, DEFAULT_LLM_RUNTIME_STATUS_PATH)
    payload = {
        "raw_documents": len(documents),
        "landing_zone_raw_documents": len(documents),
        "last_acquisition_documents": _latest_acquisition_documents(root),
        "pit_certified_documents": len(pit),
        "issuer_resolved_documents": len(issuer_resolved),
        "security_mapped_documents": len(security_mapped),
        "processable_documents": len(processable),
        "processed_documents": _int(latest.get("processed_documents")),
        "events": _int(latest.get("events_accepted")),
        "accepted_events": _int(latest.get("events_accepted")),
        "quarantined_events": _int(latest.get("events_quarantined")),
        "blocked_security_mapping_events": _int(
            latest.get("blocked_security_mapping_events")
        ),
        "shadow_features": _int(latest.get("shadow_features_generated")),
        "latest_available_at": max(
            (item.available_at for item in pit if item.available_at is not None), default=None
        ),
        "mapping_status": "SECURITY_MAPPED" if security_mapped else "SECURITY_MAPPING_MISSING",
        "llm_credential": "PRESENT" if settings.deepseek_api_key else "MISSING",
        "llm_connectivity": runtime.connectivity,
        "provider": "deepseek",
        "model": settings.deepseek_model,
        "prompt_version": PROMPT_VERSION,
        "cache_ratio": _ratio(
            _int(latest.get("llm_cache_hits")), _int(latest.get("processed_documents"))
        ),
        "estimated_cost_usd": _float(latest.get("estimated_api_cost_usd")),
        "production_influence": "NONE",
        "mode": "SHADOW",
        **counts,
    }
    console.print(json.dumps(_json(payload), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _inspect(root: Path, ticker: str) -> int:
    latest = _read_json(root / "processed" / "latest.json")
    events = [item for item in _records(latest.get("events")) if item.get("ticker_asof") == ticker]
    features = [
        item for item in _records(latest.get("features")) if item.get("ticker_asof") == ticker
    ]
    console.print(
        json.dumps(
            {"ticker": ticker, "events": events, "features": features},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if events or features else 3


def _audit(root: Path) -> int:
    landing = root / "landing"
    reports = []
    for path in landing.glob("*/acquisition.json") if landing.exists() else ():
        verification = verify_sec_edgar_landing_zone(path.parent)
        reports.append(
            {"path": str(path.parent), "ok": verification.ok, "blockers": verification.blockers}
        )
    documents = _load_documents(root)
    latest = _read_json(root / "processed" / "latest.json")
    cutoff = _datetime_arg(latest.get("decision_cutoff"))
    events = _records(latest.get("events"))
    mapped_documents = tuple(item for item in documents if item.permanent_security_id)
    all_raw_immutable = bool(reports) and all(item["ok"] for item in reports)
    event_evidence_complete = bool(events) and all(
        item.get("evidence_hash")
        and item.get("source_span")
        and item.get("response_hash")
        and item.get("model_name")
        and item.get("prompt_version")
        for item in events
    )
    evidence_span_hashes_match = bool(events) and all(
        sha256(str(item.get("source_span") or "").encode("utf-8")).hexdigest()
        == str(item.get("evidence_hash") or "")
        for item in events
    )
    future_leakage = True
    if cutoff is not None:
        processed_raw_ids = set(str(item) for item in _records(latest.get("processed_raw_ids")))
        processed_documents = tuple(
            item for item in documents if item.raw_id in processed_raw_ids
        )
        future_leakage = all(
            item.available_at is not None and item.available_at <= cutoff
            for item in processed_documents
        ) and all(
            _datetime_arg(item.get("available_at")) is not None
            and (
                _datetime_arg(item.get("available_at"))
                or datetime.min.replace(tzinfo=UTC)
            ) <= cutoff
            for item in events
        )
    production_influence_none = str(latest.get("production_influence", "NONE")) in {
        "0",
        "0.0",
        "NONE",
    } and latest.get("auto_execution", False) is False
    identity_source_complete = all(
        item.security_mapping_source and item.security_mapping_source_version
        for item in mapped_documents
    )
    payload = {
        "landing_zones": reports,
        "all_raw_immutable": all_raw_immutable,
        "raw_document_count": len(documents),
        "pit_certified_document_count": sum(
            1
            for item in documents
            if item.accepted_at is not None and item.available_at == item.accepted_at
        ),
        "issuer_resolved_document_count": sum(1 for item in documents if item.issuer_id),
        "security_mapped_document_count": len(mapped_documents),
        "event_evidence_complete": event_evidence_complete,
        "evidence_span_hashes_match": evidence_span_hashes_match,
        "llm_response_lineage_complete": bool(events) and all(
            item.get("response_hash") and item.get("model_name") and item.get("prompt_version")
            for item in events
        ),
        "future_leakage": future_leakage,
        "identity_source_complete": identity_source_complete,
        "production_influence": latest.get("production_influence", 0.0),
        "auto_execution": latest.get("auto_execution", False),
        "production_influence_none": production_influence_none,
    }
    console.print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    passed = (
        all_raw_immutable
        and event_evidence_complete
        and evidence_span_hashes_match
        and future_leakage
        and identity_source_complete
        and production_influence_none
    )
    return 0 if passed else 3


def _latest_acquisition_documents(root: Path) -> int:
    reports: list[tuple[datetime, int]] = []
    if not (root / "landing").exists():
        return 0
    for path in (root / "landing").glob("*/acquisition.json"):
        try:
            document = _read_json(path)
            retrieved = datetime.fromisoformat(str(document.get("retrieved_at") or ""))
            reports.append((retrieved, int(str(document.get("acquired_document_count") or 0))))
        except (OSError, ValueError, TypeError):
            continue
    if not reports:
        return 0
    return max(reports, key=lambda item: item[0])[1]


def _load_documents(root: Path) -> tuple[RawInformation, ...]:
    documents: dict[str, RawInformation] = {}
    for path in (root / "landing").glob("*/documents.jsonl") if (root / "landing").exists() else ():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = RawInformation.model_validate_json(line)
                current = documents.get(item.raw_id)
                if current is None or (
                    current.permanent_security_id is None and item.permanent_security_id is not None
                ):
                    documents[item.raw_id] = item
    return tuple(sorted(documents.values(), key=lambda item: (item.available_at, item.raw_id)))


def _identity(args: Namespace, root: Path, config: EffectiveRuntimeConfig) -> int:
    action = str(getattr(args, "identity_action", ""))
    if action != "import-filings":
        console.print("IDENTITY_ACTION_REQUIRED: use `intelligence identity import-filings`.")
        return 2
    upgrade_database()
    with session_scope(get_session_factory()) as session:
        documents = _load_documents(root)
        candidates = extract_issuer_identity_candidates(documents)
        imported = import_issuer_security_mappings(session, candidates)
        resolver = IssuerIdentityResolver(session)
        remapped = remap_landing_zone(root, resolver)
        repository = IntelligenceRepository(session)
        for document in _load_documents(root):
            repository.upsert_raw(document)
        session.flush()
        mapped_documents = sum(
            1 for document in _load_documents(root) if document.permanent_security_id
        )
    payload = {
        "identity_source": "sec-edgar-filing-identity-v1",
        "candidate_count": len(candidates),
        "imported_or_updated": imported,
        "remapped_documents": remapped,
        "mapped_documents": mapped_documents,
    }
    console.print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if imported or remapped else 3


def _to_unified_event(event: AcceptedSecEvent, raw: RawInformation) -> UnifiedEvent:
    event_type = {
        "EARNINGS": EventType.EARNINGS,
        "REVENUE_CHANGE": EventType.REVENUE,
        "MARGIN_CHANGE": EventType.MARGIN,
        "GUIDANCE_RAISE": EventType.GUIDANCE,
        "GUIDANCE_CUT": EventType.GUIDANCE,
        "GUIDANCE_WITHDRAWN": EventType.GUIDANCE,
        "BUYBACK": EventType.BUYBACK,
        "DIVIDEND_CHANGE": EventType.DIVIDEND,
        "MANAGEMENT_CHANGE": EventType.MANAGEMENT,
        "LITIGATION": EventType.LITIGATION,
        "REGULATORY": EventType.REGULATION,
        "CYBERSECURITY": EventType.CYBERSECURITY,
        "INSIDER_BUY": EventType.INSIDER,
        "INSIDER_SELL": EventType.INSIDER,
    }.get(event.event_type, EventType.OTHER)
    direction = {
        "POSITIVE": EventDirection.POSITIVE,
        "NEGATIVE": EventDirection.NEGATIVE,
        "MIXED": EventDirection.MIXED,
        "NEUTRAL": EventDirection.NEUTRAL,
    }[event.direction]
    materiality = {"LOW": 0.25, "MEDIUM": 0.6, "HIGH": 1.0}[event.materiality]
    novelty = {"REITERATED": 0.2, "UPDATED": 0.6, "NEW": 1.0}[event.novelty]
    horizon = {"IMMEDIATE": 3, "SHORT": 10, "MEDIUM": 30, "LONG": 90}[event.horizon]
    created_at = datetime.now(UTC)
    evidence = EventEvidence(
        evidence_id=event.evidence_hash,
        source="sec-edgar",
        source_identifier=raw.source_identifier,
        source_hash=raw.source_hash or "",
        published_at=event.event_timestamp,
        observed_at=event.available_at,
        available_at=event.available_at,
        reference=f"{raw.source_url or raw.source_identifier}#{event.evidence_hash}",
        extraction_confidence=event.extraction_confidence,
    )
    return UnifiedEvent(
        event_id=event.event_id,
        symbol=event.ticker_asof,
        entity=event.issuer_id,
        event_type=event_type,
        event_subtype=event.event_type,
        title=f"SEC {event.event_type}",
        summary=event.summary,
        published_at=event.event_timestamp,
        observed_at=event.available_at,
        effective_at=event.event_timestamp,
        ingested_at=created_at,
        source="sec-edgar",
        source_identifier=raw.source_identifier,
        source_hash=raw.source_hash or "",
        direction=direction,
        magnitude=event.magnitude,
        relevance=materiality,
        novelty=novelty,
        confidence=event.extraction_confidence,
        expected_horizon=horizon,
        affected_assets=(event.ticker_asof,) if event.ticker_asof else (),
        structured_features={
            "issuer_id": event.issuer_id,
            "issuer_name": raw.issuer_name,
            "claimed_ticker_asof": event.claimed_ticker_asof,
            "security_mapping_status": event.security_mapping_status,
            "materiality": event.materiality,
            "source_section": event.source_section,
            "source_span": event.source_span,
            "evidence_status": event.evidence_status,
            "production_influence": "NONE",
        },
        evidence=(evidence,),
        model_version=event.model_name,
        prompt_version=event.prompt_version,
        data_cutoff=event.available_at,
        created_at=created_at,
        backtest_safety=BacktestSafety.BACKTEST_SAFE,
    )


def _persist_shadow_features(
    session: Session, features: tuple[LLMShadowFeature, ...]
) -> None:
    for feature in features:
        if not feature.event_ids:
            continue
        if session.scalar(
            select(IntelligenceFeature.id).where(
                IntelligenceFeature.feature_id == feature.feature_id
            )
        ) is None:
            session.add(
                IntelligenceFeature(
                    feature_id=feature.feature_id,
                    event_id=feature.event_ids[0],
                    schema_version="round13-shadow-feature-v1",
                    model_version=feature.transform_version,
                    prompt_version=PROMPT_VERSION,
                    data_cutoff=feature.as_of,
                    status="SHADOW_ONLY",
                    payload=_json(asdict(feature)),
                )
            )


def _persist_research_dataset(
    root: Path,
    result_id: str,
    payload: dict[str, Any],
    config: EffectiveRuntimeConfig,
) -> None:
    events = _records(payload.get("events"))
    features = _records(payload.get("features"))
    by_issuer: dict[tuple[str, str | None], dict[str, float]] = {}
    for item in features:
        key = (str(item["issuer_id"]), item.get("ticker_asof"))
        by_issuer.setdefault(key, {})[str(item["feature_name"])] = float(item["value"])
    rows: list[dict[str, Any]] = []
    for (issuer_id, ticker), shadow in sorted(by_issuer.items()):
        issuer_events = [item for item in events if item.get("issuer_id") == issuer_id]
        evidence_hash = sha256(
            "|".join(sorted(str(item["evidence_hash"]) for item in issuer_events)).encode()
        ).hexdigest()
        rows.append(
            {
                "decision_date": str(payload["decision_cutoff"])[:10],
                "issuer_id": issuer_id,
                "ticker_asof": ticker,
                "classical_features": {},
                "classical_feature_status": "NOT_SUPPLIED_TO_INTELLIGENCE_BUILD",
                "llm_shadow_features": shadow,
                "event_features": issuer_events,
                "benchmark_identity": config.benchmark,
                "transaction_cost_convention": asdict(config.transaction_cost),
                "pit_evidence_hash": evidence_hash,
            }
        )
    dataset: dict[str, Any] = {
        "dataset_id": result_id,
        "status": "RESEARCH_LIMITED_SURVIVORSHIP",
        "production_influence": "NONE",
        "features": rows,
        "outcome_location": f"outcomes/{result_id}.json",
        "future_outcomes_read_during_build": False,
    }
    outcome: dict[str, Any] = {
        "dataset_id": result_id,
        "status": "OUTCOMES_NOT_YET_OBSERVED",
        "outcomes": [],
        "feature_location": f"features/{result_id}.json",
    }
    _write_immutable_json(root / "research" / "features" / f"{result_id}.json", dataset)
    _write_immutable_json(root / "research" / "outcomes" / f"{result_id}.json", outcome)


def _probability_research(args: Namespace, root: Path) -> int:
    evaluated_at = _datetime_arg(getattr(args, "evaluated_at", None)) or datetime.now(UTC)
    dataset_id = getattr(args, "dataset_id", None)
    round15_root = root / "research" / "round15"
    if dataset_id:
        dataset_path = round15_root / f"{dataset_id}.json"
        if not dataset_path.exists():
            console.print("ROUND15_DATASET_NOT_FOUND")
            return 2
    else:
        candidates = sorted(
            round15_root.glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            console.print("NO_ROUND15_DATASET")
            return 3
        dataset_path = candidates[0]
    dataset_document = _read_json(dataset_path)
    alpha_root = root / "research" / "round14-alpha"
    alpha_candidates = (
        sorted(
            alpha_root.glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if alpha_root.exists()
        else []
    )
    if alpha_candidates:
        alpha_document = _read_json(alpha_candidates[0])
        dataset_document["round14_verdict"] = str(alpha_document.get("verdict"))
    result = run_round15_probability_research(
        dataset_document,
        evaluated_at=evaluated_at,
    )
    result_path = root / "research" / "round15-probability" / f"{result.run_id}.json"
    write_probability_immutable_json(result_path, result.document())
    summary = {
        "run_id": result.run_id,
        "verdict": result.verdict,
        "production_weight": result.production_weight,
        "blockers": list(result.blockers),
        "locked_oos_sessions": result.locked_oos_sessions,
        "walk_forward_folds": result.walk_forward_folds,
        "counterfactual": result.counterfactual,
        "portfolio_cardinality": result.portfolio_cardinality,
        "result_file": str(result_path.resolve()),
    }
    console.print(json.dumps(summary, indent=2, sort_keys=True))
    return 0

def _alpha_research(args: Namespace, root: Path, config: EffectiveRuntimeConfig) -> int:
    evaluated_at = _datetime_arg(getattr(args, "evaluated_at", None)) or datetime.now(UTC)
    dataset_id = getattr(args, "dataset_id", None)
    outcome_root = root / "research" / "outcomes"
    if dataset_id:
        outcome_path = outcome_root / f"{dataset_id}.json"
        if not outcome_path.exists():
            console.print("OUTCOME_DATASET_NOT_FOUND")
            return 2
    else:
        candidates = sorted(
            outcome_root.glob("*r14-*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            console.print("NO_ROUND14_OUTCOME_DATASET")
            return 3
        outcome_path = candidates[0]
    outcome_document = _read_json(outcome_path)
    feature_dataset_id = str(outcome_document.get("feature_dataset_id") or "")
    feature_path = root / "research" / "features" / f"{feature_dataset_id}.json"
    if not feature_path.exists():
        console.print("FEATURE_DATASET_NOT_FOUND")
        return 2
    feature_document = _read_json(feature_path)
    result = run_round14_alpha_research(
        outcome_document,
        feature_document,
        evaluated_at=evaluated_at,
    )
    round15 = build_round15_dataset(outcome_document, feature_document)
    round15_path = root / "research" / "round15" / f"{outcome_document.get('dataset_id')}.json"
    write_immutable_json(round15_path, round15)
    result_path = root / "research" / "round14-alpha" / f"{result.run_id}.json"
    write_immutable_json(result_path, result.document())
    summary = {
        "run_id": result.run_id,
        "verdict": result.verdict,
        "status": result.status,
        "blockers": list(result.blockers),
        "observations": result.metrics.observations,
        "feature_count": result.metrics.feature_count,
        "issuer_count": result.metrics.issuer_count,
        "ticker_count": result.metrics.ticker_count,
        "hit_rate": result.metrics.hit_rate,
        "round15_dataset": str(round15_path.resolve()),
        "result_file": str(result_path.resolve()),
        "production_influence": "NONE",
    }
    console.print(json.dumps(summary, indent=2, sort_keys=True))
    return 0

def _outcomes(args: Namespace, root: Path, config: EffectiveRuntimeConfig) -> int:
    cutoff = _datetime_arg(getattr(args, "cutoff", None)) or datetime.now(UTC)
    dataset_id = getattr(args, "dataset_id", None)
    feature_root = root / "research" / "features"
    if dataset_id:
        feature_path = feature_root / f"{dataset_id}.json"
    else:
        candidates = sorted(
            feature_root.glob("*.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            console.print("NO_ROUND14_FEATURE_DATASET")
            return 3
        feature_path = candidates[0]
    if not feature_path.exists():
        console.print("FEATURE_DATASET_NOT_FOUND")
        return 2
    feature_document = _read_json(feature_path)
    resolved_id = str(feature_document.get("dataset_id") or feature_path.stem)
    outcome_id = f"{resolved_id}-r14-{cutoff.date().isoformat()}"
    symbols = {str(config.benchmark)}
    for row in _records(feature_document.get("features")):
        ticker = row.get("ticker_asof")
        if ticker:
            symbols.add(str(ticker))
    start = (cutoff - timedelta(days=730)).date()
    end = (cutoff + timedelta(days=60)).date()
    upgrade_database()
    with session_scope(get_session_factory()) as session:
        prices = _load_price_series(session, symbols, start=start, end=end)
    try:
        dataset = build_outcomes(
            feature_document,
            dataset_id=outcome_id,
            prices_by_symbol=prices,
            benchmark_symbol=config.benchmark,
            cutoff=cutoff,
        )
    except ValueError as error:
        console.print(f"ROUND14_OUTCOME_BLOCKED: {error}")
        return 2
    outcome_path = root / "research" / "outcomes" / f"{outcome_id}.json"
    write_outcome_dataset(outcome_path, dataset)
    ready = sum(1 for item in dataset.outcome_rows if item.status == "OUTCOME_READY")
    pending = sum(1 for item in dataset.outcome_rows if item.status == "OUTCOME_PENDING")
    summary = {
        "dataset_id": outcome_id,
        "feature_dataset_id": resolved_id,
        "feature_file": str(feature_path.resolve()),
        "outcome_file": str(outcome_path.resolve()),
        "cutoff": cutoff.isoformat(),
        "outcome_rows": len(dataset.outcome_rows),
        "outcomes_ready": ready,
        "outcomes_pending": pending,
        "dataset_hash": dataset.dataset_hash,
        "status": dataset.status,
        "production_influence": dataset.production_influence,
        "future_outcomes_read_during_build": False,
    }
    console.print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if ready else 3


def _load_price_series(
    session: Session, symbols: set[str], *, start: date, end: date
) -> dict[str, pd.Series]:
    rows = session.scalars(
        select(Price)
        .join(Stock, Price.stock_id == Stock.id)
        .where(
            Stock.symbol.in_(symbols),
            Price.trade_date >= start,
            Price.trade_date <= end,
        )
        .order_by(Price.stock_id, Price.trade_date)
    ).all()
    by_symbol: dict[str, dict[date, float]] = defaultdict(dict)
    for row in rows:
        symbol = row.stock.symbol if row.stock is not None else ""
        if not symbol:
            continue
        value = row.adjusted_close if row.adjusted_close is not None else row.close
        by_symbol[symbol][row.trade_date] = float(value)
    output: dict[str, pd.Series] = {}
    for symbol, values in by_symbol.items():
        if not values:
            continue
        series = pd.Series(values)
        series.index = pd.to_datetime(series.index)
        output[symbol] = series.sort_index()
    return output

def _mapping_for_cik(path: Path, cik: int) -> CikSecurityMapping | None:
    if not path.exists():
        return None
    return next((item for item in load_cik_mapping_manifest(path) if item.cik == cik), None)


def _date_arg(value: object) -> date | None:
    return date.fromisoformat(str(value)) if value else None


def _datetime_arg(value: object) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("intelligence cutoff must include timezone")
    return parsed


def _json(value: object) -> object:
    return json.loads(json.dumps(value, default=str, sort_keys=True))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_immutable_json(path: Path, payload: dict[str, Any]) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != rendered:
        raise FileExistsError(f"refusing to overwrite immutable intelligence artifact: {path}")
    path.write_text(rendered, encoding="utf-8")


def _write_latest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    temporary.replace(path)


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _int(value: object) -> int:
    return int(str(value)) if value is not None else 0


def _float(value: object) -> float:
    return float(str(value)) if value is not None else 0.0


def _records(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
