from decimal import Decimal

from sqlalchemy.orm import Session

from personal_alpha_terminal.alpha_discovery.schemas import (
    AlphaDiscoveryConfig,
    AlphaDiscoveryResult,
    FactorCombinationEvaluation,
    ICEvaluation,
)
from personal_alpha_terminal.models import (
    AlphaCombinationResult,
    AlphaDiscoveryRun,
    AlphaFactorEvaluation,
)


class AlphaDiscoveryRepository:
    """Persist immutable discovery evidence, splits, and selected hypotheses."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create_run(
        self,
        result: AlphaDiscoveryResult,
        config: AlphaDiscoveryConfig,
    ) -> AlphaDiscoveryRun:
        run = AlphaDiscoveryRun(
            market=result.market,
            start_date=result.start_date,
            end_date=result.end_date,
            horizon_days=result.horizon_days,
            status="running",
            data_fingerprint=result.data_fingerprint,
            parameters={
                "horizon_days": config.horizon_days,
                "rebalance_interval": config.rebalance_interval,
                "minimum_cross_section": config.minimum_cross_section,
                "minimum_dates_per_split": config.minimum_dates_per_split,
                "train_fraction": config.train_fraction,
                "validation_fraction": config.validation_fraction,
                "fdr_alpha": config.fdr_alpha,
                "minimum_abs_directional_ic": config.minimum_abs_directional_ic,
                "maximum_factor_correlation": config.maximum_factor_correlation,
                "maximum_combination_size": config.maximum_combination_size,
                "maximum_candidate_factors": config.maximum_candidate_factors,
                "maximum_selected_combinations": (config.maximum_selected_combinations),
                "selection_quantile": config.selection_quantile,
                "environment_max_staleness_days": (config.environment_max_staleness_days),
                "multiple_testing": "Benjamini-Hochberg FDR",
                "combination_weighting": "equal_weight_directional_percentile",
                "test_policy": "revealed_only_after_validation_selection",
            },
            split_dates={
                "train": [item.isoformat() for item in result.split.train_dates],
                "validation": [item.isoformat() for item in result.split.validation_dates],
                "test": [item.isoformat() for item in result.split.test_dates],
                "purged": [item.isoformat() for item in result.split.purged_dates],
            },
        )
        self.session.add(run)
        self.session.flush()
        return run

    def save_evaluations(
        self,
        run_id: int,
        evaluations: tuple[ICEvaluation, ...],
    ) -> None:
        self.session.add_all(
            [
                AlphaFactorEvaluation(
                    run_id=run_id,
                    factor_name=item.factor_name,
                    split_name=item.split_name,
                    evaluation_axis=item.evaluation_axis,
                    date_count=item.date_count,
                    observation_count=item.observation_count,
                    raw_mean_ic=_decimal(item.raw_mean_ic),
                    directional_mean_ic=_decimal(item.directional_mean_ic),
                    median_ic=_decimal(item.median_ic),
                    ic_standard_deviation=_decimal(item.ic_standard_deviation),
                    information_ratio=_decimal(item.information_ratio),
                    positive_ratio=_decimal(item.positive_ratio),
                    pearson_ic=_decimal(item.pearson_ic),
                    p_value=_decimal(item.p_value),
                    adjusted_p_value=_decimal(item.adjusted_p_value),
                    significant=item.significant,
                    confidence_score=item.confidence_score,
                    warning=item.warning,
                )
                for item in evaluations
            ]
        )

    def save_combinations(
        self,
        run_id: int,
        combinations: tuple[FactorCombinationEvaluation, ...],
    ) -> None:
        self.session.add_all(
            [
                AlphaCombinationResult(
                    run_id=run_id,
                    rank=item.rank,
                    factors=list(item.factors),
                    weights=list(item.weights),
                    train_ic=_required_decimal(item.train.directional_mean_ic),
                    validation_ic=_required_decimal(item.validation.directional_mean_ic),
                    test_ic=_decimal(item.test.directional_mean_ic),
                    train_adjusted_p=_decimal(item.train.adjusted_p_value),
                    validation_adjusted_p=_decimal(item.validation.adjusted_p_value),
                    test_adjusted_p=_decimal(item.test.adjusted_p_value),
                    train_long_short_return=_decimal(item.train_long_short_return),
                    validation_long_short_return=_decimal(item.validation_long_short_return),
                    test_long_short_return=_decimal(item.test_long_short_return),
                    maximum_pairwise_correlation=_required_decimal(
                        item.maximum_pairwise_correlation
                    ),
                    confidence_score=item.confidence_score,
                    status=item.status,
                    selection_reasons=list(item.selection_reasons),
                )
                for item in combinations
            ]
        )

    def mark_completed(self, run: AlphaDiscoveryRun) -> None:
        run.status = "completed"
        self.session.flush()

    def mark_failed(self, run: AlphaDiscoveryRun, error: Exception) -> None:
        run.status = "failed"
        run.error_message = str(error)
        self.session.flush()


def _decimal(value: float | None) -> Decimal | None:
    return Decimal(str(round(value, 14))) if value is not None else None


def _required_decimal(value: float | None) -> Decimal:
    if value is None:
        raise ValueError("selected combination is missing a required IC value")
    return Decimal(str(round(value, 14)))
