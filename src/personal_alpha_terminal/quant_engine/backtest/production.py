from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from hashlib import sha256
from json import dumps
from math import isfinite, sqrt

from personal_alpha_terminal.backtest.schemas import BacktestBar, UniversePoint
from personal_alpha_terminal.core.market_time import market_close_utc
from personal_alpha_terminal.quant_engine.costs import TransactionCostModel


class CorporateActionType(StrEnum):
    SPLIT = "SPLIT"
    CASH_DIVIDEND = "CASH_DIVIDEND"
    MERGER_CASH = "MERGER_CASH"
    DELISTING = "DELISTING"
    SYMBOL_CHANGE = "SYMBOL_CHANGE"


@dataclass(frozen=True, slots=True)
class CorporateAction:
    asset_id: int
    action_type: CorporateActionType
    effective_date: date
    announcement_date: date | None
    available_at: datetime
    ratio: float | None = None
    cash_amount: float | None = None
    new_symbol: str | None = None
    source: str = ""

    def __post_init__(self) -> None:
        if self.asset_id <= 0 or self.available_at.tzinfo is None or not self.source.strip():
            raise ValueError("corporate action requires identity, timestamp and source")
        if self.announcement_date is not None and self.announcement_date > self.effective_date:
            raise ValueError("corporate action announcement cannot follow effective date")
        if self.available_at.date() > self.effective_date:
            raise ValueError("corporate action was not available by its effective date")
        if self.action_type is CorporateActionType.SPLIT and (
            self.ratio is None or not isfinite(self.ratio) or self.ratio <= 0
        ):
            raise ValueError("split requires a positive ratio")
        if self.action_type in {
            CorporateActionType.CASH_DIVIDEND,
            CorporateActionType.MERGER_CASH,
            CorporateActionType.DELISTING,
        } and (self.cash_amount is None or not isfinite(self.cash_amount) or self.cash_amount < 0):
            raise ValueError("cash corporate action requires a non-negative amount")
        if self.action_type is CorporateActionType.SYMBOL_CHANGE and not (
            self.new_symbol and self.new_symbol.strip()
        ):
            raise ValueError("symbol change requires a new symbol")


@dataclass(frozen=True, slots=True)
class BacktestTarget:
    signal_time: datetime
    earliest_execution_date: date
    weights: dict[int, float]
    universe_snapshot_id: int
    data_version: str
    model_version: str
    validation_status: str
    alpha_source_weights: dict[int, dict[str, float]]
    parameter_lock_fingerprint: str
    oos_validation_id: str

    def __post_init__(self) -> None:
        if self.signal_time.tzinfo is None:
            raise ValueError("backtest target signal_time must be timezone-aware")
        if self.earliest_execution_date <= self.signal_time.date():
            raise ValueError("target must execute after the signal date")
        if self.validation_status != "PRODUCTION_APPROVED":
            raise ValueError("backtest target must be production approved")
        if not self.data_version.strip() or not self.model_version.strip():
            raise ValueError("backtest target requires immutable versions")
        if not self.parameter_lock_fingerprint.strip() or not self.oos_validation_id.strip():
            raise ValueError("backtest target requires locked OOS validation lineage")
        if any(not isfinite(value) or value < 0 for value in self.weights.values()):
            raise ValueError("target weights must be finite and long-only")
        if sum(self.weights.values()) > 1 + 1e-9:
            raise ValueError("target gross exposure cannot exceed one")
        if set(self.alpha_source_weights) != set(self.weights):
            raise ValueError("every target weight requires alpha-source attribution")
        for asset_id, source_weights in self.alpha_source_weights.items():
            if not source_weights or any(
                not source.strip() or not isfinite(value) or value < 0
                for source, value in source_weights.items()
            ):
                raise ValueError(f"invalid alpha-source weights for asset {asset_id}")
            if abs(sum(source_weights.values()) - 1.0) > 1e-9:
                raise ValueError("alpha-source weights must sum to one per asset")


