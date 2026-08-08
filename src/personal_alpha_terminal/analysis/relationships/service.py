from datetime import date
from decimal import Decimal

from personal_alpha_terminal.analysis.relationships.repository import (
    RelationshipRepository,
)
from personal_alpha_terminal.analysis.relationships.schemas import (
    CorrelationAnomaly,
    CorrelationObservation,
    EntityOption,
    RelationshipResult,
)
from personal_alpha_terminal.analysis.relationships.statistics import (
    correlation_matrix,
    detect_correlation_changes,
    rolling_correlations,
)
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.models import (
    RelationshipAnalysisRun,
    RelationshipAnomaly,
    RelationshipCorrelation,
)


class RelationshipAnalysisService:
    """Orchestrate explainable relationship analysis and persist every result."""

    def __init__(self, repository: RelationshipRepository, settings: Settings) -> None:
        self._repository = repository
        self._settings = settings

    def list_entities(self, universe_type: str) -> tuple[EntityOption, ...]:
        return tuple(self._repository.list_entities(universe_type))

    def run(
        self,
        *,
        universe_type: str,
        entity_ids: tuple[int, ...],
        method: str,
        start_date: date,
        end_date: date,
    ) -> RelationshipResult:
        if start_date >= end_date:
            raise ValueError("start_date must be before end_date")
        unique_ids = tuple(dict.fromkeys(entity_ids))
        if len(unique_ids) < 2:
            raise ValueError("at least two entities are required")
        if len(unique_ids) > self._settings.relationship_max_entities:
            raise ValueError(
                "entity count exceeds configured maximum "
                f"({self._settings.relationship_max_entities})"
            )
        windows = self._rolling_windows()
        run = RelationshipAnalysisRun(
            universe_type=universe_type,
            method=method,
            start_date=start_date,
            end_date=end_date,
            status="running",
            parameters={
                "entity_ids": list(unique_ids),
                "rolling_windows": list(windows),
                "min_observations": self._settings.relationship_min_observations,
                "baseline_window": self._settings.relationship_baseline_window,
                "current_window": self._settings.relationship_current_window,
                "change_threshold": self._settings.relationship_change_threshold,
                "return_type": "simple_daily",
                "industry_aggregation": "equal_weight",
                "missing_data": "pairwise_complete_no_forward_fill",
            },
        )
        self._repository.session.add(run)
        self._repository.session.flush()

        try:
            series = self._repository.load_returns(
                universe_type,
                unique_ids,
                start_date=start_date,
                end_date=end_date,
            )
            if len(series) < 2:
                raise ValueError("fewer than two valid entities were found")
            matrix = correlation_matrix(
                series,
                method=method,
                as_of_date=end_date,
                min_observations=self._settings.relationship_min_observations,
            )
            if not matrix:
                raise ValueError("insufficient overlapping return observations")
            rolling = rolling_correlations(series, method=method, windows=windows)
            anomalies = detect_correlation_changes(
                series,
                method=method,
                baseline_window=self._settings.relationship_baseline_window,
                current_window=self._settings.relationship_current_window,
                threshold=self._settings.relationship_change_threshold,
            )
            self._persist_correlations(run.id, (*matrix, *rolling))
            self._persist_anomalies(run.id, anomalies)
            run.status = "completed"
            self._repository.session.flush()
            return RelationshipResult(
                run_id=run.id,
                universe_type=universe_type,
                method=method,
                start_date=start_date,
                end_date=end_date,
                entities=tuple(item.option for item in series),
                matrix=matrix,
                rolling=rolling,
                anomalies=anomalies,
            )
        except Exception as error:
            run.status = "failed"
            run.error_message = str(error)
            raise

    def latest(self, universe_type: str, method: str) -> RelationshipResult | None:
        run = self._repository.latest_run(universe_type, method)
        if run is None:
            return None
        correlations = self._repository.correlations_for_run(run.id)
        anomalies = self._repository.anomalies_for_run(run.id)
        matrix = tuple(
            self._correlation_schema(item) for item in correlations if item.window_days is None
        )
        rolling = tuple(
            self._correlation_schema(item) for item in correlations if item.window_days is not None
        )
        entity_by_key: dict[str, EntityOption] = {}
        for item in (*matrix, *rolling):
            entity_by_key[item.left.key] = item.left
            entity_by_key[item.right.key] = item.right
        return RelationshipResult(
            run_id=run.id,
            universe_type=run.universe_type,
            method=run.method,
            start_date=run.start_date,
            end_date=run.end_date,
            entities=tuple(entity_by_key.values()),
            matrix=matrix,
            rolling=rolling,
            anomalies=tuple(self._anomaly_schema(item) for item in anomalies),
        )

    def _persist_correlations(
        self,
        run_id: int,
        observations: tuple[CorrelationObservation, ...],
    ) -> None:
        self._repository.session.add_all(
            [
                RelationshipCorrelation(
                    run_id=run_id,
                    left_entity_type=item.left.entity_type,
                    left_entity_id=item.left.id,
                    left_entity_key=item.left.key,
                    left_entity_label=item.left.label,
                    right_entity_type=item.right.entity_type,
                    right_entity_id=item.right.id,
                    right_entity_key=item.right.key,
                    right_entity_label=item.right.label,
                    window_days=item.window_days,
                    as_of_date=item.as_of_date,
                    correlation=Decimal(str(round(item.correlation, 8))),
                    sample_size=item.sample_size,
                )
                for item in observations
            ]
        )

    def _persist_anomalies(
        self,
        run_id: int,
        anomalies: tuple[CorrelationAnomaly, ...],
    ) -> None:
        self._repository.session.add_all(
            [
                RelationshipAnomaly(
                    run_id=run_id,
                    left_entity_type=item.left.entity_type,
                    left_entity_id=item.left.id,
                    left_entity_key=item.left.key,
                    left_entity_label=item.left.label,
                    right_entity_type=item.right.entity_type,
                    right_entity_id=item.right.id,
                    right_entity_key=item.right.key,
                    right_entity_label=item.right.label,
                    detected_on=item.detected_on,
                    baseline_window_days=item.baseline_window_days,
                    current_window_days=item.current_window_days,
                    baseline_correlation=Decimal(str(round(item.baseline_correlation, 8))),
                    current_correlation=Decimal(str(round(item.current_correlation, 8))),
                    absolute_change=Decimal(str(round(item.absolute_change, 8))),
                    threshold=Decimal(str(item.threshold)),
                    direction=item.direction,
                    baseline_sample_size=item.baseline_sample_size,
                    current_sample_size=item.current_sample_size,
                )
                for item in anomalies
            ]
        )

    def _rolling_windows(self) -> tuple[int, ...]:
        return tuple(int(item) for item in self._settings.relationship_rolling_windows.split(","))

    @staticmethod
    def _correlation_schema(item: RelationshipCorrelation) -> CorrelationObservation:
        return CorrelationObservation(
            left=EntityOption(
                id=item.left_entity_id,
                entity_type=item.left_entity_type,
                key=item.left_entity_key,
                label=item.left_entity_label,
            ),
            right=EntityOption(
                id=item.right_entity_id,
                entity_type=item.right_entity_type,
                key=item.right_entity_key,
                label=item.right_entity_label,
            ),
            as_of_date=item.as_of_date,
            correlation=float(item.correlation),
            sample_size=item.sample_size,
            window_days=item.window_days,
        )

    @staticmethod
    def _anomaly_schema(item: RelationshipAnomaly) -> CorrelationAnomaly:
        return CorrelationAnomaly(
            left=EntityOption(
                id=item.left_entity_id,
                entity_type=item.left_entity_type,
                key=item.left_entity_key,
                label=item.left_entity_label,
            ),
            right=EntityOption(
                id=item.right_entity_id,
                entity_type=item.right_entity_type,
                key=item.right_entity_key,
                label=item.right_entity_label,
            ),
            detected_on=item.detected_on,
            baseline_correlation=float(item.baseline_correlation),
            current_correlation=float(item.current_correlation),
            absolute_change=float(item.absolute_change),
            threshold=float(item.threshold),
            direction=item.direction,
            baseline_window_days=item.baseline_window_days,
            current_window_days=item.current_window_days,
            baseline_sample_size=item.baseline_sample_size,
            current_sample_size=item.current_sample_size,
        )
