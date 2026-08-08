from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class GraphInstrument:
    id: int
    key: str
    symbol: str
    name: str
    market: str
    asset_type: str
    industry: str | None

    @property
    def label(self) -> str:
        return f"{self.symbol} · {self.name} ({self.asset_type})"


@dataclass(frozen=True, slots=True)
class MarketSeries:
    instrument: GraphInstrument
    returns: tuple[tuple[date, float], ...]
    flow_proxy: tuple[tuple[date, float], ...]


@dataclass(frozen=True, slots=True)
class GraphEdgeMetric:
    source: GraphInstrument
    target: GraphInstrument
    relationship_type: str
    weight: float
    strength: float
    lag_days: int
    sample_size: int
    details: dict[str, object]
    p_value: float | None = None
    fdr_q_value: float | None = None
    bonferroni_p_value: float | None = None
    significant_fdr: bool = False
    significant_bonferroni: bool = False


@dataclass(frozen=True, slots=True)
class GraphNodeMetric:
    instrument: GraphInstrument
    degree_centrality: float
    betweenness_centrality: float
    influence: float
    association_strength: float
    core_score: float
    position_x: float
    position_y: float


@dataclass(frozen=True, slots=True)
class TransmissionPath:
    rank: int
    nodes: tuple[GraphInstrument, GraphInstrument, GraphInstrument]
    relationship_types: tuple[str, str]
    aggregate_strength: float
    total_lag_days: int


@dataclass(frozen=True, slots=True)
class MarketGraphResult:
    run_id: int
    start_date: date
    end_date: date
    nodes: tuple[GraphNodeMetric, ...]
    edges: tuple[GraphEdgeMetric, ...]
    paths: tuple[TransmissionPath, ...]
