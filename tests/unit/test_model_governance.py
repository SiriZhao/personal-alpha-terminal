from datetime import date

import pytest

from personal_alpha_terminal.us_quant.model_governance import (
    ModelApprovalLevel,
    ModelRegistryEntry,
    ModelStatus,
    assess_model_drift,
)


def test_registry_rejects_overlapping_locked_periods() -> None:
    with pytest.raises(ValueError, match="must not overlap"):
        ModelRegistryEntry(
            "qcm",
            "0.1",
            "owner",
            "risk-adjusted research",
            ("pit_prices",),
            ("pit_universe",),
            (date(2020, 1, 1), date(2022, 1, 1)),
            (date(2021, 12, 31), date(2023, 1, 1)),
            None,
            {},
            ModelStatus.RESEARCH,
            ("not validated",),
            ModelApprovalLevel.CODE_REVIEW,
            None,
            "unknown",
        )


def test_drift_monitor_degrades_or_suspends_without_trading() -> None:
    warning = assess_model_drift(
        {"ic": 0.3, "cost": 0.1, "turnover": 0.1},
        {"ic": 0.2, "cost": 0.2, "turnover": 0.2},
    )
    assert warning.action == "degrade_to_research_only"
    high = assess_model_drift(
        {"ic": 0.3, "cost": 0.3, "turnover": 0.1},
        {"ic": 0.2, "cost": 0.2, "turnover": 0.2},
    )
    assert high.action == "suspend_new_signals"
