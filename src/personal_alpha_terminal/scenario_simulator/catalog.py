from datetime import date

from personal_alpha_terminal.scenario_simulator.schemas import (
    AssetFactorExposure,
    FactorShock,
    RiskFactorDefinition,
    ScenarioDefinition,
)

RISK_FACTORS: tuple[RiskFactorDefinition, ...] = (
    RiskFactorDefinition(
        "equity_nasdaq",
        "NASDAQ Equity",
        "equity",
        "decimal_return",
        "NASDAQ index total-return shock.",
        -1.0,
        3.0,
    ),
    RiskFactorDefinition(
        "equity_sp500",
        "S&P 500 Equity",
        "equity",
        "decimal_return",
        "S&P 500 index total-return shock.",
        -1.0,
        3.0,
    ),
    RiskFactorDefinition(
        "equity_china",
        "China Equity",
        "equity",
        "decimal_return",
        "Broad China equity index total-return shock.",
        -1.0,
        3.0,
    ),
    RiskFactorDefinition(
        "us_policy_rate",
        "US Policy Rate",
        "rates",
        "basis_points",
        "Federal Reserve policy-rate change; exposure is return per 100bp.",
        -10.0,
        10.0,
    ),
    RiskFactorDefinition(
        "us_10y_yield",
        "US 10Y Yield",
        "rates",
        "basis_points",
        "US 10-year yield change; exposure is return per 100bp.",
        -10.0,
        10.0,
    ),
    RiskFactorDefinition(
        "usd_index",
        "US Dollar Index",
        "fx_macro",
        "decimal_return",
        "Economic sensitivity to a broad US-dollar index; not FX translation.",
        -0.5,
        1.0,
    ),
    RiskFactorDefinition(
        "oil",
        "Crude Oil",
        "commodity",
        "decimal_return",
        "Crude-oil benchmark return shock.",
        -1.0,
        5.0,
    ),
    RiskFactorDefinition(
        "gold",
        "Gold",
        "commodity",
        "decimal_return",
        "Gold benchmark return shock.",
        -1.0,
        5.0,
    ),
    RiskFactorDefinition(
        "china_growth",
        "China Growth Regime",
        "macro_regime",
        "standard_score",
        "Standardized China growth regime score from -1 contraction to +1 recovery.",
        -1.0,
        1.0,
    ),
)

RISK_FACTOR_BY_CODE = {item.code: item for item in RISK_FACTORS}


def built_in_scenarios() -> tuple[ScenarioDefinition, ...]:
    """Return conservative seed templates, not authoritative historical replays."""

    proxy_source = (
        "illustrative_seed:approximate_public_market_moves:"
        "must_recalibrate_from_licensed_or_verified_series"
    )
    return (
        ScenarioDefinition(
            name="2008 Financial Crisis Proxy",
            scenario_type="historical",
            description=(
                "Illustrative calendar-2008 multi-asset proxy. Recalibrate from the "
                "chosen indices and rate series before decision use."
            ),
            factor_shocks=(
                _return("equity_nasdaq", -0.41),
                _return("equity_sp500", -0.37),
                _return("equity_china", -0.65),
                _bp("us_policy_rate", -400),
                _bp("us_10y_yield", -180),
                _return("usd_index", 0.06),
                _return("oil", -0.54),
                _return("gold", 0.06),
            ),
            currency_shocks={},
            evidence_level="illustrative",
            data_sources=(proxy_source,),
            historical_start=date(2008, 1, 2),
            historical_end=date(2008, 12, 31),
            is_builtin=True,
        ),
        ScenarioDefinition(
            name="2020 Pandemic Drawdown Proxy",
            scenario_type="historical",
            description=(
                "Illustrative February-March 2020 drawdown proxy; asset windows are "
                "aligned approximately and require source-backed recalibration."
            ),
            factor_shocks=(
                _return("equity_nasdaq", -0.30),
                _return("equity_sp500", -0.34),
                _return("equity_china", -0.15),
                _bp("us_policy_rate", -150),
                _bp("us_10y_yield", -100),
                _return("usd_index", 0.08),
                _return("oil", -0.60),
                _return("gold", -0.03),
            ),
            currency_shocks={},
            evidence_level="illustrative",
            data_sources=(proxy_source,),
            historical_start=date(2020, 2, 19),
            historical_end=date(2020, 3, 23),
            is_builtin=True,
        ),
        ScenarioDefinition(
            name="2022 Tightening Cycle Proxy",
            scenario_type="historical",
            description=(
                "Illustrative calendar-2022 tightening proxy. Rate and asset windows "
                "must be harmonized before decision use."
            ),
            factor_shocks=(
                _return("equity_nasdaq", -0.33),
                _return("equity_sp500", -0.19),
                _return("equity_china", -0.24),
                _bp("us_policy_rate", 425),
                _bp("us_10y_yield", 236),
                _return("usd_index", 0.08),
                _return("oil", 0.07),
                _return("gold", -0.003),
            ),
            currency_shocks={},
            evidence_level="illustrative",
            data_sources=(proxy_source,),
            historical_start=date(2022, 1, 3),
            historical_end=date(2022, 12, 30),
            is_builtin=True,
        ),
        ScenarioDefinition(
            name="AI Valuation Unwind",
            scenario_type="hypothetical",
            description=(
                "Hypothetical AI and long-duration technology valuation unwind. This "
                "is not a historical event."
            ),
            factor_shocks=(
                _return("equity_nasdaq", -0.35),
                _return("equity_sp500", -0.18),
                _return("equity_china", -0.12),
                _bp("us_10y_yield", 50),
                _return("usd_index", 0.05),
                _return("oil", -0.15),
                _return("gold", 0.08),
            ),
            currency_shocks={},
            evidence_level="user_assumption",
            data_sources=("analyst_assumption:hypothetical_ai_unwind",),
            is_builtin=True,
        ),
        ScenarioDefinition(
            name="China Economic Recovery",
            scenario_type="hypothetical",
            description=(
                "Hypothetical China recovery with stronger local equities and commodity "
                "demand; sensitivities remain asset-specific."
            ),
            factor_shocks=(
                _return("equity_china", 0.25),
                FactorShock(
                    "china_growth",
                    1.0,
                    "standard_score",
                    "standardized strong-recovery assumption",
                ),
                _return("oil", 0.15),
                _return("usd_index", -0.05),
            ),
            currency_shocks={},
            evidence_level="user_assumption",
            data_sources=("analyst_assumption:hypothetical_china_recovery",),
            is_builtin=True,
        ),
        *risk_committee_scenarios(),
    )