@dataclass(frozen=True, slots=True)
class ProductionBacktestDataset:
    bars: tuple[BacktestBar, ...]
    calendar: tuple[date, ...]
    calendar_source: str
    universe_timeline: tuple[UniversePoint, ...]
    corporate_actions: tuple[CorporateAction, ...]
    corporate_action_ledger_certified: bool
    universe_certified: bool
    data_version: str
    market: str = "US"
    execution_price_policy: str = "RAW_OHLC"
    return_policy: str = "PIT_CORPORATE_ACTION_LEDGER"


@dataclass(frozen=True, slots=True)
class ProductionBacktestConfig:
    initial_capital: float = 1_000_000.0
    benchmark_symbol: str = "SPY_TOTAL_RETURN"
    benchmark_returns: tuple[tuple[date, float], ...] = ()
    annual_risk_free_rate: float = 0.0
    maximum_stale_sessions: int = 3
    minimum_sessions: int = 20
    liquidity_lookback_sessions: int = 20
    minimum_liquidity_observations: int = 1
    model_version: str = "portfolio-backtest-v1"
    config_version: str = "production-safe-v1"
    git_commit: str = "UNKNOWN"
    random_seed: int = 0

    def __post_init__(self) -> None:
        if self.initial_capital <= 0 or self.minimum_sessions < 2:
            raise ValueError("backtest capital and minimum sessions are invalid")
        if self.maximum_stale_sessions < 0 or self.liquidity_lookback_sessions < 1:
            raise ValueError("backtest stale/liquidity windows are invalid")
        if not 1 <= self.minimum_liquidity_observations <= self.liquidity_lookback_sessions:
            raise ValueError("minimum liquidity observations must fit the lookback")
        if not all(
            item.strip()
            for item in (
                self.benchmark_symbol,
                self.model_version,
                self.config_version,
                self.git_commit,
            )
        ):
            raise ValueError("backtest version and benchmark lineage are required")


@dataclass(frozen=True, slots=True)
class ProductionTrade:
    signal_time: datetime
    execution_date: date
    asset_id: int
    symbol: str
    shares: float
    raw_price: float
    trade_value: float
    transaction_cost: float
    data_version: str
    model_version: str


@dataclass(frozen=True, slots=True)
class AccountingPoint:
    trade_date: date
    cash: float
    market_value: float
    equity: float
    daily_return: float
    gross_exposure: float
    drawdown: float


@dataclass(frozen=True, slots=True)
class ProductionBacktestMetrics:
    gross_return: float
    net_return: float
    cagr: float
    annualized_return: float
    annualized_volatility: float
    sharpe: float | None
    sortino: float | None
    calmar: float | None
    maximum_drawdown: float
    drawdown_duration: int
    turnover: float
    average_holding_period: float | None
    transaction_cost: float
    cost_drag: float
    alpha: float | None
    beta: float | None
    tracking_error: float | None
    information_ratio: float | None
    up_capture: float | None
    down_capture: float | None


@dataclass(frozen=True, slots=True)
class ProductionBacktestResult:
    status: str
    points: tuple[AccountingPoint, ...]
    trades: tuple[ProductionTrade, ...]
    metrics: ProductionBacktestMetrics
    realized_pnl: float
    unrealized_pnl: float
    dividends: float
    transaction_costs: float
    symbol_contribution: dict[str, float]
    sector_contribution: dict[str, float]
    alpha_source_contribution: dict[str, float]
    risk_contribution: dict[str, float]
    limitations: tuple[str, ...]
    run_manifest_hash: str
    result_hash: str


