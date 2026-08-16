from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import exp, isfinite, log

import numpy as np
from scipy.optimize import minimize

from personal_alpha_terminal.quant_engine.alpha import AlphaSignal, UnifiedAlphaEngine
from personal_alpha_terminal.quant_engine.costs import TransactionCostModel
from personal_alpha_terminal.quant_engine.risk.budget import RiskBudget
from personal_alpha_terminal.quant_engine.risk.model import (
    RiskModelEstimate,
    SizeExposureStatus,
    portfolio_volatility,
)
from personal_alpha_terminal.research.data_gate import (
    ResearchDataAuthorization,
    ResearchDataGate,
    ResearchPurpose,
)


class PortfolioConstructionStatus(StrEnum):
    PRODUCTION_APPROVED = "PRODUCTION_APPROVED"
    PROVISIONAL_OPERATIONAL_APPROVED = "PROVISIONAL_OPERATIONAL_APPROVED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class PortfolioConstraints:
    maximum_position_weight: float = 0.12
    maximum_sector_weight: float = 0.30
    maximum_cluster_weight: float = 0.35
    maximum_hhi: float = 0.18
    minimum_cash_weight: float = 0.10
    maximum_gross_exposure: float = 0.90
    target_annualized_volatility: float = 0.15
    minimum_beta: float = 0.0
    maximum_beta: float = 1.05
    maximum_turnover: float = 0.30
    maximum_size_exposure: float = 0.35
    correlation_cluster_threshold: float = 0.75
    no_trade_band: float = 0.005
    minimum_rebalance_weight: float = 0.01
    minimum_trade_value: float = 100.0
    risk_aversion: float = 3.0
    turnover_penalty: float = 0.01
    model_version: str = "constrained-alpha-risk-v1"
    model_validation_id: str | None = None

    def __post_init__(self) -> None:
        bounded = (
            self.maximum_position_weight,
            self.maximum_sector_weight,
            self.maximum_cluster_weight,
            self.maximum_hhi,
            self.minimum_cash_weight,
            self.maximum_gross_exposure,
            self.maximum_turnover,
            self.maximum_size_exposure,
            self.correlation_cluster_threshold,
            self.no_trade_band,
            self.minimum_rebalance_weight,
        )
        if any(not isfinite(value) or not 0 <= value <= 1 for value in bounded):
            raise ValueError("portfolio constraint fractions must be in [0, 1]")
        if self.maximum_gross_exposure > 1 - self.minimum_cash_weight + 1e-12:
            raise ValueError("gross exposure conflicts with minimum cash")
        if self.minimum_beta > self.maximum_beta:
            raise ValueError("beta bounds are inconsistent")
        if not isfinite(self.minimum_beta) or not isfinite(self.maximum_beta):
            raise ValueError("beta bounds must be finite")
        if self.target_annualized_volatility <= 0 or self.minimum_trade_value < 0:
            raise ValueError("volatility target and minimum trade value are invalid")
        if self.risk_aversion <= 0 or self.turnover_penalty < 0:
            raise ValueError("optimizer penalty parameters are invalid")


@dataclass(frozen=True, slots=True)
class AlphaContribution:
    symbol: str
    signal_type: str
    horizon: int
    decayed_expected_return: float
    confidence: float
    model_version: str


@dataclass(frozen=True, slots=True)
class OptimizerCardinalityProvenance:
    """ROUND28: exact optimizer -> no-trade -> target cardinality trace.

    This is evidence, not a new policy.  It records how many symbols entered
    the solver, how many non-zero weights the solver produced, and how many
    were subsequently zeroed by each deterministic no-trade / minimum-size
    rule.  There is deliberately no ``maximum_positions`` field anywhere in
    this path.
    """

    optimizer_input_count: int
    raw_nonzero_count: int
    dropped_by_no_trade_band: int
    dropped_by_minimum_rebalance_weight: int
    dropped_by_minimum_trade_value: int
    post_filter_nonzero_count: int
    final_target_count: int
    minimum_positive_raw_weight: float | None
    minimum_positive_final_weight: float | None
    maximum_raw_weight: float
    maximum_final_weight: float
    gross_raw: float
    gross_final: float
    explicit_position_cap: float | None
    pre_optimizer_top_n: int | None

    def document(self) -> dict[str, object]:
        return {
            "optimizer_input_count": self.optimizer_input_count,
            "raw_nonzero_count": self.raw_nonzero_count,
            "dropped_by_no_trade_band": self.dropped_by_no_trade_band,
            "dropped_by_minimum_rebalance_weight": self.dropped_by_minimum_rebalance_weight,
            "dropped_by_minimum_trade_value": self.dropped_by_minimum_trade_value,
            "post_filter_nonzero_count": self.post_filter_nonzero_count,
            "final_target_count": self.final_target_count,
            "minimum_positive_raw_weight": self.minimum_positive_raw_weight,
            "minimum_positive_final_weight": self.minimum_positive_final_weight,
            "maximum_raw_weight": self.maximum_raw_weight,
            "maximum_final_weight": self.maximum_final_weight,
            "gross_raw": self.gross_raw,
            "gross_final": self.gross_final,
            "explicit_position_cap": self.explicit_position_cap,
            "pre_optimizer_top_n": self.pre_optimizer_top_n,
            "holding_cap_policy": "NO_FIXED_CARDINALITY_CAP",
        }


