from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from personal_alpha_terminal.core.market_time import normalize_utc
from personal_alpha_terminal.data.us_market.pit_total_return import PITTotalReturnSeries
from personal_alpha_terminal.models import (
    FundamentalVintage,
    MarketUniverseMember,
    MarketUniverseSnapshot,
    PITTotalReturnPointRecord,
    PITTotalReturnVersion,
    Price,
    SecurityMaster,
    SymbolAlias,
    TradingStatus,
    UniverseMembership,
)


@dataclass(frozen=True, slots=True)
class CertifiedUniverse:
    snapshot_id: str
    data_version: str
    securities: tuple[SecurityMaster, ...]


class USPointInTimeRepository:
    """Only persisted, certified, time-bounded data crosses this boundary."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def certified_universe(
        self,
        *,
        as_of: datetime,
        snapshot_id: int | None = None,
    ) -> CertifiedUniverse:
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        statement = select(MarketUniverseSnapshot).where(
            MarketUniverseSnapshot.market == "US",
            MarketUniverseSnapshot.as_of_date <= as_of.date(),
            MarketUniverseSnapshot.available_time <= as_of,
            MarketUniverseSnapshot.certification_status == "CERTIFIED",
            MarketUniverseSnapshot.version_id.is_not(None),
            MarketUniverseSnapshot.data_version.is_not(None),
            MarketUniverseSnapshot.content_hash.is_not(None),
        )
        if snapshot_id is not None:
            statement = statement.where(MarketUniverseSnapshot.id == snapshot_id)
        snapshot = self.session.scalar(
            statement.order_by(
                MarketUniverseSnapshot.as_of_date.desc(), MarketUniverseSnapshot.id.desc()
            ).limit(1)
        )
        if snapshot is None or snapshot.data_version is None:
            raise ValueError("certified US universe snapshot is unavailable")
        if snapshot.definition_id is not None:
            memberships = list(
                self.session.scalars(
                    select(UniverseMembership).where(
                        UniverseMembership.definition_id == snapshot.definition_id,
                        UniverseMembership.effective_from <= as_of.date(),
                        or_(
                            UniverseMembership.effective_to.is_(None),
                            UniverseMembership.effective_to >= as_of.date(),
                        ),
                        UniverseMembership.available_time <= as_of,
                    )
                )
            )
            stock_ids = {item.stock_id for item in memberships}
        else:
            stock_ids = set(
                self.session.scalars(
                    select(MarketUniverseMember.stock_id).where(
                        MarketUniverseMember.snapshot_id == snapshot.id
                    )
                )
            )
        if not stock_ids:
            raise ValueError("certified universe has no point-in-time members")
        securities = tuple(
            self.session.scalars(
                select(SecurityMaster)
                .where(
                    SecurityMaster.id.in_(stock_ids),
                    SecurityMaster.market == "US",
                    SecurityMaster.available_time <= as_of,
                    or_(
                        SecurityMaster.list_date.is_(None),
                        SecurityMaster.list_date <= as_of.date(),
                    ),
                    or_(
                        SecurityMaster.delist_date.is_(None),
                        SecurityMaster.delist_date >= as_of.date(),
                    ),
                )
                .order_by(SecurityMaster.canonical_code)
            )
        )
        if {item.id for item in securities} != stock_ids:
            raise ValueError("universe contains unavailable, future-listed or delisted members")
        return CertifiedUniverse(str(snapshot.id), snapshot.data_version, securities)

    def resolve_symbol(
        self,
        *,
        exchange: str,
        symbol: str,
        as_of: datetime,
    ) -> SecurityMaster:
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        normalized = symbol.upper().replace("-", ".")
        alias = self.session.scalar(
            select(SymbolAlias)
            .where(
                SymbolAlias.exchange == exchange,
                SymbolAlias.normalized_symbol == normalized,
                SymbolAlias.valid_from <= as_of.date(),
                or_(SymbolAlias.valid_to.is_(None), SymbolAlias.valid_to >= as_of.date()),
                SymbolAlias.available_time <= as_of,
            )
            .order_by(SymbolAlias.valid_from.desc(), SymbolAlias.id.desc())
            .limit(1)
        )
        if alias is None:
            raise ValueError(f"PIT symbol alias is unavailable: {exchange}:{symbol}")
        security = self.session.get(SecurityMaster, alias.stock_id)
        if security is None or normalize_utc(security.available_time) > normalize_utc(as_of):
            raise ValueError("PIT symbol alias references an unavailable security")
        return security

    def tradability(self, stock_id: int, *, as_of: datetime) -> str:
        record = self.session.scalar(
            select(TradingStatus)
            .where(
                TradingStatus.stock_id == stock_id,
                TradingStatus.available_time <= as_of,
                TradingStatus.effective_time <= as_of,
            )
            .order_by(TradingStatus.effective_time.desc(), TradingStatus.id.desc())
            .limit(1)
        )
        return record.status if record is not None else "UNKNOWN"

    def total_return_frame(
        self,
        securities: tuple[SecurityMaster, ...],
        *,
        as_of: datetime,
        start_date: datetime,
    ) -> tuple[pd.DataFrame, dict[int, PITTotalReturnVersion]]:
        rows: list[dict[str, object]] = []
        versions: dict[int, PITTotalReturnVersion] = {}
        for security in securities:
            version = self.session.scalar(
                select(PITTotalReturnVersion)
                .where(
                    PITTotalReturnVersion.stock_id == security.id,
                    PITTotalReturnVersion.as_of_time <= as_of,
                    PITTotalReturnVersion.data_cutoff.is_not(None),
                    PITTotalReturnVersion.data_cutoff <= as_of,
                    PITTotalReturnVersion.certification_status == "CERTIFIED",
                    PITTotalReturnVersion.adjustment_policy
                    == "point_in_time_total_return_v1",
                )
                .order_by(PITTotalReturnVersion.as_of_time.desc(), PITTotalReturnVersion.id.desc())
                .limit(1)
            )
            if version is None:
                raise ValueError(f"certified PIT total-return series missing: {security.symbol}")
            versions[security.id] = version
            points = self.session.scalars(
                select(PITTotalReturnPointRecord)
                .where(
                    PITTotalReturnPointRecord.version_id == version.id,
                    PITTotalReturnPointRecord.trade_date >= start_date.date(),
                    PITTotalReturnPointRecord.trade_date <= as_of.date(),
                )
                .order_by(PITTotalReturnPointRecord.trade_date)
            )
            for point in points:
                rows.append(
                    {
                        "permanent_security_id": security.canonical_code,
                        "ticker": security.symbol,
                        "trade_date": point.trade_date,
                        "available_time": version.data_cutoff,
                        "close": point.total_return_index,
                    }
                )
        frame = pd.DataFrame(rows)
        if frame.empty:
            raise ValueError("certified PIT total-return points are unavailable")
        return frame, versions

    def metadata_frame(
        self, securities: tuple[SecurityMaster, ...], *, as_of: datetime
    ) -> pd.DataFrame:
        rows = []
        for security in securities:
            prices = list(
                self.session.scalars(
                    select(Price)
                    .where(
                        Price.stock_id == security.id,
                        Price.trade_date <= as_of.date(),
                        Price.available_time.is_not(None),
                        Price.available_time <= as_of,
                        Price.price_type == "unadjusted_ohlcv",
                    )
                    .order_by(Price.trade_date.desc())
                    .limit(60)
                )
            )
            if not prices or any(item.volume is None for item in prices):
                raise ValueError(f"known raw ADV is required: {security.symbol}")
            adv = sum(float(item.close) * float(item.volume or 0) for item in prices) / len(prices)
            if adv <= 0:
                raise ValueError(f"positive raw ADV is required: {security.symbol}")
            membership = self.session.scalar(
                select(UniverseMembership)
                .where(
                    UniverseMembership.stock_id == security.id,
                    UniverseMembership.effective_from <= as_of.date(),
                    or_(
                        UniverseMembership.effective_to.is_(None),
                        UniverseMembership.effective_to >= as_of.date(),
                    ),
                    UniverseMembership.available_time <= as_of,
                )
                .order_by(
                    UniverseMembership.effective_from.desc(),
                    UniverseMembership.id.desc(),
                )
                .limit(1)
            )
            market_cap = (
                float(membership.market_cap)
                if membership is not None and membership.market_cap is not None
                else None
            )
            rows.append(
                {
                    "permanent_security_id": security.canonical_code,
                    "ticker": security.symbol,
                    "sector": (
                        security.industry.name if security.industry is not None else "UNKNOWN"
                    ),
                    "market_cap": market_cap,
                    "average_daily_dollar_volume": adv,
                }
            )
        return pd.DataFrame(rows)

    def fundamental_snapshot(
        self, securities: tuple[SecurityMaster, ...], *, as_of: datetime
    ) -> pd.DataFrame | None:
        rows: list[dict[str, object]] = []
        for security in securities:
            vintages = list(
                self.session.scalars(
                    select(FundamentalVintage)
                    .where(
                        FundamentalVintage.stock_id == security.id,
                        FundamentalVintage.available_at <= as_of,
                        FundamentalVintage.publication_time <= as_of,
                    )
                    .order_by(
                        FundamentalVintage.fiscal_period_end.desc(),
                        FundamentalVintage.available_at.desc(),
                        FundamentalVintage.id.desc(),
                    )
                )
            )
            if not vintages:
                continue
            vintage = vintages[0]
            values = vintage.restated_values if vintage.is_restatement else vintage.original_values
            values = values or vintage.original_values
            quality_values = [values.get(name) for name in ("roic", "roe", "gross_margin")]
            numeric = [float(value) for value in quality_values if isinstance(value, (int, float))]
            if numeric:
                rows.append(
                    {
                        "permanent_security_id": security.canonical_code,
                        "quality": sum(numeric) / len(numeric),
                        "available_at": vintage.available_at,
                    }
                )
        return pd.DataFrame(rows) if rows else None

    def persist_total_return_series(
        self,
        series: PITTotalReturnSeries,
        *,
        stock_id: int,
        corporate_action_ledger_hash: str,
        certification_status: str = "NOT_VALIDATED",
    ) -> PITTotalReturnVersion:
        existing = self.session.scalar(
            select(PITTotalReturnVersion).where(
                PITTotalReturnVersion.version_id == series.version_id
            )
        )
        if existing is not None:
            return existing
        record = PITTotalReturnVersion(
            version_id=series.version_id,
            stock_id=stock_id,
            as_of_time=series.as_of_time,
            data_cutoff=series.as_of_time,
            first_date=series.points[0].trade_date,
            last_date=series.points[-1].trade_date,
            source_ids=list(series.source_ids),
            point_count=len(series.points),
            result_hash=series.version_id,
            adjustment_policy="point_in_time_total_return_v1",
            corporate_action_ledger_hash=corporate_action_ledger_hash,
            certification_status=certification_status,
        )
        self.session.add(record)
        self.session.flush()
        self.session.add_all(
            [
                PITTotalReturnPointRecord(
                    version_id=record.id,
                    trade_date=point.trade_date,
                    raw_close=point.raw_close,
                    period_return=point.period_return,
                    total_return_index=point.total_return_index,
                    applied_action_ids=list(point.applied_action_ids),
                )
                for point in series.points
            ]
        )
        return record
