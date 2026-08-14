"""ROUND24 ETF universe evaluation (C1-C3, C7).

ETFs are evaluated against their own PIT-safe eligibility funnel.  Company
stock factors are never applied to ETFs; the catalog decides sleeve and
tradability.  Leveraged / inverse / volatility ETP / complex ETN instruments
are blocked by default (``BLOCKED_BY_COMPLEX_PRODUCT_POLICY``).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from hashlib import sha256

from personal_alpha_terminal.data.us_market.broad_universe import (
    CurrentDirectorySnapshot,
    CurrentSecurityMasterRecord,
    SecurityEligibilityObservation,
    SurvivorshipStatus,
)
from personal_alpha_terminal.instruments.catalog import EtfCatalog
from personal_alpha_terminal.instruments.master import (
    BenchmarkRole,
    InstrumentClassification,
    Sleeve,
    TradabilityTier,
    classify_instrument,
)


@dataclass(frozen=True, slots=True)
class EtfEligibilityRules:
    """ETF-specific eligibility gates.  Independent of equity rules."""

    minimum_price: float = 10.0
    minimum_trading_sessions: int = 252
    minimum_average_dollar_volume: float = 5_000_000.0
    minimum_median_dollar_volume: float = 5_000_000.0
    minimum_valid_bar_coverage: float = 0.98
    maximum_missing_ratio: float = 0.02
    allowed_exchanges: tuple[str, ...] = ("XNAS", "XNYS", "XASE", "ARCX", "BATS")
    minimum_operational_universe: int = 5
    coverage_collapse_ratio: float = 0.5

    def fingerprint(self) -> str:
        return _hash(asdict(self))


@dataclass(frozen=True, slots=True)
class EtfUniverseEligibility:
    universe_date: date
    decision_time: datetime
    raw_listed_etfs: int
    catalog_known: int
    unclassified_etfs: int
    core_eligible: tuple[InstrumentClassification, ...]
    tactical_eligible: tuple[InstrumentClassification, ...]
    tradable_eligible: tuple[InstrumentClassification, ...]
    research_only: tuple[InstrumentClassification, ...]
    blocked_complex: tuple[InstrumentClassification, ...]
    benchmark_roles: tuple[InstrumentClassification, ...]
    exclusions: dict[str, tuple[str, ...]]
    rules_fingerprint: str
    snapshot_hash: str
    survivorship_status: SurvivorshipStatus
    pit_status: str = "CURRENT_OPERATIONAL_PIT"

    def counts(self) -> dict[str, int]:
        return {
            "raw_listed_etfs": self.raw_listed_etfs,
            "catalog_known": self.catalog_known,
            "unclassified_etfs": self.unclassified_etfs,
            "core_eligible": len(self.core_eligible),
            "tactical_eligible": len(self.tactical_eligible),
            "tradable_eligible": len(self.tradable_eligible),
            "research_only": len(self.research_only),
            "blocked_complex": len(self.blocked_complex),
            "benchmark_roles": len(self.benchmark_roles),
        }

    def symbols_by_sleeve(self) -> dict[str, tuple[str, ...]]:
        return {
            "ETF_CORE": tuple(item.symbol for item in self.core_eligible),
            "ETF_TACTICAL": tuple(item.symbol for item in self.tactical_eligible),
            "RESEARCH_ONLY": tuple(item.symbol for item in self.research_only),
            "BLOCKED_COMPLEX": tuple(item.symbol for item in self.blocked_complex),
        }


def evaluate_etf_universe(
    snapshot: CurrentDirectorySnapshot,
    observations: tuple[SecurityEligibilityObservation, ...],
    catalog: EtfCatalog,
    *,
    supplementary_records: tuple[CurrentSecurityMasterRecord, ...] = (),
    universe_date: date,
    decision_time: datetime,
    rules: EtfEligibilityRules | None = None,
) -> EtfUniverseEligibility:
    """Evaluate the ETF sleeve universes with PIT-safe gates."""

    if decision_time.tzinfo is None:
        raise ValueError("etf universe decision_time must be timezone-aware")
    configured = rules or EtfEligibilityRules()
    catalog_by_symbol = catalog.by_symbol()
    directory_visible = tuple(
        item
        for item in snapshot.records
        if item.available_at <= decision_time
        and item.effective_date <= universe_date
        and item.active_from <= universe_date
        and (item.active_to is None or item.active_to >= universe_date)
        and item.is_etf
    )
    directory_symbols = {item.symbol for item in directory_visible}
    supplementary_visible = tuple(
        item
        for item in supplementary_records
        if item.symbol not in directory_symbols
        and item.available_at <= decision_time
        and item.effective_date <= universe_date
        and item.active_from <= universe_date
        and (item.active_to is None or item.active_to >= universe_date)
    )
    visible = directory_visible + supplementary_visible
    observed = {item.security_id: item for item in observations}
    core_eligible: list[InstrumentClassification] = []
    tactical_eligible: list[InstrumentClassification] = []
    tradable_eligible: list[InstrumentClassification] = []
    research_only: list[InstrumentClassification] = []
    blocked_complex: list[InstrumentClassification] = []
    benchmark_roles: list[InstrumentClassification] = []
    exclusions: dict[str, tuple[str, ...]] = {}
    unclassified = 0
    for security in visible:
        entry = catalog_by_symbol.get(security.symbol)
        classification = classify_instrument(
            security.symbol,
            directory_record=security,
            catalog_entry=entry,
            effective_date=security.effective_date,
        )
        if (
            classification.tradability_tier
            is TradabilityTier.BLOCKED_BY_COMPLEX_PRODUCT_POLICY
        ):
            blocked_complex.append(classification)
            exclusions[security.security_id] = ("BLOCKED_BY_COMPLEX_PRODUCT_POLICY",)
            continue
        if classification.tradability_tier is TradabilityTier.RESEARCH_ONLY:
            unclassified += 1
            research_only.append(classification)
            exclusions[security.security_id] = (
                classification.classification_reason or "RESEARCH_ONLY",
            )
            continue
        if classification.benchmark_role in {BenchmarkRole.BOTH, BenchmarkRole.BENCHMARK}:
            benchmark_roles.append(classification)
        reasons: list[str] = []
        if security.test_issue:
            reasons.append("TEST_ISSUE")
        if security.exchange not in configured.allowed_exchanges:
            reasons.append("UNSUPPORTED_EXCHANGE")
        observation = observed.get(security.security_id)
        if observation is None:
            reasons.append("PIT_PRICE_OBSERVATION_MISSING")
        elif observation.available_at > decision_time:
            reasons.append("FUTURE_DATA_NOT_ALLOWED")
        elif observation.as_of_date > universe_date:
            reasons.append("FUTURE_OBSERVATION_DATE_NOT_ALLOWED")
        elif observation.latest_price is None:
            reasons.append("PRICE_MISSING")
        elif observation.observed_sessions < configured.minimum_trading_sessions:
            reasons.append("INSUFFICIENT_TRADING_HISTORY")
        elif observation.latest_price < configured.minimum_price:
            reasons.append("PRICE_BELOW_THRESHOLD_OR_MISSING")
        elif observation.valid_bar_coverage < configured.minimum_valid_bar_coverage:
            reasons.append("VALID_BAR_COVERAGE_INSUFFICIENT")
        elif observation.missing_ratio > configured.maximum_missing_ratio:
            reasons.append("MISSING_DATA_RATIO_EXCESSIVE")
        elif (
            observation.average_dollar_volume is None
            or observation.average_dollar_volume < configured.minimum_average_dollar_volume
        ):
            reasons.append("ADV_BELOW_THRESHOLD_OR_MISSING")
        elif (
            observation.median_dollar_volume is None
            or observation.median_dollar_volume < configured.minimum_median_dollar_volume
        ):
            reasons.append("MEDIAN_DOLLAR_VOLUME_BELOW_THRESHOLD_OR_MISSING")
        if reasons:
            research_only.append(classification)
            exclusions[security.security_id] = tuple(reasons)
            continue
        tradable_eligible.append(classification)
        if classification.sleeve is Sleeve.ETF_CORE:
            core_eligible.append(classification)
        elif classification.sleeve is Sleeve.ETF_TACTICAL:
            tactical_eligible.append(classification)
    payload = {
        "universe_date": universe_date.isoformat(),
        "rules_fingerprint": configured.fingerprint(),
        "pit_status": "CURRENT_OPERATIONAL_PIT",
        "core_eligible": [item.document() for item in core_eligible],
        "tactical_eligible": [item.document() for item in tactical_eligible],
        "exclusions": exclusions,
    }
    return EtfUniverseEligibility(
        universe_date=universe_date,
        decision_time=decision_time,
        raw_listed_etfs=len(visible),
        catalog_known=sum(1 for item in visible if item.symbol in catalog_by_symbol),
        unclassified_etfs=unclassified,
        core_eligible=tuple(core_eligible),
        tactical_eligible=tuple(tactical_eligible),
        tradable_eligible=tuple(tradable_eligible),
        research_only=tuple(research_only),
        blocked_complex=tuple(blocked_complex),
        benchmark_roles=tuple(benchmark_roles),
        exclusions=exclusions,
        rules_fingerprint=configured.fingerprint(),
        snapshot_hash=_hash(payload),
        survivorship_status=snapshot.survivorship_status,
    )


def _hash(payload: object) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
