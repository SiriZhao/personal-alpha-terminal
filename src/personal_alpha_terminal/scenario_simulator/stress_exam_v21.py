"""ROUND25 PHASE 19: Stress Exam 2.1 -- overlay candidate comparison.

Scenario definitions are imported unchanged from the ROUND24 Stress Exam 2.0
(no shock parameter is ever edited to improve a result).  The same baseline
is re-run under four documented variants:

A. Classical Champion (frozen, unchanged)
B. Champion + Regime risk budget (risk-off gross scaled to 70%)
C. Champion + Drawdown Governor (gross scaled to 85%)
D. Champion + ETF Core (25% diversified across IVV/VOO/VTI/IJR)

Results are RESEARCH comparisons only; no variant is promoted automatically.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from personal_alpha_terminal.scenario_simulator.stress_exam_v2 import (
    MARKET_SCENARIOS,
    RISK_GATE_THRESHOLDS,
    ProductionBaseline,
    simulate_market_scenario,
)
from personal_alpha_terminal.scenario_simulator.stress_exam_v2_run import (
    DEFAULT_SEED,
)

ETF_CORE_VARIANT = {
    "IVV": 0.0625,
    "VOO": 0.0625,
    "VTI": 0.0625,
    "IJR": 0.0625,
}


def _variant_baseline(
    baseline: ProductionBaseline, variant: dict[str, Any]
) -> ProductionBaseline:
    holdings = dict(baseline.holdings)
    cash = max(0.0, baseline.cash_weight)
    scale = variant.get("scale_gross")
    if scale is not None:
        gross = sum(holdings.values())
        holdings = {symbol: weight * scale for symbol, weight in holdings.items()}
        cash = min(1.0, cash + gross * (1.0 - scale))
    etf_core = variant.get("etf_core")
    if etf_core:
        holdings = {symbol: weight * 0.75 for symbol, weight in holdings.items()}
        for symbol, weight in etf_core.items():
            holdings[symbol] = holdings.get(symbol, 0.0) + weight
    return replace(
        baseline,
        holdings={symbol: round(weight, 8) for symbol, weight in sorted(holdings.items())},
        cash_weight=cash,
        etf_symbols=tuple(sorted(set(baseline.etf_symbols) | set(etf_core or {}))),
    )


VARIANTS: tuple[tuple[str, dict[str, Any], str], ...] = (
    ("A_classical_champion", {}, "frozen Classical Champion"),
    (
        "B_champion_regime_risk_budget",
        {"scale_gross": 0.70},
        "risk-off regime scales gross to 70%",
    ),
    (
        "C_champion_drawdown_governor",
        {"scale_gross": 0.85},
        "drawdown governor scales gross to 85%",
    ),
    (
        "D_champion_etf_core",
        {"etf_core": ETF_CORE_VARIANT},
        "25% diversified into ETF_CORE (IVV/VOO/VTI/IJR)",
    ),
)


def run_stress_exam_v21(
    baseline: ProductionBaseline | None,
    *,
    seed: int = DEFAULT_SEED,
    sessions: int = 252,
) -> dict[str, Any]:
    if baseline is None or not baseline.valid():
        return {
            "version": "round25-stress-exam-v2.1",
            "status": "UNAVAILABLE_BASELINE",
            "scenario_definitions_unchanged": True,
            "variants": {},
        }
    comparison: dict[str, Any] = {}
    for name, variant, description in VARIANTS:
        variant_baseline = _variant_baseline(baseline, variant)
        rows: dict[str, Any] = {}
        for spec in MARKET_SCENARIOS:
            metrics = simulate_market_scenario(
                spec,
                variant_baseline,
                seed=seed,
                sessions=sessions,
                thresholds=RISK_GATE_THRESHOLDS,
            )
            rows[spec.name] = {
                "scenario_return": metrics.final_portfolio_value - 1.0,
                "max_drawdown": metrics.max_drawdown,
                "cvar_95": metrics.cvar_95,
                "annualized_volatility": metrics.annualized_volatility,
                "turnover": metrics.turnover,
                "transaction_cost": metrics.transaction_cost,
                "de_risk_sessions": metrics.time_to_de_risk,
                "recovery_sessions": metrics.time_to_recover,
                "liquidation_days": metrics.liquidation_days,
                "gate_violations": list(metrics.gate_violations),
            }
        comparison[name] = {"description": description, "scenarios": rows}
    summary = {
        "version": "round25-stress-exam-v2.1",
        "status": "COMPLETE",
        "scenario_definitions_unchanged": True,
        "baseline_run": baseline.run_id,
        "seed": seed,
        "sessions": sessions,
        "not_historical_backtest": True,
        "not_alpha_certification": True,
        "research_only": True,
        "auto_promotion": False,
        "worst_scenario_per_variant": {
            name: max(
                (
                    (scenario, rows["scenarios"][scenario]["max_drawdown"])
                    for scenario in rows["scenarios"]
                ),
                key=lambda pair: abs(pair[1]),
            )[0]
            for name, rows in comparison.items()
        },
    }
    return {"summary": summary, "comparison": comparison}
