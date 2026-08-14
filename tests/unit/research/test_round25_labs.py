"""ROUND25 PHASE 8-11: research lab honesty + experiment registry tests."""

from __future__ import annotations

from datetime import UTC, datetime

from personal_alpha_terminal.research.round25_labs import (
    INSUFFICIENT_CERTIFIED_HISTORY,
    LIMITED_EVIDENCE_RESEARCH,
    MINIMUM_SESSIONS_FOR_CERTIFICATION,
    ExperimentRegistry,
    ExperimentRegistryEntry,
    _evidence_labels,
    _metrics,
)


def test_short_window_is_insufficient_certified_history() -> None:
    labels = _evidence_labels(505)
    assert labels["evidence_class"] == LIMITED_EVIDENCE_RESEARCH
    assert labels["certification"] == INSUFFICIENT_CERTIFIED_HISTORY
    assert labels["certified_alpha"] is False
    assert labels["promoted_to_production"] is False


def test_long_window_is_still_not_certified() -> None:
    labels = _evidence_labels(MINIMUM_SESSIONS_FOR_CERTIFICATION + 1)
    # Survivorship remains unverified; longer history must not flip to CERTIFIED.
    assert labels["certified_alpha"] is False
    assert labels["certification"] == "NOT_CERTIFIABLE_SURVIVORSHIP_UNVERIFIED"


def test_metrics_are_finite_and_signed() -> None:
    import numpy as np
    import pandas as pd

    index = pd.date_range("2024-01-01", periods=260, freq="B")
    returns = pd.Series(np.sin(np.arange(260) / 10) / 100, index=index)
    metrics = _metrics(returns, benchmark_returns=returns * 0.5)
    assert metrics["net_return"] is not None
    assert metrics["max_drawdown"] <= 0
    assert metrics["sharpe"] is not None
    assert metrics["volatility"] > 0


def test_registry_is_append_only_and_frozen(tmp_path) -> None:
    registry = ExperimentRegistry(tmp_path)
    entry = ExperimentRegistryEntry(
        experiment_id="alpha-candidate-residual-momentum-001",
        hypothesis="residual momentum adds incremental after-cost alpha",
        registered_at=datetime(2026, 8, 15, tzinfo=UTC).isoformat(),
        factor_definition={"factor": "residual_momentum_v1"},
        parameters={"lookback": 252, "skip": 21},
        train=("2020-01-01", "2022-12-31"),
        validation=("2023-01-01", "2023-12-31"),
        embargo_sessions=21,
        locked_test=("2024-01-01", "2024-12-31"),
        benchmark="SPY",
        cost_model="fixed-entry-bps-v1",
        result={"status": "LIMITED_EVIDENCE_RESEARCH"},
        status="LOCKED_TEST_PENDING",
    )
    registry.register(entry)
    rows = registry.entries()
    assert len(rows) == 1
    assert rows[0]["experiment_id"] == "alpha-candidate-residual-momentum-001"
    # Second registration appends rather than overwrites.
    registry.register(entry)
    assert len(registry.entries()) == 2


def test_frozen_hypothesis_hash_detects_tampering() -> None:
    registry = ExperimentRegistry()
    entry = {
        "hypothesis": "h",
        "factor_definition": {"f": "v1"},
        "parameters": {"p": 1},
        "train": ["a", "b"],
        "validation": ["c", "d"],
        "embargo_sessions": 0,
        "locked_test": ["e", "f"],
        "benchmark": "SPY",
        "cost_model": "v1",
    }
    original = registry.frozen_hypothesis_hash(entry)
    entry["parameters"] = {"p": 2}
    assert registry.frozen_hypothesis_hash(entry) != original
