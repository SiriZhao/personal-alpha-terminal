from datetime import UTC, date, datetime

from personal_alpha_terminal.data.market_data_quality.report import render_markdown
from personal_alpha_terminal.data.market_data_quality.schemas import (
    QualityReport,
    RunStatus,
)


def test_blocked_quality_report_never_implies_missing_sample_passed() -> None:
    report = QualityReport(
        generated_at=datetime(2026, 7, 31, tzinfo=UTC),
        history_start=date(2010, 1, 1),
        history_end=date(2026, 7, 31),
        status=RunStatus.BLOCKED,
        sample=None,
        blockers=("Missing traceable universe snapshots",),
    )

    rendered = render_markdown(report, run_id=7)

    assert "Gate status: **BLOCKED**" in rendered
    assert "Actual stratified sample: **0**" in rendered
    assert "no sample was fabricated" in rendered
    assert "not certified for downstream investment research" in rendered
