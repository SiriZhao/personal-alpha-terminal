from __future__ import annotations

from dataclasses import replace

from personal_alpha_terminal.strategies.us_adaptive_alpha.schemas import (
    CapitalPreservationConfig,
    ConditionalEvidence,
    DataGateDecision,
    EnsembleDecision,
    EnsembleResult,
    EvidenceGrade,
    MomentumCrashResult,
    PortfolioRiskSnapshot,
    RegimeBudgetDecision,
    ResearchStage,
    SleeveAssessment,
    SleeveSignal,
    SleeveStatus,
)


def build_ensemble(
    *,
    data_gate: DataGateDecision,
    sleeve_assessments: tuple[SleeveAssessment, ...],
    signals: tuple[SleeveSignal, ...],
    conditional_evidence: dict[str, ConditionalEvidence],
    regime: RegimeBudgetDecision,
    momentum_crash: MomentumCrashResult,
    portfolio: PortfolioRiskSnapshot,
    config: CapitalPreservationConfig,
    stage: ResearchStage = ResearchStage.HISTORICAL_RESEARCH,
) -> EnsembleResult:
    """Allocate research risk without hiding independent sleeve contributions."""

    assessment_by_name = {item.name: item for item in sleeve_assessments}
    warnings = [*data_gate.blockers, *data_gate.warnings]
    if not data_gate.allowed_for_position_range:
        decisions = tuple(
            _blocked_decision(signal, data_gate.blockers or data_gate.warnings)
            for signal in signals
        )
        return EnsembleResult(
            data_gate=data_gate,
            decisions=decisions,
            cash_weight=1.0,
            total_invested_weight=0.0,
            warnings=tuple(dict.fromkeys(warnings)),
            stage=stage,
        )

    current_sector = dict(portfolio.sector_weights)
    current_cluster = dict(portfolio.cluster_weights)
    current_sleeve = dict(portfolio.sleeve_weights)
    current_beta = float(portfolio.portfolio_beta or 0.0)
    allocated = sum(portfolio.current_weights.values())
    pending: list[EnsembleDecision] = []
    ordered = sorted(signals, key=lambda item: (-item.evidence_score, item.symbol))
    for signal in ordered:
        blockers: list[str] = []
        reasons: list[str] = []
        assessment = assessment_by_name.get(signal.sleeve_name)
        if assessment is None or assessment.status is SleeveStatus.DISABLED:
            blockers.append("sleeve is disabled by the capability registry")
        if signal.signal_grade != "positive":
            blockers.append("base strategy signal is not positive")
        if signal.evidence_score < config.minimum_signal_evidence:
            blockers.append("base signal evidence is below minimum")
        if signal.beta is None:
            blockers.append("asset beta is unavailable")
        conditional_multiplier, conditional_reason = _conditional_multiplier(
            signal,
            conditional_evidence.get(signal.symbol),
            config,
        )
        reasons.extend(conditional_reason)
        crash_multiplier = (
            momentum_crash.momentum_multiplier
            if "momentum" in signal.sleeve_name
            else momentum_crash.total_risk_multiplier
        )
        unconstrained = (
            signal.requested_weight
            * conditional_multiplier
            * regime.applied_multiplier
            * crash_multiplier
        )
        reasons.extend(blockers)
        if blockers:
            final_weight = 0.0
        else:
            assert assessment is not None and signal.beta is not None
            sleeve_limit = min(config.maximum_sleeve_weight, assessment.maximum_capital_weight)
            if assessment.status is SleeveStatus.EXPERIMENTAL:
                sleeve_limit = min(sleeve_limit, config.maximum_experimental_sleeve_weight)
            capacities = {
                "single_name": config.maximum_single_name_weight,
                "liquidity": signal.maximum_liquidity_weight,
                "sector": max(
                    0.0,
                    config.maximum_sector_weight - current_sector.get(signal.sector, 0.0),
                ),
                "correlation_cluster": max(
                    0.0,
                    config.maximum_cluster_weight
                    - current_cluster.get(signal.correlation_cluster, 0.0),
                ),
                "sleeve": max(
                    0.0,
                    sleeve_limit - current_sleeve.get(signal.sleeve_name, 0.0),
                ),
                "total_invested": max(0.0, config.maximum_invested_weight - allocated),
                "beta": (
                    max(0.0, config.maximum_beta - current_beta) / signal.beta
                    if signal.beta > 0
                    else config.maximum_single_name_weight
                ),
            }
            final_weight = max(0.0, min(unconstrained, *capacities.values()))
            binding = [name for name, value in capacities.items() if value <= final_weight + 1e-12]
            reasons.extend(f"binding constraint: {name}" for name in binding)
            allocated += final_weight
            current_sector[signal.sector] = current_sector.get(signal.sector, 0.0) + final_weight
            current_cluster[signal.correlation_cluster] = (
                current_cluster.get(signal.correlation_cluster, 0.0) + final_weight
            )
            current_sleeve[signal.sleeve_name] = (
                current_sleeve.get(signal.sleeve_name, 0.0) + final_weight
            )
            current_beta += final_weight * signal.beta
        pending.append(
            EnsembleDecision(
                symbol=signal.symbol,
                sleeve_name=signal.sleeve_name,
                base_requested_weight=signal.requested_weight,
                conditional_multiplier=conditional_multiplier,
                regime_multiplier=regime.applied_multiplier,
                momentum_crash_multiplier=crash_multiplier,
                risk_constrained_weight=final_weight,
                suggested_weight_low=final_weight * 0.80,
                suggested_weight_high=final_weight,
                final_grade="positive" if final_weight > 0 else "insufficient",
                allowed=final_weight > 0,
                constraint_reasons=tuple(dict.fromkeys(reasons)),
                decomposition={
                    "base_strategy": signal.requested_weight,
                    "conditional_overlay": conditional_multiplier,
                    "market_regime_overlay": regime.applied_multiplier,
                    "momentum_crash_overlay": crash_multiplier,
                    "risk_constraint_reduction": max(0.0, unconstrained - final_weight),
                },
                trace_ids=signal.trace_ids,
                failure_conditions=signal.failure_conditions,
            )
        )
    pending = _enforce_top_five(pending, config.maximum_top_five_weight)
    total = sum(item.risk_constrained_weight for item in pending)
    cash = max(0.0, 1 - total)
    if not pending or total <= 1e-12:
        warnings.append("no eligible signal; remaining in cash is a valid outcome")
    warnings.extend(regime.reasons)
    warnings.extend(momentum_crash.reasons)
    return EnsembleResult(
        data_gate=data_gate,
        decisions=tuple(
            sorted(
                pending,
                key=lambda item: (-item.risk_constrained_weight, item.symbol),
            )
        ),
        cash_weight=cash,
        total_invested_weight=total,
        warnings=tuple(dict.fromkeys(warnings)),
        stage=stage,
    )


