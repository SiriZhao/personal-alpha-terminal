from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personal_alpha_terminal.application.broad_universe_service import (
    BroadUSUniverseService,
)
from personal_alpha_terminal.application.operational_readiness import (
    OperationalApprovalIdentity,
    OperationalPolicy,
    OperationalPolicyDecision,
    OperationalPolicyStore,
    resolve_current_operational_identity,
)
from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
from personal_alpha_terminal.data.us_market.broad_universe import (
    BroadUniverseEligibility,
    EligibilityRules,
)
from personal_alpha_terminal.data.us_market.repository import USPointInTimeRepository
from personal_alpha_terminal.models import Portfolio, PortfolioPosition, Price, SecurityMaster
from personal_alpha_terminal.quant_engine.alpha import AlphaSignal
from personal_alpha_terminal.quant_engine.benchmark import (
    BenchmarkEvidence,
    benchmark_evidence_from_returns,
)
from personal_alpha_terminal.quant_engine.candidates import compress_candidates
from personal_alpha_terminal.quant_engine.model_registry import ModelRegistryService
from personal_alpha_terminal.quant_engine.operational_baseline import (
    OperationalBaselineRecord,
    append_record,
    detect_collapse,
    load_baseline,
)
from personal_alpha_terminal.quant_engine.probability_assessment import (
    ProbabilityAssessmentRegistry,
)
from personal_alpha_terminal.quant_engine.probability_overlay import (
    ConditionalProbabilityEvidence,
    ProbabilityOverlayEffect,
    ProbabilityOverlayIdentity,
    ProbabilityOverlayRegistry,
    apply_probability_overlay,
)
from personal_alpha_terminal.quant_engine.production_pipeline import DailyQuantInput
from personal_alpha_terminal.quant_engine.risk.budget import (
    CorrelationRiskStatus,
    PortfolioRiskState,
    RegimeRiskInput,
)
from personal_alpha_terminal.quant_engine.risk.model import AssetRiskMetadata
from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
    StrategyFactorSnapshot,
    USAdaptiveAlphaCoreV1,
)
from personal_alpha_terminal.quant_engine.validation_artifacts import (
    ProbabilityCalibrationIdentity,
    ValidationArtifactRegistry,
)
from personal_alpha_terminal.research.data_gate import (
    ResearchDataAuthorization,
    ResearchDataRequest,
    ResearchPurpose,
)
from personal_alpha_terminal.research.service import ResearchDataGateService


@dataclass(frozen=True, slots=True)
class PortfolioInputPosition:
    symbol: str
    quantity: float
    reference_price: float
    current_weight: float


@dataclass(frozen=True, slots=True)
class AssembledDailyInput:
    inputs: DailyQuantInput
    classical_alpha_signals: tuple[AlphaSignal, ...]
    disabled_components: tuple[str, ...]
    parameter_fingerprint: str
    factors: tuple[StrategyFactorSnapshot, ...]
    universe_count: int
    data_cutoff: datetime
    source_ids: tuple[str, ...]
    benchmark_symbol: str
    benchmark_observations: int
    benchmark_period_return: float | None
    benchmark_annualized_volatility: float | None
    portfolio_positions: tuple[PortfolioInputPosition, ...]
    cash_balance: float
    benchmark_evidences: tuple[BenchmarkEvidence, ...] = ()
    data_version: str = 'UNAVAILABLE'
    universe_snapshot_id: str = 'UNAVAILABLE'
    strategy_version: str = 'UNAVAILABLE'
    model_approval_hash: str = 'NOT_APPROVED'
    model_approval_data_version: str = 'NOT_APPROVED'
    probability_artifact_id: str = 'OPTIONAL_UNAVAILABLE'
    alpha_symbols: tuple[str, ...] = ()
    candidate_symbols: tuple[str, ...] = ()
    universe_evidence: dict[str, object] = field(default_factory=dict)
    probability_overlay_active: bool = False
    probability_overlay_state: str = "RESEARCH_ONLY"
    probability_overlay_reason: str = "PROBABILITY_ARTIFACT_MISSING"
    probability_overlay_effects: tuple[ProbabilityOverlayEffect, ...] = ()
    operational_policy_id: str = "NOT_CONFIGURED"
    operational_policy_decision: str = "BLOCK"
    operational_policy_effective: bool = False
    operational_policy_reason: str = "OPERATIONAL_POLICY_NOT_CONFIGURED"
    operational_policy_hash: str = "NOT_CONFIGURED"
    operational_policy_identity_hash: str = "NOT_CONFIGURED"
    signal_authorization_class: str = "FAIL_BLOCKING"
    signal_evidence_level: str = "DIAGNOSTIC_ONLY"


