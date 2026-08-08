from datetime import date
from decimal import Decimal

from personal_alpha_terminal.analysis.market_graph.network import (
    calculate_network_metrics,
    discover_transmission_paths,
)
from personal_alpha_terminal.analysis.market_graph.repository import MarketGraphRepository
from personal_alpha_terminal.analysis.market_graph.schemas import (
    GraphEdgeMetric,
    GraphInstrument,
    GraphNodeMetric,
    MarketGraphResult,
    TransmissionPath,
)
from personal_alpha_terminal.analysis.market_graph.statistics import (
    build_statistical_edges,
)
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.models import (
    MarketGraphEdge,
    MarketGraphNode,
    MarketGraphPath,
    MarketGraphRun,
)


class MarketGraphService:
    """Build, score, persist, and restore dynamic market-network snapshots."""

    def __init__(self, repository: MarketGraphRepository, settings: Settings) -> None:
        self._repository = repository
        self._settings = settings

    def list_instruments(self) -> tuple[GraphInstrument, ...]:
        return tuple(self._repository.list_instruments())

    def run(
        self,
        *,
        instrument_ids: tuple[int, ...],
        start_date: date,
        end_date: date,
    ) -> MarketGraphResult:
        if start_date >= end_date:
            raise ValueError("start_date must be before end_date")
        unique_ids = tuple(dict.fromkeys(instrument_ids))
        if len(unique_ids) < 2:
            raise ValueError("at least two instruments are required")
        if len(unique_ids) > self._settings.market_graph_maximum_nodes:
            raise ValueError(
                "node count exceeds configured maximum "
                f"({self._settings.market_graph_maximum_nodes})"
            )
        run = MarketGraphRun(
            start_date=start_date,
            end_date=end_date,
            status="running",
            parameters={
                "instrument_ids": list(unique_ids),
                "minimum_observations": self._settings.market_graph_minimum_observations,
                "correlation_threshold": self._settings.market_graph_correlation_threshold,
                "maximum_lag_days": self._settings.market_graph_maximum_lag_days,
                "lead_threshold": self._settings.market_graph_lead_threshold,
                "lead_improvement": self._settings.market_graph_lead_improvement,
                "capital_threshold": self._settings.market_graph_capital_threshold,
                "flow_lookback_days": self._settings.market_graph_flow_lookback_days,
                "flow_proxy": "return_times_log_abnormal_volume",
                "capital_flow_is_proxy": True,
                "lag_unit": "common_trading_observations",
                "layout": "spring_layout_seed_42",
                "influence_method": "pagerank",
                "significance_alpha": self._settings.market_graph_significance_alpha,
                "significance_method": self._settings.market_graph_significance_method,
                "multiple_testing": ["benjamini_hochberg_fdr", "bonferroni"],
                "p_value_method": "pearson_t_test_effective_sample_size",
            },
        )
        self._repository.session.add(run)
        self._repository.session.flush()

        try:
            series = self._repository.load_series(
                unique_ids,
                start_date=start_date,
                end_date=end_date,
                flow_lookback_days=self._settings.market_graph_flow_lookback_days,
            )
            if len(series) != len(unique_ids):
                raise ValueError("one or more selected instruments do not exist")
            instruments = tuple(item.instrument for item in series)
            edges = build_statistical_edges(
                series,
                minimum_observations=self._settings.market_graph_minimum_observations,
                correlation_threshold=self._settings.market_graph_correlation_threshold,
                maximum_lag_days=self._settings.market_graph_maximum_lag_days,
                lead_threshold=self._settings.market_graph_lead_threshold,
                lead_improvement=self._settings.market_graph_lead_improvement,
                capital_threshold=self._settings.market_graph_capital_threshold,
                significance_alpha=self._settings.market_graph_significance_alpha,
                significance_method=self._settings.market_graph_significance_method,
            )
            nodes = calculate_network_metrics(instruments, edges)
            paths = discover_transmission_paths(
                instruments,
                edges,
                maximum_paths=self._settings.market_graph_maximum_paths,
            )
            self._persist_nodes(run.id, nodes)
            self._persist_edges(run.id, edges)
            self._persist_paths(run.id, paths)
            run.status = "completed"
            self._repository.session.flush()
            return MarketGraphResult(
                run_id=run.id,
                start_date=start_date,
                end_date=end_date,
                nodes=nodes,
                edges=edges,
                paths=paths,
            )
        except Exception as error:
            run.status = "failed"
            run.error_message = str(error)
            raise

    def latest(self) -> MarketGraphResult | None:
        run = self._repository.latest_run()
        if run is None:
            return None
        if "significance_method" not in run.parameters:
            return None
        node_models = self._repository.nodes_for_run(run.id)
        instruments = {
            item.node_key: GraphInstrument(
                id=item.stock_id,
                key=item.node_key,
                symbol=item.symbol,
                name=item.label,
                market=item.market,
                asset_type=item.asset_type,
                industry=item.industry,
            )
            for item in node_models
        }
        nodes = tuple(
            GraphNodeMetric(
                instrument=instruments[item.node_key],
                degree_centrality=float(item.degree_centrality),
                betweenness_centrality=float(item.betweenness_centrality),
                influence=float(item.influence),
                association_strength=float(item.association_strength),
                core_score=float(item.core_score),
                position_x=float(item.position_x),
                position_y=float(item.position_y),
            )
            for item in node_models
        )
        edges = tuple(
            GraphEdgeMetric(
                source=self._instrument_by_id(instruments, item.source_stock_id),
                target=self._instrument_by_id(instruments, item.target_stock_id),
                relationship_type=item.relationship_type,
                weight=float(item.weight),
                strength=float(item.strength),
                lag_days=item.lag_days,
                sample_size=item.sample_size,
                details=dict(item.details),
                p_value=self._optional_float(item.p_value),
                fdr_q_value=self._optional_float(item.fdr_q_value),
                bonferroni_p_value=self._optional_float(item.bonferroni_p_value),
                significant_fdr=item.significant_fdr,
                significant_bonferroni=item.significant_bonferroni,
            )
            for item in self._repository.edges_for_run(run.id)
        )
        paths = tuple(
            TransmissionPath(
                rank=item.path_rank,
                nodes=(
                    instruments[item.node_keys[0]],
                    instruments[item.node_keys[1]],
                    instruments[item.node_keys[2]],
                ),
                relationship_types=(
                    item.relationship_types[0],
                    item.relationship_types[1],
                ),
                aggregate_strength=float(item.aggregate_strength),
                total_lag_days=item.total_lag_days,
            )
            for item in self._repository.paths_for_run(run.id)
        )
        return MarketGraphResult(
            run_id=run.id,
            start_date=run.start_date,
            end_date=run.end_date,
            nodes=nodes,
            edges=edges,
            paths=paths,
        )

    def _persist_nodes(
        self,
        run_id: int,
        nodes: tuple[GraphNodeMetric, ...],
    ) -> None:
        self._repository.session.add_all(
            [
                MarketGraphNode(
                    run_id=run_id,
                    stock_id=item.instrument.id,
                    node_key=item.instrument.key,
                    label=item.instrument.name,
                    symbol=item.instrument.symbol,
                    market=item.instrument.market,
                    asset_type=item.instrument.asset_type,
                    industry=item.instrument.industry,
                    degree_centrality=self._decimal(item.degree_centrality),
                    betweenness_centrality=self._decimal(item.betweenness_centrality),
                    influence=self._decimal(item.influence),
                    association_strength=self._decimal(item.association_strength),
                    core_score=self._decimal(item.core_score),
                    position_x=self._decimal(item.position_x),
                    position_y=self._decimal(item.position_y),
                )
                for item in nodes
            ]
        )

    def _persist_edges(
        self,
        run_id: int,
        edges: tuple[GraphEdgeMetric, ...],
    ) -> None:
        self._repository.session.add_all(
            [
                MarketGraphEdge(
                    run_id=run_id,
                    source_stock_id=item.source.id,
                    target_stock_id=item.target.id,
                    relationship_type=item.relationship_type,
                    weight=self._decimal(item.weight),
                    strength=self._decimal(item.strength),
                    lag_days=item.lag_days,
                    sample_size=item.sample_size,
                    p_value=self._optional_decimal(item.p_value),
                    fdr_q_value=self._optional_decimal(item.fdr_q_value),
                    bonferroni_p_value=self._optional_decimal(item.bonferroni_p_value),
                    significant_fdr=item.significant_fdr,
                    significant_bonferroni=item.significant_bonferroni,
                    details=item.details,
                )
                for item in edges
            ]
        )

    def _persist_paths(
        self,
        run_id: int,
        paths: tuple[TransmissionPath, ...],
    ) -> None:
        self._repository.session.add_all(
            [
                MarketGraphPath(
                    run_id=run_id,
                    path_rank=item.rank,
                    node_keys=[node.key for node in item.nodes],
                    node_labels=[node.label for node in item.nodes],
                    relationship_types=list(item.relationship_types),
                    aggregate_strength=self._decimal(item.aggregate_strength),
                    total_lag_days=item.total_lag_days,
                )
                for item in paths
            ]
        )

    @staticmethod
    def _instrument_by_id(
        instruments: dict[str, GraphInstrument],
        stock_id: int,
    ) -> GraphInstrument:
        return next(item for item in instruments.values() if item.id == stock_id)

    @staticmethod
    def _decimal(value: float) -> Decimal:
        return Decimal(str(round(value, 10)))

    @classmethod
    def _optional_decimal(cls, value: float | None) -> Decimal | None:
        return cls._decimal(value) if value is not None else None

    @staticmethod
    def _optional_float(value: Decimal | None) -> float | None:
        return float(value) if value is not None else None
