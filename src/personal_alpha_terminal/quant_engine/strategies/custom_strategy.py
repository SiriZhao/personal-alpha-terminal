from personal_alpha_terminal.quant_engine.strategies.base_strategy import BaseStrategy


class CustomStrategy(BaseStrategy):
    """Extension point. A concrete custom strategy must implement deterministic signals."""

    name = "custom"
