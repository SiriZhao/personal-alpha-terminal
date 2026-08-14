from collections.abc import Generator, Iterable
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personal_alpha_terminal.core.market_time import normalize_utc
from personal_alpha_terminal.data.market_data.capabilities import PROVIDER_CAPABILITIES
from personal_alpha_terminal.data.market_data.schemas import (
    Market,
    PriceBar,
    UpsertResult,
)
from personal_alpha_terminal.models import Price, ProviderCapabilityRecord, Stock


class PriceRepository:
    """Persistence boundary for the normalized stock master and daily bars."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_active_stocks(
        self,
        *,
        markets: set[Market] | None = None,
        symbols: set[str] | None = None,
    ) -> list[Stock]:
        statement = select(Stock).where(Stock.is_active.is_(True))
        if markets:
            statement = statement.where(Stock.market.in_(sorted(markets)))
        if symbols:
            statement = statement.where(Stock.symbol.in_(sorted(symbols)))
        return list(self._session.scalars(statement.order_by(Stock.market, Stock.symbol)))

    def sync_provider_capabilities(self) -> None:
        """Persist the code-reviewed capability matrix without importing market data."""

        existing = {
            (item.provider, item.market, item.asset_type): item
            for item in self._session.scalars(select(ProviderCapabilityRecord))
        }
        expected_keys = {item.key for item in PROVIDER_CAPABILITIES}
        unexpected = sorted(set(existing) - expected_keys)
        if unexpected:
            raise ValueError(
                "database contains provider capabilities absent from the reviewed registry: "
                f"{unexpected}"
            )
        for capability in PROVIDER_CAPABILITIES:
            record = existing.get(capability.key)
            if record is None:
                record = ProviderCapabilityRecord(
                    provider=capability.provider,
                    market=capability.market,
                    asset_type=capability.asset_type,
                    endpoint=capability.endpoint,
                    raw_volume_unit=capability.raw_volume_unit,
                    volume_unit=capability.volume_unit,
                    price_type=capability.price_type,
                    supported=capability.supported,
                    volume_multiplier=capability.volume_multiplier,
                    raw_share_unit=capability.raw_share_unit,
                )
                self._session.add(record)
                continue
            record.endpoint = capability.endpoint
            record.raw_volume_unit = capability.raw_volume_unit
            record.volume_unit = capability.volume_unit
            record.price_type = capability.price_type
            record.supported = capability.supported
            record.volume_multiplier = capability.volume_multiplier
            record.raw_share_unit = capability.raw_share_unit
        self._session.flush()

    def price_date_bounds(self, stock_id: int, source: str) -> tuple[date | None, date | None]:
        """Return the stored source window used to prove a resumable cache complete."""
        statement = select(func.min(Price.trade_date), func.max(Price.trade_date)).where(
            Price.stock_id == stock_id,
            Price.source == source,
        )
        earliest, latest = self._session.execute(statement).one()
        return earliest, latest

    def price_date_bounds_batch(
        self, stock_ids: Iterable[int], source: str
    ) -> dict[int, tuple[date | None, date | None]]:
        """Batch price bounds for many stocks in one GROUP BY query.

        ROUND25 PHASE 13: the per-symbol ``price_date_bounds`` call is an N+1
        hot path for 5000+ securities; this method collapses the whole lookup
        into a single indexed aggregation.
        """

        ids = [int(stock_id) for stock_id in stock_ids if stock_id is not None]
        bounds: dict[int, tuple[date | None, date | None]] = {
            stock_id: (None, None) for stock_id in ids
        }
        if not ids:
            return bounds
        statement = (
            select(
                Price.stock_id,
                func.min(Price.trade_date),
                func.max(Price.trade_date),
            )
            .where(
                Price.stock_id.in_(ids),
                Price.source == source,
            )
            .group_by(Price.stock_id)
        )
        for stock_id, earliest, latest in self._session.execute(statement).all():
            bounds[int(stock_id)] = (earliest, latest)
        return bounds

    def latest_price_date(self, stock_id: int, source: str) -> date | None:
        return self.price_date_bounds(stock_id, source)[1]

    def upsert_bars(
        self,
        *,
        stock: Stock,
        source: str,
        provider: str,
        bars: Iterable[PriceBar],
    ) -> UpsertResult:
        unique_bars = {bar.date: bar for bar in bars}
        if not unique_bars:
            return UpsertResult(inserted_count=0, updated_count=0)

        statement = select(Price).where(
            Price.stock_id == stock.id,
            Price.source == source,
            Price.trade_date.in_(sorted(unique_bars)),
        )
        existing_by_date = {price.trade_date: price for price in self._session.scalars(statement)}
        inserted_count = 0
        updated_count = 0

        for trade_date, bar in sorted(unique_bars.items()):
            self._validate_research_contract(stock, bar)
            existing = existing_by_date.get(trade_date)
            if existing is None:
                self._session.add(
                    Price(
                        stock_id=stock.id,
                        trade_date=bar.date,
                        open=bar.open,
                        high=bar.high,
                        low=bar.low,
                        close=bar.close,
                        adjusted_close=bar.adjusted_close,
                        forward_adjusted_close=bar.forward_adjusted_close,
                        backward_adjusted_close=bar.backward_adjusted_close,
                        volume=bar.volume,
                        asset_type=bar.asset_type,
                        volume_unit=bar.volume_unit,
                        price_currency=bar.price_currency,
                        share_unit=bar.share_unit,
                        price_type=bar.price_type,
                        data_contract_version=bar.data_contract_version,
                        source=source,
                        provider=provider,
                        adjustment_method=bar.adjustment_method,
                        event_time=bar.event_time,
                        available_time=bar.available_time,
                        open_tradable=bar.open_tradable,
                        ingested_at=bar.ingested_time,
                    )
                )
                inserted_count += 1
                continue

            if self._has_changed(existing, bar):
                existing.open = bar.open
                existing.high = bar.high
                existing.low = bar.low
                existing.close = bar.close
                existing.adjusted_close = bar.adjusted_close
                existing.forward_adjusted_close = bar.forward_adjusted_close
                existing.backward_adjusted_close = bar.backward_adjusted_close
                existing.volume = bar.volume
                existing.asset_type = bar.asset_type
                existing.volume_unit = bar.volume_unit
                existing.price_currency = bar.price_currency
                existing.share_unit = bar.share_unit
                existing.price_type = bar.price_type
                existing.data_contract_version = bar.data_contract_version
                existing.provider = provider
                existing.adjustment_method = bar.adjustment_method
                existing.event_time = bar.event_time
                existing.available_time = bar.available_time
                existing.open_tradable = bar.open_tradable
                existing.ingested_at = bar.ingested_time
                updated_count += 1

        self._session.flush()
        return UpsertResult(
            inserted_count=inserted_count,
            updated_count=updated_count,
        )

    @contextmanager
    def savepoint(self) -> Generator[None, None, None]:
        with self._session.begin_nested():
            yield

    @staticmethod
    def _has_changed(existing: Price, bar: PriceBar) -> bool:
        return any(
            (
                PriceRepository._normalized_price(existing.open)
                != PriceRepository._normalized_price(bar.open),
                PriceRepository._normalized_price(existing.high)
                != PriceRepository._normalized_price(bar.high),
                PriceRepository._normalized_price(existing.low)
                != PriceRepository._normalized_price(bar.low),
                PriceRepository._normalized_price(existing.close)
                != PriceRepository._normalized_price(bar.close),
                PriceRepository._normalized_price(existing.adjusted_close)
                != PriceRepository._normalized_price(bar.adjusted_close),
                PriceRepository._normalized_price(existing.forward_adjusted_close)
                != PriceRepository._normalized_price(bar.forward_adjusted_close),
                PriceRepository._normalized_price(existing.backward_adjusted_close)
                != PriceRepository._normalized_price(bar.backward_adjusted_close),
                existing.volume != bar.volume,
                existing.asset_type != bar.asset_type,
                existing.volume_unit != bar.volume_unit,
                existing.price_currency != bar.price_currency,
                existing.share_unit != bar.share_unit,
                existing.price_type != bar.price_type,
                existing.data_contract_version != bar.data_contract_version,
                existing.adjustment_method != bar.adjustment_method,
                PriceRepository._normalized_time(existing.event_time)
                != PriceRepository._normalized_time(bar.event_time),
                PriceRepository._normalized_time(existing.available_time)
                != PriceRepository._normalized_time(bar.available_time),
                existing.open_tradable != bar.open_tradable,
            )
        )

    @staticmethod
    def _validate_research_contract(stock: Stock, bar: PriceBar) -> None:
        if stock.asset_type != bar.asset_type:
            raise ValueError(
                f"price asset_type {bar.asset_type!r} does not match stock master "
                f"{stock.asset_type!r}"
            )
        if stock.currency.upper() != bar.price_currency:
            raise ValueError(
                f"price currency {bar.price_currency!r} does not match stock master "
                f"{stock.currency.upper()!r}"
            )
        if bar.share_unit != Decimal("1"):
            raise ValueError("research database requires normalized share_unit=1")

    @staticmethod
    def _normalized_price(value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        return value.quantize(Decimal("0.000001"))

    @staticmethod
    def _normalized_time(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return normalize_utc(value)