@dataclass(frozen=True, slots=True)
class PortfolioTarget:
    status: PortfolioConstructionStatus
    as_of: datetime
    target_weights: dict[str, float]
    cash_weight: float
    expected_alpha: float
    expected_volatility: float | None
    expected_beta: float | None
    turnover: float
    estimated_transaction_cost: float
    hhi: float
    sector_weights: dict[str, float]
    cluster_weights: dict[str, float]
    alpha_contributions: tuple[AlphaContribution, ...]
    risk_reductions: tuple[str, ...]
    blockers: tuple[str, ...]
    model_version: str
    risk_model_version: str
    cost_model_version: str
    data_version: str
    model_validation_id: str
    target_holding_count: int = 0
    optimizer_provenance: dict[str, object] | None = None
    raw_target_weights: dict[str, float] | None = None

    @property
    def production_approved(self) -> bool:
        return self.status is PortfolioConstructionStatus.PRODUCTION_APPROVED

    @property
    def operational_approved(self) -> bool:
        return self.status in {
            PortfolioConstructionStatus.PRODUCTION_APPROVED,
            PortfolioConstructionStatus.PROVISIONAL_OPERATIONAL_APPROVED,
        }


class PortfolioConstructionEngine:
    def __init__(
        self,
        constraints: PortfolioConstraints | None = None,
        cost_model: TransactionCostModel | None = None,
        *,
        operational_mode: bool = False,
    ) -> None:
        self.constraints = constraints or PortfolioConstraints()
        self.cost_model = cost_model or TransactionCostModel()
        self.operational_mode = operational_mode

    def construct(
        self,
        *,
        authorization: ResearchDataAuthorization,
        alpha_signals: tuple[AlphaSignal, ...],
        risk: RiskModelEstimate,
        current_weights: dict[str, float],
        portfolio_value: float,
        decision_time: datetime,
        risk_budget: RiskBudget,
    ) -> PortfolioTarget:
        ResearchDataGate.require(authorization, ResearchPurpose.PORTFOLIO_DECISION)
        if decision_time.tzinfo is None or portfolio_value <= 0:
            raise ValueError("portfolio construction requires valid time and value")
        if not self.constraints.model_validation_id:
            return self._blocked(
                decision_time,
                authorization,
                risk,
                ("portfolio model lacks a locked OOS validation manifest",),
            )
        if not risk.valid_for_optimization:
            return self._blocked(decision_time, authorization, risk, ("risk model is blocked",))
        size_degraded = risk.size_exposure_status is not SizeExposureStatus.VALID
        if size_degraded and not self.operational_mode:
            return self._blocked(
                decision_time,
                authorization,
                risk,
                ("PIT market-cap size exposure is NOT_VALIDATED",),
            )
        if set(current_weights) - set(risk.symbols):
            return self._blocked(
                decision_time,
                authorization,
                risk,
                ("current holdings are missing from the risk universe",),
            )
        if any(not isfinite(value) or value < 0 for value in current_weights.values()):
            raise ValueError("current weights must be finite and long-only")
        if sum(current_weights.values()) > 1 + 1e-9:
            raise ValueError("current weights cannot exceed total portfolio value")
        approved = UnifiedAlphaEngine().for_operational_decision(
            alpha_signals, decision_time=decision_time
        )
        if not approved:
            return self._blocked(
                decision_time,
                authorization,
                risk,
                ("no operationally approved alpha is available",),
            )
        contributions, expected = _expected_returns(approved, risk.symbols, decision_time)
        if not expected or max(expected.values()) <= 0:
            return self._blocked(
                decision_time,
                authorization,
                risk,
                ("no positive decayed expected excess return",),
            )
        if not risk_budget.allow_new_risk and any(
            expected.get(symbol, 0.0) > 0 and current_weights.get(symbol, 0.0) == 0
            for symbol in risk.symbols
        ):
            return self._blocked(
                decision_time,
                authorization,
                risk,
                ("dynamic risk budget blocks new exposure",),
            )
        symbols = risk.symbols
        current = np.array([current_weights.get(symbol, 0.0) for symbol in symbols])
        mu = np.array([expected.get(symbol, 0.0) for symbol in symbols])
        covariance = risk.annualized_covariance
        gross_limit = min(
            self.constraints.maximum_gross_exposure,
            (1 - self.constraints.minimum_cash_weight),
        ) * risk_budget.gross_exposure_multiplier
        position_limit = (
            self.constraints.maximum_position_weight * risk_budget.position_cap_multiplier
        )
        volatility_limit = (
            self.constraints.target_annualized_volatility
            * risk_budget.volatility_multiplier
        )
        bounds = []
        for symbol in symbols:
            liquidity_cap = (
                risk.average_daily_dollar_volume[symbol]
                * self.cost_model.config.maximum_adv_participation
                / portfolio_value
            )
            bounds.append((0.0, min(position_limit, liquidity_cap)))
        cluster_members = _correlation_clusters(
            symbols,
            risk.correlation,
            self.constraints.correlation_cluster_threshold,
        )
        sector_members = _members_by_label(symbols, risk.sectors)
        beta = np.array([risk.beta[symbol] for symbol in symbols])
        sizes = np.array([risk.size_scores.get(symbol, 0.0) for symbol in symbols])

        # ROUND25 PHASE 13: analytic gradients (identical semantics, no
        # numerical differentiation).  SLSQP previously evaluated the objective
        # and ~1.2k constraints numerically for every iteration over ~1.2k
        # variables (~100M calls, ~700s per construction).  The closed-form
        # derivatives below are the exact derivatives of the functions above.
        turnover_coefficient = (
            self.constraints.turnover_penalty + self.cost_model.conservative_rate
        )
        # ROUND25 PHASE 13: large problems use a warm start + analytic
        # objective gradient + redundant-constraint pruning; small problems
        # keep the original exact path so miniature fixtures stay identical.
        large_problem = len(symbols) >= 500

        def objective(weights: np.ndarray) -> float:
            delta = weights - current
            smooth_turnover = float(np.sum(np.sqrt(delta * delta + 1e-12)))
            alpha_value = float(mu @ weights)
            variance_penalty = self.constraints.risk_aversion * float(
                weights @ covariance @ weights
            )
            cost_penalty = self.cost_model.conservative_rate * smooth_turnover
            return (
                -alpha_value
                + variance_penalty
                + self.constraints.turnover_penalty * smooth_turnover
                + cost_penalty
            )

        def objective_jac(weights: np.ndarray) -> np.ndarray:
            delta = weights - current
            smooth_gradient = delta / np.sqrt(delta * delta + 1e-12)
            return np.asarray(
                -mu
                + 2.0 * self.constraints.risk_aversion * (covariance @ weights)
                + turnover_coefficient * smooth_gradient,
                dtype=float,
            )

        constraints = [
            {
                "type": "ineq",
                "fun": lambda weights: gross_limit - float(np.sum(weights)),
            },
            {
                "type": "ineq",
                "fun": lambda weights: volatility_limit
                - portfolio_volatility(weights, covariance),
            },
            {
                "type": "ineq",
                "fun": lambda weights: self.constraints.maximum_turnover
                - float(np.sum(np.abs(weights - current))),
            },
            {
                "type": "ineq",
                "fun": lambda weights: self.constraints.maximum_beta - float(beta @ weights),
            },
            {
                "type": "ineq",
                "fun": lambda weights: float(beta @ weights) - self.constraints.minimum_beta,
            },
            {
                "type": "ineq",
                "fun": lambda weights: self.constraints.maximum_hhi
                - float(np.sum(weights * weights)),
            },
            {
                "type": "ineq",
                "fun": lambda weights: self.constraints.maximum_size_exposure
                - abs(float(sizes @ weights)),
            },
        ]
        # ROUND25 PHASE 13: prune provably non-binding membership constraints.
        # A singleton cluster/sector constraint is w[i] <= cap with cap larger
        # than the per-position cap (0.12 < 0.30 / 0.35), so it can never bind.
        # Omitting it changes nothing mathematically but removes ~1k redundant
        # numerical-gradient rows from SLSQP.
        constraints.extend(
            {
                "type": "ineq",
                "fun": lambda weights, members=members: self.constraints.maximum_sector_weight
                - float(np.sum(weights[list(members)])),
            }
            for members in sector_members.values()
            if len(members) > 1 or not large_problem
        )
        constraints.extend(
            {
                "type": "ineq",
                "fun": lambda weights, members=members: self.constraints.maximum_cluster_weight
                - float(np.sum(weights[list(members)])),
            }
            for members in cluster_members.values()
            if len(members) > 1 or not large_problem
        )
        initial = np.minimum(current, np.array([upper for _, upper in bounds]))
        if initial.sum() > gross_limit and initial.sum() > 0:
            initial *= gross_limit / initial.sum()
        elif initial.sum() <= 0 and large_problem:
            seed = min(gross_limit / max(1, len(symbols)), 1e-6)
            initial = np.full(len(symbols), seed)
        try:
            minimize_kwargs: dict[str, object] = {
                "method": "SLSQP",
                "bounds": bounds,
                "constraints": constraints,
                "options": {"maxiter": 500, "ftol": 1e-10, "disp": False},
            }
            if large_problem:
                minimize_kwargs["jac"] = objective_jac
            result = minimize(objective, initial, **minimize_kwargs)
        except (ArithmeticError, FloatingPointError, ValueError) as error:
            return self._blocked(
                decision_time,
                authorization,
                risk,
                (f"optimizer failed safely: {error}",),
            )
        if not result.success or not np.all(np.isfinite(result.x)):
            return self._blocked(
                decision_time,
                authorization,
                risk,
                (f"optimizer failed: {result.message}",),
            )
        weights = _apply_no_trade_bands(
            np.asarray(result.x, dtype=float),
            current,
            portfolio_value,
            self.constraints,
        )
        violations = _constraint_violations(
            weights,
            current=current,
            risk=risk,
            constraints=self.constraints,
            gross_limit=gross_limit,
            position_limit=position_limit,
            volatility_limit=volatility_limit,
            sector_members=sector_members,
            cluster_members=cluster_members,
            require_size_exposure=(
                not self.operational_mode
                or risk.size_exposure_status is SizeExposureStatus.VALID
            ),
        )
        if violations:
            return self._blocked(decision_time, authorization, risk, tuple(violations))
        target = {
            symbol: float(weights[index])
            for index, symbol in enumerate(symbols)
            if weights[index] > 1e-12
        }
        raw_weights = np.asarray(result.x, dtype=float)
        raw_nonzero = {
            symbol: float(raw_weights[index])
            for index, symbol in enumerate(symbols)
            if raw_weights[index] > 1e-12
        }
        raw_nonzero_count = len(raw_nonzero)
        dropped_no_trade = 0
        dropped_minimum_weight = 0
        dropped_minimum_value = 0
        for index, _symbol in enumerate(symbols):
            proposed = float(raw_weights[index])
            current_value = float(current[index])
            delta = proposed - current_value
            if abs(delta) < 1e-12:
                continue
            if abs(delta) < self.constraints.no_trade_band:
                dropped_no_trade += 1
            elif abs(delta) < self.constraints.minimum_rebalance_weight:
                dropped_minimum_weight += 1
            elif abs(delta) * portfolio_value < self.constraints.minimum_trade_value:
                dropped_minimum_value += 1
        positive_raw = [value for value in raw_nonzero.values() if value > 0]
        positive_final = [
            value for value in target.values() if value > 0
        ]
        provenance = OptimizerCardinalityProvenance(
            optimizer_input_count=len(symbols),
            raw_nonzero_count=raw_nonzero_count,
            dropped_by_no_trade_band=dropped_no_trade,
            dropped_by_minimum_rebalance_weight=dropped_minimum_weight,
            dropped_by_minimum_trade_value=dropped_minimum_value,
            post_filter_nonzero_count=len(target),
            final_target_count=len(target),
            minimum_positive_raw_weight=(
                min(positive_raw) if positive_raw else None
            ),
            minimum_positive_final_weight=(
                min(positive_final) if positive_final else None
            ),
            maximum_raw_weight=float(raw_weights.max(initial=0.0)),
            maximum_final_weight=float(weights.max(initial=0.0)),
            gross_raw=float(raw_weights.sum()),
            gross_final=float(weights.sum()),
            explicit_position_cap=position_limit,
            pre_optimizer_top_n=None,
        )
        turnover = float(np.sum(np.abs(weights - current)))
        estimated_cost = 0.0
        try:
            for index, symbol in enumerate(symbols):
                trade_value = abs(float(weights[index] - current[index])) * portfolio_value
                estimated_cost += self.cost_model.estimate(
                    trade_value=trade_value,
                    average_daily_dollar_volume=risk.average_daily_dollar_volume[symbol],
                ).total_cost
        except ValueError as error:
            return self._blocked(
                decision_time,
                authorization,
                risk,
                (f"transaction-cost validation failed: {error}",),
            )
        sector_weights = {
            sector: float(np.sum(weights[list(members)]))
            for sector, members in sector_members.items()
        }
        cluster_weights = {
            cluster: float(np.sum(weights[list(members)]))
            for cluster, members in cluster_members.items()
        }
        versions = {item.data_version for item in approved}
        if len(versions) != 1:
            return self._blocked(
                decision_time,
                authorization,
                risk,
                ("approved alpha signals use inconsistent data versions",),
            )
        return PortfolioTarget(
            status=(
                PortfolioConstructionStatus.PROVISIONAL_OPERATIONAL_APPROVED
                if self.operational_mode
                else PortfolioConstructionStatus.PRODUCTION_APPROVED
            ),
            as_of=decision_time,
            target_weights=target,
            cash_weight=1 - float(weights.sum()),
            expected_alpha=float(mu @ weights),
            expected_volatility=portfolio_volatility(weights, covariance),
            expected_beta=float(beta @ weights),
            turnover=turnover,
            estimated_transaction_cost=estimated_cost,
            hhi=float(np.sum(weights * weights)),
            sector_weights=sector_weights,
            cluster_weights=cluster_weights,
            alpha_contributions=contributions,
            risk_reductions=(
                *risk_budget.reasons,
                *risk.limitations,
                *(
                    ("size_neutralization:degraded",)
                    if size_degraded and self.operational_mode
                    else ()
                ),
            ),
            blockers=(),
            model_version=self.constraints.model_version,
            risk_model_version=risk.model_version,
            cost_model_version=self.cost_model.config.version,
            data_version=next(iter(versions)),
            model_validation_id=self.constraints.model_validation_id,
            target_holding_count=len(target),
            optimizer_provenance=provenance.document(),
            raw_target_weights=raw_nonzero,
        )

    def _blocked(
        self,
        decision_time: datetime,
        authorization: ResearchDataAuthorization,
        risk: RiskModelEstimate,
        blockers: tuple[str, ...],
    ) -> PortfolioTarget:
        return PortfolioTarget(
            status=PortfolioConstructionStatus.BLOCKED,
            as_of=decision_time,
            target_weights={},
            cash_weight=1.0,
            expected_alpha=0.0,
            expected_volatility=None,
            expected_beta=None,
            turnover=0.0,
            estimated_transaction_cost=0.0,
            hhi=0.0,
            sector_weights={},
            cluster_weights={},
            alpha_contributions=(),
            risk_reductions=(),
            blockers=blockers,
            model_version=self.constraints.model_version,
            risk_model_version=risk.model_version,
            cost_model_version=self.cost_model.config.version,
            data_version=authorization.decision.evidence_fingerprint,
            model_validation_id=self.constraints.model_validation_id or "",
        )


