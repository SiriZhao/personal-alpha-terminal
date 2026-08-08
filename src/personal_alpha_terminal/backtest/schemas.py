from dataclasses import dataclass, field
from datetime import date, datetime
from math import isfinite
from typing import Literal

RebalanceFrequency = Literal["daily", "monthly", "quarterly"]
RebalanceStatus = Literal["executed", "rejected"]
ValidationSeverity = Literal["warning", "error"]


@dataclass(frozen=True, slots=True)
class BacktestBar:
    asset_id: int
    symbol: str
    market: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float | None
    volume: int | None
    source: str
    adjustment_method: str | None
    provider: str | None = None
    event_time: datetime | None = None
    available_time: datetime | None = None
    ingested_time: datetime | None = None
    open_tradable: bool | None = None

    @property
    def adjustment_ratio(self) -> float:
        adjusted = self.adjusted_close
        if adjusted is None:
            return 1.0
        return adjusted / self.close

    @property
    def adjusted_open(self) -> float:
        return self.open * self.adjustment_ratio

    @property
    def adjusted_high(self) -> float:
        return self.high * self.adjustment_ratio

    @property
    def adjusted_low(self) -> float:
        return self.low * self.adjustment_ratio


@dataclass(frozen=True, slots=True)
class BacktestDataset:
    market: str
    bars: tuple[BacktestBar, ...]
    data_sources: tuple[str, ...]
    calendar: tuple[date, ...] = ()
    calendar_source: str | None = None
    universe_timeline: tuple["UniversePoint", ...] = ()


@dataclass(frozen=True, slots=True)
class UniversePoint:
    """Point-in-time membership known no later than ``available_at``."""

    snapshot_id: int
    as_of_date: date
    available_at: datetime
    asset_ids: frozenset[int]
    source: str

    def __post_init__(self) -> None:
        if self.snapshot_id <= 0:
            raise ValueError("universe snapshot id must be positive")
        if self.available_at.tzinfo is None:
            raise ValueError("universe available_at must be timezone-aware")
        if not self.asset_ids or any(asset_id <= 0 for asset_id in self.asset_ids):
            raise ValueError("universe snapshot requires positive asset ids")
        if not self.source.strip():
            raise ValueError("universe snapshot source cannot be empty")


@dataclass(frozen=True, slots=True)
class EventSignal:
    event_date: date
    available_at: datetime
    source_asset_id: int
    target_asset_id: int
    event_type: str
    description: str

    def __post_init__(self) -> None:
        if self.available_at.tzinfo is None:
            raise ValueError("event available_at must be timezone-aware")
        if self.source_asset_id <= 0 or self.target_asset_id <= 0:
            raise ValueError("event asset ids must be positive")
        if not self.event_type.strip():
            raise ValueError("event_type cannot be empty")


@dataclass(frozen=True, slots=True)
class FactorSnapshot:
    as_of_date: date
    available_at: datetime
    values: dict[int, float]
    source: str

    def __post_init__(self) -> None:
        if self.available_at.tzinfo is None:
            raise ValueError("factor available_at must be timezone-aware")
        if not self.source.strip():
            raise ValueError("factor snapshot source cannot be empty")
        if not self.values:
            raise ValueError("factor snapshot values cannot be empty")
        for asset_id, value in self.values.items():
            if asset_id <= 0 or not isfinite(float(value)):
                raise ValueError("factor snapshot requires positive ids and finite values")


@dataclass(frozen=True, slots=True)
class StrategyContext:
    signal_date: date
    signal_cutoff: datetime
    calendar: tuple[date, ...]
    decision_cutoffs: dict[date, datetime]
    history: dict[int, tuple[BacktestBar, ...]]
    current_weights: dict[int, float]
    events: tuple[EventSignal, ...] = ()
    eligible_asset_ids: frozenset[int] = frozenset()
    universe_snapshot_id: int | None = None


