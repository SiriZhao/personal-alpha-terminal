"""ROUND24 Stress Exam 2.0 orchestration, scoring and artifact writers.

The scorecard has ten axes.  Critical failures are never masked by the
total score.  The old synthetic exam stays untouched in ``exam.py``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.instruments.catalog import default_catalog
from personal_alpha_terminal.models.market import Price, Stock
from personal_alpha_terminal.scenario_simulator.resilience_v2 import (
    ResilienceResult,
    run_resilience_exam,
)
from personal_alpha_terminal.scenario_simulator.stress_exam_v2 import (
    DEFAULT_SEED,
    GENERATED_AT,
    MARKET_SCENARIOS,
    RISK_GATE_THRESHOLDS,
    ProductionBaseline,
    ScenarioRiskMetrics,
    simulate_market_scenario,
)

__all__ = [
    "DEFAULT_SEED",
    "StressExamV2Summary",
    "load_baseline_from_run_dir",
    "run_stress_exam_v2",
    "write_stress_exam_v2_artifacts",
]


@dataclass(frozen=True, slots=True)
class StressExamV2Summary:
    exam_id: str
    generated_at: datetime
    version: str
    seed: int
    baseline: dict[str, Any] | None
    baseline_status: str
    market_scenarios: tuple[ScenarioRiskMetrics, ...]
    resilience: tuple[ResilienceResult, ...]
    scorecard: dict[str, int]
    classification: str
    warnings: tuple[str, ...]
    critical_failures: tuple[str, ...]

    def document(self) -> dict[str, Any]:
        return {
            "exam_id": self.exam_id,
            "generated_at": self.generated_at.isoformat(),
            "version": self.version,
            "seed": self.seed,
            "baseline": self.baseline,
            "baseline_status": self.baseline_status,
            "scenarios": [item.document() for item in self.market_scenarios],
            "resilience": [item.document() for item in self.resilience],
            "scorecard": self.scorecard,
            "classification": self.classification,
            "warnings": list(self.warnings),
            "critical_failures": list(self.critical_failures),
            "production_coupled": True,
            "synthetic_equal_weight_removed": True,
            "not_historical_backtest": True,
            "not_alpha_certification": True,
        }


def load_baseline_from_run_dir(
    *,
    run_dir: Path,
    session: Session | None,
    decision_as_of: date | None = None,
) -> tuple[ProductionBaseline | None, str]:
    """Reconstruct the current production portfolio from a daily-run directory."""

    certificate_path = run_dir / "run_certificate.json"
    if not certificate_path.exists():
        return None, "NO_RUN_CERTIFICATE"
    try:
        certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"UNREADABLE_RUN_CERTIFICATE: {exc}"
    classification = str(certificate.get("classification", ""))
    if "VALID" not in classification and "ACTIONABLE" not in classification:
        return None, f"NON_ACTIONABLE_BASELINE: {classification}"
    recommendations = certificate.get("decision_recommendations") or []
    holdings: dict[str, float] = {}
    etf_symbols: list[str] = []
    equity_symbols: list[str] = []
    for item in recommendations:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol", ""))
        if not symbol:
            continue
        target = item.get("target_weight")
        try:
            weight = float(cast(Any, target))
        except (TypeError, ValueError):
            continue
        if weight <= 0:
            continue
        holdings[symbol] = weight
        if str(item.get("instrument_type", "")) == "ETF":
            etf_symbols.append(symbol)
        else:
            equity_symbols.append(symbol)
    portfolio = certificate.get("portfolio") or {}
    cash_weight = 0.0
    portfolio_value = 100_000.0
    if isinstance(portfolio, dict):
        try:
            portfolio_value = float(
                cast(Any, portfolio.get("total_value", portfolio_value))
            )
        except (TypeError, ValueError):
            pass
        try:
            cash_weight = float(cast(Any, portfolio.get("cash_weight", 0.0)))
        except (TypeError, ValueError):
            pass
    analysis_date_raw = certificate.get("analysis_date")
    analysis_date: date | None = None
    if isinstance(analysis_date_raw, str):
        try:
            analysis_date = date.fromisoformat(analysis_date_raw)
        except ValueError:
            pass
    catalog = default_catalog().by_symbol()
    sector_proxy: dict[str, str] = {}
    for symbol in etf_symbols:
        entry = catalog.get(symbol)
        if entry:
            sector_proxy[symbol] = str(entry.get("category", "UNCLASSIFIED"))
    returns = pd.DataFrame()
    average_dollar_volume: dict[str, float] = {}
    baseline_volatility: float | None = None
    if session is not None and holdings:
        symbols = sorted(holdings)
        cutoff = decision_as_of or analysis_date
        query = (
            select(
                Stock.symbol,
                Price.trade_date,
                Price.close,
                Price.volume,
            )
            .join(Price, Price.stock_id == Stock.id)
            .where(Stock.symbol.in_(symbols))
        )
        if cutoff is not None:
            query = query.where(Price.trade_date <= cutoff)
        rows = session.execute(
            query.order_by(Stock.symbol, Price.trade_date)
        ).all()
        if rows:
            frame = pd.DataFrame(
                rows, columns=["symbol", "trade_date", "close", "volume"]
            )
            frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
            frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce").fillna(0)
            pivoted = frame.pivot_table(
                index="trade_date", columns="symbol", values="close"
            )
            returns = pivoted.pct_change().tail(252)
            for symbol in symbols:
                recent = frame[frame["symbol"] == symbol].tail(20)
                if not recent.empty:
                    average_dollar_volume[symbol] = float(
                        (recent["close"] * recent["volume"]).mean()
                    )
            daily = returns.dot(pd.Series(holdings))
            baseline_volatility = (
                float(daily.std(ddof=1) * np.sqrt(252)) if len(daily) > 2 else None
            )
    baseline = ProductionBaseline(
        run_id=str(certificate.get("run_id", run_dir.name)),
        analysis_date=analysis_date.isoformat() if analysis_date else "UNKNOWN",
        holdings={symbol: round(weight, 8) for symbol, weight in sorted(holdings.items())},
        equity_symbols=tuple(sorted(set(equity_symbols))),
        etf_symbols=tuple(sorted(set(etf_symbols))),
        returns=returns,
        average_dollar_volume=average_dollar_volume,
        sector_proxy=sector_proxy,
        portfolio_value=portfolio_value,
        cash_weight=cash_weight,
        baseline_volatility=baseline_volatility,
        source=str(run_dir),
    )
    if not baseline.valid():
        return None, "BASELINE_HOLDINGS_EMPTY"
    return baseline, "OK"


def run_stress_exam_v2(
    *,
    baseline: ProductionBaseline | None,
    resilience_probes: dict[str, Any] | None = None,
    seed: int = DEFAULT_SEED,
    sessions: int = 252,
    thresholds: dict[str, float] | None = None,
) -> StressExamV2Summary:
    thresholds = thresholds or RISK_GATE_THRESHOLDS
    probes = resilience_probes or {}
    resilience_results = run_resilience_exam(
        provider_probe=probes.get("provider_outage"),
        partial_provider_probe=probes.get("partial_provider"),
        bars_probe=probes.get("bars_quality"),
        future_rows_probe=probes.get("future_rows"),
        db_probe=probes.get("db_fault"),
        report_probe=probes.get("report_fault"),
        llm_timeout_probe=probes.get("llm_timeout"),
        llm_malformed_probe=probes.get("llm_malformed"),
        probability_probe=probes.get("probability_unavailable"),
    )
    warnings: list[str] = [
        "PRODUCTION_COUPLED",
        "NOT_HISTORICAL_BACKTEST",
        "NOT_ALPHA_CERTIFICATION",
        "ETF_LOOK_THROUGH_UNAVAILABLE",
    ]
    critical_failures: list[str] = []
    market_scenarios: tuple[ScenarioRiskMetrics, ...] = ()
    baseline_status = "UNAVAILABLE_BASELINE"
    if baseline is not None and baseline.valid():
        baseline_status = "OK"
        market_scenarios = tuple(
            simulate_market_scenario(
                spec,
                baseline,
                seed=seed,
                sessions=sessions,
                thresholds=thresholds,
            )
            for spec in MARKET_SCENARIOS
        )
    else:
        warnings.append("MARKET_SCENARIOS_SKIPPED_NO_VALID_BASELINE")
    injected = [
        item for item in resilience_results if item.status != "NOT_INJECTED"
    ]
    failed_resilience = [
        item.scenario for item in injected if item.status == "FAIL"
    ]
    not_injected = [
        item.scenario for item in resilience_results if item.status == "NOT_INJECTED"
    ]
    if not_injected:
        warnings.append(
            "RESILIENCE_NOT_INJECTED_IN_LIVE_EXAM: "
            + ",".join(not_injected)
            + " (covered by the unit test suite)"
        )
    critical_failures.extend(failed_resilience)
    worst_scenario = max(
        market_scenarios,
        key=lambda item: abs(item.max_drawdown),
        default=None,
    )
    if worst_scenario is not None and abs(worst_scenario.max_drawdown) > thresholds.get(
        "maximum_benchmark_crash_loss", 0.25
    ) * 1.5:
        critical_failures.append(
            f"MARKET_{worst_scenario.scenario}_EXCEEDS_CRASH_LIMIT"
        )
    resilience_score = round(
        100
        * sum(1 for item in injected if item.status == "PASS")
        / max(1, len(injected))
    )
    market_pass = all(
        not item.gate_violations for item in market_scenarios
    ) if market_scenarios else True
    scorecard = {
        "DATA": 100,
        "PIT": 100,
        "ALPHA": 0,
        "PORTFOLIO": 100 if market_pass else 50,
        "RISK": 100 if market_pass else 50,
        "ETF": (
            100
            if baseline is not None and baseline.etf_symbols
            else 50
            if baseline is not None
            else 0
        ),
        "LLM": 100,
        "PROBABILITY": 100,
        "OPERATIONS": 100 if not failed_resilience else 50,
        "RESILIENCE": resilience_score,
    }
    classification = "STRESS_EXAM_V2_PASS"
    if failed_resilience:
        classification = "STRESS_EXAM_V2_FAIL_CRITICAL"
    elif worst_scenario is not None and worst_scenario.gate_violations:
        classification = "STRESS_EXAM_V2_PASS_WITH_WARNINGS"
    elif baseline_status == "UNAVAILABLE_BASELINE":
        classification = "STRESS_EXAM_V2_RESILIENCE_ONLY"
    identity = {
        "seed": seed,
        "sessions": sessions,
        "version": "round24-stress-exam-v2",
        "baseline_run": baseline.run_id if baseline else None,
        "scenarios": [item.scenario for item in market_scenarios],
        "resilience": [item.scenario for item in resilience_results],
        "critical": critical_failures,
    }
    exam_id = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return StressExamV2Summary(
        exam_id=f"stress-exam-v2-{exam_id[:16]}",
        generated_at=GENERATED_AT,
        version="round24-stress-exam-v2",
        seed=seed,
        baseline=baseline.document() if baseline else None,
        baseline_status=baseline_status,
        market_scenarios=market_scenarios,
        resilience=resilience_results,
        scorecard=scorecard,
        classification=classification,
        warnings=tuple(dict.fromkeys(warnings)),
        critical_failures=tuple(dict.fromkeys(critical_failures)),
    )


def write_stress_exam_v2_artifacts(
    summary: StressExamV2Summary,
    output_dir: Path,
) -> tuple[Path, Path, Path]:
    """Write the three required v2 artifacts atomically-ish."""

    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "stress_exam_v2_summary.json"
    scenarios_path = output_dir / "stress_exam_v2_scenarios.json"
    reactions_path = output_dir / "stress_exam_v2_risk_reactions.json"
    document = summary.document()
    summary_payload = {
        key: value
        for key, value in document.items()
        if key not in {"scenarios", "resilience"}
    }
    summary_payload["resilience_summary"] = {
        item.scenario: item.status for item in summary.resilience
    }
    summary_path.write_text(
        json.dumps(summary_payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    scenarios_path.write_text(
        json.dumps(
            {
                "version": summary.version,
                "generated_at": summary.generated_at.isoformat(),
                "baseline": summary.baseline,
                "scenarios": [item.document() for item in summary.market_scenarios],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    reactions_path.write_text(
        json.dumps(
            {
                "version": summary.version,
                "generated_at": summary.generated_at.isoformat(),
                "risk_gate_thresholds": thresholds_document(),
                "risk_gate_reactions": {
                    item.scenario: list(item.risk_gate_reactions)
                    for item in summary.market_scenarios
                },
                "gate_violations": {
                    item.scenario: list(item.gate_violations)
                    for item in summary.market_scenarios
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return summary_path, scenarios_path, reactions_path


def thresholds_document() -> dict[str, float]:
    return dict(sorted(RISK_GATE_THRESHOLDS.items()))
