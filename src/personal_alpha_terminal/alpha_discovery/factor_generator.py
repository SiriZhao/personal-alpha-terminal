from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import date
from hashlib import sha256
from json import dumps
from math import isfinite, sqrt
from statistics import stdev

from personal_alpha_terminal.alpha_discovery.schemas import (
    FactorDefinition,
    FactorObservation,
    FactorPanel,
    MarketEnvironmentPoint,
)
from personal_alpha_terminal.analysis.factors.schemas import (
    FactorAssetData,
    FactorDataset,
    FactorFinancialPoint,
)
from personal_alpha_terminal.core.market_time import market_close_utc, normalize_utc

FACTOR_LIBRARY: tuple[FactorDefinition, ...] = (
    FactorDefinition("pe", "value", "low", "cross_sectional", "Price / earnings.", "PE"),
    FactorDefinition("pb", "value", "low", "cross_sectional", "Price / book.", "PB"),
    FactorDefinition("ps", "value", "low", "cross_sectional", "Price / sales.", "PS"),
    FactorDefinition(
        "fcf_yield",
        "value",
        "high",
        "cross_sectional",
        "Free cash flow divided by raw market capitalization.",
        "FCF / (raw close * shares outstanding)",
    ),
    FactorDefinition(
        "revenue_growth",
        "growth",
        "high",
        "cross_sectional",
        "Point-in-time year-over-year revenue growth.",
        "(revenue_t - revenue_t-1y) / abs(revenue_t-1y)",
    ),
    FactorDefinition(
        "eps_growth",
        "growth",
        "high",
        "cross_sectional",
        "Point-in-time year-over-year diluted EPS growth.",
        "(EPS_t - EPS_t-1y) / abs(EPS_t-1y)",
    ),
    FactorDefinition("roe", "quality", "high", "cross_sectional", "Return on equity.", "ROE"),
    FactorDefinition(
        "roic",
        "quality",
        "high",
        "cross_sectional",
        "Return on invested capital.",
        "ROIC",
    ),
    FactorDefinition(
        "gross_margin",
        "quality",
        "high",
        "cross_sectional",
        "Gross profit margin.",
        "gross profit / revenue",
    ),
    FactorDefinition(
        "debt_ratio",
        "quality",
        "low",
        "cross_sectional",
        "Balance-sheet debt ratio; lower is the default hypothesis.",
        "reported debt ratio",
    ),
    FactorDefinition(
        "momentum_1m",
        "momentum",
        "high",
        "cross_sectional",
        "Trailing 21-session adjusted return.",
        "adjusted_close_t / adjusted_close_t-21 - 1",
        21,
    ),
    FactorDefinition(
        "momentum_3m",
        "momentum",
        "high",
        "cross_sectional",
        "Trailing 63-session adjusted return.",
        "adjusted_close_t / adjusted_close_t-63 - 1",
        63,
    ),
    FactorDefinition(
        "momentum_6m",
        "momentum",
        "high",
        "cross_sectional",
        "Trailing 126-session adjusted return.",
        "adjusted_close_t / adjusted_close_t-126 - 1",
        126,
    ),
    FactorDefinition(
        "momentum_12m",
        "momentum",
        "high",
        "cross_sectional",
        "Trailing 252-session adjusted return.",
        "adjusted_close_t / adjusted_close_t-252 - 1",
        252,
    ),
    FactorDefinition(
        "volatility_3m",
        "volatility",
        "low",
        "cross_sectional",
        "Annualized standard deviation of 63 daily adjusted returns.",
        "stdev(daily returns, 63) * sqrt(252)",
        63,
    ),
    FactorDefinition(
        "maximum_drawdown_6m",
        "volatility",
        "high",
        "cross_sectional",
        "Worst peak-to-trough adjusted-price loss over 126 sessions; closer to zero is better.",
        "min(adjusted_close / running_peak - 1, 126)",
        126,
    ),
    FactorDefinition(
        "ma_20_distance",
        "technical",
        "high",
        "cross_sectional",
        "Adjusted close relative to its 20-session simple moving average.",
        "adjusted_close / SMA20 - 1",
        20,
    ),
    FactorDefinition(
        "ma_60_distance",
        "technical",
        "high",
        "cross_sectional",
        "Adjusted close relative to its 60-session simple moving average.",
        "adjusted_close / SMA60 - 1",
        60,
    ),
    FactorDefinition(
        "rsi_14",
        "technical",
        "high",
        "cross_sectional",
        "Wilder 14-session relative strength index; high direction encodes continuation.",
        "100 - 100 / (1 + Wilder average gain / Wilder average loss)",
        14,
    ),
    FactorDefinition(
        "macd_histogram_pct",
        "technical",
        "high",
        "cross_sectional",
        "MACD(12,26,9) histogram normalized by adjusted close.",
        "(EMA12 - EMA26 - EMA9(EMA12 - EMA26)) / adjusted_close",
        35,
    ),
    FactorDefinition(
        "vix",
        "market_environment",
        "low",
        "time_series",
        "Point-in-time VIX level; evaluated once per date, never duplicated as stock samples.",
        "latest available VIX",
    ),
    FactorDefinition(
        "interest_rate",
        "market_environment",
        "low",
        "time_series",
        "Point-in-time benchmark interest-rate level.",
        "latest available benchmark rate",
    ),
    FactorDefinition(
        "dollar_index",
        "market_environment",
        "low",
        "time_series",
        "Point-in-time dollar-index level.",
        "latest available dollar index",
    ),
    FactorDefinition(
        "market_breadth",
        "market_environment",
        "high",
        "time_series",
        "Point-in-time advancing or above-trend share of the eligible universe.",
        "breadth ratio in [0, 1]",
    ),
)

