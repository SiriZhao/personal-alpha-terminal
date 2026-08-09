from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from personal_alpha_terminal.core.product import PRODUCT_DISPLAY_NAME
from personal_alpha_terminal.models import ResearchReport
from personal_alpha_terminal.reports.schemas import ReportDocument


class ResearchReportService:
    """Persist and retrieve deterministic, auditable research reports."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, document: ReportDocument) -> ResearchReport:
        content = document.markdown
        if PRODUCT_DISPLAY_NAME not in content:
            content = (
                f"{content.rstrip()}\n\n---\n\n{PRODUCT_DISPLAY_NAME} · "
                "Research only · Not investment advice."
            )
        report = ResearchReport(
            report_type=document.report_type,
            as_of_date=document.as_of_date,
            subject_key=document.subject_key,
            title=document.title,
            content_markdown=content,
            data_sources=list(document.data_sources),
            methodology=list(document.methodology),
            risk_factors=list(document.risk_factors),
            generated_by="deterministic",
        )
        self.session.add(report)
        self.session.flush()
        return report

    def latest(
        self,
        *,
        report_type: str | None = None,
        subject_key: str | None = None,
        limit: int = 20,
    ) -> tuple[ResearchReport, ...]:
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        query: Select[tuple[ResearchReport]] = select(ResearchReport)
        if report_type is not None:
            query = query.where(ResearchReport.report_type == report_type)
        if subject_key is not None:
            query = query.where(ResearchReport.subject_key == subject_key)
        query = query.order_by(
            ResearchReport.as_of_date.desc(),
            ResearchReport.created_at.desc(),
        ).limit(limit)
        return tuple(self.session.scalars(query))
