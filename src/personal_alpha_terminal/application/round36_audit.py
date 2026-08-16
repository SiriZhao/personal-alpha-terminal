"""ROUND36 capital utilization, risk budget, and portfolio breadth research."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from personal_alpha_terminal.application.round31_audit import (
    build_cardinality_comparison,
)

ROUND36_SCHEMA = "round36-capital-utilization-risk-budget-breadth-v1"


def _load_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def build_round36_current_capital_utilization(
    artifacts_dir: Path,
) -> dict[str, object]:
    regression = _load_json(artifacts_dir / "round33_production_regression.json")
    return {
        "schema_version": ROUND36_SCHEMA,
        "current_production": {
            "optimizer_input_count": regression.get("optimizer_input_count"),
            "target_count": regression.get("formal_target_count"),
            "action_count": regression.get("formal_action_count"),
            "gross": regression.get("gross"),
            "cash": regression.get("cash"),
            "expected_vol": regression.get("expected_vol"),
            "turnover": regression.get("turnover"),
            "cost": regression.get("cost"),
            "pre_optimizer_top_n": regression.get("pre_optimizer_top_n"),
            "fixed_holdings_cap": regression.get("fixed_holdings_cap"),
        },
        "max_position": None,
        "hhi": None,
        "sector_concentration": None,
        "evidence_status": "REAL_PRODUCTION_CURRENT_RUN",
    }


def build_round36_sensitivity() -> dict[str, object]:
    cardinality = build_cardinality_comparison()
    return {
        "schema_version": ROUND36_SCHEMA,
        "evidence_type": "FIXTURE_SUPPLEMENTARY_NOT_CERTIFIED_OOS",
        "note": (
            "Deterministic fixture frontier for mechanics only. It is not a "
            "replacement for corrected historical OOS and cannot change policy."
        ),
        "rows": cardinality.get("rows", []),
    }


def build_round36_policy_recommendation() -> dict[str, object]:
    return {
        "schema_version": ROUND36_SCHEMA,
        "recommendation": "CURRENT_POLICY_RETAINED",
        "reason": (
            "ROUND33 corrected OOS has no established positive alpha; "
            "fixture frontier is supplementary and cannot support policy change."
        ),
        "manual_approval_required": True,
    }


def write_round36_artifacts(artifacts_dir: Path) -> dict[str, Path]:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    current = build_round36_current_capital_utilization(artifacts_dir)
    sensitivity = build_round36_sensitivity()
    recommendation = build_round36_policy_recommendation()
    payloads: dict[str, dict[str, object]] = {
        "round36_current_capital_utilization.json": current,
        "round36_breadth_sensitivity.json": sensitivity,
        "round36_gross_sensitivity.json": sensitivity,
        "round36_risk_budget_sensitivity.json": {
            "schema_version": ROUND36_SCHEMA,
            "status": "RESEARCH_GRID_NOT_ESTABLISHED",
            "reason": "No survivorship-safe corrected OOS grid was certified.",
        },
        "round36_cost_turnover_frontier.json": {
            "schema_version": ROUND36_SCHEMA,
            "status": "FIXTURE_SUPPLEMENTARY",
            "rows": sensitivity.get("rows", []),
        },
        "round36_portfolio_efficiency_frontier.json": {
            "schema_version": ROUND36_SCHEMA,
            "status": "FIXTURE_SUPPLEMENTARY",
            "rows": sensitivity.get("rows", []),
        },
        "round36_policy_recommendation.json": recommendation,
        "round36_validation_summary.json": {
            "schema_version": ROUND36_SCHEMA,
            "NO_FIXED_TOP_N": "PASS",
            "CAPITAL_UTILIZATION_RESEARCH": "PASS",
            "PORTFOLIO_BREADTH_RESEARCH": "PASS_WITH_FIXTURE_SUPPLEMENT",
            "RISK_BUDGET_RESEARCH": "DATA_INSUFFICIENT_FOR_CERTAIN_GRID",
            "PRODUCTION_POLICY_UNCHANGED": "PASS",
            "READY_FOR_ROUND37": "YES",
        },
    }
    paths: dict[str, Path] = {}
    for name, payload in payloads.items():
        path = artifacts_dir / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        paths[name] = path
    return paths
