from __future__ import annotations

from personal_alpha_terminal.application.round35_audit import (
    build_round35_decision_attribution,
)


def test_decision_attribution_ranks_largest_effect_and_keeps_llm_zero() -> None:
    ablation = {
        "ablation_rows": [
            {
                "ablation": "small",
                "max_weight_delta": 0.001,
                "symbols_changed": 1,
            },
            {
                "ablation": "large",
                "max_weight_delta": 0.12,
                "symbols_changed": 20,
            },
        ],
        "llm_influence": 0.0,
        "probability_production_impact": 0.0,
    }
    attribution = build_round35_decision_attribution(ablation)
    assert attribution["largest_weight_effects"][0]["ablation"] == "large"
    assert attribution["largest_weight_effects"][1]["ablation"] == "small"
    assert ablation["llm_influence"] == 0.0
