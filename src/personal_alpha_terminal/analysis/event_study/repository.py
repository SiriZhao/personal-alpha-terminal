from datetime import date

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from personal_alpha_terminal.analysis.event_study.schemas import (
    EventDefinitionView,
    InstrumentOption,
    PriceBar,
)
from personal_alpha_terminal.core.data_timestamps import DataTimestamps
from personal_alpha_terminal.core.market_time import normalize_utc
from personal_alpha_terminal.data.market_data.selection import (
    preferred_source,
    select_consistent_price_series,
)
from personal_alpha_terminal.data.market_data_quality.schemas import AdjustmentMode
from personal_alpha_terminal.models import (
    EventDefinition,
    EventOccurrence,
    EventStudyRun,
    EventStudyStatistic,
    Price,
    Stock,
)


class EventStudyRepository:
    """Database access for event definitions, market inputs, and saved outputs."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_definition(
        self,
        *,
        name: str,
        description: str | None,
        rule_type: str,
        parameters: dict[str, object],
    ) -> EventDefinition:
        latest_version = self.session.scalar(
            select(func.max(EventDefinition.version)).where(EventDefinition.name == name)
        )
        self.session.execute(
            update(EventDefinition)
            .where(
                EventDefinition.name == name,
                EventDefinition.is_active.is_(True),
            )
            .values(is_active=False)
        )
        definition = EventDefinition(
            name=name,
            version=(latest_version or 0) + 1,
            description=description,
            rule_type=rule_type,
            parameters=parameters,
            is_active=True,
        )
        self.session.add(definition)
        self.session.flush()
        return definition

    def list_definitions(self, *, active_only: bool = True) -> list[EventDefinition]:
        statement = select(EventDefinition)
        if active_only:
            statement = statement.where(EventDefinition.is_active.is_(True))
        return list(
            self.session.scalars(
                statement.order_by(EventDefinition.name, EventDefinition.version.desc())
            )
        )

    def get_definition(self, definition_id: int) -> EventDefinition | None:
        return self.session.get(EventDefinition, definition_id)

    def list_instruments(self) -> list[Stock]:
        return list(
            self.session.scalars(
                select(Stock)
                .where(
                    Stock.is_active.is_(True),
                    Stock.asset_type.in_(("stock", "etf")),
                )
                .order_by(Stock.market, Stock.symbol)
            )
        )

    def get_instrument(self, stock_id: int) -> Stock | None:
        return self.session.get(Stock, stock_id)

    def load_bars(self, stock_id: int, *, end_date: date) -> tuple[PriceBar, ...]:
        stock = self.session.get(Stock, stock_id)
        if stock is None:
            return ()
        prices = list(
            self.session.scalars(
                select(Price)
                .where(
                    Price.stock_id == stock_id,
                    Price.trade_date <= end_date,
                )
                .order_by(
                    Price.trade_date,
                    Price.ingested_at.desc(),
                    Price.source,
                )
            )
        )
        selected = select_consistent_price_series(
            prices,
            preferred=preferred_source(stock.market),
        )
        output: list[PriceBar] = []
        for price in selected:
            if price.event_time is None or price.available_time is None:
                raise ValueError(
                    "event study requires re-ingested three-time price provenance: "
                    f"stock_id={stock_id} date={price.trade_date}"
                )
            timestamps = DataTimestamps(
                event_time=normalize_utc(price.event_time),
                available_time=normalize_utc(price.available_time),
                ingested_time=normalize_utc(price.ingested_at),
            )
            if (
                price.adjusted_close is None
                or price.adjustment_method
                != AdjustmentMode.POINT_IN_TIME_TOTAL_RETURN.value
            ):
                raise ValueError(
                    "event study requires point-in-time total-return prices; "
                    "raw close and provider current-snapshot adjustments can create "
                    "corporate-action leakage: "
                    f"stock_id={stock_id} date={price.trade_date} "
                    f"method={price.adjustment_method!r}"
                )
            output.append(
                PriceBar(
                    date=price.trade_date,
                    close=float(price.adjusted_close),
                    volume=price.volume,
                    available_time=timestamps.available_time,
                )
            )
        return tuple(output)

    def latest_run(self) -> EventStudyRun | None:
        return self.session.scalar(
            select(EventStudyRun)
            .where(EventStudyRun.status == "completed")
            .order_by(EventStudyRun.created_at.desc(), EventStudyRun.id.desc())
            .limit(1)
        )

    def occurrences_for_run(self, run_id: int) -> list[EventOccurrence]:
        return list(
            self.session.scalars(
                select(EventOccurrence)
                .where(EventOccurrence.run_id == run_id)
                .order_by(EventOccurrence.event_date)
            )
        )

    def statistics_for_run(self, run_id: int) -> list[EventStudyStatistic]:
        return list(
            self.session.scalars(
                select(EventStudyStatistic)
                .where(EventStudyStatistic.run_id == run_id)
                .order_by(
                    EventStudyStatistic.horizon_days,
                    EventStudyStatistic.target_stock_id,
                )
            )
        )

    @staticmethod
    def instrument_option(stock: Stock) -> InstrumentOption:
        return InstrumentOption(
            id=stock.id,
            symbol=stock.symbol,
            name=stock.name,
            market=stock.market,
        )

    @staticmethod
    def definition_view(definition: EventDefinition) -> EventDefinitionView:
        return EventDefinitionView(
            id=definition.id,
            name=definition.name,
            version=definition.version,
            description=definition.description,
            rule_type=definition.rule_type,
            parameters=dict(definition.parameters),
        )
