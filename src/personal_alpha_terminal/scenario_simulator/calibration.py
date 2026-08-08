from datetime import date

from personal_alpha_terminal.scenario_simulator.schemas import (
    FactorShock,
    HistoricalFactorSeries,
    RiskFactorDefinition,
    ScenarioDefinition,
)


def calibrate_historical_scenario(
    *,
    name: str,
    description: str,
    start_date: date,
    end_date: date,
    series: tuple[HistoricalFactorSeries, ...],
    factors: tuple[RiskFactorDefinition, ...],
    maximum_boundary_gap_days: int = 7,
) -> ScenarioDefinition:
    """Calibrate factor shocks from explicit source series and one shared window."""

    if start_date >= end_date:
        raise ValueError("historical calibration window is invalid")
    if not 0 <= maximum_boundary_gap_days <= 31:
        raise ValueError("maximum boundary gap must be between 0 and 31 days")
    factor_by_code = {item.code: item for item in factors}
    shocks: list[FactorShock] = []
    sources: list[str] = []
    for item in series:
        definition = factor_by_code.get(item.factor_code)
        if definition is None:
            raise ValueError(f"unknown historical factor: {item.factor_code}")
        if definition.shock_unit != item.unit:
            raise ValueError(f"historical series unit mismatch for {item.factor_code}")
        ordered = tuple(sorted(item.points, key=lambda point: point.date))
        start = next((point for point in ordered if point.date >= start_date), None)
        end = next(
            (point for point in reversed(ordered) if point.date <= end_date),
            None,
        )
        if start is None or end is None or start.date >= end.date:
            raise ValueError(f"historical series lacks window for {item.factor_code}")
        if (start.date - start_date).days > maximum_boundary_gap_days or (
            end_date - end.date
        ).days > maximum_boundary_gap_days:
            raise ValueError(f"historical boundary is stale for {item.factor_code}")
        if item.unit == "decimal_return":
            if start.value <= 0 or end.value <= 0:
                raise ValueError(f"historical index level is invalid for {item.factor_code}")
            magnitude = end.value / start.value - 1
        elif item.unit == "basis_points":
            magnitude = (end.value - start.value) * 100
        else:
            raise ValueError("standard-score factors require explicit scenario assumptions")
        normalized = magnitude / 100 if item.unit == "basis_points" else magnitude
        if not definition.normalized_minimum <= normalized <= (definition.normalized_maximum):
            raise ValueError(f"calibrated shock is outside bounds for {item.factor_code}")
        shocks.append(
            FactorShock(
                factor_code=item.factor_code,
                magnitude=magnitude,
                unit=item.unit,
                rationale=(f"source-derived {start.date.isoformat()} to {end.date.isoformat()}"),
            )
        )
        sources.append(
            f"{item.source}:{item.factor_code}:{start.date.isoformat()}:{end.date.isoformat()}"
        )
    return ScenarioDefinition(
        name=name,
        scenario_type="historical",
        description=description,
        factor_shocks=tuple(shocks),
        currency_shocks={},
        evidence_level="calibrated_historical",
        data_sources=tuple(sources),
        historical_start=start_date,
        historical_end=end_date,
    )
