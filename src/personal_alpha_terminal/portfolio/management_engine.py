from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from hashlib import sha256
from json import dumps
from math import sqrt
from statistics import fmean, stdev

from personal_alpha_terminal.portfolio.management_schemas import (
    AllocationTarget,
    AssetPricePoint,
    AssetPriceSeries,
    LedgerEvent,
    ManagedAsset,
    PortfolioDailyPoint,
    PortfolioManagementData,
    PortfolioManagementResult,
    PositionAllocation,
    RebalanceSuggestion,
)
from personal_alpha_terminal.portfolio.schemas import FxSeries

SUPPORTED_ASSET_CLASSES = frozenset(
    {"stock", "etf", "bond", "money_fund", "gold", "commodity"}
)
SUPPORTED_TRANSACTION_TYPES = frozenset(
    {"buy", "sell", "dividend", "fee", "deposit", "withdrawal", "split"}
)


def analyze_portfolio(
    data: PortfolioManagementData,
    *,
    annual_risk_free_rate: float = 0.0,
    minimum_observations: int = 60,
    price_max_staleness_days: int = 7,
    fx_max_staleness_days: int = 5,
    rebalance_drift_threshold: float = 0.05,
    minimum_rebalance_value: float = 100.0,
) -> PortfolioManagementResult:
    """Reconstruct an actual, long-only portfolio from an immutable transaction ledger.

    Unadjusted closes are required because cash dividends are explicit ledger events. External
    deposits and withdrawals are removed from time-weighted returns using an end-of-day flow
    convention. The result is analytical only and never creates an order.
    """

    _validate_parameters(
        data,
        annual_risk_free_rate,
        minimum_observations,
        rebalance_drift_threshold,
        minimum_rebalance_value,
    )
    transactions = tuple(sorted(data.transactions, key=lambda item: (item.trade_date, item.id)))
    _validate_transactions(transactions, data.base_currency)
    price_by_asset = {item.asset.id: item for item in data.prices}
    assets = {item.asset.id: item.asset for item in data.prices}
    for transaction in transactions:
        if transaction.asset is not None:
            assets[transaction.asset.id] = transaction.asset

    calendar = _valuation_calendar(data, transactions)
    if not calendar:
        raise ValueError("benchmark has no valuation dates in the requested period")

    holdings: defaultdict[int, float] = defaultdict(float)
    cash: defaultdict[str, float] = defaultdict(float)
    pre_period = [item for item in transactions if item.trade_date < calendar[0]]
    for transaction in pre_period:
        _apply_transaction(transaction, holdings, cash)
    opening_value, _, _ = _value_portfolio(
        calendar[0],
        holdings,
        cash,
        assets,
        price_by_asset,
        data.fx_series,
        data.base_currency,
        price_max_staleness_days,
        fx_max_staleness_days,
    )

    transaction_by_date: defaultdict[date, list[LedgerEvent]] = defaultdict(list)
    for transaction in transactions:
        if calendar[0] <= transaction.trade_date <= calendar[-1]:
            transaction_by_date[transaction.trade_date].append(transaction)

    curve: list[PortfolioDailyPoint] = []
    previous_value = opening_value
    cumulative = 1.0
    peak = 1.0
    net_external_flow = 0.0
    warnings: list[str] = []
    for valuation_date in calendar:
        daily_flow = 0.0
        for transaction in transaction_by_date[valuation_date]:
            _apply_transaction(transaction, holdings, cash)
            if transaction.transaction_type in {"deposit", "withdrawal"}:
                signed = transaction.cash_amount or 0.0
                if transaction.transaction_type == "withdrawal":
                    signed = -signed
                daily_flow += signed * transaction.fx_rate_to_base
        net_external_flow += daily_flow
        value, _, _ = _value_portfolio(
            valuation_date,
            holdings,
            cash,
            assets,
            price_by_asset,
            data.fx_series,
            data.base_currency,
            price_max_staleness_days,
            fx_max_staleness_days,
        )
        daily_return = None
        if previous_value > 1e-12:
            daily_return = (value - daily_flow) / previous_value - 1
            if daily_return <= -1:
                raise ValueError("portfolio return reached or fell below -100%; inspect ledger")
            cumulative *= 1 + daily_return
        elif abs(value - daily_flow) > 1e-8:
            warnings.append(
                f"{valuation_date.isoformat()}: return unavailable because opening value was zero"
            )
        peak = max(peak, cumulative)
        drawdown = cumulative / peak - 1
        curve.append(
            PortfolioDailyPoint(
                date=valuation_date,
                value=value,
                external_flow=daily_flow,
                daily_return=daily_return,
                cumulative_return=cumulative - 1,
                drawdown=drawdown,
            )
        )
        previous_value = value

    final_value, position_values, cash_values = _value_portfolio(
        calendar[-1],
        holdings,
        cash,
        assets,
        price_by_asset,
        data.fx_series,
        data.base_currency,
        price_max_staleness_days,
        fx_max_staleness_days,
    )
    if final_value <= 0:
        raise ValueError("portfolio ending value must be positive")

    returns_by_date = {
        point.date: point.daily_return for point in curve if point.daily_return is not None
    }
    aligned_portfolio, aligned_benchmark = _aligned_benchmark_returns(
        returns_by_date,
        data.benchmark_prices,
        data.benchmark.currency,
        data.base_currency,
        data.fx_series,
        fx_max_staleness_days,
    )
    return_values = list(returns_by_date.values())
    cumulative_return = cumulative - 1
    annualized_return = _annualized_return(return_values)
    volatility = stdev(return_values) * sqrt(252) if len(return_values) >= 2 else None
    daily_risk_free = (1 + annual_risk_free_rate) ** (1 / 252) - 1
    sharpe = _sharpe(return_values, daily_risk_free)
    sortino = _sortino(return_values, daily_risk_free)
    beta = None
    alpha = None
    if len(aligned_portfolio) >= minimum_observations:
        beta = _beta(aligned_portfolio, aligned_benchmark)
        if beta is not None:
            alpha = (
                fmean(aligned_portfolio)
                - daily_risk_free
                - beta * (fmean(aligned_benchmark) - daily_risk_free)
            ) * 252
    else:
        warnings.append(
            "Beta and alpha withheld: aligned benchmark sample "
            f"{len(aligned_portfolio)} < {minimum_observations}."
        )

    positions = _position_allocations(holdings, position_values, assets, final_value)
    asset_class_exposure, industry_exposure, currency_exposure = _exposures(
        positions,
        cash_values,
        final_value,
    )
    current_values = {item.key: item.market_value for item in positions}
    current_values.update({f"cash:{key}": value for key, value in cash_values.items()})
    suggestions = calculate_rebalancing(
        current_values=current_values,
        targets=data.targets,
        total_value=final_value,
        drift_threshold=rebalance_drift_threshold,
        minimum_value=minimum_rebalance_value,
    )
    fingerprint = _fingerprint(data)
    return PortfolioManagementResult(
        portfolio_id=data.portfolio_id,
        portfolio_name=data.portfolio_name,
        base_currency=data.base_currency,
        start_date=calendar[0],
        as_of_date=calendar[-1],
        opening_value=opening_value,
        total_value=final_value,
        net_external_flow=net_external_flow,
        period_pnl=final_value - opening_value - net_external_flow,
        latest_daily_return=next(
            (item.daily_return for item in reversed(curve) if item.daily_return is not None),
            None,
        ),
        cumulative_return=cumulative_return,
        annualized_return=annualized_return,
        annualized_volatility=volatility,
        max_drawdown=min((item.drawdown for item in curve), default=0.0),
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        beta=beta,
        alpha=alpha,
        observation_count=len(return_values),
        positions=positions,
        cash_values=cash_values,
        asset_class_exposure=asset_class_exposure,
        industry_exposure=industry_exposure,
        currency_exposure=currency_exposure,
        equity_curve=tuple(curve),
        rebalance_suggestions=suggestions,
        data_fingerprint=fingerprint,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def calculate_rebalancing(
    *,
    current_values: dict[str, float],
    targets: Sequence[AllocationTarget],
    total_value: float,
    drift_threshold: float,
    minimum_value: float,
) -> tuple[RebalanceSuggestion, ...]:
    if not targets:
        return ()
    target_total = sum(item.target_weight for item in targets)
    if abs(target_total - 1.0) > 1e-6:
        raise ValueError(f"allocation targets must sum to 1.0; got {target_total:.8f}")
    if len({item.key for item in targets}) != len(targets):
        raise ValueError("allocation target keys must be unique")
    suggestions: list[RebalanceSuggestion] = []
    target_by_key = {item.key: item for item in targets}
    all_keys = set(current_values) | set(target_by_key)
    for key in all_keys:
        current_weight = current_values.get(key, 0.0) / total_value
        target = target_by_key.get(key)
        target_weight = target.target_weight if target is not None else 0.0
        drift = target_weight - current_weight
        indicative_value = drift * total_value
        if abs(drift) < drift_threshold or abs(indicative_value) < minimum_value:
            continue
        suggestions.append(
            RebalanceSuggestion(
                key=key,
                label=target.label if target is not None else key,
                action="increase" if drift > 0 else "reduce",
                current_weight=current_weight,
                target_weight=target_weight,
                drift=drift,
                indicative_value=indicative_value,
            )
        )
    return tuple(sorted(suggestions, key=lambda item: abs(item.drift), reverse=True))


def _validate_parameters(
    data: PortfolioManagementData,
    annual_risk_free_rate: float,
    minimum_observations: int,
    drift_threshold: float,
    minimum_value: float,
) -> None:
    if data.start_date > data.end_date:
        raise ValueError("start_date must not be after end_date")
    if data.base_currency != data.base_currency.upper() or len(data.base_currency) != 3:
        raise ValueError("base_currency must be a three-letter uppercase code")
    if not -1 < annual_risk_free_rate <= 1:
        raise ValueError("annual_risk_free_rate must be greater than -1 and at most 1")
    if minimum_observations < 2:
        raise ValueError("minimum_observations must be at least 2")
    if not 0 <= drift_threshold <= 1:
        raise ValueError("rebalance drift threshold must be between 0 and 1")
    if minimum_value < 0:
        raise ValueError("minimum rebalance value cannot be negative")


def _validate_transactions(events: Sequence[LedgerEvent], base_currency: str) -> None:
    seen: set[int] = set()
    for item in events:
        if item.id in seen:
            raise ValueError(f"duplicate ledger event id {item.id}")
        seen.add(item.id)
        if item.transaction_type not in SUPPORTED_TRANSACTION_TYPES:
            raise ValueError(f"unsupported transaction type {item.transaction_type}")
        if item.currency != item.currency.upper() or len(item.currency) != 3:
            raise ValueError(f"invalid currency on transaction {item.id}")
        if item.fx_rate_to_base <= 0:
            raise ValueError(f"invalid FX rate on transaction {item.id}")
        if item.currency == base_currency and abs(item.fx_rate_to_base - 1.0) > 1e-9:
            raise ValueError(f"base-currency FX rate must equal 1 on transaction {item.id}")
        if item.settlement_date < item.trade_date:
            raise ValueError(f"settlement precedes trade date on transaction {item.id}")
        if item.asset is not None and item.asset.asset_class not in SUPPORTED_ASSET_CLASSES:
            raise ValueError(f"unsupported asset class {item.asset.asset_class}")
        if item.fee_amount < 0:
            raise ValueError(f"negative fee on transaction {item.id}")
        if item.transaction_type in {"buy", "sell"}:
            if item.asset is None or not item.quantity or not item.unit_price:
                raise ValueError(f"incomplete buy/sell payload on transaction {item.id}")
            if item.quantity <= 0 or item.unit_price <= 0 or item.cash_amount is not None:
                raise ValueError(f"invalid buy/sell payload on transaction {item.id}")
        elif item.transaction_type == "dividend":
            if (
                item.asset is None
                or item.cash_amount is None
                or item.cash_amount <= 0
                or item.quantity is not None
                or item.unit_price is not None
            ):
                raise ValueError(f"invalid dividend payload on transaction {item.id}")
        elif item.transaction_type == "split":
            if (
                item.asset is None
                or item.quantity is None
                or item.quantity <= 0
                or item.cash_amount is not None
                or item.unit_price is not None
            ):
                raise ValueError(f"invalid split payload on transaction {item.id}")
        elif item.transaction_type in {"deposit", "withdrawal"}:
            if (
                item.asset is not None
                or item.cash_amount is None
                or item.cash_amount <= 0
                or item.quantity is not None
                or item.unit_price is not None
            ):
                raise ValueError(f"invalid external cash-flow payload on transaction {item.id}")
        elif item.transaction_type == "fee" and (
            item.cash_amount is None
            or item.cash_amount <= 0
            or item.quantity is not None
            or item.unit_price is not None
        ):
            raise ValueError(f"invalid standalone fee payload on transaction {item.id}")


def _valuation_calendar(
    data: PortfolioManagementData,
    transactions: Sequence[LedgerEvent],
) -> tuple[date, ...]:
    dates = {
        point.date
        for point in data.benchmark_prices
        if data.start_date <= point.date <= data.end_date
    }
    dates.update(
        item.trade_date
        for item in transactions
        if data.start_date <= item.trade_date <= data.end_date
    )
    return tuple(sorted(dates))


def _apply_transaction(
    item: LedgerEvent,
    holdings: defaultdict[int, float],
    cash: defaultdict[str, float],
) -> None:
    kind = item.transaction_type
    amount = item.cash_amount or 0.0
    quantity = item.quantity or 0.0
    price = item.unit_price or 0.0
    if kind == "deposit":
        cash[item.currency] += amount
    elif kind == "withdrawal":
        cash[item.currency] -= amount
    elif kind == "buy":
        assert item.asset is not None
        holdings[item.asset.id] += quantity
        cash[item.currency] -= quantity * price + item.fee_amount
    elif kind == "sell":
        assert item.asset is not None
        if holdings[item.asset.id] + 1e-9 < quantity:
            raise ValueError(f"sell exceeds holdings for {item.asset.symbol} on {item.trade_date}")
        holdings[item.asset.id] -= quantity
        cash[item.currency] += quantity * price - item.fee_amount
    elif kind == "dividend":
        cash[item.currency] += amount - item.fee_amount
    elif kind == "fee":
        cash[item.currency] -= amount
    elif kind == "split":
        assert item.asset is not None
        if holdings[item.asset.id] <= 0:
            raise ValueError(f"split without holdings for {item.asset.symbol}")
        holdings[item.asset.id] *= quantity
    if cash[item.currency] < -1e-6:
        raise ValueError(
            f"negative {item.currency} cash after transaction {item.id}; leverage is not supported"
        )


def _value_portfolio(
    valuation_date: date,
    holdings: dict[int, float],
    cash: dict[str, float],
    assets: dict[int, ManagedAsset],
    price_by_asset: dict[int, AssetPriceSeries],
    fx_series: Sequence[FxSeries],
    base_currency: str,
    price_max_staleness_days: int,
    fx_max_staleness_days: int,
) -> tuple[float, dict[int, float], dict[str, float]]:
    position_values: dict[int, float] = {}
    for asset_id, quantity in holdings.items():
        if quantity <= 1e-12:
            continue
        series = price_by_asset.get(asset_id)
        asset = assets.get(asset_id)
        if series is None or asset is None:
            raise ValueError(f"missing price series for held asset {asset_id}")
        point = _latest_point(series.values, valuation_date, price_max_staleness_days)
        if point is None:
            raise ValueError(f"missing or stale price for {asset.symbol} on {valuation_date}")
        fx = _fx_rate(
            asset.currency,
            base_currency,
            valuation_date,
            fx_series,
            fx_max_staleness_days,
        )
        if fx is None:
            raise ValueError(
                f"missing or stale FX {asset.currency}/{base_currency} on {valuation_date}"
            )
        position_values[asset_id] = quantity * point.close * fx
    cash_values: dict[str, float] = {}
    for currency, amount in cash.items():
        if abs(amount) <= 1e-12:
            continue
        fx = _fx_rate(currency, base_currency, valuation_date, fx_series, fx_max_staleness_days)
        if fx is None:
            raise ValueError(f"missing or stale FX {currency}/{base_currency} on {valuation_date}")
        cash_values[currency] = amount * fx
    return sum(position_values.values()) + sum(cash_values.values()), position_values, cash_values


def _latest_point(
    values: Sequence[AssetPricePoint],
    valuation_date: date,
    maximum_staleness_days: int,
) -> AssetPricePoint | None:
    point = next((item for item in reversed(values) if item.date <= valuation_date), None)
    if point is None or (valuation_date - point.date).days > maximum_staleness_days:
        return None
    return point


def _fx_rate(
    source: str,
    target: str,
    valuation_date: date,
    series: Sequence[FxSeries],
    maximum_staleness_days: int,
) -> float | None:
    if source == target:
        return 1.0
    for item in series:
        direct = item.base_currency == source and item.quote_currency == target
        inverse = item.base_currency == target and item.quote_currency == source
        if not direct and not inverse:
            continue
        point = next(
            (value for value in reversed(item.values) if value.date <= valuation_date),
            None,
        )
        if point is None or (valuation_date - point.date).days > maximum_staleness_days:
            continue
        return point.rate if direct else 1 / point.rate
    return None


def _aligned_benchmark_returns(
    portfolio_returns: dict[date, float],
    benchmark_prices: Sequence[AssetPricePoint],
    benchmark_currency: str,
    base_currency: str,
    fx_series: Sequence[FxSeries],
    fx_max_staleness_days: int,
) -> tuple[list[float], list[float]]:
    converted: list[tuple[date, float]] = []
    for point in benchmark_prices:
        fx = _fx_rate(
            benchmark_currency,
            base_currency,
            point.date,
            fx_series,
            fx_max_staleness_days,
        )
        if fx is not None:
            converted.append((point.date, point.close * fx))
    benchmark_returns: dict[date, float] = {}
    for previous, current in zip(converted, converted[1:], strict=False):
        if previous[1] > 0:
            benchmark_returns[current[0]] = current[1] / previous[1] - 1
    dates = sorted(set(portfolio_returns) & set(benchmark_returns))
    return (
        [portfolio_returns[item] for item in dates],
        [benchmark_returns[item] for item in dates],
    )


def _position_allocations(
    holdings: dict[int, float],
    position_values: dict[int, float],
    assets: dict[int, ManagedAsset],
    total_value: float,
) -> tuple[PositionAllocation, ...]:
    results = [
        PositionAllocation(
            key=f"asset:{asset_id}",
            symbol=assets[asset_id].symbol,
            name=assets[asset_id].name,
            asset_class=assets[asset_id].asset_class,
            currency=assets[asset_id].currency,
            industry=assets[asset_id].industry,
            quantity=holdings[asset_id],
            market_value=value,
            weight=value / total_value,
        )
        for asset_id, value in position_values.items()
    ]
    return tuple(sorted(results, key=lambda item: item.weight, reverse=True))


def _exposures(
    positions: Sequence[PositionAllocation],
    cash_values: dict[str, float],
    total_value: float,
) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    classes: defaultdict[str, float] = defaultdict(float)
    industries: defaultdict[str, float] = defaultdict(float)
    currencies: defaultdict[str, float] = defaultdict(float)
    for item in positions:
        classes[item.asset_class] += item.weight
        industries[item.industry] += item.weight
        currencies[item.currency] += item.weight
    for currency, value in cash_values.items():
        weight = value / total_value
        classes["cash"] += weight
        industries["cash"] += weight
        currencies[currency] += weight
    return dict(classes), dict(industries), dict(currencies)


def _annualized_return(returns: Sequence[float]) -> float | None:
    if not returns:
        return None
    compounded = 1.0
    for value in returns:
        compounded *= 1 + value
    return float(compounded ** (252 / len(returns)) - 1)


def _sharpe(returns: Sequence[float], daily_risk_free: float) -> float | None:
    if len(returns) < 2:
        return None
    deviation = stdev(returns)
    if deviation <= 1e-18:
        return None
    return (fmean(returns) - daily_risk_free) / deviation * sqrt(252)


def _sortino(returns: Sequence[float], daily_risk_free: float) -> float | None:
    if len(returns) < 2:
        return None
    downside = [min(0.0, value - daily_risk_free) for value in returns]
    downside_deviation = sqrt(sum(value * value for value in downside) / len(downside))
    if downside_deviation <= 1e-18:
        return None
    return (fmean(returns) - daily_risk_free) / downside_deviation * sqrt(252)


def _beta(asset_returns: Sequence[float], benchmark_returns: Sequence[float]) -> float | None:
    benchmark_mean = fmean(benchmark_returns)
    variance = sum((value - benchmark_mean) ** 2 for value in benchmark_returns)
    if variance <= 1e-18:
        return None
    asset_mean = fmean(asset_returns)
    covariance = sum(
        (asset - asset_mean) * (benchmark - benchmark_mean)
        for asset, benchmark in zip(asset_returns, benchmark_returns, strict=True)
    )
    return covariance / variance


def _fingerprint(data: PortfolioManagementData) -> str:
    payload = {
        "portfolio_id": data.portfolio_id,
        "start": data.start_date.isoformat(),
        "end": data.end_date.isoformat(),
        "transactions": [
            [
                item.id,
                item.transaction_type,
                item.trade_date.isoformat(),
                item.available_time.isoformat(),
            ]
            for item in data.transactions
        ],
        "prices": [
            [
                item.asset.id,
                len(item.values),
                item.values[-1].date.isoformat() if item.values else None,
            ]
            for item in data.prices
        ],
        "benchmark": [data.benchmark.id, len(data.benchmark_prices)],
        "targets": [[item.key, item.target_weight] for item in data.targets],
    }
    return sha256(dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
