from dataclasses import dataclass

from personal_alpha_terminal.quant_engine.strategies.base_strategy import (
    BaseStrategy,
    StrategyContext,
)


@dataclass(slots=True)
class MomentumStrategy(BaseStrategy):
    lookback: int = 63
    exit_lookback: int = 21
    name: str = "momentum"

    def __post_init__(self) -> None:
        if self.lookback < 2 or self.exit_lookback < 2:
            raise ValueError("momentum lookbacks must be at least two")

    def buy_signal(self, context: StrategyContext) -> bool:
        values = context.close_history
        return len(values) > self.lookback and values[-1] > values[-1 - self.lookback]

    def sell_signal(self, context: StrategyContext) -> bool:
        values = context.close_history
        return len(values) > self.exit_lookback and values[-1] < values[-1 - self.exit_lookback]
