from personal_alpha_terminal.strategies.us_adaptive_alpha.schemas import (
    DataGateDecision,
    DataGateInput,
    GateStatus,
    ResearchCapabilities,
    SleeveAssessment,
    SleeveStatus,
)


def evaluate_data_gate(inputs: DataGateInput) -> DataGateDecision:
    """Fail closed before any US Adaptive Alpha signal is consumed."""

    blockers: list[str] = []
    warnings: list[str] = []
    if inputs.market != "US":
        blockers.append("framework v0.1 accepts only the US market")
    if inputs.quality_status.lower() != "passed":
        blockers.append(f"latest market-data quality status is {inputs.quality_status!r}")
    if inputs.sample_count < inputs.required_sample_count:
        blockers.append(
            f"certified sample {inputs.sample_count} < {inputs.required_sample_count}"
        )
    required = (
        (inputs.security_master_ready, "security master is incomplete"),
        (inputs.point_in_time_universe_ready, "point-in-time universe snapshots are absent"),
        (inputs.trading_calendar_ready, "verified US trading calendar is absent"),
        (inputs.corporate_actions_ready, "corporate-action ledger is incomplete"),
        (
            inputs.point_in_time_total_return_ready,
            "point-in-time total-return series is not certified",
        ),
    )
    blockers.extend(message for ready, message in required if not ready)
    if inputs.source_conflict:
        blockers.append("unresolved provider conflict exists")
    if inputs.stale:
        warnings.append("latest certified data is stale")
    if inputs.as_of_time is None:
        warnings.append("data freshness timestamp is unavailable")
    if not inputs.source_ids:
        warnings.append("data lineage identifiers are unavailable")

    if blockers:
        status = GateStatus.BLOCKED
    elif warnings:
        status = GateStatus.DEGRADED
    else:
        status = GateStatus.PASSED
    return DataGateDecision(
        status=status,
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=tuple(dict.fromkeys(warnings)),
        allowed_for_research=status is not GateStatus.BLOCKED,
        allowed_for_position_range=status is GateStatus.PASSED,
    )


def assess_sleeves(
    gate: DataGateDecision,
    capabilities: ResearchCapabilities,
) -> tuple[SleeveAssessment, ...]:
    """Return an explicit capability registry; unsupported sleeves never fall back."""

    blocked = gate.status is GateStatus.BLOCKED

    def status_when(condition: bool, success: SleeveStatus) -> SleeveStatus:
        return success if condition and not blocked else SleeveStatus.DISABLED

    assessments = (
        SleeveAssessment(
            name="price_momentum",
            label="Price Momentum Research",
            status=status_when(capabilities.pit_prices, SleeveStatus.EXPERIMENTAL),
            reason=(
                "PIT prices available; requires locked OOS validation"
                if capabilities.pit_prices and not blocked
                else "disabled until the data gate and PIT price history pass"
            ),
            required_capabilities=("pit_prices",),
            maximum_capital_weight=0.0 if blocked else 0.25,
        ),
        SleeveAssessment(
            name="quality_constrained_momentum",
            label="Quality-Constrained Momentum",
            status=status_when(
                capabilities.pit_prices and capabilities.pit_fundamentals,
                SleeveStatus.EXPERIMENTAL,
            ),
            reason=(
                "PIT price and fundamental histories available; OOS evidence still required"
                if capabilities.pit_prices
                and capabilities.pit_fundamentals
                and not blocked
                else "PIT fundamentals are not certified; no historical backfill substitution"
            ),
            required_capabilities=("pit_prices", "pit_fundamentals"),
            maximum_capital_weight=0.0 if blocked else 0.30,
        ),
        SleeveAssessment(
            name="sector_rotation",
            label="Sector Rotation",
            status=status_when(
                capabilities.pit_prices and capabilities.pit_sector_membership,
                SleeveStatus.ISOLATED,
            ),
            reason=(
                "isolated to prevent duplicated trend and industry exposure"
                if capabilities.pit_prices
                and capabilities.pit_sector_membership
                and not blocked
                else "historical sector membership or PIT prices are unavailable"
            ),
            required_capabilities=("pit_prices", "pit_sector_membership"),
            maximum_capital_weight=0.0 if blocked else 0.20,
        ),
        SleeveAssessment(
            name="post_earnings_drift",
            label="Post-Earnings / Event Drift",
            status=status_when(
                capabilities.pit_prices and capabilities.pit_earnings_events,
                SleeveStatus.ISOLATED,
            ),
            reason=(
                "earnings events are isolated from generic price/volume events"
                if capabilities.pit_prices
                and capabilities.pit_earnings_events
                and not blocked
                else "reliable point-in-time earnings availability is absent"
            ),
            required_capabilities=("pit_prices", "pit_earnings_events"),
            maximum_capital_weight=0.0 if blocked else 0.15,
        ),
        SleeveAssessment(
            name="market_trend_overlay",
            label="Market Trend / Regime Overlay",
            status=status_when(capabilities.benchmark_history, SleeveStatus.ACTIVE),
            reason=(
                "risk-budget overlay; probability naming requires calibration"
                if capabilities.benchmark_history and not blocked
                else "certified benchmark history is unavailable"
            ),
            required_capabilities=("benchmark_history",),
            maximum_capital_weight=0.0,
        ),
        SleeveAssessment(
            name="conditional_probability_overlay",
            label="Conditional Evidence Overlay",
            status=status_when(
                capabilities.conditional_oos_history,
                SleeveStatus.EXPERIMENTAL,
            ),
            reason=(
                "overlay only; cannot initiate a position"
                if capabilities.conditional_oos_history and not blocked
                else "no frozen out-of-sample conditional evidence"
            ),
            required_capabilities=("conditional_oos_history",),
            maximum_capital_weight=0.0,
        ),
        SleeveAssessment(
            name="relationship_overlay",
            label="Relationship / Lead-Lag Watchlist",
            status=status_when(
                capabilities.corrected_relationships,
                SleeveStatus.EXPERIMENTAL,
            ),
            reason=(
                "candidate-generation only; correlation and Granger are not causal"
                if capabilities.corrected_relationships and not blocked
                else "corrected relationship evidence is unavailable"
            ),
            required_capabilities=("corrected_relationships",),
            maximum_capital_weight=0.0,
        ),
        SleeveAssessment(
            name="defensive_allocation",
            label="Defensive Allocation",
            status=SleeveStatus.ACTIVE,
            reason=(
                "cash is the only enabled defensive asset"
                if not capabilities.defensive_asset_history
                else "cash and separately validated defensive assets are available"
            ),
            required_capabilities=(),
            maximum_capital_weight=1.0,
        ),
        SleeveAssessment(
            name="experimental",
            label="Experimental Sleeve",
            status=SleeveStatus.DISABLED if blocked else SleeveStatus.EXPERIMENTAL,
            reason="hard-capped and isolated; no automatic capital allocation",
            required_capabilities=("independent_oos_evidence",),
            maximum_capital_weight=0.0 if blocked else 0.05,
        ),
    )
    return assessments
