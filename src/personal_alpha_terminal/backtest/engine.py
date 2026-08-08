from collections import defaultdict
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta
from hashlib import sha256
from json import dumps
from math import isfinite

from personal_alpha_terminal.backtest.metrics import calculate_metrics
from personal_alpha_terminal.backtest.schemas import (
    BacktestBar,
    BacktestConfig,
    BacktestDataset,
    BacktestResult,
    DailyPortfolioPoint,
    HoldingPeriodResult,
    RebalanceRecord,
    StrategyContext,
    TargetAllocation,
    UniversePoint,
    ValidationIssue,
)
from personal_alpha_terminal.backtest.strategy import BacktestStrategy
from personal_alpha_terminal.core.data_timestamps import DataTimestamps
from personal_alpha_terminal.core.market_time import market_close_utc, normalize_utc


class BacktestEngine:
    """Long-only daily-bar engine with next-session-open execution."""

    def run(
        self,
        dataset: BacktestDataset,
        strategy: BacktestStrategy,
        config: BacktestConfig,
    ) -> BacktestResult:
        calendar, bars_by_date, issues, price_fingerprint = self._validate_dataset(
            dataset,
            config,
        )
        strategy_parameters = strategy.audit_payload()
        fingerprint = _run_fingerprint(
            price_fingerprint,
            strategy_parameters,
            config,
        )
        signal_dates = _signal_dates(calendar, config.rebalance_frequency)
        decision_cutoffs = {
            item: market_close_utc(item, dataset.market)
            + timedelta(minutes=config.decision_delay_minutes)
            for item in calendar
        }
        universe_timeline = _validate_universe_timeline(dataset.universe_timeline)
        pending: dict[date, tuple[date, TargetAllocation]] = {}
        positions: dict[int, float] = {}
        cash = config.initial_capital
        latest_close: dict[int, float] = {}
        stale_sessions: defaultdict[int, int] = defaultdict(int)
        history: defaultdict[int, list[BacktestBar]] = defaultdict(list)
        points: list[DailyPortfolioPoint] = []
        rebalances: list[RebalanceRecord] = []
        previous_nav = config.initial_capital
        peak_nav = config.initial_capital

        for index, current_date in enumerate(calendar):
            today = bars_by_date.get(current_date, {})
            signal_cutoff = decision_cutoffs[current_date]
            open_values = self._mark_open(
                positions,
                today,
                latest_close,
                stale_sessions,
                config.maximum_stale_sessions,
                current_date,
            )
            order = pending.pop(current_date, None)
            if order is not None:
                signal_date, allocation = order
                (
                    positions,
                    cash,
                    rebalance,
                ) = self._execute_rebalance(
                    signal_date=signal_date,
                    execution_date=current_date,
                    allocation=allocation,
                    positions=positions,
                    cash=cash,
                    current_values=open_values,
                    bars=today,
                    prior_history=history,
                    config=config,
                )
                rebalances.append(rebalance)
                if rebalance.status == "rejected":
                    issues.append(
                        ValidationIssue(
                            severity="warning",
                            code="REBALANCE_REJECTED",
                            message=rebalance.rejection_reason or "rebalance rejected",
                            trade_date=current_date,
                        )
                    )

            for asset_id, bar in today.items():
                latest_close[asset_id] = _adjusted_close(bar)
                stale_sessions[asset_id] = 0
                if (
                    bar.available_time is not None
                    and normalize_utc(bar.available_time) <= signal_cutoff
                ):
                    history[asset_id].append(bar)
            close_values = {
                asset_id: units * latest_close[asset_id] for asset_id, units in positions.items()
            }
            nav = cash + sum(close_values.values())
            if nav <= 0 or not isfinite(nav):
                raise ValueError(f"portfolio NAV is invalid on {current_date.isoformat()}")
            daily_return = nav / previous_nav - 1
            peak_nav = max(peak_nav, nav)
            drawdown = nav / peak_nav - 1
            gross_exposure = sum(close_values.values()) / nav
            points.append(
                DailyPortfolioPoint(
                    trade_date=current_date,
                    nav=nav,
                    daily_return=daily_return,
                    drawdown=drawdown,
                    gross_exposure=gross_exposure,
                    cash=cash,
                )
            )
            previous_nav = nav

            if current_date in signal_dates and index + 1 < len(calendar):
                universe = _universe_at(
                    universe_timeline,
                    signal_date=current_date,
                    signal_cutoff=signal_cutoff,
                )
                if config.require_pit_universe and universe is None:
                    raise ValueError(
                        "point-in-time universe is required but no snapshot was available "
                        f"for {current_date.isoformat()}"
                    )
                eligible_asset_ids = (
                    universe.asset_ids if universe is not None else frozenset(history)
                )
                current_weights = {
                    asset_id: value / nav for asset_id, value in close_values.items()
                }
                context = StrategyContext(
                    signal_date=current_date,
                    signal_cutoff=signal_cutoff,
                    calendar=calendar,
                    decision_cutoffs=decision_cutoffs,
                    history={
                        asset_id: tuple(items)
                        for asset_id, items in history.items()
                        if asset_id in eligible_asset_ids
                    },
                    current_weights=current_weights,
                    eligible_asset_ids=eligible_asset_ids,
                    universe_snapshot_id=(universe.snapshot_id if universe is not None else None),
                )
                proposed = strategy.generate_targets(context)
                if proposed is not None:
                    validated = _validate_allocation(
                        proposed,
                        eligible_asset_ids=eligible_asset_ids,
                    )
                    pending[calendar[index + 1]] = (current_date, validated)

        point_tuple = tuple(points)
        rebalance_tuple = tuple(rebalances)
        holding_periods = _holding_periods(point_tuple, rebalance_tuple)
        metrics = calculate_metrics(
            point_tuple,
            rebalance_tuple,
            holding_periods,
            initial_capital=config.initial_capital,
            annual_risk_free_rate=config.annual_risk_free_rate,
        )
        return BacktestResult(
            run_id=None,
            strategy_name=strategy.name,
            strategy_parameters=strategy_parameters,
            market=dataset.market,
            start_date=calendar[0],
            end_date=calendar[-1],
            data_fingerprint=fingerprint,
            points=point_tuple,
            rebalances=rebalance_tuple,
            holding_periods=holding_periods,
            metrics=metrics,
            validation_issues=tuple(issues),
        )

    @staticmethod
    def with_run_id(result: BacktestResult, run_id: int) -> BacktestResult:
        return replace(result, run_id=run_id)

    def _validate_dataset(
        self,
        dataset: BacktestDataset,
        config: BacktestConfig,
    ) -> tuple[
        tuple[date, ...],
        dict[date, dict[int, BacktestBar]],
        list[ValidationIssue],
        str,
    ]:
        if dataset.market not in {"A", "HK", "US"}:
            raise ValueError("dataset market must be A, HK, or US")
        if not dataset.data_sources:
            raise ValueError("backtest dataset requires explicit data sources")
        selected = [
            item for item in dataset.bars if config.start_date <= item.trade_date <= config.end_date
        ]
        if not selected:
            raise ValueError("no bars in requested backtest window")
        seen: set[tuple[int, date]] = set()
        sources: defaultdict[int, set[str]] = defaultdict(set)
        bars_by_date: defaultdict[date, dict[int, BacktestBar]] = defaultdict(dict)
        for bar in selected:
            key = (bar.asset_id, bar.trade_date)
            if key in seen:
                raise ValueError(
                    "duplicate asset/date bar: "
                    f"asset={bar.asset_id} date={bar.trade_date.isoformat()}"
                )
            seen.add(key)
            if bar.market != dataset.market:
                raise ValueError("all assets must belong to the dataset market")
            values = (bar.open, bar.high, bar.low, bar.close)
            if not all(isfinite(item) and item > 0 for item in values):
                raise ValueError(f"invalid OHLC for asset {bar.asset_id}")
            if (
                bar.low > min(bar.open, bar.close)
                or bar.high < max(bar.open, bar.close)
                or bar.high < bar.low
            ):
                raise ValueError(f"inconsistent OHLC for asset {bar.asset_id}")
            if bar.volume is not None and bar.volume < 0:
                raise ValueError(f"negative volume for asset {bar.asset_id}")
            if not bar.source.strip():
                raise ValueError(f"missing price source for asset {bar.asset_id}")
            if bar.event_time is None or bar.available_time is None or bar.ingested_time is None:
                raise ValueError(f"three-time data contract is missing for asset {bar.asset_id}")
            timestamps = DataTimestamps(
                event_time=bar.event_time,
                available_time=bar.available_time,
                ingested_time=bar.ingested_time,
            )
            expected_event = market_close_utc(bar.trade_date, bar.market)
            if timestamps.event_time != expected_event:
                raise ValueError(f"event_time does not match market close for asset {bar.asset_id}")
            if config.require_adjusted_prices and (
                bar.adjusted_close is None
                or not isfinite(bar.adjusted_close)
                or bar.adjusted_close <= 0
            ):
                raise ValueError(
                    f"adjusted close required for asset {bar.asset_id} "
                    f"on {bar.trade_date.isoformat()}"
                )
            if (
                config.require_adjusted_prices
                and bar.adjustment_method != "point_in_time_total_return"
            ):
                raise ValueError(
                    "backtest adjusted prices must be point-in-time total-return "
                    f"series; asset {bar.asset_id} on {bar.trade_date.isoformat()} "
                    f"has method {bar.adjustment_method!r}"
                )
            if not isfinite(bar.adjustment_ratio) or bar.adjustment_ratio <= 0:
                raise ValueError(f"invalid adjustment ratio for asset {bar.asset_id}")
            sources[bar.asset_id].add(bar.source)
            bars_by_date[bar.trade_date][bar.asset_id] = bar
        stitched = {asset_id: values for asset_id, values in sources.items() if len(values) != 1}
        if stitched:
            raise ValueError(
                f"price-provider stitching is forbidden within one backtest: {stitched}"
            )
        issues: list[ValidationIssue] = []
        if dataset.calendar:
            if config.require_verified_calendar and not (
                dataset.calendar_source and dataset.calendar_source.strip()
            ):
                raise ValueError("verified trading calendar requires explicit source provenance")
            filtered_calendar = tuple(
                item for item in dataset.calendar if config.start_date <= item <= config.end_date
            )
            if filtered_calendar != tuple(sorted(filtered_calendar)):
                raise ValueError("supplied trading calendar must be strictly ordered")
            if len(filtered_calendar) != len(set(filtered_calendar)):
                raise ValueError("supplied trading calendar contains duplicate sessions")
            if any(item.weekday() >= 5 for item in filtered_calendar):
                raise ValueError("supplied cash-market calendar contains weekend sessions")
            calendar = filtered_calendar
            outside_calendar = sorted(set(bars_by_date) - set(calendar))
            if outside_calendar:
                raise ValueError("price bars fall outside the supplied trading calendar")
            empty_sessions = [item for item in calendar if item not in bars_by_date]
            if empty_sessions:
                raise ValueError("supplied trading calendar contains sessions with no asset bars")
        elif config.require_verified_calendar:
            raise ValueError(
                "a verified trading calendar is required; inferring sessions "
                "from price bars is forbidden"
            )
        else:
            calendar = tuple(sorted(bars_by_date))
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="INFERRED_TRADING_CALENDAR",
                    message=(
                        "calendar inferred from asset bars; holidays and whole-universe "
                        "suspensions cannot be independently verified"
                    ),
                )
            )
        if len(calendar) < config.minimum_sessions:
            raise ValueError(f"backtest requires at least {config.minimum_sessions} sessions")
        asset_dates: defaultdict[int, int] = defaultdict(int)
        for bar in selected:
            asset_dates[bar.asset_id] += 1
        for asset_id, count in asset_dates.items():
            coverage = count / len(calendar)
            if coverage < 0.95:
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        code="LOW_SESSION_COVERAGE",
                        message=f"session coverage is {coverage:.2%}",
                        asset_id=asset_id,
                    )
                )
        payload = [
            (
                item.asset_id,
                item.trade_date.isoformat(),
                item.open,
                item.high,
                item.low,
                item.close,
                item.adjusted_close,
                item.volume,
                item.source,
                item.provider,
                item.adjustment_method,
                item.event_time.isoformat() if item.event_time else None,
                item.available_time.isoformat() if item.available_time else None,
                item.ingested_time.isoformat() if item.ingested_time else None,
                item.open_tradable,
            )
            for item in sorted(selected, key=lambda value: (value.asset_id, value.trade_date))
        ]
        fingerprint = sha256(
            dumps(
                {
                    "bars": payload,
                    "calendar": [item.isoformat() for item in calendar],
                    "calendar_source": (
                        dataset.calendar_source if dataset.calendar else "inferred_from_bars"
                    ),
                    "universe_timeline": [
                        {
                            "snapshot_id": item.snapshot_id,
                            "as_of_date": item.as_of_date.isoformat(),
                            "available_at": normalize_utc(item.available_at).isoformat(),
                            "asset_ids": sorted(item.asset_ids),
                            "source": item.source,
                        }
                        for item in dataset.universe_timeline
                    ],
                },
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode()
        ).hexdigest()
        return calendar, dict(bars_by_date), issues, fingerprint

    @staticmethod
    def _mark_open(
        positions: dict[int, float],
        today: dict[int, BacktestBar],
        latest_close: dict[int, float],
        stale_sessions: defaultdict[int, int],
        maximum_stale_sessions: int,
        current_date: date,
    ) -> dict[int, float]:
        values: dict[int, float] = {}
        for asset_id, units in positions.items():
            bar = today.get(asset_id)
            if bar is not None:
                values[asset_id] = units * bar.adjusted_open
                continue
            stale_sessions[asset_id] += 1
            if asset_id not in latest_close:
                raise ValueError(f"held asset {asset_id} has no valuation price")
            if stale_sessions[asset_id] > maximum_stale_sessions:
                raise ValueError(
                    f"held asset {asset_id} exceeded stale-price limit on {current_date}"
                )
            values[asset_id] = units * latest_close[asset_id]
        return values

    @staticmethod
    def _execute_rebalance(
        *,
        signal_date: date,
        execution_date: date,
        allocation: TargetAllocation,
        positions: dict[int, float],
        cash: float,
        current_values: dict[int, float],
        bars: dict[int, BacktestBar],
        prior_history: dict[int, list[BacktestBar]],
        config: BacktestConfig,
    ) -> tuple[dict[int, float], float, RebalanceRecord]:
        nav_before = cash + sum(current_values.values())
        changed_ids = set(current_values) | set(allocation.weights)
        unavailable = [
            item
            for item in changed_ids
            if item not in bars
            and abs(allocation.weights.get(item, 0.0) - current_values.get(item, 0.0) / nav_before)
            > 1e-10
        ]
        if unavailable:
            reason = (
                "rebalance rejected because assets are not tradable at execution open: "
                + ",".join(str(item) for item in sorted(unavailable))
            )
            return (
                positions,
                cash,
                RebalanceRecord(
                    signal_date=signal_date,
                    execution_date=execution_date,
                    status="rejected",
                    turnover=0.0,
                    transaction_cost=0.0,
                    nav_before=nav_before,
                    nav_after=nav_before,
                    target_weights=allocation.weights,
                    rationale=allocation.rationale,
                    rejection_reason=reason,
                ),
            )
        if config.require_explicit_open_tradability:
            not_confirmed = [
                item
                for item in changed_ids
                if abs(
                    allocation.weights.get(item, 0.0) - current_values.get(item, 0.0) / nav_before
                )
                > 1e-10
                and bars[item].open_tradable is not True
            ]
            if not_confirmed:
                return _rejected_rebalance(
                    signal_date=signal_date,
                    execution_date=execution_date,
                    allocation=allocation,
                    positions=positions,
                    cash=cash,
                    nav_before=nav_before,
                    reason=(
                        "rebalance rejected because opening-auction tradability "
                        "is not explicitly confirmed: "
                        + ",".join(str(item) for item in sorted(not_confirmed))
                    ),
                )
        nav_after = _solve_post_cost_nav(
            nav_before,
            current_values,
            allocation.weights,
            config.total_cost_rate,
        )
        target_values = {
            asset_id: nav_after * weight
            for asset_id, weight in allocation.weights.items()
            if weight > 1e-14
        }
        turnover_dollars = sum(
            abs(target_values.get(item, 0.0) - current_values.get(item, 0.0))
            for item in changed_ids
        )
        liquidity_failures: list[str] = []
        for asset_id in changed_ids:
            trade_value = abs(target_values.get(asset_id, 0.0) - current_values.get(asset_id, 0.0))
            if trade_value <= max(1e-8, nav_before * 1e-12):
                continue
            observations = [
                float(item.volume) * item.close
                for item in prior_history.get(asset_id, [])[-config.liquidity_lookback_sessions :]
                if item.volume is not None and item.volume > 0
            ]
            if len(observations) < config.minimum_liquidity_observations:
                liquidity_failures.append(f"{asset_id}:insufficient_prior_volume")
                continue
            average_dollar_volume = sum(observations) / len(observations)
            capacity = average_dollar_volume * config.maximum_adv_participation
            if trade_value > capacity:
                liquidity_failures.append(
                    f"{asset_id}:trade={trade_value:.2f}>capacity={capacity:.2f}"
                )
        if liquidity_failures:
            return _rejected_rebalance(
                signal_date=signal_date,
                execution_date=execution_date,
                allocation=allocation,
                positions=positions,
                cash=cash,
                nav_before=nav_before,
                reason=(
                    "rebalance rejected by prior-session liquidity limits: "
                    + ";".join(liquidity_failures)
                ),
            )
        cost = nav_before - nav_after
        expected_cost = turnover_dollars * config.total_cost_rate
        if abs(cost - expected_cost) > max(1e-7, nav_before * 1e-12):
            raise ArithmeticError("transaction-cost solver did not reconcile")
        new_positions = {
            asset_id: value / bars[asset_id].adjusted_open
            for asset_id, value in target_values.items()
        }
        new_cash = nav_after * (1 - sum(allocation.weights.values()))
        return (
            new_positions,
            new_cash,
            RebalanceRecord(
                signal_date=signal_date,
                execution_date=execution_date,
                status="executed",
                turnover=turnover_dollars / nav_before,
                transaction_cost=cost,
                nav_before=nav_before,
                nav_after=nav_after,
                target_weights=allocation.weights,
                rationale=allocation.rationale,
            ),
        )


def _adjusted_close(bar: BacktestBar) -> float:
    return bar.adjusted_close if bar.adjusted_close is not None else bar.close


def _run_fingerprint(
    price_fingerprint: str,
    strategy_parameters: dict[str, object],
    config: BacktestConfig,
) -> str:
    config_payload = {
        **asdict(config),
        "start_date": config.start_date.isoformat(),
        "end_date": config.end_date.isoformat(),
    }
    return sha256(
        dumps(
            {
                "price_fingerprint": price_fingerprint,
                "strategy": strategy_parameters,
                "config": config_payload,
            },
            separators=(",", ":"),
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _validate_allocation(
    allocation: TargetAllocation,
    *,
    eligible_asset_ids: frozenset[int] | None = None,
) -> TargetAllocation:
    cleaned: dict[int, float] = {}
    for asset_id, weight in allocation.weights.items():
        numeric = float(weight)
        if asset_id <= 0:
            raise ValueError("target asset ids must be positive")
        if not isfinite(numeric) or numeric < 0:
            raise ValueError("target weights must be finite and nonnegative")
        if numeric > 1e-14:
            if eligible_asset_ids is not None and asset_id not in eligible_asset_ids:
                raise ValueError(
                    f"target asset {asset_id} is not in the point-in-time universe"
                )
            cleaned[asset_id] = numeric
    total = sum(cleaned.values())
    if total > 1 + 1e-10:
        raise ValueError("long-only target weights cannot exceed 100%")
    return TargetAllocation(weights=cleaned, rationale=allocation.rationale)


def _validate_universe_timeline(
    timeline: tuple[UniversePoint, ...],
) -> tuple[UniversePoint, ...]:
    ordered = tuple(
        sorted(
            timeline,
            key=lambda item: (
                item.as_of_date,
                normalize_utc(item.available_at),
                item.snapshot_id,
            ),
        )
    )
    if timeline != ordered:
        raise ValueError("point-in-time universe timeline must be strictly ordered")
    ids = [item.snapshot_id for item in timeline]
    if len(ids) != len(set(ids)):
        raise ValueError("point-in-time universe timeline contains duplicate snapshots")
    return ordered


def _universe_at(
    timeline: tuple[UniversePoint, ...],
    *,
    signal_date: date,
    signal_cutoff: datetime,
) -> UniversePoint | None:
    cutoff = normalize_utc(signal_cutoff)
    eligible = [
        item
        for item in timeline
        if item.as_of_date <= signal_date and normalize_utc(item.available_at) <= cutoff
    ]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda item: (
            item.as_of_date,
            normalize_utc(item.available_at),
            item.snapshot_id,
        ),
    )


def _solve_post_cost_nav(
    nav_before: float,
    current_values: dict[int, float],
    target_weights: dict[int, float],
    cost_rate: float,
) -> float:
    if cost_rate == 0:
        return nav_before
    asset_ids = set(current_values) | set(target_weights)

    def residual(nav_after: float) -> float:
        turnover = sum(
            abs(nav_after * target_weights.get(asset_id, 0.0) - current_values.get(asset_id, 0.0))
            for asset_id in asset_ids
        )
        return nav_before - cost_rate * turnover - nav_after

    low = 0.0
    high = nav_before
    for _ in range(80):
        middle = (low + high) / 2
        if residual(middle) > 0:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def _signal_dates(
    calendar: tuple[date, ...],
    frequency: str,
) -> set[date]:
    if frequency == "daily":
        return set(calendar[:-1])
    selected: set[date] = set()
    for item, following in zip(calendar[:-1], calendar[1:], strict=True):
        if frequency == "monthly":
            boundary = (item.year, item.month) != (
                following.year,
                following.month,
            )
        elif frequency == "quarterly":
            boundary = (
                item.year,
                (item.month - 1) // 3 + 1,
            ) != (
                following.year,
                (following.month - 1) // 3 + 1,
            )
        else:
            raise ValueError(f"unsupported rebalance frequency: {frequency}")
        if boundary:
            selected.add(item)
    return selected


def _holding_periods(
    points: tuple[DailyPortfolioPoint, ...],
    rebalances: tuple[RebalanceRecord, ...],
) -> tuple[HoldingPeriodResult, ...]:
    executed = [item for item in rebalances if item.status == "executed"]
    if not executed:
        return ()
    periods: list[HoldingPeriodResult] = []
    point_index = {item.trade_date: index for index, item in enumerate(points)}
    for index, item in enumerate(executed):
        if index + 1 < len(executed):
            following = executed[index + 1]
            end_date = following.execution_date
            end_nav = following.nav_before
            is_closed = True
        else:
            end_date = points[-1].trade_date
            end_nav = points[-1].nav
            is_closed = False
        periods.append(
            HoldingPeriodResult(
                start_date=item.execution_date,
                end_date=end_date,
                net_return=end_nav / item.nav_before - 1,
                session_count=(point_index[end_date] - point_index[item.execution_date]),
                is_closed=is_closed,
            )
        )
    return tuple(periods)


def _rejected_rebalance(
    *,
    signal_date: date,
    execution_date: date,
    allocation: TargetAllocation,
    positions: dict[int, float],
    cash: float,
    nav_before: float,
    reason: str,
) -> tuple[dict[int, float], float, RebalanceRecord]:
    return (
        positions,
        cash,
        RebalanceRecord(
            signal_date=signal_date,
            execution_date=execution_date,
            status="rejected",
            turnover=0.0,
            transaction_cost=0.0,
            nav_before=nav_before,
            nav_after=nav_before,
            target_weights=allocation.weights,
            rationale=allocation.rationale,
            rejection_reason=reason,
        ),
    )
