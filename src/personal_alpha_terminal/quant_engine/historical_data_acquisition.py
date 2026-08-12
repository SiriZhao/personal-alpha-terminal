"""Auditable acquisition planning for historical US equity research data.

This module never upgrades live/current data into historical research evidence.
It freezes the exact research object, records provider capabilities from dated
official documentation, and publishes a reproducible inventory of the real
layers currently available on the workstation.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import cast

from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
from personal_alpha_terminal.core.fingerprints import fingerprint
from personal_alpha_terminal.data.us_market.broad_universe import (
    CurrentDirectorySnapshot,
    EligibilityRules,
)
from personal_alpha_terminal.quant_engine.probability_overlay import OverlayApprovalPolicy
from personal_alpha_terminal.quant_engine.research_dataset import generate_xnys_sessions
from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
    USAdaptiveAlphaCoreV1,
)


class CapabilityStatus(StrEnum):
    YES = "YES"
    PARTIAL = "PARTIAL"
    NO = "NO"
    UNKNOWN = "UNKNOWN"
    REQUIRES_LICENSE = "REQUIRES_LICENSE"


class HistoricalResearchClassification(StrEnum):
    LIVE_ONLY = "LIVE_ONLY"
    RESEARCH_PARTIAL = "RESEARCH_PARTIAL"
    RESEARCH_CERTIFIED = "RESEARCH_CERTIFIED"
    NOT_CERTIFIABLE = "NOT_CERTIFIABLE"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class AcquisitionCheckpoint:
    """Deterministic progress record for chunked provider acquisition.

    Checkpoints contain no credentials and never certify their payload.  They
    only make an interrupted, rate-limited download resumable and idempotent.
    """

    provider_id: str
    dataset_id: str
    requested_chunks: tuple[str, ...]
    completed_chunks: tuple[tuple[str, str, int], ...] = ()

    @property
    def pending_chunks(self) -> tuple[str, ...]:
        completed = {chunk_id for chunk_id, _content_hash, _rows in self.completed_chunks}
        return tuple(item for item in self.requested_chunks if item not in completed)

    def complete(self, chunk_id: str, content_hash: str, row_count: int) -> AcquisitionCheckpoint:
        if chunk_id not in self.requested_chunks:
            raise ValueError(f"unrequested acquisition chunk: {chunk_id}")
        if row_count < 0:
            raise ValueError("row_count cannot be negative")
        existing = {
            item_id: (item_hash, rows)
            for item_id, item_hash, rows in self.completed_chunks
        }
        if chunk_id in existing:
            if existing[chunk_id] != (content_hash, row_count):
                raise ValueError(f"acquisition chunk changed after completion: {chunk_id}")
            return self
        completed = (*self.completed_chunks, (chunk_id, content_hash, row_count))
        return replace(self, completed_chunks=tuple(sorted(completed)))

    def document(self) -> dict[str, object]:
        payload = cast(dict[str, object], json.loads(json.dumps(asdict(self))))
        payload["checkpoint_hash"] = fingerprint(payload)
        return payload


@dataclass(frozen=True, slots=True)
class ProviderCapabilityEvidence:
    provider_id: str
    access_tier: str
    raw_ohlcv: CapabilityStatus
    delisted_securities: CapabilityStatus
    permanent_identifiers: CapabilityStatus
    ticker_history: CapabilityStatus
    listing_lifecycle: CapabilityStatus
    historical_membership: CapabilityStatus
    corporate_actions: CapabilityStatus
    delisting_return: CapabilityStatus
    pit_vintages: CapabilityStatus
    total_return: CapabilityStatus
    pit_fundamentals: CapabilityStatus
    exchange_calendar: CapabilityStatus
    history_depth: str
    rate_limits: str
    local_cache_rights: str
    pricing: str
    personal_use_terms: str
    certification_grade: str
    official_evidence: tuple[str, ...]
    audited_on: date = date(2026, 8, 12)

    def document(self) -> dict[str, object]:
        return cast(dict[str, object], json.loads(json.dumps(asdict(self), default=str)))


def provider_capability_matrix() -> tuple[ProviderCapabilityEvidence, ...]:
    """Return conservative, official-source-backed provider capability claims.

    ``UNKNOWN`` is deliberate whenever the public product page does not prove a
    field or license right. The matrix is evidence for provider selection, not a
    substitute for validating an acquired package.
    """

    return (
        ProviderCapabilityEvidence(
            "nasdaq_trader_symbol_directory",
            "FREE_CURRENT_DIRECTORY",
            CapabilityStatus.NO,
            CapabilityStatus.NO,
            CapabilityStatus.NO,
            CapabilityStatus.NO,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.NO,
            CapabilityStatus.NO,
            CapabilityStatus.NO,
            CapabilityStatus.NO,
            CapabilityStatus.NO,
            CapabilityStatus.NO,
            CapabilityStatus.NO,
            "current listing files only",
            "daily files; no documented historical API",
            "current cache used only as LIVE_DAILY_DATA",
            "free",
            "official current directory; historical reuse not claimed",
            "LIVE_ONLY",
            (
                "https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs",
                "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
                "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
            ),
        ),
        ProviderCapabilityEvidence(
            "alpha_vantage",
            "FREE_KEY_OR_PREMIUM",
            CapabilityStatus.YES,
            CapabilityStatus.YES,
            CapabilityStatus.NO,
            CapabilityStatus.UNKNOWN,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.YES,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.NO,
            CapabilityStatus.NO,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.UNKNOWN,
            CapabilityStatus.PARTIAL,
            "listing status since 2010-01-01; prices advertised 20+ years",
            "free standard limit 25 requests/day; premium removes daily limit",
            "UNKNOWN - terms require case-specific review",
            "free key; premium price selected on official checkout",
            "terms apply; no redistribution claim made by this project",
            "RESEARCH_PARTIAL",
            (
                "https://www.alphavantage.co/documentation/",
                "https://www.alphavantage.co/premium/",
                "https://www.alphavantage.co/terms_of_service/",
            ),
        ),
        ProviderCapabilityEvidence(
            "twelve_data",
            "FREE_KEY_OR_PAID",
            CapabilityStatus.YES,
            CapabilityStatus.UNKNOWN,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.UNKNOWN,
            CapabilityStatus.UNKNOWN,
            CapabilityStatus.NO,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.NO,
            CapabilityStatus.NO,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.UNKNOWN,
            CapabilityStatus.PARTIAL,
            "full history advertised for supported EOD instruments",
            "Basic 8 credits/min and 800/day; paid tiers increase credits",
            "personal non-commercial use; persistent cache right not proven",
            "Basic free; paid individual tiers shown on official pricing",
            "personal plans restricted to individual non-commercial use",
            "RESEARCH_PARTIAL",
            (
                "https://twelvedata.com/pricing",
                "https://support.twelvedata.com/en/articles/12682324-end-of-day-eod-pricing-market-data",
                "https://twelvedata.com/docs/advanced",
            ),
        ),
        ProviderCapabilityEvidence(
            "tiingo",
            "FREE_OR_INDIVIDUAL_SUBSCRIPTION",
            CapabilityStatus.YES,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.NO,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.NO,
            CapabilityStatus.NO,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.NO,
            "per-symbol start/end; depth varies",
            "plan-specific monthly bandwidth",
            "internal/personal use allowed; redistribution prohibited",
            "$30/month or $300/year for individuals",
            "internal personal use only; no redistribution",
            "RESEARCH_PARTIAL",
            (
                "https://www.tiingo.com/documentation/end-of-day",
                "https://www.tiingo.com/documentation/appendix/symbology",
                "https://www.tiingo.com/documentation/general",
                "https://www.tiingo.com/about/pricing",
            ),
        ),
        ProviderCapabilityEvidence(
            "eodhd",
            "FREE_TRIAL_OR_PAID",
            CapabilityStatus.YES,
            CapabilityStatus.YES,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.UNKNOWN,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.NO,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.NO,
            CapabilityStatus.NO,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.PARTIAL,
            "US history varies by symbol; provider advertises multi-decade coverage",
            "plan-specific calls/day and calls/minute",
            "UNKNOWN - confirm storage terms before acquisition",
            "EOD Historical Data All World $19.99/month or $199/year",
            "personal plan offered; raw storage terms need confirmation",
            "RESEARCH_PARTIAL",
            (
                "https://eodhd.com/financial-apis/delisted-stock-companies-data-2",
                "https://eodhd.com/pricing",
                "https://eodhd.com/financial-apis/calendar-upcoming-earnings-ipos-and-splits",
            ),
        ),
        ProviderCapabilityEvidence(
            "massive",
            "INDIVIDUAL_PLAN_PLUS_REQUIRED_DATA_LICENSE",
            CapabilityStatus.YES,
            CapabilityStatus.YES,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.YES,
            CapabilityStatus.YES,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.NO,
            CapabilityStatus.NO,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.UNKNOWN,
            CapabilityStatus.NO,
            "ticker history from 2003-09-10; price depth 2/5/10/20+ years by plan",
            "5 calls/min free; paid individual plans advertise unlimited API calls",
            "termination requires deletion; non-display strategy use needs license",
            "$0/$29/$79/$199 per month for Basic/Starter/Developer/Advanced",
            "personal display right alone does not authorize non-display strategy use",
            "REQUIRES_LICENSE",
            (
                "https://massive.com/docs/rest/stocks/tickers/all-tickers",
                "https://massive.com/docs/flat-files/stocks/overview",
                "https://massive.com/stocks",
                "https://massive.com/legal/market-data-terms-of-service",
            ),
        ),
        ProviderCapabilityEvidence(
            "norgate_data",
            "PLATINUM_OR_DIAMOND_SUBSCRIPTION",
            CapabilityStatus.YES,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.UNKNOWN,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.YES,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.UNKNOWN,
            CapabilityStatus.NO,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.NO,
            CapabilityStatus.PARTIAL,
            "Platinum daily history from 1990; Diamond from 1950",
            "local updater/database; no request-rate API model",
            "Windows proprietary local DB; price export supported; access ends on lapse",
            "US Platinum $346.50/6 months or $630/12 months",
            "subscription EULA; trial required to validate adapter fields",
            "CONDITIONAL_PROFESSIONAL",
            (
                "https://norgatedata.com/prices.php",
                "https://norgatedata.com/data-content-tables.php",
                "https://norgatedata.com/index.php/pricing/",
                "https://norgatedata.com/subscribe/eula.php",
            ),
        ),
        ProviderCapabilityEvidence(
            "nasdaq_data_link_sharadar",
            "PREMIUM_INSTITUTIONAL",
            CapabilityStatus.PARTIAL,
            CapabilityStatus.UNKNOWN,
            CapabilityStatus.UNKNOWN,
            CapabilityStatus.UNKNOWN,
            CapabilityStatus.UNKNOWN,
            CapabilityStatus.UNKNOWN,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.UNKNOWN,
            CapabilityStatus.NO,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.YES,
            CapabilityStatus.NO,
            "product-specific; requires subscribed documentation",
            "Tables API and bulk download limits are product-specific",
            "REQUIRES_LICENSE",
            "price visible only after login/subscription; contact Nasdaq sales",
            "institutional product license",
            "REQUIRES_LICENSE_DUE_DILIGENCE",
            (
                "https://data.nasdaq.com/publishers/SHARADAR",
                "https://docs.data.nasdaq.com/docs/data-organization",
                "https://data.nasdaq.com/databases/SF1/documentation",
            ),
        ),
        ProviderCapabilityEvidence(
            "crsp_us_stock",
            "LICENSED_RESEARCH_DATABASE",
            CapabilityStatus.YES,
            CapabilityStatus.YES,
            CapabilityStatus.YES,
            CapabilityStatus.YES,
            CapabilityStatus.YES,
            CapabilityStatus.YES,
            CapabilityStatus.YES,
            CapabilityStatus.YES,
            CapabilityStatus.PARTIAL,
            CapabilityStatus.YES,
            CapabilityStatus.NO,
            CapabilityStatus.PARTIAL,
            "daily US stock history from 1925",
            "licensed file/platform delivery; no retail request-rate API",
            "licensed flat files/platforms; contractual terms apply",
            "request subscription quote",
            "institution/investment-practitioner license",
            "PROFESSIONAL_REFERENCE_STANDARD",
            (
                "https://indexes.morningstar.com/research-data-products/crsp-us-stock-databases",
                "https://indexes.morningstar.com/research-data-products",
                "https://www.crsp.org/wp-content/uploads/guides/CRSP_US_Stock_%26_Indexes_Database_Data_Descriptions_Guide.pdf",
            ),
        ),
    )


@dataclass(frozen=True, slots=True)
class HistoricalResearchRequirements:
    factor_warmup_sessions: int
    train_sessions: int
    validation_sessions: int
    embargo_sessions: int
    locked_oos_sessions: int
    minimum_total_sessions: int
    computed_minimum_start: date
    configured_target_start: date
    required_end: date


@dataclass(frozen=True, slots=True)
class ResearchBaseline:
    research_baseline_id: str
    universe_policy_version: str
    universe_policy_hash: str
    strategy_candidate_version: str
    strategy_parameter_hash: str
    probability_model_version: str
    probability_model_hash: str
    probability_role: str
    runtime_config_hash: str
    canonical_config_hash: str
    cost_model_hash: str
    risk_model_hash: str
    portfolio_constraint_hash: str
    git_head: str
    created_at: datetime
    requirements: HistoricalResearchRequirements

    def document(self) -> dict[str, object]:
        payload = cast(dict[str, object], json.loads(json.dumps(asdict(self), default=str)))
        payload["artifact_hash"] = fingerprint(payload)
        return payload


def build_research_baseline(
    config: EffectiveRuntimeConfig,
    *,
    git_head: str,
    git_commit_time: datetime,
    required_end: date,
) -> ResearchBaseline:
    if git_commit_time.tzinfo is None:
        raise ValueError("git commit time must be timezone-aware")
    universe_rules = EligibilityRules(**asdict(config.broad_universe))
    policy_material = {
        "market": "US",
        "allowed_exchanges": universe_rules.allowed_exchanges,
        "allowed_security_type": "COMMON_STOCK",
        "adr": universe_rules.include_adr,
        "reit": universe_rules.include_reit,
        "excluded": (
            "ETF", "ETN", "PREFERRED", "WARRANT", "RIGHT", "UNIT",
            "CLOSED_END_FUND", "OTC", "TEST_ISSUE", "ABNORMAL_FINANCIAL_STATUS",
        ),
        "filters": asdict(universe_rules),
        "liquidity_cutoff": "STRICTLY_BEFORE_UNIVERSE_DATE",
        "membership_cutoff": "AVAILABLE_AT_LE_DECISION_TIME",
        "rebalance_frequency": "DAILY_ELIGIBILITY_MEDIUM_TERM_SIGNAL",
    }
    universe_hash = fingerprint(policy_material)
    probability_material = {
        "model": "BENCHMARK_RELATIVE_CONDITIONAL_RESIDUAL",
        "mechanism": "OOS_NET_RESIDUAL_SHRINKAGE",
        "approval_policy": asdict(OverlayApprovalPolicy()),
        "role_without_approval": "SUPPORTING_OVERLAY_BASE_FALLBACK",
    }
    probability_hash = fingerprint(probability_material)
    requirements = calculate_historical_requirements(
        required_end,
        configured_start=date.fromisoformat(config.history_start),
        factor_warmup_sessions=max(
            config.strategy.momentum_lookback,
            config.strategy.trend_window,
            config.strategy.volatility_window,
            config.broad_universe.minimum_trading_sessions,
        ),
        embargo_sessions=config.strategy.horizon_sessions,
    )
    identity = {
        "universe_policy_hash": universe_hash,
        "strategy_candidate_version": (
            f"{USAdaptiveAlphaCoreV1.model_id}:{USAdaptiveAlphaCoreV1.version}"
        ),
        "strategy_parameter_hash": config.strategy_parameter_hash,
        "probability_model_hash": probability_hash,
        "runtime_config_hash": config.runtime_config_hash,
        "cost_model_hash": config.cost_model_hash,
        "risk_model_hash": config.risk_model_hash,
        "portfolio_constraint_hash": config.portfolio_constraint_hash,
        "git_head": git_head,
        "required_end": required_end.isoformat(),
    }
    baseline_hash = fingerprint(identity)
    return ResearchBaseline(
        research_baseline_id=f"historical-research-baseline-{baseline_hash[:20]}",
        universe_policy_version=f"broad-us-equity-v1-{universe_hash[:12]}",
        universe_policy_hash=universe_hash,
        strategy_candidate_version=(
            f"{USAdaptiveAlphaCoreV1.model_id}:{USAdaptiveAlphaCoreV1.version}:"
            f"{config.strategy_parameter_hash[:12]}"
        ),
        strategy_parameter_hash=config.strategy_parameter_hash,
        probability_model_version=f"probability-residual-overlay-v1-{probability_hash[:12]}",
        probability_model_hash=probability_hash,
        probability_role="SUPPORTING_OVERLAY_UNLESS_EXACT_PRODUCTION_APPROVAL",
        runtime_config_hash=config.runtime_config_hash,
        canonical_config_hash=config.canonical_run_config_hash,
        cost_model_hash=config.cost_model_hash,
        risk_model_hash=config.risk_model_hash,
        portfolio_constraint_hash=config.portfolio_constraint_hash,
        git_head=git_head,
        created_at=git_commit_time.astimezone(UTC),
        requirements=requirements,
    )


def calculate_historical_requirements(
    required_end: date,
    *,
    configured_start: date,
    factor_warmup_sessions: int = 252,
    train_sessions: int = 1008,
    validation_sessions: int = 504,
    embargo_sessions: int = 21,
    locked_oos_sessions: int = 252,
) -> HistoricalResearchRequirements:
    total = (
        factor_warmup_sessions
        + train_sessions
        + validation_sessions
        + embargo_sessions
        + locked_oos_sessions
    )
    reference = generate_xnys_sessions(
        date(1990, 1, 1), required_end, available_at=datetime(1990, 1, 1, tzinfo=UTC)
    )
    if len(reference) < total:
        raise ValueError("exchange calendar cannot satisfy historical session requirement")
    computed = reference[-total].session_date
    return HistoricalResearchRequirements(
        factor_warmup_sessions,
        train_sessions,
        validation_sessions,
        embargo_sessions,
        locked_oos_sessions,
        total,
        computed,
        min(configured_start, computed),
        required_end,
    )


@dataclass(frozen=True, slots=True)
class HistoricalAcquisitionManifest:
    acquisition_id: str
    research_baseline_id: str
    classification: HistoricalResearchClassification
    observed_at: datetime
    actual_price_start: date | None
    actual_price_end: date | None
    live_security_count: int
    live_price_rows: int
    current_directory_securities: int
    current_directory_common_equities: int
    historical_security_count: int
    historical_membership_rows: int
    membership_sessions_covered: int
    membership_coverage_pct: float
    delisted_count: int
    unknown_lifecycle_count: int
    corporate_action_rows: int
    pit_total_return_rows: int
    calendar_start: date
    calendar_end: date
    calendar_sessions: int
    calendar_early_closes: int
    benchmark_rows: dict[str, int]
    layer_content_hashes: dict[str, str | None]
    research_dataset_content_hash: str | None
    inventory_hash: str
    manifest_hash: str
    blockers: tuple[str, ...]
    oos_lock_status: str
    production_eligible: bool = False

    def document(self) -> dict[str, object]:
        return cast(dict[str, object], json.loads(json.dumps(asdict(self), default=str)))


def audit_available_historical_layers(
    *,
    database: Path,
    directory: CurrentDirectorySnapshot,
    baseline: ResearchBaseline,
) -> HistoricalAcquisitionManifest:
    """Hash real local layers while preserving their non-research classifications."""

    uri = f"file:{database.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        price_start_raw, price_end_raw, price_rows = connection.execute(
            "SELECT min(trade_date), max(trade_date), count(*) FROM prices"
        ).fetchone()
        live_security_count = _count(connection, "security_master")
        corporate_action_rows = _count(connection, "corporate_actions")
        pit_rows = _count(connection, "pit_total_return_versions")
        benchmark_documents = _benchmark_rows(connection, ("SPY", "QQQ"))
        latest_source_time = connection.execute(
            "SELECT max(coalesce(available_time, ingested_at)) FROM prices"
        ).fetchone()[0]
    actual_start = date.fromisoformat(str(price_start_raw)) if price_start_raw else None
    actual_end = date.fromisoformat(str(price_end_raw)) if price_end_raw else None
    calendar = generate_xnys_sessions(
        baseline.requirements.configured_target_start,
        baseline.requirements.required_end,
        available_at=baseline.created_at,
    )
    calendar_hash = fingerprint(tuple(asdict(item) for item in calendar))
    benchmark_hash = fingerprint(benchmark_documents) if benchmark_documents else None
    benchmark_counts = {
        symbol: sum(1 for row in benchmark_documents if row["symbol"] == symbol)
        for symbol in ("SPY", "QQQ")
    }
    current_common = sum(1 for item in directory.records if item.is_common_stock)
    blockers = (
        "HISTORICAL_MEMBERSHIP_INCOMPLETE",
        "CURRENT_CONSTITUENT_HISTORY_NOT_ALLOWED",
        "DELISTING_HISTORY_INCOMPLETE",
        "SECURITY_IDENTIFIER_HISTORY_INCOMPLETE",
        "DELISTING_RETURN_UNAVAILABLE",
        "CORPORATE_ACTION_PIT_HISTORY_INCOMPLETE",
        "PIT_TOTAL_RETURN_HISTORY_INCOMPLETE",
        "REQUIRED_PERIOD_COVERAGE_INCOMPLETE",
        "BENCHMARK_PIT_TOTAL_RETURN_CONVENTION_INCOMPLETE",
    )
    layers: dict[str, str | None] = {
        "provider_capability_matrix": fingerprint(
            tuple(item.document() for item in provider_capability_matrix())
        ),
        "current_directory_live_only": directory.content_hash,
        "live_prices_inventory_only": fingerprint(
            {
                "row_count": int(price_rows),
                "date_start": actual_start,
                "date_end": actual_end,
                "latest_available_time": latest_source_time,
            }
        ),
        "historical_security_master": None,
        "historical_membership": None,
        "delisting_lifecycle": None,
        "pit_corporate_actions": None,
        "pit_total_return": None,
        "xnys_calendar": calendar_hash,
        "benchmark_raw_live_only": benchmark_hash,
    }
    inventory = {
        "research_baseline_id": baseline.research_baseline_id,
        "actual_start": actual_start,
        "actual_end": actual_end,
        "live_security_count": live_security_count,
        "live_price_rows": int(price_rows),
        "current_directory_securities": len(directory.records),
        "current_directory_common_equities": current_common,
        "calendar_sessions": len(calendar),
        "benchmark_rows": benchmark_counts,
        "layer_hashes": layers,
        "blockers": blockers,
    }
    inventory_hash = fingerprint(inventory)
    manifest_material = {
        **inventory,
        "classification": HistoricalResearchClassification.NOT_CERTIFIABLE,
        "inventory_hash": inventory_hash,
        "research_dataset_content_hash": None,
    }
    manifest_hash = fingerprint(manifest_material)
    observed = _parse_database_datetime(latest_source_time) or directory.retrieved_at
    return HistoricalAcquisitionManifest(
        acquisition_id=f"historical-acquisition-{manifest_hash[:20]}",
        research_baseline_id=baseline.research_baseline_id,
        classification=HistoricalResearchClassification.NOT_CERTIFIABLE,
        observed_at=max(observed, directory.retrieved_at),
        actual_price_start=actual_start,
        actual_price_end=actual_end,
        live_security_count=live_security_count,
        live_price_rows=int(price_rows),
        current_directory_securities=len(directory.records),
        current_directory_common_equities=current_common,
        historical_security_count=0,
        historical_membership_rows=0,
        membership_sessions_covered=0,
        membership_coverage_pct=0.0,
        delisted_count=0,
        unknown_lifecycle_count=len(directory.records),
        corporate_action_rows=corporate_action_rows,
        pit_total_return_rows=pit_rows,
        calendar_start=calendar[0].session_date,
        calendar_end=calendar[-1].session_date,
        calendar_sessions=len(calendar),
        calendar_early_closes=sum(item.is_early_close for item in calendar),
        benchmark_rows=benchmark_counts,
        layer_content_hashes=layers,
        research_dataset_content_hash=None,
        inventory_hash=inventory_hash,
        manifest_hash=manifest_hash,
        blockers=blockers,
        oos_lock_status="NOT_CREATED_RESEARCH_DATA_NOT_CERTIFIED",
    )


def persist_acquisition_evidence(
    baseline: ResearchBaseline,
    acquisition: HistoricalAcquisitionManifest,
    root: Path,
) -> tuple[Path, Path]:
    """Atomically publish immutable evidence plus a replaceable latest pointer."""

    baseline_dir = root / "baselines" / baseline.research_baseline_id
    acquisition_dir = root / "acquisitions" / acquisition.acquisition_id
    baseline_path = baseline_dir / "baseline.json"
    acquisition_path = acquisition_dir / "manifest.json"
    _write_immutable_json(baseline_path, baseline.document())
    _write_immutable_json(acquisition_path, acquisition.document())
    latest = root / "latest-acquisition.json"
    pointer: dict[str, object] = {
        "acquisition_id": acquisition.acquisition_id,
        "manifest_path": acquisition_path.resolve().as_posix(),
        "manifest_hash": acquisition.manifest_hash,
        "classification": acquisition.classification,
    }
    _write_atomic_json(latest, pointer)
    return baseline_path, acquisition_path


def persist_acquisition_checkpoint(
    checkpoint: AcquisitionCheckpoint, path: Path
) -> None:
    """Atomically persist resumable progress without publishing a dataset."""

    _write_atomic_json(path, checkpoint.document())


def read_acquisition_checkpoint(path: Path) -> AcquisitionCheckpoint:
    document = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
    expected_hash = document.pop("checkpoint_hash", None)
    if expected_hash != fingerprint(document):
        raise ValueError("acquisition checkpoint hash mismatch")
    return AcquisitionCheckpoint(
        provider_id=str(document["provider_id"]),
        dataset_id=str(document["dataset_id"]),
        requested_chunks=tuple(
            str(item) for item in cast(list[object], document["requested_chunks"])
        ),
        completed_chunks=tuple(
            (str(item[0]), str(item[1]), int(str(item[2])))
            for item in cast(list[list[object]], document["completed_chunks"])
        ),
    )


def _benchmark_rows(
    connection: sqlite3.Connection, symbols: tuple[str, ...]
) -> tuple[dict[str, object], ...]:
    placeholders = ",".join("?" for _ in symbols)
    rows = connection.execute(
        f"SELECT s.canonical_code, s.symbol, p.trade_date, p.open, p.high, p.low, "
        f"p.close, p.volume, p.source, p.provider, p.available_time, p.price_type "
        f"FROM prices p JOIN security_master s ON s.id=p.stock_id "
        f"WHERE s.symbol IN ({placeholders}) ORDER BY s.symbol, p.trade_date, p.source",
        symbols,
    ).fetchall()
    keys = (
        "security_id", "symbol", "trade_date", "open", "high", "low", "close",
        "volume", "source", "provider", "available_time", "price_type",
    )
    return tuple(dict(zip(keys, row, strict=True)) for row in rows)


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def _parse_database_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _write_immutable_json(path: Path, document: dict[str, object]) -> None:
    rendered = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != rendered:
            raise FileExistsError(f"immutable acquisition evidence differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(path)


def _write_atomic_json(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
