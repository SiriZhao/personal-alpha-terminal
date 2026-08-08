from decimal import Decimal

from personal_alpha_terminal.core.data_timestamps import DataTimestamps, daily_bar_timestamps
from personal_alpha_terminal.data.market_data.contracts import (
    DATA_CONTRACT_VERSION,
    ProviderRawBatch,
)
from personal_alpha_terminal.data.market_data.schemas import (
    BondPriceBar,
    ETFPriceBar,
    IndexPriceBar,
    PriceBar,
    StockPriceBar,
)

SCHEMA_BY_ASSET = {
    "stock": StockPriceBar,
    "etf": ETFPriceBar,
    "index": IndexPriceBar,
    "bond": BondPriceBar,
}


class PriceNormalizer:
    """The only allowed Provider Raw -> normalized price conversion boundary."""

    def normalize(self, batch: ProviderRawBatch) -> list[PriceBar]:
        capability = batch.capability
        request = batch.request
        if not capability.supported:
            raise ValueError(
                "provider capability is not certified: "
                f"{capability.provider}/{capability.market}/{capability.asset_type}"
            )
        schema = SCHEMA_BY_ASSET[capability.asset_type]
        normalized: list[PriceBar] = []
        for raw in batch.rows:
            if (
                raw.symbol != request.symbol
                or raw.market != request.market
                or raw.asset_type != request.asset_type
            ):
                raise ValueError("raw provider row does not match the asset request")
            if raw.raw_volume_unit != capability.raw_volume_unit:
                raise ValueError(
                    "raw volume unit violates provider capability: "
                    f"received={raw.raw_volume_unit}, expected={capability.raw_volume_unit}"
                )
            if raw.raw_share_unit != capability.raw_share_unit:
                raise ValueError(
                    "raw share unit violates provider capability: "
                    f"received={raw.raw_share_unit}, expected={capability.raw_share_unit}"
                )
            if raw.price_currency != request.price_currency:
                raise ValueError(
                    "raw price currency violates instrument contract: "
                    f"received={raw.price_currency}, expected={request.price_currency}"
                )
            if raw.price_type != capability.price_type:
                raise ValueError("raw price type violates provider capability")
            volume = self._normalize_volume(raw.volume, batch)
            if any(
                value is not None
                for value in (raw.event_time, raw.available_time, raw.ingested_time)
            ):
                if None in (raw.event_time, raw.available_time, raw.ingested_time):
                    raise ValueError("provider lineage timestamps must be supplied together")
                assert raw.event_time is not None
                assert raw.available_time is not None
                assert raw.ingested_time is not None
                timestamps = DataTimestamps(
                    event_time=raw.event_time,
                    available_time=raw.available_time,
                    ingested_time=raw.ingested_time,
                )
            else:
                timestamps = daily_bar_timestamps(raw.date, raw.market)
            normalized.append(
                schema(
                    symbol=raw.symbol,
                    market=raw.market,
                    date=raw.date,
                    open=raw.open,
                    high=raw.high,
                    low=raw.low,
                    close=raw.close,
                    volume=volume,
                    event_time=timestamps.event_time,
                    available_time=timestamps.available_time,
                    ingested_time=timestamps.ingested_time,
                    adjusted_close=raw.adjusted_close,
                    forward_adjusted_close=raw.forward_adjusted_close,
                    backward_adjusted_close=raw.backward_adjusted_close,
                    adjustment_method=raw.adjustment_method,
                    open_tradable=raw.open_tradable,
                    volume_unit=capability.volume_unit,
                    price_currency=request.price_currency,
                    share_unit=Decimal("1"),
                    price_type=capability.price_type,
                    data_contract_version=DATA_CONTRACT_VERSION,
                )
            )
        return normalized

    @staticmethod
    def _normalize_volume(raw_volume: Decimal | None, batch: ProviderRawBatch) -> int | None:
        capability = batch.capability
        if capability.volume_unit == "none":
            if raw_volume not in (None, Decimal("0")):
                raise ValueError("no-volume capability received a nonzero volume")
            return None
        if raw_volume is None:
            return None
        converted = raw_volume * capability.volume_multiplier
        integral = converted.to_integral_value()
        if converted != integral:
            raise ValueError("normalized volume must be an integer base unit")
        return int(integral)
