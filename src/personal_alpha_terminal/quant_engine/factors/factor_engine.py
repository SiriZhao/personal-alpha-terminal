from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from personal_alpha_terminal.quant_engine.factors.cross_sectional import (
    FactorSpec,
    process_cross_section,
)
from personal_alpha_terminal.research.data_gate import (
    ResearchDataAuthorization,
    ResearchDataGate,
    ResearchPurpose,
)

_FACTOR_GROUPS: dict[str, tuple[tuple[str, str], ...]] = {
    "value": (("pe", "low"), ("pb", "low"), ("ps", "low")),
    "growth": (("revenue_growth", "high"), ("eps_growth", "high")),
    "quality": (("roe", "high"), ("roic", "high"), ("gross_margin", "high")),
    "momentum": (
        ("momentum_12_1", "high"),
        ("momentum_6m", "high"),
        ("momentum_3m", "high"),
    ),
    "low_risk": (("volatility", "low"), ("max_drawdown", "high")),
}


@dataclass(frozen=True, slots=True)
class FactorScore:
    permanent_security_id: str
    ticker: str
    as_of: datetime
    component_scores: dict[str, float]
    composite_score: float
    disabled_components: tuple[str, ...]
    factor_coverage: float
    confidence_penalty: float
    production_eligible: bool = False


@dataclass(frozen=True, slots=True)
class FactorResearchResult:
    scores: tuple[FactorScore, ...]
    method: str
    point_in_time_cutoff: datetime
    source_rows: int
    warnings: tuple[str, ...] = ()


class FactorEngine:
    """Causal, robust cross-sectional factor research.

    The composite is a research convenience only. It is not expected return,
    is never production eligible, and cannot directly create a target weight.
    """

    def score_snapshot(
        self,
        *,
        authorization: ResearchDataAuthorization,
        observations: pd.DataFrame,
        decision_time: datetime,
    ) -> FactorResearchResult:
        ResearchDataGate.require(authorization, ResearchPurpose.RESEARCH)
        if decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        required = {"permanent_security_id", "ticker", "available_at"}
        missing = required - set(observations.columns)
        if missing:
            raise ValueError(f"factor observations are missing columns: {sorted(missing)}")
        specs = tuple(
            FactorSpec(
                field,
                direction=direction,
                minimum_observations=5,
                sector_neutral=True,
                size_neutral=True,
            )
            for group in _FACTOR_GROUPS.values()
            for field, direction in group
            if field in observations.columns
        )
        if not specs:
            raise ValueError("no supported factor field is available")
        processed = process_cross_section(
            observations,
            specs,
            as_of=decision_time,
            minimum_required_factors=1,
        )
        frame = processed.frame.set_index("permanent_security_id", drop=False)
        output: list[FactorScore] = []
        for security_id, row in frame.iterrows():
            if not bool(row["eligible"]):
                continue
            components: dict[str, float] = {}
            for group_name, fields in _FACTOR_GROUPS.items():
                columns = [
                    f"{field}__normalized"
                    for field, _direction in fields
                    if f"{field}__normalized" in frame.columns
                ]
                values = pd.to_numeric(row[columns], errors="coerce").dropna()
                if not values.empty:
                    components[group_name] = float(values.mean())
            if not components:
                continue
            disabled = tuple(group for group in _FACTOR_GROUPS if group not in components)
            coverage = float(row["factor_coverage"])
            output.append(
                FactorScore(
                    permanent_security_id=str(security_id),
                    ticker=str(row["ticker"]),
                    as_of=decision_time,
                    component_scores=components,
                    composite_score=sum(components.values()) / len(components),
                    disabled_components=disabled,
                    factor_coverage=coverage,
                    confidence_penalty=coverage,
                )
            )
        if not output:
            raise ValueError("no factor component had sufficient point-in-time coverage")
        return FactorResearchResult(
            scores=tuple(sorted(output, key=lambda item: item.composite_score, reverse=True)),
            method=(
                "PIT cross-section; percentile winsorization; robust z-score; "
                "sector centering and log-size residualization when available; "
                "missing values excluded; equal-group composite is research-only"
            ),
            point_in_time_cutoff=decision_time,
            source_rows=len(frame),
            warnings=processed.warnings,
        )
