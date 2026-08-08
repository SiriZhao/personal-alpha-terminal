"""External market-data provider adapters."""

from personal_alpha_terminal.data.market_data.providers.akshare import (
    AKShareBondAdapter,
    AKShareETFAdapter,
    AKShareIndexAdapter,
    AKShareStockAdapter,
)
from personal_alpha_terminal.data.market_data.providers.stooq import (
    StooqETFAdapter,
    StooqStockAdapter,
)
from personal_alpha_terminal.data.market_data.providers.yahoo import (
    YahooBondAdapter,
    YahooETFAdapter,
    YahooIndexAdapter,
    YahooStockAdapter,
)

__all__ = [
    "AKShareBondAdapter",
    "AKShareETFAdapter",
    "AKShareIndexAdapter",
    "AKShareStockAdapter",
    "StooqETFAdapter",
    "StooqStockAdapter",
    "YahooBondAdapter",
    "YahooETFAdapter",
    "YahooIndexAdapter",
    "YahooStockAdapter",
]