def _expected_returns(
    signals: tuple[AlphaSignal, ...],
    symbols: tuple[str, ...],
    decision_time: datetime,
) -> tuple[tuple[AlphaContribution, ...], dict[str, float]]:
    allowed = set(symbols)
    contributions: list[AlphaContribution] = []
    grouped: dict[str, list[tuple[float, float]]] = {}
    for signal in signals:
        if signal.symbol not in allowed:
            continue
        age = max(0.0, (decision_time - signal.as_of).total_seconds() / 86_400)
        decay = (
            exp(-log(2) * age / signal.decay_half_life)
            if signal.decay_half_life and signal.decay_half_life > 0
            else 1.0
        )
        annualized = signal.expected_excess_return * 252 / signal.horizon
        decayed = annualized * decay
        contributions.append(
            AlphaContribution(
                signal.symbol,
                signal.signal_type,
                signal.horizon,
                decayed,
                signal.confidence,
                signal.model_version,
            )
        )
        # Evidence coverage is deterministic completeness. Probability
        # confidence remains zero unless a separate locked-OOS calibration
        # artifact exists, and never controls the base alpha calculation.
        grouped.setdefault(signal.symbol, []).append((decayed, signal.evidence_coverage))
    expected = {
        symbol: (
            sum(value * confidence for value, confidence in items)
            / sum(confidence for _, confidence in items)
        )
        for symbol, items in grouped.items()
        if sum(confidence for _, confidence in items) > 0
    }
    return tuple(contributions), expected


