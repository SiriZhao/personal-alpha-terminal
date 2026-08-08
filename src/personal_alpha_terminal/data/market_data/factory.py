from sqlalchemy.orm import Session

from personal_alpha_terminal.core.config import Settings, get_settings
from personal_alpha_terminal.data.market_data.ports import MarketDataProvider
from personal_alpha_terminal.data.market_data.providers import (
    AKShareBondAdapter,
    AKShareETFAdapter,
    AKShareIndexAdapter,
    AKShareStockAdapter,
    StooqETFAdapter,
    StooqStockAdapter,
    YahooBondAdapter,
    YahooETFAdapter,
    YahooIndexAdapter,
    YahooStockAdapter,
)
from personal_alpha_terminal.data.market_data.repository import PriceRepository
from personal_alpha_terminal.data.market_data.service import MarketDataEngine


def build_market_data_engine(
    session: Session,
    settings: Settings | None = None,
) -> MarketDataEngine:
    effective_settings = settings or get_settings()
    repository = PriceRepository(session)
    repository.sync_provider_capabilities()
    providers: list[MarketDataProvider] = [
        AKShareStockAdapter(),
        AKShareETFAdapter(),
        AKShareIndexAdapter(),
        AKShareBondAdapter(),
        YahooStockAdapter(
            timeout_seconds=effective_settings.market_data_timeout_seconds,
            cache_dir=effective_settings.market_data_provider_cache_dir / "yfinance",
        ),
        YahooETFAdapter(
            timeout_seconds=effective_settings.market_data_timeout_seconds,
            cache_dir=effective_settings.market_data_provider_cache_dir / "yfinance",
        ),
        YahooIndexAdapter(
            timeout_seconds=effective_settings.market_data_timeout_seconds,
            cache_dir=effective_settings.market_data_provider_cache_dir / "yfinance",
        ),
        YahooBondAdapter(
            timeout_seconds=effective_settings.market_data_timeout_seconds,
            cache_dir=effective_settings.market_data_provider_cache_dir / "yfinance",
        ),
        StooqStockAdapter(timeout_seconds=effective_settings.market_data_timeout_seconds),
        StooqETFAdapter(timeout_seconds=effective_settings.market_data_timeout_seconds),
    ]
    return MarketDataEngine(
        providers=providers,
        repository=repository,
        settings=effective_settings,
    )
