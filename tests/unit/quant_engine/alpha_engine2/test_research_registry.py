"""ROUND 8: research registry tests (rejected experiments must be preserved)."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from personal_alpha_terminal.quant_engine.alpha_engine2 import (
    ExperimentStatus,
    ResearchExperiment,
    ResearchRegistry,
)


def _experiment(status: ExperimentStatus, experiment_id: str = "exp-1") -> ResearchExperiment:
    return ResearchExperiment(
        experiment_id=experiment_id,
        strategy_id="challenger-a",
        strategy_version="1.0",
        hypothesis="higher volatility regime tilt improves net alpha",
        factors=("momentum_12_1", "low_volatility"),
        parameters={"momentum_coefficient": 0.006, "volatility_regime": True},
        universe_version="universe-v1",
        horizon=21,
        benchmark="SPY",
        cost_model_version="cost-v1",
        train_start=date(2020, 1, 2),
        train_end=date(2021, 1, 2),
        validation_start=date(2021, 1, 3),
        validation_end=date(2022, 1, 2),
        oos_start=date(2022, 1, 3),
        oos_end=date(2023, 1, 2),
        results={"oos_net_alpha": 0.01},
        status=status,
        rejection_reason=(
            "OOS net alpha below minimum"
            if status is ExperimentStatus.REJECTED
            else ""
        ),
        created_at=datetime(2024, 1, 1, tzinfo=__import__("datetime").timezone.utc),
    )


def test_registry_keeps_rejected_experiments(tmp_path: Path) -> None:
    path = tmp_path / "registry.jsonl"
    registry = ResearchRegistry(path)
    registry.append(_experiment(ExperimentStatus.REJECTED))
    registry.append(_experiment(ExperimentStatus.PROMOTED, experiment_id="exp-2"))
    loaded = registry.load()
    assert len(loaded) == 2
    statuses = {item.experiment_id: item.status for item in loaded}
    assert statuses["exp-1"] is ExperimentStatus.REJECTED
    assert statuses["exp-2"] is ExperimentStatus.PROMOTED
    assert any(item.rejection_reason for item in loaded if item.status is ExperimentStatus.REJECTED)


def test_registry_is_idempotent_and_rejects_conflicts(tmp_path: Path) -> None:
    path = tmp_path / "registry.jsonl"
    registry = ResearchRegistry(path)
    registry.append(_experiment(ExperimentStatus.REJECTED))
    registry.append(_experiment(ExperimentStatus.REJECTED))  # identical re-append
    assert len(registry.load()) == 1
    conflict = _experiment(ExperimentStatus.REJECTED)
    conflict = ResearchExperiment(
        experiment_id=conflict.experiment_id,
        strategy_id=conflict.strategy_id,
        strategy_version=conflict.strategy_version,
        hypothesis="DIFFERENT HYPOTHESIS",
        factors=conflict.factors,
        parameters=conflict.parameters,
        universe_version=conflict.universe_version,
        horizon=conflict.horizon,
        benchmark=conflict.benchmark,
        cost_model_version=conflict.cost_model_version,
        train_start=conflict.train_start,
        train_end=conflict.train_end,
        validation_start=conflict.validation_start,
        validation_end=conflict.validation_end,
        oos_start=conflict.oos_start,
        oos_end=conflict.oos_end,
        results=conflict.results,
        status=conflict.status,
        rejection_reason=conflict.rejection_reason,
        created_at=conflict.created_at,
    )
    with pytest.raises(ValueError, match="experiment identity conflict"):
        registry.append(conflict)


def test_rejected_experiment_requires_reason() -> None:
    base = _experiment(ExperimentStatus.REJECTED)
    with pytest.raises(ValueError, match="rejection reason"):
        ResearchExperiment(
            experiment_id=base.experiment_id,
            strategy_id=base.strategy_id,
            strategy_version=base.strategy_version,
            hypothesis=base.hypothesis,
            factors=base.factors,
            parameters=base.parameters,
            universe_version=base.universe_version,
            horizon=base.horizon,
            benchmark=base.benchmark,
            cost_model_version=base.cost_model_version,
            train_start=base.train_start,
            train_end=base.train_end,
            validation_start=base.validation_start,
            validation_end=base.validation_end,
            oos_start=base.oos_start,
            oos_end=base.oos_end,
            results=base.results,
            status=ExperimentStatus.REJECTED,
            rejection_reason="",
            created_at=base.created_at,
        )