@dataclass(frozen=True, slots=True)
class TargetAllocation:
    weights: dict[int, float]
    rationale: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    start_date: date
    end_date: date
    rebalance_frequency: RebalanceFrequency = "monthly"
    initial_capital: float = 1_000_000.0
    commission_bps: float = 2.0
    fee_bps: float = 1.0
    slippage_bps: float = 5.0
    annual_risk_free_rate: float = 0.0
    require_adjusted_prices: bool = True
    maximum_stale_sessions: int = 5
    minimum_sessions: int = 20
    decision_delay_minutes: int = 60
    require_verified_calendar: bool = True
    require_explicit_open_tradability: bool = True
    liquidity_lookback_sessions: int = 20
    minimum_liquidity_observations: int = 10
    maximum_adv_participation: float = 0.05
    require_pit_universe: bool = False

    def __post_init__(self) -> None:
        if self.start_date >= self.end_date:
            raise ValueError("start_date must be before end_date")
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if min(self.commission_bps, self.fee_bps, self.slippage_bps) < 0:
            raise ValueError("cost and slippage assumptions cannot be negative")
        if self.total_cost_rate >= 1:
            raise ValueError("combined proportional trading cost must be below 100%")
        if self.annual_risk_free_rate <= -1:
            raise ValueError("annual_risk_free_rate must be greater than -100%")
        if self.maximum_stale_sessions < 0:
            raise ValueError("maximum_stale_sessions cannot be negative")
        if self.minimum_sessions < 2:
            raise ValueError("minimum_sessions must be at least 2")
        if not 0 <= self.decision_delay_minutes <= 360:
            raise ValueError("decision_delay_minutes must be between 0 and 360")
        if self.liquidity_lookback_sessions < 2:
            raise ValueError("liquidity_lookback_sessions must be at least 2")
        if not 1 <= self.minimum_liquidity_observations <= (self.liquidity_lookback_sessions):
            raise ValueError("minimum liquidity observations must fit the lookback window")
        if not 0 < self.maximum_adv_participation <= 1:
            raise ValueError("maximum ADV participation must be in (0, 1]")

    @property
    def total_cost_rate(self) -> float:
        return (self.commission_bps + self.fee_bps + self.slippage_bps) / 10_000


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    severity: ValidationSeverity
    code: str
    message: str
    asset_id: int | None = None
    trade_date: date | None = None


@dataclass(frozen=True, slots=True)
class DailyPortfolioPoint:
    trade_date: date
    nav: float
    daily_return: float
    drawdown: float
    gross_exposure: float
    cash: float


@dataclass(frozen=True, slots=True)
class RebalanceRecord:
    signal_date: date
    execution_date: date
    status: RebalanceStatus
    turnover: float
    transaction_cost: float
    nav_before: float
    nav_after: float
    target_weights: dict[int, float]
    rationale: tuple[str, ...]
    rejection_reason: str | None = None


@dataclass(frozen=True, slots=True)
class HoldingPeriodResult:
    start_date: date
    end_date: date
    net_return: float
    session_count: int = 0
    is_closed: bool = True


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    total_return: float
    annualized_return: float
    annualized_volatility: float
    sharpe_ratio: float | None
    sortino_ratio: float | None
    maximum_drawdown: float
    period_win_rate: float | None
    period_profit_loss_ratio: float | None
    total_turnover: float
    average_turnover: float
    total_transaction_cost: float
    annual_returns: dict[int, float]


@dataclass(frozen=True, slots=True)
class BacktestResult:
    run_id: int | None
    strategy_name: str
    strategy_parameters: dict[str, object]
    market: str
    start_date: date
    end_date: date
    data_fingerprint: str
    points: tuple[DailyPortfolioPoint, ...]
    rebalances: tuple[RebalanceRecord, ...]
    holding_periods: tuple[HoldingPeriodResult, ...]
    metrics: BacktestMetrics
    validation_issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)
