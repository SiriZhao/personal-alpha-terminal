from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class StrategySignal(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True, slots=True)
class StrategyContext:
    ticker: str
    as_of: date
    close_history: tuple[float, ...]
    current_position: float


class BaseStrategy(ABC):
    name: str

    def initialize(self, tickers: tuple[str, ...]) -> None:
        if not tickers:
            raise ValueError("strategy universe cannot be empty")

    @abstractmethod
    def buy_signal(self, context: StrategyContext) -> bool: ...

    @abstractmethod
    def sell_signal(self, context: StrategyContext) -> bool: ...

    def position_size(self, context: StrategyContext, available_cash: float) -> float:
        if available_cash < 0:
            raise ValueError("available_cash cannot be negative")
        return available_cash

    def signal(self, context: StrategyContext) -> StrategySignal:
        if context.current_position <= 0 and self.buy_signal(context):
            return StrategySignal.BUY
        if context.current_position > 0 and self.sell_signal(context):
            return StrategySignal.SELL
        return StrategySignal.HOLD

    def reason(self, context: StrategyContext, signal: StrategySignal) -> str:
        return f"{self.name}:{signal.value}:as_of={context.as_of.isoformat()}"
