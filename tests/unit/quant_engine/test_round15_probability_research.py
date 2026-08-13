"""ROUND15 conditional probability research tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from personal_alpha_terminal.quant_engine.round15_probability_research import (
    VERDICT_FALLBACK,
    run_round15_probability_research,
    write_immutable_json,
)

DATASET_ID = "d" * 64


def _round15_document(count: int = 75) -> dict[str, object]:
    rows = []
    for index in range(count):
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "feature_dataset_id": "f" * 64,
                "issuer_id": "320193",
                "ticker_asof": "AAPL",
                "feature_name": f"feature_{index % 15}",
                "feature_value": 0.1 + index / 1000,
                "feature_as_of": "2025-02-27 23:35:41+00:00",
                "horizon": 1 + (index % 5),
                "baseline_session": "2025-02-27 00:00:00",
                "outcome_session": "2025-02-28 00:00:00",
                "outcome_available_at": "2025-03-27 00:00:00+00:00",
                "asset_return": 0.01,
                "benchmark_return": 0.005,
                "abnormal_return": 0.005,
                "status": "OUTCOME_READY",
            }
        )
    return {
        "dataset_id": DATASET_ID,
        "status": "RESEARCH_LIMITED_SURVIVORSHIP",
        "round14_verdict": "ROUND14_LLM_ALPHA_NOT_PROVED",
        "rows": rows,
    }


def test_round15_probability_fallback_when_corpus_insufficient() -> None:
    result = run_round15_probability_research(
        _round15_document(),
        evaluated_at=datetime(2026, 8, 14, tzinfo=UTC),
    )
    assert result.verdict == VERDICT_FALLBACK
    assert result.production_weight == 0.0
    assert result.promotion_candidate is None
    assert "CROSS_SECTION_INSUFFICIENT" in result.blockers
    assert "LOCKED_OOS_SAMPLE_INSUFFICIENT" in result.blockers
    assert "WALK_FORWARD_FOLDS_INSUFFICIENT" in result.blockers
    assert "LLM_FEATURES_NOT_VALIDATED" in result.blockers
    assert result.counterfactual["probability_on"] == "BLOCKED"


def test_round15_targets_are_defined_for_all_horizons() -> None:
    result = run_round15_probability_research(
        _round15_document(),
        evaluated_at=datetime(2026, 8, 14, tzinfo=UTC),
    )
    horizons = {item.horizon for item in result.targets}
    assert horizons == {5, 10, 21, 42}


def test_round15_portfolio_cardinality_is_not_fabricated() -> None:
    result = run_round15_probability_research(
        _round15_document(),
        evaluated_at=datetime(2026, 8, 14, tzinfo=UTC),
    )
    assert (
        result.portfolio_cardinality["status"]
        == "NOT_EVALUATED_NO_CERTIFIED_BROAD_PORTFOLIO_BACKTEST"
    )
    assert result.portfolio_cardinality["recommendation"] is None
    assert result.portfolio_cardinality["candidates"] == [5, 10, 15, 20, 30]


def test_round15_probability_result_is_immutable(tmp_path: Path) -> None:
    result = run_round15_probability_research(
        _round15_document(),
        evaluated_at=datetime(2026, 8, 14, tzinfo=UTC),
    )
    path = tmp_path / "result.json"
    write_immutable_json(path, result.document())
    write_immutable_json(path, result.document())
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["verdict"] == VERDICT_FALLBACK
    with pytest.raises(FileExistsError):
        write_immutable_json(path, {**result.document(), "verdict": "changed"})


def test_round15_probability_research_cli_is_registered() -> None:
    from personal_alpha_terminal.terminal.cli import build_parser

    args = build_parser().parse_args(["intelligence", "probability-research"])
    assert args.intelligence_action == "probability-research"
