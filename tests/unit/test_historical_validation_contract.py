import json
from pathlib import Path

SPEC_PATH = Path("data/validation/historical_validation_spec_v1.json")


def load_spec() -> dict[str, object]:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def test_historical_validation_periods_are_fixed_calendar_windows() -> None:
    spec = load_spec()

    assert spec["spec_version"] == "historical-validation-v1"
    assert [
        (period["id"], period["start_date"], period["end_date"])
        for period in spec["periods"]
    ] == [
        ("gfc_2008", "2008-01-01", "2008-12-31"),
        ("covid_2020", "2020-01-01", "2020-12-31"),
        ("tightening_2022", "2022-01-01", "2022-12-31"),
        ("ai_2023_2025", "2023-01-01", "2025-12-31"),
    ]
    assert all(
        "no outcome-based boundary tuning" in period["boundary_policy"]
        for period in spec["periods"]
    )


def test_historical_validation_contract_keeps_statistical_safeguards() -> None:
    modules = load_spec()["modules"]

    assert modules["event_study"]["minimum_sample_size"] == 30
    assert modules["event_study"]["bootstrap_resamples"] == 10_000
    assert modules["conditional_probability"]["minimum_sample_size"] == 30
    assert modules["conditional_probability"]["prior_alpha"] == 1.0
    assert modules["conditional_probability"]["prior_beta"] == 1.0
    assert modules["market_graph"]["multiple_testing"] == ["FDR", "Bonferroni"]
    assert modules["alpha_discovery"]["test_fraction"] == 0.2
    assert modules["alpha_discovery"]["purge_gap_days"] == 21
    assert modules["portfolio_risk"]["minimum_observations"] == 60


def test_historical_validation_contract_forbids_success_only_reporting() -> None:
    spec = load_spec()

    assert spec["reporting_policy"]["show_failed_and_blocked_results"] is True
    assert spec["reporting_policy"]["prohibit_success_only_selection"] is True
    assert spec["reporting_policy"]["unavailable_metrics"].startswith("N/A")
    assert "universe_snapshots" in spec["required_frozen_artifacts"]
    assert "portfolio_ledger" in spec["required_frozen_artifacts"]
