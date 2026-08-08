from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from personal_alpha_terminal.data.market_data.capabilities import (
    PROVIDER_CAPABILITIES,
    capability_for,
)
from personal_alpha_terminal.data.market_data.contracts import (
    AssetPriceRequest,
    ProviderCapability,
    ProviderRawBar,
    ProviderRawBatch,
)
from personal_alpha_terminal.data.market_data.exceptions import ProviderRequestError
from personal_alpha_terminal.data.market_data.normalization import PriceNormalizer
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
from personal_alpha_terminal.data.market_data.schemas import (
    ETFPriceBar,
    PriceBar,
    StockPriceBar,
)


def _raw_batch(
    capability: ProviderCapability,
    *,
    symbol: str,
    currency: str,
    volume: str = "25",
) -> ProviderRawBatch:
    request = AssetPriceRequest(
        symbol=symbol,
        market=capability.market,
        asset_type=capability.asset_type,
        price_currency=currency,
        start_date=date(2026, 7, 29),
        end_date=date(2026, 7, 29),
    )
    row = ProviderRawBar(
        symbol=symbol,
        market=capability.market,
        asset_type=capability.asset_type,
        date=date(2026, 7, 29),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10.5"),
        volume=Decimal(volume),
        raw_volume_unit=capability.raw_volume_unit,
        price_currency=currency,
        raw_share_unit=capability.raw_share_unit,
        price_type=capability.price_type,
    )
    return ProviderRawBatch(capability, request, (row,))


@pytest.mark.parametrize(
    ("capability", "symbol", "currency", "schema"),
    (
        (capability_for("akshare", "A", "stock"), "000001", "CNY", StockPriceBar),
        (
            ProviderCapability(
                provider="contract_fixture",
                market="A",
                asset_type="etf",
                endpoint="verified_etf_fixture",
                raw_volume_unit="share",
                volume_unit="share",
                price_type="unadjusted_ohlcv",
                supported=True,
                volume_multiplier=Decimal("1"),
                raw_share_unit=Decimal("1"),
            ),
            "510300",
            "CNY",
            ETFPriceBar,
        ),
        (
            capability_for("yahoo_finance", "HK", "stock"),
            "00700",
            "HKD",
            StockPriceBar,
        ),
        (
            capability_for("yahoo_finance", "US", "stock"),
            "AAPL",
            "USD",
            StockPriceBar,
        ),
    ),
)
def test_cross_market_contracts_normalize_to_base_share_units(
    capability: ProviderCapability,
    symbol: str,
    currency: str,
    schema: type[PriceBar],
) -> None:
    bar = PriceNormalizer().normalize(
        _raw_batch(capability, symbol=symbol, currency=currency)
    )[0]

    assert type(bar) is schema
    assert bar.asset_type == capability.asset_type
    assert bar.volume == 25
    assert bar.volume_unit == "share"
    assert bar.share_unit == Decimal("1")
    assert bar.price_currency == currency


def test_a_share_daily_volume_is_not_multiplied_by_one_hundred() -> None:
    capability = capability_for("akshare", "A", "stock")
    bar = PriceNormalizer().normalize(
        _raw_batch(capability, symbol="000001", currency="CNY", volume="1234")
    )[0]

    assert capability.raw_volume_unit == "share"
    assert capability.volume_multiplier == Decimal("1")
    assert bar.volume == 1_234


def test_raw_unit_mismatch_is_rejected_before_validation_or_persistence() -> None:
    capability = capability_for("yahoo_finance", "US", "stock")
    batch = _raw_batch(capability, symbol="AAPL", currency="USD")
    wrong_row = replace(
        batch.rows[0],
        raw_volume_unit="hand",
        raw_share_unit=Decimal("100"),
    )

    with pytest.raises(ValueError, match="raw volume unit violates"):
        PriceNormalizer().normalize(replace(batch, rows=(wrong_row,)))


def test_normalized_price_schema_rejects_provider_hand_units() -> None:
    capability = capability_for("akshare", "A", "stock")
    bar = PriceNormalizer().normalize(
        _raw_batch(capability, symbol="000001", currency="CNY")
    )[0]

    with pytest.raises(ValueError, match="volume_unit must be share"):
        replace(bar, volume_unit="hand")  # type: ignore[arg-type]


def test_every_asset_uses_an_explicit_adapter_and_unique_capability() -> None:
    adapters = (
        AKShareStockAdapter(),
        AKShareETFAdapter(),
        AKShareIndexAdapter(),
        AKShareBondAdapter(),
        YahooStockAdapter(),
        YahooETFAdapter(),
        YahooIndexAdapter(),
        YahooBondAdapter(),
        StooqStockAdapter(),
        StooqETFAdapter(),
    )
    adapter_keys = [capability.key for adapter in adapters for capability in adapter.capabilities]

    assert len(adapter_keys) == len(set(adapter_keys))
    assert set(adapter_keys) == {capability.key for capability in PROVIDER_CAPABILITIES}
    assert all(
        all(capability.asset_type == adapter.asset_type for capability in adapter.capabilities)
        for adapter in adapters
    )


def test_a_etf_adapter_fails_closed_until_volume_unit_is_documented() -> None:
    capability = capability_for("akshare", "A", "etf")
    request = AssetPriceRequest(
        symbol="510300",
        market="A",
        asset_type="etf",
        price_currency="CNY",
        start_date=date(2026, 7, 29),
        end_date=date(2026, 7, 29),
    )

    assert capability.endpoint == "fund_etf_hist_em"
    assert capability.raw_volume_unit == "unknown"
    assert not capability.supported
    with pytest.raises(ProviderRequestError, match="not certified"):
        AKShareETFAdapter().fetch_raw(request)
