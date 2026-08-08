from collections import Counter
from datetime import UTC, date, datetime, time
from decimal import Decimal
from hashlib import sha256

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personal_alpha_terminal.core.market_time import normalize_utc
from personal_alpha_terminal.data.market_data.schemas import Market
from personal_alpha_terminal.data.market_data_quality.classification import (
    validate_symbol_mapping,
)
from personal_alpha_terminal.data.market_data_quality.schemas import (
    CalendarSession,
    CorporateActionRecord,
    CorporateActionType,
    HistoricalBar,
    InstrumentQualityMetrics,
    ListingAgeBucket,
    MarketSegment,
    QualityReport,
    SizeBucket,
    UniverseCandidate,
)
from personal_alpha_terminal.models import (
    CorporateAction,
    ExchangeSession,
    MarketDataQualityResult,
    MarketDataQualityRun,
    MarketUniverseMember,
    MarketUniverseSnapshot,
    Price,
    Stock,
)


class MarketDataQualityRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def latest_snapshot_ids(
        self,
        as_of_date: date,
        *,
        available_by: datetime | None = None,
    ) -> dict[Market, int]:
        cutoff = normalize_utc(
            available_by or datetime.combine(as_of_date, time.max, tzinfo=UTC)
        )
        output: dict[Market, int] = {}
        for market in ("A", "HK", "US"):
            statement = (
                select(MarketUniverseSnapshot.id)
                .where(
                    MarketUniverseSnapshot.market == market,
                    MarketUniverseSnapshot.as_of_date <= as_of_date,
                    MarketUniverseSnapshot.available_time <= cutoff,
                )
                .order_by(
                    MarketUniverseSnapshot.as_of_date.desc(),
                    MarketUniverseSnapshot.id.desc(),
                )
                .limit(1)
            )
            snapshot_id = self._session.scalar(statement)
            if snapshot_id is not None:
                output[market] = snapshot_id
        return output

    def store_universe_snapshot(
        self,
        *,
        market: Market,
        as_of_date: date,
        source: str,
        provider: str,
        available_time: datetime,
        ingested_time: datetime,
        members: list[UniverseCandidate],
    ) -> int:
        if not source.strip() or not provider.strip():
            raise ValueError("Universe snapshot source and provider are required.")
        if not members:
            raise ValueError("Universe snapshot cannot be empty.")
        if normalize_utc(available_time) > normalize_utc(ingested_time):
            raise ValueError("Universe snapshot cannot be ingested before it is available.")
        if any(item.market != market for item in members):
            raise ValueError("Universe members must match the snapshot market.")
        if any(not item.reason.strip() for item in members):
            raise ValueError("Every universe member requires a membership reason.")
        for item in members:
            validate_symbol_mapping(item)
        stock_ids = [item.stock_id for item in members]
        if len(stock_ids) != len(set(stock_ids)):
            raise ValueError("Universe snapshot contains duplicate stock ids.")

        snapshot = MarketUniverseSnapshot(
            market=market,
            as_of_date=as_of_date,
            source=source,
            provider=provider,
            available_time=available_time,
            ingested_time=ingested_time,
        )
        snapshot.members.extend(
            MarketUniverseMember(
                stock_id=item.stock_id,
                segment=item.segment.value,
                size_bucket=item.size_bucket.value,
                listing_age_bucket=item.listing_age_bucket.value,
                market_cap=item.market_cap,
                reason=item.reason,
            )
            for item in members
        )
        self._session.add(snapshot)
        self._session.flush()
        return snapshot.id

    def store_calendar_sessions(self, sessions: list[CalendarSession]) -> int:
        seen: set[tuple[str, date, str, str]] = set()
        for item in sessions:
            if not item.source.strip() or not item.provider.strip():
                raise ValueError("Calendar session source and provider are required.")
            if normalize_utc(item.available_time) > normalize_utc(item.ingested_time):
                raise ValueError("Calendar session cannot be ingested before availability.")
            if not item.timezone.strip():
                raise ValueError("Calendar session timezone is required.")
            if item.is_open and (item.open_time is None or item.close_time is None):
                raise ValueError("Open sessions require open_time and close_time.")
            if not item.is_open and (
                item.open_time is not None or item.close_time is not None
            ):
                raise ValueError("Closed sessions cannot contain open or close times.")
            if item.open_time is not None and item.close_time is not None:
                if normalize_utc(item.open_time) >= normalize_utc(item.close_time):
                    raise ValueError("Calendar open_time must precede close_time.")
            key = (item.exchange, item.session_date, item.source, item.provider)
            if key in seen:
                raise ValueError(f"Duplicate calendar session in input: {key}")
            seen.add(key)
            self._session.add(
                ExchangeSession(
                    exchange=item.exchange,
                    session_date=item.session_date,
                    is_open=item.is_open,
                    open_time=item.open_time,
                    close_time=item.close_time,
                    timezone=item.timezone,
                    source=item.source,
                    provider=item.provider,
                    available_time=item.available_time,
                    ingested_time=item.ingested_time,
                )
            )
        self._session.flush()
        return len(sessions)

    def store_corporate_actions(self, actions: list[CorporateActionRecord]) -> int:
        seen: set[tuple[int, str, date, str, str]] = set()
        for item in actions:
            normalize_utc(item.event_time)
            available_time = normalize_utc(item.available_time)
            ingested_time = normalize_utc(item.ingested_time)
            if not item.source.strip() or not item.provider.strip():
                raise ValueError("Corporate action source and provider are required.")
            if item.announcement_date > item.available_date:
                raise ValueError("Corporate action cannot be available before announcement.")
            if ingested_time < available_time:
                raise ValueError("Corporate action was ingested before availability.")
            if item.action_type in {
                CorporateActionType.SPLIT,
                CorporateActionType.REVERSE_SPLIT,
            } and (item.split_ratio is None or item.split_ratio <= 0):
                raise ValueError("Split and reverse split actions require a positive ratio.")
            key = (
                item.stock_id,
                item.action_type.value,
                item.effective_date,
                item.source,
                item.provider,
            )
            if key in seen:
                raise ValueError(f"Duplicate corporate action in input: {key}")
            seen.add(key)
            action_identity = "|".join(str(value) for value in key)
            action_id = sha256(action_identity.encode()).hexdigest()
            revision_payload = (
                f"{action_identity}|{available_time.isoformat()}|{item.split_ratio}|"
                f"{item.cash_amount}|{item.currency}"
            )
            self._session.add(
                CorporateAction(
                    stock_id=item.stock_id,
                    action_id=action_id,
                    revision_id=sha256(revision_payload.encode()).hexdigest(),
                    action_type=item.action_type.value,
                    effective_date=item.effective_date,
                    announcement_date=item.announcement_date,
                    available_date=item.available_date,
                    event_time=item.event_time,
                    available_time=item.available_time,
                    ingested_time=item.ingested_time,
                    split_ratio=item.split_ratio,
                    cash_amount=item.cash_amount,
                    currency=item.currency,
                    source=item.source,
                    provider=item.provider,
                )
            )
        self._session.flush()
        return len(actions)

    def candidates(self, snapshot_ids: list[int]) -> list[UniverseCandidate]:
        if not snapshot_ids:
            return []
        statement = (
            select(MarketUniverseMember, Stock)
            .join(Stock, Stock.id == MarketUniverseMember.stock_id)
            .where(MarketUniverseMember.snapshot_id.in_(snapshot_ids))
            .order_by(Stock.market, MarketUniverseMember.segment, Stock.symbol)
        )
        output: list[UniverseCandidate] = []
        for member, stock in self._session.execute(statement):
            output.append(
                UniverseCandidate(
                    stock_id=stock.id,
                    symbol=stock.symbol,
                    market=self._market(stock.market),
                    exchange=stock.exchange,
                    segment=MarketSegment(member.segment),
                    asset_type=stock.asset_type,
                    size_bucket=SizeBucket(member.size_bucket),
                    listing_age_bucket=ListingAgeBucket(member.listing_age_bucket),
                    list_date=stock.list_date,
                    delist_date=stock.delist_date,
                    market_cap=member.market_cap,
                    reason=member.reason,
                    source=stock.source,
                    provider=stock.provider,
                    available_time=normalize_utc(stock.available_time),
                    ingested_time=normalize_utc(stock.ingested_time),
                )
            )
        return output

    def calendar_sessions(
        self,
        *,
        exchange: str,
        start_date: date,
        end_date: date,
    ) -> list[CalendarSession]:
        statement = (
            select(ExchangeSession)
            .where(
                ExchangeSession.exchange == exchange,
                ExchangeSession.session_date.between(start_date, end_date),
            )
            .order_by(ExchangeSession.session_date)
        )
        return [
            CalendarSession(
                exchange=item.exchange,
                session_date=item.session_date,
                is_open=item.is_open,
                open_time=(normalize_utc(item.open_time) if item.open_time is not None else None),
                close_time=(
                    normalize_utc(item.close_time) if item.close_time is not None else None
                ),
                timezone=item.timezone,
                source=item.source,
                provider=item.provider,
                available_time=normalize_utc(item.available_time),
                ingested_time=normalize_utc(item.ingested_time),
            )
            for item in self._session.scalars(statement)
        ]

    def price_history(
        self,
        *,
        stock_id: int,
        start_date: date,
        end_date: date,
        source: str,
    ) -> list[HistoricalBar]:
        statement = (
            select(Price)
            .where(
                Price.stock_id == stock_id,
                Price.source == source,
                Price.trade_date.between(start_date, end_date),
            )
            .order_by(Price.trade_date, Price.source)
        )
        return [
            HistoricalBar(
                trade_date=item.trade_date,
                close=item.close,
                adjusted_close=item.adjusted_close,
                source=item.source,
                provider=item.provider,
                event_time=(
                    normalize_utc(item.event_time)
                    if item.event_time is not None
                    else None
                ),
                available_time=(
                    normalize_utc(item.available_time)
                    if item.available_time is not None
                    else None
                ),
                ingested_time=normalize_utc(item.ingested_at),
            )
            for item in self._session.scalars(statement)
        ]

    def corporate_actions(
        self,
        *,
        stock_id: int,
        start_date: date,
        end_date: date,
    ) -> list[CorporateActionRecord]:
        statement = (
            select(CorporateAction)
            .where(
                CorporateAction.stock_id == stock_id,
                CorporateAction.effective_date.between(start_date, end_date),
            )
            .order_by(CorporateAction.effective_date)
        )
        return [
            CorporateActionRecord(
                stock_id=item.stock_id,
                action_type=CorporateActionType(item.action_type),
                effective_date=item.effective_date,
                announcement_date=item.announcement_date,
                available_date=item.available_date,
                event_time=normalize_utc(item.event_time),
                available_time=normalize_utc(item.available_time),
                ingested_time=normalize_utc(item.ingested_time),
                source=item.source,
                provider=item.provider,
                split_ratio=item.split_ratio,
                cash_amount=item.cash_amount,
                currency=item.currency,
            )
            for item in self._session.scalars(statement)
        ]

    def lineage_counts(self, stock_ids: list[int]) -> tuple[dict[str, int], dict[str, int]]:
        if not stock_ids:
            return {}, {}
        source_statement = (
            select(Price.source, func.count())
            .where(Price.stock_id.in_(stock_ids))
            .group_by(Price.source)
        )
        provider_statement = (
            select(Price.provider, func.count())
            .where(Price.stock_id.in_(stock_ids))
            .group_by(Price.provider)
        )
        sources = {key: int(count) for key, count in self._session.execute(source_statement)}
        providers = {key: int(count) for key, count in self._session.execute(provider_statement)}
        return sources, providers

    def persist_report(
        self,
        *,
        report: QualityReport,
        snapshot_ids: list[int],
        random_seed: int,
        minimum_sample_size: int,
    ) -> int:
        sample_count = len(report.sample.selected) if report.sample is not None else 0
        run = MarketDataQualityRun(
            history_start=report.history_start,
            history_end=report.history_end,
            random_seed=random_seed,
            minimum_sample_size=minimum_sample_size,
            sample_count=sample_count,
            status=report.status.value,
            source_snapshot_ids=snapshot_ids,
            aggregate_metrics={
                "expected_sessions": report.expected_sessions,
                "observed_sessions": report.observed_sessions,
                "missing_rate": report.missing_rate,
                "anomaly_rate": report.anomaly_rate,
                "source_counts": report.source_counts,
                "provider_counts": report.provider_counts,
            },
            blockers=list(report.blockers),
        )
        self._session.add(run)
        self._session.flush()
        for result in report.instrument_results:
            run.results.append(self._result_model(result))
        self._session.flush()
        return run.id

    @staticmethod
    def _result_model(result: InstrumentQualityMetrics) -> MarketDataQualityResult:
        return MarketDataQualityResult(
            stock_id=result.stock_id,
            segment=result.segment.value,
            expected_sessions=result.expected_sessions,
            observed_sessions=result.observed_sessions,
            missing_sessions=result.missing_sessions,
            missing_rate=Decimal(str(result.missing_rate)),
            anomalous_observations=result.anomalous_observations,
            anomaly_rate=Decimal(str(result.anomaly_rate)),
            first_date=result.first_date,
            last_date=result.last_date,
            status="passed" if result.passed else "failed",
            issues=[
                {
                    "code": item.code,
                    "severity": item.severity,
                    "message": item.message,
                    "trade_date": (
                        item.trade_date.isoformat() if item.trade_date is not None else None
                    ),
                }
                for item in result.issues
            ],
        )

    @staticmethod
    def _market(value: str) -> Market:
        if value in {"A", "HK", "US"}:
            return value  # type: ignore[return-value]
        raise ValueError(f"Unsupported market in universe snapshot: {value}")


def count_segments(candidates: list[UniverseCandidate]) -> dict[str, int]:
    return dict(Counter(item.segment.value for item in candidates))
