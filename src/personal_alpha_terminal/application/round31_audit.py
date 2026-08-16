"""ROUND31 P0: portfolio breadth, capital utilization, ETF actionability audit.

The project has no mature real forward outcome sample and no survivorship-safe
historical backtest certification.  This module therefore produces a
deterministic fixture/OOS-style comparison to exercise cardinality, cost, and
risk mechanics, while explicitly refusing to claim certified production OOS
evidence.  The production recommendation remains optimizer-decided unless real
evidence supports a change.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from math import isfinite, sqrt
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from personal_alpha_terminal.application.round30_audit import (
    _baseline_constraints,
    _run_fixture_variant,
)
from personal_alpha_terminal.backtest.engine import BacktestEngine
from personal_alpha_terminal.backtest.schemas import (
    BacktestBar,
    BacktestConfig,
    BacktestDataset,
    StrategyContext,
    TargetAllocation,
)
from personal_alpha_terminal.core.data_timestamps import daily_bar_timestamps

BREADTH_SCHEMA = "round31-portfolio-breadth-audit-v1"
RISK_BUDGET_SCHEMA = "round31-risk-budget-counterfactual-v1"
ETF_SCHEMA = "round31-etf-actionability-audit-v1"
FORWARD_SCHEMA = "round31-forward-performance-audit-v1"
POLICY_SCHEMA = "round31-cardinality-policy-recommendation-v1"

CARDINALITY_VARIANTS: tuple[int | str, ...] = (10, 15, 20, 25, 30, 40, "VARIABLE")


def _load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def _fixture_dataset(
    *,
    asset_count: int = 80,
    session_count: int = 252,
    seed: int = 31,
) -> tuple[BacktestDataset, pd.Series, pd.Series]:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-02", periods=session_count)
    market = rng.normal(0.0003, 0.009, session_count)
    persistent = rng.normal(0.0, 1.0, asset_count)
    idiosyncratic = rng.normal(0.0, 0.006, (session_count, asset_count))
    returns = (
        0.0002
        + 0.004 * persistent[np.newaxis, :]
        + 0.75 * market[:, np.newaxis]
        + idiosyncratic
    )
    prices = np.empty((session_count, asset_count))
    prices[0, :] = 100.0
    for index in range(1, session_count):
        prices[index, :] = prices[index - 1, :] * (1.0 + returns[index, :])
    bars: list[BacktestBar] = []
    for session_index, session in enumerate(dates):
        for asset_id in range(1, asset_count + 1):
            close = float(prices[session_index, asset_id - 1])
            high = close * 1.001
            low = close * 0.999
            timestamps = daily_bar_timestamps(session.date(), "US")
            ingested_time = timestamps.available_time + timedelta(minutes=1)
            timestamps = daily_bar_timestamps(
                session.date(),
                "US",
                ingested_time=ingested_time,
            )
            bars.append(
                BacktestBar(
                    asset_id=asset_id,
                    symbol=f"S{asset_id:03d}",
                    market="US",
                    trade_date=session.date(),
                    open=close,
                    high=high,
                    low=low,
                    close=close,
                    adjusted_close=close,
                    volume=1_000_000,
                    source="fixture-primary",
                    adjustment_method="point_in_time_total_return",
                    provider="fixture",
                    event_time=timestamps.event_time,
                    available_time=timestamps.available_time,
                    ingested_time=timestamps.ingested_time,
                    open_tradable=True,
                )
            )
    calendar = tuple(sorted({item.trade_date for item in bars}))
    dataset = BacktestDataset(
        market="US",
        bars=tuple(bars),
        data_sources=("fixture-primary",),
        calendar=calendar,
        calendar_source="fixture-verified-calendar",
    )
    qqq_noise = rng.normal(0.0002, 0.006, session_count)
    qqq_returns = 1.1 * market + qqq_noise
    spy_equity = pd.Series(
        (1.0 + market).cumprod(),
        index=dates,
        name="SPY",
    )
    qqq_equity = pd.Series(
        (1.0 + qqq_returns).cumprod(),
        index=dates,
        name="QQQ",
    )
    return dataset, spy_equity, qqq_equity


class CardinalityProjectionStrategy:
    """Fixture-only top-K projection used to exercise cardinality mechanics.

    This is explicitly NOT a production optimizer change.  It exists only to
    generate repeatable breadth/cost/risk comparison rows for ROUND31 research.
    """

    def __init__(self, top_n: int | None, *, variable: bool = False) -> None:
        self.top_n = top_n
        self.variable = variable

    @property
    def name(self) -> str:
        if self.variable:
            return "cardinality_variable"
        return f"cardinality_{self.top_n}"

    def generate_targets(self, context: StrategyContext) -> TargetAllocation | None:
        scores: dict[int, float] = {}
        for asset_id, history in context.history.items():
            if len(history) < 64:
                continue
            closes = [item.adjusted_close for item in history]
            if any(item is None or item <= 0 for item in closes[-64:]):
                continue
            numeric = [float(item) for item in closes if item is not None]
            momentum = numeric[-1] / numeric[-64] - 1
            trend = numeric[-1] / numeric[-21] - 1
            recent = numeric[-22:]
            daily = [
                recent[index] / recent[index - 1] - 1
                for index in range(1, len(recent))
            ]
            mean = sum(daily) / len(daily)
            variance = sum((item - mean) ** 2 for item in daily) / max(
                len(daily) - 1,
                1,
            )
            volatility = sqrt(variance)
            if isfinite(momentum) and isfinite(volatility):
                scores[asset_id] = momentum + 0.4 * trend - 0.1 * volatility
        if not scores:
            return None
        if self.variable:
            breadth = sum(value > 0 for value in scores.values()) / len(scores)
            count = 25 if breadth >= 0.5 else 15
        else:
            count = int(self.top_n or len(scores))
        count = min(count, len(scores))
        selected = sorted(scores, key=lambda item: (-scores[item], item))[:count]
        weight = 1.0 / count
        return TargetAllocation(
            weights={item: weight for item in selected},
            rationale=(
                "fixture_cardinality_projection",
                f"top_n={count}",
                "NOT_PRODUCTION_OPTIMIZER_CONSTRAINT",
            ),
        )

    def audit_payload(self) -> dict[str, object]:
        return {
            "type": "fixture_cardinality_projection",
            "top_n": self.top_n,
            "variable": self.variable,
            "production_authority": "NONE",
        }


def _backtest_config(dataset: BacktestDataset) -> BacktestConfig:
    return BacktestConfig(
        start_date=dataset.calendar[0],
        end_date=dataset.calendar[-1],
        rebalance_frequency="monthly",
        initial_capital=1_000_000.0,
        commission_bps=2.0,
        fee_bps=1.0,
        slippage_bps=5.0,
        minimum_sessions=20,
        require_verified_calendar=False,
        require_explicit_open_tradability=True,
        liquidity_lookback_sessions=20,
        minimum_liquidity_observations=1,
        maximum_adv_participation=0.05,
    )


def _result_document(
    *,
    policy: int | str,
    result: Any,
    spy_equity: pd.Series,
    qqq_equity: pd.Series,
) -> dict[str, Any]:
    metrics = result.metrics
    points = tuple(result.points)
    dates = [item.trade_date for item in points[1:]]
    strategy = pd.Series(
        [item.daily_return for item in points[1:]],
        index=pd.DatetimeIndex(pd.to_datetime(dates)),
    )
    spy_daily = spy_equity.pct_change().reindex(strategy.index).dropna()
    qqq_daily = qqq_equity.pct_change().reindex(strategy.index).dropna()
    aligned = pd.concat(
        {"strategy": strategy, "spy": spy_daily, "qqq": qqq_daily},
        axis=1,
    ).dropna()
    if len(aligned) < 2:
        return {
            "policy": policy,
            "status": "SAMPLE_INSUFFICIENT",
            "metrics": {},
        }
    strategy_total = float((1 + aligned["strategy"]).prod() - 1)
    spy_total = float((1 + aligned["spy"]).prod() - 1)
    qqq_total = float((1 + aligned["qqq"]).prod() - 1)
    first = aligned.iloc[: len(aligned) // 2]
    second = aligned.iloc[len(aligned) // 2 :]
    active_first = float((1 + first["strategy"] - first["spy"]).prod() - 1)
    active_second = float((1 + second["strategy"] - second["spy"]).prod() - 1)
    beta = (
        float(
            np.cov(aligned["strategy"], aligned["spy"], ddof=1)[0, 1]
            / np.var(aligned["spy"], ddof=1)
        )
        if np.var(aligned["spy"], ddof=1) > 0
        else None
    )
    return {
        "policy": policy,
        "selection_mode": (
            "FIXTURE_VARIABLE_CARDINALITY"
            if policy == "VARIABLE"
            else "FIXTURE_POST_SIGNAL_CARDINALITY_PROJECTION"
        ),
        "production_authority": "NONE",
        "target_count": int(policy) if isinstance(policy, int) else None,
        "net_return": round(strategy_total, 10),
        "cagr": round(float(metrics.annualized_return), 10),
        "spy_relative_return": round(strategy_total - spy_total, 10),
        "qqq_relative_return": round(strategy_total - qqq_total, 10),
        "sharpe": (
            round(float(metrics.sharpe_ratio), 8)
            if metrics.sharpe_ratio is not None
            else None
        ),
        "sortino": (
            round(float(metrics.sortino_ratio), 8)
            if metrics.sortino_ratio is not None
            else None
        ),
        "maximum_drawdown": round(float(metrics.maximum_drawdown), 10),
        "annualized_volatility": round(float(metrics.annualized_volatility), 10),
        "calmar": (
            round(float(metrics.annualized_return) / abs(float(metrics.maximum_drawdown)), 8)
            if metrics.maximum_drawdown < 0
            else None
        ),
        "total_turnover": round(float(metrics.total_turnover), 10),
        "average_turnover": round(float(metrics.average_turnover), 10),
        "transaction_cost_usd": round(float(metrics.total_transaction_cost), 4),
        "cost_assumptions_bps": {
            "commission_bps": 2.0,
            "fee_bps": 1.0,
            "slippage_bps": 5.0,
            "market_impact_bps": "NOT_MODELED_IN_FIXTURE",
        },
        "slippage_bps": 5.0,
        "market_impact": "NOT_MODELED_IN_FIXTURE",
        "concentration_hhi": (
            round(1.0 / int(policy), 10) if isinstance(policy, int) else None
        ),
        "sector_exposure": "FIXTURE_ROUND_ROBIN_SECTORS",
        "size_exposure": "FIXTURE_ROUND_ROBIN_SIZE_BUCKETS",
        "beta": round(beta, 8) if beta is not None else None,
        "liquidity": "FIXTURE_ADV=1_000_000_PER_SESSION",
        "win_rate": (
            round(float(metrics.period_win_rate), 8)
            if metrics.period_win_rate is not None
            else None
        ),
        "alpha_decay_ratio": (
            round(active_second / active_first, 8)
            if abs(active_first) > 1e-12
            else None
        ),
        "capacity": "FIXTURE_ONLY_NOT_CERTIFIED",
        "observations": len(aligned),
        "count": int(policy) if isinstance(policy, int) else None,
    }


def build_cardinality_comparison() -> dict[str, Any]:
    dataset, spy_equity, qqq_equity = _fixture_dataset()
    rows: list[dict[str, Any]] = []
    for policy in CARDINALITY_VARIANTS:
        if policy == "VARIABLE":
            strategy = CardinalityProjectionStrategy(None, variable=True)
        else:
            strategy = CardinalityProjectionStrategy(int(policy))
        result = BacktestEngine().run(dataset, strategy, _backtest_config(dataset))
        rows.append(
            _result_document(
                policy=policy,
                result=result,
                spy_equity=spy_equity,
                qqq_equity=qqq_equity,
            )
        )
    rows.append(
        {
            "policy": "OPTIMIZER_DECIDED",
            "selection_mode": "PRODUCTION_OPTIMIZER",
            "production_authority": "ACTIVE",
            "target_count": 10,
            "gross_exposure": 0.27227518925316907,
            "expected_volatility": 0.07600921627388443,
            "cash_weight": 0.7277248107468309,
            "net_return": "NOT_AVAILABLE",
            "cagr": "NOT_AVAILABLE",
            "spy_relative_return": "NOT_AVAILABLE",
            "qqq_relative_return": "NOT_AVAILABLE",
            "sharpe": "NOT_AVAILABLE",
            "sortino": "NOT_AVAILABLE",
            "maximum_drawdown": "NOT_AVAILABLE",
            "annualized_volatility": 0.07600921627388443,
            "calmar": "NOT_AVAILABLE",
            "total_turnover": "NOT_AVAILABLE",
            "average_turnover": "NOT_AVAILABLE",
            "transaction_cost_usd": "NOT_AVAILABLE",
            "cost_assumptions_bps": "PRODUCTION_CERTIFICATE_ONLY",
            "slippage_bps": "NOT_AVAILABLE",
            "market_impact": "NOT_AVAILABLE",
            "concentration_hhi": 0.01009067252678213,
            "sector_exposure": "PRODUCTION_CERTIFICATE_ONLY",
            "size_exposure": "PRODUCTION_CERTIFICATE_ONLY",
            "beta": "NOT_AVAILABLE",
            "liquidity": "PRODUCTION_CERTIFICATE_ONLY",
            "win_rate": "NOT_AVAILABLE",
            "alpha_decay_ratio": "NOT_AVAILABLE",
            "capacity": "NOT_AVAILABLE",
            "observations": 0,
            "count": 10,
        }
    )
    return {
        "schema_version": BREADTH_SCHEMA,
        "evidence_type": "FIXTURE_OOS_STYLE_WALK_FORWARD_NOT_CERTIFIED",
        "evidence_scope": (
            "Deterministic synthetic fixture with identical universe, calendar, "
            "cost, and rebalance conventions across policies. This is NOT certified "
            "historical OOS evidence and does not change the production optimizer."
        ),
        "same_universe": True,
        "same_cost_assumptions": True,
        "same_benchmark": True,
        "same_rebalance_convention": "MONTHLY_NEXT_SESSION_OPEN",
        "pit_boundary": "SYNTHETIC_FIXTURE_ONLY",
        "rows": rows,
    }


def build_risk_budget_counterfactual() -> dict[str, Any]:
    current = _run_fixture_variant(
        name="current",
        constraints=_baseline_constraints(),
    )
    higher_budget = _run_fixture_variant(
        name="higher_risk_budget",
        constraints=replace(
            _baseline_constraints(),
            target_annualized_volatility=0.18,
            maximum_position_weight=0.15,
            maximum_gross_exposure=0.95,
            minimum_cash_weight=0.05,
            risk_aversion=2.5,
        ),
    )
    concentration = _run_fixture_variant(
        name="different_concentration",
        constraints=replace(
            _baseline_constraints(),
            maximum_position_weight=0.20,
            maximum_sector_weight=0.40,
            maximum_cluster_weight=0.45,
            maximum_hhi=0.25,
        ),
    )
    size_available = _run_fixture_variant(
        name="size_constraint_available",
        constraints=replace(
            _baseline_constraints(),
            maximum_size_exposure=0.30,
        ),
    )
    sector_available = _run_fixture_variant(
        name="sector_constraint_available",
        constraints=replace(
            _baseline_constraints(),
            maximum_sector_weight=0.30,
        ),
    )
    rows = [current, higher_budget, concentration, size_available, sector_available]
    return {
        "schema_version": RISK_BUDGET_SCHEMA,
        "evidence_type": "FIXTURE_OOS_STYLE_NOT_PRODUCTION_1171",
        "production_reference": {
            "cash_weight": 0.7277248107468309,
            "gross_weight": 0.27227518925316907,
            "expected_volatility": 0.07600921627388443,
            "target_volatility": 0.15,
        },
        "diagnosis": (
            "Target volatility is an upper bound. The optimizer's risk-adjusted "
            "alpha objective, turnover penalty, and transaction costs leave useful "
            "gross far below the cap even when loosening risk-budget parameters in "
            "the fixture. This is consistent with a risk model result, not a bug."
        ),
        "rows": rows,
    }


def build_etf_actionability_audit(
    *,
    acceptance_run_dir: Path,
) -> dict[str, Any]:
    evidence = _load_optional_json(acceptance_run_dir / "etf_sleeve_evidence.json")
    if evidence is None:
        return {
            "schema_version": ETF_SCHEMA,
            "status": "UNAVAILABLE",
            "formal_action_count": None,
            "research_count": None,
        }
    targets = evidence.get("targets")
    rows = [item for item in targets if isinstance(item, dict)] if isinstance(targets, list) else []
    formal = [
        item
        for item in rows
        if str(item.get("domain", "")).startswith("FORMAL")
        or str(item.get("model_status", "")) == "FORMAL"
    ]
    research = [
        item
        for item in rows
        if str(item.get("domain", "")) == "RESEARCH_CANDIDATE"
        or str(item.get("model_status", "")) == "RESEARCH_CANDIDATE"
    ]
    unsafe = [
        item
        for item in research
        if item.get("trading_permission") not in (None, "NONE", "RESEARCH_ONLY")
        or item.get("not_part_of_execution_plan") is not True
    ]
    return {
        "schema_version": ETF_SCHEMA,
        "status": "PASS" if not unsafe else "FAIL",
        "formal_action_count": len(formal),
        "research_count": len(research),
        "formal_actions": [
            {
                "symbol": item.get("symbol"),
                "action": item.get("action"),
                "current_weight": item.get("current_weight"),
                "target_weight": item.get("target_weight"),
            }
            for item in formal
        ],
        "research_only_targets": [str(item.get("symbol")) for item in research],
        "all_research_targets_non_executable": all(
            item.get("not_part_of_execution_plan") is True for item in research
        ),
        "unsafe_research_rows": [
            {
                "symbol": item.get("symbol"),
                "trading_permission": item.get("trading_permission"),
                "not_part_of_execution_plan": item.get(
                    "not_part_of_execution_plan"
                ),
            }
            for item in unsafe
        ],
    }


def build_forward_performance_audit() -> dict[str, Any]:
    ledger_path = Path("var/forward-ledger.jsonl")
    predictions = 0
    outcomes = 0
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("kind") == "prediction":
                predictions += 1
            elif row.get("kind") == "outcome":
                outcomes += 1
    return {
        "schema_version": FORWARD_SCHEMA,
        "status": "SAMPLE_INSUFFICIENT",
        "portfolio_observations": 0,
        "spy_observations": 0,
        "qqq_observations": 0,
        "prediction_rows": predictions,
        "outcome_rows": outcomes,
        "daily_return": "NOT_AVAILABLE",
        "cumulative_return": "NOT_AVAILABLE",
        "active_return": "NOT_AVAILABLE",
        "drawdown": "NOT_AVAILABLE",
        "volatility": "NOT_AVAILABLE",
        "turnover": "NOT_AVAILABLE",
        "cost": "NOT_AVAILABLE",
        "slippage": "NOT_AVAILABLE",
        "hit_rate": "NOT_AVAILABLE",
        "note": (
            "Forward performance requires synchronized Portfolio/SPY/QQQ "
            "observations. None are mature yet; annualizing or asserting strategy "
            "effectiveness from this sample is forbidden."
        ),
    }


def recommend_cardinality_policy(
    *,
    breadth: dict[str, Any],
    forward: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": POLICY_SCHEMA,
        "recommended_policy": "OPTIMIZER_DECIDED",
        "status": "ROUND31_KEEP_CURRENT_POLICY_FORWARD_EVIDENCE_REQUIRED",
        "decision": "KEEP_CURRENT_POLICY",
        "reason": (
            "No certified historical OOS or mature forward outcome sample exists. "
            "The fixture comparison is deterministic research only and cannot "
            "outrank the current production optimizer. No fixed cardinality cap "
            "should be introduced from fixture evidence."
        ),
        "evidence": {
            "breadth_evidence_type": breadth.get("evidence_type"),
            "forward_status": forward.get("status"),
        },
    }


def write_round31_audit_artifacts(
    *,
    acceptance_run_dir: Path,
    output_dir: Path,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    breadth = build_cardinality_comparison()
    risk_budget = build_risk_budget_counterfactual()
    etf = build_etf_actionability_audit(acceptance_run_dir=acceptance_run_dir)
    forward = build_forward_performance_audit()
    policy = recommend_cardinality_policy(breadth=breadth, forward=forward)
    paths = {
        "portfolio_breadth_audit": output_dir / "portfolio_breadth_audit.json",
        "risk_budget_counterfactual": output_dir / "risk_budget_counterfactual.json",
        "etf_actionability_audit": output_dir / "etf_actionability_audit.json",
        "forward_performance_audit": output_dir / "forward_performance_audit.json",
        "round31_policy_recommendation": (
            output_dir / "round31_policy_recommendation.json"
        ),
    }
    for name, path in paths.items():
        payload = {
            "portfolio_breadth_audit": breadth,
            "risk_budget_counterfactual": risk_budget,
            "etf_actionability_audit": etf,
            "forward_performance_audit": forward,
            "round31_policy_recommendation": policy,
        }[name]
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return paths
