"""ROUND14 LLM alpha research protocol tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from personal_alpha_terminal.quant_engine.round14_llm_alpha_research import (
    NOT_PROVED,
    build_round15_dataset,
    run_round14_alpha_research,
    write_immutable_json,
)

DATASET_ID = "d" * 64
FEATURE_DATASET_ID = "f" * 64
AS_OF = datetime(2026, 8, 13, tzinfo=UTC)


def _outcome_document(count: int = 75) -> dict[str, object]:
    rows = []
    for index in range(count):
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "feature_dataset_id": FEATURE_DATASET_ID,
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
                "price_semantics": "adjusted_close_else_close",
            }
        )
    return {
        "dataset_id": DATASET_ID,
        "feature_dataset_id": FEATURE_DATASET_ID,
        "as_of": AS_OF.isoformat(),
        "outcome_rows": rows,
    }


def _feature_document() -> dict[str, object]:
    return {
        "dataset_id": FEATURE_DATASET_ID,
        "status": "RESEARCH_LIMITED_SURVIVORSHIP",
        "features": [],
    }


def test_round14_alpha_research_not_proved_with_one_issuer_corpus() -> None:
    result = run_round14_alpha_research(
        _outcome_document(),
        _feature_document(),
        evaluated_at=datetime(2026, 8, 14, tzinfo=UTC),
    )
    assert result.verdict == NOT_PROVED
    assert result.promotion_candidate is None
    assert "CROSS_SECTION_INSUFFICIENT" in result.blockers
    assert "LOCKED_OOS_SAMPLE_INSUFFICIENT" in result.blockers
    assert "WALK_FORWARD_FOLDS_INSUFFICIENT" in result.blockers
    assert result.metrics.ticker_count == 1


def test_round15_dataset_is_separate_and_pit_safe() -> None:
    dataset = build_round15_dataset(_outcome_document(), _feature_document())
    assert dataset["status"] == "RESEARCH_LIMITED_SURVIVORSHIP"
    assert dataset["production_influence"] == "NONE"
    assert dataset["future_outcomes_read_during_build"] is False
    assert len(dataset["rows"]) == 75
    assert dataset["rows"][0]["classical_feature_status"] == "NOT_SUPPLIED_TO_INTELLIGENCE_BUILD"


def test_round14_alpha_result_is_immutable(tmp_path: Path) -> None:
    result = run_round14_alpha_research(
        _outcome_document(),
        _feature_document(),
        evaluated_at=datetime(2026, 8, 14, tzinfo=UTC),
    )
    path = tmp_path / "result.json"
    write_immutable_json(path, result.document())
    write_immutable_json(path, result.document())
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["verdict"] == NOT_PROVED
    with pytest.raises(FileExistsError):
        write_immutable_json(path, {**result.document(), "verdict": "changed"})


def test_round14_alpha_research_cli_is_registered() -> None:
    from personal_alpha_terminal.terminal.cli import build_parser

    args = build_parser().parse_args(["intelligence", "alpha-research"])
    assert args.intelligence_action == "alpha-research"
