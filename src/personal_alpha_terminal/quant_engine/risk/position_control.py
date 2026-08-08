from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PositionConstraints:
    maximum_single_position: float = 0.15
    maximum_sector_weight: float = 0.35
    minimum_cash_weight: float = 0.05
    maximum_gross_exposure: float = 0.95

    def __post_init__(self) -> None:
        values = (
            self.maximum_single_position,
            self.maximum_sector_weight,
            self.minimum_cash_weight,
            self.maximum_gross_exposure,
        )
        if any(not 0 <= value <= 1 for value in values):
            raise ValueError("position constraints must be in [0, 1]")
        if self.maximum_gross_exposure > 1 - self.minimum_cash_weight:
            raise ValueError("gross exposure conflicts with the minimum cash weight")


def validate_target_weights(
    weights: dict[str, float],
    sectors: dict[str, str],
    constraints: PositionConstraints,
) -> tuple[str, ...]:
    violations: list[str] = []
    if any(weight < 0 for weight in weights.values()):
        violations.append("long-only portfolio cannot contain negative weights")
    gross = sum(weights.values())
    if gross > constraints.maximum_gross_exposure + 1e-12:
        violations.append("gross exposure exceeds configured maximum")
    for ticker, weight in weights.items():
        if weight > constraints.maximum_single_position + 1e-12:
            violations.append(f"{ticker} exceeds the single-position limit")
    sector_weights: dict[str, float] = {}
    for ticker, weight in weights.items():
        sector = sectors.get(ticker, "UNCLASSIFIED")
        sector_weights[sector] = sector_weights.get(sector, 0.0) + weight
    for sector, weight in sector_weights.items():
        if weight > constraints.maximum_sector_weight + 1e-12:
            violations.append(f"sector {sector} exceeds the sector limit")
    return tuple(violations)
