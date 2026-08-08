from dataclasses import dataclass
from datetime import date

from personal_alpha_terminal.analysis.market_graph.schemas import GraphInstrument


@dataclass(frozen=True, slots=True)
class LagMetric:
    lag_days: int
    cross_correlation: float
    granger_f_statistic: float
    granger_p_value: float
    sample_size: int


@dataclass(frozen=True, slots=True)
class PairEvidence:
    source: GraphInstrument
    target: GraphInstrument
    best_lag_days: int
    cross_correlation: float
    granger_f_statistic: float
    raw_p_value: float
    lag_adjusted_p_value: float
    q_value: float
    confidence_score: float
    sample_size: int
    is_significant: bool
    metrics: tuple[LagMetric, ...]


@dataclass(frozen=True, slots=True)
class LeadLagAnalysisResult:
    run_id: int
    start_date: date
    end_date: date
    pairs: tuple[PairEvidence, ...]

    @property
    def significant_pairs(self) -> tuple[PairEvidence, ...]:
        return tuple(pair for pair in self.pairs if pair.is_significant)