def _members_by_label(
    symbols: tuple[str, ...], labels: dict[str, str]
) -> dict[str, tuple[int, ...]]:
    output: dict[str, list[int]] = {}
    for index, symbol in enumerate(symbols):
        output.setdefault(labels[symbol], []).append(index)
    return {label: tuple(items) for label, items in output.items()}


def _correlation_clusters(
    symbols: tuple[str, ...], correlation: np.ndarray, threshold: float
) -> dict[str, tuple[int, ...]]:
    remaining = set(range(len(symbols)))
    clusters: dict[str, tuple[int, ...]] = {}
    cluster_id = 0
    while remaining:
        seed = min(remaining)
        stack = [seed]
        component: set[int] = set()
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            stack.extend(
                item
                for item in remaining
                if item != current and correlation[current, item] >= threshold
            )
        remaining -= component
        clusters[f"cluster-{cluster_id}"] = tuple(sorted(component))
        cluster_id += 1
    return clusters


def _apply_no_trade_bands(
    proposed: np.ndarray,
    current: np.ndarray,
    portfolio_value: float,
    constraints: PortfolioConstraints,
) -> np.ndarray:
    output = proposed.copy()
    for index, delta in enumerate(proposed - current):
        if abs(delta) < constraints.no_trade_band:
            output[index] = current[index]
        elif abs(delta) < constraints.minimum_rebalance_weight:
            output[index] = current[index]
        elif abs(delta) * portfolio_value < constraints.minimum_trade_value:
            output[index] = current[index]
    return output


