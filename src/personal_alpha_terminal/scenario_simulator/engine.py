from hashlib import sha256
from json import dumps
from math import isfinite

from personal_alpha_terminal.scenario_simulator.schemas import (
    AssetFactorExposure,
    FactorContribution,
    PositionScenarioImpact,
    RiskFactorDefinition,
    RiskLevel,
    ScenarioDefinition,
    ScenarioPortfolio,
    ScenarioResult,
)


class ScenarioEngine:
    """Apply transparent linear factor sensitivities and separate FX translation."""

    def simulate(
        self,
        portfolio: ScenarioPortfolio,
        scenario: ScenarioDefinition,
        *,
        factors: tuple[RiskFactorDefinition, ...],
        exposures: tuple[AssetFactorExposure, ...],
    ) -> ScenarioResult:
        factor_by_code = {item.code: item for item in factors}
        if len(factor_by_code) != len(factors):
            raise ValueError("risk factor definitions must be unique")
        shocks = {item.factor_code: item for item in scenario.factor_shocks}
        for code, shock in shocks.items():
            definition = factor_by_code.get(code)
            if definition is None:
                raise ValueError(f"unknown risk factor: {code}")
            if definition.shock_unit != shock.unit:
                raise ValueError(
                    f"shock unit mismatch for {code}: expected {definition.shock_unit}"
                )
            normalized = shock.normalized_magnitude
            if not definition.normalized_minimum <= normalized <= (definition.normalized_maximum):
                raise ValueError(f"shock for {code} is outside configured bounds")

        exposure_by_asset: dict[int, dict[str, AssetFactorExposure]] = {}
        portfolio_asset_ids = {position.instrument.id for position in portfolio.positions}
        for exposure in exposures:
            if exposure.asset_id not in portfolio_asset_ids:
                raise ValueError("asset exposure is not in the portfolio snapshot")
            if exposure.as_of_date > portfolio.as_of_date:
                raise ValueError("asset exposure is dated after portfolio valuation")
            if exposure.factor_code not in factor_by_code:
                raise ValueError(f"exposure references unknown factor: {exposure.factor_code}")
            existing = exposure_by_asset.setdefault(exposure.asset_id, {})
            if exposure.factor_code in existing:
                raise ValueError("duplicate asset/factor exposure")
            existing[exposure.factor_code] = exposure

        impacts: list[PositionScenarioImpact] = []
        warnings: list[str] = []
        if portfolio.base_currency in scenario.currency_shocks:
            raise ValueError("a portfolio base currency cannot have a translation shock")
        position_currencies = {
            position.currency
            for position in portfolio.positions
            if position.currency != portfolio.base_currency
        }
        unused_currency_shocks = set(scenario.currency_shocks) - position_currencies
        warnings.extend(
            f"{currency}: currency shock has no matching non-base-currency position"
            for currency in sorted(unused_currency_shocks)
        )
        portfolio_return = 0.0
        portfolio_low = 0.0
        portfolio_high = 0.0
        mapped_weight = 0.0
        weighted_mapping_confidence = 0.0
        for position in portfolio.positions:
            asset_exposures = exposure_by_asset.get(position.instrument.id, {})
            contributions: list[FactorContribution] = []
            factor_return = 0.0
            factor_low = 0.0
            factor_high = 0.0
            for factor_code, shock in shocks.items():
                mapping = asset_exposures.get(factor_code)
                if mapping is None:
                    continue
                normalized = shock.normalized_magnitude
                contribution = mapping.sensitivity * normalized
                interval = sorted(
                    (
                        mapping.sensitivity_low * normalized,
                        mapping.sensitivity_high * normalized,
                    )
                )
                factor_return += contribution
                factor_low += interval[0]
                factor_high += interval[1]
                contributions.append(
                    FactorContribution(
                        factor_code=factor_code,
                        normalized_shock=normalized,
                        sensitivity=mapping.sensitivity,
                        contribution=contribution,
                        sensitivity_low=mapping.sensitivity_low,
                        sensitivity_high=mapping.sensitivity_high,
                        source=mapping.source,
                        confidence_score=mapping.confidence_score,
                    )
                )
            currency_return = (
                0.0
                if position.currency.upper() == portfolio.base_currency.upper()
                else scenario.currency_shocks.get(position.currency.upper(), 0.0)
            )
            mapped = bool(contributions) or currency_return != 0
            if mapped:
                mapped_weight += position.weight
                confidences = [item.confidence_score for item in contributions]
                if currency_return != 0:
                    confidences.append(80)
                weighted_mapping_confidence += position.weight * (
                    sum(confidences) / len(confidences)
                )
            factor_return, factor_was_clamped = _floor_return(factor_return)
            factor_low, low_was_clamped = _floor_return(factor_low)
            factor_high, high_was_clamped = _floor_return(factor_high)
            if factor_was_clamped or low_was_clamped or high_was_clamped:
                warnings.append(f"{position.instrument.symbol}: factor loss was floored at -100%")
            combined = (1 + factor_return) * (1 + currency_return) - 1
            combined_low = (1 + factor_low) * (1 + currency_return) - 1
            combined_high = (1 + factor_high) * (1 + currency_return) - 1
            if not all(isfinite(item) for item in (combined, combined_low, combined_high)):
                raise ValueError("scenario produced non-finite position return")
            contribution = position.weight * combined
            portfolio_return += contribution
            portfolio_low += position.weight * min(combined_low, combined_high)
            portfolio_high += position.weight * max(combined_low, combined_high)
            impacts.append(
                PositionScenarioImpact(
                    instrument=position.instrument,
                    currency=position.currency,
                    weight=position.weight,
                    original_value=position.market_value,
                    factor_return=factor_return,
                    currency_return=currency_return,
                    combined_return=combined,
                    return_low=min(combined_low, combined_high),
                    return_high=max(combined_low, combined_high),
                    contribution=contribution,
                    stressed_value=position.market_value * (1 + combined),
                    mapped=mapped,
                    factor_contributions=tuple(
                        sorted(
                            contributions,
                            key=lambda item: item.factor_code,
                        )
                    ),
                )
            )

        invested_weight = sum(item.weight for item in portfolio.positions)
        uncovered_weight = max(0.0, invested_weight - mapped_weight)
        if uncovered_weight > 0:
            warnings.append(
                f"{uncovered_weight:.2%} of portfolio value has no mapping to the shocked factors"
            )
        if scenario.evidence_level == "illustrative":
            warnings.append("built-in historical proxy is illustrative and requires recalibration")
        confidence = _confidence_score(
            scenario,
            mapped_weight,
            weighted_mapping_confidence,
            uncovered_weight,
            warnings,
        )
        pnl_amount = portfolio.total_value * portfolio_return
        fingerprint = _fingerprint(portfolio, scenario, exposures)
        return ScenarioResult(
            run_id=None,
            portfolio_id=portfolio.portfolio_id,
            portfolio_name=portfolio.portfolio_name,
            base_currency=portfolio.base_currency,
            as_of_date=portfolio.as_of_date,
            scenario=scenario,
            original_value=portfolio.total_value,
            stressed_value=portfolio.total_value + pnl_amount,
            pnl_amount=pnl_amount,
            pnl_percent=portfolio_return,
            pnl_percent_low=portfolio_low,
            pnl_percent_high=portfolio_high,
            risk_level=_risk_level(portfolio_return),
            mapped_weight=mapped_weight,
            uncovered_weight=uncovered_weight,
            confidence_score=confidence,
            data_fingerprint=fingerprint,
            impacts=tuple(sorted(impacts, key=lambda item: item.contribution)),
            warnings=tuple(dict.fromkeys(warnings)),
        )


