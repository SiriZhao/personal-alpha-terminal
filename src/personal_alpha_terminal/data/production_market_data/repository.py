from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.core.market_time import normalize_utc
from personal_alpha_terminal.data.market_data_quality.repository import (
    MarketDataQualityRepository,
)
from personal_alpha_terminal.data.market_data_quality.schemas import (
    ListingAgeBucket,
    SizeBucket,
    UniverseCandidate,
)
from personal_alpha_terminal.data.production_market_data.schemas import (
    SecurityMasterBatch,
    SecurityMasterRecord,
)
from personal_alpha_terminal.models import Stock


class ProductionMarketDataRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def store_security_master(self, batch: SecurityMasterBatch) -> list[Stock]:
        if normalize_utc(batch.available_time) > normalize_utc(batch.ingested_time):
            raise ValueError("security-master batch was ingested before availability")
        output: list[Stock] = []
        for record in batch.records:
            self._validate_record(record)
            stock = self._session.scalar(
                select(Stock).where(Stock.canonical_code == record.canonical_code)
            )
            if stock is None:
                stock = Stock(canonical_code=record.canonical_code, symbol=record.symbol)
                self._session.add(stock)
            elif stock.source != record.source or stock.provider != record.provider:
                raise ValueError(
                    "security-master source mixing is prohibited for "
                    f"{record.canonical_code}: {stock.source}/{stock.provider} versus "
                    f"{record.source}/{record.provider}"
                )
            stock.name = record.name
            stock.market = record.market
            stock.exchange = record.exchange
            stock.asset_type = record.security_type
            stock.currency = record.currency
            stock.timezone = record.timezone
            stock.list_date = record.listing_date
            stock.delist_date = record.delisting_date
            stock.is_active = record.is_active
            stock.source = record.source
            stock.provider = record.provider
            stock.available_time = record.available_time
            stock.ingested_time = record.ingested_time
            output.append(stock)
        self._session.flush()
        return output

    def store_snapshot(
        self,
        *,
        batch: SecurityMasterBatch,
        securities: list[Stock],
    ) -> int:
        if not batch.research_eligible:
            raise ValueError(
                "security-master batch is not certified for research: "
                + batch.certification_basis
            )
        by_code = {record.canonical_code: record for record in batch.records}
        members = [
            UniverseCandidate(
                stock_id=stock.id,
                symbol=stock.symbol,
                market=batch.market,
                exchange=stock.exchange,
                segment=by_code[stock.canonical_code].segment,
                asset_type=stock.asset_type,
                size_bucket=SizeBucket.UNKNOWN,
                listing_age_bucket=ListingAgeBucket.UNKNOWN,
                list_date=stock.list_date,
                delist_date=stock.delist_date,
                reason="present_in_certified_provider_snapshot",
                source=stock.source,
                provider=stock.provider,
                available_time=normalize_utc(stock.available_time),
                ingested_time=normalize_utc(stock.ingested_time),
            )
            for stock in securities
        ]
        return MarketDataQualityRepository(self._session).store_universe_snapshot(
            market=batch.market,
            as_of_date=batch.snapshot_date,
            source=batch.source,
            provider=batch.provider,
            available_time=batch.available_time,
            ingested_time=batch.ingested_time,
            members=members,
        )

    @staticmethod
    def _validate_record(record: SecurityMasterRecord) -> None:
        if record.security_type not in {"stock", "etf", "index"}:
            raise ValueError(f"unsupported security-master type: {record.security_type}")
        if not record.source.strip() or not record.provider.strip():
            raise ValueError("security-master lineage is required")
        if record.listing_date and record.delisting_date:
            if record.listing_date > record.delisting_date:
                raise ValueError("security listing date follows delisting date")
        if normalize_utc(record.available_time) > normalize_utc(record.ingested_time):
            raise ValueError("security-master record was ingested before availability")