FACTOR_BY_NAME = {item.name: item for item in FACTOR_LIBRARY}


def build_rebalance_dates(
    dataset: FactorDataset,
    *,
    start_date: date,
    end_date: date,
    interval: int,
    minimum_cross_section: int,
) -> tuple[date, ...]:
    """Build a market-session schedule without filling suspension or holiday rows."""

    if start_date >= end_date:
        raise ValueError("start_date must be before end_date")
    if interval < 1:
        raise ValueError("interval must be positive")
    counts = Counter(
        point.date
        for asset in dataset.assets
        for point in asset.prices
        if start_date <= point.date <= end_date
    )
    eligible = sorted(
        item_date for item_date, count in counts.items() if count >= minimum_cross_section
    )
    return tuple(eligible[index] for index in range(0, len(eligible), interval))


def generate_factor_panel(
    dataset: FactorDataset,
    *,
    market: str,
    rebalance_dates: Sequence[date],
    horizon_days: int,
    minimum_cross_section: int,
    definitions: Sequence[FactorDefinition] = FACTOR_LIBRARY,
    environment: Sequence[MarketEnvironmentPoint] = (),
    environment_max_staleness_days: int = 5,
) -> FactorPanel:
    """Create point-in-time factor values and forward labels on adjusted closes."""

    if market not in {"A", "HK", "US"}:
        raise ValueError("market must be A, HK, or US")
    if horizon_days < 1:
        raise ValueError("horizon_days must be positive")
    if minimum_cross_section < 3:
        raise ValueError("minimum_cross_section must be at least 3")
    resolved_definitions = _validate_definitions(definitions)
    ordered_dates = tuple(sorted(set(rebalance_dates)))
    observations: list[FactorObservation] = []
    for as_of_date in ordered_dates:
        environment_values = _environment_values(
            environment,
            as_of_date=as_of_date,
            market=market,
            maximum_staleness_days=environment_max_staleness_days,
        )
        dated: list[FactorObservation] = []
        for asset in dataset.assets:
            if asset.instrument.market != market:
                continue
            observation = _asset_observation(
                asset,
                as_of_date=as_of_date,
                horizon_days=horizon_days,
                definitions=resolved_definitions,
                environment_values=environment_values,
            )
            if observation is not None:
                dated.append(observation)
        if len(dated) >= minimum_cross_section:
            observations.extend(dated)
    observations = _remove_overlapping_asset_labels(
        observations,
        ordered_dates,
        minimum_cross_section=minimum_cross_section,
    )
    ordered = tuple(sorted(observations, key=lambda item: (item.as_of_date, item.instrument.id)))
    return FactorPanel(
        market=market,
        horizon_days=horizon_days,
        definitions=resolved_definitions,
        observations=ordered,
        data_fingerprint=_fingerprint(market, horizon_days, resolved_definitions, ordered),
    )


