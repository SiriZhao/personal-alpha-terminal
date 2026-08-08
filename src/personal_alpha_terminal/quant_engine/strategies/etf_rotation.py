from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ETFRotationSelection:
    as_of: str
    selected: tuple[str, ...]
    scores: dict[str, float]


@dataclass(slots=True)
class ETFRotationStrategy:
    top_n: int = 2
    minimum_score: float = 0.0
    name: str = "etf_rotation"
    _last_selection: tuple[str, ...] = field(default_factory=tuple, init=False)

    def select(self, *, as_of: str, trailing_returns: dict[str, float]) -> ETFRotationSelection:
        if self.top_n < 1:
            raise ValueError("top_n must be positive")
        eligible = [item for item in trailing_returns.items() if item[1] >= self.minimum_score]
        ranked = sorted(eligible, key=lambda item: item[1], reverse=True)
        selected = tuple(symbol for symbol, _ in ranked[: self.top_n])
        self._last_selection = selected
        return ETFRotationSelection(as_of, selected, dict(trailing_returns))
