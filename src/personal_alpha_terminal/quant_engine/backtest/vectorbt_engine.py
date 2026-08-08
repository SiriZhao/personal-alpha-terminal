from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any

import pandas as pd

from personal_alpha_terminal.quant_engine.backtest.performance import (
    BacktestPerformance,
    evaluate_equity_curve,
)
from personal_alpha_terminal.research.data_gate import (
    ResearchDataAuthorization,
    ResearchDataGate,
    ResearchPurpose,
)


@dataclass(frozen=True, slots=True)
class VectorBTConfig:
    initial_cash: float = 100_000.0
    commission_bps: float = 2.0
    spread_bps: float = 4.0
    slippage_bps: float = 3.0
    annual_risk_free_rate: float = 0.0

    def __post_init__(self) -> None:
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        if min(self.commission_bps, self.spread_bps, self.slippage_bps) < 0:
            raise ValueError("cost assumptions cannot be negative")

    @property
    def fee_rate(self) -> float:
        return self.commission_bps / 10_000

    @property
    def slippage_rate(self) -> float:
        return (self.spread_bps / 2 + self.slippage_bps) / 10_000


@dataclass(frozen=True, slots=True)
class VectorBTResult:
    strategy: str
    parameters: dict[str, int | float | str]
    performance: BacktestPerformance
    trade_count: int
    trade_win_rate: float | None
    total_cost: float
    equity: pd.Series
    execution_policy: str = "signal at T close; execution at T+1 supplied price"


@dataclass(frozen=True, slots=True)
class MAOptimizationResult:
    selected_parameters: dict[str, int]
    training_result: VectorBTResult
    validation_result: VectorBTResult
    candidates_evaluated: int
    selection_rule: str


