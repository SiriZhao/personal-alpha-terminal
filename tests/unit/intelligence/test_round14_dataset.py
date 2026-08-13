"""ROUND 14 feature/outcome-separated dataset tests (research SHADOW only)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from personal_alpha_terminal.intelligence.round14_dataset import (
    build_outcomes,
    write_outcome_dataset,
)

DATASET_ID = "d" * 64
FEATURE_AS_OF = datetime(2025, 5, 1, 20, 0, tzinfo=UTC)
SESSIONS = pd.date_range("2025-04-25", periods=40, freq="B")


def _series(values: dict[pd.Timestamp, float]) -> pd.Series:
    return pd.Series(values).sort_index()


def _feature_document(ticker: str = "AAPL") -> dict[str, object]:
    return {
        "dataset_id": DATASET_ID,
        "features": [
            {
                "issuer_id": "320193",
                "ticker_asof": ticker,
                "decision_date": "2025-05-01",
                "event_features": [
                    {"available_at": FEATURE_AS_OF.isoformat()},
                ],
                "llm_shadow_features": {"llm_event_momentum": 0.5},
            }
        ],
    }


def _prices() -> dict[str, pd.Series]:
    asset = _series(
        {item: 100.0 + index * 0.1 for index, item in enumerate(SESSIONS)}
    )
    benchmark = _series(
        {item: 200.0 + index * 0.1 for index, item in enumerate(SESSIONS)}
    )
    return {"AAPL": asset, "SPY": benchmark}


def test_round14_builds_pit_visible_outcomes_without_future_leakage() -> None:
    cutoff = datetime(2025, 6, 1, tzinfo=UTC)
    dataset = build_outcomes(
        _feature_document(),
        prices_by_symbol=_prices(),
        benchmark_symbol="SPY",
        cutoff=cutoff,
    )
    ready = [item for item in dataset.outcome_rows if item.status == "OUTCOME_READY"]
    assert ready
    assert any(item.horizon == 1 for item in ready)
    assert all(
        item.outcome_available_at is not None and item.outcome_available_at <= cutoff
        for item in ready
    )
    for item in ready:
        assert item.asset_return is not None and item.benchmark_return is not None
        assert item.abnormal_return == pytest.approx(
            item.asset_return - item.benchmark_return
        )


def test_round14_pending_outcomes_are_future_invisible() -> None:
    cutoff = datetime(2025, 5, 8, tzinfo=UTC)
    dataset = build_outcomes(
        _feature_document(),
        prices_by_symbol=_prices(),
        benchmark_symbol="SPY",
        cutoff=cutoff,
    )
    pending = [item for item in dataset.outcome_rows if item.status == "OUTCOME_PENDING"]
    assert pending
    assert all(
        item.outcome_available_at is not None and item.outcome_available_at > cutoff
        for item in pending
    )
    ready = [item for item in dataset.outcome_rows if item.status == "OUTCOME_READY"]
    assert all(
        item.outcome_available_at is not None and item.outcome_available_at <= cutoff
        for item in ready
    )


def test_round14_missing_price_series_is_explicit() -> None:
    dataset = build_outcomes(
        _feature_document(ticker="UNKNOWN"),
        prices_by_symbol=_prices(),
        benchmark_symbol="SPY",
        cutoff=datetime(2025, 6, 1, tzinfo=UTC),
    )
    assert all(item.status == "NO_PRICE_SERIES" for item in dataset.outcome_rows)


def test_round14_outcome_artifact_is_deterministic_and_immutable(tmp_path: Path) -> None:
    prices = _prices()
    cutoff = datetime(2025, 6, 1, tzinfo=UTC)
    first = build_outcomes(
        _feature_document(),
        prices_by_symbol=prices,
        benchmark_symbol="SPY",
        cutoff=cutoff,
    )
    second = build_outcomes(
        _feature_document(),
        prices_by_symbol=prices,
        benchmark_symbol="SPY",
        cutoff=cutoff,
    )
    assert first.dataset_hash == second.dataset_hash
    path = tmp_path / "outcomes.json"
    write_outcome_dataset(path, first)
    write_outcome_dataset(path, first)
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["dataset_hash"] == first.dataset_hash
    assert document["future_outcomes_read_during_build"] is False
    with pytest.raises(FileExistsError):
        write_outcome_dataset(path, replace(first, dataset_hash="changed"))


def test_round14_outcomes_cli_is_registered() -> None:
    from personal_alpha_terminal.terminal.cli import build_parser

    args = build_parser().parse_args([
        "intelligence",
        "outcomes",
        "--cutoff", "2025-03-04T00:00:00+00:00",
    ])
    assert args.intelligence_action == "outcomes"
    assert args.cutoff == "2025-03-04T00:00:00+00:00"