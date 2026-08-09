from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
from personal_alpha_terminal.data.us_market.repository import USPointInTimeRepository
from personal_alpha_terminal.models import Portfolio, PortfolioPosition, Price, SecurityMaster
from personal_alpha_terminal.quant_engine.alpha import AlphaSignal
from personal_alpha_terminal.quant_engine.model_registry import ModelRegistryService
from personal_alpha_terminal.quant_engine.production_pipeline import DailyQuantInput
from personal_alpha_terminal.quant_engine.risk.budget import (
    CorrelationRiskStatus,
    PortfolioRiskState,
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


@dataclass(frozen=True, slots=True)
class AssembledResearchInput:
    authorization: ResearchDataAuthorization
    decision_time: datetime
    alpha_signals: tuple[AlphaSignal, ...]
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
            purpose=ResearchPurpose.PORTFOLIO_DECISION,
            market="US",
            asset_type="stock",
            start_date=(decision_time - timedelta(days=history_days)).date(),
            end_date=decision_time.date(),
            decision_time=decision_time,
            adjustment_mode="point_in_time_total_return",
            universe_snapshot_id=universe.snapshot_id,
        )
        authorization = ResearchDataGateService(self.session).authorize(request)
        if any(
            self.repository.tradability(item.id, as_of=decision_time) != "TRADABLE"
            for item in universe.securities
        ):
            raise ValueError("universe contains UNKNOWN or non-tradable security status")
        start_time = decision_time - timedelta(days=history_days)
        price_frame, _versions = self.repository.total_return_frame(
            universe.securities, as_of=decision_time, start_date=start_time
        )
        metadata = self.repository.metadata_frame(universe.securities, as_of=decision_time)
        if metadata["sector"].eq("UNKNOWN").any():
            raise ValueError("certified sector metadata is required for portfolio construction")
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
                "second-source reconciliation",
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
        calibration = self.validation_registry.matching_probability_calibration(
            ProbabilityCalibrationIdentity(
                alpha_model_version=f"{self.strategy.model_id}:{self.strategy.version}",
                alpha_data_version=universe.data_version,
                strategy_parameter_hash=self.strategy.config.parameter_fingerprint,
            )
        )
        fundamentals = self.repository.fundamental_snapshot(
            universe.securities, as_of=decision_time
        )
        strategy_result = self.strategy.generate(
            prices=price_frame,
            metadata=metadata,
            decision_time=decision_time,
            data_version=universe.data_version,
            approval=approval,
            calibration=calibration,
            fundamentals=fundamentals,
        )
        levels = price_frame.pivot(
            index="trade_date", columns="ticker", values="close"
        ).sort_index()
        levels.index = pd.DatetimeIndex(pd.to_datetime(levels.index, utc=True))
        returns = levels.pct_change(fill_method=None).dropna(how="all")
        if benchmark_symbol not in returns:
            raise ValueError(
                f"certified benchmark is missing from PIT universe: {benchmark_symbol}"
            )
        benchmark_returns = returns[benchmark_symbol].dropna()
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
        risk_metadata = tuple(
            AssetRiskMetadata(
                symbol=str(row.ticker),
                sector=str(row.sector),
                average_daily_dollar_volume=float(row.average_daily_dollar_volume),
                size_score=size_scores.get(str(row.ticker)),
            )
            for row in metadata.itertuples(index=False)
        )
        return AssembledResearchInput(
            authorization,
            decision_time,
            tuple(strategy_result.signals),
            returns,
            benchmark_returns,
            risk_metadata,
            strategy_result.disabled_components,
            strategy_result.parameter_fingerprint,
            strategy_result.factors,
            len(universe.securities),
            returns.index.max().to_pydatetime(),
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
        )

    def complete_with_portfolio(
        self,
        research: AssembledResearchInput,
        *,
        portfolio_id: int,
    ) -> AssembledDailyInput:
        (
            current_weights,
            portfolio_value,
            portfolio_positions,
            cash_balance,
        ) = self._portfolio_state(
            portfolio_id=portfolio_id, decision_time=research.decision_time
        )
        risk_state = self._risk_state(
            research.returns,
            research.benchmark_returns,
            current_weights,
            decision_cutoff=research.decision_time,
        )
        return AssembledDailyInput(
            DailyQuantInput(
                authorization=research.authorization,
                decision_time=research.decision_time,
                alpha_signals=research.alpha_signals,
                returns=research.returns,
                benchmark_returns=research.benchmark_returns,
                risk_metadata=research.risk_metadata,
                current_weights=current_weights,
                portfolio_value=portfolio_value,
                portfolio_risk_state=risk_state,
                regime=None,
                pit_valid=True,
                universe_snapshot_id=research.universe_snapshot_id,
                data_quality="CERTIFIED",
            ),
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
        )

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