@dataclass(frozen=True, slots=True)
class AssembledResearchInput:
    authorization: ResearchDataAuthorization
    decision_time: datetime
    alpha_signals: tuple[AlphaSignal, ...]
    classical_alpha_signals: tuple[AlphaSignal, ...]
    returns: pd.DataFrame
    benchmark_returns: pd.Series
    risk_metadata: tuple[AssetRiskMetadata, ...]
    disabled_components: tuple[str, ...]
    parameter_fingerprint: str
    factors: tuple[StrategyFactorSnapshot, ...]
    universe_count: int
    data_cutoff: datetime
    source_ids: tuple[str, ...]
    benchmark_symbol: str
    benchmark_observations: int
    benchmark_period_return: float | None
    benchmark_annualized_volatility: float | None
    universe_snapshot_id: str
    data_version: str
    benchmark_evidences: tuple[BenchmarkEvidence, ...] = ()
    strategy_version: str = 'UNAVAILABLE'
    model_approval_hash: str = 'NOT_APPROVED'
    model_approval_data_version: str = 'NOT_APPROVED'
    probability_artifact_id: str = 'OPTIONAL_UNAVAILABLE'
    alpha_symbols: tuple[str, ...] = ()
    candidate_symbols: tuple[str, ...] = ()
    universe_evidence: dict[str, object] = field(default_factory=dict)
    probability_overlay_active: bool = False
    probability_overlay_state: str = "RESEARCH_ONLY"
    probability_overlay_reason: str = "PROBABILITY_ARTIFACT_MISSING"
    probability_overlay_effects: tuple[ProbabilityOverlayEffect, ...] = ()
    operational_policy_id: str = "NOT_CONFIGURED"
    operational_policy_decision: str = "BLOCK"
    operational_policy_effective: bool = False
    operational_policy_reason: str = "OPERATIONAL_POLICY_NOT_CONFIGURED"
    operational_policy_hash: str = "NOT_CONFIGURED"
    operational_policy_identity_hash: str = "NOT_CONFIGURED"
    signal_authorization_class: str = "FAIL_BLOCKING"
    signal_evidence_level: str = "DIAGNOSTIC_ONLY"


def _funnel_counts(eligibility: BroadUniverseEligibility) -> dict[str, int]:
    """Per-layer current operational universe funnel counts."""
    return {
        "listed_securities": eligibility.raw_listed_securities,
        "listed_equities": eligibility.raw_listed_equities,
        "security_type_eligible": len(eligibility.security_type_eligible),
        "latest_price_covered": len(eligibility.latest_price_covered),
        "history_sufficient": len(eligibility.history_sufficient),
        "pit_eligible": len(eligibility.pit_eligible),
        "data_eligible": len(eligibility.data_eligible),
        "liquidity_eligible": len(eligibility.liquidity_eligible),
        "factor_eligible": len(eligibility.factor_eligible),
        "signal_eligible": len(eligibility.signal_eligible),
    }


