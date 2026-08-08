from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from math import atanh, isfinite, sqrt, tanh
from statistics import NormalDist

import numpy as np
import pandas as pd
from pydantic import Field

from personal_alpha_terminal.analysis.market_graph.statistics import correlation_test
from personal_alpha_terminal.analysis.statistical_validation import benjamini_hochberg
from personal_alpha_terminal.intelligence.schemas import BacktestSafety, StrictModel, _aware
from personal_alpha_terminal.quant_engine.relationship_validation import (
    RelationshipEvidence,
    RelationshipUse,
    validate_relationship_for_alpha,
)


class RelationshipNodeType(StrEnum):
    STOCK = "STOCK"
    ETF = "ETF"
    SECTOR = "SECTOR"
    INDEX = "INDEX"
    MACRO = "MACRO"
    NARRATIVE = "NARRATIVE"


class RelationshipType(StrEnum):
    CORRELATION = "CORRELATION"
    ROLLING_CORRELATION = "ROLLING_CORRELATION"
    LEAD_LAG = "LEAD_LAG"
    CONDITIONAL_ASSOCIATION = "CONDITIONAL_ASSOCIATION"
    EVENT_CO_EXPOSURE = "EVENT_CO_EXPOSURE"
    NARRATIVE_CO_EXPOSURE = "NARRATIVE_CO_EXPOSURE"
    SECTOR_RELATION = "SECTOR_RELATION"


class RelationshipNode(StrictModel):
    node_id: str
    symbol: str
    node_type: RelationshipNodeType
    sector: str | None = None
    industry: str | None = None
    data_version: str


class RelationshipEdge(StrictModel):
    edge_id: str
    schema_version: str = "relationship-edge-v1"
    source_node: str
    target_node: str
    relationship_type: RelationshipType
    window: int
    lag: int
    strength: float = Field(ge=0, le=1)
    signed_strength: float = Field(ge=-1, le=1)
    direction: str
    sample_size: int = Field(ge=0)
    effective_sample_size: float = Field(ge=0)
    confidence_interval: tuple[float, float]
    raw_p_value: float = Field(ge=0, le=1)
    adjusted_p_value: float = Field(ge=0, le=1)
    regime: str
    rolling_strength: tuple[float, ...]
    stability_score: float = Field(ge=0, le=1)
    recent_decay: float = Field(ge=0, le=1)
    oos_survival: float = Field(ge=0, le=1)
    relationship_use: RelationshipUse
    blockers: tuple[str, ...]
    last_updated: datetime
    data_cutoff: datetime
    model_version: str
    data_version: str
    backtest_safety: BacktestSafety
    causal_disclaimer: str = "Statistical association; not evidence of causation."

    def __init__(self, **data: object) -> None:
        super().__init__(**data)
        _aware(self.last_updated, "last_updated")
        _aware(self.data_cutoff, "data_cutoff")
        if self.last_updated > self.data_cutoff:
            raise ValueError("relationship edge was updated after its PIT cutoff")
        lower, upper = self.confidence_interval
        if not -1 <= lower <= upper <= 1:
            raise ValueError("relationship confidence interval is invalid")
        if self.source_node == self.target_node:
            raise ValueError("self relationships are not stored")
        if "caus" not in self.causal_disclaimer.lower():
            raise ValueError("relationship output must include a causal disclaimer")