def _asset_observation(
    asset: FactorAssetData,
    *,
    as_of_date: date,
    horizon_days: int,
    definitions: tuple[FactorDefinition, ...],
    environment_values: dict[str, float | None],
) -> FactorObservation | None:
    price_index = next(
        (index for index, point in enumerate(asset.prices) if point.date == as_of_date),
        None,
    )
    if price_index is None or price_index + horizon_days >= len(asset.prices):
        return None
    entry = asset.prices[price_index]
    exit_point = asset.prices[price_index + horizon_days]
    if entry.close <= 0 or exit_point.close <= 0:
        return None
    financial_values = _financial_values(asset, as_of_date, price_index)
    technical_values = _price_values(asset, price_index)
    all_values = {**financial_values, **technical_values, **environment_values}
    selected = {
        definition.name: _finite_or_none(all_values.get(definition.name))
        for definition in definitions
    }
    return FactorObservation(
        as_of_date=as_of_date,
        forward_end_date=exit_point.date,
        instrument=asset.instrument,
        factor_values=selected,
        forward_return=exit_point.close / entry.close - 1,
    )


def _financial_values(
    asset: FactorAssetData,
    as_of_date: date,
    price_index: int,
) -> dict[str, float | None]:
    cutoff = market_close_utc(as_of_date, asset.instrument.market)
    visible = [
        item
        for item in asset.financials
        if item.period_end <= as_of_date and normalize_utc(item.available_at) <= cutoff
    ]
    latest = (
        max(visible, key=lambda item: (normalize_utc(item.available_at), item.period_end))
        if visible
        else None
    )
    if latest is None:
        return {
            name: None
            for name in (
                "pe",
                "pb",
                "ps",
                "fcf_yield",
                "revenue_growth",
                "eps_growth",
                "roe",
                "roic",
                "gross_margin",
                "debt_ratio",
            )
        }
    consistent_history = [item for item in visible if item.source == latest.source]
    prior = _prior_year_record(consistent_history, latest)
    raw_close = asset.prices[price_index].raw_close or asset.prices[price_index].close
    fcf_yield = None
    if (
        latest.period_type in {"annual", "ttm"}
        and latest.free_cash_flow is not None
        and latest.shares_outstanding is not None
        and latest.shares_outstanding > 0
        and raw_close > 0
    ):
        fcf_yield = latest.free_cash_flow / (raw_close * latest.shares_outstanding)
    return {
        "pe": latest.pe if latest.pe is not None and latest.pe > 0 else None,
        "pb": latest.pb if latest.pb is not None and latest.pb > 0 else None,
        "ps": latest.ps if latest.ps is not None and latest.ps > 0 else None,
        "fcf_yield": fcf_yield,
        "revenue_growth": _growth(
            latest.revenue,
            prior.revenue if prior is not None else None,
        ),
        "eps_growth": _growth(latest.eps, prior.eps if prior is not None else None),
        "roe": latest.roe,
        "roic": latest.roic,
        "gross_margin": latest.gross_margin,
        "debt_ratio": latest.debt_ratio,
    }


def _price_values(asset: FactorAssetData, price_index: int) -> dict[str, float | None]:
    closes = [item.close for item in asset.prices[: price_index + 1]]
    return {
        "momentum_1m": _trailing_return(closes, 21),
        "momentum_3m": _trailing_return(closes, 63),
        "momentum_6m": _trailing_return(closes, 126),
        "momentum_12m": _trailing_return(closes, 252),
        "volatility_3m": _annualized_volatility(closes, 63),
        "maximum_drawdown_6m": _maximum_drawdown(closes, 126),
        "ma_20_distance": _moving_average_distance(closes, 20),
        "ma_60_distance": _moving_average_distance(closes, 60),
        "rsi_14": _wilder_rsi(closes, 14),
        "macd_histogram_pct": _macd_histogram_pct(closes),
    }


def _environment_values(
    points: Sequence[MarketEnvironmentPoint],
    *,
    as_of_date: date,
    market: str,
    maximum_staleness_days: int,
) -> dict[str, float | None]:
    cutoff = market_close_utc(as_of_date, market)
    visible = [
        item
        for item in points
        if item.date <= as_of_date
        and normalize_utc(item.available_at) <= cutoff
        and (as_of_date - item.date).days <= maximum_staleness_days
    ]
    latest = (
        max(visible, key=lambda item: (item.date, normalize_utc(item.available_at)))
        if visible
        else None
    )
    return {
        "vix": latest.vix if latest else None,
        "interest_rate": latest.interest_rate if latest else None,
        "dollar_index": latest.dollar_index if latest else None,
        "market_breadth": latest.market_breadth if latest else None,
    }


def _prior_year_record(
    financials: Sequence[FactorFinancialPoint],
    latest: FactorFinancialPoint,
) -> FactorFinancialPoint | None:
    candidates = [
        item
        for item in financials
        if item.period_type == latest.period_type
        and 300 <= (latest.period_end - item.period_end).days <= 430
    ]
    return max(candidates, key=lambda item: item.period_end) if candidates else None


