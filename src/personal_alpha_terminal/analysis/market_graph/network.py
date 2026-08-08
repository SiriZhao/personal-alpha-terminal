from collections import defaultdict
from math import sqrt

import networkx as nx

from personal_alpha_terminal.analysis.market_graph.schemas import (
    GraphEdgeMetric,
    GraphInstrument,
    GraphNodeMetric,
    TransmissionPath,
)


def calculate_network_metrics(
    instruments: tuple[GraphInstrument, ...],
    edges: tuple[GraphEdgeMetric, ...],
) -> tuple[GraphNodeMetric, ...]:
    directed = nx.DiGraph()
    undirected = nx.Graph()
    for instrument in instruments:
        directed.add_node(instrument.key)
        undirected.add_node(instrument.key)
    for edge in edges:
        if edge.relationship_type == "correlation":
            _add_weight(directed, edge.source.key, edge.target.key, edge.strength)
            _add_weight(directed, edge.target.key, edge.source.key, edge.strength)
        else:
            _add_weight(directed, edge.source.key, edge.target.key, edge.strength)
        _add_weight(undirected, edge.source.key, edge.target.key, edge.strength)

    for _source, _target, attributes in undirected.edges(data=True):
        attributes["distance"] = 1 / max(float(attributes["weight"]), 1e-12)

    degree = nx.degree_centrality(undirected)
    betweenness = nx.betweenness_centrality(
        undirected,
        weight="distance",
        normalized=True,
    )
    if directed.number_of_edges():
        try:
            pagerank = nx.pagerank(directed, weight="weight", max_iter=500)
        except nx.PowerIterationFailedConvergence:
            pagerank = {node: 1 / len(directed) for node in directed}
    else:
        pagerank = {node: 1 / len(directed) for node in directed}
    max_pagerank = max(pagerank.values(), default=1.0)
    influence = {
        node: value / max_pagerank if max_pagerank else 0.0 for node, value in pagerank.items()
    }
    weighted_degrees = dict(undirected.degree(weight="weight"))
    max_weighted_degree = max(weighted_degrees.values(), default=1.0)
    association = {
        node: value / max_weighted_degree if max_weighted_degree else 0.0
        for node, value in weighted_degrees.items()
    }
    positions = nx.spring_layout(undirected, weight="weight", seed=42)
    by_key = {instrument.key: instrument for instrument in instruments}
    metrics = []
    for node_key in directed:
        core_score = (
            degree[node_key] + betweenness[node_key] + influence[node_key] + association[node_key]
        ) / 4
        position = positions[node_key]
        metrics.append(
            GraphNodeMetric(
                instrument=by_key[node_key],
                degree_centrality=degree[node_key],
                betweenness_centrality=betweenness[node_key],
                influence=influence[node_key],
                association_strength=association[node_key],
                core_score=core_score,
                position_x=float(position[0]),
                position_y=float(position[1]),
            )
        )
    return tuple(sorted(metrics, key=lambda item: item.core_score, reverse=True))


def discover_transmission_paths(
    instruments: tuple[GraphInstrument, ...],
    edges: tuple[GraphEdgeMetric, ...],
    *,
    maximum_paths: int,
) -> tuple[TransmissionPath, ...]:
    strongest_edge: dict[tuple[str, str], GraphEdgeMetric] = {}
    for edge in edges:
        if edge.relationship_type == "correlation":
            continue
        key = (edge.source.key, edge.target.key)
        existing = strongest_edge.get(key)
        if existing is None or edge.strength > existing.strength:
            strongest_edge[key] = edge

    successors: defaultdict[str, list[str]] = defaultdict(list)
    for source, target in strongest_edge:
        successors[source].append(target)
    by_key = {instrument.key: instrument for instrument in instruments}
    candidates: list[
        tuple[
            float,
            tuple[GraphInstrument, GraphInstrument, GraphInstrument],
            tuple[str, str],
            int,
        ]
    ] = []
    for source, middle_nodes in successors.items():
        for middle in middle_nodes:
            for target in successors.get(middle, []):
                if target in {source, middle}:
                    continue
                first = strongest_edge[(source, middle)]
                second = strongest_edge[(middle, target)]
                candidates.append(
                    (
                        sqrt(first.strength * second.strength),
                        (by_key[source], by_key[middle], by_key[target]),
                        (first.relationship_type, second.relationship_type),
                        first.lag_days + second.lag_days,
                    )
                )
    candidates.sort(key=lambda item: item[0], reverse=True)
    return tuple(
        TransmissionPath(
            rank=rank,
            nodes=nodes,
            relationship_types=relationship_types,
            aggregate_strength=strength,
            total_lag_days=total_lag,
        )
        for rank, (strength, nodes, relationship_types, total_lag) in enumerate(
            candidates[:maximum_paths],
            start=1,
        )
    )


def _add_weight(
    graph: nx.Graph,
    source: str,
    target: str,
    strength: float,
) -> None:
    if graph.has_edge(source, target):
        graph[source][target]["weight"] += strength
    else:
        graph.add_edge(source, target, weight=strength)