class ProductionDailyQuantInputAssembler:
    """The only production DB -> DailyQuantInput adapter.

    It never downloads data, fabricates a universe, uses provider-adjusted closes,
    or promotes a model. Missing certified evidence is a hard failure.
    """

    def __init__(
        self,
        session: Session,
        *,
        strategy: USAdaptiveAlphaCoreV1 | None = None,
        effective_config: EffectiveRuntimeConfig | None = None,
    ) -> None:
        self.session = session
        self.repository = USPointInTimeRepository(session)
        self.effective_config = effective_config or EffectiveRuntimeConfig()
        self.strategy = strategy or USAdaptiveAlphaCoreV1(self.effective_config.strategy)
        self.validation_registry = ValidationArtifactRegistry(
            self.effective_config.validation_artifact_dir
        )
        self.probability_overlay_registry = ProbabilityOverlayRegistry(
            self.effective_config.validation_artifact_dir
        )
        self.probability_assessment_registry = ProbabilityAssessmentRegistry(
            self.effective_config.validation_artifact_dir
        )
        self.operational_store = OperationalPolicyStore(
            self.effective_config.operational_policy_path
        )

    def assemble(
        self,
        *,
        portfolio_id: int,
        decision_time: datetime,
        history_days: int = 550,
        benchmark_symbol: str = "SPY",
    ) -> AssembledDailyInput:
        research = self.assemble_research(
            decision_time=decision_time,
            history_days=history_days,
            benchmark_symbol=benchmark_symbol,
        )
        return self.complete_with_portfolio(research, portfolio_id=portfolio_id)

    def assemble_research(
        self,
        *,
        decision_time: datetime,
        history_days: int = 550,
        benchmark_symbol: str = "SPY",
    ) -> AssembledResearchInput:
        if decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        universe = self.repository.certified_universe(as_of=decision_time)
        request = ResearchDataRequest(
            # This first pass produces diagnostics even when no real portfolio is
            # configured.  Portfolio construction has a separate approval gate.
            purpose=ResearchPurpose.RESEARCH,
            market="US",
            asset_type="mixed",
            start_date=(decision_time - timedelta(days=history_days)).date(),
            end_date=decision_time.date(),
            decision_time=decision_time,
            adjustment_mode="point_in_time_total_return",
            universe_snapshot_id=universe.snapshot_id,
        )
        authorization = ResearchDataGateService(self.session).authorize(request)
        (
            alpha_securities,
            reference_securities,
            universe_evidence,
            broad_universe_production_eligible,
        ) = self._select_alpha_universe(
            universe.securities,
            universe_date=decision_time.date(),
            decision_time=decision_time,
            reference_symbols=(benchmark_symbol, self.effective_config.nasdaq_benchmark),
        )
        if not alpha_securities:
            raise ValueError("broad US equity universe contains no diagnostic equities")
        price_securities = tuple(
            {
                item.canonical_code: item
                for item in (*alpha_securities, *reference_securities)
            }.values()
        )
        start_time = decision_time - timedelta(days=history_days)
        if self.effective_config.broad_universe.require_pit_total_return:
            price_frame, _versions = self.repository.total_return_frame(
                price_securities, as_of=decision_time, start_date=start_time
            )
        else:
            # CURRENT_OPERATIONAL_PIT tier: factors are computed from the real
            # PIT-filtered raw price series available at decision_time.  This
            # is current forward-operational data, never a certified total
            # return vintage, so historical research certification is not
            # claimed.
            price_frame = self.repository.raw_price_frame(
                price_securities, as_of=decision_time, start_date=start_time
            )
        alpha_symbols = tuple(item.symbol for item in alpha_securities)
        alpha_price_frame = price_frame[price_frame["ticker"].isin(alpha_symbols)].copy()
        metadata = self.repository.metadata_frame(alpha_securities, as_of=decision_time)
        risk_metadata_frame = self.repository.metadata_frame(
            price_securities, as_of=decision_time
        )
        registry = ModelRegistryService(self.session)
        record = registry.ensure_registered(
            model_id=self.strategy.model_id,
            version=self.strategy.version,
            objective="long-only medium-term US expected excess return",
            inputs=["PIT total return", "sector", "size", "ADV", "optional PIT fundamentals"],
            data_requirements=[
                "certified US universe",
                "certified PIT corporate actions",
                "certified raw prices",
                "strict selected-source calendar and PIT certification",
            ],
            hyperparameters={
                **asdict(self.strategy.config),
                "parameter_fingerprint": self.strategy.config.parameter_fingerprint,
            },
            limitations=[
                "quality disabled until PIT fundamental vintages are certified",
                "no automatic broker execution",
            ],
        )
        del record
        approval = registry.production_approval(
            model_id=self.strategy.model_id,
            version=self.strategy.version,
            data_version=universe.data_version,
            parameter_fingerprint=self.strategy.config.parameter_fingerprint,
            decision_time=decision_time,
        )
        if not broad_universe_production_eligible:
            # Current-directory provenance is a production prerequisite. Legacy
            # local rows may still produce diagnostics but can never reach a trade.
            approval = None
        policy = None
        operational_policy = None
        operational_policy_reason = "OPERATIONAL_POLICY_NOT_CONFIGURED"
        if broad_universe_production_eligible and approval is None:
            policy_status = self.operational_store.status(
                self._operational_identity_at(decision_time),
                research_state="NOT_CERTIFIABLE",
                now=decision_time,
            )
            policy = policy_status.policy
            operational_policy_reason = policy_status.reason
            operational_policy = policy if policy_status.effective else None
        approval_data_version = (
            approval.data_version if approval is not None else 'NOT_APPROVED'
        )
        calibration = self.validation_registry.matching_probability_calibration(
            ProbabilityCalibrationIdentity(
                alpha_model_version=f"{self.strategy.model_id}:{self.strategy.version}",
                alpha_data_version=approval_data_version,
                strategy_parameter_hash=self.strategy.config.parameter_fingerprint,
            )
        )
        fundamentals = self.repository.fundamental_snapshot(
            alpha_securities, as_of=decision_time
        )
        strategy_result = self.strategy.generate(
            prices=alpha_price_frame,
            metadata=metadata,
            decision_time=decision_time,
            data_version=universe.data_version,
            approval=approval,
            operational_approval_hash=(
                operational_policy.policy_id
                if operational_policy is not None
                else None
            ),
            calibration=calibration,
            fundamentals=fundamentals,
            allow_degraded_neutralization=(
                operational_policy is not None
            ),
        )
        strategy_version = (
            f"{self.strategy.model_id}:{self.strategy.version}:"
            f"{strategy_result.parameter_fingerprint[:12]}"
        )
        overlay_universe_version = str(
            universe_evidence.get("eligibility_hash", universe.data_version)
        )
        overlay_identity = ProbabilityOverlayIdentity(
            strategy_version=strategy_version,
            strategy_parameter_hash=strategy_result.parameter_fingerprint,
            research_data_version=universe.data_version,
            research_data_hash=universe.data_version,
            universe_version=overlay_universe_version,
            probability_model_version="NOT_AVAILABLE",
            calibration_version="NOT_AVAILABLE",
        )
        overlay_artifact = None
        overlay_evidence: tuple[ConditionalProbabilityEvidence, ...] = ()
        if approval is not None and broad_universe_production_eligible:
            try:
                overlay_artifact = self.probability_overlay_registry.matching_inputs(
                    strategy_version=strategy_version,
                    strategy_parameter_hash=strategy_result.parameter_fingerprint,
                    research_data_version=universe.data_version,
                    research_data_hash=universe.data_version,
                    universe_version=overlay_universe_version,
                    decision_time=decision_time,
                )
                if overlay_artifact is not None:
                    overlay_identity = overlay_artifact.identity
                    overlay_evidence = self.probability_overlay_registry.evidence(
                        overlay_artifact,
                        decision_time=decision_time,
                    )
            except (KeyError, OSError, TypeError, ValueError):
                overlay_artifact = None
                overlay_evidence = ()
        overlay_application = apply_probability_overlay(
            tuple(strategy_result.signals),
            overlay_evidence,
            artifact=overlay_artifact,
            expected_identity=overlay_identity,
            decision_time=decision_time,
        )
        if not overlay_application.active and overlay_artifact is None:
            assessment = self.probability_assessment_registry.latest_for_strategy(
                strategy_id=self.strategy.model_id,
                strategy_version=self.strategy.version,
                strategy_parameter_hash=self.strategy.config.parameter_fingerprint,
                decision_time=decision_time,
            )
            if assessment is not None:
                overlay_application = replace(
                    overlay_application,
                    reason=f"PROBABILITY_FALLBACK_CLASSICAL:{assessment.verdict}",
                    artifact_id=assessment.assessment_id,
                )
        factors = _overlay_adjusted_factors(
            strategy_result.factors,
            overlay_application.effects,
        )
        # Candidate compression: the full operational cross-section is already
        # factor-ranked and normalized above.  Only a bounded, deterministic
        # candidate pool proceeds to portfolio optimization; every rejection
        # step is recorded and reported.
        candidate_compression = compress_candidates(
            tuple(overlay_application.signals),
            candidate_max=self.effective_config.broad_universe.candidate_max,
            candidate_min_alpha=self.effective_config.broad_universe.candidate_min_alpha,
            adv_by_symbol=(
                {
                    str(row.ticker): float(row.average_daily_dollar_volume)
                    for row in risk_metadata_frame.itertuples(index=False)
                }
                if not risk_metadata_frame.empty
                else None
            ),
            minimum_adv=(
                self.effective_config.broad_universe.minimum_average_dollar_volume
            ),
        )
        candidate_symbols = candidate_compression.candidate_symbols
        candidate_set = set(candidate_symbols)
        candidate_signals = tuple(
            item for item in overlay_application.signals if item.symbol in candidate_set
        )
        classical_compression = compress_candidates(
            tuple(strategy_result.signals),
            candidate_max=self.effective_config.broad_universe.candidate_max,
            candidate_min_alpha=self.effective_config.broad_universe.candidate_min_alpha,
            adv_by_symbol=(
                {
                    str(row.ticker): float(row.average_daily_dollar_volume)
                    for row in risk_metadata_frame.itertuples(index=False)
                }
                if not risk_metadata_frame.empty
                else None
            ),
            minimum_adv=self.effective_config.broad_universe.minimum_average_dollar_volume,
        )
        classical_candidate_set = set(classical_compression.candidate_symbols)
        classical_candidate_signals = tuple(
            item for item in strategy_result.signals if item.symbol in classical_candidate_set
        )
        candidate_evidence = {
            "candidate_compression": candidate_compression.document(),
            "candidate_count": len(candidate_symbols),
            "full_factor_count": len(strategy_result.factors),
            "alpha_positive": sum(
                item.expected_excess_return > 0 for item in strategy_result.signals
            ),
            "optimizer_input": len(candidate_signals),
        }
        universe_evidence = {**universe_evidence, **candidate_evidence}
        levels = price_frame.pivot(
            index="trade_date", columns="ticker", values="close"
        ).sort_index()
        levels.index = pd.DatetimeIndex(pd.to_datetime(levels.index, utc=True))
        all_returns = levels.pct_change(fill_method=None).dropna(how="all")
        if benchmark_symbol not in all_returns:
            raise ValueError(
                f"certified benchmark is missing from PIT universe: {benchmark_symbol}"
            )
        benchmark_returns = all_returns[benchmark_symbol].dropna()
        # Risk history includes distinct benchmark/risk-reference ETFs and current
        # portfolio cash proxies, while factors and alpha remain restricted to
        # ``alpha_price_frame`` above.  This prevents ETF cross-sectional leakage
        # without making an existing non-alpha holding unmeasurable by risk.
        returns = all_returns.dropna(how="all")
        market_caps = pd.to_numeric(metadata["market_cap"], errors="coerce")
        valid_caps = market_caps.notna() & (market_caps > 0)
        size_scores: dict[str, float] = {}
        if bool(valid_caps.all()) and len(metadata) >= 3:
            log_caps = np.log(market_caps.astype(float))
            deviation = float(log_caps.std(ddof=1))
            if np.isfinite(deviation) and deviation > 1e-12:
                centered = (log_caps - float(log_caps.mean())) / deviation
                size_scores = {
                    str(row.ticker): float(centered.iloc[index])
                    for index, row in enumerate(metadata.itertuples(index=False))
                }
        alpha_symbol_set = set(alpha_symbols)
        risk_metadata = tuple(
            AssetRiskMetadata(
                symbol=str(row.ticker),
                sector=(
                    str(row.sector)
                    if str(row.ticker) in alpha_symbol_set
                    else f"REFERENCE:{row.sector}"
                ),
                average_daily_dollar_volume=float(row.average_daily_dollar_volume),
                # Non-alpha references receive a neutral size exposure. They are
                # present solely so existing holdings can be risk-measured and
                # reduced; they are never ranked as equity alpha candidates.
                size_score=(
                    size_scores.get(str(row.ticker))
                    if str(row.ticker) in alpha_symbol_set
                    else 0.0
                ),
                market_cap=(
                    float(row.market_cap)
                    if str(row.ticker) in alpha_symbol_set
                    and row.market_cap is not None
                    and not bool(np.isnan(row.market_cap))
                    and float(row.market_cap) > 0
                    else None
                ),
            )
            for row in risk_metadata_frame.itertuples(index=False)
        )
        return AssembledResearchInput(
            authorization,
            decision_time,
            candidate_signals,
            classical_candidate_signals,
            returns,
            benchmark_returns,
            risk_metadata,
            strategy_result.disabled_components,
            strategy_result.parameter_fingerprint,
            factors,
            len(alpha_securities),
            all_returns.index.max().to_pydatetime(),
            tuple(authorization.evidence.source_ids) if authorization.evidence else (),
            benchmark_symbol,
            len(benchmark_returns),
            (
                float((1.0 + benchmark_returns).prod() - 1.0)
                if len(benchmark_returns)
                else None
            ),
            (
                float(benchmark_returns.std(ddof=1) * np.sqrt(252))
                if len(benchmark_returns) > 1
                else None
            ),
            universe.snapshot_id,
            universe.data_version,
            tuple(
                evidence
                for evidence in (
                    benchmark_evidence_from_returns(all_returns, benchmark_symbol),
                    benchmark_evidence_from_returns(
                        all_returns, self.effective_config.nasdaq_benchmark
                    ),
                )
                if evidence is not None
            ),
            strategy_version,
            (
                approval.validation_manifest_hash
                if approval is not None
                else 'NOT_APPROVED'
            ),
            approval_data_version,
            overlay_application.artifact_id,
            alpha_symbols,
            candidate_symbols,
            universe_evidence,
            overlay_application.active,
            overlay_application.state.value,
            overlay_application.reason,
            overlay_application.effects,
            (
                policy.policy_id
                if policy is not None
                else "NOT_CONFIGURED"
            ),
            (
                policy.decision.value
                if policy is not None
                else OperationalPolicyDecision.BLOCK.value
            ),
            operational_policy is not None,
            operational_policy_reason,
            policy.artifact_hash if policy is not None else "NOT_CONFIGURED",
            (
                policy.identity.identity_hash
                if policy is not None
                else "NOT_CONFIGURED"
            ),
            (
                "PASS_PRODUCTION"
                if approval is not None
                else (
                    "PASS_PROVISIONAL"
                    if operational_policy is not None
                    else "FAIL_BLOCKING"
                )
            ),
            (
                "FULL_RESEARCH_CERTIFIED"
                if approval is not None
                else (
                    "PROVISIONAL_OPERATIONAL_ADVISORY"
                    if operational_policy is not None
                    else "DIAGNOSTIC_ONLY"
                )
            ),
        )

    def _operational_policy(self, decision_time: datetime) -> OperationalPolicy | None:
        status = self.operational_store.status(
            self._operational_identity_at(decision_time),
            research_state="NOT_CERTIFIABLE",
            now=decision_time,
        )
        return status.policy if status.effective else None

    def _operational_identity_at(
        self, decision_time: datetime
    ) -> OperationalApprovalIdentity:
        return resolve_current_operational_identity(
            self.effective_config,
            self.strategy,
            decision_time=decision_time,
        )

    def complete_with_portfolio(
        self,
        research: AssembledResearchInput,
        *,
        portfolio_id: int,
        regime: RegimeRiskInput | None = None,
    ) -> AssembledDailyInput:
        universe = self.repository.certified_universe(
            as_of=research.decision_time,
            snapshot_id=int(research.universe_snapshot_id),
        )
        alpha_symbol_set = set(research.candidate_symbols or research.alpha_symbols)
        alpha_symbol_set.update(item.symbol for item in research.classical_alpha_signals)
        universe_by_symbol = {item.symbol: item for item in universe.securities}
        if any(
            self.repository.tradability(item.id, as_of=research.decision_time) != "TRADABLE"
            for item in universe.securities
            if item.symbol in alpha_symbol_set
        ):
            raise ValueError(
                "formal portfolio construction requires certified TRADABLE status"
            )
        # Broad CURRENT_OPERATIONAL_PIT candidates are usually not members of the
        # certified research snapshot.  They must still satisfy the current
        # tradability gate before they can enter portfolio construction.
        missing_symbols = sorted(alpha_symbol_set - set(universe_by_symbol))
        if missing_symbols:
            extra_securities = tuple(
                self.session.scalars(
                    select(SecurityMaster).where(
                        SecurityMaster.symbol.in_(missing_symbols)
                    )
                )
            )
            if {item.symbol for item in extra_securities} != set(missing_symbols):
                raise ValueError(
                    "candidate securities are missing from the security master"
                )
            if any(
                self.repository.tradability(
                    item.id, as_of=research.decision_time
                )
                != "TRADABLE"
                for item in extra_securities
            ):
                raise ValueError(
                    "formal portfolio construction requires certified TRADABLE status"
                )
        decision_authorization = ResearchDataGateService(self.session).authorize(
            replace(research.authorization.request, purpose=ResearchPurpose.PORTFOLIO_DECISION)
        )
        (
            current_weights,
            portfolio_value,
            portfolio_positions,
            cash_balance,
        ) = self._portfolio_state(
            portfolio_id=portfolio_id, decision_time=research.decision_time
        )
        decision_symbols = alpha_symbol_set | set(current_weights)
        decision_returns = research.returns.loc[
            :, [symbol for symbol in research.returns.columns if symbol in decision_symbols]
        ]
        decision_risk_metadata = tuple(
            item for item in research.risk_metadata if item.symbol in decision_symbols
        )
        if set(current_weights) - set(decision_returns.columns):
            raise ValueError("portfolio risk history does not cover current holdings")
        if set(current_weights) - {item.symbol for item in decision_risk_metadata}:
            raise ValueError("current holdings are missing from the risk universe")
        risk_state = self._risk_state(
            decision_returns,
            research.benchmark_returns,
            current_weights,
            decision_cutoff=research.decision_time,
        )
        return AssembledDailyInput(
            DailyQuantInput(
                authorization=decision_authorization,
                decision_time=research.decision_time,
                alpha_signals=research.alpha_signals,
                returns=decision_returns,
                benchmark_returns=research.benchmark_returns,
                risk_metadata=decision_risk_metadata,
                current_weights=current_weights,
                portfolio_value=portfolio_value,
                portfolio_risk_state=risk_state,
                regime=regime,
                pit_valid=True,
                universe_snapshot_id=research.universe_snapshot_id,
                data_quality="CERTIFIED",
            ),
            research.classical_alpha_signals,
            research.disabled_components,
            research.parameter_fingerprint,
            research.factors,
            research.universe_count,
            research.data_cutoff,
            research.source_ids,
            research.benchmark_symbol,
            research.benchmark_observations,
            research.benchmark_period_return,
            research.benchmark_annualized_volatility,
            portfolio_positions,
            cash_balance,
            research.benchmark_evidences,
            research.data_version,
            research.universe_snapshot_id,
            research.strategy_version,
            research.model_approval_hash,
            research.model_approval_data_version,
            research.probability_artifact_id,
            research.alpha_symbols,
            research.candidate_symbols,
            research.universe_evidence,
            research.probability_overlay_active,
            research.probability_overlay_state,
            research.probability_overlay_reason,
            research.probability_overlay_effects,
            research.operational_policy_id,
            research.operational_policy_decision,
            research.operational_policy_effective,
            research.operational_policy_reason,
            research.operational_policy_hash,
            research.operational_policy_identity_hash,
            research.signal_authorization_class,
            research.signal_evidence_level,
        )

    def _select_alpha_universe(
        self,
        securities: tuple[SecurityMaster, ...],
        *,
        universe_date: date,
        decision_time: datetime,
        reference_symbols: tuple[str, ...],
    ) -> tuple[
        tuple[SecurityMaster, ...],
        tuple[SecurityMaster, ...],
        dict[str, object],
        bool,
    ]:
        rules = EligibilityRules(**asdict(self.effective_config.broad_universe))
        service = BroadUSUniverseService(
            self.session,
            cache_root=self.effective_config.cache_dir / "us-current-directory",
            rules=rules,
        )
        # CURRENT_OPERATIONAL_PIT tier.  With ``require_pit_total_return`` from
        # config (False on the broad operational path) this selects the broad
        # current-directory universe; with True it stays on the strict certified
        # total-return tier.
        selection = service.select(
            universe_date=universe_date,
            decision_time=decision_time,
            reference_symbols=reference_symbols,
        )
        official = selection.directory.provider == "nasdaq_trader_symbol_directory"
        if official:
            if not selection.alpha_securities:
                raise ValueError("official broad universe has no factor eligible equities")
            evidence = selection.evidence()
            operational = selection.eligibility
            evidence["qualification"] = operational.qualification.value
            evidence["pit_status"] = operational.pit_status
            evidence["funnel"] = _funnel_counts(operational)
            # HISTORICAL_RESEARCH_PIT tier is evaluated independently.  A
            # degraded historical certification must never collapse the current
            # operational universe by itself.
            try:
                historical = BroadUSUniverseService(
                    self.session,
                    cache_root=self.effective_config.cache_dir / "us-current-directory",
                    rules=EligibilityRules(**asdict(self.effective_config.broad_universe)),
                ).select(
                    universe_date=universe_date,
                    decision_time=decision_time,
                    reference_symbols=reference_symbols,
                    require_pit_total_return=True,
                )
                historical_eligibility = historical.eligibility
                evidence["historical_research"] = {
                    "security_type_eligible": len(
                        historical_eligibility.security_type_eligible
                    ),
                    "data_eligible": len(historical_eligibility.data_eligible),
                    "liquidity_eligible": len(historical_eligibility.liquidity_eligible),
                    "factor_eligible": len(historical_eligibility.factor_eligible),
                    "signal_eligible": len(historical_eligibility.signal_eligible),
                    "pit_status": historical_eligibility.pit_status,
                    "qualification": historical_eligibility.qualification.value,
                    "survivorship_status": (
                        historical_eligibility.survivorship_status.value
                    ),
                    "symbols": sorted(
                        item.symbol for item in historical_eligibility.factor_eligible
                    ),
                }
            except (KeyError, OSError, TypeError, ValueError):
                evidence["historical_research"] = {"status": "UNAVAILABLE"}
            # Quarantine: symbols on a blocking issue are not part of the current
            # operational universe.  The quarantine store lives beside the
            # broad-universe cache and is populated by the batch downloader.
            quarantine = self._quarantine()
            evidence["quarantine_count"] = len(quarantine)
            evidence["quarantine_symbols"] = sorted(quarantine)[:200]
            # Coverage-collapse guard applies to the broad current operational
            # universe only.  The strict certified tier is intentionally small
            # and must never trip a broad-universe threshold.
            if not rules.require_pit_total_return:
                record = OperationalBaselineRecord(
                    decision_date=universe_date,
                    factor_eligible=len(operational.factor_eligible),
                    operational_eligible=len(operational.signal_eligible),
                    quarantine_count=len(quarantine),
                )
                baseline_path = self.effective_config.operational_universe_baseline_path
                prior = load_baseline(baseline_path)
                collapsed, collapse_reason = detect_collapse(
                    prior,
                    current_factor_eligible=record.factor_eligible,
                    minimum_operational_universe=rules.minimum_operational_universe,
                    coverage_collapse_ratio=rules.coverage_collapse_ratio,
                )
                append_record(baseline_path, record)
                evidence["collapse"] = {
                    "detected": collapsed,
                    "reason": collapse_reason,
                    "minimum_operational_universe": (
                        rules.minimum_operational_universe
                    ),
                    "coverage_collapse_ratio": rules.coverage_collapse_ratio,
                    "recent_factor_eligible": [
                        item.factor_eligible for item in prior[-6:]
                    ],
                }
                if collapsed:
                    return (
                        selection.alpha_securities,
                        selection.reference_securities,
                        evidence,
                        False,
                    )
            else:
                evidence["collapse"] = {
                    "detected": False,
                    "reason": "collapse guard applies to CURRENT_OPERATIONAL_PIT only",
                    "minimum_operational_universe": rules.minimum_operational_universe,
                    "coverage_collapse_ratio": rules.coverage_collapse_ratio,
                    "recent_factor_eligible": [],
                }
            return (
                selection.alpha_securities,
                selection.reference_securities,
                evidence,
                True,
            )

        # Preserve historical diagnostics when current metadata is temporarily
        # unavailable, but report zero formal eligibility and disable approval.
        alpha = tuple(item for item in securities if item.asset_type == "stock")
        references = tuple(
            item
            for item in securities
            if item.symbol in set(reference_symbols)
            and item.asset_type in {"etf", "index"}
        )
        fallback_evidence: dict[str, object] = {
            "listed_equities": "UNAVAILABLE",
            "security_type_eligible": 0,
            "data_eligible": 0,
            "liquidity_eligible": 0,
            "factor_eligible": 0,
            "signal_eligible": 0,
            "diagnostic_input_count": len(alpha),
            "universe_date": universe_date.isoformat(),
            "directory_provider": selection.directory.provider,
            "directory_version": selection.directory.dataset_version,
            "pit_status": "CURRENT_DIRECTORY_NOT_CERTIFIED",
            "survivorship_status": "UNVERIFIED",
            "historical_use_allowed": False,
            "warnings": list(selection.warnings),
        }
        return alpha, references, fallback_evidence, False

    def _quarantine(self) -> dict[str, str]:
        path = self.effective_config.cache_dir / "broad-universe" / "quarantine.json"
        if not path.exists():
            return {}
        try:
            payload = __import__("json").loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return {}
        return {str(key): str(value) for key, value in payload.items()}

    def _portfolio_state(
        self, *, portfolio_id: int, decision_time: datetime
    ) -> tuple[
        dict[str, float],
        float,
        tuple[PortfolioInputPosition, ...],
        float,
    ]:
        portfolio = self.session.get(Portfolio, portfolio_id)
        if portfolio is None:
            raise ValueError("portfolio does not exist")
        latest_dates = (
            select(
                PortfolioPosition.stock_id,
                func.max(PortfolioPosition.as_of_date).label("latest_date"),
            )
            .where(
                PortfolioPosition.portfolio_id == portfolio_id,
                PortfolioPosition.as_of_date <= decision_time.date(),
            )
            .group_by(PortfolioPosition.stock_id)
            .subquery()
        )
        positions = list(
            self.session.scalars(
                select(PortfolioPosition)
                .join(
                    latest_dates,
                    (PortfolioPosition.stock_id == latest_dates.c.stock_id)
                    & (PortfolioPosition.as_of_date == latest_dates.c.latest_date),
                )
                .where(PortfolioPosition.portfolio_id == portfolio_id)
            )
        )
        values: dict[str, float] = {}
        quantities: dict[str, float] = {}
        prices: dict[str, float] = {}
        for position in positions:
            security = self.session.get(SecurityMaster, position.stock_id)
            price = self.session.scalar(
                select(Price)
                .where(
                    Price.stock_id == position.stock_id,
                    Price.trade_date <= decision_time.date(),
                    Price.available_time.is_not(None),
                    Price.available_time <= decision_time,
                    Price.price_type == "unadjusted_ohlcv",
                )
                .order_by(Price.trade_date.desc(), Price.id.desc())
                .limit(1)
            )
            if security is None or price is None:
                raise ValueError("current portfolio contains an unpriceable security")
            values[security.symbol] = float(position.quantity) * float(price.close)
            quantities[security.symbol] = float(position.quantity)
            prices[security.symbol] = float(price.close)
        total = float(portfolio.cash_balance) + sum(values.values())
        if total <= 0:
            raise ValueError("portfolio value must be positive")
        weights = {symbol: value / total for symbol, value in values.items()}
        snapshots = tuple(
            PortfolioInputPosition(
                symbol,
                quantities[symbol],
                prices[symbol],
                weights[symbol],
            )
            for symbol in sorted(values)
        )
        return weights, total, snapshots, float(portfolio.cash_balance)

    @staticmethod
    def _risk_state(
        returns: pd.DataFrame,
        benchmark_returns: pd.Series,
        current_weights: dict[str, float],
        *,
        decision_cutoff: datetime,
    ) -> PortfolioRiskState:
        if decision_cutoff.tzinfo is None:
            raise ValueError("portfolio risk cutoff must be timezone-aware")
        cutoff = pd.Timestamp(decision_cutoff)
        for name, history in (("asset", returns), ("benchmark", benchmark_returns)):
            if not isinstance(history.index, pd.DatetimeIndex) or history.empty:
                raise ValueError(f"{name} risk history requires a non-empty DatetimeIndex")
            latest = history.index.max()
            if latest.tzinfo is None:
                if latest.date() > decision_cutoff.date():
                    raise ValueError(f"{name} risk history contains future observations")
            elif latest > cutoff:
                raise ValueError(f"{name} risk history contains future observations")
        if not current_weights:
            return PortfolioRiskState(
                0.0,
                0.0,
                0.0,
                0.0,
                None,
                None,
                CorrelationRiskStatus.NOT_APPLICABLE,
            )
        symbols = [symbol for symbol in current_weights if symbol in returns]
        if not symbols:
            raise ValueError("portfolio risk history does not cover current holdings")
        weights = np.array([current_weights[symbol] for symbol in symbols])
        aligned = returns[symbols].dropna(how="any")
        if len(aligned) < 63:
            raise ValueError("insufficient complete observations for portfolio risk")
        portfolio_returns = aligned.to_numpy() @ weights
        rolling_volatility = float(np.std(portfolio_returns[-63:], ddof=1) * np.sqrt(252))
        wealth = np.cumprod(1 + portfolio_returns)
        drawdown = float(wealth[-1] / np.maximum.accumulate(wealth)[-1] - 1) if len(wealth) else 0.0
        recent_window = 63
        baseline_window = 252
        minimum_baseline = 126
        if len(symbols) < 2:
            correlation_status = CorrelationRiskStatus.NOT_APPLICABLE
            recent_correlation = None
            baseline_correlation = None
            recent_samples = 0
            baseline_samples = 0
        else:
            recent = aligned.iloc[-recent_window:]
            baseline_end = max(0, len(aligned) - recent_window)
            baseline = aligned.iloc[max(0, baseline_end - baseline_window):baseline_end]
            recent_samples = len(recent)
            baseline_samples = len(baseline)
            if recent_samples < recent_window or baseline_samples < minimum_baseline:
                correlation_status = CorrelationRiskStatus.NOT_VALIDATED
                recent_correlation = None
                baseline_correlation = None
            else:
                recent_correlation = _average_off_diagonal_correlation(recent)
                baseline_correlation = _average_off_diagonal_correlation(baseline)
                correlation_status = CorrelationRiskStatus.VALID
        common = pd.concat(
            [
                pd.Series(portfolio_returns, index=aligned.index, name="portfolio"),
                benchmark_returns.rename("benchmark"),
            ],
            axis=1,
            join="inner",
        ).dropna()
        if len(common) < 63 or float(common["benchmark"].var(ddof=1)) <= 0:
            raise ValueError("insufficient benchmark observations for portfolio beta")
        portfolio_beta = float(
            common["portfolio"].cov(common["benchmark"])
            / common["benchmark"].var(ddof=1)
        )
        return PortfolioRiskState(
            current_drawdown=drawdown,
            rolling_volatility=rolling_volatility,
            portfolio_beta=portfolio_beta,
            concentration_hhi=sum(weight * weight for weight in current_weights.values()),
            average_correlation=recent_correlation,
            baseline_average_correlation=baseline_correlation,
            correlation_status=correlation_status,
            correlation_recent_window=recent_window,
            correlation_baseline_window=baseline_window,
            correlation_recent_samples=recent_samples,
            correlation_baseline_samples=baseline_samples,
        )


def _average_off_diagonal_correlation(values: pd.DataFrame) -> float:
    correlation = values.corr().to_numpy(dtype=float)
    off_diagonal = correlation[np.triu_indices(len(values.columns), 1)]
    if not len(off_diagonal) or np.any(~np.isfinite(off_diagonal)):
        raise ValueError("correlation window is not finite")
    return float(np.mean(off_diagonal))


def _overlay_adjusted_factors(
    factors: tuple[StrategyFactorSnapshot, ...],
    effects: tuple[ProbabilityOverlayEffect, ...],
) -> tuple[StrategyFactorSnapshot, ...]:
    """Reflect an active overlay in expected-return ranks without changing factors."""

    if not effects:
        return factors
    adjusted_returns = {
        item.symbol: item.adjusted_expected_excess_return for item in effects
    }
    adjusted = tuple(
        replace(
            factor,
            expected_alpha=adjusted_returns.get(factor.symbol, factor.expected_alpha),
        )
        for factor in factors
    )
    ordered = sorted(adjusted, key=lambda item: (-item.expected_alpha, item.symbol))
    return tuple(replace(item, rank=index) for index, item in enumerate(ordered, start=1))
