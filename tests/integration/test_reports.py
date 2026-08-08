from datetime import date

from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.reports.schemas import ReportDocument
from personal_alpha_terminal.reports.service import ResearchReportService


def test_report_service_persists_audit_metadata(
    session_factory: sessionmaker[Session],
) -> None:
    document = ReportDocument(
        report_type="daily_market",
        as_of_date=date(2026, 7, 30),
        subject_key=None,
        title="Daily Report",
        markdown="# Daily Report",
        data_sources=("prices:test",),
        methodology=("adjacent close return",),
        risk_factors=("historical data only",),
    )

    with session_factory.begin() as session:
        saved = ResearchReportService(session).save(document)
        saved_id = saved.id

    with session_factory() as session:
        reports = ResearchReportService(session).latest(report_type="daily_market")

    assert len(reports) == 1
    assert reports[0].id == saved_id
    assert reports[0].data_sources == ["prices:test"]
    assert reports[0].generated_by == "deterministic"


def test_report_service_rejects_unbounded_read(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        service = ResearchReportService(session)
        for invalid in (0, 501):
            try:
                service.latest(limit=invalid)
            except ValueError as error:
                assert "between 1 and 500" in str(error)
            else:
                raise AssertionError("expected ValueError")