def _growth(current: float | None, prior: float | None) -> float | None:
    if current is None or prior is None or abs(prior) <= 1e-12:
        return None
    return (current - prior) / abs(prior)


def _trailing_return(closes: Sequence[float], window: int) -> float | None:
    if len(closes) <= window or closes[-window - 1] <= 0:
        return None
    return closes[-1] / closes[-window - 1] - 1


def _annualized_volatility(closes: Sequence[float], window: int) -> float | None:
    if len(closes) <= window:
        return None
    selected = closes[-window - 1 :]
    returns = [
        selected[index] / selected[index - 1] - 1
        for index in range(1, len(selected))
        if selected[index - 1] > 0
    ]
    return stdev(returns) * sqrt(252) if len(returns) >= 2 else None


def _maximum_drawdown(closes: Sequence[float], window: int) -> float | None:
    if len(closes) <= window:
        return None
    peak = closes[-window - 1]
    drawdown = 0.0
    for value in closes[-window - 1 :]:
        peak = max(peak, value)
        if peak > 0:
            drawdown = min(drawdown, value / peak - 1)
    return drawdown


def _moving_average_distance(closes: Sequence[float], window: int) -> float | None:
    if len(closes) < window:
        return None
    average = sum(closes[-window:]) / window
    return closes[-1] / average - 1 if average > 0 else None


def _wilder_rsi(closes: Sequence[float], period: int) -> float | None:
    if len(closes) <= period:
        return None
    changes = [closes[index] - closes[index - 1] for index in range(1, len(closes))]
    gains = [max(value, 0.0) for value in changes]
    losses = [max(-value, 0.0) for value in changes]
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:], strict=True):
        average_gain = (average_gain * (period - 1) + gain) / period
        average_loss = (average_loss * (period - 1) + loss) / period
    if average_loss <= 1e-15:
        return 100.0 if average_gain > 0 else 50.0
    relative_strength = average_gain / average_loss
    return 100 - 100 / (1 + relative_strength)


def _ema(values: Sequence[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(alpha * value + (1 - alpha) * result[-1])
    return result


def _macd_histogram_pct(closes: Sequence[float]) -> float | None:
    if len(closes) < 35 or closes[-1] <= 0:
        return None
    fast = _ema(closes, 12)
    slow = _ema(closes, 26)
    macd = [fast[index] - slow[index] for index in range(len(closes))]
    signal = _ema(macd, 9)
    return (macd[-1] - signal[-1]) / closes[-1]


def _finite_or_none(value: float | None) -> float | None:
    return value if value is not None and isfinite(value) else None


def _validate_definitions(
    definitions: Sequence[FactorDefinition],
) -> tuple[FactorDefinition, ...]:
    resolved = tuple(definitions)
    names = [item.name for item in resolved]
    if not resolved:
        raise ValueError("at least one factor definition is required")
    if len(names) != len(set(names)):
        raise ValueError("factor definition names must be unique")
    unknown = sorted(set(names) - set(FACTOR_BY_NAME))
    if unknown:
        raise ValueError(f"unknown factor definitions: {unknown}")
    return resolved


def _remove_overlapping_asset_labels(
    observations: Sequence[FactorObservation],
    ordered_dates: Sequence[date],
    *,
    minimum_cross_section: int,
) -> list[FactorObservation]:
    next_date = {
        current: following
        for current, following in zip(ordered_dates, ordered_dates[1:], strict=False)
    }
    filtered = [
        item
        for item in observations
        if item.as_of_date not in next_date or item.forward_end_date <= next_date[item.as_of_date]
    ]
    counts = Counter(item.as_of_date for item in filtered)
    return [item for item in filtered if counts[item.as_of_date] >= minimum_cross_section]


def _fingerprint(
    market: str,
    horizon_days: int,
    definitions: Sequence[FactorDefinition],
    observations: Iterable[FactorObservation],
) -> str:
    payload = {
        "market": market,
        "horizon_days": horizon_days,
        "definitions": [
            {
                "name": item.name,
                "formula": item.formula,
                "direction": item.direction,
                "scope": item.scope,
            }
            for item in definitions
        ],
        "observations": [
            {
                "date": item.as_of_date.isoformat(),
                "forward_end": item.forward_end_date.isoformat(),
                "instrument_id": item.instrument.id,
                "forward_return": format(item.forward_return, ".17g"),
                "values": {
                    key: format(value, ".17g") if value is not None else None
                    for key, value in sorted(item.factor_values.items())
                },
            }
            for item in observations
        ],
    }
    return sha256(
        dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
