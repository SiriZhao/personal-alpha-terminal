from dataclasses import dataclass

from personal_alpha_terminal.quant_engine.risk.position_control import (
    PositionConstraints,
    validate_target_weights,
)
from personal_alpha_terminal.research.data_gate import (
    ResearchDataAuthorization,
    ResearchDataGate,
    ResearchPurpose,
)


@dataclass(frozen=True, slots=True)
class AllocationResult:
    target_weights: dict[str, float]
    cash_weight: float
    method: str
    constraints: PositionConstraints


class AllocationEngine:
    """Legacy research allocator; never eligible for production decisions.

    Production callers must use ``PortfolioConstructionEngine``. This class is
    retained only for reproducibility of historical research artifacts.
    """

    def allocate(
        self,
        *,
        authorization: ResearchDataAuthorization,
        selected_scores: dict[str, float],
        annualized_volatility: dict[str, float],
        sectors: dict[str, str],
        constraints: PositionConstraints | None = None,
        method: str = "equal_weight",
    ) -> AllocationResult:
        ResearchDataGate.require(authorization, ResearchPurpose.PORTFOLIO_DECISION)
        limits = constraints or PositionConstraints()
        if not selected_scores:
            raise ValueError("allocation requires deterministic selected assets")
        tickers = tuple(
            sorted(selected_scores, key=lambda ticker: selected_scores[ticker], reverse=True)
        )
        gross = limits.maximum_gross_exposure
        if method == "equal_weight":
            raw = {ticker: 1.0 for ticker in tickers}
        elif method == "inverse_volatility":
            if any(annualized_volatility.get(ticker, 0) <= 0 for ticker in tickers):
                raise ValueError("inverse volatility requires positive volatility for every asset")
            raw = {ticker: 1 / annualized_volatility[ticker] for ticker in tickers}
        else:
            raise ValueError("allocation method must be equal_weight or inverse_volatility")
        raw_total = sum(raw.values())
        weights = {
            ticker: min(raw[ticker] / raw_total * gross, limits.maximum_single_position)
            for ticker in tickers
        }
        # Capping can leave additional cash; it is not redistributed into concentration.
        violations = validate_target_weights(weights, sectors, limits)
        if violations:
            raise ValueError("; ".join(violations))
        return AllocationResult(weights, 1 - sum(weights.values()), method, limits)