class ProductionBacktestEngine:
    """Raw-price, next-session event-driven accounting engine."""

    def __init__(self, cost_model: TransactionCostModel | None = None) -> None:
        self.cost_model = cost_model or TransactionCostModel()

    def run(
        self,
        dataset: ProductionBacktestDataset,
        targets: tuple[BacktestTarget, ...],
        config: ProductionBacktestConfig,
        *,
        sectors: dict[int, str],
    ) -> ProductionBacktestResult:
        limitations = _validate_dataset(dataset, config)
        _validate_targets(dataset, targets)
        bars = {(item.trade_date, item.asset_id): item for item in dataset.bars}
        symbols = {item.asset_id: item.symbol for item in dataset.bars}
        target_by_date = {item.earliest_execution_date: item for item in targets}
        if len(target_by_date) != len(targets):
            raise ValueError("only one immutable target is allowed per execution session")
        actions_by_date: dict[date, list[CorporateAction]] = {}
        for action in dataset.corporate_actions:
            actions_by_date.setdefault(action.effective_date, []).append(action)
        universe_by_id = {item.snapshot_id: item for item in dataset.universe_timeline}
        cash = config.initial_capital
        shares: dict[int, float] = {}
        average_cost: dict[int, float] = {}
        latest_close: dict[int, float] = {}
        stale: dict[int, int] = {}
        realized = 0.0
        dividends = 0.0
        total_cost = 0.0
        total_turnover_dollars = 0.0
        points: list[AccountingPoint] = []
        trades: list[ProductionTrade] = []
        peak = config.initial_capital
        previous_equity = config.initial_capital
        holding_sessions: dict[int, int] = {}
        completed_holding_periods: list[int] = []
        symbol_contribution: dict[str, float] = {}
        sector_contribution: dict[str, float] = {}
        alpha_source_contribution: dict[str, float] = {}
        prior_weights: dict[int, float] = {}
        active_alpha_sources: dict[int, dict[str, float]] = {}
        dollar_volume_history: dict[int, list[float]] = {}

        for current_date in dataset.calendar:
            prior_close = dict(latest_close)
            for asset_id in list(shares):
                holding_sessions[asset_id] = holding_sessions.get(asset_id, 0) + 1
            for action in actions_by_date.get(current_date, []):
                if action.action_type is CorporateActionType.SYMBOL_CHANGE:
                    assert action.new_symbol is not None
                    symbols[action.asset_id] = action.new_symbol
                cash_before_action = cash
                cash, realized, dividends = _apply_corporate_action(
                    action,
                    shares=shares,
                    average_cost=average_cost,
                    cash=cash,
                    realized=realized,
                    dividends=dividends,
                    holding_sessions=holding_sessions,
                    completed_holding_periods=completed_holding_periods,
                )
                action_income = cash - cash_before_action
                if (
                    action.action_type is CorporateActionType.CASH_DIVIDEND
                    and action_income > 0
                    and previous_equity > 0
                ):
                    contribution = action_income / previous_equity
                    symbol = symbols[action.asset_id]
                    symbol_contribution[symbol] = (
                        symbol_contribution.get(symbol, 0.0) + contribution
                    )
                    sector = sectors.get(action.asset_id, "UNCLASSIFIED")
                    sector_contribution[sector] = (
                        sector_contribution.get(sector, 0.0) + contribution
                    )
            target = target_by_date.get(current_date)
            if target is not None:
                universe = universe_by_id.get(target.universe_snapshot_id)
                if (
                    universe is None
                    or universe.as_of_date > target.signal_time.date()
                    or target.signal_time < universe.available_at
                ):
                    raise ValueError("target references an unavailable PIT universe")
                if set(target.weights) - set(universe.asset_ids):
                    raise ValueError("target contains assets outside its PIT universe")
                (
                    cash,
                    trade_cost,
                    turnover_dollars,
                    generated,
                    realized_delta,
                ) = self._rebalance(
                    current_date=current_date,
                    target=target,
                    bars=bars,
                    shares=shares,
                    average_cost=average_cost,
                    cash=cash,
                    holding_sessions=holding_sessions,
                    completed_holding_periods=completed_holding_periods,
                    dollar_volume_history=dollar_volume_history,
                    config=config,
                )
                total_cost += trade_cost
                total_turnover_dollars += turnover_dollars
                realized += realized_delta
                trades.extend(generated)
                active_alpha_sources = {
                    asset_id: dict(source_weights)
                    for asset_id, source_weights in target.alpha_source_weights.items()
                    if target.weights.get(asset_id, 0.0) > 0
                }
            current_values: dict[int, float] = {}
            for asset_id, units in shares.items():
                bar = bars.get((current_date, asset_id))
                if bar is not None:
                    latest_close[asset_id] = bar.close
                    stale[asset_id] = 0
                else:
                    stale[asset_id] = stale.get(asset_id, 0) + 1
                    if stale[asset_id] > config.maximum_stale_sessions:
                        raise ValueError("held asset exceeded the stale-price limit")
                if asset_id not in latest_close:
                    raise ValueError("held asset lacks a raw valuation price")
                current_values[asset_id] = units * latest_close[asset_id]
            market_value = sum(current_values.values())
            equity = cash + market_value
            if not isfinite(equity) or equity <= 0:
                raise ValueError("backtest equity is invalid")
            if abs(equity - (cash + sum(current_values.values()))) > 1e-8:
                raise ArithmeticError("ending equity accounting invariant failed")
            daily_return = equity / previous_equity - 1
            for asset_id, prior_weight in prior_weights.items():
                prior_asset_close = prior_close.get(asset_id)
                bar = bars.get((current_date, asset_id))
                if bar is None or prior_asset_close is None or prior_asset_close <= 0:
                    continue
                contribution = prior_weight * (bar.close / prior_asset_close - 1)
                symbol = symbols[asset_id]
                symbol_contribution[symbol] = symbol_contribution.get(symbol, 0.0) + contribution
                sector = sectors.get(asset_id, "UNCLASSIFIED")
                sector_contribution[sector] = sector_contribution.get(sector, 0.0) + contribution
                for source, source_weight in active_alpha_sources.get(asset_id, {}).items():
                    alpha_source_contribution[source] = (
                        alpha_source_contribution.get(source, 0.0)
                        + contribution * source_weight
                    )
            peak = max(peak, equity)
            points.append(
                AccountingPoint(
                    current_date,
                    cash,
                    market_value,
                    equity,
                    daily_return,
                    market_value / equity,
                    equity / peak - 1,
                )
            )
            prior_weights = {
                asset_id: value / equity for asset_id, value in current_values.items()
            }
            for (bar_date, asset_id), bar in bars.items():
                if bar_date == current_date and bar.volume is not None and bar.volume > 0:
                    dollar_volume_history.setdefault(asset_id, []).append(
                        float(bar.volume) * bar.close
                    )
            previous_equity = equity

        ending_market_value = sum(
            units * latest_close[asset_id] for asset_id, units in shares.items()
        )
        unrealized = sum(
            units * (latest_close[asset_id] - average_cost[asset_id])
            for asset_id, units in shares.items()
        )
        ending_equity = cash + ending_market_value
        accounting_equity = config.initial_capital + realized + unrealized + dividends - total_cost
        if abs(ending_equity - accounting_equity) > max(1e-6, ending_equity * 1e-10):
            raise ArithmeticError("PnL accounting invariant failed")
        metrics = _calculate_metrics(
            tuple(points),
            initial_capital=config.initial_capital,
            total_cost=total_cost,
            total_turnover_dollars=total_turnover_dollars,
            holding_periods=tuple(
                [*completed_holding_periods, *holding_sessions.values()]
            ),
            benchmark_returns=config.benchmark_returns,
            annual_risk_free_rate=config.annual_risk_free_rate,
        )
        risk_contribution = _realized_risk_contribution(prior_weights, symbols)
        result_payload = {
            "equity": ending_equity,
            "accounting": {
                "cash": cash,
                "market_value": ending_market_value,
                "realized_pnl": realized,
                "unrealized_pnl": unrealized,
                "dividends": dividends,
                "transaction_costs": total_cost,
            },
            "daily_equity": [
                (item.trade_date.isoformat(), item.equity, item.daily_return)
                for item in points
            ],
            "trades": [
                (
                    item.execution_date.isoformat(),
                    item.asset_id,
                    item.shares,
                    item.raw_price,
                    item.transaction_cost,
                )
                for item in trades
            ],
            "symbol_contribution": symbol_contribution,
            "sector_contribution": sector_contribution,
            "alpha_source_contribution": alpha_source_contribution,
            "data_version": dataset.data_version,
            "model_version": config.model_version,
        }
        result_hash = sha256(dumps(result_payload, sort_keys=True).encode()).hexdigest()
        manifest_payload = {
            "data_version": dataset.data_version,
            "model_version": config.model_version,
            "config_version": config.config_version,
            "git_commit": config.git_commit,
            "random_seed": config.random_seed,
            "start": dataset.calendar[0].isoformat(),
            "end": dataset.calendar[-1].isoformat(),
            "universe": [item.snapshot_id for item in dataset.universe_timeline],
            "target_validations": [
                (
                    item.model_version,
                    item.parameter_lock_fingerprint,
                    item.oos_validation_id,
                )
                for item in targets
            ],
            "cost_model": self.cost_model.config.version,
            "benchmark": config.benchmark_symbol,
            "execution_price_policy": dataset.execution_price_policy,
            "return_policy": dataset.return_policy,
            "result_hash": result_hash,
        }
        manifest_hash = sha256(dumps(manifest_payload, sort_keys=True).encode()).hexdigest()
        return ProductionBacktestResult(
            status=("PRODUCTION_APPROVED" if not limitations else "RESEARCH_ONLY"),
            points=tuple(points),
            trades=tuple(trades),
            metrics=metrics,
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            dividends=dividends,
            transaction_costs=total_cost,
            symbol_contribution=symbol_contribution,
            sector_contribution=sector_contribution,
            alpha_source_contribution=alpha_source_contribution,
            risk_contribution=risk_contribution,
            limitations=limitations,
            run_manifest_hash=manifest_hash,
            result_hash=result_hash,
        )

    def _rebalance(
        self,
        *,
        current_date: date,
        target: BacktestTarget,
        bars: dict[tuple[date, int], BacktestBar],
        shares: dict[int, float],
        average_cost: dict[int, float],
        cash: float,
        holding_sessions: dict[int, int],
        completed_holding_periods: list[int],
        dollar_volume_history: dict[int, list[float]],
        config: ProductionBacktestConfig,
    ) -> tuple[float, float, float, tuple[ProductionTrade, ...], float]:
        prices: dict[int, float] = {}
        adv: dict[int, float] = {}
        changed = set(shares) | set(target.weights)
        for asset_id in changed:
            bar = bars.get((current_date, asset_id))
            if bar is None or bar.open_tradable is not True or bar.open <= 0:
                raise ValueError("target asset is not tradable at the next session open")
            prices[asset_id] = bar.open
            observations = dollar_volume_history.get(asset_id, [])
            observations = observations[-config.liquidity_lookback_sessions :]
            if len(observations) < config.minimum_liquidity_observations:
                raise ValueError("known prior-session ADV is required")
            adv[asset_id] = sum(observations) / len(observations)
        current_values = {asset_id: units * prices[asset_id] for asset_id, units in shares.items()}
        nav_before = cash + sum(current_values.values())
        nav_after = nav_before
        estimates: dict[int, float] = {}
        for _ in range(100):
            target_values = {
                asset_id: nav_after * weight for asset_id, weight in target.weights.items()
            }
            estimates = {
                asset_id: self.cost_model.estimate(
                    trade_value=abs(
                        target_values.get(asset_id, 0.0) - current_values.get(asset_id, 0.0)
                    ),
                    average_daily_dollar_volume=adv[asset_id],
                ).total_cost
                for asset_id in changed
            }
            updated = nav_before - sum(estimates.values())
            if abs(updated - nav_after) < 1e-10:
                nav_after = updated
                break
            nav_after = updated
        else:
            raise ArithmeticError("production transaction-cost solver did not converge")
        target_values = {
            asset_id: nav_after * weight for asset_id, weight in target.weights.items()
        }
        generated: list[ProductionTrade] = []
        realized_delta = 0.0
        for asset_id in sorted(changed, key=lambda item: target_values.get(item, 0.0)):
            desired_shares = target_values.get(asset_id, 0.0) / prices[asset_id]
            delta_shares = desired_shares - shares.get(asset_id, 0.0)
            if abs(delta_shares) <= 1e-12:
                continue
            trade_value = abs(delta_shares) * prices[asset_id]
            cost = estimates[asset_id]
            prior_shares = shares.get(asset_id, 0.0)
            prior_cost = average_cost.get(asset_id, 0.0)
            if delta_shares < 0:
                sold = -delta_shares
                realized_delta += sold * (prices[asset_id] - prior_cost)
                if desired_shares <= 1e-12:
                    completed_holding_periods.append(holding_sessions.pop(asset_id, 0))
                    average_cost.pop(asset_id, None)
                    shares.pop(asset_id, None)
                else:
                    shares[asset_id] = desired_shares
            else:
                total_cost_basis = prior_shares * prior_cost + delta_shares * prices[asset_id]
                shares[asset_id] = desired_shares
                average_cost[asset_id] = total_cost_basis / desired_shares
                holding_sessions.setdefault(asset_id, 0)
            cash -= delta_shares * prices[asset_id] + cost
            generated.append(
                ProductionTrade(
                    target.signal_time,
                    current_date,
                    asset_id,
                    bars[(current_date, asset_id)].symbol,
                    delta_shares,
                    prices[asset_id],
                    trade_value,
                    cost,
                    target.data_version,
                    target.model_version,
                )
            )
        expected_cash = nav_after - sum(target_values.values())
        if abs(cash - expected_cash) > max(1e-7, nav_after * 1e-10):
            raise ArithmeticError("post-trade cash accounting invariant failed")
        turnover = sum(
            abs(target_values.get(item, 0.0) - current_values.get(item, 0.0))
            for item in changed
        )
        return cash, sum(estimates.values()), turnover, tuple(generated), realized_delta


