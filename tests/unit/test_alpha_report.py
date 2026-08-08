from datetime import date

from personal_alpha_terminal.alpha_discovery.alpha_report import (
    render_alpha_research_report,
)
from personal_alpha_terminal.alpha_discovery.schemas import (
    AlphaDiscoveryResult,
    ChronologicalSplit,
)


def test_alpha_report_contains_audit_risk_and_no_prediction_claim() -> None:
    result = AlphaDiscoveryResult(
        run_id=7,
        market="US",
        start_date=date(2018, 1, 1),
        end_date=date(2025, 12, 31),
        horizon_days=21,
        data_fingerprint="a" * 64,
        split=ChronologicalSplit(
            train_dates=(date(2018, 1, 1),),
            validation_dates=(date(2022, 1, 1),),
            test_dates=(date(2024, 1, 1),),
            purged_dates=(),
        ),
        factor_evaluations=(),
        combinations=(),
        tested_factor_count=24,
        tested_combination_count=0,
    )

    report = render_alpha_research_report(
        result,
        data_sources=("prices:test", "financials:test"),
    )

    assert report.report_type == "alpha_discovery"
    assert "Data fingerprint" in report.markdown
    assert "Benjamini-Hochberg" in report.markdown
    assert "not forecasts" in report.markdown
    assert "Risks and Known Limitations" in report.markdown
    assert "no validated candidate" in report.markdown
