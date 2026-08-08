from datetime import UTC, date, datetime
from decimal import Decimal

from personal_alpha_terminal.analysis.event_study.repository import EventStudyRepository
from personal_alpha_terminal.analysis.event_study.rules import apply_cooldown, build_rule
from personal_alpha_terminal.analysis.event_study.schemas import (
    EventDefinitionView,
    EventMatch,
    EventOutcome,
    EventStatistic,
    EventStudyResult,
    InstrumentOption,
)
from personal_alpha_terminal.analysis.event_study.statistics import (
    aggregate_outcomes,
    calculate_outcomes,
)
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.core.market_time import market_close_utc
from personal_alpha_terminal.data.market_data_quality.schemas import AdjustmentMode
from personal_alpha_terminal.models import (
    EventOccurrence,
    EventStudyObservation,
    EventStudyRun,
    EventStudyStatistic,
)


class EventStudyService:
    """Create reusable definitions and run auditable, point-in-time event studies."""

    def __init__(self, repository: EventStudyRepository, settings: Settings) -> None:
        self._repository = repository
        self._settings = settings

    def list_instruments(self) -> tuple[InstrumentOption, ...]:
        return tuple(
            self._repository.instrument_option(stock)
            for stock in self._repository.list_instruments()
        )

    def list_definitions(self) -> tuple[EventDefinitionView, ...]:
        return tuple(
            self._repository.definition_view(definition)
            for definition in self._repository.list_definitions()
        )

    def create_definition(
        self,
        *,
        name: str,
        description: str | None,
        rule_type: str,
        parameters: dict[str, object],
    ) -> EventDefinitionView:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("event definition name is required")
        rule = build_rule(rule_type, parameters)
        rule.detect(())
        definition = self._repository.create_definition(
            name=normalized_name,
            description=description.strip() if description else None,
            rule_type=rule_type,
            parameters=parameters,
        )
        return self._repository.definition_view(definition)

    def run(
        self,
        *,
        definition_id: int,
        trigger_stock_id: int,
        target_stock_ids: tuple[int, ...],
        start_date: date,
        end_date: date,
        horizons: tuple[int, ...] | None = None,
        cooldown_days: int | None = None,
        win_threshold: float | None = None,
    ) -> EventStudyResult:
        if start_date >= end_date:
            raise ValueError("start_date must be before end_date")
        definition = self._repository.get_definition(definition_id)
        if definition is None:
            raise ValueError("event definition does not exist")
        trigger = self._repository.get_instrument(trigger_stock_id)
        if trigger is None or trigger.asset_type not in {"stock", "etf"}:
            raise ValueError("trigger instrument does not exist")
        unique_target_ids = tuple(dict.fromkeys(target_stock_ids))
        if not unique_target_ids:
            raise ValueError("at least one target instrument is required")
        if len(unique_target_ids) > self._settings.event_study_max_targets:
            raise ValueError(
                "target count exceeds configured maximum "
                f"({self._settings.event_study_max_targets})"
            )
        targets = []
        for stock_id in unique_target_ids:
            stock = self._repository.get_instrument(stock_id)
            if stock is None or stock.asset_type not in {"stock", "etf"}:
                raise ValueError(f"target instrument does not exist: {stock_id}")
            targets.append(stock)

        resolved_horizons = horizons or self._default_horizons()
        if not resolved_horizons or any(horizon <= 0 for horizon in resolved_horizons):
            raise ValueError("event horizons must be positive")
        if len(set(resolved_horizons)) != len(resolved_horizons):
            raise ValueError("event horizons must be unique")
        resolved_horizons = tuple(sorted(resolved_horizons))
        resolved_cooldown = (
            cooldown_days
            if cooldown_days is not None
            else self._settings.event_study_default_cooldown_days
        )
        if resolved_cooldown < 1:
            raise ValueError("event cooldown must be at least one trigger trading session")
        resolved_win_threshold = (
            win_threshold
            if win_threshold is not None
            else self._settings.event_study_default_win_threshold
        )
        if resolved_win_threshold <= -1:
            raise ValueError("win threshold must be greater than -1")

        definition_view = self._repository.definition_view(definition)
        trigger_option = self._repository.instrument_option(trigger)
        run = EventStudyRun(
            definition_id=definition.id,
            trigger_stock_id=trigger.id,
            start_date=start_date,
            end_date=end_date,
            status="running",
            horizons=list(resolved_horizons),
            parameters={
                "definition_name": definition.name,
                "definition_version": definition.version,
                "rule_type": definition.rule_type,
                "rule_parameters": dict(definition.parameters),
                "target_stock_ids": list(unique_target_ids),
                "cooldown_days": resolved_cooldown,
                "deduplication_method": "candidate_episode_cooldown",
                "win_threshold": resolved_win_threshold,
                "return_type": "simple_close_to_close",
                "horizon_unit": "target_trading_observations",
                "right_censoring": "exclude_incomplete_horizon",
                "minimum_sample_size": self._settings.event_study_minimum_sample_size,
                "confidence_level": self._settings.event_study_confidence_level,
                "probability_interval_method": "wilson_score",
                "mean_interval_method": "moving_block_bootstrap_percentile",
                "bootstrap_resamples": self._settings.event_study_bootstrap_resamples,
                "small_sample_policy": "descriptive_only_low_confidence",
                "price_adjustment_policy": AdjustmentMode.POINT_IN_TIME_TOTAL_RETURN.value,
            },
        )
        self._repository.session.add(run)
        self._repository.session.flush()

        try:
            trigger_bars = self._repository.load_bars(trigger.id, end_date=end_date)
            rule = build_rule(definition.rule_type, dict(definition.parameters))
            matches = tuple(
                match for match in rule.detect(trigger_bars) if start_date <= match.date <= end_date
            )
            matches = apply_cooldown(matches, trigger_bars, resolved_cooldown)
            occurrence_by_date = self._persist_occurrences(
                run.id,
                trigger.id,
                trigger.market,
                matches,
            )

            all_outcomes: list[EventOutcome] = []
            for target in targets:
                target_option = self._repository.instrument_option(target)
                bars = self._repository.load_bars(target.id, end_date=end_date)
                all_outcomes.extend(
                    calculate_outcomes(
                        matches,
                        target_option,
                        bars,
                        trigger_market=trigger.market,
                        horizons=resolved_horizons,
                        win_threshold=resolved_win_threshold,
                    )
                )
            outcomes = tuple(all_outcomes)
            statistics = aggregate_outcomes(
                outcomes,
                minimum_sample_size=self._settings.event_study_minimum_sample_size,
                confidence_level=self._settings.event_study_confidence_level,
                bootstrap_resamples=self._settings.event_study_bootstrap_resamples,
            )
            self._persist_outcomes(occurrence_by_date, outcomes)
            self._persist_statistics(run.id, statistics)
            run.status = "completed"
            self._repository.session.flush()
            return EventStudyResult(
                run_id=run.id,
                definition=definition_view,
                trigger=trigger_option,
                start_date=start_date,
                end_date=end_date,
                horizons=resolved_horizons,
                occurrences=matches,
                statistics=statistics,
            )
        except Exception as error:
            run.status = "failed"
            run.error_message = str(error)
            raise

    def latest(self) -> EventStudyResult | None:
        run = self._repository.latest_run()
        if run is None:
            return None
        if (
            run.parameters.get("price_adjustment_policy")
            != AdjustmentMode.POINT_IN_TIME_TOTAL_RETURN.value
        ):
            return None
        definition = self._repository.get_definition(run.definition_id)
        trigger = self._repository.get_instrument(run.trigger_stock_id)
        if definition is None or trigger is None:
            return None
        occurrences = tuple(
            EventMatch(
                date=item.event_date,
                trigger_value=float(item.trigger_value),
                reference_value=(
                    float(item.reference_value) if item.reference_value is not None else None
                ),
                details=dict(item.details),
                available_time=item.available_time,
            )
            for item in self._repository.occurrences_for_run(run.id)
        )
        statistics: list[EventStatistic] = []
        for item in self._repository.statistics_for_run(run.id):
            target = self._repository.get_instrument(item.target_stock_id)
            if target is None:
                continue
            statistics.append(
                EventStatistic(
                    target=self._repository.instrument_option(target),
                    horizon_days=item.horizon_days,
                    sample_size=item.sample_size,
                    positive_probability=float(item.positive_probability),
                    win_rate=float(item.win_rate),
                    average_return=float(item.average_return),
                    median_return=float(item.median_return),
                    return_stddev=float(item.return_stddev),
                    best_return=float(item.best_return),
                    worst_return=float(item.worst_return),
                    average_max_upside=float(item.average_max_upside),
                    best_max_upside=float(item.best_max_upside),
                    average_max_drawdown=float(item.average_max_drawdown),
                    worst_max_drawdown=float(item.worst_max_drawdown),
                    meets_minimum=item.meets_minimum,
                    confidence_level=float(item.confidence_level),
                    positive_probability_lower=self._optional_float(
                        item.positive_probability_lower
                    ),
                    positive_probability_upper=self._optional_float(
                        item.positive_probability_upper
                    ),
                    win_rate_lower=self._optional_float(item.win_rate_lower),
                    win_rate_upper=self._optional_float(item.win_rate_upper),
                    average_return_lower=self._optional_float(item.average_return_lower),
                    average_return_upper=self._optional_float(item.average_return_upper),
                )
            )
        return EventStudyResult(
            run_id=run.id,
            definition=self._repository.definition_view(definition),
            trigger=self._repository.instrument_option(trigger),
            start_date=run.start_date,
            end_date=run.end_date,
            horizons=tuple(run.horizons),
            occurrences=occurrences,
            statistics=tuple(statistics),
        )

    def _persist_occurrences(
        self,
        run_id: int,
        trigger_stock_id: int,
        trigger_market: str,
        matches: tuple[EventMatch, ...],
    ) -> dict[date, EventOccurrence]:
        occurrences = [
            EventOccurrence(
                run_id=run_id,
                trigger_stock_id=trigger_stock_id,
                event_date=match.date,
                event_time=market_close_utc(match.date, trigger_market),
                available_time=(
                    match.available_time or market_close_utc(match.date, trigger_market)
                ),
                ingested_time=datetime.now(UTC),
                trigger_value=self._decimal(match.trigger_value),
                reference_value=(
                    self._decimal(match.reference_value)
                    if match.reference_value is not None
                    else None
                ),
                details=match.details,
            )
            for match in matches
        ]
        self._repository.session.add_all(occurrences)
        self._repository.session.flush()
        return {item.event_date: item for item in occurrences}

    def _persist_outcomes(
        self,
        occurrence_by_date: dict[date, EventOccurrence],
        outcomes: tuple[EventOutcome, ...],
    ) -> None:
        self._repository.session.add_all(
            [
                EventStudyObservation(
                    occurrence_id=occurrence_by_date[item.event.date].id,
                    target_stock_id=item.target.id,
                    horizon_days=item.horizon_days,
                    baseline_date=item.baseline_date,
                    horizon_date=item.horizon_date,
                    forward_return=self._decimal(item.forward_return),
                    max_upside=self._decimal(item.max_upside),
                    max_drawdown=self._decimal(item.max_drawdown),
                    is_win=item.is_win,
                )
                for item in outcomes
            ]
        )

    def _persist_statistics(
        self,
        run_id: int,
        statistics: tuple[EventStatistic, ...],
    ) -> None:
        self._repository.session.add_all(
            [
                EventStudyStatistic(
                    run_id=run_id,
                    target_stock_id=item.target.id,
                    horizon_days=item.horizon_days,
                    sample_size=item.sample_size,
                    positive_probability=self._decimal(item.positive_probability),
                    win_rate=self._decimal(item.win_rate),
                    average_return=self._decimal(item.average_return),
                    median_return=self._decimal(item.median_return),
                    return_stddev=self._decimal(item.return_stddev),
                    best_return=self._decimal(item.best_return),
                    worst_return=self._decimal(item.worst_return),
                    average_max_upside=self._decimal(item.average_max_upside),
                    best_max_upside=self._decimal(item.best_max_upside),
                    average_max_drawdown=self._decimal(item.average_max_drawdown),
                    worst_max_drawdown=self._decimal(item.worst_max_drawdown),
                    meets_minimum=item.meets_minimum,
                    confidence_level=self._decimal(item.confidence_level),
                    positive_probability_lower=self._optional_decimal(
                        item.positive_probability_lower
                    ),
                    positive_probability_upper=self._optional_decimal(
                        item.positive_probability_upper
                    ),
                    win_rate_lower=self._optional_decimal(item.win_rate_lower),
                    win_rate_upper=self._optional_decimal(item.win_rate_upper),
                    average_return_lower=self._optional_decimal(item.average_return_lower),
                    average_return_upper=self._optional_decimal(item.average_return_upper),
                )
                for item in statistics
            ]
        )

    def _default_horizons(self) -> tuple[int, ...]:
        return tuple(int(item) for item in self._settings.event_study_horizons.split(","))

    @staticmethod
    def _decimal(value: float) -> Decimal:
        return Decimal(str(round(value, 10)))

    @classmethod
    def _optional_decimal(cls, value: float | None) -> Decimal | None:
        return cls._decimal(value) if value is not None else None

    @staticmethod
    def _optional_float(value: Decimal | None) -> float | None:
        return float(value) if value is not None else None
