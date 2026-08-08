from datetime import date
from decimal import Decimal

from personal_alpha_terminal.analysis.conditional_probability.repository import (
    ConditionalProbabilityRepository,
)
from personal_alpha_terminal.analysis.conditional_probability.schemas import (
    ConditionalProbabilityStudy,
    ProbabilityEstimate,
)
from personal_alpha_terminal.analysis.conditional_probability.statistics import (
    estimate_conditional_probability,
)
from personal_alpha_terminal.analysis.event_study.repository import EventStudyRepository
from personal_alpha_terminal.analysis.event_study.schemas import (
    EventDefinitionView,
    InstrumentOption,
)
from personal_alpha_terminal.analysis.event_study.service import EventStudyService
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.data.market_data_quality.schemas import AdjustmentMode
from personal_alpha_terminal.models import (
    ConditionalProbabilityResult,
    ConditionalProbabilityRun,
)


class ConditionalProbabilityService:
    """Estimate P(B future move | A event) with enforced sample safeguards."""

    def __init__(
        self,
        repository: ConditionalProbabilityRepository,
        settings: Settings,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._event_repository = EventStudyRepository(repository.session)
        self._event_service = EventStudyService(self._event_repository, settings)

    def list_instruments(self) -> tuple[InstrumentOption, ...]:
        return self._event_service.list_instruments()

    def list_definitions(self) -> tuple[EventDefinitionView, ...]:
        return self._event_service.list_definitions()

    def run(
        self,
        *,
        definition_id: int,
        trigger_stock_id: int,
        target_stock_ids: tuple[int, ...],
        start_date: date,
        end_date: date,
        outcome_direction: str,
        outcome_threshold: float = 0.0,
        horizons: tuple[int, ...] | None = None,
        minimum_sample_size: int | None = None,
        confidence_level: float | None = None,
        cooldown_days: int | None = None,
    ) -> ConditionalProbabilityStudy:
        if outcome_direction not in {"up", "down"}:
            raise ValueError("outcome_direction must be up or down")
        if outcome_threshold < 0:
            raise ValueError("outcome_threshold must be nonnegative")
        unique_target_ids = tuple(dict.fromkeys(target_stock_ids))
        if len(unique_target_ids) > self._settings.conditional_probability_max_targets:
            raise ValueError(
                "target count exceeds configured maximum "
                f"({self._settings.conditional_probability_max_targets})"
            )
        resolved_minimum = (
            minimum_sample_size
            if minimum_sample_size is not None
            else self._settings.conditional_probability_minimum_sample_size
        )
        configured_minimum = self._settings.conditional_probability_minimum_sample_size
        if resolved_minimum < configured_minimum:
            raise ValueError(
                f"minimum sample size cannot be below configured safeguard ({configured_minimum})"
            )
        resolved_confidence = (
            confidence_level
            if confidence_level is not None
            else self._settings.conditional_probability_confidence_level
        )
        if not 0 < resolved_confidence < 1:
            raise ValueError("confidence_level must be between zero and one")
        resolved_horizons = horizons or self._default_horizons()
        requested_cooldown = (
            cooldown_days
            if cooldown_days is not None
            else self._settings.event_study_default_cooldown_days
        )
        effective_cooldown = max(requested_cooldown, max(resolved_horizons))

        event_study = self._event_service.run(
            definition_id=definition_id,
            trigger_stock_id=trigger_stock_id,
            target_stock_ids=unique_target_ids,
            start_date=start_date,
            end_date=end_date,
            horizons=resolved_horizons,
            cooldown_days=effective_cooldown,
            win_threshold=0.0,
        )
        run = ConditionalProbabilityRun(
            event_study_run_id=event_study.run_id,
            outcome_direction=outcome_direction,
            outcome_threshold=self._decimal(outcome_threshold),
            minimum_sample_size=resolved_minimum,
            confidence_level=self._decimal(resolved_confidence),
            status="running",
            parameters={
                "condition_definition_id": definition_id,
                "condition_definition_version": event_study.definition.version,
                "trigger_stock_id": trigger_stock_id,
                "target_stock_ids": list(unique_target_ids),
                "horizons": list(resolved_horizons),
                "requested_cooldown_days": cooldown_days,
                "effective_cooldown_days": effective_cooldown,
                "dependence_policy": "non_overlapping_trigger_windows",
                "probability_estimator": "beta_binomial_posterior_mean",
                "interval_method": "beta_posterior_equal_tailed",
                "prior_alpha": self._settings.conditional_probability_prior_alpha,
                "prior_beta": self._settings.conditional_probability_prior_beta,
                "small_sample_policy": "suppress_inference",
                "price_adjustment_policy": AdjustmentMode.POINT_IN_TIME_TOTAL_RETURN.value,
                "success_rule": (
                    f"forward_return > {outcome_threshold}"
                    if outcome_direction == "up"
                    else f"forward_return < {-outcome_threshold}"
                ),
            },
        )
        self._repository.session.add(run)
        self._repository.session.flush()

        try:
            grouped_returns = self._repository.grouped_returns(event_study.run_id)
            target_by_id = {
                target.id: target
                for target in self.list_instruments()
                if target.id in unique_target_ids
            }
            estimates: list[ProbabilityEstimate] = []
            for target_id in unique_target_ids:
                target = target_by_id[target_id]
                for horizon in resolved_horizons:
                    returns = grouped_returns.get((target_id, horizon), ())
                    calculated = estimate_conditional_probability(
                        returns,
                        outcome_direction=outcome_direction,
                        outcome_threshold=outcome_threshold,
                        minimum_sample_size=resolved_minimum,
                        confidence_level=resolved_confidence,
                        prior_alpha=self._settings.conditional_probability_prior_alpha,
                        prior_beta=self._settings.conditional_probability_prior_beta,
                    )
                    estimate = ProbabilityEstimate(
                        target=target,
                        horizon_days=horizon,
                        sample_size=len(returns),
                        success_count=calculated.success_count,
                        meets_minimum=calculated.meets_minimum,
                        raw_probability=calculated.raw_probability,
                        probability=calculated.posterior_probability,
                        confidence_lower=calculated.credible_lower,
                        confidence_upper=calculated.credible_upper,
                        average_return=calculated.average_return,
                        prior_alpha=calculated.prior_alpha,
                        prior_beta=calculated.prior_beta,
                    )
                    estimates.append(estimate)
                    self._repository.session.add(self._result_model(run.id, estimate))
            run.status = "completed"
            self._repository.session.flush()
            return ConditionalProbabilityStudy(
                run_id=run.id,
                event_study_run_id=event_study.run_id,
                condition=event_study.definition,
                trigger=event_study.trigger,
                start_date=start_date,
                end_date=end_date,
                outcome_direction=outcome_direction,
                outcome_threshold=outcome_threshold,
                minimum_sample_size=resolved_minimum,
                confidence_level=resolved_confidence,
                event_count=len(event_study.occurrences),
                results=tuple(estimates),
            )
        except Exception as error:
            run.status = "failed"
            run.error_message = str(error)
            raise

    def latest(self) -> ConditionalProbabilityStudy | None:
        run = self._repository.latest_run()
        if run is None:
            return None
        if run.parameters.get("probability_estimator") != "beta_binomial_posterior_mean":
            return None
        if (
            run.parameters.get("price_adjustment_policy")
            != AdjustmentMode.POINT_IN_TIME_TOTAL_RETURN.value
        ):
            return None
        event_run = self._repository.get_event_study_run(run.event_study_run_id)
        if event_run is None:
            return None
        if (
            event_run.parameters.get("price_adjustment_policy")
            != AdjustmentMode.POINT_IN_TIME_TOTAL_RETURN.value
        ):
            return None
        definition = self._event_repository.get_definition(event_run.definition_id)
        trigger = self._event_repository.get_instrument(event_run.trigger_stock_id)
        if definition is None or trigger is None:
            return None
        estimates: list[ProbabilityEstimate] = []
        for item in self._repository.results_for_run(run.id):
            target = self._event_repository.get_instrument(item.target_stock_id)
            if target is None:
                continue
            estimates.append(
                ProbabilityEstimate(
                    target=self._event_repository.instrument_option(target),
                    horizon_days=item.horizon_days,
                    sample_size=item.sample_size,
                    success_count=item.success_count,
                    meets_minimum=item.meets_minimum,
                    raw_probability=self._optional_float(item.raw_probability),
                    probability=self._optional_float(item.probability),
                    confidence_lower=self._optional_float(item.confidence_lower),
                    confidence_upper=self._optional_float(item.confidence_upper),
                    average_return=self._optional_float(item.average_return),
                    prior_alpha=self._parameter_float(run.parameters, "prior_alpha", 1.0),
                    prior_beta=self._parameter_float(run.parameters, "prior_beta", 1.0),
                )
            )
        return ConditionalProbabilityStudy(
            run_id=run.id,
            event_study_run_id=event_run.id,
            condition=self._event_repository.definition_view(definition),
            trigger=self._event_repository.instrument_option(trigger),
            start_date=event_run.start_date,
            end_date=event_run.end_date,
            outcome_direction=run.outcome_direction,
            outcome_threshold=float(run.outcome_threshold),
            minimum_sample_size=run.minimum_sample_size,
            confidence_level=float(run.confidence_level),
            event_count=self._repository.event_count(event_run.id),
            results=tuple(estimates),
        )

    def minimum_sample_size(self) -> int:
        return self._settings.conditional_probability_minimum_sample_size

    def _default_horizons(self) -> tuple[int, ...]:
        return tuple(
            int(item) for item in self._settings.conditional_probability_horizons.split(",")
        )

    @classmethod
    def _result_model(
        cls,
        run_id: int,
        estimate: ProbabilityEstimate,
    ) -> ConditionalProbabilityResult:
        return ConditionalProbabilityResult(
            run_id=run_id,
            target_stock_id=estimate.target.id,
            horizon_days=estimate.horizon_days,
            sample_size=estimate.sample_size,
            success_count=estimate.success_count,
            meets_minimum=estimate.meets_minimum,
            raw_probability=cls._optional_decimal(estimate.raw_probability),
            probability=cls._optional_decimal(estimate.probability),
            confidence_lower=cls._optional_decimal(estimate.confidence_lower),
            confidence_upper=cls._optional_decimal(estimate.confidence_upper),
            average_return=cls._optional_decimal(estimate.average_return),
        )

    @staticmethod
    def _decimal(value: float) -> Decimal:
        return Decimal(str(round(value, 10)))

    @classmethod
    def _optional_decimal(cls, value: float | None) -> Decimal | None:
        return cls._decimal(value) if value is not None else None

    @staticmethod
    def _optional_float(value: Decimal | None) -> float | None:
        return float(value) if value is not None else None

    @staticmethod
    def _parameter_float(
        parameters: dict[str, object],
        key: str,
        default: float,
    ) -> float:
        value = parameters.get(key, default)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return default
