"""Unified daily market-data engine.

Import concrete contracts from ``schemas``, ``service`` or ``factory``. Keeping
this package initializer side-effect free prevents provider construction from
creating circular imports in the timestamp safety layer.
"""

from typing import Any

__all__ = [
    "DailyUpdateReport",
    "InstrumentUpdateResult",
    "Market",
    "MarketDataEngine",
    "PriceBar",
    "build_market_data_engine",
]


def __getattr__(name: str) -> Any:
    if name == "build_market_data_engine":
        from personal_alpha_terminal.data.market_data.factory import (
            build_market_data_engine,
        )

        return build_market_data_engine
    if name == "MarketDataEngine":
        from personal_alpha_terminal.data.market_data.service import MarketDataEngine

        return MarketDataEngine
    if name in {
        "DailyUpdateReport",
        "InstrumentUpdateResult",
        "Market",
        "PriceBar",
    }:
        from personal_alpha_terminal.data.market_data import schemas

        return getattr(schemas, name)
    raise AttributeError(name)