def risk_committee_scenarios() -> tuple[ScenarioDefinition, ...]:
    """Pre-registered hypothetical shocks; exposure gaps remain visible."""

    source = ("risk_committee_assumption:pre_registered_stress",)
    return (
        ScenarioDefinition(
            name="NASDAQ Down 30%",
            scenario_type="hypothetical",
            description="NASDAQ total-return shock of minus 30 percent.",
            factor_shocks=(_return("equity_nasdaq", -0.30),),
            currency_shocks={},
            evidence_level="user_assumption",
            data_sources=source,
            is_builtin=True,
        ),
        ScenarioDefinition(
            name="US Dollar Index Up 20%",
            scenario_type="hypothetical",
            description=(
                "Broad dollar-index shock of plus 20 percent; this is an economic "
                "factor shock, not an automatic FX translation return."
            ),
            factor_shocks=(_return("usd_index", 0.20),),
            currency_shocks={},
            evidence_level="user_assumption",
            data_sources=source,
            is_builtin=True,
        ),
        ScenarioDefinition(
            name="Rapid US Rate Increase",
            scenario_type="hypothetical",
            description=(
                "Parallel 200bp policy-rate and US ten-year-yield increase; assets "
                "without source-backed rate sensitivities remain uncovered."
            ),
            factor_shocks=(
                _bp("us_policy_rate", 200),
                _bp("us_10y_yield", 200),
            ),
            currency_shocks={},
            evidence_level="user_assumption",
            data_sources=source,
            is_builtin=True,
        ),
    )


def direct_proxy_exposures(
    *,
    asset_id: int,
    symbol: str,
    as_of_date: date,
) -> tuple[AssetFactorExposure, ...]:
    """Return only identity-like mappings; never invent single-stock betas."""

    code = symbol.upper()
    if code in {"QQQ", "QQQM"}:
        mapping = ("equity_nasdaq", "identity_proxy:nasdaq_tracking_etf")
    elif code in {"SPY", "VOO", "IVV"}:
        mapping = ("equity_sp500", "identity_proxy:sp500_tracking_etf")
    elif code in {"GLD", "IAU"}:
        mapping = ("gold", "identity_proxy:gold_tracking_etf")
    elif code in {"USO", "BNO"}:
        mapping = ("oil", "identity_proxy:oil_tracking_etf")
    else:
        return ()
    factor_code, source = mapping
    return (
        AssetFactorExposure(
            asset_id=asset_id,
            factor_code=factor_code,
            sensitivity=1.0,
            sensitivity_low=0.90,
            sensitivity_high=1.10,
            as_of_date=as_of_date,
            method="identity_proxy",
            source=source,
            confidence_score=90,
        ),
    )


def _return(factor_code: str, value: float) -> FactorShock:
    return FactorShock(
        factor_code,
        value,
        "decimal_return",
        "illustrative seed shock requiring source-backed recalibration",
    )


def _bp(factor_code: str, value: float) -> FactorShock:
    return FactorShock(
        factor_code,
        value,
        "basis_points",
        "illustrative seed rate change requiring source-backed recalibration",
    )
