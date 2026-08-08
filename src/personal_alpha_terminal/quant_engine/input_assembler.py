from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personal_alpha_terminal.data.us_market.repository import USPointInTimeRepository
from personal_alpha_terminal.models import Portfolio, PortfolioPosition, Price, SecurityMaster
from personal_alpha_terminal.quant_engine.model_registry import ModelRegistryService
from personal_alpha_terminal.quant_engine.production_pipeline import DailyQuantInput
from personal_alpha_terminal.quant_engine.risk.budget import PortfolioRiskState
from personal_alpha_terminal.quant_engine.risk.model import AssetRiskMetadata
from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
    USAdaptiveAlphaCoreV1,
)
from personal_alpha_terminal.research.data_gate import ResearchDataRequest, ResearchPurpose
from personal_alpha_terminal.research.service import ResearchDataGateService


@dataclass(frozen=True, slots=True)
class AssembledDailyInput:
    inputs: DailyQuantInput
    disabled_components: tuple[str, ...]
    parameter_fingerprint: str


class ProductionDailyQuantInputAssembler:
    """The only production DB -> DailyQuantInput adapter.

    It never downloads data, fabricates a universe, uses provider-adjusted closes,
    or promotes a model. Missing certified evidence is a hard failure.
    """

    def __init__(self, session: Session, *, strategy: USAdaptiveAlphaCoreV1 | None = None) -> None:
        self.session = session
        self.repository = USPointInTimeRepository(session)
        self.strategy = strategy or USAdaptiveAlphaCoreV1()

    def assemble(
        self,
        *,
        portfolio_id: int,
        decision_time: datetime,
        history_days: int = 550,
        benchmark_symbol: str = "SPY",
    ) -> AssembledDailyInput:
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
        fundamentals = self.repository.fundamental_snapshot(
            universe.securities, as_of=decision_time
        )
        strategy_result = self.strategy.generate(
            prices=price_frame,
            metadata=metadata,
            decision_time=decision_time,
            data_version=universe.data_version,
            approval=approval,
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
        risk_metadata = tuple(
            AssetRiskMetadata(
                symbol=str(row.ticker),
                sector=str(row.sector),
                average_daily_dollar_volume=float(row.average_daily_dollar_volume),
                size_score=0.0,
            )
            for row in metadata.itertuples(index=False)
        )
        current_weights, portfolio_value = self._portfolio_state(
            portfolio_id=portfolio_id,
            decision_time=decision_time,
        )
        risk_state = self._risk_state(returns, benchmark_returns, current_weights)
        return AssembledDailyInput(
            DailyQuantInput(
                authorization=authorization,
                decision_time=decision_time,
                alpha_signals=strategy_result.signals,
                returns=returns,
                benchmark_returns=benchmark_returns,
                risk_metadata=risk_metadata,
                current_weights=current_weights,
                portfolio_value=portfolio_value,
                portfolio_risk_state=risk_state,
                regime=None,
                pit_valid=True,
                universe_snapshot_id=universe.snapshot_id,
                data_quality="CERTIFIED",
            ),
            strategy_result.disabled_components,
            strategy_result.parameter_fingerprint,
        )

    def _portfolio_state(
        self, *, portfolio_id: int, decision_time: datetime
    ) -> tuple[dict[str, float], float]:
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
        total = float(portfolio.cash_balance) + sum(values.values())
        if total <= 0:
            raise ValueError("portfolio value must be positive")
        return {symbol: value / total for symbol, value in values.items()}, total

    @staticmethod
    def _risk_state(
        returns: pd.DataFrame,
        benchmark_returns: pd.Series,
        current_weights: dict[str, float],
    ) -> PortfolioRiskState:
        if not current_weights:
            return PortfolioRiskState(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
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
        correlation = aligned.corr().to_numpy()
        off_diagonal = correlation[np.triu_indices(len(symbols), 1)]
        average_correlation = float(np.nanmean(off_diagonal)) if len(off_diagonal) else 0.0
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
            average_correlation=average_correlation,
            baseline_average_correlation=average_correlation,
        )