def _validate_dataset(
    dataset: ProductionBacktestDataset, config: ProductionBacktestConfig
) -> tuple[str, ...]:
    if len(dataset.calendar) < config.minimum_sessions:
        raise ValueError("production backtest has insufficient verified sessions")
    if tuple(sorted(set(dataset.calendar))) != dataset.calendar:
        raise ValueError("trading calendar must be sorted and unique")
    if not dataset.calendar_source.strip() or not dataset.data_version.strip():
        raise ValueError("calendar and data version lineage are required")
    if dataset.market != "US":
        raise ValueError("production backtest currently supports the US market only")
    if dataset.execution_price_policy != "RAW_OHLC":
        raise ValueError("execution must use raw, unadjusted OHLC prices")
    if dataset.return_policy != "PIT_CORPORATE_ACTION_LEDGER":
        raise ValueError("returns must use the PIT corporate-action ledger")
    if any(item.weekday() >= 5 for item in dataset.calendar):
        raise ValueError("verified US calendar contains weekend sessions")
    try:
        import exchange_calendars as xcals  # type: ignore[import-untyped]
    except ImportError as error:
        raise ValueError("exchange_calendars is required to verify US sessions") from error
    exchange = xcals.get_calendar("XNYS")
    verified_sessions = {
        item.date()
        for item in exchange.sessions_in_range(dataset.calendar[0], dataset.calendar[-1])
    }
    invalid_sessions = set(dataset.calendar) - verified_sessions
    if invalid_sessions:
        raise ValueError(
            "verified US calendar contains non-exchange sessions: "
            + ", ".join(item.isoformat() for item in sorted(invalid_sessions))
        )
    if not dataset.corporate_action_ledger_certified:
        raise ValueError("PIT corporate-action ledger is not certified")
    limitations: list[str] = []
    if not dataset.universe_certified:
        limitations.append("SURVIVORSHIP_BIAS_RISK")
    if not dataset.universe_timeline:
        raise ValueError("PIT universe timeline is required")
    if config.git_commit == "UNKNOWN":
        limitations.append("CODE_VERSION_UNKNOWN")
    benchmark_dates = {item[0] for item in config.benchmark_returns}
    expected_benchmark_dates = set(dataset.calendar[1:])
    if not expected_benchmark_dates.issubset(benchmark_dates):
        limitations.append("BENCHMARK_TOTAL_RETURN_COVERAGE_INCOMPLETE")
    calendar = set(dataset.calendar)
    seen: set[tuple[date, int]] = set()
    providers: dict[int, set[tuple[str, str | None]]] = {}
    for bar in dataset.bars:
        key = (bar.trade_date, bar.asset_id)
        if key in seen:
            raise ValueError("duplicate production backtest bar")
        seen.add(key)
        if bar.trade_date not in calendar:
            raise ValueError("bar is outside the verified trading calendar")
        if bar.event_time is None or bar.available_time is None or bar.ingested_time is None:
            raise ValueError("backtest bar lacks three-time lineage")
        if not all(
            isfinite(value) and value > 0
            for value in (bar.open, bar.high, bar.low, bar.close)
        ):
            raise ValueError("backtest bar has invalid raw prices")
        if bar.market != dataset.market:
            raise ValueError("backtest bar market does not match dataset market")
        if bar.event_time != market_close_utc(bar.trade_date, dataset.market):
            raise ValueError("bar event_time does not match the US market close")
        if not (bar.event_time <= bar.available_time <= bar.ingested_time):
            raise ValueError("backtest bar violates event/available/ingested ordering")
        if not bar.source.strip() or not (bar.provider and bar.provider.strip()):
            raise ValueError("backtest bar lacks source/provider lineage")
        providers.setdefault(bar.asset_id, set()).add((bar.source, bar.provider))
    stitched = {
        asset_id: values for asset_id, values in providers.items() if len(values) != 1
    }
    if stitched:
        raise ValueError(f"provider stitching is forbidden in one immutable run: {stitched}")
    return tuple(limitations)


