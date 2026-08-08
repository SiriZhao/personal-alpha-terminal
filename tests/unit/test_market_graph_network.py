from personal_alpha_terminal.analysis.market_graph.network import (
    calculate_network_metrics,
    discover_transmission_paths,
)
from personal_alpha_terminal.analysis.market_graph.schemas import (
    GraphEdgeMetric,
    GraphInstrument,
)


def instrument(instrument_id: int, symbol: str) -> GraphInstrument:
    return GraphInstrument(
        id=instrument_id,
        key=f"stock:{instrument_id}",
        symbol=symbol,
        name=symbol,
        market="US",
        asset_type="stock",
        industry="Semiconductors",
    )


def edge(
    source: GraphInstrument,
    target: GraphInstrument,
    strength: float,
) -> GraphEdgeMetric:
    return GraphEdgeMetric(
        source=source,
        target=target,
        relationship_type="lead_lag",
        weight=strength,
        strength=strength,
        lag_days=1,
        sample_size=100,
        details={},
    )


def test_network_metrics_and_three_node_path() -> None:
    nvda = instrument(1, "NVDA")
    tsm = instrument(2, "TSM")
    asml = instrument(3, "ASML")
    edges = (edge(nvda, tsm, 0.9), edge(tsm, asml, 0.8))

    nodes = calculate_network_metrics((nvda, tsm, asml), edges)
    paths = discover_transmission_paths(
        (nvda, tsm, asml),
        edges,
        maximum_paths=10,
    )

    by_symbol = {node.instrument.symbol: node for node in nodes}
    assert by_symbol["TSM"].betweenness_centrality == 1
    assert all(0 <= node.core_score <= 1 for node in nodes)
    assert len(paths) == 1
    assert [node.symbol for node in paths[0].nodes] == ["NVDA", "TSM", "ASML"]
    assert paths[0].aggregate_strength > 0.8