def _conditional_multiplier(
    signal: SleeveSignal,
    evidence: ConditionalEvidence | None,
    config: CapitalPreservationConfig,
) -> tuple[float, tuple[str, ...]]:
    if evidence is None or evidence.grade is EvidenceGrade.INSUFFICIENT:
        return 1.0, ("conditional evidence unavailable; no enhancement applied",)
    if evidence.grade is EvidenceGrade.LOW or evidence.probability_lift is None:
        return 1.0, ("conditional evidence is low; no enhancement applied",)
    if signal.signal_grade != "positive":
        return 1.0, ("conditional evidence cannot create a position",)
    if evidence.lift_lower is not None and evidence.lift_lower > 0:
        increase = min(config.positive_overlay_limit, max(0.0, evidence.probability_lift))
        return 1 + increase, ("positive conditional evidence enhanced an existing signal",)
    if evidence.lift_upper is not None and evidence.lift_upper < 0:
        reduction = min(config.negative_overlay_limit, abs(evidence.probability_lift))
        return 1 - reduction, ("negative conditional evidence reduced the base signal",)
    return 1.0, ("conditional lift interval crosses zero",)


def _blocked_decision(
    signal: SleeveSignal,
    blockers: tuple[str, ...],
) -> EnsembleDecision:
    return EnsembleDecision(
        symbol=signal.symbol,
        sleeve_name=signal.sleeve_name,
        base_requested_weight=signal.requested_weight,
        conditional_multiplier=1.0,
        regime_multiplier=0.0,
        momentum_crash_multiplier=0.0,
        risk_constrained_weight=0.0,
        suggested_weight_low=0.0,
        suggested_weight_high=0.0,
        final_grade="insufficient",
        allowed=False,
        constraint_reasons=tuple(blockers) or ("data gate did not pass",),
        decomposition={
            "base_strategy": signal.requested_weight,
            "conditional_overlay": 1.0,
            "market_regime_overlay": 0.0,
            "momentum_crash_overlay": 0.0,
            "risk_constraint_reduction": signal.requested_weight,
        },
        trace_ids=signal.trace_ids,
        failure_conditions=signal.failure_conditions,
    )


def _enforce_top_five(
    decisions: list[EnsembleDecision],
    maximum_top_five_weight: float,
) -> list[EnsembleDecision]:
    ranked = sorted(decisions, key=lambda item: item.risk_constrained_weight, reverse=True)
    top = ranked[:5]
    top_total = sum(item.risk_constrained_weight for item in top)
    if top_total <= maximum_top_five_weight + 1e-12 or top_total <= 0:
        return decisions
    scale = maximum_top_five_weight / top_total
    top_keys = {(item.symbol, item.sleeve_name) for item in top}
    output: list[EnsembleDecision] = []
    for item in decisions:
        if (item.symbol, item.sleeve_name) not in top_keys:
            output.append(item)
            continue
        revised = item.risk_constrained_weight * scale
        decomposition = dict(item.decomposition)
        decomposition["risk_constraint_reduction"] += item.risk_constrained_weight - revised
        output.append(
            replace(
                item,
                risk_constrained_weight=revised,
                suggested_weight_low=revised * 0.80,
                suggested_weight_high=revised,
                constraint_reasons=(
                    *item.constraint_reasons,
                    "binding constraint: top_five_concentration",
                ),
                decomposition=decomposition,
            )
        )
    return output
