from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import floor
from typing import Any

import pandas as pd

from personal_alpha_terminal.quant_engine.backtest.performance import (
    BacktestPerformance,
    evaluate_equity_curve,
)
from personal_alpha_terminal.quant_engine.strategies.base_strategy import (
    BaseStrategy,
    StrategyContext,
    StrategySignal,
)
from personal_alpha_terminal.research.data_gate import (
    ResearchDataAuthorization,
    ResearchDataGate,
    ResearchPurpose,
)


@dataclass(frozen=True, slots=True)
class TradeLogEntry:
    trade_date: date
    ticker: str
    action: str
    price: float
    quantity: float
    reason: str


@dataclass(frozen=True, slots=True)
class BacktraderResult:
    strategy: str
    performance: BacktestPerformance
    trades: tuple[TradeLogEntry, ...]
    equity: pd.Series
    execution_policy: str = "signal at T close; Backtrader market order fills next bar"


class BacktraderEngine:
    def run(
        self,
        *,
        authorization: ResearchDataAuthorization,
        ticker: str,
        bars: pd.DataFrame,
        strategy: BaseStrategy,
        initial_cash: float = 100_000.0,
        commission_rate: float = 0.0002,
        slippage_rate: float = 0.0005,
    ) -> BacktraderResult:
        ResearchDataGate.require(authorization, ResearchPurpose.BACKTEST)
        frame = _validated_frame(bars)
        if initial_cash <= 0 or commission_rate < 0 or slippage_rate < 0:
            raise ValueError("cash must be positive and costs cannot be negative")
        bt = _backtrader()
        strategy.initialize((ticker,))
        outer_strategy = strategy

        class ManagedStrategy(bt.Strategy):  # type: ignore[misc,name-defined]
            params = (("ticker", ticker),)

            def __init__(self) -> None:
                self.history: list[float] = []
                self.trade_log: list[TradeLogEntry] = []
                self.equity_dates: list[date] = []
                self.equity_values: list[float] = []
                self.pending_reason: str | None = None
                self.order: Any | None = None

            def next(self) -> None:
                self.history.append(float(self.data.close[0]))
                current_date = self.data.datetime.date(0)
                self.equity_dates.append(current_date)
                self.equity_values.append(float(self.broker.getvalue()))
                if self.order is not None:
                    return
                context = StrategyContext(
                    ticker=self.p.ticker,
                    as_of=current_date,
                    close_history=tuple(self.history),
                    current_position=float(self.position.size),
                )
                signal = outer_strategy.signal(context)
                if signal is StrategySignal.BUY:
                    budget = outer_strategy.position_size(context, float(self.broker.getcash()))
                    quantity = floor(budget / float(self.data.close[0]))
                    if quantity > 0:
                        self.pending_reason = outer_strategy.reason(context, signal)
                        self.order = self.buy(size=quantity)
                elif signal is StrategySignal.SELL:
                    self.pending_reason = outer_strategy.reason(context, signal)
                    self.order = self.close()

            def notify_order(self, order: Any) -> None:
                if order.status in {order.Submitted, order.Accepted}:
                    return
                if order.status == order.Completed:
                    self.trade_log.append(
                        TradeLogEntry(
                            trade_date=self.data.datetime.date(0),
                            ticker=self.p.ticker,
                            action="BUY" if order.isbuy() else "SELL",
                            price=float(order.executed.price),
                            quantity=abs(float(order.executed.size)),
                            reason=self.pending_reason or "deterministic strategy signal",
                        )
                    )
                self.order = None
                self.pending_reason = None

        cerebro = bt.Cerebro(stdstats=False)
        cerebro.broker.setcash(initial_cash)
        cerebro.broker.setcommission(commission=commission_rate)
        cerebro.broker.set_slippage_perc(slippage_rate, slip_open=True)
        cerebro.broker.set_coc(False)
        cerebro.adddata(bt.feeds.PandasData(dataname=frame), name=ticker)
        cerebro.addstrategy(ManagedStrategy)
        instance = cerebro.run(runonce=True)[0]
        equity = pd.Series(
            instance.equity_values,
            index=pd.DatetimeIndex(instance.equity_dates),
            name="equity",
            dtype=float,
        )
        return BacktraderResult(
            strategy=strategy.name,
            performance=evaluate_equity_curve(equity),
            trades=tuple(instance.trade_log),
            equity=equity,
        )


def _validated_frame(bars: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(bars.columns.str.lower())
    if missing:
        raise ValueError(f"Backtrader bars are missing columns: {sorted(missing)}")
    frame = bars.copy()
    frame.columns = [str(column).lower() for column in frame.columns]
    frame = frame.sort_index()
    if frame.index.has_duplicates or not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError("Backtrader bars require a unique DatetimeIndex")
    if bool((frame[["open", "high", "low", "close"]] <= 0).any().any()):
        raise ValueError("Backtrader OHLC prices must be positive")
    return frame


def _backtrader() -> Any:
    try:
        import backtrader as bt
    except ImportError as error:
        raise RuntimeError("Backtrader is optional; install the quant-backends extra") from error
    return bt
