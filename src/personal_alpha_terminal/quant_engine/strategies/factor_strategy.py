from dataclasses import dataclass, field

from personal_alpha_terminal.quant_engine.strategies.base_strategy import (
    BaseStrategy,
    StrategyContext,
)


@dataclass(slots=True)
class FactorStrategy(BaseStrategy):
    scores: dict[tuple[str, str], float] = field(default_factory=dict)
    entry_threshold: float = 70.0
    exit_threshold: float = 45.0
    name: str = "factor"

    def _score(self, context: StrategyContext) -> float | None:
        return self.scores.get((context.ticker, context.as_of.isoformat()))

    def buy_signal(self, context: StrategyContext) -> bool:
        score = self._score(context)
        return score is not None and score >= self.entry_threshold

    def sell_signal(self, context: StrategyContext) -> bool:
        score = self._score(context)
        return score is not None and score <= self.exit_threshold