class VectorBTEngine:
    """Fast research adapter; the audited event-driven engine remains canonical."""

    def __init__(self, config: VectorBTConfig | None = None) -> None:
        self.config = config or VectorBTConfig()

    def run_moving_average(
        self,
        *,
        authorization: ResearchDataAuthorization,
        close: pd.Series,
        execution_price: pd.Series,
        fast_window: int,
        slow_window: int,
    ) -> VectorBTResult:
        ResearchDataGate.require(authorization, ResearchPurpose.BACKTEST)
        if fast_window < 2 or slow_window <= fast_window:
            raise ValueError("moving-average windows require 2 <= fast < slow")
        prices = _aligned_prices(close, execution_price)
        signal = prices["close"].rolling(fast_window).mean() > prices["close"].rolling(
            slow_window
        ).mean()
        # A signal derived from T close can first become an order on the following bar.
        entries = (signal & ~signal.shift(1, fill_value=False)).shift(1, fill_value=False)
        exits = ((~signal) & signal.shift(1, fill_value=False)).shift(1, fill_value=False)
        portfolio = _vectorbt().Portfolio.from_signals(
            prices["execution"],
            entries=entries,
            exits=exits,
            init_cash=self.config.initial_cash,
            fees=self.config.fee_rate,
            slippage=self.config.slippage_rate,
            freq="1D",
        )
        return self._result(
            portfolio,
            strategy="moving_average",
            parameters={"fast_window": fast_window, "slow_window": slow_window},
        )

    def run_momentum(
        self,
        *,
        authorization: ResearchDataAuthorization,
        close: pd.Series,
        execution_price: pd.Series,
        lookback: int,
    ) -> VectorBTResult:
        if lookback < 2:
            raise ValueError("momentum lookback must be at least two")
        prices = _aligned_prices(close, execution_price)
        signal = prices["close"].pct_change(lookback) > 0
        return self._run_long_signal(
            authorization=authorization,
            prices=prices,
            signal=signal,
            strategy="momentum",
            parameters={"lookback": lookback},
        )

    def run_target_weights(
        self,
        *,
        authorization: ResearchDataAuthorization,
        execution_prices: pd.DataFrame,
        target_weights: pd.DataFrame,
        strategy: str,
    ) -> VectorBTResult:
        """Run precomputed ETF/factor weights; weights from T execute on T+1."""
        ResearchDataGate.require(authorization, ResearchPurpose.BACKTEST)
        prices, weights = execution_prices.astype(float).align(
            target_weights.astype(float), join="inner", axis=0
        )
        prices, weights = prices.align(weights, join="inner", axis=1)
        if prices.empty or bool((prices <= 0).any().any()):
            raise ValueError("positive aligned execution prices are required")
        if bool((weights.fillna(0) < 0).any().any()) or bool(
            (weights.fillna(0).sum(axis=1) > 1 + 1e-12).any()
        ):
            raise ValueError("target weights must be long-only and sum to at most one")
        execution_weights = weights.shift(1)
        portfolio = _vectorbt().Portfolio.from_orders(
            prices,
            size=execution_weights,
            size_type="targetpercent",
            init_cash=self.config.initial_cash,
            fees=self.config.fee_rate,
            slippage=self.config.slippage_rate,
            cash_sharing=True,
            group_by=True,
            call_seq="auto",
            freq="1D",
        )
        return self._result(
            portfolio,
            strategy=strategy,
            parameters={"assets": len(prices.columns)},
        )

    def _run_long_signal(
        self,
        *,
        authorization: ResearchDataAuthorization,
        prices: pd.DataFrame,
        signal: pd.Series,
        strategy: str,
        parameters: dict[str, int | float | str],
    ) -> VectorBTResult:
        ResearchDataGate.require(authorization, ResearchPurpose.BACKTEST)
        entries = (signal & ~signal.shift(1, fill_value=False)).shift(1, fill_value=False)
        exits = ((~signal) & signal.shift(1, fill_value=False)).shift(1, fill_value=False)
        portfolio = _vectorbt().Portfolio.from_signals(
            prices["execution"],
            entries=entries,
            exits=exits,
            init_cash=self.config.initial_cash,
            fees=self.config.fee_rate,
            slippage=self.config.slippage_rate,
            freq="1D",
        )
        return self._result(
            portfolio,
            strategy=strategy,
            parameters=parameters,
        )

    def optimize_moving_average(
        self,
        *,
        authorization: ResearchDataAuthorization,
        close: pd.Series,
        execution_price: pd.Series,
        windows: tuple[int, ...] = (20, 50, 100, 200),
        training_fraction: float = 0.7,
        maximum_training_drawdown: float = -0.5,
    ) -> MAOptimizationResult:
        ResearchDataGate.require(authorization, ResearchPurpose.BACKTEST)
        if not 0.5 <= training_fraction <= 0.9:
            raise ValueError("training_fraction must be between 0.5 and 0.9")
        prices = _aligned_prices(close, execution_price)
        split = int(len(prices) * training_fraction)
        if split < max(windows) + 2 or len(prices) - split < 2:
            raise ValueError("insufficient observations for train/validation optimization")
        train = prices.iloc[:split]
        validation_start = max(0, split - max(windows))
        validation = prices.iloc[validation_start:]
        candidates: list[tuple[float, VectorBTResult]] = []
        for fast, slow in product(sorted(set(windows)), repeat=2):
            if fast >= slow:
                continue
            result = self.run_moving_average(
                authorization=authorization,
                close=train["close"],
                execution_price=train["execution"],
                fast_window=fast,
                slow_window=slow,
            )
            metrics = result.performance
            if metrics.maximum_drawdown < maximum_training_drawdown:
                continue
            score = (metrics.sharpe_ratio or -10.0) + metrics.annualized_return - abs(
                metrics.maximum_drawdown
            )
            candidates.append((score, result))
        if not candidates:
            raise ValueError("no moving-average candidate passed the training risk gate")
        _, selected = max(candidates, key=lambda item: item[0])
        validation_result = self.run_moving_average(
            authorization=authorization,
            close=validation["close"],
            execution_price=validation["execution"],
            fast_window=int(selected.parameters["fast_window"]),
            slow_window=int(selected.parameters["slow_window"]),
        )
        return MAOptimizationResult(
            selected_parameters={
                "fast_window": int(selected.parameters["fast_window"]),
                "slow_window": int(selected.parameters["slow_window"]),
            },
            training_result=selected,
            validation_result=validation_result,
            candidates_evaluated=len(candidates),
            selection_rule="training Sharpe + CAGR - absolute drawdown; validation not optimized",
        )

    def _result(
        self,
        portfolio: Any,
        *,
        strategy: str,
        parameters: dict[str, int | float | str],
    ) -> VectorBTResult:
        equity = portfolio.value().astype(float)
        if isinstance(equity, pd.DataFrame):
            if equity.shape[1] != 1:
                raise ValueError("VectorBT result must resolve to one cash-sharing portfolio")
            equity = equity.iloc[:, 0]
        performance = evaluate_equity_curve(
            equity,
            annual_risk_free_rate=self.config.annual_risk_free_rate,
        )
        records = portfolio.orders.records_readable
        trade_records = portfolio.trades.records_readable
        trade_count = int(len(trade_records))
        win_rate = None
        if trade_count and "Return" in trade_records:
            win_rate = float((trade_records["Return"] > 0).mean())
        total_cost = 0.0
        if len(records) and "Fees" in records:
            total_cost = float(records["Fees"].sum())
        return VectorBTResult(
            strategy=strategy,
            parameters=parameters,
            performance=performance,
            trade_count=trade_count,
            trade_win_rate=win_rate,
            total_cost=total_cost,
            equity=equity,
        )


def _aligned_prices(close: pd.Series, execution_price: pd.Series) -> pd.DataFrame:
    frame = pd.concat(
        [close.astype(float).rename("close"), execution_price.astype(float).rename("execution")],
        axis=1,
        join="inner",
    ).dropna()
    if len(frame) < 3 or bool((frame <= 0).any().any()):
        raise ValueError("positive aligned close and execution prices are required")
    if not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise ValueError("price index must be unique and increasing")
    return frame


def _vectorbt() -> Any:
    try:
        import vectorbt as vbt
    except ImportError as error:
        raise RuntimeError("VectorBT is optional; install the quant-backends extra") from error
    return vbt
