from collections import defaultdict
from dataclasses import asdict
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.backtest.schemas import (
    BacktestBar,
    BacktestConfig,
    BacktestDataset,
    BacktestResult,
    UniversePoint,
)
from personal_alpha_terminal.core.market_time import normalize_utc
from personal_alpha_terminal.data.market_data.selection import (
    preferred_source,
    select_consistent_price_series,
)
from personal_alpha_terminal.models import (
    BacktestDailyResult,
    BacktestRebalance,
    BacktestRun,
    BacktestSummaryMetric,
    MarketUniverseMember,
    MarketUniverseSnapshot,
    Price,
    Stock,
)


class BacktestRepository:
    """Load one-source price histories and persist auditable run evidence."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def load_dataset(
        self,
        *,
        market: str,
        asset_ids: tuple[int, ...],
        start_date: date,
        end_date: date,
        calendar: tuple[date, ...],
        calendar_source: str,
        universe_timeline: tuple[UniversePoint, ...] = (),
    ) -> BacktestDataset:
        if not asset_ids:
            raise ValueError("asset_ids cannot be empty")
        if not calendar:
            raise ValueError("verified trading calendar cannot be empty")
        stocks = list(
            self.session.scalars(
                select(Stock)
                .where(
                    Stock.id.in_(asset_ids),
                    Stock.market == market,
                    Stock.asset_type.in_(("stock", "etf")),
                )
                .order_by(Stock.id)
            )
        )
        if {item.id for item in stocks} != set(asset_ids):
            raise ValueError("some assets do not exist in the requested market")
        prices = self.session.scalars(
            select(Price)
            .where(
                Price.stock_id.in_(asset_ids),
                Price.trade_date >= start_date,
                Price.trade_date <= end_date,
            )
            .order_by(
                Price.stock_id,
                Price.trade_date,
                Price.ingested_at.desc(),
                Price.source,
            )
        )
        rows: defaultdict[int, list[Price]] = defaultdict(list)
        for item in prices:
            rows[item.stock_id].append(item)
        stock_by_id = {item.id: item for item in stocks}
        output: list[BacktestBar] = []
        selected_sources: set[str] = set()
        for asset_id in asset_ids:
            chosen = select_consistent_price_series(
                rows[asset_id],
                preferred=preferred_source(market),
            )
            for price in chosen:
                if price.event_time is None or price.available_time is None:
                    raise ValueError(
                        "backtest price rows must be re-ingested with exact "
                        f"three-time provenance: stock_id={asset_id} "
                        f"date={price.trade_date}"
                    )
                selected_sources.add(price.source)
                stock = stock_by_id[asset_id]
                output.append(
                    BacktestBar(
                        asset_id=asset_id,
                        symbol=stock.symbol,
                        market=stock.market,
                        trade_date=price.trade_date,
                        open=float(price.open),
                        high=float(price.high),
                        low=float(price.low),
                        close=float(price.close),
                        adjusted_close=(
                            float(price.adjusted_close)
                            if price.adjusted_close is not None
                            else None
                        ),
                        volume=price.volume,
                        source=price.source,
                        adjustment_method=price.adjustment_method,
                        provider=price.provider,
                        event_time=price.event_time,
                        available_time=price.available_time,
                        ingested_time=normalize_utc(price.ingested_at),
                        open_tradable=price.open_tradable,
                    )
                )
        return BacktestDataset(
            market=market,
            bars=tuple(output),
            data_sources=tuple(
                f"prices:{item}:consistent_single_provider" for item in sorted(selected_sources)
            ),
            calendar=calendar,
            calendar_source=calendar_source,
            universe_timeline=universe_timeline,
        )

    def load_universe_timeline(
        self,
        snapshot_ids: tuple[int, ...],
        *,
        market: str,
    ) -> tuple[UniversePoint, ...]:
        """Load immutable membership snapshots without using today's survivor set."""

        if not snapshot_ids:
            raise ValueError("at least one universe snapshot is required")
        snapshots = list(
            self.session.scalars(
                select(MarketUniverseSnapshot)
                .where(
                    MarketUniverseSnapshot.id.in_(snapshot_ids),
                    MarketUniverseSnapshot.market == market,
                )
                .order_by(
                    MarketUniverseSnapshot.as_of_date,
                    MarketUniverseSnapshot.available_time,
                    MarketUniverseSnapshot.id,
                )
            )
        )
        if {item.id for item in snapshots} != set(snapshot_ids):
            raise ValueError("some universe snapshots do not exist in the requested market")
        member_rows = self.session.execute(
            select(
                MarketUniverseMember.snapshot_id,
                MarketUniverseMember.stock_id,
            )
            .where(MarketUniverseMember.snapshot_id.in_(snapshot_ids))
            .order_by(
                MarketUniverseMember.snapshot_id,
                MarketUniverseMember.stock_id,
            )
        )
        members: defaultdict[int, set[int]] = defaultdict(set)
        for snapshot_id, stock_id in member_rows:
            members[int(snapshot_id)].add(int(stock_id))
        return tuple(
            UniversePoint(
                snapshot_id=item.id,
                as_of_date=item.as_of_date,
                available_at=normalize_utc(item.available_time),
                asset_ids=frozenset(members[item.id]),
                source=f"{item.source}:{item.provider}",
            )
            for item in snapshots
        )

    def asset_ids_for_snapshot(self, snapshot_id: int, *, market: str) -> tuple[int, ...]:
        """Resolve the immutable historical universe; callers cannot supply survivors."""
        ids = tuple(
            self.session.scalars(
                select(MarketUniverseMember.stock_id)
                .join(Stock, Stock.id == MarketUniverseMember.stock_id)
                .where(
                    MarketUniverseMember.snapshot_id == snapshot_id,
                    Stock.market == market,
                )
                .order_by(MarketUniverseMember.stock_id)
            )
        )
        if not ids:
            raise ValueError("historical universe snapshot is empty or does not match market")
        return ids

    def save(
        self,
        result: BacktestResult,
        config: BacktestConfig,
    ) -> BacktestRun:
        run = BacktestRun(
            strategy_name=result.strategy_name,
            market=result.market,
            start_date=result.start_date,
            end_date=result.end_date,
            rebalance_frequency=config.rebalance_frequency,
            status="completed",
            initial_capital=_decimal(config.initial_capital),
            data_fingerprint=result.data_fingerprint,
            parameters={
                **asdict(config),
                "start_date": config.start_date.isoformat(),
                "end_date": config.end_date.isoformat(),
                "execution_policy": "signal_close_execute_next_session_open",
                "weight_policy": "long_only_no_leverage",
                "strategy": result.strategy_parameters,
            },
            validation_issues=[
                {
                    **asdict(item),
                    "trade_date": (
                        item.trade_date.isoformat() if item.trade_date is not None else None
                    ),
                }
                for item in result.validation_issues
            ],
        )
        self.session.add(run)
        self.session.flush()
        self.session.add_all(
            [
                BacktestDailyResult(
                    run_id=run.id,
                    trade_date=item.trade_date,
                    nav=_decimal(item.nav),
                    daily_return=_decimal(item.daily_return),
                    drawdown=_decimal(item.drawdown),
                    gross_exposure=_decimal(item.gross_exposure),
                    cash=_decimal(item.cash),
                )
                for item in result.points
            ]
        )
        self.session.add_all(
            [
                BacktestRebalance(
                    run_id=run.id,
                    signal_date=item.signal_date,
                    execution_date=item.execution_date,
                    status=item.status,
                    turnover=_decimal(item.turnover),
                    transaction_cost=_decimal(item.transaction_cost),
                    nav_before=_decimal(item.nav_before),
                    nav_after=_decimal(item.nav_after),
                    target_weights={
                        str(asset_id): weight for asset_id, weight in item.target_weights.items()
                    },
                    rationale=list(item.rationale),
                    rejection_reason=item.rejection_reason,
                )
                for item in result.rebalances
            ]
        )
        metrics = result.metrics
        self.session.add(
            BacktestSummaryMetric(
                run_id=run.id,
                total_return=_decimal(metrics.total_return),
                annualized_return=_decimal(metrics.annualized_return),
                annualized_volatility=_decimal(metrics.annualized_volatility),
                sharpe_ratio=_optional_decimal(metrics.sharpe_ratio),
                sortino_ratio=_optional_decimal(metrics.sortino_ratio),
                maximum_drawdown=_decimal(metrics.maximum_drawdown),
                period_win_rate=_optional_decimal(metrics.period_win_rate),
                period_profit_loss_ratio=_optional_decimal(metrics.period_profit_loss_ratio),
                total_turnover=_decimal(metrics.total_turnover),
                average_turnover=_decimal(metrics.average_turnover),
                total_transaction_cost=_decimal(metrics.total_transaction_cost),
                annual_returns={str(year): value for year, value in metrics.annual_returns.items()},
            )
        )
        self.session.flush()
        return run


def _decimal(value: float) -> Decimal:
    return Decimal(str(round(value, 12)))


def _optional_decimal(value: float | None) -> Decimal | None:
    return _decimal(value) if value is not None else None