def _floor_return(value: float) -> tuple[float, bool]:
    if value < -1:
        return -1.0, True
    return value, False


def _risk_level(portfolio_return: float) -> RiskLevel:
    tolerance = 1e-12
    if portfolio_return <= -0.20 + tolerance:
        return "Critical"
    if portfolio_return <= -0.10 + tolerance:
        return "High"
    if portfolio_return <= -0.05 + tolerance:
        return "Medium"
    return "Low"


def _confidence_score(
    scenario: ScenarioDefinition,
    mapped_weight: float,
    weighted_mapping_confidence: float,
    uncovered_weight: float,
    warnings: list[str],
) -> int:
    evidence_scores = {
        "source_backed": 90,
        "calibrated_historical": 85,
        "user_assumption": 65,
        "illustrative": 45,
    }
    mapping_score = weighted_mapping_confidence / mapped_weight if mapped_weight > 0 else 0
    score = 0.45 * evidence_scores[scenario.evidence_level] + 0.55 * mapping_score
    score -= uncovered_weight * 40
    score -= min(10, 2 * len(warnings))
    if uncovered_weight > 0.20:
        score = min(score, 60)
    if scenario.evidence_level == "illustrative":
        score = min(score, 55)
    return max(0, min(90, round(score)))


def _fingerprint(
    portfolio: ScenarioPortfolio,
    scenario: ScenarioDefinition,
    exposures: tuple[AssetFactorExposure, ...],
) -> str:
    payload = {
        "portfolio": {
            "id": portfolio.portfolio_id,
            "as_of_date": portfolio.as_of_date.isoformat(),
            "total_value": portfolio.total_value,
            "cash_value": portfolio.cash_value,
            "positions": [
                {
                    "asset_id": item.instrument.id,
                    "currency": item.currency,
                    "market_value": item.market_value,
                    "weight": item.weight,
                }
                for item in sorted(
                    portfolio.positions,
                    key=lambda value: value.instrument.id,
                )
            ],
        },
        "scenario": {
            "name": scenario.name,
            "type": scenario.scenario_type,
            "evidence": scenario.evidence_level,
            "factor_shocks": [
                {
                    "factor": item.factor_code,
                    "magnitude": item.magnitude,
                    "unit": item.unit,
                }
                for item in scenario.factor_shocks
            ],
            "currency_shocks": scenario.currency_shocks,
        },
        "exposures": [
            {
                "asset_id": item.asset_id,
                "factor": item.factor_code,
                "sensitivity": item.sensitivity,
                "low": item.sensitivity_low,
                "high": item.sensitivity_high,
                "as_of": item.as_of_date.isoformat(),
                "source": item.source,
            }
            for item in sorted(
                exposures,
                key=lambda value: (
                    value.asset_id,
                    value.factor_code,
                    value.as_of_date,
                    value.source,
                ),
            )
        ],
    }
    return sha256(
        dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()