def _validate_targets(
    dataset: ProductionBacktestDataset, targets: tuple[BacktestTarget, ...]
) -> None:
    calendar_index = {session: index for index, session in enumerate(dataset.calendar)}
    for target in targets:
        signal_date = target.signal_time.date()
        signal_index = calendar_index.get(signal_date)
        if signal_index is None:
            raise ValueError("target signal date is not a verified trading session")
        if target.signal_time < market_close_utc(signal_date, dataset.market):
            raise ValueError("target signal was generated before the signal-session close")
        if target.data_version != dataset.data_version:
            raise ValueError("target and backtest dataset versions do not match")
        if signal_index + 1 >= len(dataset.calendar):
            raise ValueError("target has no next verified execution session")
        if target.earliest_execution_date != dataset.calendar[signal_index + 1]:
            raise ValueError("target must execute on the next verified trading session")


def _apply_corporate_action(
    action: CorporateAction,
    *,
    shares: dict[int, float],
    average_cost: dict[int, float],
    cash: float,
    realized: float,
    dividends: float,
    holding_sessions: dict[int, int],
    completed_holding_periods: list[int],
) -> tuple[float, float, float]:
    units = shares.get(action.asset_id, 0.0)
    if units <= 0:
        return cash, realized, dividends
    if action.action_type is CorporateActionType.SPLIT:
        assert action.ratio is not None
        shares[action.asset_id] = units * action.ratio
        average_cost[action.asset_id] /= action.ratio
    elif action.action_type is CorporateActionType.CASH_DIVIDEND:
        assert action.cash_amount is not None
        payment = units * action.cash_amount
        cash += payment
        dividends += payment
    elif action.action_type in {CorporateActionType.MERGER_CASH, CorporateActionType.DELISTING}:
        assert action.cash_amount is not None
        proceeds = units * action.cash_amount
        cash += proceeds
        realized += proceeds - units * average_cost[action.asset_id]
        shares.pop(action.asset_id, None)
        average_cost.pop(action.asset_id, None)
        completed_holding_periods.append(holding_sessions.pop(action.asset_id, 0))
    return cash, realized, dividends


