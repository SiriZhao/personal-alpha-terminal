# ruff: noqa: E501
"""ROUND67 data-evidence inventory, fail-closed gates, and replay contracts.

This module is deliberately an evidence layer.  It does not change the
production champion, factor definitions, portfolio constraints, or execution
policy.  It makes the existing lineage contracts inspectable in one
machine-readable inventory and gives research callers an explicit answer when
PIT, survivorship, OOS, or tradability evidence is missing.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from math import isfinite
from typing import cast

from personal_alpha_terminal.core.fingerprints import fingerprint


class EvidenceStatus(StrEnum):
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    BLOCKED_DATA_QUALITY = "BLOCKED_DATA_QUALITY"
    BLOCKED_PIT = "BLOCKED_PIT"
    BLOCKED_SURVIVORSHIP = "BLOCKED_SURVIVORSHIP"
    BLOCKED_OOS = "BLOCKED_OOS"
    BLOCKED_TRADABILITY = "BLOCKED_TRADABILITY"
    BLOCKED_WITH_EVIDENCE = "BLOCKED_WITH_EVIDENCE"


class BlockerDisposition(StrEnum):
    RESOLVED = "RESOLVED"
    PARTIALLY_RESOLVED = "PARTIALLY_RESOLVED"
    STILL_BLOCKED = "STILL_BLOCKED"
    NOT_RESOLVABLE_WITH_CURRENT_DATA = "NOT_RESOLVABLE_WITH_CURRENT_DATA"


@dataclass(frozen=True, slots=True)
class EvidenceSource:
    source_id: str
    implementation: str
    timestamp_contract: str
    current_capability: str
    reproducibility: str


@dataclass(frozen=True, slots=True)
class EvidenceField:
    field_id: str
    source: str
    timestamp_semantics: str
    observation_timestamp: str
    effective_timestamp: str
    knowable_at_decision: str
    pit_safety: str
    survivorship_risk: str
    lookahead_risk: str
    missing_data_semantics: str
    stale_data_semantics: str
    reproducibility: str
    status: EvidenceStatus
    production_dependency: str
    notes: str = ""


@dataclass(frozen=True, slots=True)
class DataEvidenceInventory:
    inventory_version: str
    generated_at: datetime
    decision_graph: tuple[str, ...]
    sources: tuple[EvidenceSource, ...]
    fields: tuple[EvidenceField, ...]

    def __post_init__(self) -> None:
        if self.generated_at.tzinfo is None:
            raise ValueError("inventory generated_at must be timezone-aware")
        if not self.inventory_version.strip() or not self.decision_graph:
            raise ValueError("inventory identity and decision graph are required")
        ids = [item.field_id for item in self.fields]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence field ids must be unique")

    @property
    def inventory_hash(self) -> str:
        return fingerprint(
            {
                "inventory_version": self.inventory_version,
                "decision_graph": self.decision_graph,
                "sources": self.sources,
                "fields": self.fields,
            }
        )

    def document(self) -> dict[str, object]:
        payload = asdict(self)
        payload["generated_at"] = self.generated_at.astimezone(UTC).isoformat()
        payload["inventory_hash"] = self.inventory_hash
        return cast(dict[str, object], json.loads(json.dumps(payload, default=str)))


@dataclass(frozen=True, slots=True)
class EvidenceGateResult:
    overall_status: EvidenceStatus
    field_statuses: tuple[tuple[str, EvidenceStatus], ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    diagnostic_mode_allowed: bool
    promotion_allowed: bool
    inventory_hash: str

    def document(self) -> dict[str, object]:
        return asdict(self) | {"overall_status": self.overall_status.value}


@dataclass(frozen=True, slots=True)
class LockedOOSManifest:
    protocol_version: str
    dataset_fingerprint: str
    model_config_hash: str
    feature_schema_hash: str
    train_start: date
    train_end: date
    evaluation_start: date
    evaluation_end: date
    embargo_sessions: int
    created_at: datetime
    evaluation_count: int = 0
    evaluation_id: str | None = None
    sealed: bool = False
    manifest_hash: str = ""

    def __post_init__(self) -> None:
        if self.train_end >= self.evaluation_start or self.evaluation_start > self.evaluation_end:
            raise ValueError("locked OOS windows overlap or are reversed")
        if self.embargo_sessions < 0 or self.evaluation_count < 0:
            raise ValueError("locked OOS counts must be non-negative")
        if any(
            not value.strip()
            for value in (
                self.protocol_version,
                self.dataset_fingerprint,
                self.model_config_hash,
                self.feature_schema_hash,
            )
        ):
            raise ValueError("locked OOS identity hashes are required")
        if self.created_at.tzinfo is None:
            raise ValueError("locked OOS created_at must be timezone-aware")
        if self.sealed and (self.evaluation_count != 1 or not self.evaluation_id):
            raise ValueError("sealed locked OOS must contain exactly one evaluation")
        expected = _manifest_hash(self)
        if self.manifest_hash and self.manifest_hash != expected:
            raise ValueError("locked OOS manifest hash is invalid")

    def document(self) -> dict[str, object]:
        payload = asdict(self)
        payload.update(
            {
                "train_start": self.train_start.isoformat(),
                "train_end": self.train_end.isoformat(),
                "evaluation_start": self.evaluation_start.isoformat(),
                "evaluation_end": self.evaluation_end.isoformat(),
                "created_at": self.created_at.astimezone(UTC).isoformat(),
            }
        )
        return payload


@dataclass(frozen=True, slots=True)
class TradabilityObservation:
    permanent_security_id: str
    symbol_at_decision: str
    symbol_at_execution: str
    decision_session: date
    decision_time: datetime
    information_available_at: datetime
    execution_session: date
    execution_time: datetime
    execution_open: float | None
    open_available_at: datetime | None
    open_tradable: bool
    halted: bool
    volume: float | None
    quote_observed_at: datetime | None
    benchmark_session: date | None
    symbol_transition_recorded: bool = False


@dataclass(frozen=True, slots=True)
class TradabilityResult:
    status: EvidenceStatus
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    checked: int


@dataclass(frozen=True, slots=True)
class SymbolVintage:
    permanent_security_id: str
    ticker: str
    valid_from: date
    valid_to: date | None
    available_at: datetime
    delisting_date: date | None = None


@dataclass(frozen=True, slots=True)
class MembershipVintage:
    permanent_security_id: str
    effective_from: date
    effective_to: date | None
    available_at: datetime


@dataclass(frozen=True, slots=True)
class BlockerAssessment:
    round_id: str
    blocker_id: str
    disposition: BlockerDisposition
    evidence: str


def default_inventory(*, generated_at: datetime | None = None) -> DataEvidenceInventory:
    """Return the inventory for the currently implemented production path."""

    timestamp = (generated_at or datetime(2026, 8, 18, 0, 0, tzinfo=UTC)).astimezone(UTC)
    sources = (
        EvidenceSource("prices_ohlcv", "models.Price + data.market_data.providers", "event_time <= available_time <= ingested_at", "daily raw OHLCV and provider adapters; historical PIT vintages incomplete", "content-addressed run bundles and source/provider lineage"),
        EvidenceSource("corporate_actions", "data.us_market.pit_total_return + research_dataset", "effective_date plus available_at/revision_id", "split/dividend schemas exist; complete historical PIT ledger unavailable", "immutable action ids and revision ids when supplied"),
        EvidenceSource("security_master", "models.Stock / security_master", "listing/delisting dates plus available_time", "current operational security master", "database snapshot and source/provider lineage"),
        EvidenceSource("universe_membership", "research_dataset.HistoricalUniverseMembership + broad_universe_service", "effective_from/to plus available_at", "current/broad snapshots; full historical membership unavailable", "manifest hashes when imported"),
        EvidenceSource("benchmark", "quant_engine.benchmark + Price", "same bar lineage as prices; benchmark session alignment", "SPY/QQQ operational benchmark evidence; bound PIT package incomplete", "benchmark ids and run-bundle inputs"),
        EvidenceSource("fundamentals_filings", "models.Financial + quant_engine.data.fundamental_data", "publication/available/ingested timestamps and revision_id", "schema supports PIT reads; historical vintage coverage incomplete", "revision/source/provider required"),
        EvidenceSource("news_events", "intelligence.market_news / macro_news", "published_at and available_at classify decision safety", "decision-safe rows are isolated; historical release-vintage completeness varies", "content/url hashes and append-only ledger"),
        EvidenceSource("market_calendar", "exchange_calendars + data.us_market.session", "session date, open/close, early-close flag", "US holidays and early closes are locally verifiable", "calendar id and session rows"),
        EvidenceSource("execution", "quant_engine.backtest.production + manual_execution_service", "signal/decision cutoff -> next verified session open", "manual-only execution; historical open tradability is not fully evidenced", "dataset/version and transaction audit lineage"),
        EvidenceSource("classification", "models.Stock.asset_type + provider capabilities", "security type effective in security master snapshot", "ETF/equity/index classification is explicit for current rows", "provider capability records and asset type constraints"),
        EvidenceSource("fallbacks", "research.data_gate + application/quant_daily_service", "gate evaluated at decision time", "missing/stale/unknown values fail closed or become diagnostic-only", "gate fingerprint and blocker list"),
    )
    fields = (
        _field("prices_ohlcv", "prices_ohlcv", "bar event/available/ingested", "trade_date close/open", "trade_date", "conditional: available_time <= decision cutoff", "partial PIT; raw bars safer than provider-adjusted", "high without historical universe", "same-bar close leakage if used before available", "invalid/missing rows rejected; empty panels remain diagnostic", "stale bars block decisions by age gate", "source/provider/data version and run bundle", EvidenceStatus.PASS_WITH_WARNINGS, "price/factor/label/backtest", "raw OHLCV exists, but historical revisions and coverage must be certified"),
        _field("corporate_actions", "corporate_actions", "effective plus announcement/available revision", "action effective date", "effective_date", "conditional on action available_at <= cutoff", "BLOCKED: complete PIT action vintages unavailable", "high around delistings/mergers", "applying revised action before availability", "missing action is not a neutral zero; it blocks total-return certification", "stale action vintages are not silently substituted", "action/revision ids support replay", EvidenceStatus.BLOCKED_PIT, "returns/labels/portfolio accounting", "splits and dividends are modeled, but certification is incomplete"),
        _field("splits", "corporate_actions", "available_at/revision_id", "effective_date", "effective_date", "only after available_at", "BLOCKED_PIT until historical ledger complete", "medium/high", "forward-adjusted close used before vintage availability", "missing split blocks affected security", "stale revision blocks PIT research", "immutable action identity", EvidenceStatus.BLOCKED_PIT, "total-return and holdings", "deterministic fixtures prove semantics only"),
        _field("dividends", "corporate_actions", "available_at/revision_id", "payment/effective date", "effective_date", "only after available_at", "BLOCKED_PIT until cash-dividend vintages complete", "medium/high", "future dividend inclusion", "missing dividend is unknown, not zero", "stale dividend revision blocks certification", "cash amount/currency/source ids", EvidenceStatus.BLOCKED_PIT, "total-return and benchmark", "cash dividends require explicit USD lineage"),
        _field("symbol_history", "security_master", "ticker validity plus available_time", "ticker observation", "valid_from/to", "conditional on vintage availability", "BLOCKED_SURVIVORSHIP: permanent historical mapping incomplete", "high", "current ticker mapped backward", "unknown symbol is quarantined", "stale mapping cannot resolve historical row", "permanent id and vintage dates", EvidenceStatus.BLOCKED_SURVIVORSHIP, "universe/price joins", "historical_pit.identifiers has the contract but not complete history"),
        _field("delistings", "security_master", "delisting_date plus available_time", "last observation/delisting", "delisting_date", "conditional on known-at-cutoff lifecycle", "BLOCKED_SURVIVORSHIP", "high", "dropping failed names from historical panel", "missing delisting is an explicit blocker", "stale lifecycle data isolates affected evaluation", "security manifest and delisting reason", EvidenceStatus.BLOCKED_SURVIVORSHIP, "universe/returns", "no fabricated delisted population"),
        _field("security_master", "security_master", "available_time snapshot", "security row", "listing/delisting/type validity", "current operational rows only", "PASS_WITH_WARNINGS", "high for historical research", "current active flag used historically", "unknown rows excluded with warning", "stale master blocks decisions if beyond freshness", "database and provider lineage", EvidenceStatus.PASS_WITH_WARNINGS, "all joins", "operationally usable, historically incomplete"),
        _field("universe_membership", "universe_membership", "available_at plus effective_from/to", "membership observation", "effective interval", "conditional on membership available_at", "BLOCKED_SURVIVORSHIP", "high", "current constituents used for all dates", "missing membership excludes certification", "stale snapshot is not historical truth", "membership source type and manifest hash", EvidenceStatus.BLOCKED_SURVIVORSHIP, "candidate universe", "current-directory membership is never promoted to historical proof"),
        _field("benchmark_prices", "benchmark", "same three-time bar contract", "benchmark trade date", "session date", "conditional on available_time", "BLOCKED_PIT for bound research package", "medium", "benchmark close from future session", "missing session causes mismatch blocker", "stale benchmark blocks comparison", "benchmark id, data version, calendar", EvidenceStatus.BLOCKED_PIT, "relative labels/metrics", "SPY/QQQ are operational references, not certified PIT history"),
        _field("fundamentals", "fundamentals_filings", "publication/available/ingested + revision", "fiscal period end", "available_at", "only if available_at <= decision", "BLOCKED_PIT for historical vintage coverage", "medium/high", "period end treated as release date", "unknown values remain missing; no imputation for certification", "stale filing blocks factor use", "revision/source/provider hashes", EvidenceStatus.BLOCKED_PIT, "fundamental factors", "schema supports value_as_of; current package is incomplete"),
        _field("filing_availability", "fundamentals_filings", "SEC acceptance/available timestamp", "filing acceptance", "available_at", "only after acceptance", "BLOCKED_PIT without complete SEC vintage package", "medium", "filing period end used as availability", "unmapped records remain pending", "late/unknown acceptance blocks feature", "CIK/accession/raw identity", EvidenceStatus.BLOCKED_PIT, "fundamental/event features", "ticker is display mapping only"),
        _field("factor_inputs", "prices_ohlcv + fundamentals_filings", "feature_available_at is max visible input", "feature as-of date", "decision cutoff", "yes only when every input is visible", "PASS_WITH_WARNINGS", "inherits source gaps", "future feature row or label overlap", "disabled features stay explicit", "stale input disables or blocks by gate", "feature schema and dataset hash", EvidenceStatus.PASS_WITH_WARNINGS, "alpha engines", "Alpha Engine 3 enforces visible prices and optional PIT fundamentals"),
        _field("news_events", "news_events", "published_at/retrieved_at/available_at", "published/event time", "available_at", "decision-safe only when available_at <= cutoff", "PASS_WITH_WARNINGS", "medium for historical event study", "retrieval time substituted for unknown release time", "unknown timestamp rows are display-only", "freshness is explicit; stale is context-only", "content/url hashes and append-only ledger", EvidenceStatus.PASS_WITH_WARNINGS, "context/shadow only", "LLM formal influence remains zero"),
        _field("market_calendar", "market_calendar", "session open/close and availability", "session date", "session boundaries", "calendar is known locally before run", "PASS", "low", "weekend/holiday treated as session", "missing session blocks execution", "calendar vintage/version required", "calendar id and session rows", EvidenceStatus.PASS, "all session alignment", "exchange_calendars verifies US holidays and early closes"),
        _field("trading_session_alignment", "market_calendar", "decision session to next legal session", "decision timestamp", "next execution session", "must be derived from verified calendar", "PASS_WITH_WARNINGS", "inherits lifecycle gaps", "same-bar fill or holiday skip", "missing next session blocks", "stale calendar blocks", "calendar id plus deterministic mapping", EvidenceStatus.PASS_WITH_WARNINGS, "backtest/execution", "production backtest has explicit next-session invariant"),
        _field("execution_price_availability", "execution", "open availability and open_tradable", "next-session open", "execution timestamp", "only after open is legally available", "BLOCKED_TRADABILITY for historical evidence gaps", "high around halts/delistings", "same-bar close/open fill", "missing open/zero volume/halt blocks", "stale quote blocks", "raw OHLC, price version, cost model", EvidenceStatus.BLOCKED_TRADABILITY, "backtest/manual ticket", "manual execution remains enabled; auto execution remains disabled"),
        _field("etf_security_classification", "classification", "security type snapshot availability", "security type observation", "asset type", "only as known at cutoff", "PASS_WITH_WARNINGS", "medium historically", "ETF/current type used for historical stock universe", "unknown type excluded", "stale classification quarantined", "asset_type/provider capability", EvidenceStatus.PASS_WITH_WARNINGS, "universe/benchmark", "classification is explicit but historical vintages are limited"),
        _field("missing_data_fallback", "fallbacks", "gate evaluation at decision time", "missing/anomaly observation", "gate status", "yes: unknown never becomes PASS", "PASS", "low", "silent default/imputation", "diagnostic/shadow fallback; critical evidence blocks promotion", "stale data warns or blocks by purpose", "gate fingerprint and blockers", EvidenceStatus.PASS, "all production gates", "safe diagnostic mode remains available"),
    )
    return DataEvidenceInventory(
        inventory_version="ROUND67-DATA-EVIDENCE-v1",
        generated_at=timestamp,
        decision_graph=(
            "market calendar/session -> data refresh and availability cutoff",
            "security master/permanent id -> symbol history and lifecycle",
            "universe membership -> eligible candidates (all eligible, no fixed Top-N)",
            "raw OHLCV + PIT corporate actions -> returns/labels/benchmark alignment",
            "fundamentals/filings/news -> timestamp-gated optional features/context",
            "factor inputs -> current Production Quant Champion / shadow challengers",
            "risk/cost/optimizer -> target weights and manual recommendations",
            "next legal execution price -> manual confirmation -> portfolio state update",
        ),
        sources=sources,
        fields=fields,
    )


def evaluate_data_evidence(inventory: DataEvidenceInventory | None = None) -> EvidenceGateResult:
    current = inventory or default_inventory()
    blockers: list[str] = []
    warnings: list[str] = []
    field_statuses: list[tuple[str, EvidenceStatus]] = []
    for field in current.fields:
        field_statuses.append((field.field_id, field.status))
        if field.status in {
            EvidenceStatus.BLOCKED_PIT,
            EvidenceStatus.BLOCKED_SURVIVORSHIP,
            EvidenceStatus.BLOCKED_OOS,
            EvidenceStatus.BLOCKED_TRADABILITY,
            EvidenceStatus.BLOCKED_WITH_EVIDENCE,
        }:
            blockers.append(f"{field.field_id}:{field.status.value}")
        elif field.status is EvidenceStatus.PASS_WITH_WARNINGS:
            warnings.append(f"{field.field_id}:PASS_WITH_WARNINGS")
    overall = EvidenceStatus.BLOCKED_DATA_QUALITY if blockers else (
        EvidenceStatus.PASS_WITH_WARNINGS if warnings else EvidenceStatus.PASS
    )
    return EvidenceGateResult(
        overall_status=overall,
        field_statuses=tuple(field_statuses),
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        diagnostic_mode_allowed=True,
        promotion_allowed=not blockers,
        inventory_hash=current.inventory_hash,
    )


def create_locked_oos_manifest(
    *,
    dataset_fingerprint: str,
    model_config_hash: str,
    feature_schema_hash: str,
    train_start: date,
    train_end: date,
    evaluation_start: date,
    evaluation_end: date,
    embargo_sessions: int = 1,
    created_at: datetime | None = None,
) -> LockedOOSManifest:
    base = LockedOOSManifest(
        protocol_version="ROUND67-LOCKED-OOS-v1",
        dataset_fingerprint=dataset_fingerprint,
        model_config_hash=model_config_hash,
        feature_schema_hash=feature_schema_hash,
        train_start=train_start,
        train_end=train_end,
        evaluation_start=evaluation_start,
        evaluation_end=evaluation_end,
        embargo_sessions=embargo_sessions,
        created_at=(created_at or datetime.now(UTC)).astimezone(UTC),
    )
    return replace(base, manifest_hash=_manifest_hash(base))


def seal_locked_oos_manifest(
    manifest: LockedOOSManifest,
    *,
    evaluation_id: str,
    dataset_fingerprint: str,
    post_hoc_tuning: bool = False,
) -> LockedOOSManifest:
    if manifest.sealed or manifest.evaluation_count != 0:
        raise ValueError("locked OOS evaluation is immutable and may run once")
    if dataset_fingerprint != manifest.dataset_fingerprint:
        raise ValueError("locked OOS dataset fingerprint mismatch")
    if post_hoc_tuning:
        raise ValueError("post-hoc tuning using locked OOS results is forbidden")
    if not evaluation_id.strip():
        raise ValueError("locked OOS evaluation_id is required")
    sealed = replace(
        manifest,
        evaluation_count=1,
        evaluation_id=evaluation_id,
        sealed=True,
        manifest_hash="",
    )
    return replace(sealed, manifest_hash=_manifest_hash(sealed))


def verify_locked_oos_manifest(manifest: LockedOOSManifest) -> tuple[str, ...]:
    blockers: list[str] = []
    if manifest.manifest_hash != _manifest_hash(manifest):
        blockers.append("LOCKED_OOS_MANIFEST_HASH_MISMATCH")
    if not manifest.sealed:
        blockers.append("LOCKED_OOS_NOT_EVALUATED_OR_SEALED")
    if manifest.evaluation_count != 1:
        blockers.append("LOCKED_OOS_EVALUATION_COUNT_NOT_ONE")
    return tuple(blockers)


def assess_locked_oos(manifest: LockedOOSManifest | None) -> EvidenceStatus:
    if manifest is None or verify_locked_oos_manifest(manifest):
        return EvidenceStatus.BLOCKED_OOS
    return EvidenceStatus.PASS


def evaluate_tradability(
    observations: Sequence[TradabilityObservation],
    *,
    verified_calendar: Sequence[date],
    stale_after: timedelta = timedelta(days=1),
) -> TradabilityResult:
    calendar = tuple(verified_calendar)
    blockers: list[str] = []
    warnings: list[str] = []
    if tuple(sorted(set(calendar))) != calendar:
        blockers.append("CALENDAR_NOT_SORTED_UNIQUE")
    index = {session: position for position, session in enumerate(calendar)}
    for row in observations:
        prefix = row.permanent_security_id or "UNKNOWN_SECURITY"
        if row.decision_time.tzinfo is None or row.information_available_at.tzinfo is None:
            blockers.append(f"{prefix}:NAIVE_DECISION_OR_INFORMATION_TIME")
            continue
        if row.information_available_at > row.decision_time:
            blockers.append(f"{prefix}:INFORMATION_AFTER_DECISION")
        expected_position = index.get(row.decision_session)
        if expected_position is None or expected_position + 1 >= len(calendar):
            blockers.append(f"{prefix}:NO_NEXT_VERIFIED_SESSION")
        elif row.execution_session != calendar[expected_position + 1]:
            blockers.append(f"{prefix}:EXECUTION_NOT_NEXT_SESSION")
        if row.execution_time.tzinfo is None:
            blockers.append(f"{prefix}:NAIVE_EXECUTION_TIME")
        if row.open_available_at is None or row.execution_open is None:
            blockers.append(f"{prefix}:MISSING_NEXT_OPEN")
        else:
            if row.open_available_at > row.execution_time:
                blockers.append(f"{prefix}:OPEN_NOT_AVAILABLE_AT_EXECUTION")
            if not isfinite(row.execution_open) or row.execution_open <= 0:
                blockers.append(f"{prefix}:INVALID_EXECUTION_OPEN")
        if not row.open_tradable:
            blockers.append(f"{prefix}:OPEN_NOT_TRADABLE")
        if row.halted:
            blockers.append(f"{prefix}:HALTED_INSTRUMENT")
        if row.volume is None or not isfinite(row.volume) or row.volume <= 0:
            blockers.append(f"{prefix}:ZERO_OR_INVALID_VOLUME")
        if row.quote_observed_at is None:
            blockers.append(f"{prefix}:STALE_QUOTE_TIMESTAMP_MISSING")
        elif row.quote_observed_at > row.execution_time:
            blockers.append(f"{prefix}:QUOTE_AFTER_EXECUTION")
        elif row.execution_time - row.quote_observed_at > stale_after:
            blockers.append(f"{prefix}:STALE_QUOTE")
        if row.symbol_at_decision != row.symbol_at_execution and not row.symbol_transition_recorded:
            blockers.append(f"{prefix}:UNRECORDED_SYMBOL_TRANSITION")
        if row.benchmark_session != row.execution_session:
            blockers.append(f"{prefix}:BENCHMARK_SESSION_MISMATCH")
        if row.execution_time <= row.decision_time:
            warnings.append(f"{prefix}:EXECUTION_TIME_NOT_AFTER_DECISION")
    unique_blockers = tuple(dict.fromkeys(blockers))
    unique_warnings = tuple(dict.fromkeys(warnings))
    return TradabilityResult(
        status=EvidenceStatus.BLOCKED_TRADABILITY if unique_blockers else (
            EvidenceStatus.PASS_WITH_WARNINGS if unique_warnings else EvidenceStatus.PASS
        ),
        blockers=unique_blockers,
        warnings=unique_warnings,
        checked=len(observations),
    )


def resolve_symbol_vintage(
    vintages: Sequence[SymbolVintage],
    *,
    permanent_security_id: str,
    session: date,
    decision_time: datetime,
) -> str | None:
    if decision_time.tzinfo is None:
        raise ValueError("decision_time must be timezone-aware")
    matches = tuple(
        item
        for item in vintages
        if item.permanent_security_id == permanent_security_id
        and item.available_at <= decision_time
        and item.valid_from <= session
        and (item.valid_to is None or session <= item.valid_to)
        and (item.delisting_date is None or session <= item.delisting_date)
    )
    if len(matches) > 1:
        raise ValueError("ambiguous overlapping symbol vintages")
    return matches[0].ticker if matches else None


def membership_active_as_of(
    membership: MembershipVintage,
    *,
    session: date,
    decision_time: datetime,
) -> bool:
    if decision_time.tzinfo is None or membership.available_at.tzinfo is None:
        raise ValueError("membership timestamps must be timezone-aware")
    return (
        membership.available_at <= decision_time
        and membership.effective_from <= session
        and (membership.effective_to is None or session <= membership.effective_to)
    )


def reassess_round_blockers(
    *,
    inventory: DataEvidenceInventory | None = None,
    locked_oos_manifest: LockedOOSManifest | None = None,
    historical_membership_coverage: float = 0.0,
    locked_oos_independent_sessions: int = 0,
    probability_forward_observations: int = 0,
    llm_forward_observations: int = 0,
) -> tuple[BlockerAssessment, ...]:
    current = inventory or default_inventory()
    data = evaluate_data_evidence(current)
    locked_status = assess_locked_oos(locked_oos_manifest)
    assessments: list[BlockerAssessment] = []
    alpha3_blockers = (
        "CERTIFIED_RESEARCH_MANIFEST_REQUIRED",
        "PIT_TOTAL_RETURN_HISTORY_INCOMPLETE",
        "HISTORICAL_MEMBERSHIP_INCOMPLETE",
        "LOCKED_OOS_NOT_FROZEN",
    )
    for blocker in alpha3_blockers:
        resolved = (
            blocker == "LOCKED_OOS_NOT_FROZEN" and locked_status is EvidenceStatus.PASS
        ) or (
            blocker == "HISTORICAL_MEMBERSHIP_INCOMPLETE"
            and historical_membership_coverage >= 1.0
        )
        assessments.append(
            BlockerAssessment(
                "ROUND62",
                blocker,
                BlockerDisposition.RESOLVED if resolved else BlockerDisposition.STILL_BLOCKED,
                "locked manifest verified" if resolved else "current inventory still lacks certifiable evidence",
            )
        )
    round65_blockers = (
        "CERTIFIED_PIT_DATASET_REQUIRED",
        "HISTORICAL_MEMBERSHIP_INCOMPLETE",
        "LOCKED_OOS_NOT_CERTIFIABLE",
        "LOCKED_OOS_SAMPLE_INSUFFICIENT",
        "PROBABILITY_FORWARD_EVIDENCE_INSUFFICIENT",
        "LLM_FORWARD_EVIDENCE_INSUFFICIENT",
        "ADAPTIVE_PARTICIPATION_OOS_NOT_VALIDATED",
    )
    for blocker in round65_blockers:
        if blocker == "HISTORICAL_MEMBERSHIP_INCOMPLETE":
            resolved = historical_membership_coverage >= 1.0
        elif blocker == "LOCKED_OOS_NOT_CERTIFIABLE":
            resolved = locked_status is EvidenceStatus.PASS
        elif blocker == "LOCKED_OOS_SAMPLE_INSUFFICIENT":
            resolved = locked_oos_independent_sessions >= 40
        elif blocker == "PROBABILITY_FORWARD_EVIDENCE_INSUFFICIENT":
            resolved = probability_forward_observations >= 40
        elif blocker == "LLM_FORWARD_EVIDENCE_INSUFFICIENT":
            resolved = llm_forward_observations >= 40
        else:
            resolved = False
        assessments.append(
            BlockerAssessment(
                "ROUND65",
                blocker,
                BlockerDisposition.RESOLVED if resolved else BlockerDisposition.STILL_BLOCKED,
                "threshold satisfied" if resolved else "not satisfied; promotion remains prohibited",
            )
        )
    if data.overall_status is EvidenceStatus.BLOCKED_DATA_QUALITY:
        assessments.append(
            BlockerAssessment(
                "ROUND67",
                "DATA_EVIDENCE_FOUNDATION",
                BlockerDisposition.NOT_RESOLVABLE_WITH_CURRENT_DATA,
                f"{len(data.blockers)} critical evidence gaps remain",
            )
        )
    return tuple(assessments)


def render_scorecard(
    *,
    inventory: DataEvidenceInventory | None = None,
    locked_oos_manifest: LockedOOSManifest | None = None,
    tradability: TradabilityResult | None = None,
) -> str:
    current = inventory or default_inventory()
    data = evaluate_data_evidence(current)
    by_id = dict(data.field_statuses)
    rows = (
        ("PIT integrity", _status_for(by_id, ("prices_ohlcv", "corporate_actions", "factor_inputs"))),
        ("survivorship integrity", _status_for(by_id, ("symbol_history", "delistings", "universe_membership"))),
        ("OOS integrity", assess_locked_oos(locked_oos_manifest)),
        ("price integrity", by_id["prices_ohlcv"]),
        ("benchmark integrity", by_id["benchmark_prices"]),
        ("fundamental timestamp integrity", by_id["fundamentals"]),
        ("news timestamp integrity", by_id["news_events"]),
        ("tradability integrity", tradability.status if tradability else by_id["execution_price_availability"]),
        ("corporate action integrity", by_id["corporate_actions"]),
        ("reproducibility", EvidenceStatus.PASS_WITH_WARNINGS),
    )
    lines = [
        f"ROUND67 DATA EVIDENCE | overall={data.overall_status.value} | inventory={current.inventory_hash[:16]}",
        "diagnostic_mode=ALLOWED | model_promotion=PROHIBITED" if not data.promotion_allowed else "diagnostic_mode=ALLOWED | model_promotion=ALLOWED",
    ]
    lines.extend(f"{label}: {status.value}" for label, status in rows)
    if data.blockers:
        lines.append(f"critical_blockers={len(data.blockers)}")
    return "\n".join(lines)


def _field(
    field_id: str,
    source: str,
    timestamp_semantics: str,
    observation_timestamp: str,
    effective_timestamp: str,
    knowable_at_decision: str,
    pit_safety: str,
    survivorship_risk: str,
    lookahead_risk: str,
    missing_data_semantics: str,
    stale_data_semantics: str,
    reproducibility: str,
    status: EvidenceStatus,
    production_dependency: str,
    notes: str,
) -> EvidenceField:
    return EvidenceField(
        field_id,
        source,
        timestamp_semantics,
        observation_timestamp,
        effective_timestamp,
        knowable_at_decision,
        pit_safety,
        survivorship_risk,
        lookahead_risk,
        missing_data_semantics,
        stale_data_semantics,
        reproducibility,
        status,
        production_dependency,
        notes,
    )


def _manifest_hash(manifest: LockedOOSManifest) -> str:
    payload = asdict(manifest)
    payload["manifest_hash"] = ""
    return fingerprint(payload)


def _status_for(statuses: dict[str, EvidenceStatus], field_ids: Iterable[str]) -> EvidenceStatus:
    selected = tuple(statuses[field_id] for field_id in field_ids)
    if any(item in {EvidenceStatus.BLOCKED_PIT, EvidenceStatus.BLOCKED_SURVIVORSHIP, EvidenceStatus.BLOCKED_TRADABILITY, EvidenceStatus.BLOCKED_OOS} for item in selected):
        return EvidenceStatus.BLOCKED_DATA_QUALITY
    return EvidenceStatus.PASS_WITH_WARNINGS if any(item is EvidenceStatus.PASS_WITH_WARNINGS for item in selected) else EvidenceStatus.PASS