class RelationshipGraphSnapshot(StrictModel):
    snapshot_id: str
    schema_version: str = "relationship-graph-v1"
    nodes: tuple[RelationshipNode, ...]
    edges: tuple[RelationshipEdge, ...]
    data_cutoff: datetime
    model_version: str
    data_version: str

    def __init__(self, **data: object) -> None:
        super().__init__(**data)
        _aware(self.data_cutoff, "data_cutoff")
        node_ids = {item.node_id for item in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("relationship graph contains duplicate nodes")
        if any(
            edge.source_node not in node_ids or edge.target_node not in node_ids
            for edge in self.edges
        ):
            raise ValueError("relationship edge references an unknown node")


@dataclass(frozen=True, slots=True)
class RelationshipGraphConfig:
    windows: tuple[int, ...] = (20, 60, 120)
    minimum_sample_size: int = 60
    maximum_lag: int = 5
    fdr_threshold: float = 0.05
    minimum_abs_strength: float = 0.20
    minimum_oos_survival: float = 0.60
    model_version: str = "pit-relationship-graph-v1"

    def __post_init__(self) -> None:
        if not self.windows or tuple(sorted(set(self.windows))) != self.windows:
            raise ValueError("relationship windows must be sorted and unique")
        if min(self.windows) < 3 or self.minimum_sample_size < 30:
            raise ValueError("relationship windows/sample threshold are too small")
        if self.maximum_lag < 1 or not 0 < self.fdr_threshold < 1:
            raise ValueError("relationship lag/FDR settings are invalid")
        if not 0 <= self.minimum_abs_strength <= 1:
            raise ValueError("relationship strength threshold is invalid")


@dataclass(frozen=True, slots=True)
class _RawEdge:
    source: RelationshipNode
    target: RelationshipNode
    relationship_type: RelationshipType
    lag: int
    correlation: float
    p_value: float
    effective_n: float
    sample_size: int
    rolling: tuple[float, ...]


class MarketRelationshipGraphEngine:
    """PIT statistical graph. Edges remain contextual until OOS/economic validation."""

    def __init__(self, config: RelationshipGraphConfig | None = None) -> None:
        self.config = config or RelationshipGraphConfig()

    def build(
        self,
        returns: pd.DataFrame,
        *,
        nodes: tuple[RelationshipNode, ...],
        data_cutoff: datetime,
        data_version: str,
        regime: str = "UNAVAILABLE",
        estimated_cost: float = 0.001,
        expected_return_by_edge: dict[tuple[str, str, int], float] | None = None,
        oos_survival_by_edge: dict[tuple[str, str, int], float] | None = None,
    ) -> RelationshipGraphSnapshot:
        _aware(data_cutoff, "data_cutoff")
        clean = _validate_returns(returns, data_cutoff)
        node_map = {item.symbol: item for item in nodes}
        symbols = tuple(symbol for symbol in clean.columns if symbol in node_map)
        if len(symbols) < 2:
            return self._snapshot(nodes, (), data_cutoff, data_version)
        raw: list[_RawEdge] = []
        for left_index, left_symbol in enumerate(symbols):
            for right_symbol in symbols[left_index + 1 :]:
                pair = clean[[left_symbol, right_symbol]].dropna()
                if len(pair) < self.config.minimum_sample_size:
                    continue
                tested = correlation_test(
                    tuple(float(value) for value in pair[left_symbol]),
                    tuple(float(value) for value in pair[right_symbol]),
                )
                if tested is not None:
                    correlation, p_value, effective_n = tested
                    raw.append(
                        _RawEdge(
                            node_map[left_symbol],
                            node_map[right_symbol],
                            RelationshipType.CORRELATION,
                            0,
                            correlation,
                            p_value,
                            effective_n,
                            len(pair),
                            _rolling_correlations(
                                pair[left_symbol],
                                pair[right_symbol],
                                self.config.windows,
                            ),
                        )
                    )
                raw.extend(
                    self._lead_lag_edges(
                        pair,
                        node_map[left_symbol],
                        node_map[right_symbol],
                    )
                )
        adjusted = benjamini_hochberg([item.p_value for item in raw])
        edges = tuple(
            self._materialize_edge(
                item,
                adjusted_p=q_value,
                data_cutoff=data_cutoff,
                data_version=data_version,
                regime=regime,
                estimated_cost=estimated_cost,
                expected_return=(expected_return_by_edge or {}).get(
                    (item.source.node_id, item.target.node_id, item.lag), 0.0
                ),
                oos_survival=(oos_survival_by_edge or {}).get(
                    (item.source.node_id, item.target.node_id, item.lag), 0.0
                ),
            )
            for item, q_value in zip(raw, adjusted, strict=True)
        )
        return self._snapshot(nodes, edges, data_cutoff, data_version)

    def coexposure_edges(
        self,
        *,
        nodes: tuple[RelationshipNode, ...],
        exposures: dict[str, set[str]],
        relationship_type: RelationshipType,
        data_cutoff: datetime,
        data_version: str,
        backtest_safe: bool,
    ) -> tuple[RelationshipEdge, ...]:
        if relationship_type not in {
            RelationshipType.EVENT_CO_EXPOSURE,
            RelationshipType.NARRATIVE_CO_EXPOSURE,
        }:
            raise ValueError("co-exposure edge type is invalid")
        _aware(data_cutoff, "data_cutoff")
        output: list[RelationshipEdge] = []
        for left_index, left in enumerate(nodes):
            for right in nodes[left_index + 1 :]:
                left_set = exposures.get(left.node_id, set())
                right_set = exposures.get(right.node_id, set())
                union = left_set | right_set
                if not union:
                    continue
                strength = len(left_set & right_set) / len(union)
                if strength <= 0:
                    continue
                edge_id = _edge_id(
                    left.node_id,
                    right.node_id,
                    relationship_type.value,
                    "0",
                    data_cutoff.isoformat(),
                )
                output.append(
                    RelationshipEdge(
                        edge_id=edge_id,
                        source_node=left.node_id,
                        target_node=right.node_id,
                        relationship_type=relationship_type,
                        window=0,
                        lag=0,
                        strength=strength,
                        signed_strength=strength,
                        direction="UNDIRECTED",
                        sample_size=len(union),
                        effective_sample_size=float(len(union)),
                        confidence_interval=(0.0, min(1.0, strength)),
                        raw_p_value=1.0,
                        adjusted_p_value=1.0,
                        regime="UNAVAILABLE",
                        rolling_strength=(),
                        stability_score=0.0,
                        recent_decay=0.0,
                        oos_survival=0.0,
                        relationship_use=RelationshipUse.RESEARCH_INSIGHT,
                        blockers=("co-exposure is contextual and has no causal validation",),
                        last_updated=data_cutoff,
                        data_cutoff=data_cutoff,
                        model_version=self.config.model_version,
                        data_version=data_version,
                        backtest_safety=(
                            BacktestSafety.BACKTEST_SAFE
                            if backtest_safe
                            else BacktestSafety.NOT_BACKTEST_SAFE
                        ),
                    )
                )
        return tuple(output)

    def _lead_lag_edges(
        self,
        pair: pd.DataFrame,
        left: RelationshipNode,
        right: RelationshipNode,
    ) -> tuple[_RawEdge, ...]:
        output: list[_RawEdge] = []
        for source, target in ((left, right), (right, left)):
            source_values = pair[source.symbol]
            target_values = pair[target.symbol]
            for lag in range(1, self.config.maximum_lag + 1):
                aligned = pd.concat(
                    [
                        source_values.iloc[:-lag].reset_index(drop=True),
                        target_values.iloc[lag:].reset_index(drop=True),
                    ],
                    axis=1,
                ).dropna()
                if len(aligned) < self.config.minimum_sample_size:
                    continue
                tested = correlation_test(
                    tuple(float(value) for value in aligned.iloc[:, 0]),
                    tuple(float(value) for value in aligned.iloc[:, 1]),
                )
                if tested is None:
                    continue
                correlation, p_value, effective_n = tested
                output.append(
                    _RawEdge(
                        source,
                        target,
                        RelationshipType.LEAD_LAG,
                        lag,
                        correlation,
                        p_value,
                        effective_n,
                        len(aligned),
                        (),
                    )
                )
        return tuple(output)

    def _materialize_edge(
        self,
        raw: _RawEdge,
        *,
        adjusted_p: float,
        data_cutoff: datetime,
        data_version: str,
        regime: str,
        estimated_cost: float,
        expected_return: float,
        oos_survival: float,
    ) -> RelationshipEdge:
        rolling = raw.rolling
        stability = _stability(rolling, raw.correlation)
        recent = rolling[-1] if rolling else raw.correlation
        recent_decay = (
            max(0.0, 1 - min(1.0, abs(recent) / max(abs(raw.correlation), 1e-12)))
            if raw.correlation
            else 1.0
        )
        validation = validate_relationship_for_alpha(
            RelationshipEvidence(
                adjusted_p_value=adjusted_p,
                gross_expected_return=expected_return,
                estimated_cost=estimated_cost,
                oos_periods=len(rolling),
                oos_survival_ratio=oos_survival,
                effective_sample_size=raw.effective_n,
            ),
            significance_level=self.config.fdr_threshold,
            minimum_effective_sample=float(self.config.minimum_sample_size),
            minimum_oos_survival=self.config.minimum_oos_survival,
        )
        blockers = list(validation.blockers)
        if abs(raw.correlation) < self.config.minimum_abs_strength:
            blockers.append("relationship strength is below research threshold")
        use = RelationshipUse.RESEARCH_INSIGHT if blockers else validation.use
        return RelationshipEdge(
            edge_id=_edge_id(
                raw.source.node_id,
                raw.target.node_id,
                raw.relationship_type.value,
                str(raw.lag),
                data_cutoff.isoformat(),
            ),
            source_node=raw.source.node_id,
            target_node=raw.target.node_id,
            relationship_type=raw.relationship_type,
            window=max(self.config.windows),
            lag=raw.lag,
            strength=abs(raw.correlation),
            signed_strength=raw.correlation,
            direction=(
                "UNDIRECTED"
                if raw.relationship_type is RelationshipType.CORRELATION
                else f"{raw.source.node_id}_LEADS_{raw.target.node_id}"
            ),
            sample_size=raw.sample_size,
            effective_sample_size=raw.effective_n,
            confidence_interval=_fisher_interval(raw.correlation, raw.effective_n),
            raw_p_value=raw.p_value,
            adjusted_p_value=adjusted_p,
            regime=regime,
            rolling_strength=rolling,
            stability_score=stability,
            recent_decay=recent_decay,
            oos_survival=oos_survival,
            relationship_use=use,
            blockers=tuple(dict.fromkeys(blockers)),
            last_updated=data_cutoff,
            data_cutoff=data_cutoff,
            model_version=self.config.model_version,
            data_version=data_version,
            backtest_safety=BacktestSafety.BACKTEST_SAFE,
        )

    def _snapshot(
        self,
        nodes: tuple[RelationshipNode, ...],
        edges: tuple[RelationshipEdge, ...],
        data_cutoff: datetime,
        data_version: str,
    ) -> RelationshipGraphSnapshot:
        edge_ids = tuple(sorted(item.edge_id for item in edges))
        return RelationshipGraphSnapshot(
            snapshot_id=sha256(
                "|".join((*edge_ids, data_cutoff.isoformat(), data_version)).encode()
            ).hexdigest(),
            nodes=nodes,
            edges=tuple(sorted(edges, key=lambda item: item.edge_id)),
            data_cutoff=data_cutoff,
            model_version=self.config.model_version,
            data_version=data_version,
        )


def _validate_returns(returns: pd.DataFrame, cutoff: datetime) -> pd.DataFrame:
    if returns.empty or not isinstance(returns.index, pd.DatetimeIndex):
        raise ValueError("relationship graph requires a datetime-indexed return matrix")
    if returns.index.tz is None:
        raise ValueError("relationship return timestamps must be timezone-aware")
    if not returns.index.is_monotonic_increasing or returns.index.has_duplicates:
        raise ValueError("relationship return timestamps must be sorted and unique")
    if returns.index.max().to_pydatetime() > cutoff:
        raise ValueError("relationship graph received future returns")
    numeric = returns.astype(float).replace([np.inf, -np.inf], np.nan)
    if numeric.columns.duplicated().any():
        raise ValueError("relationship graph contains duplicate symbols")
    return numeric


def _rolling_correlations(
    left: pd.Series,
    right: pd.Series,
    windows: tuple[int, ...],
) -> tuple[float, ...]:
    output: list[float] = []
    for window in windows:
        if len(left) < window:
            continue
        value = float(left.iloc[-window:].corr(right.iloc[-window:]))
        if isfinite(value):
            output.append(value)
    return tuple(output)


def _stability(rolling: tuple[float, ...], full: float) -> float:
    if not rolling:
        return 0.0
    sign_match = sum((item >= 0) == (full >= 0) for item in rolling) / len(rolling)
    dispersion = float(np.std(rolling))
    return max(0.0, min(1.0, sign_match * (1 - min(1.0, dispersion))))


def _fisher_interval(correlation: float, effective_n: float) -> tuple[float, float]:
    if effective_n <= 3 or abs(correlation) >= 1 - 1e-12:
        return correlation, correlation
    transformed = atanh(correlation)
    margin = NormalDist().inv_cdf(0.975) / sqrt(effective_n - 3)
    return tanh(transformed - margin), tanh(transformed + margin)


def _edge_id(*parts: str) -> str:
    return sha256("|".join(parts).encode()).hexdigest()
