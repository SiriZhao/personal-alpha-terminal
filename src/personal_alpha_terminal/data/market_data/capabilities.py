from decimal import Decimal
from typing import Literal

from personal_alpha_terminal.data.market_data.contracts import AssetType, ProviderCapability


def _yahoo_capabilities(
    market: Literal["HK", "US"],
) -> tuple[ProviderCapability, ...]:
    return (
        ProviderCapability(
            provider="yahoo_finance",
            market=market,
            asset_type="stock",
            endpoint="yfinance.download",
            raw_volume_unit="share",
            volume_unit="share",
            price_type="unadjusted_ohlcv",
            supported=True,
            volume_multiplier=Decimal("1"),
            raw_share_unit=Decimal("1"),
        ),
        ProviderCapability(
            provider="yahoo_finance",
            market=market,
            asset_type="etf",
            endpoint="yfinance.download",
            raw_volume_unit="share",
            volume_unit="share",
            price_type="unadjusted_ohlcv",
            supported=True,
            volume_multiplier=Decimal("1"),
            raw_share_unit=Decimal("1"),
        ),
        ProviderCapability(
            provider="yahoo_finance",
            market=market,
            asset_type="index",
            endpoint="yfinance.download",
            raw_volume_unit="none",
            volume_unit="none",
            price_type="index_level_ohlcv",
            supported=True,
            volume_multiplier=Decimal("1"),
            raw_share_unit=Decimal("1"),
        ),
        ProviderCapability(
            provider="yahoo_finance",
            market=market,
            asset_type="bond",
            endpoint="yfinance.download",
            raw_volume_unit="unknown",
            volume_unit="face_value",
            price_type="clean_price_ohlcv",
            supported=False,
            volume_multiplier=Decimal("1"),
            raw_share_unit=Decimal("1"),
        ),
    )


def _stooq_capabilities() -> tuple[ProviderCapability, ...]:
    asset_types: tuple[AssetType, ...] = ("stock", "etf")
    return tuple(
        ProviderCapability(
            provider="stooq",
            market="US",
            asset_type=asset_type,
            endpoint="stooq_daily_csv",
            raw_volume_unit="share",
            volume_unit="share",
            # Stooq is a fallback research feed. Its historical-adjustment
            # lineage is not treated as PIT corporate-action certification.
            price_type="unadjusted_ohlcv",
            supported=True,
            volume_multiplier=Decimal("1"),
            raw_share_unit=Decimal("1"),
        )
        for asset_type in asset_types
    )

PROVIDER_CAPABILITIES: tuple[ProviderCapability, ...] = (
    ProviderCapability(
        provider="akshare",
        market="A",
        asset_type="stock",
        endpoint="stock_zh_a_hist",
        raw_volume_unit="share",
        volume_unit="share",
        price_type="unadjusted_ohlcv",
        supported=True,
        volume_multiplier=Decimal("1"),
        raw_share_unit=Decimal("1"),
    ),
    ProviderCapability(
        provider="akshare",
        market="A",
        asset_type="etf",
        endpoint="fund_etf_hist_em",
        raw_volume_unit="unknown",
        volume_unit="share",
        price_type="unadjusted_ohlcv",
        supported=False,
        volume_multiplier=Decimal("1"),
        raw_share_unit=Decimal("1"),
    ),
    ProviderCapability(
        provider="akshare",
        market="A",
        asset_type="index",
        endpoint="stock_zh_index_daily",
        raw_volume_unit="unknown",
        volume_unit="share",
        price_type="index_level_ohlcv",
        supported=False,
        volume_multiplier=Decimal("1"),
        raw_share_unit=Decimal("1"),
    ),
    ProviderCapability(
        provider="akshare",
        market="A",
        asset_type="bond",
        endpoint="UNVERIFIED_A_BOND_ENDPOINT",
        raw_volume_unit="unknown",
        volume_unit="face_value",
        price_type="clean_price_ohlcv",
        supported=False,
        volume_multiplier=Decimal("1"),
        raw_share_unit=Decimal("1"),
    ),
    *_yahoo_capabilities("HK"),
    *_yahoo_capabilities("US"),
    *_stooq_capabilities(),
)

CAPABILITY_BY_PROVIDER_MARKET_ASSET = {item.key: item for item in PROVIDER_CAPABILITIES}

if len(CAPABILITY_BY_PROVIDER_MARKET_ASSET) != len(PROVIDER_CAPABILITIES):
    raise RuntimeError("provider capability keys must be unique")


def capability_for(
    provider: str,
    market: str,
    asset_type: str,
) -> ProviderCapability:
    try:
        return CAPABILITY_BY_PROVIDER_MARKET_ASSET[(provider, market, asset_type)]  # type: ignore[index]
    except KeyError as error:
        raise ValueError(
            f"no provider capability for provider={provider} market={market} "
            f"asset_type={asset_type}"
        ) from error