def _calculate_metrics(
    points: tuple[AccountingPoint, ...],
    *,
    initial_capital: float,
    total_cost: float,
    total_turnover_dollars: float,
    holding_periods: tuple[int, ...],
    benchmark_returns: tuple[tuple[date, float], ...],
    annual_risk_free_rate: float,
) -> ProductionBacktestMetrics:
    returns = [item.daily_return for item in points[1:]]
    net_return = points[-1].equity / initial_capital - 1
    gross_return = (points[-1].equity + total_cost) / initial_capital - 1
    years = max(len(returns) / 252, 1 / 252)
    cagr = (1 + net_return) ** (1 / years) - 1 if net_return > -1 else -1.0
    mean = sum(returns) / len(returns) if returns else 0.0
    std = _sample_std(returns)
    annualized_volatility = std * sqrt(252)
    daily_rf = (1 + annual_risk_free_rate) ** (1 / 252) - 1
    sharpe = (mean - daily_rf) / std * sqrt(252) if std > 0 else None
    downside = (
        sqrt(sum(min(0.0, item - daily_rf) ** 2 for item in returns) / len(returns))
        if returns
        else 0.0
    )
    sortino = (mean - daily_rf) / downside * sqrt(252) if downside > 0 else None
    maximum_drawdown = min(item.drawdown for item in points)
    duration = _maximum_drawdown_duration(points)
    beta, alpha, tracking, information, up_capture, down_capture = _benchmark_metrics(
        points, benchmark_returns, annual_risk_free_rate
    )
    return ProductionBacktestMetrics(
        gross_return,
        net_return,
        cagr,
        cagr,
        annualized_volatility,
        sharpe,
        sortino,
        cagr / abs(maximum_drawdown) if maximum_drawdown < 0 else None,
        maximum_drawdown,
        duration,
        total_turnover_dollars / initial_capital,
        sum(holding_periods) / len(holding_periods) if holding_periods else None,
        total_cost,
        total_cost / initial_capital,
        alpha,
        beta,
        tracking,
        information,
        up_capture,
        down_capture,
    )


