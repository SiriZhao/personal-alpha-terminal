from __future__ import annotations

from collections.abc import Callable
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


class PortfolioOptimizationStage(StrEnum):
    PRIMARY_OPTIMIZER = "PRIMARY_OPTIMIZER"
    FEASIBILITY_RECOVERY = "FEASIBILITY_RECOVERY"
    SELL_ONLY_FALLBACK = "SELL_ONLY_FALLBACK"
    BLOCKED = "BLOCKED"


class PortfolioOperatingMode(StrEnum):
    NORMAL = "NORMAL"
    RISK_REDUCTION_ONLY = "RISK_REDUCTION_ONLY"


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
    mandatory_risk_repair_count: int = 0
    mandatory_risk_repair_symbols: tuple[str, ...] = ()

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
            "mandatory_risk_repair_count": self.mandatory_risk_repair_count,
            "mandatory_risk_repair_symbols": list(self.mandatory_risk_repair_symbols),
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
    optimization_stage: PortfolioOptimizationStage = PortfolioOptimizationStage.BLOCKED
    operating_mode: PortfolioOperatingMode = PortfolioOperatingMode.NORMAL
    risk_repair_symbols: tuple[str, ...] = ()

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
        operating_mode = (
            PortfolioOperatingMode.NORMAL
            if risk_budget.allow_new_risk
            else PortfolioOperatingMode.RISK_REDUCTION_ONLY
        )
        if operating_mode is PortfolioOperatingMode.NORMAL and (
            not expected or max(expected.values()) <= 0
        ):
            return self._blocked(
                decision_time,
                authorization,
                risk,
                ("no positive decayed expected excess return",),
                operating_mode=operating_mode,
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
        bounds: list[tuple[float, float]] = []
        for symbol in symbols:
            liquidity_cap = (
                risk.average_daily_dollar_volume[symbol]
                * self.cost_model.config.maximum_adv_participation
                / portfolio_value
            )
            bounds.append((0.0, min(position_limit, liquidity_cap)))
        liquidity_limits = np.asarray([upper for _, upper in bounds], dtype=float)
        cluster_members = _correlation_clusters(
            symbols,
            risk.correlation,
            self.constraints.correlation_cluster_threshold,
        )
        sector_members = _members_by_label(symbols, risk.sectors)
        beta = np.array([risk.beta[symbol] for symbol in symbols])
        sizes = np.array([risk.size_scores.get(symbol, 0.0) for symbol in symbols])

        def validate(weights: np.ndarray) -> list[str]:
            return _constraint_violations(
                weights,
                current=current,
                risk=risk,
                constraints=self.constraints,
                gross_limit=gross_limit,
                position_limit=position_limit,
                volatility_limit=volatility_limit,
                sector_members=sector_members,
                cluster_members=cluster_members,
                liquidity_limits=liquidity_limits,
                require_size_exposure=(
                    not self.operational_mode
                    or risk.size_exposure_status is SizeExposureStatus.VALID
                ),
            )

        pre_solve_violations = tuple(validate(current))

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
        initial = np.minimum(current, liquidity_limits)
        if initial.sum() > gross_limit and initial.sum() > 0:
            initial *= gross_limit / initial.sum()
        elif initial.sum() <= 0 and large_problem:
            seed = min(gross_limit / max(1, len(symbols)), 1e-6)
            initial = np.full(len(symbols), seed)
        attempts: list[dict[str, object]] = []
        selected_weights: np.ndarray | None = None
        selected_raw_weights: np.ndarray | None = None
        selected_stage = PortfolioOptimizationStage.BLOCKED
        selected_message = ""
        selected_iterations: int | None = None
        mandatory_indices: tuple[int, ...] = ()

        def evaluate_candidate(
            raw_weights: np.ndarray,
            *,
            sell_only: bool,
        ) -> tuple[np.ndarray, tuple[int, ...], tuple[str, ...]]:
            processed, mandatory = _apply_constraint_aware_no_trade_bands(
                raw_weights,
                current,
                portfolio_value,
                self.constraints,
                validator=validate,
            )
            candidate_violations = validate(processed)
            if sell_only:
                candidate_violations.extend(
                    _sell_only_violations(
                        processed,
                        current=current,
                        risk=risk,
                    )
                )
            return processed, mandatory, tuple(candidate_violations)

        def record_attempt(
            *,
            stage: PortfolioOptimizationStage,
            solver_success: bool,
            message: str,
            iterations: int | None,
            violations: tuple[str, ...],
            accepted: bool,
        ) -> None:
            attempts.append(
                {
                    "stage": stage.value,
                    "solver_success": solver_success,
                    "solver_message": message,
                    "iterations": iterations,
                    "post_solve_validation": "PASS" if not violations else "FAIL",
                    "blocking_constraints": list(violations),
                    "accepted": accepted,
                }
            )

        if operating_mode is PortfolioOperatingMode.NORMAL:
            try:
                minimize_kwargs: dict[str, object] = {
                    "method": "SLSQP",
                    "bounds": bounds,
                    "constraints": constraints,
                    "options": {"maxiter": 500, "ftol": 1e-10, "disp": False},
                }
                if large_problem:
                    minimize_kwargs["jac"] = objective_jac
                primary_result = minimize(objective, initial, **minimize_kwargs)
                primary_message = str(primary_result.message)
                primary_iterations = int(getattr(primary_result, "nit", 0))
                primary_solver_success = bool(primary_result.success) and bool(
                    np.all(np.isfinite(primary_result.x))
                )
                primary_raw = np.asarray(primary_result.x, dtype=float)
                if primary_solver_success:
                    primary_weights, primary_mandatory, primary_violations = (
                        evaluate_candidate(primary_raw, sell_only=False)
                    )
                else:
                    primary_weights = primary_raw
                    primary_mandatory = ()
                    primary_violations = (f"optimizer failed: {primary_message}",)
                primary_accepted = primary_solver_success and not primary_violations
                record_attempt(
                    stage=PortfolioOptimizationStage.PRIMARY_OPTIMIZER,
                    solver_success=primary_solver_success,
                    message=primary_message,
                    iterations=primary_iterations,
                    violations=primary_violations,
                    accepted=primary_accepted,
                )
                if primary_accepted:
                    selected_weights = primary_weights
                    selected_raw_weights = primary_raw
                    selected_stage = PortfolioOptimizationStage.PRIMARY_OPTIMIZER
                    selected_message = primary_message
                    selected_iterations = primary_iterations
                    mandatory_indices = primary_mandatory
            except (ArithmeticError, FloatingPointError, ValueError) as error:
                record_attempt(
                    stage=PortfolioOptimizationStage.PRIMARY_OPTIMIZER,
                    solver_success=False,
                    message=f"optimizer failed safely: {error}",
                    iterations=None,
                    violations=("primary optimizer raised a numerical error",),
                    accepted=False,
                )
        else:
            record_attempt(
                stage=PortfolioOptimizationStage.PRIMARY_OPTIMIZER,
                solver_success=False,
                message="skipped because the production risk budget forbids new risk",
                iterations=None,
                violations=("RISK_REDUCTION_ONLY",),
                accepted=False,
            )

        def run_projection(
            *,
            stage: PortfolioOptimizationStage,
            projection_bounds: list[tuple[float, float]],
            sell_only: bool,
        ) -> None:
            nonlocal mandatory_indices
            nonlocal selected_iterations
            nonlocal selected_message
            nonlocal selected_raw_weights
            nonlocal selected_stage
            nonlocal selected_weights
            projection_initial = _recovery_initial(
                current,
                bounds=projection_bounds,
                gross_limit=gross_limit,
                volatility_limit=volatility_limit,
                covariance=covariance,
            )

            def projection_objective(weights: np.ndarray) -> float:
                delta = weights - current
                return 0.5 * float(delta @ delta)

            def projection_jac(weights: np.ndarray) -> np.ndarray:
                return np.asarray(weights - current, dtype=float)

            try:
                projection_result = minimize(
                    projection_objective,
                    projection_initial,
                    method="SLSQP",
                    jac=projection_jac,
                    bounds=projection_bounds,
                    constraints=constraints,
                    options={"maxiter": 1_000, "ftol": 1e-12, "disp": False},
                )
                message = str(projection_result.message)
                iterations = int(getattr(projection_result, "nit", 0))
                solver_success = bool(projection_result.success) and bool(
                    np.all(np.isfinite(projection_result.x))
                )
                raw_weights = np.asarray(projection_result.x, dtype=float)
                if solver_success:
                    processed, mandatory, violations = evaluate_candidate(
                        raw_weights,
                        sell_only=sell_only,
                    )
                else:
                    processed = raw_weights
                    mandatory = ()
                    violations = (f"optimizer failed: {message}",)
                accepted = solver_success and not violations
                record_attempt(
                    stage=stage,
                    solver_success=solver_success,
                    message=message,
                    iterations=iterations,
                    violations=violations,
                    accepted=accepted,
                )
                if accepted:
                    selected_weights = processed
                    selected_raw_weights = raw_weights
                    selected_stage = stage
                    selected_message = message
                    selected_iterations = iterations
                    mandatory_indices = mandatory
            except (ArithmeticError, FloatingPointError, ValueError) as error:
                record_attempt(
                    stage=stage,
                    solver_success=False,
                    message=f"recovery failed safely: {error}",
                    iterations=None,
                    violations=("recovery optimizer raised a numerical error",),
                    accepted=False,
                )

        if (
            selected_weights is None
            and operating_mode is PortfolioOperatingMode.NORMAL
        ):
            run_projection(
                stage=PortfolioOptimizationStage.FEASIBILITY_RECOVERY,
                projection_bounds=bounds,
                sell_only=False,
            )
        if selected_weights is None:
            sell_only_bounds = [
                (0.0, min(float(current[index]), upper))
                for index, (_, upper) in enumerate(bounds)
            ]
            run_projection(
                stage=PortfolioOptimizationStage.SELL_ONLY_FALLBACK,
                projection_bounds=sell_only_bounds,
                sell_only=True,
            )
        if selected_weights is None or selected_raw_weights is None:
            blocking_items: list[str] = []
            for attempt in attempts:
                recorded_constraints = attempt.get("blocking_constraints")
                if isinstance(recorded_constraints, list):
                    blocking_items.extend(str(item) for item in recorded_constraints)
            blocking_constraints = tuple(dict.fromkeys(blocking_items))
            diagnostics = _optimizer_diagnostics(
                attempts=attempts,
                stage=PortfolioOptimizationStage.BLOCKED,
                operating_mode=operating_mode,
                pre_solve_violations=pre_solve_violations,
                solver_message="no recovery stage produced a valid target",
                iterations=None,
                blocking_constraints=blocking_constraints,
                final_target_status=PortfolioConstructionStatus.BLOCKED,
            )
            return self._blocked(
                decision_time,
                authorization,
                risk,
                (
                    "PORTFOLIO_BLOCKED_NO_FEASIBLE_TARGET",
                    *blocking_constraints,
                ),
                optimizer_provenance=diagnostics,
                operating_mode=operating_mode,
            )
        weights = selected_weights
        raw_weights = selected_raw_weights
        target = {
            symbol: float(weights[index])
            for index, symbol in enumerate(symbols)
            if weights[index] > 1e-12
        }
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
            if abs(float(weights[index] - current_value)) >= 1e-12:
                continue
            if abs(delta) < self.constraints.no_trade_band:
                dropped_no_trade += 1
            elif abs(delta) < self.constraints.minimum_rebalance_weight:
                dropped_minimum_weight += 1
            elif abs(delta) * portfolio_value < self.constraints.minimum_trade_value:
                dropped_minimum_value += 1
        positive_raw = [value for value in raw_nonzero.values() if value > 0]
        positive_final = [value for value in target.values() if value > 0]
        risk_repair_symbols = tuple(symbols[index] for index in mandatory_indices)
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
            mandatory_risk_repair_count=len(risk_repair_symbols),
            mandatory_risk_repair_symbols=risk_repair_symbols,
        )
        provenance_document = provenance.document()
        provenance_document.update(
            _optimizer_diagnostics(
                attempts=attempts,
                stage=selected_stage,
                operating_mode=operating_mode,
                pre_solve_violations=pre_solve_violations,
                solver_message=selected_message,
                iterations=selected_iterations,
                blocking_constraints=(),
                final_target_status=(
                    PortfolioConstructionStatus.PROVISIONAL_OPERATIONAL_APPROVED
                    if self.operational_mode
                    else PortfolioConstructionStatus.PRODUCTION_APPROVED
                ),
            )
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
                optimizer_provenance=provenance_document,
                operating_mode=operating_mode,
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
                optimizer_provenance=provenance_document,
                operating_mode=operating_mode,
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
            optimizer_provenance=provenance_document,
            raw_target_weights=raw_nonzero,
            optimization_stage=selected_stage,
            operating_mode=operating_mode,
            risk_repair_symbols=risk_repair_symbols,
        )

    def _blocked(
        self,
        decision_time: datetime,
        authorization: ResearchDataAuthorization,
        risk: RiskModelEstimate,
        blockers: tuple[str, ...],
        *,
        optimizer_provenance: dict[str, object] | None = None,
        operating_mode: PortfolioOperatingMode = PortfolioOperatingMode.NORMAL,
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
            optimizer_provenance=optimizer_provenance,
            optimization_stage=PortfolioOptimizationStage.BLOCKED,
            operating_mode=operating_mode,
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


def _apply_constraint_aware_no_trade_bands(
    proposed: np.ndarray,
    current: np.ndarray,
    portfolio_value: float,
    constraints: PortfolioConstraints,
    *,
    validator: Callable[[np.ndarray], list[str]],
) -> tuple[np.ndarray, tuple[int, ...]]:
    output = proposed.copy()
    mandatory: list[int] = []
    for index, delta in enumerate(proposed - current):
        suppressible = (
            abs(delta) < constraints.no_trade_band
            or abs(delta) < constraints.minimum_rebalance_weight
            or abs(delta) * portfolio_value < constraints.minimum_trade_value
        )
        if not suppressible:
            continue
        reverted = output.copy()
        reverted[index] = current[index]
        if validator(reverted):
            mandatory.append(index)
        else:
            output = reverted
    return output, tuple(mandatory)


def _recovery_initial(
    current: np.ndarray,
    *,
    bounds: list[tuple[float, float]],
    gross_limit: float,
    volatility_limit: float,
    covariance: np.ndarray,
) -> np.ndarray:
    initial = np.clip(
        current,
        np.asarray([lower for lower, _ in bounds], dtype=float),
        np.asarray([upper for _, upper in bounds], dtype=float),
    )
    gross = float(initial.sum())
    if gross > gross_limit and gross > 0:
        initial *= gross_limit / gross
    volatility = portfolio_volatility(initial, covariance)
    if volatility > volatility_limit and volatility > 0:
        initial *= volatility_limit / volatility
    return np.asarray(initial, dtype=float)


def _sell_only_violations(
    weights: np.ndarray,
    *,
    current: np.ndarray,
    risk: RiskModelEstimate,
) -> list[str]:
    tolerance = 1e-8
    violations: list[str] = []
    if np.any(weights > current + tolerance):
        violations.append("sell-only fallback increased a position")
    if float(weights.sum()) > float(current.sum()) + tolerance:
        violations.append("sell-only fallback increased gross exposure")
    current_volatility = portfolio_volatility(current, risk.annualized_covariance)
    target_volatility = portfolio_volatility(weights, risk.annualized_covariance)
    if target_volatility > current_volatility + tolerance:
        violations.append("sell-only fallback increased portfolio volatility")
    current_hhi = float(np.sum(current * current))
    target_hhi = float(np.sum(weights * weights))
    if target_hhi > current_hhi + tolerance:
        violations.append("sell-only fallback increased concentration HHI")
    beta = np.asarray([risk.beta[symbol] for symbol in risk.symbols], dtype=float)
    if abs(float(beta @ weights)) > abs(float(beta @ current)) + tolerance:
        violations.append("sell-only fallback increased absolute beta")
    return violations


def _optimizer_diagnostics(
    *,
    attempts: list[dict[str, object]],
    stage: PortfolioOptimizationStage,
    operating_mode: PortfolioOperatingMode,
    pre_solve_violations: tuple[str, ...],
    solver_message: str,
    iterations: int | None,
    blocking_constraints: tuple[str, ...],
    final_target_status: PortfolioConstructionStatus,
) -> dict[str, object]:
    primary = next(
        (
            item
            for item in attempts
            if item.get("stage") == PortfolioOptimizationStage.PRIMARY_OPTIMIZER.value
        ),
        {},
    )
    status = {
        PortfolioOptimizationStage.PRIMARY_OPTIMIZER: "OPTIMIZER_PRIMARY_PASS",
        PortfolioOptimizationStage.FEASIBILITY_RECOVERY: "FEASIBILITY_RECOVERY_PASS",
        PortfolioOptimizationStage.SELL_ONLY_FALLBACK: "SELL_ONLY_FALLBACK_PASS",
        PortfolioOptimizationStage.BLOCKED: "PORTFOLIO_BLOCKED_NO_FEASIBLE_TARGET",
    }[stage]
    return {
        "optimizer_status": status,
        "solver_message": solver_message,
        "iterations": iterations,
        "primary_success": bool(primary.get("accepted", False)),
        "fallback_stage_used": stage.value,
        "operating_mode": operating_mode.value,
        "pre_solve_constraint_state": list(pre_solve_violations),
        "post_solve_validation": "PASS" if not blocking_constraints else "FAIL",
        "blocking_constraints": list(blocking_constraints),
        "recovery_result": status,
        "final_target_status": final_target_status.value,
        "attempts": attempts,
    }


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
    liquidity_limits: np.ndarray | None = None,
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
    if liquidity_limits is not None:
        for index in np.flatnonzero(weights > liquidity_limits + tolerance):
            violations.append(f"liquidity limit failed: {risk.symbols[int(index)]}")
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
