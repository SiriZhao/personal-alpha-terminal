"""ROUND38 strategy robustness, walk-forward, locked OOS, and stress status."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast

from personal_alpha_terminal.quant_engine.backtest.validation import (
    build_walk_forward_folds,
)

ROUND38_SCHEMA = "round38-strategy-robustness-v1"


def _load_json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def build_round38_walk_forward() -> dict[str, object]:
    sessions = tuple(
        date(2026, 1, 1)
        + timedelta(days=index)
        for index in range(20)
    )
    folds = build_walk_forward_folds(
        sessions,
        train_sessions=8,
        validation_sessions=3,
        test_sessions=3,
        step_sessions=3,
        embargo_sessions=1,
    )
    return {
        "schema_version": ROUND38_SCHEMA,
        "status": "DATA_INSUFFICIENT",
        "fold_count": len(folds),
        "fold_specs": [
            {
                "fold_id": fold.fold_id,
                "train": [fold.split.train_start.isoformat(), fold.split.train_end.isoformat()],
                "validation": [
                    fold.split.validation_start.isoformat(),
                    fold.split.validation_end.isoformat(),
                ],
                "oos": [fold.split.test_start.isoformat(), fold.split.test_end.isoformat()],
                "embargo_sessions": fold.embargo_sessions,
            }
            for fold in folds
        ],
        "reason": "Corrected OOS has only 3 decision dates; no credible walk-forward alpha result.",
    }


def build_round38_locked_oos() -> dict[str, object]:
    return {
        "schema_version": ROUND38_SCHEMA,
        "locked_oos_status": "NOT_CERTIFIABLE",
        "locked_definition": {
            "train": ["2025-08-05", "2026-01-05"],
            "validation": ["2026-02-04", "2026-04-07"],
            "oos": ["2026-05-06", "2026-07-08"],
            "embargo_sessions": 21,
        },
        "reason": "Sample has 3 decision dates and survivorship-limited data.",
    }


def build_round38_benchmark_robustness(
    artifacts_dir: Path,
) -> dict[str, object]:
    benchmark = _load_json(artifacts_dir / "round33_benchmark_comparison.json")
    return {
        "schema_version": ROUND38_SCHEMA,
        "status": "SHORT_SAMPLE",
        "spy": benchmark.get("spy"),
        "qqq": benchmark.get("qqq"),
    }


def build_round38_regime_analysis() -> dict[str, object]:
    return {
        "schema_version": ROUND38_SCHEMA,
        "status": "DATA_INSUFFICIENT",
        "regimes": ["bull", "bear", "high_vol", "low_vol", "rate_shock", "liquidity_stress"],
        "reason": "No survivorship-safe historical regime coverage is certified.",
    }


def build_round38_parameter_robustness() -> dict[str, object]:
    return {
        "schema_version": ROUND38_SCHEMA,
        "status": "NOT_REEXECUTED_SAMPLE_INSUFFICIENT",
        "perturbed_parameters": [
            "factor_coefficient",
            "gross",
            "max_weight",
            "turnover_penalty",
            "cost",
            "volatility_target",
        ],
        "reason": "Parameter perturbation cannot establish robustness on 3 OOS dates.",
    }


def build_round38_cost_stress() -> dict[str, object]:
    return {
        "schema_version": ROUND38_SCHEMA,
        "status": "DATA_INSUFFICIENT",
        "cost_levels": [1.0, 1.5, 2.0],
        "base_cost_config": "ROUND33 us-daily-cost-v1",
    }


def build_round38_multiple_testing() -> dict[str, object]:
    return {
        "schema_version": ROUND38_SCHEMA,
        "challenger_count": 5,
        "challengers": [
            "fixed_engineering",
            "equal_weight_rank",
            "nonnegative_ridge",
            "ic_weighted",
            "regularized_ic_weighted",
        ],
        "rejected_experiments": [
            "fixed_engineering",
            "equal_weight_rank",
            "nonnegative_ridge",
            "ic_weighted",
        ],
        "deflated_sharpe": "NOT_CALCULATED_SAMPLE_INSUFFICIENT",
    }


def write_round38_artifacts(artifacts_dir: Path) -> dict[str, Path]:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    payloads: dict[str, dict[str, object]] = {
        "round38_walk_forward.json": build_round38_walk_forward(),
        "round38_locked_oos.json": build_round38_locked_oos(),
        "round38_benchmark_robustness.json": build_round38_benchmark_robustness(
            artifacts_dir
        ),
        "round38_regime_analysis.json": build_round38_regime_analysis(),
        "round38_parameter_robustness.json": build_round38_parameter_robustness(),
        "round38_cost_stress.json": build_round38_cost_stress(),
        "round38_multiple_testing.json": build_round38_multiple_testing(),
        "round38_validation_summary.json": {
            "schema_version": ROUND38_SCHEMA,
            "FINAL_VERDICT": "STRATEGY_DATA_INSUFFICIENT",
            "READY_FOR_ROUND39": "YES",
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