def _benchmark_metrics(
    points: tuple[AccountingPoint, ...],
    benchmark_returns: tuple[tuple[date, float], ...],
    annual_risk_free_rate: float,
) -> tuple[float | None, float | None, float | None, float | None, float | None, float | None]:
    benchmark = dict(benchmark_returns)
    aligned = [
        (item.daily_return, benchmark[item.trade_date])
        for item in points[1:]
        if item.trade_date in benchmark
    ]
    if len(aligned) < 2:
        return None, None, None, None, None, None
    strategy = [item[0] for item in aligned]
    market = [item[1] for item in aligned]
    market_variance = _sample_std(market) ** 2
    covariance = _sample_covariance(strategy, market)
    beta = covariance / market_variance if market_variance > 0 else None
    daily_rf = (1 + annual_risk_free_rate) ** (1 / 252) - 1
    alpha = (
        (
            (sum(strategy) / len(strategy) - daily_rf)
            - beta * (sum(market) / len(market) - daily_rf)
        )
        * 252
        if beta is not None
        else None
    )
    active = [left - right for left, right in aligned]
    tracking = _sample_std(active) * sqrt(252)
    information = (sum(active) / len(active) * 252 / tracking) if tracking > 0 else None
    up_market = [index for index, value in enumerate(market) if value > 0]
    down_market = [index for index, value in enumerate(market) if value < 0]
    up_capture = _capture(strategy, market, up_market)
    down_capture = _capture(strategy, market, down_market)
    return beta, alpha, tracking, information, up_capture, down_capture


def _capture(strategy: list[float], market: list[float], indexes: list[int]) -> float | None:
    if not indexes:
        return None
    market_mean = sum(market[index] for index in indexes) / len(indexes)
    if abs(market_mean) < 1e-15:
        return None
    return (sum(strategy[index] for index in indexes) / len(indexes)) / market_mean


def _maximum_drawdown_duration(points: tuple[AccountingPoint, ...]) -> int:
    longest = 0
    current = 0
    for item in points:
        if item.drawdown < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _sample_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sqrt(sum((item - mean) ** 2 for item in values) / (len(values) - 1))


def _sample_covariance(left: list[float], right: list[float]) -> float:
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    return sum(
        (first - left_mean) * (second - right_mean)
        for first, second in zip(left, right, strict=True)
    ) / (len(left) - 1)


def _realized_risk_contribution(
    weights: dict[int, float], symbols: dict[int, str]
) -> dict[str, float]:
    if not weights:
        return {}
    total = sum(value * value for value in weights.values())
    if total <= 0:
        return {symbols[item]: 0.0 for item in weights}
    return {symbols[item]: value * value / total for item, value in weights.items()}