def _constraint_violations(
    weights: np.ndarray,
    *,
    current: np.ndarray,
    risk: RiskModelEstimate,
    constraints: PortfolioConstraints,
    gross_limit: float,
    position_limit: float,
    volatility_limit: float,
    sector_members: dict[str, tuple[int, ...]],
    cluster_members: dict[str, tuple[int, ...]],
    require_size_exposure: bool = True,
) -> list[str]:
    violations: list[str] = []
    tolerance = 1e-6
    if np.any(~np.isfinite(weights)) or np.any(weights < -tolerance):
        violations.append("optimizer returned non-finite or negative weights")
        return violations
    if float(weights.sum()) > gross_limit + tolerance:
        violations.append("gross exposure limit failed after no-trade processing")
    if float(weights.max(initial=0.0)) > position_limit + tolerance:
        violations.append("single-name limit failed after no-trade processing")
    if float(np.sum(np.abs(weights - current))) > constraints.maximum_turnover + tolerance:
        violations.append("turnover limit failed after no-trade processing")
    if float(np.sum(weights * weights)) > constraints.maximum_hhi + tolerance:
        violations.append("HHI limit failed after no-trade processing")
    if portfolio_volatility(weights, risk.annualized_covariance) > volatility_limit + tolerance:
        violations.append("volatility limit failed after no-trade processing")
    beta = np.array([risk.beta[symbol] for symbol in risk.symbols])
    beta_value = float(beta @ weights)
    if not (
        constraints.minimum_beta - tolerance
        <= beta_value
        <= constraints.maximum_beta + tolerance
    ):
        violations.append("beta band failed after no-trade processing")
    if require_size_exposure and risk.size_exposure_status is not SizeExposureStatus.VALID:
        violations.append("PIT market-cap size exposure is NOT_VALIDATED")
    elif require_size_exposure:
        sizes = np.array([risk.size_scores[symbol] for symbol in risk.symbols])
        if abs(float(sizes @ weights)) > constraints.maximum_size_exposure + tolerance:
            violations.append("size exposure limit failed after no-trade processing")
    for sector, members in sector_members.items():
        if float(np.sum(weights[list(members)])) > constraints.maximum_sector_weight + tolerance:
            violations.append(f"sector limit failed: {sector}")
    for cluster, members in cluster_members.items():
        if float(np.sum(weights[list(members)])) > constraints.maximum_cluster_weight + tolerance:
            violations.append(f"correlation cluster limit failed: {cluster}")
    return violations
