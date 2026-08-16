"""ROUND29 frozen-output replay: real LLM output must not pollute formal facts."""

from __future__ import annotations

from pathlib import Path

import pytest

from personal_alpha_terminal.application.round29_replay import replay_round29_brief

RUN_ID = "daily-c3c0107d1d7641b49bbb81c32615fbbc"


def test_frozen_llm_output_replay_preserves_formal_fields() -> None:
    run_dir = Path("reports/daily-runs") / RUN_ID
    if not (run_dir / "ai_brief.json").exists():
        pytest.skip("ROUND29 frozen daily-run artifact not present")
    report = replay_round29_brief(run_dir)
    assert report["status"] == "PASS"
    assert report["formal_action_count"] == 10
    assert report["action_commentary_count"] == 10
    assert report["formal_fields_preserved"] is True
    assert report["critical_failure"] is False
    assert report["source"] == "FROZEN_LLM_OUTPUT_REPLAY"
